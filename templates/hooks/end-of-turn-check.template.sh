#!/bin/bash
# Hook: End-of-Turn Verification (Stop)
# Fires after Claude finishes responding. Checks for common session hygiene
# issues and injects warnings. Silent when clean; non-blocking.
#
# Checks in order:
#   1. Uncommitted changes (git dirty tree)
#   2. Scope crossed without delegation approval (via lib-scope-counter)
#   3. NEXT_SESSION.md staleness
#   4. Health cache verdict (DOGFOOD ALERT on failure)
#   5. Last checked task not marked DONE/SKIP/WONTFIX
#   6. Unresolved ⚡ DISCOVERY blocks (opt-out via DISCOVERY_TRACKING=0)
#
# Env knobs:
#   DISCOVERY_TRACKING          — 0 to disable Check 6 (default: 1)
#   DISCOVERY_TASK_ID_REGEX     — regex for CAPTURED task IDs (default: [A-Z]{2,4}-[0-9]+)

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"
# Scope tracker — used for the scope-aware advisory in Check 2.
source "$(dirname "${BASH_SOURCE[0]}")/lib-scope-counter.sh"

set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Fallback CWD — if empty or not a directory, bail silently.
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    exit 0
fi

WARNINGS=""

# ── Check 1: Large number of uncommitted changes ──────────────────────────
if [ -d "$CWD/.git" ]; then
    DIRTY=$(cd "$CWD" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$DIRTY" -gt 10 ]; then
        WARNINGS="${WARNINGS}\n- 📁 ${DIRTY} uncommitted files — consider committing before continuing"
    fi
fi

# ── Check 2: Scope crossed without delegation approval ────────────────────
# Replaces the old EDIT_COUNT > 8 heuristic (fired on trivial large-file
# reformats). The scope tracker dedupes retries by sha1(old_string) and
# fires exactly once per task boundary when thresholds are crossed.
export SCOPE_STATE_FILE="$CWD/.claude/hooks/.delegation_scope.json"
export SCOPE_HISTORY_FILE="$CWD/.claude/hooks/.scope_history.jsonl"

STATE_FILE="$CWD/.claude/hooks/.delegation_state"
LAST_APPROVAL=0
if [ -f "$STATE_FILE" ]; then
    LAST_APPROVAL=$(sed -n '2p' "$STATE_FILE" 2>/dev/null || echo "0")
fi
NOW=$(date +%s)
APPROVAL_AGE=$((NOW - LAST_APPROVAL))

# Plan-active suppression (same 6h horizon as pre-edit-check).
PLAN_MARKER="$CWD/.claude/hooks/.active-plan"
PLAN_ACTIVE=false
if [ -f "$PLAN_MARKER" ]; then
    PLAN_TS=$(sed -n '1p' "$PLAN_MARKER" 2>/dev/null || echo "0")
    PLAN_AGE=$((NOW - PLAN_TS))
    if [ "$PLAN_AGE" -lt 21600 ]; then
        PLAN_ACTIVE=true
    fi
fi

if [ "$APPROVAL_AGE" -gt 1800 ] && [ "$PLAN_ACTIVE" = "false" ]; then
    if FIRE_REASON=$(scope_should_fire); then
        WARNINGS="${WARNINGS}\n- ✏️ Scope crossed threshold (${FIRE_REASON}) without delegation approval — is this still a single-task scope?"
        scope_mark_fired
    fi
fi

# ── Check 3: NEXT_SESSION.md very stale (>24h) ────────────────────────────
if [ -f "$CWD/NEXT_SESSION.md" ]; then
    NOW=$(date +%s)
    MTIME=$(stat -c %Y "$CWD/NEXT_SESSION.md" 2>/dev/null || stat -f %m "$CWD/NEXT_SESSION.md" 2>/dev/null || echo "0")
    AGE_HOURS=$(( (NOW - MTIME) / 3600 ))
    if [ "$AGE_HOURS" -gt 24 ]; then
        WARNINGS="${WARNINGS}\n- 📋 NEXT_SESSION.md is ${AGE_HOURS}h old — save session when ready"
    fi
fi

# ── Check 4: Health cache verdict (dogfood alert) ─────────────────────────
# Format (current): epoch|exit_code|verdict
# Format (legacy):  bare exit_code on a single line
# An in-place v1.2 → v1.3 upgrade may have a legacy cache on disk for one
# invocation; after the next health write, the new format takes over.
HEALTH_CACHE="$CWD/.claude/hooks/.health_cache"
if [ -f "$HEALTH_CACHE" ]; then
    CACHE_LINE=$(head -1 "$HEALTH_CACHE" | tr -d '\n')
    if [[ "$CACHE_LINE" == *"|"* ]]; then
        # New format: ts|exit|verdict
        CACHE_TS=$(printf '%s' "$CACHE_LINE" | cut -d'|' -f1)
        CACHE_EXIT=$(printf '%s' "$CACHE_LINE" | cut -d'|' -f2)
        CACHE_VERDICT=$(printf '%s' "$CACHE_LINE" | cut -d'|' -f3)
        NOW=$(date +%s)
        CACHE_AGE=$((NOW - CACHE_TS))
        if [ "$CACHE_AGE" -lt 600 ] && [ "$CACHE_EXIT" != "0" ]; then
            WARNINGS="${WARNINGS}\n- DOGFOOD ALERT: last health check failed (${CACHE_VERDICT})"
        fi
    elif [[ "$CACHE_LINE" =~ ^[0-9]+$ ]]; then
        # Legacy format: bare exit code, no timestamp, no verdict.
        # We can't check freshness — warn conservatively only on nonzero.
        if [ "$CACHE_LINE" != "0" ]; then
            WARNINGS="${WARNINGS}\n- DOGFOOD ALERT: last health check failed (LEGACY format, exit ${CACHE_LINE}) — run bash db_queries.sh health to refresh"
        fi
    fi
    # Any other shape → silently ignored (malformed cache).
fi

# ── Check 5: Last checked task not marked done ────────────────────────────
TASK_FILE="$CWD/.claude/hooks/.last_check_result"
if [ -f "$TASK_FILE" ] && [ -f "$CWD/db_queries.sh" ]; then
    STARTED_TASK=$(cut -d'|' -f3 "$TASK_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$STARTED_TASK" ]; then
        TASK_STATUS=$(bash "$CWD/db_queries.sh" task "$STARTED_TASK" 2>/dev/null | grep -oE 'Status: [A-Z_]+' | head -1 | cut -d' ' -f2 || echo "")
        TASK_STATUS="${TASK_STATUS:-unknown}"
        if [ "$TASK_STATUS" != "DONE" ] && [ "$TASK_STATUS" != "SKIP" ] && [ "$TASK_STATUS" != "WONTFIX" ] && [ "$TASK_STATUS" != "unknown" ]; then
            WARNINGS="${WARNINGS}\n- 📋 Task ${STARTED_TASK} was checked but still ${TASK_STATUS} — mark done when complete: bash db_queries.sh done ${STARTED_TASK}"
        fi
    fi
fi

# ── Check 6 (opt-out): Unresolved ⚡ DISCOVERY blocks ─────────────────────
# Default behavior is ENABLED. Set DISCOVERY_TRACKING=0 to silence.
# A DISCOVERY block must be followed by either:
#   → CAPTURED: <task-id matching $DISCOVERY_TASK_ID_REGEX>
#   → PROCESSED
if [ "${DISCOVERY_TRACKING:-1}" = "1" ]; then
    DISC_REGEX="${DISCOVERY_TASK_ID_REGEX:-[A-Z]{2,4}-[0-9]+}"
    # Try multiple transcript field names — Claude Code's Stop payload
    # shape has shifted over versions.
    TRANSCRIPT=""
    for field in transcript last_assistant_message message.content content; do
        CANDIDATE=$(echo "$INPUT" | jq -r ".${field} // empty" 2>/dev/null)
        if [ -n "$CANDIDATE" ]; then
            TRANSCRIPT="$CANDIDATE"
            break
        fi
    done

    if [ -n "$TRANSCRIPT" ]; then
        DISC_COUNT=$(echo "$TRANSCRIPT" | grep -c '⚡ DISCOVERY:' 2>/dev/null || echo "0")
        # Resolution = either "→ CAPTURED: <matching-task-id>" or "→ PROCESSED"
        RESOLVED_COUNT=$(echo "$TRANSCRIPT" | grep -cE "→ CAPTURED: ${DISC_REGEX}|→ PROCESSED" 2>/dev/null || echo "0")
        if [ "$DISC_COUNT" -gt 0 ] && [ "$RESOLVED_COUNT" -lt "$DISC_COUNT" ]; then
            UNRESOLVED=$((DISC_COUNT - RESOLVED_COUNT))
            WARNINGS="${WARNINGS}\n- ⚡ ${UNRESOLVED} unresolved DISCOVERY block(s) — each must end with → CAPTURED: <task-id> or → PROCESSED"
        fi
    fi
fi

# ── Output ────────────────────────────────────────────────────────────────
if [ -n "$WARNINGS" ]; then
    jq -n --arg reason "$(echo -e "🔍 END-OF-TURN CHECKS:${WARNINGS}")" '{
        stopReason: $reason
    }'
fi

exit 0
