#!/bin/bash
# Hook: Static Analysis Gate (PostToolUse)
# Fires after Edit and Write tool calls.
# Runs Semgrep on the modified file using project-local rules (.semgrep/).
#
# Replaces: nothing (new capability — SAST integration)
#
# Returns: additionalContext with ERROR/WARNING findings (non-blocking)
# Silent when no findings, semgrep absent, or no .semgrep/ config directory.
# Never blocking — PostToolUse hooks are advisory only.

set -euo pipefail

INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Only fire on Edit and Write tool calls
case "$TOOL" in
    Edit|Write) ;;
    *) exit 0 ;;
esac

# Extract file path from tool input
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Skip if no file path
if [ -z "$FILE" ]; then
    exit 0
fi

# Skip silently if semgrep is not installed — no token cost
if ! command -v semgrep >/dev/null 2>&1; then
    exit 0
fi

# Resolve project root via git
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
    exit 0
fi

PROJECT_ROOT=$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -z "$PROJECT_ROOT" ]; then
    exit 0
fi

# ── Semgrep hardened environment ─────────────────────────────────────
_semgrep_env() {
  # SSL certificate bundle — try common locations
  if [ -z "${SSL_CERT_FILE:-}" ]; then
    for _cert in /etc/ssl/cert.pem /private/etc/ssl/cert.pem \
                 /opt/homebrew/etc/openssl@3/cert.pem \
                 /opt/homebrew/etc/ca-certificates/cert.pem \
                 /etc/ssl/certs/ca-certificates.crt; do
      [ -r "$_cert" ] && export SSL_CERT_FILE="$_cert" && break
    done
  fi
  # Redirect Semgrep user-data to project hooks dir
  local _hooks_dir="$PROJECT_ROOT/.claude/hooks"
  mkdir -p "$_hooks_dir" 2>/dev/null || true
  : "${SEMGREP_LOG_FILE:="$_hooks_dir/semgrep.log"}"
  : "${SEMGREP_SETTINGS_FILE:="$_hooks_dir/semgrep-settings.yml"}"
  : "${SEMGREP_VERSION_CACHE_PATH:="$_hooks_dir/semgrep-version-cache"}"
  : "${SEMGREP_VERSION_CHECK_TIMEOUT:=1}"
  export SEMGREP_LOG_FILE SEMGREP_SETTINGS_FILE SEMGREP_VERSION_CACHE_PATH SEMGREP_VERSION_CHECK_TIMEOUT
}

_semgrep_probe() {
  # Quick sanity check — if semgrep can't start, skip gracefully
  # Note: no stdout output here — PostToolUse hooks must emit only valid JSON or nothing
  _semgrep_env
  if ! semgrep --version >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

# Skip silently if no .semgrep/ config directory — project has not opted in
if [ ! -d "$PROJECT_ROOT/.semgrep" ]; then
    exit 0
fi

# Probe semgrep with hardened env before committing to a full scan
_semgrep_probe || exit 0

# Resolve the file path relative to PROJECT_ROOT.
# This is mandatory: semgrep's paths.exclude patterns only match relative paths.
# Absolute paths silently bypass rule-level exclusions.
REL_PATH=$(python3 -c "
import os, sys
try:
    rel = os.path.relpath('$FILE', '$PROJECT_ROOT')
    print(rel)
except Exception:
    sys.exit(1)
" 2>/dev/null || echo "")

if [ -z "$REL_PATH" ]; then
    exit 0
fi

# Run semgrep with local config, JSON output, quiet mode, 5s timeout.
# --config=auto is intentionally avoided (too slow for PostToolUse: ~3.4s vs ~1.0s local).
# Pass relative path so paths.exclude patterns work correctly.
_semgrep_env
SEMGREP_OUTPUT=$(cd "$PROJECT_ROOT" && semgrep \
    --config=.semgrep/ \
    --severity=ERROR \
    "./$REL_PATH" \
    --json \
    --quiet \
    --timeout 5 \
    2>/dev/null || echo "{}")

# Extract findings from JSON output
FINDINGS=$(echo "$SEMGREP_OUTPUT" | jq -r '.results // [] | length' 2>/dev/null || echo "0")

if [ "$FINDINGS" -eq 0 ]; then
    # No findings — silent, no token cost
    exit 0
fi

# Build the context message from findings
# Semgrep with --severity=ERROR returns only ERROR and above by default.
# We distinguish severities from the results themselves.
CONTEXT=$(echo "$SEMGREP_OUTPUT" | jq -r '
    .results[]
    | (
        if (.extra.severity // "ERROR") == "WARNING"
        then "⚠️ SAST: " + .check_id + " — " + .extra.message + " (" + .path + ":" + (.start.line | tostring) + ")"
        else "⛔ SAST: " + .check_id + " — " + .extra.message + " (" + .path + ":" + (.start.line | tostring) + ")"
        end
      )
' 2>/dev/null || echo "")

if [ -z "$CONTEXT" ]; then
    exit 0
fi

jq -n --arg ctx "$CONTEXT" '{
    hookSpecificOutput: {
        hookEventName: "PostToolUse",
        additionalContext: $ctx
    }
}'

exit 0
