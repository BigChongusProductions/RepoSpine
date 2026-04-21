#!/bin/bash
# test-gate-c.sh — Gate C verification for Block C (telemetry + new hooks).
#
# Covers:
#   C1 fire-counter is now sourced in the retrofit set
#   C2 correction-detector writes .correction_pending + .correction_debug on match
#   C3 session-end-safety removes .delegation_scope.json + closes stale .active-plan
#   C4 mark_plan_active + mark_plan_done round-trip
#
# Run: bash templates/hooks/tests/test-gate-c.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
FAILED=()

record() {
    if [ "$2" = "1" ]; then
        PASS=$((PASS + 1)); echo "  ✓ $1"
    else
        FAIL=$((FAIL + 1)); FAILED+=("$1"); echo "  ✗ $1"
    fi
}

new_project() {
    PROJ=$(mktemp -d)
    mkdir -p "$PROJ/.claude/hooks"
    cp "$HOOKS_DIR/lib-fire-counter.template.sh" "$PROJ/.claude/hooks/lib-fire-counter.sh"
    cp "$HOOKS_DIR/lib-scope-counter.template.sh" "$PROJ/.claude/hooks/lib-scope-counter.sh"
    for tmpl in correction-detector session-end-safety escalation-tracker subagent-delegation-check \
                mark_plan_active mark_plan_done; do
        sed "s|%%PROJECT_DB%%|test.db|g; s|%%LESSON_LOG_COMMAND%%|bash db_queries.sh log-lesson|g" \
            "$HOOKS_DIR/${tmpl}.template.sh" \
            > "$PROJ/.claude/hooks/${tmpl}.sh"
        chmod +x "$PROJ/.claude/hooks/${tmpl}.sh"
    done
}

cleanup_project() {
    [ -n "${PROJ:-}" ] && rm -rf "$PROJ"
    unset PROJ
}

# ── C1: fire-counter source appears in retrofit set ────────────────────────
test_c1_fire_counter_sourced() {
    local ok=1
    for hook in correction-detector escalation-tracker subagent-delegation-check session-end-safety; do
        if ! grep -q 'lib-fire-counter.sh' "$HOOKS_DIR/${hook}.template.sh"; then
            ok=0
            echo "    ${hook}.template.sh missing lib-fire-counter source"
        fi
    done
    record "C1 fire-counter sourced in all 4 retrofit hooks" "$ok"
}

# ── C2: correction-detector marker + debug log ─────────────────────────────
test_c2_correction_detector() {
    new_project
    local ok=1

    # Fire with a message containing a correction signal
    local payload='{"prompt":"no no, that is wrong, you broke it"}'
    echo "$payload" | bash "$PROJ/.claude/hooks/correction-detector.sh" >/dev/null 2>&1

    [ -f "$PROJ/.claude/hooks/.correction_pending" ] || { ok=0; echo "    .correction_pending not written"; }
    [ -f "$PROJ/.claude/hooks/.correction_debug" ]   || { ok=0; echo "    .correction_debug not written"; }

    # Fire 8 more times to test rotation (keeps last 5)
    for i in 1 2 3 4 5 6 7 8; do
        echo "$payload" | bash "$PROJ/.claude/hooks/correction-detector.sh" >/dev/null 2>&1
    done
    local lines
    lines=$(wc -l < "$PROJ/.claude/hooks/.correction_debug" 2>/dev/null | tr -d ' ')
    if [ "$lines" != "5" ]; then
        ok=0
        echo "    .correction_debug rotation broken: got $lines lines, expected 5"
    fi

    record "C2 correction-detector writes marker + rotates debug log" "$ok"
    cleanup_project
}

# ── C3: session-end-safety cleans scope + closes stale plan ────────────────
test_c3_session_end_cleanup() {
    new_project
    local ok=1

    # Seed state: scope file + STALE active-plan (5h old > 4h threshold)
    echo '{"records":[]}' > "$PROJ/.claude/hooks/.delegation_scope.json"
    local stale_ts=$(( $(date +%s) - 18000 ))   # 5h ago
    printf '%s\nold-plan\n' "$stale_ts" > "$PROJ/.claude/hooks/.active-plan"

    local payload='{"cwd":"'"$PROJ"'"}'
    echo "$payload" | bash "$PROJ/.claude/hooks/session-end-safety.sh" >/dev/null 2>&1

    if [ -f "$PROJ/.claude/hooks/.delegation_scope.json" ]; then
        ok=0; echo "    scope file NOT removed"
    fi
    if [ -f "$PROJ/.claude/hooks/.active-plan" ]; then
        ok=0; echo "    stale .active-plan NOT cleared"
    fi

    record "C3 session-end cleans scope + closes stale plan" "$ok"
    cleanup_project
}

# ── C3b: session-end PRESERVES a FRESH active-plan ────────────────────────
test_c3b_fresh_plan_preserved() {
    new_project
    local ok=1
    local fresh_ts=$(( $(date +%s) - 600 ))   # 10min ago, well within 4h
    printf '%s\nactive-plan\n' "$fresh_ts" > "$PROJ/.claude/hooks/.active-plan"

    echo '{"cwd":"'"$PROJ"'"}' | bash "$PROJ/.claude/hooks/session-end-safety.sh" >/dev/null 2>&1

    if [ ! -f "$PROJ/.claude/hooks/.active-plan" ]; then
        ok=0; echo "    fresh .active-plan was incorrectly cleared"
    fi

    record "C3b session-end preserves fresh .active-plan" "$ok"
    cleanup_project
}

# ── C4: mark_plan_active / mark_plan_done round-trip ──────────────────────
test_c4_plan_marker_roundtrip() {
    new_project
    local ok=1
    bash "$PROJ/.claude/hooks/mark_plan_active.sh" "demo-plan" "$PROJ" >/dev/null
    [ -f "$PROJ/.claude/hooks/.active-plan" ] || { ok=0; echo "    mark_plan_active did not create marker"; }

    local name
    name=$(sed -n '2p' "$PROJ/.claude/hooks/.active-plan" 2>/dev/null)
    [ "$name" = "demo-plan" ] || { ok=0; echo "    marker body wrong: '$name'"; }

    bash "$PROJ/.claude/hooks/mark_plan_done.sh" "$PROJ" >/dev/null
    if [ -f "$PROJ/.claude/hooks/.active-plan" ]; then
        ok=0; echo "    mark_plan_done did not remove marker"
    fi

    record "C4 plan marker active/done round-trip" "$ok"
    cleanup_project
}

# ── Run all ────────────────────────────────────────────────────────────────
echo "=== Gate C test suite ==="
test_c1_fire_counter_sourced
test_c2_correction_detector
test_c3_session_end_cleanup
test_c3b_fresh_plan_preserved
test_c4_plan_marker_roundtrip

echo ""
echo "=== Results: $PASS pass, $FAIL fail ==="
if [ $FAIL -gt 0 ]; then
    for f in "${FAILED[@]}"; do echo "  FAILED: $f"; done
    exit 1
fi
exit 0
