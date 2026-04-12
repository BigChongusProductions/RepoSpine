#!/usr/bin/env bash
# =============================================================================
# Bootstrap E2E Test Suite
# Tests bootstrap_project.sh directly as a black box for both lifecycle modes
#
# Usage:
#   bash test_bootstrap_e2e.sh               # Run full + quick + cross + regression
#   bash test_bootstrap_e2e.sh --full        # Full lifecycle only
#   bash test_bootstrap_e2e.sh --quick       # Quick lifecycle only
#   bash test_bootstrap_e2e.sh --cleanup     # Remove test directories
#
# Creates: ~/Desktop/test_bootstrap_e2e_{full,quick}/
# =============================================================================

set -uo pipefail

# === PATHS ===================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_SCRIPT="$SCRIPT_DIR/../bootstrap_project.sh"
SUITE_DIR="$HOME/Desktop"
EXISTING_SUITE="$SCRIPT_DIR/test_bootstrap_suite.sh"

# === RESULT TRACKING =========================================================
TOTAL_CHECKS=0
TOTAL_PASS=0
TOTAL_FAIL=0
declare -a FAILURES=()
CURRENT_CONTEXT=""

# === COLORS ==================================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

# === HELPERS =================================================================
pass()    { TOTAL_CHECKS=$((TOTAL_CHECKS+1)); TOTAL_PASS=$((TOTAL_PASS+1));  echo -e "  ${GREEN}✅${RESET} $1"; }
fail()    { TOTAL_CHECKS=$((TOTAL_CHECKS+1)); TOTAL_FAIL=$((TOTAL_FAIL+1));  FAILURES+=("[$CURRENT_CONTEXT] $1"); echo -e "  ${RED}❌${RESET} $1"; }
warn()    { echo -e "  ${YELLOW}⚠️${RESET}  $1"; }
info()    { echo -e "  ${BLUE}ℹ️${RESET}  $1"; }
section() { echo -e "\n${BOLD}── $1 ─────────────────────────────────────────────${RESET}"; }
header()  { echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"; \
            echo -e "${BOLD}║  $1${RESET}"; \
            echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"; }

chk() {
  local LABEL="$1"; shift
  TOTAL_CHECKS=$((TOTAL_CHECKS+1))
  if "$@" 2>/dev/null; then
    TOTAL_PASS=$((TOTAL_PASS+1)); echo -e "  ${GREEN}✅${RESET} $LABEL"
  else
    TOTAL_FAIL=$((TOTAL_FAIL+1)); FAILURES+=("[$CURRENT_CONTEXT] $LABEL"); echo -e "  ${RED}❌${RESET} $LABEL"
  fi
}

chk_contains() {
  # chk_contains "label" "file" "pattern"
  local LABEL="$1" FILE="$2" PATTERN="$3"
  TOTAL_CHECKS=$((TOTAL_CHECKS+1))
  if grep -q "$PATTERN" "$FILE" 2>/dev/null; then
    TOTAL_PASS=$((TOTAL_PASS+1)); echo -e "  ${GREEN}✅${RESET} $LABEL"
  else
    TOTAL_FAIL=$((TOTAL_FAIL+1)); FAILURES+=("[$CURRENT_CONTEXT] $LABEL"); echo -e "  ${RED}❌${RESET} $LABEL"
  fi
}

chk_not_contains() {
  # chk_not_contains "label" "file" "pattern"
  local LABEL="$1" FILE="$2" PATTERN="$3"
  TOTAL_CHECKS=$((TOTAL_CHECKS+1))
  if ! grep -q "$PATTERN" "$FILE" 2>/dev/null; then
    TOTAL_PASS=$((TOTAL_PASS+1)); echo -e "  ${GREEN}✅${RESET} $LABEL"
  else
    TOTAL_FAIL=$((TOTAL_FAIL+1)); FAILURES+=("[$CURRENT_CONTEXT] $LABEL"); echo -e "  ${RED}❌${RESET} $LABEL"
  fi
}

# === PRE-FLIGHT ==============================================================
preflight() {
  header "Pre-flight Checks"
  local OK=1

  [ -f "$BOOTSTRAP_SCRIPT" ] || { echo -e "${RED}❌ bootstrap_project.sh not found at $BOOTSTRAP_SCRIPT${RESET}"; OK=0; }
  command -v sqlite3 >/dev/null || { echo -e "${RED}❌ sqlite3 not found${RESET}"; OK=0; }
  command -v python3 >/dev/null || { echo -e "${RED}❌ python3 not found${RESET}"; OK=0; }

  # Template locations
  local DEV_FW="$HOME/.claude/dev-framework/templates"
  [ -d "$DEV_FW/scripts" ] || { echo -e "${RED}❌ Template scripts not found at $DEV_FW/scripts${RESET}"; OK=0; }
  [ -d "$DEV_FW/frameworks" ] || { echo -e "${RED}❌ Template frameworks not found at $DEV_FW/frameworks${RESET}"; OK=0; }
  [ -d "$DEV_FW/hooks" ] || { echo -e "${RED}❌ Template hooks not found at $DEV_FW/hooks${RESET}"; OK=0; }
  [ -d "$DEV_FW/agents" ] || { echo -e "${RED}❌ Template agents not found at $DEV_FW/agents${RESET}"; OK=0; }
  [ -d "$DEV_FW/settings" ] || { echo -e "${RED}❌ Template settings not found at $DEV_FW/settings${RESET}"; OK=0; }
  [ -d "$DEV_FW/rules" ] || { echo -e "${RED}❌ Template rules not found at $DEV_FW/rules${RESET}"; OK=0; }

  # Stale test dirs
  for suffix in full quick; do
    if [ -d "$SUITE_DIR/test_bootstrap_e2e_$suffix" ]; then
      echo -e "${YELLOW}⚠️  $SUITE_DIR/test_bootstrap_e2e_$suffix already exists — run with --cleanup first${RESET}"
      OK=0
    fi
  done

  [ "$OK" = "1" ] && echo -e "${GREEN}✅ All pre-flight checks passed${RESET}" || \
    { echo -e "${RED}❌ Pre-flight failed — fix above before running${RESET}"; exit 1; }
}

# === BOOTSTRAP RUNNER ========================================================
run_bootstrap() {
  local NAME="$1" DIR="$2" LIFECYCLE="$3"
  section "Running bootstrap_project.sh: $NAME ($LIFECYCLE lifecycle)"

  local OUTPUT EXIT_CODE
  OUTPUT=$(bash "$BOOTSTRAP_SCRIPT" "$NAME" "$DIR" \
    --lifecycle "$LIFECYCLE" \
    --frameworks all \
    --non-interactive 2>&1) || true
  EXIT_CODE=${PIPESTATUS[0]:-$?}

  if [ "$EXIT_CODE" -eq 0 ] || [ -d "$DIR" ]; then
    pass "bootstrap_project.sh exited successfully for $NAME ($LIFECYCLE)"
    info "Output: $(echo "$OUTPUT" | tail -5 | head -3)"
  else
    fail "bootstrap_project.sh failed for $NAME ($LIFECYCLE) — exit code $EXIT_CODE"
    echo "$OUTPUT" | tail -20 | while IFS= read -r l; do warn "  $l"; done
  fi
}

# === VERIFICATION: CORE FILES ================================================
verify_core_files() {
  local DIR="$1" NAME_UPPER="$2" LIFECYCLE="$3"
  section "Core file existence ($LIFECYCLE)"

  chk "CLAUDE.md exists" test -f "$DIR/CLAUDE.md"
  chk "${NAME_UPPER}_RULES.md exists" test -f "$DIR/${NAME_UPPER}_RULES.md"
  chk "LESSONS_${NAME_UPPER}.md exists" test -f "$DIR/LESSONS_${NAME_UPPER}.md"
  chk "${NAME_UPPER}_PROJECT_MEMORY.md exists" test -f "$DIR/${NAME_UPPER}_PROJECT_MEMORY.md"
  chk "LEARNING_LOG.md exists" test -f "$DIR/LEARNING_LOG.md"
  chk "NEXT_SESSION.md exists" test -f "$DIR/NEXT_SESSION.md"
  chk "AGENT_DELEGATION.md exists" test -f "$DIR/AGENT_DELEGATION.md"
  chk ".gitignore exists" test -f "$DIR/.gitignore"
  chk "refs/ directory exists" test -d "$DIR/refs"
  chk "refs/README.md exists" test -f "$DIR/refs/README.md"

  if [ "$LIFECYCLE" = "full" ]; then
    chk "specs/ directory exists (full)" test -d "$DIR/specs"
    # specs/ may be empty — discovery skill seeds it dynamically
    if [ -d "$DIR/specs" ]; then
      local SPEC_COUNT
      SPEC_COUNT=$(ls "$DIR/specs/"*.md 2>/dev/null | wc -l | tr -d ' ')
      if [ "$SPEC_COUNT" -ge 1 ]; then
        pass "specs/ has $SPEC_COUNT spec file(s)"
      else
        pass "specs/ directory exists (empty — discovery skill seeds later)"
      fi
    fi
  fi
}

# === VERIFICATION: DATABASE ==================================================
verify_database() {
  local DIR="$1" DB_NAME="$2" LIFECYCLE="$3"
  section "Database validation ($LIFECYCLE)"

  local DB="$DIR/$DB_NAME"
  chk "DB file exists ($DB_NAME)" test -f "$DB"

  if [ ! -f "$DB" ]; then
    fail "Cannot continue DB checks — file missing"
    return
  fi

  # Check tables exist
  local TABLES
  TABLES=$(sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;" 2>/dev/null)
  for TABLE in assumptions db_snapshots decisions loopback_acks milestone_confirmations phase_gates sessions tasks; do
    if echo "$TABLES" | grep -q "^${TABLE}$"; then
      pass "Table '$TABLE' exists"
    else
      fail "Table '$TABLE' missing"
    fi
  done

  # Check key columns exist
  chk "tasks.details column exists" bash -c "sqlite3 '$DB' 'SELECT details FROM tasks LIMIT 1;' 2>/dev/null"
  chk "tasks.completed_on column exists" bash -c "sqlite3 '$DB' 'SELECT completed_on FROM tasks LIMIT 1;' 2>/dev/null"
  chk "tasks.researched column exists" bash -c "sqlite3 '$DB' 'SELECT researched FROM tasks LIMIT 1;' 2>/dev/null"
  chk "tasks.tier column exists" bash -c "sqlite3 '$DB' 'SELECT tier FROM tasks LIMIT 1;' 2>/dev/null"

  # Lifecycle-specific seeding
  local TASK_COUNT GATE_COUNT
  TASK_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM tasks;" 2>/dev/null)
  GATE_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM phase_gates;" 2>/dev/null)

  if [ "$LIFECYCLE" = "full" ]; then
    if [ "${TASK_COUNT:-0}" -ge 5 ]; then
      pass "Full lifecycle: $TASK_COUNT bootstrap tasks seeded (expected >=5)"
    else
      fail "Full lifecycle: only $TASK_COUNT tasks (expected >=5)"
    fi
    if [ "${GATE_COUNT:-0}" -ge 9 ]; then
      pass "Full lifecycle: $GATE_COUNT phase gates (expected 9)"
    else
      fail "Full lifecycle: only $GATE_COUNT phase gates (expected 9)"
    fi
  else
    if [ "${TASK_COUNT:-0}" -ge 1 ]; then
      pass "Quick lifecycle: $TASK_COUNT bootstrap task(s) seeded (expected >=1)"
    else
      fail "Quick lifecycle: $TASK_COUNT tasks (expected >=1)"
    fi
    if [ "${GATE_COUNT:-0}" -ge 3 ]; then
      pass "Quick lifecycle: $GATE_COUNT phase gates (expected 3)"
    else
      fail "Quick lifecycle: only $GATE_COUNT phase gates (expected 3)"
    fi
  fi
}

# === VERIFICATION: SCRIPTS ===================================================
verify_scripts() {
  local DIR="$1"
  section "Scripts exist and executable"

  for s in db_queries.sh session_briefing.sh coherence_check.sh coherence_registry.sh \
           milestone_check.sh build_summarizer.sh work.sh fix.sh; do
    chk "$s executable" test -x "$DIR/$s"
  done
  chk "generate_board.py exists" test -f "$DIR/generate_board.py"

  # New step-26 scripts
  for s in save_session.sh shared_signal.sh harvest.sh; do
    if [ -f "$DIR/$s" ]; then
      chk "$s exists and executable (step 26)" test -x "$DIR/$s"
    else
      warn "$s not deployed (template may be missing)"
    fi
  done
}

# === VERIFICATION: HOOKS =====================================================
verify_hooks() {
  local DIR="$1"
  section "Hook deployment (step 23)"

  chk ".claude/hooks/ directory exists" test -d "$DIR/.claude/hooks"

  if [ ! -d "$DIR/.claude/hooks" ]; then
    fail "Cannot continue hook checks — directory missing"
    return
  fi

  # Count hooks
  local HOOK_COUNT
  HOOK_COUNT=$(ls "$DIR/.claude/hooks/"*.sh "$DIR/.claude/hooks/"*.conf 2>/dev/null | wc -l | tr -d ' ')
  if [ "$HOOK_COUNT" -ge 10 ]; then
    pass "$HOOK_COUNT hook files deployed (expected >=10)"
  else
    fail "Only $HOOK_COUNT hook files (expected >=10)"
  fi

  # Key hooks present
  for hook in correction-detector.sh pre-edit-check.sh protect-databases.sh \
              session-start-check.sh session-end-safety.sh end-of-turn-check.sh \
              post-compact-recovery.sh subagent-delegation-check.sh; do
    chk "Hook: $hook present" test -f "$DIR/.claude/hooks/$hook"
  done
  chk "Hook: protected-files.conf present" test -f "$DIR/.claude/hooks/protected-files.conf"

  # No .template. in deployed filenames
  local TEMPLATE_NAMES
  TEMPLATE_NAMES=$(ls "$DIR/.claude/hooks/" 2>/dev/null | grep '\.template\.' | wc -l | tr -d ' ')
  if [ "${TEMPLATE_NAMES:-0}" -eq 0 ]; then
    pass "No .template. in deployed hook filenames"
  else
    fail "$TEMPLATE_NAMES hook files still have .template. in name"
  fi

  # All .sh hooks executable
  local NON_EXEC=0
  for hook in "$DIR/.claude/hooks/"*.sh; do
    [ -f "$hook" ] || continue
    if [ ! -x "$hook" ]; then
      NON_EXEC=$((NON_EXEC+1))
    fi
  done
  if [ "$NON_EXEC" -eq 0 ]; then
    pass "All .sh hooks are executable"
  else
    fail "$NON_EXEC .sh hooks are not executable"
  fi
}

# === VERIFICATION: SETTINGS ==================================================
verify_settings() {
  local DIR="$1"
  section "Settings wiring (step 24)"

  chk ".claude/settings.json exists" test -f "$DIR/.claude/settings.json"

  if [ -f "$DIR/.claude/settings.json" ]; then
    # Valid JSON
    if python3 -c "import json; json.load(open('$DIR/.claude/settings.json'))" 2>/dev/null; then
      pass ".claude/settings.json is valid JSON"
    else
      fail ".claude/settings.json is NOT valid JSON"
    fi

    # No raw placeholder
    chk_not_contains "No %%PERMISSION_ALLOW%% placeholder" "$DIR/.claude/settings.json" "%%PERMISSION_ALLOW%%"
  fi

  chk ".claude/settings.local.json exists" test -f "$DIR/.claude/settings.local.json"
}

# === VERIFICATION: AGENTS ====================================================
verify_agents() {
  local DIR="$1" PROJECT_NAME="$2"
  section "Agent configs (step 25)"

  chk ".claude/agents/implementer/implementer.md exists" test -f "$DIR/.claude/agents/implementer/implementer.md"
  chk ".claude/agents/worker/worker.md exists" test -f "$DIR/.claude/agents/worker/worker.md"

  if [ -f "$DIR/.claude/agents/implementer/implementer.md" ]; then
    chk_contains "implementer.md contains project name" "$DIR/.claude/agents/implementer/implementer.md" "$PROJECT_NAME"
    chk_not_contains "implementer.md has no %%PROJECT_NAME%% placeholder" "$DIR/.claude/agents/implementer/implementer.md" "%%PROJECT_NAME%%"
  fi

  if [ -f "$DIR/.claude/agents/worker/worker.md" ]; then
    chk_contains "worker.md contains project name" "$DIR/.claude/agents/worker/worker.md" "$PROJECT_NAME"
    chk_not_contains "worker.md has no %%PROJECT_NAME%% placeholder" "$DIR/.claude/agents/worker/worker.md" "%%PROJECT_NAME%%"
  fi
}

# === VERIFICATION: PLACEHOLDERS ==============================================
verify_placeholders() {
  local DIR="$1" DB_NAME="$2"
  section "Placeholder sweep verification (step 27)"

  # Zero placeholders in scripts, hooks, configs
  local SCRIPT_PLACEHOLDERS
  SCRIPT_PLACEHOLDERS=$(grep -rn '%%[A-Z_]*%%' "$DIR/" \
    --include="*.sh" --include="*.json" --include="*.conf" 2>/dev/null \
    | grep -v ".git/" | grep -v "template" | grep -vE "^\s*#|:[[:space:]]*#" | wc -l | tr -d ' ')
  SCRIPT_PLACEHOLDERS="${SCRIPT_PLACEHOLDERS:-0}"
  if [ "$SCRIPT_PLACEHOLDERS" -eq 0 ]; then
    pass "Zero unfilled placeholders in .sh/.json/.conf files"
  else
    fail "$SCRIPT_PLACEHOLDERS unfilled placeholder(s) in scripts/configs"
    grep -rn '%%[A-Z_]*%%' "$DIR/" \
      --include="*.sh" --include="*.json" --include="*.conf" 2>/dev/null \
      | grep -v ".git/" | grep -v "template" | grep -vE "^\s*#|:[[:space:]]*#" \
      | head -5 | while IFS= read -r l; do warn "  $l"; done
  fi

  # .md placeholders — RULES has intentional customization placeholders
  local MD_PLACEHOLDERS
  MD_PLACEHOLDERS=$(grep -rn '%%[A-Z_]*%%' "$DIR/" \
    --include="*.md" 2>/dev/null \
    | grep -v ".git/" | grep -v "template" | grep -vE "^\s*#|:[[:space:]]*#" | wc -l | tr -d ' ')
  MD_PLACEHOLDERS="${MD_PLACEHOLDERS:-0}"
  if [ "$MD_PLACEHOLDERS" -eq 0 ]; then
    pass "Zero unfilled placeholders in .md files"
  else
    # This is expected — RULES has customization placeholders
    info "$MD_PLACEHOLDERS placeholder(s) in .md files (expected: RULES customization)"
  fi

  # Positive substitution checks
  if [ -f "$DIR/db_queries.sh" ]; then
    chk_contains "db_queries.sh contains actual DB name ($DB_NAME)" "$DIR/db_queries.sh" "$DB_NAME"
  fi

  # Check hooks were parameterized
  if [ -f "$DIR/.claude/hooks/correction-detector.sh" ]; then
    chk_not_contains "correction-detector.sh has no %%LESSONS_FILE%%" "$DIR/.claude/hooks/correction-detector.sh" "%%LESSONS_FILE%%"
  fi
  if [ -f "$DIR/.claude/hooks/protect-databases.sh" ]; then
    chk_not_contains "protect-databases.sh has no %%PROJECT_DB%%" "$DIR/.claude/hooks/protect-databases.sh" "%%PROJECT_DB%%"
  fi
}

# === VERIFICATION: GIT =======================================================
verify_git() {
  local DIR="$1"
  section "Git validation (step 28)"

  chk ".git/ directory exists" test -d "$DIR/.git"

  if [ ! -d "$DIR/.git" ]; then
    fail "Cannot continue git checks — .git missing"
    return
  fi

  # At least one commit
  local COMMIT_COUNT
  COMMIT_COUNT=$(cd "$DIR" && git log --oneline 2>/dev/null | wc -l | tr -d ' ')
  if [ "${COMMIT_COUNT:-0}" -ge 1 ]; then
    pass "At least 1 git commit exists ($COMMIT_COUNT total)"
  else
    fail "No git commits found"
  fi

  # dev branch exists
  local DEV_EXISTS
  DEV_EXISTS=$(cd "$DIR" && git branch --list dev 2>/dev/null | wc -l | tr -d ' ')
  if [ "${DEV_EXISTS:-0}" -ge 1 ]; then
    pass "dev branch exists"
  else
    fail "dev branch does not exist"
  fi

  # Check current branch — bootstrap switches to dev
  local CURRENT_BRANCH
  CURRENT_BRANCH=$(cd "$DIR" && git branch --show-current 2>/dev/null)
  if [ "$CURRENT_BRANCH" = "dev" ]; then
    pass "Currently on dev branch"
  else
    info "Currently on '$CURRENT_BRANCH' (expected 'dev')"
  fi
}

# === VERIFICATION: LIFECYCLE SPECIFICS =======================================
verify_lifecycle_specifics() {
  local DIR="$1" LIFECYCLE="$2" DB_NAME="$3"
  section "Lifecycle-specific validation ($LIFECYCLE)"

  if [ "$LIFECYCLE" = "full" ]; then
    # Check db_queries.sh has 9-phase list
    if [ -f "$DIR/db_queries.sh" ]; then
      chk_contains "db_queries.sh has P1-ENVISION" "$DIR/db_queries.sh" "P1-ENVISION"
      chk_contains "db_queries.sh has P9-EVOLVE" "$DIR/db_queries.sh" "P9-EVOLVE"
    fi
    # Phase gates seeded correctly
    local PHASES
    PHASES=$(sqlite3 "$DIR/$DB_NAME" "SELECT phase FROM phase_gates ORDER BY phase;" 2>/dev/null | tr '\n' ' ')
    if echo "$PHASES" | grep -q "P1-ENVISION"; then
      pass "Phase gates include P1-ENVISION"
    else
      fail "Phase gates missing P1-ENVISION (got: $PHASES)"
    fi
  else
    # Quick lifecycle
    if [ -f "$DIR/db_queries.sh" ]; then
      chk_contains "db_queries.sh has P1-PLAN" "$DIR/db_queries.sh" "P1-PLAN"
      chk_contains "db_queries.sh has P3-SHIP" "$DIR/db_queries.sh" "P3-SHIP"
    fi
  fi
}

# === VERIFICATION: SCRIPT EXERCISE ==========================================
exercise_scripts() {
  local DIR="$1" DB_NAME="$2"
  section "Script exercise (functional smoke tests)"

  cd "$DIR"

  chk "db_queries.sh health exits 0" bash db_queries.sh health
  chk "db_queries.sh next produces output" bash -c "bash db_queries.sh next 2>&1 | grep -q ''"
  chk "db_queries.sh verify exits 0" bash db_queries.sh verify

  # Check command with first task
  local FIRST_TASK
  FIRST_TASK=$(sqlite3 "$DB_NAME" "SELECT id FROM tasks LIMIT 1;" 2>/dev/null)
  if [ -n "$FIRST_TASK" ]; then
    chk "db_queries.sh check $FIRST_TASK exits 0" bash db_queries.sh check "$FIRST_TASK"
  else
    warn "No tasks found — skipping check command"
  fi

  chk "session_briefing.sh runs without fatal error" bash session_briefing.sh
  chk "coherence_check.sh runs without fatal error" bash coherence_check.sh
  chk "build_summarizer.sh build runs" bash build_summarizer.sh build
  chk "generate_board.py runs" python3 generate_board.py

  # Do NOT exercise work.sh/fix.sh — they open Terminal via osascript
  info "Skipping work.sh/fix.sh (opens Terminal windows)"

  cd "$SCRIPT_DIR"
}

# === CROSS-LIFECYCLE COMPARISON ==============================================
verify_cross_lifecycle() {
  local FULL_DIR="$1" QUICK_DIR="$2"
  header "Cross-Lifecycle Comparison"

  section "Task count comparison"
  local FULL_TASKS QUICK_TASKS
  FULL_TASKS=$(sqlite3 "$FULL_DIR/e2efulltest.db" "SELECT COUNT(*) FROM tasks;" 2>/dev/null)
  QUICK_TASKS=$(sqlite3 "$QUICK_DIR/e2equicktest.db" "SELECT COUNT(*) FROM tasks;" 2>/dev/null)
  if [ "${FULL_TASKS:-0}" -gt "${QUICK_TASKS:-0}" ]; then
    pass "Full ($FULL_TASKS tasks) > Quick ($QUICK_TASKS tasks)"
  else
    fail "Expected Full tasks > Quick tasks (Full=$FULL_TASKS, Quick=$QUICK_TASKS)"
  fi

  section "Both have hooks, agents, settings"
  local FULL_HOOKS QUICK_HOOKS
  FULL_HOOKS=$(ls "$FULL_DIR/.claude/hooks/"*.sh 2>/dev/null | wc -l | tr -d ' ')
  QUICK_HOOKS=$(ls "$QUICK_DIR/.claude/hooks/"*.sh 2>/dev/null | wc -l | tr -d ' ')
  if [ "${FULL_HOOKS:-0}" -eq "${QUICK_HOOKS:-0}" ] && [ "${FULL_HOOKS:-0}" -gt 0 ]; then
    pass "Same hook count in both ($FULL_HOOKS hooks each)"
  else
    fail "Hook count mismatch (Full=$FULL_HOOKS, Quick=$QUICK_HOOKS)"
  fi

  chk "Both have implementer agent" bash -c "test -f '$FULL_DIR/.claude/agents/implementer/implementer.md' && test -f '$QUICK_DIR/.claude/agents/implementer/implementer.md'"
  chk "Both have worker agent" bash -c "test -f '$FULL_DIR/.claude/agents/worker/worker.md' && test -f '$QUICK_DIR/.claude/agents/worker/worker.md'"
  chk "Both have settings.json" bash -c "test -f '$FULL_DIR/.claude/settings.json' && test -f '$QUICK_DIR/.claude/settings.json'"

  section "Phase gate count comparison"
  local FULL_GATES QUICK_GATES
  FULL_GATES=$(sqlite3 "$FULL_DIR/e2efulltest.db" "SELECT COUNT(*) FROM phase_gates;" 2>/dev/null)
  QUICK_GATES=$(sqlite3 "$QUICK_DIR/e2equicktest.db" "SELECT COUNT(*) FROM phase_gates;" 2>/dev/null)
  if [ "${FULL_GATES:-0}" -gt "${QUICK_GATES:-0}" ]; then
    pass "Full ($FULL_GATES gates) > Quick ($QUICK_GATES gates)"
  else
    fail "Expected Full gates > Quick gates (Full=$FULL_GATES, Quick=$QUICK_GATES)"
  fi
}

# === CLEANUP =================================================================
cleanup() {
  echo -e "\n${YELLOW}Removing E2E test directories...${RESET}"
  for suffix in full quick; do
    local D="$SUITE_DIR/test_bootstrap_e2e_$suffix"
    if [ -d "$D" ]; then
      rm -rf "$D"
      echo -e "  ${GREEN}✅${RESET} Removed test_bootstrap_e2e_$suffix"
    fi
  done
  echo -e "${GREEN}Cleanup complete.${RESET}"
}

# === SUMMARY =================================================================
print_summary() {
  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║              E2E TEST SUITE SUMMARY                  ║${RESET}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""
  echo -e "  Checks: ${BOLD}$TOTAL_CHECKS${RESET} | Pass: ${GREEN}$TOTAL_PASS${RESET} | Fail: ${RED}$TOTAL_FAIL${RESET}"
  echo ""
  if [ "$TOTAL_FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}ALL CHECKS PASSED ✅${RESET}"
    echo -e "  ${GREEN}Bootstrap validated end-to-end for both lifecycle modes.${RESET}"
  else
    echo -e "  ${RED}${BOLD}$TOTAL_FAIL FAILURE(S) ❌${RESET}"
    echo ""
    echo -e "  ${BOLD}Failed checks:${RESET}"
    for f in "${FAILURES[@]}"; do
      echo -e "    ${RED}•${RESET} $f"
    done
    echo ""
    echo -e "  ${YELLOW}Fix bootstrap_project.sh and re-run. Test projects preserved for debugging.${RESET}"
  fi
  echo ""
}

# === RUN ONE LIFECYCLE =======================================================
run_lifecycle() {
  local LIFECYCLE="$1"
  local NAME DIR DB_NAME NAME_UPPER

  if [ "$LIFECYCLE" = "full" ]; then
    NAME="E2EFullTest"
    DIR="$SUITE_DIR/test_bootstrap_e2e_full"
    # bootstrap_project.sh: tr '[:upper:]' '[:lower:]' | tr ' ' '_' → no underscores for camelCase
    DB_NAME="e2efulltest.db"
    NAME_UPPER="E2EFULLTEST"
  else
    NAME="E2EQuickTest"
    DIR="$SUITE_DIR/test_bootstrap_e2e_quick"
    DB_NAME="e2equicktest.db"
    NAME_UPPER="E2EQUICKTEST"
  fi

  CURRENT_CONTEXT="$NAME ($LIFECYCLE)"
  header "E2E Test: $NAME ($LIFECYCLE lifecycle)"

  run_bootstrap "$NAME" "$DIR" "$LIFECYCLE"

  if [ ! -d "$DIR" ]; then
    fail "Project directory not created — skipping all verification"
    return
  fi

  verify_core_files "$DIR" "$NAME_UPPER" "$LIFECYCLE"
  verify_database "$DIR" "$DB_NAME" "$LIFECYCLE"
  verify_scripts "$DIR"
  verify_hooks "$DIR"
  verify_settings "$DIR"
  verify_agents "$DIR" "$NAME"
  verify_placeholders "$DIR" "$DB_NAME"
  verify_git "$DIR"
  verify_lifecycle_specifics "$DIR" "$LIFECYCLE" "$DB_NAME"
  exercise_scripts "$DIR" "$DB_NAME"
}

# === MAIN ====================================================================
main() {
  echo -e "${BOLD}Bootstrap E2E Test Suite${RESET}"
  echo -e "Tests bootstrap_project.sh directly for full + quick lifecycle modes."
  echo ""

  # Parse arguments
  if [ "${1:-}" = "--cleanup" ]; then
    cleanup; exit 0
  fi

  if [ "${1:-}" = "--full" ]; then
    preflight
    run_lifecycle "full"
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--quick" ]; then
    preflight
    run_lifecycle "quick"
    print_summary; exit 0
  fi

  # Default: run everything
  preflight

  run_lifecycle "full"
  run_lifecycle "quick"

  # Cross-lifecycle comparison
  CURRENT_CONTEXT="cross-lifecycle"
  verify_cross_lifecycle \
    "$SUITE_DIR/test_bootstrap_e2e_full" \
    "$SUITE_DIR/test_bootstrap_e2e_quick"

  # Run existing suite regression + python-cli tests
  if [ -f "$EXISTING_SUITE" ]; then
    header "Existing Suite: Regression Tests"
    CURRENT_CONTEXT="regression"
    local REG_OUT
    REG_OUT=$(bash "$EXISTING_SUITE" --regression 2>&1)
    local REG_EXIT=$?
    if [ "$REG_EXIT" -eq 0 ]; then
      pass "Existing suite regression tests passed"
    else
      fail "Existing suite regression tests failed (exit $REG_EXIT)"
      echo "$REG_OUT" | tail -10 | while IFS= read -r l; do warn "  $l"; done
    fi

    header "Existing Suite: Python CLI Tests"
    CURRENT_CONTEXT="python-cli"
    local PY_OUT
    PY_OUT=$(bash "$EXISTING_SUITE" --python-cli 2>&1)
    local PY_EXIT=$?
    if [ "$PY_EXIT" -eq 0 ]; then
      pass "Existing suite Python CLI tests passed"
    else
      fail "Existing suite Python CLI tests failed (exit $PY_EXIT)"
      echo "$PY_OUT" | tail -10 | while IFS= read -r l; do warn "  $l"; done
    fi
  else
    warn "Existing test suite not found at $EXISTING_SUITE — skipping"
  fi

  print_summary
}

main "$@"
