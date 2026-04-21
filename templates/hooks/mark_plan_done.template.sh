#!/bin/bash
# Clear the active-plan marker so the delegation scope advisory resumes
# normal behavior. Called at plan completion or from session-end-safety
# when the plan exceeds its 4h useful lifetime.
#
# Usage: bash .claude/hooks/mark_plan_done.sh [project-root]

set -euo pipefail

PROJECT_ROOT="${1:-.}"
MARKER="$PROJECT_ROOT/.claude/hooks/.active-plan"

if [ -f "$MARKER" ]; then
    NAME=$(sed -n '2p' "$MARKER" 2>/dev/null || echo "unknown")
    rm "$MARKER"
    echo "✅ Plan cleared: $NAME"
else
    echo "ℹ️  No active plan marker."
fi
