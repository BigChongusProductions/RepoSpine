#!/usr/bin/env python3
"""preflight_check.py — Prerequisite checker for bootstrap projects.

QUICK MODE (default, no args): For SessionStart hook use.
  Checks jq, python3, git, bash in PATH. Prints one-line summary. Exits 0 always.

FULL MODE (--full [--project-dir PATH]): For pre-bootstrap validation.
  Human-readable output. Exits 0 (all pass), 1 (critical failures), 2 (warnings only).
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CRITICAL_FAILURES = 0
WARN_COUNT = 0
INFO_COUNT = 0


def _pass(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str, hint: str = "") -> None:
    global CRITICAL_FAILURES
    print(f"  [FAIL] {msg}")
    if hint:
        print(f"         Install: {hint}")
    CRITICAL_FAILURES += 1


def _warn(msg: str) -> None:
    global WARN_COUNT
    print(f"  [WARN] {msg}")
    WARN_COUNT += 1


def _info(msg: str) -> None:
    global INFO_COUNT
    print(f"  [INFO] {msg}")
    INFO_COUNT += 1


def _install_hint(tool: str) -> str:
    """Return a platform-appropriate install hint for a tool."""
    plat = platform.system().lower()
    hints: dict[str, dict[str, str]] = {
        "jq": {
            "darwin": "brew install jq",
            "linux": "sudo apt-get install jq",
        },
        "python3": {
            "darwin": "brew install python@3.12",
            "linux": "sudo apt-get install python3.12",
        },
        "git": {
            "darwin": "xcode-select --install",
            "linux": "sudo apt-get install git",
        },
        "bash": {
            "darwin": "brew install bash",
            "linux": "built-in (usually 5.x)",
        },
        "sqlite3": {
            "darwin": "built-in on macOS",
            "linux": "sudo apt-get install sqlite3",
        },
    }
    tool_hints = hints.get(tool, {})
    return tool_hints.get(plat, "see documentation")


# ---------------------------------------------------------------------------
# QUICK MODE
# ---------------------------------------------------------------------------

def run_quick() -> None:
    """Quick mode: check core tools, print one-line summary, exit 0 always."""
    tools = ["jq", "python3", "git", "bash"]
    missing = [t for t in tools if shutil.which(t) is None]
    if not missing:
        print("Prerequisites OK: jq, python3, git, bash all found")
    else:
        hints = ", ".join(f"{t} (install: {_install_hint(t)})" for t in missing)
        print(f"Missing tools: {hints}")
    sys.exit(0)


# ---------------------------------------------------------------------------
# FULL MODE — check groups
# ---------------------------------------------------------------------------

def check_critical_tools() -> None:
    """Group 1: Critical tools — exit 1 on any failure."""
    print("\nCritical tools:")

    # jq
    jq_path = shutil.which("jq")
    if jq_path:
        _pass(f"jq found: {jq_path}")
    else:
        _fail("jq not found", _install_hint("jq"))

    # python3 presence + version
    py_path = shutil.which("python3")
    if py_path:
        _pass(f"python3 found: {py_path}")
        ver = sys.version_info
        ver_str = f"{ver.major}.{ver.minor}.{ver.micro}"
        if ver >= (3, 10):
            _pass(f"python3 >= 3.10 ({ver_str})")
        else:
            _fail(
                f"python3 version {ver_str} < 3.10 (need 3.10+ for match statements, PEP 604)",
                _install_hint("python3"),
            )
    else:
        _fail("python3 not found", _install_hint("python3"))
        _fail("python3 version check skipped (python3 not found)")

    # git
    git_path = shutil.which("git")
    if git_path:
        _pass(f"git found: {git_path}")
    else:
        _fail("git not found", _install_hint("git"))


def check_important_tools() -> None:
    """Group 2: Important tools — warn only."""
    print("\nImportant tools:")

    # sqlite3
    sq_path = shutil.which("sqlite3")
    if sq_path:
        _pass(f"sqlite3 found: {sq_path}")
    else:
        _warn("sqlite3 not found (Python fallback available via python3 -m sqlite3)")

    # git user config
    try:
        git_name = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True
        ).stdout.strip()
        git_email = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True
        ).stdout.strip()
    except FileNotFoundError:
        git_name = ""
        git_email = ""

    if git_name and git_email:
        _pass(f"git user configured: {git_name} <{git_email}>")
    else:
        _warn(
            "git user not fully configured — first commit will fail. "
            "Run: git config --global user.name 'Your Name' && "
            "git config --global user.email 'you@example.com'"
        )


def _find_templates_dir(script_dir: Path) -> Path | None:
    """Search for templates/ directory relative to script location."""
    candidates = [
        script_dir / ".." / "templates",
        script_dir / ".." / ".." / "templates",
    ]
    for c in candidates:
        resolved = c.resolve()
        if resolved.is_dir():
            return resolved
    return None


def check_structural(script_dir: Path) -> None:
    """Group 3: Structural checks."""
    print("\nStructural:")

    templates_dir = _find_templates_dir(script_dir)

    key_files = [
        "scripts/dbq/__main__.py",
        "hooks/session-start-check.template.sh",
        "rules/RULES_TEMPLATE.md",
        "settings/settings.template.json",
    ]

    if templates_dir is not None:
        found = sum(1 for kf in key_files if (templates_dir / kf).is_file())
        total = len(key_files)
        display = str(templates_dir).replace(str(Path.home()), "~")
        if found == total:
            _pass(f"Templates: {display} ({found}/{total} key files)")
        else:
            _fail(
                f"Templates: {display} found but only {found}/{total} key files present",
                "Run /setup-templates or check template installation",
            )
    else:
        _fail(
            "Template directory not found (searched relative to script location)",
            "Run /setup-templates",
        )

    # Local frameworks/ directory — search relative to script
    frameworks_candidates = [
        script_dir / ".." / "frameworks",
        script_dir / ".." / ".." / "frameworks",
        script_dir / "frameworks",
    ]
    frameworks_dir: Path | None = None
    for fc in frameworks_candidates:
        resolved = fc.resolve()
        if resolved.is_dir():
            frameworks_dir = resolved
            break

    if frameworks_dir is not None:
        md_files = list(frameworks_dir.glob("*.md"))
        count = len(md_files)
        display = str(frameworks_dir).replace(str(Path.home()), "~")
        if count >= 7:
            _pass(f"Frameworks: {display} ({count} .md files)")
        else:
            _fail(
                f"Frameworks: {display} exists but only {count} .md files (need >= 7)",
                "Check frameworks/ installation",
            )
    else:
        _fail(
            "Local frameworks/ directory not found",
            "Install frameworks from the bootstrap repo",
        )


def check_platform() -> None:
    """Group 4: Platform info — always pass."""
    print("\nPlatform:")
    plat = platform.system().lower()
    if plat == "darwin":
        _info("Platform: darwin (macOS)")
        _info("grep -P not available on macOS — use grep -E instead")
    elif plat == "linux":
        _info("Platform: linux")
        _info("sed -i has no '' argument on Linux (use sed -i 's/old/new/' file — no backup suffix)")
    else:
        _warn(f"Unrecognized platform: {plat} (supported: darwin, linux)")


def check_discovery_handoff(project_dir: Path) -> None:
    """Group 5: Discovery handoff contract (only when --project-dir given)."""
    print("\nDiscovery handoff:")

    required_specs = [
        "specs/VISION.md",
        "specs/BLUEPRINT.md",
        "specs/RESEARCH.md",
        "specs/INFRASTRUCTURE.md",
    ]

    for spec in required_specs:
        spec_path = project_dir / spec
        if spec_path.is_file():
            content = spec_path.read_text(errors="replace")
            if "TODO" in content:
                _warn(f"{spec} exists but contains unresolved TODO markers — review before activating")
            else:
                _pass(f"{spec} exists (no TODO markers)")
        else:
            _fail(
                f"{spec} not found — run bootstrap-discovery first",
                "Create specs/ via the /bootstrap-discovery skill",
            )

    # .bootstrap_mode — must exist and equal SPECIFICATION
    mode_file = project_dir / ".bootstrap_mode"
    if mode_file.is_file():
        mode_val = mode_file.read_text().strip()
        if mode_val == "SPECIFICATION":
            _pass(".bootstrap_mode = SPECIFICATION")
        else:
            _fail(
                f".bootstrap_mode exists but value is '{mode_val}' (expected: SPECIFICATION)",
                "Discovery phase must complete with SPECIFICATION mode set",
            )
    else:
        _fail(
            ".bootstrap_mode not found — discovery phase did not complete",
            "Run bootstrap-discovery skill and complete the spec phase",
        )

    # NEXT_SESSION.md — advisory
    next_session = project_dir / "NEXT_SESSION.md"
    if next_session.is_file():
        content = next_session.read_text(errors="replace")
        if "Handoff Source: COWORK" in content:
            _info("NEXT_SESSION.md found with Handoff Source: COWORK marker")
        else:
            _info("NEXT_SESSION.md found (no Cowork handoff marker — proceeding without discovery context)")
    else:
        _info("NEXT_SESSION.md not found — no discovery session context available")

    # scripts/dbq/ — bundled engine check
    dbq_dir = project_dir / "scripts" / "dbq"
    if dbq_dir.is_dir():
        _pass(f"scripts/dbq/ found (bundled engine)")
    else:
        _warn("scripts/dbq/ not found — bundled CLI engine missing; bootstrap may fail")


def print_summary() -> None:
    """Print the summary line."""
    print()
    parts = []
    if CRITICAL_FAILURES > 0:
        parts.append(f"{CRITICAL_FAILURES} critical failure(s)")
    if WARN_COUNT > 0:
        parts.append(f"{WARN_COUNT} warning(s)")
    if INFO_COUNT > 0:
        parts.append(f"{INFO_COUNT} info")

    if not parts:
        print("Preflight: all checks passed")
    elif CRITICAL_FAILURES == 0 and WARN_COUNT == 0:
        print(f"Preflight: all critical checks passed ({', '.join(parts)})")
    else:
        print(f"Preflight: {', '.join(parts)}")


def run_full(project_dir_arg: str | None) -> None:
    """Full mode: all check groups, human-readable output."""
    script_dir = Path(__file__).resolve().parent

    check_critical_tools()
    check_important_tools()
    check_structural(script_dir)
    check_platform()

    if project_dir_arg is not None:
        project_dir = Path(project_dir_arg).resolve()
        if not project_dir.is_dir():
            print(f"\n  [FAIL] --project-dir does not exist or is not a directory: {project_dir_arg}")
            global CRITICAL_FAILURES
            CRITICAL_FAILURES += 1
        else:
            check_discovery_handoff(project_dir)

    print_summary()

    if CRITICAL_FAILURES > 0:
        sys.exit(1)
    elif WARN_COUNT > 0:
        sys.exit(2)
    else:
        sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preflight checker for bootstrap projects.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full validation (default: quick mode for SessionStart hook)",
    )
    parser.add_argument(
        "--project-dir",
        metavar="PATH",
        help="Path to project directory for discovery handoff contract checks (requires --full)",
    )
    args = parser.parse_args()

    if args.full:
        run_full(args.project_dir)
    else:
        run_quick()
