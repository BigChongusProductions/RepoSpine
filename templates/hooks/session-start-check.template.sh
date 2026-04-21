#!/bin/bash
# Hook: Session Start — Full Briefing Injection (SessionStart)
# Fires when a Claude Code session begins or resumes.
#
# What it does:
#   1. Runs session_briefing.py --compact (or session_briefing.sh fallback)
#   2. Reads NEXT_SESSION.md (last session's handoff) + freshness check
#   3. Runs verify-handoff.sh (if present) → BLOCKING drift section
#   4. DB health, dirty tree, prereq missing
#   5. Cleans orphaned WAL/SHM/journal files project-wide (no active sqlite3)
#   6. Resets delegation + escalation state for the fresh session
#   7. Pre-warms Semgrep cache (background, non-blocking)
#
# The drift block is injected at the top of additionalContext — it's a
# structural BLOCKING gate, not a soft warning. See NEXT_SESSION.md
# overrides process for how to bypass.

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"

set -euo pipefail

# ── 0. Prerequisite guard (graceful degradation) ──
PREREQ_WARNINGS=""
for cmd in jq python3 git; do
    if ! command -v "$cmd" &>/dev/null; then
        PREREQ_WARNINGS="${PREREQ_WARNINGS}\n⚠️ Missing prerequisite: ${cmd}"
    fi
done
# jq is required for stdin parsing — exit gracefully if missing
if ! command -v jq &>/dev/null; then
    echo '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"⚠️ SESSION START DEGRADED: jq not found. Install with: brew install jq"}}'
    exit 0
fi

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

CONTEXT_PARTS=""
WARNINGS=""
DRIFT_BLOCK=""

# ── 1. Session briefing — prefer Python (structured), fall back to sh ──
BRIEFING_PY="$CWD/scripts/session_briefing.py"
if [ -f "$BRIEFING_PY" ]; then
    BRIEFING=$(PROJECT_DB=%%PROJECT_DB%% python3 "$BRIEFING_PY" --compact 2>/dev/null) || BRIEFING="(session_briefing.py failed — check db_queries.sh)"
    CONTEXT_PARTS="${CONTEXT_PARTS}

## Session Briefing (compact)
${BRIEFING}"
elif [ -f "$CWD/session_briefing.sh" ]; then
    BRIEFING=$(bash "$CWD/session_briefing.sh" --compact 2>/dev/null) || BRIEFING="(session_briefing.sh failed)"
    CONTEXT_PARTS="${CONTEXT_PARTS}

## Briefing
${BRIEFING}
(Full briefing: bash session_briefing.sh)"
fi

# ── 2. Read NEXT_SESSION.md (last session's handoff) ──
NEXT_SESSION="$CWD/NEXT_SESSION.md"
if [ -f "$NEXT_SESSION" ]; then
    NOW=$(date +%s)
    FILE_MTIME=$(stat -c %Y "$NEXT_SESSION" 2>/dev/null || stat -f %m "$NEXT_SESSION" 2>/dev/null || echo "0")
    AGE_HOURS=$(( (NOW - FILE_MTIME) / 3600 ))

    if [ "$AGE_HOURS" -gt 48 ]; then
        WARNINGS="${WARNINGS}\n⚠️ STALE HANDOFF: NEXT_SESSION.md is ${AGE_HOURS}h old (>48h). State may have changed."
    elif [ "$AGE_HOURS" -gt 24 ]; then
        WARNINGS="${WARNINGS}\nℹ️ AGING HANDOFF: NEXT_SESSION.md is ${AGE_HOURS}h old."
    fi

    # Extract Signal/Phase/Next-task bullets only (saves ~800 tokens vs full inject)
    HANDOFF_SIGNAL=$(grep -E '^(Signal:|Phase:|Next|Pick up|##)' "$NEXT_SESSION" | head -10)
    HANDOFF_WARNINGS=$(sed -n '/^## Warnings/,/^## /p' "$NEXT_SESSION" | head -10)
    CONTEXT_PARTS="${CONTEXT_PARTS}

## Handoff (NEXT_SESSION.md, ${AGE_HOURS}h old)
${HANDOFF_SIGNAL}
${HANDOFF_WARNINGS}
(Full handoff: cat NEXT_SESSION.md)"
else
    WARNINGS="${WARNINGS}\n⚠️ NO HANDOFF: NEXT_SESSION.md missing. No context from previous session."
fi

# ── 2.5. Handoff drift check (blocking) ──
# verify-handoff.sh exits non-zero on drift and emits a JSON summary. Drift
# is promoted to its OWN BLOCKING section (not folded into WARNINGS) because
# past incidents showed mixed warnings went silent under cognitive load.
VERIFY_HANDOFF="$CWD/scripts/verify-handoff.sh"
if [ -x "$VERIFY_HANDOFF" ] && [ -f "$NEXT_SESSION" ]; then
    DRIFT_JSON=$("$VERIFY_HANDOFF" --json 2>/dev/null || true)
    [ -z "$DRIFT_JSON" ] && DRIFT_JSON='{"drift":0}'
    DRIFT_FLAG=$(echo "$DRIFT_JSON" | sed -n 's/.*"drift":\([0-9]*\).*/\1/p')
    if [ "${DRIFT_FLAG:-0}" -gt 0 ]; then
        FWD=$(echo "$DRIFT_JSON" | sed -n 's/.*"forward_drift_count":\([0-9]*\).*/\1/p')
        BLK=$(echo "$DRIFT_JSON" | sed -n 's/.*"block_state":"\([a-z]*\)".*/\1/p')
        SIG=$(echo "$DRIFT_JSON" | sed -n 's/.*"signal_drift":\([0-9]*\).*/\1/p')
        HSIG=$(echo "$DRIFT_JSON" | sed -n 's/.*"handoff_signal":"\([A-Z]*\)".*/\1/p')
        FSIG=$(echo "$DRIFT_JSON" | sed -n 's/.*"fresh_signal":"\([A-Z]*\)".*/\1/p')
        DRIFT_BLOCK="

## 🛑 HANDOFF DRIFT — BLOCKING
NEXT_SESSION.md contradicts current state. Resolve before doing any work."
        [ "${FWD:-0}" -gt 0 ]         && DRIFT_BLOCK="${DRIFT_BLOCK}
  • Forward-looking: ${FWD} task ID(s) claimed as upcoming, already DONE/SKIP in DB."
        [ "${BLK:-absent}" = "stale" ] && DRIFT_BLOCK="${DRIFT_BLOCK}
  • Rendered handoff-queue block is stale vs DB."
        [ "${SIG:-0}" -gt 0 ]         && DRIFT_BLOCK="${DRIFT_BLOCK}
  • Signal drift: handoff says ${HSIG:-?}, fresh state is ${FSIG:-?}."
        DRIFT_BLOCK="${DRIFT_BLOCK}
Remediation:
  1. bash scripts/verify-handoff.sh   # full diagnostic
  2. /handoff                          # regenerate with fresh signal
Do NOT proceed until drift is resolved (or explicitly overridden in NEXT_SESSION.md 'Overrides (active)')."
    fi
fi

# ── 3. DB health (cached via .health_cache written by briefing) ──
# session_briefing.py writes the cache; no redundant subprocess here.

# ── 4. Uncommitted changes ──
if [ -d "$CWD/.git" ]; then
    DIRTY_COUNT=$(cd "$CWD" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$DIRTY_COUNT" -gt 0 ]; then
        WARNINGS="${WARNINGS}\nℹ️ DIRTY TREE: ${DIRTY_COUNT} uncommitted change(s) from previous session."
    fi
fi

# ── 5. DB journal cleanup — scope pgrep to this project's DB file ──
# Bug fix: bare `pgrep -f sqlite3` matched any sqlite3 process on the host,
# including ones against unrelated DBs. Now: regex-escape the DB filename
# and match only processes touching THIS project's DB. Dots in the DB name
# (e.g. my.project.db) are escaped so they match literally, not any char.
PROJECT_DB_NAME='%%PROJECT_DB%%'
PROJECT_DB_RE=$(printf '%s' "$PROJECT_DB_NAME" | sed 's/[][\.*^$|(){}?+/]/\\&/g')

WAL_CLEANED=0
if ! pgrep -f "sqlite3.*${PROJECT_DB_RE}" >/dev/null 2>&1; then
    NOW_TS=$(date +%s)
    # Scan the project for orphaned WAL/SHM/journal files (maxdepth 2 keeps
    # the scan bounded — nested node_modules/test fixtures shouldn't match).
    while IFS= read -r -d '' journal; do
        JOURNAL_MTIME=$(stat -f %m "$journal" 2>/dev/null || stat -c %Y "$journal" 2>/dev/null || echo "0")
        JOURNAL_AGE=$((NOW_TS - JOURNAL_MTIME))
        if [ "$JOURNAL_AGE" -gt 300 ]; then
            rm -f "$journal"
            WAL_CLEANED=$((WAL_CLEANED + 1))
        fi
    done < <(find "$CWD" -maxdepth 2 \( -name "*.db-wal" -o -name "*.db-shm" -o -name "*.db-journal" -o -name "*-journal" \) -print0 2>/dev/null)
    if [ "$WAL_CLEANED" -gt 0 ]; then
        WARNINGS="${WARNINGS}\nℹ️ DB HYGIENE: Cleaned ${WAL_CLEANED} orphaned WAL/SHM/journal file(s)."
    fi
fi

# ── 6. Reset delegation + scope state for fresh session ──
STATE_FILE="$CWD/.claude/hooks/.delegation_state"
echo "0" > "$STATE_FILE"
echo "0" >> "$STATE_FILE"
rm -f "$CWD/.claude/hooks/.delegation_tasks.json"
# Clear scope tracker so old boundary doesn't leak into new session.
rm -f "$CWD/.claude/hooks/.delegation_scope.json"

# ── 7. Reset escalation state for fresh session ──
printf 'haiku|0|0|\nsonnet|0|0|\nopus|0|0|\n' > "$CWD/.claude/hooks/.escalation_state"
rm -f "$CWD/.claude/hooks/.last_spawn_tier" \
      "$CWD/.claude/hooks/.last_check_result" \
      "$CWD/.claude/hooks/.last_confirm_timestamp"

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

if [ -n "$PREREQ_WARNINGS" ]; then
    WARNINGS="${PREREQ_WARNINGS}${WARNINGS}"
fi

# Drift block goes BEFORE warnings so it anchors at top of the briefing.
if [ -n "$DRIFT_BLOCK" ]; then
    FULL_CONTEXT="${FULL_CONTEXT}${DRIFT_BLOCK}"
fi

if [ -n "$WARNINGS" ]; then
    FULL_CONTEXT="${FULL_CONTEXT}

## Warnings
$(echo -e "$WARNINGS")"
fi

# Tail depends on drift state
if [ -n "$DRIFT_BLOCK" ]; then
    FULL_CONTEXT="${FULL_CONTEXT}

## Action Required
Present status brief WITH the HANDOFF DRIFT section at the top. Do NOT proceed until drift is resolved."
else
    FULL_CONTEXT="${FULL_CONTEXT}

## Action Required
Present the status brief (signal, phase, next task) as your FIRST response.
Wait for Master's 'go' before starting any work."
fi

jq -n --arg ctx "$FULL_CONTEXT" '{
    hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: $ctx
    }
}'
