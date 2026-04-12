#!/usr/bin/env python3
"""fill_placeholders.py — CLI entry point for placeholder token replacement.

Usage:
    python3 fill_placeholders.py PROJECT_PATH --project-name NAME [OPTIONS]

Reads a bootstrapped project directory and replaces all placeholder tokens
using re.sub with a callable replacer. Derives values from project name/path
(sed tokens), tech detection, spec files, DB queries, and lifecycle mode.

Token pattern: two percent signs, uppercase name, two percent signs.

Implementation is split across three modules:
  fp_registry.py  — TokenDef/Replacement dataclasses + REGISTRY (49 tokens)
  fp_engine.py    — SpecReader, TechDetector, derivation functions, build_values()
  fp_replacer.py  — PlaceholderEngine, ReportGenerator

Stdlib only: argparse, json, pathlib, sys  (+ stdlib used by sub-modules)
Python 3.10+
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Public API re-exports (backward compatibility for test imports)
# ---------------------------------------------------------------------------

from fp_registry import TokenDef, Replacement, REGISTRY
from fp_engine import (
    SpecReader,
    TechDetector,
    build_values,
    derive_sed_tokens,
    derive_script_tokens,
    derive_framework_tokens,
    generate_case_ordinals,
    generate_case_sql,
    generate_in_sql,
)
from fp_replacer import PlaceholderEngine, ReportGenerator


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code (0 = all resolved, 1 = unresolved)."""
    parser = argparse.ArgumentParser(
        description="Replace %%PLACEHOLDER%% tokens in bootstrapped project files",
        epilog=(
            "Reads specs for auto-derivation. "
            "Use --dry-run to preview without modifying files."
        ),
    )

    parser.add_argument(
        "project_path",
        help="Path to the bootstrapped project directory",
    )
    parser.add_argument(
        "--project-name",
        required=True,
        help="Project display name (e.g., 'My Project')",
    )
    parser.add_argument(
        "--specs-dir",
        help="Path to specs/ directory (default: <project_path>/specs)",
    )
    parser.add_argument(
        "--db-path",
        help="Path to SQLite DB (default: auto-detect in project)",
    )
    parser.add_argument(
        "--lifecycle",
        choices=["full", "quick"],
        default="full",
        help="Lifecycle mode for phase derivation (default: full)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use defaults for user-provided tokens (no prompts)",
    )
    parser.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("TOKEN", "VALUE"),
        help="Override a token value: --set COMMIT_FORMAT 'type: desc'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be replaced without modifying files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON report to stdout",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print each replacement as it happens",
    )

    args = parser.parse_args(argv)

    project_path = str(Path(args.project_path).resolve())
    project_name = args.project_name

    if not Path(project_path).is_dir():
        print(
            f"Error: project_path '{project_path}' is not a directory",
            file=sys.stderr,
        )
        return 2

    overrides: dict[str, str] = {}
    if args.set:
        for token, value in args.set:
            overrides[token] = value

    specs = SpecReader(specs_dir=args.specs_dir, project_path=project_path)
    tech = TechDetector(project_path=project_path)

    if not specs.available_specs() and args.verbose:
        print(
            "Warning: No spec files found — auto-derivable tokens will use defaults",
            file=sys.stderr,
        )

    values = build_values(
        project_name=project_name,
        project_path=project_path,
        specs=specs,
        tech=tech,
        lifecycle=args.lifecycle,
        db_path=args.db_path,
        interactive=not args.non_interactive,
        overrides=overrides,
        verbose=args.verbose,
    )

    engine = PlaceholderEngine(values=values, dry_run=args.dry_run)
    stats = engine.apply_all(Path(project_path))

    if args.verbose and not args.json:
        for rep in engine.report:
            if rep.replacement is not None:
                preview = rep.replacement[:40].replace("\n", "\\n")
                print(
                    f"  {Path(rep.file).name}:{rep.line} "
                    f"%%{rep.token}%% -> {preview}",
                    file=sys.stderr,
                )

    report = ReportGenerator(
        engine=engine,
        project_name=project_name,
        project_path=project_path,
        dry_run=args.dry_run,
        stats=stats,
    ).build()

    if args.json:
        print(json.dumps(report, indent=2))
    elif args.dry_run:
        print(
            f"Dry run: would make {stats['total_replacements']} replacements "
            f"in {stats['files_modified']} files",
            file=sys.stderr,
        )
    else:
        print(
            f"Done: {stats['total_replacements']} replacements "
            f"in {stats['files_modified']} files",
            file=sys.stderr,
        )

    has_unresolved = any(rep.replacement is None for rep in engine.report)
    return 1 if has_unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
