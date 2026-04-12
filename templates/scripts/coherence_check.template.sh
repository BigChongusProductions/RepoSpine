#!/usr/bin/env bash
# Coherence Check — scan markdown files for stale references
#
# ┌─────────────────────────────────────────────────────────────────┐
# │  TEMPLATE PLACEHOLDERS — replace before use                     │
# │                                                                 │
# │  %%SKIP_PATTERN_1%%   Filename to exclude from scanning         │
# │                       Always include: "coherence_registry.sh"  │
# │                       and "coherence_check.sh" (self-exclude)  │
# │  %%SKIP_PATTERN_2%%   Additional skip pattern (e.g. lessons     │
# │                       file, since it documents deprecated names)│
# │                                                                 │
# │  The SKIP_PATTERNS array below pre-includes the two universal   │
# │  self-exclusions. Add project-specific entries after them.      │
# │                                                                 │
# │  Example sed replacement (if your lessons file differs):        │
# │    sed 's/%%LESSONS_FILE%%/LESSONS_MYPROJECT.md/g' \            │
# │      coherence_check.template.sh > coherence_check.sh           │
# │                                                                 │
# │  If you have no extra skip patterns beyond the two universal    │
# │  ones, just delete the %%SKIP_PATTERN_*%% placeholder lines     │
# │  from the SKIP_PATTERNS array.                                  │
# └─────────────────────────────────────────────────────────────────┘

SCRIPT_DIR="$(dirname "$0")"
REGISTRY="$SCRIPT_DIR/coherence_registry.sh"
QUIET=false
SHOW_HINTS=false

for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=true ;;
        --fix)   SHOW_HINTS=true ;;
    esac
done

if [ ! -f "$REGISTRY" ]; then
    echo "❌ coherence_registry.sh not found at $REGISTRY"
    exit 2
fi
source "$REGISTRY"

# Always skip the registry and this script itself (they document deprecated names by design).
# PROJECT_MEMORY.md and CAPTAINS_LOG.md are skipped because they contain canonical term
# reference tables that intentionally list deprecated terms alongside their replacements.
# Add additional project-specific files that should not be scanned below.
SKIP_PATTERNS=("coherence_registry.sh" "coherence_check.sh" "%%LESSONS_FILE%%" "PROJECT_MEMORY.md" "CAPTAINS_LOG.md")
FIND_EXCLUDES=()
for skip in "${SKIP_PATTERNS[@]}"; do
    FIND_EXCLUDES+=("!" "-name" "$skip")
done

MARKDOWN_FILES=$(find "$SCRIPT_DIR" -maxdepth 1 -name "*.md" "${FIND_EXCLUDES[@]}" 2>/dev/null)
if [ -z "$MARKDOWN_FILES" ]; then
    [ "$QUIET" = false ] && echo "No markdown files found to check."
    exit 0
fi

TOTAL_HITS=0
declare -a REPORT_LINES=()

for i in "${!DEPRECATED_PATTERNS[@]}"; do
    pattern="${DEPRECATED_PATTERNS[$i]}"
    canonical="${CANONICAL_LABELS[$i]}"
    introduced="${INTRODUCED_ON[$i]}"

    while IFS= read -r file; do
        matches=$(grep -n "$pattern" "$file" 2>/dev/null)
        if [ -n "$matches" ]; then
            filename=$(basename "$file")
            while IFS= read -r match; do
                lineno=$(echo "$match" | cut -d: -f1)
                content=$(echo "$match" | cut -d: -f2- | sed 's/^[[:space:]]*//')
                REPORT_LINES+=("  $filename:$lineno  →  \"$content\"")
                if [ "$SHOW_HINTS" = true ]; then
                    REPORT_LINES+=("    ↳ Replace with: $canonical  [since $introduced]")
                fi
                TOTAL_HITS=$((TOTAL_HITS + 1))
            done <<< "$matches"
        fi
    done <<< "$MARKDOWN_FILES"
done

if [ $TOTAL_HITS -eq 0 ]; then
    [ "$QUIET" = false ] && echo "✅ Coherence check passed — no stale references found."
    exit 0
else
    if [ "$QUIET" = false ]; then
        echo ""
        echo "⚠️  Coherence check: $TOTAL_HITS stale reference(s) found"
        echo "────────────────────────────────────────────────────────"
        for line in "${REPORT_LINES[@]}"; do
            echo "$line"
        done
        echo "────────────────────────────────────────────────────────"
        echo "Run with --fix for replacement hints."
        echo ""
    fi
    exit 1
fi
