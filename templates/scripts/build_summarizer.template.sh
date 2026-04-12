#!/usr/bin/env bash
# Build Summarizer — runs build, test, and SAST steps
#
# Usage: bash build_summarizer.sh [build|test|clean]
#
# PLACEHOLDERS:
#   %%BUILD_COMMAND%%   — build command for this tech stack (e.g. npm run build)
#   %%TEST_COMMAND%%    — test command for this tech stack  (e.g. npm test)
#   %%LINT_COMMAND%%    — lint command for this tech stack  (e.g. npm run lint)

set -euo pipefail

MODE="${1:-build}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR")"

# ── Utility: macOS-compatible timeout wrapper ─────────────────────────────────
_timeout() {
  local secs=$1; shift
  "$@" &
  local pid=$!
  ( sleep "$secs" && kill "$pid" 2>/dev/null ) &
  local watchdog=$!
  wait "$pid" 2>/dev/null
  local rc=$?
  kill "$watchdog" 2>/dev/null
  wait "$watchdog" 2>/dev/null
  return $rc
}

# ── Utility: check if a tool is available ────────────────────────────────────
_require_tool() {
  command -v "$1" >/dev/null 2>&1
}

# ── Semgrep hardened environment ─────────────────────────────────────
_semgrep_env() {
  if [ -z "${SSL_CERT_FILE:-}" ]; then
    for _cert in /etc/ssl/cert.pem /private/etc/ssl/cert.pem \
                 /opt/homebrew/etc/openssl@3/cert.pem \
                 /opt/homebrew/etc/ca-certificates/cert.pem \
                 /etc/ssl/certs/ca-certificates.crt; do
      [ -r "$_cert" ] && export SSL_CERT_FILE="$_cert" && break
    done
  fi
  local _hooks_dir="${PROJECT_ROOT}/.claude/hooks"
  mkdir -p "$_hooks_dir" 2>/dev/null || true
  : "${SEMGREP_LOG_FILE:="$_hooks_dir/semgrep.log"}"
  : "${SEMGREP_SETTINGS_FILE:="$_hooks_dir/semgrep-settings.yml"}"
  : "${SEMGREP_VERSION_CACHE_PATH:="$_hooks_dir/semgrep-version-cache"}"
  : "${SEMGREP_VERSION_CHECK_TIMEOUT:=1}"
  export SEMGREP_LOG_FILE SEMGREP_SETTINGS_FILE SEMGREP_VERSION_CACHE_PATH SEMGREP_VERSION_CHECK_TIMEOUT
}

_semgrep_probe() {
  _semgrep_env
  if ! semgrep --version >/dev/null 2>&1; then
    echo "  ⚠️  Semgrep unavailable (startup probe failed) — skipping SAST"
    return 1
  fi
  return 0
}

# ── SAST availability check ───────────────────────────────────────────────────
_sast_available() {
  if ! _require_tool semgrep; then
    echo "-- SAST: skipped (semgrep not installed)"
    return 1
  fi
  if [ ! -d "${PROJECT_ROOT}/.semgrep" ]; then
    echo "-- SAST: skipped (no .semgrep/ config dir)"
    return 1
  fi
  if ! _semgrep_probe; then
    return 1
  fi
  return 0
}

# ── Step counters ─────────────────────────────────────────────────────────────
STEPS_PASSED=0
STEPS_FAILED=0

_step_pass() { STEPS_PASSED=$(( STEPS_PASSED + 1 )); }
_step_fail() { STEPS_FAILED=$(( STEPS_FAILED + 1 )); }

# ── Step: Lint ────────────────────────────────────────────────────────────────
run_lint() {
  echo "── Step: Lint ──"
  if %%LINT_COMMAND%% 2>&1; then
    echo "   Lint: PASSED"
    _step_pass
  else
    echo "   Lint: FAILED"
    _step_fail
    return 1
  fi
}

# ── Step: Build ───────────────────────────────────────────────────────────────
run_build() {
  echo "── Step: Build ──"
  if %%BUILD_COMMAND%% 2>&1; then
    echo "   Build: PASSED"
    _step_pass
  else
    echo "   Build: FAILED"
    _step_fail
    return 1
  fi
}

# ── Step: Test ────────────────────────────────────────────────────────────────
run_tests() {
  echo "── Step: Test ──"
  if %%TEST_COMMAND%% 2>&1; then
    echo "   Tests: PASSED"
    _step_pass
  else
    echo "   Tests: FAILED"
    _step_fail
    return 1
  fi
}

# ── Step: SAST (quick — changed files, security rules only) ──────────────────
run_sast_quick() {
  echo "── Step: SAST (quick scan) ──"
  if ! _sast_available; then
    return 0
  fi

  _timeout 30 semgrep --config=.semgrep/ --severity=ERROR . --quiet
  local rc=$?

  if [ "$rc" -eq 137 ]; then
    echo "   SAST: timed out (30s) — skipping"
  elif [ "$rc" -ne 0 ]; then
    echo "   SAST: findings detected (exit $rc) — review before merge"
    _step_fail
    return 1
  else
    echo "   SAST: PASSED (no ERROR-severity findings)"
    _step_pass
  fi
}

# ── Step: SAST (full — all rules, all files, summary count) ──────────────────
run_sast_full() {
  echo "── Step: SAST (full scan) ──"
  if ! _sast_available; then
    return 0
  fi

  if ! _require_tool jq; then
    echo "   SAST: skipped (jq not installed; required for full-scan summary)"
    return 0
  fi

  local findings
  findings=$( _timeout 60 semgrep --config=.semgrep/ . --json 2>/dev/null | jq '.results | length' 2>/dev/null || echo "timeout" )
  local rc=$?

  if [ "$findings" = "timeout" ] || [ "$rc" -eq 137 ]; then
    echo "   SAST: timed out (60s) — skipping"
  elif [ "$findings" -eq 0 ] 2>/dev/null; then
    echo "   SAST: PASSED (0 findings)"
    _step_pass
  else
    echo "   SAST: $findings finding(s) detected — review output above"
    _step_fail
    return 1
  fi
}

# ── Mode dispatch ─────────────────────────────────────────────────────────────
echo ""
echo "── Build Summarizer ($MODE) — $(date '+%H:%M:%S') ──"
echo ""

case "$MODE" in
  build)
    run_lint || true
    run_build
    run_sast_quick || true
    ;;
  test)
    run_lint || true
    run_build
    run_tests
    run_sast_full || true
    ;;
  clean)
    echo "── Step: Clean ──"
    echo "   No clean target configured"
    ;;
  *)
    echo "Usage: bash build_summarizer.sh [build|test|clean]"
    exit 1
    ;;
esac

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
TOTAL=$(( STEPS_PASSED + STEPS_FAILED ))
if [ "$STEPS_FAILED" -eq 0 ]; then
  echo "── Summary: PASSED ($STEPS_PASSED/$TOTAL steps) ──"
  exit 0
else
  echo "── Summary: FAILED ($STEPS_FAILED/$TOTAL steps failed) ──"
  exit 1
fi
