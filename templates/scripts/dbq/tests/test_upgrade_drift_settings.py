"""Tests for upgrade_drift_settings three-way merge (v1.2 → v1.3 migration)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, Any

import pytest

from dbq.commands.upgrade_drift_settings import (
    HookEntry,
    MergeReport,
    merge_settings,
    detect_base_version,
    run_upgrade_drift_settings,
    run_rollback_settings,
    _classify,
    _collect_entries,
)


# ── Helpers ────────────────────────────────────────────────────────────────

V12_BASELINE: Dict[str, Any] = {
    "permissions": {"allow": ["Read(*)"], "deny": []},
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/correction-detector.sh",
                        "timeout": 5}]}
        ],
        "PreToolUse": [
            {"matcher": "Edit|Write",
             "hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/pre-edit-check.sh",
                        "timeout": 10}]},
            {"matcher": "Bash",
             "hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/protect-databases.sh",
                        "timeout": 5}]},
            {"matcher": "Agent",
             "hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/agent-spawn-gate.sh",
                        "timeout": 5}]},
        ],
        "PostToolUse": [
            {"matcher": "Edit|Write",
             "hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/framework-contamination-check.sh",
                        "timeout": 5}]}
        ],
        "Stop": [
            {"hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/end-of-turn-check.sh",
                        "timeout": 10}]}
        ],
    },
}

V13_BASELINE: Dict[str, Any] = {
    "permissions": {"allow": ["Read(*)"], "deny": []},
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/correction-detector.sh",
                        "timeout": 5}]}
        ],
        "PreToolUse": [
            {"matcher": "Edit|Write|MultiEdit|Bash|Agent",
             "hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/pre-tool-gate.sh",
                        "timeout": 10}]}
        ],
        "PostToolUse": [
            {"matcher": "Edit|Write|MultiEdit",
             "hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/post-tool-check.sh",
                        "timeout": 5}]}
        ],
        "Stop": [
            {"hooks": [{"type": "command",
                        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/end-of-turn-check.sh",
                        "timeout": 10}]}
        ],
    },
}


def make_ours_vanilla() -> Dict[str, Any]:
    """User never touched settings.json — identical to v1.2 baseline."""
    return json.loads(json.dumps(V12_BASELINE))


def make_ours_with_custom_prebash() -> Dict[str, Any]:
    """User added a Bash-matcher PreToolUse hook."""
    s = json.loads(json.dumps(V12_BASELINE))
    s["hooks"]["PreToolUse"].append({
        "matcher": "Bash",
        "hooks": [{"type": "command",
                   "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/my-custom-bash-guard.sh",
                   "timeout": 5}]
    })
    return s


def make_ours_modified_stop() -> Dict[str, Any]:
    """User modified Stop hook command."""
    s = json.loads(json.dumps(V12_BASELINE))
    s["hooks"]["Stop"][0]["hooks"][0]["command"] = \
        "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/my-custom-stop.sh"
    return s


def make_ours_fully_custom() -> Dict[str, Any]:
    """Multiple edits: added user-added entry + modified existing."""
    s = make_ours_with_custom_prebash()
    s["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 15
    s["hooks"]["Stop"][0]["hooks"][0]["command"] = \
        "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/my-custom-stop.sh"
    return s


def make_ours_timeout_only_stop() -> Dict[str, Any]:
    """User changed ONLY the Stop hook timeout (command unchanged).

    Regression fixture for Codex P0 review finding: command-only identity
    dropped timeout/type customizations silently.
    """
    s = json.loads(json.dumps(V12_BASELINE))
    s["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 99
    return s


# ── Unit tests for _classify ──────────────────────────────────────────────

class TestClassify:
    def test_inherited_when_signature_matches_base(self):
        base_entries = _collect_entries(V12_BASELINE)["PreToolUse"]
        entry = base_entries[0]  # matcher=Edit|Write, pre-edit-check
        assert _classify(entry, base_entries) == "inherited"

    def test_user_added_when_matcher_new(self):
        base_entries = _collect_entries(V12_BASELINE)["PreToolUse"]
        new = HookEntry.from_raw(
            "PreToolUse",
            {"matcher": "Read", "hooks": [{"type": "command", "command": "custom.sh"}]},
        )
        assert _classify(new, base_entries) == "user-added"

    def test_user_modified_when_matcher_same_command_differs(self):
        base_entries = _collect_entries(V12_BASELINE)["PreToolUse"]
        modified = HookEntry.from_raw(
            "PreToolUse",
            {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "mine.sh"}]},
        )
        assert _classify(modified, base_entries) == "user-modified"


# ── Merge-level tests ─────────────────────────────────────────────────────

class TestMerge:
    def test_vanilla_v12_yields_clean_merge(self):
        ours = make_ours_vanilla()
        merged, report = merge_settings(V12_BASELINE, ours, V13_BASELINE, "1.2.0")
        assert not report.has_conflicts(), \
            f"Expected clean merge; got conflicts: {report.conflicts}"
        # Every OURS entry matches a V12 baseline signature → all inherited, all dropped.
        total_ours_entries = sum(len(v) for v in _collect_entries(V12_BASELINE).values())
        assert len(report.dropped) == total_ours_entries, \
            f"Expected {total_ours_entries} inherited entries dropped, got {len(report.dropped)}"
        # Merged PreToolUse should have exactly 1 entry (the router)
        assert len(merged["hooks"]["PreToolUse"]) == 1

    def test_custom_prebash_preserved_after_router(self):
        ours = make_ours_with_custom_prebash()
        merged, report = merge_settings(V12_BASELINE, ours, V13_BASELINE, "1.2.0")
        # user-added Bash hook: the ORIGINAL v1.2 had protect-databases under Bash matcher,
        # which is inherited. The user's SECOND Bash entry (my-custom-bash-guard) is user-added.
        preserved_cmds = {
            cmd for e in report.preserved for cmd in e.commands
        }
        assert any("my-custom-bash-guard" in c for c in preserved_cmds), \
            f"Custom prebash should appear in preserved; got {preserved_cmds}"
        # Router entry + preserved custom = 2 entries in merged PreToolUse
        assert len(merged["hooks"]["PreToolUse"]) == 2

    def test_modified_stop_flagged_as_conflict(self):
        ours = make_ours_modified_stop()
        merged, report = merge_settings(V12_BASELINE, ours, V13_BASELINE, "1.2.0")
        assert report.has_conflicts(), "Expected conflict on modified Stop hook"
        assert any(c.event == "Stop" for c in report.conflicts), \
            f"Expected Stop conflict; got events: {[c.event for c in report.conflicts]}"

    def test_fully_custom_has_multiple_outcomes(self):
        ours = make_ours_fully_custom()
        merged, report = merge_settings(V12_BASELINE, ours, V13_BASELINE, "1.2.0")
        # Has custom prebash (preserved) AND modified stop (conflict)
        assert report.has_conflicts()
        assert len(report.preserved) >= 1
        assert any("my-custom-bash-guard" in c for e in report.preserved for c in e.commands)

    def test_timeout_only_change_is_conflict(self):
        """Regression: Codex P0 — timeout-only customization must be flagged
        as a conflict, not silently classified as 'inherited' and dropped."""
        ours = make_ours_timeout_only_stop()
        merged, report = merge_settings(V12_BASELINE, ours, V13_BASELINE, "1.2.0")
        assert report.has_conflicts(), \
            "Timeout-only customization must be flagged as conflict"
        assert any(c.event == "Stop" for c in report.conflicts), \
            f"Expected Stop conflict; got events: {[c.event for c in report.conflicts]}"
        # Ensure the OURS entry is NOT silently in the dropped list either
        dropped_cmds = [e.raw.get("hooks", [{}])[0].get("timeout") for e in report.dropped]
        assert 99 not in dropped_cmds, \
            "User's timeout=99 customization must not be silently dropped"


# ── End-to-end tests (run_upgrade_drift_settings) ─────────────────────────

@pytest.fixture()
def fake_bootstrap_root(tmp_path: Path) -> Path:
    """Minimal bootstrap-root layout needed by the command."""
    root = tmp_path / "bootstrap"
    history = root / "templates" / "settings" / "history"
    history.mkdir(parents=True)
    theirs_path = root / "templates" / "settings" / "settings.template.json"
    (history / "settings.template.json.v1.2.0").write_text(json.dumps(V12_BASELINE))
    theirs_path.write_text(json.dumps(V13_BASELINE))
    return root


@pytest.fixture()
def fake_project_with(tmp_path: Path):
    """Factory: give it a settings dict, get back a project dir with it installed."""
    def _make(ours: Dict[str, Any], bootstrap_version: str = "1.2.0") -> Path:
        proj = tmp_path / "project"
        (proj / ".claude").mkdir(parents=True)
        (proj / ".claude" / "settings.json").write_text(json.dumps(ours))
        (proj / ".bootstrap_version").write_text(bootstrap_version)
        return proj
    return _make


class TestRun:
    def test_vanilla_dry_run_exits_zero(self, fake_project_with, fake_bootstrap_root):
        proj = fake_project_with(make_ours_vanilla())
        rc = run_upgrade_drift_settings(proj, fake_bootstrap_root, mode="dry-run")
        assert rc == 0
        # Artifacts should be in merged/
        assert (proj / ".claude" / "merged" / "settings.json").exists()
        assert (proj / ".claude" / "merged" / "migration-report.md").exists()

    def test_modified_stop_dry_run_exits_one(self, fake_project_with, fake_bootstrap_root):
        proj = fake_project_with(make_ours_modified_stop())
        rc = run_upgrade_drift_settings(proj, fake_bootstrap_root, mode="dry-run")
        assert rc == 1   # conflicts → exit 1

    def test_apply_refuses_with_conflicts(self, fake_project_with, fake_bootstrap_root):
        proj = fake_project_with(make_ours_fully_custom())
        rc = run_upgrade_drift_settings(proj, fake_bootstrap_root, mode="apply")
        assert rc == 1
        # Should NOT have written the backup (apply refused before that)
        assert not (proj / ".claude" / "settings.json.pre-v1.3").exists()

    def test_apply_succeeds_on_clean_merge(self, fake_project_with, fake_bootstrap_root):
        proj = fake_project_with(make_ours_vanilla())
        rc = run_upgrade_drift_settings(proj, fake_bootstrap_root, mode="apply")
        assert rc == 0
        # Backup created
        backup = proj / ".claude" / "settings.json.pre-v1.3"
        assert backup.exists()
        # Bootstrap version bumped
        assert (proj / ".bootstrap_version").read_text().strip() == "1.3.0"
        # settings.json now has the v1.3 router structure
        settings = json.loads((proj / ".claude" / "settings.json").read_text())
        pre = settings["hooks"]["PreToolUse"]
        assert len(pre) == 1
        assert pre[0]["matcher"] == "Edit|Write|MultiEdit|Bash|Agent"

    def test_emit_patch_writes_proposed_without_touching_live(self, fake_project_with, fake_bootstrap_root):
        proj = fake_project_with(make_ours_vanilla())
        original = (proj / ".claude" / "settings.json").read_text()
        rc = run_upgrade_drift_settings(proj, fake_bootstrap_root, mode="emit-patch")
        assert rc == 0
        assert (proj / ".claude" / "settings.json.v1.3-proposed").exists()
        # Live settings.json unchanged
        assert (proj / ".claude" / "settings.json").read_text() == original

    def test_rollback_restores_from_backup(self, fake_project_with, fake_bootstrap_root):
        proj = fake_project_with(make_ours_vanilla())
        run_upgrade_drift_settings(proj, fake_bootstrap_root, mode="apply")
        # Corrupt settings (simulate trouble after apply)
        (proj / ".claude" / "settings.json").write_text('{"corrupted": true}')
        rc = run_rollback_settings(proj)
        assert rc == 0
        settings = json.loads((proj / ".claude" / "settings.json").read_text())
        # Restored to pre-v1.3 (which was vanilla v1.2)
        assert "corrupted" not in settings
        assert "hooks" in settings

    def test_rollback_restores_bootstrap_version(self, fake_project_with, fake_bootstrap_root):
        """Regression: Codex P1 — rollback must restore .bootstrap_version too,
        otherwise settings.json is at v1.2 content but the version file still
        advertises 1.3.0."""
        proj = fake_project_with(make_ours_vanilla(), bootstrap_version="1.2.0")
        run_upgrade_drift_settings(proj, fake_bootstrap_root, mode="apply")
        # After apply, .bootstrap_version should be 1.3.0
        assert (proj / ".bootstrap_version").read_text().strip() == "1.3.0"
        # After rollback, it should be back to 1.2.0
        run_rollback_settings(proj)
        assert (proj / ".bootstrap_version").read_text().strip() == "1.2.0", \
            "rollback must restore .bootstrap_version to pre-v1.3 value"


class TestDetectBaseVersion:
    def test_reads_bootstrap_version_file(self, tmp_path: Path):
        proj = tmp_path / "p"
        proj.mkdir()
        (proj / ".bootstrap_version").write_text("1.2.0\n")
        assert detect_base_version(proj) == "1.2.0"

    def test_falls_back_when_missing(self, tmp_path: Path):
        proj = tmp_path / "p"
        proj.mkdir()
        assert detect_base_version(proj) == "1.2.0"
