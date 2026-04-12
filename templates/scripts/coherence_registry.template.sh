#!/usr/bin/env bash
# Coherence Registry — deprecated pattern definitions
#
# This file is sourced by coherence_check.sh. It defines three parallel arrays:
#
#   DEPRECATED_PATTERNS  — exact string to grep for in markdown files
#   CANONICAL_LABELS     — what the correct replacement is (shown with --fix)
#   INTRODUCED_ON        — date the deprecation was introduced (for audit trail)
#
# All three arrays must stay in sync: entry N in each array describes the same rule.
#
# HOW TO ADD AN ENTRY:
#   When an architecture change makes an old term/filename/concept stale, add a
#   row here so the coherence check will catch prose docs that still use the old name.
#
#   DEPRECATED_PATTERNS+=("exact old string")
#   CANONICAL_LABELS+=("what to use instead, with context if helpful")
#   INTRODUCED_ON+=("Month DD YYYY")
#
# WHAT TO SKIP:
#   Do NOT add patterns that appear legitimately in the lessons file or in this
#   registry itself. Add those filenames to the SKIP_PATTERNS array in
#   coherence_check.sh instead.
#
# ─────────────────────────────────────────────────────────────────────────────

DEPRECATED_PATTERNS=()
CANONICAL_LABELS=()
INTRODUCED_ON=()

# ── Add entries below this line ───────────────────────────────────────────────

# Example entry — replace or remove before use:
# DEPRECATED_PATTERNS+=("old-feature-name")
# CANONICAL_LABELS+=("new-feature-name (renamed in vX.Y — see CHANGELOG)")
# INTRODUCED_ON+=("January 01 2026")
