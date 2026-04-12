"""
Tests for the health command module: init-db, health, verify, export, import.
"""
import json
import sys
from pathlib import Path
from io import StringIO

import pytest

from dbq.db import Database, SCHEMA_TABLES
from dbq.config import ProjectConfig
from dbq.commands.health import (
    cmd_init_db, cmd_health, cmd_verify, cmd_export, cmd_import,
)


# ---------------------------------------------------------------------------
# cmd_init_db
# ---------------------------------------------------------------------------

class TestCmdInitDb:
    def test_creates_all_tables(self, empty_db: Database):
        """init_db leaves all expected tables present."""
        expected = list(SCHEMA_TABLES.keys())
        for table in expected:
            assert empty_db.table_exists(table), f"Table missing: {table}"

    def test_idempotent(self, empty_db: Database, capsys):
        """Running init_db twice does not raise and leaves schema intact."""
        cmd_init_db(empty_db)  # second call
        captured = capsys.readouterr()
        assert "Schema ready" in captured.out
        for table in SCHEMA_TABLES:
            assert empty_db.table_exists(table)

    def test_creates_tasks_columns(self, empty_db: Database):
        """After init, tasks table has core required columns."""
        required_cols = [
            "id", "phase", "title", "status", "assignee",
            "blocked_by", "sort_order", "tier", "track",
            "origin_phase", "severity", "gate_critical",
        ]
        actual = empty_db.get_table_columns("tasks")
        for col in required_cols:
            assert col in actual, f"Column missing from tasks: {col}"


# ---------------------------------------------------------------------------
# cmd_health
# ---------------------------------------------------------------------------

class TestCmdHealth:
    def test_healthy_empty_db(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """An empty but correctly-initialised DB should report HEALTHY."""
        cmd_health(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "HEALTHY" in out

    def test_healthy_populated_db(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """A populated DB with no integrity issues should report HEALTHY."""
        cmd_health(populated_db, populated_config)
        out = capsys.readouterr().out
        assert "HEALTHY" in out

    def test_output_contract_last_lines(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """Output contract: last non-empty line contains HEALTHY/DEGRADED/CRITICAL."""
        cmd_health(empty_db, simple_config)
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if l.strip()]
        last = lines[-1] if lines else ""
        assert any(kw in last for kw in ("HEALTHY", "DEGRADED", "CRITICAL")), (
            f"Last non-empty line should contain a verdict keyword, got: {last!r}"
        )

    def test_missing_table_triggers_critical(self, tmp_db_path: Path, simple_config: ProjectConfig, capsys):
        """A DB missing a required table should exit with code 1."""
        # Create DB with only the tasks table
        db = Database(str(tmp_db_path))
        db.execute(SCHEMA_TABLES["tasks"])
        db.commit()

        with pytest.raises(SystemExit) as exc_info:
            cmd_health(db, simple_config)
        db.close()
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "CRITICAL" in out or "Missing table" in out

    def test_integrity_ok(self, empty_db: Database):
        """integrity_check() returns 'ok' for a fresh DB."""
        result = empty_db.integrity_check()
        assert result == "ok"

    def test_detects_broken_blocked_by(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """A broken blocked_by reference should produce a warning (DEGRADED or warning line)."""
        # Insert task with nonexistent blocker
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, blocked_by, queue) "
            "VALUES ('T-99', 'P1-DISCOVER', 'Orphan', 'TODO', 'CLAUDE', 'T-NONEXISTENT', 'A')"
        )
        empty_db.commit()
        cmd_health(empty_db, simple_config)
        out = capsys.readouterr().out
        # Broken ref → warning, so output should note the warning or DEGRADED
        assert "Broken blocked_by" in out or "DEGRADED" in out or "warning" in out.lower()

    def test_detects_invalid_status(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """A task with an invalid status should produce a warning."""
        empty_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue) "
            "VALUES ('T-BAD', 'P1-DISCOVER', 'Bad status', 'INVALID_STATUS', 'CLAUDE', 'A')"
        )
        empty_db.commit()
        cmd_health(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "Invalid statuses" in out or "DEGRADED" in out


# ---------------------------------------------------------------------------
# cmd_verify
# ---------------------------------------------------------------------------

class TestCmdVerify:
    def test_empty_db_reports_empty(self, empty_db: Database, capsys):
        """verify on an empty tasks table should flag it as empty."""
        cmd_verify(empty_db)
        out = capsys.readouterr().out
        assert "DB IS EMPTY" in out or "Tasks total:  0" in out

    def test_populated_db_reports_counts(self, populated_db: Database, capsys):
        """verify on a populated DB should print correct task counts."""
        cmd_verify(populated_db)
        out = capsys.readouterr().out
        # 5 tasks in populated_db fixture (T-01..T-04 forward + LB-01 loopback)
        assert "Tasks total:" in out
        # Should confirm schema complete (all migration columns exist)
        assert "complete" in out or "populated" in out
        # The total count should reference 5 (not 0 and not arbitrary)
        assert " 5" in out or "5 " in out or "5\n" in out


# ---------------------------------------------------------------------------
# Database class unit tests (schema layer)
# ---------------------------------------------------------------------------

class TestDatabase:
    @pytest.mark.parametrize("table_name,expected", [
        ("tasks", True),
        ("phase_gates", True),
        ("sessions", True),
        ("assumptions", True),
        ("nonexistent_table", False),
        ("also_nonexistent", False),
    ])
    def test_table_exists(self, empty_db: Database, table_name: str, expected: bool):
        """table_exists returns True for schema tables and False for unknown names."""
        assert empty_db.table_exists(table_name) is expected

    def test_column_exists(self, empty_db: Database):
        assert empty_db.column_exists("tasks", "id") is True
        assert empty_db.column_exists("tasks", "nonexistent_col") is False

    def test_get_table_columns(self, empty_db: Database):
        cols = empty_db.get_table_columns("tasks")
        assert isinstance(cols, list)
        assert "id" in cols
        assert "phase" in cols
        assert "status" in cols

    def test_migrate_is_idempotent(self, empty_db: Database):
        """migrate() can be called multiple times without error."""
        added1 = empty_db.migrate()
        added2 = empty_db.migrate()
        # Second call should add nothing (all columns already present)
        assert added2 == []

    def test_fetch_scalar_default(self, empty_db: Database):
        """fetch_scalar returns default when no rows match."""
        result = empty_db.fetch_scalar(
            "SELECT COUNT(*) FROM tasks WHERE id='no-such-id'"
        )
        assert result == 0

    def test_fetch_one_missing_returns_none(self, empty_db: Database):
        result = empty_db.fetch_one(
            "SELECT id FROM tasks WHERE id=?", ("MISSING",)
        )
        assert result is None

    def test_commit_persists_data(self, tmp_db_path: Path):
        """Data written in one connection is readable by a second connection."""
        db1 = Database(str(tmp_db_path))
        db1.init_schema()
        db1.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue) "
            "VALUES ('T-PERSIST', 'P1', 'Persist test', 'TODO', 'CLAUDE', 'A')"
        )
        db1.commit()
        db1.close()

        db2 = Database(str(tmp_db_path))
        count = db2.fetch_scalar("SELECT COUNT(*) FROM tasks WHERE id='T-PERSIST'")
        db2.close()
        assert count == 1


# ---------------------------------------------------------------------------
# cmd_export
# ---------------------------------------------------------------------------

class TestCmdExport:
    def test_export_all_tables(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """Full export produces valid JSON with meta + all existing table keys."""
        cmd_export(populated_db, populated_config)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "meta" in data
        assert "tasks" in data
        assert isinstance(data["meta"]["tables"], list)
        # All schema tables should be present as keys
        for table in SCHEMA_TABLES:
            if populated_db.table_exists(table):
                assert table in data

    def test_export_single_table(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """--table tasks only includes tasks key (plus meta)."""
        cmd_export(populated_db, populated_config, tables="tasks")
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "tasks" in data
        assert "meta" in data
        # Other tables should NOT be present
        assert "sessions" not in data
        assert "phase_gates" not in data

    def test_export_pretty(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """--pretty output contains newlines and indentation."""
        cmd_export(populated_db, populated_config, pretty=True)
        out = capsys.readouterr().out
        assert "\n  " in out  # indented
        data = json.loads(out)
        assert "meta" in data

    def test_export_to_file(self, populated_db: Database, populated_config: ProjectConfig,
                            tmp_path: Path, capsys):
        """-o writes to file, stdout has no JSON."""
        outfile = str(tmp_path / "export.json")
        cmd_export(populated_db, populated_config, output_file=outfile)
        stdout = capsys.readouterr().out
        assert stdout.strip() == ""  # no JSON on stdout
        data = json.loads(Path(outfile).read_text(encoding="utf-8"))
        assert "meta" in data
        assert len(data["tasks"]) == 5

    def test_export_task_count(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """Exported task count matches DB."""
        cmd_export(populated_db, populated_config, tables="tasks")
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data["tasks"]) == 5

    def test_export_null_preservation(self, populated_db: Database, populated_config: ProjectConfig, capsys):
        """Tasks with NULL columns export as null in JSON."""
        cmd_export(populated_db, populated_config, tables="tasks")
        out = capsys.readouterr().out
        data = json.loads(out)
        # T-01 has blocked_by=None
        t01 = [t for t in data["tasks"] if t["id"] == "T-01"][0]
        assert t01["blocked_by"] is None

    def test_export_invalid_table(self, populated_db: Database, populated_config: ProjectConfig):
        """Requesting a nonexistent table exits with error."""
        with pytest.raises(SystemExit):
            cmd_export(populated_db, populated_config, tables="nonexistent_table")

    def test_export_nested_json_text(self, empty_db: Database, simple_config: ProjectConfig, capsys):
        """Snapshot with JSON in TEXT column exports as string, not parsed object."""
        empty_db.execute(
            "INSERT INTO db_snapshots (label, task_summary, stats) "
            "VALUES (?, ?, ?)",
            ("snap1", '{"tasks": 5}', '{"score": 90}'),
        )
        empty_db.commit()
        cmd_export(empty_db, simple_config, tables="db_snapshots")
        out = capsys.readouterr().out
        data = json.loads(out)
        row = data["db_snapshots"][0]
        # Nested JSON is stored as a string, not a parsed dict
        assert isinstance(row["task_summary"], str)
        assert row["task_summary"] == '{"tasks": 5}'


# ---------------------------------------------------------------------------
# cmd_import
# ---------------------------------------------------------------------------

class TestCmdImport:
    def _export_json(self, db: Database, config: ProjectConfig) -> dict:
        """Helper: export DB and return parsed JSON."""
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cmd_export(db, config)
        json_str = sys.stdout.getvalue()
        sys.stdout = old_stdout
        return json.loads(json_str)

    def test_import_roundtrip(self, populated_db: Database, populated_config: ProjectConfig,
                              tmp_path: Path):
        """Export populated_db → import into fresh DB → row counts match."""
        # Export
        export_file = str(tmp_path / "roundtrip.json")
        cmd_export(populated_db, populated_config, output_file=export_file)

        # Create fresh DB
        fresh_path = tmp_path / "fresh.db"
        fresh_db = Database(str(fresh_path))
        fresh_db.init_schema()
        fresh_db.migrate()
        fresh_config = ProjectConfig(db_path=str(fresh_path), project_name="fresh")

        # Import
        cmd_import(fresh_db, fresh_config, input_file=export_file)

        # Verify counts
        orig_count = populated_db.fetch_scalar("SELECT COUNT(*) FROM tasks")
        fresh_count = fresh_db.fetch_scalar("SELECT COUNT(*) FROM tasks")
        assert fresh_count == orig_count
        assert fresh_count == 5
        fresh_db.close()

    def test_import_merge_no_duplicates(self, populated_db: Database,
                                        populated_config: ProjectConfig, tmp_path: Path):
        """Import into populated_db (already has data) → counts unchanged (INSERT OR IGNORE)."""
        export_file = str(tmp_path / "merge.json")
        cmd_export(populated_db, populated_config, output_file=export_file)

        before = populated_db.fetch_scalar("SELECT COUNT(*) FROM tasks")
        cmd_import(populated_db, populated_config, input_file=export_file)
        after = populated_db.fetch_scalar("SELECT COUNT(*) FROM tasks")
        assert after == before

    def test_import_merge_reports_accurate_count(self, populated_db: Database,
                                                  populated_config: ProjectConfig,
                                                  tmp_path: Path, capsys):
        """Merge import into existing DB reports 0 inserted (all ignored), not attempted count."""
        export_file = str(tmp_path / "count.json")
        cmd_export(populated_db, populated_config, output_file=export_file)

        cmd_import(populated_db, populated_config, input_file=export_file)
        err = capsys.readouterr().err
        # All 5 tasks already exist → INSERT OR IGNORE skips all → 0 rows reported
        assert "tasks: 0 rows" in err

    def test_import_replace(self, populated_db: Database, populated_config: ProjectConfig,
                            tmp_path: Path):
        """Import with --replace → exact match with source data."""
        export_file = str(tmp_path / "replace.json")
        cmd_export(populated_db, populated_config, output_file=export_file)

        # Add extra row that should be wiped by replace
        populated_db.execute(
            "INSERT INTO tasks (id, phase, title, status, assignee, queue) "
            "VALUES ('T-EXTRA', 'P1-DISCOVER', 'Extra', 'TODO', 'CLAUDE', 'A')"
        )
        populated_db.commit()
        assert populated_db.fetch_scalar("SELECT COUNT(*) FROM tasks") == 6

        cmd_import(populated_db, populated_config, input_file=export_file, replace=True)
        assert populated_db.fetch_scalar("SELECT COUNT(*) FROM tasks") == 5

    def test_import_schema_drift(self, empty_db: Database, simple_config: ProjectConfig,
                                 tmp_path: Path):
        """Extra keys in JSON rows are silently skipped — no error."""
        data = {
            "meta": {"exported_at": "2026-01-01", "project_name": "test",
                     "source_db": "test.db", "tables": ["tasks"]},
            "tasks": [{
                "id": "T-DRIFT", "phase": "P1-DISCOVER", "title": "Drift test",
                "status": "TODO", "assignee": "CLAUDE", "queue": "A",
                "future_column": "should be ignored",
            }]
        }
        import_file = tmp_path / "drift.json"
        import_file.write_text(json.dumps(data), encoding="utf-8")

        cmd_import(empty_db, simple_config, input_file=str(import_file))
        count = empty_db.fetch_scalar("SELECT COUNT(*) FROM tasks WHERE id='T-DRIFT'")
        assert count == 1

    def test_import_stdin(self, empty_db: Database, simple_config: ProjectConfig,
                          monkeypatch):
        """Import from stdin (- argument)."""
        data = {
            "meta": {"exported_at": "2026-01-01", "project_name": "test",
                     "source_db": "test.db", "tables": ["tasks"]},
            "tasks": [{
                "id": "T-STDIN", "phase": "P1-DISCOVER", "title": "Stdin test",
                "status": "TODO", "assignee": "CLAUDE", "queue": "A",
            }]
        }
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(data)))
        cmd_import(empty_db, simple_config, input_file="-")
        count = empty_db.fetch_scalar("SELECT COUNT(*) FROM tasks WHERE id='T-STDIN'")
        assert count == 1

    def test_import_null_preservation(self, populated_db: Database,
                                      populated_config: ProjectConfig, tmp_path: Path):
        """Export → import round-trip preserves NULLs."""
        export_file = str(tmp_path / "nulls.json")
        cmd_export(populated_db, populated_config, output_file=export_file)

        fresh_path = tmp_path / "nulls.db"
        fresh_db = Database(str(fresh_path))
        fresh_db.init_schema()
        fresh_db.migrate()
        fresh_config = ProjectConfig(db_path=str(fresh_path), project_name="null-test")

        cmd_import(fresh_db, fresh_config, input_file=export_file)

        # T-01 has blocked_by=NULL
        row = fresh_db.fetch_one(
            "SELECT blocked_by FROM tasks WHERE id=?", ("T-01",)
        )
        assert row is None
        fresh_db.close()

    def test_import_invalid_json(self, empty_db: Database, simple_config: ProjectConfig,
                                 tmp_path: Path):
        """Invalid JSON exits with error."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")
        with pytest.raises(SystemExit):
            cmd_import(empty_db, simple_config, input_file=str(bad_file))

    def test_import_missing_meta(self, empty_db: Database, simple_config: ProjectConfig,
                                 tmp_path: Path):
        """JSON without meta key exits with error."""
        no_meta = tmp_path / "no_meta.json"
        no_meta.write_text(json.dumps({"tasks": []}), encoding="utf-8")
        with pytest.raises(SystemExit):
            cmd_import(empty_db, simple_config, input_file=str(no_meta))

    def test_import_nested_json_roundtrip(self, empty_db: Database,
                                          simple_config: ProjectConfig, tmp_path: Path):
        """Snapshot with JSON-in-TEXT columns survives export → import."""
        empty_db.execute(
            "INSERT INTO db_snapshots (label, task_summary, stats) "
            "VALUES (?, ?, ?)",
            ("snap1", '{"tasks": 5}', '{"score": 90}'),
        )
        empty_db.commit()

        export_file = str(tmp_path / "nested.json")
        cmd_export(empty_db, simple_config, output_file=export_file)

        fresh_path = tmp_path / "nested.db"
        fresh_db = Database(str(fresh_path))
        fresh_db.init_schema()
        fresh_db.migrate()
        fresh_config = ProjectConfig(db_path=str(fresh_path), project_name="nested")

        cmd_import(fresh_db, fresh_config, input_file=export_file)

        row = fresh_db.fetch_one(
            "SELECT task_summary, stats FROM db_snapshots WHERE label=?",
            ("snap1",),
        )
        assert row["task_summary"] == '{"tasks": 5}'
        assert row["stats"] == '{"score": 90}'
        fresh_db.close()
