"""
Evaluation commands: eval, eval-report, eval-compare.

Three-layer scoring system:
  Layer 1 (D1-D8): Deployment Quality — filesystem + DB checks
  Layer 2 (P1-P7): Process Health — DB query metrics
  Layer 3 (V1-V4): Improvement Velocity — temporal trends

Spec reference: eval-system-implementation-spec.md §5-§9.
"""
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import ProjectConfig
from ..db import Database
from ..remediation import EvalCheckResult
from ..scoring import (
    score_with_confidence,
    sigmoid_penalty,
    weighted_composite,
)


# ── Layer 1: Deployment Quality (D1-D8) ──────────────────────────

# Weight config from spec §5
L1_WEIGHTS = {
    "D1": 0.20,
    "D2": 0.20,
    "D3": 0.15,
    "D4": 0.10,
    "D5": 0.10,
    "D6": 0.10,
    "D7": 0.10,
    "D8": 0.05,
}

# Scripts expected at project root (D1)
_EXPECTED_SCRIPTS = [
    "db_queries.sh",
    "session_briefing.sh",
    "save_session.sh",
    "work.sh",
    "build_summarizer.sh",
]

# Operational files to scan for placeholders (D7)
_OPERATIONAL_GLOBS = [
    "db_queries.sh",
    "session_briefing.sh",
    "save_session.sh",
    "work.sh",
    "CLAUDE.md",
    "*RULES*.md",
    "AGENT_DELEGATION.md",
    "milestone_check.sh",
    "build_summarizer.sh",
    "coherence_check.sh",
]

# Frameworks expected (D4)
_EXPECTED_FRAMEWORKS = [
    "session-protocol.md",
    "phase-gates.md",
    "correction-protocol.md",
    "delegation.md",
    "loopback-system.md",
    "quality-gates.md",
    "falsification.md",
    "visual-verification.md",
    "coherence-system.md",
    "development-discipline.md",
]


def _check_d1_tools(project_dir: Path) -> EvalCheckResult:
    """D1: Tools — Script Deployment. Verify scripts exist and are executable."""
    found = 0
    missing = []
    for name in _EXPECTED_SCRIPTS:
        p = project_dir / name
        if p.exists() and os.access(p, os.X_OK):
            found += 1
        elif p.exists():
            found += 1  # exists but not executable — partial credit
        else:
            missing.append(name)

    # Also check for project-specific variants (generate_board.py, etc.)
    extras = ["generate_board.py", "coherence_check.sh"]
    for name in extras:
        p = project_dir / name
        if p.exists():
            found += 1

    expected = len(_EXPECTED_SCRIPTS) + sum(
        1 for n in extras if (project_dir / n).exists()
    )
    expected = max(expected, len(_EXPECTED_SCRIPTS))
    score = (found / expected) * 100 if expected > 0 else 100.0

    remediation = ""
    if missing:
        remediation = f"Missing scripts: {', '.join(missing)}"

    return EvalCheckResult(
        id="D1",
        name="Tools — Script Deployment",
        score=score,
        details=f"{found}/{expected} scripts deployed",
        remediation=remediation,
    )


def _check_d2_database(db: Database, config: ProjectConfig) -> EvalCheckResult:
    """D2: Database — Schema & Population. 10 checks."""
    checks_passed = 0
    total_checks = 10
    issues = []

    # 1. All 8 tables exist
    expected_tables = [
        "tasks",
        "phase_gates",
        "decisions",
        "sessions",
        "milestone_confirmations",
        "db_snapshots",
        "assumptions",
        "loopback_acks",
    ]
    tables_ok = all(db.table_exists(t) for t in expected_tables)
    if tables_ok:
        checks_passed += 1
    else:
        missing = [t for t in expected_tables if not db.table_exists(t)]
        issues.append(f"Missing tables: {', '.join(missing)}")

    # 2. Tasks table has expected columns
    expected_cols = [
        "id",
        "phase",
        "title",
        "status",
        "priority",
        "assignee",
        "blocked_by",
        "sort_order",
        "queue",
        "tier",
        "skill",
        "track",
        "origin_phase",
        "severity",
        "completed_on",
    ]
    cols_ok = all(db.column_exists("tasks", c) for c in expected_cols)
    if cols_ok:
        checks_passed += 1
    else:
        issues.append("Tasks table missing expected columns")

    # 3. Tasks table is non-empty
    task_count = db.fetch_scalar("SELECT COUNT(*) FROM tasks", default=0)
    if task_count > 0:
        checks_passed += 1
    else:
        issues.append("Tasks table is empty")

    # 4. Multiple phases represented
    phase_count = db.fetch_scalar(
        "SELECT COUNT(DISTINCT phase) FROM tasks", default=0
    )
    if phase_count >= 2:
        checks_passed += 1
    else:
        issues.append(f"Only {phase_count} phase(s) — need >= 2")

    # 5. Tasks have tier assignments
    tiered = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE tier IS NOT NULL", default=0
    )
    if tiered > 0:
        checks_passed += 1
    else:
        issues.append("No tasks have tier assignments")

    # 6. Phase gate entries match task phases
    if db.table_exists("phase_gates"):
        gate_phases = {
            r["phase"]
            for r in db.fetch_all("SELECT DISTINCT phase FROM phase_gates")
        }
        task_phases = {
            r["phase"]
            for r in db.fetch_all("SELECT DISTINCT phase FROM tasks")
        }
        if gate_phases <= task_phases or not gate_phases:
            checks_passed += 1
        else:
            orphaned = gate_phases - task_phases
            issues.append(f"Orphaned gate phases: {orphaned}")
    else:
        checks_passed += 1  # no gate table = no orphans

    # 7. blocked_by references point to real task IDs
    rows = db.fetch_all(
        "SELECT id, blocked_by FROM tasks WHERE blocked_by IS NOT NULL "
        "AND blocked_by != ''"
    )
    all_ids = {
        r["id"] for r in db.fetch_all("SELECT id FROM tasks")
    }
    broken_refs = []
    for row in rows:
        for ref in str(row["blocked_by"]).split(","):
            ref = ref.strip()
            if ref and ref not in all_ids:
                broken_refs.append(f"{row['id']} → {ref}")
    if not broken_refs:
        checks_passed += 1
    else:
        issues.append(f"Broken blocked_by refs: {broken_refs[:3]}")

    # 8. No duplicate task IDs
    dup_count = db.fetch_scalar(
        "SELECT COUNT(*) FROM ("
        "  SELECT id FROM tasks GROUP BY id HAVING COUNT(*) > 1"
        ")",
        default=0,
    )
    if dup_count == 0:
        checks_passed += 1
    else:
        issues.append(f"{dup_count} duplicate task ID(s)")

    # 9. No circular dependencies (A blocks B, B blocks A)
    # Build blocked_by map from already-fetched rows
    block_map: Dict[str, List[str]] = {}
    for row in rows:
        block_map[row["id"]] = [
            b.strip()
            for b in str(row["blocked_by"]).split(",")
            if b.strip()
        ]
    circular = False
    for task_id, blockers in block_map.items():
        for blocker_id in blockers:
            reverse = block_map.get(blocker_id, [])
            if task_id in reverse:
                circular = True
                issues.append(f"Circular: {task_id} ↔ {blocker_id}")
                break
        if circular:
            break
    if not circular:
        checks_passed += 1

    # 10. SQLite integrity check
    integrity = db.integrity_check()
    if integrity == "ok":
        checks_passed += 1
    else:
        # Integrity failure → score 0 immediately
        return EvalCheckResult(
            id="D2",
            name="Database — Schema & Population",
            score=0,
            details=f"INTEGRITY FAILED: {integrity}",
            remediation="Run: bash db_queries.sh restore",
            auto_fixable=True,
            fix_command="bash db_queries.sh restore",
        )

    score = (checks_passed / total_checks) * 100
    remediation = "; ".join(issues) if issues else ""
    fix_cmd = None
    if not tables_ok:
        remediation = "Run schema migration to add missing tables"
        fix_cmd = "bash db_queries.sh init-db"

    return EvalCheckResult(
        id="D2",
        name="Database — Schema & Population",
        score=score,
        details=f"{checks_passed}/{total_checks} checks pass",
        remediation=remediation,
        auto_fixable=fix_cmd is not None,
        fix_command=fix_cmd,
    )


def _check_d3_infrastructure(project_dir: Path) -> EvalCheckResult:
    """D3: Infrastructure — Hooks, Agents, Rules."""
    checks_passed = 0
    total_checks = 8
    issues = []

    claude_dir = project_dir / ".claude"

    # 1. .claude/hooks/ directory exists
    hooks_dir = claude_dir / "hooks"
    if hooks_dir.is_dir():
        checks_passed += 1
    else:
        issues.append(".claude/hooks/ not found")

    # 2. At least 3 hook scripts present and executable
    hook_scripts = list(hooks_dir.glob("*.sh")) if hooks_dir.is_dir() else []
    if len(hook_scripts) >= 3:
        checks_passed += 1
    else:
        issues.append(f"Only {len(hook_scripts)} hook scripts (need >= 3)")

    # 3. settings.json exists and is valid JSON
    settings_path = claude_dir / "settings.json"
    settings = None
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            checks_passed += 1
        except (json.JSONDecodeError, OSError):
            issues.append("settings.json is invalid JSON")
    else:
        issues.append(".claude/settings.json not found")

    # 4. settings.json has hooks key with >= 3 events
    if settings and "hooks" in settings:
        hook_events = settings["hooks"]
        if isinstance(hook_events, dict) and len(hook_events) >= 3:
            checks_passed += 1
        else:
            issues.append(f"Only {len(hook_events)} hook events (need >= 3)")
    else:
        issues.append("No 'hooks' key in settings.json")

    # 5. Every hook command path resolves to a real file
    if settings and "hooks" in settings:
        all_resolve = True
        for _event, hooks in settings.get("hooks", {}).items():
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                cmd = hook.get("command", "") if isinstance(hook, dict) else ""
                if not cmd:
                    continue
                # Extract the script path (first arg or "bash <path>")
                parts = cmd.split()
                script = parts[1] if len(parts) > 1 and parts[0] == "bash" else parts[0]
                script_path = project_dir / script
                if not script_path.exists():
                    # Try relative to .claude/
                    script_path = claude_dir / script
                if not script_path.exists():
                    all_resolve = False
                    break
        if all_resolve:
            checks_passed += 1
        else:
            issues.append("Hook command path doesn't resolve")
    else:
        issues.append("Cannot check hook paths — no hooks config")

    # 6. .claude/agents/ directory exists with agent subdirectories
    agents_dir = claude_dir / "agents"
    if agents_dir.is_dir():
        checks_passed += 1
    else:
        issues.append(".claude/agents/ not found")

    # 7. Agent .md files exist and are non-empty (rglob for subdirs)
    agent_files = list(agents_dir.rglob("*.md")) if agents_dir.is_dir() else []
    if agent_files and all(f.stat().st_size > 0 for f in agent_files):
        checks_passed += 1
    else:
        issues.append("No agent .md files or some are empty")

    # 8. .claude/rules/ directory exists
    rules_dir = claude_dir / "rules"
    if rules_dir.is_dir():
        checks_passed += 1
    else:
        issues.append(".claude/rules/ not found")

    score = (checks_passed / total_checks) * 100
    return EvalCheckResult(
        id="D3",
        name="Infrastructure — Hooks, Agents, Rules",
        score=score,
        details=f"{checks_passed}/{total_checks} checks pass",
        remediation="; ".join(issues) if issues else "",
    )


def _check_d4_frameworks(project_dir: Path) -> EvalCheckResult:
    """D4: Frameworks — Presence & Import Chain."""
    checks_passed = 0
    total_checks = 4
    issues = []

    # 1. All 10 framework .md files present
    fw_dir = project_dir / "templates" / "frameworks"
    if not fw_dir.is_dir():
        # Try deployed location
        fw_dir = Path.home() / ".claude" / "frameworks"

    found_fw = 0
    for name in _EXPECTED_FRAMEWORKS:
        if (fw_dir / name).exists():
            found_fw += 1
    if found_fw == len(_EXPECTED_FRAMEWORKS):
        checks_passed += 1
    else:
        issues.append(
            f"{found_fw}/{len(_EXPECTED_FRAMEWORKS)} frameworks present"
        )

    # 2. CLAUDE.md contains @-import references
    claude_md = project_dir / "CLAUDE.md"
    claude_text = ""
    if claude_md.exists():
        claude_text = claude_md.read_text()
    imports = re.findall(r"^@(.+)$", claude_text, re.MULTILINE)
    if imports:
        checks_passed += 1
    else:
        issues.append("CLAUDE.md has no @-import references")

    # 3. Each @-import resolves to a real file (skip absolute paths outside project)
    unresolved = []
    for imp in imports:
        imp = imp.strip()
        if imp.startswith("~"):
            # Skip home-dir paths — they resolve on user's machine
            continue
        imp_path = project_dir / imp
        if not imp_path.exists():
            unresolved.append(imp)
    if not unresolved:
        checks_passed += 1
    else:
        issues.append(f"Unresolved @-imports: {unresolved[:3]}")

    # 4. RULES file contains @-import references
    rules_files = list(project_dir.glob("*RULES*.md"))
    has_rules_imports = False
    for rf in rules_files:
        text = rf.read_text()
        if re.search(r"^@", text, re.MULTILINE):
            has_rules_imports = True
            break
    if has_rules_imports or not rules_files:
        checks_passed += 1
    else:
        issues.append("RULES file has no @-import references")

    score = (checks_passed / total_checks) * 100
    return EvalCheckResult(
        id="D4",
        name="Frameworks — Presence & Import Chain",
        score=score,
        details=f"{checks_passed}/{total_checks} checks pass",
        remediation="; ".join(issues) if issues else "",
    )


def _check_d5_coherence(
    db: Database, config: ProjectConfig, project_dir: Path
) -> EvalCheckResult:
    """D5: Configuration Coherence — phases consistent across files."""
    issues = []

    # 1. Config phases match DB phases
    db_phases = sorted(
        {r["phase"] for r in db.fetch_all("SELECT DISTINCT phase FROM tasks")}
    )
    config_phases = sorted(config.phases) if config.phases else []
    phases_match = db_phases == config_phases or not config_phases

    # 2. Project name is non-empty and not a placeholder
    name_ok = bool(
        config.project_name
        and "%%" not in config.project_name
        and "PLACEHOLDER" not in config.project_name.upper()
    )

    # 3. Phase ordinals consistent (DB phases match phase_gates phases)
    if db.table_exists("phase_gates"):
        gate_phases = sorted(
            {
                r["phase"]
                for r in db.fetch_all("SELECT DISTINCT phase FROM phase_gates")
            }
        )
        gates_consistent = set(gate_phases) <= set(db_phases) or not gate_phases
    else:
        gates_consistent = True

    # 4. CLAUDE.md references correct RULES file
    claude_md = project_dir / "CLAUDE.md"
    rules_ref_ok = True
    if claude_md.exists():
        text = claude_md.read_text()
        rules_files = list(project_dir.glob("*RULES*.md"))
        if rules_files:
            rules_ref_ok = any(rf.name in text for rf in rules_files)

    all_ok = phases_match and name_ok and gates_consistent and rules_ref_ok
    if not phases_match:
        issues.append("Phase mismatch between config and DB")
    if not name_ok:
        issues.append("Project name is empty or placeholder")
    if not gates_consistent:
        issues.append("Phase gates reference unknown phases")
    if not rules_ref_ok:
        issues.append("CLAUDE.md doesn't reference RULES file")

    score = 100.0 if all_ok else 40.0
    return EvalCheckResult(
        id="D5",
        name="Configuration Coherence",
        score=score,
        details="All consistent" if all_ok else "; ".join(issues),
        remediation=(
            "Sync DBQ_PHASES in db_queries.sh with phases in tasks table"
            if not phases_match
            else "; ".join(issues) if issues else ""
        ),
    )


def _check_d6_tokens(project_dir: Path, config: ProjectConfig) -> EvalCheckResult:
    """D6: Token Efficiency — word count of key config files."""
    from ..scoring import sigmoid_penalty as _sigmoid

    files = ["CLAUDE.md", "AGENT_DELEGATION.md"]
    # Find RULES file
    rules_files = list(project_dir.glob("*RULES*.md"))
    if rules_files:
        files.append(rules_files[0].name)

    total_words = 0
    for name in files:
        p = project_dir / name
        if p.exists():
            total_words += len(p.read_text().split())

    # Archetype detection from DB phase count
    phase_count = len(config.phases) if config.phases else 0
    if phase_count <= 3:
        target = 1500
    elif phase_count <= 5:
        target = 2500
    else:
        target = 3500

    score = _sigmoid(total_words, target)
    details = f"{total_words}w (target: {target})"
    remediation = ""
    if score < 100:
        remediation = (
            f"Context files are {total_words}w vs {target}w target. "
            "Review CLAUDE.md for trimming."
        )

    return EvalCheckResult(
        id="D6",
        name="Token Efficiency",
        score=score,
        details=details,
        remediation=remediation,
    )


def _check_d7_placeholders(project_dir: Path) -> EvalCheckResult:
    """D7: Placeholder Freedom — zero %%PLACEHOLDER%% in operational files."""
    violations = []
    placeholder_re = re.compile(r"%%[A-Z_]+%%")

    for glob_pattern in _OPERATIONAL_GLOBS:
        for p in project_dir.glob(glob_pattern):
            if not p.is_file():
                continue
            # Skip templates/, specs/, tests/, skills/, refs/ etc.
            rel = str(p.relative_to(project_dir))
            skip_dirs = [
                "templates/",
                "skills/",
                "specs/",
                "backlog/",
                "design-outputs/",
                "tests/",
                "Improvement Plan/",
                "refs/",
            ]
            if any(rel.startswith(d) for d in skip_dirs):
                continue
            try:
                text = p.read_text()
            except OSError:
                continue
            matches = placeholder_re.findall(text)
            if matches:
                violations.append(f"{p.name}: {matches[:2]}")

    # Also check hooks
    hooks_dir = project_dir / ".claude" / "hooks"
    if hooks_dir.is_dir():
        for p in hooks_dir.glob("*.sh"):
            try:
                text = p.read_text()
            except OSError:
                continue
            matches = placeholder_re.findall(text)
            if matches:
                violations.append(f".claude/hooks/{p.name}: {matches[:2]}")

    # Also check settings.json
    settings = project_dir / ".claude" / "settings.json"
    if settings.exists():
        try:
            text = settings.read_text()
            matches = placeholder_re.findall(text)
            if matches:
                violations.append(f".claude/settings.json: {matches[:2]}")
        except OSError:
            pass

    score = 100.0 if not violations else 0.0
    return EvalCheckResult(
        id="D7",
        name="Placeholder Freedom",
        score=score,
        details=(
            "0 stray in operational files"
            if not violations
            else f"{len(violations)} file(s) with placeholders"
        ),
        remediation=(
            f"Replace placeholders in: {', '.join(v.split(':')[0] for v in violations[:3])}"
            if violations
            else ""
        ),
    )


def _check_d8_knowledge(
    project_dir: Path, config: ProjectConfig
) -> EvalCheckResult:
    """D8: Knowledge Scaffold — LESSONS + PROJECT_MEMORY exist & non-empty."""
    expected = 0
    non_empty = 0

    # LESSONS file
    lessons_path = (
        Path(config.lessons_file) if config.lessons_file else None
    )
    if lessons_path is None:
        candidates = list(project_dir.glob("LESSONS*.md"))
        if candidates:
            lessons_path = candidates[0]
    if lessons_path:
        expected += 1
        if lessons_path.exists() and lessons_path.stat().st_size > 50:
            non_empty += 1

    # PROJECT_MEMORY file
    memory_candidates = list(project_dir.glob("*PROJECT_MEMORY*.md"))
    if memory_candidates:
        expected += 1
        if memory_candidates[0].stat().st_size > 50:
            non_empty += 1
    else:
        expected += 1  # expected but missing

    # LEARNING_LOG.md (may be empty on fresh deploy — OK)
    learning = project_dir / "LEARNING_LOG.md"
    if learning.exists():
        expected += 1
        non_empty += 1  # existence is enough

    score = (non_empty / expected) * 100 if expected > 0 else 100.0
    return EvalCheckResult(
        id="D8",
        name="Knowledge Scaffold",
        score=score,
        details=f"{non_empty}/{expected} knowledge files present",
        remediation=(
            "Create LESSONS and/or PROJECT_MEMORY files"
            if non_empty < expected
            else ""
        ),
    )


def eval_layer1(
    db: Database, config: ProjectConfig
) -> Tuple[Optional[float], Dict[str, EvalCheckResult]]:
    """Run all Layer 1 checks (D1-D8). Returns (composite, results_dict)."""
    project_dir = config.project_dir

    results = {
        "D1": _check_d1_tools(project_dir),
        "D2": _check_d2_database(db, config),
        "D3": _check_d3_infrastructure(project_dir),
        "D4": _check_d4_frameworks(project_dir),
        "D5": _check_d5_coherence(db, config, project_dir),
        "D6": _check_d6_tokens(project_dir, config),
        "D7": _check_d7_placeholders(project_dir),
        "D8": _check_d8_knowledge(project_dir, config),
    }

    # Critical failure ceiling: D2 < 50 OR D7 = 0 → cap at 30
    d2_score = results["D2"].score or 0
    d7_score = results["D7"].score or 0

    scores = {k: r.score for k, r in results.items()}
    composite = weighted_composite(scores, L1_WEIGHTS)

    if composite is not None and (d2_score < 50 or d7_score == 0):
        composite = min(composite, 30.0)

    return composite, results


# ── Layer 2: Process Health (P1-P7) ──────────────────────────────

L2_WEIGHTS = {
    "P1": 0.18,
    "P2": 0.18,
    "P3": 0.18,
    "P4": 0.13,
    "P5": 0.13,
    "P6": 0.05,
    "P7": 0.05,
    "P8": 0.10,
}


def _check_p1_completion(db: Database) -> EvalCheckResult:
    """P1: Task Completion Rate."""
    done = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE status='DONE'", default=0
    )
    eligible = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('SKIP','WONTFIX')",
        default=0,
    )
    if eligible == 0:
        return EvalCheckResult(
            id="P1",
            name="Task Completion Rate",
            score=None,
            details="No eligible tasks",
        )

    score = (done / eligible) * 100
    return EvalCheckResult(
        id="P1",
        name="Task Completion Rate",
        score=score,
        details=f"{done}/{eligible} done",
        remediation=(
            f"Complete remaining tasks ({eligible - done} pending)"
            if score < 100
            else ""
        ),
    )


def _check_p2_defect_escape(
    db: Database, config: ProjectConfig
) -> EvalCheckResult:
    """P2: Defect Escape Distance — how far loopbacks travel."""
    rows = db.fetch_all(
        "SELECT origin_phase, discovered_in FROM tasks "
        "WHERE track='loopback' AND origin_phase IS NOT NULL "
        "AND discovered_in IS NOT NULL"
    )
    if not rows:
        return EvalCheckResult(
            id="P2",
            name="Defect Escape Distance",
            score=None,
            details="No loopback data",
        )

    distances = []
    for row in rows:
        origin_ord = config.phase_ordinal(row["origin_phase"])
        disc_ord = config.phase_ordinal(row["discovered_in"])
        distances.append(disc_ord - origin_ord)

    avg_lag = sum(distances) / len(distances) if distances else 0
    raw_score = max(0, 100 - (avg_lag * 25))
    score = score_with_confidence(raw_score, len(distances))

    return EvalCheckResult(
        id="P2",
        name="Defect Escape Distance",
        score=score,
        details=f"Avg lag: {avg_lag:.1f} phases ({len(distances)} loopbacks)",
    )


def _check_p3_rework(db: Database) -> EvalCheckResult:
    """P3: Rework Rate — loopback percentage."""
    loopbacks = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE track='loopback'", default=0
    )
    total = db.fetch_scalar("SELECT COUNT(*) FROM tasks", default=0)

    if loopbacks == 0:
        return EvalCheckResult(
            id="P3",
            name="Rework Rate",
            score=None,
            details="No loopback data",
        )

    rework_pct = (loopbacks / total) * 100 if total > 0 else 0
    score = max(0, 100 - rework_pct * 5)  # 20% rework = 0

    return EvalCheckResult(
        id="P3",
        name="Rework Rate",
        score=score,
        details=f"{loopbacks}/{total} tasks are loopbacks ({rework_pct:.0f}%)",
    )


def _check_p4_research(db: Database) -> EvalCheckResult:
    """P4: Research Discipline — researched ratio."""
    researched = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE status='DONE' AND researched=1",
        default=0,
    )
    done = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE status='DONE'", default=0
    )
    if done == 0:
        return EvalCheckResult(
            id="P4",
            name="Research Discipline",
            score=None,
            details="No completed tasks",
        )

    score = (researched / done) * 100
    return EvalCheckResult(
        id="P4",
        name="Research Discipline",
        score=score,
        details=f"{researched}/{done} researched",
        remediation=(
            "Mark completed research with: bash db_queries.sh researched <task-id>"
            if score < 100
            else ""
        ),
        auto_fixable=score < 100,
        fix_command=(
            "bash db_queries.sh researched <task-id>"
            if score < 100
            else None
        ),
    )


def _check_p5_gates(db: Database, config: ProjectConfig) -> EvalCheckResult:
    """P5: Phase Gate Discipline — gated ratio."""
    gated = db.fetch_scalar(
        "SELECT COUNT(*) FROM phase_gates WHERE gated_on IS NOT NULL",
        default=0,
    )
    total_phases = len(config.phases) if config.phases else 1

    score = (gated / total_phases) * 100
    return EvalCheckResult(
        id="P5",
        name="Phase Gate Discipline",
        score=score,
        details=f"{gated}/{total_phases} gated",
        remediation=(
            f"Record phase gate: bash db_queries.sh gate-pass <phase>"
            if score < 100
            else ""
        ),
        auto_fixable=score < 100,
        fix_command=(
            "bash db_queries.sh gate-pass <phase>"
            if score < 100
            else None
        ),
    )


def _check_p6_assumptions(db: Database) -> EvalCheckResult:
    """P6: Assumption Verification."""
    if not db.table_exists("assumptions"):
        return EvalCheckResult(
            id="P6",
            name="Assumption Verification",
            score=None,
            details="No assumptions table",
        )

    total = db.fetch_scalar(
        "SELECT COUNT(*) FROM assumptions", default=0
    )
    if total == 0:
        return EvalCheckResult(
            id="P6",
            name="Assumption Verification",
            score=None,
            details="No assumptions recorded",
            remediation=(
                "Log key assumptions with: bash db_queries.sh assume"
            ),
        )

    verified = db.fetch_scalar(
        "SELECT COUNT(*) FROM assumptions WHERE verified=1", default=0
    )
    score = (verified / total) * 100
    return EvalCheckResult(
        id="P6",
        name="Assumption Verification",
        score=score,
        details=f"{verified}/{total} verified",
    )


def _check_p7_enforcement(
    db: Database, project_dir: Path
) -> EvalCheckResult:
    """P7: Enforcement Effectiveness — hooks have evidence of activation."""
    hooks_checked = 0
    hooks_with_evidence = 0

    # correction-detector hook → lessons exist?
    hooks_checked += 1
    lessons_files = list(project_dir.glob("LESSONS*.md"))
    if lessons_files and any(f.stat().st_size > 50 for f in lessons_files):
        hooks_with_evidence += 1

    # session-start hook → phase gates recorded?
    hooks_checked += 1
    gates = db.fetch_scalar(
        "SELECT COUNT(*) FROM phase_gates WHERE gated_on IS NOT NULL",
        default=0,
    )
    if gates > 0:
        hooks_with_evidence += 1

    # delegation hook → tasks have tier assignments?
    hooks_checked += 1
    tiered = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE tier IS NOT NULL", default=0
    )
    if tiered > 0:
        hooks_with_evidence += 1

    score = (
        (hooks_with_evidence / hooks_checked) * 100
        if hooks_checked > 0
        else 100.0
    )
    return EvalCheckResult(
        id="P7",
        name="Enforcement Effectiveness",
        score=score,
        details=f"{hooks_with_evidence}/{hooks_checked} hooks have evidence",
    )


def _check_p8_escalation(db: Database) -> EvalCheckResult:
    """P8: Escalation Rate — tier accuracy at triage time."""
    escalated = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE escalation_count > 0", default=0
    )
    triaged = db.fetch_scalar(
        "SELECT COUNT(*) FROM tasks WHERE original_tier IS NOT NULL", default=0
    )
    if triaged == 0:
        return EvalCheckResult(
            id="P8",
            name="Escalation Rate",
            score=None,
            details="No triaged tasks with tier tracking",
        )
    esc_pct = (escalated / triaged) * 100
    # 0% escalation = 100 score; 25%+ = 0
    score = max(0.0, 100.0 - esc_pct * 4)
    return EvalCheckResult(
        id="P8",
        name="Escalation Rate",
        score=score,
        details=f"{escalated}/{triaged} tasks escalated ({esc_pct:.0f}%)",
    )


def eval_layer2(
    db: Database, config: ProjectConfig
) -> Tuple[Optional[float], Dict[str, EvalCheckResult]]:
    """Run all Layer 2 checks (P1-P8). Returns (composite, results_dict)."""
    project_dir = config.project_dir

    results = {
        "P1": _check_p1_completion(db),
        "P2": _check_p2_defect_escape(db, config),
        "P3": _check_p3_rework(db),
        "P4": _check_p4_research(db),
        "P5": _check_p5_gates(db, config),
        "P6": _check_p6_assumptions(db),
        "P7": _check_p7_enforcement(db, project_dir),
        "P8": _check_p8_escalation(db),
    }

    scores = {k: r.score for k, r in results.items()}
    composite = weighted_composite(scores, L2_WEIGHTS)

    return composite, results


# ── Layer 3: Improvement Velocity (V1-V4) ────────────────────────

L3_WEIGHTS = {
    "V1": 0.30,
    "V2": 0.25,
    "V3": 0.25,
    "V4": 0.20,
}

LAYER_WEIGHTS = {"L1": 0.45, "L2": 0.35, "L3": 0.20}


def _check_v1_composite_trend(db: Database) -> EvalCheckResult:
    """V1: Composite Trend — compare with previous eval."""
    prev = db.fetch_one(
        "SELECT composite_score FROM evaluations "
        "ORDER BY evaluated_at DESC LIMIT 1",
        default=None,
    )
    if prev is None:
        return EvalCheckResult(
            id="V1",
            name="Composite Trend",
            score=None,
            details="First evaluation",
        )

    # Will be filled after composite is known (deferred scoring)
    return EvalCheckResult(
        id="V1",
        name="Composite Trend",
        score=None,  # placeholder — filled by eval_layer3
        details=f"Previous composite: {prev:.1f}",
    )


def _check_v2_lesson_capture(config: ProjectConfig) -> EvalCheckResult:
    """V2: Lesson Capture Rate — count structured entries in LESSONS file."""
    lessons_path = (
        Path(config.lessons_file) if config.lessons_file else None
    )
    if lessons_path is None:
        candidates = list(config.project_dir.glob("LESSONS*.md"))
        if candidates:
            lessons_path = candidates[0]

    if not lessons_path or not lessons_path.exists():
        return EvalCheckResult(
            id="V2",
            name="Lesson Capture Rate",
            score=None,
            details="No LESSONS file found",
        )

    text = lessons_path.read_text()
    # Count markdown table rows (lines starting with |, minus header rows)
    table_rows = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") and "---" not in line
    ]
    # Subtract 1 for the header row
    entry_count = max(0, len(table_rows) - 1)

    score = min(entry_count * 15, 100)  # 7+ lessons = perfect
    return EvalCheckResult(
        id="V2",
        name="Lesson Capture Rate",
        score=float(score),
        details=f"{entry_count} lessons logged",
        remediation=(
            "Use: bash db_queries.sh log-lesson after corrections"
            if score < 100
            else ""
        ),
    )


def _check_v3_defect_trend(db: Database) -> EvalCheckResult:
    """V3: Defect Escape Trend — compare P2 with previous eval."""
    prev_details = db.fetch_one(
        "SELECT process_details FROM evaluations "
        "ORDER BY evaluated_at DESC LIMIT 1",
        default=None,
    )
    if prev_details is None:
        return EvalCheckResult(
            id="V3",
            name="Defect Escape Trend",
            score=None,
            details="First evaluation",
        )

    # Parse previous P2 score from stored JSON
    try:
        details = json.loads(prev_details)
        prev_p2 = details.get("P2", {}).get("score")
    except (json.JSONDecodeError, TypeError, AttributeError):
        prev_p2 = None

    if prev_p2 is None:
        return EvalCheckResult(
            id="V3",
            name="Defect Escape Trend",
            score=None,
            details="No previous P2 data",
        )

    # Will be filled after current P2 is known
    return EvalCheckResult(
        id="V3",
        name="Defect Escape Trend",
        score=None,  # placeholder
        details=f"Previous P2: {prev_p2:.1f}",
    )


def _check_v4_snapshot_trend(db: Database) -> EvalCheckResult:
    """V4: Snapshot Health Trend — compare across db_snapshots."""
    if not db.table_exists("db_snapshots"):
        return EvalCheckResult(
            id="V4",
            name="Snapshot Health Trend",
            score=None,
            details="No snapshots table",
        )

    snapshots = db.fetch_all(
        "SELECT task_count, stats FROM db_snapshots "
        "ORDER BY created_at DESC LIMIT 5"
    )
    if len(snapshots) < 2:
        return EvalCheckResult(
            id="V4",
            name="Snapshot Health Trend",
            score=None,
            details=f"Insufficient data ({len(snapshots)} snapshot(s))",
        )

    # Compare most recent vs previous
    recent = snapshots[0]
    previous = snapshots[1]

    # Handle NULL task_count — fall back to stats JSON
    def _get_count(snap):
        if snap["task_count"] is not None:
            return snap["task_count"]
        if snap["stats"]:
            try:
                stats = json.loads(snap["stats"])
                return stats.get("total", 0)
            except (json.JSONDecodeError, TypeError):
                pass
        return 0

    recent_count = _get_count(recent)
    prev_count = _get_count(previous)

    # Score: 50 (neutral) + improvement indicators
    score = 50.0
    if recent_count > prev_count:
        score += 20  # more tasks = project is active
    if recent_count == prev_count:
        score += 10  # stable

    # Check if stats show improvement
    try:
        recent_stats = json.loads(recent["stats"]) if recent["stats"] else {}
        prev_stats = json.loads(previous["stats"]) if previous["stats"] else {}
        recent_done = recent_stats.get("done", 0)
        prev_done = prev_stats.get("done", 0)
        if recent_done > prev_done:
            score += 20
    except (json.JSONDecodeError, TypeError):
        pass

    score = min(100.0, score)

    return EvalCheckResult(
        id="V4",
        name="Snapshot Health Trend",
        score=score,
        details=f"Tasks: {prev_count} → {recent_count}",
    )


def eval_layer3(
    db: Database,
    config: ProjectConfig,
    current_composite: Optional[float] = None,
    current_p2: Optional[float] = None,
) -> Tuple[Optional[float], Dict[str, EvalCheckResult]]:
    """Run all Layer 3 checks (V1-V4). Returns (composite, results_dict).

    Args:
        current_composite: Overall composite from L1+L2 (for V1 trend).
        current_p2: Current P2 score (for V3 trend).
    """
    results = {
        "V1": _check_v1_composite_trend(db),
        "V2": _check_v2_lesson_capture(config),
        "V3": _check_v3_defect_trend(db),
        "V4": _check_v4_snapshot_trend(db),
    }

    # Resolve deferred V1 score if we have previous + current data
    if results["V1"].score is None and "Previous composite" in results["V1"].details:
        prev_str = results["V1"].details.split(": ")[1]
        try:
            prev_composite = float(prev_str)
            if current_composite is not None:
                delta = current_composite - prev_composite
                v1_score = max(0, min(100, 50 + (delta * 5)))
                results["V1"] = EvalCheckResult(
                    id="V1",
                    name="Composite Trend",
                    score=v1_score,
                    details=f"{prev_composite:.1f} → {current_composite:.1f} ({delta:+.1f})",
                )
        except ValueError:
            pass

    # Resolve deferred V3 score
    if results["V3"].score is None and "Previous P2" in results["V3"].details:
        prev_str = results["V3"].details.split(": ")[1]
        try:
            prev_p2 = float(prev_str)
            if current_p2 is not None:
                delta = current_p2 - prev_p2
                v3_score = max(0, min(100, 50 + (delta * 3)))
                results["V3"] = EvalCheckResult(
                    id="V3",
                    name="Defect Escape Trend",
                    score=v3_score,
                    details=f"{prev_p2:.1f} → {current_p2:.1f} ({delta:+.1f})",
                )
        except ValueError:
            pass

    scores = {k: r.score for k, r in results.items()}
    composite = weighted_composite(scores, L3_WEIGHTS)

    return composite, results


# ── Public command functions ──────────────────────────────────────


def cmd_eval(
    db: Database,
    config: ProjectConfig,
    version: Optional[str] = None,
    json_output: bool = False,
    layer: Optional[str] = None,
    auto_fix: bool = False,
    auto_fix_yes: bool = False,
    no_store: bool = False,
):
    """Run full 3-layer evaluation, store result, print scorecard."""
    from .. import output
    from ..remediation import get_recommendations

    # Ensure evaluations table exists
    db.execute(
        "CREATE TABLE IF NOT EXISTS evaluations ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  version TEXT, phase TEXT,"
        "  artifact_score REAL, artifact_details TEXT,"
        "  process_score REAL, process_details TEXT,"
        "  velocity_score REAL, velocity_details TEXT,"
        "  composite_score REAL, raw_metrics TEXT,"
        "  evaluated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )

    # Detect current phase
    phase = db.fetch_one(
        "SELECT DISTINCT phase FROM tasks "
        "WHERE status NOT IN ('DONE','SKIP') "
        "ORDER BY phase LIMIT 1",
        default="complete",
    )

    # Run layers
    all_results: Dict[str, EvalCheckResult] = {}

    l1_score, l1_results = eval_layer1(db, config)
    all_results.update(l1_results)

    l2_score, l2_results = eval_layer2(db, config)
    all_results.update(l2_results)

    # L3 needs L1+L2 composites for trend calculation
    # Compute preliminary composite for V1
    prelim_scores = {"L1": l1_score, "L2": l2_score, "L3": None}
    prelim_composite = weighted_composite(prelim_scores, LAYER_WEIGHTS)

    current_p2 = l2_results.get("P2", EvalCheckResult(id="P2", name="", score=None)).score

    l3_score, l3_results = eval_layer3(
        db, config,
        current_composite=prelim_composite,
        current_p2=current_p2,
    )
    all_results.update(l3_results)

    # Overall composite
    layer_scores = {"L1": l1_score, "L2": l2_score, "L3": l3_score}
    composite = weighted_composite(layer_scores, LAYER_WEIGHTS)

    # Get recommendations
    flat_scores = {k: r.score for k, r in all_results.items()}
    recommendations = get_recommendations(flat_scores)

    # Store in DB (unless --no-store)
    eval_id = None
    if not no_store:
        artifact_details = json.dumps(
            {k: r.to_dict() for k, r in l1_results.items()}
        )
        process_details = json.dumps(
            {k: r.to_dict() for k, r in l2_results.items()}
        )
        velocity_details = json.dumps(
            {k: r.to_dict() for k, r in l3_results.items()}
        )
        raw_metrics = json.dumps(flat_scores)

        db.execute(
            "INSERT INTO evaluations "
            "(version, phase, artifact_score, artifact_details, "
            " process_score, process_details, "
            " velocity_score, velocity_details, "
            " composite_score, raw_metrics) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version,
                phase if isinstance(phase, str) else str(phase),
                l1_score,
                artifact_details,
                l2_score,
                process_details,
                l3_score,
                velocity_details,
                composite,
                raw_metrics,
            ),
        )
        db.commit()

        eval_id = db.fetch_one(
            "SELECT id FROM evaluations ORDER BY id DESC LIMIT 1", default=0
        )

    # Auto-escalate template-related issues to bootstrap backlog
    _auto_escalate(config, all_results, recommendations)

    # Output
    if json_output:
        result = {
            "id": eval_id,
            "version": version,
            "phase": phase if isinstance(phase, str) else str(phase),
            "layers": {
                "L1": {
                    "score": l1_score,
                    "checks": {k: r.to_dict() for k, r in l1_results.items()},
                },
                "L2": {
                    "score": l2_score,
                    "checks": {k: r.to_dict() for k, r in l2_results.items()},
                },
                "L3": {
                    "score": l3_score,
                    "checks": {k: r.to_dict() for k, r in l3_results.items()},
                },
            },
            "composite": composite,
            "recommendations": [
                {
                    "priority": r.priority,
                    "category": r.category,
                    "message": r.message,
                    "trigger": r.trigger,
                }
                for r in recommendations
            ],
        }
        print(json.dumps(result, indent=2))
    else:
        output.eval_scorecard(
            project_name=config.project_name or "Project",
            version=version,
            phase=phase if isinstance(phase, str) else str(phase),
            l1_score=l1_score,
            l1_results=l1_results,
            l2_score=l2_score,
            l2_results=l2_results,
            l3_score=l3_score,
            l3_results=l3_results,
            composite=composite,
            recommendations=recommendations,
        )

    # Auto-fix handling
    if auto_fix:
        fixable = [
            r
            for r in all_results.values()
            if r.auto_fixable and r.fix_command and (r.score or 0) < 100
        ]
        if not fixable:
            print("\n  No auto-fixable issues found.")
        else:
            print(f"\n  {len(fixable)} auto-fixable issue(s):")
            for r in fixable:
                print(f"    [{r.id}] {r.fix_command}")
            if not auto_fix_yes:
                print("  Re-run with --auto-fix --yes to execute.")


def cmd_eval_report(
    db: Database,
    config: ProjectConfig,
    eval_id: Optional[int] = None,
    show_all: bool = False,
):
    """Show evaluation report."""
    from .. import output

    if show_all:
        rows = db.fetch_all(
            "SELECT id, version, phase, composite_score, evaluated_at "
            "FROM evaluations ORDER BY evaluated_at DESC"
        )
        if not rows:
            print("  No evaluations stored.")
            return
        print("")
        print(output.section_header("All Evaluations"))
        print(f"  {'ID':>4}  {'Version':<10} {'Phase':<15} {'Score':>6}  {'Date':<20}")
        print(f"  {'─' * 4}  {'─' * 10} {'─' * 15} {'─' * 6}  {'─' * 20}")
        for row in rows:
            score = row["composite_score"]
            score_str = f"{score:.1f}" if score is not None else "—"
            print(
                f"  {row['id']:>4}  {(row['version'] or '—'):<10} "
                f"{(row['phase'] or '—'):<15} {score_str:>6}  "
                f"{row['evaluated_at']}"
            )
        print("")
        return

    # Single eval
    if eval_id is None:
        row = db.fetch_all(
            "SELECT * FROM evaluations ORDER BY evaluated_at DESC LIMIT 1"
        )
    else:
        row = db.fetch_all(
            "SELECT * FROM evaluations WHERE id = ?", (eval_id,)
        )

    if not row:
        print("  No evaluation found.")
        return

    row = row[0]
    print("")
    print(output.section_header(f"Evaluation #{row['id']}"))
    print(f"  Version: {row['version'] or '—'}")
    print(f"  Phase: {row['phase'] or '—'}")
    print(f"  Date: {row['evaluated_at']}")
    print("")
    print(f"  Deployment Quality:   {_fmt_score(row['artifact_score'])}")
    print(f"  Process Health:       {_fmt_score(row['process_score'])}")
    print(f"  Improvement Velocity: {_fmt_score(row['velocity_score'])}")
    print(f"  ─────────────────────────────")
    print(f"  COMPOSITE:            {_fmt_score(row['composite_score'])}")
    print("")


def cmd_eval_compare(
    db: Database,
    config: ProjectConfig,
    id1: Optional[int] = None,
    id2: Optional[int] = None,
    last_n: Optional[int] = None,
):
    """Compare two evaluations."""
    from .. import output

    if last_n:
        rows = db.fetch_all(
            "SELECT * FROM evaluations ORDER BY evaluated_at DESC LIMIT ?",
            (last_n,),
        )
        if len(rows) < 2:
            print("  Need at least 2 evaluations to compare.")
            return
        eval2, eval1 = rows[0], rows[1]  # newer is second
    elif id1 is not None and id2 is not None:
        r1 = db.fetch_all("SELECT * FROM evaluations WHERE id = ?", (id1,))
        r2 = db.fetch_all("SELECT * FROM evaluations WHERE id = ?", (id2,))
        if not r1 or not r2:
            print("  Evaluation ID not found.")
            return
        eval1, eval2 = r1[0], r2[0]
    else:
        print("  Usage: eval-compare ID1 ID2  or  eval-compare --last 2")
        return

    output.eval_comparison(eval1, eval2)


def cmd_eval_last(
    db: Database,
    config: ProjectConfig,
    json_output: bool = False,
):
    """Read the last stored evaluation without re-running. Fast, no side effects."""
    row = db.fetch_all(
        "SELECT * FROM evaluations ORDER BY evaluated_at DESC LIMIT 1"
    )
    if not row:
        if json_output:
            print(json.dumps({"error": "no evaluations stored"}))
        else:
            print("  No evaluations stored. Run: bash db_queries.sh eval")
        return

    row = row[0]
    if json_output:
        result = {
            "id": row["id"],
            "version": row["version"],
            "phase": row["phase"],
            "artifact_score": row["artifact_score"],
            "process_score": row["process_score"],
            "velocity_score": row["velocity_score"],
            "composite": row["composite_score"],
            "evaluated_at": row["evaluated_at"],
        }
        print(json.dumps(result, indent=2))
    else:
        from .. import output
        print("")
        print(output.section_header(f"Last Evaluation (#{row['id']})"))
        print(f"  Date: {row['evaluated_at']}")
        print(f"  Version: {row['version'] or '—'}")
        print(f"  Phase: {row['phase'] or '—'}")
        print("")
        print(f"  Deployment Quality:   {_fmt_score(row['artifact_score'])}")
        print(f"  Process Health:       {_fmt_score(row['process_score'])}")
        print(f"  Improvement Velocity: {_fmt_score(row['velocity_score'])}")
        print(f"  ─────────────────────────────")
        print(f"  COMPOSITE:            {_fmt_score(row['composite_score'])}")
        print("")


# ── Auto-escalation ──────────────────────────────────────────────

# Checks whose low scores indicate template/framework problems (not project-local)
_TEMPLATE_CHECKS = {
    "D1": "template",    # Missing scripts = template didn't deploy them
    "D3": "template",    # Infrastructure gaps = template hooks/agents missing
    "D4": "framework",   # Framework gaps = framework files missing
    "D6": "template",    # Token bloat = template CLAUDE.md too large
    "D7": "template",    # Stray placeholders = fill_placeholders incomplete
}

_ESCALATION_THRESHOLD = 75  # Only escalate checks scoring below this


def _auto_escalate(
    config: ProjectConfig,
    all_results: Dict[str, "EvalCheckResult"],
    recommendations: list,
) -> int:
    """Auto-escalate template/framework issues to bootstrap backlog.

    Only fires for checks mapped in _TEMPLATE_CHECKS that score below
    the threshold. Writes BP-NNN entries to BOOTSTRAP_BACKLOG.md.

    Returns number of escalations written.
    """
    backlog_path = Path(config.project_dir) / "backlog" / "BOOTSTRAP_BACKLOG.md"
    if not backlog_path.parent.exists():
        return 0

    escalations = []
    for check_id, category in _TEMPLATE_CHECKS.items():
        result = all_results.get(check_id)
        if result is None:
            continue
        if result.score is not None and result.score < _ESCALATION_THRESHOLD:
            escalations.append((check_id, category, result))

    if not escalations:
        return 0

    # Read existing backlog to generate next BP-NNN ID
    existing_ids = []
    if backlog_path.exists():
        import re as _re
        content = backlog_path.read_text()
        existing_ids = [
            int(m) for m in _re.findall(r"BP-(\d+)", content)
        ]
    else:
        content = "# Bootstrap Backlog\n\n"

    next_id = max(existing_ids, default=0) + 1
    project_name = config.project_name or "unknown"
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    new_entries = []
    for check_id, category, result in escalations:
        bp_id = f"BP-{next_id:03d}"
        next_id += 1

        entry = (
            f"\n### {bp_id} [{category}] "
            f"Eval auto-escalation: {check_id} scored {result.score:.0f}/100\n"
            f"- **Escalated:** {today}\n"
            f"- **Source:** {project_name} (auto-eval)\n"
            f"- **Priority:** P2\n"
            f"- **Check:** {check_id} — {result.name}\n"
            f"- **Details:** {result.details}\n"
            f"- **Remediation:** {result.remediation or 'Review needed'}\n"
            f"- **Status:** pending\n"
        )
        new_entries.append(entry)
        print(
            f"  📤 Auto-escalated {check_id} ({result.score:.0f}/100) → {bp_id}",
            file=sys.stderr,
        )

    # Append to backlog
    with open(backlog_path, "a") as f:
        for entry in new_entries:
            f.write(entry)

    return len(new_entries)


def cmd_eval_gate(
    db: Database,
    config: ProjectConfig,
    min_score: int = 70,
    max_age: int = 7,
    bootstrap_min: int = 85,
):
    """P4-VALIDATE gate: verify all projects meet eval thresholds.

    Reads PROJECTS.md for active projects, checks each project's last
    stored eval for score and freshness. Returns exit code 0 (pass) or 1 (fail).
    """
    from datetime import datetime

    project_root = Path(config.db_path).parent
    projects_file = project_root / "PROJECTS.md"

    print("")
    print("══ P4-VALIDATE EVAL GATE ═══════════════════════════════════")
    print(f"   Thresholds: projects ≥ {min_score}, bootstrap ≥ {bootstrap_min}, "
          f"freshness ≤ {max_age}d")
    print("")

    failures = []
    checked = 0

    # Check bootstrap itself (use current DB)
    row = db.fetch_all(
        "SELECT composite_score, evaluated_at FROM evaluations "
        "ORDER BY evaluated_at DESC LIMIT 1"
    )
    if not row:
        failures.append(("Bootstrap", "no evaluation stored", "Run: bash db_queries.sh eval"))
    else:
        score = row[0]["composite_score"]
        ts = row[0]["evaluated_at"]
        age = (datetime.now() - datetime.fromisoformat(ts)).days if ts else 999
        score_str = f"{score:.0f}" if score is not None else "—"
        age_str = f"{age}d"

        icon = "✅" if (score or 0) >= bootstrap_min and age <= max_age else "❌"
        print(f"  {icon} Bootstrap: {score_str}/100 ({age_str} old)")
        checked += 1

        if score is not None and score < bootstrap_min:
            failures.append(("Bootstrap", f"score {score:.0f} < {bootstrap_min}", "Run: bash db_queries.sh eval --auto-fix"))
        if age > max_age:
            failures.append(("Bootstrap", f"eval is {age}d old (max {max_age}d)", "Run: bash db_queries.sh eval"))

    # Check other projects from PROJECTS.md
    if projects_file.exists():
        import sqlite3

        for line in projects_file.read_text().splitlines():
            if not line.startswith("|") or "---" in line or "Project" in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5:
                continue
            name, path_str, status = parts[1], parts[2], parts[3]
            if status != "active":
                continue

            expanded = Path(path_str.replace("~", str(Path.home())))
            db_path = expanded / "bootstrap.db"
            if not expanded.is_dir():
                print(f"  ⚠️  {name}: directory not found")
                continue
            if not db_path.exists():
                # Try project.db as fallback
                db_path = expanded / "project.db"
                if not db_path.exists():
                    print(f"  ⚠️  {name}: no database found")
                    continue

            try:
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT composite_score, evaluated_at FROM evaluations "
                    "ORDER BY evaluated_at DESC LIMIT 1"
                )
                proj_row = cursor.fetchone()
                conn.close()

                if not proj_row:
                    print(f"  ⚠️  {name}: no evaluation stored")
                    failures.append((name, "no evaluation stored", f"cd {path_str} && bash db_queries.sh eval"))
                    continue

                score = proj_row["composite_score"]
                ts = proj_row["evaluated_at"]
                age = (datetime.now() - datetime.fromisoformat(ts)).days if ts else 999
                score_str = f"{score:.0f}" if score is not None else "—"
                age_str = f"{age}d"

                passed = (score is None or score >= min_score) and age <= max_age
                icon = "✅" if passed else "❌"
                print(f"  {icon} {name}: {score_str}/100 ({age_str} old)")
                checked += 1

                if score is not None and score < min_score:
                    failures.append((name, f"score {score:.0f} < {min_score}", f"cd {path_str} && bash db_queries.sh eval --auto-fix"))
                if age > max_age:
                    failures.append((name, f"eval is {age}d old (max {max_age}d)", f"cd {path_str} && bash db_queries.sh eval"))

            except (sqlite3.Error, Exception) as e:
                print(f"  ⚠️  {name}: DB error — {e}")
                continue

    print("")

    if failures:
        print(f"  ❌ GATE FAILED — {len(failures)} issue(s):")
        for name, reason, fix in failures:
            print(f"    • {name}: {reason}")
            print(f"      Fix: {fix}")
        print("")
        print("══════════════════════════════════════════════════════════════")
        sys.exit(1)
    else:
        print(f"  ✅ GATE PASSED — {checked} project(s) checked, all healthy")
        print("")
        print("══════════════════════════════════════════════════════════════")


def _fmt_score(score) -> str:
    """Format a score for display."""
    if score is None:
        return "  —"
    return f"{score:5.1f}/100"
