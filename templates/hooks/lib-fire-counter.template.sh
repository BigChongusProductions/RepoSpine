#!/bin/bash
# Sourceable fire-rate logger for hooks.
# Each sourcing hook logs one JSONL line to .claude/hooks/.fire-counts.jsonl.
# Format: {"ts":epoch,"hook":"name.sh","session":"id-or-unknown"}
#
# Usage (put as FIRST executable line in a hook):
#   source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"
#
# Silent + append-only + best-effort: any failure is swallowed so we never
# break the actual hook logic. Analyze with .claude/hooks/show-fire-rates.sh.

{
    # Only write if sourced from a real hook script (BASH_SOURCE[1] set AND
    # points into a directory named 'hooks'). Prevents stray logs when the
    # helper is sourced from ad-hoc bash invocations.
    if [ -n "${BASH_SOURCE[1]:-}" ]; then
        _counter_dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
        if [ "$(basename "$_counter_dir")" = "hooks" ]; then
            _counter_log="$_counter_dir/.fire-counts.jsonl"
            _counter_hook="$(basename "${BASH_SOURCE[1]}")"
            _counter_session="${CLAUDE_SESSION_ID:-${CMUX_SURFACE_ID:-unknown}}"
            _counter_ts=$(date +%s)
            printf '{"ts":%s,"hook":"%s","session":"%s"}\n' \
                "$_counter_ts" "$_counter_hook" "$_counter_session" \
                >> "$_counter_log" 2>/dev/null || true
        fi
    fi
} 2>/dev/null || true
