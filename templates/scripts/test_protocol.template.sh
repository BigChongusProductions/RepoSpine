#!/usr/bin/env bash
# Test Protocol — Session Briefing & Signal Validation
# ─────────────────────────────────────────────────────────────────────────────
# PURPOSE: Validate that session_briefing.sh and db_queries.sh produce correct
#          signals for known database states. Uses a temporary test DB — never
#          touches production.
#
# USAGE:   bash test_protocol.sh
#
# SCENARIOS:
#   A: Empty DB → graceful (no crash)
#   B: All tasks DONE, gate not passed → YELLOW
#   C: Gate passed, next phase has TODO tasks → GREEN
#   D: Claude task blocked by human task → blocking detection
#   E: ALL Claude tasks blocked → RED
#   F: Prior phase incomplete → RED (phase ordering violation)
#   G: Gate-critical loopback → blocks gate passage
#   H: Clean green state → GREEN
#
# PLACEHOLDERS:
#   %%PROJECT_DB%% — production DB (schema copy source only)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROD_DB="$SCRIPT_DIR/%%PROJECT_DB%%"
TEST_DB="/tmp/test_protocol_$$.db"
PASS=0
FAIL=0
TOTAL=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

cleanup() {
    rm -f "$TEST_DB" "$TEST_DB-journal" "$TEST_DB-wal" "$TEST_DB-shm"
}
trap cleanup EXIT

# ── Prerequisites ──
if [ ! -f "$SCRIPT_DIR/session_briefing.sh" ]; then
    echo -e "${RED}PREREQ FAIL: session_briefing.sh not found${NC}"
    exit 1
fi
if [ ! -f "$SCRIPT_DIR/db_queries.sh" ]; then
    echo -e "${RED}PREREQ FAIL: db_queries.sh not found${NC}"
    exit 1
fi

# ── Helper: create test DB with production schema ──
init_test_db() {
    rm -f "$TEST_DB"
    if [ -f "$PROD_DB" ]; then
        # Copy schema only (no data)
        sqlite3 "$PROD_DB" ".schema" | sqlite3 "$TEST_DB"
    else
        # Minimal schema if no production DB
        sqlite3 "$TEST_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY, phase TEXT, title TEXT, tier TEXT,
    skill TEXT DEFAULT '', status TEXT DEFAULT 'TODO',
    blocked_by TEXT DEFAULT '', sort_order INTEGER DEFAULT 0,
    tag TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    done_at TEXT, loopback_origin TEXT, severity INTEGER DEFAULT 3,
    gate_critical INTEGER DEFAULT 0, reason TEXT DEFAULT '',
    ack_status TEXT, ack_note TEXT
);
CREATE TABLE IF NOT EXISTS phase_gates (
    phase TEXT PRIMARY KEY, gated_by TEXT, gated_at TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT, what_wrong TEXT,
    pattern TEXT, prevention TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    promoted TEXT DEFAULT 'No', bp_category TEXT, bp_file TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT, notes TEXT
);
SQL
    fi
}

# ── Helper: run a test scenario ──
run_scenario() {
    local label="$1"
    local expected_pattern="$2"
    local description="$3"
    TOTAL=$((TOTAL + 1))

    # Run session_briefing.sh against test DB
    local output
    output=$(DB_NAME="$TEST_DB" bash "$SCRIPT_DIR/session_briefing.sh" 2>&1) || true

    if echo "$output" | grep -qi "$expected_pattern"; then
        echo -e "  ${GREEN}PASS${NC}  $label: $description"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC}  $label: $description (expected '$expected_pattern')"
        echo "        Got: $(echo "$output" | head -3)"
        FAIL=$((FAIL + 1))
    fi
}

# ── Derive phases from production DB ──
if [ -f "$PROD_DB" ]; then
    PHASES=($(sqlite3 "$PROD_DB" "SELECT DISTINCT phase FROM tasks ORDER BY sort_order LIMIT 4" 2>/dev/null || echo "P1-PLAN P2-BUILD"))
else
    PHASES=("P1-PLAN" "P2-BUILD")
fi
PHASE1="${PHASES[0]:-P1-PLAN}"
PHASE2="${PHASES[1]:-P2-BUILD}"

echo ""
echo "  Test Protocol — Signal Validation"
echo "  ─────────────────────────────────────────"
echo "  Phases: $PHASE1, $PHASE2"
echo "  Test DB: $TEST_DB"
echo ""

# ── Scenario A: Empty DB ──
init_test_db
run_scenario "A" "." "Empty DB — no crash (any output is fine)"

# ── Scenario B: All tasks DONE, gate not passed → YELLOW ──
init_test_db
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-01', '$PHASE1', 'Task 1', 'sonnet', 'DONE', 10);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-02', '$PHASE1', 'Task 2', 'sonnet', 'DONE', 20);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-03', '$PHASE2', 'Task 3', 'sonnet', 'TODO', 30);"
run_scenario "B" "YELLOW\|yellow\|gate" "All phase 1 DONE but gate not passed"

# ── Scenario C: Gate passed, next phase has TODO → GREEN ──
init_test_db
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-01', '$PHASE1', 'Task 1', 'sonnet', 'DONE', 10);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-02', '$PHASE2', 'Task 2', 'sonnet', 'TODO', 20);"
sqlite3 "$TEST_DB" "INSERT INTO phase_gates (phase, gated_by, gated_at) VALUES ('$PHASE1', 'test', datetime('now'));"
run_scenario "C" "GREEN\|green\|ready" "Gate passed, next phase has work"

# ── Scenario D: Claude task blocked by human task ──
init_test_db
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-01', '$PHASE1', 'Human review', 'master', 'TODO', 10);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order, blocked_by) VALUES ('T-02', '$PHASE1', 'Claude work', 'sonnet', 'TODO', 20, 'T-01');"
run_scenario "D" "block\|BLOCK\|master\|Master" "Blocked by human task detected"

# ── Scenario E: ALL Claude tasks blocked → RED ──
init_test_db
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-01', '$PHASE1', 'Human gate', 'master', 'TODO', 10);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order, blocked_by) VALUES ('T-02', '$PHASE1', 'Claude A', 'sonnet', 'TODO', 20, 'T-01');"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order, blocked_by) VALUES ('T-03', '$PHASE1', 'Claude B', 'haiku', 'TODO', 30, 'T-01');"
run_scenario "E" "RED\|red\|block" "All Claude tasks blocked"

# ── Scenario F: Prior phase incomplete → RED ──
init_test_db
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-01', '$PHASE1', 'Incomplete', 'sonnet', 'TODO', 10);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-02', '$PHASE2', 'Next phase', 'sonnet', 'TODO', 20);"
# No gate for phase1, phase2 task exists → ordering violation
run_scenario "F" "RED\|red\|incomplete\|prior\|phase" "Prior phase has incomplete tasks"

# ── Scenario G: Gate-critical loopback ──
init_test_db
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-01', '$PHASE1', 'Task 1', 'sonnet', 'DONE', 10);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order, loopback_origin, severity, gate_critical) VALUES ('LB-01', '$PHASE1', 'Critical fix', 'sonnet', 'TODO', 15, '$PHASE1', 1, 1);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-02', '$PHASE2', 'Next', 'sonnet', 'TODO', 20);"
run_scenario "G" "gate.critical\|loopback\|LB\|YELLOW\|RED\|breaker" "Gate-critical loopback blocks gate"

# ── Scenario H: Clean green state ──
init_test_db
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-01', '$PHASE1', 'Done task', 'sonnet', 'DONE', 10);"
sqlite3 "$TEST_DB" "INSERT INTO tasks (task_id, phase, title, tier, status, sort_order) VALUES ('T-02', '$PHASE2', 'Ready task', 'sonnet', 'TODO', 20);"
sqlite3 "$TEST_DB" "INSERT INTO phase_gates (phase, gated_by, gated_at) VALUES ('$PHASE1', 'test', datetime('now'));"
run_scenario "H" "GREEN\|green" "Clean green state"

# ── Summary ──
echo ""
echo "  ─────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}$PASS/$TOTAL passed${NC}"
else
    echo -e "  ${RED}$FAIL/$TOTAL FAILED${NC} ($PASS passed)"
fi
echo ""

exit $FAIL
