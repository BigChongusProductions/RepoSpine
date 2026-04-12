#!/bin/bash
# Hook: Permission Denied Tracker (PermissionDenied)
# Fires when a sub-agent's Bash tool call is denied by the user.
# Increments the failure counter for the currently-active sub-agent tier.
# This is a hard blocker — the sub-agent cannot proceed without approval.
#
# State files (in $CWD/.claude/hooks/):
#   .last_spawn_tier     — written by SubagentStart hook; single line: haiku|sonnet|opus
#   .escalation_state    — one line per tier: tier|failure_count|last_failure_epoch|last_failure_reason
#
# Returns: additionalContext (top-level only — PermissionDenied does not support
#          hookSpecificOutput; hookSpecificOutput would be silently dropped)
#
# Timeout: 5s (no DB queries, minimal processing)

set -euo pipefail

INPUT=$(cat)

# ── Parse stdin ────────────────────────────────────────────────────────────────

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
REASON=$(echo "$INPUT" | jq -r '.reason // "unknown"')
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

# ── Update escalation state ─────────────────────────────────────────────────

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

# Build failure reason
FAILURE_REASON="PermissionDenied: ${TOOL_NAME}"
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

# ── Build advisory message ──────────────────────────────────────────────────

THRESHOLD=2

if [ "$NEW_COUNT" -ge "$THRESHOLD" ]; then
    ESCALATION_MSG="AUTO-MODE DENIAL during ${TIER} sub-agent: ${TOOL_NAME} — User denied permission. Failure count for ${TIER}: ${NEW_COUNT}/${THRESHOLD}. THRESHOLD REACHED — escalate to next tier."
else
    ESCALATION_MSG="AUTO-MODE DENIAL during ${TIER} sub-agent: ${TOOL_NAME} — User denied permission. Failure count for ${TIER}: ${NEW_COUNT}/${THRESHOLD}."
fi

jq -n --arg ctx "$ESCALATION_MSG" '{
    additionalContext: $ctx
}'
