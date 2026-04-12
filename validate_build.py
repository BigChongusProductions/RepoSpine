#!/usr/bin/env python3
"""validate_build.py — Build-time consistency checks for project-bootstrap.

Catches common inconsistencies before shipping.

Checks:
  V01  Skill/command match — ALLOWED_SKILLS in build_plugin.sh vs skills/ and README Commands
  V02  Hook references — settings.template.json hook commands vs templates/hooks/
  V03  Version match — VERSION file, plugin.json, SYSTEMS_MANIFEST.json
  V04  Manifest agreement — SYSTEMS_MANIFEST.json counts vs actual file counts
  V05  Forbidden path check — deployed template files must not reference global paths
  V06  Allowed refs check — key template files reference only declared dependencies
  V07  Public skill hygiene — no developer-machine paths in public SKILL.md files

Usage:
    python3 validate_build.py [--repo-root PATH]

Exit codes:
  0  All checks pass
  1  One or more checks failed

Stdlib only: json, re, os, pathlib, sys, argparse
Python 3.8+
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, check_id: str, name: str, passed: bool, message: str,
                 details: list[str] | None = None) -> None:
        self.check_id = check_id
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or []

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.check_id}: {self.name} — {self.message}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pass(check_id: str, name: str, message: str,
          details: list[str] | None = None) -> CheckResult:
    return CheckResult(check_id, name, True, message, details)


def _fail(check_id: str, name: str, message: str,
          details: list[str] | None = None) -> CheckResult:
    return CheckResult(check_id, name, False, message, details)


def _extract_readme_commands(readme: Path) -> list[str]:
    """Extract slash-commands from the Commands table in README.md."""
    commands: list[str] = []
    in_commands_section = False
    for line in readme.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("## Commands"):
            in_commands_section = True
            continue
        if in_commands_section and stripped.startswith("## ") and not stripped.startswith("## Commands"):
            # Left the Commands section
            break
        if in_commands_section and "|" in stripped:
            # Skip header and separator rows
            if "Command" in stripped and "Where" in stripped:
                continue
            if re.match(r"^\|[-| ]+\|$", stripped):
                continue
            # Parse command cell (first column)
            cols = [c.strip() for c in stripped.split("|") if c.strip()]
            if cols:
                cmd_cell = cols[0]
                # Extract `/command-name` pattern
                match = re.search(r"`(/[\w-]+)`", cmd_cell)
                if match:
                    commands.append(match.group(1))
    return commands


def _extract_settings_hook_commands(settings_path: Path) -> list[str]:
    """Extract .sh filenames from hook commands in settings.template.json."""
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    commands: list[str] = []
    hooks_block = data.get("hooks", {})
    for _event, matchers in hooks_block.items():
        for matcher_group in matchers:
            for hook in matcher_group.get("hooks", []):
                cmd = hook.get("command", "")
                # Extract the basename of the hook script
                # e.g. "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/correction-detector.sh"
                match = re.search(r"/([\w.-]+\.sh)\"?\s*$", cmd)
                if match:
                    commands.append(match.group(1))
    return commands


# ---------------------------------------------------------------------------
# Check V01: Skill/command match
# ---------------------------------------------------------------------------

def _extract_allowed_skills(build_plugin: Path) -> list[str]:
    """Extract ALLOWED_SKILLS array from build_plugin.sh."""
    skills: list[str] = []
    text = build_plugin.read_text(encoding="utf-8")
    match = re.search(r"ALLOWED_SKILLS=\(([^)]+)\)", text)
    if match:
        skills = match.group(1).split()
    return skills


def check_v01_skill_command_match(repo: Path) -> CheckResult:
    """Public skills in build_plugin.sh ALLOWED_SKILLS each have a SKILL.md,
    and every README Commands slash-command maps to an allowed skill."""
    cid, name = "V01", "Skill/Command Match"

    build_plugin = repo / "build_plugin.sh"
    if not build_plugin.exists():
        return _fail(cid, name, "build_plugin.sh not found")

    skills_dir = repo / "skills"
    if not skills_dir.exists():
        return _fail(cid, name, "skills/ directory not found")

    readme = repo / "README.md"

    # Authoritative public skill list from build_plugin.sh
    allowed_skills = _extract_allowed_skills(build_plugin)
    if not allowed_skills:
        return _fail(cid, name, "No ALLOWED_SKILLS found in build_plugin.sh")

    details: list[str] = []
    failures: list[str] = []

    # Check 1: Every allowed skill has a directory with SKILL.md
    for skill in allowed_skills:
        skill_md = skills_dir / skill / "SKILL.md"
        if not skill_md.exists():
            failures.append(f"Allowed skill '{skill}' missing SKILL.md at skills/{skill}/")

    # Check 2: README Commands table slash-commands map to allowed skills
    # Known command-to-skill mappings (command names differ from skill directory names)
    _COMMAND_SKILL_MAP: dict[str, str] = {
        "/new-project": "bootstrap-discovery",
        "/activate-engine": "bootstrap-activate",
        "/spec-status": "spec-status",
    }
    if readme.exists():
        readme_commands = _extract_readme_commands(readme)
        details.append(f"README commands: {readme_commands}")
        for cmd in readme_commands:
            mapped_skill = _COMMAND_SKILL_MAP.get(cmd)
            if mapped_skill:
                if mapped_skill not in allowed_skills:
                    failures.append(
                        f"README command '{cmd}' maps to '{mapped_skill}' "
                        f"which is not in ALLOWED_SKILLS"
                    )
            else:
                # Fallback: try substring match for unmapped commands
                cmd_bare = cmd.lstrip("/")
                matched = any(
                    cmd_bare == skill or cmd_bare in skill or skill in cmd_bare
                    for skill in allowed_skills
                )
                if not matched:
                    failures.append(f"README command '{cmd}' has no matching allowed skill")

    details.append(f"ALLOWED_SKILLS: {allowed_skills}")
    details.append(f"Skill directories: {sorted(d.name for d in skills_dir.iterdir() if d.is_dir())}")

    if failures:
        return _fail(cid, name,
                     f"{len(failures)} skill/command issue(s)",
                     details + failures)
    return _pass(cid, name,
                 f"{len(allowed_skills)} public skill(s) verified, commands aligned",
                 details)


# ---------------------------------------------------------------------------
# Check V02: Hook references
# ---------------------------------------------------------------------------

def check_v02_hook_references(repo: Path) -> CheckResult:
    """Every hook referenced in settings.template.json has a matching .template.sh in templates/hooks/."""
    cid, name = "V02", "Hook References"

    settings_path = repo / "templates" / "settings" / "settings.template.json"
    if not settings_path.exists():
        return _fail(cid, name, "templates/settings/settings.template.json not found")

    hooks_dir = repo / "templates" / "hooks"
    if not hooks_dir.exists():
        return _fail(cid, name, "templates/hooks/ directory not found")

    # Hook filenames in settings (deployed names, e.g. correction-detector.sh)
    deployed_names = _extract_settings_hook_commands(settings_path)
    if not deployed_names:
        return _fail(cid, name, "No hook commands found in settings.template.json")

    # Template files in templates/hooks/ (e.g. correction-detector.template.sh)
    template_files = {f.name for f in hooks_dir.iterdir() if f.is_file()}

    dangling: list[str] = []
    for deployed in deployed_names:
        # Convert deployed name (correction-detector.sh) to template name (correction-detector.template.sh)
        template_name = deployed.replace(".sh", ".template.sh")
        if template_name not in template_files:
            dangling.append(f"{deployed} -> expected {template_name}")

    details = [f"Hook commands referenced: {deployed_names}"]
    details.append(f"Template files in templates/hooks/: {sorted(template_files)}")

    if dangling:
        return _fail(cid, name,
                     f"{len(dangling)} dangling hook reference(s) — no matching .template.sh",
                     details + [f"Dangling: {dangling}"])
    return _pass(cid, name,
                 f"All {len(deployed_names)} hook reference(s) have matching .template.sh files",
                 details)


# ---------------------------------------------------------------------------
# Check V03: Version match
# ---------------------------------------------------------------------------

def check_v03_version_match(repo: Path) -> CheckResult:
    """VERSION file, plugin.json, and SYSTEMS_MANIFEST.json all agree."""
    cid, name = "V03", "Version Match"

    version_file = repo / "VERSION"
    plugin_json = repo / ".claude-plugin" / "plugin.json"
    manifest_json = repo / "SYSTEMS_MANIFEST.json"

    versions: dict[str, str] = {}
    missing: list[str] = []

    for label, path in [("VERSION", version_file),
                        ("plugin.json", plugin_json),
                        ("SYSTEMS_MANIFEST.json", manifest_json)]:
        if not path.exists():
            missing.append(str(path.relative_to(repo)))
            continue
        if label == "VERSION":
            versions[label] = path.read_text(encoding="utf-8").strip()
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            v = data.get("version", "")
            if v:
                versions[label] = v
            else:
                missing.append(f"{label} (no 'version' key)")

    if missing:
        return _fail(cid, name,
                     f"Missing or unreadable sources: {missing}",
                     [f"Versions found: {versions}"])

    unique_versions = set(versions.values())
    details = [f"{k}: {v}" for k, v in versions.items()]

    if len(unique_versions) == 1:
        return _pass(cid, name,
                     f"All versions agree: {next(iter(unique_versions))}",
                     details)
    return _fail(cid, name,
                 f"Version mismatch across {len(versions)} sources",
                 details + [f"Unique values: {sorted(unique_versions)}"])


# ---------------------------------------------------------------------------
# Check V04: Manifest agreement
# ---------------------------------------------------------------------------

def check_v04_manifest_agreement(repo: Path) -> CheckResult:
    """SYSTEMS_MANIFEST.json summary counts match actual file counts."""
    cid, name = "V04", "Manifest Agreement"

    manifest_path = repo / "SYSTEMS_MANIFEST.json"
    if not manifest_path.exists():
        return _fail(cid, name, "SYSTEMS_MANIFEST.json not found")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})

    frameworks_dir = repo / "templates" / "frameworks"
    hooks_dir = repo / "templates" / "hooks"
    agents_dir = repo / "templates" / "agents"
    rules_dir = repo / "templates" / "rules"
    dbq_commands_dir = repo / "templates" / "scripts" / "dbq" / "commands"

    def count_md(d: Path) -> int:
        return len([f for f in d.iterdir() if f.suffix == ".md"]) if d.exists() else 0

    def count_files(d: Path) -> int:
        return len([f for f in d.iterdir() if f.is_file()]) if d.exists() else 0

    def count_py_commands(d: Path) -> int:
        return len([
            f for f in d.iterdir()
            if f.is_file() and f.suffix == ".py"
            and f.name not in ("__init__.py",)
        ]) if d.exists() else 0

    actual: dict[str, int] = {
        "frameworks": count_md(frameworks_dir),  # .md only, excludes sync.sh
        "hooks": count_files(hooks_dir),
        "agents": count_md(agents_dir),
        "rules": count_files(rules_dir),
        "dbq_commands": count_py_commands(dbq_commands_dir),
    }

    manifest_counts: dict[str, int] = {
        "frameworks": summary.get("frameworks", -1),
        "hooks": summary.get("hooks", -1),
        "agents": summary.get("agents", -1),
        "rules": summary.get("rules", -1),
        "dbq_commands": summary.get("dbq_commands", -1),
    }

    mismatches: list[str] = []
    details: list[str] = []

    for key in actual:
        a = actual[key]
        m = manifest_counts[key]
        status = "OK" if a == m else "MISMATCH"
        details.append(f"  {key}: manifest={m}, actual={a} [{status}]")
        if a != m:
            mismatches.append(f"{key}: manifest says {m}, found {a}")

    if mismatches:
        return _fail(cid, name,
                     f"{len(mismatches)} count mismatch(es) between manifest and actual files",
                     details + [f"Mismatches: {mismatches}"])
    return _pass(cid, name,
                 f"All {len(actual)} manifest counts agree with actual file counts",
                 details)


# ---------------------------------------------------------------------------
# Check V05: Forbidden path check
# ---------------------------------------------------------------------------

# Paths that must NOT appear in files deployed to generated projects.
_FORBIDDEN_PATTERNS: list[str] = [
    r"~/\.claude/frameworks/",
    r"~/\.claude/dev-framework/",
    r"~/\.claude/templates/",
    r"~/\.claude/LESSONS_UNIVERSAL\.md",
    r"/setup-templates",
]

# Markers that indicate an allowed exception on that line.
_EXCEPTION_MARKERS: list[str] = [
    "deprecated",
    "fallback",
    "# was",
    "was ~/",
    "(legacy)",
    "# fall back",
    "# prefer symlink",
]

# File extensions / glob patterns that represent deployed template content.
# Engine files (dbq commands, verify_deployment.py, tests, etc.) are excluded.
_DEPLOYED_GLOBS: list[tuple[str, str]] = [
    # (sub-dir relative to templates/, glob pattern)
    ("rules", "*.md"),
    ("scripts", "*.template.sh"),
    ("hooks", "*.template.sh"),
    ("agents", "*.template.md"),
]


def _is_exception_line(line: str) -> bool:
    """Return True if the line contains an allowed exception marker."""
    lower = line.lower()
    return any(marker in lower for marker in _EXCEPTION_MARKERS)


def _scan_deployed_templates(
    repo: Path,
) -> list[tuple[Path, int, str, str]]:
    """Scan deployed template files for forbidden path patterns.

    Returns a list of (file_path, line_number, matched_pattern, line_text)
    tuples for each violation found.
    """
    templates_dir = repo / "templates"
    violations: list[tuple[Path, int, str, str]] = []

    compiled = [(pat, re.compile(pat, re.IGNORECASE)) for pat in _FORBIDDEN_PATTERNS]

    for subdir, glob_pat in _DEPLOYED_GLOBS:
        target_dir = templates_dir / subdir
        if not target_dir.exists():
            continue
        for fpath in sorted(target_dir.glob(glob_pat)):
            if not fpath.is_file():
                continue
            try:
                lines = fpath.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                if _is_exception_line(line):
                    continue
                for pat_str, pat_re in compiled:
                    if pat_re.search(line):
                        violations.append((fpath, lineno, pat_str, line.strip()))
                        break  # one violation per line is enough

    return violations


def check_v05_forbidden_paths(repo: Path) -> CheckResult:
    """Deployed template files must not reference forbidden global paths.

    Forbidden paths are those that belong to the bootstrap developer's machine
    (~/.claude/frameworks/, ~/.claude/dev-framework/, etc.) and must be replaced
    with local project-relative paths in the v1.0 rewrite (tasks V1-033 through
    V1-052).  Lines containing deprecation/fallback markers are exempt.
    """
    cid, name = "V05", "Forbidden Path Check"

    templates_dir = repo / "templates"
    if not templates_dir.exists():
        return _fail(cid, name, "templates/ directory not found")

    violations = _scan_deployed_templates(repo)

    # Group by file for readable output
    by_file: dict[str, list[str]] = {}
    for fpath, lineno, _pat, line_text in violations:
        rel = str(fpath.relative_to(repo))
        by_file.setdefault(rel, []).append(f"  L{lineno}: {line_text[:120]}")

    details: list[str] = []
    details.append(f"Scanned deployed template dirs: {[g[0] for g in _DEPLOYED_GLOBS]}")
    details.append(
        f"Forbidden patterns: {_FORBIDDEN_PATTERNS}"
    )
    details.append(
        "Exception markers (lines with these are skipped): "
        + str(_EXCEPTION_MARKERS)
    )

    if not violations:
        return _pass(
            cid, name,
            "No forbidden global paths found in deployed template files",
            details,
        )

    for rel_path, hits in sorted(by_file.items()):
        details.append(f"\n  {rel_path} ({len(hits)} violation(s)):")
        details.extend(hits)

    return _fail(
        cid, name,
        f"{len(violations)} forbidden path reference(s) in {len(by_file)} file(s) "
        f"— pending v1.0 rewrite (V1-033 through V1-052)",
        details,
    )


# ---------------------------------------------------------------------------
# Check V06: Allowed refs check
# ---------------------------------------------------------------------------

def check_v06_allowed_refs(repo: Path) -> CheckResult:
    """Key template files reference only their declared dependencies.

    Sub-checks:
      (a) db_queries.template.sh — must not reference global paths outside comments.
          It should use only ${SCRIPT_DIR}/scripts (the local dbq package).
      (b) CLAUDE_TEMPLATE.md — must not @-import paths that resolve outside the
          project directory (i.e. @~/ or @/ absolute paths).
    """
    cid, name = "V06", "Allowed Refs Check"

    failures: list[str] = []
    details: list[str] = []

    # --- Sub-check (a): db_queries.template.sh ---
    dbq_tpl = repo / "templates" / "scripts" / "db_queries.template.sh"
    if not dbq_tpl.exists():
        failures.append("db_queries.template.sh not found")
    else:
        global_path_re = re.compile(r"~/\.claude/", re.IGNORECASE)
        forbidden_lines: list[str] = []
        for lineno, line in enumerate(
            dbq_tpl.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            # Allow comment lines (they may reference paths for documentation)
            if stripped.startswith("#"):
                continue
            if global_path_re.search(line) and not _is_exception_line(line):
                forbidden_lines.append(f"  L{lineno}: {stripped[:120]}")

        if forbidden_lines:
            failures.append(
                f"db_queries.template.sh contains {len(forbidden_lines)} "
                "global path reference(s) outside comments"
            )
            details.append(
                f"db_queries.template.sh violations ({len(forbidden_lines)}):"
            )
            details.extend(forbidden_lines)
        else:
            details.append(
                "db_queries.template.sh: OK — only ${SCRIPT_DIR}/scripts references found"
            )

    # --- Sub-check (b): CLAUDE_TEMPLATE.md @-imports ---
    claude_tpl = repo / "templates" / "rules" / "CLAUDE_TEMPLATE.md"
    if not claude_tpl.exists():
        failures.append("CLAUDE_TEMPLATE.md not found")
    else:
        # An @-import is a line starting with @ followed by a path.
        # External @-imports are those pointing outside the project:
        #   @~/ (home-relative) or @/ (absolute)
        external_import_re = re.compile(r"^@(~/|/)")
        external_imports: list[str] = []
        for lineno, line in enumerate(
            claude_tpl.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if external_import_re.match(stripped) and not _is_exception_line(stripped):
                external_imports.append(f"  L{lineno}: {stripped}")

        if external_imports:
            failures.append(
                f"CLAUDE_TEMPLATE.md contains {len(external_imports)} external @-import(s) "
                "— must be replaced with local framework paths (V1-033)"
            )
            details.append(
                f"CLAUDE_TEMPLATE.md external @-imports ({len(external_imports)}):"
            )
            details.extend(external_imports)
        else:
            details.append(
                "CLAUDE_TEMPLATE.md: OK — no external @-imports found"
            )

    if failures:
        return _fail(cid, name, "; ".join(failures), details)
    return _pass(
        cid, name,
        "All allowed-refs sub-checks passed",
        details,
    )


# ---------------------------------------------------------------------------
# Check V07: Public skill hygiene
# ---------------------------------------------------------------------------

# Patterns that must not appear in public-facing skill files.
# Note: ~/.claude/CLAUDE.md is a standard user path (not developer-specific),
# so we only flag ~/.claude/ sub-paths that are bootstrap-internal.
_PRIVATE_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/Users/\w+/Desktop/"),
    re.compile(r"/Users/\w+/Documents/"),
    re.compile(r"~/\.claude/frameworks/"),
    re.compile(r"~/\.claude/dev-framework/"),
    re.compile(r"~/\.claude/templates/"),
]


def check_v07_public_skill_hygiene(repo: Path) -> CheckResult:
    """Public skill SKILL.md files must not contain developer-machine paths."""
    cid, name = "V07", "Public Skill Hygiene"

    build_plugin = repo / "build_plugin.sh"
    if not build_plugin.exists():
        return _fail(cid, name, "build_plugin.sh not found")

    allowed_skills = _extract_allowed_skills(build_plugin)
    if not allowed_skills:
        return _fail(cid, name, "No ALLOWED_SKILLS found in build_plugin.sh")

    skills_dir = repo / "skills"
    violations: list[str] = []

    scanned_files = 0
    for skill in allowed_skills:
        skill_path = skills_dir / skill
        if not skill_path.exists():
            continue
        # Scan all files in the skill directory, not just SKILL.md
        for fpath in skill_path.rglob("*"):
            if not fpath.is_file():
                continue
            # Only scan text files
            if fpath.suffix in (".sh", ".md", ".py", ".json", ".yaml", ".yml", ".conf", ".txt", ""):
                scanned_files += 1
                rel = fpath.relative_to(skills_dir)
                try:
                    text = fpath.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    for pat in _PRIVATE_PATH_PATTERNS:
                        if pat.search(line):
                            violations.append(
                                f"skills/{rel} L{lineno}: {line.strip()[:100]}"
                            )
                            break  # one violation per line

    details = [f"Checked {len(allowed_skills)} public skill(s): {allowed_skills}",
               f"Scanned {scanned_files} file(s) across skill directories"]

    if violations:
        return _fail(cid, name,
                     f"{len(violations)} private path(s) in public skill files",
                     details + violations)
    return _pass(cid, name,
                 f"No private paths found in {len(allowed_skills)} public skill file(s)",
                 details)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CHECKS = [
    check_v01_skill_command_match,
    check_v02_hook_references,
    check_v03_version_match,
    check_v04_manifest_agreement,
    check_v05_forbidden_paths,
    check_v06_allowed_refs,
    check_v07_public_skill_hygiene,
]


def run_all(repo: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check_fn in CHECKS:
        result = check_fn(repo)
        results.append(result)
    return results


def print_results(results: list[CheckResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total = len(results)

    print(f"\nvalidate_build.py — {total} checks\n{'=' * 50}")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"\n[{status}] {r.check_id}: {r.name}")
        print(f"      {r.message}")
        for detail in r.details:
            print(f"      {detail}")

    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} FAILED")
    else:
        print(" — all clear")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="validate_build.py — build-time consistency checks for project-bootstrap"
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to the repository root (default: current directory)",
    )
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    if not repo.is_dir():
        print(f"ERROR: repo root not found: {repo}", file=sys.stderr)
        return 1

    results = run_all(repo)
    print_results(results)

    any_failed = any(not r.passed for r in results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
