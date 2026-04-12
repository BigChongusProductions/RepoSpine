"""
Tests for knowledge and falsification command modules:
    commands/falsification.py — assume, verify-assumption, verify-all, assumptions
    commands/knowledge.py     — lessons, log-lesson, promote, escalate
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dbq.db import Database
from dbq.config import ProjectConfig
from dbq.commands.falsification import (
    cmd_assume,
    cmd_verify_assumption,
    cmd_verify_all,
    cmd_assumptions,
)
from dbq.commands.knowledge import (
    cmd_lessons,
    cmd_log_lesson,
    cmd_promote,
    cmd_escalate,
    cmd_harvest,
    _mark_source_promoted,
    _parse_unpromoted,
    _load_universal_entries,
    _score_dedup,
    _extract_keywords,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_assumption(
    db: Database,
    task_id: str,
    assumption: str,
    verify_cmd: str = "",
    verified: int = 0,
) -> int:
    """Insert an assumption row directly and return its id."""
    if verify_cmd:
        db.execute(
            "INSERT INTO assumptions (task_id, assumption, verify_cmd, verified) "
            "VALUES (?, ?, ?, ?)",
            (task_id, assumption, verify_cmd, verified),
        )
    else:
        db.execute(
            "INSERT INTO assumptions (task_id, assumption, verified) "
            "VALUES (?, ?, ?)",
            (task_id, assumption, verified),
        )
    db.commit()
    return db.fetch_scalar(
        "SELECT MAX(id) FROM assumptions WHERE task_id=?", (task_id,)
    )


def _make_lessons_file(tmp_path: Path, content: str) -> Path:
    """Create a LESSONS.md file in tmp_path and return its path."""
    lf = tmp_path / "LESSONS_TEST.md"
    lf.write_text(content)
    return lf


def _make_config(tmp_path: Path, populated_db: Database, lessons_file: str = "") -> ProjectConfig:
    """Build a ProjectConfig using an existing populated_db."""
    return ProjectConfig(
        db_path=str(tmp_path / "test.db"),
        project_name="test-project",
        phases=["P1-DISCOVER", "P2-DESIGN", "P3-IMPLEMENT"],
        lessons_file=lessons_file,
    )


# ---------------------------------------------------------------------------
# TestCmdAssume
# ---------------------------------------------------------------------------

class TestCmdAssume:
    def test_creates_assumption(self, populated_db: Database, capsys):
        """assume command inserts a new row and prints confirmation."""
        cmd_assume(populated_db, "T-02", "The parser handles UTF-8 input")
        out = capsys.readouterr().out
        assert "Assumption #" in out
        assert "T-02" in out
        assert "The parser handles UTF-8 input" in out
        # Row should exist in DB
        row = populated_db.fetch_one(
            "SELECT assumption FROM assumptions WHERE task_id='T-02'"
        )
        assert row is not None
        assert "UTF-8" in str(row)

    def test_with_verify_cmd(self, populated_db: Database, capsys):
        """assume with verify_cmd stores cmd and prints it."""
        cmd_assume(populated_db, "T-02", "Python 3.11+ is available", verify_cmd="python3 --version")
        out = capsys.readouterr().out
        assert "python3 --version" in out
        # Row stored with verify_cmd
        row = populated_db.fetch_one(
            "SELECT verify_cmd FROM assumptions WHERE task_id='T-02'"
        )
        assert row is not None
        assert "python3" in str(row)

    def test_without_verify_cmd_prints_manual(self, populated_db: Database, capsys):
        """assume without verify_cmd prints 'manual' verification note."""
        cmd_assume(populated_db, "T-01", "Tests always pass on CI")
        out = capsys.readouterr().out
        assert "manual" in out.lower()

    def test_invalid_task_exits(self, populated_db: Database):
        """assume on nonexistent task_id calls sys.exit."""
        with pytest.raises(SystemExit):
            cmd_assume(populated_db, "NONEXISTENT", "some assumption")

    def test_assumption_id_increments(self, populated_db: Database, capsys):
        """Multiple assumptions for same task get distinct incrementing IDs."""
        cmd_assume(populated_db, "T-02", "First assumption")
        capsys.readouterr()
        cmd_assume(populated_db, "T-02", "Second assumption")
        capsys.readouterr()
        count = populated_db.fetch_scalar(
            "SELECT COUNT(*) FROM assumptions WHERE task_id='T-02'"
        )
        assert count == 2


# ---------------------------------------------------------------------------
# TestCmdVerifyAssumption
# ---------------------------------------------------------------------------

class TestCmdVerifyAssumption:
    def test_passes_verification(self, populated_db: Database, capsys):
        """verify-assumption marks verified=1 when subprocess returns 0."""
        aid = _insert_assumption(
            populated_db, "T-02", "Shell is available", verify_cmd="true"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("dbq.commands.falsification.subprocess.run", return_value=mock_result):
            cmd_verify_assumption(populated_db, "T-02", aid)
        out = capsys.readouterr().out
        assert "PASSED" in out
        row = populated_db.fetch_one(
            "SELECT verified FROM assumptions WHERE id=?", (aid,)
        )
        assert row == 1

    def test_fails_verification(self, populated_db: Database, capsys):
        """verify-assumption marks verified=-1 when subprocess returns nonzero."""
        aid = _insert_assumption(
            populated_db, "T-02", "File exists", verify_cmd="false"
        )
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"
        with patch("dbq.commands.falsification.subprocess.run", return_value=mock_result):
            cmd_verify_assumption(populated_db, "T-02", aid)
        out = capsys.readouterr().out
        assert "FAILED" in out
        row = populated_db.fetch_one(
            "SELECT verified FROM assumptions WHERE id=?", (aid,)
        )
        assert row == -1

    def test_manual_verification_no_cmd(self, populated_db: Database, capsys):
        """verify-assumption with no verify_cmd prints manual instructions."""
        aid = _insert_assumption(populated_db, "T-02", "UI looks correct")
        cmd_verify_assumption(populated_db, "T-02", aid)
        out = capsys.readouterr().out
        assert "manual" in out.lower() or "Manual" in out

    def test_invalid_assumption_id_exits(self, populated_db: Database):
        """verify-assumption with nonexistent assumption_id calls sys.exit."""
        with pytest.raises(SystemExit):
            cmd_verify_assumption(populated_db, "T-02", 99999)

    def test_verified_on_is_set(self, populated_db: Database, capsys):
        """verify-assumption sets verified_on date on pass."""
        aid = _insert_assumption(
            populated_db, "T-02", "DB accessible", verify_cmd="true"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("dbq.commands.falsification.subprocess.run", return_value=mock_result):
            cmd_verify_assumption(populated_db, "T-02", aid)
        row = populated_db.fetch_one(
            "SELECT verified_on FROM assumptions WHERE id=?", (aid,)
        )
        assert row is not None


# ---------------------------------------------------------------------------
# TestCmdVerifyAll
# ---------------------------------------------------------------------------

class TestCmdVerifyAll:
    def test_runs_all_checks(self, populated_db: Database, capsys):
        """verify-all runs every unverified assumption with a verify_cmd."""
        _insert_assumption(populated_db, "T-02", "Check A", verify_cmd="true")
        _insert_assumption(populated_db, "T-02", "Check B", verify_cmd="false")
        mock_pass = MagicMock(returncode=0, stdout="ok", stderr="")
        mock_fail = MagicMock(returncode=1, stdout="", stderr="err")
        with patch(
            "dbq.commands.falsification.subprocess.run",
            side_effect=[mock_pass, mock_fail],
        ):
            cmd_verify_all(populated_db, "T-02")
        out = capsys.readouterr().out
        assert "PASSED" in out
        assert "FAILED" in out
        assert "1 passed" in out
        assert "1 failed" in out

    def test_no_unverified_assumptions(self, populated_db: Database, capsys):
        """verify-all with no unverified assumptions prints 'No unverified' message."""
        cmd_verify_all(populated_db, "T-02")
        out = capsys.readouterr().out
        assert "No unverified" in out

    def test_manual_assumptions_counted(self, populated_db: Database, capsys):
        """verify-all counts manual assumptions (no verify_cmd) separately."""
        _insert_assumption(populated_db, "T-02", "Manual review needed")
        cmd_verify_all(populated_db, "T-02")
        out = capsys.readouterr().out
        assert "manual" in out

    def test_updates_db_after_run(self, populated_db: Database, capsys):
        """verify-all persists pass/fail results to the DB."""
        aid = _insert_assumption(
            populated_db, "T-02", "Service reachable", verify_cmd="ping"
        )
        mock_result = MagicMock(returncode=0, stdout="pong", stderr="")
        with patch("dbq.commands.falsification.subprocess.run", return_value=mock_result):
            cmd_verify_all(populated_db, "T-02")
        row = populated_db.fetch_one(
            "SELECT verified FROM assumptions WHERE id=?", (aid,)
        )
        assert row == 1


# ---------------------------------------------------------------------------
# TestCmdAssumptions
# ---------------------------------------------------------------------------

class TestCmdAssumptions:
    def test_empty_no_crash(self, empty_db: Database, capsys):
        """assumptions with no rows prints a 'No assumptions' message."""
        # Need a valid task to avoid other issues — but the command queries
        # assumptions directly without validating task existence.
        cmd_assumptions(empty_db, "T-NONEXISTENT")
        out = capsys.readouterr().out
        assert "No assumptions" in out

    def test_shows_assumptions(self, populated_db: Database, capsys):
        """assumptions lists inserted rows with status icons."""
        _insert_assumption(populated_db, "T-02", "Parser handles UTF-8", verified=0)
        _insert_assumption(populated_db, "T-02", "DB schema up to date", verified=1)
        cmd_assumptions(populated_db, "T-02")
        out = capsys.readouterr().out
        assert "Parser handles UTF-8" in out
        assert "DB schema up to date" in out

    @pytest.mark.parametrize("verified_value,expected_icon,label", [
        (0, "⏳", "Unverified thing"),
        (1, "✅", "Passed assumption"),
        (-1, "❌", "Failed assumption"),
    ])
    def test_status_icon_shown(
        self,
        populated_db: Database,
        capsys,
        verified_value: int,
        expected_icon: str,
        label: str,
    ):
        """assumptions shows the correct status icon for each verification state."""
        _insert_assumption(populated_db, "T-02", label, verified=verified_value)
        cmd_assumptions(populated_db, "T-02")
        out = capsys.readouterr().out
        assert expected_icon in out
        assert label in out  # the assumption text should also be visible


# ---------------------------------------------------------------------------
# TestCmdLessons
# ---------------------------------------------------------------------------

MINIMAL_LESSONS_CONTENT = """\
# Lessons

<!-- CORRECTIONS-ANCHOR -->

| Date | What happened | Promoted | Prevention Rule | Last Ref | Violations | Promoted |
|------|---------------|----------|-----------------|----------|------------|----------|
| 2026-01-15 | First correction | no | Avoid X | — | 3 | No |
| 2026-02-20 | Second correction | no | Avoid Z | 2026-01-01 | 0 | No |

## Insights
Nothing here yet.
"""


class TestCmdLessons:
    def test_shows_lessons(self, tmp_path: Path, capsys):
        """lessons command prints table rows from LESSONS file."""
        lf = _make_lessons_file(tmp_path, MINIMAL_LESSONS_CONTENT)
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(lf),
        )
        cmd_lessons(config)
        out = capsys.readouterr().out
        assert "Avoid X" in out
        assert "Avoid Z" in out

    def test_no_lessons_file_exits(self, tmp_path: Path):
        """lessons exits when lessons_file is empty string."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file="",
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_lessons(config)
        assert exc_info.value.code == 1

    def test_missing_file_exits(self, tmp_path: Path):
        """lessons exits when the configured file does not exist on disk."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(tmp_path / "NONEXISTENT.md"),
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_lessons(config)
        assert exc_info.value.code == 1

    def test_never_referenced_stale_warning(self, tmp_path: Path, capsys):
        """lessons flags rows with last_ref == '—' as NEVER REFERENCED."""
        lf = _make_lessons_file(tmp_path, MINIMAL_LESSONS_CONTENT)
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(lf),
        )
        cmd_lessons(config)
        out = capsys.readouterr().out
        assert "NEVER REFERENCED" in out

    def test_violation_warning(self, tmp_path: Path, capsys):
        """lessons flags rows with violations >= 2 with a violation warning."""
        lf = _make_lessons_file(tmp_path, MINIMAL_LESSONS_CONTENT)
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(lf),
        )
        cmd_lessons(config)
        out = capsys.readouterr().out
        assert "VIOLATED" in out


# ---------------------------------------------------------------------------
# TestCmdLogLesson
# ---------------------------------------------------------------------------

LESSONS_WITH_ANCHOR = """\
# Lessons

<!-- CORRECTIONS-ANCHOR -->

## Insights
Nothing here yet.
"""

LESSONS_WITH_INSIGHTS = """\
# Lessons

## Insights
Nothing here yet.
"""


class TestCmdLogLesson:
    def test_appends_lesson_via_anchor(self, tmp_path: Path, capsys):
        """log-lesson inserts after CORRECTIONS-ANCHOR."""
        lf = _make_lessons_file(tmp_path, LESSONS_WITH_ANCHOR)
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(lf),
        )
        cmd_log_lesson(config, "Bad assumption", "Never assume X", "Always check Y first")
        out = capsys.readouterr().out
        assert "Lesson logged" in out
        content = lf.read_text()
        assert "Bad assumption" in content
        assert "Never assume X" in content
        assert "Always check Y first" in content

    def test_appends_lesson_via_insights_fallback(self, tmp_path: Path, capsys):
        """log-lesson falls back to ## Insights anchor when no CORRECTIONS-ANCHOR."""
        lf = _make_lessons_file(tmp_path, LESSONS_WITH_INSIGHTS)
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(lf),
        )
        cmd_log_lesson(config, "Missing check", "Pattern here", "Prevention here")
        out = capsys.readouterr().out
        assert "Lesson logged" in out
        content = lf.read_text()
        assert "Missing check" in content

    def test_no_lessons_file_exits(self, tmp_path: Path):
        """log-lesson exits when lessons_file is not configured."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file="",
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_log_lesson(config, "what", "pattern", "prevention")
        assert exc_info.value.code == 1

    def test_missing_anchor_exits(self, tmp_path: Path):
        """log-lesson exits when neither anchor nor ## Insights is found."""
        lf = _make_lessons_file(tmp_path, "# No anchors here\n\nJust text.\n")
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(lf),
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_log_lesson(config, "what", "pattern", "prevention")
        assert exc_info.value.code == 1

    def test_bp_category_triggers_escalation(self, tmp_path: Path, capsys):
        """log-lesson with bp_category triggers backlog escalation."""
        lf = _make_lessons_file(tmp_path, LESSONS_WITH_ANCHOR)
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=str(lf),
        )
        # Create a fake backlog file in tmp_path
        backlog = tmp_path / "BOOTSTRAP_BACKLOG.md"
        backlog.write_text("# Bootstrap Backlog\n\n<!-- PENDING-ANCHOR -->\n\n## Applied\n")
        with patch(
            "dbq.commands.knowledge.Path.home",
            return_value=tmp_path,
        ):
            # Adjust the backlog path structure: ~/.claude/dev-framework/BOOTSTRAP_BACKLOG.md
            (tmp_path / ".claude" / "dev-framework").mkdir(parents=True, exist_ok=True)
            real_backlog = tmp_path / ".claude" / "dev-framework" / "BOOTSTRAP_BACKLOG.md"
            real_backlog.write_text(
                "# Bootstrap Backlog\n\n<!-- PENDING-ANCHOR -->\n\n## Applied\n"
            )
            cmd_log_lesson(
                config,
                "Template missing guard",
                "Pattern: guard missing",
                "Always add guard",
                bp_category="template",
                bp_file="templates/foo.sh",
            )
        out = capsys.readouterr().out
        assert "Lesson logged" in out
        assert "Escalated" in out


# ---------------------------------------------------------------------------
# TestCmdPromote
# ---------------------------------------------------------------------------

class TestCmdPromote:
    def test_promotes_pattern(self, tmp_path: Path, capsys):
        """promote appends an entry to LESSONS_UNIVERSAL.md."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        # Set up fake ~/.claude/LESSONS_UNIVERSAL.md
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        universal = claude_dir / "LESSONS_UNIVERSAL.md"
        universal.write_text("# Universal Lessons\n\n")

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_promote(config, "Always validate inputs", rule="Use schema validation")

        out = capsys.readouterr().out
        assert "Promoted" in out
        content = universal.read_text()
        assert "Always validate inputs" in content
        assert "Use schema validation" in content
        assert "my-project" in content

    def test_promotes_with_default_rule(self, tmp_path: Path, capsys):
        """promote uses default rule text when rule is empty and prints confirmation."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        universal = claude_dir / "LESSONS_UNIVERSAL.md"
        universal.write_text("# Universal Lessons\n\n")

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_promote(config, "Some pattern")

        out = capsys.readouterr().out
        content = universal.read_text()
        assert "See source project LESSONS.md" in content
        assert "Some pattern" in content  # the pattern text must also be written
        assert "Promoted" in out  # confirmation output

    def test_missing_universal_file_exits(self, tmp_path: Path):
        """promote exits when LESSONS_UNIVERSAL.md does not exist."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        # Do NOT create the file
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            with pytest.raises(SystemExit):
                cmd_promote(config, "Some pattern")

    def test_fallback_to_project_local(self, tmp_path: Path, capsys):
        """promote writes to project-local LESSONS_UNIVERSAL.md when ~/.claude/ version is absent."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        # Create project-local file but NOT ~/.claude/LESSONS_UNIVERSAL.md
        project_local = tmp_path / "LESSONS_UNIVERSAL.md"
        project_local.write_text("# Universal Lessons\n\n")

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_promote(config, "Always validate inputs", rule="Use schema validation")

        content = project_local.read_text()
        assert "Always validate inputs" in content
        assert "Use schema validation" in content

    def test_both_missing_exits_with_message(self, tmp_path: Path, capsys):
        """promote exits with clear message when neither LESSONS_UNIVERSAL.md exists."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        # Do NOT create either file
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            with pytest.raises(SystemExit):
                cmd_promote(config, "Some pattern")

        out = capsys.readouterr().out
        assert "not found at ~/.claude/ or project root" in out

    def test_prefers_home_over_project_local(self, tmp_path: Path, capsys):
        """promote writes to ~/.claude/ version when both files exist."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        # Create BOTH files
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        home_universal = claude_dir / "LESSONS_UNIVERSAL.md"
        home_universal.write_text("# Universal Lessons\n\n")
        project_local = tmp_path / "LESSONS_UNIVERSAL.md"
        project_local.write_text("# Project Local Lessons\n\n")

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_promote(config, "Prefer home pattern", rule="Home rule")

        home_content = home_universal.read_text()
        local_content = project_local.read_text()
        assert "Prefer home pattern" in home_content
        assert "Prefer home pattern" not in local_content

    def test_promote_readonly_universal(self, tmp_path: Path):
        """promote raises when LESSONS_UNIVERSAL.md is read-only."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        universal = claude_dir / "LESSONS_UNIVERSAL.md"
        universal.write_text("# Universal Lessons\n\n")
        os.chmod(str(universal), 0o444)
        try:
            with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
                with pytest.raises((PermissionError, SystemExit)):
                    cmd_promote(config, "Some pattern", rule="Some rule")
        finally:
            os.chmod(str(universal), 0o644)

    def test_promote_empty_universal(self, tmp_path: Path, capsys):
        """promote appends correctly to an empty LESSONS_UNIVERSAL.md."""
        config = ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            phases=[],
        )
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        universal = claude_dir / "LESSONS_UNIVERSAL.md"
        universal.write_text("")  # empty file

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_promote(config, "Empty file pattern", rule="Append anyway")

        content = universal.read_text()
        assert "Empty file pattern" in content
        assert "Append anyway" in content


# ---------------------------------------------------------------------------
# TestCmdEscalate
# ---------------------------------------------------------------------------

BACKLOG_CONTENT = """\
# Bootstrap Backlog

<!-- PENDING-ANCHOR -->

## Applied
"""


class TestCmdEscalate:
    def _setup_backlog(self, tmp_path: Path) -> Path:
        """Create the fake ~/.claude/dev-framework/BOOTSTRAP_BACKLOG.md."""
        backlog_dir = tmp_path / ".claude" / "dev-framework"
        backlog_dir.mkdir(parents=True, exist_ok=True)
        backlog = backlog_dir / "BOOTSTRAP_BACKLOG.md"
        backlog.write_text(BACKLOG_CONTENT)
        return backlog

    def _make_config(self, tmp_path: Path) -> ProjectConfig:
        return ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
        )

    def test_escalates_to_backlog(self, tmp_path: Path, capsys):
        """escalate writes a new BP entry into BOOTSTRAP_BACKLOG.md."""
        backlog = self._setup_backlog(tmp_path)
        config = self._make_config(tmp_path)
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_escalate(
                config,
                description="Fix hook template",
                category="template",
                affected_file="templates/hooks/pre-commit",
                priority="P1",
            )
        out = capsys.readouterr().out
        assert "Escalated" in out
        assert "BP-001" in out
        content = backlog.read_text()
        assert "Fix hook template" in content
        assert "template" in content
        assert "templates/hooks/pre-commit" in content
        assert "P1" in content

    def test_bp_id_increments(self, tmp_path: Path, capsys):
        """escalate increments BP ID when existing entries are present."""
        backlog = self._setup_backlog(tmp_path)
        # Pre-populate with one entry
        existing = backlog.read_text()
        backlog.write_text(
            existing.replace(
                "<!-- PENDING-ANCHOR -->",
                "<!-- PENDING-ANCHOR -->\n\n### BP-005 [template] Old entry\n- **Status:** pending\n",
            )
        )
        config = self._make_config(tmp_path)
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_escalate(config, "New entry", "template", "some/file.sh", "P2")
        out = capsys.readouterr().out
        assert "BP-006" in out

    def test_invalid_category_defaults_to_template(self, tmp_path: Path, capsys):
        """escalate warns and falls back to 'template' for unknown categories."""
        self._setup_backlog(tmp_path)
        config = self._make_config(tmp_path)
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_escalate(config, "Something", "bogus_category", "file.py", "P2")
        out = capsys.readouterr().out
        assert "Unknown category" in out or "template" in out

    def test_missing_backlog_exits(self, tmp_path: Path):
        """escalate exits when BOOTSTRAP_BACKLOG.md does not exist."""
        config = self._make_config(tmp_path)
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            with pytest.raises(SystemExit):
                cmd_escalate(config, "Something", "template", "file.py", "P2")

    def test_applied_section_anchor_fallback(self, tmp_path: Path, capsys):
        """escalate falls back to ## Applied anchor when PENDING-ANCHOR is absent."""
        backlog_dir = tmp_path / ".claude" / "dev-framework"
        backlog_dir.mkdir(parents=True, exist_ok=True)
        backlog = backlog_dir / "BOOTSTRAP_BACKLOG.md"
        backlog.write_text("# Backlog\n\n## Applied\nOld entry here.\n")
        config = self._make_config(tmp_path)
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_escalate(config, "Framework fix", "framework", "fw/file.md", "P3")
        out = capsys.readouterr().out
        assert "Escalated" in out
        content = backlog.read_text()
        assert "Framework fix" in content


# ---------------------------------------------------------------------------
# TestMarkSourcePromoted
# ---------------------------------------------------------------------------

class TestMarkSourcePromoted:
    def _make_config(self, tmp_path: Path, lessons_path: str = "") -> ProjectConfig:
        return ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="my-project",
            lessons_file=lessons_path,
            phases=[],
        )

    def test_marks_table_row_promoted(self, tmp_path: Path, capsys):
        """Marks a matching table row from '| No |' to '| Yes (date) |'."""
        lessons_path = tmp_path / "LESSONS.md"
        lessons_path.write_text(
            "# Lessons\n\n"
            "| Date | Pattern | Source | Prevention | Promoted |\n"
            "|------|---------|--------|------------|----------|\n"
            "| 2026-04-01 | Always validate schema inputs before processing | Project | Run validator | No |\n"
        )
        config = self._make_config(tmp_path, str(lessons_path))
        _mark_source_promoted(config, "always validate schema inputs before processing", "2026-04-03")
        content = lessons_path.read_text()
        assert "| Yes (2026-04-03) |" in content
        assert "| No |" not in content

    def test_marks_block_promoted(self, tmp_path: Path, capsys):
        """Marks a matching ### block's Promoted field from No to Yes."""
        lessons_path = tmp_path / "LESSONS.md"
        lessons_path.write_text(
            "# Lessons\n\n"
            "### Validate Inputs Before Processing\n"
            "**Date:** 2026-04-01\n"
            "**Source:** Project\n"
            "**Promoted:** No\n"
            "Always validate inputs before processing to prevent injection errors.\n"
        )
        config = self._make_config(tmp_path, str(lessons_path))
        _mark_source_promoted(config, "validate inputs before processing prevent injection", "2026-04-03")
        content = lessons_path.read_text()
        assert "**Promoted:** Yes (2026-04-03)" in content
        assert "**Promoted:** No" not in content

    def test_threshold_below_3_skips(self, tmp_path: Path, capsys):
        """Does not modify file when keyword overlap is below 3."""
        lessons_path = tmp_path / "LESSONS.md"
        original = (
            "# Lessons\n\n"
            "| Date | Pattern | Source | Prevention | Promoted |\n"
            "|------|---------|--------|------------|----------|\n"
            "| 2026-04-01 | Unrelated content here today | Project | Some rule | No |\n"
        )
        lessons_path.write_text(original)
        config = self._make_config(tmp_path, str(lessons_path))
        # Pattern shares at most 2 words with the row above
        _mark_source_promoted(config, "completely different separate topic", "2026-04-03")
        content = lessons_path.read_text()
        assert content == original
        out = capsys.readouterr().out
        assert "Could not find" in out

    def test_threshold_at_3_marks(self, tmp_path: Path):
        """Marks the entry when keyword overlap is exactly 3."""
        lessons_path = tmp_path / "LESSONS.md"
        lessons_path.write_text(
            "# Lessons\n\n"
            "| Date | Pattern | Source | Prevention | Promoted |\n"
            "|------|---------|--------|------------|----------|\n"
            "| 2026-04-01 | Validate schema inputs always during runtime | Project | Some rule | No |\n"
        )
        config = self._make_config(tmp_path, str(lessons_path))
        # Pattern shares exactly: "validate", "schema", "inputs" (3 words ≥4 chars)
        _mark_source_promoted(config, "validate schema inputs", "2026-04-03")
        content = lessons_path.read_text()
        assert "| Yes (2026-04-03) |" in content

    def test_prefers_higher_scoring_match(self, tmp_path: Path):
        """Marks the row with more keyword matches, not the first match found."""
        lessons_path = tmp_path / "LESSONS.md"
        lessons_path.write_text(
            "# Lessons\n\n"
            "| Date | Pattern | Source | Prevention | Promoted |\n"
            "|------|---------|--------|------------|----------|\n"
            "| 2026-04-01 | Validate schema inputs | Project | Rule A | No |\n"
            "| 2026-04-01 | Validate schema inputs always during runtime processing | Project | Rule B | No |\n"
        )
        config = self._make_config(tmp_path, str(lessons_path))
        # Second row has 5 matches: validate, schema, inputs, always, runtime, processing
        _mark_source_promoted(
            config,
            "validate schema inputs always during runtime processing",
            "2026-04-03",
        )
        content = lessons_path.read_text()
        lines = content.splitlines()
        # The second data row (index 4 in 0-based, 5th line) should be marked
        marked_lines = [l for l in lines if "| Yes (2026-04-03) |" in l]
        assert len(marked_lines) == 1
        assert "processing" in marked_lines[0] or "runtime" in marked_lines[0]

    def test_no_lessons_file_returns_silently(self, tmp_path: Path, capsys):
        """Returns without error when config.lessons_file is empty string."""
        config = self._make_config(tmp_path, "")
        # Should not raise, should produce no output
        _mark_source_promoted(config, "some pattern text here", "2026-04-03")
        out = capsys.readouterr().out
        assert out == ""

    def test_missing_file_returns_silently(self, tmp_path: Path, capsys):
        """Returns without error when lessons_file path does not exist."""
        config = self._make_config(tmp_path, str(tmp_path / "nonexistent.md"))
        _mark_source_promoted(config, "some pattern text here", "2026-04-03")
        out = capsys.readouterr().out
        assert out == ""

    def test_short_keywords_ignored(self, tmp_path: Path, capsys):
        """Emits 'Could not find' warning when all pattern words are shorter than 4 chars."""
        lessons_path = tmp_path / "LESSONS.md"
        lessons_path.write_text(
            "# Lessons\n\n"
            "| Date | Pattern | Source | Prevention | Promoted |\n"
            "|------|---------|--------|------------|----------|\n"
            "| 2026-04-01 | Do it now as per the fix | Project | Rule | No |\n"
        )
        config = self._make_config(tmp_path, str(lessons_path))
        # All words < 4 chars: "do", "it", "now"
        _mark_source_promoted(config, "do it now", "2026-04-03")
        out = capsys.readouterr().out
        assert "Could not find" in out


# ---------------------------------------------------------------------------
# TestCmdHarvest
# ---------------------------------------------------------------------------

HARVEST_TABLE_CONTENT = """\
# Lessons

| Date | What Happened | Pattern | Prevention Rule | Promoted |
|------|---------------|---------|-----------------|----------|
| 2026-01-15 | Schema broke deploy | Schema validation prevents deploy failures | Run schema check in CI | No |
| 2026-02-20 | Tests skipped | Integration tests catch API drift | Add integration gate | Yes (2026-02-25) |
| 2026-03-01 | Envvars missing | Missing envvars cause silent failures | Use envvar validation at startup | No |
"""

HARVEST_BLOCK_CONTENT = """\
# Lessons

<!-- CORRECTIONS-ANCHOR -->

### 2026-01-20 — Config drift caused outage
**Pattern:** Configuration files diverged between environments
**Prevention:** Use config diffing tool before deploy
**Promoted:** No

### 2026-02-10 — Already promoted item
**Pattern:** Something already handled
**Prevention:** Already in universal
**Promoted:** Yes (2026-02-15)
"""

HARVEST_MIXED_CONTENT = """\
# Lessons

| Date | What Happened | Pattern | Prevention Rule | Promoted |
|------|---------------|---------|-----------------|----------|
| 2026-01-15 | Schema broke deploy | Schema validation prevents failures | Run schema check | No |

<!-- CORRECTIONS-ANCHOR -->

### 2026-03-10 — Hook contamination
**Pattern:** Detection hooks contained inline project names
**Prevention:** Load patterns from external config files
**Promoted:** No
"""

HARVEST_UNIVERSAL_CONTENT = """\
# Universal Lessons

| Date | Pattern | Source Project | Prevention Rule |
|------|---------|---------------|-----------------|
| 2026-01-01 | Schema validation prevents deploy failures in production | other-project | Run schema check in CI pipeline before every deploy |
| 2026-01-10 | Always check environment variables exist at startup | another-project | Validate required envvars in application entrypoint |
"""


class TestCmdHarvest:
    """Tests for cmd_harvest and its helper functions."""

    def _make_config(self, tmp_path: Path, lessons_file: str = "") -> ProjectConfig:
        return ProjectConfig(
            db_path=str(tmp_path / "test.db"),
            project_name="test-project",
            phases=[],
            lessons_file=lessons_file,
        )

    def test_table_format_unpromoted(self, tmp_path: Path, capsys):
        """Parses table rows correctly, finds 2 unpromoted, skips promoted."""
        lf = tmp_path / "LESSONS_TEST.md"
        lf.write_text(HARVEST_TABLE_CONTENT)
        config = self._make_config(tmp_path, str(lf))

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        assert "Schema validation" in out
        assert "Missing envvars" in out
        assert "Integration tests catch" not in out  # promoted — should not appear
        assert "2 unpromoted" in out

    def test_block_format_unpromoted(self, tmp_path: Path, capsys):
        """Parses ### blocks, finds 1 unpromoted, skips promoted."""
        lf = tmp_path / "LESSONS_TEST.md"
        lf.write_text(HARVEST_BLOCK_CONTENT)
        config = self._make_config(tmp_path, str(lf))

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        assert "Configuration files diverged" in out
        assert "Something already handled" not in out  # promoted
        assert "1 unpromoted" in out

    def test_mixed_formats(self, tmp_path: Path, capsys):
        """Both table rows and ### blocks in one file, all unpromoted found."""
        lf = tmp_path / "LESSONS_TEST.md"
        lf.write_text(HARVEST_MIXED_CONTENT)
        config = self._make_config(tmp_path, str(lf))

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        assert "Schema validation" in out
        assert "Detection hooks" in out
        assert "2 unpromoted" in out

    def test_dedup_high_overlap(self, tmp_path: Path, capsys):
        """Entry with high keyword overlap shows duplicate warning."""
        lf = tmp_path / "LESSONS_TEST.md"
        lf.write_text(HARVEST_TABLE_CONTENT)
        config = self._make_config(tmp_path, str(lf))

        # Create universal file with overlapping entry
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "LESSONS_UNIVERSAL.md").write_text(HARVEST_UNIVERSAL_CONTENT)

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        assert "Potential duplicate" in out
        assert "score:" in out

    def test_unique_no_overlap(self, tmp_path: Path, capsys):
        """Entry with no keyword overlap shows unique marker."""
        lf = tmp_path / "LESSONS_TEST.md"
        # Entry about something completely different from universal
        lf.write_text(
            "# Lessons\n\n"
            "| Date | Pattern | Prevention | Promoted |\n"
            "|------|---------|------------|----------|\n"
            "| 2026-04-01 | Kubernetes pods crashed during rollback | Monitor pod health during deploys | No |\n"
        )
        config = self._make_config(tmp_path, str(lf))

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "LESSONS_UNIVERSAL.md").write_text(HARVEST_UNIVERSAL_CONTENT)

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        assert "Unique" in out
        assert "Potential duplicate" not in out

    def test_no_unpromoted_entries(self, tmp_path: Path, capsys):
        """All entries promoted → 0 unpromoted in summary."""
        lf = tmp_path / "LESSONS_TEST.md"
        lf.write_text(
            "# Lessons\n\n"
            "| Date | Pattern | Prevention | Promoted |\n"
            "|------|---------|------------|----------|\n"
            "| 2026-01-15 | Something | Rule | Yes (2026-02-01) |\n"
        )
        config = self._make_config(tmp_path, str(lf))

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        assert "0 unpromoted" in out

    def test_missing_lessons_file_exits(self, tmp_path: Path):
        """No file configured and no paths → sys.exit(1)."""
        config = self._make_config(tmp_path, "")

        with pytest.raises(SystemExit):
            cmd_harvest(config)

    def test_missing_universal_still_works(self, tmp_path: Path, capsys):
        """No universal file → entries shown as unique + info message."""
        lf = tmp_path / "LESSONS_TEST.md"
        lf.write_text(HARVEST_TABLE_CONTENT)
        config = self._make_config(tmp_path, str(lf))

        # No .claude dir, no universal file
        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        assert "No LESSONS_UNIVERSAL.md found" in out
        assert "Unique" in out
        assert "2 unpromoted" in out

    def test_extra_paths_argument(self, tmp_path: Path, capsys):
        """Explicit paths are used instead of config.lessons_file."""
        lf1 = tmp_path / "LESSONS_A.md"
        lf1.write_text(HARVEST_TABLE_CONTENT)
        lf2 = tmp_path / "LESSONS_B.md"
        lf2.write_text(HARVEST_BLOCK_CONTENT)
        config = self._make_config(tmp_path, "")  # no default lessons file

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config, str(lf1), str(lf2))

        out = capsys.readouterr().out
        assert "LESSONS_A.md" in out
        assert "LESSONS_B.md" in out
        assert "3 unpromoted" in out  # 2 from table + 1 from block

    def test_keyword_overlap_shown(self, tmp_path: Path, capsys):
        """Overlapping keywords are printed in dedup warning output."""
        lf = tmp_path / "LESSONS_TEST.md"
        lf.write_text(HARVEST_TABLE_CONTENT)
        config = self._make_config(tmp_path, str(lf))

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "LESSONS_UNIVERSAL.md").write_text(HARVEST_UNIVERSAL_CONTENT)

        with patch("dbq.commands.knowledge.Path.home", return_value=tmp_path):
            cmd_harvest(config)

        out = capsys.readouterr().out
        # The schema entry should have keyword overlap
        assert "Keywords:" in out
        # Extract the keywords line and check for expected overlaps
        for line in out.splitlines():
            if "Keywords:" in line:
                kw_line = line.lower()
                hits = sum(1 for kw in ["schema", "validation", "deploy", "failures"]
                          if kw in kw_line)
                assert hits >= 2, f"Expected ≥2 keyword overlaps, got {hits} in: {line}"
                break
