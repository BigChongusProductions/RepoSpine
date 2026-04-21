#!/bin/bash
# Hook: Session End Safety Net (SessionEnd)
# Fires when a Claude Code session terminates.
# Warns on session-close hygiene issues, cleans scope state, closes stale plans.
#
# Checks:
#   1. Uncommitted changes exist
#   2. NEXT_SESSION.md not updated recently (or missing)
#   3. IN_PROGRESS tasks in db_queries.sh
#
# Side effects (best-effort, silent on failure):
#   - Remove .delegation_scope.json so next session starts with a fresh scope.
#   - Call mark_plan_done.sh if .active-plan marker is older than 4h (plan timeout).
#
# Returns: stopReason JSON with actionable warnings if issues found.
# Best-effort: no set -e; SessionEnd hooks that fail should not surface.

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"

INPUT=$(cat 2>/dev/null || echo '{}')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    exit 0
fi

WARNINGS=""

# ── Check 1: Uncommitted changes ──────────────────────────────────────────
if [ -d "$CWD/.git" ]; then
    DIRTY=$(cd "$CWD" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$DIRTY" -gt 0 ]; then
        WARNINGS="${WARNINGS}\n- ${DIRTY} uncommitted change(s) — commit or stash before ending the session"
    fi
fi

# ── Check 2: NEXT_SESSION.md freshness ────────────────────────────────────
NEXT_SESSION="$CWD/NEXT_SESSION.md"
if [ -f "$NEXT_SESSION" ]; then
    NOW=$(date +%s)
    MTIME=$(stat -c %Y "$NEXT_SESSION" 2>/dev/null || stat -f %m "$NEXT_SESSION" 2>/dev/null || echo "0")
    AGE_HOURS=$(( (NOW - MTIME) / 3600 ))
    if [ "$AGE_HOURS" -ge 1 ]; then
        WARNINGS="${WARNINGS}\n- NEXT_SESSION.md is ${AGE_HOURS}h old — run /handoff to update it"
    fi
else
    WARNINGS="${WARNINGS}\n- NEXT_SESSION.md missing — run /handoff to create the session handoff before leaving"
fi

# ── Check 3: IN_PROGRESS tasks not closed ─────────────────────────────────
if [ -f "$CWD/db_queries.sh" ]; then
    IN_PROGRESS=$(bash "$CWD/db_queries.sh" in-progress 2>/dev/null | grep -E '^[A-Z0-9-]+' | head -5 || true)
    if [ -n "$IN_PROGRESS" ]; then
        TASK_LIST=$(echo "$IN_PROGRESS" | tr '\n' ' ' | sed 's/ $//')
        WARNINGS="${WARNINGS}\n- IN_PROGRESS tasks not closed: ${TASK_LIST} — mark done or revert before ending"
    fi
fi

# ── Side effect: clean scope state (fresh accumulation next session) ──────
SCOPE_STATE="$CWD/.claude/hooks/.delegation_scope.json"
if [ -f "$SCOPE_STATE" ]; then
    rm -f "$SCOPE_STATE" 2>/dev/null || true
fi

# ── Side effect: close plans that exceeded their 4h useful lifetime ───────
PLAN_MARKER="$CWD/.claude/hooks/.active-plan"
MARK_PLAN_DONE="$CWD/.claude/hooks/mark_plan_done.sh"
if [ -f "$PLAN_MARKER" ] && [ -x "$MARK_PLAN_DONE" ]; then
    NOW=$(date +%s)
    PLAN_TS=$(sed -n '1p' "$PLAN_MARKER" 2>/dev/null || echo "0")
    PLAN_AGE=$((NOW - PLAN_TS))
    if [ "$PLAN_AGE" -gt 14400 ]; then    # 4h
        bash "$MARK_PLAN_DONE" "$CWD" >/dev/null 2>&1 || true
    fi
fi

# ── Emit warnings if any ──────────────────────────────────────────────────
if [ -n "$WARNINGS" ]; then
    jq -n --arg reason "$(printf 'SESSION-END SAFETY:\n%s' "$(echo -e "$WARNINGS")")" '{
        stopReason: $reason
    }'
fi

exit 0
