"""Tests for the lint command module (L1-L6 checks and integration)."""
import pytest
from pathlib import Path
from typing import Optional

from dbq.config import ProjectConfig
from dbq.commands.lint import cmd_lint, quick_lint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> ProjectConfig:
    """Build a ProjectConfig whose project_dir == tmp_path."""
    db_path = tmp_path / "test.db"
    db_path.touch()
    return ProjectConfig(
        db_path=str(db_path),
        project_name="test-project",
        phases=["P1-TEST"],
    )


def _make_rules_file(rules_dir: Path, name: str, content: str) -> Path:
    """Create a rules .md file with given content. Returns the file path."""
    rules_dir.mkdir(parents=True, exist_ok=True)
    p = rules_dir / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# L1: Dead glob patterns
# ---------------------------------------------------------------------------

class TestL1DeadGlobs:
    def test_dead_pattern_warns(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A pattern matching no files produces an L1 warning."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\npaths: ["nonexistent/**/*.zzzz"]\n---\n# Rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L1" in out
        assert "nonexistent/**/*.zzzz" in out

    def test_valid_pattern_no_warning(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A pattern matching at least one file produces no L1 warning."""
        config = _make_config(tmp_path)
        (tmp_path / "real_file.py").touch()
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\npaths: ["*.py"]\n---\n# Rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L1" not in out

    def test_lint_ignore_suppresses_dead_pattern(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """# lint:ignore in rule body suppresses L1 warning for that file."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\npaths: ["nonexistent/**/*.zzzz"]\n---\n# lint:ignore\n# Rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L1" not in out

    def test_no_rules_dir_no_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Missing .claude/rules/ directory produces no L1 output."""
        config = _make_config(tmp_path)
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L1" not in out

    def test_unconditional_rule_no_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A rules file with no frontmatter (unconditional rule) is skipped by L1."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            "# No frontmatter here\nJust a rule.\n",
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L1" not in out

    @pytest.mark.parametrize("pattern,should_warn", [
        ("nonexistent_dir/**/*.py", True),
        ("*.zzzzzz_unused_extension", True),
    ])
    def test_dead_patterns_parametrized(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        pattern: str,
        should_warn: bool,
    ) -> None:
        """Parametrized: verify L1 fires for patterns that match no files."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            f'---\npaths: ["{pattern}"]\n---\n# Rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        if should_warn:
            assert "L1" in out
        else:
            assert "L1" not in out


# ---------------------------------------------------------------------------
# L2: Wrong field name
# ---------------------------------------------------------------------------

class TestL2WrongFieldName:
    def test_globs_field_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A rules file using 'globs:' instead of 'paths:' produces an L2 error."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\nglobs: ["**/*.py"]\n---\n# Rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L2" in out
        assert "globs" in out

    def test_paths_field_no_error(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A rules file using 'paths:' produces no L2 error."""
        config = _make_config(tmp_path)
        # Match the db file we created so L1 does not fire
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\npaths: ["test.db"]\n---\n# Rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L2" not in out

    def test_no_frontmatter_no_error(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A rules file with no frontmatter produces no L2 error."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            "# No frontmatter\nJust content.\n",
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L2" not in out

    @pytest.mark.parametrize("field,expect_error", [
        ("globs", True),
        ("paths", False),
    ])
    def test_field_name_parametrized(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        field: str,
        expect_error: bool,
    ) -> None:
        """Parametrized: L2 fires for 'globs:', not for 'paths:'."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            f'---\n{field}: ["test.db"]\n---\n# Rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        if expect_error:
            assert "L2" in out
        else:
            assert "L2" not in out


# ---------------------------------------------------------------------------
# L3: Broken @-imports
# ---------------------------------------------------------------------------

class TestL3BrokenImports:
    def test_nonexistent_import_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """@nonexistent-file.md in CLAUDE.md produces an L3 error."""
        config = _make_config(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("@nonexistent-file.md\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L3" in out
        assert "nonexistent-file.md" in out

    def test_existing_import_no_error(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """@existing-file.md in CLAUDE.md with the file present produces no L3 error."""
        config = _make_config(tmp_path)
        referenced = tmp_path / "existing-file.md"
        referenced.write_text("# content\n", encoding="utf-8")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("@existing-file.md\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L3" not in out

    def test_at_import_prefix_skipped(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Lines starting with @import are skipped (not treated as @-imports)."""
        config = _make_config(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("@import nonexistent.md\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L3" not in out

    def test_double_at_skipped(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Lines starting with @@ are skipped entirely."""
        config = _make_config(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("@@nonexistent.md\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L3" not in out

    def test_no_claude_md_no_error(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Absence of CLAUDE.md produces no L3 error."""
        config = _make_config(tmp_path)
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L3" not in out

    def test_multiple_imports_mixed(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Only the missing @-import produces an error; present ones are clean."""
        config = _make_config(tmp_path)
        present = tmp_path / "present.md"
        present.write_text("# present\n", encoding="utf-8")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "@present.md\n@missing.md\n",
            encoding="utf-8",
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L3" in out
        assert "missing.md" in out
        assert out.count("L3") == 1


# ---------------------------------------------------------------------------
# L4: Unfilled placeholders
# ---------------------------------------------------------------------------

class TestL4Placeholders:
    def test_placeholder_in_hooks_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """%%PLACEHOLDER%% in .claude/hooks/ file produces an L4 error."""
        config = _make_config(tmp_path)
        hooks_dir = tmp_path / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "myhook.sh"
        hook.write_text("#!/bin/bash\necho %%PROJECT_NAME%%\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L4" in out
        assert "%%PROJECT_NAME%%" in out

    def test_backtick_placeholder_suppressed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """%%PLACEHOLDER%% inside backticks is treated as documentation, not an error."""
        config = _make_config(tmp_path)
        hooks_dir = tmp_path / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "myhook.sh"
        hook.write_text(
            "#!/bin/bash\n# Replace `%%PROJECT_NAME%%` before use\necho hello\n",
            encoding="utf-8",
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L4" not in out

    def test_placeholder_in_agents_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """%%PLACEHOLDER%% in .claude/agents/ file produces an L4 error."""
        config = _make_config(tmp_path)
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent = agents_dir / "agent.md"
        agent.write_text("# Agent\nProject: %%PROJECT_NAME%%\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L4" in out

    def test_no_placeholder_clean(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A hooks file with no placeholders produces no L4 error."""
        config = _make_config(tmp_path)
        hooks_dir = tmp_path / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "myhook.sh"
        hook.write_text("#!/bin/bash\necho hello world\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L4" not in out

    def test_no_hook_dirs_no_error(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Absence of .claude/hooks/ produces no L4 error."""
        config = _make_config(tmp_path)
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L4" not in out


# ---------------------------------------------------------------------------
# L5: Missing test modules
# ---------------------------------------------------------------------------

class TestL5MissingTestModules:
    def test_command_without_test_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A commands/ .py file with no test_*.py counterpart produces an L5 warning."""
        config = _make_config(tmp_path)
        commands_dir = tmp_path / "templates" / "scripts" / "dbq" / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "foo.py").write_text("def cmd_foo(): pass\n", encoding="utf-8")
        # No test file
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L5" in out
        assert "foo.py" in out

    def test_command_with_test_no_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A commands/ .py file that has a test_*.py counterpart produces no L5 warning."""
        config = _make_config(tmp_path)
        commands_dir = tmp_path / "templates" / "scripts" / "dbq" / "commands"
        dbq_tests_dir = tmp_path / "templates" / "scripts" / "dbq" / "tests"
        commands_dir.mkdir(parents=True, exist_ok=True)
        dbq_tests_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "bar.py").write_text("def cmd_bar(): pass\n", encoding="utf-8")
        (dbq_tests_dir / "test_bar.py").write_text("def test_bar(): pass\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L5" not in out

    def test_dunder_files_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """__init__.py and similar dunder files are not checked by L5."""
        config = _make_config(tmp_path)
        commands_dir = tmp_path / "templates" / "scripts" / "dbq" / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "__init__.py").write_text("", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L5" not in out

    def test_no_commands_dir_no_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Absence of commands/ directory produces no L5 warning."""
        config = _make_config(tmp_path)
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L5" not in out

    @pytest.mark.parametrize("test_filename", [
        "test_baz.py",
        "test_dbq_baz.py",
    ])
    def test_alternative_test_names_accepted(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        test_filename: str,
    ) -> None:
        """Both test_<module>.py and test_dbq_<module>.py count as valid test coverage."""
        config = _make_config(tmp_path)
        commands_dir = tmp_path / "templates" / "scripts" / "dbq" / "commands"
        dbq_tests_dir = tmp_path / "templates" / "scripts" / "dbq" / "tests"
        commands_dir.mkdir(parents=True, exist_ok=True)
        dbq_tests_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "baz.py").write_text("def cmd_baz(): pass\n", encoding="utf-8")
        (dbq_tests_dir / test_filename).write_text("def test_baz(): pass\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L5" not in out


# ---------------------------------------------------------------------------
# L6: Agent tool contradictions
# ---------------------------------------------------------------------------

class TestL6AgentToolContradictions:
    def test_contradiction_warns(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """An agent with a tool in both 'tools' and 'disallowedTools' produces an L6 warning."""
        config = _make_config(tmp_path)
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent = agents_dir / "my-agent.md"
        agent.write_text(
            "---\ntools: [Read, Write]\ndisallowedTools: [Write]\n---\n# Agent\n",
            encoding="utf-8",
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L6" in out
        assert "Write" in out

    def test_no_contradiction_clean(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """An agent with no overlap between tools and disallowedTools produces no L6 warning."""
        config = _make_config(tmp_path)
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent = agents_dir / "my-agent.md"
        agent.write_text(
            "---\ntools: [Read, Write]\ndisallowedTools: [Bash]\n---\n# Agent\n",
            encoding="utf-8",
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L6" not in out

    def test_no_agents_dir_no_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Absence of .claude/agents/ produces no L6 warning."""
        config = _make_config(tmp_path)
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L6" not in out

    def test_no_frontmatter_no_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """An agent file with no frontmatter produces no L6 warning."""
        config = _make_config(tmp_path)
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent = agents_dir / "my-agent.md"
        agent.write_text("# Agent\nNo frontmatter.\n", encoding="utf-8")
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L6" not in out

    def test_multiple_contradictions_all_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Multiple overlapping tools are all reported in a single L6 warning."""
        config = _make_config(tmp_path)
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent = agents_dir / "my-agent.md"
        agent.write_text(
            "---\ntools: [Read, Write, Bash]\ndisallowedTools: [Read, Write]\n---\n# Agent\n",
            encoding="utf-8",
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "L6" in out
        # Both contradicting tools should appear in the output
        assert "Read" in out
        assert "Write" in out


# ---------------------------------------------------------------------------
# Integration: cmd_lint on empty project
# ---------------------------------------------------------------------------

class TestCmdLintIntegration:
    def test_empty_project_runs_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """cmd_lint on a bare project directory produces no errors and exits normally."""
        config = _make_config(tmp_path)
        cmd_lint(config)  # must not raise
        out = capsys.readouterr().out
        # Verdict line should indicate clean or only warnings (no explicit error count)
        assert "Lint" in out

    def test_empty_project_verdict_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Empty project verdict contains 'clean' (zero errors, zero warnings)."""
        config = _make_config(tmp_path)
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "clean" in out

    def test_error_verdict_when_errors_present(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """When there are errors the verdict line mentions error count."""
        config = _make_config(tmp_path)
        # L2 error: globs field
        _make_rules_file(
            tmp_path / ".claude" / "rules", "bad.md",
            '---\nglobs: ["**/*.py"]\n---\n# Bad rule\n',
        )
        cmd_lint(config)
        out = capsys.readouterr().out
        assert "error" in out.lower()


# ---------------------------------------------------------------------------
# Integration: quick_lint
# ---------------------------------------------------------------------------

class TestQuickLint:
    def test_returns_tuple(self, tmp_path: Path) -> None:
        """quick_lint returns a (warnings, errors) tuple."""
        config = _make_config(tmp_path)
        result = quick_lint(config)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_clean_project_zero_counts(self, tmp_path: Path) -> None:
        """quick_lint on an empty project returns (0, 0)."""
        config = _make_config(tmp_path)
        warnings, errors = quick_lint(config)
        assert warnings == 0
        assert errors == 0

    def test_dead_glob_increments_warnings(self, tmp_path: Path) -> None:
        """quick_lint reports a warning for a dead glob pattern."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\npaths: ["nonexistent/**/*.zzzz"]\n---\n# Rule\n',
        )
        warnings, errors = quick_lint(config)
        assert warnings >= 1
        assert errors == 0

    def test_wrong_field_increments_errors(self, tmp_path: Path) -> None:
        """quick_lint reports an error for a globs: field."""
        config = _make_config(tmp_path)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\nglobs: ["**/*.py"]\n---\n# Rule\n',
        )
        warnings, errors = quick_lint(config)
        assert errors >= 1

    def test_broken_import_increments_errors(self, tmp_path: Path) -> None:
        """quick_lint reports an error for a broken @-import."""
        config = _make_config(tmp_path)
        (tmp_path / "CLAUDE.md").write_text("@does-not-exist.md\n", encoding="utf-8")
        warnings, errors = quick_lint(config)
        assert errors >= 1

    def test_returns_warnings_errors_order(self, tmp_path: Path) -> None:
        """quick_lint returns (warnings, errors) — first element is warnings."""
        config = _make_config(tmp_path)
        # Introduce one warning (dead glob) and one error (broken import)
        _make_rules_file(
            tmp_path / ".claude" / "rules", "test.md",
            '---\npaths: ["nonexistent/**/*.zzzz"]\n---\n# Rule\n',
        )
        (tmp_path / "CLAUDE.md").write_text("@does-not-exist.md\n", encoding="utf-8")
        warnings, errors = quick_lint(config)
        assert warnings >= 1
        assert errors >= 1
