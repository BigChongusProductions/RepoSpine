#!/bin/bash
# Hook: Framework Contamination Detection (PostToolUse → Edit|Write)
# Fires after Edit or Write tool calls. If the modified file is a framework,
# scans it for project-specific strings that violate framework genericity.
#
# Frameworks must be generic — they're reused across projects via symlink.
# Project-specific references (e.g., "Bootstrap", "bootstrap.db") break other projects.
#
# Patterns loaded from framework-contamination-patterns.conf (one per line).
# Kept external so this hook itself doesn't trigger contamination checks.
#
# Returns: additionalContext warning if matches found (non-blocking advisory)

set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only care about files in templates/frameworks/
if [[ ! "$FILE_PATH" == *"templates/frameworks/"* ]]; then
    exit 0
fi

# Fallback CWD
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    CWD="$(pwd)"
fi

# Verify file exists
if [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

# Load contamination patterns from config file
CONF_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF_FILE="$CONF_DIR/framework-contamination-patterns.conf"
if [ ! -f "$CONF_FILE" ]; then
    exit 0
fi
# Build pipe-delimited pattern from config (skip comments and blanks)
PATTERN=$(grep -v '^#' "$CONF_FILE" | grep -v '^$' | tr '\n' '|' | sed 's/|$//')

MATCH=$(grep -inE "$PATTERN" "$FILE_PATH" 2>/dev/null | head -1 || true)

if [ -n "$MATCH" ]; then
    # Extract just the framework filename for cleaner output
    FRAMEWORK_NAME=$(basename "$FILE_PATH")

    # Output advisory context
    jq -n --arg file "$FRAMEWORK_NAME" --arg match "$MATCH" '{
        hookSpecificOutput: {
            hookEventName: "PostToolUse",
            additionalContext: ("⚠️ FRAMEWORK CONTAMINATION: " + $file + " contains a project-specific reference:\n\n  " + $match + "\n\nFrameworks are generic and reused across projects via symlink. Remove or parameterize this reference.\n\nExamples of fixes:\n  - Replace \"Bootstrap\" with \"{{PROJECT_NAME}}\"\n  - Move project-specific logic to .claude/rules/ instead\n  - Use placeholder syntax if the reference must appear in docs")
        }
    }'
fi

exit 0
