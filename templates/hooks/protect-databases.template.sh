#!/bin/bash
# Hook: Database Write Protection (PreToolUse → Bash)
# Fires before every Bash command. Scans for sqlite3 write operations
# targeting files other than our own project databases.
#
# Replaces: prose "STOP before writing to registered project DB" rule
#
# Returns: permissionDecision "deny" for external DB writes (no user override)
# Silent exit 0 for allowed commands.
#
# Note: Write/Edit to .db files is already blocked by permissions.deny in settings.json.
# This hook catches the Bash vector (sqlite3 commands, redirects to .db files).
#
# Configuration: %%OWN_DB_PATTERNS%% should be replaced with a grep-compatible
# regex pattern matching your project's own writable databases.
# Example: my_project\.db\|extra\.db

set -euo pipefail

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only process Bash commands
if [ "$TOOL" != "Bash" ] || [ -z "$COMMAND" ]; then
    exit 0
fi

# Own DB pattern — replace this placeholder with your project's writable DB regex
OWN_DB_PATTERN='%%OWN_DB_PATTERNS%%'

# Pattern 1: sqlite3 with write operations targeting external DBs
# We check for sqlite3 followed by a write keyword (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE)
# but EXEMPT our own project DBs
if echo "$COMMAND" | grep -qiE 'sqlite3\s+' ; then
    # Check if it's a write operation
    if echo "$COMMAND" | grep -qiE '(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|VACUUM|REINDEX)'; then
        # Check if it's targeting our own DB (allowed)
        if echo "$COMMAND" | grep -qE "$OWN_DB_PATTERN"; then
            exit 0  # Our DB — allow
        fi
        # External DB write — DENY
        jq -n '{
            hookSpecificOutput: {
                hookEventName: "PreToolUse",
                permissionDecision: "deny",
                permissionDecisionReason: "🛑 DATABASE PROTECTION: This command would write to an external database. Writing to registered project DBs is permanently forbidden. Only project-owned databases are writable. Use db_queries.sh for task DB operations."
            }
        }'
        exit 0
    fi
fi

# Pattern 2: Shell redirect to .db file (e.g., > output.db, >> data.db)
if echo "$COMMAND" | grep -qE '>>?\s*\S+\.(db|sqlite|sqlite3)\b'; then
    # Exempt our own DBs
    if echo "$COMMAND" | grep -qE "$OWN_DB_PATTERN"; then
        exit 0
    fi
    jq -n '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: "🛑 DATABASE PROTECTION: This command redirects output to a database file. Writing to external .db files is permanently forbidden."
        }
    }'
    exit 0
fi

# Pattern 3: cp/mv overwriting a .db file (not ours)
if echo "$COMMAND" | grep -qE '(cp|mv)\s+.*\.(db|sqlite|sqlite3)\b'; then
    if echo "$COMMAND" | grep -qE "$OWN_DB_PATTERN"; then
        exit 0  # Our DBs
    fi
    # Only block if destination looks like a .db file
    # This is intentionally conservative — cp from a .db is fine (read)
    # We check if the LAST argument ends in .db (likely the destination)
    LAST_ARG=$(echo "$COMMAND" | awk '{print $NF}')
    if echo "$LAST_ARG" | grep -qE '\.(db|sqlite|sqlite3)$'; then
        jq -n '{
            hookSpecificOutput: {
                hookEventName: "PreToolUse",
                permissionDecision: "deny",
                permissionDecisionReason: "🛑 DATABASE PROTECTION: This command would overwrite an external database file. Writing to external .db files is permanently forbidden."
            }
        }'
        exit 0
    fi
fi

# Pattern 4: Advisory for reads against non-project DBs
# Non-blocking — warns when sqlite3 targets a DB that isn't ours.
# Prevents agents from accidentally querying the wrong database.
# Pattern validated in production usage across multiple projects.
if echo "$COMMAND" | grep -qiE 'sqlite3\s+\S+' ; then
    if ! echo "$COMMAND" | grep -qE "$OWN_DB_PATTERN"; then
        TARGET_DB=$(echo "$COMMAND" | grep -oiE 'sqlite3\s+\S+' | awk '{print $2}' | tr -d "'\"")
        if [ -n "$TARGET_DB" ]; then
            jq -n --arg db "$TARGET_DB" '{
                hookSpecificOutput: {
                    hookEventName: "PreToolUse",
                    additionalContext: ("⚠️ Reading non-project DB: " + $db + "\nConsider using db_queries.sh for project task operations.")
                }
            }'
            exit 0
        fi
    fi
fi

# All other commands — allow silently
exit 0
