#!/usr/bin/env bash
# Pre-commit hook — Gate 1 (quality-gates.md)
# Blocks: lint, type check, SAST (S1/S2), secrets
# Warns: coherence, knowledge health
# Install: cp pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#
# ┌─────────────────────────────────────────────────────────────────┐
# │  TEMPLATE PLACEHOLDERS — replace before use                     │
# │                                                                 │
# │  %%LINT_COMMAND%%         Linter invocation for your stack      │
# │                           e.g. "ruff check ."                   │
# │                           e.g. "eslint src/ --max-warnings 0"   │
# │                           e.g. "golangci-lint run"              │
# │                                                                 │
# │  %%TYPE_CHECK_COMMAND%%   Type checker for your stack           │
# │                           e.g. "mypy src/"                      │
# │                           e.g. "tsc --noEmit"                   │
# │                           Leave as "true" for no-op (e.g. Go)  │
# │                                                                 │
# │  Example sed replacement:                                       │
# │    sed 's/%%LINT_COMMAND%%/ruff check ./g; \                    │
# │         s/%%TYPE_CHECK_COMMAND%%/mypy src\//g' \                │
# │      pre-commit.template.sh > .git/hooks/pre-commit             │
# │    chmod +x .git/hooks/pre-commit                               │
# └─────────────────────────────────────────────────────────────────┘

set -euo pipefail

PROJECT_ROOT="$(git rev-parse --show-toplevel)"

PASS=0
FAIL=1
BLOCKED=false

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_require_tool() {
  command -v "$1" >/dev/null 2>&1
}

# macOS-compatible timeout wrapper (macOS ships gtimeout via coreutils or not at all)
_timeout() {
  local secs=$1; shift
  "$@" &
  local pid=$!
  ( sleep "$secs" && kill "$pid" 2>/dev/null ) &
  local watchdog=$!
  wait "$pid" 2>/dev/null
  local rc=$?
  kill "$watchdog" 2>/dev/null 2>&1
  wait "$watchdog" 2>/dev/null 2>&1
  return $rc
}

_pass() {
  echo "   PASS: $1"
}

_fail() {
  echo "   FAIL: $1"
  BLOCKED=true
}

_warn() {
  echo "   WARN: $1"
}

_skip() {
  echo "   SKIP: $1"
}

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
  local _hooks_dir="${PROJECT_ROOT:-.}/.claude/hooks"
  mkdir -p "$_hooks_dir" 2>/dev/null || true
  : "${SEMGREP_LOG_FILE:="$_hooks_dir/semgrep.log"}"
  : "${SEMGREP_SETTINGS_FILE:="$_hooks_dir/semgrep-settings.yml"}"
  : "${SEMGREP_VERSION_CACHE_PATH:="$_hooks_dir/semgrep-version-cache"}"
  : "${SEMGREP_VERSION_CHECK_TIMEOUT:=1}"
  export SEMGREP_LOG_FILE SEMGREP_SETTINGS_FILE SEMGREP_VERSION_CACHE_PATH SEMGREP_VERSION_CHECK_TIMEOUT
}

_semgrep_probe() {
  # Quick sanity check — if semgrep can't start, skip gracefully
  _semgrep_env
  if ! semgrep --version >/dev/null 2>&1; then
    echo "  ⚠️  Semgrep unavailable (startup probe failed) — skipping SAST"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Step 1 — Lint
# ---------------------------------------------------------------------------

echo "── Pre-commit: Lint ──"

if %%LINT_COMMAND%%; then
  _pass "Lint"
else
  _fail "Lint — fix errors above before committing"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 2 — Type check
# ---------------------------------------------------------------------------

echo "── Pre-commit: Type check ──"

if %%TYPE_CHECK_COMMAND%%; then
  _pass "Type check"
else
  _fail "Type check — fix errors above before committing"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 3 — SAST (semgrep, staged files only)
# ---------------------------------------------------------------------------

echo "── Pre-commit: SAST ──"

if ! _require_tool semgrep; then
  _skip "SAST (semgrep not installed)"
elif [ ! -d "$PROJECT_ROOT/.semgrep" ]; then
  _skip "SAST (.semgrep/ directory not found)"
elif ! _semgrep_probe; then
  _skip "SAST (semgrep probe failed)"
else
  STAGED_FILES="$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(py|js|ts|go|rs|swift)$' || true)"

  if [ -z "$STAGED_FILES" ]; then
    _skip "SAST (no matching staged files)"
  else
    FILE_COUNT="$(echo "$STAGED_FILES" | wc -l | tr -d ' ')"
    echo "   Scanning $FILE_COUNT staged file(s) with semgrep..."

    cd "$PROJECT_ROOT"
    _semgrep_env
    set +e
    echo "$STAGED_FILES" | xargs _timeout 15 semgrep --config=.semgrep/ --severity=ERROR --quiet --timeout 5
    SAST_RC=$?
    set -e

    if [ "$SAST_RC" -eq 0 ]; then
      _pass "SAST"
    elif [ "$SAST_RC" -eq 137 ]; then
      _warn "SAST timed out after 15s — skipping (non-blocking)"
    else
      _fail "SAST — semgrep found ERROR-severity findings above"
    fi
  fi
fi

echo ""

# ---------------------------------------------------------------------------
# Step 4 — Secrets (gitleaks)
# ---------------------------------------------------------------------------

echo "── Pre-commit: Secrets ──"

if ! _require_tool gitleaks; then
  _skip "Secrets scan (gitleaks not installed)"
else
  set +e
  gitleaks protect --staged --no-banner
  GITLEAKS_RC=$?
  set -e

  if [ "$GITLEAKS_RC" -eq 0 ]; then
    _pass "Secrets scan"
  else
    _fail "Secrets scan — gitleaks found potential secrets in staged files"
  fi
fi

echo ""

# ---------------------------------------------------------------------------
# Non-blocking warnings
# ---------------------------------------------------------------------------

echo "── Pre-commit: Warnings (non-blocking) ──"

# Coherence check (placeholder — wire to coherence_check.sh if present)
if [ -f "$PROJECT_ROOT/coherence_check.sh" ]; then
  set +e
  bash "$PROJECT_ROOT/coherence_check.sh" --quiet
  COHERENCE_RC=$?
  set -e
  if [ "$COHERENCE_RC" -ne 0 ]; then
    _warn "Coherence: stale references found — run coherence_check.sh --fix for hints"
  fi
fi

# Knowledge health (placeholder — extend with harvest.sh or similar)
# _warn "Knowledge health: unpromoted lessons pending — run db_queries.sh harvest"

echo ""

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

echo "── Pre-commit: Summary ──"

if [ "$BLOCKED" = true ]; then
  echo "   BLOCKED — one or more checks failed. Fix errors above and re-commit."
  echo ""
  exit 1
else
  echo "   PASSED — all blocking checks clear."
  echo ""
  exit 0
fi
