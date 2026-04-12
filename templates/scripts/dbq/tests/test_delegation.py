"""
Tests for delegation commands: tier-up.

Uses the shared fixtures from conftest.py (empty_db, simple_config).
"""
import pytest

from dbq.db import Database
from dbq.commands.delegation import cmd_tier_up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_task(db: Database, task_id: str, tier: str = "haiku",
                 status: str = "TODO", original_tier: str = None):
    """Insert a minimal task for delegation testing."""
    db.execute(
        "INSERT INTO tasks "
        "(id, phase, title, status, assignee, tier, original_tier, "
        "track, sort_order, queue, severity, gate_critical) "
        "VALUES (?, 'P1-TEST', ?, ?, 'CLAUDE', ?, ?, "
        "'forward', 1, 'A', 3, 0)",
        (task_id, f"Task {task_id}", status, tier, original_tier),
    )
    db.commit()


# ---------------------------------------------------------------------------
# cmd_tier_up
# ---------------------------------------------------------------------------

class TestCmdTierUp:
    def test_escalates_haiku_to_sonnet(self, empty_db: Database, capsys):
        """Basic escalation: haiku → sonnet updates tier and records metadata."""
        _insert_task(empty_db, "T-ESC", tier="haiku", original_tier="haiku")
        cmd_tier_up(empty_db, "T-ESC", "sonnet", "ceiling")

        row = empty_db.fetch_one(
            "SELECT tier, original_tier, escalation_reason, escalation_count "
            "FROM tasks WHERE id='T-ESC'"
        )
        assert row["tier"] == "sonnet"
        assert row["original_tier"] == "haiku"
        assert row["escalation_reason"] == "ceiling"
        assert row["escalation_count"] == 1

        out = capsys.readouterr().out
        assert "sonnet" in out
        assert "T-ESC" in out

    def test_escalates_sonnet_to_opus(self, empty_db: Database, capsys):
        """Escalation: sonnet → opus."""
        _insert_task(empty_db, "T-ESC2", tier="sonnet", original_tier="haiku")
        cmd_tier_up(empty_db, "T-ESC2", "opus", "context")

        row = empty_db.fetch_one(
            "SELECT tier, original_tier, escalation_count "
            "FROM tasks WHERE id='T-ESC2'"
        )
        assert row["tier"] == "opus"
        assert row["original_tier"] == "haiku"  # unchanged from first assignment
        assert row["escalation_count"] == 1

    def test_increments_escalation_count(self, empty_db: Database, capsys):
        """Multiple escalations increment the counter."""
        _insert_task(empty_db, "T-MULTI", tier="haiku", original_tier="haiku")
        cmd_tier_up(empty_db, "T-MULTI", "sonnet", "ceiling")
        cmd_tier_up(empty_db, "T-MULTI", "opus", "context")

        row = empty_db.fetch_one(
            "SELECT tier, escalation_count FROM tasks WHERE id='T-MULTI'"
        )
        assert row["tier"] == "opus"
        assert row["escalation_count"] == 2

    def test_backfills_original_tier_when_null(self, empty_db: Database, capsys):
        """Pre-migration tasks (original_tier=NULL) get backfilled on first escalation."""
        _insert_task(empty_db, "T-LEGACY", tier="haiku", original_tier=None)
        cmd_tier_up(empty_db, "T-LEGACY", "sonnet", "prompt")

        row = empty_db.fetch_one(
            "SELECT tier, original_tier FROM tasks WHERE id='T-LEGACY'"
        )
        assert row["original_tier"] == "haiku"

    def test_rejects_downgrade(self, empty_db: Database):
        """Cannot escalate from a higher tier to a lower one."""
        _insert_task(empty_db, "T-DOWN", tier="opus", original_tier="sonnet")
        with pytest.raises(SystemExit) as exc_info:
            cmd_tier_up(empty_db, "T-DOWN", "haiku", "ceiling")
        assert exc_info.value.code == 1

    def test_rejects_same_tier(self, empty_db: Database):
        """Cannot 'escalate' to the same tier."""
        _insert_task(empty_db, "T-SAME", tier="sonnet", original_tier="sonnet")
        with pytest.raises(SystemExit) as exc_info:
            cmd_tier_up(empty_db, "T-SAME", "sonnet", "ceiling")
        assert exc_info.value.code == 1

    def test_rejects_invalid_reason(self, empty_db: Database):
        """Invalid escalation reason is rejected."""
        _insert_task(empty_db, "T-BAD-R", tier="haiku")
        with pytest.raises(SystemExit) as exc_info:
            cmd_tier_up(empty_db, "T-BAD-R", "sonnet", "laziness")
        assert exc_info.value.code == 1

    def test_rejects_invalid_tier(self, empty_db: Database):
        """Invalid target tier is rejected."""
        _insert_task(empty_db, "T-BAD-T", tier="haiku")
        with pytest.raises(SystemExit) as exc_info:
            cmd_tier_up(empty_db, "T-BAD-T", "gpt5", "ceiling")
        assert exc_info.value.code == 1

    def test_rejects_nonexistent_task(self, empty_db: Database):
        """Nonexistent task ID is rejected."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_tier_up(empty_db, "GHOST-99", "sonnet", "ceiling")
        assert exc_info.value.code == 1

    def test_rejects_done_task(self, empty_db: Database):
        """Cannot escalate a task that's already DONE."""
        _insert_task(empty_db, "T-DONE", tier="haiku", status="DONE")
        with pytest.raises(SystemExit) as exc_info:
            cmd_tier_up(empty_db, "T-DONE", "sonnet", "ceiling")
        assert exc_info.value.code == 1

    def test_all_valid_reasons_accepted(self, empty_db: Database, capsys):
        """All 4 valid reasons are accepted."""
        for i, reason in enumerate(("prompt", "context", "ceiling", "environment")):
            tid = f"T-R{i}"
            _insert_task(empty_db, tid, tier="haiku", original_tier="haiku")
            cmd_tier_up(empty_db, tid, "sonnet", reason)
            row = empty_db.fetch_one(
                "SELECT tier, escalation_reason FROM tasks WHERE id=?", (tid,)
            )
            assert row["escalation_reason"] == reason
