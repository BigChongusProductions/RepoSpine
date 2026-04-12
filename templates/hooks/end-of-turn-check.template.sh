#!/bin/bash
# Hook: End-of-Turn Verification (Stop)
# Fires after Claude finishes responding.
# Checks for common session hygiene issues and injects warnings.
#
# Replaces: nothing (new capability)
#
# Returns: additionalContext with warnings (non-blocking)
# Only fires if issues are detected — silent when clean.

set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Fallback CWD
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    exit 0
fi

WARNINGS=""

# Check 1: Large number of uncommitted changes
if [ -d "$CWD/.git" ]; then
    DIRTY=$(cd "$CWD" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$DIRTY" -gt 10 ]; then
        WARNINGS="${WARNINGS}\n- 📁 ${DIRTY} uncommitted files — consider committing before continuing"
    fi
fi

# Check 2: High edit count without delegation approval
STATE_FILE="$CWD/.claude/hooks/.delegation_state"
if [ -f "$STATE_FILE" ]; then
    EDIT_COUNT=$(sed -n '1p' "$STATE_FILE" 2>/dev/null || echo "0")
    LAST_APPROVAL=$(sed -n '2p' "$STATE_FILE" 2>/dev/null || echo "0")
    NOW=$(date +%s)
    APPROVAL_AGE=$((NOW - LAST_APPROVAL))

    if [ "$EDIT_COUNT" -gt 8 ] && [ "$APPROVAL_AGE" -gt 1800 ]; then
        WARNINGS="${WARNINGS}\n- ✏️ ${EDIT_COUNT} edits this session without delegation approval — is this still a single-task scope?"
    fi
fi

# Check 3: NEXT_SESSION.md very stale (>24h) — reminder to save
if [ -f "$CWD/NEXT_SESSION.md" ]; then
    NOW=$(date +%s)
    MTIME=$(stat -c %Y "$CWD/NEXT_SESSION.md" 2>/dev/null || stat -f %m "$CWD/NEXT_SESSION.md" 2>/dev/null || echo "0")
    AGE_HOURS=$(( (NOW - MTIME) / 3600 ))
    if [ "$AGE_HOURS" -gt 24 ]; then
        WARNINGS="${WARNINGS}\n- 📋 NEXT_SESSION.md is ${AGE_HOURS}h old — save session when ready"
    fi
fi

# Check 4: Dogfood check — read cached health verdict (no subprocess spawn)
# Format contract: epoch_timestamp|exit_code|verdict (written by `health` command)
# See refs/hook-state-formats.md for all state file formats.
HEALTH_CACHE="$CWD/.claude/hooks/.health_cache"
if [ -f "$HEALTH_CACHE" ]; then
    CACHE_LINE=$(cat "$HEALTH_CACHE")
    CACHE_TS=$(echo "$CACHE_LINE" | cut -d'|' -f1)
    CACHE_EXIT=$(echo "$CACHE_LINE" | cut -d'|' -f2)
    NOW=$(date +%s)
    CACHE_AGE=$((NOW - CACHE_TS))
    if [ "$CACHE_AGE" -lt 600 ] && [ "$CACHE_EXIT" != "0" ]; then
        CACHE_VERDICT=$(echo "$CACHE_LINE" | cut -d'|' -f3)
        WARNINGS="${WARNINGS}\n- DOGFOOD ALERT: last health check failed ($CACHE_VERDICT)"
    fi
fi

# Check 5: Last checked task not marked done
# Reads .last_check_result (written by db_queries.sh check) — format: verdict|timestamp|task_id
TASK_FILE="$CWD/.claude/hooks/.last_check_result"
if [ -f "$TASK_FILE" ]; then
    STARTED_TASK=$(cut -d'|' -f3 "$TASK_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$STARTED_TASK" ] && [ -f "$CWD/db_queries.sh" ]; then
        TASK_STATUS=$(bash "$CWD/db_queries.sh" task "$STARTED_TASK" 2>/dev/null | sed -n 's/.*Status: *\([^ ]*\).*/\1/p' | head -1)
        TASK_STATUS="${TASK_STATUS:-unknown}"
        if [ "$TASK_STATUS" != "DONE" ] && [ "$TASK_STATUS" != "SKIP" ] && [ "$TASK_STATUS" != "WONTFIX" ] && [ "$TASK_STATUS" != "unknown" ]; then
            WARNINGS="${WARNINGS}\n- Task ${STARTED_TASK} was started but not marked DONE — run: bash db_queries.sh done ${STARTED_TASK}"
        fi
    fi
fi

# Check 6 (optional): Unresolved discovery blocks
# Enable via DISCOVERY_TRACKING=1 in your environment or hook wrapper.
# Scans for ⚡ DISCOVERY: tags without matching → CAPTURED: or → PROCESSED resolutions.
if [ "${DISCOVERY_TRACKING:-0}" = "1" ]; then
    LAST_MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)
    if [ -n "$LAST_MSG" ]; then
        DISC_COUNT=$(echo "$LAST_MSG" | grep -c '⚡ DISCOVERY:' 2>/dev/null || true)
        CAP_COUNT=$(echo "$LAST_MSG" | grep -cE '→ (CAPTURED|PROCESSED)' 2>/dev/null || true)
        UNRESOLVED=$((DISC_COUNT - CAP_COUNT))
        if [ "$UNRESOLVED" -gt 0 ]; then
            WARNINGS="${WARNINGS}\n- ⚡ ${UNRESOLVED} unresolved discovery block(s) — capture or dismiss before continuing"
        fi
    fi
fi

# Only output if we have warnings
if [ -n "$WARNINGS" ]; then
    jq -n --arg reason "$(echo -e "🔍 END-OF-TURN CHECKS:${WARNINGS}")" '{
        stopReason: $reason
    }'
fi

exit 0
