#!/usr/bin/env bash
# shared_signal.sh — Compute session signal from DB state
#
# Source this file, then call compute_signal.
# After calling, these variables are set:
#   SIGNAL          — GREEN, YELLOW, or RED
#   SIGNAL_REASONS  — newline-separated reasons (with emoji prefixes for display)
#   NEXT_TASK_ID, NEXT_TASK_PHASE, NEXT_TASK_TITLE, NEXT_TASK_BLOCKED
#
# Usage:
#   source "$DIR/shared_signal.sh"
#   compute_signal "$DB"

compute_signal() {
    local SIG_DB="$1"
    SIGNAL="GREEN"
    SIGNAL_REASONS=""

    # Next Claude task
    NEXT_CLAUDE_TASK=$(sqlite3 "$SIG_DB" "
        SELECT id || '|' || phase || '|' || title || '|' || COALESCE(blocked_by,'')
        FROM tasks
        WHERE status='TODO' AND assignee='CLAUDE'
          AND queue != 'INBOX'
        ORDER BY phase, sort_order
        LIMIT 1;
    " 2>/dev/null)

    NEXT_TASK_ID=$(echo "$NEXT_CLAUDE_TASK" | cut -d'|' -f1)
    NEXT_TASK_PHASE=$(echo "$NEXT_CLAUDE_TASK" | cut -d'|' -f2)
    NEXT_TASK_TITLE=$(echo "$NEXT_CLAUDE_TASK" | cut -d'|' -f3)
    NEXT_TASK_BLOCKED=$(echo "$NEXT_CLAUDE_TASK" | cut -d'|' -f4)

    # Prior phases incomplete → RED
    if [ -n "$NEXT_TASK_PHASE" ]; then
        local INCOMPLETE_PRIOR
        INCOMPLETE_PRIOR=$(sqlite3 "$SIG_DB" "
            SELECT phase || ' (' || COUNT(*) || ' task(s))'
            FROM tasks
            WHERE status NOT IN ('DONE','SKIP')
            AND COALESCE(track,'forward')='forward'
            AND phase < '$NEXT_TASK_PHASE'
            AND queue != 'INBOX'
            GROUP BY phase;
        " 2>/dev/null)
        if [ -n "$INCOMPLETE_PRIOR" ]; then
            SIGNAL="RED"
            SIGNAL_REASONS="${SIGNAL_REASONS}  ❌ Prior phase(s) have incomplete tasks: $INCOMPLETE_PRIOR\n"
        fi
    fi

    # Phase gates not passed → RED
    if [ -n "$NEXT_TASK_PHASE" ]; then
        local PHASES_BEFORE PB GATE_PASSED
        PHASES_BEFORE=$(sqlite3 "$SIG_DB" "
            SELECT DISTINCT phase FROM tasks WHERE phase < '$NEXT_TASK_PHASE' AND queue != 'INBOX' ORDER BY phase;
        " 2>/dev/null)
        for PB in $PHASES_BEFORE; do
            GATE_PASSED=$(sqlite3 "$SIG_DB" "SELECT COUNT(*) FROM phase_gates WHERE phase='$PB' AND gated_on IS NOT NULL;" 2>/dev/null)
            if [ "${GATE_PASSED:-0}" -eq 0 ]; then
                SIGNAL="RED"
                SIGNAL_REASONS="${SIGNAL_REASONS}  ❌ $PB phase gate not passed\n"
            fi
        done
    fi

    # Master/Gemini blockers
    local BLOCKER_COUNT UNBLOCKED_CLAUDE
    BLOCKER_COUNT=$(sqlite3 "$SIG_DB" "
        SELECT COUNT(DISTINCT b.id)
        FROM tasks t JOIN tasks b ON t.blocked_by = b.id
        WHERE t.status != 'DONE' AND t.assignee = 'CLAUDE'
          AND b.status != 'DONE' AND b.assignee IN ('MASTER', 'GEMINI');
    " 2>/dev/null)

    if [ "${BLOCKER_COUNT:-0}" -gt 0 ]; then
        UNBLOCKED_CLAUDE=$(sqlite3 "$SIG_DB" "
            SELECT COUNT(*) FROM tasks
            WHERE status='TODO' AND assignee='CLAUDE'
            AND (blocked_by IS NULL OR blocked_by = ''
                 OR blocked_by IN (SELECT id FROM tasks WHERE status IN ('DONE','SKIP'))
                 OR blocked_by NOT IN (SELECT id FROM tasks));
        " 2>/dev/null)
        if [ "${UNBLOCKED_CLAUDE:-0}" -eq 0 ]; then
            SIGNAL="RED"
            SIGNAL_REASONS="${SIGNAL_REASONS}  ❌ All Claude tasks are blocked by Master/Gemini\n"
        elif [ "$SIGNAL" != "RED" ]; then
            SIGNAL="YELLOW"
            SIGNAL_REASONS="${SIGNAL_REASONS}  ⚠️  Some Master/Gemini blockers exist but unblocked Claude tasks available\n"
        fi
    fi

    # S1 gate-critical loopback unresolved + unacknowledged → YELLOW
    local CB_UNACKED
    CB_UNACKED=$(sqlite3 "$SIG_DB" "
        SELECT COUNT(*) FROM tasks t
        LEFT JOIN loopback_acks la ON t.id = la.loopback_id
        WHERE t.track='loopback' AND t.severity=1 AND t.gate_critical=1
          AND t.status NOT IN ('DONE','SKIP')
          AND la.loopback_id IS NULL;
    " 2>/dev/null)
    if [ "${CB_UNACKED:-0}" -gt 0 ]; then
        [ "$SIGNAL" != "RED" ] && SIGNAL="YELLOW"
        SIGNAL_REASONS="${SIGNAL_REASONS}  ⚠️  $CB_UNACKED S1 circuit breaker(s) unacknowledged\n"
    fi

    # Next task cross-phase blocker → YELLOW
    if [ -n "$NEXT_TASK_BLOCKED" ]; then
        local BLOCKER_INFO BLOCKER_STATUS BLOCKER_PHASE
        BLOCKER_INFO=$(sqlite3 "$SIG_DB" "SELECT status || '|' || phase FROM tasks WHERE id='$NEXT_TASK_BLOCKED';" 2>/dev/null)
        BLOCKER_STATUS=$(echo "$BLOCKER_INFO" | cut -d'|' -f1)
        BLOCKER_PHASE=$(echo "$BLOCKER_INFO" | cut -d'|' -f2)
        if [ "$BLOCKER_STATUS" != "DONE" ] && [ "$BLOCKER_STATUS" != "SKIP" ]; then
            if [ -z "$BLOCKER_STATUS" ]; then
                [ "$SIGNAL" != "RED" ] && SIGNAL="YELLOW"
                SIGNAL_REASONS="${SIGNAL_REASONS}  ⚠️  Next task $NEXT_TASK_ID has stale blocked_by: $NEXT_TASK_BLOCKED (not found)\n"
            elif [ "$BLOCKER_PHASE" != "$NEXT_TASK_PHASE" ]; then
                [ "$SIGNAL" != "RED" ] && SIGNAL="YELLOW"
                SIGNAL_REASONS="${SIGNAL_REASONS}  ⚠️  Next task $NEXT_TASK_ID is blocked by $NEXT_TASK_BLOCKED (cross-phase)\n"
            fi
        fi
    fi
}
