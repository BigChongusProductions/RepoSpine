#!/bin/bash
# Pre-Edit Gate — consolidated check for Edit/Write/MultiEdit tool calls.
# Combines: architecture protection + scope-aware delegation advisory.
# Single process, single JSON parse.
#
# Order: architecture check → record scope contribution → advisory emission.
# Architecture protection takes priority (always "ask" for protected files).
#
# State:
#   .claude/hooks/.delegation_scope.json    — scope tracker (via lib)
#   .claude/hooks/.delegation_state         — legacy edit counter + approval ts
#   .claude/hooks/.active-plan              — plan-mode suppression marker
#
# Protected patterns: .claude/hooks/protected-files.conf

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"
# Scope tracker
source "$(dirname "${BASH_SOURCE[0]}")/lib-scope-counter.sh"

set -euo pipefail

INPUT=$(cat)

# Single jq parse for all needed fields
TOOL=$(echo "$INPUT" | jq -r '.tool_name')
CWD=$(echo "$INPUT" | jq -r '.cwd')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
OLD_STRING=$(echo "$INPUT" | jq -r '.tool_input.old_string // empty')
NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')

# ── Legacy edit-count state (kept for backward compat with existing hooks) ──

STATE_FILE="$CWD/.claude/hooks/.delegation_state"
if [ ! -f "$STATE_FILE" ]; then
    echo "0" > "$STATE_FILE"
    echo "0" >> "$STATE_FILE"
fi
EDIT_COUNT=$(sed -n '1p' "$STATE_FILE" 2>/dev/null || echo "0")
LAST_APPROVAL=$(sed -n '2p' "$STATE_FILE" 2>/dev/null || echo "0")
EDIT_COUNT=$((EDIT_COUNT + 1))
echo "$EDIT_COUNT" > "$STATE_FILE"
echo "$LAST_APPROVAL" >> "$STATE_FILE"

# ── ARCHITECTURE PROTECTION (priority — short-circuits if match) ────────────

if [ -n "$FILE" ]; then
    CONF_FILE="$CWD/.claude/hooks/protected-files.conf"

    if [ -f "$CONF_FILE" ]; then
        PATTERNS=()
        while IFS= read -r line; do
            line=$(echo "$line" | sed 's/#.*//' | xargs)
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

# ── SCOPE TRACKER + DELEGATION ADVISORY ─────────────────────────────────────
#
# Replaces the old stateless {3,10,25,50} edit-count ladder with scope-aware
# tracking. Advisory fires ONCE per task-boundary when scope crosses any of:
#   - 3 files AND 50 lines total
#   - 4 files (regardless of line count)
#   - 100 lines in a single file
# Retries (same old_string → new_string) dedupe by sha1; they do not inflate
# the counters.

export SCOPE_STATE_FILE="$CWD/.claude/hooks/.delegation_scope.json"
export SCOPE_HISTORY_FILE="$CWD/.claude/hooks/.scope_history.jsonl"

# Record this tool call's contribution to scope.
if [ -n "$FILE" ]; then
    if [ "$TOOL" = "Edit" ] || [ "$TOOL" = "MultiEdit" ]; then
        [ -n "$OLD_STRING" ] && scope_record "$FILE" "$OLD_STRING" "$NEW_STRING" || true
    elif [ "$TOOL" = "Write" ]; then
        [ -n "$NEW_CONTENT" ] && scope_record_write "$FILE" "$NEW_CONTENT" || true
    fi
fi

NOW=$(date +%s)
APPROVAL_AGE=$((NOW - LAST_APPROVAL))
APPROVAL_FRESH=false
if [ "$APPROVAL_AGE" -lt 1800 ]; then  # 30 minutes
    APPROVAL_FRESH=true
fi

# Plan-marker suppression (longer-horizon than 30-min approval TTL).
# Set via mark_plan_active.sh after ExitPlanMode for plans > 30 min.
PLAN_MARKER="$CWD/.claude/hooks/.active-plan"
PLAN_ACTIVE=false
if [ -f "$PLAN_MARKER" ]; then
    PLAN_TS=$(sed -n '1p' "$PLAN_MARKER" 2>/dev/null || echo "0")
    PLAN_AGE=$((NOW - PLAN_TS))
    if [ "$PLAN_AGE" -lt 21600 ]; then  # 6h
        PLAN_ACTIVE=true
    fi
fi

EMIT_ADVISORY=false
FIRE_REASON=""
if [ "$APPROVAL_FRESH" = "false" ] && [ "$PLAN_ACTIVE" = "false" ]; then
    if FIRE_REASON=$(scope_should_fire); then
        EMIT_ADVISORY=true
    fi
fi

if [ "$EMIT_ADVISORY" = "true" ]; then
    scope_mark_fired
    jq -n --arg reason "$FIRE_REASON" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            additionalContext: ("DELEGATION GATE (scope crossed: " + $reason + "): this task has grown past single-task scope. If this is a multi-step task with 2+ subtasks, a delegation table must have been presented and approved. If you skipped it, STOP and present the table now.\n\n📖 FRAMEWORK: @frameworks/delegation.md")
        }
    }'
fi
