"""
Upgrade drift detection for generated projects.

Reads .bootstrap_profile and .bootstrap_manifest from a generated project
directory and reports the bootstrap version used plus which template-derived
files are present or missing.

v1.1 scope: presence/absence check only.
v1.2 planned: hash comparison once bootstrap_project.sh writes .bootstrap_hashes.

Does NOT require a database — this operates on generated project files.
"""
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..db import Database
from ..config import ProjectConfig


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class BootstrapProfile:
    """Parsed contents of .bootstrap_profile."""
    profile: str = "unknown"
    version: str = "unknown"
    timestamp: str = "unknown"


@dataclass
class FileStatus:
    """Status of a single manifest-listed file."""
    path: str
    present: bool


@dataclass
class UpgradeDriftReport:
    """Full report from upgrade drift detection."""
    profile: BootstrapProfile
    project_dir: str
    total_files: int = 0
    present_count: int = 0
    missing_count: int = 0
    files: List[FileStatus] = field(default_factory=list)

    @property
    def score_pct(self) -> int:
        """Percentage of manifest files that are present (0-100)."""
        if self.total_files == 0:
            return 100
        return int(self.present_count / self.total_files * 100)


# ── Parsing helpers ──────────────────────────────────────────────────────────

def _parse_profile(profile_path: Path) -> Tuple[BootstrapProfile, Optional[str]]:
    """
    Parse .bootstrap_profile (key=value format).

    Returns (BootstrapProfile, error_message_or_None).
    """
    if not profile_path.exists():
        return BootstrapProfile(), f".bootstrap_profile not found at {profile_path}"

    profile = BootstrapProfile()
    try:
        for line in profile_path.read_text().splitlines():
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key == "profile":
                    profile.profile = value
                elif key == "version":
                    profile.version = value
                elif key == "timestamp":
                    profile.timestamp = value
    except OSError as exc:
        return BootstrapProfile(), f"Could not read .bootstrap_profile: {exc}"

    return profile, None


def _read_manifest(manifest_path: Path) -> Tuple[List[str], Optional[str]]:
    """
    Read a bootstrap manifest (one file path per line).

    Returns (file_list, error_message_or_None).
    Prefers .bootstrap_created (post-bootstrap, template-derived files)
    over .bootstrap_manifest (pre-bootstrap, rollback snapshot).
    """
    if not manifest_path.exists():
        return [], f"{manifest_path.name} not found at {manifest_path}"

    try:
        lines = manifest_path.read_text().splitlines()
    except OSError as exc:
        return [], f"Could not read .bootstrap_manifest: {exc}"

    # Filter out blank lines and comment-like entries; normalise leading ./
    files = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Normalise: strip leading "./"
        if line.startswith("./"):
            line = line[2:]
        files.append(line)

    return files, None


# ── Core logic ───────────────────────────────────────────────────────────────

def run_upgrade_drift(project_dir: Path) -> Tuple[UpgradeDriftReport, List[str]]:
    """
    Run upgrade drift detection against a generated project directory.

    Returns (report, list_of_errors).
    Errors are non-fatal problems (missing files, unreadable profile etc.)
    that should be surfaced to the user but do not prevent output.
    """
    errors: List[str] = []

    profile, profile_err = _parse_profile(project_dir / ".bootstrap_profile")
    if profile_err:
        errors.append(profile_err)

    # Prefer .bootstrap_created (template-derived files) over .bootstrap_manifest (rollback list)
    created_path = project_dir / ".bootstrap_created"
    manifest_path = project_dir / ".bootstrap_manifest"
    manifest_files, manifest_err = _read_manifest(
        created_path if created_path.exists() else manifest_path
    )
    if manifest_err:
        errors.append(manifest_err)

    report = UpgradeDriftReport(
        profile=profile,
        project_dir=str(project_dir),
    )

    for rel_path in manifest_files:
        abs_path = project_dir / rel_path
        present = abs_path.exists()
        report.files.append(FileStatus(path=rel_path, present=present))
        report.total_files += 1
        if present:
            report.present_count += 1
        else:
            report.missing_count += 1

    return report, errors


# ── CLI command ──────────────────────────────────────────────────────────────

def cmd_upgrade_drift(
    db: Database,
    config: ProjectConfig,
    project_path: str = "",
    json_output: bool = False,
    show_all: bool = False,
) -> None:
    """
    Report upgrade drift for a generated project.

    Reads .bootstrap_profile and .bootstrap_manifest from the project
    directory and reports which template-derived files are present or missing.
    """
    # Resolve target directory: explicit arg, or current project root
    if project_path:
        target = Path(project_path).expanduser().resolve()
    else:
        target = config.project_dir

    if not target.is_dir():
        print(
            f"ERROR: project directory does not exist: {target}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    report, errors = run_upgrade_drift(target)

    if json_output:
        data = {
            "project_dir": report.project_dir,
            "profile": {
                "profile": report.profile.profile,
                "version": report.profile.version,
                "timestamp": report.profile.timestamp,
            },
            "total_files": report.total_files,
            "present_count": report.present_count,
            "missing_count": report.missing_count,
            "score_pct": report.score_pct,
            "errors": errors,
            "files": [
                {"path": f.path, "present": f.present}
                for f in report.files
            ],
        }
        print(json.dumps(data, indent=2))
        return

    # Human-readable output
    print("")
    print("== UPGRADE DRIFT REPORT =========================================")
    print(f"  Project:   {report.project_dir}")
    print(f"  Profile:   {report.profile.profile}")
    print(f"  Bootstrapped with version: {report.profile.version}")
    print(f"  Bootstrap timestamp: {report.profile.timestamp}")
    print("")

    if errors:
        print("  Warnings:")
        for err in errors:
            print(f"    [warn]  {err}")
        print("")

    if report.total_files == 0:
        print("  No manifest files to check.")
        print("  (Either .bootstrap_manifest is absent or empty.)")
    else:
        missing = [f for f in report.files if not f.present]
        present = [f for f in report.files if f.present]

        print(f"  Files:     {report.present_count}/{report.total_files} present "
              f"({report.score_pct}% unchanged)")

        if missing:
            print("")
            print(f"  Missing ({len(missing)}):")
            for f in missing:
                print(f"    [missing]  {f.path}")

        if show_all and present:
            print("")
            print(f"  Present ({len(present)}):")
            for f in present:
                print(f"    [ok]       {f.path}")
        elif not missing:
            print("  All manifest files are present.")

    print("")
    print("  Note: hash comparison will be available once bootstrap_project.sh")
    print("  is updated to write .bootstrap_hashes (planned for v1.2).")
    print("")
    print("=================================================================")
    print("")
