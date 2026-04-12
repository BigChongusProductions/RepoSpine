#!/usr/bin/env bash
set -euo pipefail

# post-bootstrap-health.sh
# Validates a deployed project is functional after bootstrap.
# Usage: bash post-bootstrap-health.sh [project-dir]
# Exit codes: 0=all pass, 1=any FAIL, 2=no FAILs but WARNs present

PROJECT_DIR="${1:-$(pwd)}"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "ERROR: Project directory not found: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
RESULTS=()

# ── helpers ──────────────────────────────────────────────────────────────────

pass() { RESULTS+=("  [PASS] $1"); (( PASS_COUNT++ )) || true; }
fail() { RESULTS+=("  [FAIL] $1"); (( FAIL_COUNT++ )) || true; }
warn() { RESULTS+=("  [WARN] $1"); (( WARN_COUNT++ )) || true; }

separator="──────────────────────────────────────────────"

# ── check 1: hooks executable ─────────────────────────────────────────────

check_hooks() {
  local hooks_dir=".claude/hooks"
  if [[ ! -d "$hooks_dir" ]]; then
    fail "Hooks: $hooks_dir directory not found"
    return
  fi

  local total=0
  local non_exec=()
  while IFS= read -r -d '' f; do
    (( total++ )) || true
    if [[ ! -x "$f" ]]; then
      non_exec+=("$f")
    fi
  done < <(find "$hooks_dir" -maxdepth 1 -name "*.sh" -print0 2>/dev/null)

  if [[ $total -eq 0 ]]; then
    warn "Hooks: no .sh files found in $hooks_dir"
    return
  fi

  local exec_count=$(( total - ${#non_exec[@]} ))
  if [[ ${#non_exec[@]} -eq 0 ]]; then
    pass "Hooks: ${exec_count}/${total} executable"
  else
    local names
    names=$(printf '%s ' "${non_exec[@]}")
    fail "Hooks: ${exec_count}/${total} executable — not executable: ${names% }"
  fi
}

# ── check 2: settings valid ───────────────────────────────────────────────

check_settings() {
  local settings=".claude/settings.json"
  if [[ ! -f "$settings" ]]; then
    fail "Settings: $settings not found"
    return
  fi

  local valid=0
  if command -v jq &>/dev/null; then
    if jq empty "$settings" 2>/dev/null; then
      valid=1
    fi
  else
    if python3 -c "import json; json.load(open('$settings'))" 2>/dev/null; then
      valid=1
    fi
  fi

  if [[ $valid -eq 1 ]]; then
    pass "Settings: $settings is valid JSON"
  else
    fail "Settings: $settings exists but is invalid JSON"
  fi
}

# ── check 3: database functional ─────────────────────────────────────────

check_database() {
  # Find *.db in project root, excluding backups/
  local db_file
  db_file=$(find . -maxdepth 1 -name "*.db" ! -path "./backups/*" 2>/dev/null | head -1)

  if [[ -z "$db_file" ]]; then
    fail "Database: no *.db file found in project root"
    return
  fi

  # Strip leading ./
  db_file="${db_file#./}"

  if [[ ! -f "db_queries.sh" ]]; then
    warn "Database: $db_file found but db_queries.sh missing — cannot run health check"
    return
  fi

  local health_output
  if health_output=$(bash db_queries.sh health 2>&1); then
    # Try to extract table count from output
    local table_count=""
    if echo "$health_output" | grep -q "table"; then
      table_count=$(echo "$health_output" | grep -o '[0-9]* table' | head -1 || true)
    fi
    if [[ -n "$table_count" ]]; then
      pass "Database: $db_file healthy ($table_count)"
    else
      pass "Database: $db_file healthy"
    fi
  else
    fail "Database: $db_file found but 'bash db_queries.sh health' failed"
  fi
}

# ── check 4: no leftover placeholders ────────────────────────────────────

check_placeholders() {
  local found_any=0
  local found_files=()

  # Build list of files to check (expand globs manually)
  local candidates=()

  [[ -f "CLAUDE.md" ]] && candidates+=("CLAUDE.md")

  # *_RULES.md
  while IFS= read -r -d '' f; do
    candidates+=("$f")
  done < <(find . -maxdepth 1 -name "*_RULES.md" -print0 2>/dev/null)

  [[ -f ".claude/settings.json" ]] && candidates+=(".claude/settings.json")
  [[ -f ".claude/settings.local.json" ]] && candidates+=(".claude/settings.local.json")
  [[ -f "db_queries.sh" ]] && candidates+=("db_queries.sh")
  [[ -f "session_briefing.sh" ]] && candidates+=("session_briefing.sh")

  for f in "${candidates[@]}"; do
    if grep -n '%%' "$f" &>/dev/null 2>&1; then
      local count
      count=$(grep -c '%%' "$f" 2>/dev/null || echo "?")
      found_files+=("${count} in ${f}")
      (( found_any++ )) || true
    fi
  done

  if [[ $found_any -eq 0 ]]; then
    pass "Placeholders: none found in critical files"
  else
    local summary
    summary=$(IFS=', '; echo "${found_files[*]}")
    warn "Placeholders: ${found_any} file(s) with %% tokens — ${summary}"
  fi
}

# ── check 5: @-import resolution ─────────────────────────────────────────

check_imports() {
  if [[ ! -f "CLAUDE.md" ]]; then
    warn "@-imports: CLAUDE.md not found, skipping"
    return
  fi

  local total=0
  local missing=()

  while IFS= read -r raw_target; do
    local target="$raw_target"

    # Expand ~ to $HOME — must escape ~ in pattern for bash parameter expansion
    if [[ "$target" == "~/"* ]]; then
      target="${HOME}/${target#\~/}"
    fi

    # Resolve relative paths (anything not starting with /)
    if [[ "$target" != /* ]]; then
      target="${PROJECT_DIR}/${target}"
    fi

    (( total++ )) || true

    if [[ ! -f "$target" ]]; then
      missing+=("$raw_target")
    fi
  done < <(grep -E '^@[^[:space:]]' "CLAUDE.md" 2>/dev/null | sed 's/^@//')

  if [[ $total -eq 0 ]]; then
    pass "@-imports: none found in CLAUDE.md"
    return
  fi

  local resolved=$(( total - ${#missing[@]} ))
  if [[ ${#missing[@]} -eq 0 ]]; then
    pass "@-imports: ${resolved}/${total} resolved"
  else
    local missing_list
    missing_list=$(printf '%s ' "${missing[@]}")
    fail "@-imports: ${resolved}/${total} resolved — missing: ${missing_list% }"
  fi
}

# ── check 6: git initialized ──────────────────────────────────────────────

check_git() {
  if [[ ! -d ".git" ]]; then
    fail "Git: .git directory not found — not a git repository"
    return
  fi

  local branch=""
  if command -v git &>/dev/null; then
    branch=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
  fi

  if [[ -n "$branch" ]]; then
    pass "Git: initialized on branch ${branch}"
  else
    pass "Git: initialized (.git exists)"
  fi
}

# ── run all checks ────────────────────────────────────────────────────────

echo "Post-Bootstrap Health Check: ${PROJECT_DIR}"
echo "${separator}"

check_hooks
check_settings
check_database
check_placeholders
check_imports
check_git

# ── print all results ─────────────────────────────────────────────────────

for line in "${RESULTS[@]}"; do
  echo "$line"
done

echo "${separator}"
echo "Health: ${PASS_COUNT} pass, ${FAIL_COUNT} fail, ${WARN_COUNT} warning"

# ── exit code ─────────────────────────────────────────────────────────────

if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
elif [[ $WARN_COUNT -gt 0 ]]; then
  exit 2
else
  exit 0
fi
