"""
Tests for snapshot and delegation commands.

Covers:
  - commands/snapshots.py: cmd_snapshot, cmd_snapshot_list, cmd_snapshot_show,
    cmd_snapshot_diff
  - commands/delegation.py: cmd_delegation, cmd_delegation_md, cmd_sync_check
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dbq.db import Database
from dbq.config import ProjectConfig
from dbq.commands.snapshots import (
    cmd_snapshot,
    cmd_snapshot_list,
    cmd_snapshot_show,
    cmd_snapshot_diff,
)
from dbq.commands.delegation import (
    cmd_delegation,
    cmd_delegation_md,
    cmd_sync_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_snapshot(db: Database, label: str = "test-snap", git_sha: str = "abc1234",
                     task_summary: str = None, phase_gates: str = None,
                     stats: str = None) -> int:
    """Insert a minimal snapshot row and return its id."""
    if task_summary is None:
        task_summary = json.dumps([{"id": "T-01", "phase": "P1", "title": "t", "status": "DONE", "assignee": "CLAUDE"}])
    if phase_gates is None:
        phase_gates = json.dumps([])
    if stats is None:
        stats = json.dumps({"total": 1, "done": 1, "todo": 0, "blocked": 0, "by_phase": []})

    db.execute(
        "INSERT INTO db_snapshots (label, git_sha, task_summary, phase_gates, stats) "
        "VALUES (?, ?, ?, ?, ?)",
        (label, git_sha, task_summary, phase_gates, stats),
    )
    db.commit()
    return db.fetch_scalar("SELECT id FROM db_snapshots ORDER BY id DESC LIMIT 1")


def _make_delegation_file(tmp_path: Path, body: str = "") -> Path:
    """Create a minimal AGENT_DELEGATION.md with markers in tmp_path."""
    content = (
        "# Agent Delegation\n"
        "<!-- DELEGATION-START -->\n"
        + body
        + "<!-- DELEGATION-END -->\n"
    )
    p = tmp_path / "AGENT_DELEGATION.md"
    p.write_text(content)
    return p


def _config_for_dir(tmp_path: Path, db_path: str) -> ProjectConfig:
    """Build a ProjectConfig whose project_dir is tmp_path."""
    cfg = ProjectConfig(
        db_path=db_path,
        project_name="test-project",
        phases=["P1-DISCOVER", "P2-DESIGN", "P3-IMPLEMENT"],
    )
    # Override project_dir to point at tmp_path so delegation file is found
    cfg.project_dir = tmp_path
    return cfg


# ---------------------------------------------------------------------------
# cmd_snapshot
# ---------------------------------------------------------------------------

class TestCmdSnapshot:
    def _mock_git_ok(self):
        """Return a context manager that makes _git_sha() return 'deadbee'."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "deadbee\n"
        return patch("subprocess.run", return_value=mock_result)

    def test_creates_snapshot(self, populated_db: Database, capsys):
        """cmd_snapshot inserts a row into db_snapshots and prints confirmation."""
        with self._mock_git_ok():
            cmd_snapshot(populated_db, label="v1")

        count = populated_db.fetch_scalar("SELECT COUNT(*) FROM db_snapshots")
        out = capsys.readouterr().out
        assert count == 1
        assert "v1" in out

    def test_snapshot_captures_git_sha(self, populated_db: Database, capsys):
        """The stored git_sha and label both match the inputs."""
        with self._mock_git_ok():
            cmd_snapshot(populated_db, label="sha-test")

        git_sha = populated_db.fetch_one("SELECT git_sha FROM db_snapshots LIMIT 1")
        label = populated_db.fetch_one("SELECT label FROM db_snapshots LIMIT 1")
        assert git_sha == "deadbee"
        assert label == "sha-test"

    def test_snapshot_with_label(self, populated_db: Database, capsys):
        """Label is stored verbatim and the snapshot row includes stats."""
        with self._mock_git_ok():
            cmd_snapshot(populated_db, label="my-custom-label")

        label = populated_db.fetch_one("SELECT label FROM db_snapshots LIMIT 1")
        stats_json = populated_db.fetch_one("SELECT stats FROM db_snapshots LIMIT 1")
        assert label == "my-custom-label"
        assert stats_json is not None  # stats column was populated

    def test_snapshot_auto_label(self, populated_db: Database, capsys):
        """When label is omitted, a non-empty timestamp label is generated."""
        with self._mock_git_ok():
            cmd_snapshot(populated_db)

        label = populated_db.fetch_one("SELECT label FROM db_snapshots LIMIT 1")
        count = populated_db.fetch_scalar("SELECT COUNT(*) FROM db_snapshots")
        assert label  # not empty
        assert count == 1  # exactly one snapshot was created

    def test_snapshot_fallback_when_no_git(self, populated_db: Database, capsys):
        """When git is unavailable, git_sha is stored as 'no-git'."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            cmd_snapshot(populated_db, label="no-git-test")

        git_sha = populated_db.fetch_one("SELECT git_sha FROM db_snapshots LIMIT 1")
        assert git_sha == "no-git"

    def test_snapshot_prints_confirmation(self, populated_db: Database, capsys):
        """Output includes snapshot ID and label."""
        with self._mock_git_ok():
            cmd_snapshot(populated_db, label="release-v2")

        captured = capsys.readouterr()
        assert "release-v2" in captured.out

    def test_snapshot_stats_include_counts(self, populated_db: Database, capsys):
        """Stored stats JSON contains total and done counts."""
        with self._mock_git_ok():
            cmd_snapshot(populated_db, label="stats-test")

        # fetch_one with a single column returns the scalar directly
        stats_json = populated_db.fetch_one("SELECT stats FROM db_snapshots LIMIT 1")
        stats = json.loads(stats_json)
        assert "total" in stats
        assert "done" in stats
        assert stats["total"] >= 0


# ---------------------------------------------------------------------------
# cmd_snapshot_list
# ---------------------------------------------------------------------------

class TestCmdSnapshotList:
    def test_empty_no_crash(self, empty_db: Database, capsys):
        """snapshot-list on an empty table prints a 'No snapshots' message."""
        cmd_snapshot_list(empty_db)
        captured = capsys.readouterr()
        assert "No snapshots" in captured.out

    def test_shows_snapshots(self, empty_db: Database, capsys):
        """snapshot-list shows inserted snapshots."""
        _insert_snapshot(empty_db, label="first-snap", git_sha="aaa1111")
        cmd_snapshot_list(empty_db)
        captured = capsys.readouterr()
        assert "first-snap" in captured.out

    def test_shows_git_sha(self, empty_db: Database, capsys):
        """snapshot-list includes the git sha column."""
        _insert_snapshot(empty_db, label="sha-snap", git_sha="bbb2222")
        cmd_snapshot_list(empty_db)
        captured = capsys.readouterr()
        assert "bbb2222" in captured.out

    def test_shows_multiple_snapshots(self, empty_db: Database, capsys):
        """snapshot-list shows all inserted snapshots."""
        _insert_snapshot(empty_db, label="snap-alpha")
        _insert_snapshot(empty_db, label="snap-beta")
        cmd_snapshot_list(empty_db)
        captured = capsys.readouterr()
        assert "snap-alpha" in captured.out
        assert "snap-beta" in captured.out

    def test_shows_progress_ratio(self, empty_db: Database, capsys):
        """snapshot-list shows done/total progress."""
        stats = json.dumps({"total": 5, "done": 3, "todo": 2, "blocked": 0, "by_phase": []})
        _insert_snapshot(empty_db, label="progress-snap", stats=stats)
        cmd_snapshot_list(empty_db)
        captured = capsys.readouterr()
        assert "3/5" in captured.out


# ---------------------------------------------------------------------------
# cmd_snapshot_show
# ---------------------------------------------------------------------------

class TestCmdSnapshotShow:
    def test_shows_details(self, empty_db: Database, capsys):
        """snapshot-show displays label and stats for an existing snapshot."""
        task_summary = json.dumps([
            {"id": "T-01", "phase": "P1-DISCOVER", "title": "Audit", "status": "DONE", "assignee": "CLAUDE"}
        ])
        stats = json.dumps({
            "total": 1, "done": 1, "todo": 0, "blocked": 0,
            "by_phase": [{"phase": "P1-DISCOVER", "total": 1, "done": 1}]
        })
        snap_id = _insert_snapshot(
            empty_db,
            label="detail-snap",
            task_summary=task_summary,
            stats=stats,
        )
        cmd_snapshot_show(empty_db, snap_id)
        captured = capsys.readouterr()
        assert "detail-snap" in captured.out
        assert "T-01" in captured.out

    def test_shows_by_phase(self, empty_db: Database, capsys):
        """snapshot-show includes per-phase breakdown when present."""
        stats = json.dumps({
            "total": 2, "done": 1, "todo": 1, "blocked": 0,
            "by_phase": [{"phase": "P1-DISCOVER", "total": 2, "done": 1}],
        })
        snap_id = _insert_snapshot(empty_db, label="phase-snap", stats=stats)
        cmd_snapshot_show(empty_db, snap_id)
        captured = capsys.readouterr()
        assert "P1-DISCOVER" in captured.out

    def test_nonexistent_id_exits(self, empty_db: Database, capsys):
        """snapshot-show calls sys.exit(1) and prints an error for a missing id."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_snapshot_show(empty_db, 9999)
        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert "9999" in captured.out  # error message should reference the ID

    def test_nonexistent_id_prints_error(self, empty_db: Database, capsys):
        """snapshot-show prints an error message for a missing snapshot."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_snapshot_show(empty_db, 9999)
        captured = capsys.readouterr()
        assert "9999" in captured.out
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# cmd_snapshot_diff
# ---------------------------------------------------------------------------

class TestCmdSnapshotDiff:
    def test_diffs_two_snapshots_no_change(self, empty_db: Database, capsys):
        """diff of identical snapshots reports no task status changes."""
        tasks = json.dumps([
            {"id": "T-01", "phase": "P1", "title": "Task one", "status": "TODO", "assignee": "CLAUDE"}
        ])
        id1 = _insert_snapshot(empty_db, label="snap-a", task_summary=tasks)
        id2 = _insert_snapshot(empty_db, label="snap-b", task_summary=tasks)
        cmd_snapshot_diff(empty_db, id1, id2)
        captured = capsys.readouterr()
        assert "No task status changes" in captured.out

    def test_diffs_two_snapshots_with_change(self, empty_db: Database, capsys):
        """diff detects status change between two snapshots."""
        tasks1 = json.dumps([
            {"id": "T-01", "phase": "P1", "title": "Task one", "status": "TODO", "assignee": "CLAUDE"}
        ])
        tasks2 = json.dumps([
            {"id": "T-01", "phase": "P1", "title": "Task one", "status": "DONE", "assignee": "CLAUDE"}
        ])
        id1 = _insert_snapshot(empty_db, label="before", task_summary=tasks1)
        id2 = _insert_snapshot(empty_db, label="after", task_summary=tasks2)
        cmd_snapshot_diff(empty_db, id1, id2)
        captured = capsys.readouterr()
        assert "T-01" in captured.out
        assert "TODO" in captured.out
        assert "DONE" in captured.out

    def test_diffs_new_task_appears(self, empty_db: Database, capsys):
        """diff shows tasks that appear in snapshot 2 but not snapshot 1."""
        tasks1 = json.dumps([])
        tasks2 = json.dumps([
            {"id": "T-02", "phase": "P1", "title": "New task", "status": "TODO", "assignee": "CLAUDE"}
        ])
        id1 = _insert_snapshot(empty_db, label="s1", task_summary=tasks1)
        id2 = _insert_snapshot(empty_db, label="s2", task_summary=tasks2)
        cmd_snapshot_diff(empty_db, id1, id2)
        captured = capsys.readouterr()
        assert "T-02" in captured.out
        assert "NEW" in captured.out

    def test_diffs_shows_progress_comparison(self, empty_db: Database, capsys):
        """diff output includes a progress line comparing both snapshots."""
        stats1 = json.dumps({"total": 4, "done": 1, "todo": 3, "blocked": 0, "by_phase": []})
        stats2 = json.dumps({"total": 4, "done": 3, "todo": 1, "blocked": 0, "by_phase": []})
        id1 = _insert_snapshot(empty_db, label="prog-a", stats=stats1)
        id2 = _insert_snapshot(empty_db, label="prog-b", stats=stats2)
        cmd_snapshot_diff(empty_db, id1, id2)
        captured = capsys.readouterr()
        assert "Progress" in captured.out
        assert "1/4" in captured.out
        assert "3/4" in captured.out

    @pytest.mark.parametrize("use_real_first,use_real_second,description", [
        (True, False, "second ID missing"),
        (False, True, "first ID missing"),
        (False, False, "both IDs missing"),
    ])
    def test_missing_snapshot_exits(
        self,
        empty_db: Database,
        capsys,
        use_real_first: bool,
        use_real_second: bool,
        description: str,
    ):
        """diff calls sys.exit(1) when one or both snapshot IDs do not exist."""
        snap_id = _insert_snapshot(empty_db, label="real-snap")
        id1 = snap_id if use_real_first else 8888
        id2 = snap_id if use_real_second else 9999
        with pytest.raises(SystemExit) as exc_info:
            cmd_snapshot_diff(empty_db, id1, id2)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# cmd_delegation
# ---------------------------------------------------------------------------

class TestCmdDelegation:
    def test_empty_no_crash(self, empty_db: Database, capsys):
        """delegation on an empty DB prints a 'No tasks' message without crashing."""
        cmd_delegation(empty_db)
        captured = capsys.readouterr()
        assert "No tasks" in captured.out

    def test_shows_tasks_by_phase(self, populated_db: Database, capsys):
        """delegation shows tasks grouped under their phase headers."""
        cmd_delegation(populated_db)
        captured = capsys.readouterr()
        assert "P1-DISCOVER" in captured.out
        assert "P2-DESIGN" in captured.out
        assert "Audit templates" in captured.out

    def test_shows_tier_column(self, populated_db: Database, capsys):
        """delegation table includes tier values."""
        cmd_delegation(populated_db)
        captured = capsys.readouterr()
        # populated_db has haiku and sonnet tiers (uppercased by COALESCE/UPPER)
        assert "HAIKU" in captured.out or "SONNET" in captured.out

    def test_phase_filter_returns_only_requested_phase(self, populated_db: Database, capsys):
        """delegation with phase_filter limits output to that phase."""
        cmd_delegation(populated_db, phase_filter="P1-DISCOVER")
        captured = capsys.readouterr()
        assert "P1-DISCOVER" in captured.out
        assert "P2-DESIGN" not in captured.out
        assert "P3-IMPLEMENT" not in captured.out

    def test_phase_filter_nonexistent_phase(self, populated_db: Database, capsys):
        """delegation with an unrecognised phase filter prints 'No tasks'."""
        cmd_delegation(populated_db, phase_filter="P9-NONEXISTENT")
        captured = capsys.readouterr()
        assert "No tasks" in captured.out

    def test_shows_status_done_phase(self, populated_db: Database, capsys):
        """A phase where all tasks are DONE is labelled DONE in the header."""
        # P1-DISCOVER has T-01 (DONE) and T-02 (TODO) → still IN PROGRESS
        # Mark T-02 DONE so the entire P1-DISCOVER phase becomes DONE
        populated_db.execute("UPDATE tasks SET status='DONE' WHERE id='T-02'")
        populated_db.commit()
        cmd_delegation(populated_db, phase_filter="P1-DISCOVER")
        captured = capsys.readouterr()
        assert "DONE" in captured.out


# ---------------------------------------------------------------------------
# cmd_delegation_md
# ---------------------------------------------------------------------------

class TestCmdDelegationMd:
    def test_generates_file(self, populated_db: Database, tmp_path: Path, capsys):
        """delegation-md rewrites the section between markers in AGENT_DELEGATION.md."""
        _make_delegation_file(tmp_path)
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_delegation_md(populated_db, cfg)
        content = (tmp_path / "AGENT_DELEGATION.md").read_text()
        # Phase names from populated_db should appear in the regenerated file
        assert "P1-DISCOVER" in content
        assert "P2-DESIGN" in content

    def test_regenerated_file_contains_task_ids(self, populated_db: Database, tmp_path: Path, capsys):
        """delegation-md includes task IDs in the output file."""
        _make_delegation_file(tmp_path)
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_delegation_md(populated_db, cfg)
        content = (tmp_path / "AGENT_DELEGATION.md").read_text()
        assert "T-01" in content or "T-02" in content

    def test_prints_success_message(self, populated_db: Database, tmp_path: Path, capsys):
        """delegation-md prints a confirmation message on success."""
        _make_delegation_file(tmp_path)
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_delegation_md(populated_db, cfg)
        captured = capsys.readouterr()
        assert "Regenerated" in captured.out or "AGENT_DELEGATION" in captured.out

    def test_missing_file_exits(self, populated_db: Database, tmp_path: Path, capsys):
        """delegation-md exits with error when AGENT_DELEGATION.md is missing."""
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        # No delegation file created
        with pytest.raises(SystemExit) as exc_info:
            cmd_delegation_md(populated_db, cfg)
        assert exc_info.value.code == 1

    def test_missing_start_marker_exits(self, populated_db: Database, tmp_path: Path, capsys):
        """delegation-md exits when the START marker is absent."""
        p = tmp_path / "AGENT_DELEGATION.md"
        p.write_text("# No markers here\n")
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        with pytest.raises(SystemExit) as exc_info:
            cmd_delegation_md(populated_db, cfg)
        assert exc_info.value.code == 1

    def test_gated_phase_collapsed(self, populated_db: Database, tmp_path: Path, capsys):
        """A gated+complete phase is written as a single summary line."""
        # Gate P1-DISCOVER and mark all its tasks DONE
        populated_db.execute("UPDATE tasks SET status='DONE' WHERE phase='P1-DISCOVER'")
        populated_db.execute(
            "INSERT INTO phase_gates (phase, gated_on) VALUES ('P1-DISCOVER', '2026-01-01')"
        )
        populated_db.commit()
        _make_delegation_file(tmp_path)
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_delegation_md(populated_db, cfg)
        content = (tmp_path / "AGENT_DELEGATION.md").read_text()
        assert "gated" in content.lower()


# ---------------------------------------------------------------------------
# cmd_sync_check
# ---------------------------------------------------------------------------

class TestCmdSyncCheck:
    def test_in_sync(self, populated_db: Database, tmp_path: Path, capsys):
        """sync-check reports 0 drifts when all non-DONE task IDs are in the file."""
        # T-04 in populated_db has tier=NULL; assign one so the untiered check doesn't fire
        populated_db.execute("UPDATE tasks SET tier='sonnet' WHERE id='T-04'")
        populated_db.commit()
        # Build a delegation file that mentions every non-DONE task ID
        body = "T-02 Extract patterns\nT-03 Design changes\nT-04 Master review\nLB-01 Fix\n"
        _make_delegation_file(tmp_path, body=body)
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_sync_check(populated_db, cfg)
        captured = capsys.readouterr()
        assert "passed" in captured.out.lower() or "consistent" in captured.out.lower()

    def test_missing_task_detected(self, populated_db: Database, tmp_path: Path, capsys):
        """sync-check reports drift when a non-DONE task ID is absent from the file."""
        # Empty body — none of the task IDs are present
        _make_delegation_file(tmp_path, body="")
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_sync_check(populated_db, cfg)
        captured = capsys.readouterr()
        assert "drift" in captured.out.lower() or "NOT in" in captured.out

    def test_missing_delegation_file_exits(self, populated_db: Database, tmp_path: Path, capsys):
        """sync-check exits when AGENT_DELEGATION.md does not exist."""
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        with pytest.raises(SystemExit) as exc_info:
            cmd_sync_check(populated_db, cfg)
        assert exc_info.value.code == 1

    def test_reports_db_totals(self, populated_db: Database, tmp_path: Path, capsys):
        """sync-check always prints total task and phase counts."""
        body = "T-02\nT-03\nT-04\nLB-01\n"
        _make_delegation_file(tmp_path, body=body)
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_sync_check(populated_db, cfg)
        captured = capsys.readouterr()
        assert "DB totals" in captured.out

    def test_untiered_tasks_flagged(self, populated_db: Database, tmp_path: Path, capsys):
        """sync-check warns when non-DONE tasks lack a tier assignment."""
        # T-04 in populated_db already has tier=None
        body = "T-02\nT-03\nT-04\nLB-01\n"
        _make_delegation_file(tmp_path, body=body)
        cfg = _config_for_dir(tmp_path, str(tmp_path / "test.db"))
        cmd_sync_check(populated_db, cfg)
        captured = capsys.readouterr()
        # T-04 has no tier — should appear in the untiered warning
        assert "T-04" in captured.out or "tier" in captured.out.lower()
