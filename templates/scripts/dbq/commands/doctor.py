"""
Bootstrap Doctor — environment health check.

Reads prerequisites.json from the project root and checks whether the
bootstrap environment is healthy: prerequisites present, templates found,
frameworks installed, host capabilities available.

Does NOT require a database — this is environment-layer, not DB-layer.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import ProjectConfig
from ..output import section_header


# ── Data model ──────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Result of a single doctor check."""
    name: str
    status: str          # "pass", "fail", "warn", "info"
    detail: str          # Version string, "present", error text, etc.
    hint: str = ""       # Install/fix hint shown on failure


@dataclass
class DoctorReport:
    """Full report from all doctor checks."""
    results: List[CheckResult] = field(default_factory=list)
    critical_failures: int = 0
    warnings: int = 0
    total_checks: int = 0
    passed: int = 0

    def add(self, result: CheckResult) -> None:
        """Add a check result and update counters."""
        self.results.append(result)
        if result.status in ("pass", "info"):
            self.passed += 1
        if result.status == "fail":
            self.critical_failures += 1
        if result.status == "warn":
            self.warnings += 1
        if result.status != "info":
            self.total_checks += 1

    @property
    def healthy(self) -> bool:
        """True when no critical failures exist."""
        return self.critical_failures == 0


# ── Version comparison ───────────────────────────────────────────────────

def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse a version string into a tuple of ints for comparison.

    Strips leading 'v' and any suffix after the last numeric component.
    Examples: '3.12.4' -> (3, 12, 4), '4.0' -> (4, 0), '5' -> (5,)
    """
    v = v.strip().lstrip("v")
    parts = []
    for part in v.split("."):
        # Take only leading digits
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def _version_meets_minimum(actual: str, minimum: str) -> bool:
    """Return True if actual version >= minimum version."""
    try:
        actual_t = _parse_version(actual)
        min_t = _parse_version(minimum)
        # Compare component by component, zero-pad the shorter
        max_len = max(len(actual_t), len(min_t))
        a = actual_t + (0,) * (max_len - len(actual_t))
        m = min_t + (0,) * (max_len - len(min_t))
        return a >= m
    except (ValueError, TypeError):
        # If we can't compare, assume it passes
        return True


# ── Prerequisites checks ─────────────────────────────────────────────────

def _run_version_cmd(cmd: str, timeout: int = 5) -> Optional[str]:
    """Run a version-check command and return stdout stripped, or None on error."""
    try:
        parts = cmd.split()
        # Handle commands with Python -c "..." style
        if len(parts) >= 3 and parts[1] == "-c":
            # Reassemble: parts[0] + ['-c', rest]
            prog = parts[0]
            rest = " ".join(parts[2:]).strip('"').strip("'")
            run_parts = [prog, "-c", rest]
        else:
            run_parts = parts
        result = subprocess.run(
            run_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _check_prerequisite(
    prereq: dict,
    current_platform: str,
) -> CheckResult:
    """Check a single prerequisite entry (critical or important)."""
    name = prereq.get("name", "?")

    # Special case: git-config uses check_commands (array of git config queries)
    if "check_commands" in prereq:
        return _check_git_config(prereq, current_platform)

    # Presence check
    if shutil.which(name) is None:
        install = prereq.get("install", {})
        hint = install.get(current_platform, install.get("linux", ""))
        return CheckResult(
            name=name,
            status="fail",
            detail="not found",
            hint=hint,
        )

    # Version check (if specified)
    version_cmd = prereq.get("version_check", "")
    min_version = prereq.get("min_version", "")

    if version_cmd and min_version:
        actual = _run_version_cmd(version_cmd)
        if actual is None:
            return CheckResult(
                name=name,
                status="warn",
                detail="version check failed",
                hint=f"Ensure {name} is accessible and '{version_cmd}' works",
            )
        if not _version_meets_minimum(actual, min_version):
            install = prereq.get("install", {})
            hint = install.get(current_platform, install.get("linux", ""))
            return CheckResult(
                name=name,
                status="fail",
                detail=f"{actual} (needs >= {min_version})",
                hint=hint,
            )
        return CheckResult(
            name=name,
            status="pass",
            detail=f"{actual} (>= {min_version})",
        )

    # Simple presence only (no version check)
    return CheckResult(
        name=name,
        status="pass",
        detail="present",
    )


def _check_git_config(prereq: dict, current_platform: str) -> CheckResult:
    """Check git-config prerequisite using check_commands array."""
    name = prereq.get("name", "git-config")
    check_cmds: List[str] = prereq.get("check_commands", [])
    fix = prereq.get("fix", "")

    missing = []
    for cmd in check_cmds:
        parts = cmd.split()
        try:
            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=5,
            )
            val = result.stdout.strip()
            if result.returncode != 0 or not val:
                # Extract the config key from the command (e.g. "user.name")
                key = parts[-1] if parts else cmd
                missing.append(key)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            key = parts[-1] if parts else cmd
            missing.append(key)

    if missing:
        not_set = ", ".join(missing)
        return CheckResult(
            name=name,
            status="warn",
            detail=f"{not_set} not set",
            hint=fix,
        )
    return CheckResult(
        name=name,
        status="pass",
        detail="configured",
    )


# ── Structural checks ────────────────────────────────────────────────────

def _check_templates(
    structural: dict,
    project_dir: Path,
) -> CheckResult:
    """Check templates directory exists and has required key files."""
    tmpl_config = structural.get("templates", {})
    search_paths: List[str] = tmpl_config.get("search_paths", [])
    key_files: List[str] = tmpl_config.get("key_files", [])

    home = Path.home()

    def _expand(p: str) -> Path:
        p = p.replace("$BOOTSTRAP_DIR", str(project_dir))
        p = p.replace("~", str(home))
        return Path(p)

    found_dir: Optional[Path] = None
    for sp in search_paths:
        candidate = _expand(sp)
        if candidate.is_dir():
            found_dir = candidate
            break

    if found_dir is None:
        return CheckResult(
            name="Templates",
            status="fail",
            detail="templates directory not found",
            hint="Check search_paths in prerequisites.json; in v1.0+ templates are bundled locally in generated projects",
        )

    # Check key files
    present = 0
    for kf in key_files:
        if (found_dir / kf).exists():
            present += 1

    total = len(key_files)
    rel = str(found_dir.relative_to(project_dir)) if found_dir.is_relative_to(project_dir) else str(found_dir)
    detail = f"./{rel}/ ({present}/{total} key files)"

    if present < total:
        return CheckResult(
            name="Templates",
            status="warn",
            detail=detail,
            hint="Some key template files are missing",
        )
    return CheckResult(
        name="Templates",
        status="pass",
        detail=detail,
    )


def _check_frameworks(structural: dict) -> CheckResult:
    """Check frameworks/ has enough files."""
    fw_config = structural.get("frameworks", {})
    fw_path_str: str = fw_config.get("path", "frameworks/")
    min_files: int = fw_config.get("min_files", 7)

    fw_path = Path(os.path.expanduser(fw_path_str))

    if not fw_path.is_dir():
        return CheckResult(
            name="Frameworks",
            status="fail",
            detail=f"{fw_path_str} not found",
            hint="frameworks/ directory missing — re-run bootstrap or check project setup",
        )

    count = sum(1 for _ in fw_path.iterdir() if _.is_file())
    detail = f"{fw_path_str} ({count} files, >= {min_files} required)"

    if count < min_files:
        return CheckResult(
            name="Frameworks",
            status="warn",
            detail=detail,
            hint=f"Only {count} framework files found, expected >= {min_files}",
        )
    return CheckResult(
        name="Frameworks",
        status="pass",
        detail=detail,
    )


# ── Minimal fallback ─────────────────────────────────────────────────────

_MINIMAL_PREREQS = {
    "critical": [
        {
            "name": "python3",
            "version_check": "python3 -c \"import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')\"",
            "min_version": "3.10",
            "install": {
                "darwin": "brew install python@3.12",
                "linux": "sudo apt-get install python3.12",
            },
        },
        {
            "name": "git",
            "install": {
                "darwin": "xcode-select --install",
                "linux": "sudo apt-get install git",
            },
        },
    ],
    "important": [],
}


# ── Formatting helpers ───────────────────────────────────────────────────

_STATUS_ICONS = {
    "pass": "✅",
    "fail": "❌",
    "warn": "⚠️ ",
    "info": "ℹ️ ",
}


def _format_line(result: CheckResult) -> str:
    """Format a single check result line."""
    icon = _STATUS_ICONS.get(result.status, "?  ")
    # Pad name to ~20 chars with dots
    name_padded = (result.name + " " + "." * 20)[:22]
    return f"    {icon} {name_padded} {result.detail}"


# ── Main command ─────────────────────────────────────────────────────────

def cmd_doctor(
    config: ProjectConfig,
    *,
    json_output: bool = False,
    quiet: bool = False,
    # Accept db for dispatch-pattern compatibility, but don't use it
    **_kwargs,
) -> None:
    """Run bootstrap environment health check.

    Checks prerequisites, structural files, and platform notes.
    Exits with code 1 if any critical check fails.
    """
    project_dir = config.project_dir
    current_platform = platform.system().lower()

    # Load prerequisites.json
    prereq_path = project_dir / "prerequisites.json"
    try:
        prereq_data = json.loads(prereq_path.read_text())
    except (OSError, json.JSONDecodeError):
        prereq_data = _MINIMAL_PREREQS  # type: ignore[assignment]

    prerequisites = prereq_data.get("prerequisites", _MINIMAL_PREREQS)
    structural = prereq_data.get("structural", {})
    platform_data = prereq_data.get("platform", {})
    host_data = prereq_data.get("host", {})

    report = DoctorReport()

    # ── 1. Critical prerequisites ────────────────────────────────────
    critical_results: List[CheckResult] = []
    for prereq in prerequisites.get("critical", []):
        r = _check_prerequisite(prereq, current_platform)
        critical_results.append(r)
        report.add(r)

    # ── 2. Important prerequisites ───────────────────────────────────
    important_results: List[CheckResult] = []
    for prereq in prerequisites.get("important", []):
        r = _check_prerequisite(prereq, current_platform)
        # Demote important failures to warnings
        if r.status == "fail":
            r = CheckResult(
                name=r.name,
                status="warn",
                detail=r.detail,
                hint=r.hint,
            )
        important_results.append(r)
        report.add(r)

    # ── 3. Structural checks ─────────────────────────────────────────
    structural_results: List[CheckResult] = []

    if structural:
        r_tmpl = _check_templates(structural, project_dir)
        structural_results.append(r_tmpl)
        report.add(r_tmpl)

        r_fw = _check_frameworks(structural)
        structural_results.append(r_fw)
        report.add(r_fw)

    # ── Collect next steps ────────────────────────────────────────────
    next_steps: List[str] = []
    for r in report.results:
        if r.status in ("fail", "warn") and r.hint:
            next_steps.append(r.hint)

    # ── JSON output ───────────────────────────────────────────────────
    if json_output:
        data = {
            "healthy": report.healthy,
            "critical_failures": report.critical_failures,
            "warnings": report.warnings,
            "total_checks": report.total_checks,
            "passed": report.passed,
            "platform": current_platform,
            "results": [asdict(r) for r in report.results],
        }
        print(json.dumps(data, indent=2))
        sys.exit(0 if report.healthy else 1)

    # ── Quiet output ──────────────────────────────────────────────────
    if quiet:
        if report.healthy and report.warnings == 0:
            print("HEALTHY")
        elif report.healthy:
            print(f"HEALTHY: {report.warnings} warning(s)")
        else:
            print(
                f"NOT_READY: {report.critical_failures} critical, "
                f"{report.warnings} warning(s)"
            )
        sys.exit(0 if report.healthy else 1)

    # ── Full console output ───────────────────────────────────────────
    print("")
    print(section_header("Bootstrap Doctor"))
    print("")

    # Critical prerequisites
    print("  Prerequisites (critical):")
    for r in critical_results:
        print(_format_line(r))
        if r.hint and r.status in ("fail", "warn"):
            print(f"       → {r.hint}")

    print("")

    # Important prerequisites
    print("  Prerequisites (important):")
    for r in important_results:
        print(_format_line(r))
        if r.hint and r.status in ("fail", "warn"):
            print(f"       → {r.hint}")

    print("")

    # Structural
    if structural_results:
        print("  Structural:")
        for r in structural_results:
            print(_format_line(r))
            if r.hint and r.status in ("fail", "warn"):
                print(f"       → {r.hint}")
        print("")

    # Platform notes (informational)
    known_issues = platform_data.get("known_issues", {})
    platform_notes = known_issues.get(current_platform, [])
    if platform_notes:
        print(f"  Platform ({current_platform}):")
        for note in platform_notes:
            print(f"    {_STATUS_ICONS['info']} {note}")
        print("")

    # Host info (informational)
    if host_data:
        print("  Host:")
        app = host_data.get("application", "")
        if app:
            print(f"    {_STATUS_ICONS['info']} {app}")
        features = host_data.get("features_required", [])
        if features:
            print(f"    {_STATUS_ICONS['info']} Features: {', '.join(features)}")
        plan_note = host_data.get("plan_note", "")
        if plan_note:
            print(f"    {_STATUS_ICONS['info']} {plan_note}")
        print("")

    # Summary
    print("  " + "─" * 14 + " Summary " + "─" * 14)
    if report.healthy and report.warnings == 0:
        print(
            f"  ✅ HEALTHY — {report.passed}/{report.total_checks} "
            f"checks passed, 0 warnings"
        )
    elif report.healthy:
        print(
            f"  ⚠️  HEALTHY (with warnings) — "
            f"{report.passed}/{report.total_checks} checks passed, "
            f"{report.warnings} warning(s)"
        )
    else:
        crit = report.critical_failures
        warn = report.warnings
        crit_label = f"{crit} critical failure{'s' if crit != 1 else ''}"
        warn_label = f"{warn} warning{'s' if warn != 1 else ''}"
        print(f"  ❌ NOT READY — {crit_label}, {warn_label}")

    if next_steps:
        print("")
        print("  Next steps:")
        for i, step in enumerate(next_steps, 1):
            print(f"    {i}. {step}")

    print("")

    sys.exit(0 if report.healthy else 1)
