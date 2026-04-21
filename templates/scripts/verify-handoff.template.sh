#!/usr/bin/env bash
# Handoff drift enforcement — verifies NEXT_SESSION.md against DB + fresh state.
#
# Checks:
#   1. Forward-looking task IDs (Focus:, Next session —, ## Pick up, "next task:")
#      must NOT be DONE/SKIP/WONTFIX in the DB.
#   2. HANDOFF-QUEUE-{START,END} block (if present) must byte-match fresh output
#      of scripts/render-handoff-queue.sh.
#   3. Signal: line must match session_briefing.sh --signal-only
#      (or session_briefing.py --signal-only fallback).
#
# Any check whose prerequisite script is missing is SKIPPED silently, not
# failed — so projects without render-handoff-queue.sh still get checks 1+3.
#
# Exit codes:
#   0   no drift
#   1   drift detected
#   2   usage / missing core prerequisites (DB, handoff file)
#
# Flags:
#   --quiet     suppress output on pass
#   --file F    verify a file other than NEXT_SESSION.md
#   --json      emit JSON summary (for hook parsing)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${REPO_ROOT}/%%PROJECT_DB%%"
TARGET="${REPO_ROOT}/NEXT_SESSION.md"
RENDERER="${REPO_ROOT}/scripts/render-handoff-queue.sh"
BRIEFING_SH="${REPO_ROOT}/session_briefing.sh"
BRIEFING_PY="${REPO_ROOT}/scripts/session_briefing.py"
START_MARKER="<!-- HANDOFF-QUEUE-START -->"
END_MARKER="<!-- HANDOFF-QUEUE-END -->"

QUIET=0
JSON=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quiet) QUIET=1; shift ;;
        --json)  JSON=1; QUIET=1; shift ;;
        --file)  TARGET="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,24p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

[[ -f "$DB"     ]] || { echo "❌ DB missing: $DB" >&2; exit 2; }
[[ -f "$TARGET" ]] || { echo "❌ Handoff file missing: $TARGET" >&2; exit 2; }
command -v sqlite3 >/dev/null 2>&1 || { echo "❌ sqlite3 not on PATH" >&2; exit 2; }

CONTENT="$(cat "$TARGET")"

# ── Helpers ────────────────────────────────────────────────────────────────

db_status() {
    local id="$1"
    local safe_id="${id//\'/}"    # strip single quotes defensively
    local s
    s=$(sqlite3 "$DB" "SELECT status FROM tasks WHERE id='${safe_id}';" 2>/dev/null)
    if [[ -z "$s" ]]; then
        echo "__MISSING__"
    else
        echo "$s"
    fi
}

# Extract task IDs from a chunk of text. Format: project prefix (2+ caps),
# hyphen, alphanumeric suffix. Matches QK-2833, SEO-19, QK-7064a, etc.
extract_ids() {
    grep -Eo '\b[A-Z]{2,}-[A-Za-z0-9]+\b' <<< "$1" | sort -u || true
}

# ── Check 1: forward-looking drift ─────────────────────────────────────────

FORWARD_TEXT=""
focus_line="$(grep -iE '^(Signal:|# Next Session|## ).*Focus:' <<< "$CONTENT" || true)"
FORWARD_TEXT+="${focus_line}"$'\n'
next_heading="$(grep -E '^## Next session' <<< "$CONTENT" || true)"
FORWARD_TEXT+="${next_heading}"$'\n'
pickup_bullets="$(awk '
    /^## Pick up/ { in_sec=1; next }
    in_sec && /^## / { in_sec=0 }
    in_sec && /^[[:space:]]*[-*]/ { print }
' <<< "$CONTENT")"
FORWARD_TEXT+="${pickup_bullets}"$'\n'
inline_matches="$(grep -iE 'next task[:=]|pick up[:=]|start here[:=]' <<< "$CONTENT" || true)"
FORWARD_TEXT+="${inline_matches}"$'\n'

FORWARD_IDS="$(extract_ids "$FORWARD_TEXT")"

DRIFT=()
MISSING=()

while IFS= read -r tid; do
    [[ -z "$tid" ]] && continue
    st="$(db_status "$tid")"
    case "$st" in
        DONE|SKIP|WONTFIX)
            DRIFT+=("$tid  status=$st (claimed as upcoming work)")
            ;;
        __MISSING__)
            MISSING+=("$tid  not in DB")
            ;;
    esac
done <<< "$FORWARD_IDS"

# ── Check 3: signal-line drift ─────────────────────────────────────────────

SIGNAL_DRIFT=0
HANDOFF_SIGNAL=""
FRESH_SIGNAL=""

HANDOFF_SIGNAL="$(grep -oE '^Signal:[[:space:]]+(GREEN|YELLOW|RED)' "$TARGET" | awk '{print $2}' | head -1)"
if [[ -n "$HANDOFF_SIGNAL" ]]; then
    if [[ -x "$BRIEFING_SH" ]]; then
        FRESH_SIGNAL="$(bash "$BRIEFING_SH" --signal-only 2>/dev/null || true)"
    elif [[ -f "$BRIEFING_PY" ]]; then
        FRESH_SIGNAL="$(python3 "$BRIEFING_PY" --signal-only 2>/dev/null || true)"
    fi
    if [[ "$FRESH_SIGNAL" =~ ^(GREEN|YELLOW|RED)$ && "$HANDOFF_SIGNAL" != "$FRESH_SIGNAL" ]]; then
        SIGNAL_DRIFT=1
    fi
fi

# ── Check 2: rendered block freshness ──────────────────────────────────────

BLOCK_STATE="absent"
BLOCK_DIFF=""

# Only attempt block check if both markers present AND a renderer exists.
if grep -qxF "$START_MARKER" "$TARGET" && grep -qxF "$END_MARKER" "$TARGET"; then
    if [[ -x "$RENDERER" || -f "$RENDERER" ]]; then
        current_block="$(awk -v start="$START_MARKER" -v end="$END_MARKER" '
            $0 == start { keep=1 }
            keep { print }
            $0 == end { keep=0 }
        ' "$TARGET")"
        fresh_block="$(bash "$RENDERER" 2>/dev/null || true)"
        if [[ -n "$fresh_block" && "$current_block" == "$fresh_block" ]]; then
            BLOCK_STATE="fresh"
        elif [[ -n "$fresh_block" ]]; then
            BLOCK_STATE="stale"
            BLOCK_DIFF="$(diff <(echo "$current_block") <(echo "$fresh_block") || true)"
        fi
    fi
fi

# ── Verdict ────────────────────────────────────────────────────────────────

EXIT=0
if [[ ${#DRIFT[@]} -gt 0 || "$BLOCK_STATE" == "stale" || $SIGNAL_DRIFT -eq 1 ]]; then
    EXIT=1
fi

if [[ $JSON -eq 1 ]]; then
    printf '{"drift":%d,"forward_drift_count":%d,"missing_count":%d,"block_state":"%s","signal_drift":%d,"handoff_signal":"%s","fresh_signal":"%s"}\n' \
        "$EXIT" "${#DRIFT[@]}" "${#MISSING[@]}" "$BLOCK_STATE" "$SIGNAL_DRIFT" "${HANDOFF_SIGNAL:-}" "${FRESH_SIGNAL:-}"
    exit "$EXIT"
fi

if [[ $EXIT -eq 0 && $QUIET -eq 1 ]]; then
    exit 0
fi

echo ""
echo "── Handoff Verify: ${TARGET#$REPO_ROOT/} ──────────────────────"
echo ""

if [[ ${#DRIFT[@]} -gt 0 ]]; then
    echo "  ❌ FORWARD-LOOKING DRIFT — the handoff claims these are upcoming,"
    echo "     but the DB says they are already done/skipped:"
    for d in "${DRIFT[@]}"; do
        echo "     • $d"
    done
    echo ""
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "  ⚠️  REFERENCED IDS NOT IN DB (typos or deleted tasks):"
    for m in "${MISSING[@]}"; do
        echo "     • $m"
    done
    echo ""
fi

if [[ $SIGNAL_DRIFT -eq 1 ]]; then
    echo "  ❌ SIGNAL DRIFT — the handoff's Signal line disagrees with fresh state:"
    echo "     • NEXT_SESSION.md says: Signal: ${HANDOFF_SIGNAL}"
    echo "     • briefing says:        Signal: ${FRESH_SIGNAL}"
    echo "     Fix: re-run /handoff or resolve the condition that changed the signal."
    echo ""
fi

case "$BLOCK_STATE" in
    fresh) echo "  ✅ Rendered block is fresh (byte-equal to DB)." ;;
    stale)
        echo "  ❌ STALE HANDOFF QUEUE BLOCK — rendered section differs from DB."
        echo "     Fix: bash scripts/render-handoff-queue.sh --inject ${TARGET#$REPO_ROOT/}"
        if [[ $QUIET -eq 0 ]]; then
            echo ""
            echo "     Diff (current ← | → fresh):"
            echo "$BLOCK_DIFF" | sed 's/^/       /'
        fi
        ;;
    absent) : ;;    # no-op: renderer missing or block not present
esac

echo ""
if [[ $EXIT -eq 0 ]]; then
    echo "  ✅ PASS — no drift detected."
else
    echo "  ❌ FAIL — drift detected. Resolve before committing the handoff."
fi
echo ""

exit "$EXIT"
