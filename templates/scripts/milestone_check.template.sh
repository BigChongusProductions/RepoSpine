#!/usr/bin/env bash
# Milestone Check — merge-readiness gate for dev → main
#
# ┌─────────────────────────────────────────────────────────────────┐
# │  TEMPLATE PLACEHOLDERS — replace before use                     │
# │                                                                 │
# │  %%PROJECT_DB%%        SQLite database filename (basename only)    │
# │                     e.g. "my_project.db"                   │
# │  main    Name of the production/main branch          │
# │                     e.g. "main"                                 │
# │  dev     Name of the development branch              │
# │                     e.g. "dev"                                  │
# │                                                                 │
# │  Example sed replacement:                                       │
# │    sed 's/%%PROJECT_DB%%/my_project.db/g; \                        │
# │         s/main/main/g; \                             │
# │         s/dev/dev/g' \                               │
# │      milestone_check.template.sh > milestone_check.sh           │
# └─────────────────────────────────────────────────────────────────┘

set -euo pipefail

_run_sql() {
  local db="$1" sql="$2"
  if command -v sqlite3 &>/dev/null; then
    sqlite3 "$db" "$sql"
  elif python3 -c "pass" 2>/dev/null; then
    _RUNSQL_DB="$db" _RUNSQL_SQL="$sql" python3 -c "
import sqlite3, sys, os
conn = sqlite3.connect(os.environ['_RUNSQL_DB'])
cur = conn.cursor()
for stmt in os.environ['_RUNSQL_SQL'].strip().split(';'):
    stmt = stmt.strip()
    if stmt:
        cur.execute(stmt)
rows = cur.fetchall()
for r in rows:
    print('|'.join(str(c) for c in r))
conn.commit()
conn.close()
"
  else
    echo "ERROR: Neither sqlite3 CLI nor python3 available" >&2
    return 1
  fi
}

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$PROJECT_DIR/%%PROJECT_DB%%"
COHERENCE_SCRIPT="$PROJECT_DIR/coherence_check.sh"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

pass() { echo -e "${GREEN}✅ $1${RESET}"; }
fail() { echo -e "${RED}❌ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $1${RESET}"; }
info() { echo -e "${CYAN}   $1${RESET}"; }
header() { echo -e "\n${BOLD}$1${RESET}"; }

# ── Prerequisite checks ──────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo -e "${RED}❌ PREREQUISITE FAILED: git is not installed${RESET}"
    exit 2
fi
if [[ ! -f "$DB" ]]; then
    echo -e "${RED}❌ PREREQUISITE FAILED: Database not found at $DB${RESET}"
    echo "   Create it: bash db_queries.sh init-db"
    exit 2
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: bash milestone_check.sh <PHASE>"
    exit 1
fi

PHASE=$(echo "$1" | tr '[:lower:]' '[:upper:]')
ERRORS=0

echo -e "\n${BOLD}═══════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Milestone gate: $PHASE${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}"

# 1. Task completion
header "Step 1 · Task completion ($PHASE)"

# Condition 1: Forward tasks in this phase must all be DONE (preserve MASTER exclusion)
FWD_TOTAL=$(_run_sql "$DB" "SELECT COUNT(*) FROM tasks WHERE phase='$PHASE' AND COALESCE(track,'forward')='forward';")
FWD_DONE=$(_run_sql "$DB" "SELECT COUNT(*) FROM tasks WHERE phase='$PHASE' AND COALESCE(track,'forward')='forward' AND status='DONE';")
FWD_INCOMPLETE=$(_run_sql "$DB" "
    SELECT COUNT(*) FROM tasks
    WHERE phase='$PHASE' AND COALESCE(track,'forward')='forward'
      AND status NOT IN ('DONE','SKIP','MASTER')
      AND (queue IS NULL OR queue != 'INBOX');
")

# Condition 2: Gate-critical loopbacks discovered in this phase must be DONE
GC_INCOMPLETE=$(_run_sql "$DB" "
    SELECT COUNT(*) FROM tasks
    WHERE track='loopback' AND discovered_in='$PHASE'
      AND gate_critical=1 AND status NOT IN ('DONE','SKIP');
")

TODO=$((FWD_INCOMPLETE + GC_INCOMPLETE))

if [[ "$FWD_INCOMPLETE" -eq 0 ]] && [[ "$GC_INCOMPLETE" -eq 0 ]]; then
    pass "All $FWD_DONE/$FWD_TOTAL forward tasks DONE in $PHASE"
else
    [[ "$FWD_INCOMPLETE" -gt 0 ]] && fail "Forward tasks incomplete: $FWD_INCOMPLETE remaining"
    [[ "$GC_INCOMPLETE" -gt 0 ]] && fail "Gate-critical loopbacks incomplete: $GC_INCOMPLETE remaining"
    ERRORS=$((ERRORS + 1))
fi

# Non-critical loopbacks (informational, doesn't block)
NC_OPEN=$(_run_sql "$DB" "
    SELECT COUNT(*) FROM tasks
    WHERE track='loopback' AND discovered_in='$PHASE'
      AND (gate_critical=0 OR gate_critical IS NULL)
      AND status NOT IN ('DONE','SKIP');
")
if [[ "$NC_OPEN" -gt 0 ]]; then
    warn "Non-critical loopbacks still open: $NC_OPEN (won't block gate)"
fi

# 2. Branch check
header "Step 2 · Git branch"
# Verify expected branches exist before comparing them
if ! git -C "$PROJECT_DIR" rev-parse --verify "dev" &>/dev/null; then
    fail "Branch 'dev' does not exist in this repository"
    ERRORS=$((ERRORS + 1))
fi
if ! git -C "$PROJECT_DIR" rev-parse --verify "main" &>/dev/null; then
    fail "Branch 'main' does not exist in this repository"
    ERRORS=$((ERRORS + 1))
fi

CURRENT_BRANCH=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
if [[ "$CURRENT_BRANCH" == "dev" ]]; then pass "On branch: dev"
else fail "Not on dev (on: $CURRENT_BRANCH)"; ERRORS=$((ERRORS + 1)); fi

# 3. Working tree
header "Step 3 · Working tree"
DIRTY=$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null | grep -v '^??' || true)
if [[ -z "$DIRTY" ]]; then pass "Working tree clean"
else fail "Uncommitted changes"; ERRORS=$((ERRORS + 1)); fi

if git -C "$PROJECT_DIR" rev-parse --verify "main" &>/dev/null && \
   git -C "$PROJECT_DIR" rev-parse --verify "dev" &>/dev/null; then
    AHEAD=$(git -C "$PROJECT_DIR" rev-list --count main..dev)
    info "$AHEAD commit(s) on dev ahead of main"
fi

# 4. Coherence
header "Step 4 · Coherence"
if [[ -f "$COHERENCE_SCRIPT" ]]; then
    COHERENCE_OUTPUT=$(bash "$COHERENCE_SCRIPT" 2>&1)
    if ! echo "$COHERENCE_OUTPUT" | grep -q "Coherence check passed"; then
        fail "Coherence issues found"; ERRORS=$((ERRORS + 1))
    else pass "Coherence clean"; fi
else warn "coherence_check.sh not found — skipping"; fi

# 5. Build + tests (if build_summarizer is implemented)
header "Step 5 · Build + tests"
BUILD_SCRIPT="$PROJECT_DIR/build_summarizer.sh"
if [[ -f "$BUILD_SCRIPT" ]]; then
    if grep -q "stub" "$BUILD_SCRIPT" 2>/dev/null; then
        warn "build_summarizer.sh is still a stub — skipping"
    else
        BUILD_OUTPUT=$(bash "$BUILD_SCRIPT" test 2>&1)
        if echo "$BUILD_OUTPUT" | grep -q "All checks passed"; then
            pass "Build + tests passed"
        else
            fail "Build or tests failed"; ERRORS=$((ERRORS + 1))
            echo "$BUILD_OUTPUT" | tail -10 | sed 's/^/   /'
        fi
    fi
else
    warn "build_summarizer.sh not found — skipping"
fi

# Summary
echo -e "\n${BOLD}═══════════════════════════════════════════════════${RESET}"
if [[ "$ERRORS" -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}  ✅ ALL CHECKS PASSED — $PHASE is merge-ready${RESET}"
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}\n"

    # Check if source code was changed (not just markdown/config)
    SRC_CHANGES=0
    if git -C "$PROJECT_DIR" rev-parse --verify "main" &>/dev/null && \
       git -C "$PROJECT_DIR" rev-parse --verify "dev" &>/dev/null; then
        SRC_CHANGES=$(git -C "$PROJECT_DIR" diff main..dev --name-only | grep -c '^src/' || true)
    fi

    if [[ "$SRC_CHANGES" -gt 0 ]]; then
        echo -e "${YELLOW}${BOLD}  ⚠️  BEFORE MERGING — Run code review in Cowork:${RESET}"
        echo -e "${YELLOW}"
        echo "  ┌────────────────────────────────────────────────────────┐"
        echo "  │  1. Open Cowork (Claude desktop app)                   │"
        echo "  │  2. Run:  /engineering:review                          │"
        echo "  │  3. Paste:  git diff main..dev                       │"
        echo "  │  4. Fix any issues found on dev branch                 │"
        echo "  │  5. Re-run this check if fixes were needed             │"
        echo "  └────────────────────────────────────────────────────────┘"
        echo -e "${RESET}"
        echo -e "  ${SRC_CHANGES} source file(s) changed since main.\n"
    fi

    echo -e "${CYAN}  Once review is done, merge with:"
    echo ""
    echo "  git checkout main"
    echo "  git merge dev --no-ff -m \"Milestone: $PHASE complete\""
    PHASE_LOWER=$(echo "$PHASE" | tr '[:upper:]' '[:lower:]')
    echo "  git tag milestone-${PHASE_LOWER}"
    echo "  git push origin main"
    echo "  git push origin --tags"
    echo -e "  git checkout dev${RESET}\n"
else
    echo -e "${RED}${BOLD}  ❌ $ERRORS check(s) failed — fix before merging${RESET}"
    echo -e "${BOLD}═══════════════════════════════════════════════════${RESET}\n"
    exit 1
fi
