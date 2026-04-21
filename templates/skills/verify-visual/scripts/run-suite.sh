#!/usr/bin/env bash
# run-suite.sh — orchestrate verify-visual Playwright run
#
# Preflight: validates contract, checks Playwright installed, creates report dir.
# Invokes: npx playwright test against the skill's specs/ directory.
#
# Usage:
#   bash run-suite.sh                      # normal run
#   bash run-suite.sh --update             # update baselines
#   bash run-suite.sh --spec routes        # single spec
#   bash run-suite.sh --project chromium   # specific Playwright project

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SPECS_DIR="$SKILL_DIR/specs"
REPORTS_DIR="$SKILL_DIR/reports"
TIMESTAMP="$(date '+%Y-%m-%d-%H%M')"
RUN_DIR="$REPORTS_DIR/$TIMESTAMP"

UPDATE=false
SPEC=""
PROJECT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --update)   UPDATE=true ;;
        --spec)     shift; SPEC="$1" ;;
        --project)  shift; PROJECT="$1" ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -20
            exit 0
            ;;
        *) echo "Unknown flag: $1" >&2; exit 1 ;;
    esac
    shift
done

# 1. Preflight — contract must be valid
if ! bash "$SCRIPT_DIR/validate-contract.sh"; then
    echo "❌ Contract validation failed. Fix the contract before running the suite."
    exit 1
fi

# 2. Preflight — Playwright must be on PATH
if ! command -v npx >/dev/null 2>&1; then
    echo "❌ npx not found. Install Node.js and ensure npx is on PATH."
    exit 1
fi

if ! npx --no-install playwright --version >/dev/null 2>&1; then
    echo "❌ Playwright not installed. Run:"
    echo "     npm install --save-dev @playwright/test"
    echo "     npx playwright install"
    exit 1
fi

mkdir -p "$RUN_DIR"

echo "============================================================"
echo "  verify-visual"
echo "  Run: $TIMESTAMP"
echo "  Report dir: $RUN_DIR"
echo "  Specs: $SPECS_DIR"
echo "============================================================"

# 3. Build Playwright args
PW_ARGS=("--reporter=list,html")
[ -n "$PROJECT" ] && PW_ARGS+=("--project=$PROJECT")
$UPDATE && PW_ARGS+=("--update-snapshots")

if [ -n "$SPEC" ]; then
    TARGET="$SPECS_DIR/$SPEC.spec.ts"
    [ -f "$TARGET" ] || TARGET="$SPECS_DIR/$SPEC"
    PW_ARGS+=("$TARGET")
else
    PW_ARGS+=("$SPECS_DIR")
fi

# 4. Run
export VISUAL_CONTRACT="${VISUAL_CONTRACT:-$SKILL_DIR/visual-contract.json}"
export VERIFY_VISUAL_RUN_DIR="$RUN_DIR"

echo "→ npx playwright test ${PW_ARGS[*]}"
set +e
npx playwright test "${PW_ARGS[@]}"
EXIT=$?
set -e

echo ""
if [ "$EXIT" -eq 0 ]; then
    echo "✅ verify-visual suite PASSED"
else
    echo "❌ verify-visual suite FAILED (exit $EXIT)"
    echo "   Open the HTML report:"
    echo "     npx playwright show-report"
fi

exit "$EXIT"
