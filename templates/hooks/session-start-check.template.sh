#!/bin/bash
# Hook: Session Start — Full Briefing Injection (SessionStart)
# Fires when a Claude Code session begins or resumes.
#
# What it does:
#   1. Runs session_briefing.py --compact (structured JSON output) with fallback to session_briefing.sh
#   2. Reads NEXT_SESSION.md (last session's handoff)
#   3. Checks handoff freshness, DB health, dirty tree
#   4. Injects EVERYTHING as additionalContext so Claude has full state
#      on the very first interaction — no manual "run briefing" step needed
#
# The CLAUDE.md rule "present status brief on first interaction" means
# Claude will auto-present this when the user types anything.
#
# Replaces: manual "python3 scripts/session_briefing.py --compact" + "cat NEXT_SESSION.md" at session start

set -euo pipefail

# ── 0. Prerequisite check (must not use jq) ──
MISSING_PREREQS=""
command -v jq >/dev/null 2>&1 || MISSING_PREREQS="${MISSING_PREREQS} jq"
command -v python3 >/dev/null 2>&1 || MISSING_PREREQS="${MISSING_PREREQS} python3"
command -v git >/dev/null 2>&1 || MISSING_PREREQS="${MISSING_PREREQS} git"

if [ -n "$MISSING_PREREQS" ]; then
    PREREQ_MSG="MISSING PREREQUISITES:${MISSING_PREREQS}. Install before continuing. All hooks depend on jq for JSON I/O."
    printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
        "$(printf '%s' "$PREREQ_MSG" | sed 's/"/\\"/g')"
    exit 0
fi

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

CONTEXT_PARTS=""
WARNINGS=""

# ── 1. Run session_briefing.py --compact (Python, structured output) ──
BRIEFING_PY="$CWD/scripts/session_briefing.py"
if [ -f "$BRIEFING_PY" ]; then
    BRIEFING=$(PROJECT_DB=%%PROJECT_DB%% python3 "$BRIEFING_PY" --compact 2>/dev/null) || BRIEFING="(session_briefing.py failed — check db_queries.sh)"
    CONTEXT_PARTS="${CONTEXT_PARTS}

## Session Briefing (compact)
${BRIEFING}"
elif [ -f "$CWD/session_briefing.sh" ]; then
    BRIEFING=$(bash "$CWD/session_briefing.sh" 2>/dev/null) || BRIEFING="(session_briefing.sh failed)"
    CONTEXT_PARTS="${CONTEXT_PARTS}

## Session Briefing (computed)
${BRIEFING}"
fi

# ── 2. Read NEXT_SESSION.md (last session's handoff) ──
NEXT_SESSION="$CWD/NEXT_SESSION.md"
if [ -f "$NEXT_SESSION" ]; then
    # Freshness check
    NOW=$(date +%s)
    FILE_MTIME=$(stat -c %Y "$NEXT_SESSION" 2>/dev/null || stat -f %m "$NEXT_SESSION" 2>/dev/null || echo "0")
    AGE_HOURS=$(( (NOW - FILE_MTIME) / 3600 ))

    if [ "$AGE_HOURS" -gt 48 ]; then
        WARNINGS="${WARNINGS}\n⚠️ STALE HANDOFF: NEXT_SESSION.md is ${AGE_HOURS}h old (>48h). State may have changed."
    elif [ "$AGE_HOURS" -gt 24 ]; then
        WARNINGS="${WARNINGS}\nℹ️ AGING HANDOFF: NEXT_SESSION.md is ${AGE_HOURS}h old."
    fi

    # Include the handoff content (truncate if huge)
    HANDOFF=$(head -80 "$NEXT_SESSION")
    CONTEXT_PARTS="${CONTEXT_PARTS}

## Last Session Handoff (NEXT_SESSION.md, ${AGE_HOURS}h old)
${HANDOFF}"
else
    WARNINGS="${WARNINGS}\n⚠️ NO HANDOFF: NEXT_SESSION.md missing. No context from previous session."
fi

# ── 3. DB health — handled by session_briefing.py (which writes .health_cache)
# No redundant subprocess spawn here.

# ── 4. Uncommitted changes ──
if [ -d "$CWD/.git" ]; then
    DIRTY_COUNT=$(cd "$CWD" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$DIRTY_COUNT" -gt 0 ]; then
        WARNINGS="${WARNINGS}\nℹ️ DIRTY TREE: ${DIRTY_COUNT} uncommitted change(s) from previous session."
    fi
fi

# ── 5. DB lock cleanup (stale SQLite journal) ──
DB_JOURNAL="$CWD/%%PROJECT_DB%%-journal"
DB_CLEANUP_MSG=""
if [ -f "$DB_JOURNAL" ]; then
    # Guard 1: skip if sqlite3 is actively using the DB
    if ! pgrep -f "sqlite3.*%%PROJECT_DB%%" >/dev/null 2>&1; then
        # Guard 2: only remove if journal is >300 seconds old (stale)
        JOURNAL_MTIME=$(stat -f %m "$DB_JOURNAL" 2>/dev/null || stat -c %Y "$DB_JOURNAL" 2>/dev/null || echo 0)
        JOURNAL_AGE=$(( $(date +%s) - JOURNAL_MTIME ))
        if [ "$JOURNAL_AGE" -gt 300 ]; then
            rm -f "$DB_JOURNAL"
            DB_CLEANUP_MSG="Removed stale DB journal (${JOURNAL_AGE}s old). DB should be unlocked now."
        fi
    fi
fi

# ── 6. Reset delegation state for fresh session ──
STATE_FILE="$CWD/.claude/hooks/.delegation_state"
echo "0" > "$STATE_FILE"
echo "0" >> "$STATE_FILE"

# ── 7. Reset escalation state for fresh session ──
ESC_FILE="$CWD/.claude/hooks/.escalation_state"
printf 'haiku|0|0|\nsonnet|0|0|\nopus|0|0|\n' > "$ESC_FILE"
# Clear ephemeral state files from prior session
rm -f "$CWD/.claude/hooks/.last_spawn_tier" "$CWD/.claude/hooks/.last_check_result" "$CWD/.claude/hooks/.last_confirm_timestamp"

# ── 8. Pre-warm Semgrep rule cache (background, non-blocking) ──
if command -v semgrep >/dev/null 2>&1 && [ -d "$CWD/.semgrep" ]; then
    # Hardened env: avoid trust-store/X509 crashes and ~/.semgrep write failures
    if [ -z "${SSL_CERT_FILE:-}" ]; then
        for _cert in /etc/ssl/cert.pem /private/etc/ssl/cert.pem \
                     /opt/homebrew/etc/openssl@3/cert.pem \
                     /opt/homebrew/etc/ca-certificates/cert.pem \
                     /etc/ssl/certs/ca-certificates.crt; do
            [ -r "$_cert" ] && export SSL_CERT_FILE="$_cert" && break
        done
    fi
    _sg_hooks="$CWD/.claude/hooks"
    mkdir -p "$_sg_hooks" 2>/dev/null || true
    : "${SEMGREP_LOG_FILE:="$_sg_hooks/semgrep.log"}"
    : "${SEMGREP_SETTINGS_FILE:="$_sg_hooks/semgrep-settings.yml"}"
    : "${SEMGREP_VERSION_CACHE_PATH:="$_sg_hooks/semgrep-version-cache"}"
    : "${SEMGREP_VERSION_CHECK_TIMEOUT:=1}"
    export SEMGREP_LOG_FILE SEMGREP_SETTINGS_FILE SEMGREP_VERSION_CACHE_PATH SEMGREP_VERSION_CHECK_TIMEOUT
    semgrep --config="$CWD/.semgrep/" --version >/dev/null 2>&1 &
fi

# ── Build final context ──
FULL_CONTEXT="🚀 SESSION START — AUTO-BRIEFING
${CONTEXT_PARTS}"

if [ -n "$DB_CLEANUP_MSG" ]; then
    WARNINGS="${WARNINGS}\nℹ️ DB CLEANUP: $DB_CLEANUP_MSG"
fi

if [ -n "$WARNINGS" ]; then
    FULL_CONTEXT="${FULL_CONTEXT}

## Warnings
$(echo -e "$WARNINGS")"
fi

FULL_CONTEXT="${FULL_CONTEXT}

## Action Required
Present the status brief (signal, phase, next task) as your FIRST response.
Wait for Master's 'go' before starting any work."

jq -n --arg ctx "$FULL_CONTEXT" '{
    hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: $ctx
    }
}'
