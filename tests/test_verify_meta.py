#!/usr/bin/env python3
# NOTE: This file is private-only — not included in the public repo (Phase 10 exclusion list).
"""Tests for meta-project awareness in verify_deployment.py."""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERIFY_SCRIPT = PROJECT_ROOT / "templates" / "scripts" / "verify_deployment.py"


def run_verify(check_id: str, *extra_args: str) -> subprocess.CompletedProcess:
    """Run verify_deployment.py with a single check against the bootstrap project itself."""
    cmd = [
        sys.executable, str(VERIFY_SCRIPT),
        str(PROJECT_ROOT),
        "--check", check_id,
        "--json",
        *extra_args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def test_c06_passes_on_meta_project():
    """C06 should pass on bootstrap (meta-project) — templates/ excluded."""
    result = run_verify("C06")
    assert result.returncode == 0, f"C06 failed on meta-project: {result.stdout}\n{result.stderr}"


def test_c13_passes_on_meta_project():
    """C13 should pass on bootstrap (meta-project) — lower hook threshold."""
    result = run_verify("C13")
    assert result.returncode == 0, f"C13 failed on meta-project: {result.stdout}\n{result.stderr}"


def test_c14_passes_on_meta_project():
    """C14 should pass on bootstrap (meta-project) — lower event threshold."""
    result = run_verify("C14")
    assert result.returncode == 0, f"C14 failed on meta-project: {result.stdout}\n{result.stderr}"


def test_c17_passes_on_meta_project():
    """C17 should pass on bootstrap (meta-project) �� only scans templates/ for contamination."""
    result = run_verify("C17")
    assert result.returncode == 0, f"C17 failed on meta-project: {result.stdout}\n{result.stderr}"


def test_meta_detection_is_automatic():
    """Verify auto-detection works — bootstrap has templates/scripts/dbq/."""
    assert (PROJECT_ROOT / "templates" / "scripts" / "dbq").is_dir(), \
        "Bootstrap should be detected as meta-project"


if __name__ == "__main__":
    # Simple runner for bash test integration
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                print(f"  FAIL  {name}: {e}")
                failures += 1
    sys.exit(1 if failures else 0)
