#!/bin/bash
# Hook: Post-Compaction Context Recovery (PostCompact)
# Fires after context compaction (manual /compact or auto at 95% capacity).
# Re-injects critical behavioral rules and compact state that may have been
# summarized away. Uses session_briefing.py --compact for minimal token cost.
#
# Returns: additionalContext with critical rules + compact current state

set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    CWD="$(pwd)"
fi

# Read delegation state
EDIT_COUNT=0
APPROVAL_STATUS="unknown"
STATE_FILE="$CWD/.claude/hooks/.delegation_state"
if [ -f "$STATE_FILE" ]; then
    EDIT_COUNT=$(sed -n '1p' "$STATE_FILE" 2>/dev/null || echo "0")
    LAST_APPROVAL=$(sed -n '2p' "$STATE_FILE" 2>/dev/null || echo "0")
    NOW=$(date +%s)
    AGE=$(( (NOW - LAST_APPROVAL) / 60 ))
    if [ "$AGE" -lt 30 ]; then
        APPROVAL_STATUS="approved ${AGE}m ago"
    else
        APPROVAL_STATUS="expired (${AGE}m ago)"
    fi
fi

# Read escalation state
ESC_SUMMARY="No escalations this session."
ESC_FILE="$CWD/.claude/hooks/.escalation_state"
if [ -f "$ESC_FILE" ]; then
    ACTIVE=$(awk -F'|' '$2 > 0 {printf "  %s: %s failure(s)\n", $1, $2}' "$ESC_FILE")
    if [ -n "$ACTIVE" ]; then
        ESC_SUMMARY="Active escalations:\n${ACTIVE}\nRule: tier fails 2x → agent-spawn-gate blocks. haiku→sonnet→opus."
    fi
fi

# Read last check result
CHECK_STATUS="No pre-task check on record."
CHECK_FILE="$CWD/.claude/hooks/.last_check_result"
if [ -f "$CHECK_FILE" ]; then
    CHECK_STATUS="Last check: $(cat "$CHECK_FILE")"
fi

# Compact briefing from Python
BRIEFING="(unavailable)"
BRIEFING_PY="$CWD/scripts/session_briefing.py"
if [ -f "$BRIEFING_PY" ]; then
    BRIEFING=$(PROJECT_DB=%%PROJECT_DB%% python3 "$BRIEFING_PY" --compact 2>/dev/null) || BRIEFING="(query failed)"
fi

# Build recovery context
CONTEXT="POST-COMPACTION CONTEXT RECOVERY

## Critical Rules (these survive compaction)
1. CORRECTION GATE: If user indicates something failed/is wrong → FIRST action is: bash db_queries.sh log-lesson
2. DELEGATION GATE: 2+ subtasks or 3+ files → present delegation table FIRST, wait for approval
3. PRE-TASK CHECK: Run bash db_queries.sh check <id> before each task — obey STOP verdicts
4. DB PROTECTION: NEVER write to %%PROJECT_DB%% directly — always use db_queries.sh
5. PHASE GATE: Don't cross phase boundaries without bash db_queries.sh gate-pass

## Current State
- Briefing: ${BRIEFING}
- Delegation: edit #${EDIT_COUNT}, approval ${APPROVAL_STATUS}
- Escalation: $(echo -e "$ESC_SUMMARY")
- Pre-task check: ${CHECK_STATUS}

## Available Frameworks (NOT auto-imported — load on demand)
- correction-protocol.md — WHEN: correction signal in user message
  Read: frameworks/correction-protocol.md
- delegation.md — WHEN: starting a multi-step task
  Read: frameworks/delegation.md
- phase-gates.md — WHEN: running pre-task check or crossing a phase boundary
  Read: frameworks/phase-gates.md

Optional: coherence-system, falsification, loopback-system, quality-gates, visual-verification
  Path pattern: frameworks/<name>.md

%%AGENT_NAMES%%"

jq -n --arg ctx "$CONTEXT" '{
    additionalContext: $ctx
}'
