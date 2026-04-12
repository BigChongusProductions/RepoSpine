"""
Structural lint checks for project configuration files.
"""
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import ProjectConfig


def cmd_lint(config: ProjectConfig, fix: bool = False) -> None:
    """Run structural lint checks on project configuration."""
    errors = 0
    warnings = 0

    print("")
    print("── Lint Checks ─────────────────────────────────────────────")

    # L1: Dead glob patterns in .claude/rules/*.md
    e, w = _check_dead_globs(config)
    errors += e
    warnings += w

    # L2: Wrong field name (globs: instead of paths:)
    e, w = _check_field_names(config)
    errors += e
    warnings += w

    # L3: Broken @-imports in CLAUDE.md
    e, w = _check_imports(config)
    errors += e
    warnings += w

    # L4: Unfilled placeholders in operational files
    e, w = _check_placeholders(config)
    errors += e
    warnings += w

    # L5: Missing test modules
    e, w = _check_test_coverage(config)
    errors += e
    warnings += w

    # L6: Agent tool contradictions
    e, w = _check_agent_tools(config)
    errors += e
    warnings += w

    # Verdict
    print("")
    if errors > 0:
        print(f"  \u274c Lint: {errors} error(s), {warnings} warning(s)")
    elif warnings > 0:
        print(f"  \u26a0\ufe0f  Lint: {warnings} warning(s)")
    else:
        print(f"  \u2705 Lint: clean")
    print("")


def quick_lint(config: ProjectConfig) -> Tuple[int, int]:
    """Run fast lint checks only (L1-L3). Returns (warnings, errors)."""
    errors = 0
    warnings = 0

    e, w = _check_dead_globs(config)
    errors += e
    warnings += w

    e, w = _check_field_names(config)
    errors += e
    warnings += w

    e, w = _check_imports(config)
    errors += e
    warnings += w

    return warnings, errors


def _parse_paths_field(rule_file: Path) -> Optional[List[str]]:
    """Parse paths: (or globs:) field from a rules .md file frontmatter.

    Returns list of patterns, or empty list if no paths/globs field found.
    Returns None for unconditional rules (no frontmatter or no paths field).
    """
    content = rule_file.read_text(encoding="utf-8")

    # Check for frontmatter
    if not content.startswith("---"):
        return None

    # Find end of frontmatter
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return None

    frontmatter = content[3:end_idx]

    # Look for paths: or globs: field
    patterns: List[str] = []
    in_paths_field = False
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("paths:") or stripped.startswith("globs:"):
            in_paths_field = True
            # Could be inline array or start of list
            value = stripped.split(":", 1)[1].strip()
            if value:
                # Inline: paths: ["foo", "bar"] or paths: foo
                # Strip brackets and quotes
                value = value.strip("[]")
                for item in value.split(","):
                    item = item.strip().strip("'\"")
                    if item:
                        patterns.append(item)
        elif stripped.startswith("- ") and in_paths_field:
            # YAML list continuation (only if we already found paths:)
            item = stripped[2:].strip().strip("'\"")
            if item:
                patterns.append(item)
        elif stripped and ":" in stripped and not stripped.startswith("-"):
            # New field started — stop collecting list items
            in_paths_field = False

    return patterns if patterns else None


# ── L1: Dead glob patterns ────────────────────────────────────────────

def _check_dead_globs(config: ProjectConfig) -> Tuple[int, int]:
    """Check .claude/rules/*.md for paths: patterns matching zero files."""
    rules_dir = config.project_dir / ".claude" / "rules"
    if not rules_dir.is_dir():
        return 0, 0

    errors = 0
    warnings = 0
    for rule_file in sorted(rules_dir.glob("*.md")):
        patterns = _parse_paths_field(rule_file)
        if patterns is None:
            continue  # unconditional rule — skip

        for pattern in patterns:
            matches = list(config.project_dir.glob(pattern))
            if not matches:
                content = rule_file.read_text(encoding="utf-8")
                if "# lint:ignore" in content:
                    continue
                print(f"  \u26a0\ufe0f  L1: Dead pattern in {rule_file.name}: '{pattern}' matches 0 files")
                warnings += 1

    return errors, warnings


# ── L2: Wrong field name ──────────────────────────────────────────────

def _check_field_names(config: ProjectConfig) -> Tuple[int, int]:
    """Check rules files for deprecated globs: field instead of paths:."""
    rules_dir = config.project_dir / ".claude" / "rules"
    if not rules_dir.is_dir():
        return 0, 0

    errors = 0
    warnings = 0
    for rule_file in sorted(rules_dir.glob("*.md")):
        content = rule_file.read_text(encoding="utf-8")
        if not content.startswith("---"):
            continue
        end_idx = content.find("---", 3)
        if end_idx == -1:
            continue
        frontmatter = content[3:end_idx]
        for line in frontmatter.splitlines():
            if line.strip().startswith("globs:"):
                print(f"  \u274c L2: Wrong field in {rule_file.name}: 'globs:' should be 'paths:'")
                errors += 1

    return errors, warnings


# ── L3: Broken @-imports ──────────────────────────────────────────────

def _check_imports(config: ProjectConfig) -> Tuple[int, int]:
    """Check CLAUDE.md for @-import paths that don't exist."""
    claude_md = config.project_dir / "CLAUDE.md"
    if not claude_md.exists():
        return 0, 0

    errors = 0
    warnings = 0
    content = claude_md.read_text(encoding="utf-8")

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("@"):
            continue
        # Skip @-imports that are clearly comments or doubled
        if stripped.startswith("@import") or stripped.startswith("@@"):
            continue

        path_str = stripped[1:].strip()
        if not path_str:
            continue

        # Expand ~ to home directory
        if path_str.startswith("~"):
            import os
            path = Path(os.path.expanduser(path_str))
        else:
            path = config.project_dir / path_str

        if not path.exists():
            print(f"  \u274c L3: Broken @-import in CLAUDE.md: '{stripped}' \u2192 {path} not found")
            errors += 1

    return errors, warnings


# ── L4: Unfilled placeholders ─────────────────────────────────────────

def _check_placeholders(config: ProjectConfig) -> Tuple[int, int]:
    """Check operational files for unfilled %%PLACEHOLDER%% tokens."""
    errors = 0
    warnings = 0

    # Only check operational files (hooks, scripts), not templates
    check_dirs = [
        config.project_dir / ".claude" / "hooks",
        config.project_dir / ".claude" / "agents",
        config.project_dir / ".claude" / "rules",
    ]

    placeholder_re = re.compile(r"%%[A-Z_]+%%")
    # Skip placeholders inside backticks (documentation references)
    backtick_re = re.compile(r"`[^`]*%%[A-Z_]+%%[^`]*`")

    for check_dir in check_dirs:
        if not check_dir.is_dir():
            continue
        for f in sorted(check_dir.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix in (".md", ".sh", ".py", ".json", ".yaml", ".yml"):
                try:
                    content = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                # Strip backtick-quoted content before checking
                stripped_content = backtick_re.sub("", content)
                matches = placeholder_re.findall(stripped_content)
                if matches:
                    rel = f.relative_to(config.project_dir)
                    print(f"  \u274c L4: Unfilled placeholder in {rel}: {', '.join(set(matches))}")
                    errors += 1

    return errors, warnings


# ── L5: Missing test modules ─────────────────────────────────────────

def _check_test_coverage(config: ProjectConfig) -> Tuple[int, int]:
    """Check that dbq command modules have corresponding test files."""
    errors = 0
    warnings = 0

    commands_dir = config.project_dir / "templates" / "scripts" / "dbq" / "commands"
    # Check both the project-level tests/ dir and the dbq-internal tests/ dir
    dbq_tests_dir = config.project_dir / "templates" / "scripts" / "dbq" / "tests"
    project_tests_dir = config.project_dir / "tests"

    if not commands_dir.is_dir():
        return 0, 0

    for cmd_file in sorted(commands_dir.glob("*.py")):
        if cmd_file.name.startswith("__"):
            continue

        # Expected test file: test_dbq_{module_name}.py or test_{module_name}.py
        module_name = cmd_file.stem
        test_candidates = [
            dbq_tests_dir / f"test_{module_name}.py",
            dbq_tests_dir / f"test_dbq_{module_name}.py",
            project_tests_dir / f"test_dbq_{module_name}.py",
            project_tests_dir / f"test_{module_name}.py",
        ]

        has_test = any(t.exists() for t in test_candidates)
        if not has_test:
            print(f"  \u26a0\ufe0f  L5: No test file for commands/{cmd_file.name}")
            warnings += 1

    return errors, warnings


# ── L6: Agent tool contradictions ─────────────────────────────────────

def _check_agent_tools(config: ProjectConfig) -> Tuple[int, int]:
    """Check agent definitions for tools in both tools and disallowedTools."""
    errors = 0
    warnings = 0

    agents_dir = config.project_dir / ".claude" / "agents"
    if not agents_dir.is_dir():
        return 0, 0

    for agent_file in sorted(agents_dir.glob("*.md")):
        content = agent_file.read_text(encoding="utf-8")

        # Parse tools and disallowedTools from frontmatter
        if not content.startswith("---"):
            continue
        end_idx = content.find("---", 3)
        if end_idx == -1:
            continue
        frontmatter = content[3:end_idx]

        tools: set = set()
        disallowed: set = set()
        current_field: Optional[str] = None

        for line in frontmatter.splitlines():
            stripped = line.strip()
            if stripped.startswith("tools:"):
                current_field = "tools"
                val = stripped.split(":", 1)[1].strip()
                if val:
                    for item in val.strip("[]").split(","):
                        item = item.strip().strip("'\"")
                        if item:
                            tools.add(item)
            elif stripped.startswith("disallowedTools:"):
                current_field = "disallowed"
                val = stripped.split(":", 1)[1].strip()
                if val:
                    for item in val.strip("[]").split(","):
                        item = item.strip().strip("'\"")
                        if item:
                            disallowed.add(item)
            elif stripped.startswith("- ") and current_field:
                item = stripped[2:].strip().strip("'\"")
                if current_field == "tools":
                    tools.add(item)
                elif current_field == "disallowed":
                    disallowed.add(item)
            elif stripped and ":" in stripped and not stripped.startswith("-"):
                current_field = None  # New field started

        # Check for contradictions
        overlap = tools & disallowed
        if overlap:
            print(f"  \u26a0\ufe0f  L6: Contradiction in {agent_file.name}: "
                  f"{', '.join(sorted(overlap))} in both tools and disallowedTools")
            warnings += 1

    return errors, warnings
