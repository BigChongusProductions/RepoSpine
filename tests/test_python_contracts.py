#!/usr/bin/env python3
# NOTE: This file is private-only — not included in the public repo (Phase 10 exclusion list).
"""Contract tests for session_briefing.py, save_session.py, and preflight_check.py.

Tests use isolated in-memory SQLite fixtures to verify signal computation,
NEXT_SESSION.md generation, and preflight handoff contracts deterministically.

Run via:
    python3 tests/test_python_contracts.py
    bash tests/test_bootstrap_suite.sh --python-contract  (includes these)
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — import the scripts under test from templates/scripts/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "templates" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from session_briefing import compute_signal  # noqa: E402
from save_session import generate_next_session_md  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture helpers — create minimal DBs with known states
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'TODO',
    priority TEXT DEFAULT 'P2',
    assignee TEXT NOT NULL DEFAULT 'CLAUDE',
    blocked_by TEXT,
    sort_order INTEGER DEFAULT 999,
    queue TEXT NOT NULL DEFAULT 'BACKLOG',
    tier TEXT,
    skill TEXT,
    needs_browser INTEGER DEFAULT 0,
    track TEXT DEFAULT 'forward',
    origin_phase TEXT,
    discovered_in TEXT,
    severity INTEGER DEFAULT 3,
    gate_critical INTEGER DEFAULT 0,
    loopback_reason TEXT,
    details TEXT,
    completed_on TEXT,
    researched INTEGER DEFAULT 0,
    breakage_tested INTEGER DEFAULT 0,
    notes TEXT,
    research_notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    files_touched TEXT,
    handover_notes TEXT,
    original_tier TEXT,
    escalation_reason TEXT,
    escalation_count INTEGER DEFAULT 0,
    sort_key TEXT
);
CREATE TABLE phase_gates (
    phase TEXT PRIMARY KEY,
    gated_on TEXT,
    gated_by TEXT DEFAULT 'MASTER',
    notes TEXT
);
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_type TEXT DEFAULT 'Claude Code',
    summary TEXT,
    logged_at TEXT DEFAULT (datetime('now'))
);
"""


def _create_db(tasks: list[dict], gates: list[tuple] | None = None) -> str:
    """Create a temp SQLite DB with the given tasks and gates.

    Each task dict must have at least: id, phase, title, status.
    Optional: blocked_by, tier, assignee, queue, track, severity, gate_critical, sort_key.

    Returns the path to the temp DB file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(_SCHEMA)

    for t in tasks:
        conn.execute(
            """INSERT INTO tasks (id, phase, title, status, blocked_by, tier,
               assignee, queue, track, severity, gate_critical, sort_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                t["id"],
                t["phase"],
                t["title"],
                t.get("status", "TODO"),
                t.get("blocked_by"),
                t.get("tier"),
                t.get("assignee", "CLAUDE"),
                t.get("queue", "BACKLOG"),
                t.get("track", "forward"),
                t.get("severity", 3),
                t.get("gate_critical", 0),
                t.get("sort_key", t["id"]),
            ),
        )

    for phase in {t["phase"] for t in tasks}:
        gate = None
        if gates:
            matching = [g for g in gates if g[0] == phase]
            if matching:
                gate = matching[0][1]  # gated_on timestamp
        conn.execute(
            "INSERT OR IGNORE INTO phase_gates (phase, gated_on) VALUES (?, ?)",
            (phase, gate),
        )

    conn.commit()
    conn.close()
    return tmp.name


# ============================================================================
# Contract tests: session_briefing.py — compute_signal()
# ============================================================================


def test_signal_required_keys():
    """compute_signal() output must contain signal, reasons, stats, next_task."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Test task", "status": "TODO"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    assert isinstance(result, dict), "result must be a dict"
    for key in ("signal", "reasons", "stats", "next_task"):
        assert key in result, f"missing required key: {key}"


def test_signal_enum_values():
    """signal must be one of GREEN, YELLOW, RED."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Test task", "status": "TODO"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] in ("GREEN", "YELLOW", "RED"), \
        f"invalid signal: {result['signal']}"


def test_stats_integer_fields():
    """stats.total/done/ready/blocked/active must all be ints."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Test task", "status": "TODO"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    stats = result["stats"]
    for field in ("total", "done", "ready", "blocked", "active"):
        assert field in stats, f"missing stats.{field}"
        assert isinstance(stats[field], int), f"stats.{field} must be int, got {type(stats[field])}"


def test_green_all_done():
    """Signal is GREEN when all tasks are DONE and gates passed."""
    db = _create_db(
        [
            {"id": "T-001", "phase": "P1", "title": "Task 1", "status": "DONE"},
            {"id": "T-002", "phase": "P1", "title": "Task 2", "status": "DONE"},
        ],
        gates=[("P1", "2026-01-01")],
    )
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] == "GREEN", f"expected GREEN, got {result['signal']}: {result['reasons']}"
    assert result["reasons"] == [], f"expected no reasons, got {result['reasons']}"


def test_green_single_phase_ready():
    """Signal is GREEN when one phase has a ready task and gate is not needed."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Ready task", "status": "TODO"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] == "GREEN", f"expected GREEN, got {result['signal']}: {result['reasons']}"


def test_red_prior_phase_incomplete():
    """Signal is RED when prior phase has incomplete forward tasks.

    The next-task query excludes master-tier tasks, so a master task in P1
    makes P2's Claude task the 'next' — triggering the prior-phase check.
    """
    db = _create_db(
        [
            {"id": "T-001", "phase": "P1", "title": "Incomplete P1 (master)",
             "status": "TODO", "tier": "master", "assignee": "MASTER"},
            {"id": "T-002", "phase": "P2", "title": "P2 Claude task", "status": "TODO"},
        ],
        gates=[("P1", None)],  # P1 not gated
    )
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] == "RED", f"expected RED, got {result['signal']}: {result['reasons']}"
    assert any("incomplete" in r.lower() or "prior" in r.lower() or "gate" in r.lower()
               for r in result["reasons"]), \
        f"expected reason about prior phase, got {result['reasons']}"


def test_red_gate_not_passed():
    """Signal is RED when prior phase gate has not been passed."""
    db = _create_db(
        [
            {"id": "T-001", "phase": "P1", "title": "P1 done", "status": "DONE"},
            {"id": "T-002", "phase": "P2", "title": "P2 task", "status": "TODO"},
        ],
        gates=[("P1", None)],  # P1 completed but not gated
    )
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] == "RED", f"expected RED, got {result['signal']}: {result['reasons']}"
    assert any("gate" in r.lower() for r in result["reasons"]), \
        f"expected reason about gate, got {result['reasons']}"


def test_green_gate_passed():
    """Signal is GREEN when prior phase gate has been passed."""
    db = _create_db(
        [
            {"id": "T-001", "phase": "P1", "title": "P1 done", "status": "DONE"},
            {"id": "T-002", "phase": "P2", "title": "P2 task", "status": "TODO"},
        ],
        gates=[("P1", "2026-01-01")],  # P1 gated
    )
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] == "GREEN", f"expected GREEN, got {result['signal']}: {result['reasons']}"


def test_yellow_master_blockers_with_unblocked():
    """Signal is YELLOW when Master blockers exist but unblocked Claude tasks available."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Master task", "status": "TODO",
         "assignee": "MASTER", "tier": "master"},
        {"id": "T-002", "phase": "P1", "title": "Claude blocked", "status": "TODO",
         "blocked_by": "T-001"},
        {"id": "T-003", "phase": "P1", "title": "Claude unblocked", "status": "TODO"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] == "YELLOW", f"expected YELLOW, got {result['signal']}: {result['reasons']}"
    assert any("master" in r.lower() or "gemini" in r.lower() for r in result["reasons"]), \
        f"expected reason about Master blockers, got {result['reasons']}"


def test_red_all_claude_blocked():
    """Signal is RED when all Claude tasks are blocked by Master."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Master task", "status": "TODO",
         "assignee": "MASTER", "tier": "master"},
        {"id": "T-002", "phase": "P1", "title": "Claude blocked", "status": "TODO",
         "blocked_by": "T-001"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    assert result["signal"] == "RED", f"expected RED, got {result['signal']}: {result['reasons']}"
    assert any("all claude" in r.lower() for r in result["reasons"]), \
        f"expected reason about all blocked, got {result['reasons']}"


def test_red_db_not_found():
    """Signal is RED when DB path doesn't exist."""
    result = compute_signal("/nonexistent/path/to.db")

    assert result["signal"] == "RED"
    assert len(result["reasons"]) > 0


def test_next_task_populated():
    """next_task is populated when ready tasks exist."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "First ready", "status": "TODO"},
        {"id": "T-002", "phase": "P1", "title": "Second ready", "status": "TODO"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    nt = result["next_task"]
    assert nt is not None, "next_task should not be None when ready tasks exist"
    assert nt["id"] == "T-001"
    assert nt["phase"] == "P1"
    assert "title" in nt


def test_next_task_none_when_all_done():
    """next_task is None when all tasks are done."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Done task", "status": "DONE"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    assert result["next_task"] is None


def test_stats_counts_accurate():
    """Stats counters match the actual task states in the DB."""
    db = _create_db([
        {"id": "T-001", "phase": "P1", "title": "Done", "status": "DONE"},
        {"id": "T-002", "phase": "P1", "title": "Ready", "status": "TODO"},
        {"id": "T-003", "phase": "P1", "title": "Blocked", "status": "TODO",
         "blocked_by": "T-002"},
        {"id": "T-004", "phase": "P1", "title": "Active", "status": "IN_PROGRESS"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    s = result["stats"]
    assert s["total"] == 4, f"expected total=4, got {s['total']}"
    assert s["done"] == 1, f"expected done=1, got {s['done']}"
    assert s["active"] == 1, f"expected active=1, got {s['active']}"
    # T-002 ready, T-004 in-progress counts as not-done not-blocked
    assert s["ready"] >= 1, f"expected ready>=1, got {s['ready']}"
    assert s["blocked"] >= 1, f"expected blocked>=1, got {s['blocked']}"


def test_inbox_tasks_excluded():
    """INBOX tasks are excluded from next_task and signal computation."""
    db = _create_db([
        {"id": "QK-001", "phase": "P1", "title": "Inbox task", "status": "TODO",
         "queue": "INBOX"},
        {"id": "T-001", "phase": "P1", "title": "Real task", "status": "DONE"},
    ])
    result = compute_signal(db)
    Path(db).unlink()

    # next_task should not pick up INBOX items
    assert result["next_task"] is None, \
        f"INBOX task should not appear as next_task, got {result['next_task']}"


# ============================================================================
# Contract tests: save_session.py — generate_next_session_md()
# ============================================================================


def _make_state(**overrides) -> dict:
    """Build a minimal state dict for generate_next_session_md()."""
    state = {
        "signal": "GREEN",
        "reasons": [],
        "stats": {"total": 10, "done": 8, "ready": 1, "blocked": 1, "active": 0},
        "next_task": {"id": "T-009", "phase": "P4", "title": "Next task", "blocked_by": None},
        "current_phase": "P4-VALIDATE",
        "gates_passed": "P1, P2, P3",
        "master_pending": 0,
        "next_3": [{"id": "T-009", "title": "Next task"}],
        "next_task_files": "",
        "next_task_handover": "",
        "git": {"branch": "main", "uncommitted": 0, "completed_this_session": []},
        "eval": None,
        "version": "0.7.0",
        "date": "2026-04-10",
    }
    state.update(overrides)
    return state


def test_nextsession_required_sections():
    """NEXT_SESSION.md must have header, signal, last session, pick up, context."""
    state = _make_state()
    md = generate_next_session_md(state, "TestProject", "Did stuff")

    assert md.startswith("# Next Session"), "must start with # Next Session header"
    assert "Signal:" in md, "must contain Signal: line"
    assert "## Last session" in md, "must contain ## Last session section"
    assert "## Pick up" in md, "must contain ## Pick up section"
    assert "## Context" in md, "must contain ## Context section"


def test_nextsession_project_name_in_header():
    """Project name appears in the NEXT_SESSION.md header."""
    state = _make_state()
    md = generate_next_session_md(state, "MyProject", "summary")

    assert "# Next Session — MyProject" in md


def test_nextsession_summary_in_body():
    """Session summary appears in the Last session section."""
    state = _make_state()
    md = generate_next_session_md(state, "Proj", "Implemented V1-042 and V1-043")

    assert "Implemented V1-042 and V1-043" in md


def test_nextsession_tasks_in_pickup():
    """Next tasks appear in the Pick up section."""
    state = _make_state(next_3=[
        {"id": "T-009", "title": "First task"},
        {"id": "T-010", "title": "Second task"},
    ])
    md = generate_next_session_md(state, "Proj", "summary")

    assert "T-009" in md
    assert "T-010" in md


def test_nextsession_signal_in_header_line():
    """Signal value and date appear in the signal line."""
    state = _make_state(signal="YELLOW", date="2026-04-10")
    md = generate_next_session_md(state, "Proj", "summary")

    assert "YELLOW" in md
    assert "2026-04-10" in md


def test_nextsession_compact_when_green():
    """GREEN/no-warnings output should be under 20 lines (contract from feedback)."""
    state = _make_state(signal="GREEN", reasons=[], eval=None)
    md = generate_next_session_md(state, "Proj", "summary")

    line_count = len(md.strip().splitlines())
    assert line_count <= 20, f"GREEN output should be <=20 lines, got {line_count}"


def test_nextsession_warnings_section_when_eval():
    """Warnings section appears when eval data has warnings."""
    state = _make_state(eval={"composite": 65, "warnings": ["COMPOSITE SCORE: 65/100"]})
    md = generate_next_session_md(state, "Proj", "summary")

    assert "## Warnings" in md
    assert "65" in md


def test_nextsession_no_warnings_section_when_clean():
    """No Warnings section when eval is None or has no warnings."""
    state = _make_state(eval=None)
    md = generate_next_session_md(state, "Proj", "summary")

    assert "## Warnings" not in md


def test_nextsession_empty_pickup_when_no_tasks():
    """Pick up section shows (none) when no tasks are ready."""
    state = _make_state(next_3=[])
    md = generate_next_session_md(state, "Proj", "summary")

    assert "(none)" in md


def test_nextsession_reasons_in_context():
    """Signal reasons appear in the Context section."""
    state = _make_state(
        signal="YELLOW",
        reasons=["Some Master/Gemini blockers exist but unblocked Claude tasks available"],
    )
    md = generate_next_session_md(state, "Proj", "summary")

    assert "Master/Gemini" in md


# ============================================================================
# Contract tests: preflight_check.py — discovery handoff
# ============================================================================


def test_preflight_quick_mode_exit_zero():
    """Quick mode always exits 0, regardless of what tools are missing."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "preflight_check.py")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"quick mode must exit 0, got {result.returncode}"


def test_preflight_quick_mode_output():
    """Quick mode prints a one-line summary about prerequisites."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "preflight_check.py")],
        capture_output=True, text=True, timeout=30,
    )
    output = result.stdout.strip()
    assert len(output.splitlines()) == 1, f"expected 1 line, got {len(output.splitlines())}"
    assert "prerequisites" in output.lower() or "missing" in output.lower(), \
        f"expected prerequisites summary, got: {output}"


def test_preflight_discovery_handoff_all_specs():
    """Discovery handoff passes when all 4 spec files and .bootstrap_mode exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        specs_dir = project / "specs"
        specs_dir.mkdir()

        for spec in ("VISION.md", "BLUEPRINT.md", "RESEARCH.md", "INFRASTRUCTURE.md"):
            (specs_dir / spec).write_text(f"# {spec}\nContent here.\n")

        (project / ".bootstrap_mode").write_text("SPECIFICATION")
        (project / "scripts" / "dbq").mkdir(parents=True)

        # Import and run check_discovery_handoff directly
        sys.path.insert(0, str(SCRIPTS_DIR))
        import preflight_check
        # Reset counters
        preflight_check.CRITICAL_FAILURES = 0
        preflight_check.WARN_COUNT = 0
        preflight_check.INFO_COUNT = 0

        preflight_check.check_discovery_handoff(project)

        assert preflight_check.CRITICAL_FAILURES == 0, \
            f"expected 0 critical failures with all specs present, got {preflight_check.CRITICAL_FAILURES}"


def test_preflight_discovery_handoff_missing_spec():
    """Discovery handoff reports failure when a spec file is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        specs_dir = project / "specs"
        specs_dir.mkdir()

        # Only create 2 of 4 required specs
        (specs_dir / "VISION.md").write_text("# Vision\n")
        (specs_dir / "BLUEPRINT.md").write_text("# Blueprint\n")
        (project / ".bootstrap_mode").write_text("SPECIFICATION")

        sys.path.insert(0, str(SCRIPTS_DIR))
        import preflight_check
        preflight_check.CRITICAL_FAILURES = 0
        preflight_check.WARN_COUNT = 0
        preflight_check.INFO_COUNT = 0

        preflight_check.check_discovery_handoff(project)

        # 2 missing specs (RESEARCH.md, INFRASTRUCTURE.md)
        assert preflight_check.CRITICAL_FAILURES >= 2, \
            f"expected >=2 failures for missing specs, got {preflight_check.CRITICAL_FAILURES}"


def test_preflight_discovery_handoff_todo_in_spec():
    """Discovery handoff warns when a spec contains TODO markers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        specs_dir = project / "specs"
        specs_dir.mkdir()

        for spec in ("VISION.md", "BLUEPRINT.md", "RESEARCH.md", "INFRASTRUCTURE.md"):
            content = "# Spec\nContent here.\n"
            if spec == "RESEARCH.md":
                content = "# Research\nTODO: fill in details\n"
            (specs_dir / spec).write_text(content)

        (project / ".bootstrap_mode").write_text("SPECIFICATION")

        sys.path.insert(0, str(SCRIPTS_DIR))
        import preflight_check
        preflight_check.CRITICAL_FAILURES = 0
        preflight_check.WARN_COUNT = 0
        preflight_check.INFO_COUNT = 0

        preflight_check.check_discovery_handoff(project)

        assert preflight_check.CRITICAL_FAILURES == 0, "TODO in spec should warn, not fail"
        assert preflight_check.WARN_COUNT >= 1, \
            f"expected warning for TODO in spec, got {preflight_check.WARN_COUNT} warnings"


def test_preflight_discovery_handoff_wrong_mode():
    """Discovery handoff fails when .bootstrap_mode is not SPECIFICATION."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        specs_dir = project / "specs"
        specs_dir.mkdir()

        for spec in ("VISION.md", "BLUEPRINT.md", "RESEARCH.md", "INFRASTRUCTURE.md"):
            (specs_dir / spec).write_text(f"# {spec}\n")

        (project / ".bootstrap_mode").write_text("ACTIVATION")

        sys.path.insert(0, str(SCRIPTS_DIR))
        import preflight_check
        preflight_check.CRITICAL_FAILURES = 0
        preflight_check.WARN_COUNT = 0
        preflight_check.INFO_COUNT = 0

        preflight_check.check_discovery_handoff(project)

        assert preflight_check.CRITICAL_FAILURES >= 1, \
            f"expected failure for wrong bootstrap_mode, got {preflight_check.CRITICAL_FAILURES}"


def test_preflight_discovery_handoff_no_mode_file():
    """Discovery handoff fails when .bootstrap_mode doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        specs_dir = project / "specs"
        specs_dir.mkdir()

        for spec in ("VISION.md", "BLUEPRINT.md", "RESEARCH.md", "INFRASTRUCTURE.md"):
            (specs_dir / spec).write_text(f"# {spec}\n")

        # No .bootstrap_mode file

        sys.path.insert(0, str(SCRIPTS_DIR))
        import preflight_check
        preflight_check.CRITICAL_FAILURES = 0
        preflight_check.WARN_COUNT = 0
        preflight_check.INFO_COUNT = 0

        preflight_check.check_discovery_handoff(project)

        assert preflight_check.CRITICAL_FAILURES >= 1, \
            f"expected failure for missing .bootstrap_mode, got {preflight_check.CRITICAL_FAILURES}"


# ============================================================================
# Runner — compatible with bash test integration
# ============================================================================

if __name__ == "__main__":
    failures = 0
    total = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            total += 1
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                print(f"  FAIL  {name}: {e}")
                failures += 1
            except Exception as e:
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
                failures += 1

    print(f"\n  {total - failures}/{total} passed")
    sys.exit(1 if failures else 0)
