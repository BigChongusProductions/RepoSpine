#!/bin/bash
# test-gate-b.sh — Gate B verification: end-of-turn, session-start, pre-edit.
#
# Covers plan verification items 1, 2, 3, 4, 8, 10, 13, 14.
# Test 14 (perf baseline) logs timing but doesn't hard-fail — we capture
# the number for trend tracking.
#
# Runs each test in isolation with a fresh temp project; harness substitutes
# %%PROJECT_DB%% so the template-as-shipped is exercised.
#
# Run: bash templates/hooks/tests/test-gate-b.sh
# Exit 0 = all pass, non-zero = at least one failure.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATES_ROOT="$(cd "$HOOKS_DIR/../.." && pwd)"

PASS=0
FAIL=0
FAILED=()

# ── Harness helpers ────────────────────────────────────────────────────────

# Materialize a fresh project dir with hook templates copied + placeholders
# substituted. Populates:
#   $PROJ               — absolute path to project root
#   $PROJ/db_queries.sh — stub
#   $PROJ/.claude/hooks/ — hooks with placeholders filled
new_project() {
    local db_name="${1:-test.db}"
    PROJ=$(mktemp -d)
    mkdir -p "$PROJ/.claude/hooks"
    mkdir -p "$PROJ/scripts"

    # Copy libs (they have no placeholders)
    cp "$HOOKS_DIR/lib-fire-counter.template.sh" "$PROJ/.claude/hooks/lib-fire-counter.sh"
    cp "$HOOKS_DIR/lib-scope-counter.template.sh" "$PROJ/.claude/hooks/lib-scope-counter.sh"

    # Copy hook templates with placeholder substitution
    for tmpl in end-of-turn-check pre-edit-check session-start-check; do
        sed "s|%%PROJECT_DB%%|${db_name}|g" \
            "$HOOKS_DIR/${tmpl}.template.sh" \
            > "$PROJ/.claude/hooks/${tmpl}.sh"
        chmod +x "$PROJ/.claude/hooks/${tmpl}.sh"
    done

    # Empty DB file so session-start doesn't bail on db-missing
    touch "$PROJ/$db_name"

    # Minimal db_queries.sh stub — supports `task <id>` queries
    cat > "$PROJ/db_queries.sh" <<'STUB'
#!/bin/bash
# Stub db_queries.sh for tests — reads task status from .task_statuses.
CMD="$1"; shift
case "$CMD" in
    task)
        TID="$1"
        FILE="${PROJECT_DB_STATUSES:-$(dirname "$0")/.task_statuses}"
        if [ -f "$FILE" ]; then
            grep "^${TID}=" "$FILE" | head -1 | sed 's/.*=/Status: /'
        fi
        ;;
    *) : ;;
esac
STUB
    chmod +x "$PROJ/db_queries.sh"
    echo "$PROJ"
}

cleanup_project() {
    [ -n "${PROJ:-}" ] && rm -rf "$PROJ"
    unset PROJ
}

# Fire a hook with a JSON payload on stdin. Captures stdout.
fire_hook() {
    local hook="$1" payload="$2"
    echo "$payload" | bash "$PROJ/.claude/hooks/${hook}.sh"
}

record() {
    local name="$1" ok="$2"
    if [ "$ok" = "1" ]; then
        PASS=$((PASS + 1))
        echo "  ✓ $name"
    else
        FAIL=$((FAIL + 1))
        FAILED+=("$name")
        echo "  ✗ $name"
    fi
}

# ── Test 1: fire-counts + show-fire-rates smoke ────────────────────────────
test_01_fire_counts() {
    new_project >/dev/null
    local payload='{"tool_name":"Edit","cwd":"'"$PROJ"'","tool_input":{"file_path":"'"$PROJ/a.ts"'","old_string":"x","new_string":"y"}}'
    fire_hook pre-edit-check "$payload" >/dev/null 2>&1
    local ok=1
    [ -f "$PROJ/.claude/hooks/.fire-counts.jsonl" ] || ok=0
    [ -s "$PROJ/.claude/hooks/.fire-counts.jsonl" ] || ok=0
    local hook_field
    hook_field=$(head -1 "$PROJ/.claude/hooks/.fire-counts.jsonl" 2>/dev/null | jq -r '.hook' 2>/dev/null)
    [ "$hook_field" = "pre-edit-check.sh" ] || ok=0
    record "01 fire-counts populated by pre-edit-check" "$ok"
    cleanup_project
}

# ── Test 2: scope advisory dedupes retries + fires once ────────────────────
test_02_scope_dedup() {
    new_project >/dev/null
    local payload_tmpl
    payload_tmpl='{"tool_name":"Edit","cwd":"'"$PROJ"'","tool_input":{"file_path":"__F__","old_string":"OLD","new_string":"NEW"}}'

    # Fire same (file, old) 5 times — should dedupe to ONE record.
    for _ in 1 2 3 4 5; do
        fire_hook pre-edit-check "${payload_tmpl/__F__/$PROJ/x.ts}" >/dev/null 2>&1
    done

    local records
    records=$(jq '[.records[] | select(.file == "'"$PROJ/x.ts"'")] | length' \
        "$PROJ/.claude/hooks/.delegation_scope.json" 2>/dev/null)

    local ok=1
    [ "$records" = "1" ] || { ok=0; echo "    expected 1 dedup'd record, got $records"; }
    record "02 scope dedupe: 5 retries → 1 record" "$ok"
    cleanup_project
}

# ── Test 3: end-of-turn BROKEN + WONTFIX ──────────────────────────────────
test_03_endofturn_verdicts() {
    new_project >/dev/null

    # Sub-case 3a: recent BROKEN health cache → DOGFOOD ALERT warning
    local now ts
    now=$(date +%s)
    ts=$((now - 60))    # 60s ago, within 600s freshness
    printf '%s|1|BROKEN\n' "$ts" > "$PROJ/.claude/hooks/.health_cache"

    local out ok=1
    out=$(fire_hook end-of-turn-check '{"cwd":"'"$PROJ"'"}' 2>&1)
    echo "$out" | grep -q 'DOGFOOD ALERT.*BROKEN' || { ok=0; echo "    missing DOGFOOD ALERT BROKEN in: $out"; }
    record "03a end-of-turn warns on recent BROKEN .health_cache" "$ok"

    # Sub-case 3b: task with WONTFIX status → no unclosed-task warning
    printf 'QK-777|%s|QK-777\n' "$now" > "$PROJ/.claude/hooks/.last_check_result"
    printf 'QK-777=WONTFIX\n' > "$PROJ/.task_statuses"
    rm -f "$PROJ/.claude/hooks/.health_cache"

    ok=1
    out=$(fire_hook end-of-turn-check '{"cwd":"'"$PROJ"'"}' 2>&1)
    if echo "$out" | grep -q 'was checked but still'; then
        ok=0
        echo "    WONTFIX task wrongly flagged as unclosed: $out"
    fi
    record "03b end-of-turn silent on WONTFIX task" "$ok"

    cleanup_project
}

# ── Test 8: legacy .health_cache bare-exit-code tolerance ──────────────────
test_08_legacy_health_cache() {
    new_project >/dev/null
    # Legacy format: just a bare exit code, no pipes, no timestamp.
    printf '1\n' > "$PROJ/.claude/hooks/.health_cache"

    local out ok=1
    out=$(fire_hook end-of-turn-check '{"cwd":"'"$PROJ"'"}' 2>&1)
    # Must emit the LEGACY marker — not silently misparse the bare int as a
    # timestamp and compute a bogus age.
    echo "$out" | grep -q 'LEGACY' || { ok=0; echo "    expected LEGACY marker: $out"; }
    record "08 legacy bare-exit-code .health_cache detected" "$ok"
    cleanup_project
}

# ── Test 13: placeholder regex-escape in session-start pgrep ──────────────
test_13_placeholder_escape() {
    new_project "my.project.db" >/dev/null

    # Inspect the materialized session-start-check.sh to ensure the pgrep
    # pattern would escape dots. Grep for an unescaped literal — if the
    # template didn't escape, we'd see the unescaped DB name next to pgrep.
    local ok=1
    if ! grep -q 'sed .*\\\\' "$PROJ/.claude/hooks/session-start-check.sh"; then
        ok=0
        echo "    regex-escape sed step not present in session-start-check.sh"
    fi

    # Exercise the escape logic with a controlled input.
    local raw='my.project.db'
    local escaped
    escaped=$(printf '%s' "$raw" | sed 's/[][\.*^$|(){}?+/]/\\&/g')
    # Expected: my\.project\.db
    if [ "$escaped" != 'my\.project\.db' ]; then
        ok=0
        echo "    escape logic produced '$escaped', expected 'my\\.project\\.db'"
    fi
    record "13 pgrep pattern regex-escapes dotted DB name" "$ok"
    cleanup_project
}

# ── Test 4 + 10: pgrep scope fix (negative + positive) ────────────────────
# 4: sqlite3 against a DIFFERENT DB must NOT inhibit our journal cleanup.
# 10: sqlite3 against OUR DB must inhibit it.
test_04_10_pgrep_scope() {
    new_project "our.project.db" >/dev/null

    # Seed a stale journal that session-start would clean if lock-free
    local stale_journal="$PROJ/our.project.db-wal"
    touch -t 202001010000 "$stale_journal"    # 2020 — definitely stale

    # Sub-case 4: start a harmless background process masquerading as
    # sqlite3 against a DIFFERENT DB. Use sleep-with-custom-name via bash.
    # The simplest reliable approach: spawn a bash subprocess whose command
    # line contains "sqlite3 /some/other/db.file" via exec -a.
    (exec -a "sqlite3 /tmp/totally-different.db" sleep 30) &
    local other_pid=$!
    sleep 0.3

    # Fire session-start — journal should be cleaned since the running
    # sqlite3-looking process doesn't match our DB.
    local payload='{"cwd":"'"$PROJ"'"}'
    fire_hook session-start-check "$payload" >/dev/null 2>&1
    local ok=1
    if [ -f "$stale_journal" ]; then
        ok=0
        echo "    journal NOT cleaned despite unrelated sqlite3 process"
    fi
    kill "$other_pid" 2>/dev/null || true
    wait "$other_pid" 2>/dev/null || true
    record "04 pgrep scoped: unrelated sqlite3 does not inhibit cleanup" "$ok"

    # Sub-case 10: now spawn an "sqlite3" process that IS touching our DB.
    # Recreate the stale journal so we can test again.
    touch -t 202001010000 "$stale_journal"
    (exec -a "sqlite3 $PROJ/our.project.db" sleep 30) &
    local our_pid=$!
    sleep 0.3

    fire_hook session-start-check "$payload" >/dev/null 2>&1
    ok=1
    if [ ! -f "$stale_journal" ]; then
        ok=0
        echo "    journal WAS cleaned despite active sqlite3 on our DB"
    fi
    kill "$our_pid" 2>/dev/null || true
    wait "$our_pid" 2>/dev/null || true
    record "10 pgrep positive: active sqlite3 on our DB inhibits cleanup" "$ok"

    cleanup_project
}

# ── Test 14: perf baseline for pre-edit-check ─────────────────────────────
test_14_perf_baseline() {
    new_project >/dev/null
    local payload='{"tool_name":"Edit","cwd":"'"$PROJ"'","tool_input":{"file_path":"'"$PROJ/a.ts"'","old_string":"x","new_string":"y"}}'

    # Warm up (jq cold-start, fs cache)
    fire_hook pre-edit-check "$payload" >/dev/null 2>&1

    # Measure 5 invocations
    local total=0 i
    for i in 1 2 3 4 5; do
        local t_start t_end
        t_start=$(python3 -c 'import time; print(int(time.time()*1000))')
        fire_hook pre-edit-check "$payload" >/dev/null 2>&1
        t_end=$(python3 -c 'import time; print(int(time.time()*1000))')
        total=$((total + t_end - t_start))
    done
    local avg=$((total / 5))
    echo "    pre-edit-check avg: ${avg}ms (5 runs)"

    local ok=1
    if [ "$avg" -gt 500 ]; then
        ok=0
        echo "    PERF REGRESSION: avg ${avg}ms > 500ms budget"
    fi
    record "14 pre-edit-check perf baseline (<500ms)" "$ok"
    cleanup_project
}

# ── Run all ────────────────────────────────────────────────────────────────

echo "=== Gate B test suite ==="
test_01_fire_counts
test_02_scope_dedup
test_03_endofturn_verdicts
test_08_legacy_health_cache
test_13_placeholder_escape
test_04_10_pgrep_scope
test_14_perf_baseline

echo ""
echo "=== Results: $PASS pass, $FAIL fail ==="
if [ $FAIL -gt 0 ]; then
    for f in "${FAILED[@]}"; do
        echo "  FAILED: $f"
    done
    exit 1
fi
exit 0
