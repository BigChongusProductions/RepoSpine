#!/bin/bash
# Hook: Agent Spawn Gate (PreToolUse → Agent)
# Fires before every Agent tool call.
# Primary enforcement mechanism for delegation rules — can BLOCK sub-agent spawns.
#
# Replaces: subagent-delegation-check.template.sh's advisory-only approach for agent launches.
# This hook enforces hard blocks when required, not just warnings.
#
# Event:   PreToolUse
# Matcher: Agent
# Timeout: 5s
#
# Checks (in order):
#   1. Delegation approval freshness (30-min window)
#   2. Pre-task check enforcement (db_queries.sh check must be recent, <5 min)
#   3. CONFIRM bypass prevention (CONFIRM verdict requires explicit confirm call)
#   4. Escalation enforcement (tier failed 2x → deny; 1x → warn)
#
# State files (all in $CWD/.claude/hooks/):
#   .delegation_state       — line 1: edit count, line 2: last approval epoch
#   .last_check_result      — format: verdict|timestamp|task_id
#   .last_confirm_timestamp — format: timestamp|task_id
#   .escalation_state       — format: tier|count|epoch|reason (one line per tier)
#   .last_spawn_tier        — records requested tier on allow

set -euo pipefail

INPUT=$(cat)

# Single jq parse for all needed fields
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')
DESCRIPTION=$(echo "$INPUT" | jq -r '.tool_input.description // empty')
SUBAGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty')
REQUESTED_TIER=$(echo "$INPUT" | jq -r '.tool_input.model // empty')

# Validate we have a working directory
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    exit 0
fi

HOOKS_DIR="$CWD/.claude/hooks"

# ── HELPER: next_tier ─────────────────────────────────────────────────────────

next_tier() {
    case "$1" in
        haiku)  echo "sonnet" ;;
        sonnet) echo "opus" ;;
        opus)   echo "opus" ;;
    esac
}

# ── MISSING MODEL / NAMED AGENT TYPES ─────────────────────────────────────────
# If no explicit model is set, or subagent_type is a named type (Explore, Plan, etc.)
# without a model, emit advisory only — do NOT block.

if [ -z "$REQUESTED_TIER" ]; then
    ADVISORY_MSG="Agent spawned without explicit tier — escalation tracking won't apply."
    if [ -n "$SUBAGENT_TYPE" ] && [ "$SUBAGENT_TYPE" != "general-purpose" ]; then
        ADVISORY_MSG="Agent spawned as named type '${SUBAGENT_TYPE}' without explicit model — escalation tracking won't apply."
    fi
    jq -n --arg msg "$ADVISORY_MSG" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            additionalContext: $msg
        }
    }'
    exit 0
fi

# ── CHECK 1: DELEGATION APPROVAL FRESHNESS ────────────────────────────────────

DELEGATION_FILE="$HOOKS_DIR/.delegation_state"
NOW=$(date +%s)

if [ ! -f "$DELEGATION_FILE" ]; then
    jq -n '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "ask",
            permissionDecisionReason: "DELEGATION GATE: No delegation approval found for this session. Present a delegation table and run: bash mark_delegation_approved.sh — then retry spawning the sub-agent."
        }
    }'
    exit 0
fi

LAST_APPROVAL=$(sed -n '2p' "$DELEGATION_FILE" 2>/dev/null || echo "0")
# Guard: treat empty or non-numeric as 0
if ! [[ "$LAST_APPROVAL" =~ ^[0-9]+$ ]]; then
    LAST_APPROVAL=0
fi

# Guard: epoch 0 means never approved — treat as "no approval" rather than computing broken age
if [ "$LAST_APPROVAL" -eq 0 ]; then
    jq -n '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            additionalContext: "DELEGATION ADVISORY: No delegation approval recorded. Consider running: bash mark_delegation_approved.sh"
        }
    }'
    exit 0
fi

APPROVAL_AGE=$((NOW - LAST_APPROVAL))

if [ "$APPROVAL_AGE" -gt 1800 ]; then
    AGE_MIN=$((APPROVAL_AGE / 60))
    jq -n --arg age "${AGE_MIN}m ago" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "ask",
            permissionDecisionReason: ("DELEGATION GATE: Delegation approval has expired (last approved " + $age + "). Present a delegation table and run: bash mark_delegation_approved.sh — then retry.")
        }
    }'
    exit 0
fi

# ── CHECK 2: PRE-TASK CHECK ENFORCEMENT ───────────────────────────────────────

CHECK_FILE="$HOOKS_DIR/.last_check_result"

if [ ! -f "$CHECK_FILE" ]; then
    jq -n '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "ask",
            permissionDecisionReason: "PRE-TASK CHECK REQUIRED: Run db_queries.sh check <task-id> before spawning sub-agents. No check result found for this session."
        }
    }'
    exit 0
fi

# Parse verdict|timestamp|task_id
CHECK_RAW=$(cat "$CHECK_FILE" 2>/dev/null || echo "")
CHECK_VERDICT=$(echo "$CHECK_RAW" | cut -d'|' -f1)
CHECK_TS=$(echo "$CHECK_RAW" | cut -d'|' -f2)
CHECK_TASK=$(echo "$CHECK_RAW" | cut -d'|' -f3)

# Guard: treat empty or non-numeric timestamp as 0
if ! [[ "$CHECK_TS" =~ ^[0-9]+$ ]]; then
    CHECK_TS=0
fi

CHECK_AGE=$((NOW - CHECK_TS))

if [ "$CHECK_AGE" -gt 300 ]; then
    TASK_HINT="${CHECK_TASK:-<task-id>}"
    jq -n --arg task "$TASK_HINT" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "ask",
            permissionDecisionReason: ("PRE-TASK CHECK STALE: Last check result is >5 minutes old. Run db_queries.sh check " + $task + " before spawning sub-agents.")
        }
    }'
    exit 0
fi

# ── CHECK 3: CONFIRM BYPASS PREVENTION ────────────────────────────────────────

if [ "$CHECK_VERDICT" = "CONFIRM" ]; then
    CONFIRM_FILE="$HOOKS_DIR/.last_confirm_timestamp"
    TASK_HINT="${CHECK_TASK:-<task-id>}"

    # Deny if confirm file missing entirely
    if [ ! -f "$CONFIRM_FILE" ]; then
        jq -n --arg task "$TASK_HINT" '{
            hookSpecificOutput: {
                hookEventName: "PreToolUse",
                permissionDecision: "deny",
                permissionDecisionReason: ("CONFIRM GATE: Pre-task check returned CONFIRM. Handle the milestone gate first: db_queries.sh confirm " + $task)
            }
        }'
        exit 0
    fi

    # Parse timestamp|task_id from confirm file
    CONFIRM_RAW=$(cat "$CONFIRM_FILE" 2>/dev/null || echo "")
    CONFIRM_TS=$(echo "$CONFIRM_RAW" | cut -d'|' -f1)

    if ! [[ "$CONFIRM_TS" =~ ^[0-9]+$ ]]; then
        CONFIRM_TS=0
    fi

    # Deny if confirm timestamp is older than (or equal to) the check timestamp
    # i.e., the confirm happened before the most recent check — not yet confirmed for THIS check
    if [ "$CONFIRM_TS" -le "$CHECK_TS" ]; then
        jq -n --arg task "$TASK_HINT" '{
            hookSpecificOutput: {
                hookEventName: "PreToolUse",
                permissionDecision: "deny",
                permissionDecisionReason: ("CONFIRM GATE: Pre-task check returned CONFIRM and gate has not been acknowledged. Handle the milestone gate first: db_queries.sh confirm " + $task)
            }
        }'
        exit 0
    fi
fi

# ── CHECK 4: ESCALATION ENFORCEMENT ──────────────────────────────────────────

ESC_FILE="$HOOKS_DIR/.escalation_state"

# Initialize if missing
if [ ! -f "$ESC_FILE" ]; then
    printf 'haiku|0|0|\nsonnet|0|0|\nopus|0|0|\n' > "$ESC_FILE"
fi

# Read the line matching REQUESTED_TIER, with corruption guard
TIER_LINE=$(grep "^${REQUESTED_TIER}|" "$ESC_FILE" 2>/dev/null || echo "")

if [ -z "$TIER_LINE" ]; then
    # Tier not found in file — possibly corrupt; reset to zeros
    printf 'haiku|0|0|\nsonnet|0|0|\nopus|0|0|\n' > "$ESC_FILE"
    TIER_LINE="${REQUESTED_TIER}|0|0|"
fi

# Parse tier|count|epoch|reason
TIER_COUNT=$(echo "$TIER_LINE" | cut -d'|' -f2)
TIER_REASON=$(echo "$TIER_LINE" | cut -d'|' -f4)

# Guard against corrupt count
if ! [[ "$TIER_COUNT" =~ ^[0-9]+$ ]]; then
    # Corrupt state — reset
    printf 'haiku|0|0|\nsonnet|0|0|\nopus|0|0|\n' > "$ESC_FILE"
    TIER_COUNT=0
fi

if [ "$TIER_COUNT" -ge 2 ]; then
    NEXT=$(next_tier "$REQUESTED_TIER")
    if [ "$REQUESTED_TIER" = "opus" ]; then
        jq -n --arg tier "$REQUESTED_TIER" '{
            hookSpecificOutput: {
                hookEventName: "PreToolUse",
                permissionDecision: "deny",
                permissionDecisionReason: ("ESCALATION REQUIRED: " + $tier + " failed 2x. Opus is the highest tier — handle directly or reassign task.")
            }
        }'
    else
        jq -n --arg tier "$REQUESTED_TIER" --arg next "$NEXT" '{
            hookSpecificOutput: {
                hookEventName: "PreToolUse",
                permissionDecision: "deny",
                permissionDecisionReason: ("ESCALATION REQUIRED: " + $tier + " failed 2x. Use " + $next + ".")
            }
        }'
    fi
    exit 0
fi

if [ "$TIER_COUNT" -eq 1 ]; then
    # Advisory warning — non-blocking
    NEXT=$(next_tier "$REQUESTED_TIER")
    WARN_MSG="has 1 prior failure this session. If this attempt also fails, escalate to ${NEXT}."
    if [ -n "$TIER_REASON" ]; then
        WARN_MSG="has 1 prior failure this session (reason: ${TIER_REASON}). If this attempt also fails, escalate to ${NEXT}."
    fi
    # Record spawn tier before warning output
    echo "$REQUESTED_TIER" > "$HOOKS_DIR/.last_spawn_tier"
    jq -n --arg tier "$REQUESTED_TIER" --arg warn "$WARN_MSG" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            additionalContext: ("WARNING: " + $tier + " " + $warn)
        }
    }'
    exit 0
fi

# ── ALL CHECKS PASSED ────────────────────────────────────────────────────────

# ── BUILD ADVISORY CONTEXT (LESSONS + parallel-work guard) ───────────────────

ADVISORY=""

# LESSONS injection — enrich sub-agent with recent project corrections
LESSONS_FILE=""
for candidate in "$CWD"/LESSONS_*.md "$CWD"/LESSONS.md; do
    if [ -f "$candidate" ]; then
        LESSONS_FILE="$candidate"
        break
    fi
done

if [ -n "$LESSONS_FILE" ]; then
    FILE_SIZE=$(wc -c < "$LESSONS_FILE" 2>/dev/null || echo "0")
    # Strip whitespace from wc output (macOS wc pads with spaces)
    FILE_SIZE=$(echo "$FILE_SIZE" | tr -d ' ')
    if [ "$FILE_SIZE" -lt 20480 ]; then
        RECENT_LESSONS=$(tail -30 "$LESSONS_FILE" 2>/dev/null || echo "")
    else
        RECENT_LESSONS=$(tail -15 "$LESSONS_FILE" 2>/dev/null || echo "")
        RECENT_LESSONS="[truncated — file >20KB, showing last 15 lines]
${RECENT_LESSONS}"
    fi
    if [ -n "$RECENT_LESSONS" ]; then
        ADVISORY="RECENT PROJECT LESSONS (avoid repeating these patterns):
${RECENT_LESSONS}"
    fi
fi

# Parallel-work guard — check BEFORE updating .last_spawn_tier
LAST_SPAWN_FILE="$HOOKS_DIR/.last_spawn_tier"
if [ -f "$LAST_SPAWN_FILE" ]; then
    LAST_SPAWN_MTIME=$(stat -f %m "$LAST_SPAWN_FILE" 2>/dev/null || stat -c %Y "$LAST_SPAWN_FILE" 2>/dev/null || echo "0")
    SPAWN_AGE=$((NOW - LAST_SPAWN_MTIME))

    if [ "$SPAWN_AGE" -lt 300 ]; then
        PRIOR_TIER=$(cat "$LAST_SPAWN_FILE" 2>/dev/null || echo "unknown")
        PARALLEL_MSG="⚠️ PARALLEL WORK: Another ${PRIOR_TIER} agent was spawned ${SPAWN_AGE}s ago. Use 'done --files <file1> <file2>' when marking tasks complete to prevent cross-contamination in auto-commits."
        if [ -n "$ADVISORY" ]; then
            ADVISORY="${ADVISORY}

${PARALLEL_MSG}"
        else
            ADVISORY="$PARALLEL_MSG"
        fi
    fi
fi

# Record spawn tier (AFTER guard check)
echo "$REQUESTED_TIER" > "$HOOKS_DIR/.last_spawn_tier"

# Emit advisory context (or silent allow)
if [ -n "$ADVISORY" ]; then
    jq -n --arg ctx "$ADVISORY" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            additionalContext: $ctx
        }
    }'
fi
exit 0
