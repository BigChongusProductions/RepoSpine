#!/bin/bash
# Hook: Correction Detection (UserPromptSubmit)
# Fires BEFORE Claude starts thinking on every user message.
# Scans for correction signals and injects HARD GATE reminder into context.
#
# Replaces: prose "HARD GATE: FIRST tool call = Edit to LESSONS" rule
# (which failed 2× — see LESSONS)
#
# Returns: additionalContext (non-blocking context injection)
# Never returns permissionDecision — we want Claude to respond, just with the right priority.

set -euo pipefail

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')

# Exit silently if no prompt (shouldn't happen, but be safe)
if [ -z "$PROMPT" ]; then
    exit 0
fi

# Correction signal patterns (case-insensitive)
# These are phrases that indicate the user is correcting Claude's previous work.
# Kept broad intentionally — false positives (extra context) are cheap,
# false negatives (missed corrections) cause lesson-logging failures.
SIGNALS="didn't work|did not work|doesn't work|does not work|failed|wrong|broken|not right|why didn't you|why did you|that's not|thats not|no no|still broken|same error|same issue|try again|that broke|not what I|you forgot|you missed|you skipped|ugh|come on|seriously\?"

if echo "$PROMPT" | grep -qiE "$SIGNALS"; then
    jq -n '{
        hookSpecificOutput: {
            hookEventName: "UserPromptSubmit",
            additionalContext: "⚠️ CORRECTION SIGNAL DETECTED in user message.\n\n🔴 HARD GATE: Your FIRST action MUST be to log the correction:\n  %%LESSON_LOG_COMMAND%%\n\nLog the correction BEFORE diagnosing or fixing anything.\nThis gate has been violated 2× before — it is now hook-enforced.\nAfter logging, proceed with diagnosis and fix.\n\n📖 FRAMEWORK LOAD REQUIRED: correction-protocol.md is NOT loaded at startup.\nRead it now before proceeding:\n  @frameworks/correction-protocol.md\nThis framework defines the full correction detection gate, lesson extraction, and promotion pipeline."
        }
    }'
else
    # No correction signal — silent pass
    exit 0
fi
