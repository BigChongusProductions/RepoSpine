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
#
# Side effects on match:
#   .claude/hooks/.correction_pending  — epoch timestamp (consumed by downstream tooling)
#   .claude/hooks/.correction_debug    — last 5 matches with matched pattern + text snippet

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"

set -euo pipefail

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')

# Exit silently if no prompt (shouldn't happen, but be safe)
if [ -z "$PROMPT" ]; then
    exit 0
fi

# Skip slash command invocations — they're skill expansions, not user corrections
echo "$PROMPT" | grep -q '<command-name>' && exit 0
echo "$PROMPT" | grep -q '<command-message>' && exit 0

# Skip messages that are primarily tool/system output (high false-positive risk)
echo "$PROMPT" | grep -q '<task-notification>' && exit 0
# If prompt is ENTIRELY system-reminders with no user text, skip
USER_ONLY=$(echo "$PROMPT" | sed '/<system-reminder>/,/<\/system-reminder>/d' | sed '/^$/d' || true)
if [ -z "$USER_ONLY" ]; then
    exit 0
fi

# Aggressive stripping of non-user content:
# 1. System reminder blocks (multi-line)
# 2. Code blocks (``` fenced)
# 3. Task notification blocks
# 4. ALL XML/HTML-style tags and their content
# 5. Lines starting with common tool output prefixes
USER_TEXT=$(echo "$PROMPT" | \
    sed '/<system-reminder>/,/<\/system-reminder>/d' | \
    sed '/^```/,/^```/d' | \
    sed '/<task-notification>/,/<\/task-notification>/d' | \
    sed '/<[a-zA-Z_:-]*>/,/<\/[a-zA-Z_:-]*>/d' | \
    sed 's/<[^>]*>//g' | \
    grep -vE '^\s*(✅|❌|⚠️|──|═|╔|╚|║|\[rerun|Checks:|Pass:|Fail:|FAILURE|PASSED|Summary:|Hook |hook )' || true)

if [ -z "$USER_TEXT" ]; then
    exit 0
fi

# Minimum length check — very short messages after stripping are unlikely corrections
CHAR_COUNT=${#USER_TEXT}
if [ "$CHAR_COUNT" -lt 10 ]; then
    exit 0
fi

# Correction signal patterns (case-insensitive)
# Phrase patterns are specific enough to match as-is
# Word patterns use \b boundaries to avoid substring matches (e.g. "wrongly")
PHRASE_SIGNALS="didn't work|did not work|doesn't work|does not work|that failed|not right|why didn't you|why did you|that's not|thats not|no no|still broken|same error|same issue|try again|that broke|not what I|you forgot|you missed|you skipped|come on"
WORD_SIGNALS="\bwrong\b|\bbroken\b|\bugh\b|\bseriously\?"

if echo "$USER_TEXT" | grep -qiE "$PHRASE_SIGNALS|$WORD_SIGNALS"; then
    # Side effects: marker + rotated debug log (helps diagnose false positives).
    HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    MATCHED=$(echo "$USER_TEXT" | grep -oiE "$PHRASE_SIGNALS|$WORD_SIGNALS" | head -1)
    printf '%s\n' "$(date +%s)" > "$HOOKS_DIR/.correction_pending"

    DEBUG_FILE="$HOOKS_DIR/.correction_debug"
    printf '%s | matched="%s" | text="%s"\n' \
        "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" \
        "$MATCHED" \
        "$(echo "$USER_TEXT" | head -1 | cut -c1-80)" \
        >> "$DEBUG_FILE"
    # Rotate: keep last 5 entries
    if [ -f "$DEBUG_FILE" ]; then
        tail -5 "$DEBUG_FILE" > "$DEBUG_FILE.tmp" && mv "$DEBUG_FILE.tmp" "$DEBUG_FILE"
    fi

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
