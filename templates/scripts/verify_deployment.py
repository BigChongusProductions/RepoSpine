#!/usr/bin/env python3
"""verify_deployment.py — Run 18 deployment verification checks for bootstrapped projects.

Usage:
    python3 verify_deployment.py PROJECT_PATH [OPTIONS]

Checks that a bootstrapped project has all required files, configurations,
and working scripts. Outputs human-readable text or machine-readable JSON.

Exit codes:
  0  All checks pass
  1  Any critical failure
  2  Warnings only (no critical failures)

Stdlib only: subprocess, json, re, os, pathlib, dataclasses, argparse, sys
Python 3.10+
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    id: str              # "C01"
    name: str            # "DB Health"
    passed: bool
    severity: str        # "critical" | "warning"
    message: str         # One-line verdict
    details: str | None = None


@dataclass
class DeploymentReport:
    passed: int
    failed: int
    total: int
    critical_failures: int
    warning_failures: int
    profile: str
    checks: list[CheckResult]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 60

_SUBPROCESS_TIMEOUT: int = _DEFAULT_TIMEOUT  # module-level; overridden by --timeout


def _load_manifest_summary(project_path: Path) -> dict:
    manifest = project_path / "SYSTEMS_MANIFEST.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return data.get("summary", {})
    return {}


_THRESHOLDS = {
    "standard": {"min_hooks": 11, "min_hook_events": 7},
    "meta":     {"min_hooks": 3,  "min_hook_events": 3},
}


def _run(cmd: list[str], cwd: Path, timeout: int | None = None) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr). Never raises."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout if timeout is not None else _SUBPROCESS_TIMEOUT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout or _SUBPROCESS_TIMEOUT}s"
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


def _failed(check_id: str, name: str, severity: str, message: str, details: str | None = None) -> CheckResult:
    return CheckResult(id=check_id, name=name, passed=False, severity=severity,
                       message=message, details=details)


def _passed(check_id: str, name: str, severity: str, message: str, details: str | None = None) -> CheckResult:
    return CheckResult(id=check_id, name=name, passed=True, severity=severity,
                       message=message, details=details)


def _check_id(fn) -> str:
    """Extract check ID from function name, e.g. check_c01_db_health -> C01."""
    m = re.search(r"_c(\d+)_", fn.__name__)
    if m:
        return f"C{int(m.group(1)):02d}"
    return ""


def _is_meta_project(project_path: Path) -> bool:
    """A meta-project dogfoods its own dbq CLI from templates/scripts/dbq/."""
    return (project_path / "templates" / "scripts" / "dbq").is_dir()


def _read_profile(project_path: Path) -> str:
    """Read deployment profile from .bootstrap_profile, defaulting to 'standard'."""
    profile_file = project_path / ".bootstrap_profile"
    if profile_file.exists():
        content = profile_file.read_text(encoding="utf-8").strip()
        if content in ("standard", "extended"):
            return content
    return "standard"


_PROFILE_THRESHOLDS: dict[str, dict[str, int]] = {
    "standard": {"min_hooks": 11, "min_hook_events": 7},
    "extended": {"min_hooks": 11, "min_hook_events": 7},
}


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_c01_db_health(project_path: Path) -> CheckResult:
    cid, name, sev = "C01", "DB Health", "critical"
    try:
        rc, stdout, stderr = _run(["bash", "db_queries.sh", "health"], project_path)
        if rc == 0:
            return _passed(cid, name, sev, "db_queries.sh health exited 0")
        return _failed(cid, name, sev, f"db_queries.sh health exited {rc}",
                       (stdout + stderr).strip() or None)
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c02_task_queue(project_path: Path) -> CheckResult:
    cid, name, sev = "C02", "Task Queue Accessible", "critical"
    try:
        rc, stdout, stderr = _run(["bash", "db_queries.sh", "next"], project_path)
        if rc == 0:
            return _passed(cid, name, sev, "db_queries.sh next exited 0")
        return _failed(cid, name, sev, f"db_queries.sh next exited {rc}",
                       (stdout + stderr).strip() or None)
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c03_session_briefing(project_path: Path) -> CheckResult:
    cid, name, sev = "C03", "Session Briefing", "critical"
    try:
        rc, stdout, stderr = _run(["bash", "session_briefing.sh"], project_path)
        if rc == 0:
            return _passed(cid, name, sev, "session_briefing.sh exited 0")
        return _failed(cid, name, sev, f"session_briefing.sh exited {rc}",
                       (stdout + stderr).strip() or None)
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c04_coherence_check(project_path: Path) -> CheckResult:
    cid, name, sev = "C04", "Coherence Check", "warning"
    try:
        rc, stdout, stderr = _run(["bash", "coherence_check.sh"], project_path)
        if rc == 0:
            return _passed(cid, name, sev, "coherence_check.sh exited 0")
        return _failed(cid, name, sev, f"coherence_check.sh exited {rc}",
                       (stdout + stderr).strip() or None)
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c05_import_chain(project_path: Path) -> CheckResult:
    cid, name, sev = "C05", "@-import Chain", "critical"
    try:
        claude_md = project_path / "CLAUDE.md"
        if not claude_md.exists():
            return _failed(cid, name, sev, "CLAUDE.md not found")

        missing: list[str] = []
        import_count = 0
        for raw_line in claude_md.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("@"):
                continue
            import_count += 1
            # Strip the leading '@'
            ref = line[1:].split()[0]  # take first token in case of trailing comment
            ref_path = Path(ref)
            # Prefer project-local resolution first (v1.0 canonical model):
            #   1. If the ref is relative, resolve against project_path
            #   2. If not found locally AND the ref uses ~, fall back to expanduser()
            if not ref_path.is_absolute() and not ref.startswith("~"):
                local_resolved = project_path / ref_path
                if local_resolved.exists():
                    continue
                # Not found locally — also try global expansion as fallback
                global_resolved = ref_path.expanduser()
                if global_resolved.exists():
                    continue
                missing.append(str(local_resolved))
            else:
                # Absolute or ~-prefixed: expand user, check existence
                resolved = ref_path.expanduser()
                if not resolved.exists():
                    missing.append(str(resolved))

        if not missing:
            return _passed(cid, name, sev,
                           f"All {import_count} @-import(s) resolve to existing files")
        return _failed(cid, name, sev,
                       f"{len(missing)} @-import(s) unresolved",
                       "\n".join(missing))
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def _is_documentation_line(line: str) -> bool:
    """Return True if the placeholder match is documentation, not an actual unfilled token.

    Catches shell comments (#...), HTML comments (<!--...-->), and markdown
    inline code (backtick-quoted references like `%%PLACEHOLDER%%`).
    """
    # Extract the content after the filename:lineno: prefix
    parts = line.split(":", 2)
    content = parts[2].strip() if len(parts) >= 3 else line.strip()
    if content.startswith("#") or content.startswith("<!--"):
        return True
    # Placeholder inside backticks is documentation about the syntax, not a real token
    if re.search(r'`[^`]*%%[A-Z_][A-Z_0-9]*%%[^`]*`', content):
        return True
    return False


def check_c06_no_stray_placeholders(project_path: Path, is_meta: bool = False) -> CheckResult:
    cid, name, sev = "C06", "No Stray Placeholders", "critical"
    try:
        if is_meta:
            # Meta-projects ARE the template system — placeholders exist everywhere
            # by design. Only scan .claude/ (operational config that must be resolved).
            scan_path = str(project_path / ".claude")
            cmd = ["grep", "-rn", r"%%[A-Z_][A-Z_0-9]*%%",
                   "--include=*.md", "--include=*.sh", "--include=*.json",
                   "--exclude-dir=.git",
                   "--exclude-dir=worktrees",
                   scan_path]
            rc, stdout, stderr = _run(cmd, project_path)
            if rc == 1:
                return _passed(cid, name, sev,
                               "No stray placeholders in .claude/ (meta-project: templates excluded)")
            if rc == 0:
                raw_lines = stdout.strip().splitlines()
                real_hits = [l for l in raw_lines if not _is_documentation_line(l)]
                if not real_hits:
                    return _passed(cid, name, sev,
                                   "No stray placeholders in .claude/ (comment-only matches filtered)")
                return _failed(cid, name, sev,
                               f"{len(real_hits)} placeholder(s) in .claude/",
                               "\n".join(real_hits))
            return _passed(cid, name, sev,
                           "No stray placeholders in .claude/ (meta-project: templates excluded)")

        # Standard project: scan everything
        cmd1 = ["grep", "-rn", r"%%[A-Z_][A-Z_0-9]*%%",
                "--include=*.md", "--include=*.sh",
                "--exclude-dir=.git",
                str(project_path)]
        rc, stdout, stderr = _run(cmd1, project_path)
        # grep exit code: 0 = matches found, 1 = no matches, 2 = error
        if rc == 1:
            return _passed(cid, name, sev, "No stray placeholders found")
        if rc == 0:
            # Filter out comment lines — these are documentation about placeholders,
            # not actual unfilled tokens (e.g. "replace %%PLACEHOLDERS%% after copying")
            raw_lines = stdout.strip().splitlines()
            real_hits = [l for l in raw_lines if not _is_documentation_line(l)]
            if not real_hits:
                return _passed(cid, name, sev, "No stray placeholders found (comment-only matches filtered)")
            return _failed(cid, name, sev,
                           f"{len(real_hits)} placeholder(s) found",
                           "\n".join(real_hits))
        # Also check .claude/ directory explicitly
        cmd2 = ["grep", "-rn", r"%%[A-Z_][A-Z_0-9]*%%",
                "--include=*.md", "--include=*.sh",
                "--exclude-dir=.git",
                str(project_path / ".claude")]
        rc2, stdout2, stderr2 = _run(cmd2, project_path)
        all_matches: list[str] = []
        if rc2 == 0:
            all_matches.extend(l for l in stdout2.strip().splitlines()
                               if not _is_documentation_line(l))
        if all_matches:
            return _failed(cid, name, sev,
                           f"{len(all_matches)} placeholder(s) found",
                           "\n".join(all_matches))
        return _passed(cid, name, sev, "No stray placeholders found")
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c07_hook_settings_wired(project_path: Path) -> CheckResult:
    """Verify settings.json hook commands resolve to existing, executable scripts.

    Replaces the old git-hooks check — bootstrap uses Claude Code hooks
    (.claude/hooks/ + settings.json), not .git/hooks/. This checks the
    forward direction: every script referenced in settings.json must exist
    and be executable. Utility scripts called by other hooks (not by
    settings.json events directly) are not checked here.
    """
    cid, name, sev = "C07", "Hook Commands Resolve", "critical"
    try:
        settings_path = project_path / ".claude" / "settings.json"
        if not settings_path.exists():
            return _failed(cid, name, sev, ".claude/settings.json not found")

        data = json.loads(settings_path.read_text(encoding="utf-8"))
        hooks_config = data.get("hooks", {})
        if not isinstance(hooks_config, dict):
            return _failed(cid, name, sev, "hooks is not a dict in settings.json")

        # Extract all "command" values from the nested hook structure
        broken: list[str] = []
        checked = 0
        for event_name, event_entries in hooks_config.items():
            if not isinstance(event_entries, list):
                continue
            for entry in event_entries:
                for hook_def in entry.get("hooks", []):
                    cmd = hook_def.get("command", "")
                    if not cmd:
                        continue
                    # Resolve the script path from the command string
                    script_token = cmd.split()[0]
                    # Handle $CLAUDE_PROJECT_DIR and quoted variants
                    script_token = script_token.replace('"$CLAUDE_PROJECT_DIR"', str(project_path))
                    script_token = script_token.replace("$CLAUDE_PROJECT_DIR", str(project_path))
                    cmd_path = project_path / script_token if not Path(script_token).is_absolute() else Path(script_token)
                    checked += 1
                    if not cmd_path.exists():
                        broken.append(f"{event_name}: {cmd} (file not found)")
                    elif not os.access(str(cmd_path), os.X_OK):
                        broken.append(f"{event_name}: {cmd} (not executable)")

        if not broken:
            return _passed(cid, name, sev,
                           f"All {checked} hook command(s) resolve to executable scripts")
        return _failed(cid, name, sev,
                       f"{len(broken)} hook command(s) broken",
                       "\n".join(broken))
    except json.JSONDecodeError as exc:
        return _failed(cid, name, sev, "settings.json is not valid JSON", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


_FRAMEWORK_FILES = [
    "session-protocol.md",
    "phase-gates.md",
    "correction-protocol.md",
    "delegation.md",
    "loopback-system.md",
    "quality-gates.md",
    "coherence-system.md",
    "falsification.md",
    "visual-verification.md",
    "development-discipline.md",
]


def check_c08_framework_files(project_path: Path) -> CheckResult:
    cid, name, sev = "C08", "Framework Files Present", "critical"
    try:
        # v1.0 canonical: frameworks live under project_path/frameworks/
        # (also check legacy paths: templates/frameworks/, .claude/frameworks/).
        local_dirs = [
            project_path / "frameworks",
            project_path / "templates" / "frameworks",
            project_path / ".claude" / "frameworks",
        ]

        missing: list[str] = []
        for fname in _FRAMEWORK_FILES:
            found = any((d / fname).exists() for d in local_dirs)
            if not found:
                missing.append(fname)

        if not missing:
            return _passed(cid, name, sev, f"All {len(_FRAMEWORK_FILES)} framework files present")
        return _failed(cid, name, sev,
                       f"{len(missing)} framework file(s) missing",
                       "\n".join(missing))
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


_TRACKING_PATTERNS = {
    "LESSONS": ["LESSONS*.md", "LESSONS_*.md"],
    "LEARNING_LOG": ["LEARNING_LOG*.md", "learning_log*.md"],
    "PROJECT_MEMORY": ["*PROJECT_MEMORY*.md", "*_PROJECT_MEMORY.md", "BOOTSTRAP_PROJECT_MEMORY.md"],
    "AGENT_DELEGATION": ["AGENT_DELEGATION*.md"],
}


def check_c09_tracking_files(project_path: Path) -> CheckResult:
    cid, name, sev = "C09", "Tracking Files Present", "critical"
    try:
        missing: list[str] = []
        for label, patterns in _TRACKING_PATTERNS.items():
            found = False
            for pat in patterns:
                if list(project_path.glob(pat)):
                    found = True
                    break
            if not found:
                missing.append(label)

        if not missing:
            return _passed(cid, name, sev, "All tracking files present")
        return _failed(cid, name, sev,
                       f"Missing tracking file(s): {', '.join(missing)}",
                       "\n".join(missing))
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c10_refs_directory(project_path: Path) -> CheckResult:
    cid, name, sev = "C10", "refs/ Directory Scaffolded", "warning"
    try:
        refs_dir = project_path / "refs"
        if not refs_dir.is_dir():
            return _failed(cid, name, sev, "refs/ directory does not exist")

        # Only require the directory exists with at least a README.
        # Specific ref files (tool-inventory, gotchas-workflow, etc.) are
        # progressive-disclosure artifacts created during project work —
        # requiring them at deployment time is premature.
        if (refs_dir / "README.md").exists():
            return _passed(cid, name, sev, "refs/ exists with README.md")
        md_count = len(list(refs_dir.glob("*.md")))
        if md_count > 0:
            return _passed(cid, name, sev, f"refs/ exists with {md_count} file(s)")
        return _passed(cid, name, sev, "refs/ directory exists (empty — files added during project work)")
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c11_build_command(project_path: Path) -> CheckResult:
    cid, name, sev = "C11", "Build Command Succeeds", "warning"
    try:
        rc, stdout, stderr = _run(
            ["bash", "build_summarizer.sh", "build"],
            project_path,
            timeout=60,
        )
        if rc == 0:
            return _passed(cid, name, sev, "build_summarizer.sh build exited 0")
        return _failed(cid, name, sev,
                       f"build_summarizer.sh build exited {rc}",
                       (stdout + stderr).strip() or None)
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c12_global_lessons(project_path: Path) -> CheckResult:
    cid, name, sev = "C12", "Global Lessons File", "warning"

    # v1.0 canonical: LESSONS_UNIVERSAL.md lives at project root
    local_path = project_path / "LESSONS_UNIVERSAL.md"
    if local_path.exists():
        return _passed(cid, name, sev, "LESSONS_UNIVERSAL.md found at project root")

    # Not found — report failure without creating any file
    return _failed(cid, name, sev,
                   "LESSONS_UNIVERSAL.md not found at project root")


def check_c13_enforcement_hooks(project_path: Path, thresholds: dict | None = None) -> CheckResult:
    cid, name, sev = "C13", "Enforcement Hooks Deployed", "critical"
    min_hooks = (thresholds or {}).get("min_hooks", 11)
    try:
        hooks_dir = project_path / ".claude" / "hooks"
        if not hooks_dir.is_dir():
            return _failed(cid, name, sev, ".claude/hooks/ directory does not exist")

        executable_hooks = [
            p for p in hooks_dir.rglob("*.sh")
            if os.access(str(p), os.X_OK)
        ]
        count = len(executable_hooks)
        if count >= min_hooks:
            return _passed(cid, name, sev, f"{count} executable hook(s) found (>= {min_hooks})")
        return _failed(cid, name, sev,
                       f"Only {count} executable hook(s) found (expected {min_hooks}+)",
                       "\n".join(str(p) for p in sorted(executable_hooks)))
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c14_settings_json(project_path: Path, thresholds: dict | None = None) -> CheckResult:
    cid, name, sev = "C14", "settings.json Valid and Wired", "critical"
    min_events = (thresholds or {}).get("min_hook_events", 7)
    try:
        settings_path = project_path / ".claude" / "settings.json"
        if not settings_path.exists():
            return _failed(cid, name, sev, ".claude/settings.json not found")

        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return _failed(cid, name, sev, "settings.json is not valid JSON", str(exc))

        # Count hook events — hooks is typically a dict keyed by event name
        hooks = data.get("hooks", {})
        if isinstance(hooks, dict):
            event_count = len(hooks)
        elif isinstance(hooks, list):
            event_count = len(hooks)
        else:
            event_count = 0

        if event_count >= min_events:
            return _passed(cid, name, sev,
                           f"Valid JSON with {event_count} hook event(s) (>= {min_events})")
        return _failed(cid, name, sev,
                       f"Only {event_count} hook event(s) found (expected {min_events}+)",
                       f"hooks keys: {list(hooks.keys()) if isinstance(hooks, dict) else hooks!r}")
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c15_custom_agents(project_path: Path) -> CheckResult:
    cid, name, sev = "C15", "Custom Agents Defined", "warning"
    try:
        agents_dir = project_path / ".claude" / "agents"
        if not agents_dir.is_dir():
            return _failed(cid, name, sev, ".claude/agents/ directory does not exist")

        missing: list[str] = []
        for agent_name in ("implementer", "worker"):
            agent_dir = agents_dir / agent_name
            if not agent_dir.is_dir():
                missing.append(agent_name)
                continue
            md_files = list(agent_dir.glob("*.md"))
            if not md_files:
                missing.append(f"{agent_name} (no .md files)")

        if not missing:
            return _passed(cid, name, sev, "implementer and worker agent dirs each have .md")
        return _failed(cid, name, sev,
                       f"Agent(s) missing or empty: {', '.join(missing)}",
                       "\n".join(missing))
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c16_path_rules(project_path: Path) -> CheckResult:
    cid, name, sev = "C16", "Path Rules Scaffolded", "warning"
    try:
        rules_dir = project_path / ".claude" / "rules"
        if not rules_dir.is_dir():
            return _failed(cid, name, sev, ".claude/rules/ directory does not exist")

        # Just verify the directory exists — rule files are added progressively
        # during project work as path-specific patterns emerge.
        md_files = list(rules_dir.glob("*.md"))
        count = len(md_files)
        if count > 0:
            return _passed(cid, name, sev, f"{count} rule file(s) present")
        return _passed(cid, name, sev, ".claude/rules/ exists (empty — rules added during project work)")
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


# Patterns are split to prevent this file itself from matching the contamination scan.
_HARDCODED_PATTERNS = [
    "chonk" + "ius",
    "Master" + "Dashboard",
    "master" + "_dashboard",
]


def _is_path_only_match(line: str, patterns: list[str]) -> bool:
    """Return True if the pattern match appears only inside a file path.

    Lines like '/Users/username/Desktop/project' match 'username' but are
    legitimate path references, not source contamination. We detect this by
    checking if the match is preceded by '/' (absolute path segment only).
    Relative paths like 'SomeProject/config' are still flagged.
    """
    # Extract the content after the filename:linenum: prefix
    content = line.split(":", 2)[-1] if ":" in line else line
    for pat in patterns:
        for m in re.finditer(re.escape(pat), content):
            start = m.start()
            # Only filter if preceded by / (absolute path segment)
            in_path = start > 0 and content[start - 1] == "/"
            if not in_path:
                return False  # Found a non-path match
    return True  # All matches were inside absolute paths


def check_c17_no_hardcoded_refs(project_path: Path, is_meta: bool = False) -> CheckResult:
    cid, name, sev = "C17", "No Hardcoded Source Refs", "critical"
    try:
        # Meta-projects only risk contamination in templates/ (what gets copied).
        # Docs, backlog, tests, skills legitimately reference other projects.
        if is_meta:
            scan_path = project_path / "templates"
            if not scan_path.is_dir():
                return _passed(cid, name, sev,
                               "No templates/ directory to scan (meta-project)")
        else:
            scan_path = project_path
        pattern = "|".join(re.escape(p) for p in _HARDCODED_PATTERNS)
        rc, stdout, stderr = _run(
            ["grep", "-rn", "-E", pattern,
             "--include=*.sh", "--include=*.md", "--include=*.json",
             "--exclude-dir=.git",
             str(scan_path)],
            project_path,
        )
        if rc == 1:
            return _passed(cid, name, sev, "No hardcoded source references found")
        if rc == 0:
            raw_lines = stdout.strip().splitlines()
            # Filter out matches that only appear inside file paths
            lines = [l for l in raw_lines
                     if not _is_path_only_match(l, _HARDCODED_PATTERNS)]
            if not lines:
                return _passed(cid, name, sev,
                               "No hardcoded source references found (path-only matches filtered)")
            return _failed(cid, name, sev,
                           f"{len(lines)} hardcoded reference(s) found",
                           "\n".join(lines))
        # rc == 2 means grep error
        return _failed(cid, name, sev, f"grep error (exit {rc})",
                       stderr.strip() or None)
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


def check_c18_drift_score(project_path: Path) -> CheckResult:
    """Verify drift detection score is above threshold (>= 80)."""
    cid, name, sev = "C18", "Drift Score", "warning"
    try:
        rc, stdout, stderr = _run(
            ["bash", "db_queries.sh", "drift", "--quiet"],
            project_path,
        )
        if rc != 0:
            return _failed(cid, name, sev,
                           f"drift --quiet exited {rc}",
                           (stdout + stderr).strip() or None)

        # Parse "drift: NN/100 (details)"
        m = re.search(r"drift:\s*(\d+)/100", stdout)
        if not m:
            return _failed(cid, name, sev,
                           "Could not parse drift score from output",
                           stdout.strip() or None)

        score = int(m.group(1))
        if score >= 80:
            return _passed(cid, name, sev, f"Drift score {score}/100 (>= 80)")
        return _failed(cid, name, sev,
                       f"Drift score {score}/100 (below 80 threshold)",
                       stdout.strip() or None)
    except Exception as exc:  # noqa: BLE001
        return _failed(cid, name, sev, "Exception during check", str(exc))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_c01_db_health,
    check_c02_task_queue,
    check_c03_session_briefing,
    check_c04_coherence_check,
    check_c05_import_chain,
    check_c06_no_stray_placeholders,
    check_c07_hook_settings_wired,
    check_c08_framework_files,
    check_c09_tracking_files,
    check_c10_refs_directory,
    check_c11_build_command,
    check_c12_global_lessons,
    check_c13_enforcement_hooks,
    check_c14_settings_json,
    check_c15_custom_agents,
    check_c16_path_rules,
    check_c17_no_hardcoded_refs,
    check_c18_drift_score,
]


def run_checks(project_path: Path, check_ids: list[str] | None = None, is_meta: bool = False, profile: str = "standard") -> DeploymentReport:
    """Run all (or specified) checks and return a DeploymentReport."""
    # Normalise check_ids to uppercase
    if check_ids is not None:
        check_ids = [cid.upper() for cid in check_ids]

    # Meta-project uses its own thresholds; otherwise use profile-based thresholds
    if is_meta:
        thresholds = _THRESHOLDS["meta"]
    else:
        thresholds = _PROFILE_THRESHOLDS.get(profile, _PROFILE_THRESHOLDS["standard"])

    targets = [fn for fn in ALL_CHECKS
               if check_ids is None or _check_id(fn) in check_ids]

    # Checks with meta-project-aware signatures
    _META_AWARE = {
        "check_c06_no_stray_placeholders": {"is_meta": is_meta},
        "check_c13_enforcement_hooks": {"thresholds": thresholds},
        "check_c14_settings_json": {"thresholds": thresholds},
        "check_c17_no_hardcoded_refs": {"is_meta": is_meta},
    }

    results = []
    for fn in targets:
        extra_kwargs = _META_AWARE.get(fn.__name__, {})
        results.append(fn(project_path, **extra_kwargs))

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count
    crits = sum(1 for r in results if not r.passed and r.severity == "critical")
    warns = sum(1 for r in results if not r.passed and r.severity == "warning")

    return DeploymentReport(
        passed=passed_count,
        failed=failed_count,
        total=len(results),
        critical_failures=crits,
        warning_failures=warns,
        profile=profile,
        checks=results,
    )


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _format_human(report: DeploymentReport, verbose: bool = False) -> str:
    lines: list[str] = [f"=== Deployment Verification (profile: {report.profile}) ===", ""]

    for check in report.checks:
        status = "PASS" if check.passed else f"FAIL [{check.severity}]"
        line = f"  {check.id:<4} {check.name:<32} {status}"
        if not check.passed:
            line += f"  {check.message}"
        lines.append(line)

        show_details = (not check.passed or verbose) and check.details
        if show_details:
            for detail_line in check.details.splitlines():
                lines.append(f"       {detail_line}")

    lines.append("")
    result_parts = [f"{report.passed}/{report.total} passed"]
    if report.critical_failures:
        result_parts.append(f"{report.critical_failures} critical failure{'s' if report.critical_failures != 1 else ''}")
    if report.warning_failures:
        result_parts.append(f"{report.warning_failures} warning{'s' if report.warning_failures != 1 else ''}")
    lines.append(f"=== Result: {' — '.join(result_parts)} ===")

    return "\n".join(lines)


def _format_json(report: DeploymentReport) -> str:
    data = {
        "passed": report.passed,
        "failed": report.failed,
        "total": report.total,
        "critical_failures": report.critical_failures,
        "warning_failures": report.warning_failures,
        "profile": report.profile,
        "checks": [asdict(c) for c in report.checks],
    }
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_check_ids(raw: str, valid_ids: set[str]) -> list[str] | None:
    """Parse and validate comma-separated check IDs. Returns None if raw is empty."""
    if not raw:
        return None
    ids = [cid.strip().upper() for cid in raw.split(",") if cid.strip()]
    invalid = [cid for cid in ids if cid not in valid_ids]
    if invalid:
        print(f"Error: unknown check ID(s): {', '.join(invalid)}", file=sys.stderr)
        print(f"Valid IDs: {', '.join(sorted(valid_ids))}", file=sys.stderr)
        sys.exit(1)
    return ids


def main(argv: list[str] | None = None) -> int:
    global _SUBPROCESS_TIMEOUT  # noqa: PLW0603

    parser = argparse.ArgumentParser(
        prog="verify_deployment.py",
        description="Run 18 deployment verification checks for a bootstrapped project.",
    )
    parser.add_argument(
        "project_path",
        help="Absolute path to deployed project root",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output machine-readable JSON (default: human-readable)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show details for all checks, not just failures",
    )
    parser.add_argument(
        "--check",
        default="",
        metavar="C01,C02,...",
        help="Run only specified check IDs (comma-separated, case-insensitive)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=_DEFAULT_TIMEOUT,
        metavar="N",
        help=f"Override subprocess timeout in seconds (default: {_DEFAULT_TIMEOUT})",
    )

    parser.add_argument(
        "--meta-project",
        action="store_true",
        default=None,
        dest="meta_project",
        help="Force meta-project thresholds (auto-detected if omitted)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        metavar="PROFILE",
        help="Override deployment profile (auto-detected from .bootstrap_profile if omitted)",
    )

    args = parser.parse_args(argv)

    # Set module-level timeout
    _SUBPROCESS_TIMEOUT = args.timeout

    project_path = Path(args.project_path).resolve()
    if not project_path.is_dir():
        print(f"Error: project path does not exist or is not a directory: {project_path}", file=sys.stderr)
        return 1

    # Detect meta-project (auto or explicit override)
    is_meta = _is_meta_project(project_path)
    if args.meta_project is not None:
        is_meta = args.meta_project

    valid_ids = {_check_id(fn) for fn in ALL_CHECKS}
    check_ids = _parse_check_ids(args.check, valid_ids)

    # Detect deployment profile (auto from .bootstrap_profile, or explicit override)
    profile = _read_profile(project_path)
    if args.profile is not None:
        if args.profile not in _PROFILE_THRESHOLDS:
            print(f"Error: unknown profile '{args.profile}'. "
                  f"Valid: {', '.join(sorted(_PROFILE_THRESHOLDS))}", file=sys.stderr)
            return 1
        profile = args.profile

    report = run_checks(project_path, check_ids, is_meta=is_meta, profile=profile)

    if args.output_json:
        print(_format_json(report))
    else:
        print(_format_human(report, verbose=args.verbose))

    # Determine exit code
    if report.critical_failures > 0:
        return 1
    if report.warning_failures > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
