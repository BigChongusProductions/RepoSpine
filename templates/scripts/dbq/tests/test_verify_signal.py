"""Tests for the verify signal output in cmd_done (tasks.py).

The verify signal fires after _check_phase_complete() when a task is
marked done. It prints "VERIFY RECOMMENDED" when the task tier warrants
human/agent verification (sonnet, opus, etc.) or when a large number of
files were touched.
"""
import pytest
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

from dbq.db import Database
from dbq.config import ProjectConfig
from dbq.commands.tasks import cmd_done


# ---------------------------------------------------------------------------
# Helpers (mirror test_tasks.py conventions)
# ---------------------------------------------------------------------------

def _insert_task(
    db: Database,
    task_id: str,
    phase: str = "P1-TEST",
    status: str = "TODO",
    assignee: str = "CLAUDE",
    tier: Optional[str] = "haiku",
    blocked_by: Optional[str] = None,
    track: str = "forward",
    sort_order: int = 1,
) -> None:
    """Insert a minimal task row for testing."""
    db.execute(
        "INSERT INTO tasks "
        "(id, phase, title, status, assignee, tier, blocked_by, "
        "track, sort_order, queue, severity, gate_critical) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'A', 3, 0)",
        (
            task_id,
            phase,
            f"Task {task_id}",
            status,
            assignee,
            tier,
            blocked_by,
            track,
            sort_order,
        ),
    )
    db.commit()


def _make_config(db: Database, tmp_path: Path) -> ProjectConfig:
    """Build a ProjectConfig pointing at the test DB in a temp project dir."""
    return ProjectConfig(
        db_path=str(tmp_path / "test.db"),
        project_name="test",
        phases=["P1-TEST", "P2-TEST", "P3-TEST"],
    )


def _run_done(
    db: Database,
    config: ProjectConfig,
    task_id: str,
    files: Optional[List[str]] = None,
) -> str:
    """Call cmd_done with git mocked out. Returns captured stdout."""
    ...  # defined inline in each test via capsys


# ---------------------------------------------------------------------------
# Verify signal: tier-based triggering
# ---------------------------------------------------------------------------

class TestVerifySignalTierBased:
    def test_sonnet_tier_prints_verify_recommended(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Sonnet-tier task marked done triggers 'VERIFY RECOMMENDED' output."""
        _insert_task(empty_db, "T-SIG-1", tier="sonnet")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-SIG-1", skip_break=True)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" in out
        assert "T-SIG-1" in out

    def test_opus_tier_prints_verify_recommended(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Opus-tier task marked done triggers 'VERIFY RECOMMENDED' output."""
        _insert_task(empty_db, "T-SIG-2", tier="opus")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-SIG-2", skip_break=True)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" in out
        assert "T-SIG-2" in out

    def test_haiku_tier_no_verify_signal(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Haiku-tier task marked done does NOT trigger 'VERIFY RECOMMENDED'."""
        _insert_task(empty_db, "T-SIG-3", tier="haiku")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-SIG-3", skip_break=True)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" not in out

    def test_none_tier_no_verify_signal(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Task with no tier (None) does NOT trigger 'VERIFY RECOMMENDED'."""
        _insert_task(empty_db, "T-SIG-4", tier=None)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-SIG-4", skip_break=True)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" not in out

    def test_skip_tier_no_verify_signal(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Task with tier='skip' does NOT trigger 'VERIFY RECOMMENDED'."""
        _insert_task(empty_db, "T-SIG-5", tier="skip")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-SIG-5", skip_break=True)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" not in out

    @pytest.mark.parametrize("tier,expect_signal", [
        ("sonnet", True),
        ("opus", True),
        ("haiku", False),
        (None, False),
        ("skip", False),
    ])
    def test_tier_signal_parametrized(
        self,
        empty_db: Database,
        simple_config: ProjectConfig,
        capsys: pytest.CaptureFixture,
        tier: Optional[str],
        expect_signal: bool,
    ) -> None:
        """Parametrized: verify signal fires for high-tier tasks only."""
        task_id = f"T-PARAM-{tier or 'none'}"
        _insert_task(empty_db, task_id, tier=tier)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, task_id, skip_break=True)
        out = capsys.readouterr().out
        if expect_signal:
            assert "VERIFY RECOMMENDED" in out
        else:
            assert "VERIFY RECOMMENDED" not in out


# ---------------------------------------------------------------------------
# Verify signal: file-count-based triggering
# ---------------------------------------------------------------------------

class TestVerifySignalFileBased:
    def test_haiku_with_four_files_triggers_signal(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Haiku-tier task with 4 files triggers 'VERIFY RECOMMENDED'."""
        _insert_task(empty_db, "T-FILES-1", tier="haiku")
        files = ["a.py", "b.py", "c.py", "d.py"]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-FILES-1", skip_break=True, files=files)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" in out
        assert "4" in out

    def test_haiku_with_three_files_no_signal(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Haiku-tier task with exactly 3 files does NOT trigger 'VERIFY RECOMMENDED'."""
        _insert_task(empty_db, "T-FILES-2", tier="haiku")
        files = ["a.py", "b.py", "c.py"]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-FILES-2", skip_break=True, files=files)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" not in out

    def test_none_tier_with_four_files_triggers_signal(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """No-tier task with 4+ files still triggers 'VERIFY RECOMMENDED'."""
        _insert_task(empty_db, "T-FILES-3", tier=None)
        files = ["a.py", "b.py", "c.py", "d.py"]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-FILES-3", skip_break=True, files=files)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" in out

    def test_haiku_no_files_no_signal(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """Haiku-tier task with no --files argument does NOT trigger file-count signal."""
        _insert_task(empty_db, "T-FILES-4", tier="haiku")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-FILES-4", skip_break=True, files=None)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" not in out

    @pytest.mark.parametrize("file_count,expect_signal", [
        (3, False),
        (4, True),
        (5, True),
        (10, True),
    ])
    def test_file_count_threshold_parametrized(
        self,
        empty_db: Database,
        simple_config: ProjectConfig,
        capsys: pytest.CaptureFixture,
        file_count: int,
        expect_signal: bool,
    ) -> None:
        """Parametrized: signal fires when more than 3 files are touched."""
        task_id = f"T-FC-{file_count}"
        _insert_task(empty_db, task_id, tier="haiku")
        files = [f"file{i}.py" for i in range(file_count)]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, task_id, skip_break=True, files=files)
        out = capsys.readouterr().out
        if expect_signal:
            assert "VERIFY RECOMMENDED" in out
        else:
            assert "VERIFY RECOMMENDED" not in out


# ---------------------------------------------------------------------------
# Signal content: tier-based output mentions tier and files
# ---------------------------------------------------------------------------

class TestVerifySignalContent:
    def test_signal_mentions_tier(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """VERIFY RECOMMENDED output mentions the tier name."""
        _insert_task(empty_db, "T-CONTENT-1", tier="sonnet")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-CONTENT-1", skip_break=True)
        out = capsys.readouterr().out
        assert "sonnet" in out
        assert "VERIFY RECOMMENDED" in out

    def test_signal_with_files_list_mentions_files(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """When --files provided to a sonnet task, the signal mentions file names."""
        _insert_task(empty_db, "T-CONTENT-2", tier="sonnet")
        files = ["src/module.py", "tests/test_module.py"]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(
                empty_db, simple_config, "T-CONTENT-2", skip_break=True, files=files
            )
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" in out
        assert "src/module.py" in out or "tests/test_module.py" in out

    def test_signal_without_files_says_all_staged(
        self, empty_db: Database, simple_config: ProjectConfig, capsys: pytest.CaptureFixture
    ) -> None:
        """When no --files provided to a sonnet task, signal indicates all files staged."""
        _insert_task(empty_db, "T-CONTENT-3", tier="sonnet")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            cmd_done(empty_db, simple_config, "T-CONTENT-3", skip_break=True)
        out = capsys.readouterr().out
        assert "VERIFY RECOMMENDED" in out
        assert "all staged" in out
