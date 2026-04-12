#!/bin/bash
# Hook: Swift File Registration Check (PostToolUse → Write)
# Fires after a Write tool call succeeds. If the written file is .swift,
# checks whether it appears in the Xcode project's project.pbxproj.
#
# Replaces: LESSONS entry "T-013 created SeverityEngine.swift but never added it to pbxproj"
#
# Scoped to: implementer agent (via agent-level hooks config)
# Can also be used globally if desired.
#
# Returns: additionalContext warning if file missing from pbxproj (non-blocking)

set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only care about .swift files
if [[ ! "$FILE_PATH" == *.swift ]]; then
    exit 0
fi

# Fallback CWD
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    CWD="$(pwd)"
fi

# Find the pbxproj file
PBXPROJ=$(find "$CWD" -name "project.pbxproj" -path "*.xcodeproj/*" 2>/dev/null | head -1)

if [ -z "$PBXPROJ" ]; then
    # No Xcode project found — can't check
    exit 0
fi

# Get just the filename
BASENAME=$(basename "$FILE_PATH")

# Check if the filename appears in pbxproj
if ! grep -q "$BASENAME" "$PBXPROJ" 2>/dev/null; then
    jq -n --arg file "$BASENAME" --arg pbx "$(basename "$(dirname "$PBXPROJ")")/project.pbxproj" '{
        hookSpecificOutput: {
            hookEventName: "PostToolUse",
            additionalContext: ("⚠️ NEW SWIFT FILE NOT IN XCODE PROJECT: " + $file + " was just created but does not appear in " + $pbx + ". It will NOT compile. You must add it to the Xcode project:\n  1. PBXFileReference section (file ref)\n  2. PBXBuildFile section (build file ref)\n  3. PBXGroup section (add to the correct group)\n  4. PBXSourcesBuildPhase section (compile source)\n\nFix this NOW before continuing with other work.")
        }
    }'
fi

exit 0
