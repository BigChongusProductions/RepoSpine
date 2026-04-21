#!/bin/bash
# test-scope-missing-deps.sh — fail-soft verification for lib-scope-counter.
# Gate A verification item #11. Ensures scope_record/scope_should_fire
# degrade to silent no-ops (no stderr noise, no nonzero exit that would
# propagate into the calling hook) when jq or sha1 tools are absent.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB="$HOOKS_DIR/lib-scope-counter.template.sh"
[ -f "$LIB" ] || LIB="$HOOKS_DIR/lib-scope-counter.sh"
if [ ! -f "$LIB" ]; then
    echo "FATAL: lib-scope-counter(.template).sh not found"
    exit 1
fi

FAIL_COUNT=0

run_missing_dep() {
    local label="$1" shim="$2"
    echo "=== Missing: $label ==="

    local tmp stubdir
    tmp=$(mktemp -d)
    stubdir="$tmp/stub"
    mkdir -p "$stubdir"

    # Create empty shim(s) named like the missing tool, so `command -v` finds
    # nothing. Wrong approach — instead we shadow them via a PATH with no
    # binaries for those names. So: construct a minimal PATH excluding any
    # dir that has $shim, then source the lib in that environment.

    # Simplest portable approach: build a PATH that lists only the stubdir.
    # bash still needs a few externals (mkdir, cat, printf), so copy those
    # stubs in if present.
    for t in bash cat printf mkdir rm mv mktemp awk date diff grep sleep \
             sha1sum shasum jq dirname basename; do
        if [ "$t" = "${shim%% *}" ]; then continue; fi
        local src
        src=$(command -v "$t" 2>/dev/null || true)
        [ -n "$src" ] && ln -sf "$src" "$stubdir/$t"
    done
    # For "jq and sha1 both" case, the shim string has two names space-separated.
    for bad in $shim; do
        rm -f "$stubdir/$bad"
    done

    export SCOPE_STATE_FILE="$tmp/scope.json"
    export SCOPE_HISTORY_FILE="$tmp/history.jsonl"

    # Run under restricted PATH. Capture stdout+stderr+rc.
    local out rc
    out=$(
        PATH="$stubdir" bash -c "
            source '$LIB'
            # Under missing deps, these must not crash, must exit 0, and must
            # produce no state file (no-op).
            scope_record 'a.ts' 'old' 'new' || echo 'record-rc-nonzero'
            scope_record_write 'b.ts' 'content' || echo 'write-rc-nonzero'
            scope_should_fire
            echo \"rc:\$?\"
        " 2>&1
    )
    rc=$?

    # Verdict checks:
    # 1. exit rc should be 0 (script completed)
    # 2. no 'record-rc-nonzero' / 'write-rc-nonzero' markers in output
    # 3. state file must not exist (or be empty) — lib no-op'd
    # 4. scope_should_fire prints 'lib_unavailable' and returns 1
    local ok=1
    if [ $rc -ne 0 ]; then
        echo "  FAIL: bash -c exit nonzero ($rc)"
        echo "    output: $out"
        ok=0
    fi
    if echo "$out" | grep -q 'record-rc-nonzero\|write-rc-nonzero'; then
        echo "  FAIL: scope_record/record_write returned nonzero"
        ok=0
    fi
    if [ -s "$SCOPE_STATE_FILE" ]; then
        echo "  FAIL: state file was written despite missing deps"
        ok=0
    fi
    if ! echo "$out" | grep -q 'lib_unavailable'; then
        echo "  FAIL: scope_should_fire did not emit 'lib_unavailable'"
        echo "    output: $out"
        ok=0
    fi

    if [ $ok -eq 1 ]; then
        echo "  PASS: fail-soft no-op confirmed"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    rm -rf "$tmp"
    unset SCOPE_STATE_FILE SCOPE_HISTORY_FILE
}

run_missing_dep "jq only"              "jq"
run_missing_dep "sha1sum + shasum"     "sha1sum shasum"
run_missing_dep "jq + sha1sum + shasum" "jq sha1sum shasum"

if [ $FAIL_COUNT -gt 0 ]; then
    echo ""
    echo "OVERALL: FAIL ($FAIL_COUNT case(s) failed)"
    exit 1
fi

echo ""
echo "OVERALL: PASS"
