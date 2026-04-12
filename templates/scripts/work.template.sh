#!/usr/bin/env bash
# %%PROJECT_NAME%% — WORK MODE

set -euo pipefail

PROJECT="%%PROJECT_PATH%%"
DB="$PROJECT/%%PROJECT_DB%%"

BOLD="\033[1m" GREEN="\033[32m" YELLOW="\033[33m" CYAN="\033[36m" RED="\033[31m" RESET="\033[0m"

clear
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║  🎯  %%PROJECT_NAME%% — WORK MODE                              ║${RESET}"
echo -e "${BOLD}║  $(date '+%A, %B %d, %Y')                                  ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

# Check DB
if [ ! -f "$DB" ]; then
    echo -e "${RED}❌ Database not found${RESET}"
    exit 1
fi

# Backup DB
cp "$DB" "$DB.bak"
echo -e "${GREEN}✅${RESET} Database backed up"

# Clean journal
[ -f "$DB-journal" ] && rm -f "$DB-journal" && echo -e "${YELLOW}⚠️${RESET}  Cleaned stale journal"

# Git state
cd "$PROJECT"
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
if [ "$BRANCH" != "dev" ]; then
    echo -e "${RED}⚠️  On branch '$BRANCH' — should be 'dev'${RESET}"
else
    echo -e "${GREEN}✅${RESET} Branch: dev"
fi

# Show tasks
echo ""
bash "$PROJECT/db_queries.sh" next
bash "$PROJECT/db_queries.sh" master

# Signal check
BRIEFING_OUTPUT=$(bash "$PROJECT/session_briefing.sh" 2>&1)
if echo "$BRIEFING_OUTPUT" | grep -q "🛑 RED"; then
    echo -e "${RED}${BOLD}  🛑 SESSION SIGNAL: RED — BLOCKERS${RESET}"
    echo "$BRIEFING_OUTPUT" | grep "❌" | sed 's/^/  /'
    echo ""
    read -p "  Launch Claude Code anyway? (y/N) " OVERRIDE
    [[ ! "$OVERRIDE" =~ ^[Yy]$ ]] && exit 0
elif echo "$BRIEFING_OUTPUT" | grep -q "YELLOW"; then
    echo -e "${YELLOW}⚠️  Signal: YELLOW${RESET}"
else
    echo -e "${GREEN}✅ Signal: GREEN${RESET}"
fi

# Launch
echo ""
echo -e "${CYAN}Launching Claude Code (opusplan)...${RESET}"
osascript -e "
tell application \"Terminal\"
    activate
    do script \"cd %%PROJECT_PATH%% && claude --model opusplan --dangerously-skip-permissions\"
end tell
"
echo -e "${GREEN}✅ Claude Code launched${RESET}"
