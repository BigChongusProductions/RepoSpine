#!/bin/bash
# Hook: Sub-Agent Escalation Tracker (SubagentStop)
# Fires after a sub-agent completes.
# Parses last_assistant_message to detect failures and increments per-tier
# failure counters. Also flags completion claims that lack test evidence.
#
# State files (in $CWD/.claude/hooks/):
#   .last_spawn_tier     — written by SubagentStart hook; single line: haiku|sonnet|opus
#   .escalation_state    — one line per tier: tier|failure_count|last_failure_epoch|last_failure_reason
#
# Returns: additionalContext (top-level, not hookSpecificOutput — SubagentStop
#          does not support hookSpecificOutput; output would be silently dropped)

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"

set -euo pipefail

INPUT=$(cat)

# ── Parse stdin (single jq call) ────────────────────────────────────────────

MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Fallback CWD
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    CWD="$(pwd)"
fi

HOOKS_DIR="$CWD/.claude/hooks"
TIER_FILE="$HOOKS_DIR/.last_spawn_tier"
STATE_FILE="$HOOKS_DIR/.escalation_state"

# ── Guard: tier file must exist to track anything ────────────────────────────

if [ ! -f "$TIER_FILE" ]; then
    exit 0
fi

TIER=$(cat "$TIER_FILE" 2>/dev/null | tr -d '[:space:]')

# Validate tier value
case "$TIER" in
    haiku|sonnet|opus) ;;
    *) exit 0 ;;
esac

# ── Initialise state file if missing ────────────────────────────────────────

if [ ! -f "$STATE_FILE" ]; then
    mkdir -p "$HOOKS_DIR"
    printf 'haiku|0|0|\nsonnet|0|0|\nopus|0|0|\n' > "$STATE_FILE"
fi

# ── Function 1: Failure Detection ───────────────────────────────────────────

FAILURE_DETECTED=false
FAILURE_REASON=""

# Empty or very short message — likely truncated/crashed
MSG_LEN=${#MSG}
if [ -z "$MSG" ] || [ "$MSG_LEN" -lt 50 ]; then
    FAILURE_DETECTED=true
    if [ -z "$MSG" ]; then
        FAILURE_REASON="empty last_assistant_message"
    else
        FAILURE_REASON="message too short (${MSG_LEN} chars) — likely truncated"
    fi
fi

# Pattern-based failure detection (only run if not already flagged)
if [ "$FAILURE_DETECTED" = "false" ]; then
    # Check each line: match failure pattern but skip negation lines
    FAILURE_LINE=""
    while IFS= read -r line; do
        # Skip lines that are negations / error-handling context
        if echo "$line" | grep -qiE '(no error|0 error|error.free|without error|error handling|errors found: 0|not.an.error)'; then
            continue
        fi
        # Match failure indicators as whole words/phrases
        if echo "$line" | grep -qiE '\b(error|failed|failure|could not|unable to|exception|traceback)\b'; then
            FAILURE_LINE="$line"
            break
        fi
    done <<< "$MSG"

    if [ -n "$FAILURE_LINE" ]; then
        FAILURE_DETECTED=true
        # Truncate to first 80 chars for reason field
        FAILURE_REASON="${FAILURE_LINE:0:80}"
    fi
fi

# ── On failure: update escalation state ─────────────────────────────────────

if [ "$FAILURE_DETECTED" = "true" ]; then
    NOW=$(date +%s)

    # Read current state for this tier
    CURRENT_COUNT=0
    OTHER_LINES=""

    while IFS= read -r line; do
        LINE_TIER=$(echo "$line" | cut -d'|' -f1)
        if [ "$LINE_TIER" = "$TIER" ]; then
            CURRENT_COUNT=$(echo "$line" | cut -d'|' -f2)
            # Ensure it's a number
            CURRENT_COUNT=$(echo "$CURRENT_COUNT" | grep -E '^[0-9]+$' || echo "0")
        else
            if [ -n "$OTHER_LINES" ]; then
                OTHER_LINES="${OTHER_LINES}
${line}"
            else
                OTHER_LINES="$line"
            fi
        fi
    done < "$STATE_FILE"

    NEW_COUNT=$(( CURRENT_COUNT + 1 ))

    # Sanitise reason for pipe-delimited storage (strip pipe chars)
    SAFE_REASON=$(echo "$FAILURE_REASON" | tr '|' ' ')

    # Write updated state (preserve order: haiku, sonnet, opus)
    {
        # Re-emit all non-target tiers from existing file first to preserve them
        while IFS= read -r line; do
            LINE_TIER=$(echo "$line" | cut -d'|' -f1)
            if [ "$LINE_TIER" != "$TIER" ]; then
                echo "$line"
            fi
        done < "$STATE_FILE"
        # Emit updated tier line
        echo "${TIER}|${NEW_COUNT}|${NOW}|${SAFE_REASON}"
    } | sort > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

    # Determine escalation target
    case "$TIER" in
        haiku)  NEXT_TIER="sonnet" ;;
        sonnet) NEXT_TIER="opus"   ;;
        opus)   NEXT_TIER="opus"   ;;
    esac

    # Build escalation message
    THRESHOLD=2
    if [ "$NEW_COUNT" -ge "$THRESHOLD" ]; then
        ESCALATION_MSG="ESCALATION LOG: ${TIER} failed on sub-agent task.
Failure count: ${NEW_COUNT}/${THRESHOLD}. Reason: ${SAFE_REASON}
THRESHOLD REACHED — use ${NEXT_TIER} for remaining tasks."
    else
        ESCALATION_MSG="ESCALATION LOG: ${TIER} failed on sub-agent task.
Failure count: ${NEW_COUNT}/${THRESHOLD}. Reason: ${SAFE_REASON}
Next tier on next failure: ${NEXT_TIER}."
    fi

    jq -n --arg ctx "$ESCALATION_MSG" '{
        additionalContext: $ctx
    }'
    exit 0
fi

# ── Function 2: Proof-of-Completion Advisory ────────────────────────────────

# Check for completion claims
HAS_CLAIM=false
if echo "$MSG" | grep -qiE '\b(done|completed?|fixed|implemented|finished)\b'; then
    HAS_CLAIM=true
fi

if [ "$HAS_CLAIM" = "true" ]; then
    # Check for test evidence markers
    HAS_EVIDENCE=false
    if echo "$MSG" | grep -qiE '(PASS|OK|assert|test_|✓|0 fail|pass(ed)?|all .* pass)'; then
        HAS_EVIDENCE=true
    fi

    if [ "$HAS_EVIDENCE" = "false" ]; then
        jq -n '{
            additionalContext: "WARNING PROOF CHECK: Sub-agent claims completion without visible test evidence. Verify before marking done."
        }'
        exit 0
    fi
fi

# No issues detected — exit silently
exit 0
