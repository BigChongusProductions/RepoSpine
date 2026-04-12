#!/usr/bin/env bash
# harvest.sh — Scan project lessons for patterns eligible for promotion
#
# Scans %%LESSONS_FILE%% for entries not yet promoted to LESSONS_UNIVERSAL.md.
# Run on-demand or at session end to catch unpromoted patterns.
#
# Usage: bash harvest.sh [--dry-run]

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LESSONS="$PROJECT_DIR/%%LESSONS_FILE%%"
# Use project-local LESSONS_UNIVERSAL.md
if [ -f "$PROJECT_DIR/LESSONS_UNIVERSAL.md" ]; then
    UNIVERSAL="$PROJECT_DIR/LESSONS_UNIVERSAL.md"
else
    UNIVERSAL="$PROJECT_DIR/LESSONS_UNIVERSAL.md"  # will be created if needed
fi

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

if [ ! -f "$LESSONS" ]; then
    echo "❌ %%LESSONS_FILE%% not found at $LESSONS"
    exit 1
fi

if [ ! -f "$UNIVERSAL" ]; then
    echo "⚠️  LESSONS_UNIVERSAL.md not found — creating at $UNIVERSAL"
    cat > "$UNIVERSAL" << 'HEREDOC'
# Universal Lessons
> Patterns that recur across 2+ projects. Promoted from project-level LESSONS files.

| Date | Pattern | Source Project | Prevention Rule |
|------|---------|---------------|-----------------|
HEREDOC
fi

echo "── Harvest: scanning %%LESSONS_FILE%% for unpromoted patterns ──"
echo ""

# Count and collect unpromoted entries (table rows + ### blocks)
# Uses same column-agnostic Python logic as session_briefing.sh
HARVEST_OUTPUT=$(python3 -c "
import sys

lessons_path = sys.argv[1]
unpromoted = []

with open(lessons_path) as f:
    lines = f.readlines()

i = 0
while i < len(lines):
    s = lines[i].strip()

    # Table rows: pipe-delimited, skip header and separator
    if s.startswith('|') and not s.startswith('| Date') and not s.startswith('|---'):
        cols = [c_.strip() for c_ in s.split('|') if c_.strip()]
        if any(col == 'No' or col.startswith('No —') for col in cols):
            # Extract date and what-happened from first two columns
            label = ' | '.join(cols[:2]) if len(cols) >= 2 else cols[0]
            unpromoted.append(label)
        i += 1

    # ### blocks: heading followed by **Key:** value lines
    elif s.startswith('### '):
        heading = s
        # Scan the block lines following the heading
        j = i + 1
        block_promoted = None
        while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith('### ') and not lines[j].strip().startswith('## '):
            if lines[j].strip().startswith('**Promoted:**'):
                val = lines[j].strip().split('**Promoted:**')[1].strip()
                block_promoted = val
            j += 1
        if block_promoted is not None and (block_promoted == 'No' or block_promoted.startswith('No')):
            # Use heading text (strip ### prefix) as label
            unpromoted.append(heading.lstrip('#').strip())
        i = j
    else:
        i += 1

print(len(unpromoted))
for entry in unpromoted:
    print(entry)
" "$LESSONS" 2>/dev/null)

UNPROMOTED=$(echo "$HARVEST_OUTPUT" | head -n1)
UNPROMOTED="${UNPROMOTED:-0}"

if ! [[ "$UNPROMOTED" =~ ^[0-9]+$ ]] || [ "$UNPROMOTED" -le 0 ]; then
    echo "✅ No unpromoted patterns found."
    exit 0
fi

echo "📋 $UNPROMOTED unpromoted pattern(s) found:"
echo ""
# Display each unpromoted entry (lines 2+ from Python output)
echo "$HARVEST_OUTPUT" | tail -n +2 | while IFS= read -r line; do
    echo "  • $line"
done

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "(dry run — no changes made)"
else
    echo ""
    echo "Review the patterns above. To promote, manually add to $UNIVERSAL"
    echo "and mark the source entry as promoted in %%LESSONS_FILE%%."
fi
