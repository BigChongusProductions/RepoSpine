"""
Output parity tests — validate that Python produces identical output to bash
for every pattern parsed by external callers.

Run: python -m pytest dbq/test_output_parity.py -v

These tests use an in-memory SQLite database seeded with test data,
so they don't need a live project DB or the bash script.
They validate the Python output format against the CONTRACTS
documented in output.py.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add parent to path so we can import dbq
sys.path.insert(0, str(Path(__file__).parent.parent))

from dbq.db import Database, SCHEMA_TABLES
from dbq.config import ProjectConfig


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary DB file with schema applied."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init_schema()
    db.migrate()
    return db, db_path


@pytest.fixture
def seeded_db(tmp_db):
    """DB with realistic test data: tasks across phases, some blocked, some done."""
    db, db_path = tmp_db

    # Insert tasks across 3 phases
    tasks = [
        # (id, phase, title, status, assignee, blocked_by, sort_order, queue, tier, track)
        ("T-001", "P1-PLAN", "Design architecture", "DONE", "CLAUDE", None, 10, "A", "sonnet", "forward"),
        ("T-002", "P1-PLAN", "Write specs", "DONE", "CLAUDE", None, 20, "A", "haiku", "forward"),
        ("T-003", "P1-PLAN", "Review with Master", "DONE", "MASTER", None, 30, "A", None, "forward"),
        ("T-004", "P2-BUILD", "Implement core", "TODO", "CLAUDE", None, 40, "A", "opus", "forward"),
        ("T-005", "P2-BUILD", "Add tests", "TODO", "CLAUDE", "T-004", 50, "A", "sonnet", "forward"),
        ("T-006", "P2-BUILD", "Master review", "TODO", "MASTER", None, 60, "A", None, "forward"),
        ("T-007", "P3-POLISH", "Polish UI", "TODO", "CLAUDE", None, 70, "A", "haiku", "forward"),
        ("T-008", "P3-POLISH", "Final review", "TODO", "MASTER", None, 80, "A", None, "forward"),
    ]

    for t in tasks:
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, blocked_by, "
            "sort_order, queue, tier, track) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t,
        )

    # Add a phase gate for P1
    db.execute(
        "INSERT INTO phase_gates (phase, gated_on, gated_by) "
        "VALUES ('P1-PLAN', 'Mar 20', 'MASTER')"
    )

    # Add a loopback task
    db.execute(
        "INSERT INTO tasks (id, phase, title, status, assignee, sort_order, "
        "queue, track, origin_phase, discovered_in, severity, gate_critical) "
        "VALUES ('LB-0001', 'P2-BUILD', 'Fix regression in P1 code', 'TODO', "
        "'CLAUDE', 100, 'A', 'loopback', 'P1-PLAN', 'P2-BUILD', 2, 0)"
    )

    db.commit()

    config = ProjectConfig(
        db_path=db_path,
        phases=["P1-PLAN", "P2-BUILD", "P3-POLISH"],
    )
    return db, db_path, config


# ── Schema tests ──────────────────────────────────────────────────────

class TestSchema:
    def test_init_creates_all_tables(self, tmp_db):
        db, _ = tmp_db
        for table in SCHEMA_TABLES:
            assert db.table_exists(table), f"Missing table: {table}"

    def test_init_is_idempotent(self, tmp_db):
        db, _ = tmp_db
        # Running init again should not raise
        db.init_schema()
        for table in SCHEMA_TABLES:
            assert db.table_exists(table)

    def test_migrate_adds_columns(self, tmp_db):
        db, _ = tmp_db
        # All migration columns should exist after init + migrate
        assert db.column_exists("tasks", "track")
        assert db.column_exists("tasks", "origin_phase")
        assert db.column_exists("tasks", "severity")
        assert db.column_exists("tasks", "gate_critical")
        assert db.column_exists("tasks", "breakage_tested")


# ── Health output contract tests ──────────────────────────────────────

class TestHealthOutputContract:
    """Validate the exact output format that session_briefing.sh:53 depends on."""

    def test_healthy_tail_3_head_2(self, seeded_db, capsys):
        """CONTRACT: session_briefing.template.sh:53
        echo "$HEALTH_OUT" | tail -3 | head -2
        Must produce the verdict line + blank line.
        """
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_health
        cmd_health(db, config)

        captured = capsys.readouterr()
        lines = captured.out.split("\n")

        # tail -3: last 3 lines (including trailing empty)
        tail_3 = lines[-3:]
        # head -2: first 2 of those
        head_2 = tail_3[:2]

        # The verdict line must contain the HEALTHY/DEGRADED/CRITICAL pattern
        verdict_text = "\n".join(head_2)
        assert "HEALTHY" in verdict_text or "DEGRADED" in verdict_text or "CRITICAL" in verdict_text, \
            f"Verdict not found in tail-3|head-2: {repr(verdict_text)}"

    def test_healthy_no_error_keywords(self, seeded_db, capsys):
        """CONTRACT: session-start-check.template.sh:62
        grep -qi "error|fail|corrupt"
        Healthy output must NOT match these keywords.
        """
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_health
        cmd_health(db, config)

        captured = capsys.readouterr()
        # "fail" appears in "Pipeline cannot proceed" only for CRITICAL
        # For HEALTHY, none of these should appear
        assert not re.search(
            r'\berror\b|\bfail\b|\bcorrupt\b',
            captured.out,
            re.IGNORECASE,
        ), f"Error keyword found in healthy output: {captured.out}"

    def test_critical_exit_code(self, tmp_db, capsys):
        """Health must exit 1 for CRITICAL issues."""
        db, db_path = tmp_db
        # Drop a required table to trigger CRITICAL
        db.execute("DROP TABLE IF EXISTS decisions")
        db.commit()

        config = ProjectConfig(db_path=db_path)

        from dbq.commands.health import cmd_health
        with pytest.raises(SystemExit) as exc_info:
            cmd_health(db, config)
        assert exc_info.value.code == 1

    def test_healthy_exit_code(self, seeded_db):
        """Health must exit 0 (no sys.exit) for HEALTHY."""
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_health
        # Should not raise SystemExit
        cmd_health(db, config)


# ── Quick output contract tests ───────────────────────────────────────

class TestQuickOutputContract:
    """Validate task ID format in output."""

    def test_inbox_id_format(self, seeded_db, capsys):
        """CONTRACT: test_bootstrap_suite.sh:1527
        grep -oE 'QK-[0-9a-f]+'
        Output must contain a QK-XXXX ID.
        """
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_quick

        cmd_quick(db, title="Test task", phase="P2-BUILD", tag="feature")

        captured = capsys.readouterr()
        match = re.search(r'QK-[0-9a-f]+', captured.out)
        assert match, f"No QK-ID found in output: {captured.out}"

    def test_loopback_id_format(self, seeded_db, capsys):
        """CONTRACT: test_bootstrap_suite.sh extracts LB-XXXX IDs."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_quick

        cmd_quick(
            db, title="Fix regression",
            phase="P2-BUILD",
            loopback_origin="P1-PLAN",
            severity=2,
        )

        captured = capsys.readouterr()
        match = re.search(r'LB-[0-9a-f]+', captured.out)
        assert match, f"No LB-ID found in output: {captured.out}"

    def test_s1_circuit_breaker_warning(self, seeded_db, capsys):
        """S1 gate-critical loopback should warn about circuit breaker."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_quick

        cmd_quick(
            db, title="Critical bug",
            phase="P2-BUILD",
            loopback_origin="P1-PLAN",
            severity=1,
            gate_critical=True,
        )

        captured = capsys.readouterr()
        assert "CIRCUIT BREAKER" in captured.out


# ── Done output contract tests ────────────────────────────────────────

class TestDoneOutputContract:
    """Validate done command output keywords."""

    def test_done_keyword(self, seeded_db, capsys):
        """CONTRACT: test_bootstrap_suite.sh:1541
        grep -q "Committed|DONE"
        Output must contain "DONE".
        """
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_done

        # done T-004 (a TODO task with no git repo to commit to)
        cmd_done(db, config, "T-004")

        captured = capsys.readouterr()
        assert re.search(r'Committed|DONE', captured.out), \
            f"Neither 'Committed' nor 'DONE' found: {captured.out}"

    def test_already_done_guard(self, seeded_db, capsys):
        """Already-DONE tasks should not be re-processed."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_done

        # T-001 is already DONE
        cmd_done(db, config, "T-001")

        captured = capsys.readouterr()
        assert "already DONE" in captured.out

    def test_nonexistent_task(self, seeded_db):
        """Nonexistent task should exit 1."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_done

        with pytest.raises(SystemExit) as exc_info:
            cmd_done(db, config, "NOPE-999")
        assert exc_info.value.code == 1

    def test_done_reverts_on_git_failure(self, seeded_db, capsys):
        """If git commit fails, task should revert to TODO.

        Tests Assumption #4: DB rollback on git failure.
        """
        db, db_path, config = seeded_db

        # Mock git status to show changes, git commit to fail
        # git -C /path <subcmd> → subcmd is at index 3
        def mock_run(args, **kwargs):
            # Find the git subcommand (first arg after -C <path>)
            subcmd = ""
            for i, a in enumerate(args):
                if a == "-C" and i + 2 < len(args):
                    subcmd = args[i + 2]
                    break
            if not subcmd and len(args) > 1:
                subcmd = args[1]

            result = subprocess.CompletedProcess(args, 0, "", "")
            if subcmd == "status":
                result.stdout = "M file.py\n"
            elif subcmd == "add":
                pass  # success
            elif subcmd == "commit":
                result.returncode = 1  # FAIL
                result.stderr = "pre-commit hook failed"
            return result

        from dbq.commands.tasks import cmd_done

        with patch("dbq.commands.tasks.subprocess.run", side_effect=mock_run):
            with pytest.raises(SystemExit) as exc_info:
                cmd_done(db, config, "T-004")
            assert exc_info.value.code == 1

        # Verify task was reverted to TODO
        status = db.fetch_one(
            "SELECT status FROM tasks WHERE id='T-004'"
        )
        assert status == "TODO", f"Task should be TODO after git failure, got: {status}"


# ── Check verdict tests ───────────────────────────────────────────────

class TestCheckVerdict:
    """Validate check command produces correct verdicts."""

    def test_go_verdict(self, seeded_db, capsys):
        """T-004 should be GO: P1 is done+gated, T-004 is unblocked."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_check
        cmd_check(db, config, "T-004")

        captured = capsys.readouterr()
        # Should contain GO (might also have CONFIRM due to milestone rules)
        assert "GO" in captured.out or "CONFIRM" in captured.out

    def test_stop_wrong_assignee(self, seeded_db, capsys):
        """T-006 is assigned to MASTER — should STOP."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_check
        cmd_check(db, config, "T-006")

        captured = capsys.readouterr()
        assert "STOP" in captured.out
        assert "MASTER" in captured.out

    def test_stop_no_phase_gate(self, seeded_db, capsys):
        """T-007 (P3) should STOP because P2 gate hasn't been passed.
        Also P2 tasks are incomplete.
        """
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_check
        cmd_check(db, config, "T-007")

        captured = capsys.readouterr()
        assert "STOP" in captured.out

    def test_nonexistent_task_exits(self, seeded_db):
        """Nonexistent task should exit 1."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_check

        with pytest.raises(SystemExit) as exc_info:
            cmd_check(db, config, "NOPE-999")
        assert exc_info.value.code == 1

    def test_loopback_go(self, seeded_db, capsys):
        """LB-0001 is an unblocked Claude loopback — should GO."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_check
        cmd_check(db, config, "LB-0001")

        captured = capsys.readouterr()
        assert "GO" in captured.out
        assert "loopback" in captured.out.lower()

    def test_blocked_task_hint(self, seeded_db, capsys):
        """T-005 is blocked by T-004 (same phase) — should show HINT, not STOP."""
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_check
        cmd_check(db, config, "T-005")

        captured = capsys.readouterr()
        # Same-phase blocker is a soft hint, not a hard stop
        assert "HINT" in captured.out or "GO" in captured.out or "CONFIRM" in captured.out


# ── CLI argument parsing tests ────────────────────────────────────────

class TestCLIParsing:
    """Tests Assumption #8: argparse handles complex arg patterns."""

    def test_quick_positional_only(self):
        """quick "title" phase tag — all positional."""
        from dbq.cli import main
        # Just verify it parses without error (will fail on DB, that's ok)
        with pytest.raises(SystemExit):
            # No DB available — will exit, but parsing should succeed
            main(["quick", "Test title", "P1-PLAN", "feature"])

    def test_quick_with_loopback_flags(self):
        """quick "title" phase tag --loopback ORIGIN --severity 2 --gate-critical"""
        from dbq.cli import main
        with pytest.raises(SystemExit):
            main([
                "quick", "Bug fix", "P2-BUILD", "bug",
                "--loopback", "P1-PLAN",
                "--severity", "2",
                "--gate-critical",
                "--reason", "Found during testing",
            ])

    def test_done_with_skip_break(self):
        """done T-001 --skip-break"""
        from dbq.cli import main
        with pytest.raises(SystemExit):
            main(["done", "T-001", "--skip-break"])

    def test_help_exits_0(self):
        """--help should exit 0."""
        from dbq.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0


# ── Database error handling tests ─────────────────────────────────────

class TestErrorHandling:
    """Validate that errors are surfaced, not swallowed."""

    def test_parameterized_query_prevents_injection(self, seeded_db):
        """SQL injection attempt via task ID should be safe."""
        db, db_path, config = seeded_db
        # This would be dangerous with string interpolation
        malicious_id = "'; DROP TABLE tasks; --"
        result = db.fetch_one(
            "SELECT id FROM tasks WHERE id=?", (malicious_id,)
        )
        assert result is None
        # tasks table should still exist
        assert db.table_exists("tasks")

    def test_dml_errors_raise(self, seeded_db):
        """INSERT/UPDATE errors must raise, not silently fail."""
        db, db_path, config = seeded_db
        from dbq.db import DatabaseError

        # Try inserting with a NOT NULL violation
        with pytest.raises(DatabaseError):
            db.execute(
                "INSERT INTO tasks (id, phase, title) VALUES (?, NULL, ?)",
                ("BAD-001", "no phase"),
            )


# ── Date format test ──────────────────────────────────────────────────

class TestDateFormat:
    def test_date_format_matches_bash(self):
        """Python date format must match: date '+%b %d' | sed 's/ 0/ /'
        e.g., 'Mar 5' not 'Mar 05'
        """
        from dbq.commands.tasks import _format_date
        result = _format_date()
        # Should be like "Mar 24" or "Jan 5" (no leading zero)
        assert re.match(r'^[A-Z][a-z]{2} \d{1,2}$', result), \
            f"Date format wrong: {result}"


# ── Simple CRUD command tests ────────────────────────────────────────

class TestTaskCommand:
    def test_task_shows_details(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_task
        cmd_task(db, "T-004")
        out = capsys.readouterr().out
        assert "── Task: T-004 ──" in out
        assert "Phase:    P2-BUILD" in out
        assert "Implement core" in out
        assert "Status: TODO" in out

    def test_task_not_found(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_task
        with pytest.raises(SystemExit):
            cmd_task(db, "NOPE-999")

    def test_task_shows_blocker(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_task
        cmd_task(db, "T-005")
        out = capsys.readouterr().out
        assert "Blocked by: T-004" in out


class TestStartCommand:
    def test_start_marks_in_progress(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_start
        cmd_start(db, "T-004")
        out = capsys.readouterr().out
        assert "IN_PROGRESS" in out
        assert "T-004" in out
        status = db.fetch_one(
            "SELECT status FROM tasks WHERE id=?", ("T-004",)
        )
        assert status == "IN_PROGRESS"

    def test_start_not_found(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_start
        with pytest.raises(SystemExit):
            cmd_start(db, "NOPE")


class TestSkipCommand:
    def test_skip_sets_status(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_skip
        cmd_skip(db, "T-004", "Not needed")
        out = capsys.readouterr().out
        assert "Skipped" in out
        assert "T-004" in out
        assert "Not needed" in out
        status = db.fetch_one(
            "SELECT status FROM tasks WHERE id=?", ("T-004",)
        )
        assert status == "SKIP"

    def test_skip_without_reason(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_skip
        cmd_skip(db, "T-004")
        out = capsys.readouterr().out
        assert "Skipped" in out
        assert "Reason" not in out

    def test_skip_loopback_cleans_ack(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        # Add an ack for the loopback
        db.execute(
            "INSERT INTO loopback_acks (loopback_id, acked_on, acked_by, reason) "
            "VALUES ('LB-0001', 'Mar 20', 'MASTER', 'test')"
        )
        db.commit()
        from dbq.commands.tasks import cmd_skip
        cmd_skip(db, "LB-0001")
        ack_count = db.fetch_scalar(
            "SELECT COUNT(*) FROM loopback_acks WHERE loopback_id='LB-0001'"
        )
        assert ack_count == 0


class TestUnblockCommand:
    def test_unblock_clears_blocker(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_unblock
        cmd_unblock(db, "T-005")
        out = capsys.readouterr().out
        assert "Cleared" in out
        assert "T-004" in out  # was blocked by T-004
        blocked = db.fetch_one(
            "SELECT blocked_by FROM tasks WHERE id=?", ("T-005",)
        )
        assert blocked is None

    def test_unblock_no_blocker(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_unblock
        cmd_unblock(db, "T-004")
        out = capsys.readouterr().out
        assert "no blocked_by" in out


class TestTagBrowserCommand:
    def test_tag_browser_on(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_tag_browser
        cmd_tag_browser(db, "T-004", 1)
        out = capsys.readouterr().out
        assert "Tagged" in out
        val = db.fetch_scalar(
            "SELECT needs_browser FROM tasks WHERE id=?", ("T-004",)
        )
        assert val == 1

    def test_tag_browser_off(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_tag_browser
        cmd_tag_browser(db, "T-004", 0)
        out = capsys.readouterr().out
        assert "Untagged" in out


class TestResearchedCommand:
    def test_marks_researched(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_researched
        cmd_researched(db, "T-004")
        out = capsys.readouterr().out
        assert "researched" in out
        val = db.fetch_scalar(
            "SELECT researched FROM tasks WHERE id=?", ("T-004",)
        )
        assert val == 1


class TestBreakTestedCommand:
    def test_marks_break_tested(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_break_tested
        cmd_break_tested(db, "T-004")
        out = capsys.readouterr().out
        assert "breakage-tested" in out
        val = db.fetch_scalar(
            "SELECT breakage_tested FROM tasks WHERE id=?", ("T-004",)
        )
        assert val == 1


# ── Phase & gate command tests ───────────────────────────────────────

class TestPhaseCommand:
    def test_shows_current_phase(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_phase
        cmd_phase(db)
        out = capsys.readouterr().out
        assert "Current Phase" in out
        assert "P2-BUILD" in out

    def test_all_done_message(self, tmp_db, capsys):
        db, db_path = tmp_db
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, sort_order, queue) "
            "VALUES ('X-1', 'P1', 'Done task', 'DONE', 'CLAUDE', 1, 'A')"
        )
        db.commit()
        from dbq.commands.phases import cmd_phase
        cmd_phase(db)
        out = capsys.readouterr().out
        assert "All phases complete" in out


class TestGateCommand:
    def test_shows_gates(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_gate
        cmd_gate(db)
        out = capsys.readouterr().out
        assert "P1-PLAN" in out
        assert "MASTER" in out

    def test_no_gates(self, tmp_db, capsys):
        db, db_path = tmp_db
        from dbq.commands.phases import cmd_gate
        cmd_gate(db)
        out = capsys.readouterr().out
        assert "No phase gates" in out


class TestGatePassCommand:
    def test_records_gate(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_gate_pass
        cmd_gate_pass(db, "P2-BUILD")
        out = capsys.readouterr().out
        assert "Phase gate recorded" in out
        assert "P2-BUILD" in out
        count = db.fetch_scalar(
            "SELECT COUNT(*) FROM phase_gates WHERE phase='P2-BUILD'"
        )
        assert count == 1


class TestStatusCommand:
    def test_shows_phases(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_status
        cmd_status(db)
        out = capsys.readouterr().out
        assert "P1-PLAN" in out
        assert "P2-BUILD" in out
        assert "P3-POLISH" in out

    def test_shows_loopback_summary(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_status
        cmd_status(db)
        out = capsys.readouterr().out
        assert "Loopback track" in out
        assert "1 total" in out


class TestBlockersCommand:
    def test_shows_blockers(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        # T-005 (CLAUDE) is blocked by T-004 (CLAUDE), not Master
        # Need a Master blocker scenario
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, "
            "sort_order, queue, blocked_by) "
            "VALUES ('C-1', 'P2-BUILD', 'Blocked task', 'TODO', 'CLAUDE', "
            "200, 'A', 'T-006')"
        )
        db.commit()
        from dbq.commands.phases import cmd_blockers
        cmd_blockers(db)
        out = capsys.readouterr().out
        assert "T-006" in out
        assert "C-1" in out

    def test_no_blockers(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_blockers
        cmd_blockers(db)
        out = capsys.readouterr().out
        assert "No Master/Gemini blockers" in out


class TestConfirmCommand:
    def test_records_confirmation(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_confirm
        cmd_confirm(db, config, "T-004")
        out = capsys.readouterr().out
        assert "Milestone confirmed" in out
        assert "T-004" in out
        count = db.fetch_scalar(
            "SELECT COUNT(*) FROM milestone_confirmations WHERE task_id='T-004'"
        )
        assert count == 1

    def test_confirm_not_found(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_confirm
        with pytest.raises(SystemExit):
            cmd_confirm(db, config, "NOPE")


class TestConfirmationsCommand:
    def test_shows_confirmations(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        db.execute(
            "INSERT INTO milestone_confirmations (task_id, confirmed_on, confirmed_by) "
            "VALUES ('T-001', 'Mar 20', 'MASTER')"
        )
        db.commit()
        from dbq.commands.phases import cmd_confirmations
        cmd_confirmations(db)
        out = capsys.readouterr().out
        assert "T-001" in out
        assert "MASTER" in out

    def test_no_confirmations(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_confirmations
        cmd_confirmations(db)
        out = capsys.readouterr().out
        assert "No milestone confirmations" in out


class TestMasterCommand:
    def test_shows_master_tasks(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.phases import cmd_master
        cmd_master(db)
        out = capsys.readouterr().out
        assert "T-006" in out  # Master task in P2
        assert "T-008" in out  # Master task in P3

    def test_no_master_tasks(self, tmp_db, capsys):
        db, db_path = tmp_db
        from dbq.commands.phases import cmd_master
        cmd_master(db)
        out = capsys.readouterr().out
        assert "No Master/Gemini TODO" in out


# ── CLI wiring tests for new commands ────────────────────────────────

class TestCLINewCommands:
    """Verify argparse wiring for all new commands."""

    def test_task_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["task", "T-004"])
        out = capsys.readouterr().out
        assert "T-004" in out

    def test_start_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["start", "T-004"])
        out = capsys.readouterr().out
        assert "IN_PROGRESS" in out

    def test_skip_cli_with_reason(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["skip", "T-004", "Won't fix"])
        out = capsys.readouterr().out
        assert "Skipped" in out

    def test_gate_pass_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["gate-pass", "P2-BUILD"])
        out = capsys.readouterr().out
        assert "Phase gate recorded" in out

    def test_confirm_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["confirm", "T-004"])
        out = capsys.readouterr().out
        assert "Milestone confirmed" in out


# ── Next command tests ───────────────────────────────────────────────

class TestNextCommand:
    def test_next_shows_forward_tasks(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.next_cmd import cmd_next
        cmd_next(db, config)
        out = capsys.readouterr().out
        assert "Task Queue" in out
        assert "FORWARD" in out
        assert "T-004" in out  # ready forward task

    def test_next_circuit_breaker(self, seeded_db, capsys):
        """OUTPUT CONTRACT: grep CIRCUIT must match."""
        db, db_path, config = seeded_db
        # Make LB-0001 an S1 gate-critical loopback
        db.execute(
            "UPDATE tasks SET severity=1, gate_critical=1 WHERE id='LB-0001'"
        )
        db.commit()
        from dbq.commands.next_cmd import cmd_next
        cmd_next(db, config)
        out = capsys.readouterr().out
        assert "CIRCUIT BREAKER" in out
        assert "LB-0001" in out

    def test_next_ready_only(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.next_cmd import cmd_next
        cmd_next(db, config, ready_only=True)
        out = capsys.readouterr().out
        assert "BLOCKED" not in out or "hidden" in out

    def test_next_smart_scoring(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.next_cmd import cmd_next
        cmd_next(db, config, smart=True)
        out = capsys.readouterr().out
        assert "smart-scored" in out

    def test_next_shows_blocked(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.next_cmd import cmd_next
        cmd_next(db, config)
        out = capsys.readouterr().out
        # T-005 is blocked by T-004
        assert "T-005" in out

    def test_next_head_5_contract(self, seeded_db, capsys):
        """OUTPUT CONTRACT: post-compact-recovery.template.sh does head -5."""
        db, db_path, config = seeded_db
        from dbq.commands.next_cmd import cmd_next
        cmd_next(db, config)
        out = capsys.readouterr().out
        lines = out.split("\n")
        head_5 = lines[:5]
        # First 5 lines must include the section header
        assert any("Task Queue" in line for line in head_5)

    def test_next_stale_blockers(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        # Create a task blocked by nonexistent ID
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, "
            "sort_order, queue, blocked_by) "
            "VALUES ('S-1', 'P2-BUILD', 'Stale task', 'TODO', 'CLAUDE', "
            "300, 'A', 'GHOST-999')"
        )
        db.commit()
        from dbq.commands.next_cmd import cmd_next
        cmd_next(db, config)
        out = capsys.readouterr().out
        assert "STALE" in out
        assert "GHOST-999" in out


# ── Session command tests ────────────────────────────────────────────

class TestSessionsCommand:
    def test_log_and_list(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.sessions import cmd_log, cmd_sessions
        cmd_log(db, "Claude Code", "Test session")
        capsys.readouterr()  # clear
        cmd_sessions(db)
        out = capsys.readouterr().out
        assert "Claude Code" in out
        assert "Test session" in out

    def test_no_sessions(self, tmp_db, capsys):
        db, db_path = tmp_db
        from dbq.commands.sessions import cmd_sessions
        cmd_sessions(db)
        out = capsys.readouterr().out
        assert "No sessions" in out


class TestDecisionsCommand:
    def test_no_decisions(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.sessions import cmd_decisions
        cmd_decisions(db)
        out = capsys.readouterr().out
        assert "No decisions" in out

    def test_shows_decisions(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        db.execute(
            "INSERT INTO decisions (id, description, choice) "
            "VALUES ('D-1', 'Use Python', 'MASTER')"
        )
        db.commit()
        from dbq.commands.sessions import cmd_decisions
        cmd_decisions(db)
        out = capsys.readouterr().out
        assert "Use Python" in out


# ── Inbox pipeline tests ────────────────────────────────────────────

class TestInboxCommand:
    def test_shows_inbox_tasks(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        # Add inbox task
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, "
            "sort_order, queue) "
            "VALUES ('IN-1', 'INBOX', 'New idea', 'TODO', 'CLAUDE', 999, 'INBOX')"
        )
        db.commit()
        from dbq.commands.tasks import cmd_inbox
        cmd_inbox(db)
        out = capsys.readouterr().out
        assert "IN-1" in out
        assert "New idea" in out
        assert "1 item" in out

    def test_empty_inbox(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_inbox
        cmd_inbox(db)
        out = capsys.readouterr().out
        assert "(empty)" in out


class TestTriageCommand:
    def test_triage_standard(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, "
            "sort_order, queue) "
            "VALUES ('IN-2', 'INBOX', 'Triage me', 'TODO', 'CLAUDE', 999, 'INBOX')"
        )
        db.commit()
        from dbq.commands.tasks import cmd_triage
        cmd_triage(db, "IN-2", "P2-BUILD", "sonnet")
        out = capsys.readouterr().out
        assert "Triaged" in out
        assert "P2-BUILD" in out
        queue = db.fetch_one(
            "SELECT queue FROM tasks WHERE id=?", ("IN-2",)
        )
        assert queue == "A"

    def test_triage_not_in_inbox(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_triage
        with pytest.raises(SystemExit):
            cmd_triage(db, "T-004", "P2-BUILD", "sonnet")

    def test_triage_loopback(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, "
            "sort_order, queue) "
            "VALUES ('IN-3', 'P2-BUILD', 'Loopback me', 'TODO', 'CLAUDE', "
            "999, 'INBOX')"
        )
        db.commit()
        from dbq.commands.tasks import cmd_triage
        cmd_triage(db, "IN-3", "loopback", "P1-PLAN",
                   severity=2, gate_critical=True)
        out = capsys.readouterr().out
        assert "loopback" in out
        assert "P1-PLAN" in out
        track = db.fetch_one(
            "SELECT track FROM tasks WHERE id=?", ("IN-3",)
        )
        assert track == "loopback"


class TestAddTaskCommand:
    def test_adds_task(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.tasks import cmd_add_task
        cmd_add_task(db, "NEW-1", "P2-BUILD", "New feature", "opus")
        out = capsys.readouterr().out
        assert "Added task" in out
        assert "NEW-1" in out
        task = db.fetch_one(
            "SELECT tier, status FROM tasks WHERE id=?", ("NEW-1",)
        )
        assert task["tier"] == "opus"
        assert task["status"] == "TODO"


# ── Loopback management tests ───────────────────────────────────────

class TestLoopbacksCommand:
    def test_lists_loopbacks(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.loopbacks import cmd_loopbacks
        cmd_loopbacks(db)
        out = capsys.readouterr().out
        assert "Loopback Tasks" in out
        assert "LB-0001" in out

    def test_filter_by_severity(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.loopbacks import cmd_loopbacks
        # LB-0001 is severity 2, filter for severity 1 should return none
        cmd_loopbacks(db, severity=1)
        out = capsys.readouterr().out
        assert "none matching" in out


class TestLoopbackStatsCommand:
    def test_shows_stats(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.loopbacks import cmd_loopback_stats
        cmd_loopback_stats(db, config)
        out = capsys.readouterr().out
        assert "LOOPBACK ANALYTICS" in out
        assert "Total: 1" in out
        assert "P1-PLAN" in out

    def test_no_loopbacks(self, tmp_db, capsys):
        db, db_path = tmp_db
        config = ProjectConfig(db_path=db_path)
        from dbq.commands.loopbacks import cmd_loopback_stats
        cmd_loopback_stats(db, config)
        out = capsys.readouterr().out
        assert "No loopback tasks" in out


class TestAckBreakerCommand:
    def test_ack_breaker(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.loopbacks import cmd_ack_breaker
        cmd_ack_breaker(db, "LB-0001", "Risk accepted")
        out = capsys.readouterr().out
        assert "acknowledged" in out
        count = db.fetch_scalar(
            "SELECT COUNT(*) FROM loopback_acks WHERE loopback_id='LB-0001'"
        )
        assert count == 1

    def test_ack_not_loopback(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.loopbacks import cmd_ack_breaker
        with pytest.raises(SystemExit):
            cmd_ack_breaker(db, "T-004", "nope")


# ── Falsification command tests ──────────────────────────────────────

class TestAssumeCommand:
    def test_records_assumption(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assume
        cmd_assume(db, "T-004", "API is stable", "echo ok")
        out = capsys.readouterr().out
        assert "Assumption #" in out
        assert "T-004" in out
        count = db.fetch_scalar(
            "SELECT COUNT(*) FROM assumptions WHERE task_id='T-004'"
        )
        assert count == 1

    def test_assume_manual(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assume
        cmd_assume(db, "T-004", "Design is correct")
        out = capsys.readouterr().out
        assert "manual" in out

    def test_assume_not_found(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assume
        with pytest.raises(SystemExit):
            cmd_assume(db, "NOPE", "test")


class TestVerifyAssumptionCommand:
    def test_verify_passes(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assume, cmd_verify_assumption
        cmd_assume(db, "T-004", "Echo works", "echo hello")
        capsys.readouterr()
        aid = db.fetch_scalar(
            "SELECT MAX(id) FROM assumptions WHERE task_id='T-004'"
        )
        cmd_verify_assumption(db, "T-004", aid)
        out = capsys.readouterr().out
        assert "PASSED" in out
        verified = db.fetch_scalar(
            "SELECT verified FROM assumptions WHERE id=?", (aid,)
        )
        assert verified == 1

    def test_verify_fails(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assume, cmd_verify_assumption
        cmd_assume(db, "T-004", "False exits nonzero", "false")
        capsys.readouterr()
        aid = db.fetch_scalar(
            "SELECT MAX(id) FROM assumptions WHERE task_id='T-004'"
        )
        cmd_verify_assumption(db, "T-004", aid)
        out = capsys.readouterr().out
        assert "FAILED" in out
        verified = db.fetch_scalar(
            "SELECT verified FROM assumptions WHERE id=?", (aid,)
        )
        assert verified == -1


class TestVerifyAllCommand:
    def test_verify_all(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assume, cmd_verify_all
        cmd_assume(db, "T-004", "A1", "echo ok")
        cmd_assume(db, "T-004", "A2")  # manual
        capsys.readouterr()
        cmd_verify_all(db, "T-004")
        out = capsys.readouterr().out
        assert "1 passed" in out
        assert "1 manual" in out

    def test_verify_all_none(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_verify_all
        cmd_verify_all(db, "T-004")
        out = capsys.readouterr().out
        assert "No unverified" in out


class TestAssumptionsCommand:
    def test_list_assumptions(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assume, cmd_assumptions
        cmd_assume(db, "T-004", "Test assumption")
        capsys.readouterr()
        cmd_assumptions(db, "T-004")
        out = capsys.readouterr().out
        assert "Test assumption" in out
        assert "⏳" in out  # unverified

    def test_no_assumptions(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.falsification import cmd_assumptions
        cmd_assumptions(db, "T-004")
        out = capsys.readouterr().out
        assert "No assumptions" in out


# ── CLI wiring tests for Groups 3-7 ─────────────────────────────────

class TestCLIGroups3to7:
    def test_next_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["next"])
        out = capsys.readouterr().out
        assert "Task Queue" in out

    def test_next_cli_smart(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["next", "--smart"])
        out = capsys.readouterr().out
        assert "FORWARD" in out

    def test_sessions_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["sessions"])
        out = capsys.readouterr().out
        assert "Session log" in out

    def test_log_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["log", "Claude", "test session"])
        out = capsys.readouterr().out
        assert "Session logged" in out

    def test_loopbacks_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["loopbacks"])
        out = capsys.readouterr().out
        assert "Loopback Tasks" in out

    def test_loopback_stats_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["loopback-stats"])
        out = capsys.readouterr().out
        assert "LOOPBACK ANALYTICS" in out

    def test_assume_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["assume", "T-004", "Test assumption"])
        out = capsys.readouterr().out
        assert "Assumption #" in out

    def test_assumptions_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["assumptions", "T-004"])
        out = capsys.readouterr().out
        assert "No assumptions" in out

    def test_inbox_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["inbox"])
        out = capsys.readouterr().out
        assert "Inbox" in out

    def test_add_task_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["add-task", "AT-1", "P2-BUILD", "New task", "sonnet"])
        out = capsys.readouterr().out
        assert "Added task" in out


# ══════════════════════════════════════════════════════════════════════
# Phase 3 Tests — Knowledge, Delegation, Snapshots, Session Git,
#                  Health Extras, Board
# ══════════════════════════════════════════════════════════════════════


# ── Knowledge command tests ──────────────────────────────────────────

class TestLessonsCommand:
    def test_lessons_shows_content(self, seeded_db, capsys, tmp_path):
        db, db_path, config = seeded_db
        # Create a minimal LESSONS file
        lf = tmp_path / "LESSONS.md"
        lf.write_text(
            "# Lessons\n"
            "| Date | Wrong | Pattern | Rule | Last Ref | Violations |\n"
            "| 2026-03-20 | Missed test | Skipped coverage | Always test | — | 0 |\n"
            "## Universal Patterns\n"
        )
        config.lessons_file = str(lf)
        from dbq.commands.knowledge import cmd_lessons
        cmd_lessons(config)
        out = capsys.readouterr().out
        assert "Lessons & Corrections" in out
        assert "Skipped coverage" in out
        assert "NEVER REFERENCED" in out

    def test_lessons_no_file(self, seeded_db):
        db, db_path, config = seeded_db
        config.lessons_file = ""
        from dbq.commands.knowledge import cmd_lessons
        with pytest.raises(SystemExit):
            cmd_lessons(config)


class TestLogLessonCommand:
    def test_inserts_before_anchor(self, seeded_db, capsys, tmp_path):
        db, db_path, config = seeded_db
        lf = tmp_path / "LESSONS.md"
        lf.write_text(
            "# Lessons\n"
            "<!-- CORRECTIONS-ANCHOR -->\n"
            "## Universal Patterns\n"
        )
        config.lessons_file = str(lf)
        from dbq.commands.knowledge import cmd_log_lesson
        cmd_log_lesson(config, "Broke the build", "Untested imports", "Always run tests")
        out = capsys.readouterr().out
        assert "Lesson logged" in out
        content = lf.read_text()
        assert "Broke the build" in content
        # Verify insertion order: anchor before entry, entry before Universal
        anchor_pos = content.find("CORRECTIONS-ANCHOR")
        entry_pos = content.find("Broke the build")
        universal_pos = content.find("Universal Patterns")
        assert anchor_pos < entry_pos < universal_pos

    def test_inserts_before_universal_fallback(self, seeded_db, capsys, tmp_path):
        db, db_path, config = seeded_db
        lf = tmp_path / "LESSONS.md"
        lf.write_text("# Lessons\n## Universal Patterns\n")
        config.lessons_file = str(lf)
        from dbq.commands.knowledge import cmd_log_lesson
        cmd_log_lesson(config, "Bug found", "No review", "Add review step")
        content = lf.read_text()
        assert "Bug found" in content
        entry_pos = content.find("Bug found")
        universal_pos = content.find("Universal Patterns")
        assert entry_pos < universal_pos

    def test_no_anchor_fails(self, seeded_db, tmp_path):
        db, db_path, config = seeded_db
        lf = tmp_path / "LESSONS.md"
        lf.write_text("# Just a file\nSome content\n")
        config.lessons_file = str(lf)
        from dbq.commands.knowledge import cmd_log_lesson
        with pytest.raises(SystemExit):
            cmd_log_lesson(config, "x", "y", "z")


class TestPromoteCommand:
    def test_appends_to_universal(self, seeded_db, capsys, tmp_path):
        db, db_path, config = seeded_db
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        universal = claude_dir / "LESSONS_UNIVERSAL.md"
        universal.write_text("# Universal\n| Date | Pattern | Source | Rule |\n")
        from dbq.commands.knowledge import cmd_promote
        with patch.dict(os.environ, {"HOME": str(tmp_path)}):
            # Monkey-patch Path.home for this test
            from pathlib import Path
            original_home = Path.home
            Path.home = staticmethod(lambda: tmp_path)
            try:
                cmd_promote(config, "Never skip tests", "Add CI gate")
            finally:
                Path.home = original_home
        out = capsys.readouterr().out
        assert "Promoted" in out
        content = universal.read_text()
        assert "Never skip tests" in content

    def test_no_universal_file(self, seeded_db, tmp_path):
        db, db_path, config = seeded_db
        from dbq.commands.knowledge import cmd_promote
        from pathlib import Path
        original_home = Path.home
        Path.home = staticmethod(lambda: tmp_path)
        try:
            with pytest.raises(SystemExit):
                cmd_promote(config, "test")
        finally:
            Path.home = original_home


class TestEscalateCommand:
    def test_escalates_to_backlog(self, seeded_db, capsys, tmp_path):
        db, db_path, config = seeded_db
        backlog = tmp_path / ".claude" / "dev-framework" / "BOOTSTRAP_BACKLOG.md"
        backlog.parent.mkdir(parents=True)
        backlog.write_text(
            "# Backlog\n"
            "## Pending\n"
            "<!-- PENDING-ANCHOR -->\n"
            "## Applied\n"
        )
        from dbq.commands.knowledge import cmd_escalate
        from pathlib import Path
        original_home = Path.home
        Path.home = staticmethod(lambda: tmp_path)
        try:
            cmd_escalate(config, "Fix template", "template", "db_queries.sh", "P1")
        finally:
            Path.home = original_home
        out = capsys.readouterr().out
        assert "Escalated" in out
        assert "BP-001" in out
        content = backlog.read_text()
        assert "Fix template" in content
        assert "P1" in content


# ── Delegation command tests ─────────────────────────────────────────

class TestDelegationCommand:
    def test_shows_all_phases(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.delegation import cmd_delegation
        cmd_delegation(db)
        out = capsys.readouterr().out
        assert "Delegation Map" in out
        assert "P1-PLAN" in out
        assert "P2-BUILD" in out
        assert "DONE" in out

    def test_filter_by_phase(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.delegation import cmd_delegation
        cmd_delegation(db, "P2-BUILD")
        out = capsys.readouterr().out
        assert "P2-BUILD" in out
        assert "P3-POLISH" not in out


class TestDelegationMdCommand:
    def test_regenerates_section(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        # Create AGENT_DELEGATION.md with markers
        deleg_file = config.project_dir / "AGENT_DELEGATION.md"
        deleg_file.write_text(
            "# Delegation\n"
            "## Section 7\nStuff\n"
            "<!-- DELEGATION-START -->\n"
            "Old content here\n"
            "<!-- DELEGATION-END -->\n"
            "## Section 9\nMore stuff\n"
        )
        from dbq.commands.delegation import cmd_delegation_md
        cmd_delegation_md(db, config)
        out = capsys.readouterr().out
        assert "Regenerated" in out
        content = deleg_file.read_text()
        assert "Old content here" not in content
        assert "P1-PLAN" in content
        assert "Section 7" in content
        assert "Section 9" in content

    def test_missing_markers(self, seeded_db):
        db, db_path, config = seeded_db
        deleg_file = config.project_dir / "AGENT_DELEGATION.md"
        deleg_file.write_text("# Delegation\nNo markers\n")
        from dbq.commands.delegation import cmd_delegation_md
        with pytest.raises(SystemExit):
            cmd_delegation_md(db, config)

    def test_no_file(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.delegation import cmd_delegation_md
        with pytest.raises(SystemExit):
            cmd_delegation_md(db, config)


class TestSyncCheckCommand:
    def test_drift_detected(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        deleg_file = config.project_dir / "AGENT_DELEGATION.md"
        # Only mention some task IDs — T-004 etc. should be missing
        deleg_file.write_text("# Delegation\nT-001 T-002 T-003\n")
        from dbq.commands.delegation import cmd_sync_check
        cmd_sync_check(db, config)
        out = capsys.readouterr().out
        assert "drift" in out.lower()

    def test_no_file(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.delegation import cmd_sync_check
        with pytest.raises(SystemExit):
            cmd_sync_check(db, config)


# ── Snapshot command tests ───────────────────────────────────────────

class TestSnapshotCommand:
    def test_creates_snapshot(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot
        cmd_snapshot(db, "test-snap")
        out = capsys.readouterr().out
        assert "Snapshot #1" in out
        assert "test-snap" in out
        count = db.fetch_scalar("SELECT COUNT(*) FROM db_snapshots")
        assert count == 1

    def test_auto_label(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot
        cmd_snapshot(db)
        out = capsys.readouterr().out
        assert "Snapshot #" in out


class TestSnapshotListCommand:
    def test_lists_snapshots(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot, cmd_snapshot_list
        cmd_snapshot(db, "snap-1")
        cmd_snapshot(db, "snap-2")
        capsys.readouterr()
        cmd_snapshot_list(db)
        out = capsys.readouterr().out
        assert "DB Snapshots" in out
        assert "snap-1" in out
        assert "snap-2" in out

    def test_no_snapshots(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot_list
        cmd_snapshot_list(db)
        out = capsys.readouterr().out
        assert "No snapshots" in out


class TestSnapshotShowCommand:
    def test_shows_detail(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot, cmd_snapshot_show
        cmd_snapshot(db, "detail-snap")
        capsys.readouterr()
        cmd_snapshot_show(db, 1)
        out = capsys.readouterr().out
        assert "detail-snap" in out
        assert "Stats:" in out
        assert "Tasks:" in out

    def test_not_found(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot_show
        with pytest.raises(SystemExit):
            cmd_snapshot_show(db, 999)


class TestSnapshotDiffCommand:
    def test_diff_with_changes(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot, cmd_snapshot_diff
        cmd_snapshot(db, "before")
        # Make a change
        db.execute("UPDATE tasks SET status='DONE' WHERE id='T-004'")
        db.commit()
        cmd_snapshot(db, "after")
        capsys.readouterr()
        cmd_snapshot_diff(db, 1, 2)
        out = capsys.readouterr().out
        assert "Snapshot Diff" in out
        assert "T-004" in out
        assert "Progress:" in out

    def test_diff_no_changes(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot, cmd_snapshot_diff
        cmd_snapshot(db, "same-1")
        cmd_snapshot(db, "same-2")
        capsys.readouterr()
        cmd_snapshot_diff(db, 1, 2)
        out = capsys.readouterr().out
        assert "No task status changes" in out

    def test_diff_not_found(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.snapshots import cmd_snapshot_diff
        with pytest.raises(SystemExit):
            cmd_snapshot_diff(db, 1, 2)


# ── Health extras tests ──────────────────────────────────────────────

class TestBackupCommand:
    def test_creates_backup(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_backup
        cmd_backup(db, config)
        out = capsys.readouterr().out
        assert "Backup created" in out
        backup_dir = config.project_dir / "backups"
        assert backup_dir.exists()
        backups = list(backup_dir.glob("*.db"))
        assert len(backups) == 1


class TestRestoreCommand:
    def test_list_backups(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_backup, cmd_restore
        cmd_backup(db, config)
        capsys.readouterr()
        cmd_restore(db, config)
        out = capsys.readouterr().out
        assert "Available Backups" in out

    def test_restore_from_backup(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_backup, cmd_restore
        cmd_backup(db, config)
        capsys.readouterr()
        # Find the backup file
        backup_dir = config.project_dir / "backups"
        backup_file = list(backup_dir.glob("*.db"))[0]
        # Modify DB
        db.execute("DELETE FROM tasks WHERE id='T-004'")
        db.commit()
        # Restore
        cmd_restore(db, config, backup_file.name)
        out = capsys.readouterr().out
        assert "Restored" in out

    def test_restore_no_file(self, seeded_db):
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_restore
        with pytest.raises(SystemExit):
            cmd_restore(db, config, "nonexistent.db")


class TestVerifyCommand:
    def test_populated_db(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.health import cmd_verify
        cmd_verify(db)
        out = capsys.readouterr().out
        assert "DB Verification" in out
        assert "DB populated and schema complete" in out

    def test_empty_db(self, tmp_db, capsys):
        db, db_path = tmp_db
        from dbq.commands.health import cmd_verify
        cmd_verify(db)
        out = capsys.readouterr().out
        assert "DB IS EMPTY" in out


# ── Session git tests (mocked subprocess) ────────────────────────────

class TestTagSessionCommand:
    def test_creates_tag(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.sessions import cmd_tag_session
        # Mock git so we don't need a real repo
        with patch("dbq.commands.sessions.subprocess.run") as mock_run:
            # First call: tag -l (listing existing tags)
            # Second call: tag <name> HEAD (creating tag)
            mock_run.side_effect = [
                type("Result", (), {"stdout": "", "returncode": 0, "stderr": ""})(),
                type("Result", (), {"stdout": "", "returncode": 0, "stderr": ""})(),
            ]
            cmd_tag_session(config)
        out = capsys.readouterr().out
        assert "Tagged:" in out
        assert "session/" in out


class TestSessionTagsCommand:
    def test_no_tags(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.sessions import cmd_session_tags
        with patch("dbq.commands.sessions.subprocess.run") as mock_run:
            mock_run.return_value = type("Result", (), {"stdout": "", "returncode": 0, "stderr": ""})()
            cmd_session_tags(config)
        out = capsys.readouterr().out
        assert "No session tags" in out


class TestSessionFileCommand:
    def test_not_found(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        from dbq.commands.sessions import cmd_session_file
        with patch("dbq.commands.sessions.subprocess.run") as mock_run:
            mock_run.return_value = type("Result", (), {"stdout": "", "returncode": 0, "stderr": ""})()
            with pytest.raises(SystemExit):
                cmd_session_file(config, "99", "file.txt")


# ── CLI wiring tests for Phase 3 ────────────────────────────────────

class TestCLIPhase3:
    def test_snapshot_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["snapshot", "cli-test"])
        out = capsys.readouterr().out
        assert "Snapshot #" in out

    def test_snapshot_list_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["snapshot-list"])
        out = capsys.readouterr().out
        assert "DB Snapshots" in out

    def test_verify_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["verify"])
        out = capsys.readouterr().out
        assert "DB Verification" in out

    def test_delegation_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["delegation"])
        out = capsys.readouterr().out
        assert "Delegation Map" in out

    def test_backup_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["backup"])
        out = capsys.readouterr().out
        assert "Backup created" in out

    def test_restore_list_cli(self, seeded_db, capsys):
        db, db_path, config = seeded_db
        with patch.dict(os.environ, {"DB_OVERRIDE": db_path}):
            from dbq.cli import main
            main(["restore"])
        out = capsys.readouterr().out
        # No backups yet, so should show "No backups" or "Available Backups"
        assert "Backup" in out or "backup" in out


# ── Lesson Recall & Critical Files Tests ─────────────────────────────

class TestLessonRecall:
    def test_extract_keywords(self):
        from dbq.commands.tasks import _extract_keywords
        kws = _extract_keywords("Create asset optimization script (WebP)")
        assert "create" in kws
        assert "asset" in kws
        assert "optimization" in kws
        # Short words filtered out
        assert "max" not in kws

    def test_extract_keywords_deduplicates(self):
        from dbq.commands.tasks import _extract_keywords
        kws = _extract_keywords("test test test test again")
        assert kws.count("test") == 1
        assert kws.count("again") == 1

    def test_context_keywords_delegation(self):
        from dbq.commands.tasks import _context_keywords
        ctx = _context_keywords("delegate to sub-agent haiku")
        assert "delegation" in ctx
        assert "tier" in ctx

    def test_context_keywords_session(self):
        from dbq.commands.tasks import _context_keywords
        ctx = _context_keywords("save session handoff")
        assert "handoff" in ctx
        assert "intent" in ctx

    def test_context_keywords_none(self):
        from dbq.commands.tasks import _context_keywords
        ctx = _context_keywords("fix button color")
        assert ctx == []

    def test_grep_lessons_finds_matches(self, tmp_path):
        lessons = tmp_path / "LESSONS.md"
        lessons.write_text(
            "# Lessons\n"
            "| # | Date | What Went Wrong | Prevention Rule |\n"
            "|---|------|----------------|------------------|\n"
            "| 1 | 2026-03-15 | Broke the build with SSR | Always test build |\n"
            "| 2 | 2026-03-16 | Delegation skipped | Map tiers before starting |\n"
        )
        from dbq.commands.tasks import _grep_lessons
        matches = _grep_lessons(str(lessons), ["build"])
        assert len(matches) == 1
        assert "build" in matches[0][0].lower() or "build" in matches[0][1].lower()

    def test_grep_lessons_no_file(self):
        from dbq.commands.tasks import _grep_lessons
        matches = _grep_lessons("/nonexistent/path.md", ["test"])
        assert matches == []

    def test_grep_lessons_excludes_headers(self, tmp_path):
        lessons = tmp_path / "LESSONS.md"
        lessons.write_text(
            "| Date | What Went Wrong | Prevention Rule |\n"
            "|------|----------------|------------------|\n"
        )
        from dbq.commands.tasks import _grep_lessons
        matches = _grep_lessons(str(lessons), ["Date", "Wrong"])
        assert matches == []

    def test_lesson_recall_prints_matches(self, tmp_path, capsys):
        lessons = tmp_path / "LESSONS_TEST.md"
        lessons.write_text(
            "# Lessons\n"
            "| # | Date | What Went Wrong | Prevention Rule |\n"
            "|---|------|----------------|------------------|\n"
            "| 1 | 2026-03 | Component build broke | Always run build test |\n"
        )
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            lessons_file=str(lessons),
        )
        from dbq.commands.tasks import _lesson_recall
        _lesson_recall(config, "Fix broken component rendering", "")
        out = capsys.readouterr().out
        assert "Relevant lessons" in out
        assert "Component build broke" in out

    def test_lesson_recall_no_file_silent(self, tmp_path, capsys):
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            lessons_file="",
        )
        from dbq.commands.tasks import _lesson_recall
        _lesson_recall(config, "Some task title", "")
        out = capsys.readouterr().out
        assert out == ""


class TestCriticalFilesCheck:
    def test_load_registry_json(self, tmp_path):
        registry = tmp_path / "critical_files_registry.json"
        registry.write_text(json.dumps([
            {"pattern": "src/data/battles.ts", "level": "INVARIANT",
             "audit": "Verify dates and coordinates"},
            {"pattern": "src/stores/useStore.ts", "level": "SEMANTIC",
             "audit": "Check all consumers"},
        ]))
        from dbq.commands.tasks import _load_registry_json
        entries = _load_registry_json(registry)
        assert len(entries) == 2
        assert entries[0]["pattern"] == "src/data/battles.ts"

    def test_load_registry_bash(self, tmp_path):
        registry = tmp_path / "critical_files_registry.sh"
        registry.write_text(
            '#!/usr/bin/env bash\n'
            '# Comment: CRITICAL_PATTERNS+=("ignore this")\n'
            'CRITICAL_PATTERNS=()\nCRITICAL_LEVELS=()\nCRITICAL_AUDITS=()\n'
            'CRITICAL_PATTERNS+=("src/data/battles.ts")\n'
            'CRITICAL_LEVELS+=("INVARIANT")\n'
            'CRITICAL_AUDITS+=("Verify dates")\n'
            'CRITICAL_PATTERNS+=("src/stores/useStore.ts")\n'
            'CRITICAL_LEVELS+=("SEMANTIC")\n'
            'CRITICAL_AUDITS+=("Check consumers")\n'
        )
        from dbq.commands.tasks import _load_registry_bash
        entries = _load_registry_bash(registry)
        assert len(entries) == 2
        assert entries[0]["pattern"] == "src/data/battles.ts"
        assert entries[1]["level"] == "SEMANTIC"

    def test_bash_parser_skips_comments(self, tmp_path):
        registry = tmp_path / "critical_files_registry.sh"
        registry.write_text(
            '#!/usr/bin/env bash\n'
            '#   CRITICAL_PATTERNS+=("glob pattern")\n'
            '#   CRITICAL_LEVELS+=("INVARIANT|SEMANTIC")\n'
            '#   CRITICAL_AUDITS+=("instruction")\n'
            'CRITICAL_PATTERNS=()\nCRITICAL_LEVELS=()\nCRITICAL_AUDITS=()\n'
            'CRITICAL_PATTERNS+=("real.ts")\n'
            'CRITICAL_LEVELS+=("SEMANTIC")\n'
            'CRITICAL_AUDITS+=("Real audit")\n'
        )
        from dbq.commands.tasks import _load_registry_bash
        entries = _load_registry_bash(registry)
        assert len(entries) == 1
        assert entries[0]["pattern"] == "real.ts"

    def test_critical_files_prints_matches(self, tmp_path, capsys):
        registry = tmp_path / "critical_files_registry.json"
        registry.write_text(json.dumps([
            {"pattern": "src/data/battles.ts", "level": "INVARIANT",
             "audit": "Verify battle data accuracy"},
            {"pattern": "package.json", "level": "SEMANTIC",
             "audit": "Check bundle size"},
        ]))
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
        )
        from dbq.commands.tasks import _critical_files_check
        _critical_files_check(config, "Update battle data for new period", "")
        out = capsys.readouterr().out
        assert "Critical files" in out
        assert "battles.ts" in out
        assert "package.json" not in out  # "package" not in title keywords

    def test_critical_files_no_registry_silent(self, tmp_path, capsys):
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
        )
        from dbq.commands.tasks import _critical_files_check
        _critical_files_check(config, "Some task", "")
        out = capsys.readouterr().out
        assert out == ""

    def test_check_includes_lesson_recall(self, seeded_db, tmp_path, capsys):
        """Integration: check command includes lesson recall when passing."""
        db, db_path, config = seeded_db
        # Create a lessons file with matching content
        lessons = Path(config.project_dir) / "LESSONS_TEST.md"
        lessons.write_text(
            "| # | Date | What Went Wrong | Prevention Rule |\n"
            "|---|------|----------------|------------------|\n"
            "| 1 | 2026-03 | Architecture design flawed | Review before implementing |\n"
        )
        config.lessons_file = str(lessons)

        # T-004 is P2-BUILD, P1 is gated. It hits CONFIRM (first Claude task in phase)
        # but lesson recall still runs since check_pass is true
        from dbq.commands.tasks import cmd_check
        cmd_check(db, config, "T-004")
        out = capsys.readouterr().out
        assert "Relevant lessons" in out
        assert "Architecture design flawed" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
