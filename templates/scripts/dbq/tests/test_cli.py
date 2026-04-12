"""
CLI integration tests: argument parsing, command dispatch, help text.

These tests call main() directly with a patched DB_OVERRIDE so they never
touch the real bootstrap.db.  They validate the full argument-parsing +
dispatch path without spawning a subprocess.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dbq.cli import main
from dbq.db import Database
from dbq.config import ProjectConfig


# ---------------------------------------------------------------------------
# Helper: build a pre-initialised DB and point DB_OVERRIDE at it
# ---------------------------------------------------------------------------

def _init_db(path: Path) -> None:
    """Create schema at path so commands that need an existing DB work."""
    db = Database(str(path))
    db.init_schema()
    db.migrate()
    db.close()


# ---------------------------------------------------------------------------
# Argument parsing — no-command and help
# ---------------------------------------------------------------------------

class TestArgumentParsing:
    def test_no_command_exits_zero(self, tmp_db_path: Path, capsys):
        """Calling main() with no args exits 0 and prints help."""
        _init_db(tmp_db_path)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0

    def test_unknown_command_exits_nonzero(self, tmp_db_path: Path, capsys):
        """An unrecognised command should cause argparse to exit non-zero."""
        _init_db(tmp_db_path)
        with pytest.raises(SystemExit) as exc_info:
            main(["totally-bogus-command"])
        assert exc_info.value.code != 0

    def test_done_requires_task_id(self, tmp_db_path: Path):
        """'done' with no positional arg should fail argparse (exit 2)."""
        _init_db(tmp_db_path)
        with pytest.raises(SystemExit) as exc_info:
            main(["done"])
        assert exc_info.value.code == 2

    def test_quick_defaults_phase_to_inbox(self, tmp_db_path: Path, capsys):
        """'quick <title>' without phase should default to INBOX."""
        _init_db(tmp_db_path)
        import re
        main(["quick", "Auto inbox task"])
        out = capsys.readouterr().out
        match = re.search(r"QK-[0-9a-f]+", out)
        assert match, f"No QK-xxxx ID in output: {out!r}"
        # Verify in DB
        db = Database(str(tmp_db_path))
        task_id = match.group(0)
        row = db.fetch_one("SELECT phase FROM tasks WHERE id=?", (task_id,))
        db.close()
        assert row is not None
        # fetch_one with single column returns scalar directly
        assert row == "INBOX"

    def test_quick_loopback_flags(self, tmp_db_path: Path, capsys):
        """'quick' with --loopback and --severity flags parses correctly."""
        _init_db(tmp_db_path)
        import re
        main([
            "quick", "Loopback task", "P1-TEST", "",
            "--loopback", "P1-TEST",
            "--severity", "2",
        ])
        out = capsys.readouterr().out
        match = re.search(r"LB-[0-9a-f]+", out)
        assert match, f"No LB-xxxx ID in output: {out!r}"

    def test_gate_pass_defaults(self, tmp_db_path: Path, capsys):
        """'gate-pass P1-TEST' should use default gated_by=MASTER."""
        _init_db(tmp_db_path)
        # Insert a task so phase exists
        db = Database(str(tmp_db_path))
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue) "
            "VALUES ('T-01', 'P1-TEST', 'Test', 'DONE', 'CLAUDE', 'A')"
        )
        db.commit()
        db.close()
        main(["gate-pass", "P1-TEST"])
        out = capsys.readouterr().out
        assert "P1-TEST" in out
        assert "MASTER" in out
        # Verify the gate row was actually written to DB
        db = Database(str(tmp_db_path))
        count = db.fetch_scalar("SELECT COUNT(*) FROM phase_gates WHERE phase='P1-TEST'")
        db.close()
        assert count == 1

    def test_skip_with_reason(self, tmp_db_path: Path, capsys):
        """'skip <task_id> <reason>' passes reason through correctly."""
        _init_db(tmp_db_path)
        db = Database(str(tmp_db_path))
        db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue) "
            "VALUES ('T-SKIP', 'P1-TEST', 'Skip me', 'TODO', 'CLAUDE', 'A')"
        )
        db.commit()
        db.close()
        main(["skip", "T-SKIP", "not needed"])
        # Verify status in DB
        db = Database(str(tmp_db_path))
        row = db.fetch_one("SELECT status FROM tasks WHERE id='T-SKIP'")
        db.close()
        assert row == "SKIP"


# ---------------------------------------------------------------------------
# Command dispatch — smoke tests via main()
# ---------------------------------------------------------------------------

class TestCommandDispatch:
    def test_health_command(self, tmp_db_path: Path, capsys):
        """health command dispatches and prints a verdict keyword."""
        _init_db(tmp_db_path)
        main(["health"])
        out = capsys.readouterr().out
        assert any(kw in out for kw in ("HEALTHY", "DEGRADED", "CRITICAL"))
        # Output should be non-trivially long (not just a single word)
        assert len(out.strip()) > 6

    def test_init_db_command(self, tmp_db_path: Path, capsys):
        """init-db creates all tables even if DB did not exist yet."""
        # Do NOT pre-init; let init-db create it from scratch
        main(["init-db"])
        out = capsys.readouterr().out
        assert "Schema ready" in out
        db = Database(str(tmp_db_path))
        assert db.table_exists("tasks")
        assert db.table_exists("phase_gates")  # second table sanity check
        db.close()

    def test_phase_command_empty(self, tmp_db_path: Path, capsys):
        """phase on an empty DB runs without error."""
        _init_db(tmp_db_path)
        main(["phase"])
        # Should not raise — just print "all phases complete" or similar
        out = capsys.readouterr().out
        assert out  # something was printed

    def test_gate_command_empty(self, tmp_db_path: Path, capsys):
        """gate on an empty DB runs without error."""
        _init_db(tmp_db_path)
        main(["gate"])
        out = capsys.readouterr().out
        assert "No phase gates" in out or "gate" in out.lower()

    def test_status_command(self, tmp_db_path: Path, capsys):
        """status command dispatches and prints output."""
        _init_db(tmp_db_path)
        main(["status"])
        out = capsys.readouterr().out
        assert out  # something was printed

    def test_inbox_command(self, tmp_db_path: Path, capsys):
        """inbox command dispatches without error."""
        _init_db(tmp_db_path)
        main(["inbox"])
        out = capsys.readouterr().out
        assert out

    def test_verify_command(self, tmp_db_path: Path, capsys):
        """verify command dispatches and reports task count."""
        _init_db(tmp_db_path)
        main(["verify"])
        out = capsys.readouterr().out
        assert "Tasks total:" in out

    def test_blockers_command(self, tmp_db_path: Path, capsys):
        """blockers command dispatches and prints output."""
        _init_db(tmp_db_path)
        main(["blockers"])
        out = capsys.readouterr().out
        assert out

    @pytest.mark.parametrize("cmd", ["done", "check"])
    def test_unknown_task_exits_1(self, tmp_db_path: Path, cmd: str):
        """done and check both exit 1 when given an unknown task ID."""
        _init_db(tmp_db_path)
        with pytest.raises(SystemExit) as exc_info:
            main([cmd, "T-UNKNOWN"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# init-db special-case: must work without an existing DB
# ---------------------------------------------------------------------------

class TestInitDbSpecialCase:
    def test_init_db_without_preexisting_db(self, tmp_db_path: Path, capsys):
        """init-db must succeed even when DB_OVERRIDE points at a non-existent file.

        This tests the key lesson: 'Special-case init commands to bypass
        prerequisite checks'.
        """
        assert not tmp_db_path.exists(), "Pre-condition: DB must not exist yet"
        main(["init-db"])
        assert tmp_db_path.exists(), "init-db should have created the DB file"
        out = capsys.readouterr().out
        assert "Schema ready" in out

    def test_init_db_creates_all_required_tables(self, tmp_db_path: Path, capsys):
        """After init-db, all 8 schema tables must exist."""
        main(["init-db"])
        capsys.readouterr()
        from dbq.db import SCHEMA_TABLES
        db = Database(str(tmp_db_path))
        for table in SCHEMA_TABLES:
            assert db.table_exists(table), f"Table missing after init-db: {table}"
        db.close()


# ---------------------------------------------------------------------------
# Config detection
# ---------------------------------------------------------------------------

class TestConfigDetection:
    def test_db_override_env_used(self, tmp_db_path: Path, monkeypatch):
        """detect_config() reads DB_OVERRIDE from environment."""
        _init_db(tmp_db_path)
        monkeypatch.setenv("DB_OVERRIDE", str(tmp_db_path))
        from dbq.config import detect_config
        config = detect_config()
        assert config.db_path == tmp_db_path

    def test_placeholder_phases_ignored(self, tmp_db_path: Path, monkeypatch):
        """%%PLACEHOLDER%% values in env vars are treated as unset."""
        _init_db(tmp_db_path)
        monkeypatch.setenv("DBQ_PHASES", "%%PROJECT_PHASES%%")
        monkeypatch.setenv("DB_OVERRIDE", str(tmp_db_path))
        from dbq.config import detect_config
        config = detect_config()
        # phases should come from DB auto-detect (empty DB = [])
        assert config.phases == []

    def test_valid_phases_from_env(self, tmp_db_path: Path, monkeypatch):
        """Space-separated DBQ_PHASES env var is parsed into a list."""
        _init_db(tmp_db_path)
        monkeypatch.setenv("DBQ_PHASES", "P1-PLAN P2-BUILD P3-SHIP")
        monkeypatch.setenv("DB_OVERRIDE", str(tmp_db_path))
        from dbq.config import detect_config
        config = detect_config()
        assert config.phases == ["P1-PLAN", "P2-BUILD", "P3-SHIP"]

    def test_no_db_raises_system_exit(self, tmp_path: Path, monkeypatch):
        """detect_config() with no DB file and no auto-detect should raise SystemExit."""
        monkeypatch.delenv("DB_OVERRIDE", raising=False)
        # Point cwd to empty temp dir with no .db files
        monkeypatch.chdir(tmp_path)
        from dbq.config import detect_config
        with pytest.raises(SystemExit):
            detect_config()
