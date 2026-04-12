"""fp_replacer.py — Placeholder substitution engine for fill_placeholders.

Contains PlaceholderEngine (applies re.sub to files) and ReportGenerator
(builds the JSON report from engine state).

Stdlib only: re, pathlib, typing
Python 3.10+
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fp_registry import Replacement, REGISTRY


# ---------------------------------------------------------------------------
# PlaceholderEngine
# ---------------------------------------------------------------------------

class PlaceholderEngine:
    """Applies placeholder replacements using re.sub across files."""

    # Match placeholder tokens: two-pct + NAME + two-pct, uppercase + underscores/digits
    # Lazy *? quantifier prevents matching across boundaries in adjacent tokens
    PLACEHOLDER_RE = re.compile(r"%%([A-Z][A-Z0-9_]*?)%%")

    def __init__(self, values: dict[str, str], dry_run: bool = False) -> None:
        self.values = values
        self.dry_run = dry_run
        self.report: list[Replacement] = []

    def apply(self, file_path: Path) -> int:
        """Apply all replacements to a single file. Returns count of replacements made."""
        try:
            content = file_path.read_text(errors="ignore")
        except OSError:
            return 0

        count = 0

        def replacer(match: re.Match) -> str:  # type: ignore[type-arg]
            nonlocal count
            token_name = match.group(1)
            if token_name in self.values:
                replacement = self.values[token_name]
                self.report.append(Replacement(
                    file=str(file_path),
                    token=token_name,
                    original=match.group(0),
                    replacement=replacement,
                    line=content[: match.start()].count("\n") + 1,
                ))
                count += 1
                return replacement
            # Unknown token — leave as-is, record as unresolved
            self.report.append(Replacement(
                file=str(file_path),
                token=token_name,
                original=match.group(0),
                replacement=None,
                line=content[: match.start()].count("\n") + 1,
            ))
            return match.group(0)

        new_content = self.PLACEHOLDER_RE.sub(replacer, content)

        if not self.dry_run and new_content != content:
            try:
                file_path.write_text(new_content)
            except OSError:
                pass

        return count

    def apply_all(
        self,
        directory: Path,
        extensions: tuple[str, ...] = (".md", ".sh", ".json", ".conf", ".py"),
    ) -> dict[str, int]:
        """Walk directory tree and apply to all matching files."""
        total = 0
        files_modified = 0

        for ext in extensions:
            for file_path in sorted(directory.rglob(f"*{ext}")):
                if ".git" in file_path.parts:
                    continue
                if file_path.name == "placeholder-registry.md":
                    continue
                if file_path.name == "fill_placeholders.py":
                    continue

                count = self.apply(file_path)
                if count > 0:
                    files_modified += 1
                    total += count

        return {"total_replacements": total, "files_modified": files_modified}


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Builds the JSON report from engine state."""

    def __init__(
        self,
        engine: PlaceholderEngine,
        project_name: str,
        project_path: str,
        dry_run: bool,
        stats: dict[str, int],
    ) -> None:
        self.engine = engine
        self.project_name = project_name
        self.project_path = project_path
        self.dry_run = dry_run
        self.stats = stats

    def build(self) -> dict[str, Any]:
        """Build and return the JSON report dict."""
        # Aggregate per-token occurrence counts and seen values
        token_occurrences: dict[str, int] = {}
        token_values: dict[str, str] = {}
        unresolved_files: dict[str, list[str]] = {}

        for rep in self.engine.report:
            if rep.replacement is not None:
                token_occurrences[rep.token] = (
                    token_occurrences.get(rep.token, 0) + 1
                )
                token_values[rep.token] = rep.replacement
            else:
                unresolved_files.setdefault(rep.token, [])
                if rep.file not in unresolved_files[rep.token]:
                    unresolved_files[rep.token].append(rep.file)

        # Build tokens section
        tokens_section: dict[str, Any] = {}
        resolved_count = 0
        unresolved_count = 0

        for name, token_def in REGISTRY.items():
            if name in token_values:
                tokens_section[name] = {
                    "category": token_def.category,
                    "value": token_values[name],
                    "source": "derived",
                    "occurrences": token_occurrences.get(name, 0),
                }
                resolved_count += 1
            elif name in self.engine.values:
                # Token has a value but zero occurrences in files
                tokens_section[name] = {
                    "category": token_def.category,
                    "value": self.engine.values[name],
                    "source": "derived",
                    "occurrences": 0,
                }
                resolved_count += 1
            else:
                tokens_section[name] = {
                    "category": token_def.category,
                    "value": None,
                    "source": None,
                    "occurrences": 0,
                    "reason": f"No value derived for {name}",
                }
                unresolved_count += 1

        # Unknown tokens seen in files (not in REGISTRY)
        unresolved_section = [
            {
                "token": token,
                "files": files,
                "reason": f"Token %%{token}%% not in registry — left as-is",
            }
            for token, files in unresolved_files.items()
            if token not in self.engine.values
        ]

        replacements_list = [
            {
                "file": rep.file,
                "token": rep.token,
                "line": rep.line,
                "original": rep.original,
                "replacement": rep.replacement,
            }
            for rep in self.engine.report
            if rep.replacement is not None
        ]

        return {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "dry_run": self.dry_run,
            "summary": {
                "total_tokens": len(REGISTRY),
                "resolved": resolved_count,
                "unresolved": unresolved_count,
                "files_modified": self.stats.get("files_modified", 0),
                "total_replacements": self.stats.get("total_replacements", 0),
            },
            "tokens": tokens_section,
            "replacements": replacements_list,
            "unresolved": unresolved_section,
        }
