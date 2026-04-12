"""
Tests for loopback commands: loopbacks, loopback-stats, loopback-lesson, ack-breaker,
and the next (task queue) command.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dbq.db import Database
from dbq.config import ProjectConfig
from dbq.commands.loopbacks import (
    cmd_loopbacks,
    cmd_loopback_stats,
    cmd_loopback_lesson,
    cmd_ack_breaker,
)
from dbq.commands.next_cmd import cmd_next


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_loopback(
    db: Database,
    task_id: str,
    title: str = "Fix something",
    origin_phase: str = "P1-DISCOVER",
    discovered_in: str = "P2-DESIGN",
    severity: int = 3,
    gate_critical: int = 0,
    status: str = "TODO",
    loopback_reason: str = None,
):
    """Insert a loopback task row for testing."""
    db.execute(
        "INSERT INTO tasks "
        "(id, phase, title, status, assignee, track, origin_phase, "
        "discovered_in, severity, gate_critical, loopback_reason, "
        "sort_order, queue) "
        "VALUES (?, ?, ?, ?, 'CLAUDE', 'loopback', ?, ?, ?, ?, ?, 999, 'A')",
        (task_id, origin_phase, title, status, origin_phase,
         discovered_in, severity, gate_critical, loopback_reason),
    )
    db.commit()


def _insert_forward_task(
    db: Database,
    task_id: str,
    phase: str = "P1-DISCOVER",
    status: str = "TODO",
    assignee: str = "CLAUDE",
    blocked_by: str = None,
    sort_order: int = 1,
):
    """Insert a forward-track task row for testing."""
    db.execute(
        "INSERT INTO tasks "
        "(id, phase, title, status, assignee, track, blocked_by, "
        "sort_order, queue, severity, gate_critical) "
        "VALUES (?, ?, ?, ?, ?, 'forward', ?, ?, 'A', 3, 0)",
        (task_id, phase, f"Task {task_id}", status, assignee, blocked_by, sort_order),
    )
    db.commit()


# ---------------------------------------------------------------------------
# TestCmdLoopbacks
# ---------------------------------------------------------------------------

class TestCmdLoopbacks:

    def test_empty_db_no_crash(self, empty_db: Database, capsys):
        """loopbacks command runs without error on an empty database."""
        cmd_loopbacks(empty_db)
        out = capsys.readouterr().out
        assert "Loopback Tasks" in out
        assert "(none matching filters)" in out
        # Summary line should report 0 open
        assert "Open: 0" in out

    def test_shows_loopback_task(self, empty_db: Database, capsys):
        """loopbacks command lists a loopback task with its ID and title."""
        _insert_loopback(empty_db, "LB-10", title="Fix regex bug", severity=2)
        cmd_loopbacks(empty_db)
        out = capsys.readouterr().out
        assert "LB-10" in out
        assert "Fix regex bug" in out
        # Summary line should report the open task count
        assert "Open: 1" in out

    def test_summary_counts_are_accurate(self, empty_db: Database, capsys):
        """Summary line shows correct open/done/skipped counts."""
        _insert_loopback(empty_db, "LB-20", status="TODO")
        _insert_loopback(empty_db, "LB-21", status="DONE")
        _insert_loopback(empty_db, "LB-22", status="SKIP")
        cmd_loopbacks(empty_db)
        out = capsys.readouterr().out
        assert "Open: 1" in out
        assert "Done: 1" in out
        assert "Skipped: 1" in out

    def test_filters_by_origin(self, empty_db: Database, capsys):
        """--origin filter hides tasks from other origin phases."""
        _insert_loopback(empty_db, "LB-30", origin_phase="P1-DISCOVER")
        _insert_loopback(empty_db, "LB-31", origin_phase="P2-DESIGN")
        cmd_loopbacks(empty_db, origin="P1-DISCOVER")
        out = capsys.readouterr().out
        assert "LB-30" in out
        assert "LB-31" not in out

    @pytest.mark.parametrize("keep_severity,hide_severity,keep_id,hide_id", [
        (1, 3, "LB-40A", "LB-41A"),
        (2, 3, "LB-40B", "LB-41B"),
        (1, 2, "LB-40C", "LB-41C"),
    ])
    def test_filters_by_severity(
        self,
        empty_db: Database,
        capsys,
        keep_severity: int,
        hide_severity: int,
        keep_id: str,
        hide_id: str,
    ):
        """--severity filter shows only tasks at the requested severity level."""
        _insert_loopback(empty_db, keep_id, severity=keep_severity)
        _insert_loopback(empty_db, hide_id, severity=hide_severity)
        cmd_loopbacks(empty_db, severity=keep_severity)
        out = capsys.readouterr().out
        assert keep_id in out
        assert hide_id not in out

    def test_gate_critical_only(self, empty_db: Database, capsys):
        """--gate-critical-only hides non-gate-critical tasks."""
        _insert_loopback(empty_db, "LB-50", gate_critical=1, title="Critical fix")
        _insert_loopback(empty_db, "LB-51", gate_critical=0, title="Minor fix")
        cmd_loopbacks(empty_db, gate_critical_only=True)
        out = capsys.readouterr().out
        assert "LB-50" in out
        assert "LB-51" not in out

    def test_show_all_includes_done(self, empty_db: Database, capsys):
        """--show-all displays DONE tasks that are otherwise filtered out."""
        _insert_loopback(empty_db, "LB-60", status="DONE", title="Already fixed")
        # Without show_all, DONE tasks should not appear
        cmd_loopbacks(empty_db, show_all=False)
        out_default = capsys.readouterr().out
        assert "LB-60" not in out_default

        # With show_all, DONE tasks appear
        cmd_loopbacks(empty_db, show_all=True)
        out_all = capsys.readouterr().out
        assert "LB-60" in out_all

    def test_gate_critical_tag_displayed(self, empty_db: Database, capsys):
        """Gate-critical tasks display 'GATE-CRITICAL' marker."""
        _insert_loopback(empty_db, "LB-70", gate_critical=1)
        cmd_loopbacks(empty_db)
        out = capsys.readouterr().out
        assert "GATE-CRITICAL" in out

    def test_populated_db_shows_loopback(self, populated_db: Database, capsys):
        """Fixture LB-01 (severity=3) appears in default listing."""
        cmd_loopbacks(populated_db)
        out = capsys.readouterr().out
        assert "LB-01" in out


# ---------------------------------------------------------------------------
# TestCmdLoopbackStats
# ---------------------------------------------------------------------------

class TestCmdLoopbackStats:

    def test_empty_db_no_crash(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """loopback-stats runs without error on an empty database."""
        cmd_loopback_stats(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "LOOPBACK ANALYTICS" in out
        assert "No loopback tasks" in out

    def test_shows_stats_with_data(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """loopback-stats shows total count and severity distribution when data exists."""
        cmd_loopback_stats(populated_db, populated_config)
        out = capsys.readouterr().out
        assert "LOOPBACK ANALYTICS" in out
        assert "Total:" in out
        assert "Severity distribution:" in out

    def test_shows_origin_phase_breakdown(self, empty_db: Database, populated_config: ProjectConfig, capsys):
        """Stats shows by-origin-phase breakdown."""
        _insert_loopback(empty_db, "LB-80", origin_phase="P1-DISCOVER", severity=2)
        _insert_loopback(empty_db, "LB-81", origin_phase="P1-DISCOVER", severity=3)
        cmd_loopback_stats(empty_db, populated_config)
        out = capsys.readouterr().out
        assert "By origin phase:" in out
        assert "P1-DISCOVER" in out

    def test_gate_critical_summary_shown(self, empty_db: Database, populated_config: ProjectConfig, capsys):
        """Stats shows gate-critical status section."""
        _insert_loopback(empty_db, "LB-90", gate_critical=1, severity=2)
        cmd_loopback_stats(empty_db, populated_config)
        out = capsys.readouterr().out
        assert "Gate-critical status:" in out

    def test_hotspot_reported_when_threshold_met(self, empty_db: Database, populated_config: ProjectConfig, capsys):
        """An origin phase with 3+ loopbacks is reported as an iteration hotspot."""
        for i in range(3):
            _insert_loopback(empty_db, f"LB-9{i}", origin_phase="P1-DISCOVER")
        cmd_loopback_stats(empty_db, populated_config)
        out = capsys.readouterr().out
        assert "hotspot" in out.lower()
        assert "P1-DISCOVER" in out

    def test_discovery_lag_shown_when_phases_differ(self, empty_db: Database, populated_config: ProjectConfig, capsys):
        """Discovery lag section appears when origin and discovered_in differ."""
        _insert_loopback(
            empty_db, "LB-100",
            origin_phase="P1-DISCOVER",
            discovered_in="P2-DESIGN",
            severity=2,
        )
        cmd_loopback_stats(empty_db, populated_config)
        out = capsys.readouterr().out
        assert "Discovery lag:" in out


# ---------------------------------------------------------------------------
# TestCmdLoopbackLesson
# ---------------------------------------------------------------------------

class TestCmdLoopbackLesson:

    def test_generates_lesson_append(self, populated_db: Database, populated_config: ProjectConfig, capsys, tmp_path: Path):
        """cmd_loopback_lesson appends a lesson entry to the LESSONS file."""
        lessons_file = tmp_path / "LESSONS_TEST.md"
        lessons_file.write_text("# Lessons\n\nSome existing content.\n")

        config = ProjectConfig(
            db_path=str(populated_config.db_path),
            project_name="test-project",
            phases=["P1-DISCOVER", "P2-DESIGN", "P3-IMPLEMENT"],
            lessons_file=str(lessons_file),
        )

        cmd_loopback_lesson(populated_db, config, "LB-01")

        out = capsys.readouterr().out
        assert "Lesson" in out

        content = lessons_file.read_text()
        assert "LB-01" in content

    def test_generates_lesson_inserts_before_marker(self, populated_db: Database, populated_config: ProjectConfig, capsys, tmp_path: Path):
        """Lesson is inserted before '## Universal Patterns' if that marker exists."""
        lessons_file = tmp_path / "LESSONS_MARKER.md"
        lessons_file.write_text("# Lessons\n\n## Universal Patterns\n\nold content\n")

        config = ProjectConfig(
            db_path=str(populated_config.db_path),
            project_name="test-project",
            phases=["P1-DISCOVER", "P2-DESIGN", "P3-IMPLEMENT"],
            lessons_file=str(lessons_file),
        )

        cmd_loopback_lesson(populated_db, config, "LB-01")

        content = lessons_file.read_text()
        # The new lesson entry must appear before the marker
        lesson_pos = content.find("LB-01")
        marker_pos = content.find("## Universal Patterns")
        assert lesson_pos != -1
        assert marker_pos != -1
        assert lesson_pos < marker_pos

    def test_no_lessons_file_warns_gracefully(self, populated_db: Database, capsys):
        """If no LESSONS file is configured, a warning is printed (no crash)."""
        config = ProjectConfig(
            db_path="/tmp/fake.db",
            project_name="test-project",
            phases=["P1-DISCOVER"],
            lessons_file="",
        )
        cmd_loopback_lesson(populated_db, config, "LB-01")
        out = capsys.readouterr().out
        assert "No LESSONS file" in out or "Lesson entry" in out

    def test_missing_lessons_file_warns_gracefully(self, populated_db: Database, capsys, tmp_path: Path):
        """If LESSONS file path is set but file doesn't exist, a warning is printed."""
        config = ProjectConfig(
            db_path="/tmp/fake.db",
            project_name="test-project",
            phases=["P1-DISCOVER"],
            lessons_file=str(tmp_path / "DOES_NOT_EXIST.md"),
        )
        cmd_loopback_lesson(populated_db, config, "LB-01")
        out = capsys.readouterr().out
        assert "not found" in out or "Lesson entry" in out

    def test_nonexistent_task_exits(self, empty_db: Database, capsys):
        """cmd_loopback_lesson exits with SystemExit for an unknown task ID."""
        config = ProjectConfig(
            db_path="/tmp/fake.db",
            project_name="test",
            phases=[],
        )
        with pytest.raises(SystemExit):
            cmd_loopback_lesson(empty_db, config, "LB-NONEXISTENT")


# ---------------------------------------------------------------------------
# TestCmdAckBreaker
# ---------------------------------------------------------------------------

class TestCmdAckBreaker:

    def test_acknowledges_loopback(self, populated_db: Database, capsys):
        """ack-breaker inserts a row into loopback_acks for an existing loopback task."""
        cmd_ack_breaker(populated_db, "LB-01", "fixing now")

        out = capsys.readouterr().out
        assert "acknowledged" in out.lower()
        assert "LB-01" in out

        row = populated_db.fetch_one(
            "SELECT reason FROM loopback_acks WHERE loopback_id='LB-01'"
        )
        assert row == "fixing now"

    def test_ack_is_idempotent(self, populated_db: Database, capsys):
        """Calling ack-breaker twice for the same task replaces the existing ack."""
        cmd_ack_breaker(populated_db, "LB-01", "first reason")
        cmd_ack_breaker(populated_db, "LB-01", "updated reason")

        count = populated_db.fetch_scalar(
            "SELECT COUNT(*) FROM loopback_acks WHERE loopback_id='LB-01'"
        )
        assert count == 1

        row = populated_db.fetch_one(
            "SELECT reason FROM loopback_acks WHERE loopback_id='LB-01'"
        )
        assert row == "updated reason"

    def test_nonexistent_task_exits(self, empty_db: Database, capsys):
        """ack-breaker exits with SystemExit for a task ID that doesn't exist."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_ack_breaker(empty_db, "LB-GHOST", "some reason")
        assert exc_info.value.code == 1
        # Nothing should be written to loopback_acks
        count = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM loopback_acks WHERE loopback_id='LB-GHOST'"
        )
        assert count == 0

    def test_non_loopback_task_exits(self, empty_db: Database, capsys):
        """ack-breaker exits with SystemExit if task track is not 'loopback'."""
        _insert_forward_task(empty_db, "T-01")
        with pytest.raises(SystemExit) as exc_info:
            cmd_ack_breaker(empty_db, "T-01", "should fail")
        assert exc_info.value.code == 1
        # No ack row should have been created
        count = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM loopback_acks WHERE loopback_id='T-01'"
        )
        assert count == 0

    def test_reason_stored_correctly(self, populated_db: Database, capsys):
        """The reason string is stored verbatim in loopback_acks."""
        reason = "deferring because P3 deadline overrides"
        cmd_ack_breaker(populated_db, "LB-01", reason)
        capsys.readouterr()

        stored = populated_db.fetch_one(
            "SELECT reason FROM loopback_acks WHERE loopback_id='LB-01'"
        )
        assert stored == reason


# ---------------------------------------------------------------------------
# TestCmdNext
# ---------------------------------------------------------------------------

class TestCmdNext:

    def test_empty_db_no_crash(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """next command runs without error on an empty database."""
        cmd_next(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "Task Queue" in out

    def test_shows_ready_forward_tasks(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """next command lists CLAUDE-owned TODO tasks in the FORWARD section."""
        cmd_next(populated_db, populated_config)
        out = capsys.readouterr().out
        assert "FORWARD" in out
        # T-02 is TODO, CLAUDE-owned, unblocked
        assert "T-02" in out

    def test_shows_loopback_in_s3_section(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """LB-01 (severity=3) from populated_db appears in S3/S4 section."""
        cmd_next(populated_db, populated_config)
        out = capsys.readouterr().out
        # S3 loopbacks appear at the bottom of the queue
        assert "LB-01" in out

    def test_circuit_breaker_shown_for_s1_gc(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """An S1 gate-critical loopback triggers the CIRCUIT BREAKER section."""
        _insert_loopback(empty_db, "LB-S1", severity=1, gate_critical=1, title="Critical blocker")
        cmd_next(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "CIRCUIT BREAKER" in out
        assert "LB-S1" in out

    def test_s2_loopback_shown_prominently(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """S2 loopbacks appear before forward tasks."""
        _insert_loopback(empty_db, "LB-S2", severity=2, title="S2 loopback task")
        _insert_forward_task(empty_db, "T-FWD", sort_order=1)
        cmd_next(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "S2 Loopbacks" in out
        assert "LB-S2" in out

    def test_ready_only_hides_blocked(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """--ready-only suppresses blocked tasks and shows a count summary instead."""
        # Insert blocker task and dependent task
        _insert_forward_task(empty_db, "T-BLOCKER", status="TODO", sort_order=1)
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, track, "
            "blocked_by, sort_order, queue, severity, gate_critical) "
            "VALUES ('T-BLOCKED', 'P1-DISCOVER', 'Blocked task', 'TODO', "
            "'CLAUDE', 'forward', 'T-BLOCKER', 2, 'A', 3, 0)"
        )
        empty_db.commit()

        cmd_next(empty_db, simple_config, ready_only=True)
        out = capsys.readouterr().out
        assert "T-BLOCKED" not in out
        # The count summary should mention blocked tasks were hidden
        assert "blocked" in out.lower()

    def test_blocked_tasks_visible_without_ready_only(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """Without --ready-only, tasks blocked by an active blocker appear in BLOCKED section."""
        _insert_forward_task(empty_db, "T-BLOCKER2", status="TODO", sort_order=1)
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, track, "
            "blocked_by, sort_order, queue, severity, gate_critical) "
            "VALUES ('T-BLOCKED2', 'P1-DISCOVER', 'Still blocked', 'TODO', "
            "'CLAUDE', 'forward', 'T-BLOCKER2', 2, 'A', 3, 0)"
        )
        empty_db.commit()

        cmd_next(empty_db, simple_config, ready_only=False)
        out = capsys.readouterr().out
        assert "BLOCKED" in out
        assert "T-BLOCKED2" in out

    def test_done_tasks_not_in_forward(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """DONE tasks do not appear in the FORWARD section."""
        _insert_forward_task(empty_db, "T-DONE", status="DONE")
        cmd_next(empty_db, simple_config)
        out = capsys.readouterr().out
        # T-DONE must not appear as a ready forward task
        lines = [ln for ln in out.splitlines() if "T-DONE" in ln]
        assert not lines

    def test_circuit_breaker_shows_acknowledged_tag(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """An acknowledged S1 breaker displays '(acknowledged)' in its row."""
        _insert_loopback(empty_db, "LB-ACK", severity=1, gate_critical=1)
        # Acknowledge it
        empty_db.execute(
            "INSERT INTO loopback_acks (loopback_id, acked_on, acked_by, reason) "
            "VALUES ('LB-ACK', '2026-01-01', 'MASTER', 'noted')"
        )
        empty_db.commit()

        cmd_next(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "acknowledged" in out

    def test_master_tasks_excluded_from_forward(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """MASTER-owned tasks do not appear in the FORWARD ready section."""
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, track, "
            "sort_order, queue, severity, gate_critical) "
            "VALUES ('T-MASTER', 'P1-DISCOVER', 'Master task', 'TODO', "
            "'MASTER', 'forward', 1, 'A', 3, 0)"
        )
        empty_db.commit()

        cmd_next(empty_db, simple_config)
        out = capsys.readouterr().out
        # FORWARD section only lists CLAUDE tasks
        forward_section = out[out.find("FORWARD"):]
        assert "T-MASTER" not in forward_section.split("BLOCKED")[0]
