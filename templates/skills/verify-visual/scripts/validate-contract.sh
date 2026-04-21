#!/usr/bin/env bash
# validate-contract.sh — preflight for verify-visual
#
# Fails fast if visual-contract.json is missing, empty, malformed, or does not
# declare any routes/components. Exit 0 if the contract is usable.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTRACT="${VISUAL_CONTRACT:-$SKILL_DIR/visual-contract.json}"
EXAMPLE="$SKILL_DIR/visual-contract.example.json"

if [ ! -f "$CONTRACT" ]; then
    echo "❌ visual-contract.json missing at $CONTRACT"
    echo "   Create one by copying the example:"
    echo "     cp $EXAMPLE $CONTRACT"
    echo "   Then edit it to declare your routes, components, and interactions."
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "❌ jq is required for contract validation."
    exit 1
fi

if ! jq empty "$CONTRACT" 2>/dev/null; then
    echo "❌ visual-contract.json is not valid JSON: $CONTRACT"
    exit 1
fi

ERRORS=0

VIEWPORTS=$(jq -r '.viewports | keys | length' "$CONTRACT")
if [ "$VIEWPORTS" -eq 0 ]; then
    echo "❌ No viewports defined. Add at least one (e.g. desktop)."
    ERRORS=$((ERRORS + 1))
fi

ROUTES=$(jq -r '.routes | length // 0' "$CONTRACT")
COMPONENTS=$(jq -r '.components | length // 0' "$CONTRACT")
if [ "$ROUTES" -eq 0 ] && [ "$COMPONENTS" -eq 0 ]; then
    echo "❌ Contract must declare at least one route OR one component."
    ERRORS=$((ERRORS + 1))
fi

# Every route must have id, url, wait_for
ROUTE_ERRS=$(jq -r '
  .routes // [] |
  to_entries[] |
  select(.value.id == null or .value.url == null or .value.wait_for == null) |
  "route[\(.key)] missing id/url/wait_for"
' "$CONTRACT")
if [ -n "$ROUTE_ERRS" ]; then
    echo "❌ Route shape errors:"
    echo "$ROUTE_ERRS" | sed 's/^/   /'
    ERRORS=$((ERRORS + 1))
fi

# Every component must have id, selector
COMP_ERRS=$(jq -r '
  .components // [] |
  to_entries[] |
  select(.value.id == null or .value.selector == null) |
  "component[\(.key)] missing id/selector"
' "$CONTRACT")
if [ -n "$COMP_ERRS" ]; then
    echo "❌ Component shape errors:"
    echo "$COMP_ERRS" | sed 's/^/   /'
    ERRORS=$((ERRORS + 1))
fi

# Vision check provider must be one of the known modes
VISION=$(jq -r '.vision_check.provider // "none"' "$CONTRACT")
case "$VISION" in
    none|gemini|manual) ;;
    *)
        echo "❌ vision_check.provider must be one of: none, gemini, manual (got '$VISION')"
        ERRORS=$((ERRORS + 1))
        ;;
esac

if [ "$ERRORS" -gt 0 ]; then
    echo ""
    echo "Contract validation FAILED with $ERRORS issue(s)."
    exit 1
fi

echo "✅ visual-contract.json valid"
echo "   viewports: $VIEWPORTS | routes: $ROUTES | components: $COMPONENTS | vision: $VISION"
exit 0
