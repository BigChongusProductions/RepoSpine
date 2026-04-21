#!/bin/bash
# test-scope-concurrent.sh — concurrent-write test for lib-scope-counter.
# Gate A verification item #9. Passes if final state has all 200 records
# with valid JSON after 200 parallel scope_record calls.
#
# Runs twice:
#   1. Native mode (whatever this host supports — flock or sentinel fallback)
#   2. Forced sentinel mode (FORCE_NO_FLOCK=1) to exercise the macOS path
#      even on Linux CI runners.
#
# Exit 0 = all passed, non-zero = at least one mode failed.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB="$HOOKS_DIR/lib-scope-counter.template.sh"

if [ ! -f "$LIB" ]; then
    # Allow running from the bootstrapped copy too.
    LIB="$HOOKS_DIR/lib-scope-counter.sh"
fi
if [ ! -f "$LIB" ]; then
    echo "FATAL: lib-scope-counter(.template).sh not found near $HOOKS_DIR"
    exit 1
fi

FAIL_COUNT=0

run_mode() {
    local label="$1" force_no_flock="$2"
    echo "=== Mode: $label ==="

    local tmp
    tmp=$(mktemp -d)
    export SCOPE_STATE_FILE="$tmp/scope.json"
    export SCOPE_HISTORY_FILE="$tmp/history.jsonl"

    (
        # shellcheck disable=SC1090
        source "$LIB"

        # Force sentinel path by overriding the lib's detection AFTER sourcing.
        # The lib checks _SCOPE_FLOCK_OK at call-time, not at source-time,
        # so an override here takes effect for every scope_* call below.
        if [ "$force_no_flock" = "1" ]; then
            _SCOPE_FLOCK_OK=false
        fi

        scope_reset "concurrent-test"

        # Fire 200 parallel scope_record calls (100 pairs of two files).
        for i in $(seq 1 100); do
            ( scope_record "file-a-$i.ts" "old$i" "new$i" ) &
            ( scope_record "file-b-$i.ts" "old$i" "new$i" ) &
        done
        wait

        # Validate JSON
        if ! jq empty "$SCOPE_STATE_FILE" >/dev/null 2>&1; then
            echo "  FAIL: state file is not valid JSON"
            exit 1
        fi

        # Count records
        local count
        count=$(jq '.records | length' "$SCOPE_STATE_FILE")
        if [ "$count" -ne 200 ]; then
            echo "  FAIL: expected 200 records, got $count"
            exit 1
        fi

        # Sanity — unique file count is 200 (100 file-a-* + 100 file-b-*)
        local files
        files=$(jq '[.records[].file] | unique | length' "$SCOPE_STATE_FILE")
        if [ "$files" -ne 200 ]; then
            echo "  FAIL: expected 200 unique files, got $files"
            exit 1
        fi

        echo "  PASS: 200 records, $files unique files, valid JSON"
    )
    local mode_rc=$?

    rm -rf "$tmp"
    unset SCOPE_STATE_FILE SCOPE_HISTORY_FILE

    if [ $mode_rc -ne 0 ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

run_mode "native (flock if available)" 0
run_mode "forced-sentinel fallback" 1

if [ $FAIL_COUNT -gt 0 ]; then
    echo ""
    echo "OVERALL: FAIL ($FAIL_COUNT mode(s) failed)"
    exit 1
fi

echo ""
echo "OVERALL: PASS"
