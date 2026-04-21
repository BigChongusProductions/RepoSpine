#!/bin/bash
# Consolidated PreToolUse Gate — single entry point for all pre-tool checks.
#
# Replaces 3+ separate PreToolUse hook registrations with 1, reducing
# "Async hook PreToolUse completed" log lines and letting projects disable
# sub-checks by editing this router rather than settings.json.
#
# Internal routing by tool_name:
#   Edit|Write|MultiEdit → pre-edit-check (delegation + architecture protection)
#   Bash                 → protect-databases
#   Agent                → agent-spawn-gate
#   Other                → silent exit
#
# Any sub-check may short-circuit the chain by writing hookSpecificOutput JSON
# and exiting 0. We use `exec` to hand off stdin cleanly.

# Fire-rate telemetry
source "$(dirname "${BASH_SOURCE[0]}")/lib-fire-counter.sh"

set -euo pipefail

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
HOOKS_DIR="$CWD/.claude/hooks"

case "$TOOL" in
    Edit|Write|MultiEdit)
        if [ -x "$HOOKS_DIR/pre-edit-check.sh" ]; then
            exec "$HOOKS_DIR/pre-edit-check.sh" <<< "$INPUT"
        fi
        ;;
    Bash)
        if [ -x "$HOOKS_DIR/protect-databases.sh" ]; then
            exec "$HOOKS_DIR/protect-databases.sh" <<< "$INPUT"
        fi
        ;;
    Agent)
        if [ -x "$HOOKS_DIR/agent-spawn-gate.sh" ]; then
            exec "$HOOKS_DIR/agent-spawn-gate.sh" <<< "$INPUT"
        fi
        ;;
    *)
        # Read/Glob/Grep/etc — no pre-tool checks configured
        ;;
esac

exit 0
