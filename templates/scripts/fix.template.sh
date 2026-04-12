#!/usr/bin/env bash
# %%PROJECT_NAME%% — FIX MODE

set -euo pipefail

# Platform guard — osascript is macOS-only (AppleScript)
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "fix.sh requires macOS (uses osascript to launch Terminal)."
    echo "On Linux, run directly: claude --model claude-opus-4-6 --dangerously-skip-permissions"
    exit 0
fi

PROJECT="%%PROJECT_PATH%%"
PROBLEM="${1:-}"

BOLD="\033[1m" GREEN="\033[32m" YELLOW="\033[33m" CYAN="\033[36m" RED="\033[31m" RESET="\033[0m"

clear
echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${RED}${BOLD}║  🔧  %%PROJECT_NAME%% — FIX MODE                                ║${RESET}"
echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

cd "$PROJECT"
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
echo "  Branch: $BRANCH"
git log --oneline -5 2>/dev/null | sed 's/^/  /'
echo ""

if [ -n "$PROBLEM" ]; then
    INITIAL_PROMPT="Fix this issue: $PROBLEM"
    osascript -e "
    tell application \"Terminal\"
        activate
        do script \"cd %%PROJECT_PATH%% && claude --model claude-opus-4-6 --dangerously-skip-permissions -p \\"$INITIAL_PROMPT\\"\"
    end tell
    "
else
    osascript -e '
    tell application "Terminal"
        activate
        do script "cd %%PROJECT_PATH%% && claude --model claude-opus-4-6 --dangerously-skip-permissions"
    end tell
    '
fi
echo -e "${GREEN}✅ Opus launched${RESET}"
