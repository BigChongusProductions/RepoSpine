"""
Drift detection: unified coherence checking with scored report.

Runs deterministic checkers (C1-C10) against the project and produces
a 0-100 score. Designed to surface configuration rot early.

Checkers C1-C5 implemented in QK-0325a.
Checkers C6-C10 will be implemented in QK-0329.
"""
import fnmatch
import glob as glob_module
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..db import Database
from ..config import ProjectConfig


# ── Data Model ──────────────────────────────────────────────────────

@dataclass
class DriftIssue:
    """A single drift issue found by a checker."""
    code: str           # e.g. "MISSING_PATH", "STALE_FILE"
    severity: str       # "error", "warning", "info"
    checker: str        # e.g. "C1-path-refs", "C2-framework-sync"
    file: str           # Which file has the issue
    line: Optional[int] # Line number if applicable
    message: str        # Human-readable description


@dataclass
class DriftReport:
    """Aggregated drift report from all checkers."""
    score: int
    issues: List[DriftIssue] = field(default_factory=list)
    checker_count: int = 0
    checkers_passed: int = 0
    timestamp: str = ""

    def add_issues(self, new_issues: List[DriftIssue]) -> None:
        """Append issues from a single checker run."""
        self.issues.extend(new_issues)

    def compute_score(self) -> None:
        """Score = 100, minus penalties per issue severity."""
        score = 100
        for issue in self.issues:
            score -= SEVERITY_PENALTIES.get(issue.severity, 0)
        self.score = max(0, score)


# ── Severity penalty constants ──────────────────────────────────────

SEVERITY_PENALTIES = {"error": 10, "warning": 3, "info": 1}


# ── Checker registry ────────────────────────────────────────────────

# Each checker is a callable: (project_root: Path, db: Database) -> List[DriftIssue]
# C1-C5 implemented (QK-0325a). C6-C10 implemented (QK-0329).

CHECKER_REGISTRY = {
    "C1-path-refs": "File paths in config files exist on disk",
    "C2-framework-sync": "Template frameworks match deployed copies",
    "C3-placeholder-registry": "Placeholder usage matches registry",
    "C4-staleness": "Key files updated within thresholds",
    "C5-delegation-coherence": "Delegation map matches DB state",
    "C6-import-chain": "@-imports and ROUTER.md refs exist",
    "C7-hook-validity": "Hook scripts in settings.json are executable",
    "C8-db-health": "Database tables, schema, integrity",
    "C9-test-pass-rate": "Last test run passed",
    "C10-rule-coverage": "Rule file globs match existing files",
    "C11-version-consistency": "VERSION file matches plugin.json version",
}


def _stub_checker(
    checker_id: str,
    project_root: Path,
    db: Database,
) -> List[DriftIssue]:
    """Placeholder checker — returns no issues. Used for C6-C10 until implemented."""
    return []


# ── Checker implementations (C1-C5) ────────────────────────────────


def check_path_refs(project_root: Path, db: Database) -> List[DriftIssue]:
    """C1: Verify file paths referenced in config files exist."""
    issues = []
    files_to_scan = ["CLAUDE.md", "BOOTSTRAP_RULES.md", "ROUTER.md"]

    path_patterns = [
        re.compile(r'@(~?[^\s]+\.md)'),                    # @-imports
        re.compile(r'`([^\s`]+\.(md|sh|py|json))`'),        # backtick paths
    ]

    for fname in files_to_scan:
        fpath = project_root / fname
        if not fpath.exists():
            continue
        content = fpath.read_text()
        for line_num, line in enumerate(content.splitlines(), 1):
            # Skip Markdown blockquote lines — they contain documentation text,
            # not actual path references to validate.
            if line.strip().startswith(">"):
                continue
            for pattern in path_patterns:
                for match in pattern.finditer(line):
                    ref_path = match.group(1)
                    # Skip patterns with variables or template tokens
                    if "$" in ref_path or "{{" in ref_path:
                        continue
                    # Skip paths that start with @ — these are @-import prefixes
                    # captured by the backtick pattern, not raw paths
                    if ref_path.startswith("@"):
                        continue
                    # Resolve path
                    if ref_path.startswith("~"):
                        resolved = Path(os.path.expanduser(ref_path))
                    elif ref_path.startswith("/"):
                        resolved = Path(ref_path)
                    else:
                        resolved = project_root / ref_path

                    if not resolved.exists():
                        issues.append(DriftIssue(
                            code="MISSING_PATH",
                            severity="error",
                            checker="C1-path-refs",
                            file=fname,
                            line=line_num,
                            message=f"Referenced path does not exist: {ref_path}",
                        ))
    return issues


def check_framework_sync(project_root: Path, db: Database) -> List[DriftIssue]:
    """C2: Verify template frameworks match bundled local copies in frameworks/."""
    issues = []
    source_dir = project_root / "templates" / "frameworks"
    deployed_dir = project_root / "frameworks"

    # Not a meta-project (no templates/frameworks/) — nothing to sync
    if not source_dir.exists():
        return issues

    if not deployed_dir.exists():
        issues.append(DriftIssue(
            code="MISSING_DEPLOY_DIR",
            severity="error",
            checker="C2-framework-sync",
            file="frameworks/",
            line=None,
            message="frameworks/ directory missing — project may not have been bootstrapped with v1.0+",
        ))
        return issues

    for source_file in sorted(source_dir.glob("*.md")):
        deployed_file = deployed_dir / source_file.name
        if not deployed_file.exists():
            issues.append(DriftIssue(
                code="MISSING_DEPLOYED",
                severity="warning",
                checker="C2-framework-sync",
                file=f"frameworks/{source_file.name}",
                line=None,
                message=f"Template {source_file.name} not present in frameworks/",
            ))
            continue

        source_content = source_file.read_text()
        deployed_content = deployed_file.read_text()
        if source_content != deployed_content:
            issues.append(DriftIssue(
                code="CONTENT_MISMATCH",
                severity="error",
                checker="C2-framework-sync",
                file=f"frameworks/{source_file.name}",
                line=None,
                message="Content differs from templates/frameworks/ source",
            ))
    return issues


def check_placeholder_registry(project_root: Path, db: Database) -> List[DriftIssue]:
    """C3: Verify placeholder usage matches registry."""
    issues = []
    registry_path = (
        project_root
        / "skills"
        / "bootstrap-activate"
        / "references"
        / "placeholder-registry.md"
    )

    if not registry_path.exists():
        issues.append(DriftIssue(
            code="MISSING_REGISTRY",
            severity="warning",
            checker="C3-placeholder-registry",
            file="skills/bootstrap-activate/references/placeholder-registry.md",
            line=None,
            message="Placeholder registry file not found",
        ))
        return issues

    registry_content = registry_path.read_text()
    # Registry uses %%PLACEHOLDER%% syntax (the actual token format)
    registered = set(re.findall(r'%%([A-Z_]+)%%', registry_content))

    templates_dir = project_root / "templates"
    if not templates_dir.exists():
        return issues

    used: set = set()
    placeholder_pattern = re.compile(r'%%([A-Z_]+)%%')

    for fpath in templates_dir.rglob("*"):
        if fpath.is_file() and fpath.suffix in (".md", ".sh", ".py", ".json", ".yaml", ".yml"):
            try:
                content = fpath.read_text()
                found = placeholder_pattern.findall(content)
                used.update(found)
            except (UnicodeDecodeError, PermissionError):
                continue

    unregistered = used - registered
    for ph in sorted(unregistered):
        issues.append(DriftIssue(
            code="UNREGISTERED_PLACEHOLDER",
            severity="warning",
            checker="C3-placeholder-registry",
            file="templates/",
            line=None,
            message=f"Placeholder %%{ph}%% used in templates but not in registry",
        ))

    return issues


def check_staleness(project_root: Path, db: Database) -> List[DriftIssue]:
    """C4: Key files updated within freshness thresholds."""
    issues = []
    now = time.time()

    checks = [
        ("NEXT_SESSION.md", 48 * 3600, "48 hours"),
    ]

    for filename, threshold, label in checks:
        fpath = project_root / filename
        if not fpath.exists():
            continue
        mtime = fpath.stat().st_mtime
        age = now - mtime
        if age > threshold:
            age_hours = int(age / 3600)
            issues.append(DriftIssue(
                code="STALE_FILE",
                severity="warning",
                checker="C4-staleness",
                file=filename,
                line=None,
                message=f"File is {age_hours}h old (threshold: {label})",
            ))

    lessons_candidates = list(project_root.glob("LESSONS*.md"))
    if lessons_candidates:
        lessons_file = lessons_candidates[0]
        mtime = lessons_file.stat().st_mtime
        age_days = (now - mtime) / 86400
        if age_days > 30:
            issues.append(DriftIssue(
                code="STALE_FILE",
                severity="warning",
                checker="C4-staleness",
                file=lessons_file.name,
                line=None,
                message=f"File is {int(age_days)} days old (threshold: 30 days)",
            ))

    return issues


def check_delegation_coherence(project_root: Path, db: Database) -> List[DriftIssue]:
    """C5: Delegation file references match DB state."""
    issues = []
    deleg_file = project_root / "AGENT_DELEGATION.md"

    if not deleg_file.exists():
        issues.append(DriftIssue(
            code="MISSING_DELEGATION",
            severity="warning",
            checker="C5-delegation-coherence",
            file="AGENT_DELEGATION.md",
            line=None,
            message="AGENT_DELEGATION.md not found",
        ))
        return issues

    task_count = db.fetch_scalar("SELECT COUNT(*) FROM tasks")
    if task_count == 0:
        return issues

    untiered = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE tier IS NULL "
        "AND status NOT IN ('DONE','SKIP') AND queue != 'INBOX'"
    )
    if untiered > 0:
        issues.append(DriftIssue(
            code="UNTIERED_TASKS",
            severity="warning",
            checker="C5-delegation-coherence",
            file="DB:tasks",
            line=None,
            message=f"{untiered} active task(s) have no tier assignment",
        ))

    return issues


def run_all_checkers(project_root: Path, db: Database) -> DriftReport:
    """Run all registered checkers and produce a scored report."""
    report = DriftReport(
        score=100,
        checker_count=len(CHECKER_REGISTRY),
        timestamp=datetime.now().isoformat(),
    )

    for checker_id in CHECKER_REGISTRY:
        fn = CHECKER_FUNCTIONS.get(checker_id)
        if fn is not None:
            issues = fn(project_root, db)
        else:
            issues = _stub_checker(checker_id, project_root, db)
        if not issues:
            report.checkers_passed += 1
        report.add_issues(issues)

    report.compute_score()
    return report


# ── C6-C10 Checker implementations ──────────────────────────────────


def check_import_chain(project_root: Path, db: Database) -> List[DriftIssue]:
    """C6: @-imports and ROUTER.md references exist."""
    issues: List[DriftIssue] = []

    # Check @-imports in CLAUDE.md
    claude_md = project_root / "CLAUDE.md"
    if claude_md.exists():
        for line_num, line in enumerate(claude_md.read_text().splitlines(), 1):
            if line.startswith("@"):
                ref = line[1:].strip()
                if ref.startswith("~"):
                    resolved = Path(os.path.expanduser(ref))
                else:
                    resolved = project_root / ref
                if not resolved.exists():
                    issues.append(DriftIssue(
                        code="BROKEN_IMPORT",
                        severity="error",
                        checker="C6-import-chain",
                        file="CLAUDE.md",
                        line=line_num,
                        message=f"@-import target does not exist: {ref}",
                    ))

    # Check file refs in ROUTER.md
    router_md = project_root / "ROUTER.md"
    if router_md.exists():
        content = router_md.read_text()
        ref_pattern = re.compile(r'`((?:templates|refs|skills)/[^\s`]+)`')
        for line_num, line in enumerate(content.splitlines(), 1):
            for match in ref_pattern.finditer(line):
                ref = match.group(1)
                resolved = project_root / ref
                if not resolved.exists():
                    issues.append(DriftIssue(
                        code="BROKEN_ROUTER_REF",
                        severity="error",
                        checker="C6-import-chain",
                        file="ROUTER.md",
                        line=line_num,
                        message=f"Referenced file does not exist: {ref}",
                    ))

    return issues


def check_hook_validity(project_root: Path, db: Database) -> List[DriftIssue]:
    """C7: Hook scripts in settings.json are executable."""
    issues: List[DriftIssue] = []
    settings_path = project_root / ".claude" / "settings.json"

    if not settings_path.exists():
        issues.append(DriftIssue(
            code="MISSING_SETTINGS",
            severity="warning",
            checker="C7-hook-validity",
            file=".claude/settings.json",
            line=None,
            message="Settings file not found",
        ))
        return issues

    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        issues.append(DriftIssue(
            code="INVALID_JSON",
            severity="error",
            checker="C7-hook-validity",
            file=".claude/settings.json",
            line=None,
            message="Settings file contains invalid JSON",
        ))
        return issues

    hooks = settings.get("hooks", {})
    for event_name, event_hooks in hooks.items():
        for hook_group in event_hooks:
            for hook in hook_group.get("hooks", []):
                cmd = hook.get("command", "")
                # Extract script path — handle $CLAUDE_PROJECT_DIR substitution
                script = cmd.replace('"$CLAUDE_PROJECT_DIR"', str(project_root))
                script = script.replace("$CLAUDE_PROJECT_DIR", str(project_root))
                parts = script.split()
                script_path = Path(parts[0]) if parts else None

                if script_path and not script_path.exists():
                    issues.append(DriftIssue(
                        code="MISSING_HOOK",
                        severity="error",
                        checker="C7-hook-validity",
                        file=".claude/settings.json",
                        line=None,
                        message=f"Hook script not found: {script} (event: {event_name})",
                    ))
                elif script_path and not os.access(str(script_path), os.X_OK):
                    issues.append(DriftIssue(
                        code="NON_EXECUTABLE_HOOK",
                        severity="error",
                        checker="C7-hook-validity",
                        file=str(script_path),
                        line=None,
                        message=f"Hook script is not executable (event: {event_name})",
                    ))

    return issues


def check_db_health(project_root: Path, db: Database) -> List[DriftIssue]:
    """C8: Database tables, schema, integrity."""
    issues: List[DriftIssue] = []

    required_tables = ["tasks", "phase_gates", "sessions", "decisions"]
    for table in required_tables:
        if not db.table_exists(table):
            issues.append(DriftIssue(
                code="MISSING_TABLE",
                severity="error",
                checker="C8-db-health",
                file="bootstrap.db",
                line=None,
                message=f"Required table '{table}' missing",
            ))

    if db.table_exists("tasks"):
        required_cols = ["id", "phase", "title", "status", "tier", "assignee"]
        try:
            col_rows = db.fetch_all("PRAGMA table_info(tasks)")
            existing_cols = {r["name"] for r in col_rows}
            for col in required_cols:
                if col not in existing_cols:
                    issues.append(DriftIssue(
                        code="MISSING_COLUMN",
                        severity="error",
                        checker="C8-db-health",
                        file="bootstrap.db",
                        line=None,
                        message=f"Required column 'tasks.{col}' missing",
                    ))
        except Exception:
            issues.append(DriftIssue(
                code="SCHEMA_ERROR",
                severity="error",
                checker="C8-db-health",
                file="bootstrap.db",
                line=None,
                message="Failed to inspect tasks table schema",
            ))

    return issues


def check_test_pass_rate(project_root: Path, db: Database) -> List[DriftIssue]:
    """C9: Last health check passed (from cache)."""
    issues: List[DriftIssue] = []
    cache_file = project_root / ".claude" / "hooks" / ".health_cache"

    if not cache_file.exists():
        issues.append(DriftIssue(
            code="NO_HEALTH_CACHE",
            severity="info",
            checker="C9-test-pass-rate",
            file=".claude/hooks/.health_cache",
            line=None,
            message="No cached health check result found",
        ))
        return issues

    cache_age = time.time() - cache_file.stat().st_mtime
    if cache_age > 3600:  # older than 1 hour
        issues.append(DriftIssue(
            code="STALE_HEALTH",
            severity="info",
            checker="C9-test-pass-rate",
            file=".claude/hooks/.health_cache",
            line=None,
            message=f"Health cache is {int(cache_age / 60)}min old (threshold: 60min)",
        ))

    cache_content = cache_file.read_text().strip()
    if "CRITICAL" in cache_content or "DEGRADED" in cache_content:
        issues.append(DriftIssue(
            code="UNHEALTHY",
            severity="warning",
            checker="C9-test-pass-rate",
            file=".claude/hooks/.health_cache",
            line=None,
            message=f"Last health check was not HEALTHY: {cache_content[:80]}",
        ))

    return issues


def check_rule_coverage(project_root: Path, db: Database) -> List[DriftIssue]:
    """C10: Rule file globs match existing files."""
    issues: List[DriftIssue] = []
    rules_dir = project_root / ".claude" / "rules"

    if not rules_dir.exists():
        return issues

    for rule_file in sorted(rules_dir.glob("*.md")):
        content = rule_file.read_text()

        # Extract globs from frontmatter
        glob_match = re.search(r'^globs:\s*(.+)$', content, re.MULTILINE)
        if not glob_match:
            issues.append(DriftIssue(
                code="NO_GLOB",
                severity="info",
                checker="C10-rule-coverage",
                file=f".claude/rules/{rule_file.name}",
                line=None,
                message="Rule file has no globs: field in frontmatter",
            ))
            continue

        glob_pattern = glob_match.group(1).strip()

        # Check if glob matches any existing files
        matches = glob_module.glob(str(project_root / glob_pattern), recursive=True)
        if not matches:
            issues.append(DriftIssue(
                code="EMPTY_GLOB",
                severity="info",
                checker="C10-rule-coverage",
                file=f".claude/rules/{rule_file.name}",
                line=None,
                message=f"Glob '{glob_pattern}' matches no files",
            ))

    return issues


def check_version_consistency(project_root: Path, db: Database) -> List[DriftIssue]:
    """C11: VERSION file matches plugin.json version field."""
    issues: List[DriftIssue] = []

    version_file = project_root / "VERSION"
    plugin_json = project_root / ".claude-plugin" / "plugin.json"

    if not version_file.exists():
        # No VERSION file — not all projects have one, skip silently
        return issues

    if not plugin_json.exists():
        # No plugin — skip silently
        return issues

    try:
        version_content = version_file.read_text().strip()
    except OSError:
        return issues

    try:
        import json as _json
        plugin_data = _json.loads(plugin_json.read_text())
        plugin_version = plugin_data.get("version", "")
    except (OSError, ValueError):
        issues.append(DriftIssue(
            code="PLUGIN_JSON_INVALID",
            severity="warning",
            checker="C11-version-consistency",
            file=".claude-plugin/plugin.json",
            line=None,
            message="plugin.json is unreadable or invalid JSON",
        ))
        return issues

    if version_content != plugin_version:
        issues.append(DriftIssue(
            code="VERSION_MISMATCH",
            severity="error",
            checker="C11-version-consistency",
            file="VERSION",
            line=None,
            message=f"VERSION ({version_content}) != plugin.json ({plugin_version})",
        ))

    return issues


# ── Checker function dispatch table ─────────────────────────────────
# Maps checker IDs to their real implementations.
# C1-C5 implemented in QK-0325a; C6-C10 implemented in QK-0329.
# run_all_checkers() uses this dict and falls back to _stub_checker.

CHECKER_FUNCTIONS = {
    "C1-path-refs": check_path_refs,
    "C2-framework-sync": check_framework_sync,
    "C3-placeholder-registry": check_placeholder_registry,
    "C4-staleness": check_staleness,
    "C5-delegation-coherence": check_delegation_coherence,
    "C6-import-chain": check_import_chain,
    "C7-hook-validity": check_hook_validity,
    "C8-db-health": check_db_health,
    "C9-test-pass-rate": check_test_pass_rate,
    "C10-rule-coverage": check_rule_coverage,
    "C11-version-consistency": check_version_consistency,
}


# ── CLI commands ────────────────────────────────────────────────────

def cmd_drift(
    db: Database,
    config: ProjectConfig,
    json_output: bool = False,
    quiet: bool = False,
) -> None:
    """Run drift detection and display report."""
    project_root = config.project_dir
    report = run_all_checkers(project_root, db)

    if json_output:
        data = {
            "score": report.score,
            "checker_count": report.checker_count,
            "checkers_passed": report.checkers_passed,
            "timestamp": report.timestamp,
            "issues": [asdict(i) for i in report.issues],
        }
        print(json.dumps(data, indent=2))
        return

    if quiet:
        errors = sum(1 for i in report.issues if i.severity == "error")
        warnings = sum(1 for i in report.issues if i.severity == "warning")
        infos = sum(1 for i in report.issues if i.severity == "info")
        parts = []
        if errors:
            parts.append(f"{errors} error(s)")
        if warnings:
            parts.append(f"{warnings} warning(s)")
        if infos:
            parts.append(f"{infos} info(s)")
        detail = ", ".join(parts) if parts else "clean"
        print(f"drift: {report.score}/100 ({detail})")
        return

    # Full console report
    print("")
    print("== DRIFT DETECTION REPORT =======================================")
    print(f"  Timestamp: {report.timestamp}")
    print(f"  Checkers:  {report.checkers_passed}/{report.checker_count} passed")
    print(f"  Score:     {report.score}/100")

    if report.issues:
        print("")
        print("  Issues:")
        severity_icons = {"error": "[error]", "warning": "[warn] ", "info":  "[info] "}
        for issue in report.issues:
            icon = severity_icons.get(issue.severity, "       ")
            line_ref = f":{issue.line}" if issue.line else ""
            print(f"    {icon} [{issue.checker}] {issue.file}{line_ref}")
            print(f"           {issue.message}")
    else:
        print("")
        print("  No issues detected")

    print("")
    print("=================================================================")
    print("")
