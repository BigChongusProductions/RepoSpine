"""
Unit tests for fill_placeholders.py

Covers:
1. Registry completeness (41 tokens, no duplicates)
2. re.sub correctness (single/multiple tokens, unknown preserved)
3. Sed token derivation from project name
4. Phase ordinal generation (full 9 phases, quick 3 phases)
5. Tech detection (package.json -> javascript, Cargo.toml -> rust, no files -> None)
6. Spec reading (exists -> content, missing -> None)
7. Dry-run mode (file unchanged, report generated)
8. JSON report format (required keys present)
9. Missing specs graceful (no error)
10. User override via --set
11. Empty file (no crash)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add the scripts directory to sys.path so fill_placeholders is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fill_placeholders import (
    REGISTRY,
    PlaceholderEngine,
    Replacement,
    ReportGenerator,
    SpecReader,
    TechDetector,
    TokenDef,
    build_values,
    derive_framework_tokens,
    derive_script_tokens,
    derive_sed_tokens,
    generate_case_ordinals,
    generate_case_sql,
    generate_in_sql,
    main,
)


# ---------------------------------------------------------------------------
# 1. Registry completeness
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_registry_has_41_tokens(self):
        assert len(REGISTRY) == 41, (
            f"Expected 41 tokens, got {len(REGISTRY)}. "
            f"Tokens: {sorted(REGISTRY)}"
        )

    def test_no_duplicate_keys(self):
        # dict keys are unique by definition, but verify all names match keys
        for key, token_def in REGISTRY.items():
            assert key == token_def.name, (
                f"Key '{key}' does not match token name '{token_def.name}'"
            )

    def test_all_tokens_have_required_fields(self):
        for name, token_def in REGISTRY.items():
            assert isinstance(token_def, TokenDef), f"{name} is not a TokenDef"
            assert token_def.name, f"{name} has empty name"
            assert token_def.category in ("auto", "user", "sed", "script", "framework"), (
                f"{name} has invalid category '{token_def.category}'"
            )
            assert token_def.pattern == f"%%{name}%%", (
                f"{name} has unexpected pattern '{token_def.pattern}'"
            )

    def test_categories_present(self):
        categories = {td.category for td in REGISTRY.values()}
        assert "auto" in categories
        assert "user" in categories
        assert "sed" in categories
        assert "script" in categories
        assert "framework" in categories

    def test_auto_tokens_count(self):
        auto = [t for t in REGISTRY.values() if t.category == "auto"]
        assert len(auto) == 12, f"Expected 12 auto tokens, got {len(auto)}"

    def test_user_tokens_count(self):
        user = [t for t in REGISTRY.values() if t.category == "user"]
        assert len(user) == 4, f"Expected 4 user tokens, got {len(user)}"

    def test_sed_tokens_count(self):
        sed = [t for t in REGISTRY.values() if t.category == "sed"]
        assert len(sed) == 12, f"Expected 12 sed tokens, got {len(sed)}"

    def test_script_tokens_count(self):
        # 11 script tokens in REGISTRY; Xcode conditionals (XCODE_PROJECT_PATH,
        # XCODE_SCHEME, XCODE_TEST_SCHEME) are derived and injected at runtime
        # when .xcodeproj is detected, but are not pre-registered as they are
        # conditional extras outside the 41-token set.
        script = [t for t in REGISTRY.values() if t.category == "script"]
        assert len(script) == 11, f"Expected 11 script tokens, got {len(script)}"

    def test_framework_tokens_count(self):
        fw = [t for t in REGISTRY.values() if t.category == "framework"]
        assert len(fw) == 2, f"Expected 2 framework tokens, got {len(fw)}"

    def test_known_tokens_present(self):
        expected = [
            "PROJECT_NORTH_STAR", "TECH_STACK", "FIRST_PHASE",
            "COMMIT_FORMAT", "BUILD_TEST_INSTRUCTIONS",
            "PROJECT_NAME", "PROJECT_PATH", "PROJECT_DB", "LESSONS_FILE",
            "PHASES", "PROJECT_PHASES", "PHASE_CASE_ORDINALS",
            "SKIP_PATTERN_1", "SKIP_PATTERN_2",
        ]
        for token in expected:
            assert token in REGISTRY, f"Expected token '{token}' not in REGISTRY"


# ---------------------------------------------------------------------------
# 2. re.sub correctness
# ---------------------------------------------------------------------------

class TestPlaceholderEngine:
    def test_single_token_replaced(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("Hello %%PROJECT_NAME%%!\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "MyApp"})
        count = engine.apply(f)
        assert count == 1
        assert f.read_text() == "Hello MyApp!\n"

    def test_multiple_tokens_replaced(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("Name: %%PROJECT_NAME%%\nPath: %%PROJECT_PATH%%\n")
        engine = PlaceholderEngine(
            values={"PROJECT_NAME": "MyApp", "PROJECT_PATH": "/tmp/myapp"}
        )
        count = engine.apply(f)
        assert count == 2
        assert "MyApp" in f.read_text()
        assert "/tmp/myapp" in f.read_text()

    def test_unknown_token_preserved(self, tmp_path: Path):
        # Build the token string at runtime to avoid triggering template scanner
        unknown_tok = "%%" + "UNKNOWN_TOKEN" + "%%"
        f = tmp_path / "test.md"
        original = f"{unknown_tok} should stay\n"
        f.write_text(original)
        engine = PlaceholderEngine(values={"PROJECT_NAME": "MyApp"})
        count = engine.apply(f)
        assert count == 0
        assert f.read_text() == original

    def test_unknown_token_recorded_as_unresolved(self, tmp_path: Path):
        unknown_tok = "%%" + "UNKNOWN_TOKEN" + "%%"
        f = tmp_path / "test.md"
        f.write_text(f"{unknown_tok}\n")
        engine = PlaceholderEngine(values={})
        engine.apply(f)
        unresolved = [r for r in engine.report if r.replacement is None]
        assert len(unresolved) == 1
        assert unresolved[0].token == "UNKNOWN_TOKEN"

    def test_same_token_multiple_occurrences(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("%%PROJECT_NAME%% and %%PROJECT_NAME%% again\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        count = engine.apply(f)
        assert count == 2
        assert f.read_text() == "X and X again\n"

    def test_meta_token_placeholder_not_replaced(self, tmp_path: Path):
        """%%PLACEHOLDER%% is a meta-token — not in values dict, left as-is."""
        f = tmp_path / "test.md"
        original = "This is %%PLACEHOLDER%% text\n"
        f.write_text(original)
        engine = PlaceholderEngine(values={"PROJECT_NAME": "MyApp"})
        count = engine.apply(f)
        assert count == 0
        assert f.read_text() == original

    def test_meta_token_placeholders_not_replaced(self, tmp_path: Path):
        """%%PLACEHOLDERS%% is a meta-token — left as-is."""
        f = tmp_path / "test.md"
        original = "Replace %%PLACEHOLDERS%% after copying\n"
        f.write_text(original)
        engine = PlaceholderEngine(values={})
        count = engine.apply(f)
        assert count == 0
        assert f.read_text() == original

    def test_empty_file_no_crash(self, tmp_path: Path):
        f = tmp_path / "empty.md"
        f.write_text("")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        count = engine.apply(f)
        assert count == 0
        assert f.read_text() == ""

    def test_multiline_value_replacement(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("Standards:\n%%TECH_STANDARDS%%\nEnd\n")
        multiline = "- Rule 1\n- Rule 2\n- Rule 3"
        engine = PlaceholderEngine(values={"TECH_STANDARDS": multiline})
        count = engine.apply(f)
        assert count == 1
        content = f.read_text()
        assert "- Rule 1" in content
        assert "- Rule 3" in content

    def test_apply_all_skips_git_dir(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        git_file = git_dir / "config"
        git_file.write_text("%%PROJECT_NAME%%\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        engine.apply_all(tmp_path)
        assert git_file.read_text() == "%%PROJECT_NAME%%\n"

    def test_apply_all_skips_placeholder_registry(self, tmp_path: Path):
        reg = tmp_path / "placeholder-registry.md"
        reg.write_text("%%PROJECT_NAME%%\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        engine.apply_all(tmp_path)
        assert reg.read_text() == "%%PROJECT_NAME%%\n"

    def test_apply_all_returns_stats(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("%%PROJECT_NAME%%\n")
        (tmp_path / "b.md").write_text("%%PROJECT_NAME%% %%PROJECT_PATH%%\n")
        engine = PlaceholderEngine(
            values={"PROJECT_NAME": "X", "PROJECT_PATH": "/tmp"}
        )
        stats = engine.apply_all(tmp_path)
        assert stats["total_replacements"] == 3
        assert stats["files_modified"] == 2

    def test_line_number_reported_correctly(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("line1\nline2\n%%PROJECT_NAME%%\nline4\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        engine.apply(f)
        resolved = [r for r in engine.report if r.replacement is not None]
        assert len(resolved) == 1
        assert resolved[0].line == 3


# ---------------------------------------------------------------------------
# 3. Sed token derivation
# ---------------------------------------------------------------------------

class TestSedTokenDerivation:
    def test_project_name_passed_through(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["PROJECT_NAME"] == "My Project"

    def test_project_path_passed_through(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["PROJECT_PATH"] == "/tmp/myproject"

    def test_lessons_file_derived(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["LESSONS_FILE"] == "LESSONS_MY_PROJECT.md"

    def test_rules_file_derived(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["RULES_FILE"] == "MY_PROJECT_RULES.md"

    def test_memory_file_derived(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["MEMORY_FILE"] == "MY_PROJECT_PROJECT_MEMORY.md"

    def test_project_memory_file_derived(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["PROJECT_MEMORY_FILE"] == "MY_PROJECT_PROJECT_MEMORY.md"

    def test_project_db_name_strips_extension(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject", "my_project.db")
        assert tokens["PROJECT_DB_NAME"] == "my_project"

    def test_project_db_defaults_to_slug(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["PROJECT_DB"] == "my_project.db"

    def test_project_rules_file_derived(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["PROJECT_RULES_FILE"] == "MY_PROJECT_RULES.md"

    def test_project_name_upper_derived(self):
        tokens = derive_sed_tokens("My Project", "/tmp/myproject")
        assert tokens["PROJECT_NAME_UPPER"] == "MY_PROJECT"

    def test_hyphenated_name(self):
        tokens = derive_sed_tokens("auth-service", "/tmp/auth")
        assert tokens["PROJECT_NAME_UPPER"] == "AUTH_SERVICE"
        assert tokens["LESSONS_FILE"] == "LESSONS_AUTH_SERVICE.md"

    def test_all_12_sed_tokens_present(self):
        tokens = derive_sed_tokens("Test", "/tmp/test")
        expected = {
            "PROJECT_NAME", "PROJECT_PATH", "PROJECT_DB", "LESSONS_FILE",
            "RULES_FILE", "MEMORY_FILE", "PROJECT_MEMORY_FILE", "PROJECT_DB_NAME",
            "PROJECT_RULES_FILE", "PROJECT_NAME_UPPER", "PERMISSION_ALLOW",
            "LOCAL_PERMISSIONS",
        }
        assert expected.issubset(set(tokens.keys()))


# ---------------------------------------------------------------------------
# 4. Phase ordinal generation
# ---------------------------------------------------------------------------

class TestPhaseGeneration:
    def test_full_lifecycle_9_phases(self):
        tokens = derive_script_tokens(
            "full", "Test Project",
            TechDetector("/tmp"),
            SpecReader(None, "/tmp"),
        )
        phase_list = tokens["PHASES"].split()
        assert len(phase_list) == 9

    def test_quick_lifecycle_3_phases(self):
        tokens = derive_script_tokens(
            "quick", "Test Project",
            TechDetector("/tmp"),
            SpecReader(None, "/tmp"),
        )
        phase_list = tokens["PHASES"].split()
        assert len(phase_list) == 3

    def test_full_lifecycle_phase_names(self):
        tokens = derive_script_tokens(
            "full", "Test Project",
            TechDetector("/tmp"),
            SpecReader(None, "/tmp"),
        )
        assert "P1-ENVISION" in tokens["PHASES"]
        assert "P9-EVOLVE" in tokens["PHASES"]

    def test_quick_lifecycle_phase_names(self):
        tokens = derive_script_tokens(
            "quick", "Test Project",
            TechDetector("/tmp"),
            SpecReader(None, "/tmp"),
        )
        assert "P1-PLAN" in tokens["PHASES"]
        assert "P3-SHIP" in tokens["PHASES"]

    def test_generate_case_ordinals_format(self):
        phases = ["P1-FOO", "P2-BAR", "P3-BAZ"]
        result = generate_case_ordinals(phases)
        assert "'P1-FOO') echo 1;;" in result
        assert "'P2-BAR') echo 2;;" in result
        assert "'P3-BAZ') echo 3;;" in result

    def test_generate_case_sql_format(self):
        phases = ["P1-FOO", "P2-BAR"]
        result = generate_case_sql(phases)
        assert "WHEN 'P1-FOO' THEN 1" in result
        assert "WHEN 'P2-BAR' THEN 2" in result

    def test_generate_in_sql_format(self):
        phases = ["P1-FOO", "P2-BAR", "P3-BAZ"]
        result = generate_in_sql(phases)
        assert result == "'P1-FOO','P2-BAR','P3-BAZ'"

    def test_phase_case_ordinals_in_script_tokens(self):
        tokens = derive_script_tokens(
            "quick", "Test",
            TechDetector("/tmp"),
            SpecReader(None, "/tmp"),
        )
        assert "PHASE_CASE_ORDINALS" in tokens
        assert "'P1-PLAN') echo 1;;" in tokens["PHASE_CASE_ORDINALS"]

    def test_phase_in_sql_in_script_tokens(self):
        tokens = derive_script_tokens(
            "quick", "Test",
            TechDetector("/tmp"),
            SpecReader(None, "/tmp"),
        )
        assert "'P1-PLAN'" in tokens["PHASE_IN_SQL"]
        assert "'P3-SHIP'" in tokens["PHASE_IN_SQL"]

    def test_project_phases_same_as_phases(self):
        tokens = derive_script_tokens(
            "full", "Test",
            TechDetector("/tmp"),
            SpecReader(None, "/tmp"),
        )
        assert tokens["PHASES"] == tokens["PROJECT_PHASES"]


# ---------------------------------------------------------------------------
# 5. Tech detection
# ---------------------------------------------------------------------------

class TestTechDetector:
    def test_package_json_detected_as_javascript(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "myapp"}')
        det = TechDetector(str(tmp_path))
        assert det.primary_language == "javascript"

    def test_cargo_toml_detected_as_rust(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"\nedition = "2021"\n')
        det = TechDetector(str(tmp_path))
        assert det.primary_language == "rust"

    def test_no_indicator_files_returns_none(self, tmp_path: Path):
        det = TechDetector(str(tmp_path))
        assert det.primary_language is None

    def test_pyproject_toml_detected_as_python(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "myapp"\n')
        det = TechDetector(str(tmp_path))
        assert det.primary_language == "python"

    def test_setup_py_detected_as_python(self, tmp_path: Path):
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")
        det = TechDetector(str(tmp_path))
        assert det.primary_language == "python"

    def test_go_mod_detected_as_go(self, tmp_path: Path):
        (tmp_path / "go.mod").write_text("module myapp\n\ngo 1.21\n")
        det = TechDetector(str(tmp_path))
        assert det.primary_language == "go"

    def test_package_swift_detected_as_swift(self, tmp_path: Path):
        (tmp_path / "Package.swift").write_text('// swift-tools-version:5.9\n')
        det = TechDetector(str(tmp_path))
        assert det.primary_language == "swift"

    def test_xcode_project_detected(self, tmp_path: Path):
        xcode_dir = tmp_path / "MyApp.xcodeproj"
        xcode_dir.mkdir()
        det = TechDetector(str(tmp_path))
        assert det.primary_language == "swift"
        assert det.xcodeproj_path == "MyApp.xcodeproj"

    def test_detect_returns_language_version_framework_tuple(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            '{"name": "myapp", "dependencies": {"react": "18.0.0"}}'
        )
        det = TechDetector(str(tmp_path))
        stacks = det.detect()
        assert len(stacks) == 1
        lang, version, fw = stacks[0]
        assert lang == "javascript"
        assert fw == "react"

    def test_detect_cached_on_second_call(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
        det = TechDetector(str(tmp_path))
        result1 = det.detect()
        result2 = det.detect()
        assert result1 is result2  # same object (cached)

    def test_rust_edition_parsed(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text('[package]\nedition = "2021"\n')
        det = TechDetector(str(tmp_path))
        stacks = det.detect()
        assert stacks[0][1] == "edition-2021"

    def test_go_version_parsed(self, tmp_path: Path):
        (tmp_path / "go.mod").write_text("module myapp\n\ngo 1.21\n")
        det = TechDetector(str(tmp_path))
        stacks = det.detect()
        assert stacks[0][1] == "1.21"


# ---------------------------------------------------------------------------
# 6. Spec reading
# ---------------------------------------------------------------------------

class TestSpecReader:
    def test_read_existing_file_returns_content(self, tmp_path: Path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "ENVISION.md").write_text("# Vision\nBuild something great\n")
        reader = SpecReader(str(specs_dir), str(tmp_path))
        content = reader.read("ENVISION.md")
        assert content is not None
        assert "Build something great" in content

    def test_read_missing_file_returns_none(self, tmp_path: Path):
        reader = SpecReader(None, str(tmp_path))
        assert reader.read("nonexistent.md") is None

    def test_read_from_project_root(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# My Project\nNorth star here\n")
        reader = SpecReader(None, str(tmp_path))
        content = reader.read("README.md")
        assert content is not None
        assert "North star here" in content

    def test_read_from_specs_subdir(self, tmp_path: Path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "SPEC.md").write_text("spec content")
        reader = SpecReader(None, str(tmp_path))
        content = reader.read("SPEC.md")
        assert content is not None
        assert "spec content" in content

    def test_available_specs_with_specs_dir(self, tmp_path: Path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "A.md").write_text("a")
        (specs_dir / "B.md").write_text("b")
        (specs_dir / "not_md.txt").write_text("c")
        reader = SpecReader(str(specs_dir), str(tmp_path))
        specs = reader.available_specs()
        assert "A.md" in specs
        assert "B.md" in specs
        assert "not_md.txt" not in specs

    def test_available_specs_no_dir_returns_empty(self, tmp_path: Path):
        reader = SpecReader(None, str(tmp_path))
        assert reader.available_specs() == []

    def test_custom_specs_dir_takes_precedence(self, tmp_path: Path):
        custom_dir = tmp_path / "custom_specs"
        custom_dir.mkdir()
        (custom_dir / "SPEC.md").write_text("custom content")
        (tmp_path / "SPEC.md").write_text("root content")
        reader = SpecReader(str(custom_dir), str(tmp_path))
        content = reader.read("SPEC.md")
        assert content == "custom content"


# ---------------------------------------------------------------------------
# 7. Dry-run mode
# ---------------------------------------------------------------------------

class TestDryRunMode:
    def test_file_unchanged_in_dry_run(self, tmp_path: Path):
        f = tmp_path / "test.md"
        original = "Name: %%PROJECT_NAME%%\n"
        f.write_text(original)
        engine = PlaceholderEngine(values={"PROJECT_NAME": "MyApp"}, dry_run=True)
        engine.apply(f)
        assert f.read_text() == original

    def test_report_generated_in_dry_run(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("%%PROJECT_NAME%%\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "MyApp"}, dry_run=True)
        engine.apply(f)
        assert len(engine.report) == 1
        assert engine.report[0].replacement == "MyApp"

    def test_count_returned_in_dry_run(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("%%PROJECT_NAME%% %%PROJECT_PATH%%\n")
        engine = PlaceholderEngine(
            values={"PROJECT_NAME": "X", "PROJECT_PATH": "/y"},
            dry_run=True,
        )
        count = engine.apply(f)
        assert count == 2

    def test_cli_dry_run_flag(self, tmp_path: Path):
        f = tmp_path / "doc.md"
        original = "%%PROJECT_NAME%%\n"
        f.write_text(original)
        exit_code = main([
            str(tmp_path),
            "--project-name", "TestProj",
            "--non-interactive",
            "--dry-run",
        ])
        assert f.read_text() == original
        assert exit_code in (0, 1)  # 0 = all resolved, 1 = some unresolved


# ---------------------------------------------------------------------------
# 8. JSON report format
# ---------------------------------------------------------------------------

class TestJsonReport:
    def test_json_report_required_top_level_keys(self, tmp_path: Path):
        (tmp_path / "test.md").write_text("%%PROJECT_NAME%%\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        stats = engine.apply_all(tmp_path)
        report = ReportGenerator(
            engine=engine,
            project_name="X",
            project_path=str(tmp_path),
            dry_run=False,
            stats=stats,
        ).build()
        required_keys = {
            "project_name", "project_path", "dry_run",
            "summary", "tokens", "replacements", "unresolved",
        }
        assert required_keys.issubset(set(report.keys()))

    def test_summary_keys(self, tmp_path: Path):
        (tmp_path / "test.md").write_text("%%PROJECT_NAME%%\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        stats = engine.apply_all(tmp_path)
        report = ReportGenerator(
            engine=engine,
            project_name="X",
            project_path=str(tmp_path),
            dry_run=False,
            stats=stats,
        ).build()
        summary = report["summary"]
        assert "total_tokens" in summary
        assert "resolved" in summary
        assert "unresolved" in summary
        assert "files_modified" in summary
        assert "total_replacements" in summary
        assert summary["total_tokens"] == 41

    def test_tokens_section_contains_all_registry_tokens(self, tmp_path: Path):
        engine = PlaceholderEngine(values={})
        stats = {"total_replacements": 0, "files_modified": 0}
        report = ReportGenerator(
            engine=engine,
            project_name="X",
            project_path=str(tmp_path),
            dry_run=False,
            stats=stats,
        ).build()
        for token_name in REGISTRY:
            assert token_name in report["tokens"], (
                f"Token '{token_name}' missing from report['tokens']"
            )

    def test_replacements_list_format(self, tmp_path: Path):
        f = tmp_path / "a.md"
        f.write_text("%%PROJECT_NAME%%\n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "MyApp"})
        stats = engine.apply_all(tmp_path)
        report = ReportGenerator(
            engine=engine,
            project_name="MyApp",
            project_path=str(tmp_path),
            dry_run=False,
            stats=stats,
        ).build()
        assert len(report["replacements"]) == 1
        rep = report["replacements"][0]
        assert "file" in rep
        assert "token" in rep
        assert "line" in rep
        assert "original" in rep
        assert "replacement" in rep
        assert rep["token"] == "PROJECT_NAME"
        assert rep["original"] == "%%PROJECT_NAME%%"
        assert rep["replacement"] == "MyApp"

    def test_dry_run_true_in_report(self, tmp_path: Path):
        engine = PlaceholderEngine(values={}, dry_run=True)
        stats = {"total_replacements": 0, "files_modified": 0}
        report = ReportGenerator(
            engine=engine,
            project_name="X",
            project_path=str(tmp_path),
            dry_run=True,
            stats=stats,
        ).build()
        assert report["dry_run"] is True

    def test_cli_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        (tmp_path / "doc.md").write_text("%%PROJECT_NAME%%\n")
        exit_code = main([
            str(tmp_path),
            "--project-name", "TestProj",
            "--non-interactive",
            "--json",
        ])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "summary" in data
        assert "tokens" in data
        assert data["project_name"] == "TestProj"


# ---------------------------------------------------------------------------
# 9. Missing specs graceful (no error)
# ---------------------------------------------------------------------------

class TestMissingSpecsGraceful:
    def test_no_specs_dir_no_error(self, tmp_path: Path):
        """Running on a project with no specs/ dir should not raise."""
        engine = PlaceholderEngine(values={})
        # This should complete without raising
        stats = engine.apply_all(tmp_path)
        assert stats["total_replacements"] == 0

    def test_build_values_no_specs_dir(self, tmp_path: Path):
        """build_values() with no specs dir should return defaults."""
        specs = SpecReader(None, str(tmp_path))
        tech = TechDetector(str(tmp_path))
        values = build_values(
            project_name="TestProj",
            project_path=str(tmp_path),
            specs=specs,
            tech=tech,
            lifecycle="quick",
            db_path=None,
            interactive=False,
            overrides={},
        )
        assert "PROJECT_NAME" in values
        assert values["PROJECT_NAME"] == "TestProj"
        # Auto tokens should fall back to defaults (not raise)
        assert "PROJECT_NORTH_STAR" in values
        assert values["PROJECT_NORTH_STAR"] == "TODO: Define project north star"

    def test_spec_reader_available_specs_no_dir(self, tmp_path: Path):
        reader = SpecReader(None, str(tmp_path))
        assert reader.available_specs() == []

    def test_empty_project_dir(self, tmp_path: Path):
        exit_code = main([
            str(tmp_path),
            "--project-name", "EmptyProj",
            "--non-interactive",
        ])
        assert exit_code in (0, 1)


# ---------------------------------------------------------------------------
# 10. User override via --set
# ---------------------------------------------------------------------------

class TestUserOverride:
    def test_set_overrides_auto_derived_value(self, tmp_path: Path):
        (tmp_path / "doc.md").write_text("%%COMMIT_FORMAT%%\n")
        exit_code = main([
            str(tmp_path),
            "--project-name", "TestProj",
            "--non-interactive",
            "--set", "COMMIT_FORMAT", "feat: description",
        ])
        content = (tmp_path / "doc.md").read_text()
        assert "feat: description" in content

    def test_set_overrides_sed_token(self, tmp_path: Path):
        (tmp_path / "doc.md").write_text("%%PROJECT_NAME%%\n")
        exit_code = main([
            str(tmp_path),
            "--project-name", "Original",
            "--non-interactive",
            "--set", "PROJECT_NAME", "Overridden",
        ])
        content = (tmp_path / "doc.md").read_text()
        assert "Overridden" in content
        assert "Original" not in content

    def test_multiple_set_flags(self, tmp_path: Path):
        (tmp_path / "doc.md").write_text(
            "%%PROJECT_NAME%% at %%PROJECT_PATH%%\n"
        )
        exit_code = main([
            str(tmp_path),
            "--project-name", "TestProj",
            "--non-interactive",
            "--set", "PROJECT_NAME", "CustomName",
            "--set", "PROJECT_PATH", "/custom/path",
        ])
        content = (tmp_path / "doc.md").read_text()
        assert "CustomName" in content
        assert "/custom/path" in content

    def test_build_values_overrides_applied(self, tmp_path: Path):
        specs = SpecReader(None, str(tmp_path))
        tech = TechDetector(str(tmp_path))
        values = build_values(
            project_name="TestProj",
            project_path=str(tmp_path),
            specs=specs,
            tech=tech,
            lifecycle="quick",
            db_path=None,
            interactive=False,
            overrides={"COMMIT_FORMAT": "custom: format"},
        )
        assert values["COMMIT_FORMAT"] == "custom: format"


# ---------------------------------------------------------------------------
# 11. Empty file
# ---------------------------------------------------------------------------

class TestEmptyFile:
    def test_empty_file_returns_zero_count(self, tmp_path: Path):
        f = tmp_path / "empty.md"
        f.write_text("")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        count = engine.apply(f)
        assert count == 0

    def test_empty_file_content_unchanged(self, tmp_path: Path):
        f = tmp_path / "empty.md"
        f.write_text("")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        engine.apply(f)
        assert f.read_text() == ""

    def test_empty_file_no_report_entries(self, tmp_path: Path):
        f = tmp_path / "empty.md"
        f.write_text("")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        engine.apply(f)
        assert engine.report == []

    def test_whitespace_only_file(self, tmp_path: Path):
        f = tmp_path / "ws.md"
        f.write_text("   \n\n   \n")
        engine = PlaceholderEngine(values={"PROJECT_NAME": "X"})
        count = engine.apply(f)
        assert count == 0


# ---------------------------------------------------------------------------
# Integration: framework tokens
# ---------------------------------------------------------------------------

class TestFrameworkTokens:
    def test_javascript_skip_patterns(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "app"}')
        det = TechDetector(str(tmp_path))
        tokens = derive_framework_tokens(det)
        assert tokens["SKIP_PATTERN_1"] == "build/*"
        assert tokens["SKIP_PATTERN_2"] == "dist/*"

    def test_python_skip_patterns(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "app"\n')
        det = TechDetector(str(tmp_path))
        tokens = derive_framework_tokens(det)
        assert tokens["SKIP_PATTERN_1"] == "venv/*"
        assert tokens["SKIP_PATTERN_2"] == "__pycache__/*"

    def test_rust_skip_patterns(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "app"\n')
        det = TechDetector(str(tmp_path))
        tokens = derive_framework_tokens(det)
        assert tokens["SKIP_PATTERN_1"] == "target/*"

    def test_unknown_tech_defaults_to_build_dist(self, tmp_path: Path):
        det = TechDetector(str(tmp_path))  # no indicator files
        tokens = derive_framework_tokens(det)
        assert tokens["SKIP_PATTERN_1"] == "build/*"
        assert tokens["SKIP_PATTERN_2"] == "dist/*"


# ---------------------------------------------------------------------------
# Integration: north star derivation from specs
# ---------------------------------------------------------------------------

class TestNorthStarDerivation:
    def test_north_star_from_vision_header(self, tmp_path: Path):
        (tmp_path / "README.md").write_text(
            "# MyProject\n\n## Vision\nMake developers happy\n"
        )
        specs = SpecReader(None, str(tmp_path))
        tech = TechDetector(str(tmp_path))
        values = build_values(
            project_name="Test",
            project_path=str(tmp_path),
            specs=specs,
            tech=tech,
            lifecycle="quick",
            db_path=None,
            interactive=False,
            overrides={},
        )
        assert values["PROJECT_NORTH_STAR"] == "Make developers happy"

    def test_north_star_default_when_no_spec(self, tmp_path: Path):
        specs = SpecReader(None, str(tmp_path))
        tech = TechDetector(str(tmp_path))
        values = build_values(
            project_name="Test",
            project_path=str(tmp_path),
            specs=specs,
            tech=tech,
            lifecycle="quick",
            db_path=None,
            interactive=False,
            overrides={},
        )
        assert "TODO" in values["PROJECT_NORTH_STAR"]
