#!/usr/bin/env bash
# =============================================================================
# db_queries.sh — Thin Python CLI dispatcher
#
# Delegates to the Python `dbq` package for all db_queries commands.
#
# Placeholders replaced at activation time:
#   %%PROJECT_DB%%      — SQLite database filename (e.g. my_project.db)
#   %%PROJECT_NAME%%    — Human-readable project name
#   %%LESSONS_FILE%%    — Lessons/corrections log filename
#   %%PHASES%%          — Space-separated phase list (e.g. P1-PLAN P2-BUILD)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Set DB path for the Python package if not already overridden
export DB_OVERRIDE="${DB_OVERRIDE:-${SCRIPT_DIR}/%%PROJECT_DB%%}"

# Set project config via env vars (populated at activation time)
export DBQ_PROJECT_NAME="${DBQ_PROJECT_NAME:-%%PROJECT_NAME%%}"
export DBQ_LESSONS_FILE="${DBQ_LESSONS_FILE:-%%LESSONS_FILE%%}"
export DBQ_PHASES="${DBQ_PHASES:-%%PHASES%%}"

# Find the dbq package (local to project)
DBQ_LIB="${SCRIPT_DIR}/scripts"
if [ ! -d "${DBQ_LIB}/dbq" ]; then
    echo "ERROR: dbq package not found at ${SCRIPT_DIR}/scripts/dbq" >&2
    echo "       Ensure the project was bootstrapped correctly." >&2
    exit 1
fi
export PYTHONPATH="${DBQ_LIB}${PYTHONPATH:+:${PYTHONPATH}}"

exec python3 -m dbq "$@"
