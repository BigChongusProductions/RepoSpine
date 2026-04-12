#!/bin/bash
# Called after a delegation table is presented and Master approves.
# Resets the edit counter and sets a fresh approval timestamp.
#
# Usage: bash mark_delegation_approved.sh [project_root]

PROJECT_ROOT="${1:-.}"
STATE_FILE="$PROJECT_ROOT/.claude/hooks/.delegation_state"

mkdir -p "$(dirname "$STATE_FILE")"

NOW=$(date +%s)
echo "0" > "$STATE_FILE"
echo "$NOW" >> "$STATE_FILE"

echo "✅ Delegation gate approved. Edit counter reset. Approval valid for 30 minutes."
