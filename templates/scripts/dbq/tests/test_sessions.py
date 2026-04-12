"""
Tests for session commands (sessions.py) and handover commands (handover.py).

Covers:
    sessions.py  — cmd_sessions, cmd_log, cmd_decisions, cmd_tag_session,
                   cmd_session_tags, cmd_session_file
    handover.py  — cmd_resume, cmd_handover
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from dbq.db import Database
from dbq.config import ProjectConfig
from dbq.commands.sessions import (
    cmd_sessions,
    cmd_log,
    cmd_decisions,
    cmd_tag_session,
    cmd_session_tags,
    cmd_session_file,
)
from dbq.commands.handover import cmd_resume, cmd_handover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subprocess_result(stdout: str = "", returncode: int = 0, stderr: str = ""):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# cmd_sessions
# ---------------------------------------------------------------------------

class TestCmdSessions:
    def test_empty_no_crash(self, empty_db: Database, capsys):
        """sessions command on empty table prints 'No sessions logged yet.'"""
        cmd_sessions(empty_db)
        out = capsys.readouterr().out
        assert "No sessions logged yet." in out

    def test_shows_logged_sessions(self, empty_db: Database, capsys):
        """sessions command shows a session that was previously inserted."""
        empty_db.execute(
            "INSERT INTO sessions (session_type, summary) VALUES (?, ?)",
            ("work", "Implemented eval layer"),
        )
        empty_db.commit()

        cmd_sessions(empty_db)
        out = capsys.readouterr().out
        assert "work" in out
        assert "Implemented eval layer" in out

    def test_multiple_sessions_shown(self, empty_db: Database, capsys):
        """sessions command shows all logged sessions."""
        empty_db.execute(
            "INSERT INTO sessions (session_type, summary) VALUES (?, ?)",
            ("plan", "Designed phase gates"),
        )
        empty_db.execute(
            "INSERT INTO sessions (session_type, summary) VALUES (?, ?)",
            ("work", "Fixed bug in output.py"),
        )
        empty_db.commit()

        cmd_sessions(empty_db)
        out = capsys.readouterr().out
        assert "plan" in out
        assert "Designed phase gates" in out
        assert "work" in out
        assert "Fixed bug in output.py" in out


# ---------------------------------------------------------------------------
# cmd_log
# ---------------------------------------------------------------------------

class TestCmdLog:
    def test_inserts_session(self, empty_db: Database, capsys):
        """log command inserts a row into the sessions table and prints confirmation."""
        cmd_log(empty_db, "work", "Completed eval tasks")
        out = capsys.readouterr().out

        row = empty_db.fetch_one(
            "SELECT session_type, summary FROM sessions LIMIT 1"
        )
        assert row is not None
        assert row["session_type"] == "work"
        assert row["summary"] == "Completed eval tasks"
        # Output should also confirm the session was logged
        assert "Session logged" in out or "work" in out

    def test_prints_confirmation(self, empty_db: Database, capsys):
        """log command prints a success message and persists to DB."""
        cmd_log(empty_db, "plan", "Reviewed blockers")
        out = capsys.readouterr().out
        assert "Session logged" in out
        assert "plan" in out
        # Verify DB write happened
        row = empty_db.fetch_one(
            "SELECT session_type, summary FROM sessions LIMIT 1"
        )
        assert row is not None
        assert row["session_type"] == "plan"

    def test_multiple_logs_accumulate(self, empty_db: Database, capsys):
        """Calling cmd_log twice inserts two distinct rows."""
        cmd_log(empty_db, "work", "First session")
        cmd_log(empty_db, "review", "Second session")

        rows = empty_db.fetch_all("SELECT summary FROM sessions ORDER BY id")
        assert len(rows) == 2
        assert rows[0]["summary"] == "First session"
        assert rows[1]["summary"] == "Second session"


# ---------------------------------------------------------------------------
# cmd_decisions
# ---------------------------------------------------------------------------

class TestCmdDecisions:
    def test_empty_no_crash(self, empty_db: Database, capsys):
        """decisions command on empty table prints 'No decisions logged yet.'"""
        cmd_decisions(empty_db)
        out = capsys.readouterr().out
        assert "No decisions logged yet." in out

    def test_shows_logged_decision(self, empty_db: Database, capsys):
        """decisions command shows a decision that was inserted."""
        empty_db.execute(
            "INSERT INTO decisions (choice, description) VALUES (?, ?)",
            ("Master", "Use SQLite over Postgres"),
        )
        empty_db.commit()

        cmd_decisions(empty_db)
        out = capsys.readouterr().out
        assert "Master" in out
        assert "Use SQLite over Postgres" in out

    def test_shows_multiple_decisions(self, empty_db: Database, capsys):
        """decisions command shows all recent decisions (up to 15)."""
        for i in range(3):
            empty_db.execute(
                "INSERT INTO decisions (choice, description) VALUES (?, ?)",
                ("Claude", f"Decision {i}"),
            )
        empty_db.commit()

        cmd_decisions(empty_db)
        out = capsys.readouterr().out
        for i in range(3):
            assert f"Decision {i}" in out


# ---------------------------------------------------------------------------
# cmd_tag_session
# ---------------------------------------------------------------------------

class TestCmdTagSession:
    def test_creates_git_tag_when_none_exist(self, simple_config: ProjectConfig, capsys):
        """tag-session creates a new session/YYYY-MM-DD/1 tag when no prior tags exist."""
        list_result = _make_subprocess_result(stdout="")
        tag_result = _make_subprocess_result(returncode=0)

        with patch("subprocess.run", side_effect=[list_result, tag_result]) as mock_run:
            cmd_tag_session(simple_config)

        out = capsys.readouterr().out
        assert "Tagged" in out
        # Second call should be the actual tag creation
        tag_call_args = mock_run.call_args_list[1]
        cmd_used = tag_call_args[0][0]
        assert "tag" in cmd_used
        # Tag name should follow session/YYYY-MM-DD/1 pattern
        tag_name_arg = cmd_used[-2]
        assert tag_name_arg.startswith("session/")
        assert tag_name_arg.endswith("/1")

    def test_increments_session_number(self, simple_config: ProjectConfig, capsys):
        """tag-session uses N+1 when N existing session tags are found."""
        existing_tags = "session/2026-01-01/1\nsession/2026-01-02/2\n"
        list_result = _make_subprocess_result(stdout=existing_tags)
        tag_result = _make_subprocess_result(returncode=0)

        with patch("subprocess.run", side_effect=[list_result, tag_result]) as mock_run:
            cmd_tag_session(simple_config)

        out = capsys.readouterr().out
        assert "Tagged" in out
        tag_call_args = mock_run.call_args_list[1]
        cmd_used = tag_call_args[0][0]
        tag_name_arg = cmd_used[-2]
        assert tag_name_arg.endswith("/3")

    def test_exits_on_git_failure(self, simple_config: ProjectConfig, capsys):
        """tag-session exits with code 1 when git tag command fails."""
        list_result = _make_subprocess_result(stdout="")
        tag_result = _make_subprocess_result(returncode=1, stderr="already exists")

        with patch("subprocess.run", side_effect=[list_result, tag_result]):
            with pytest.raises(SystemExit) as exc_info:
                cmd_tag_session(simple_config)

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Failed" in out


# ---------------------------------------------------------------------------
# cmd_session_tags
# ---------------------------------------------------------------------------

class TestCmdSessionTags:
    def test_no_tags_no_crash(self, simple_config: ProjectConfig, capsys):
        """session-tags prints 'No session tags yet.' when git has none."""
        list_result = _make_subprocess_result(stdout="")

        with patch("subprocess.run", return_value=list_result):
            cmd_session_tags(simple_config)

        out = capsys.readouterr().out
        assert "No session tags yet." in out

    def test_lists_tags(self, simple_config: ProjectConfig, capsys):
        """session-tags prints tag names along with sha and date info."""
        tags_output = "session/2026-03-28/1\nsession/2026-03-28/2\n"
        list_result = _make_subprocess_result(stdout=tags_output)
        date_result = _make_subprocess_result(stdout="2026-03-28 10:00:00 +0000\n")
        sha_result = _make_subprocess_result(stdout="abc1234\n")

        # Pattern: list_result, then for each tag: date_result + sha_result
        side_effects = [
            list_result,
            date_result, sha_result,
            date_result, sha_result,
        ]

        with patch("subprocess.run", side_effect=side_effects):
            cmd_session_tags(simple_config)

        out = capsys.readouterr().out
        assert "session/2026-03-28/1" in out
        assert "session/2026-03-28/2" in out
        assert "abc1234" in out


# ---------------------------------------------------------------------------
# cmd_session_file
# ---------------------------------------------------------------------------

class TestCmdSessionFile:
    def test_shows_file_content(self, simple_config: ProjectConfig, capsys):
        """session-file prints file content from the matching session tag."""
        find_result = _make_subprocess_result(stdout="session/2026-03-28/1\n")
        show_result = _make_subprocess_result(stdout="# File contents here\nline 2\n")

        with patch("subprocess.run", side_effect=[find_result, show_result]):
            cmd_session_file(simple_config, "1", "README.md")

        out = capsys.readouterr().out
        assert "README.md" in out
        assert "# File contents here" in out

    def test_exits_when_no_matching_tag(self, simple_config: ProjectConfig, capsys):
        """session-file exits with code 1 when no tag matches the session number."""
        find_result = _make_subprocess_result(stdout="")
        all_tags_result = _make_subprocess_result(stdout="")

        with patch("subprocess.run", side_effect=[find_result, all_tags_result]):
            with pytest.raises(SystemExit) as exc_info:
                cmd_session_file(simple_config, "99", "README.md")

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "No tag found for session 99" in out

    def test_prints_error_when_file_missing_at_tag(self, simple_config: ProjectConfig, capsys):
        """session-file prints error message when git show fails for the file."""
        find_result = _make_subprocess_result(stdout="session/2026-03-28/1\n")
        show_result = _make_subprocess_result(returncode=128, stdout="", stderr="not found")

        with patch("subprocess.run", side_effect=[find_result, show_result]):
            cmd_session_file(simple_config, "1", "missing.md")

        out = capsys.readouterr().out
        assert "not found" in out.lower() or "missing.md" in out


# ---------------------------------------------------------------------------
# cmd_resume
# ---------------------------------------------------------------------------

class TestCmdResume:
    def test_empty_db_no_crash(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """resume on an empty DB prints 'No actionable tasks found.'"""
        # Patch subprocess so _show_git_activity is a no-op
        no_tags = _make_subprocess_result(stdout="")
        with patch("subprocess.run", return_value=no_tags):
            cmd_resume(empty_db, simple_config)

        out = capsys.readouterr().out
        assert "No actionable tasks found." in out

    def test_shows_task_info(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """resume shows id and title for the next ready task."""
        no_tags = _make_subprocess_result(stdout="")
        with patch("subprocess.run", return_value=no_tags):
            cmd_resume(populated_db, populated_config)

        out = capsys.readouterr().out
        # T-02 is the next ready TODO task for CLAUDE (T-01 is DONE)
        assert "T-02" in out
        assert "Extract patterns" in out

    def test_task_override_finds_specific_task(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """resume with task_override shows the requested task even if not next in queue."""
        no_tags = _make_subprocess_result(stdout="")
        with patch("subprocess.run", return_value=no_tags):
            cmd_resume(populated_db, populated_config, task_override="T-01")

        out = capsys.readouterr().out
        assert "T-01" in out
        assert "Audit templates" in out

    def test_task_override_nonexistent_exits(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """resume with an unknown task_override exits with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_resume(populated_db, populated_config, task_override="NONEXISTENT")

        assert exc_info.value.code == 1

    def test_shows_in_progress_task_first(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """resume prefers IN_PROGRESS tasks over TODO tasks."""
        populated_db.execute(
            "UPDATE tasks SET status='IN_PROGRESS' WHERE id='T-02'"
        )
        populated_db.commit()

        no_tags = _make_subprocess_result(stdout="")
        with patch("subprocess.run", return_value=no_tags):
            cmd_resume(populated_db, populated_config)

        out = capsys.readouterr().out
        assert "T-02" in out
        assert "CONTINUING" in out

    def test_shows_git_activity_when_tags_exist(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """resume shows GIT ACTIVITY section when session tags are present."""
        tags_result = _make_subprocess_result(stdout="session/2026-03-01/1\n")
        diff_result = _make_subprocess_result(stdout=" some/file.py | 5 +++++\n 1 file changed\n")

        with patch("subprocess.run", side_effect=[tags_result, diff_result]):
            cmd_resume(populated_db, populated_config)

        out = capsys.readouterr().out
        assert "GIT ACTIVITY" in out


# ---------------------------------------------------------------------------
# cmd_handover
# ---------------------------------------------------------------------------

class TestCmdHandover:
    def test_adds_notes(self, populated_db: Database, capsys):
        """handover saves notes to an existing task and prints confirmation."""
        cmd_handover(populated_db, "T-02", "Left off after writing the extractor loop.")
        out = capsys.readouterr().out

        notes = populated_db.fetch_one(
            "SELECT handover_notes FROM tasks WHERE id='T-02'"
        )
        assert notes == "Left off after writing the extractor loop."
        assert "T-02" in out or "Handover" in out

    def test_prints_confirmation(self, populated_db: Database, capsys):
        """handover prints a confirmation message and persists notes to DB."""
        cmd_handover(populated_db, "T-02", "Some notes")
        out = capsys.readouterr().out
        assert "T-02" in out
        assert "Handover notes saved" in out
        # Verify DB write
        notes = populated_db.fetch_one(
            "SELECT handover_notes FROM tasks WHERE id='T-02'"
        )
        assert notes == "Some notes"

    def test_nonexistent_task_exits(self, empty_db: Database, capsys):
        """handover exits with code 1 when the task does not exist."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_handover(empty_db, "MISSING-99", "notes")

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "MISSING-99" in out

    def test_overwrites_existing_notes(self, populated_db: Database, capsys):
        """handover replaces any previously stored notes."""
        cmd_handover(populated_db, "T-02", "First note")
        cmd_handover(populated_db, "T-02", "Updated note")

        # fetch_one with a single-column SELECT returns the scalar value directly
        notes = populated_db.fetch_one(
            "SELECT handover_notes FROM tasks WHERE id='T-02'"
        )
        assert notes == "Updated note"
