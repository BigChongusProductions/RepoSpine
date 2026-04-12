#!/usr/bin/env bash
# save_session.sh — Generate NEXT_SESSION.md from current DB + git state
# Usage: bash save_session.sh ["Session summary — what was accomplished"]
#
# Thin wrapper around save_session.py (Phase 4 Python extraction).
# Called manually or via: bash db_queries.sh save-session "summary"

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DB="$DIR/%%PROJECT_DB%%"
SCRIPT="$DIR/templates/scripts/save_session.py"

if [ ! -f "$DB" ]; then
    echo "ERROR: Database not found: $DB" >&2
    exit 1
fi

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: save_session.py not found: $SCRIPT" >&2
    echo "       Run from the project root directory." >&2
    exit 1
fi

export PROJECT_DB="$DB"

exec python3 "$SCRIPT" \
    --project-name "%%PROJECT_NAME%%" \
    --project-dir "$DIR" \
    "$@"
