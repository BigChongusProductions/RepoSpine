"""fp_registry.py — Token registry for fill_placeholders.

Defines the TokenDef and Replacement dataclasses, the _td() helper, and
the REGISTRY dict of 50 placeholder tokens.

Stdlib only: dataclasses, typing
Python 3.10+
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TokenDef:
    """Definition of a single placeholder token (format: pct pct NAME pct pct)."""
    name: str
    category: str           # auto | user | sed | script | framework
    pattern: str            # regex pattern for this token
    files: list[str]        # which template files contain this token
    derivation: str         # human-readable derivation strategy
    default: str | None     # fallback if derivation fails
    requires_spec: bool     # True if spec files needed for derivation
    requires_tech: bool     # True if tech detection needed


@dataclass
class Replacement:
    """Record of a single token replacement (or unresolved token)."""
    file: str
    token: str
    original: str
    replacement: str | None  # None = unresolved
    line: int


# ---------------------------------------------------------------------------
# Registry — 50 tokens
# ---------------------------------------------------------------------------

def _td(name: str, category: str, files: list[str], derivation: str,
        default: str | None = None, requires_spec: bool = False,
        requires_tech: bool = False) -> TokenDef:
    """Convenience constructor for TokenDef."""
    return TokenDef(
        name=name,
        category=category,
        pattern=f"%%{name}%%",
        files=files,
        derivation=derivation,
        default=default,
        requires_spec=requires_spec,
        requires_tech=requires_tech,
    )


REGISTRY: dict[str, TokenDef] = {
    # --- Auto-derivable (12) ---
    "PROJECT_NORTH_STAR": _td(
        "PROJECT_NORTH_STAR", "auto",
        ["RULES_TEMPLATE.md"],
        "Read spec.md or main README — the 1-line vision statement",
        default="TODO: Define project north star",
        requires_spec=True,
    ),
    "TECH_STACK": _td(
        "TECH_STACK", "auto",
        ["RULES_TEMPLATE.md"],
        "Detect language/framework from root files",
        default="TODO: Define tech stack",
        requires_tech=True,
    ),
    "FIRST_PHASE": _td(
        "FIRST_PHASE", "auto",
        ["RULES_TEMPLATE.md", "AGENT_DELEGATION_TEMPLATE.md", "db_queries.template.sh"],
        "Query DB for first phase, or derive from lifecycle mode",
        default="P1-ENVISION",
    ),
    "MCP_SERVERS": _td(
        "MCP_SERVERS", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "Check environment for connected MCP servers",
        default="TODO: List MCP servers (check .claude/settings.json)",
    ),
    "GEMINI_MCP_TABLE": _td(
        "GEMINI_MCP_TABLE", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "Table of Gemini-capable MCP tools",
        default="TODO: Fill Gemini MCP table",
    ),
    "VISUAL_VERIFICATION": _td(
        "VISUAL_VERIFICATION", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "If web/desktop UI project: visual verification checklist; else 'Not applicable'",
        default="Not applicable — non-UI project",
        requires_tech=True,
    ),
    "EXTRA_MANDATORY_SKILLS": _td(
        "EXTRA_MANDATORY_SKILLS", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "List skills that must run before merge",
        default="None additional",
    ),
    "RECOMMENDED_SKILLS": _td(
        "RECOMMENDED_SKILLS", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "Skills recommended for new phases",
        default="None additional",
    ),
    "EXTRA_MODEL_DELEGATION": _td(
        "EXTRA_MODEL_DELEGATION", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "Additional model delegation rows if using Gemini/Grok/Ollama",
        default="",
    ),
    "GITIGNORE_TABLE": _td(
        "GITIGNORE_TABLE", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "Table of .gitignore patterns by tech stack",
        default="TODO: Fill .gitignore table for your tech stack",
        requires_tech=True,
    ),
    "OUTPUT_VERIFICATION_GATE": _td(
        "OUTPUT_VERIFICATION_GATE", "auto",
        ["RULES_TEMPLATE.md"],
        "Define output verification gate based on project type",
        default="Not applicable",
        requires_tech=True,
    ),
    "TEAM_TOPOLOGY": _td(
        "TEAM_TOPOLOGY", "auto",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "Agent Teams topology table if Agent Teams is ACTIVE",
        default=(
            "Agent Teams mode is INACTIVE. "
            "Activate in .claude/settings.json and restart."
        ),
    ),

    # --- User-provided (4) ---
    "COMMIT_FORMAT": _td(
        "COMMIT_FORMAT", "user",
        ["RULES_TEMPLATE.md"],
        "What commit message format does your team use?",
        default="type(scope): description\n\nBody (optional)\n\nCo-Authored-By: ...",
    ),
    "BUILD_TEST_INSTRUCTIONS": _td(
        "BUILD_TEST_INSTRUCTIONS", "user",
        ["RULES_TEMPLATE.md"],
        "How do you build and test locally?",
        default="TODO: Add build and test instructions",
        requires_tech=True,
    ),
    "CODE_STANDARDS": _td(
        "CODE_STANDARDS", "user",
        ["RULES_EXTENDED_TEMPLATE.md"],
        "What code quality tools do you use?",
        default="TODO: Define code standards",
        requires_tech=True,
    ),
    "PROJECT_STOP_RULES": _td(
        "PROJECT_STOP_RULES", "user",
        ["RULES_TEMPLATE.md"],
        "Any project-specific STOP rules beyond universal rules?",
        default="None beyond universal (see CLAUDE.md §10)",
    ),

    # --- Sed tokens (12) ---
    "PROJECT_NAME": _td(
        "PROJECT_NAME", "sed",
        [
            "implementer.template.md", "worker.template.md",
            "save_session.template.sh", "fix.template.sh", "work.template.sh",
            "db_queries.template.sh", "session_briefing.template.sh",
            "RULES_TEMPLATE.md",
        ],
        "Project display name from --project-name argument",
        default="TODO: Set PROJECT_NAME",
    ),
    "PROJECT_PATH": _td(
        "PROJECT_PATH", "sed",
        [
            "save_session.template.sh", "fix.template.sh", "work.template.sh",
            "RULES_TEMPLATE.md", "RULES_EXTENDED_TEMPLATE.md",
        ],
        "Absolute path to project root",
        default="TODO: Set PROJECT_PATH",
    ),
    "PROJECT_DB": _td(
        "PROJECT_DB", "sed",
        [
            "save_session.template.sh", "db_queries.template.sh",
            "milestone_check.template.sh", "work.template.sh",
            "session_briefing.template.sh", "generate_board.template.py",
        ],
        "SQLite database filename (with .db extension)",
        default="TODO: Set PROJECT_DB",
    ),
    "LESSONS_FILE": _td(
        "LESSONS_FILE", "sed",
        [
            "db_queries.template.sh", "session_briefing.template.sh",
            "coherence_check.template.sh", "harvest.template.sh",
            "CLAUDE_TEMPLATE.md",
        ],
        "Lessons/corrections log filename",
        default="TODO: Set LESSONS_FILE",
    ),
    "RULES_FILE": _td(
        "RULES_FILE", "sed",
        [
            "session_briefing.template.sh", "CLAUDE_TEMPLATE.md",
            "AGENT_DELEGATION_TEMPLATE.md",
        ],
        "Project rules markdown filename",
        default="TODO: Set RULES_FILE",
    ),
    "MEMORY_FILE": _td(
        "MEMORY_FILE", "sed",
        ["session_briefing.template.sh"],
        "Project memory markdown filename",
        default="TODO: Set MEMORY_FILE",
    ),
    "PROJECT_MEMORY_FILE": _td(
        "PROJECT_MEMORY_FILE", "sed",
        [
            "session_briefing.template.sh", "RULES_TEMPLATE.md",
            "RULES_EXTENDED_TEMPLATE.md",
        ],
        "Project memory markdown filename",
        default="TODO: Set PROJECT_MEMORY_FILE",
    ),
    "PROJECT_DB_NAME": _td(
        "PROJECT_DB_NAME", "sed",
        ["session_briefing.template.sh"],
        "DB filename without .db extension",
        default="TODO: Set PROJECT_DB_NAME",
    ),
    "PROJECT_RULES_FILE": _td(
        "PROJECT_RULES_FILE", "sed",
        ["templates/hooks/protected-files.template.conf"],
        "Project rules markdown filename (for hooks)",
        default="TODO: Set PROJECT_RULES_FILE",
    ),
    "PROJECT_NAME_UPPER": _td(
        "PROJECT_NAME_UPPER", "sed",
        ["RULES_TEMPLATE.md"],
        "Project name uppercased with underscores",
        default="TODO: Set PROJECT_NAME_UPPER",
    ),
    "PERMISSION_ALLOW": _td(
        "PERMISSION_ALLOW", "sed",
        ["templates/settings/settings.template.json"],
        "Permission allow array (JSON array of tool patterns)",
        default="",
    ),
    "LOCAL_PERMISSIONS": _td(
        "LOCAL_PERMISSIONS", "sed",
        ["templates/settings/settings.local.template.json"],
        "Local permission overrides (empty by default)",
        default="",
    ),

    # --- Script-specific (12) ---
    "PHASES": _td(
        "PHASES", "script",
        ["db_queries.template.sh"],
        "Space-separated phase list for DBQ_PHASES env var",
        default="P1-PLAN P2-BUILD P3-SHIP",
    ),
    "PROJECT_PHASES": _td(
        "PROJECT_PHASES", "script",
        ["templates/scripts/dbq/tests/test_cli.py"],
        "Space-separated phase list (same as PHASES, used in pytest fixtures)",
        default="P1-PLAN P2-BUILD P3-SHIP",
    ),
    "OWN_DB_PATTERNS": _td(
        "OWN_DB_PATTERNS", "script",
        [".claude/hooks/protect-databases.template.sh"],
        "Grep regex pattern for project DB name(s)",
        default=r"project\.db",
    ),
    "AGENT_NAMES": _td(
        "AGENT_NAMES", "script",
        [".claude/hooks/post-compact-recovery.template.sh"],
        "Formatted agent list for post-compaction recovery context",
        default="",
    ),
    "TECH_STANDARDS": _td(
        "TECH_STANDARDS", "script",
        ["templates/agents/implementer.template.md"],
        "Full tech standards block for implementer agent",
        default="TODO: Define tech standards",
        requires_tech=True,
    ),
    "TECH_STANDARDS_BRIEF": _td(
        "TECH_STANDARDS_BRIEF", "script",
        ["templates/agents/worker.template.md"],
        "Brief tech standards (3-4 key rules) for worker agent",
        default="TODO: Define brief tech standards",
        requires_tech=True,
    ),
    "LESSON_LOG_COMMAND": _td(
        "LESSON_LOG_COMMAND", "script",
        ["templates/hooks/correction-detector.template.sh"],
        "Lesson logging command",
        default="bash db_queries.sh log-lesson",
    ),
    "BUILD_COMMAND": _td(
        "BUILD_COMMAND", "script",
        ["templates/agents/implementer.template.md", "templates/scripts/build_summarizer.template.sh"],
        "Build/health-check command sub-agents run after implementation",
        default="bash db_queries.sh health",
        requires_tech=True,
    ),
    "TEST_COMMAND": _td(
        "TEST_COMMAND", "script",
        ["templates/scripts/build_summarizer.template.sh"],
        "Test command for build summarizer test step",
        default="bash db_queries.sh health",
        requires_tech=True,
    ),
    "LINT_COMMAND": _td(
        "LINT_COMMAND", "script",
        ["templates/scripts/build_summarizer.template.sh"],
        "Lint command for build summarizer lint step",
        default="echo 'No linter configured'",
        requires_tech=True,
    ),
    "BATCH_PROCESS_COMMAND": _td(
        "BATCH_PROCESS_COMMAND", "script",
        ["templates/scripts/batch_pipeline.template.sh"],
        "Command to process a single item in the batch pipeline (receives $ITEM)",
        default="echo \"Processing: $ITEM\"",
    ),
    # --- Framework-specific (2) ---
    "SKIP_PATTERN_1": _td(
        "SKIP_PATTERN_1", "framework",
        ["templates/scripts/coherence_check.template.sh"],
        "First coherence_check skip pattern (tech-stack-specific)",
        default="build/*",
        requires_tech=True,
    ),
    "SKIP_PATTERN_2": _td(
        "SKIP_PATTERN_2", "framework",
        ["templates/scripts/coherence_check.template.sh"],
        "Second coherence_check skip pattern (tech-stack-specific)",
        default="dist/*",
        requires_tech=True,
    ),

    # --- Alias / compat tokens (2) ---
    "DB_NAME": _td(
        "DB_NAME", "sed",
        [
            "db_queries.template.sh", "session_briefing.template.sh",
            "milestone_check.template.sh", "build_summarizer.template.sh",
            "save_session.template.sh", "shared_signal.template.sh",
        ],
        "Database filename (alias for PROJECT_DB)",
        default="%%PROJECT_DB%%",
    ),
    "DB_NAME_BASE": _td(
        "DB_NAME_BASE", "sed",
        ["session_briefing.template.sh"],
        "Database name without .db extension (alias for PROJECT_DB_NAME)",
        default="%%PROJECT_DB_NAME%%",
    ),

    # --- Git tokens (2) ---
    "MAIN_BRANCH": _td(
        "MAIN_BRANCH", "sed",
        ["milestone_check.template.sh", "RULES_TEMPLATE.md"],
        "Main git branch name",
        default="main",
    ),
    "DEV_BRANCH": _td(
        "DEV_BRANCH", "sed",
        ["milestone_check.template.sh", "RULES_TEMPLATE.md"],
        "Development branch name",
        default="dev",
    ),

    # --- Framework file token (1) ---
    "DELEGATION_FILE": _td(
        "DELEGATION_FILE", "framework",
        ["db_queries.template.sh"],
        "Delegation mapping filename",
        default="AGENT_DELEGATION.md",
    ),

    # --- Tech-specific tokens (4) ---
    "TECH_STACK_HOOKS": _td(
        "TECH_STACK_HOOKS", "tech",
        ["templates/agents/implementer.template.md"],
        "Tech-stack-specific hook configuration",
        default="",
        requires_tech=True,
    ),
    "XCODE_PROJECT_PATH": _td(
        "XCODE_PROJECT_PATH", "tech",
        ["templates/scripts/build_summarizer_xcode.template.sh"],
        "Xcode project file path",
        default="",
        requires_tech=True,
    ),
    "XCODE_SCHEME": _td(
        "XCODE_SCHEME", "tech",
        ["templates/scripts/build_summarizer_xcode.template.sh"],
        "Xcode build scheme name",
        default="",
        requires_tech=True,
    ),
    "XCODE_TEST_SCHEME": _td(
        "XCODE_TEST_SCHEME", "tech",
        ["templates/scripts/build_summarizer_xcode.template.sh"],
        "Xcode test scheme name",
        default="",
        requires_tech=True,
    ),
}

# Development guard: fail fast if registry count drifts from expected
assert len(REGISTRY) == 50, (
    f"REGISTRY has {len(REGISTRY)} tokens, expected 50. "
    "Update this assertion if you intentionally add/remove tokens."
)
