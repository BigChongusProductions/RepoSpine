#!/bin/bash
# Hook: Session End Safety Net (SessionEnd)
# Fires when a Claude Code session terminates.
# Auto-saves session state if no manual save was done recently.
#
# Replaces: prose "MANDATORY: run save_session.sh" rule
#
# Requires: CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS=15000 in work.sh
# (default 1.5s is too short for save_session.sh)
#
# Returns: nothing (side-effect only — writes NEXT_SESSION.md)

# NOTE: Don't use set -e here — we want best-effort, not fail-fast.
# SessionEnd hooks that fail are logged but don't affect anything.

INPUT=$(cat 2>/dev/null || echo '{}')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

# Fallback CWD
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    exit 0  # Can't do anything without a working directory
fi

NEXT_SESSION="$CWD/NEXT_SESSION.md"
SAVE_SCRIPT="$CWD/save_session.sh"

# If save_session.sh doesn't exist, nothing to do
if [ ! -f "$SAVE_SCRIPT" ]; then
    exit 0
fi

# Check if NEXT_SESSION.md was updated recently (within last 5 minutes)
if [ -f "$NEXT_SESSION" ]; then
    NOW=$(date +%s)
    # macOS stat uses -f %m, Linux uses -c %Y
    MTIME=$(stat -c %Y "$NEXT_SESSION" 2>/dev/null || stat -f %m "$NEXT_SESSION" 2>/dev/null || echo "0")
    AGE_MINUTES=$(( (NOW - MTIME) / 60 ))

    if [ "$AGE_MINUTES" -lt 5 ]; then
        exit 0  # Recent save exists — no need for safety net
    fi
fi

# No recent save — auto-save with disclaimer
bash "$SAVE_SCRIPT" "AUTO-SAVED: Session ended without manual save_session.sh" 2>/dev/null || true

exit 0
