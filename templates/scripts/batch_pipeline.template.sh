#!/usr/bin/env bash
# Batch Pipeline — resumable processing with checkpoint/resume
# Usage: bash batch_pipeline.sh <input-file> [--resume]
set -euo pipefail

INPUT_FILE="${1:?Usage: batch_pipeline.sh <input-file>}"
CHECKPOINT=".batch_checkpoint"
RESUME=false
[[ "${2:-}" == "--resume" ]] && RESUME=true

# Load checkpoint
LAST_DONE=0
if $RESUME && [ -f "$CHECKPOINT" ]; then
    LAST_DONE=$(cat "$CHECKPOINT")
    echo "Resuming from item $LAST_DONE"
fi

# Trap for graceful shutdown
trap 'echo "$CURRENT" > "$CHECKPOINT"; echo "Interrupted at item $CURRENT"; exit 130' INT

TOTAL=$(wc -l < "$INPUT_FILE")
CURRENT=0

while IFS= read -r ITEM; do
    CURRENT=$((CURRENT + 1))
    [ "$CURRENT" -le "$LAST_DONE" ] && continue

    echo "[$CURRENT/$TOTAL] Processing: $ITEM"
    %%BATCH_PROCESS_COMMAND%%

    echo "$CURRENT" > "$CHECKPOINT"
done < "$INPUT_FILE"

echo "Complete: $TOTAL items processed"
rm -f "$CHECKPOINT"
