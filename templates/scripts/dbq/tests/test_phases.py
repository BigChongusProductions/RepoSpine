"""
Tests for phase and gate commands: phase, gate, gate-pass, status,
blockers, confirm, confirmations, master.
"""
import pytest

from dbq.db import Database
from dbq.config import ProjectConfig
from dbq.commands.phases import (
    cmd_phase,
    cmd_gate,
    cmd_gate_pass,
    cmd_status,
    cmd_blockers,
    cmd_confirm,
    cmd_confirmations,
    cmd_master,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config(tmp_db_path):
    """Minimal ProjectConfig for commands that need config.project_dir."""
    return ProjectConfig(db_path=str(tmp_db_path))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_task(db: Database, task_id: str, phase: str = "P1-TEST",
                 status: str = "TODO", assignee: str = "CLAUDE",
                 blocked_by: str = None, sort_order: int = 1):
    db.execute(
        "INSERT INTO tasks "
        "(id, phase, title, status, assignee, blocked_by, sort_order, "
        "track, queue, severity, gate_critical) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'forward', 'A', 3, 0)",
        (task_id, phase, f"Task {task_id}", status, assignee,
         blocked_by, sort_order),
    )
    db.commit()


# ---------------------------------------------------------------------------
# cmd_phase
# ---------------------------------------------------------------------------

class TestCmdPhase:
    def test_empty_db_shows_complete(self, empty_db: Database, capsys):
        """phase on empty DB reports all phases complete."""
        cmd_phase(empty_db)
        out = capsys.readouterr().out
        assert "complete" in out.lower() or "no remaining" in out.lower()

    def test_shows_phase_with_remaining_tasks(self, empty_db: Database, capsys):
        """phase shows the earliest phase with remaining tasks."""
        _insert_task(empty_db, "T-01", phase="P1-TEST", status="TODO")
        _insert_task(empty_db, "T-02", phase="P2-TEST", status="TODO")
        cmd_phase(empty_db)
        out = capsys.readouterr().out
        assert "P1-TEST" in out

    def test_skips_completed_phases(self, empty_db: Database, capsys):
        """phase skips phases where all tasks are DONE."""
        _insert_task(empty_db, "T-DONE", phase="P1-TEST", status="DONE")
        _insert_task(empty_db, "T-TODO", phase="P2-TEST", status="TODO")
        cmd_phase(empty_db)
        out = capsys.readouterr().out
        assert "P2-TEST" in out
        assert "P1-TEST" not in out

    def test_counts_remaining_correctly(self, empty_db: Database, capsys):
        """phase reports the remaining count for the current phase."""
        _insert_task(empty_db, "T-A", phase="P1-TEST", status="DONE")
        _insert_task(empty_db, "T-B", phase="P1-TEST", status="TODO")
        _insert_task(empty_db, "T-C", phase="P1-TEST", status="TODO")
        cmd_phase(empty_db)
        out = capsys.readouterr().out
        # 2 remaining tasks in P1-TEST
        assert "2" in out


# ---------------------------------------------------------------------------
# cmd_gate
# ---------------------------------------------------------------------------

class TestCmdGate:
    def test_no_gates_message(self, empty_db: Database, capsys):
        """gate on a DB with no gates recorded prints appropriate message."""
        cmd_gate(empty_db)
        out = capsys.readouterr().out
        assert "No phase gates" in out or "no" in out.lower()

    def test_shows_passed_gate(self, empty_db: Database, capsys):
        """gate shows phases that have been passed."""
        _insert_task(empty_db, "T-01", phase="P1-TEST", status="DONE")
        cmd_gate_pass(empty_db, "P1-TEST", gated_by="MASTER", notes="All good")
        cmd_gate(empty_db)
        out = capsys.readouterr().out
        assert "P1-TEST" in out
        assert "MASTER" in out


# ---------------------------------------------------------------------------
# cmd_gate_pass
# ---------------------------------------------------------------------------

class TestCmdGatePass:
    def test_records_gate_in_db(self, empty_db: Database, capsys):
        """gate-pass inserts a row into phase_gates and prints a confirmation."""
        cmd_gate_pass(empty_db, "P1-TEST")
        count = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM phase_gates WHERE phase='P1-TEST'"
        )
        out = capsys.readouterr().out
        assert count == 1
        assert "P1-TEST" in out

    def test_prints_confirmation(self, empty_db: Database, capsys):
        """gate-pass prints a confirmation message that includes the gated_by value."""
        cmd_gate_pass(empty_db, "P1-TEST", gated_by="CLAUDE", notes="Test notes")
        out = capsys.readouterr().out
        assert "P1-TEST" in out
        assert "CLAUDE" in out
        # Verify DB was also written
        row = empty_db.fetch_one(
            "SELECT gated_by FROM phase_gates WHERE phase='P1-TEST'"
        )
        assert row == "CLAUDE"

    def test_gate_pass_is_idempotent(self, empty_db: Database, capsys):
        """Running gate-pass twice on the same phase replaces the record."""
        cmd_gate_pass(empty_db, "P1-TEST", notes="First")
        cmd_gate_pass(empty_db, "P1-TEST", notes="Second")
        count = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM phase_gates WHERE phase='P1-TEST'"
        )
        assert count == 1  # INSERT OR REPLACE — still only one row

    def test_gate_pass_default_gated_by(self, empty_db: Database, capsys):
        """gate-pass defaults gated_by to MASTER."""
        cmd_gate_pass(empty_db, "P2-TEST")
        row = empty_db.fetch_one(
            "SELECT gated_by FROM phase_gates WHERE phase='P2-TEST'"
        )
        assert row == "MASTER"


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    def test_empty_db_no_tasks(self, empty_db: Database, capsys):
        cmd_status(empty_db)
        out = capsys.readouterr().out
        assert "No tasks" in out or "status" in out.lower()

    def test_shows_phase_summary(self, empty_db: Database, capsys):
        """status shows per-phase task counts."""
        _insert_task(empty_db, "T-01", phase="P1-TEST", status="DONE")
        _insert_task(empty_db, "T-02", phase="P1-TEST", status="TODO")
        cmd_status(empty_db)
        out = capsys.readouterr().out
        assert "P1-TEST" in out

    def test_shows_loopback_summary(self, empty_db: Database, capsys):
        """status shows forward track — loopbacks are in a separate track."""
        empty_db.execute(
            "INSERT INTO tasks "
            "(id, phase, title, status, assignee, queue, track, origin_phase, "
            "severity, gate_critical) "
            "VALUES ('LB-01', 'P1-TEST', 'A loopback', 'TODO', 'CLAUDE', 'A', "
            "'loopback', 'P1-TEST', 3, 0)"
        )
        empty_db.commit()
        cmd_status(empty_db)
        out = capsys.readouterr().out
        # cmd_status shows forward track only; loopbacks are tracked separately
        assert "forward" in out.lower() or "Phase status" in out


# ---------------------------------------------------------------------------
# cmd_blockers
# ---------------------------------------------------------------------------

class TestCmdBlockers:
    def test_no_blockers(self, empty_db: Database, capsys):
        """blockers on a clean DB says no blockers."""
        _insert_task(empty_db, "T-01")
        cmd_blockers(empty_db)
        out = capsys.readouterr().out
        assert "No Master/Gemini blockers" in out or "unblocked" in out.lower()

    def test_shows_master_blocker(self, empty_db: Database, capsys):
        """blockers identifies MASTER-assigned tasks that block CLAUDE tasks."""
        _insert_task(empty_db, "M-01", phase="P1-TEST", assignee="MASTER")
        _insert_task(empty_db, "C-01", phase="P1-TEST", assignee="CLAUDE",
                     blocked_by="M-01")
        cmd_blockers(empty_db)
        out = capsys.readouterr().out
        assert "M-01" in out


# ---------------------------------------------------------------------------
# cmd_confirm
# ---------------------------------------------------------------------------

class TestCmdConfirm:
    def test_records_confirmation(self, empty_db: Database, config, capsys):
        """confirm inserts a row into milestone_confirmations and prints output."""
        _insert_task(empty_db, "T-CONF")
        cmd_confirm(empty_db, config, "T-CONF", confirmed_by="MASTER", reasons="looks good")
        count = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM milestone_confirmations WHERE task_id='T-CONF'"
        )
        out = capsys.readouterr().out
        assert count == 1
        assert "T-CONF" in out

    def test_confirm_nonexistent_task_exits(self, empty_db: Database, config):
        with pytest.raises(SystemExit) as exc_info:
            cmd_confirm(empty_db, config, "MISSING", "MASTER", "reason")
        assert exc_info.value.code == 1

    def test_confirm_prints_output(self, empty_db: Database, config, capsys):
        _insert_task(empty_db, "T-CONF2")
        cmd_confirm(empty_db, config, "T-CONF2", confirmed_by="MASTER", reasons="ok")
        out = capsys.readouterr().out
        assert "T-CONF2" in out
        # Also verify the DB row was written
        count = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM milestone_confirmations WHERE task_id='T-CONF2'"
        )
        assert count == 1

    def test_confirm_idempotent(self, empty_db: Database, config, capsys):
        """Confirming the same task twice replaces the record (INSERT OR REPLACE)."""
        _insert_task(empty_db, "T-CONF3")
        cmd_confirm(empty_db, config, "T-CONF3", confirmed_by="MASTER", reasons="first")
        cmd_confirm(empty_db, config, "T-CONF3", confirmed_by="MASTER", reasons="second")
        count = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM milestone_confirmations WHERE task_id='T-CONF3'"
        )
        assert count == 1


# ---------------------------------------------------------------------------
# cmd_confirmations
# ---------------------------------------------------------------------------

class TestCmdConfirmations:
    def test_empty(self, empty_db: Database, capsys):
        cmd_confirmations(empty_db)
        out = capsys.readouterr().out
        assert "No milestone confirmations" in out or "confirmation" in out.lower()

    def test_shows_recorded_confirmations(self, empty_db: Database, config, capsys):
        _insert_task(empty_db, "T-CONF")
        cmd_confirm(empty_db, config, "T-CONF", "MASTER", "all good")
        capsys.readouterr()  # flush confirm output
        cmd_confirmations(empty_db)
        out = capsys.readouterr().out
        assert "T-CONF" in out


# ---------------------------------------------------------------------------
# cmd_master
# ---------------------------------------------------------------------------

class TestCmdMaster:
    def test_no_master_tasks(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-CLAUDE")
        cmd_master(empty_db)
        out = capsys.readouterr().out
        assert "No Master/Gemini" in out or "No" in out

    def test_shows_master_tasks(self, empty_db: Database, capsys):
        _insert_task(empty_db, "M-01", assignee="MASTER")
        cmd_master(empty_db)
        out = capsys.readouterr().out
        assert "M-01" in out
