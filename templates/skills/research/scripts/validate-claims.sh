#!/usr/bin/env bash
# validate-claims.sh — Post-research validation for /research pipeline
#
# Generic validator: checks the core ResearchClaim shape only.
# domain_metadata is opaque — project-specific merge scripts validate its shape.
#
# Usage: bash validate-claims.sh <report.json>
# Exit: 0 = PASS, 1 = FAIL

set -uo pipefail

REPORT="${1:-}"
if [ -z "$REPORT" ]; then
    echo "❌ Usage: bash validate-claims.sh <report.json>"
    exit 1
fi

if [ ! -f "$REPORT" ]; then
    echo "❌ Report file not found: $REPORT"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "❌ jq is required but not installed."
    exit 1
fi

if ! jq empty "$REPORT" 2>/dev/null; then
    echo "❌ Invalid JSON in $REPORT"
    exit 1
fi

FAILURES=0
WARNINGS=0

echo "🔍 Validating research report: $REPORT"
echo "---"

CLAIM_COUNT=$(jq '.claims | length // 0' "$REPORT")
echo "📊 Claims found: $CLAIM_COUNT"

if [ "$CLAIM_COUNT" -eq 0 ]; then
    echo "❌ FAIL: No claims in report"
    exit 1
fi

# --- Required fields (core generic shape) ---
echo ""
echo "📋 Checking core required fields..."
MISSING=$(jq -r '
  .claims[] |
  [
    (if .id == null or (.id | type) != "string" or .id == "" then "id" else empty end),
    (if .claim == null or (.claim | type) != "string" or (.claim | length) < 10 then "claim" else empty end),
    (if .confidence == null or (.confidence | tostring | test("^(HIGH|MEDIUM|LOW|DISPUTED)$")) == false then "confidence" else empty end),
    (if .sources == null or (.sources | type) != "array" or (.sources | length) == 0 then "sources" else empty end)
  ] |
  if length > 0 then "\(.id // "UNKNOWN"): missing \(join(", "))" else empty end
' "$REPORT" 2>/dev/null) || true

if [ -n "$MISSING" ]; then
    echo "❌ FAIL: Missing required fields:"
    echo "$MISSING" | while IFS= read -r line; do echo "   $line"; done
    FAILURES=$((FAILURES + 1))
else
    echo "   ✅ All core required fields present"
fi

# --- domain_metadata type check (opaque object) ---
echo ""
echo "🧩 Checking domain_metadata shape..."
DOMAIN_ERRORS=$(jq -r '
  .claims[] |
  select(.domain_metadata != null and (.domain_metadata | type) != "object") |
  "\(.id // "UNKNOWN"): domain_metadata must be an object (got \(.domain_metadata | type))"
' "$REPORT" 2>/dev/null) || true

if [ -n "$DOMAIN_ERRORS" ]; then
    echo "❌ FAIL:"
    echo "$DOMAIN_ERRORS" | while IFS= read -r line; do echo "   $line"; done
    FAILURES=$((FAILURES + 1))
else
    echo "   ✅ domain_metadata fields are objects (or absent)"
fi

# --- Duplicate ID check ---
echo ""
echo "🔑 Checking for duplicate IDs..."
DUPS=$(jq -r '.claims[].id' "$REPORT" | sort | uniq -d)
if [ -n "$DUPS" ]; then
    echo "❌ FAIL: Duplicate IDs:"
    echo "$DUPS" | while IFS= read -r line; do echo "   $line"; done
    FAILURES=$((FAILURES + 1))
else
    echo "   ✅ No duplicate IDs"
fi

# --- Source shape check ---
echo ""
echo "📚 Checking source shape..."
SOURCE_ERRORS=$(jq -r '
  .claims[] |
  select(.sources != null and (.sources | type) == "array") |
  .sources[] |
  [
    (if .title == null or .title == "" then "source missing title" else empty end),
    (if .retrievedBy == null or (.retrievedBy | tostring | test("^T[1-4]$")) == false then "source missing/invalid retrievedBy" else empty end)
  ] |
  if length > 0 then join(", ") else empty end
' "$REPORT" 2>/dev/null) || true

if [ -n "$SOURCE_ERRORS" ]; then
    echo "❌ FAIL:"
    echo "$SOURCE_ERRORS" | while IFS= read -r line; do echo "   $line"; done
    FAILURES=$((FAILURES + 1))
else
    echo "   ✅ All sources well-formed"
fi

# --- Confidence distribution ---
echo ""
echo "📊 Confidence distribution:"
jq -r '
  .claims | group_by(.confidence) | map({
    confidence: .[0].confidence,
    count: length
  }) | .[] | "   \(.confidence): \(.count)"
' "$REPORT"

# --- Summary ---
echo ""
echo "==========================="
if [ "$FAILURES" -gt 0 ]; then
    echo "❌ FAIL — $FAILURES failure(s), $WARNINGS warning(s)"
    echo "   Note: domain-specific fields (in domain_metadata) are not checked here."
    echo "   Run your project-specific merge/validation script for those."
    exit 1
else
    echo "✅ PASS — $CLAIM_COUNT claims validated, $WARNINGS warning(s)"
    echo "   Note: only core ResearchClaim shape validated."
    echo "   Run your project-specific merge/validation script for domain_metadata."
    exit 0
fi
