#!/bin/bash
# Consolidated PostToolUse Check — single entry point for all post-tool hooks.
#
# Routes Edit|Write|MultiEdit through a short pipeline of checks. First
# sub-check that writes hookSpecificOutput JSON and exits 0 wins (the tool
# result already landed; these are advisories only).
#
# Pipeline (in order):
#   1. Framework contamination check — only for files under .claude/frameworks/
#      or templates/frameworks/. Scans new content against contamination patterns.
#   2. README drift check — only for README.md edits. Delegates to
#      readme-drift-check.sh if present.
#   3. Commit nudge — if N+ files modified since last commit, suggest a checkpoint.

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"

set -uo pipefail

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')

case "$TOOL" in
    Edit|Write|MultiEdit) ;;
    *) exit 0 ;;
esac

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
HOOKS_DIR="$CWD/.claude/hooks"

# ── 1. Framework contamination ────────────────────────────────────────────
case "$FILE_PATH" in
    *"/frameworks/"*|*"/templates/frameworks/"*)
        CONF_FILE="$HOOKS_DIR/framework-contamination-patterns.conf"
        if [ -f "$FILE_PATH" ] && [ -f "$CONF_FILE" ]; then
            PATTERN=$(grep -v '^#' "$CONF_FILE" | grep -v '^$' | tr '\n' '|' | sed 's/|$//')
            if [ -n "$PATTERN" ]; then
                MATCH=$(grep -inE "$PATTERN" "$FILE_PATH" 2>/dev/null | head -1 || true)
                if [ -n "$MATCH" ]; then
                    FRAMEWORK_NAME=$(basename "$FILE_PATH")
                    jq -n --arg file "$FRAMEWORK_NAME" --arg match "$MATCH" '{
                        hookSpecificOutput: {
                            hookEventName: "PostToolUse",
                            additionalContext: ("FRAMEWORK CONTAMINATION: " + $file + " contains a project-specific reference:\n  " + $match + "\nFrameworks are generic and reused across projects. Remove or parameterize this reference.")
                        }
                    }'
                    exit 0
                fi
            fi
        fi
        ;;
esac

# ── 2. README drift check ─────────────────────────────────────────────────
case "$FILE_PATH" in
    */README.md|README.md)
        if [ -x "$HOOKS_DIR/readme-drift-check.sh" ]; then
            echo "$INPUT" | "$HOOKS_DIR/readme-drift-check.sh" 2>/dev/null && exit 0 || true
        fi
        ;;
esac

# ── 3. Commit nudge ───────────────────────────────────────────────────────
# Only nudge when editing within the project root (not subprojects).
if [ -d "$CWD/.git" ] && [ "$CWD" = "$(cd "$CWD" && pwd)" ]; then
    CHANGED_COUNT=$(git -C "$CWD" status --short 2>/dev/null | wc -l | tr -d ' ')
    THRESHOLD="${COMMIT_NUDGE_THRESHOLD:-8}"
    if [ "$CHANGED_COUNT" -ge "$THRESHOLD" ]; then
        SUMMARY=$(git -C "$CWD" status --short 2>/dev/null | awk '{print $NF}' | xargs -I{} basename {} | sed 's/\.[^.]*$//' | sort -u | head -5 | tr '\n' ',' | sed 's/,$//')
        jq -n --arg count "$CHANGED_COUNT" --arg summary "$SUMMARY" '{
            hookSpecificOutput: {
                hookEventName: "PostToolUse",
                additionalContext: ("📌 COMMIT NUDGE: " + $count + " files modified since last commit (" + $summary + "). Consider committing to keep the git tree readable.")
            }
        }'
    fi
fi

exit 0
