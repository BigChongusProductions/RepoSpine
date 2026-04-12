"""fp_engine.py — Derivation engine for fill_placeholders.

Contains SpecReader, TechDetector, all per-tech constants, all derivation
functions, AUTO_DERIVATION_DISPATCH, USER_QUESTIONS, and build_values().

Stdlib only: json, os, re, sqlite3, sys, pathlib, typing
Python 3.10+
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from fp_registry import TokenDef, Replacement, REGISTRY


# ---------------------------------------------------------------------------
# SpecReader
# ---------------------------------------------------------------------------

class SpecReader:
    """Reads project spec files for auto-derivation context."""

    def __init__(self, specs_dir: str | None, project_path: str) -> None:
        self.specs_dir = Path(specs_dir) if specs_dir else None
        self.project_path = Path(project_path)

    def read(self, filename: str) -> str | None:
        """Read a file from specs_dir or project root. Returns None if not found."""
        candidates: list[Path] = []
        if self.specs_dir:
            candidates.append(self.specs_dir / filename)
        candidates.append(self.project_path / filename)
        candidates.append(self.project_path / "specs" / filename)

        for path in candidates:
            if path.exists():
                try:
                    return path.read_text(errors="ignore")
                except OSError:
                    pass
        return None

    def available_specs(self) -> list[str]:
        """List available spec files (.md only)."""
        if self.specs_dir and self.specs_dir.exists():
            return [f.name for f in self.specs_dir.iterdir() if f.suffix == ".md"]
        specs_path = self.project_path / "specs"
        if specs_path.exists():
            return [f.name for f in specs_path.iterdir() if f.suffix == ".md"]
        return []


# ---------------------------------------------------------------------------
# TechDetector
# ---------------------------------------------------------------------------

def _parse_node_version(content: str) -> tuple[str, str, str | None]:
    try:
        data = json.loads(content)
        version = data.get("engines", {}).get("node", "lts")
        framework: str | None = None
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for fw in ("next", "react", "vue", "angular", "svelte", "express", "fastify"):
            if fw in deps:
                framework = fw
                break
        return ("javascript", version or "lts", framework)
    except (json.JSONDecodeError, AttributeError):
        return ("javascript", "lts", None)


def _parse_python_version(content: str) -> tuple[str, str, str | None]:
    match = re.search(r'python_requires\s*=\s*["\']([^"\']+)', content)
    version = match.group(1) if match else "3.x"
    framework: str | None = None
    for fw in ("django", "flask", "fastapi", "starlette"):
        if fw in content.lower():
            framework = fw
            break
    return ("python", version, framework)


def _parse_rust_version(content: str) -> tuple[str, str, str | None]:
    match = re.search(r'edition\s*=\s*["\'](\d+)', content)
    edition = match.group(1) if match else "2021"
    return ("rust", f"edition-{edition}", None)


def _parse_go_version(content: str) -> tuple[str, str, str | None]:
    match = re.search(r"^go\s+([\d.]+)", content, re.MULTILINE)
    version = match.group(1) if match else "1.x"
    return ("go", version, None)


class TechDetector:
    """Detects project tech stack from root files."""

    # File-based indicators: filename -> (language, parser_fn)
    INDICATORS: dict[str, tuple[str, Any]] = {
        "package.json": ("javascript", _parse_node_version),
        "setup.py": ("python", lambda c: ("python", "3.x", None)),
        "pyproject.toml": ("python", _parse_python_version),
        "Cargo.toml": ("rust", _parse_rust_version),
        "go.mod": ("go", _parse_go_version),
        "Package.swift": ("swift", lambda c: ("swift", "5.x", "SwiftPM")),
    }

    # Glob-based indicators
    GLOB_INDICATORS: dict[str, tuple[str, Any]] = {
        "*.xcodeproj": ("swift", lambda c: ("swift", "5.x", "Xcode")),
    }

    def __init__(self, project_path: str) -> None:
        self.project_path = Path(project_path)
        self._detected: list[tuple[str, str, str | None]] | None = None
        self._xcodeproj: str | None = None

    def detect(self) -> list[tuple[str, str, str | None]]:
        """Return list of (language, version, framework) tuples."""
        if self._detected is not None:
            return self._detected
        results: list[tuple[str, str, str | None]] = []

        for indicator, (_, parser) in self.INDICATORS.items():
            path = self.project_path / indicator
            if path.exists():
                try:
                    content = path.read_text(errors="ignore")
                except OSError:
                    content = ""
                results.append(parser(content))

        for pattern, (_, parser) in self.GLOB_INDICATORS.items():
            matches = list(self.project_path.glob(pattern))
            if matches:
                self._xcodeproj = str(matches[0].relative_to(self.project_path))
                results.append(parser(""))

        self._detected = results
        return results

    @property
    def primary_language(self) -> str | None:
        """Return the first detected language, or None."""
        stacks = self.detect()
        return stacks[0][0] if stacks else None

    @property
    def xcodeproj_path(self) -> str | None:
        """Return relative path to .xcodeproj if detected."""
        self.detect()
        return self._xcodeproj


# ---------------------------------------------------------------------------
# Per-tech constants
# ---------------------------------------------------------------------------

SKIP_PATTERNS_BY_TECH: dict[str, tuple[str, str]] = {
    "javascript": ("build/*", "dist/*"),
    "typescript": ("build/*", "dist/*"),
    "python": ("venv/*", "__pycache__/*"),
    "rust": ("target/*", ""),
    "swift": (".build/*", ""),
    "go": ("vendor/*", ""),
}

TECH_STANDARDS_BY_LANG: dict[str, str] = {
    "javascript": (
        "- Use TypeScript strict mode\n"
        "- ESLint + Prettier enforced\n"
        "- async/await over callbacks\n"
        "- No `any` type without justification"
    ),
    "python": (
        "- Type hints required on all functions\n"
        "- ruff + mypy enforced\n"
        "- No bare `except:` clauses\n"
        "- Use dataclasses or Pydantic for structured data"
    ),
    "rust": (
        "- No `unwrap()` in production code — use `?` or proper error handling\n"
        "- clippy lints must pass\n"
        "- `unsafe` blocks require justification comment"
    ),
    "swift": (
        "- Use Swift concurrency (async/await) over callbacks\n"
        "- No force unwrap in production code\n"
        "- SwiftLint enforced"
    ),
    "go": (
        "- Errors must be handled explicitly\n"
        "- Use `context.Context` for cancellation\n"
        "- golangci-lint enforced"
    ),
}

BUILD_COMMANDS_BY_LANG: dict[str, str] = {
    "javascript": "npm run build && npm test",
    "python": "python3 -m pytest",
    "rust": "cargo build && cargo test",
    "swift": "swift build && swift test",
    "go": "go build ./... && go test ./...",
}

TEST_COMMANDS_BY_LANG: dict[str, str] = {
    "javascript": "npm test",
    "python": "python3 -m pytest",
    "rust": "cargo test",
    "swift": "swift test",
    "go": "go test ./...",
}

LINT_COMMANDS_BY_LANG: dict[str, str] = {
    "javascript": "npm run lint",
    "python": "ruff check .",
    "rust": "cargo clippy",
    "swift": "swiftlint",
    "go": "golangci-lint run",
}


# ---------------------------------------------------------------------------
# Derivation functions — uniform signature: (specs, tech, **kwargs) -> str
# ---------------------------------------------------------------------------

def _derive_project_north_star(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    for spec_file in ["spec.md", "README.md", "specs/ENVISION.md", "ENVISION.md"]:
        content = specs.read(spec_file)
        if content:
            m = re.search(
                r"##\s+(?:Vision|Purpose|North Star|Goal)\s*\n(.+)", content
            )
            if m:
                return m.group(1).strip()
            # Fallback: first non-header, non-empty line
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line[:120]
    return "TODO: Define project north star"


def _derive_tech_stack(specs: SpecReader, tech: TechDetector, **kwargs: Any) -> str:
    stack_parts = tech.detect()
    if not stack_parts:
        return "TODO: Define tech stack"
    return ", ".join(
        f"{lang} {ver} + {fw}" if fw else f"{lang} {ver}"
        for lang, ver, fw in stack_parts
    )


def _derive_first_phase(specs: SpecReader, tech: TechDetector, **kwargs: Any) -> str:
    db_path = kwargs.get("db_path")
    if db_path and Path(db_path).exists():
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT DISTINCT phase FROM tasks ORDER BY phase LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                return row[0]
        except sqlite3.Error:
            pass
    lifecycle = kwargs.get("lifecycle", "full")
    return "P1-ENVISION" if lifecycle == "full" else "P1-PLAN"


def _derive_visual_verification(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    if lang in ("javascript", "typescript"):
        return (
            "For each UI change: screenshot before/after, "
            "check layout at 320px/768px/1440px, run Playwright smoke tests."
        )
    return "Not applicable — non-UI project"


def _derive_gitignore_table(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    tables: dict[str, str] = {
        "javascript": (
            "| Pattern | Reason |\n"
            "|---------|--------|\n"
            "| `node_modules/` | Dependencies |\n"
            "| `dist/` | Build output |\n"
            "| `build/` | Build output |\n"
            "| `.env` | Secrets |\n"
            "| `coverage/` | Test coverage |\n"
            "| `.next/` | Next.js cache |"
        ),
        "python": (
            "| Pattern | Reason |\n"
            "|---------|--------|\n"
            "| `venv/` | Virtual environment |\n"
            "| `__pycache__/` | Bytecode cache |\n"
            "| `*.pyc` | Compiled Python |\n"
            "| `.env` | Secrets |\n"
            "| `.pytest_cache/` | Test cache |\n"
            "| `*.egg-info/` | Package metadata |"
        ),
        "rust": (
            "| Pattern | Reason |\n"
            "|---------|--------|\n"
            "| `target/` | Build artifacts |\n"
            "| `Cargo.lock` | Lock file (for libs) |"
        ),
        "swift": (
            "| Pattern | Reason |\n"
            "|---------|--------|\n"
            "| `.build/` | Build artifacts |\n"
            "| `*.xcuserstate` | Xcode user state |\n"
            "| `DerivedData/` | Xcode derived data |"
        ),
        "go": (
            "| Pattern | Reason |\n"
            "|---------|--------|\n"
            "| `vendor/` | Vendored dependencies |\n"
            "| `*.test` | Test binaries |"
        ),
    }
    return tables.get(lang or "", "TODO: Fill .gitignore table for your tech stack")


def _derive_output_verification_gate(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    if lang in ("javascript", "typescript"):
        return (
            "1. `npm run build` passes (build gate)\n"
            "2. `npm test` passes (test gate)\n"
            "3. No TypeScript errors (`tsc --noEmit`)"
        )
    if lang == "python":
        return (
            "1. `python3 -m pytest` passes\n"
            "2. `mypy .` passes (type gate)\n"
            "3. `ruff check .` passes (lint gate)"
        )
    if lang == "rust":
        return (
            "1. `cargo build` passes\n"
            "2. `cargo test` passes\n"
            "3. `cargo clippy` passes"
        )
    return "Not applicable"


def _derive_build_test_instructions(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    return BUILD_COMMANDS_BY_LANG.get(lang or "", "TODO: Add build and test instructions")


def _derive_code_standards(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    return TECH_STANDARDS_BY_LANG.get(lang or "", "TODO: Define code standards")


def _derive_tech_standards(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    return TECH_STANDARDS_BY_LANG.get(lang or "", "TODO: Define tech standards")


def _derive_tech_standards_brief(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    full = _derive_tech_standards(specs, tech, **kwargs)
    lines = [ln for ln in full.splitlines() if ln.strip()][:4]
    return "\n".join(lines) if lines else "TODO: Define brief tech standards"


def _derive_build_command(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    return BUILD_COMMANDS_BY_LANG.get(lang or "", "bash db_queries.sh health")


def _derive_test_command(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    return TEST_COMMANDS_BY_LANG.get(lang or "", "bash db_queries.sh health")


def _derive_lint_command(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language
    return LINT_COMMANDS_BY_LANG.get(lang or "", "echo 'No linter configured'")


def _derive_sast_config(specs: SpecReader, tech: TechDetector, **kwargs: Any) -> str:
    """Derive SAST configuration based on detected tech stack."""
    lang = tech.primary_language
    sast_configs = {
        "javascript": "semgrep --config=p/nodejs --config=p/security",
        "python": "semgrep --config=p/python --config=p/security",
        "rust": "semgrep --config=p/rust --config=p/security",
        "swift": "semgrep --config=auto --severity=ERROR",
        "go": "semgrep --config=p/golang --config=p/security",
    }
    return sast_configs.get(lang or "", "semgrep --config=auto --severity=ERROR")


def _derive_skip_pattern_1(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language or ""
    return SKIP_PATTERNS_BY_TECH.get(lang, ("build/*", "dist/*"))[0]


def _derive_skip_pattern_2(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    lang = tech.primary_language or ""
    patterns = SKIP_PATTERNS_BY_TECH.get(lang, ("build/*", "dist/*"))
    return patterns[1] if len(patterns) > 1 else ""


def _derive_xcode_project_path(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    return tech.xcodeproj_path or ""


def _derive_xcode_scheme(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    xcodeproj = tech.xcodeproj_path
    if not xcodeproj:
        return ""
    return Path(xcodeproj).stem


def _derive_xcode_test_scheme(
    specs: SpecReader, tech: TechDetector, **kwargs: Any
) -> str:
    scheme = _derive_xcode_scheme(specs, tech, **kwargs)
    return f"{scheme}Tests" if scheme else ""


# Dispatch table: token_name -> derivation function
AUTO_DERIVATION_DISPATCH: dict[str, Any] = {
    "PROJECT_NORTH_STAR": _derive_project_north_star,
    "TECH_STACK": _derive_tech_stack,
    "FIRST_PHASE": _derive_first_phase,
    "MCP_SERVERS": lambda s, t, **kw: (
        "TODO: List MCP servers (check .claude/settings.json)"
    ),
    "GEMINI_MCP_TABLE": lambda s, t, **kw: "TODO: Fill Gemini MCP table",
    "VISUAL_VERIFICATION": _derive_visual_verification,
    "EXTRA_MANDATORY_SKILLS": lambda s, t, **kw: "None additional",
    "RECOMMENDED_SKILLS": lambda s, t, **kw: "None additional",
    "EXTRA_MODEL_DELEGATION": lambda s, t, **kw: "",
    "GITIGNORE_TABLE": _derive_gitignore_table,
    "OUTPUT_VERIFICATION_GATE": _derive_output_verification_gate,
    "TEAM_TOPOLOGY": lambda s, t, **kw: (
        "Agent Teams mode is INACTIVE. "
        "Activate in .claude/settings.json and restart."
    ),
    # User-provided (auto defaults used in non-interactive mode)
    "COMMIT_FORMAT": lambda s, t, **kw: (
        "type(scope): description\n\nBody (optional)\n\nCo-Authored-By: ..."
    ),
    "BUILD_TEST_INSTRUCTIONS": _derive_build_test_instructions,
    "CODE_STANDARDS": _derive_code_standards,
    "PROJECT_STOP_RULES": lambda s, t, **kw: (
        "None beyond universal (see CLAUDE.md §10)"
    ),
    # Script-specific
    "TECH_STANDARDS": _derive_tech_standards,
    "TECH_STANDARDS_BRIEF": _derive_tech_standards_brief,
    "BUILD_COMMAND": _derive_build_command,
    "TEST_COMMAND": _derive_test_command,
    "LINT_COMMAND": _derive_lint_command,
    "SAST_CONFIG": _derive_sast_config,
    "LESSON_LOG_COMMAND": lambda s, t, **kw: "bash db_queries.sh log-lesson",
    "AGENT_NAMES": lambda s, t, **kw: "",
    # Framework
    "SKIP_PATTERN_1": _derive_skip_pattern_1,
    "SKIP_PATTERN_2": _derive_skip_pattern_2,
    # Xcode
    "XCODE_PROJECT_PATH": _derive_xcode_project_path,
    "XCODE_SCHEME": _derive_xcode_scheme,
    "XCODE_TEST_SCHEME": _derive_xcode_test_scheme,
}

# Interactive questions for user-provided tokens
USER_QUESTIONS: dict[str, str] = {
    "COMMIT_FORMAT": "What commit message format does your team use?",
    "BUILD_TEST_INSTRUCTIONS": "How do you build and test locally?",
    "CODE_STANDARDS": "What code quality tools do you use?",
    "PROJECT_STOP_RULES": "Any project-specific STOP rules beyond universal rules?",
}


# ---------------------------------------------------------------------------
# Sed token derivation
# ---------------------------------------------------------------------------

def derive_sed_tokens(
    project_name: str,
    project_path: str,
    db_name: str | None = None,
) -> dict[str, str]:
    """Derive all 12 sed tokens from project metadata."""
    upper = project_name.upper().replace(" ", "_").replace("-", "_")
    if db_name is None:
        slug = project_name.lower().replace(" ", "_").replace("-", "_")
        db_name = f"{slug}.db"
    db_stem = db_name[:-3] if db_name.endswith(".db") else db_name
    return {
        "PROJECT_NAME": project_name,
        "PROJECT_PATH": project_path,
        "PROJECT_DB": db_name,
        "LESSONS_FILE": f"LESSONS_{upper}.md",
        "RULES_FILE": f"{upper}_RULES.md",
        "MEMORY_FILE": f"{upper}_PROJECT_MEMORY.md",
        "PROJECT_MEMORY_FILE": f"{upper}_PROJECT_MEMORY.md",
        "PROJECT_DB_NAME": db_stem,
        "PROJECT_RULES_FILE": f"{upper}_RULES.md",
        "PROJECT_NAME_UPPER": upper,
        "PERMISSION_ALLOW": "",
        "LOCAL_PERMISSIONS": "",
    }


# ---------------------------------------------------------------------------
# Script token derivation
# ---------------------------------------------------------------------------

def generate_case_ordinals(phases: list[str]) -> str:
    """Generate bash case arms: 'P1-FOO') echo 1;;"""
    return " ".join(f"'{p}') echo {i + 1};;" for i, p in enumerate(phases))


def generate_case_sql(phases: list[str]) -> str:
    """Generate SQL CASE arms: WHEN 'P1-FOO' THEN 1"""
    return " ".join(f"WHEN '{p}' THEN {i + 1}" for i, p in enumerate(phases))


def generate_in_sql(phases: list[str]) -> str:
    """Generate SQL IN list: 'P1-FOO','P2-BAR'"""
    return ",".join(f"'{p}'" for p in phases)


def derive_script_tokens(
    lifecycle: str,
    project_name: str,
    tech: TechDetector,
    specs: SpecReader,
    **kwargs: Any,
) -> dict[str, str]:
    """Derive script-specific tokens from lifecycle + tech detection."""
    if lifecycle == "full":
        phases_str = (
            "P1-ENVISION P2-RESEARCH P3-DECIDE P4-SPECIFY "
            "P5-PLAN P6-BUILD P7-VALIDATE P8-SHIP P9-EVOLVE"
        )
    else:
        phases_str = "P1-PLAN P2-BUILD P3-SHIP"

    phase_list = phases_str.split()
    slug = project_name.lower().replace(" ", "_").replace("-", "_")

    return {
        "PHASES": phases_str,
        "PROJECT_PHASES": phases_str,
        "PHASE_CASE_ORDINALS": generate_case_ordinals(phase_list),
        "PHASE_CASE_SQL": generate_case_sql(phase_list),
        "PHASE_IN_SQL": generate_in_sql(phase_list),
        "OWN_DB_PATTERNS": rf"{slug}\.db",
        "AGENT_NAMES": "",
        "TECH_STANDARDS": _derive_tech_standards(specs, tech, **kwargs),
        "TECH_STANDARDS_BRIEF": _derive_tech_standards_brief(specs, tech, **kwargs),
        "LESSON_LOG_COMMAND": "bash db_queries.sh log-lesson",
        "BUILD_COMMAND": _derive_build_command(specs, tech, **kwargs),
        "TEST_COMMAND": _derive_test_command(specs, tech, **kwargs),
        "LINT_COMMAND": _derive_lint_command(specs, tech, **kwargs),
        "XCODE_PROJECT_PATH": _derive_xcode_project_path(specs, tech, **kwargs),
        "XCODE_SCHEME": _derive_xcode_scheme(specs, tech, **kwargs),
        "XCODE_TEST_SCHEME": _derive_xcode_test_scheme(specs, tech, **kwargs),
    }


def derive_framework_tokens(tech: TechDetector) -> dict[str, str]:
    """Derive skip patterns for coherence_check based on tech stack."""
    lang = tech.primary_language or ""
    patterns = SKIP_PATTERNS_BY_TECH.get(lang, ("build/*", "dist/*"))
    return {
        "SKIP_PATTERN_1": patterns[0],
        "SKIP_PATTERN_2": patterns[1] if len(patterns) > 1 else "",
    }


def safe_derive(
    token_name: str,
    specs: SpecReader,
    tech: TechDetector,
    **kwargs: Any,
) -> str:
    """Derive a token value safely, returning 'TODO: Fill TOKEN' on error."""
    try:
        fn = AUTO_DERIVATION_DISPATCH.get(token_name)
        if fn is not None:
            value = fn(specs, tech, **kwargs)
            if value is not None:
                return value
        token_def = REGISTRY.get(token_name)
        if token_def and token_def.default is not None:
            return token_def.default
        return f"TODO: Fill {token_name}"
    except Exception as exc:
        return f"TODO: Fill {token_name} (error: {exc})"


# ---------------------------------------------------------------------------
# Value builder
# ---------------------------------------------------------------------------

def build_values(
    project_name: str,
    project_path: str,
    specs: SpecReader,
    tech: TechDetector,
    lifecycle: str,
    db_path: str | None,
    interactive: bool,
    overrides: dict[str, str],
    verbose: bool = False,
) -> dict[str, str]:
    """Build the complete token values dict from all sources."""
    values: dict[str, str] = {}

    # 1. Sed tokens (always deterministic from project name/path)
    db_name: str | None = None
    if db_path:
        db_name = Path(db_path).name
    sed_tokens = derive_sed_tokens(project_name, project_path, db_name)
    values.update(sed_tokens)

    # 2. Script-specific tokens (lifecycle + tech)
    script_tokens = derive_script_tokens(
        lifecycle, project_name, tech, specs, db_path=db_path
    )
    values.update(script_tokens)

    # 3. Framework tokens (tech-stack skip patterns)
    framework_tokens = derive_framework_tokens(tech)
    values.update(framework_tokens)

    # 4. Auto-derivable + user-provided tokens (fill any gaps)
    for name in REGISTRY:
        if name not in values:
            values[name] = safe_derive(
                name, specs, tech, db_path=db_path, lifecycle=lifecycle
            )

    # 5. Interactive prompts for user-provided tokens
    if interactive and sys.stdin.isatty():
        for token_name, question in USER_QUESTIONS.items():
            if token_name in overrides:
                continue
            current = values.get(token_name, "")
            try:
                response = input(f"  {question} [{current}]: ").strip()
                if response:
                    values[token_name] = response
            except (EOFError, KeyboardInterrupt):
                pass  # keep auto-derived default

    # 6. Apply CLI overrides (highest priority)
    values.update(overrides)

    if verbose:
        for name in sorted(values):
            val = values[name]
            preview = val[:60].replace("\n", "\\n") if val else "(empty)"
            print(f"  TOKEN {name}: {preview}", file=sys.stderr)

    return values
