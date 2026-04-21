#!/bin/bash
# Mark an approved plan active so pre-edit-check.sh suppresses the delegation
# scope advisory during plan-scope execution.
#
# Call this after `ExitPlanMode` approval when the plan will span > 30 minutes
# (the default delegation-approval TTL). For shorter plans, the regular
# `db_queries.sh delegate` approval is sufficient.
#
# Usage: bash .claude/hooks/mark_plan_active.sh "short-plan-name" [project-root]
# Clear: bash .claude/hooks/mark_plan_done.sh [project-root]
#
# Marker: .claude/hooks/.active-plan
# Format: line 1 = epoch timestamp, line 2 = plan name
# TTL:    6h — older markers are ignored by readers.

set -euo pipefail

NAME="${1:-unnamed-plan}"
PROJECT_ROOT="${2:-.}"
MARKER="$PROJECT_ROOT/.claude/hooks/.active-plan"

mkdir -p "$(dirname "$MARKER")"

NOW=$(date +%s)
echo "$NOW" > "$MARKER"
echo "$NAME" >> "$MARKER"

echo "✅ Plan marked active: $NAME"
echo "   Delegation scope advisory suppressed for 6 hours."
echo "   Clear with: bash .claude/hooks/mark_plan_done.sh"
