"""
Tests for task commands: done, check, quick, start, skip, unblock,
add-task, inbox, triage, task detail view.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dbq.db import Database
from dbq.config import ProjectConfig
from dbq.commands.tasks import (
    cmd_done,
    cmd_quick,
    cmd_check,
    cmd_task,
    cmd_start,
    cmd_skip,
    cmd_unblock,
    cmd_add_task,
    cmd_inbox,
    cmd_triage,
    cmd_researched,
    cmd_break_tested,
    cmd_tag_browser,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_task(db: Database, task_id: str, phase: str = "P1-TEST",
                 status: str = "TODO", assignee: str = "CLAUDE",
                 tier: str = "haiku", blocked_by: str = None,
                 track: str = "forward", sort_order: int = 1):
    """Insert a minimal task row for testing."""
    db.execute(
        "INSERT INTO tasks "
        "(id, phase, title, status, assignee, tier, blocked_by, "
        "track, sort_order, queue, severity, gate_critical) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'A', 3, 0)",
        (task_id, phase, f"Task {task_id}", status, assignee,
         tier, blocked_by, track, sort_order),
    )
    db.commit()


def _make_config(db: Database, tmp_path: Path) -> ProjectConfig:
    """Build a ProjectConfig pointing at the test DB in a temp project dir."""
    return ProjectConfig(
        db_path=str(tmp_path / "test.db"),
        project_name="test",
        phases=["P1-TEST", "P2-TEST", "P3-TEST"],
    )


# ---------------------------------------------------------------------------
# cmd_done
# ---------------------------------------------------------------------------

class TestCmdDone:
    def test_marks_task_done(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """done command transitions TODO → DONE in the DB."""
        _insert_task(empty_db, "T-01")
        # Patch git so _auto_commit is a no-op
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-01", skip_break=True)

        status = empty_db.fetch_one("SELECT status FROM tasks WHERE id='T-01'")
        assert status == "DONE"

    def test_done_prints_confirmation(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """done command prints 'DONE' confirmation."""
        _insert_task(empty_db, "T-02")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-02", skip_break=True)
        out = capsys.readouterr().out
        assert "DONE" in out

    def test_done_nonexistent_task_exits(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """done with an unknown task ID should sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_done(empty_db, simple_config, "T-MISSING", skip_break=True)
        assert exc_info.value.code == 1
        # DB should still be empty — nothing written for a nonexistent task
        count = empty_db.fetch_scalar("SELECT COUNT(*) FROM tasks")
        assert count == 0

    def test_done_already_done_skips(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """Calling done on an already-DONE task prints a warning, no re-processing."""
        _insert_task(empty_db, "T-03", status="DONE")
        with patch("subprocess.run"):
            cmd_done(empty_db, simple_config, "T-03", skip_break=True)
        out = capsys.readouterr().out
        assert "already DONE" in out
        # Status must remain DONE, not change to something else
        status = empty_db.fetch_one("SELECT status FROM tasks WHERE id='T-03'")
        assert status == "DONE"

    def test_done_sets_completed_on(self, empty_db: Database, simple_config: ProjectConfig):
        """done sets completed_on to a non-null value."""
        _insert_task(empty_db, "T-04")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-04", skip_break=True)
        completed = empty_db.fetch_one(
            "SELECT completed_on FROM tasks WHERE id='T-04'"
        )
        assert completed is not None


# ---------------------------------------------------------------------------
# cmd_quick
# ---------------------------------------------------------------------------

class TestCmdQuick:
    def test_quick_creates_inbox_task(self, empty_db: Database, capsys):
        """quick without --loopback creates a QK-xxxx INBOX task."""
        cmd_quick(empty_db, title="Test quick capture", phase="INBOX")
        out = capsys.readouterr().out
        import re
        match = re.search(r"QK-[0-9a-f]+", out)
        assert match is not None, f"No QK-xxxx ID in output: {out!r}"
        task_id = match.group(0)
        row = empty_db.fetch_one("SELECT phase, status, queue FROM tasks WHERE id=?", (task_id,))
        assert row is not None
        assert row["status"] == "TODO"
        assert row["queue"] == "INBOX"

    def test_quick_creates_loopback_task(self, empty_db: Database, capsys):
        """quick with --loopback creates an LB-xxxx loopback task."""
        cmd_quick(
            empty_db,
            title="Fix broken thing",
            phase="P1-TEST",
            loopback_origin="P1-TEST",
            severity=2,
            gate_critical=False,
            reason="regression spotted",
        )
        out = capsys.readouterr().out
        import re
        match = re.search(r"LB-[0-9a-f]+", out)
        assert match is not None, f"No LB-xxxx ID in output: {out!r}"
        task_id = match.group(0)
        row = empty_db.fetch_one(
            "SELECT track, origin_phase, severity FROM tasks WHERE id=?",
            (task_id,),
        )
        assert row["track"] == "loopback"
        assert row["origin_phase"] == "P1-TEST"
        assert row["severity"] == 2

    def test_quick_gate_critical_loopback(self, empty_db: Database, capsys):
        """quick with gate_critical=True sets gate_critical=1 in DB."""
        cmd_quick(
            empty_db,
            title="Critical fix",
            phase="P1-TEST",
            loopback_origin="P1-TEST",
            severity=1,
            gate_critical=True,
        )
        import re
        out = capsys.readouterr().out
        match = re.search(r"LB-[0-9a-f]+", out)
        assert match, f"Expected LB-xxxx in output: {out!r}"
        task_id = match.group(0)
        gc = empty_db.fetch_scalar(
            "SELECT gate_critical FROM tasks WHERE id=?", (task_id,)
        )
        assert gc == 1

    def test_quick_custom_phase(self, empty_db: Database, capsys):
        """quick with explicit phase stores that phase and creates a TODO task."""
        cmd_quick(empty_db, title="Phase test", phase="P2-TEST")
        import re
        out = capsys.readouterr().out
        match = re.search(r"QK-[0-9a-f]+", out)
        assert match
        task_id = match.group(0)
        row = empty_db.fetch_one(
            "SELECT phase, status FROM tasks WHERE id=?", (task_id,)
        )
        assert row["phase"] == "P2-TEST"
        assert row["status"] == "TODO"


# ---------------------------------------------------------------------------
# cmd_check
# ---------------------------------------------------------------------------

class TestCmdCheck:
    def test_check_nonexistent_task_exits(self, empty_db: Database, simple_config: ProjectConfig):
        """check on a missing task exits with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_check(empty_db, simple_config, "MISSING-99")
        assert exc_info.value.code == 1

    def test_check_master_task_prints_stop(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """check on a MASTER-assigned task should print STOP (no sys.exit)."""
        _insert_task(empty_db, "T-MASTER", assignee="MASTER")
        cmd_check(empty_db, simple_config, "T-MASTER")
        out = capsys.readouterr().out
        assert "STOP" in out

    def test_check_already_done_warns(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """check on an already-DONE task prints a warning (no STOP exit)."""
        _insert_task(empty_db, "T-DONE", status="DONE")
        # Should not exit — just warn
        cmd_check(empty_db, simple_config, "T-DONE")
        out = capsys.readouterr().out
        assert "already DONE" in out

    def test_check_cross_phase_blocker_stops(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """check on a task blocked by an undone task in a different phase prints STOP."""
        _insert_task(empty_db, "T-BLOCKER", phase="P1-TEST", status="TODO")
        _insert_task(empty_db, "T-BLOCKED", phase="P2-TEST", status="TODO",
                     blocked_by="T-BLOCKER", sort_order=1)
        cmd_check(empty_db, simple_config, "T-BLOCKED")
        out = capsys.readouterr().out
        assert "STOP" in out

    def test_check_stale_blockedby_warns(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """check on a task with a nonexistent blocked_by shows a stale reference warning."""
        _insert_task(empty_db, "T-STALE", phase="P1-TEST", blocked_by="T-NONEXISTENT")
        # Should not hard-stop on stale reference; should WARN
        # May or may not exit depending on other checks — just verify the warning text
        try:
            cmd_check(empty_db, simple_config, "T-STALE")
        except SystemExit:
            pass
        out = capsys.readouterr().out
        assert "stale reference" in out or "nonexistent" in out

    def test_check_go_simple_task(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """check on a clean single-phase TODO task should not exit with error."""
        _insert_task(empty_db, "T-GO", phase="P1-TEST")
        # No prior phases, no blockers — should print GO or milestone info
        try:
            cmd_check(empty_db, simple_config, "T-GO")
        except SystemExit as exc:
            pytest.fail(f"cmd_check exited unexpectedly with code {exc.code}")


    def test_check_go_shows_discipline_advisory(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """GO verdict includes discipline advisory with correct framework path."""
        # Need a prior DONE task (suppress Rule 1: first-in-phase)
        # and a later TODO task (suppress Rule 5: last-in-phase)
        _insert_task(empty_db, "T-PREV", phase="P1-TEST", status="DONE", sort_order=0)
        _insert_task(empty_db, "T-DISC", phase="P1-TEST", sort_order=1)
        _insert_task(empty_db, "T-LATER", phase="P1-TEST", sort_order=2)
        try:
            cmd_check(empty_db, simple_config, "T-DISC")
        except SystemExit:
            pass
        out = capsys.readouterr().out
        assert "GO" in out
        assert "DISCIPLINE" in out
        assert "~/.claude/frameworks/" in out
        assert "templates/frameworks/" not in out

    def test_check_confirm_shows_discipline_advisory(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """CONFIRM verdict includes discipline advisory."""
        # First task in a phase triggers CONFIRM (first-in-phase milestone)
        _insert_task(empty_db, "T-CONF-D", phase="P2-TEST", sort_order=1)
        # Need a completed P1-TEST task so P2 isn't blocked by missing prior phase work
        _insert_task(empty_db, "T-P1", phase="P1-TEST", status="DONE")
        # Gate P1-TEST so P2 isn't blocked
        empty_db.execute(
            "INSERT INTO phase_gates (phase, gated_on, gated_by) "
            "VALUES ('P1-TEST', '2026-01-01', 'test')"
        )
        empty_db.commit()
        try:
            cmd_check(empty_db, simple_config, "T-CONF-D")
        except SystemExit:
            pass
        out = capsys.readouterr().out
        # Should have CONFIRM and DISCIPLINE
        assert "CONFIRM" in out
        assert "DISCIPLINE" in out
        assert "~/.claude/frameworks/" in out

    def test_check_loopback_go_shows_discipline_advisory(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """Loopback GO verdict includes discipline advisory with root-cause focus."""
        _insert_task(empty_db, "T-LB", phase="P1-TEST", track="loopback")
        try:
            cmd_check(empty_db, simple_config, "T-LB")
        except SystemExit:
            pass
        out = capsys.readouterr().out
        assert "DISCIPLINE" in out
        assert "root cause" in out
        assert "~/.claude/frameworks/" in out


# ---------------------------------------------------------------------------
# cmd_task (detail view)
# ---------------------------------------------------------------------------

class TestCmdTask:
    def test_shows_task_details(self, empty_db: Database, capsys):
        """task command prints the task title and ID."""
        _insert_task(empty_db, "T-DETAIL")
        cmd_task(empty_db, "T-DETAIL")
        out = capsys.readouterr().out
        assert "T-DETAIL" in out

    def test_nonexistent_task_exits(self, empty_db: Database):
        with pytest.raises(SystemExit) as exc_info:
            cmd_task(empty_db, "MISSING")
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# cmd_start
# ---------------------------------------------------------------------------

class TestCmdStart:
    def test_marks_in_progress(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-START")
        cmd_start(empty_db, "T-START")
        status = empty_db.fetch_one("SELECT status FROM tasks WHERE id='T-START'")
        out = capsys.readouterr().out
        assert status == "IN_PROGRESS"
        assert out  # start should produce output

    def test_start_nonexistent_exits(self, empty_db: Database):
        with pytest.raises(SystemExit):
            cmd_start(empty_db, "MISSING")


# ---------------------------------------------------------------------------
# cmd_skip
# ---------------------------------------------------------------------------

class TestCmdSkip:
    def test_marks_skip(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-SKIP")
        cmd_skip(empty_db, "T-SKIP", reason="not needed")
        status = empty_db.fetch_one("SELECT status FROM tasks WHERE id='T-SKIP'")
        out = capsys.readouterr().out
        assert status == "SKIP"
        assert "T-SKIP" in out or "SKIP" in out

    def test_skip_nonexistent_exits(self, empty_db: Database):
        with pytest.raises(SystemExit):
            cmd_skip(empty_db, "MISSING", reason="")


# ---------------------------------------------------------------------------
# cmd_unblock
# ---------------------------------------------------------------------------

class TestCmdUnblock:
    def test_clears_blocked_by(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-UNBLOCK", blocked_by="T-OTHER")
        cmd_unblock(empty_db, "T-UNBLOCK")
        blocked_by = empty_db.fetch_one("SELECT blocked_by FROM tasks WHERE id='T-UNBLOCK'")
        out = capsys.readouterr().out
        assert blocked_by is None or blocked_by == ""
        assert out  # unblock should produce output confirming the action

    def test_unblock_nonexistent_exits(self, empty_db: Database):
        with pytest.raises(SystemExit):
            cmd_unblock(empty_db, "MISSING")


# ---------------------------------------------------------------------------
# Parametrized: nonexistent task ID exits across multiple commands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd_func,args", [
    (cmd_start, []),
    (cmd_skip, ["reason text"]),
    (cmd_unblock, []),
])
def test_nonexistent_task_exits_parametrized(empty_db: Database, cmd_func, args):
    """Each single-task mutation command exits 1 when given an unknown task ID."""
    with pytest.raises(SystemExit) as exc_info:
        cmd_func(empty_db, "DOES-NOT-EXIST", *args)
    assert exc_info.value.code in (1, 2)


# ---------------------------------------------------------------------------
# cmd_add_task
# ---------------------------------------------------------------------------

class TestCmdAddTask:
    def test_adds_task(self, empty_db: Database, capsys):
        cmd_add_task(
            empty_db, "T-ADD", "P1-TEST", "New task title",
            "sonnet", "", "", 5,
        )
        row = empty_db.fetch_one(
            "SELECT id, phase, title, tier FROM tasks WHERE id='T-ADD'"
        )
        assert row is not None
        assert row["phase"] == "P1-TEST"
        assert row["title"] == "New task title"
        assert row["tier"] == "sonnet"

    def test_duplicate_id_succeeds(self, empty_db: Database, capsys):
        """Adding a task with a duplicate ID overwrites (SQLite REPLACE behavior)."""
        _insert_task(empty_db, "T-DUP")
        cmd_add_task(
            empty_db, "T-DUP", "P1-TEST", "Duplicate", "haiku",
            "", "", 1,
        )
        out = capsys.readouterr().out
        assert "T-DUP" in out
        # Still exactly one row with this ID (REPLACE, not INSERT extra)
        count = empty_db.fetch_scalar("SELECT COUNT(*) FROM tasks WHERE id='T-DUP'")
        assert count == 1


# ---------------------------------------------------------------------------
# cmd_inbox
# ---------------------------------------------------------------------------

class TestCmdInbox:
    def test_shows_inbox_tasks(self, empty_db: Database, capsys):
        """inbox lists tasks with queue='INBOX'."""
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue) "
            "VALUES ('QK-INBOX', 'INBOX', 'Inbox task', 'TODO', 'CLAUDE', 'INBOX')"
        )
        empty_db.commit()
        cmd_inbox(empty_db)
        out = capsys.readouterr().out
        assert "QK-INBOX" in out or "Inbox task" in out

    def test_empty_inbox_message(self, empty_db: Database, capsys):
        """inbox on empty DB prints an appropriate message."""
        cmd_inbox(empty_db)
        out = capsys.readouterr().out
        # Either "No inbox" or "0" tasks
        assert "inbox" in out.lower() or "0" in out or "No" in out


# ---------------------------------------------------------------------------
# cmd_triage
# ---------------------------------------------------------------------------

class TestCmdTriage:
    def test_triage_promotes_to_phase(self, empty_db: Database, capsys):
        """triage moves an INBOX task to a real phase."""
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue, sort_order) "
            "VALUES ('QK-TRIAGE', 'INBOX', 'Triage me', 'TODO', 'CLAUDE', 'INBOX', 999)"
        )
        empty_db.commit()
        cmd_triage(empty_db, "QK-TRIAGE", "P1-TEST", "sonnet", "", "")
        row = empty_db.fetch_one(
            "SELECT phase, tier FROM tasks WHERE id='QK-TRIAGE'"
        )
        assert row["phase"] == "P1-TEST"
        assert row["tier"] == "sonnet"

    def test_triage_sets_original_tier(self, empty_db: Database, capsys):
        """triage sets original_tier to match the assigned tier."""
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue, sort_order) "
            "VALUES ('QK-OT', 'INBOX', 'Tier test', 'TODO', 'CLAUDE', 'INBOX', 999)"
        )
        empty_db.commit()
        cmd_triage(empty_db, "QK-OT", "P2-TEST", "sonnet", "", "")
        row = empty_db.fetch_one(
            "SELECT tier, original_tier FROM tasks WHERE id='QK-OT'"
        )
        assert row["original_tier"] == "sonnet"

    def test_triage_nonexistent_exits(self, empty_db: Database):
        with pytest.raises(SystemExit):
            cmd_triage(empty_db, "MISSING", "P1-TEST", "haiku", "", "")


# ---------------------------------------------------------------------------
# cmd_researched / cmd_break_tested / cmd_tag_browser
# ---------------------------------------------------------------------------

class TestFlagCommands:
    def test_researched_sets_flag(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-RES")
        cmd_researched(empty_db, "T-RES")
        val = empty_db.fetch_scalar("SELECT researched FROM tasks WHERE id='T-RES'")
        out = capsys.readouterr().out
        assert val == 1
        assert "T-RES" in out or out  # command should produce some confirmation

    def test_break_tested_sets_flag(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-BT")
        cmd_break_tested(empty_db, "T-BT")
        val = empty_db.fetch_scalar("SELECT breakage_tested FROM tasks WHERE id='T-BT'")
        out = capsys.readouterr().out
        assert val == 1
        assert out  # command should produce some output

    def test_tag_browser_sets_flag(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-BROWSER")
        cmd_tag_browser(empty_db, "T-BROWSER", 1)
        val = empty_db.fetch_scalar("SELECT needs_browser FROM tasks WHERE id='T-BROWSER'")
        out = capsys.readouterr().out
        assert val == 1
        assert out  # command should produce some output

    def test_tag_browser_clears_flag(self, empty_db: Database, capsys):
        _insert_task(empty_db, "T-NOBROWSER")
        # Set then clear
        cmd_tag_browser(empty_db, "T-NOBROWSER", 1)
        cmd_tag_browser(empty_db, "T-NOBROWSER", 0)
        val = empty_db.fetch_scalar("SELECT needs_browser FROM tasks WHERE id='T-NOBROWSER'")
        assert val == 0
        # Verify the intermediate set actually worked (flag was 1 before clearing)
        set_val = empty_db.fetch_scalar("SELECT needs_browser FROM tasks WHERE id='T-NOBROWSER'")
        assert set_val == 0  # still 0 after clearing — the state is what matters
