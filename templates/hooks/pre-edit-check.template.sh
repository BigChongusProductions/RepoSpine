#!/bin/bash
# Pre-Edit Gate — consolidated check for Edit/Write tool calls (BP-012)
# Replaces: delegation-reminder (Tier 1) + protect-architecture (Tier 3) — both removed
# Single process, single JSON parse, single timeout.
#
# Order: increment delegation counter → architecture check → delegation check
# Architecture protection takes priority (always "ask" for protected files).
#
# State file: .claude/hooks/.delegation_state
# Format: line 1 = edit count, line 2 = last approval timestamp (epoch)
# Protected patterns: .claude/hooks/protected-files.conf

set -euo pipefail

INPUT=$(cat)

# Single jq parse for all needed fields
TOOL=$(echo "$INPUT" | jq -r '.tool_name')
CWD=$(echo "$INPUT" | jq -r '.cwd')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# ── DELEGATION COUNTER (always runs, even for protected files) ──────────────

STATE_FILE="$CWD/.claude/hooks/.delegation_state"

# Initialize state file if missing
if [ ! -f "$STATE_FILE" ]; then
    echo "0" > "$STATE_FILE"
    date +%s >> "$STATE_FILE"
fi

# Read state
EDIT_COUNT=$(sed -n '1p' "$STATE_FILE" 2>/dev/null || echo "0")
LAST_APPROVAL=$(sed -n '2p' "$STATE_FILE" 2>/dev/null || echo "0")

# Increment counter
EDIT_COUNT=$((EDIT_COUNT + 1))

# Write updated count back
echo "$EDIT_COUNT" > "$STATE_FILE"
echo "$LAST_APPROVAL" >> "$STATE_FILE"

# ── ARCHITECTURE PROTECTION (priority — short-circuits if match) ────────────

if [ -n "$FILE" ]; then
    CONF_FILE="$CWD/.claude/hooks/protected-files.conf"

    if [ -f "$CONF_FILE" ]; then
        # Read patterns from config (skip comments and blank lines)
        PATTERNS=()
        while IFS= read -r line; do
            line=$(echo "$line" | sed 's/#.*//' | xargs)  # strip comments + whitespace
            [ -n "$line" ] && PATTERNS+=("$line")
        done < "$CONF_FILE"
    else
        # Default protected patterns
        PATTERNS=(
            "CLAUDE.md"
            "_RULES.md"
            "AGENT_DELEGATION.md"
            "db_queries.sh"
            "coherence_registry.sh"
            "coherence_check.sh"
            "session_briefing.sh"
            "milestone_check.sh"
            "save_session.sh"
            "work.sh"
            "fix.sh"
            ".git/hooks/"
            "frameworks/"
        )
    fi

    # Check if the file matches any protected pattern
    BASENAME=$(basename "$FILE")
    for pattern in "${PATTERNS[@]}"; do
        if [[ "$FILE" == *"$pattern"* ]] || [[ "$BASENAME" == *"$pattern"* ]]; then
            jq -n --arg file "$BASENAME" --arg pattern "$pattern" '{
                hookSpecificOutput: {
                    hookEventName: "PreToolUse",
                    permissionDecision: "ask",
                    permissionDecisionReason: ("ARCHITECTURE PROTECTION: " + $file + " is a protected infrastructure file (matched: " + $pattern + "). Modifying it requires explicit human approval. Verify this change is intentional and won'\''t break the workflow engine.")
                }
            }'
            exit 0
        fi
    done
fi

# ── DELEGATION GATE ─────────────────────────────────────────────────────────

NOW=$(date +%s)
APPROVAL_AGE=$((NOW - LAST_APPROVAL))
APPROVAL_FRESH=false
if [ "$APPROVAL_AGE" -lt 1800 ]; then  # 30 minutes
    APPROVAL_FRESH=true
fi

if [ "$EDIT_COUNT" -ge 3 ] && [ "$APPROVAL_FRESH" = "false" ]; then
    # Escalate: 3+ file edits without delegation approval
    jq -n '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "ask",
            permissionDecisionReason: "DELEGATION GATE: 3+ file modifications detected without delegation approval. If this is a multi-step task (2+ subtasks or 3+ files), present a delegation table first. Run: bash mark_delegation_approved.sh to clear this gate after approval.\n\n📖 FRAMEWORK REQUIRED: Read delegation.md for the full 6-tier model table and assignment rules:\n  @frameworks/delegation.md"
        }
    }'
else
    # Advisory at milestone edit counts only — reduces token waste vs every-edit emission.
    # Threshold pattern validated in production across 60+ sessions.
    case "$EDIT_COUNT" in
        3|10|25|50)
            jq -n --arg count "$EDIT_COUNT" '{
                hookSpecificOutput: {
                    hookEventName: "PreToolUse",
                    additionalContext: ("DELEGATION GATE REMINDER (edit #" + $count + "): If this is part of a multi-step task (2+ subtasks or 3+ files), a delegation table must have been presented and approved. ROUTING: For delegation framework: templates/frameworks/delegation.md")
                }
            }'
            ;;
    esac
fi
