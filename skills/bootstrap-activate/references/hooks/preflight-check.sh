#!/usr/bin/env bash
set -euo pipefail

# preflight-check.sh — Prerequisite checker for the bootstrap-activate plugin
#
# QUICK MODE (no args): Called by SessionStart hook. Completes in <3 seconds.
#   Outputs JSON for Claude Code hook system. Always exits 0.
#
# FULL MODE (--full [--project-dir PATH]): Called before bootstrap.
#   Human-readable output. Exits 0/1/2.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# hooks/ -> references/ -> bootstrap-activate/ -> skills/ -> repo root
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')"  # darwin or linux

# Hardcoded install commands used when prerequisites.json or jq is unavailable
_install_hint() {
    local tool="$1"
    case "$tool" in
        jq)
            if [[ "$PLATFORM" == "darwin" ]]; then echo "brew install jq"
            else echo "sudo apt-get install jq"; fi ;;
        python3)
            if [[ "$PLATFORM" == "darwin" ]]; then echo "brew install python@3.12"
            else echo "sudo apt-get install python3.12"; fi ;;
        git)
            if [[ "$PLATFORM" == "darwin" ]]; then echo "xcode-select --install"
            else echo "sudo apt-get install git"; fi ;;
        bash)
            if [[ "$PLATFORM" == "darwin" ]]; then echo "brew install bash"
            else echo "built-in (usually 5.x)"; fi ;;
        sqlite3)
            if [[ "$PLATFORM" == "darwin" ]]; then echo "built-in on macOS"
            else echo "sudo apt-get install sqlite3"; fi ;;
        *)
            echo "see documentation" ;;
    esac
}

# Try to load prerequisites.json for install hints (jq must be available)
# Sets PREREQS_JSON to the file path if readable, or empty string.
PREREQS_JSON=""
_candidate="${REPO_ROOT}/prerequisites.json"
if [[ -f "$_candidate" ]]; then
    PREREQS_JSON="$_candidate"
fi

# Get install hint for a tool from prerequisites.json if possible,
# falling back to hardcoded hints.
_install_hint_from_json() {
    local tool="$1"
    if [[ -n "$PREREQS_JSON" ]] && command -v jq > /dev/null 2>&1; then
        local hint
        local key
        # Map platform to json key
        if [[ "$PLATFORM" == "darwin" ]]; then key="darwin"; else key="linux"; fi
        # Try critical array first, then important
        hint="$(jq -r --arg t "$tool" --arg p "$key" '
            (.prerequisites.critical[]? | select(.name == $t) | .install[$p] // empty),
            (.prerequisites.important[]? | select(.name == $t) | .install[$p] // empty)
            | select(. != null and . != "")
        ' "$PREREQS_JSON" 2>/dev/null | head -1)"
        if [[ -n "$hint" ]]; then
            printf '%s' "$hint"
            return
        fi
    fi
    _install_hint "$tool"
}

# ---------------------------------------------------------------------------
# MODE DETECTION
# ---------------------------------------------------------------------------

FULL_MODE=0
PROJECT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)   FULL_MODE=1; shift ;;
        --project-dir)
            if [[ -z "${2:-}" ]]; then
                printf 'Error: --project-dir requires a path argument\n' >&2
                exit 1
            fi
            PROJECT_DIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# ---------------------------------------------------------------------------
# QUICK MODE
# ---------------------------------------------------------------------------

if [[ "$FULL_MODE" -eq 0 ]]; then
    missing=()
    for tool in jq python3 git bash; do
        if ! command -v "$tool" > /dev/null 2>&1; then
            missing+=("$tool")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Prerequisites OK"}}\n'
    else
        # Build a short install guidance string
        msg="Missing tools:"
        for t in "${missing[@]}"; do
            hint="$(_install_hint_from_json "$t")"
            msg="${msg} ${t} (install: ${hint});"
        done
        printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
            "$(printf '%s' "$msg" | sed 's/"/\\"/g')"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# FULL MODE — tracking variables
# ---------------------------------------------------------------------------

CRITICAL_FAILURES=0
WARN_COUNT=0
INFO_COUNT=0

_pass()  { printf '  [PASS] %s\n' "$*"; }
_fail()  { printf '  [FAIL] %s\n' "$1"; [[ -n "${2:-}" ]] && printf '         Install: %s\n' "$2"; (( CRITICAL_FAILURES++ )) || true; }
_warn()  { printf '  [WARN] %s\n' "$*"; (( WARN_COUNT++ )) || true; }
_info()  { printf '  [INFO] %s\n' "$*"; (( INFO_COUNT++ )) || true; }

# ---------------------------------------------------------------------------
# 1. Critical tools
# ---------------------------------------------------------------------------

printf '\nCritical tools:\n'

# jq
if command -v jq > /dev/null 2>&1; then
    _pass "jq found: $(command -v jq)"
else
    _fail "jq not found" "$(_install_hint_from_json jq)"
fi

# python3 presence
if command -v python3 > /dev/null 2>&1; then
    _pass "python3 found: $(command -v python3)"
    # python3 version >= 3.10
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
        py_ver="$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)"
        _pass "python3 version ${py_ver} >= 3.10"
    else
        py_ver="$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")"
        _fail "python3 version ${py_ver} < 3.10 (need 3.10+ for match statements, PEP 604)" \
              "$(_install_hint_from_json python3)"
    fi
else
    _fail "python3 not found" "$(_install_hint_from_json python3)"
    _fail "python3 version check skipped (python3 not found)"
fi

# git
if command -v git > /dev/null 2>&1; then
    _pass "git found: $(command -v git)"
else
    _fail "git not found" "$(_install_hint_from_json git)"
fi

# bash >= 4.0 (warn, not fail — critical hooks work on bash 3.2, only coherence_check needs 4+)
BASH_MAJOR="${BASH_VERSINFO[0]:-0}"
if [[ "$BASH_MAJOR" -ge 4 ]]; then
    _pass "bash ${BASH_VERSION} >= 4.0"
else
    _warn "bash ${BASH_VERSION} < 4.0 — some optional scripts (coherence_check) need 4.0+"
fi

# ---------------------------------------------------------------------------
# 2. Important tools
# ---------------------------------------------------------------------------

printf '\nImportant tools:\n'

# sqlite3
if command -v sqlite3 > /dev/null 2>&1; then
    _pass "sqlite3 found: $(command -v sqlite3)"
else
    _warn "sqlite3 not found (Python fallback available via python3 -m sqlite3)"
fi

# git user config
git_name="$(git config user.name 2>/dev/null || true)"
git_email="$(git config user.email 2>/dev/null || true)"
if [[ -n "$git_name" && -n "$git_email" ]]; then
    _pass "git user configured: ${git_name} <${git_email}>"
else
    _warn "git user not fully configured — first commit will fail." \
          "Run: git config --global user.name 'Your Name' && git config --global user.email 'you@example.com'"
fi

# ---------------------------------------------------------------------------
# 3. Structural checks
# ---------------------------------------------------------------------------

printf '\nStructural:\n'

# Context detection: plugin mode (strict) vs CLI/dev mode (relaxed).
# When CLAUDE_PLUGIN_ROOT is set, Claude Code loaded this as a plugin —
# templates MUST be bundled. Global fallbacks would mask packaging bugs.
# When unset, this is a dev/CLI run where global paths are legitimate.
STRICT_MODE=0
[[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]] && STRICT_MODE=1

# Template directory: search in priority order
TEMPLATES_DIR=""
TEMPLATE_SEARCH_PATHS=(
    "${REPO_ROOT}/engine/templates"
    "${REPO_ROOT}/templates"
)
if [[ "$STRICT_MODE" -eq 0 ]]; then
    TEMPLATE_SEARCH_PATHS+=(
        "${HOME}/.claude/dev-framework/templates"
        "${HOME}/.claude/templates"
    )
fi
for candidate in "${TEMPLATE_SEARCH_PATHS[@]}"; do
    if [[ -d "$candidate" ]]; then
        TEMPLATES_DIR="$candidate"
        break
    fi
done

KEY_FILES=(
    "scripts/dbq/__main__.py"
    "hooks/session-start-check.template.sh"
    "rules/RULES_TEMPLATE.md"
    "settings/settings.template.json"
)

if [[ -n "$TEMPLATES_DIR" ]]; then
    found_keys=0
    for kf in "${KEY_FILES[@]}"; do
        [[ -f "${TEMPLATES_DIR}/${kf}" ]] && (( found_keys++ )) || true
    done
    total_keys="${#KEY_FILES[@]}"
    # Display tilde-abbreviated path for readability
    display_path="${TEMPLATES_DIR/${HOME}/~}"
    if [[ "$found_keys" -eq "$total_keys" ]]; then
        _pass "Templates: ${display_path} (${found_keys}/${total_keys} key files)"
    else
        _fail "Templates: ${display_path} found but only ${found_keys}/${total_keys} key files present" \
              "Check plugin installation or template paths"
    fi
else
    if [[ "$STRICT_MODE" -eq 1 ]]; then
        _fail "Template directory not found — bundled engine missing from plugin" \
              "Reinstall the plugin (global fallbacks disabled in plugin mode)"
    else
        _fail "Template directory not found (checked: ${TEMPLATE_SEARCH_PATHS[*]})" \
              "Check template paths or install via dev-framework"
    fi
fi

# Frameworks directory: search in priority order (strict/relaxed aware)
FRAMEWORKS_DIR=""
FRAMEWORK_SEARCH_PATHS=(
    "${REPO_ROOT}/engine/templates/frameworks"
    "${REPO_ROOT}/templates/frameworks"
)
if [[ "$STRICT_MODE" -eq 0 ]]; then
    FRAMEWORK_SEARCH_PATHS+=(
        "${HOME}/.claude/frameworks"
    )
fi
for candidate in "${FRAMEWORK_SEARCH_PATHS[@]}"; do
    if [[ -d "$candidate" ]]; then
        FRAMEWORKS_DIR="$candidate"
        break
    fi
done

if [[ -n "$FRAMEWORKS_DIR" ]]; then
    fw_count="$(ls -1 "${FRAMEWORKS_DIR}" | wc -l | tr -d ' ')"
    display_path="${FRAMEWORKS_DIR/${HOME}/~}"
    if [[ "$fw_count" -ge 7 ]]; then
        _pass "Frameworks: ${display_path} (${fw_count} files)"
    else
        _fail "Frameworks: ${display_path} exists but only ${fw_count} files (need >= 7)" \
              "Check framework installation"
    fi
else
    if [[ "$STRICT_MODE" -eq 1 ]]; then
        _fail "Frameworks directory not found — bundled engine missing from plugin" \
              "Reinstall the plugin (global fallbacks disabled in plugin mode)"
    else
        _fail "Frameworks directory not found (checked: ${FRAMEWORK_SEARCH_PATHS[*]})" \
              "Check framework paths or install via dev-framework"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Platform notes
# ---------------------------------------------------------------------------

printf '\nPlatform:\n'

case "$PLATFORM" in
    darwin)
        _info "Platform: darwin (macOS)"
        _info "grep -P not available on macOS — use grep -E instead"
        ;;
    linux)
        _info "Platform: linux"
        _info "sed -i has no '' argument on Linux (use sed -i 's/old/new/' file — no backup suffix)"
        ;;
    *)
        _warn "Unrecognized platform: ${PLATFORM} (supported: darwin, linux)"
        ;;
esac

# ---------------------------------------------------------------------------
# 5. Optional project-dir check
# ---------------------------------------------------------------------------

if [[ -n "$PROJECT_DIR" ]]; then
    printf '\nProject directory:\n'
    if [[ -w "$PROJECT_DIR" ]]; then
        _pass "Project dir writable: ${PROJECT_DIR}"
    else
        _fail "Project dir not writable: ${PROJECT_DIR}" \
              "Check permissions: ls -la $(dirname "$PROJECT_DIR")"
    fi
fi

# ---------------------------------------------------------------------------
# 6. Discovery handoff contract (only when --project-dir given)
# ---------------------------------------------------------------------------

if [[ -n "$PROJECT_DIR" ]]; then
    printf '\nDiscovery handoff:\n'

    # Spec files — all four must exist and must not contain unresolved TODO markers
    REQUIRED_SPECS=(
        "specs/VISION.md"
        "specs/BLUEPRINT.md"
        "specs/RESEARCH.md"
        "specs/INFRASTRUCTURE.md"
    )

    for spec in "${REQUIRED_SPECS[@]}"; do
        spec_path="${PROJECT_DIR}/${spec}"
        if [[ -f "$spec_path" ]]; then
            if grep -q "TODO" "$spec_path" 2>/dev/null; then
                _warn "${spec} exists but contains unresolved TODO markers — review before activating"
            else
                _pass "${spec} exists (no TODO markers)"
            fi
        else
            _fail "${spec} not found — run bootstrap-discovery first" \
                  "Create specs/ via the /bootstrap-discovery skill"
        fi
    done

    # .bootstrap_mode — must exist and contain SPECIFICATION
    bootstrap_mode_file="${PROJECT_DIR}/.bootstrap_mode"
    if [[ -f "$bootstrap_mode_file" ]]; then
        bootstrap_mode_val="$(tr -d '[:space:]' < "$bootstrap_mode_file")"
        if [[ "$bootstrap_mode_val" == "SPECIFICATION" ]]; then
            _pass ".bootstrap_mode = SPECIFICATION"
        else
            _fail ".bootstrap_mode exists but value is '${bootstrap_mode_val}' (expected: SPECIFICATION)" \
                  "Discovery phase must complete with SPECIFICATION mode set"
        fi
    else
        _fail ".bootstrap_mode not found — discovery phase did not complete" \
              "Run bootstrap-discovery skill and complete the spec phase"
    fi

    # NEXT_SESSION.md — advisory: check existence and Cowork handoff marker
    next_session_file="${PROJECT_DIR}/NEXT_SESSION.md"
    if [[ -f "$next_session_file" ]]; then
        if grep -q "Handoff Source: COWORK" "$next_session_file" 2>/dev/null; then
            _info "NEXT_SESSION.md found with Handoff Source: COWORK marker"
        else
            _info "NEXT_SESSION.md found (no Cowork handoff marker — proceeding without discovery context)"
        fi
    else
        _info "NEXT_SESSION.md not found — no discovery session context available"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\n'

summary_parts=()
[[ "$CRITICAL_FAILURES" -gt 0 ]] && summary_parts+=("${CRITICAL_FAILURES} critical failure(s)")
[[ "$WARN_COUNT" -gt 0 ]]        && summary_parts+=("${WARN_COUNT} warning(s)")
[[ "$INFO_COUNT" -gt 0 ]]        && summary_parts+=("${INFO_COUNT} info")

if [[ ${#summary_parts[@]} -eq 0 ]]; then
    printf 'Preflight: all checks passed\n'
else
    # Join summary_parts with ", "
    summary_str="${summary_parts[0]}"
    for (( i=1; i<${#summary_parts[@]}; i++ )); do
        summary_str="${summary_str}, ${summary_parts[$i]}"
    done
    if [[ "$CRITICAL_FAILURES" -eq 0 && "$WARN_COUNT" -eq 0 ]]; then
        printf 'Preflight: all critical checks passed (%s)\n' "$summary_str"
    else
        printf 'Preflight: %s\n' "$summary_str"
    fi
fi

# ---------------------------------------------------------------------------
# Exit codes: 0 = all critical pass, 1 = critical failures, 2 = warnings only
# ---------------------------------------------------------------------------

if [[ "$CRITICAL_FAILURES" -gt 0 ]]; then
    exit 1
elif [[ "$WARN_COUNT" -gt 0 ]]; then
    exit 2
else
    exit 0
fi
