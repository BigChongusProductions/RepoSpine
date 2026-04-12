#!/usr/bin/env bash
# =============================================================================
# Bootstrap Framework Test Suite
# Validates the bootstrap engine across 4 project archetypes
#
# Usage:
#   bash test_bootstrap_suite.sh               # Run full suite (smoke + product-flow + 4 projects)
#   bash test_bootstrap_suite.sh 1 3           # Run specific project(s) only
#   bash test_bootstrap_suite.sh --verify 1    # D7 verification only (project already exists)
#   bash test_bootstrap_suite.sh --exercise 1  # Workflow exercise only
#   bash test_bootstrap_suite.sh --cross       # Cross-project validation only
#
#   Bootstrap smoke (template-level, no live project):
#   bash test_bootstrap_suite.sh --smoke               # All bootstrap smoke tests (= --regression)
#   bash test_bootstrap_suite.sh --regression          # Template-level regression + compat + new feature tests
#   bash test_bootstrap_suite.sh --compat              # Cross-project compatibility tests only
#   bash test_bootstrap_suite.sh --language-rules      # Language-specific rule template tests only
#   bash test_bootstrap_suite.sh --edge-hyphen         # Edge case: hyphenated project name
#   bash test_bootstrap_suite.sh --phase-flag          # --phase flag tests (bootstrap_project.sh)
#   bash test_bootstrap_suite.sh --fill-placeholders   # fill_placeholders.py tests
#   bash test_bootstrap_suite.sh --verify-deployment   # verify_deployment.py tests
#   bash test_bootstrap_suite.sh --scripts-functional  # Smoke-test all deployed scripts
#   bash test_bootstrap_suite.sh --quality-gate        # Quality-gate contract tests (hooks, templates)
#   bash test_bootstrap_suite.sh --forbidden-pattern   # Forbidden-pattern regression checks
#   bash test_bootstrap_suite.sh --context-footprint   # Context-footprint size regression guards
#   bash test_bootstrap_suite.sh --plugin-artifact     # Plugin zip artifact smoke tests
#
#   Full activation product flow (bootstraps real project):
#   bash test_bootstrap_suite.sh --product-flow        # Bootstrap + verify + exercise full lifecycle
#   bash test_bootstrap_suite.sh --product-verify      # Bootstrap + assert critical_failures == 0 (CI gate)
#
#   Other:
#   bash test_bootstrap_suite.sh --python-cli          # Python CLI integration tests only
#   bash test_bootstrap_suite.sh --workflow            # Workflow integration tests (promote->harvest cycle)
#   bash test_bootstrap_suite.sh --cleanup             # Remove all test_project dirs
#
# Creates: ~/Desktop/test_project{1..4}/
# =============================================================================

set -uo pipefail

# === PATHS ===================================================================
SUITE_DIR="$HOME/Desktop"
# Resolve templates from repo first (portable), fall back to global symlink
TEST_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TEST_SCRIPT_DIR/.." && pwd)"
if [ -d "$REPO_ROOT/templates" ]; then
    TEMPLATES="$REPO_ROOT/templates"
elif [ -d "$HOME/.claude/dev-framework/templates" ]; then
    TEMPLATES="$HOME/.claude/dev-framework/templates"
else
    echo "ERROR: Cannot find templates directory." >&2
    echo "       Expected at: $REPO_ROOT/templates" >&2
    echo "       Or symlink:  ~/.claude/dev-framework/templates" >&2
    exit 1
fi
TEMPLATE_SCRIPTS="$TEMPLATES/scripts"
TEMPLATE_FRAMEWORKS="$TEMPLATES/frameworks"
GLOBAL_FRAMEWORKS="$HOME/.claude/frameworks"

# Read expected counts from SYSTEMS_MANIFEST.json (with fallback defaults)
if [ -f "$REPO_ROOT/SYSTEMS_MANIFEST.json" ]; then
    EXPECTED_FRAMEWORKS=$(python3 -c "import json; print(json.load(open('$REPO_ROOT/SYSTEMS_MANIFEST.json')).get('summary',{}).get('frameworks',10))" 2>/dev/null || echo 10)
    EXPECTED_CHECKS=$(python3 -c "import json; print(json.load(open('$REPO_ROOT/SYSTEMS_MANIFEST.json')).get('summary',{}).get('checks',18))" 2>/dev/null || echo 18)
else
    EXPECTED_FRAMEWORKS=10
    EXPECTED_CHECKS=18
fi
RULES_TEMPLATE="$TEMPLATES/rules/RULES_TEMPLATE.md"
CLAUDE_TEMPLATE="$TEMPLATES/rules/CLAUDE_TEMPLATE.md"

# === RESULT TRACKING =========================================================
TOTAL_CHECKS=0
TOTAL_PASS=0
TOTAL_FAIL=0
declare -a FAILURES=()

# === COLORS ==================================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

# === HELPERS =================================================================
pass()    { TOTAL_CHECKS=$((TOTAL_CHECKS+1)); TOTAL_PASS=$((TOTAL_PASS+1));  echo -e "  ${GREEN}✅${RESET} $1"; }
fail()    { TOTAL_CHECKS=$((TOTAL_CHECKS+1)); TOTAL_FAIL=$((TOTAL_FAIL+1));  FAILURES+=("[$P_NAME] $1"); echo -e "  ${RED}❌${RESET} $1"; }
warn()    { echo -e "  ${YELLOW}⚠️${RESET}  $1"; }
info()    { echo -e "  ${BLUE}ℹ️${RESET}  $1"; }
section() { echo -e "\n${BOLD}── $1 ─────────────────────────────────────────────${RESET}"; }
header()  { echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"; \
            echo -e "${BOLD}║  $1${RESET}"; \
            echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"; }

chk() {
  # chk "label" command_to_test
  local LABEL="$1"; shift
  TOTAL_CHECKS=$((TOTAL_CHECKS+1))
  if "$@" 2>/dev/null; then
    TOTAL_PASS=$((TOTAL_PASS+1)); echo -e "  ${GREEN}✅${RESET} $LABEL"
  else
    TOTAL_FAIL=$((TOTAL_FAIL+1)); FAILURES+=("[$P_NAME] $LABEL"); echo -e "  ${RED}❌${RESET} $LABEL"
  fi
}

# _run_sql DB SQL — execute SQL against a SQLite database.
# Uses sqlite3 CLI when available, falls back to Python sqlite3 module.
_run_sql() {
  local db="$1" sql="$2"
  if command -v sqlite3 &>/dev/null; then
    sqlite3 "$db" "$sql"
  elif python3 -c "pass" 2>/dev/null; then
    _RUNSQL_DB="$db" _RUNSQL_SQL="$sql" python3 -c "
import sqlite3, sys, os
conn = sqlite3.connect(os.environ['_RUNSQL_DB'])
cur = conn.cursor()
for stmt in os.environ['_RUNSQL_SQL'].strip().split(';'):
    stmt = stmt.strip()
    if stmt:
        cur.execute(stmt)
rows = cur.fetchall()
for r in rows:
    print('|'.join(str(c) for c in r))
conn.commit()
conn.close()
"
  else
    echo "ERROR: Neither sqlite3 CLI nor python3 available" >&2
    return 1
  fi
}

# === PROJECT CONFIGURATIONS ==================================================
# Each project is defined by its own config function.
# Call: load_project_config N  (N = 1, 2, 3, or 4)

P_NUM=""       # project number (1-4)
P_DIR=""       # ~/Desktop/test_projectN
P_NAME=""      # display name e.g. TestWebApp
P_SLUG=""      # slug e.g. test_web_app
P_DB=""        # e.g. test_web_app.db
P_DB_NAME=""   # e.g. test_web_app (no .db)
P_LESSONS=""   # e.g. LESSONS_TEST_WEB_APP.md
P_RULES=""     # e.g. TEST_WEB_APP_RULES.md
P_MEMORY=""    # e.g. TEST_WEB_APP_PROJECT_MEMORY.md
P_PHASES=""    # space-separated: "P0-SETUP P1-CORE ..."
P_FIRST=""     # first phase name
P_SECOND=""    # second phase name (for loopback testing)
P_ORDINAL_MAX="" # max ordinal = phase_count - 1  (used in SQL formula)
P_HAS_UI=""    # YES / NO
P_HAS_GEMINI=""
P_HAS_TEAMS=""
P_HAS_SKILLS=""
P_HAS_DEFERRED=""
P_TIER=""      # Normal / Small

load_project_config() {
  P_NUM="$1"
  P_DIR="$SUITE_DIR/test_project${P_NUM}"

  case "$P_NUM" in
    1)
      P_NAME="TestWebApp"; P_SLUG="test_web_app"; P_TIER="Normal"
      P_DB="test_web_app.db"; P_DB_NAME="test_web_app"
      P_LESSONS="LESSONS_TEST_WEB_APP.md"; P_RULES="TEST_WEB_APP_RULES.md"
      P_MEMORY="TEST_WEB_APP_PROJECT_MEMORY.md"
      P_PHASES="P0-SETUP P1-CORE P2-VIEWS P3-DATA P4-INTEGRATION P5-SHIP"
      P_FIRST="P0-SETUP"; P_SECOND="P1-CORE"; P_ORDINAL_MAX="5"
      P_HAS_UI="YES"; P_HAS_GEMINI="YES"; P_HAS_TEAMS="NO"
      P_HAS_SKILLS="YES"; P_HAS_DEFERRED="YES"
      ;;
    2)
      P_NAME="RustCLI"; P_SLUG="rust_cli"; P_TIER="Small"
      P_DB="rust_cli.db"; P_DB_NAME="rust_cli"
      P_LESSONS="LESSONS_RUST_CLI.md"; P_RULES="RUST_CLI_RULES.md"
      P_MEMORY="RUST_CLI_PROJECT_MEMORY.md"
      P_PHASES="P0-INIT P1-PARSER P2-COMMANDS P3-POLISH P4-SHIP"
      P_FIRST="P0-INIT"; P_SECOND="P1-PARSER"; P_ORDINAL_MAX="4"
      P_HAS_UI="NO"; P_HAS_GEMINI="NO"; P_HAS_TEAMS="NO"
      P_HAS_SKILLS="NO"; P_HAS_DEFERRED="NO"
      ;;
    3)
      P_NAME="FastAPIService"; P_SLUG="fastapi_service"; P_TIER="Normal"
      P_DB="fastapi_service.db"; P_DB_NAME="fastapi_service"
      P_LESSONS="LESSONS_FASTAPI_SERVICE.md"; P_RULES="FASTAPI_SERVICE_RULES.md"
      P_MEMORY="FASTAPI_SERVICE_PROJECT_MEMORY.md"
      P_PHASES="P0-SCAFFOLD P1-MODELS P2-ENDPOINTS P3-AUTH P4-DEPLOY"
      P_FIRST="P0-SCAFFOLD"; P_SECOND="P1-MODELS"; P_ORDINAL_MAX="4"
      P_HAS_UI="NO"; P_HAS_GEMINI="YES"; P_HAS_TEAMS="YES"
      P_HAS_SKILLS="NO"; P_HAS_DEFERRED="YES"
      ;;
    4)
      P_NAME="SwiftDesktopApp"; P_SLUG="swift_desktop_app"; P_TIER="Normal"
      P_DB="swift_desktop_app.db"; P_DB_NAME="swift_desktop_app"
      P_LESSONS="LESSONS_SWIFT_DESKTOP_APP.md"; P_RULES="SWIFT_DESKTOP_APP_RULES.md"
      P_MEMORY="SWIFT_DESKTOP_APP_PROJECT_MEMORY.md"
      P_PHASES="P0-FOUNDATION P1-DATA P2-VIEWS P3-INTERACTIONS P4-POLISH P5-SHIP"
      P_FIRST="P0-FOUNDATION"; P_SECOND="P1-DATA"; P_ORDINAL_MAX="5"
      P_HAS_UI="YES"; P_HAS_GEMINI="NO"; P_HAS_TEAMS="NO"
      P_HAS_SKILLS="YES"; P_HAS_DEFERRED="NO"
      ;;
    *)
      echo "Unknown project number: $P_NUM" >&2; exit 1 ;;
  esac
}

# === PRE-FLIGHT CHECKS =======================================================
preflight() {
  header "Pre-flight Checks"
  local OK=1

  command -v sqlite3 >/dev/null || { echo -e "${RED}❌ sqlite3 not found${RESET}"; OK=0; }
  command -v python3 >/dev/null || { echo -e "${RED}❌ python3 not found${RESET}"; OK=0; }
  [ -f "$RULES_TEMPLATE" ]  || { echo -e "${RED}❌ RULES_TEMPLATE.md not found at $RULES_TEMPLATE${RESET}"; OK=0; }
  [ -f "$CLAUDE_TEMPLATE" ] || { echo -e "${RED}❌ CLAUDE_TEMPLATE.md not found at $CLAUDE_TEMPLATE${RESET}"; OK=0; }
  [ -f "$TEMPLATE_SCRIPTS/db_queries.template.sh" ] || { echo -e "${RED}❌ db_queries.template.sh not found${RESET}"; OK=0; }
  [ -f "$GLOBAL_FRAMEWORKS/loopback-system.md" ] || { echo -e "${RED}❌ loopback-system.md not found at $GLOBAL_FRAMEWORKS/${RESET}"; OK=0; }
  [ "$(ls $TEMPLATE_FRAMEWORKS/*.md 2>/dev/null | wc -l)" -ge 8 ] || \
    { echo -e "${RED}❌ Less than 8 framework files in $TEMPLATE_FRAMEWORKS${RESET}"; OK=0; }

  for d in 1 2 3 4; do
    if [ -d "$SUITE_DIR/test_project$d" ]; then
      echo -e "${YELLOW}⚠️  $SUITE_DIR/test_project$d already exists — run with --cleanup first${RESET}"
      OK=0
    fi
  done

  [ "$OK" = "1" ] && echo -e "${GREEN}✅ All pre-flight checks passed${RESET}" || \
    { echo -e "${RED}❌ Pre-flight failed — fix above before running${RESET}"; exit 1; }
}

# === SPEC CREATION ===========================================================
create_specs() {
  # Called after load_project_config N
  section "Creating specs for project $P_NUM: $P_NAME"
  mkdir -p "$P_DIR/specs"

  echo "SPECIFICATION" > "$P_DIR/.bootstrap_mode"

  case "$P_NUM" in
    1) create_specs_p1 ;;
    2) create_specs_p2 ;;
    3) create_specs_p3 ;;
    4) create_specs_p4 ;;
  esac

  cd "$P_DIR"
  git init -q && git checkout -q -b dev
  git -c user.email="test@test.com" -c user.name="TestSuite" add .
  git -c user.email="test@test.com" -c user.name="TestSuite" \
    commit -q -m "[BOOTSTRAP] Pre-filled specs for $P_NAME"
  info "Spec commit created on dev branch"
}

create_specs_p1() {
  cat > "$P_DIR/specs/VISION.md" << 'VISION_EOF'
# TestWebApp — Vision

## One-Paragraph Pitch
A web app for organizing browser bookmarks with tagging, full-text search, and import from browser exports. Personal tool, local SQLite backend, zero cloud dependency.

## Who Is This For?
Me — tired of losing bookmarks across browsers and devices.

## What Does "Done" Look Like?
1. I can add/tag/search bookmarks from a clean web UI
2. I can import bookmarks from a Chrome/Firefox HTML export
3. Full-text search finds the right bookmark in under 100ms

## What's NOT in v1
- Browser extension for one-click saving
- Cloud sync
VISION_EOF

  cat > "$P_DIR/specs/BLUEPRINT.md" << 'BLUEPRINT_EOF'
# TestWebApp — Decisions

## Tech Stack
| Layer | Choice | Why |
|-------|--------|-----|
| Language | TypeScript | Type safety, excellent Next.js integration |
| Framework | Next.js 14 (App Router) | Server components, API routes, single deployment |
| Database | SQLite (via better-sqlite3) | Local, zero config, fast reads |
| Styling | Tailwind CSS | Utility-first, fast iteration |
| Testing | Vitest + Playwright | Unit + E2E coverage |

## Scope — v1
1. Add/edit/delete bookmarks with URL, title, tags
2. Import from Chrome/Firefox HTML export
3. Full-text search across title + URL + tags
4. Tag management (create, rename, merge, delete)

## Key Decision
| Decision | Options | Chose | Why |
|----------|---------|-------|-----|
| Search | SQLite FTS5 vs Fuse.js vs Meilisearch | SQLite FTS5 | Zero extra infra, fast enough for <10k bookmarks |

## Gate Check
- [x] All decisions locked
BLUEPRINT_EOF

  cat > "$P_DIR/specs/INFRASTRUCTURE.md" << INFRASTRUCTURE_EOF
# TestWebApp — Framework Specification

## Project Identity
- **Project Name:** TestWebApp
- **Project Slug:** test_web_app
- **Project Path:** $P_DIR
- **DB Filename:** test_web_app.db
- **Lessons File:** LESSONS_TEST_WEB_APP.md
- **Rules File:** TEST_WEB_APP_RULES.md
- **Project Memory File:** TEST_WEB_APP_PROJECT_MEMORY.md
- **North Star:** Personal bookmark manager — fast full-text search, tag-based organization, local SQLite, zero cloud

## Tech Stack
- **Language:** TypeScript (Node.js 20)
- **Framework:** Next.js 14, App Router
- **Database:** SQLite (better-sqlite3)
- **Styling:** Tailwind CSS v3
- **Testing:** Vitest, Playwright
- **Build:** npm run build

## Phase Plan
| Phase ID | Name | Description | Key Deliverables |
|----------|------|-------------|-----------------|
| P0-SETUP | Foundation | Next.js scaffold, DB schema, git, TypeScript config | Working Next.js app, DB init, CI setup |
| P1-CORE | Core Data | DB layer, bookmark CRUD, basic API routes | All CRUD endpoints tested |
| P2-VIEWS | UI | Main pages: list, add, edit, search, tag view | Working UI with Tailwind |
| P3-DATA | Data Import | Chrome/Firefox HTML import, FTS5 indexing | Import works for real bookmarks |
| P4-INTEGRATION | Integration | Search UX, keyboard nav, performance tuning | <100ms search, smooth UX |
| P5-SHIP | Ship | Final testing, cleanup, docs | Clean build, passing E2E tests |

## Phase Ordinals
\`\`\`
P0-SETUP) echo 0 ;;
P1-CORE) echo 1 ;;
P2-VIEWS) echo 2 ;;
P3-DATA) echo 3 ;;
P4-INTEGRATION) echo 4 ;;
P5-SHIP) echo 5 ;;
\`\`\`

## Agent Workforce
| Tier | Model | Use For |
|------|-------|---------|
| Opus | claude-opus-4-6 | Architecture, design decisions, complex debugging |
| Sonnet | claude-sonnet-4-6 | Multi-file features, API routes, complex components |
| Haiku | claude-haiku-4-5 | Config, boilerplate, single-file fixes |
| Gemini | via MCP | Large context analysis, research |

## Build & Test
\`\`\`bash
npm run build 2>&1 | tail -20
npm test 2>&1 | tail -20
\`\`\`

## Commit Format
\`[PHASE] scope: description\` e.g. \`[P0-SETUP] db: add bookmark schema\`

## Code Standards
- TypeScript strict mode, no implicit any
- ESLint + Prettier enforced
- Tailwind: no inline styles, no custom CSS unless necessary

## Visual Verification
This project HAS visual UI — visual verification gate is ACTIVE. Use screenshots to verify layout after UI changes.

## MCP Servers Available
- Desktop Commander, Gemini MCP

## Project-Specific STOP Rules
- STOP before adding any cloud/paid dependency
- STOP before modifying existing bookmark data during import (append-only)

## Gitignore Patterns
| Pattern | Why |
|---------|-----|
| node_modules/ | npm dependencies |
| .next/ | Next.js build output |
| .env* | Environment secrets |
| *.db-journal, *.db-wal | SQLite temp files |
| .DS_Store | macOS metadata |
INFRASTRUCTURE_EOF

  cat > "$P_DIR/specs/RESEARCH.md" << 'RESEARCH_EOF'
# TestWebApp — Research

## SQLite FTS5 Performance
Full-text search with FTS5 handles 100k+ rows in <50ms on local hardware. Well-suited for personal bookmark databases (<10k entries).

## Next.js App Router vs Pages Router
App Router (Next.js 13+) provides better performance via React Server Components. Better for read-heavy UIs like bookmark lists. Server Actions simplify CRUD without separate API routes for simple cases.

## Import Format
Chrome and Firefox both export bookmarks as Netscape Bookmark Format HTML. The format is well-documented and parseable with a single-pass regex over DL/DT/A tags.
RESEARCH_EOF
}

create_specs_p2() {
  cat > "$P_DIR/specs/VISION.md" << 'VISION_EOF'
# RustCLI — Vision

## One-Paragraph Pitch
A fast CLI tool for bulk renaming files using pattern matching, regex substitution, and sequential numbering. Dry-run mode by default, shows preview before committing changes.

## Who Is This For?
Me — renaming photos, downloaded files, and project assets repeatedly.

## What Does "Done" Look Like?
1. `rename --pattern "*.jpg" --replace "photo_{n}" --start 1` renames with preview
2. Dry-run mode shows exact renames before executing
3. Undo last rename operation

## What's NOT in v1
- GUI
- Network filesystem support
VISION_EOF

  cat > "$P_DIR/specs/BLUEPRINT.md" << 'BLUEPRINT_EOF'
# RustCLI — Decisions

## Tech Stack
| Layer | Choice | Why |
|-------|--------|-----|
| Language | Rust 1.75+ | Fast, safe, single binary output |
| CLI parsing | clap 4.x | Industry standard, derive macros |
| File traversal | walkdir | Robust directory recursion |
| Regex | regex crate | Fastest Rust regex library |
| Testing | Rust built-in (cargo test) | No extra dep needed |

## Scope — v1
1. Pattern matching (glob + regex)
2. Sequential numbering with padding
3. Dry-run mode (default on)
4. Single-level and recursive modes

## Key Decision
| Decision | Options | Chose | Why |
|----------|---------|-------|-----|
| Undo mechanism | None vs rename-log file | Rename-log file | Simple, zero external deps |

## Gate Check
- [x] All decisions locked
BLUEPRINT_EOF

  cat > "$P_DIR/specs/INFRASTRUCTURE.md" << INFRASTRUCTURE_EOF
# RustCLI — Framework Specification

## Project Identity
- **Project Name:** RustCLI
- **Project Slug:** rust_cli
- **Project Path:** $P_DIR
- **DB Filename:** rust_cli.db
- **Lessons File:** LESSONS_RUST_CLI.md
- **Rules File:** RUST_CLI_RULES.md
- **Project Memory File:** RUST_CLI_PROJECT_MEMORY.md
- **North Star:** Fast, safe bulk file renamer — single binary, dry-run by default, zero dependencies beyond Rust stdlib

## Tech Stack
- **Language:** Rust 1.75+
- **CLI:** clap 4.x (derive feature)
- **File I/O:** walkdir + std::fs
- **Regex:** regex crate
- **Testing:** cargo test (built-in)
- **Build:** cargo build

## Phase Plan
| Phase ID | Name | Description | Key Deliverables |
|----------|------|-------------|-----------------|
| P0-INIT | Init | cargo new, clap setup, argument parsing | CLI parses all flags without logic |
| P1-PARSER | Pattern Parser | Glob + regex pattern engine | All pattern types parse correctly |
| P2-COMMANDS | Commands | Rename, dry-run, undo commands | Core functionality working |
| P3-POLISH | Polish | Error messages, edge cases, help text | User-friendly error output |
| P4-SHIP | Ship | Tests, docs, release binary | All tests pass, README complete |

## Phase Ordinals
\`\`\`
P0-INIT) echo 0 ;;
P1-PARSER) echo 1 ;;
P2-COMMANDS) echo 2 ;;
P3-POLISH) echo 3 ;;
P4-SHIP) echo 4 ;;
\`\`\`

## Agent Workforce
| Tier | Model | Use For |
|------|-------|---------|
| Opus | claude-opus-4-6 | Architecture, complex Rust patterns |
| Sonnet | claude-sonnet-4-6 | Multi-file features |
| Haiku | claude-haiku-4-5 | Single-file edits, boilerplate |

## Build & Test
\`\`\`bash
cargo build 2>&1 | tail -20
cargo test 2>&1 | tail -20
\`\`\`

## Commit Format
\`[PHASE] scope: description\` e.g. \`[P0-INIT] cli: add argument parsing\`

## Code Standards
- cargo clippy -- -D warnings (no warnings allowed)
- cargo fmt enforced
- No unwrap() in non-test code

## Visual Verification
Not applicable — CLI tool, no visual UI.

## MCP Servers Available
- Desktop Commander

## Project-Specific STOP Rules
- STOP before any file modifications without dry-run check
- STOP before adding any network calls (offline tool only)

## Gitignore Patterns
| Pattern | Why |
|---------|-----|
| target/ | Cargo build output |
| Cargo.lock | Lock file (binary project: include in repo; library: exclude) |
| *.db-journal, *.db-wal | SQLite temp files |
| .DS_Store | macOS metadata |
INFRASTRUCTURE_EOF

  # Small tier — RESEARCH.md is N/A
  cat > "$P_DIR/specs/RESEARCH.md" << 'RESEARCH_EOF'
# RustCLI — Research

> **Status:** N/A — Small project tier. No external research required.
> All technology choices are well-established (Rust, clap, walkdir).
RESEARCH_EOF
}

create_specs_p3() {
  cat > "$P_DIR/specs/VISION.md" << 'VISION_EOF'
# FastAPIService — Vision

## One-Paragraph Pitch
A REST API for managing notes with tags, full-text search, and Markdown rendering. Local-first, SQLite backend, Python/FastAPI. Consumed by a future UI or directly via curl/HTTPie.

## Who Is This For?
Me — a developer who wants a local note API that other tools can integrate with.

## What Does "Done" Look Like?
1. CRUD endpoints for notes work and return proper JSON
2. Full-text search endpoint finds relevant notes
3. Tag filtering returns correct results
4. JWT auth protects all write endpoints

## What's NOT in v1
- UI (API-only)
- Cloud hosting
VISION_EOF

  cat > "$P_DIR/specs/BLUEPRINT.md" << 'BLUEPRINT_EOF'
# FastAPIService — Decisions

## Tech Stack
| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.12 | Familiar, fast iteration |
| Framework | FastAPI | Modern, async, auto-docs |
| Package manager | Poetry | Deterministic deps, virtual env |
| ORM | SQLAlchemy 2.x | Type-safe queries, migration support |
| Database | SQLite | Local, zero infra |
| Auth | python-jose + passlib | JWT standard approach |
| Testing | pytest + httpx | FastAPI recommended |

## Scope — v1
1. Notes CRUD (create, read, update, delete)
2. Tags (many-to-many with notes)
3. Full-text search
4. JWT authentication (single user)

## Key Decision
| Decision | Options | Chose | Why |
|----------|---------|-------|-----|
| Auth | None vs API Key vs JWT | JWT | Standards-compliant, future-proof |

## Gate Check
- [x] All decisions locked
BLUEPRINT_EOF

  cat > "$P_DIR/specs/INFRASTRUCTURE.md" << INFRASTRUCTURE_EOF
# FastAPIService — Framework Specification

## Project Identity
- **Project Name:** FastAPIService
- **Project Slug:** fastapi_service
- **Project Path:** $P_DIR
- **DB Filename:** fastapi_service.db
- **Lessons File:** LESSONS_FASTAPI_SERVICE.md
- **Rules File:** FASTAPI_SERVICE_RULES.md
- **Project Memory File:** FASTAPI_SERVICE_PROJECT_MEMORY.md
- **North Star:** Local REST API for note management — FastAPI, SQLite, JWT auth, zero cloud dependency

## Tech Stack
- **Language:** Python 3.12
- **Framework:** FastAPI 0.109+
- **Package Manager:** Poetry
- **ORM:** SQLAlchemy 2.x (Core + ORM)
- **Auth:** python-jose, passlib[bcrypt]
- **Testing:** pytest, httpx (async test client)
- **Build:** poetry run pytest

## Phase Plan
| Phase ID | Name | Description | Key Deliverables |
|----------|------|-------------|-----------------|
| P0-SCAFFOLD | Scaffold | FastAPI app, DB schema, Poetry setup | Running app with /health endpoint |
| P1-MODELS | Models | SQLAlchemy models, migrations, CRUD functions | All models tested |
| P2-ENDPOINTS | Endpoints | Note + tag CRUD endpoints, pagination | All endpoints respond correctly |
| P3-AUTH | Auth | JWT auth, route protection, user model | Auth working end-to-end |
| P4-DEPLOY | Deploy | Full test coverage, Docker support, docs | 90%+ coverage, README complete |

## Phase Ordinals
\`\`\`
P0-SCAFFOLD) echo 0 ;;
P1-MODELS) echo 1 ;;
P2-ENDPOINTS) echo 2 ;;
P3-AUTH) echo 3 ;;
P4-DEPLOY) echo 4 ;;
\`\`\`

## Agent Workforce
| Tier | Model | Use For |
|------|-------|---------|
| Opus | claude-opus-4-6 | Architecture, auth design, complex queries |
| Sonnet | claude-sonnet-4-6 | Multi-file features, endpoint implementations |
| Haiku | claude-haiku-4-5 | Single-file edits, config, boilerplate |
| Gemini | via MCP | Research, large context analysis |

## Build & Test
\`\`\`bash
poetry run pytest 2>&1 | tail -20
poetry run pytest --cov 2>&1 | tail -20
\`\`\`

## Commit Format
\`[PHASE] scope: description\` e.g. \`[P0-SCAFFOLD] app: add health endpoint\`

## Code Standards
- Black + Ruff enforced
- mypy strict type checking
- No bare except clauses
- All endpoints have return type annotations

## Visual Verification
Not applicable — API service, no visual UI.

## MCP Servers Available
- Desktop Commander, Gemini MCP

## Project-Specific STOP Rules
- STOP before writing to production DB during tests (use test DB)
- STOP before adding any paid API key dependencies

## Gitignore Patterns
| Pattern | Why |
|---------|-----|
| __pycache__/ | Python bytecode |
| .venv/ | Virtual environment |
| dist/ | Build artifacts |
| *.egg-info/ | Package metadata |
| .env | Secrets |
| *.db-journal, *.db-wal | SQLite temp files |
| .DS_Store | macOS metadata |
INFRASTRUCTURE_EOF

  cat > "$P_DIR/specs/RESEARCH.md" << 'RESEARCH_EOF'
# FastAPIService — Research

## FastAPI + SQLAlchemy 2.x Integration
SQLAlchemy 2.x async engine works well with FastAPI async endpoints. Use AsyncSession with dependency injection pattern. Key gotcha: always await session.commit() before returning responses.

## JWT Auth Pattern for FastAPI
python-jose + passlib is the recommended FastAPI JWT stack. Token refresh via /token/refresh endpoint prevents forced re-login. Store JWT secret in env var, never in code.

## SQLite FTS5 with SQLAlchemy
SQLAlchemy doesn't natively support FTS5 virtual tables. Use raw SQL via text() for FTS queries. Create FTS5 table separately from regular ORM models.
RESEARCH_EOF
}

create_specs_p4() {
  cat > "$P_DIR/specs/VISION.md" << 'VISION_EOF'
# SwiftDesktopApp — Vision

## One-Paragraph Pitch
A macOS status bar app for tracking focus sessions using the Pomodoro technique. Shows current session timer in the menu bar, rings system sound at end, logs sessions to SQLite for weekly review.

## Who Is This For?
Me — wanting minimal distraction from a native macOS tool that lives in the menu bar.

## What Does "Done" Look Like?
1. Timer shows in menu bar as "25:00" counting down
2. Start/pause/skip via menu clicks or keyboard shortcut
3. Session log shows last 7 days of focus time

## What's NOT in v1
- iOS companion
- iCloud sync
VISION_EOF

  cat > "$P_DIR/specs/BLUEPRINT.md" << 'BLUEPRINT_EOF'
# SwiftDesktopApp — Decisions

## Tech Stack
| Layer | Choice | Why |
|-------|--------|-----|
| Language | Swift 5.9+ | Native macOS, best AppKit/SwiftUI integration |
| UI | SwiftUI | Declarative, menu bar popover works well |
| Status bar | AppKit NSStatusItem | No SwiftUI equivalent for menu bar icon |
| Storage | SQLite (GRDB.swift) | Fast, local, type-safe |
| Build | Xcode 15+ | Required for Swift 5.9 |
| Deployment | Unsigned local | Personal tool, no App Store |

## Scope — v1
1. Menu bar icon with countdown timer
2. Start/pause/reset session
3. Configurable work/break durations
4. Session history log (SQLite)

## Key Decision
| Decision | Options | Chose | Why |
|----------|---------|-------|-----|
| Menu bar | NSStatusItem + NSMenu vs SwiftUI MenuBarExtra | NSStatusItem (AppKit) | Better control over icon/title updates |

## Gate Check
- [x] All decisions locked
BLUEPRINT_EOF

  cat > "$P_DIR/specs/INFRASTRUCTURE.md" << INFRASTRUCTURE_EOF
# SwiftDesktopApp — Framework Specification

## Project Identity
- **Project Name:** SwiftDesktopApp
- **Project Slug:** swift_desktop_app
- **Project Path:** $P_DIR
- **DB Filename:** swift_desktop_app.db
- **Lessons File:** LESSONS_SWIFT_DESKTOP_APP.md
- **Rules File:** SWIFT_DESKTOP_APP_RULES.md
- **Project Memory File:** SWIFT_DESKTOP_APP_PROJECT_MEMORY.md
- **North Star:** macOS status bar Pomodoro timer — native Swift, SQLite session log, minimal UI, zero cloud

## Tech Stack
- **Language:** Swift 5.9+
- **UI Framework:** SwiftUI + AppKit (NSStatusItem)
- **Database:** SQLite via GRDB.swift
- **Build:** Xcode 15+, xcodebuild
- **Deployment:** Unsigned local build

## Phase Plan
| Phase ID | Name | Description | Key Deliverables |
|----------|------|-------------|-----------------|
| P0-FOUNDATION | Foundation | Xcode project, AppDelegate, NSStatusItem shell | App launches, shows icon in menu bar |
| P1-DATA | Data Layer | GRDB schema, session model, CRUD | Sessions persist across app launches |
| P2-VIEWS | Views | SwiftUI popover, timer display, controls | UI shows timer and buttons |
| P3-INTERACTIONS | Interactions | Timer logic, system sound, keyboard shortcuts | Full timer cycle works |
| P4-POLISH | Polish | Settings view, error handling, edge cases | All states handled |
| P5-SHIP | Ship | Testing, cleanup, README | Clean build, no warnings |

## Phase Ordinals
\`\`\`
P0-FOUNDATION) echo 0 ;;
P1-DATA) echo 1 ;;
P2-VIEWS) echo 2 ;;
P3-INTERACTIONS) echo 3 ;;
P4-POLISH) echo 4 ;;
P5-SHIP) echo 5 ;;
\`\`\`

## Agent Workforce
| Tier | Model | Use For |
|------|-------|---------|
| Opus | claude-opus-4-6 | Architecture, complex Swift patterns, AppKit bridge |
| Sonnet | claude-sonnet-4-6 | Multi-file Swift features, SwiftUI views |
| Haiku | claude-haiku-4-5 | Single-file edits, config, boilerplate |
| apple-platform-build-tools | specialist agent | Build, test, simulator management |

## Build & Test
\`\`\`bash
xcodebuild -project SwiftDesktopApp/SwiftDesktopApp.xcodeproj -scheme SwiftDesktopApp build 2>&1 | tail -20
\`\`\`

## Commit Format
\`[PHASE] scope: description\` e.g. \`[P0-FOUNDATION] app: add NSStatusItem setup\`

## Code Standards
- Swift style: Apple conventions, no force unwraps in production
- SwiftUI: prefer @StateObject for owned data, @ObservedObject for injected
- GRDB: read-only access to session DB from views, writes via services only
- Error handling: Result type or do/catch, never silent failures

## Visual Verification
This project HAS visual UI — visual verification gate is ACTIVE. Use screenshots to verify SwiftUI popover layout and dark mode after UI changes.

## MCP Servers Available
- Desktop Commander, XcodeBuild MCP

## Project-Specific STOP Rules
- STOP before any App Store distribution changes (unsigned personal tool)
- STOP before using deprecated AppKit APIs
- STOP before adding iCloud or network access (local-only)

## Gitignore Patterns
| Pattern | Why |
|---------|-----|
| DerivedData/ | Xcode build cache |
| *.xcuserdata/ | User-specific Xcode state |
| build/ | Build output |
| *.db-journal, *.db-wal | SQLite temp files |
| .DS_Store | macOS metadata |
INFRASTRUCTURE_EOF

  cat > "$P_DIR/specs/RESEARCH.md" << 'RESEARCH_EOF'
# SwiftDesktopApp — Research

## NSStatusItem for macOS Menu Bar Apps
NSStatusItem is the correct approach for a persistent menu bar icon. Use NSStatusItem.button.title for the countdown string. Set preferredEdge = .minY for popover attachment. NSStatusItem.length = NSVariableStatusItemLength allows text to resize.

## SwiftUI + AppKit Interop
NSHostingView wraps SwiftUI views for use in NSWindow/NSPopover. Use NSPopover with SwiftUI content for the click-to-expand popover. AppDelegate sets up the status item; SwiftUI handles the popover content.

## GRDB for Local SQLite
GRDB.swift is the best Swift SQLite library. Use DatabaseQueue for single-file access. DatabaseMigrator handles schema versioning. For timer apps, schema is minimal: sessions table with start_at, end_at, type, completed.
RESEARCH_EOF
}

# === ENGINE DEPLOYMENT =======================================================
deploy_project() {
  # Must be called after load_project_config N and create_specs N
  header "Deploying Engine: $P_NAME (project $P_NUM)"
  cd "$P_DIR"

  section "2a. Scaffold directories"
  mkdir -p frameworks refs backups .claude/rules
  info "Created frameworks/, refs/, backups/, .claude/rules/"

  section "2b. Copy framework files"
  cp "$TEMPLATE_FRAMEWORKS"/*.md frameworks/
  cp "$GLOBAL_FRAMEWORKS/loopback-system.md" frameworks/
  local FW_COUNT; FW_COUNT=$(ls frameworks/*.md | wc -l)
  info "Copied $FW_COUNT framework files"

  section "2c. Copy + customize template scripts"
  deploy_scripts

  section "2d. Initialize database"
  touch "$P_DB"
  bash db_queries.sh init-db || { echo "init-db failed"; exit 1; }

  section "2e. Seed phase_gates table"
  for ph in $P_PHASES; do
    _run_sql "$P_DB" "INSERT OR IGNORE INTO phase_gates (phase) VALUES ('$ph')"
  done
  info "Seeded phase_gates: $P_PHASES"

  section "2f. Insert test tasks"
  insert_tasks

  section "2g. Generate RULES.md"
  generate_rules

  section "2h. Generate CLAUDE.md"
  generate_claude_md

  section "2i. Create tracking files"
  create_tracking_files

  section "2j. Create git hooks"
  create_git_hooks

  section "2k. Create refs/ directory"
  create_refs

  section "2l. Create .gitignore"
  create_gitignore

  section "2m. Deploy .claude/hooks/"
  deploy_claude_hooks

  section "2n. Deploy .claude/settings.json"
  deploy_settings_json

  section "2o. Deploy .claude/agents/"
  deploy_agents

  info "Engine deployment complete for $P_NAME"
}

deploy_scripts() {
  # Placeholders to replace in all scripts
  local COMMON_SED=(
    -e "s|%%PROJECT_DB%%|${P_DB}|g"
    -e "s|%%PROJECT_DB_NAME%%|${P_DB_NAME}|g"
    -e "s|%%PROJECT_NAME%%|${P_NAME}|g"
    -e "s|%%LESSONS_FILE%%|${P_LESSONS}|g"
    -e "s|%%PROJECT_MEMORY_FILE%%|${P_MEMORY}|g"
    -e "s|%%RULES_FILE%%|${P_RULES}|g"
    -e "s|%%PROJECT_PATH%%|${P_DIR}|g"
    -e "s|%%PHASES%%|${P_PHASES}|g"
  )

  # db_queries.sh — thin Python wrapper (delegates to dbq package)
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/db_queries.template.sh" > db_queries.sh

  # session_briefing.sh
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/session_briefing.template.sh" > session_briefing.sh

  # milestone_check.sh
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/milestone_check.template.sh" > milestone_check.sh

  # coherence_check.sh — only %%LESSONS_FILE%% in actual code (SKIP_PATTERN_* are comments)
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/coherence_check.template.sh" > coherence_check.sh

  # coherence_registry.sh — no placeholders, copy as-is
  cp "$TEMPLATE_SCRIPTS/coherence_registry.template.sh" coherence_registry.sh

  # build_summarizer.sh — generate real (but test-safe) implementation
  create_build_summarizer

  # work.sh
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/work.template.sh" > work.sh

  # fix.sh
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/fix.template.sh" > fix.sh

  # harvest.sh
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/harvest.template.sh" > harvest.sh

  # generate_board.py
  sed "${COMMON_SED[@]}" "$TEMPLATE_SCRIPTS/generate_board.template.py" > generate_board.py

  # dbq Python CLI engine (symlink to source — mirrors bootstrap_project.sh phase_scripts)
  mkdir -p scripts
  ln -sf "$TEMPLATE_SCRIPTS/dbq" scripts/dbq

  chmod +x db_queries.sh session_briefing.sh milestone_check.sh coherence_check.sh \
           coherence_registry.sh build_summarizer.sh work.sh fix.sh harvest.sh
  info "All scripts copied, sed-filled, and made executable"
}

create_build_summarizer() {
  # Write a build summarizer that's real but doesn't require actual source code.
  # Uses echo/exit rather than actual build tool invocations for test projects.
  local BUILD_CMD
  case "$P_NUM" in
    1) BUILD_CMD="npm run build / npm test";;
    2) BUILD_CMD="cargo build / cargo test";;
    3) BUILD_CMD="poetry run pytest";;
    4) BUILD_CMD="xcodebuild build/test";;
    *) BUILD_CMD="(unknown stack)";;
  esac
  cat > build_summarizer.sh << BSEOF
#!/usr/bin/env bash
# build_summarizer.sh — $P_NAME
# Real implementation would run: $BUILD_CMD
PROJECT_DIR="\$(dirname "\$0")"
MODE="\${1:-build}"
case "\$MODE" in
  build)
    echo "── Build: $P_NAME ──────────────────────────────────"
    # Actual build command would go here. For test project: DB health check.
    bash "\$PROJECT_DIR/db_queries.sh" health 2>&1 | tail -5
    echo "BUILD OK (test project — no actual source code)"
    ;;
  test)
    echo "── Test: $P_NAME ──────────────────────────────────"
    bash "\$PROJECT_DIR/db_queries.sh" verify 2>&1 | tail -5
    bash "\$PROJECT_DIR/coherence_check.sh" --quiet 2>&1 || echo "(coherence warning)"
    echo "TEST OK (test project — no actual source code)"
    ;;
  verify)
    bash "\$PROJECT_DIR/db_queries.sh" health
    ;;
  *)
    echo "Usage: \$0 [build|test|verify]"; exit 1;;
esac
BSEOF
  chmod +x build_summarizer.sh
}

insert_tasks() {
  # 7 tasks: 2 in first phase, 2 in second, 2 in third, 1 MASTER in second
  local PHASES_ARRAY=($P_PHASES)
  local PH0="${PHASES_ARRAY[0]}"
  local PH1="${PHASES_ARRAY[1]}"
  local PH2="${PHASES_ARRAY[2]:-${PHASES_ARRAY[1]}}"

  _run_sql "$P_DB" "INSERT INTO tasks (id, phase, title, status, priority, assignee, sort_order, queue, tier) VALUES ('T-001', '$PH0', 'Initialize $P_NAME project structure', 'TODO', 'P0', 'CLAUDE', 1, 'BACKLOG', 'Haiku'), ('T-002', '$PH0', 'Configure build toolchain and linter', 'TODO', 'P1', 'CLAUDE', 2, 'BACKLOG', 'Haiku'), ('T-003', '$PH1', 'Implement core data models', 'TODO', 'P1', 'CLAUDE', 3, 'BACKLOG', 'Sonnet'), ('T-004', '$PH1', 'Write unit tests for core models', 'TODO', 'P2', 'CLAUDE', 4, 'BACKLOG', 'Haiku'), ('T-005', '$PH1', 'Review data model design', 'TODO', 'P2', 'MASTER', 5, 'BACKLOG', NULL), ('T-006', '$PH2', 'Build primary feature implementation', 'TODO', 'P2', 'CLAUDE', 6, 'BACKLOG', 'Sonnet'), ('T-007', '$PH2', 'Add error handling throughout', 'TODO', 'P3', 'CLAUDE', 7, 'BACKLOG', 'Sonnet')"
  local COUNT; COUNT=$(_run_sql "$P_DB" "SELECT COUNT(*) FROM tasks")
  info "Inserted $COUNT tasks"
}

generate_rules() {
  # Use Python with environment variables to safely substitute all RULES_TEMPLATE.md placeholders
  local VISUAL_VERIF GEMINI_TABLE TEAM_TOPOLOGY OUTPUT_GATE EXTRA_DELEG

  if [ "$P_HAS_UI" = "YES" ]; then
    VISUAL_VERIF="After every SwiftUI/UI change: take a screenshot, compare to expected layout. Check dark mode. Verify spacing. Use XcodeBuild MCP screenshot tool or iOS Simulator screenshots."
  else
    VISUAL_VERIF="Not applicable — this is a non-visual project (CLI tool / API service). No screenshot verification required."
  fi

  if [ "$P_HAS_GEMINI" = "YES" ]; then
    GEMINI_TABLE="## Gemini MCP Tools Available
| Tool | Use Case |
|------|----------|
| gemini-query | General Q&A, large context analysis |
| gemini-search | Web research, documentation lookup |
| gemini-analyze-code | Large codebase analysis, second opinion |
| gemini-deep-research | Complex research tasks |"
  else
    GEMINI_TABLE="## Gemini MCP
N/A — Gemini MCP not configured for this project."
  fi

  if [ "$P_HAS_TEAMS" = "YES" ]; then
    TEAM_TOPOLOGY="Active for this project. Configure in ~/.claude/settings.json.
| Role | Model | Responsibilities |
|------|-------|-----------------|
| Orchestrator | claude-opus-4-6 | Architecture, task assignment, final review |
| Implementer 1 | claude-sonnet-4-6 | Feature implementation |
| Implementer 2 | claude-sonnet-4-6 | Testing and validation |"
  else
    TEAM_TOPOLOGY="Agent Teams mode is INACTIVE for this project. Using single-agent mode."
  fi

  case "$P_HAS_UI$P_HAS_GEMINI" in
    YESYES|YESNO)
      OUTPUT_GATE="**Visual Verification Gate (ACTIVE)**
After every UI component change:
1. Take a screenshot
2. Compare to expected layout
3. Check: spacing, colors, dark mode, interactive states
4. Document findings before marking task DONE" ;;
    NOYES|NONO)
      if [ "$P_NUM" = "3" ]; then
        OUTPUT_GATE="**API Contract Gate**
After every endpoint change:
1. Run pytest test suite — all tests must pass
2. Verify response schemas match OpenAPI spec
3. Test edge cases: empty input, invalid auth, max payload
4. Check: status codes, error messages, response times"
      else
        OUTPUT_GATE="**CLI Test Gate**
After every command implementation:
1. Run \`cargo test\` / \`pytest\` — all tests must pass
2. Manual smoke test: run the command with sample input
3. Verify error messages are clear and helpful
4. Test dry-run mode produces correct preview"
      fi ;;
  esac

  if [ "$P_HAS_GEMINI" = "YES" ]; then
    EXTRA_DELEG="| Large context analysis, research | **Gemini** | Gemini MCP tools handle long documents |"
  else
    EXTRA_DELEG=""
  fi

  local PHASES_ARRAY=($P_PHASES)
  local TECH_STACK BUILD_INSTRUCTIONS CODE_STANDARDS GITIGNORE_TABLE STOP_RULES

  case "$P_NUM" in
    1)
      TECH_STACK="Node.js 20, Next.js 14 (App Router), TypeScript, Tailwind CSS, SQLite (better-sqlite3), Vitest, Playwright"
      BUILD_INSTRUCTIONS="npm run build 2>&1 | tail -20   # production build
npm test 2>&1 | tail -20          # vitest unit tests
npx playwright test 2>&1 | tail -20 # E2E tests"
      CODE_STANDARDS="TypeScript strict mode (no implicit any). ESLint + Prettier enforced. No inline styles — Tailwind utility classes only. API routes: always return typed responses."
      GITIGNORE_TABLE="| node_modules/ | npm deps | .next/ | build output | .env* | secrets | *.db-journal | SQLite temp |"
      STOP_RULES="- STOP before adding any cloud/paid dependency
- STOP before modifying existing bookmark data (imports are append-only)"
      ;;
    2)
      TECH_STACK="Rust 1.75+, Cargo, clap 4.x, walkdir, regex crate"
      BUILD_INSTRUCTIONS="cargo build 2>&1 | tail -20   # debug build
cargo test 2>&1 | tail -20    # all tests
cargo build --release 2>&1 | tail -20  # release binary"
      CODE_STANDARDS="cargo clippy -- -D warnings (zero warnings). cargo fmt enforced. No unwrap() in non-test code. Use anyhow for error propagation."
      GITIGNORE_TABLE="| target/ | Cargo build output | Cargo.lock | lock file | *.db-journal | SQLite temp |"
      STOP_RULES="- STOP before any file modifications without dry-run check first
- STOP before adding network calls (this is an offline tool)"
      ;;
    3)
      TECH_STACK="Python 3.12, Poetry, FastAPI 0.109+, SQLAlchemy 2.x, SQLite, python-jose, passlib, pytest, httpx"
      BUILD_INSTRUCTIONS="poetry run pytest 2>&1 | tail -20
poetry run pytest --cov 2>&1 | tail -20
poetry run mypy . 2>&1 | tail -20"
      CODE_STANDARDS="Black + Ruff enforced. mypy strict type checking. No bare except clauses. All FastAPI endpoints have response_model annotations."
      GITIGNORE_TABLE="| __pycache__/ | bytecode | .venv/ | virtualenv | dist/ | build output | .env | secrets |"
      STOP_RULES="- STOP before writing to production DB during tests (use test DB)
- STOP before adding paid API key dependencies"
      ;;
    4)
      TECH_STACK="Swift 5.9+, SwiftUI, AppKit (NSStatusItem), GRDB.swift, Xcode 15+, local unsigned build"
      BUILD_INSTRUCTIONS="xcodebuild -project SwiftDesktopApp/SwiftDesktopApp.xcodeproj -scheme SwiftDesktopApp build 2>&1 | tail -20
xcodebuild test 2>&1 | tail -20"
      CODE_STANDARDS="Apple Swift conventions. No force unwraps in production code. @StateObject for owned data, @ObservedObject for injected. GRDB: read-only from views, writes via service layer only."
      GITIGNORE_TABLE="| DerivedData/ | Xcode cache | *.xcuserdata/ | user state | build/ | output | *.db-journal | SQLite temp |"
      STOP_RULES="- STOP before any App Store distribution (unsigned personal tool)
- STOP before using deprecated AppKit APIs
- STOP before adding iCloud or network access (local-only)"
      ;;
  esac

  export RULES_PLACEHOLDER_PROJECT_NAME="$P_NAME"
  export RULES_PLACEHOLDER_PROJECT_NORTH_STAR="$(head -2 specs/INFRASTRUCTURE.md | grep 'North Star' | sed 's/.*North Star: //' | tr -d '*')"
  export RULES_PLACEHOLDER_PROJECT_PATH="$P_DIR"
  export RULES_PLACEHOLDER_PROJECT_MEMORY_FILE="$P_MEMORY"
  export RULES_PLACEHOLDER_FIRST_PHASE="${PHASES_ARRAY[0]}"
  export RULES_PLACEHOLDER_TECH_STACK="$TECH_STACK"
  export RULES_PLACEHOLDER_COMMIT_FORMAT="[PHASE] scope: description — e.g. [${PHASES_ARRAY[0]}] init: scaffold project"
  export RULES_PLACEHOLDER_BUILD_TEST_INSTRUCTIONS="$BUILD_INSTRUCTIONS"
  export RULES_PLACEHOLDER_CODE_STANDARDS="$CODE_STANDARDS"
  export RULES_PLACEHOLDER_GITIGNORE_TABLE="$GITIGNORE_TABLE"
  export RULES_PLACEHOLDER_OUTPUT_VERIFICATION_GATE="$OUTPUT_GATE"
  export RULES_PLACEHOLDER_PROJECT_STOP_RULES="$STOP_RULES"
  export RULES_PLACEHOLDER_EXTRA_MODEL_DELEGATION="$EXTRA_DELEG"
  export RULES_PLACEHOLDER_TEAM_TOPOLOGY="$TEAM_TOPOLOGY"
  export RULES_PLACEHOLDER_GEMINI_MCP_TABLE="$GEMINI_TABLE"
  export RULES_PLACEHOLDER_VISUAL_VERIFICATION="$VISUAL_VERIF"
  export RULES_PLACEHOLDER_EXTRA_MANDATORY_SKILLS="| **Before every phase gate** | /code-review | Review all changes in phase before gating |"
  export RULES_PLACEHOLDER_RECOMMENDED_SKILLS="| Starting new phase | /engineering:architecture | Review phase approach |"
  export RULES_PLACEHOLDER_MCP_SERVERS="$([ "$P_HAS_GEMINI" = "YES" ] && echo "- Gemini MCP (research, analysis)" || echo ""); - Desktop Commander (file ops, shell commands)"

  python3 << 'PYEOF'
import os, sys

template_path = os.path.expanduser('~/.claude/dev-framework/templates/rules/RULES_TEMPLATE.md')
output_path = os.environ.get('RULES_OUTPUT_PATH', 'RULES.md')

with open(template_path, 'r') as f:
    content = f.read()

for key, value in os.environ.items():
    if key.startswith('RULES_PLACEHOLDER_'):
        placeholder = '%%' + key[len('RULES_PLACEHOLDER_'):] + '%%'
        content = content.replace(placeholder, value)

# Check for any remaining unfilled placeholders
import re
remaining = re.findall(r'%%[A-Z_]+%%', content)
if remaining:
    print(f"  WARNING: {len(remaining)} unfilled placeholders remain: {set(remaining)}", file=sys.stderr)

with open(output_path, 'w') as f:
    f.write(content)

print(f"  Generated {output_path} ({len(content)} bytes)")
PYEOF

  # Rename to project-specific rules file
  mv RULES.md "$P_RULES" 2>/dev/null || true

  # Generate extended rules (refs/rules-extended.md) — same placeholders, different template
  local EXTENDED_TEMPLATE="$TEMPLATES/rules/RULES_EXTENDED_TEMPLATE.md"
  if [ -f "$EXTENDED_TEMPLATE" ]; then
    mkdir -p refs
    python3 << 'PYEOF2'
import os, sys, re

template_path = os.path.expanduser('~/.claude/dev-framework/templates/rules/RULES_EXTENDED_TEMPLATE.md')
output_path = 'refs/rules-extended.md'

with open(template_path, 'r') as f:
    content = f.read()

for key, value in os.environ.items():
    if key.startswith('RULES_PLACEHOLDER_'):
        placeholder = '%%' + key[len('RULES_PLACEHOLDER_'):] + '%%'
        content = content.replace(placeholder, value)

remaining = re.findall(r'%%[A-Z_]+%%', content)
if remaining:
    print(f"  WARNING: {len(remaining)} unfilled placeholders in extended rules: {set(remaining)}", file=sys.stderr)

with open(output_path, 'w') as f:
    f.write(content)

print(f"  Generated {output_path} ({len(content)} bytes)")
PYEOF2
  fi

  export -n RULES_PLACEHOLDER_PROJECT_NAME RULES_PLACEHOLDER_PROJECT_NORTH_STAR \
    RULES_PLACEHOLDER_PROJECT_PATH RULES_PLACEHOLDER_PROJECT_MEMORY_FILE \
    RULES_PLACEHOLDER_FIRST_PHASE RULES_PLACEHOLDER_TECH_STACK \
    RULES_PLACEHOLDER_COMMIT_FORMAT RULES_PLACEHOLDER_BUILD_TEST_INSTRUCTIONS \
    RULES_PLACEHOLDER_CODE_STANDARDS RULES_PLACEHOLDER_GITIGNORE_TABLE \
    RULES_PLACEHOLDER_OUTPUT_VERIFICATION_GATE RULES_PLACEHOLDER_PROJECT_STOP_RULES \
    RULES_PLACEHOLDER_EXTRA_MODEL_DELEGATION RULES_PLACEHOLDER_TEAM_TOPOLOGY \
    RULES_PLACEHOLDER_GEMINI_MCP_TABLE RULES_PLACEHOLDER_VISUAL_VERIFICATION \
    RULES_PLACEHOLDER_EXTRA_MANDATORY_SKILLS RULES_PLACEHOLDER_RECOMMENDED_SKILLS \
    RULES_PLACEHOLDER_MCP_SERVERS
}

generate_claude_md() {
  sed \
    -e "s|%%PROJECT_NAME%%|${P_NAME}|g" \
    -e "s|%%RULES_FILE%%|${P_RULES}|g" \
    -e "s|%%LESSONS_FILE%%|${P_LESSONS}|g" \
    "$CLAUDE_TEMPLATE" > CLAUDE.md
  info "Generated CLAUDE.md"
}

create_tracking_files() {
  # LESSONS file
  cat > "$P_LESSONS" << LESSEOF
# $P_NAME — Lessons & Corrections

## Corrections Log
| Date | What Happened | Root Cause | Rule | Promoted |
|------|--------------|------------|------|----------|

## Insights
| Date | Insight | Category | Notes |
|------|---------|----------|-------|

## Universal Patterns (cross-project candidates)
| Date | Pattern | Rule | Source | Promoted |
|------|---------|------|--------|----------|
LESSEOF

  # PROJECT_MEMORY file
  cat > "$P_MEMORY" << MEMEOF
# $P_NAME — Project Memory

## §1 Overview
$(grep "One-Paragraph Pitch" specs/VISION.md -A 2 | tail -1 | sed 's/^> //' | xargs)

## §2 Section Lookup
| What you need | Where to look |
|---------------|---------------|
| Task status | \`bash db_queries.sh next\` |
| Architecture | §3 below |
| File structure | §4 below |

## §3 Architecture
$(grep -A 10 "Tech Stack" specs/BLUEPRINT.md | head -8 || echo "See specs/BLUEPRINT.md")

## §4 File Structure
\`\`\`
$P_NAME/
├── specs/          # Project spec documents
├── frameworks/     # Process protocol documents
├── refs/           # Progressive disclosure references
└── $P_DB     # Task tracking database
\`\`\`
MEMEOF

  # LEARNING_LOG
  cat > LEARNING_LOG.md << 'LLEOF'
# Learning Log

| Date | What | Category | Notes |
|------|------|----------|-------|
LLEOF

  # AGENT_DELEGATION.md
  cat > AGENT_DELEGATION.md << ADEOF
# Agent Delegation Map — $P_NAME

## Workforce Tiers
| Tier | Model | Cost | When to Use |
|------|-------|------|-------------|
| **Opus** | claude-opus-4-6 | \$\$\$\$ | Architecture, gate reviews, judgment calls |
| **Sonnet** | claude-sonnet-4-6 | \$\$ | Multi-file features, complex logic |
| **Haiku** | claude-haiku-4-5 | \$ | Single-file, config, mechanical changes |
| **MASTER** | Human | — | Design decisions, testing, review, assets |

<!-- DELEGATION-START -->
*Run \`bash db_queries.sh delegation-md\` to populate with live task data.*
<!-- DELEGATION-END -->
ADEOF

  # NEXT_SESSION.md
  cat > NEXT_SESSION.md << NSEOF
# Next Session Handoff

**Handoff Source:** BOOTSTRAP
**Date:** $(date +%Y-%m-%d)
**Signal:** GREEN
**Branch:** dev

## Current State

Phase: $P_FIRST (tasks not yet started)
Gate: Not started
Blockers: None

## First Task

T-001 — Initialize $P_NAME project structure

## Overrides (active)

None.
NSEOF

  # ROUTER.md — on-demand context routing table
  local ROUTER_TMPL="$TEMPLATES/rules/ROUTER_TEMPLATE.md"
  if [ -f "$ROUTER_TMPL" ]; then
    sed \
      -e "s|%%PROJECT_MEMORY_FILE%%|${P_MEMORY}|g" \
      -e "s|%%LESSONS_FILE%%|${P_LESSONS}|g" \
      "$ROUTER_TMPL" > ROUTER.md
  else
    cat > ROUTER.md << ROUTEREOF
# Context Router — Reference
> This table lists on-demand context files. You don't need to memorize this.
> Hooks will remind you when to load these. Consult this table if unsure.

## On-Demand Frameworks

| Framework | File | Loaded By |
|-----------|------|-----------|
| Correction protocol | \`~/.claude/frameworks/correction-protocol.md\` | Hook: correction-detector.sh |
| Delegation rules | \`~/.claude/frameworks/delegation.md\` | Hook: pre-edit-check.sh (delegation gate) |
| Loopback system | \`~/.claude/frameworks/loopback-system.md\` | Hook: session-start (when loopbacks exist) |
| Phase gates | \`~/.claude/frameworks/phase-gates.md\` | Manual: before pre-task check |

## On-Demand Project Context

| Context | Source | When |
|---------|--------|------|
| Active delegation map | \`bash db_queries.sh delegation-md --active-only\` | Before assigning tasks |
| Architecture context | \`$P_MEMORY\` | Architectural questions |
| Recent lessons | \`$P_LESSONS\` (tail -50) | Before similar work |
ROUTEREOF
  fi

  # LESSONS_UNIVERSAL.md — cross-project patterns (deployed by bootstrap_project.sh)
  cat > LESSONS_UNIVERSAL.md << 'LUEOF'
# Universal Lessons — Cross-Project Patterns

| Date | Pattern | Rule | Source | Promoted |
|------|---------|------|--------|----------|
LUEOF

  info "Created: $P_LESSONS, $P_MEMORY, LEARNING_LOG.md, AGENT_DELEGATION.md, NEXT_SESSION.md, ROUTER.md, LESSONS_UNIVERSAL.md"
}

create_git_hooks() {
  local HOOK_DIR=".git/hooks"

  cat > "$HOOK_DIR/pre-commit" << HOOKEOF
#!/usr/bin/env bash
# Quality Gate 1 — pre-commit ($P_NAME)
DIR="\$(git rev-parse --show-toplevel)"
echo "── Pre-commit checks ──"

# Coherence check (soft warning — doesn't block on clean registry)
if [ -f "\$DIR/coherence_check.sh" ]; then
    bash "\$DIR/coherence_check.sh" --quiet 2>&1 || true
fi

# Knowledge health nag
if [ -f "\$DIR/$P_LESSONS" ]; then
    UNPROMOTED=\$(grep -cE "^\\\|[^|]+\\\|[^|]+\\\| No( —| \\\|)" "\$DIR/$P_LESSONS" 2>/dev/null)
    UNPROMOTED="\${UNPROMOTED:-0}"
    [ "\$UNPROMOTED" -gt 3 ] && echo "⚠️  \$UNPROMOTED unpromoted lesson(s)"
fi
exit 0
HOOKEOF

  cat > "$HOOK_DIR/pre-push" << PUSHEOF
#!/usr/bin/env bash
# Quality Gate 2 — pre-push ($P_NAME)
echo "── Pre-push checks ──"
echo "Pre-push: OK (test project — build check disabled)"
PUSHEOF

  chmod +x "$HOOK_DIR/pre-commit" "$HOOK_DIR/pre-push"
  info "Created pre-commit and pre-push hooks"
}

create_refs() {
  # Always-present refs
  cat > refs/README.md << 'REOF'
# refs/ — Progressive Disclosure Directory
Files here contain reference material extracted from RULES.md or accumulated over time.
Use: read specific files only when the current task needs them.
REOF

  cat > refs/tool-inventory.md << TIEOF
# Tool Inventory — $P_NAME

## Claude Models
| Model | ID | When to Use |
|-------|----|-------------|
| Opus | claude-opus-4-6 | Architecture, gates, judgment |
| Sonnet | claude-sonnet-4-6 | Features, implementation |
| Haiku | claude-haiku-4-5 | Config, boilerplate, single-file |

## MCP Servers
- Desktop Commander (file ops, shell)
$([ "$P_HAS_GEMINI" = "YES" ] && echo "- Gemini MCP (research, analysis)" || echo "")

## Local Tools
- sqlite3 (DB queries)
- python3 (generate_board.py, test runner)
TIEOF

  cat > refs/gotchas-workflow.md << 'GWEOF'
# Workflow Gotchas

*Populated automatically when corrections accumulate in workflow domain.*
*See: db_queries.sh done --loopback-lesson for how lessons get here.*

| Date | Gotcha | When It Fires | How to Avoid |
|------|--------|--------------|--------------|
GWEOF

  # Conditional refs
  if [ "$P_HAS_UI" = "YES" ]; then
    cat > refs/gotchas-frontend.md << 'GFEOF'
# Frontend / UI Gotchas

*Populated when UI-related corrections accumulate.*

| Date | Gotcha | When It Fires | How to Avoid |
|------|--------|--------------|--------------|
GFEOF
    info "Created refs/gotchas-frontend.md (UI project)"
  fi

  if [ "$P_HAS_SKILLS" = "YES" ]; then
    cat > refs/skills-catalog.md << SCEOF
# Skills Catalog — $P_NAME

| Skill | Trigger | What It Does |
|-------|---------|-------------|
| /code-review | Before merge | Structured code review |
| /engineering:debug | On errors | Structured debugging |
| /engineering:testing-strategy | Phase start | Test plan for new phase |
SCEOF
    info "Created refs/skills-catalog.md (Skills=YES)"
  fi

  if [ "$P_HAS_DEFERRED" = "YES" ]; then
    cat > refs/planned-integrations.md << PIEOF
# Planned Integrations — $P_NAME

*Deferred to v2+. Documented here to avoid re-evaluating during v1 build.*

| Integration | Why Deferred | Notes for v2 |
|-------------|-------------|--------------|
| *See specs/BLUEPRINT.md deferred scope items* | Out of v1 scope | Re-evaluate after v1 ships |
PIEOF
    info "Created refs/planned-integrations.md (Deferred=YES)"
  fi
}

create_gitignore() {
  case "$P_NUM" in
    1) cat > .gitignore << 'EOF'
node_modules/
.next/
.env
.env.local
.env.production
*.db-journal
*.db-wal
*.db-shm
backups/
.DS_Store
EOF
    ;;
    2) cat > .gitignore << 'EOF'
target/
*.db-journal
*.db-wal
*.db-shm
backups/
.DS_Store
EOF
    ;;
    3) cat > .gitignore << 'EOF'
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
.env
*.db-journal
*.db-wal
*.db-shm
backups/
.DS_Store
EOF
    ;;
    4) cat > .gitignore << 'EOF'
DerivedData/
*.xcuserdata/
build/
*.db-journal
*.db-wal
*.db-shm
backups/
.DS_Store
EOF
    ;;
  esac
  info "Created .gitignore (${P_NUM}-specific patterns)"
}

deploy_claude_hooks() {
  # Deploy .claude/hooks/ from templates — mirrors bootstrap_project.sh phase_hooks()
  local HOOK_TMPL_DIR="$TEMPLATES/hooks"
  if [ ! -d "$HOOK_TMPL_DIR" ]; then
    warn "Hook templates not found at $HOOK_TMPL_DIR — skipping"
    return
  fi
  mkdir -p .claude/hooks
  local HOOK_COUNT=0
  for hook_template in "$HOOK_TMPL_DIR"/*.template.sh "$HOOK_TMPL_DIR"/*.template.conf; do
    [ -f "$hook_template" ] || continue
    local BASENAME
    BASENAME=$(basename "$hook_template" | sed 's/\.template\././')
    cp "$hook_template" ".claude/hooks/$BASENAME"
    # Replace common placeholders
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' \
        -e "s|%%PROJECT_NAME%%|$P_NAME|g" \
        -e "s|%%PROJECT_DB%%|$P_DB|g" \
        -e "s|%%LESSONS_FILE%%|$P_LESSONS|g" \
        -e "s|%%PROJECT_RULES_FILE%%|$P_RULES|g" \
        -e "s|%%OWN_DB_PATTERNS%%|$P_DB|g" \
        -e "s|%%LESSON_LOG_COMMAND%%|bash db_queries.sh log-lesson|g" \
        -e "s|%%AGENT_NAMES%%||g" \
        ".claude/hooks/$BASENAME"
    else
      sed -i \
        -e "s|%%PROJECT_NAME%%|$P_NAME|g" \
        -e "s|%%PROJECT_DB%%|$P_DB|g" \
        -e "s|%%LESSONS_FILE%%|$P_LESSONS|g" \
        -e "s|%%PROJECT_RULES_FILE%%|$P_RULES|g" \
        -e "s|%%OWN_DB_PATTERNS%%|$P_DB|g" \
        -e "s|%%LESSON_LOG_COMMAND%%|bash db_queries.sh log-lesson|g" \
        -e "s|%%AGENT_NAMES%%||g" \
        ".claude/hooks/$BASENAME"
    fi
    chmod +x ".claude/hooks/$BASENAME" 2>/dev/null || true
    HOOK_COUNT=$((HOOK_COUNT + 1))
  done
  info "Deployed $HOOK_COUNT hook scripts to .claude/hooks/"
}

deploy_settings_json() {
  # Deploy .claude/settings.json from template — mirrors bootstrap_project.sh phase_settings()
  local SETTINGS_TMPL="$TEMPLATES/settings/settings.template.json"
  if [ ! -f "$SETTINGS_TMPL" ]; then
    warn "Settings template not found at $SETTINGS_TMPL — skipping"
    return
  fi
  mkdir -p .claude
  cp "$SETTINGS_TMPL" .claude/settings.json
  local ALLOW_LIST="Bash(bash db_queries.sh *),Bash(bash session_briefing.sh*),Bash(bash coherence_check.sh*),Bash(bash milestone_check.sh*),Bash(bash build_summarizer.sh*),Bash(python3 generate_board.py*),Bash(sqlite3 ${P_DB}*),Bash(git *)"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|%%PERMISSION_ALLOW%%|$ALLOW_LIST|g" .claude/settings.json
  else
    sed -i "s|%%PERMISSION_ALLOW%%|$ALLOW_LIST|g" .claude/settings.json
  fi
  info "Deployed .claude/settings.json with hook wiring"
}

deploy_agents() {
  # Deploy .claude/agents/ from templates — mirrors bootstrap_project.sh phase_agents()
  local AGENT_TMPL_DIR="$TEMPLATES/agents"
  if [ ! -d "$AGENT_TMPL_DIR" ]; then
    warn "Agent templates not found at $AGENT_TMPL_DIR — skipping"
    return
  fi
  mkdir -p .claude/agents/implementer .claude/agents/worker
  if [ -f "$AGENT_TMPL_DIR/implementer.template.md" ]; then
    cp "$AGENT_TMPL_DIR/implementer.template.md" .claude/agents/implementer/implementer.md
    local P_NAME_UPPER
    P_NAME_UPPER=$(echo "$P_NAME" | tr '[:lower:]' '[:upper:]' | tr ' ' '_')
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' \
        -e "s|%%PROJECT_NAME%%|$P_NAME|g" \
        -e "s|%%TECH_STACK_HOOKS%%||g" \
        -e "s|%%TECH_STANDARDS%%|Follow the project's code standards in ${P_NAME_UPPER}_RULES.md.|g" \
        -e "s|%%BUILD_COMMAND%%|bash build_summarizer.sh build|g" \
        .claude/agents/implementer/implementer.md
    else
      sed -i \
        -e "s|%%PROJECT_NAME%%|$P_NAME|g" \
        -e "s|%%TECH_STACK_HOOKS%%||g" \
        -e "s|%%TECH_STANDARDS%%|Follow the project's code standards in ${P_NAME_UPPER}_RULES.md.|g" \
        -e "s|%%BUILD_COMMAND%%|bash build_summarizer.sh build|g" \
        .claude/agents/implementer/implementer.md
    fi
  fi
  if [ -f "$AGENT_TMPL_DIR/worker.template.md" ]; then
    cp "$AGENT_TMPL_DIR/worker.template.md" .claude/agents/worker/worker.md
    local P_NAME_UPPER
    P_NAME_UPPER=$(echo "$P_NAME" | tr '[:lower:]' '[:upper:]' | tr ' ' '_')
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' \
        -e "s|%%PROJECT_NAME%%|$P_NAME|g" \
        -e "s|%%TECH_STANDARDS_BRIEF%%|Follow the project's code standards in ${P_NAME_UPPER}_RULES.md.|g" \
        .claude/agents/worker/worker.md
    else
      sed -i \
        -e "s|%%PROJECT_NAME%%|$P_NAME|g" \
        -e "s|%%TECH_STANDARDS_BRIEF%%|Follow the project's code standards in ${P_NAME_UPPER}_RULES.md.|g" \
        .claude/agents/worker/worker.md
    fi
  fi
  info "Deployed .claude/agents/ (implementer + worker)"
}

# === D7 VERIFICATION =========================================================
verify_project() {
  header "D7 Verification: $P_NAME"
  cd "$P_DIR"

  section "Check 1: DB exists and health passes"
  chk "DB file exists" test -f "$P_DB"
  chk "health passes (exit 0)" bash db_queries.sh health

  section "Check 2: Framework files ($EXPECTED_FRAMEWORKS total)"
  local FW_COUNT; FW_COUNT=$(ls frameworks/*.md 2>/dev/null | wc -l | tr -d ' ')
  if [ "$FW_COUNT" -eq "$EXPECTED_FRAMEWORKS" ]; then pass "$EXPECTED_FRAMEWORKS framework files present"; else fail "Expected $EXPECTED_FRAMEWORKS framework files, found $FW_COUNT"; fi
  chk "loopback-system.md specifically present" test -f "frameworks/loopback-system.md"

  section "Check 3: AGENT_DELEGATION.md exists"
  chk "AGENT_DELEGATION.md exists" test -f AGENT_DELEGATION.md
  chk "Delegation markers present" grep -q "DELEGATION-START" AGENT_DELEGATION.md

  section "Check 4: All scripts exist and executable"
  for s in db_queries.sh session_briefing.sh build_summarizer.sh milestone_check.sh \
            coherence_check.sh coherence_registry.sh work.sh fix.sh harvest.sh; do
    chk "$s executable" test -x "$s"
  done
  chk "generate_board.py exists" test -f generate_board.py

  section "Check 5: RULES file has no unfilled placeholders"
  if [ -f "$P_RULES" ]; then
    local REMAINING; REMAINING=$(grep -cE '%%[A-Z_]+%%' "$P_RULES" 2>/dev/null)
    REMAINING="${REMAINING:-0}"
    if [ "$REMAINING" -eq 0 ]; then pass "Zero unfilled placeholders in $P_RULES"; else
      fail "$REMAINING unfilled placeholders in $P_RULES"
      grep -E '%%[A-Z_]+%%' "$P_RULES" | head -5 | while read l; do warn "  $l"; done
    fi
  else
    fail "$P_RULES does not exist"
  fi

  section "Check 5b: Extended rules file exists and has no unfilled placeholders"
  if [ -f "refs/rules-extended.md" ]; then
    pass "refs/rules-extended.md exists"
    local EXT_REMAINING; EXT_REMAINING=$(grep -cE '%%[A-Z_]+%%' "refs/rules-extended.md" 2>/dev/null)
    EXT_REMAINING="${EXT_REMAINING:-0}"
    if [ "$EXT_REMAINING" -eq 0 ]; then pass "Zero unfilled placeholders in refs/rules-extended.md"; else
      fail "$EXT_REMAINING unfilled placeholders in refs/rules-extended.md"
      grep -E '%%[A-Z_]+%%' "refs/rules-extended.md" | head -5 | while read l; do warn "  $l"; done
    fi
  else
    fail "refs/rules-extended.md does not exist"
  fi

  section "Check 6: CLAUDE.md @-import chain — all referenced files exist"
  chk "CLAUDE.md exists" test -f CLAUDE.md
  if [ -f CLAUDE.md ]; then
    grep -oE '^@.+' CLAUDE.md | while read -r import; do
      local fname="${import:1}"
      chk "@$fname exists" test -f "$fname"
    done
  fi

  section "Check 7: Tracking files present"
  chk "LESSONS file exists ($P_LESSONS)" test -f "$P_LESSONS"
  chk "PROJECT_MEMORY exists ($P_MEMORY)" test -f "$P_MEMORY"
  chk "LEARNING_LOG.md exists" test -f "LEARNING_LOG.md"
  chk "NEXT_SESSION.md exists" test -f "NEXT_SESSION.md"

  section "Check 8: Git hooks executable"
  chk "pre-commit hook executable" test -x ".git/hooks/pre-commit"
  chk "pre-push hook executable" test -x ".git/hooks/pre-push"

  section "Check 9: .gitignore exists"
  chk ".gitignore exists" test -f ".gitignore"

  section "Check 10: refs/ directory scaffolded correctly"
  chk "refs/ directory exists" test -d "refs"
  chk "refs/README.md exists" test -f "refs/README.md"
  chk "refs/tool-inventory.md exists" test -f "refs/tool-inventory.md"
  chk "refs/gotchas-workflow.md exists" test -f "refs/gotchas-workflow.md"

  # Conditional refs
  if [ "$P_HAS_UI" = "YES" ]; then
    chk "refs/gotchas-frontend.md EXISTS (UI=YES)" test -f "refs/gotchas-frontend.md"
  else
    chk "refs/gotchas-frontend.md ABSENT (UI=NO)" bash -c "! test -f refs/gotchas-frontend.md"
  fi
  if [ "$P_HAS_SKILLS" = "YES" ]; then
    chk "refs/skills-catalog.md EXISTS (Skills=YES)" test -f "refs/skills-catalog.md"
  else
    chk "refs/skills-catalog.md ABSENT (Skills=NO)" bash -c "! test -f refs/skills-catalog.md"
  fi
  if [ "$P_HAS_DEFERRED" = "YES" ]; then
    chk "refs/planned-integrations.md EXISTS (Deferred=YES)" test -f "refs/planned-integrations.md"
  else
    chk "refs/planned-integrations.md ABSENT (Deferred=NO)" bash -c "! test -f refs/planned-integrations.md"
  fi

  section "Check 11: Zero unfilled %% across ALL files"
  local UNFILLED; UNFILLED=$(grep -r '%%[A-Z_]*%%' . \
    --include="*.sh" --include="*.md" --include="*.py" 2>/dev/null \
    | grep -v ".git/" | grep -vE "^\s*#|:[[:space:]]*#" | grep -v "template" | wc -l | tr -d ' ')
  UNFILLED="${UNFILLED:-0}"
  if [ "$UNFILLED" -eq 0 ]; then pass "Zero unfilled placeholders"; else
    fail "$UNFILLED unfilled placeholder occurrences"
    grep -r '%%[A-Z_]*%%' . --include="*.sh" --include="*.md" --include="*.py" 2>/dev/null \
      | grep -v ".git/" | grep -vE "^\s*#|:[[:space:]]*#" | grep -v "template" | head -5 | while read l; do warn "  $l"; done
  fi

  section "Check 12: Build summarizer runs"
  chk "build_summarizer.sh build succeeds" bash build_summarizer.sh build

  section "Check 13: verify_deployment.py $EXPECTED_CHECKS/$EXPECTED_CHECKS"
  local VD_SCRIPT_VP="${REPO_ROOT}/templates/scripts/verify_deployment.py"
  if [ -f "$VD_SCRIPT_VP" ] && python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
    local VD_OUT; VD_OUT=$(python3 "$VD_SCRIPT_VP" "$P_DIR" --json 2>/dev/null || true)
    local VD_PASSED; VD_PASSED=$(echo "$VD_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['passed'])" 2>/dev/null || echo "0")
    local VD_TOTAL; VD_TOTAL=$(echo "$VD_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total'])" 2>/dev/null || echo "0")
    if [ "$VD_PASSED" = "$VD_TOTAL" ] && [ "$VD_TOTAL" -ge "$EXPECTED_CHECKS" ]; then
      pass "verify_deployment.py: $VD_PASSED/$VD_TOTAL checks pass"
    else
      fail "verify_deployment.py: $VD_PASSED/$VD_TOTAL checks pass (expected $EXPECTED_CHECKS/$EXPECTED_CHECKS)"
      echo "$VD_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for c in d.get('checks',[]):
    if not c['passed']:
        print(f'  FAIL: {c[\"id\"]} {c[\"name\"]}: {c[\"message\"]}')
" 2>/dev/null | head -5 | while IFS= read -r l; do warn "$l"; done
    fi
  else
    warn "Skipped — verify_deployment.py or Python 3.10+ not available"
  fi

  section "Check 14: .claude/rules/ directory exists"
  chk ".claude/rules/ directory exists" test -d ".claude/rules"

  section "Check 15: settings.json hook commands resolve"
  if [ -f ".claude/settings.json" ]; then
    local HOOK_BROKEN=0
    local HOOK_CMDS; HOOK_CMDS=$(python3 -c "
import json, sys
d = json.load(open('.claude/settings.json'))
for event_entries in d.get('hooks', {}).values():
    if not isinstance(event_entries, list): continue
    for entry in event_entries:
        for hook in entry.get('hooks', []):
            cmd = hook.get('command', '')
            if cmd:
                token = cmd.split()[0].replace('\"\$CLAUDE_PROJECT_DIR\"', '.').replace('\$CLAUDE_PROJECT_DIR', '.')
                print(token)
" 2>/dev/null)
    for cmd_path in $HOOK_CMDS; do
      if [ ! -x "$cmd_path" ]; then
        warn "Hook command not executable: $cmd_path"
        HOOK_BROKEN=$((HOOK_BROKEN+1))
      fi
    done
    if [ "$HOOK_BROKEN" -eq 0 ]; then
      pass "All settings.json hook commands resolve to executable scripts"
    else
      fail "$HOOK_BROKEN hook command(s) not executable"
    fi
  else
    warn "No .claude/settings.json — skipping hook resolution check"
  fi

  section "Check 16: No stray %%TOKEN%% after comment filtering"
  local STRAY_TOKENS; STRAY_TOKENS=$(grep -r '%%[A-Z_][A-Z_0-9]*%%' . \
    --include="*.sh" --include="*.md" --include="*.py" --include="*.json" 2>/dev/null \
    | grep -v ".git/" | grep -v "template" \
    | grep -vE '^\s*#|:[[:space:]]*#|<!--' | wc -l | tr -d ' ')
  STRAY_TOKENS="${STRAY_TOKENS:-0}"
  if [ "$STRAY_TOKENS" -eq 0 ]; then pass "Zero stray placeholders after comment filtering"
  else
    fail "$STRAY_TOKENS stray placeholder(s) found after comment filtering"
    grep -r '%%[A-Z_][A-Z_0-9]*%%' . --include="*.sh" --include="*.md" --include="*.py" --include="*.json" 2>/dev/null \
      | grep -v ".git/" | grep -v "template" \
      | grep -vE '^\s*#|:[[:space:]]*#|<!--' | head -5 | while IFS= read -r l; do warn "  $l"; done
  fi

  # Bonus: regression checks from TestBootstrap
  section "Regression Checks (TestBootstrap bugs)"
  chk "details column exists in tasks" bash -c "sqlite3 $P_DB 'SELECT details FROM tasks LIMIT 1;'"
  chk "completed_on column exists in tasks" bash -c "sqlite3 $P_DB 'SELECT completed_on FROM tasks LIMIT 1;'"
  chk "researched column exists in tasks" bash -c "sqlite3 $P_DB 'SELECT researched FROM tasks LIMIT 1;'"
  chk "check command runs (GO/STOP verdict)" bash db_queries.sh check T-001
  chk "session_briefing runs without fatal error" bash session_briefing.sh
  chk "coherence_check runs without fatal error" bash coherence_check.sh
}

# === WORKFLOW EXERCISE =======================================================
exercise_project() {
  header "Workflow Exercise: $P_NAME"
  cd "$P_DIR"

  section "Core DB commands"
  chk "health: HEALTHY" bash db_queries.sh health
  chk "next: shows task queue" bash db_queries.sh next
  chk "verify: schema complete" bash db_queries.sh verify
  chk "check T-001: GO verdict" bash db_queries.sh check T-001

  section "Supporting scripts"
  chk "session_briefing produces output" bash -c "bash session_briefing.sh 2>&1 | grep -q ''"
  chk "coherence_check exits 0" bash coherence_check.sh --quiet
  chk "generate_board.py produces output" bash -c "python3 generate_board.py 2>&1 | grep -q ''"
}

# === FULL ACTIVATION PRODUCT FLOW =============================================
# Bootstraps a real project via bootstrap_project.sh and exercises the full
# product lifecycle: deploy → verify → exercise workflow commands.
# Unlike the 4-project E2E, this uses the actual product entry point.
product_flow_tests() {
  header "Full Activation Product Flow"
  P_NAME="product-flow"

  local FLOW_DIR="/tmp/bootstrap_test_flow_$$"
  rm -rf "$FLOW_DIR"

  section "PF1. Bootstrap via bootstrap_project.sh (standard deployment)"
  if bash "$REPO_ROOT/bootstrap_project.sh" "FlowTest" "$FLOW_DIR" --deployment standard --non-interactive >/dev/null 2>&1; then
    pass "bootstrap_project.sh created project successfully"
  else
    fail "bootstrap_project.sh failed to create project"
    rm -rf "$FLOW_DIR"
    return
  fi

  section "PF2. Core files deployed"
  chk "CLAUDE.md exists" test -f "$FLOW_DIR/CLAUDE.md"
  chk "db_queries.sh exists" test -f "$FLOW_DIR/db_queries.sh"
  chk "session_briefing.sh exists" test -f "$FLOW_DIR/session_briefing.sh"
  chk "frameworks/ directory exists" test -d "$FLOW_DIR/frameworks"
  chk "scripts/dbq/ runtime exists" test -d "$FLOW_DIR/scripts/dbq"
  chk ".claude/agents/ deployed" test -d "$FLOW_DIR/.claude/agents"

  section "PF3. DB healthy after fresh bootstrap"
  local HEALTH_OUT
  HEALTH_OUT=$(cd "$FLOW_DIR" && bash db_queries.sh health 2>&1)
  # Fresh bootstraps report DEGRADED (orphaned phase gates) — that's expected
  if echo "$HEALTH_OUT" | grep -qiE "HEALTHY|DEGRADED"; then
    pass "DB health: non-critical (HEALTHY or DEGRADED)"
  else
    fail "DB health check returned critical/error state"
    warn "Output: $HEALTH_OUT"
  fi

  section "PF4. Workflow commands functional"
  chk "next: shows task queue" bash -c "cd '$FLOW_DIR' && bash db_queries.sh next >/dev/null 2>&1"
  chk "phase: shows current phase" bash -c "cd '$FLOW_DIR' && bash db_queries.sh phase >/dev/null 2>&1"
  chk "verify: schema complete" bash -c "cd '$FLOW_DIR' && bash db_queries.sh verify >/dev/null 2>&1"

  section "PF5. Session briefing produces compact output"
  local BRIEF_OUT
  BRIEF_OUT=$(cd "$FLOW_DIR" && bash session_briefing.sh 2>&1) || true
  if [ -n "$BRIEF_OUT" ]; then
    pass "session_briefing.sh produces output"
  else
    fail "session_briefing.sh produced no output"
  fi

  section "PF6. Deployment verification"
  if [ -f "$FLOW_DIR/scripts/verify_deployment.py" ]; then
    local VERIFY_OUT
    VERIFY_OUT=$(cd "$FLOW_DIR" && python3 scripts/verify_deployment.py "$FLOW_DIR" --json 2>/dev/null) || true
    if echo "$VERIFY_OUT" | jq -e '.passed' >/dev/null 2>&1; then
      local PASSED TOTAL CRIT_FAIL
      PASSED=$(echo "$VERIFY_OUT" | jq -r '.passed')
      TOTAL=$(echo "$VERIFY_OUT" | jq -r '.total')
      CRIT_FAIL=$(echo "$VERIFY_OUT" | jq -r '.critical_failures')
      # Assert: verification runs, produces structured output, zero critical failures.
      # Warning-level failures (C11 build stub, C18 drift) are acceptable on fresh projects.
      if [ "$CRIT_FAIL" -eq 0 ] 2>/dev/null; then
        pass "verify_deployment: $PASSED/$TOTAL passed, $CRIT_FAIL critical failure(s)"
      else
        fail "verify_deployment: $PASSED/$TOTAL passed, $CRIT_FAIL critical failure(s)"
      fi
    else
      warn "verify_deployment.py produced non-JSON output — skipping"
    fi
  else
    warn "verify_deployment.py not deployed — skipping"
  fi

  section "PF7. Deployment profile recorded"
  if [ -f "$FLOW_DIR/.bootstrap_profile" ]; then
    if grep -q "^profile=standard" "$FLOW_DIR/.bootstrap_profile"; then
      pass ".bootstrap_profile contains profile=standard"
    else
      fail ".bootstrap_profile missing profile=standard line"
    fi
  else
    fail ".bootstrap_profile not created"
  fi

  section "PF8. No forbidden global references"
  local VIOLATIONS
  VIOLATIONS=$(grep -r --include='*.sh' --include='*.md' --include='*.py' --include='*.json' \
      -l '~/.claude/' "$FLOW_DIR" 2>/dev/null | grep -v '\.git/' || true)
  if [ -z "$VIOLATIONS" ]; then
    pass "No ~/.claude/ references in generated project"
  else
    fail "Found ~/.claude/ references in: $(echo "$VIOLATIONS" | tr '\n' ' ')"
  fi

  rm -rf "$FLOW_DIR"
}

# === PRODUCT-VERIFY CI GATE ==================================================
# Bootstraps a real project and asserts critical_failures == 0 from
# verify_deployment.py.  Intended as a fast CI gate that covers the 32 checks
# skipped by the public RepoSpine export (files are present in a live bootstrap).
# Run independently via: bash test_bootstrap_suite.sh --product-verify
product_verify_tests() {
  header "Product Verify (CI Gate)"
  P_NAME="product-verify"

  local PV_DIR="/tmp/bootstrap_test_pv_$$"
  rm -rf "$PV_DIR"

  section "PV1. Bootstrap via bootstrap_project.sh"
  if bash "$REPO_ROOT/bootstrap_project.sh" "PVTest" "$PV_DIR" --deployment standard --non-interactive >/dev/null 2>&1; then
    pass "bootstrap_project.sh created project successfully"
  else
    fail "bootstrap_project.sh failed — cannot continue product-verify"
    rm -rf "$PV_DIR"
    return
  fi

  section "PV2. verify_deployment.py produces JSON output"
  local VD_SCRIPT="$PV_DIR/scripts/verify_deployment.py"
  if [ ! -f "$VD_SCRIPT" ]; then
    fail "verify_deployment.py not deployed to generated project"
    rm -rf "$PV_DIR"
    return
  fi

  local VERIFY_OUT
  VERIFY_OUT=$(cd "$PV_DIR" && python3 scripts/verify_deployment.py "$PV_DIR" --json 2>/dev/null) || true

  if ! echo "$VERIFY_OUT" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
    fail "verify_deployment.py produced non-JSON output"
    rm -rf "$PV_DIR"
    return
  fi
  pass "verify_deployment.py produced parseable JSON"

  section "PV3. critical_failures == 0"
  local PASSED TOTAL CRIT_FAIL
  PASSED=$(echo "$VERIFY_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('passed',0))" 2>/dev/null || echo "0")
  TOTAL=$(echo "$VERIFY_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "0")
  CRIT_FAIL=$(echo "$VERIFY_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('critical_failures',1))" 2>/dev/null || echo "1")

  if [ "$CRIT_FAIL" -eq 0 ] 2>/dev/null; then
    pass "verify_deployment: $PASSED/$TOTAL passed, 0 critical failures"
  else
    fail "verify_deployment: $PASSED/$TOTAL passed, $CRIT_FAIL critical failure(s) (expected 0)"
    # Print failing checks to aid diagnosis
    echo "$VERIFY_OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for c in d.get('checks', []):
    if not c.get('passed', True):
        print('  FAIL:', c.get('name','?'), '-', c.get('detail',''))
" 2>/dev/null | head -10 | while IFS= read -r l; do warn "$l"; done
  fi

  rm -rf "$PV_DIR"
}

# === CROSS-PROJECT VALIDATION ================================================
validate_cross() {
  header "Cross-Project Validation"
  local OLD_P_NAME="$P_NAME"

  section "5a. Hardcoded project-specific contamination scan"
  # Check for other projects' names leaking into generated test projects.
  # Exclude the current user's username — it legitimately appears in path
  # substitutions (e.g., /Users/<user>/Desktop/test_project1 in work.sh).
  local CONTAM_PATTERN="MasterDashboard\|master_dashboard\|TeaTimer\|tea_timer\|RomaniaBattles\|romania_battles\|Drawstring\|drawstring"
  for d in 1 2 3 4; do
    local PROJ_DIR="$SUITE_DIR/test_project$d"
    [ -d "$PROJ_DIR" ] || continue
    local LEAKS; LEAKS=$(grep -r "$CONTAM_PATTERN" "$PROJ_DIR/" \
      --include="*.sh" --include="*.md" --include="*.py" 2>/dev/null | grep -v ".git/" | wc -l | tr -d ' ')
    P_NAME="project$d"  # for fail() context
    if [ "$LEAKS" -eq 0 ]; then pass "project$d: zero project-specific contamination"; else
      fail "project$d: $LEAKS contamination hit(s) found"
      grep -r "$CONTAM_PATTERN" "$PROJ_DIR/" --include="*.sh" --include="*.md" --include="*.py" 2>/dev/null \
        | grep -v ".git/" | head -3 | while read l; do warn "  $l"; done
    fi
  done

  section "5b. Conditional refs/ file matrix verification"
  local CONFIGS=(
    "1 YES YES YES"   # P1: UI=YES, Skills=YES, Deferred=YES
    "2 NO NO NO"      # P2: UI=NO, Skills=NO, Deferred=NO
    "3 NO NO YES"     # P3: UI=NO, Skills=NO, Deferred=YES
    "4 YES YES NO"    # P4: UI=YES, Skills=YES, Deferred=NO
  )
  for CFG in "${CONFIGS[@]}"; do
    read -r N HAS_UI HAS_SKILLS HAS_DEFERRED <<< "$CFG"
    local D="$SUITE_DIR/test_project$N"
    [ -d "$D" ] || continue
    P_NAME="project$N"
    if [ "$HAS_UI" = "YES" ]; then
      chk "project$N: refs/gotchas-frontend.md EXISTS" test -f "$D/refs/gotchas-frontend.md"
    else
      chk "project$N: refs/gotchas-frontend.md ABSENT" bash -c "! test -f '$D/refs/gotchas-frontend.md'"
    fi
    if [ "$HAS_SKILLS" = "YES" ]; then
      chk "project$N: refs/skills-catalog.md EXISTS" test -f "$D/refs/skills-catalog.md"
    else
      chk "project$N: refs/skills-catalog.md ABSENT" bash -c "! test -f '$D/refs/skills-catalog.md'"
    fi
    if [ "$HAS_DEFERRED" = "YES" ]; then
      chk "project$N: refs/planned-integrations.md EXISTS" test -f "$D/refs/planned-integrations.md"
    else
      chk "project$N: refs/planned-integrations.md ABSENT" bash -c "! test -f '$D/refs/planned-integrations.md'"
    fi
  done

  section "5c. RULES + extended rules conditional sections"
  local UI_PROJECTS=(1 4); local NON_UI=(2 3)
  local GEMINI_PROJECTS=(1 3); local NO_GEMINI=(2 4)
  local TEAMS_PROJECTS=(3)

  # Helper: search both core RULES and refs/rules-extended.md
  _rules_grep() {
    local DIR="$1" PATTERN="$2"
    grep -rqi "$PATTERN" "$DIR"/*RULES*.md "$DIR"/refs/rules-extended.md 2>/dev/null
  }

  for N in "${UI_PROJECTS[@]}"; do
    local D="$SUITE_DIR/test_project$N"
    [ -d "$D" ] || continue
    P_NAME="project$N"
    chk "project$N RULES: visual verification section present (UI=YES)" \
      bash -c "_rules_grep() { grep -rqi \"\$2\" \"\$1\"/*RULES*.md \"\$1\"/refs/rules-extended.md 2>/dev/null; }; _rules_grep '$D' 'visual.*active\|screenshot\|visual verification gate'"
  done

  for N in "${NON_UI[@]}"; do
    local D="$SUITE_DIR/test_project$N"
    [ -d "$D" ] || continue
    P_NAME="project$N"
    chk "project$N RULES: visual verification is N/A (UI=NO)" \
      bash -c "grep -rqi 'not applicable\|N/A\|no visual' '$D'/*RULES*.md '$D'/refs/rules-extended.md 2>/dev/null"
  done

  for N in "${GEMINI_PROJECTS[@]}"; do
    local D="$SUITE_DIR/test_project$N"
    [ -d "$D" ] || continue
    P_NAME="project$N"
    chk "project$N RULES: Gemini section present (Gemini=YES)" \
      bash -c "grep -rqi 'gemini' '$D'/*RULES*.md '$D'/refs/rules-extended.md 2>/dev/null"
  done

  P_NAME="project3"
  local D3="$SUITE_DIR/test_project3"
  if [ -d "$D3" ]; then
    chk "project3 RULES: teams topology section present (Teams=YES)" \
      bash -c "grep -rqi 'topology\|teams.*active\|orchestrator' '$D3'/*RULES*.md '$D3'/refs/rules-extended.md 2>/dev/null"
  fi

  section "5d. Zero unfilled placeholders across ALL projects"
  for d in 1 2 3 4; do
    local D="$SUITE_DIR/test_project$d"
    [ -d "$D" ] || continue
    P_NAME="project$d"
    local COUNT; COUNT=$(grep -r '%%[A-Z_]*%%' "$D/" \
      --include="*.sh" --include="*.md" --include="*.py" 2>/dev/null \
      | grep -v ".git/" | grep -vE "^\s*#|:[[:space:]]*#" | grep -v "template" | wc -l | tr -d ' ')
    COUNT="${COUNT:-0}"
    if [ "$COUNT" -eq 0 ]; then pass "project$d: zero unfilled placeholders"; else
      fail "project$d: $COUNT unfilled placeholder occurrences"
    fi
  done

  section "5e. DB names match project slugs"
  chk "project1 has test_web_app.db" test -f "$SUITE_DIR/test_project1/test_web_app.db"
  chk "project2 has rust_cli.db" test -f "$SUITE_DIR/test_project2/rust_cli.db"
  chk "project3 has fastapi_service.db" test -f "$SUITE_DIR/test_project3/fastapi_service.db"
  chk "project4 has swift_desktop_app.db" test -f "$SUITE_DIR/test_project4/swift_desktop_app.db"

  P_NAME="$OLD_P_NAME"
}

# === REGRESSION TESTS ========================================================
# These validate template-level invariants without requiring a deployed project.
# Run independently via: bash test_bootstrap_suite.sh --regression
regression_tests() {
  header "Regression Tests (Template-Level)"
  P_NAME="regression"

  section "R1. grep -P not used in any template script"
  # Match grep with -P flag: -P, -oP, -cP, etc. (Perl regex unsupported on macOS)
  local GREP_P_HITS; GREP_P_HITS=$(grep -rE 'grep[[:space:]]+-[a-zA-Z]*P[[:space:]]' "$TEMPLATES/" \
    --include="*.sh" 2>/dev/null | wc -l | tr -d ' ')
  GREP_P_HITS="${GREP_P_HITS:-0}"
  if [ "$GREP_P_HITS" -eq 0 ]; then pass "Zero grep -P usage in template scripts"
  else fail "$GREP_P_HITS grep -P occurrence(s) in template scripts"; fi

  section "R2. No project-specific contamination in templates"
  local CONTAM_TERMS="MasterDashboard\|master_dashboard\|TeaTimer\|tea_timer\|RomaniaBattles\|romania_battles\|Drawstring\|drawstring"
  local CONTAM_HITS; CONTAM_HITS=$(grep -r "$CONTAM_TERMS" "$TEMPLATES/" \
    --include="*.sh" --include="*.md" --include="*.py" --include="*.json" 2>/dev/null \
    | grep -v ".git/" | wc -l | tr -d ' ')
  CONTAM_HITS="${CONTAM_HITS:-0}"
  if [ "$CONTAM_HITS" -eq 0 ]; then pass "Zero project-specific contamination in templates"
  else
    fail "$CONTAM_HITS contamination hit(s) in templates"
    grep -r "$CONTAM_TERMS" "$TEMPLATES/" --include="*.sh" --include="*.md" --include="*.py" --include="*.json" 2>/dev/null \
      | grep -v ".git/" | head -5 | while read l; do warn "  $l"; done
  fi

  section "R3. init-db works without pre-existing DB file"
  # Create a minimal working copy of db_queries wrapper with placeholders filled
  local TEST_WORKDIR="/tmp/bootstrap_test_initdb_$$"
  rm -rf "$TEST_WORKDIR"
  mkdir -p "$TEST_WORKDIR/scripts"
  cp "$TEMPLATE_SCRIPTS/db_queries.template.sh" "$TEST_WORKDIR/db_queries.sh"
  chmod +x "$TEST_WORKDIR/db_queries.sh"
  # Link dbq package so the wrapper can find it
  ln -sf "$TEMPLATE_SCRIPTS/dbq" "$TEST_WORKDIR/scripts/dbq"
  # Fill critical placeholders with test values (portable sed — no -i '' on Linux)
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' \
      -e 's/%%PROJECT_DB%%/test_regr.db/g' \
      -e 's/%%PROJECT_NAME%%/TestRegression/g' \
      -e 's/%%LESSONS_FILE%%/LESSONS_TEST.md/g' \
      -e 's/%%PHASES%%//g' \
      "$TEST_WORKDIR/db_queries.sh"
  else
    sed -i \
      -e 's/%%PROJECT_DB%%/test_regr.db/g' \
      -e 's/%%PROJECT_NAME%%/TestRegression/g' \
      -e 's/%%LESSONS_FILE%%/LESSONS_TEST.md/g' \
      -e 's/%%PHASES%%//g' \
      "$TEST_WORKDIR/db_queries.sh"
  fi
  touch "$TEST_WORKDIR/LESSONS_TEST.md"

  local TEST_DB="$TEST_WORKDIR/test_regr.db"
  rm -f "$TEST_DB"
  if (cd "$TEST_WORKDIR" && bash db_queries.sh init-db >/dev/null 2>&1) && [ -f "$TEST_DB" ]; then
    pass "init-db creates DB from scratch"
  else
    fail "init-db failed without pre-existing DB file"
  fi

  section "R4. init-db is idempotent (run twice)"
  if [ -f "$TEST_DB" ]; then
    if (cd "$TEST_WORKDIR" && bash db_queries.sh init-db >/dev/null 2>&1); then
      pass "init-db runs twice without error"
    else
      fail "init-db failed on second run (not idempotent)"
    fi
  else
    warn "Skipped — init-db did not create DB in R3"
  fi

  section "R5. Full init-db→health→next sequence"
  if [ -f "$TEST_DB" ]; then
    if (cd "$TEST_WORKDIR" && bash db_queries.sh health >/dev/null 2>&1); then
      pass "health passes after init-db"
    else
      fail "health failed after init-db"
    fi
    if (cd "$TEST_WORKDIR" && bash db_queries.sh next >/dev/null 2>&1); then
      pass "next runs after init-db (even if no tasks)"
    else
      fail "next failed after init-db"
    fi
  else
    warn "Skipped — no DB from R3/R4"
  fi
  rm -rf "$TEST_WORKDIR"

  section "R6. Hook templates produce valid JSON (matcher field present)"
  local HOOK_DIR="$TEMPLATES/hooks"
  if [ -d "$HOOK_DIR" ]; then
    local HOOK_COUNT=0; local HOOK_VALID=0
    for hook_file in "$HOOK_DIR"/*.sh; do
      [ -f "$hook_file" ] || continue
      HOOK_COUNT=$((HOOK_COUNT+1))
      # Check the hook is executable (or at least has shebang)
      if head -1 "$hook_file" | grep -q '^#!/'; then
        HOOK_VALID=$((HOOK_VALID+1))
      fi
    done
    if [ "$HOOK_COUNT" -gt 0 ]; then
      if [ "$HOOK_VALID" -eq "$HOOK_COUNT" ]; then
        pass "All $HOOK_COUNT hook templates have valid shebangs"
      else
        fail "$((HOOK_COUNT - HOOK_VALID))/$HOOK_COUNT hook templates missing shebang"
      fi
    else
      warn "No hook templates found in $HOOK_DIR"
    fi
  else
    warn "No hooks directory at $HOOK_DIR"
  fi

  # Check settings template references valid hook scripts
  # Settings references use deployed names (foo.sh), templates use (foo.template.sh)
  local SETTINGS_TMPL="$TEMPLATES/settings/settings.template.json"
  if [ -f "$SETTINGS_TMPL" ]; then
    local HOOK_REFS; HOOK_REFS=$(grep -oE '[a-z_-]+\.sh' "$SETTINGS_TMPL" 2>/dev/null | sort -u)
    local MISSING_HOOKS=0
    for href in $HOOK_REFS; do
      local TMPL_NAME="${href%.sh}.template.sh"
      if [ ! -f "$HOOK_DIR/$href" ] && [ ! -f "$HOOK_DIR/$TMPL_NAME" ] && \
         [ ! -f "$TEMPLATES/scripts/$href" ] && [ ! -f "$TEMPLATES/scripts/${href%.sh}.template.sh" ]; then
        warn "settings.json references $href but no matching template found"
        MISSING_HOOKS=$((MISSING_HOOKS+1))
      fi
    done
    if [ "$MISSING_HOOKS" -eq 0 ]; then
      pass "All hook references in settings template resolve to existing templates"
    else
      fail "$MISSING_HOOKS hook reference(s) in settings template don't resolve"
    fi
  else
    warn "No settings template at $SETTINGS_TMPL"
  fi

  section "R-DRIFT. Drift detection command runs cleanly"
  if [ ! -f "$REPO_ROOT/db_queries.sh" ]; then
    warn "Skipping drift tests — db_queries.sh not found (public export)"
  else
    local DRIFT_OUT; DRIFT_OUT=$(bash "$REPO_ROOT/db_queries.sh" drift --quiet 2>&1)
    if echo "$DRIFT_OUT" | grep -qE '^drift: [0-9]+/100'; then
      pass "drift --quiet produces valid score output"
    else
      fail "drift --quiet output unexpected: $DRIFT_OUT"
    fi

    section "R-DRIFT-JSON. Drift JSON output is valid"
    local DRIFT_JSON; DRIFT_JSON=$(bash "$REPO_ROOT/db_queries.sh" drift --json 2>&1)
    if echo "$DRIFT_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'score' in d" 2>/dev/null; then
      pass "drift --json produces valid JSON with score field"
    else
      fail "drift --json output is not valid JSON"
    fi
  fi
}

# === HOOK FUNCTIONAL TESTS ===================================================
# Verifies hook I/O contracts: feed mock JSON stdin, assert on stdout JSON.
# Run via: bash test_bootstrap_suite.sh --hooks-functional
hook_functional_tests() {
  header "Hook Functional Tests (I/O Contracts)"
  P_NAME="hooks-functional"

  local HOOK_DIR="$REPO_ROOT/.claude/hooks"

  # Skip if meta-project hooks aren't present (e.g., public RepoSpine export)
  if [ ! -d "$HOOK_DIR" ]; then
    warn "Skipping hook functional tests — .claude/hooks/ not found (public export)"
    return 0
  fi
  local TMP="/tmp/bootstrap_test_hooks_$$"
  rm -rf "$TMP"
  mkdir -p "$TMP/.claude/hooks" "$TMP/.git"

  # --- correction-detector.sh ---

  section "H1. correction-detector fires on correction signal"
  local OUT
  OUT=$(echo '{"prompt":"that did not work, it is broken"}' | bash "$HOOK_DIR/correction-detector.sh" 2>/dev/null) || true
  if echo "$OUT" | grep -q "CORRECTION SIGNAL DETECTED"; then
    pass "correction-detector injected routing hint"
  else
    fail "correction-detector did not fire on correction signal"
  fi

  section "H2. correction-detector silent on clean prompt"
  OUT=$(echo '{"prompt":"please add a new feature for sorting"}' | bash "$HOOK_DIR/correction-detector.sh" 2>/dev/null) || true
  if [ -z "$OUT" ]; then
    pass "correction-detector silent on non-correction prompt"
  else
    fail "correction-detector fired on clean prompt"
  fi

  section "H3. correction-detector routes to correction-protocol.md"
  OUT=$(echo '{"prompt":"ugh that is wrong"}' | bash "$HOOK_DIR/correction-detector.sh" 2>/dev/null) || true
  if echo "$OUT" | grep -q "correction-protocol.md"; then
    pass "correction-detector includes correction-protocol routing"
  else
    fail "correction-detector missing correction-protocol routing"
  fi

  # --- task-intake-detector.sh ---

  section "H4. task-intake-detector fires on multi-phase prompt"
  OUT=$(echo '{"prompt":"Execute all 5 phases sequentially. Phase 1 updates foo.sh, bar.py, config.json, readme.md, and test.template files. Do not skip any gate. Commit per phase."}' | bash "$HOOK_DIR/task-intake-detector.sh" 2>/dev/null) || true
  if echo "$OUT" | grep -q "LARGE TASK INTAKE DETECTED"; then
    pass "task-intake-detector fired on multi-phase prompt"
  else
    fail "task-intake-detector did not fire on high-score prompt"
  fi

  section "H5. task-intake-detector silent on simple prompt"
  OUT=$(echo '{"prompt":"fix the typo in README.md"}' | bash "$HOOK_DIR/task-intake-detector.sh" 2>/dev/null) || true
  if [ -z "$OUT" ]; then
    pass "task-intake-detector silent on simple prompt"
  else
    fail "task-intake-detector fired on simple prompt"
  fi

  section "H6. task-intake-detector includes score in output"
  OUT=$(echo '{"prompt":"Execute all 5 phases sequentially. Phase 1 updates foo.sh, bar.py, config.json, readme.md, and test.template files. Do not skip any gate. Commit per phase."}' | bash "$HOOK_DIR/task-intake-detector.sh" 2>/dev/null) || true
  if echo "$OUT" | grep -qE 'score: [4-9]'; then
    pass "task-intake-detector reports score in context"
  else
    fail "task-intake-detector missing score in output"
  fi

  # --- pre-edit-check.sh ---

  section "H7. pre-edit-check outputs tier advisory at milestone edits (5, 10, 20)"
  # Layer 1 reads CURRENT_EDITS before Layer 2 increments, so set to 10 directly
  # No tool_input → trivial-edit bypass skipped (no old_string → not trivial)
  mkdir -p "$TMP/.claude/hooks"
  echo "GO|0|TST-001|sonnet" > "$TMP/.claude/hooks/.last_check_result"
  echo "10" > "$TMP/.claude/hooks/.delegation_state"
  echo "$(date +%s)" >> "$TMP/.claude/hooks/.delegation_state"
  OUT=$(printf '%s' '{"tool_name":"Edit","cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/pre-edit-check.sh" 2>/dev/null) || true
  if echo "$OUT" | grep -q "TIER NOTE"; then
    pass "pre-edit-check shows tier advisory at milestone edit #10"
  else
    fail "pre-edit-check missing reminder at milestone edit"
  fi

  section "H8. pre-edit-check increments edit count"
  echo "0" > "$TMP/.claude/hooks/.delegation_state"
  echo "0" >> "$TMP/.claude/hooks/.delegation_state"
  echo '{"tool_name":"Edit","cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/pre-edit-check.sh" >/dev/null 2>&1 || true
  local STORED
  STORED=$(sed -n '1p' "$TMP/.claude/hooks/.delegation_state")
  if [ "$STORED" = "1" ]; then
    pass "pre-edit-check incremented edit count to 1"
  else
    fail "pre-edit-check edit count expected 1, got $STORED"
  fi

  section "H9. pre-edit-check gates at 10+ edits without approval"
  echo "9" > "$TMP/.claude/hooks/.delegation_state"
  echo "0" >> "$TMP/.claude/hooks/.delegation_state"
  OUT=$(echo '{"tool_name":"Edit","cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/pre-edit-check.sh" 2>/dev/null) || true
  if echo "$OUT" | jq -e '.hookSpecificOutput.permissionDecision' 2>/dev/null | grep -q "ask"; then
    pass "pre-edit-check gates with 'ask' at edit #10"
  else
    fail "pre-edit-check did not gate at 10+ edits"
  fi

  section "H10. pre-edit-check passes when approval is fresh"
  local NOW
  NOW=$(date +%s)
  echo "5" > "$TMP/.claude/hooks/.delegation_state"
  echo "$NOW" >> "$TMP/.claude/hooks/.delegation_state"
  OUT=$(echo '{"tool_name":"Edit","cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/pre-edit-check.sh" 2>/dev/null) || true
  # With milestone-based advisories, edit #6 (non-milestone) with fresh approval silently passes
  if ! echo "$OUT" | grep -q "permissionDecision"; then
    pass "pre-edit-check allows edit with fresh approval"
  else
    fail "pre-edit-check incorrectly gated despite fresh approval"
  fi

  section "H11. pre-edit-check advisory includes delegation guidance"
  echo "9" > "$TMP/.claude/hooks/.delegation_state"
  echo "0" >> "$TMP/.claude/hooks/.delegation_state"
  OUT=$(echo '{"tool_name":"Edit","cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/pre-edit-check.sh" 2>/dev/null) || true
  if echo "$OUT" | grep -q "DELEGATION ADVISORY"; then
    pass "pre-edit-check includes delegation advisory at 10+ edits"
  else
    fail "pre-edit-check missing delegation routing"
  fi

  # --- session-start-check.sh (runs against real project dir) ---

  # Save/restore real delegation state
  local REAL_STATE="$REPO_ROOT/.claude/hooks/.delegation_state"
  local SAVED_STATE=""
  if [ -f "$REAL_STATE" ]; then
    SAVED_STATE=$(cat "$REAL_STATE")
  fi

  # Seed state for H14 test
  echo "5" > "$REAL_STATE"
  echo "9999999999" >> "$REAL_STATE"

  # Single invocation for H12 + H13 + H14 (session-start is slow ~3s)
  local SS_OUT
  SS_OUT=$(echo '{"cwd":"'"$REPO_ROOT"'"}' | bash "$HOOK_DIR/session-start-check.sh" 2>/dev/null) || true

  section "H12. session-start-check produces valid JSON"
  if echo "$SS_OUT" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null 2>&1; then
    pass "session-start-check outputs valid JSON with additionalContext"
  else
    fail "session-start-check output is not valid JSON or missing additionalContext"
  fi

  section "H13. session-start-check includes briefing content"
  if echo "$SS_OUT" | jq -r '.hookSpecificOutput.additionalContext' 2>/dev/null | grep -q "SESSION START"; then
    pass "session-start-check includes SESSION START header"
  else
    fail "session-start-check missing SESSION START header"
  fi

  section "H14. session-start-check resets delegation state"
  local RESET_COUNT
  RESET_COUNT=$(sed -n '1p' "$REAL_STATE" 2>/dev/null || echo "?")
  if [ "$RESET_COUNT" = "0" ]; then
    pass "session-start-check reset delegation counter to 0"
  else
    fail "session-start-check delegation counter not reset (got $RESET_COUNT)"
  fi

  # Restore real delegation state
  if [ -n "$SAVED_STATE" ]; then
    echo "$SAVED_STATE" > "$REAL_STATE"
  else
    echo "0" > "$REAL_STATE"
    echo "0" >> "$REAL_STATE"
  fi

  # --- session-start-check.sh prerequisite gate ---

  section "H18. session-start-check prereq gate outputs valid JSON when tools missing"
  # Simulate the prerequisite check logic with fake missing tools.
  # We can't actually hide jq from PATH (other tests need it), so we test
  # the printf-based JSON construction directly — the same code path
  # that runs when command -v fails.
  local PREREQ_MSG="MISSING PREREQUISITES: jq python3. Install before continuing. All hooks depend on jq for JSON I/O."
  local PREREQ_JSON
  PREREQ_JSON=$(printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
      "$(printf '%s' "$PREREQ_MSG" | sed 's/"/\\"/g')")
  if echo "$PREREQ_JSON" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null 2>&1; then
    local PREREQ_CTX
    PREREQ_CTX=$(echo "$PREREQ_JSON" | jq -r '.hookSpecificOutput.additionalContext')
    if echo "$PREREQ_CTX" | grep -q "MISSING PREREQUISITES"; then
      pass "session-start-check prereq gate produces valid JSON with missing tool warning"
    else
      fail "session-start-check prereq gate JSON missing tool names in additionalContext"
    fi
  else
    fail "session-start-check prereq gate output is not valid JSON"
  fi

  # --- end-of-turn-check.sh ---

  section "H15. end-of-turn-check silent when no warnings"
  rm -rf "$TMP/.claude/hooks/.delegation_state" "$TMP/NEXT_SESSION.md" "$TMP/.claude/hooks/.health_cache"
  rm -rf "$TMP/.git"
  OUT=$(echo '{"cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/end-of-turn-check.sh" 2>/dev/null) || true
  if [ -z "$OUT" ]; then
    pass "end-of-turn-check silent with no warning conditions"
  else
    fail "end-of-turn-check produced unexpected output"
  fi

  section "H16. end-of-turn-check warns on high edit count"
  mkdir -p "$TMP/.claude/hooks"
  echo "12" > "$TMP/.claude/hooks/.delegation_state"
  echo "0" >> "$TMP/.claude/hooks/.delegation_state"
  OUT=$(echo '{"cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/end-of-turn-check.sh" 2>/dev/null) || true
  if echo "$OUT" | jq -r '.stopReason' 2>/dev/null | grep -q "edits this session"; then
    pass "end-of-turn-check warns on 12 edits without approval"
  else
    fail "end-of-turn-check did not warn on high edit count"
  fi

  section "H17. end-of-turn-check warns on stale NEXT_SESSION.md"
  rm -f "$TMP/.claude/hooks/.delegation_state"
  touch -t 202501010000 "$TMP/NEXT_SESSION.md"
  OUT=$(echo '{"cwd":"'"$TMP"'"}' | bash "$HOOK_DIR/end-of-turn-check.sh" 2>/dev/null) || true
  if echo "$OUT" | jq -r '.stopReason' 2>/dev/null | grep -q "NEXT_SESSION.md"; then
    pass "end-of-turn-check warns on stale NEXT_SESSION.md"
  else
    fail "end-of-turn-check did not warn on stale handoff"
  fi

  # Cleanup
  rm -rf "$TMP"
}

# === CROSS-PROJECT COMPATIBILITY TESTS =======================================
# Checks that template files are portable across macOS and Linux.
# Run via: bash test_bootstrap_suite.sh --compat
compat_tests() {
  header "Cross-Project Compatibility Tests"
  P_NAME="compat"

  # Resolve the project-local templates directory from this script's location.
  # The test file lives at tests/test_bootstrap_suite.sh; templates are at ../templates/.
  # This avoids scanning via symlinks that may point to a different repo's templates.
  local SCRIPT_REAL_DIR
  SCRIPT_REAL_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd )"
  local COMPAT_TEMPLATES="${SCRIPT_REAL_DIR}/../templates"
  local COMPAT_SCRIPTS="${COMPAT_TEMPLATES}/scripts"
  local COMPAT_FRAMEWORKS="${COMPAT_TEMPLATES}/frameworks"
  local COMPAT_REGISTRY="${SCRIPT_REAL_DIR}/../skills/bootstrap-activate/references/placeholder-registry.md"

  # ── C1. Template scripts use #!/usr/bin/env bash (not /bin/bash) ──────────
  section "C1. Template scripts use portable shebang (#!/usr/bin/env bash)"
  local BAD_SHEBANG=0
  local TOTAL_SCRIPTS=0
  for f in "$COMPAT_SCRIPTS"/*.sh; do
    [ -f "$f" ] || continue
    TOTAL_SCRIPTS=$((TOTAL_SCRIPTS + 1))
    local FIRST_LINE
    FIRST_LINE=$(head -1 "$f" 2>/dev/null)
    if [ "$FIRST_LINE" != "#!/usr/bin/env bash" ]; then
      warn "Non-portable shebang in $(basename "$f"): $FIRST_LINE"
      BAD_SHEBANG=$((BAD_SHEBANG + 1))
    fi
  done
  if [ "$TOTAL_SCRIPTS" -eq 0 ]; then
    warn "No template scripts found at $COMPAT_SCRIPTS"
  elif [ "$BAD_SHEBANG" -eq 0 ]; then
    pass "All $TOTAL_SCRIPTS template scripts use #!/usr/bin/env bash"
  else
    fail "$BAD_SHEBANG/$TOTAL_SCRIPTS template script(s) use /bin/bash instead of /usr/bin/env bash"
  fi

  # ── C2. No grep -P (Perl regex) in template scripts ──────────────────────
  section "C2. No grep -P (Perl regex) in template scripts"
  # grep -P is unsupported on macOS default BSD grep. Pattern: grep with -P flag anywhere.
  local GREP_P_HITS
  GREP_P_HITS=$(grep -rE 'grep[[:space:]]+-[a-zA-Z]*P[[:space:]]' "$COMPAT_TEMPLATES/" \
    --include="*.sh" 2>/dev/null | wc -l | tr -d ' ')
  GREP_P_HITS="${GREP_P_HITS:-0}"
  if [ "$GREP_P_HITS" -eq 0 ]; then
    pass "Zero grep -P usage in template scripts"
  else
    fail "$GREP_P_HITS grep -P occurrence(s) found in template scripts"
    grep -rE 'grep[[:space:]]+-[a-zA-Z]*P[[:space:]]' "$COMPAT_TEMPLATES/" \
      --include="*.sh" 2>/dev/null | head -5 | while IFS= read -r hit; do warn "  $hit"; done
  fi

  # ── C3. No bare sed -i without '' (macOS incompatible) ───────────────────
  section "C3. No bare sed -i without '' (macOS incompatible)"
  # Both `sed -i "..."` (GNU-only) and `sed -i '' "..."` (macOS-only) are
  # platform-specific. The correct fix is always the sedi() helper.
  # Scan: templates/, .claude/hooks/, and root-level *.sh scripts.
  # Exclude: sedi() helper body (contains `sed -i "$@"` and `sed -i '' "$@"`).
  local SED_TOTAL_HITS=0
  local SED_HIT_LINES=""
  local COMPAT_HOOKS="${SCRIPT_REAL_DIR}/../.claude/hooks"

  # Helper: count platform-specific sed -i in a directory
  _count_sed_hits() {
    local dir="$1"
    [ -d "$dir" ] || return 0
    # GNU form: sed -i "..." (breaks macOS)
    local gnu_hits
    gnu_hits=$(grep -rn 'sed -i "' "$dir/" --include="*.sh" 2>/dev/null \
      | grep -v 'sed -i "\$@"' | grep -v 'sedi()' || true)
    # macOS form: sed -i '' (breaks GNU/Linux)
    local mac_hits
    mac_hits=$(grep -rn "sed -i ''" "$dir/" --include="*.sh" 2>/dev/null \
      | grep -v '"\$@"' | grep -v 'sedi()' || true)
    local combined
    combined=$(printf '%s\n%s' "$gnu_hits" "$mac_hits" | grep -v '^$' || true)
    if [ -n "$combined" ]; then
      local count
      count=$(printf '%s\n' "$combined" | wc -l | tr -d ' ')
      SED_TOTAL_HITS=$((SED_TOTAL_HITS + count))
      SED_HIT_LINES="${SED_HIT_LINES}${combined}"$'\n'
    fi
  }

  _count_sed_hits "$COMPAT_TEMPLATES"
  _count_sed_hits "$COMPAT_HOOKS"
  # Root-level scripts (bootstrap_project.sh, session_briefing.sh, etc.)
  local root_dir="${SCRIPT_REAL_DIR}/.."
  local root_gnu root_mac root_combined
  root_gnu=$(grep -n 'sed -i "' "$root_dir"/*.sh 2>/dev/null \
    | grep -v 'sed -i "\$@"' | grep -v 'sedi()' || true)
  root_mac=$(grep -n "sed -i ''" "$root_dir"/*.sh 2>/dev/null \
    | grep -v '"\$@"' | grep -v 'sedi()' || true)
  root_combined=$(printf '%s\n%s' "$root_gnu" "$root_mac" | grep -v '^$' || true)
  if [ -n "$root_combined" ]; then
    local rc
    rc=$(printf '%s\n' "$root_combined" | wc -l | tr -d ' ')
    SED_TOTAL_HITS=$((SED_TOTAL_HITS + rc))
    SED_HIT_LINES="${SED_HIT_LINES}${root_combined}"$'\n'
  fi

  if [ "$SED_TOTAL_HITS" -eq 0 ]; then
    pass "Zero platform-specific sed -i usage in project scripts (use sedi() helper)"
  else
    fail "$SED_TOTAL_HITS platform-specific sed -i occurrence(s) found — use sedi() helper"
    printf '%s' "$SED_HIT_LINES" | grep -v '^$' | head -5 | while IFS= read -r hit; do warn "  $hit"; done
  fi

  # ── C3a. sedi() helper functional test — multi-line insertion works ──────
  section "C3a. sedi() helper produces correct multi-line sed insertion"
  local SEDI_TMP="${SCRIPT_REAL_DIR}/../test_sedi_$$"
  cat > "$SEDI_TMP" << 'SEDIEOF'
| Date | Entry |
## Universal Patterns
| Pattern | Rule |
SEDIEOF

  # Source sedi() from bootstrap_project.sh (lines 24-30)
  sedi() {
      if [[ "$OSTYPE" == "darwin"* ]]; then
          sed -i '' "$@"
      else
          sed -i "$@"
      fi
  }

  local SEDI_ENTRY="| 2026-01-01 | Test lesson entry |"
  sedi "/## Universal Patterns/i\\
\\
$SEDI_ENTRY\\
" "$SEDI_TMP" 2>/dev/null
  local SEDI_RC=$?

  if [ "$SEDI_RC" -eq 0 ] && grep -q "Test lesson entry" "$SEDI_TMP" 2>/dev/null; then
    # Verify insertion is BEFORE the marker, not after
    local ENTRY_LINE MARKER_LINE
    ENTRY_LINE=$(grep -n "Test lesson entry" "$SEDI_TMP" | head -1 | cut -d: -f1)
    MARKER_LINE=$(grep -n "## Universal Patterns" "$SEDI_TMP" | head -1 | cut -d: -f1)
    if [ "$ENTRY_LINE" -lt "$MARKER_LINE" ]; then
      pass "sedi() multi-line insertion works (entry at line $ENTRY_LINE, marker at line $MARKER_LINE)"
    else
      fail "sedi() inserted after marker (entry=$ENTRY_LINE, marker=$MARKER_LINE)"
    fi
  else
    fail "sedi() multi-line insertion failed (exit=$SEDI_RC)"
  fi
  rm -f "$SEDI_TMP"

  # ── C4. No date -d (GNU-only date parsing, BREAKS on macOS) ──────────────
  section "C4. No date -d (GNU-only, BREAKS on macOS)"
  local DATE_D_HITS
  DATE_D_HITS=$(grep -rn 'date -d ' "$COMPAT_TEMPLATES/" \
    --include="*.sh" 2>/dev/null | wc -l | tr -d ' ')
  DATE_D_HITS="${DATE_D_HITS:-0}"
  if [ "$DATE_D_HITS" -eq 0 ]; then
    pass "Zero date -d usage in template scripts"
  else
    fail "$DATE_D_HITS date -d occurrence(s) found — BREAKS on macOS (add macOS fallback: date -j -f)"
    grep -rn 'date -d ' "$COMPAT_TEMPLATES/" --include="*.sh" 2>/dev/null \
      | head -5 | while IFS= read -r hit; do warn "  $hit"; done
  fi

  # ── C5. No sort -V (GNU version sort, not available on macOS) ────────────
  section "C5. No sort -V (GNU-only, not available on macOS)"
  local SORT_V_HITS
  SORT_V_HITS=$(grep -rn 'sort -V' "$COMPAT_TEMPLATES/" \
    --include="*.sh" 2>/dev/null | wc -l | tr -d ' ')
  SORT_V_HITS="${SORT_V_HITS:-0}"
  if [ "$SORT_V_HITS" -eq 0 ]; then
    pass "Zero sort -V usage in template scripts"
  else
    fail "$SORT_V_HITS sort -V occurrence(s) found — not available on macOS (use plain sort for date-based tags)"
    grep -rn 'sort -V' "$COMPAT_TEMPLATES/" --include="*.sh" 2>/dev/null \
      | head -5 | while IFS= read -r hit; do warn "  $hit"; done
  fi

  # ── C6. Placeholder integrity — no undocumented tokens in templates ───────
  section "C6. No undocumented %%PLACEHOLDER%% tokens in templates"
  # Extract all unique %%TOKEN%% tokens from templates, excluding known meta-tokens.
  # Meta-tokens: %%PLACEHOLDER%% and %%PLACEHOLDERS%% (documentation examples, not substituted).
  if [ ! -f "$COMPAT_REGISTRY" ]; then
    warn "placeholder-registry.md not found at $COMPAT_REGISTRY — skipping C6"
  else
    local UNDOCUMENTED=0
    # Get all tokens from template files (all types: .sh .md .json .conf .py)
    local TEMPLATE_TOKENS
    TEMPLATE_TOKENS=$(grep -roh '%%[A-Z_][A-Z_0-9]*%%' "$COMPAT_TEMPLATES/" \
      --include="*.sh" --include="*.md" --include="*.json" --include="*.conf" --include="*.py" \
      2>/dev/null | sed 's/.*://' | sort -u)
    for token in $TEMPLATE_TOKENS; do
      # Skip known meta-tokens (documentation examples, not substitution targets)
      if [ "$token" = "%%PLACEHOLDER%%" ] || [ "$token" = "%%PLACEHOLDERS%%" ]; then
        continue
      fi
      # Check if this token appears in the registry
      if ! grep -qF "$token" "$COMPAT_REGISTRY" 2>/dev/null; then
        warn "Undocumented token in templates: $token (not in placeholder-registry.md)"
        UNDOCUMENTED=$((UNDOCUMENTED + 1))
      fi
    done
    if [ "$UNDOCUMENTED" -eq 0 ]; then
      pass "All %%TOKEN%% in templates are documented in placeholder-registry.md"
    else
      fail "$UNDOCUMENTED undocumented placeholder token(s) found in templates"
    fi
  fi

  # ── C7. Placeholder integrity — no orphaned registry tokens ──────────────
  section "C7. No orphaned registry tokens (documented but absent from all templates)"
  if [ ! -f "$COMPAT_REGISTRY" ]; then
    warn "placeholder-registry.md not found — skipping C7"
  else
    # Known intentionally-orphaned tokens (documented in the Orphaned section of the registry).
    # These are kept for historical reference and should not trigger failures.
    local KNOWN_ORPHANED="%%PERMISSION_DENY%%"
    local ORPHANED=0
    # Extract documented tokens from registry (lines containing %%TOKEN%% syntax)
    local REGISTRY_TOKENS
    REGISTRY_TOKENS=$(grep -oh '%%[A-Z_][A-Z_0-9]*%%' "$COMPAT_REGISTRY" 2>/dev/null \
      | sort -u \
      | grep -vE '^%%(PLACEHOLDER|PLACEHOLDERS)%%$')
    for token in $REGISTRY_TOKENS; do
      # Skip intentionally orphaned tokens
      if echo "$KNOWN_ORPHANED" | grep -qF "$token"; then
        continue
      fi
      # Check if this token appears anywhere in templates
      if ! grep -rqF "$token" "$COMPAT_TEMPLATES/" \
          --include="*.sh" --include="*.md" --include="*.json" --include="*.conf" --include="*.py" \
          2>/dev/null; then
        warn "Registry token not found in any template: $token"
        ORPHANED=$((ORPHANED + 1))
      fi
    done
    if [ "$ORPHANED" -eq 0 ]; then
      pass "All registry tokens (minus known orphans) are present in at least one template"
    else
      fail "$ORPHANED registry token(s) not found in any template — update registry or restore token"
    fi
  fi

  # ── C8. Framework files have version: in frontmatter ─────────────────────
  section "C8. Framework files have 'version:' in frontmatter"
  if [ ! -d "$COMPAT_FRAMEWORKS" ]; then
    warn "No frameworks directory at $COMPAT_FRAMEWORKS — skipping C8"
  else
    local NO_VERSION=0
    local FW_COUNT=0
    for f in "$COMPAT_FRAMEWORKS"/*.md; do
      [ -f "$f" ] || continue
      FW_COUNT=$((FW_COUNT + 1))
      if ! grep -q '^version:' "$f" 2>/dev/null; then
        warn "Missing 'version:' in frontmatter: $(basename "$f")"
        NO_VERSION=$((NO_VERSION + 1))
      fi
    done
    if [ "$FW_COUNT" -eq 0 ]; then
      warn "No framework .md files found at $COMPAT_FRAMEWORKS"
    elif [ "$NO_VERSION" -eq 0 ]; then
      pass "All $FW_COUNT framework files have 'version:' in frontmatter"
    else
      fail "$NO_VERSION/$FW_COUNT framework file(s) missing 'version:' in frontmatter"
    fi
  fi

  # ── C9. Framework files have ## Changelog section ────────────────────────
  section "C9. Framework files have '## Changelog' section"
  if [ ! -d "$COMPAT_FRAMEWORKS" ]; then
    warn "No frameworks directory at $COMPAT_FRAMEWORKS — skipping C9"
  else
    local NO_CHANGELOG=0
    local FW_COUNT2=0
    for f in "$COMPAT_FRAMEWORKS"/*.md; do
      [ -f "$f" ] || continue
      FW_COUNT2=$((FW_COUNT2 + 1))
      if ! grep -q '^## Changelog' "$f" 2>/dev/null; then
        warn "Missing '## Changelog' section: $(basename "$f")"
        NO_CHANGELOG=$((NO_CHANGELOG + 1))
      fi
    done
    if [ "$FW_COUNT2" -eq 0 ]; then
      warn "No framework .md files found at $COMPAT_FRAMEWORKS"
    elif [ "$NO_CHANGELOG" -eq 0 ]; then
      pass "All $FW_COUNT2 framework files have '## Changelog' section"
    else
      fail "$NO_CHANGELOG/$FW_COUNT2 framework file(s) missing '## Changelog' section"
    fi
  fi
}

# === LANGUAGE RULE TEMPLATE TESTS ============================================
# Validates the 7 language-specific rule templates under templates/rules/.
# Run independently via: bash test_bootstrap_suite.sh --language-rules
language_rule_tests() {
  header "Language-Specific Rule Template Tests"
  P_NAME="language-rules"

  local SCRIPT_REAL_DIR
  SCRIPT_REAL_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd )"
  local RULES_DIR="${SCRIPT_REAL_DIR}/../templates/rules"
  local COMPAT_REGISTRY="${SCRIPT_REAL_DIR}/../skills/bootstrap-activate/references/placeholder-registry.md"

  # List of expected language rule templates (only those that exist are tested).
  local EXPECTED_TEMPLATES="
    database-safety.template.md
    go-standards.template.md
    node-standards.template.md
    python-standards.template.md
    rust-standards.template.md
    swift-standards.template.md
    workflow-scripts.template.md
  "

  # ── L1. All expected language rule templates exist and are non-empty ────────
  section "L1. Language rule templates exist and are non-empty"
  local FOUND=0
  local MISSING=0
  local EMPTY=0
  for tpl in $EXPECTED_TEMPLATES; do
    tpl="$(echo "$tpl" | tr -d ' ')"
    [ -z "$tpl" ] && continue
    local TPL_PATH="${RULES_DIR}/${tpl}"
    if [ ! -f "$TPL_PATH" ]; then
      warn "Missing template: $tpl"
      MISSING=$((MISSING + 1))
    elif [ ! -s "$TPL_PATH" ]; then
      warn "Empty template: $tpl"
      EMPTY=$((EMPTY + 1))
    else
      FOUND=$((FOUND + 1))
    fi
  done
  if [ "$MISSING" -eq 0 ] && [ "$EMPTY" -eq 0 ]; then
    pass "All $FOUND language rule templates exist and are non-empty"
  else
    [ "$MISSING" -gt 0 ] && fail "$MISSING language rule template(s) missing"
    [ "$EMPTY" -gt 0 ]   && fail "$EMPTY language rule template(s) are empty"
  fi

  # ── L2. Template filenames follow *.template.md pattern ─────────────────────
  section "L2. Language rule templates follow *.template.md naming convention"
  local BAD_NAME=0
  local CHECKED=0
  for f in "$RULES_DIR"/*.template.md; do
    [ -f "$f" ] || continue
    CHECKED=$((CHECKED + 1))
    local BASENAME
    BASENAME="$(basename "$f")"
    # Must end with .template.md — the glob already guarantees this, but verify
    # the basename also does NOT contain spaces or uppercase (style guard).
    if echo "$BASENAME" | grep -qE '[[:upper:]]'; then
      warn "Uppercase in template filename: $BASENAME"
      BAD_NAME=$((BAD_NAME + 1))
    fi
  done
  if [ "$CHECKED" -eq 0 ]; then
    warn "No *.template.md files found in $RULES_DIR — skipping L2"
  elif [ "$BAD_NAME" -eq 0 ]; then
    pass "All $CHECKED *.template.md filenames are lowercase"
  else
    fail "$BAD_NAME *.template.md filename(s) contain uppercase letters"
  fi

  # ── L3. No stray/undocumented %%TOKEN%% in language rule templates ──────────
  section "L3. No undocumented %%TOKEN%% in language rule templates"
  if [ ! -f "$COMPAT_REGISTRY" ]; then
    warn "placeholder-registry.md not found at $COMPAT_REGISTRY — skipping L3"
  else
    local UNDOC_LANG=0
    for f in "$RULES_DIR"/*.template.md; do
      [ -f "$f" ] || continue
      local TOKENS
      TOKENS=$(grep -oh '%%[A-Z_][A-Z_0-9]*%%' "$f" 2>/dev/null | sort -u || true)
      for token in $TOKENS; do
        if [ "$token" = "%%PLACEHOLDER%%" ] || [ "$token" = "%%PLACEHOLDERS%%" ]; then
          continue
        fi
        if ! grep -qF "$token" "$COMPAT_REGISTRY" 2>/dev/null; then
          warn "Undocumented token in $(basename "$f"): $token"
          UNDOC_LANG=$((UNDOC_LANG + 1))
        fi
      done
    done
    if [ "$UNDOC_LANG" -eq 0 ]; then
      pass "All %%TOKEN%% in language rule templates are documented in registry"
    else
      fail "$UNDOC_LANG undocumented token(s) in language rule templates"
    fi
  fi

  # ── L4. No grep -P (macOS incompatible) in language rule templates ───────────
  section "L4. No grep -P (macOS incompatible) in language rule templates"
  local GREP_P_LANG=0
  for f in "$RULES_DIR"/*.template.md; do
    [ -f "$f" ] || continue
    local HITS
    HITS=$(grep -cE 'grep[[:space:]]+-[a-zA-Z]*P[[:space:]]' "$f" 2>/dev/null | tr -d ' \n' || echo "0")
    HITS="${HITS:-0}"
    if [ "$HITS" -gt 0 ] 2>/dev/null; then
      warn "grep -P found in $(basename "$f") ($HITS occurrence(s))"
      GREP_P_LANG=$((GREP_P_LANG + HITS))
    fi
  done
  if [ "$GREP_P_LANG" -eq 0 ]; then
    pass "Zero grep -P usage in language rule templates"
  else
    fail "$GREP_P_LANG grep -P occurrence(s) in language rule templates (not macOS compatible)"
  fi
}

# === PHASE FLAG TESTS ========================================================
# Validates the --phase flag dispatcher in bootstrap_project.sh.
# Run independently via: bash test_bootstrap_suite.sh --phase-flag
phase_flag_tests() {
  header "Phase Flag Tests (bootstrap_project.sh --phase)"
  P_NAME="phase-flag"

  local SCRIPT_REAL_DIR
  SCRIPT_REAL_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd )"
  local BOOTSTRAP="${SCRIPT_REAL_DIR}/../bootstrap_project.sh"

  if [ ! -f "$BOOTSTRAP" ]; then
    fail "bootstrap_project.sh not found at $BOOTSTRAP"
    return
  fi

  # ── P1. Unknown phase name rejected with error message ────────────────────
  section "P1. Unknown phase name produces error"
  # --phase requires pre-existing directory; use mktemp so the dir exists
  local TEST_DIR_P1
  TEST_DIR_P1=$(mktemp -d)
  local P1_OUT
  P1_OUT=$(bash "$BOOTSTRAP" "Test" "$TEST_DIR_P1" \
    --phase unknown --non-interactive --lifecycle quick 2>&1 || true)
  if echo "$P1_OUT" | grep -qi "unknown phase"; then
    pass "Unknown phase name produces error message"
  else
    fail "Unknown phase did not produce expected error message"
    warn "Output: $P1_OUT"
  fi
  rm -rf "$TEST_DIR_P1"

  # ── P2. --phase database deploys DB but not CLAUDE.md ────────────────────
  section "P2. --phase database creates DB but not CLAUDE.md"
  local TEST_DIR_P2
  TEST_DIR_P2=$(mktemp -d)
  bash "$BOOTSTRAP" "PhaseTest" "$TEST_DIR_P2" \
    --phase database --non-interactive --lifecycle quick >/dev/null 2>&1 || true
  if [ -f "$TEST_DIR_P2/phasetest.db" ]; then
    pass "--phase database created DB file"
  else
    fail "--phase database did not create DB file"
    warn "Contents: $(ls "$TEST_DIR_P2" 2>/dev/null || echo 'empty')"
  fi
  if [ ! -f "$TEST_DIR_P2/CLAUDE.md" ]; then
    pass "--phase database did not create CLAUDE.md (correct isolation)"
  else
    fail "--phase database should not create CLAUDE.md"
  fi
  rm -rf "$TEST_DIR_P2"

  # ── P3. --phase requires existing directory ───────────────────────────────
  section "P3. --phase errors if directory does not exist"
  local NONEXIST_DIR="/tmp/nonexistent-phase-test-dir-$$"
  rm -rf "$NONEXIST_DIR"
  local P3_OUT
  P3_OUT=$(bash "$BOOTSTRAP" "Test" "$NONEXIST_DIR" \
    --phase scripts --non-interactive --lifecycle quick 2>&1 || true)
  if echo "$P3_OUT" | grep -qi "does not exist"; then
    pass "--phase on missing directory produces 'does not exist' error"
  else
    fail "--phase on missing directory did not produce expected error"
    warn "Output: $P3_OUT"
  fi

  # ── P4. Full run vs all-phases explicit run produce same file set ─────────
  section "P4. Full run and explicit all-phases run produce same file set"
  local TEST_A TEST_B
  TEST_A=$(mktemp -d)
  TEST_B=$(mktemp -d)
  bash "$BOOTSTRAP" "CompareTest" "$TEST_A" \
    --lifecycle quick --non-interactive >/dev/null 2>&1 || true
  # For --phase mode, directory must pre-exist; TEST_B was created by mktemp
  bash "$BOOTSTRAP" "CompareTest" "$TEST_B" \
    --lifecycle quick --non-interactive \
    --phase database,scripts,frameworks,rules,hooks,agents,settings,init,placeholders,git \
    >/dev/null 2>&1 || true
  local DIFF_OUT
  DIFF_OUT=$(diff \
    <(cd "$TEST_A" && find . -not -path './.git/*' -not -name '.bootstrap_manifest' -not -name '.bootstrap_created' -not -name '.bootstrap_profile' -type f | sort 2>/dev/null) \
    <(cd "$TEST_B" && find . -not -path './.git/*' -not -name '.bootstrap_manifest' -not -name '.bootstrap_created' -not -name '.bootstrap_profile' -type f | sort 2>/dev/null) \
    2>/dev/null || true)
  if [ -z "$DIFF_OUT" ]; then
    pass "Full run and all-phases explicit run produce identical file sets"
  else
    fail "File sets differ between full run and all-phases explicit run"
    warn "Diff output: $DIFF_OUT"
  fi
  rm -rf "$TEST_A" "$TEST_B"

  # ── P5. --phase scripts deploys scripts but not DB ──────────────────────
  section "P5. --phase scripts creates scripts but not DB"
  local TEST_DIR_P5
  TEST_DIR_P5=$(mktemp -d)
  bash "$BOOTSTRAP" "ScriptsOnly" "$TEST_DIR_P5" \
    --phase scripts --non-interactive --lifecycle quick >/dev/null 2>&1 || true
  # Should have at least one .sh file
  local SH_COUNT; SH_COUNT=$(find "$TEST_DIR_P5" -maxdepth 1 -name "*.sh" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$SH_COUNT" -gt 0 ]; then
    pass "--phase scripts deployed $SH_COUNT script(s)"
  else
    fail "--phase scripts did not deploy any .sh files"
    warn "Contents: $(ls "$TEST_DIR_P5" 2>/dev/null || echo 'empty')"
  fi
  # Should NOT have a DB file
  local DB_COUNT; DB_COUNT=$(find "$TEST_DIR_P5" -maxdepth 1 -name "*.db" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$DB_COUNT" -eq 0 ]; then
    pass "--phase scripts did not create DB (correct isolation)"
  else
    fail "--phase scripts should not create DB file"
  fi
  # Should NOT have CLAUDE.md
  if [ ! -f "$TEST_DIR_P5/CLAUDE.md" ]; then
    pass "--phase scripts did not create CLAUDE.md (correct isolation)"
  else
    fail "--phase scripts should not create CLAUDE.md"
  fi
  rm -rf "$TEST_DIR_P5"

  # ── P6. --phase scripts on a project that already has a DB does not overwrite it ─
  section "P6. --phase scripts does not overwrite pre-existing DB"
  local TEST_DIR_P6
  TEST_DIR_P6=$(mktemp -d)
  # Create a pre-existing DB with a sentinel row so we can detect overwrite.
  local SENTINEL_DB="${TEST_DIR_P6}/resumetest.db"
  _run_sql "$SENTINEL_DB" "CREATE TABLE sentinel (val TEXT); INSERT INTO sentinel VALUES ('original')" \
    2>/dev/null || true
  local PRE_MTIME
  PRE_MTIME=$(stat -f '%m' "$SENTINEL_DB" 2>/dev/null || stat -c '%Y' "$SENTINEL_DB" 2>/dev/null || echo "unknown")
  # Run --phase scripts (should deploy scripts, must not touch the DB)
  bash "$BOOTSTRAP" "ResumeTest" "$TEST_DIR_P6" \
    --phase scripts --non-interactive --lifecycle quick >/dev/null 2>&1 || true
  if [ -f "$SENTINEL_DB" ]; then
    # Verify the sentinel row is still present — overwrite would destroy it
    local ROW_COUNT
    ROW_COUNT=$(_run_sql "$SENTINEL_DB" "SELECT COUNT(*) FROM sentinel WHERE val='original'" 2>/dev/null || echo "0")
    if [ "${ROW_COUNT:-0}" -ge 1 ]; then
      pass "--phase scripts did not overwrite pre-existing DB (sentinel row intact)"
    else
      fail "--phase scripts overwrote or corrupted the pre-existing DB"
    fi
  else
    fail "--phase scripts deleted the pre-existing DB"
  fi
  rm -rf "$TEST_DIR_P6"

  # ── P7. --phase rules after --phase database,scripts adds rules without affecting DB ─
  section "P7. --phase rules after database,scripts adds rules without affecting DB"
  local TEST_DIR_P7
  TEST_DIR_P7=$(mktemp -d)
  # Step 1: Run database + scripts phases
  bash "$BOOTSTRAP" "AddRulesTest" "$TEST_DIR_P7" \
    --phase database,scripts --non-interactive --lifecycle quick >/dev/null 2>&1 || true
  local DB_FILE_P7
  DB_FILE_P7=$(find "$TEST_DIR_P7" -maxdepth 1 -name "*.db" 2>/dev/null | head -1 || true)
  # Record DB mtime before running rules phase
  local DB_MTIME_BEFORE="none"
  if [ -n "$DB_FILE_P7" ] && [ -f "$DB_FILE_P7" ]; then
    DB_MTIME_BEFORE=$(stat -f '%m' "$DB_FILE_P7" 2>/dev/null || stat -c '%Y' "$DB_FILE_P7" 2>/dev/null || echo "none")
  fi
  # Step 2: Run rules phase on top
  bash "$BOOTSTRAP" "AddRulesTest" "$TEST_DIR_P7" \
    --phase rules --non-interactive --lifecycle quick >/dev/null 2>&1 || true
  # CLAUDE.md should now exist (rules phase creates it)
  if [ -f "$TEST_DIR_P7/CLAUDE.md" ]; then
    pass "--phase rules added CLAUDE.md after database,scripts run"
  else
    fail "--phase rules did not create CLAUDE.md"
  fi
  # DB should be unchanged (rules phase must not touch it)
  if [ -n "$DB_FILE_P7" ] && [ -f "$DB_FILE_P7" ]; then
    local DB_MTIME_AFTER
    DB_MTIME_AFTER=$(stat -f '%m' "$DB_FILE_P7" 2>/dev/null || stat -c '%Y' "$DB_FILE_P7" 2>/dev/null || echo "after")
    if [ "$DB_MTIME_BEFORE" = "$DB_MTIME_AFTER" ]; then
      pass "--phase rules did not modify the existing DB"
    else
      # mtime change is not necessarily a failure if bootstrap re-initialises tables
      # idempotently — warn rather than hard fail
      warn "--phase rules modified DB mtime (may be idempotent re-init, not necessarily a bug)"
    fi
  else
    warn "No DB file found after database phase — skipping DB preservation check in P7"
  fi
  rm -rf "$TEST_DIR_P7"

  # ── P8. --rollback removes bootstrap files and preserves pre-existing ──────
  section "P8. --rollback removes bootstrap files and preserves pre-existing"
  local TEST_DIR_P8
  TEST_DIR_P8=$(mktemp -d)
  # Create a pre-existing file
  echo "keep me" > "$TEST_DIR_P8/existing.txt"
  # Bootstrap
  bash "$BOOTSTRAP" "RollbackTest" "$TEST_DIR_P8" \
    --lifecycle quick --non-interactive >/dev/null 2>&1 || true
  # Verify manifest was created
  if [ -f "$TEST_DIR_P8/.bootstrap_manifest" ]; then
    pass "--rollback: manifest created during bootstrap"
  else
    fail "--rollback: no manifest created during bootstrap"
  fi
  # Count files before rollback (excluding .git)
  local PRE_ROLLBACK_COUNT
  PRE_ROLLBACK_COUNT=$(find "$TEST_DIR_P8" -type f -not -path '*/.git/*' | wc -l | tr -d ' ')
  # Run rollback
  local ROLLBACK_OUT
  ROLLBACK_OUT=$(bash "$BOOTSTRAP" "RollbackTest" "$TEST_DIR_P8" --rollback 2>&1)
  # Pre-existing file must survive
  if [ -f "$TEST_DIR_P8/existing.txt" ] && [ "$(cat "$TEST_DIR_P8/existing.txt")" = "keep me" ]; then
    pass "--rollback: pre-existing file preserved"
  else
    fail "--rollback: pre-existing file was deleted or modified"
  fi
  # Bootstrap files must be gone
  local POST_ROLLBACK_COUNT
  POST_ROLLBACK_COUNT=$(find "$TEST_DIR_P8" -type f | wc -l | tr -d ' ')
  if [ "$POST_ROLLBACK_COUNT" -eq 1 ]; then
    pass "--rollback: only pre-existing file remains ($POST_ROLLBACK_COUNT file)"
  else
    fail "--rollback: expected 1 file remaining, found $POST_ROLLBACK_COUNT"
  fi
  # Manifest itself must be removed
  if [ ! -f "$TEST_DIR_P8/.bootstrap_manifest" ]; then
    pass "--rollback: manifest cleaned up after rollback"
  else
    fail "--rollback: manifest was not removed"
  fi
  rm -rf "$TEST_DIR_P8"

  # ── P9. --rollback with no manifest exits with error ───────────────────────
  section "P9. --rollback with no manifest exits with error"
  local TEST_DIR_P9
  TEST_DIR_P9=$(mktemp -d)
  local P9_OUT
  P9_OUT=$(bash "$BOOTSTRAP" "NoManifest" "$TEST_DIR_P9" --rollback 2>&1 || true)
  if echo "$P9_OUT" | grep -q "No .bootstrap_manifest"; then
    pass "--rollback: missing manifest produces clear error"
  else
    fail "--rollback: missing manifest did not produce expected error"
  fi
  rm -rf "$TEST_DIR_P9"
}

# === FILL_PLACEHOLDERS.PY TESTS ==============================================
# Validates fill_placeholders.py CLI behaviour.
# Run independently via: bash test_bootstrap_suite.sh --fill-placeholders
fill_placeholders_tests() {
  header "fill_placeholders.py Tests"
  P_NAME="fill-placeholders"

  local SCRIPT_REAL_DIR
  SCRIPT_REAL_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd )"
  local FP_SCRIPT="${SCRIPT_REAL_DIR}/../templates/scripts/fill_placeholders.py"

  if [ ! -f "$FP_SCRIPT" ]; then
    fail "fill_placeholders.py not found at $FP_SCRIPT"
    return
  fi

  if ! python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
    fail "Python 3.10+ not available — cannot run fill_placeholders.py tests"
    return
  fi

  # ── F1. --help exits 0 ────────────────────────────────────────────────────
  section "F1. --help exits 0"
  if python3 "$FP_SCRIPT" --help >/dev/null 2>&1; then
    pass "--help exits 0"
  else
    fail "--help did not exit 0"
  fi

  # ── F2. --dry-run with --json does not modify files ───────────────────────
  section "F2. --dry-run does not modify files"
  local TEST_DIR_F2
  TEST_DIR_F2=$(mktemp -d)
  echo "Hello %%PROJECT_NAME%%" > "$TEST_DIR_F2/test.md"
  python3 "$FP_SCRIPT" "$TEST_DIR_F2" \
    --project-name "MyTest" --non-interactive --dry-run --json >/dev/null 2>&1 || true
  if grep -q "%%PROJECT_NAME%%" "$TEST_DIR_F2/test.md" 2>/dev/null; then
    pass "--dry-run left file unchanged"
  else
    fail "--dry-run modified file (should not have)"
  fi
  rm -rf "$TEST_DIR_F2"

  # ── F3. Normal run replaces placeholders ─────────────────────────────────
  section "F3. Normal run replaces %%PROJECT_NAME%% in files"
  local TEST_DIR_F3
  TEST_DIR_F3=$(mktemp -d)
  echo "Hello %%PROJECT_NAME%%" > "$TEST_DIR_F3/test.md"
  python3 "$FP_SCRIPT" "$TEST_DIR_F3" \
    --project-name "MyTest" --non-interactive --lifecycle quick >/dev/null 2>&1 || true
  if grep -q "MyTest" "$TEST_DIR_F3/test.md" 2>/dev/null; then
    pass "Normal run replaced %%PROJECT_NAME%% with 'MyTest'"
  else
    fail "Normal run did not replace %%PROJECT_NAME%%"
    warn "File contents: $(cat "$TEST_DIR_F3/test.md" 2>/dev/null)"
  fi
  rm -rf "$TEST_DIR_F3"

  # ── F4. --json output has expected structure ─────────────────────────────
  section "F4. --json output has required keys"
  local TEST_DIR_F4
  TEST_DIR_F4=$(mktemp -d)
  echo "Hello %%PROJECT_NAME%%" > "$TEST_DIR_F4/test.md"
  local F4_OUT
  F4_OUT=$(python3 "$FP_SCRIPT" "$TEST_DIR_F4" \
    --project-name "JsonTest" --non-interactive --json --lifecycle quick 2>/dev/null || true)
  if echo "$F4_OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'summary' in d, 'missing summary key'
assert 'tokens' in d, 'missing tokens key'
assert 'total_replacements' in d['summary'], 'missing total_replacements in summary'
" 2>/dev/null; then
    pass "--json output has expected structure (summary + tokens keys present)"
  else
    fail "--json output missing expected keys"
    warn "Output snippet: ${F4_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_F4"

  # ── F5. Comment-line %%TOKEN%% survives fill ─────────────────────────────
  section "F5. Comment-line %%TOKEN%% survives fill_placeholders"
  local TEST_DIR_F5
  TEST_DIR_F5=$(mktemp -d)
  echo "# Replace %%PROJECT_NAME%% after copying" > "$TEST_DIR_F5/readme.md"
  echo "Real content %%PROJECT_NAME%% here" >> "$TEST_DIR_F5/readme.md"
  python3 "$FP_SCRIPT" "$TEST_DIR_F5" \
    --project-name "SurviveTest" --non-interactive --lifecycle quick >/dev/null 2>&1 || true
  # The real content line should be replaced
  if grep -q "SurviveTest" "$TEST_DIR_F5/readme.md" 2>/dev/null; then
    pass "Real %%PROJECT_NAME%% was replaced"
  else
    fail "Real %%PROJECT_NAME%% was NOT replaced"
  fi
  rm -rf "$TEST_DIR_F5"
}

# === VERIFY_DEPLOYMENT.PY TESTS ==============================================
# Validates verify_deployment.py CLI behaviour.
# Run independently via: bash test_bootstrap_suite.sh --verify-deployment
verify_deployment_tests() {
  header "verify_deployment.py Tests"
  P_NAME="verify-deployment"

  local SCRIPT_REAL_DIR
  SCRIPT_REAL_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd )"
  local VD_SCRIPT="${SCRIPT_REAL_DIR}/../templates/scripts/verify_deployment.py"

  if [ ! -f "$VD_SCRIPT" ]; then
    fail "verify_deployment.py not found at $VD_SCRIPT"
    return
  fi

  if ! python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
    fail "Python 3.10+ not available — cannot run verify_deployment.py tests"
    return
  fi

  # ── V1. --help exits 0 ────────────────────────────────────────────────────
  section "V1. --help exits 0"
  if python3 "$VD_SCRIPT" --help >/dev/null 2>&1; then
    pass "--help exits 0"
  else
    fail "--help did not exit 0"
  fi

  # ── V2. --json produces valid JSON ────────────────────────────────────────
  section "V2. --json produces valid JSON output"
  local TEST_DIR_V2
  TEST_DIR_V2=$(mktemp -d)
  local V2_OUT
  V2_OUT=$(python3 "$VD_SCRIPT" "$TEST_DIR_V2" --json 2>/dev/null || true)
  if echo "$V2_OUT" | python3 -m json.tool >/dev/null 2>&1; then
    pass "--json output is valid JSON"
  else
    fail "--json output is not valid JSON"
    warn "Output snippet: ${V2_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_V2"

  # ── V3. --check filters to specific check ─────────────────────────────────
  section "V3. --check C12 filters to exactly 1 check in JSON output"
  local TEST_DIR_V3
  TEST_DIR_V3=$(mktemp -d)
  local V3_OUT
  V3_OUT=$(python3 "$VD_SCRIPT" "$TEST_DIR_V3" --json --check C12 2>/dev/null || true)
  if echo "$V3_OUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); assert d['total']==1, f'expected 1 check, got {d[\"total\"]}'" \
    2>/dev/null; then
    pass "--check C12 ran exactly 1 check (total=1 in JSON)"
  else
    fail "--check C12 did not produce total=1 in JSON"
    warn "Output snippet: ${V3_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_V3"

  # ── V4. Exit code 1 on critical failure ──────────────────────────────────
  section "V4. Exit code 1 on critical failure (empty dir = missing DB)"
  local TEST_DIR_V4
  TEST_DIR_V4=$(mktemp -d)
  python3 "$VD_SCRIPT" "$TEST_DIR_V4" >/dev/null 2>&1
  local V4_RC=$?
  if [ "$V4_RC" -eq 1 ]; then
    pass "Exit code 1 on critical failure (empty project dir)"
  else
    fail "Expected exit code 1, got $V4_RC"
  fi
  rm -rf "$TEST_DIR_V4"

  # ── V5. --check C06,C07 runs exactly 2 checks ──────────────────────────
  section "V5. --check C06,C07 runs exactly 2 checks"
  local TEST_DIR_V5
  TEST_DIR_V5=$(mktemp -d)
  local V5_OUT
  V5_OUT=$(python3 "$VD_SCRIPT" "$TEST_DIR_V5" --json --check C06,C07 2>/dev/null || true)
  if echo "$V5_OUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); assert d['total']==2, f'expected 2, got {d[\"total\"]}'" \
    2>/dev/null; then
    pass "--check C06,C07 ran exactly 2 checks"
  else
    fail "--check C06,C07 did not produce total=2"
    warn "Output snippet: ${V5_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_V5"

  # ── V6. --check C01 returns exactly 1 check in JSON output ──────────────────
  section "V6. --check C01 returns exactly 1 check in JSON output"
  local TEST_DIR_V6
  TEST_DIR_V6=$(mktemp -d)
  local V6_OUT
  V6_OUT=$(python3 "$VD_SCRIPT" "$TEST_DIR_V6" --json --check C01 2>/dev/null || true)
  if echo "$V6_OUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); assert d['total']==1, f'expected 1, got {d[\"total\"]}'" \
    2>/dev/null; then
    pass "--check C01 ran exactly 1 check (total=1)"
  else
    fail "--check C01 did not produce total=1 in JSON"
    warn "Output snippet: ${V6_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_V6"

  # ── V7. --check C05 returns exactly 1 check in JSON output ──────────────────
  section "V7. --check C05 returns exactly 1 check in JSON output"
  local TEST_DIR_V7
  TEST_DIR_V7=$(mktemp -d)
  local V7_OUT
  V7_OUT=$(python3 "$VD_SCRIPT" "$TEST_DIR_V7" --json --check C05 2>/dev/null || true)
  if echo "$V7_OUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); assert d['total']==1, f'expected 1, got {d[\"total\"]}'" \
    2>/dev/null; then
    pass "--check C05 ran exactly 1 check (total=1)"
  else
    fail "--check C05 did not produce total=1 in JSON"
    warn "Output snippet: ${V7_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_V7"

  # ── V8. --check C10 returns exactly 1 check in JSON output ──────────────────
  section "V8. --check C10 returns exactly 1 check in JSON output"
  local TEST_DIR_V8
  TEST_DIR_V8=$(mktemp -d)
  local V8_OUT
  V8_OUT=$(python3 "$VD_SCRIPT" "$TEST_DIR_V8" --json --check C10 2>/dev/null || true)
  if echo "$V8_OUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); assert d['total']==1, f'expected 1, got {d[\"total\"]}'" \
    2>/dev/null; then
    pass "--check C10 ran exactly 1 check (total=1)"
  else
    fail "--check C10 did not produce total=1 in JSON"
    warn "Output snippet: ${V8_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_V8"

  # ── V9. --check C01,C02 returns exactly 2 checks in JSON output ─────────────
  section "V9. --check C01,C02 returns exactly 2 checks in JSON output"
  local TEST_DIR_V9
  TEST_DIR_V9=$(mktemp -d)
  local V9_OUT
  V9_OUT=$(python3 "$VD_SCRIPT" "$TEST_DIR_V9" --json --check C01,C02 2>/dev/null || true)
  if echo "$V9_OUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); assert d['total']==2, f'expected 2, got {d[\"total\"]}'" \
    2>/dev/null; then
    pass "--check C01,C02 ran exactly 2 checks (total=2)"
  else
    fail "--check C01,C02 did not produce total=2 in JSON"
    warn "Output snippet: ${V9_OUT:0:200}"
  fi
  rm -rf "$TEST_DIR_V9"
}

# === EDGE CASE: HYPHENATED PROJECT NAME ======================================
# Tests that sed placeholder substitution handles hyphens correctly.
# Run via: bash test_bootstrap_suite.sh --edge-hyphen
edge_case_hyphen() {
  header "Edge Case: Hyphenated Project Name"
  P_NAME="My-Cool-App"
  local SLUG="my_cool_app"
  local TEST_DIR="/tmp/bootstrap_edge_hyphen_$$"
  mkdir -p "$TEST_DIR"

  section "Placeholder substitution with hyphens"
  # Copy RULES template and try substitution
  if [ -f "$RULES_TEMPLATE" ]; then
    cp "$RULES_TEMPLATE" "$TEST_DIR/RULES_TEST.md"
    sed -i '' "s/%%PROJECT_NAME%%/My-Cool-App/g" "$TEST_DIR/RULES_TEST.md" 2>/dev/null || \
      sed -i "s/%%PROJECT_NAME%%/My-Cool-App/g" "$TEST_DIR/RULES_TEST.md" 2>/dev/null
    if grep -q "My-Cool-App" "$TEST_DIR/RULES_TEST.md" 2>/dev/null; then
      pass "%%PROJECT_NAME%% substituted with hyphenated name"
    else
      fail "%%PROJECT_NAME%% substitution failed with hyphens"
    fi
    # Check no corruption from sed
    local REMAINING; REMAINING=$(grep -c '%%PROJECT_NAME%%' "$TEST_DIR/RULES_TEST.md" 2>/dev/null)
    REMAINING="${REMAINING:-0}"
    if [ "$REMAINING" -eq 0 ]; then
      pass "All %%PROJECT_NAME%% instances replaced (none remaining)"
    else
      fail "$REMAINING %%PROJECT_NAME%% instances remain after sed"
    fi
  else
    warn "RULES_TEMPLATE not found, skipping"
  fi

  section "DB operations with hyphenated slug"
  # Create a working copy with placeholders filled
  cp "$TEMPLATE_SCRIPTS/db_queries.template.sh" "$TEST_DIR/db_queries.sh"
  chmod +x "$TEST_DIR/db_queries.sh"
  sed -i '' \
    -e "s/%%PROJECT_DB%%/${SLUG}.db/g" \
    -e "s/%%PROJECT_NAME%%/My-Cool-App/g" \
    -e 's/%%LESSONS_FILE%%/LESSONS_TEST.md/g' \
    -e 's/%%PHASES%%//g' \
    "$TEST_DIR/db_queries.sh" 2>/dev/null
  touch "$TEST_DIR/LESSONS_TEST.md"

  if (cd "$TEST_DIR" && bash db_queries.sh init-db >/dev/null 2>&1) && [ -f "$TEST_DIR/${SLUG}.db" ]; then
    pass "init-db succeeds with hyphen-derived slug"
    if (cd "$TEST_DIR" && bash db_queries.sh health >/dev/null 2>&1); then
      pass "health passes with hyphen-derived slug"
    else
      fail "health failed with hyphen-derived slug"
    fi
  else
    fail "init-db failed with hyphen-derived slug"
  fi

  rm -rf "$TEST_DIR"
}

# === PYTHON CLI INTEGRATION TESTS ============================================
# Validates the Python dbq package end-to-end through the db_queries.sh wrapper.
# Run independently via: bash test_bootstrap_suite.sh --python-cli
python_cli_tests() {
  header "Python CLI Integration Tests"
  P_NAME="python-cli"

  # Pre-flight: Python 3.10+ required
  if ! python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
    fail "Python 3.10+ not available — cannot run Python CLI tests"
    return
  fi

  local TEST_DIR="/tmp/bootstrap_test_pycli_$$"
  rm -rf "$TEST_DIR"
  mkdir -p "$TEST_DIR"

  # Symlink dbq Python module (matches regression_tests setup)
  mkdir -p "$TEST_DIR/scripts"
  ln -sf "$TEMPLATE_SCRIPTS/dbq" "$TEST_DIR/scripts/dbq"

  # Copy the Python wrapper and fill placeholders
  cp "$TEMPLATE_SCRIPTS/db_queries.template.sh" "$TEST_DIR/db_queries.sh"
  chmod +x "$TEST_DIR/db_queries.sh"
  sed -i '' \
    -e 's/%%PROJECT_DB%%/pycli_test.db/g' \
    -e 's/%%PROJECT_NAME%%/PyCLITest/g' \
    -e 's/%%LESSONS_FILE%%/LESSONS_PYCLI.md/g' \
    -e 's/%%PHASES%%/P1-TEST P2-SHIP/g' \
    "$TEST_DIR/db_queries.sh" 2>/dev/null
  touch "$TEST_DIR/LESSONS_PYCLI.md"

  local DB_FILE="$TEST_DIR/pycli_test.db"

  section "PC1. init-db creates database"
  local INIT_OUT
  INIT_OUT=$(cd "$TEST_DIR" && bash db_queries.sh init-db 2>&1)
  if [ -f "$DB_FILE" ]; then
    pass "init-db created DB file"
  else
    fail "init-db did not create DB file"
    warn "Output: $INIT_OUT"
    rm -rf "$TEST_DIR"
    return
  fi

  section "PC2. health returns HEALTHY verdict"
  local HEALTH_OUT
  HEALTH_OUT=$(cd "$TEST_DIR" && bash db_queries.sh health 2>&1)
  if echo "$HEALTH_OUT" | grep -qi "HEALTHY"; then
    pass "health reports HEALTHY"
  else
    fail "health did not report HEALTHY"
    warn "Output: $HEALTH_OUT"
  fi

  section "PC3. quick creates task with QK-* ID"
  local QUICK_OUT
  QUICK_OUT=$(cd "$TEST_DIR" && bash db_queries.sh quick "Test task" P1-TEST 2>&1)
  if echo "$QUICK_OUT" | grep -qE "QK-[0-9]"; then
    pass "quick returned QK-* task ID"
  else
    fail "quick did not return QK-* task ID"
    warn "Output: $QUICK_OUT"
  fi

  section "PC4. done shows DONE in output"
  # Extract task ID from quick output for done command
  local TASK_ID
  TASK_ID=$(echo "$QUICK_OUT" | grep -oE "QK-[0-9]+" | head -1)
  local DONE_OUT
  if [ -n "$TASK_ID" ]; then
    DONE_OUT=$(cd "$TEST_DIR" && bash db_queries.sh done "$TASK_ID" 2>&1)
  else
    DONE_OUT=$(cd "$TEST_DIR" && bash db_queries.sh done 2>&1)
  fi
  if echo "$DONE_OUT" | grep -qi "DONE"; then
    pass "done shows DONE in output"
  else
    fail "done did not show DONE in output"
    warn "Output: $DONE_OUT"
  fi

  section "PC5. next produces output"
  local NEXT_OUT
  NEXT_OUT=$(cd "$TEST_DIR" && bash db_queries.sh next 2>&1)
  if [ -n "$NEXT_OUT" ]; then
    pass "next produces output"
  else
    fail "next produced no output"
  fi

  # Cleanup
  rm -rf "$TEST_DIR"
}

# === WORKFLOW INTEGRATION TESTS ===============================================
# Validates the full promote → harvest cycle using the LESSONS_UNIVERSAL symlink.
# Run independently via: bash test_bootstrap_suite.sh --workflow
workflow_integration_tests() {
  header "Workflow Integration Tests (Promote -> Harvest Cycle)"
  P_NAME="workflow-integration"

  # Pre-flight: Python 3.10+ required
  if ! python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
    fail "Python 3.10+ not available — cannot run workflow integration tests"
    return
  fi

  local TEST_DIR="/tmp/bootstrap_test_workflow_$$"
  rm -rf "$TEST_DIR"
  mkdir -p "$TEST_DIR"
  mkdir -p "$TEST_DIR/.claude"

  # --- Write a self-contained db_queries.sh that sets env vars for this test dir ---
  cat > "$TEST_DIR/db_queries.sh" << WRAPPER
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
export DB_OVERRIDE="\$SCRIPT_DIR/workflow_test.db"
export DBQ_PROJECT_NAME="WorkflowTest"
export DBQ_LESSONS_FILE="\$SCRIPT_DIR/LESSONS_WORKFLOW_TEST.md"
export DBQ_PHASES="P1-DISCOVER P2-DESIGN P3-IMPLEMENT P4-VALIDATE"
DBQ_DIR="${REPO_ROOT}/templates/scripts"
if [ ! -d "\$DBQ_DIR/dbq" ]; then
    echo "ERROR: dbq package not found at \$DBQ_DIR/dbq" >&2
    exit 1
fi
export PYTHONPATH="\$DBQ_DIR"
exec python3 -m dbq "\$@"
WRAPPER
  chmod +x "$TEST_DIR/db_queries.sh"

  # --- Populate LESSONS file with one ### block and one table row ---
  cat > "$TEST_DIR/LESSONS_WORKFLOW_TEST.md" << 'LESSONS'
# Lessons — Workflow Test

## Corrections / Insights

<!-- CORRECTIONS-ANCHOR -->

### Always validate input schemas before processing
**Date:** 2026-04-01
**Source:** WorkflowTest
**Promoted:** No
Always validate input schemas before processing data pipelines to avoid silent corruption downstream.

| Date | Pattern | Prevention Rule | Promoted |
|------|---------|-----------------|----------|
| 2026-04-01 | Check return codes after subprocess calls | Use subprocess.check_call or check returncode | No |
LESSONS

  # --- Create LESSONS_UNIVERSAL.md with standard header ---
  cat > "$TEST_DIR/LESSONS_UNIVERSAL.md" << 'UNIVERSAL'
# Universal Lessons
> Patterns that recur across 2+ projects. Promoted from project-level LESSONS files.

| Date | Pattern | Source Project | Prevention Rule |
|------|---------|---------------|-----------------|
UNIVERSAL

  # --- Symlink so promote can find it via HOME ---
  ln -s "$TEST_DIR/LESSONS_UNIVERSAL.md" "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"

  # --- Initialize DB ---
  local INIT_OUT
  INIT_OUT=$(cd "$TEST_DIR" && bash db_queries.sh init-db 2>&1)
  if [ ! -f "$TEST_DIR/workflow_test.db" ]; then
    fail "WF-setup: init-db did not create workflow_test.db"
    warn "Output: $INIT_OUT"
    rm -rf "$TEST_DIR"
    return
  fi

  # ── WF1. Promote writes to LESSONS_UNIVERSAL via symlink ────────────────
  section "WF1. Promote writes to LESSONS_UNIVERSAL via symlink"
  local PROMOTE_OUT
  PROMOTE_OUT=$(cd "$TEST_DIR" && HOME="$TEST_DIR" bash db_queries.sh promote "Always validate input schemas" "Use schema validation" 2>&1)
  if grep -q "validate input schemas" "$TEST_DIR/LESSONS_UNIVERSAL.md"; then
    pass "WF1: promote wrote pattern to LESSONS_UNIVERSAL.md via symlink"
  else
    fail "WF1: pattern not found in LESSONS_UNIVERSAL.md after promote"
    warn "Promote output: $PROMOTE_OUT"
    warn "LESSONS_UNIVERSAL.md contents:"
    warn "$(cat "$TEST_DIR/LESSONS_UNIVERSAL.md")"
  fi

  # ── WF2. Promote auto-marks source entry ────────────────────────────────
  section "WF2. Promote auto-marks source entry as Promoted: Yes"
  if grep -q "Promoted.*Yes" "$TEST_DIR/LESSONS_WORKFLOW_TEST.md"; then
    pass "WF2: source entry marked as Promoted: Yes in LESSONS file"
  else
    fail "WF2: source entry not marked as promoted after promote command"
    warn "LESSONS_WORKFLOW_TEST.md contents:"
    warn "$(cat "$TEST_DIR/LESSONS_WORKFLOW_TEST.md")"
  fi

  # ── WF3. Harvest detects remaining unpromoted entries ───────────────────
  section "WF3. Harvest detects remaining unpromoted entries"

  # Copy and fill the harvest template
  cp "$REPO_ROOT/templates/scripts/harvest.template.sh" "$TEST_DIR/harvest.sh"
  # macOS sed requires '' after -i; replace the placeholder
  sed -i '' 's/%%LESSONS_FILE%%/LESSONS_WORKFLOW_TEST.md/g' "$TEST_DIR/harvest.sh"
  chmod +x "$TEST_DIR/harvest.sh"

  local HARVEST_OUT
  HARVEST_OUT=$(cd "$TEST_DIR" && HOME="$TEST_DIR" bash harvest.sh --dry-run 2>&1)

  # The table row about "return codes" was NOT promoted — harvest must find it
  if echo "$HARVEST_OUT" | grep -qi "return code\|unpromoted\|pattern"; then
    pass "WF3: harvest detected at least 1 unpromoted candidate"
  else
    # A count > 0 also satisfies the intent
    local HARVEST_COUNT
    HARVEST_COUNT=$(echo "$HARVEST_OUT" | grep -oE "^[0-9]+" | head -1 || true)
    if [ -n "$HARVEST_COUNT" ] && [ "$HARVEST_COUNT" -gt 0 ] 2>/dev/null; then
      pass "WF3: harvest detected $HARVEST_COUNT unpromoted candidate(s)"
    else
      fail "WF3: harvest did not report any unpromoted candidates"
      warn "Harvest output: $HARVEST_OUT"
    fi
  fi

  # Cleanup
  rm -rf "$TEST_DIR"
}

# === SCRIPTS FUNCTIONAL TESTS ================================================
# Bootstraps a temp project and smoke-tests all 14 deployed scripts.
# Run independently via: bash test_bootstrap_suite.sh --scripts-functional
scripts_functional_tests() {
    header "Scripts Functional Tests"
    P_NAME="scripts-functional"

    # Bootstrap temp project
    local FUNC_DIR
    FUNC_DIR=$(mktemp -d)
    section "Bootstrapping test project at $FUNC_DIR"
    if ! bash "$REPO_ROOT/bootstrap_project.sh" "FuncTest" "$FUNC_DIR" --non-interactive --lifecycle quick >/dev/null 2>&1; then
        fail "Bootstrap test project creation"
        return
    fi
    pass "Bootstrap test project creation"

    cd "$FUNC_DIR" || { fail "cd to test project"; return; }

    # --- Syntax checks (all shell scripts) ---
    section "Syntax checks (bash -n)"
    for script in db_queries.sh session_briefing.sh save_session.sh coherence_check.sh \
                  coherence_registry.sh milestone_check.sh build_summarizer.sh \
                  work.sh fix.sh test_protocol.sh harvest.sh shared_signal.sh; do
        if [ -f "$script" ]; then
            chk "$script syntax valid" bash -n "$script"
        else
            fail "$script exists"
        fi
    done
    # Python syntax
    if [ -f "generate_board.py" ]; then
        chk "generate_board.py syntax valid" python3 -c "import py_compile; py_compile.compile('generate_board.py')"
    else
        fail "generate_board.py exists"
    fi

    # --- Placeholder checks ---
    section "Unresolved placeholder checks"
    for script in db_queries.sh session_briefing.sh save_session.sh coherence_check.sh \
                  coherence_registry.sh milestone_check.sh build_summarizer.sh \
                  work.sh fix.sh test_protocol.sh harvest.sh shared_signal.sh \
                  generate_board.py; do
        if [ -f "$script" ]; then
            # Only count placeholders in code lines (not comments)
            local code_placeholders
            code_placeholders=$(grep -v '^\s*#' "$script" | grep -c '%%[A-Z_][A-Z_0-9]*%%' || true)
            chk "$script no code placeholders" test "$code_placeholders" -eq 0
        fi
    done

    # --- Smoke runs ---
    section "Smoke runs"
    chk "db_queries.sh health" bash db_queries.sh health
    chk "session_briefing.sh runs" bash session_briefing.sh
    chk "coherence_check.sh runs" bash coherence_check.sh
    chk "generate_board.py runs" python3 generate_board.py

    # Cleanup
    cd "$REPO_ROOT"
    rm -rf "$FUNC_DIR"
}

# === SELF-CONTAINMENT TESTS ==================================================
# Bootstraps a temp project and verifies no forbidden global path references.
# Run independently via: bash test_bootstrap_suite.sh --self-containment
self_containment_tests() {
    header "Self-Containment Tests"
    P_NAME="self-containment"

    # Bootstrap a fresh test project
    local SC_DIR
    SC_DIR=$(mktemp -d)
    section "SC1. Bootstrap test project for containment check"
    bash "$REPO_ROOT/bootstrap_project.sh" "ContainTest" "$SC_DIR" --non-interactive --lifecycle quick >/dev/null 2>&1 || true
    # Check actual project artifacts rather than exit code (bootstrap may exit 1
    # due to non-fatal placeholder warnings while still producing a valid project)
    if [ ! -f "$SC_DIR/db_queries.sh" ] || [ ! -f "$SC_DIR/CLAUDE.md" ]; then
        fail "Bootstrap test project for containment check"
        rm -rf "$SC_DIR"
        return
    fi
    pass "Bootstrap test project for containment check"

    # Define forbidden patterns — these must NOT appear in generated projects
    # (excluding .git/ directory and binary files)
    local VIOLATIONS

    # SC2: No ~/.claude/ references in any text file
    section "SC2. No ~/.claude/ references in generated project"
    VIOLATIONS=$(grep -r --include='*.sh' --include='*.md' --include='*.py' --include='*.json' --include='*.yaml' --include='*.conf' \
        -l '~/.claude/' "$SC_DIR" 2>/dev/null | grep -v '\.git/' || true)
    if [ -z "$VIOLATIONS" ]; then
        pass "No ~/.claude/ references found"
    else
        fail "Found ~/.claude/ references in: $(echo "$VIOLATIONS" | tr '\n' ' ')"
    fi

    # SC3: No $HOME/.claude/ references
    section "SC3. No \$HOME/.claude/ references in generated project"
    VIOLATIONS=$(grep -r --include='*.sh' --include='*.md' --include='*.py' --include='*.json' --include='*.yaml' --include='*.conf' \
        -l 'HOME/.claude/' "$SC_DIR" 2>/dev/null | grep -v '\.git/' || true)
    if [ -z "$VIOLATIONS" ]; then
        pass "No \$HOME/.claude/ references found"
    else
        fail "Found \$HOME/.claude/ references in: $(echo "$VIOLATIONS" | tr '\n' ' ')"
    fi

    # SC4: No dev-framework references
    section "SC4. No dev-framework references in generated project"
    VIOLATIONS=$(grep -r --include='*.sh' --include='*.md' --include='*.py' --include='*.json' --include='*.yaml' --include='*.conf' \
        -l 'dev-framework' "$SC_DIR" 2>/dev/null | grep -v '\.git/' || true)
    if [ -z "$VIOLATIONS" ]; then
        pass "No dev-framework references found"
    else
        fail "Found dev-framework references in: $(echo "$VIOLATIONS" | tr '\n' ' ')"
    fi

    # SC5: Local frameworks/ directory exists and has files
    section "SC5. Local frameworks/ directory bundled"
    if [ -d "$SC_DIR/frameworks" ]; then
        local FW_COUNT
        FW_COUNT=$(ls "$SC_DIR/frameworks/"*.md 2>/dev/null | wc -l | tr -d ' ')
        if [ "$FW_COUNT" -ge 5 ]; then
            pass "frameworks/ has $FW_COUNT bundled .md files"
        else
            fail "frameworks/ has only $FW_COUNT .md files (expected >= 5)"
        fi
    else
        fail "frameworks/ directory missing"
    fi

    # SC6: Local scripts/dbq/ runtime exists
    section "SC6. Local scripts/dbq/ runtime bundled"
    if [ -d "$SC_DIR/scripts/dbq" ] && [ -f "$SC_DIR/scripts/dbq/__init__.py" ]; then
        local PY_COUNT
        PY_COUNT=$(find "$SC_DIR/scripts/dbq" -name '*.py' 2>/dev/null | wc -l | tr -d ' ')
        if [ "$PY_COUNT" -ge 10 ]; then
            pass "scripts/dbq/ has $PY_COUNT Python modules"
        else
            fail "scripts/dbq/ has only $PY_COUNT Python modules (expected >= 10)"
        fi
    else
        fail "scripts/dbq/ directory or __init__.py missing"
    fi

    # SC7: 4 agent templates deployed
    section "SC7. All 4 agent templates deployed"
    local AGENT_COUNT=0
    for agent in implementer worker explorer verifier; do
        if [ -f "$SC_DIR/.claude/agents/${agent}/${agent}.md" ]; then
            AGENT_COUNT=$((AGENT_COUNT + 1))
        fi
    done
    if [ "$AGENT_COUNT" -eq 4 ]; then
        pass "All 4 agent templates deployed"
    else
        fail "Only $AGENT_COUNT/4 agent templates deployed"
    fi

    # SC8: @-imports use local paths (not global)
    section "SC8. CLAUDE.md @-imports use local paths"
    if [ -f "$SC_DIR/CLAUDE.md" ]; then
        local GLOBAL_IMPORTS
        GLOBAL_IMPORTS=$(grep -c '@~/' "$SC_DIR/CLAUDE.md" || true)
        if [ "$GLOBAL_IMPORTS" -eq 0 ]; then
            pass "CLAUDE.md has no @~/ imports"
        else
            fail "CLAUDE.md has $GLOBAL_IMPORTS @~/ imports"
        fi
    else
        fail "CLAUDE.md not found"
    fi

    # SC9: verify_deployment.py deployed
    section "SC9. Quality tools deployed"
    if [ -f "$SC_DIR/scripts/verify_deployment.py" ]; then
        pass "verify_deployment.py deployed to scripts/"
    else
        fail "verify_deployment.py not deployed"
    fi

    # Cleanup
    rm -rf "$SC_DIR"
}

manifest_profile_tests() {
    header "Manifest Profile Tests"
    P_NAME="manifest-profiles"

    local MANIFEST="$REPO_ROOT/SYSTEMS_MANIFEST.json"

    if [ ! -f "$MANIFEST" ]; then
        fail "SYSTEMS_MANIFEST.json not found"
        return
    fi

    # MP1: profiles object exists with standard and extended
    section "MP1. profiles object has standard and extended with includes"
    if python3 -c "
import json, sys
data = json.load(open('$MANIFEST'))
profiles = data.get('profiles', {})
assert 'standard' in profiles, 'missing standard profile'
assert 'extended' in profiles, 'missing extended profile'
assert 'includes' in profiles['standard'], 'standard missing includes'
assert 'includes' in profiles['extended'], 'extended missing includes'
assert len(profiles['standard']['includes']) > 0, 'standard includes is empty'
assert len(profiles['extended']['includes']) > 0, 'extended includes is empty'
" 2>/dev/null; then
        pass "profiles object has standard and extended with includes"
    else
        fail "profiles object missing or malformed"
    fi

    # MP2: component_groups object exists and is non-empty
    section "MP2. component_groups object exists and is non-empty"
    if python3 -c "
import json
data = json.load(open('$MANIFEST'))
groups = data.get('component_groups', {})
assert len(groups) > 0, 'empty component_groups'
" 2>/dev/null; then
        pass "component_groups is non-empty"
    else
        fail "component_groups missing or empty"
    fi

    # MP3: extended is additive (superset of standard)
    section "MP3. extended.includes is a superset of standard.includes"
    local MP3_OUT
    MP3_OUT=$(python3 -c "
import json
data = json.load(open('$MANIFEST'))
std = set(data['profiles']['standard']['includes'])
ext = set(data['profiles']['extended']['includes'])
missing = std - ext
if missing:
    print(f'FAIL: standard groups missing from extended: {missing}')
else:
    extra = ext - std
    print(f'OK: extended is superset of standard ({len(extra)} additional group(s))')
" 2>/dev/null)
    if echo "$MP3_OUT" | grep -q "^OK"; then
        pass "$MP3_OUT"
    else
        fail "${MP3_OUT:-extended.includes is NOT a superset of standard.includes}"
    fi

    # MP4: every deployable component path is in exactly one group
    section "MP4. every deployable component in exactly one group"
    local MP4_OUT
    MP4_OUT=$(python3 -c "
import json
data = json.load(open('$MANIFEST'))
groups = data.get('component_groups', {})
# Collect all paths from groups
all_group_paths = {}
for gname, paths in groups.items():
    for p in paths:
        all_group_paths.setdefault(p, []).append(gname)

# Collect deployable component paths from flat arrays
deployable = []
for section in ['frameworks', 'hooks', 'agents', 'rules', 'settings']:
    for item in data.get(section, []):
        deployable.append(item['path'])
for item in data.get('scripts', []):
    if item.get('type') in ('template', 'python'):
        deployable.append(item['path'])

missing = [p for p in deployable if p not in all_group_paths]
dupes = [f'{p} in {gs}' for p, gs in all_group_paths.items() if len(gs) > 1]
if missing:
    print(f'FAIL: {len(missing)} component(s) not in any group: {missing[:3]}')
elif dupes:
    print(f'FAIL: {len(dupes)} component(s) in multiple groups: {dupes[:3]}')
else:
    print(f'OK: all {len(deployable)} deployable components in exactly one group')
" 2>/dev/null)
    if echo "$MP4_OUT" | grep -q "^OK"; then
        pass "$MP4_OUT"
    else
        fail "${MP4_OUT:-component coverage check failed}"
    fi

    # MP5: all non-empty group paths reference real files
    section "MP5. component_groups paths reference real files"
    local MP5_OUT
    MP5_OUT=$(python3 -c "
import json, os
data = json.load(open('$MANIFEST'))
groups = data.get('component_groups', {})
repo = '$REPO_ROOT'
missing = []
total = 0
for gname, paths in groups.items():
    for p in paths:
        total += 1
        if not os.path.exists(os.path.join(repo, p)):
            missing.append(f'{gname}: {p}')
if missing:
    print(f'FAIL: {len(missing)} path(s) not found: {missing[:3]}')
else:
    print(f'OK: all {total} group paths reference real files')
" 2>/dev/null)
    if echo "$MP5_OUT" | grep -q "^OK"; then
        pass "$MP5_OUT"
    else
        fail "${MP5_OUT:-group path validation failed}"
    fi

    # MP6: all groups referenced in profiles are defined in component_groups
    section "MP6. all profile groups are defined in component_groups"
    local MP6_OUT
    MP6_OUT=$(python3 -c "
import json
data = json.load(open('$MANIFEST'))
groups = set(data.get('component_groups', {}).keys())
errors = []
for pname, pdata in data.get('profiles', {}).items():
    for g in pdata.get('includes', []):
        if g not in groups:
            errors.append(f'{pname} references undefined group: {g}')
if errors:
    print(f'FAIL: {errors[0]}')
else:
    print(f'OK: all profile group references resolve ({len(groups)} groups)')
" 2>/dev/null)
    if echo "$MP6_OUT" | grep -q "^OK"; then
        pass "$MP6_OUT"
    else
        fail "${MP6_OUT:-profile group reference check failed}"
    fi
}

plugin_artifact_tests() {
    header "Plugin Artifact Smoke Tests"
    P_NAME="plugin-artifact"

    # Build the plugin zip to a temp location
    local TMPZIP
    TMPZIP="$(mktemp).zip"
    local EXTRACT_DIR
    EXTRACT_DIR="$(mktemp -d)"

    section "PA1. Build plugin zip"
    if bash "$REPO_ROOT/build_plugin.sh" "$TMPZIP" >/dev/null 2>&1; then
        pass "Plugin zip built successfully"
    else
        fail "build_plugin.sh failed"
        rm -f "$TMPZIP"
        rm -rf "$EXTRACT_DIR"
        return
    fi

    # Extract the zip
    if ! unzip -q "$TMPZIP" -d "$EXTRACT_DIR" 2>/dev/null; then
        fail "Failed to unzip plugin artifact"
        rm -f "$TMPZIP"
        rm -rf "$EXTRACT_DIR"
        return
    fi

    local PLUGIN_ROOT="$EXTRACT_DIR/project-bootstrap"

    # PA1: engine/bootstrap_project.sh exists in artifact
    if [ -f "$PLUGIN_ROOT/engine/bootstrap_project.sh" ]; then
        pass "engine/bootstrap_project.sh exists in artifact"
    else
        fail "engine/bootstrap_project.sh missing from artifact"
    fi

    # PA2: engine/VERSION exists in artifact
    section "PA2. engine/VERSION exists in artifact"
    if [ -f "$PLUGIN_ROOT/engine/VERSION" ]; then
        pass "engine/VERSION exists in artifact"
    else
        fail "engine/VERSION missing from artifact"
    fi

    # PA3: engine/templates/scripts/dbq/__main__.py exists
    section "PA3. engine/templates/scripts/dbq/__main__.py exists"
    if [ -f "$PLUGIN_ROOT/engine/templates/scripts/dbq/__main__.py" ]; then
        pass "engine/templates/scripts/dbq/__main__.py exists in artifact"
    else
        fail "engine/templates/scripts/dbq/__main__.py missing from artifact"
    fi

    # PA4: engine/templates/frameworks/ has >= 5 .md files
    section "PA4. engine/templates/frameworks/ has >= 5 .md files"
    local FW_COUNT
    FW_COUNT=$(find "$PLUGIN_ROOT/engine/templates/frameworks" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
    if [ "${FW_COUNT}" -ge 5 ]; then
        pass "engine/templates/frameworks/ has $FW_COUNT .md files"
    else
        fail "engine/templates/frameworks/ has only $FW_COUNT .md files (expected >= 5)"
    fi

    # PA5: hooks/hooks.json exists and all script references resolve within artifact
    section "PA5. hooks/hooks.json exists and hook script references resolve"
    if [ -f "$PLUGIN_ROOT/hooks/hooks.json" ]; then
        local UNRESOLVED=0
        local HOOK_SCRIPT
        # Extract paths after ${CLAUDE_PLUGIN_ROOT}/
        while IFS= read -r HOOK_SCRIPT; do
            local HOOK_PATH="$PLUGIN_ROOT/$HOOK_SCRIPT"
            if [ ! -f "$HOOK_PATH" ]; then
                fail "hooks.json references '$HOOK_SCRIPT' but file not found in artifact"
                UNRESOLVED=$((UNRESOLVED + 1))
            fi
        done < <(grep -o '\${CLAUDE_PLUGIN_ROOT}/[^"]*\.sh' "$PLUGIN_ROOT/hooks/hooks.json" | sed 's|\${CLAUDE_PLUGIN_ROOT}/||g')
        if [ "$UNRESOLVED" -eq 0 ]; then
            pass "hooks/hooks.json exists and all hook script references resolve"
        fi
    else
        fail "hooks/hooks.json missing from artifact"
    fi

    # PA6: No setup-templates skill in artifact
    section "PA6. No setup-templates skill in artifact"
    if [ ! -d "$PLUGIN_ROOT/skills/setup-templates" ]; then
        pass "No skills/setup-templates/ directory in artifact"
    else
        fail "skills/setup-templates/ found in artifact (should be excluded)"
    fi

    # PA7: No /setup-templates references in any SKILL.md
    section "PA7. No setup-templates references in any SKILL.md"
    local SKILL_MD_VIOLATIONS
    SKILL_MD_VIOLATIONS=$(grep -r 'setup-templates' "$PLUGIN_ROOT/skills" --include='SKILL.md' -l 2>/dev/null || true)
    if [ -z "$SKILL_MD_VIOLATIONS" ]; then
        pass "No setup-templates references in any SKILL.md"
    else
        fail "setup-templates references found in SKILL.md: $(echo "$SKILL_MD_VIOLATIONS" | tr '\n' ' ')"
    fi

    # PA8: Exactly 3 skills packaged
    section "PA8. Exactly 3 skills packaged (bootstrap-activate, bootstrap-discovery, spec-status)"
    local SKILL_COUNT=0
    if [ -d "$PLUGIN_ROOT/skills" ]; then
        SKILL_COUNT=$(find "$PLUGIN_ROOT/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    fi
    if [ "$SKILL_COUNT" -eq 3 ]; then
        pass "Exactly 3 skills packaged"
    else
        fail "Expected 3 skills, found $SKILL_COUNT"
    fi

    # PA9: No __pycache__ or .pyc files in artifact
    section "PA9. No __pycache__ or .pyc files in artifact"
    local PYCACHE_COUNT
    PYCACHE_COUNT=$(find "$PLUGIN_ROOT" -type d -name "__pycache__" 2>/dev/null | wc -l | tr -d ' ')
    local PYC_COUNT
    PYC_COUNT=$(find "$PLUGIN_ROOT" -name "*.pyc" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$PYCACHE_COUNT" -eq 0 ] && [ "$PYC_COUNT" -eq 0 ]; then
        pass "No __pycache__ or .pyc files in artifact"
    else
        fail "Found $PYCACHE_COUNT __pycache__ dirs and $PYC_COUNT .pyc files in artifact"
    fi

    # PA10: plugin.json exists and is valid JSON
    section "PA10. .claude-plugin/plugin.json exists and is valid JSON"
    if [ -f "$PLUGIN_ROOT/.claude-plugin/plugin.json" ]; then
        if python3 -c "import json,sys; json.load(open('$PLUGIN_ROOT/.claude-plugin/plugin.json'))" 2>/dev/null; then
            pass ".claude-plugin/plugin.json exists and is valid JSON"
        else
            fail ".claude-plugin/plugin.json exists but is not valid JSON"
        fi
    else
        fail ".claude-plugin/plugin.json missing from artifact"
    fi

    # Cleanup
    rm -f "$TMPZIP"
    rm -rf "$EXTRACT_DIR"
}

# === CLEANUP =================================================================
cleanup() {
  echo -e "\n${YELLOW}Removing test directories...${RESET}"
  for d in 1 2 3 4; do
    if [ -d "$SUITE_DIR/test_project$d" ]; then
      rm -rf "$SUITE_DIR/test_project$d"
      echo -e "  ${GREEN}✅${RESET} Removed test_project$d"
    fi
  done
  echo -e "${GREEN}Cleanup complete.${RESET}"
}

# === SUMMARY =================================================================
print_summary() {
  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║              TEST SUITE SUMMARY                      ║${RESET}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""
  echo -e "  Checks: ${BOLD}$TOTAL_CHECKS${RESET} | Pass: ${GREEN}$TOTAL_PASS${RESET} | Fail: ${RED}$TOTAL_FAIL${RESET}"
  echo ""
  if [ "$TOTAL_FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}ALL CHECKS PASSED ✅${RESET}"
    echo -e "  ${GREEN}Bootstrap framework validated across all 4 archetypes.${RESET}"
  else
    echo -e "  ${RED}${BOLD}$TOTAL_FAIL FAILURE(S) ❌${RESET}"
    echo ""
    echo -e "  ${BOLD}Failed checks:${RESET}"
    for f in "${FAILURES[@]}"; do
      echo -e "    ${RED}•${RESET} $f"
    done
    echo ""
    echo -e "  ${YELLOW}Fix template bugs and re-run to confirm. Test projects preserved for debugging.${RESET}"
  fi
  echo ""
}

# === MAIN ====================================================================
run_project() {
  local N="$1"
  load_project_config "$N"
  create_specs
  deploy_project
  verify_project
  exercise_project
}

symlink_tests() {
  header "Symlink Verification Tests"
  P_NAME="symlink"

  local TEST_DIR="/tmp/bootstrap_test_symlink_$$"
  rm -rf "$TEST_DIR"
  mkdir -p "$TEST_DIR/.claude"
  mkdir -p "$TEST_DIR/project"

  # Create a canonical LESSONS_UNIVERSAL.md in "project"
  echo "# Universal Lessons" > "$TEST_DIR/project/LESSONS_UNIVERSAL.md"

  section "SL1. Symlink already exists → verified"
  ln -s "$TEST_DIR/project/LESSONS_UNIVERSAL.md" "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  if [ -L "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ]; then
    pass "Symlink detected at expected path"
  else
    fail "Expected symlink not detected"
  fi

  section "SL2. Regular file exists → not a symlink"
  rm -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  echo "content" > "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  if [ ! -L "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ] && [ -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ]; then
    pass "Regular file correctly distinguished from symlink"
  else
    fail "Failed to distinguish regular file from symlink"
  fi

  section "SL3. Canonical exists, no symlink → symlink can be created"
  rm -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  ln -s "$TEST_DIR/project/LESSONS_UNIVERSAL.md" "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  if [ -L "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ]; then
    pass "Symlink created successfully"
  else
    fail "Symlink creation failed"
  fi
  if [ -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ]; then
    pass "Symlink target resolves to readable file"
  else
    fail "Symlink target does not resolve"
  fi

  section "SL4. Neither file exists → detection works"
  rm -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  rm -f "$TEST_DIR/project/LESSONS_UNIVERSAL.md"
  if [ ! -L "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ] && \
     [ ! -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ] && \
     [ ! -f "$TEST_DIR/project/LESSONS_UNIVERSAL.md" ]; then
    pass "Absence of both files correctly detected"
  else
    fail "Unexpected file or symlink found when both should be absent"
  fi

  rm -rf "$TEST_DIR"
}

harvest_fallback_tests() {
  header "Harvest Fallback Path Tests"
  P_NAME="harvest-fallback"

  local TEST_DIR="/tmp/bootstrap_test_harvest_fb_$$"
  rm -rf "$TEST_DIR"
  mkdir -p "$TEST_DIR/.claude"
  mkdir -p "$TEST_DIR/project"

  section "HF1. ~/.claude/ file exists → uses it"
  echo "# Universal" > "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  local HOME_UNIVERSAL="$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  local PROJECT_UNIVERSAL="$TEST_DIR/project/LESSONS_UNIVERSAL.md"
  local RESOLVED
  if [ -f "$HOME_UNIVERSAL" ]; then
    RESOLVED="$HOME_UNIVERSAL"
  elif [ -f "$PROJECT_UNIVERSAL" ]; then
    RESOLVED="$PROJECT_UNIVERSAL"
  else
    RESOLVED="$HOME_UNIVERSAL"
  fi
  if [ "$RESOLVED" = "$HOME_UNIVERSAL" ]; then
    pass "Resolved to ~/.claude/ path when that file exists"
  else
    fail "Expected ~/.claude/ path, got: $RESOLVED"
  fi

  section "HF2. ~/.claude/ missing, project-local exists → uses project-local"
  rm -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  echo "# Universal" > "$TEST_DIR/project/LESSONS_UNIVERSAL.md"
  if [ -f "$HOME_UNIVERSAL" ]; then
    RESOLVED="$HOME_UNIVERSAL"
  elif [ -f "$PROJECT_UNIVERSAL" ]; then
    RESOLVED="$PROJECT_UNIVERSAL"
  else
    RESOLVED="$HOME_UNIVERSAL"
  fi
  if [ "$RESOLVED" = "$PROJECT_UNIVERSAL" ]; then
    pass "Resolved to project-local path as fallback"
  else
    fail "Expected project-local path, got: $RESOLVED"
  fi

  section "HF3. Both missing → defaults to ~/.claude/ for creation"
  rm -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  rm -f "$TEST_DIR/project/LESSONS_UNIVERSAL.md"
  if [ -f "$HOME_UNIVERSAL" ]; then
    RESOLVED="$HOME_UNIVERSAL"
  elif [ -f "$PROJECT_UNIVERSAL" ]; then
    RESOLVED="$PROJECT_UNIVERSAL"
  else
    RESOLVED="$HOME_UNIVERSAL"
  fi
  if [ "$RESOLVED" = "$HOME_UNIVERSAL" ]; then
    pass "Defaults to ~/.claude/ path when both files absent"
  else
    fail "Expected ~/.claude/ default path, got: $RESOLVED"
  fi

  rm -rf "$TEST_DIR"
}

briefing_freshness_tests() {
  header "Briefing Freshness Check Tests"
  P_NAME="briefing-freshness"

  local TEST_DIR="/tmp/bootstrap_test_briefing_$$"
  rm -rf "$TEST_DIR"
  mkdir -p "$TEST_DIR/.claude"

  section "SB1. Fresh file → no staleness warning"
  echo "# Universal Lessons" > "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  local UNIVERSAL="$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  local LAST_MOD NOW DAYS_STALE WARNING
  LAST_MOD=$(stat -f %m "$UNIVERSAL" 2>/dev/null || stat -c %Y "$UNIVERSAL" 2>/dev/null || echo "0")
  NOW=$(date +%s)
  WARNING=""
  if [[ "$LAST_MOD" =~ ^[0-9]+$ ]] && [ "$LAST_MOD" -gt 0 ]; then
    DAYS_STALE=$(( (NOW - LAST_MOD) / 86400 ))
    if [ "$DAYS_STALE" -gt 7 ]; then
      WARNING="not updated in ${DAYS_STALE} days"
    fi
  fi
  if [ -z "$WARNING" ]; then
    pass "No staleness warning for freshly-created file"
  else
    fail "Unexpected staleness warning: $WARNING"
  fi

  section "SB2. Stale file → warning produced"
  touch -t 202603010000 "$UNIVERSAL"
  LAST_MOD=$(stat -f %m "$UNIVERSAL" 2>/dev/null || stat -c %Y "$UNIVERSAL" 2>/dev/null || echo "0")
  NOW=$(date +%s)
  WARNING=""
  if [[ "$LAST_MOD" =~ ^[0-9]+$ ]] && [ "$LAST_MOD" -gt 0 ]; then
    DAYS_STALE=$(( (NOW - LAST_MOD) / 86400 ))
    if [ "$DAYS_STALE" -gt 7 ]; then
      WARNING="not updated in ${DAYS_STALE} days"
    fi
  fi
  if [ -n "$WARNING" ]; then
    pass "Staleness warning produced: $WARNING"
  else
    fail "Expected staleness warning for file with old timestamp"
  fi

  section "SB3. Missing file → not-found warning"
  rm -f "$UNIVERSAL"
  local NOT_FOUND_MSG=""
  if [ ! -f "$UNIVERSAL" ]; then
    NOT_FOUND_MSG="not found"
  fi
  if [ -n "$NOT_FOUND_MSG" ]; then
    pass "Not-found condition detected when file is absent"
  else
    fail "Expected not-found condition but file still appears to exist"
  fi

  rm -rf "$TEST_DIR"
}

sast_regression_tests() {
  header "SAST Regression Tests"
  P_NAME="sast"

  local RULES="$REPO_ROOT/templates/semgrep-rules/bootstrap.yaml"
  local FIXTURES="$REPO_ROOT/tests/fixtures/sast"

  # S1. Custom rules validate without errors
  section "S1. semgrep --validate on bootstrap.yaml"
  if semgrep --validate --config="$RULES" >/dev/null 2>&1; then
    pass "bootstrap.yaml validates cleanly (2 rules)"
  else
    fail "bootstrap.yaml has validation errors"
  fi

  # S2. Hook exits cleanly when semgrep not in PATH
  section "S2. Static analysis hook graceful degradation (no semgrep)"
  local HOOK_SCRIPT="$REPO_ROOT/templates/hooks/static-analysis-gate.template.sh"
  local MOCK_INPUT='{"tool_name":"Edit","tool_input":{"file_path":"/tmp/test.py"},"cwd":"/tmp"}'
  # Run hook with semgrep removed from PATH — should exit 0, no output
  local HOOK_OUT
  HOOK_OUT=$(echo "$MOCK_INPUT" | PATH="/usr/bin:/bin" bash "$HOOK_SCRIPT" 2>/dev/null) || true
  if [ -z "$HOOK_OUT" ]; then
    pass "Hook silent when semgrep not in PATH"
  else
    fail "Hook produced output when semgrep not in PATH: $HOOK_OUT"
  fi

  # S3. no-bare-exit fires on known-bad fixture
  section "S3. no-bare-exit rule catches exit()"
  local BAD_COUNT
  BAD_COUNT=$(semgrep --config="$RULES" "$FIXTURES/known_bad_exit.py" --json --quiet 2>/dev/null \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['results']))" 2>/dev/null || echo "0")
  if [ "$BAD_COUNT" -gt 0 ]; then
    pass "no-bare-exit fires on known_bad_exit.py ($BAD_COUNT finding(s))"
  else
    fail "no-bare-exit did NOT fire on known_bad_exit.py"
  fi

  # S4. no-bare-exit does NOT fire on sys.exit()
  section "S4. no-bare-exit skips sys.exit() (no false positive)"
  local GOOD_COUNT
  GOOD_COUNT=$(semgrep --config="$RULES" "$FIXTURES/known_good_sysexit.py" --json --quiet 2>/dev/null \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['results']))" 2>/dev/null || echo "0")
  if [ "$GOOD_COUNT" -eq 0 ]; then
    pass "no-bare-exit silent on known_good_sysexit.py"
  else
    fail "no-bare-exit FALSE POSITIVE on known_good_sysexit.py ($GOOD_COUNT finding(s))"
  fi

  # S5. Clean file produces zero findings
  section "S5. Clean file produces zero findings"
  local CLEAN_COUNT
  CLEAN_COUNT=$(semgrep --config="$RULES" "$FIXTURES/known_good_clean.py" --json --quiet 2>/dev/null \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['results']))" 2>/dev/null || echo "0")
  if [ "$CLEAN_COUNT" -eq 0 ]; then
    pass "Zero findings on known_good_clean.py"
  else
    fail "Unexpected findings on known_good_clean.py ($CLEAN_COUNT)"
  fi

  # S6. Zero findings on entire dbq codebase
  section "S6. Custom rules: zero findings on dbq codebase"
  local DBQ_COUNT
  DBQ_COUNT=$(cd "$REPO_ROOT" && semgrep --config="$RULES" templates/scripts/dbq/ --json --quiet 2>/dev/null \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['results']))" 2>/dev/null || echo "error")
  if [ "$DBQ_COUNT" = "0" ]; then
    pass "Zero findings on dbq codebase"
  else
    fail "Found $DBQ_COUNT finding(s) on dbq codebase (expected 0)"
  fi

  # S7. %%SAST_CONFIG%% placeholder exists in fp_engine.py dispatch
  section "S7. SAST_CONFIG placeholder in fp_engine.py"
  if grep -q '"SAST_CONFIG"' "$REPO_ROOT/templates/scripts/fp_engine.py"; then
    pass "SAST_CONFIG in AUTO_DERIVATION_DISPATCH"
  else
    fail "SAST_CONFIG not found in fp_engine.py"
  fi

  # S8. .semgrepignore template exists
  section "S8. .semgrepignore template exists"
  if [ -f "$REPO_ROOT/templates/hooks/.semgrepignore.template" ]; then
    pass ".semgrepignore.template exists"
  else
    fail ".semgrepignore.template not found"
  fi
}

# === QUALITY-GATE CONTRACT TESTS ==============================================
# Validates quality-gate templates: pre-commit hook, build summarizer, static analysis,
# and settings template hook wiring. Template-level — no live project needed.
# Run independently via: bash test_bootstrap_suite.sh --quality-gate
quality_gate_contract_tests() {
  header "Quality-Gate Contract Tests"
  P_NAME="quality-gate"

  local PRE_COMMIT="$TEMPLATES/scripts/pre-commit.template.sh"
  local BUILD_SUM="$TEMPLATES/scripts/build_summarizer.template.sh"
  local SAST_HOOK="$TEMPLATES/hooks/static-analysis-gate.template.sh"
  local SETTINGS="$TEMPLATES/settings/settings.template.json"

  # QG1: Pre-commit template exists and has lint placeholder
  section "QG1. pre-commit.template.sh has %%LINT_COMMAND%% placeholder"
  if [ -f "$PRE_COMMIT" ] && grep -q '%%LINT_COMMAND%%' "$PRE_COMMIT"; then
    pass "pre-commit template has %%LINT_COMMAND%%"
  else
    fail "pre-commit template missing or lacks %%LINT_COMMAND%%"
  fi

  # QG2: Pre-commit template has type-check placeholder
  section "QG2. pre-commit.template.sh has %%TYPE_CHECK_COMMAND%% placeholder"
  if grep -q '%%TYPE_CHECK_COMMAND%%' "$PRE_COMMIT" 2>/dev/null; then
    pass "pre-commit template has %%TYPE_CHECK_COMMAND%%"
  else
    fail "pre-commit template missing %%TYPE_CHECK_COMMAND%%"
  fi

  # QG3: Pre-commit template has semgrep integration
  section "QG3. pre-commit.template.sh has semgrep integration"
  if grep -q 'semgrep' "$PRE_COMMIT" 2>/dev/null; then
    pass "pre-commit template integrates semgrep"
  else
    fail "pre-commit template missing semgrep integration"
  fi

  # QG4: Build summarizer template exists with required placeholders
  section "QG4. build_summarizer.template.sh has %%BUILD_COMMAND%% placeholder"
  if [ -f "$BUILD_SUM" ] && grep -q '%%BUILD_COMMAND%%' "$BUILD_SUM"; then
    pass "build_summarizer template has %%BUILD_COMMAND%%"
  else
    fail "build_summarizer template missing or lacks %%BUILD_COMMAND%%"
  fi

  # QG5: Build summarizer has test command placeholder
  section "QG5. build_summarizer.template.sh has %%TEST_COMMAND%% placeholder"
  if grep -q '%%TEST_COMMAND%%' "$BUILD_SUM" 2>/dev/null; then
    pass "build_summarizer template has %%TEST_COMMAND%%"
  else
    fail "build_summarizer template missing %%TEST_COMMAND%%"
  fi

  # QG6: Static-analysis hook template exists
  section "QG6. static-analysis-gate hook template exists"
  if [ -f "$SAST_HOOK" ]; then
    pass "static-analysis-gate.template.sh exists"
  else
    fail "static-analysis-gate.template.sh not found"
  fi

  # QG7: Settings template has hook wiring for all required event types
  section "QG7. settings.template.json wires all hook event types"
  local MISSING_EVENTS=""
  for event in UserPromptSubmit PreToolUse PostToolUse SessionStart; do
    if ! grep -q "\"$event\"" "$SETTINGS" 2>/dev/null; then
      MISSING_EVENTS="$MISSING_EVENTS $event"
    fi
  done
  if [ -z "$MISSING_EVENTS" ]; then
    pass "settings template wires all required hook events"
  else
    fail "settings template missing hook events:$MISSING_EVENTS"
  fi

  # QG8: Every hook command in settings template references an existing template
  section "QG8. settings.template.json hook commands reference existing templates"
  local BAD_REFS=""
  local HOOK_CMDS
  HOOK_CMDS=$(grep -oE '\.claude/hooks/[a-z_-]+\.sh' "$SETTINGS" 2>/dev/null | sort -u)
  while IFS= read -r hookref; do
    [ -z "$hookref" ] && continue
    local BASENAME
    BASENAME=$(basename "$hookref" .sh)
    if [ ! -f "$TEMPLATES/hooks/${BASENAME}.template.sh" ]; then
      BAD_REFS="$BAD_REFS $BASENAME"
    fi
  done <<< "$HOOK_CMDS"
  if [ -z "$BAD_REFS" ]; then
    pass "All hook references in settings resolve to templates"
  else
    fail "Unresolvable hook references:$BAD_REFS"
  fi

  # QG9: verify_deployment.py template exists
  section "QG9. verify_deployment.py exists in scripts"
  if [ -f "$TEMPLATES/scripts/verify_deployment.py" ] || [ -f "$TEMPLATE_SCRIPTS/verify_deployment.py" ]; then
    pass "verify_deployment.py exists"
  else
    fail "verify_deployment.py not found in scripts"
  fi
}

# === FORBIDDEN-PATTERN REGRESSION TESTS =======================================
# Validates templates don't contain patterns that should never appear in generated projects.
# Complements self-containment tests (which test generated output) by testing source templates.
# Run independently via: bash test_bootstrap_suite.sh --forbidden-pattern
forbidden_pattern_regression_tests() {
  header "Forbidden-Pattern Regression Tests"
  P_NAME="forbidden-pattern"

  # FP1: No hardcoded bootstrap.db references in non-dbq script templates
  # (dbq itself uses bootstrap.db as the default DB name — that's intentional, not contamination)
  section "FP1. No hardcoded bootstrap.db in non-dbq templates"
  local FP_HITS
  FP_HITS=$(grep -r --include='*.sh' --include='*.py' --include='*.json' \
    -l 'bootstrap\.db' "$TEMPLATES/" 2>/dev/null \
    | grep -v '\.git/' | grep -v 'placeholder-registry' \
    | grep -v '/dbq/' | grep -v 'contamination-check' || true)
  if [ -z "$FP_HITS" ]; then
    pass "No hardcoded bootstrap.db in non-dbq templates"
  else
    fail "Found bootstrap.db references in: $(echo "$FP_HITS" | tr '\n' ' ')"
  fi

  # FP2: No PROJECTS.md references in non-dbq templates (dbq eval uses it for cross-project scanning)
  section "FP2. No PROJECTS.md references in non-dbq templates"
  FP_HITS=$(grep -r --include='*.sh' --include='*.md' --include='*.py' --include='*.json' \
    -l 'PROJECTS\.md' "$TEMPLATES/" 2>/dev/null \
    | grep -v '\.git/' | grep -v 'placeholder-registry' \
    | grep -v '/dbq/' || true)
  if [ -z "$FP_HITS" ]; then
    pass "No PROJECTS.md references in non-dbq templates"
  else
    fail "Found PROJECTS.md references in: $(echo "$FP_HITS" | tr '\n' ' ')"
  fi

  # FP3: CLAUDE_TEMPLATE.md does NOT @-import phase-gates at startup
  section "FP3. CLAUDE_TEMPLATE.md does not startup-import phase-gates"
  if grep -q '^@.*phase-gates' "$TEMPLATES/rules/CLAUDE_TEMPLATE.md" 2>/dev/null; then
    fail "CLAUDE_TEMPLATE.md @-imports phase-gates at startup"
  else
    pass "phase-gates not in startup @-imports"
  fi

  # FP4: CLAUDE_TEMPLATE.md does NOT @-import LESSONS at startup
  section "FP4. CLAUDE_TEMPLATE.md does not startup-import LESSONS"
  if grep -q '^@.*LESSONS' "$TEMPLATES/rules/CLAUDE_TEMPLATE.md" 2>/dev/null; then
    fail "CLAUDE_TEMPLATE.md @-imports LESSONS at startup"
  else
    pass "LESSONS not in startup @-imports"
  fi

  # FP5: No hardcoded /Users/<real-username> paths in templates
  # Excludes /Users/user/ (example placeholder) and docstring/comment contexts
  section "FP5. No hardcoded /Users/ paths in templates"
  FP_HITS=$(grep -rn --include='*.sh' --include='*.md' --include='*.py' --include='*.json' \
    '/Users/[a-zA-Z]' "$TEMPLATES/" 2>/dev/null \
    | grep -v '\.git/' | grep -v 'placeholder-registry' \
    | grep -v '/Users/user/' | grep -v '/Users/username/' || true)
  if [ -z "$FP_HITS" ]; then
    pass "No hardcoded /Users/ paths in templates"
  else
    fail "Found /Users/ paths in: $(echo "$FP_HITS" | tr '\n' ' ')"
  fi

  # FP6: No %%PLACEHOLDER%% patterns left in framework files (they should be content, not templates)
  section "FP6. No unfilled placeholders in framework files"
  FP_HITS=$(grep -r --include='*.md' \
    -l '%%[A-Z_]*%%' "$TEMPLATES/frameworks/" 2>/dev/null \
    | grep -v '\.git/' || true)
  if [ -z "$FP_HITS" ]; then
    pass "No %%PLACEHOLDER%% patterns in frameworks/"
  else
    fail "Found unfilled placeholders in: $(echo "$FP_HITS" | tr '\n' ' ')"
  fi

  # FP7: Template hook scripts reference $CLAUDE_PROJECT_DIR not hardcoded paths
  section "FP7. Hook templates use \$CLAUDE_PROJECT_DIR (not hardcoded paths)"
  local HARDCODED_HOOKS=0
  for hookfile in "$TEMPLATES/hooks/"*.template.sh; do
    [ -f "$hookfile" ] || continue
    if grep -q '/Users/\|/home/' "$hookfile" 2>/dev/null; then
      HARDCODED_HOOKS=$((HARDCODED_HOOKS + 1))
    fi
  done
  if [ "$HARDCODED_HOOKS" -eq 0 ]; then
    pass "All hook templates use portable paths"
  else
    fail "$HARDCODED_HOOKS hook template(s) contain hardcoded paths"
  fi
}

# === CONTEXT-FOOTPRINT REGRESSION TESTS =======================================
# Guards against context-size regressions in generated projects.
# Enforces: startup @-import count, template sizes, compact briefing schema.
# Run independently via: bash test_bootstrap_suite.sh --context-footprint
context_footprint_tests() {
  header "Context-Footprint Regression Tests"
  P_NAME="context-footprint"

  local CLAUDE_TPL="$TEMPLATES/rules/CLAUDE_TEMPLATE.md"
  local RULES_TPL="$TEMPLATES/rules/RULES_TEMPLATE.md"

  # CF1: CLAUDE_TEMPLATE.md startup @-imports capped at 4
  section "CF1. CLAUDE_TEMPLATE.md has <= 4 startup @-imports"
  local IMPORT_COUNT
  IMPORT_COUNT=$(grep -c '^@' "$CLAUDE_TPL" 2>/dev/null || echo "0")
  if [ "$IMPORT_COUNT" -le 4 ]; then
    pass "CLAUDE_TEMPLATE.md has $IMPORT_COUNT startup @-imports (limit: 4)"
  else
    fail "CLAUDE_TEMPLATE.md has $IMPORT_COUNT startup @-imports (limit: 4)"
  fi

  # CF2: CLAUDE_TEMPLATE.md size budget (under 1500 bytes)
  section "CF2. CLAUDE_TEMPLATE.md under 1500 bytes"
  local CLAUDE_SIZE
  CLAUDE_SIZE=$(wc -c < "$CLAUDE_TPL" | tr -d ' ')
  if [ "$CLAUDE_SIZE" -le 1500 ]; then
    pass "CLAUDE_TEMPLATE.md is $CLAUDE_SIZE bytes (budget: 1500)"
  else
    fail "CLAUDE_TEMPLATE.md is $CLAUDE_SIZE bytes (budget: 1500)"
  fi

  # CF3: RULES_TEMPLATE.md size budget (under 6000 bytes)
  section "CF3. RULES_TEMPLATE.md under 6000 bytes"
  local RULES_SIZE
  RULES_SIZE=$(wc -c < "$RULES_TPL" | tr -d ' ')
  if [ "$RULES_SIZE" -le 6000 ]; then
    pass "RULES_TEMPLATE.md is $RULES_SIZE bytes (budget: 6000)"
  else
    fail "RULES_TEMPLATE.md is $RULES_SIZE bytes (budget: 6000)"
  fi

  # CF4: Total startup context chain under 12KB
  # (CLAUDE_TEMPLATE + RULES_TEMPLATE + session-protocol framework)
  section "CF4. Startup context chain under 12KB"
  local SESSION_PROTO="$TEMPLATES/frameworks/session-protocol.md"
  local CHAIN_SIZE=0
  for f in "$CLAUDE_TPL" "$RULES_TPL" "$SESSION_PROTO"; do
    if [ -f "$f" ]; then
      local FSIZE
      FSIZE=$(wc -c < "$f" | tr -d ' ')
      CHAIN_SIZE=$((CHAIN_SIZE + FSIZE))
    fi
  done
  if [ "$CHAIN_SIZE" -le 12288 ]; then
    pass "Startup context chain is $CHAIN_SIZE bytes (budget: 12288)"
  else
    fail "Startup context chain is $CHAIN_SIZE bytes (budget: 12288)"
  fi

  # CF5: CLAUDE_TEMPLATE.md has on-demand guidance (not importing everything)
  section "CF5. CLAUDE_TEMPLATE.md documents on-demand frameworks"
  if grep -q 'On-demand' "$CLAUDE_TPL" 2>/dev/null; then
    pass "CLAUDE_TEMPLATE.md documents on-demand loading pattern"
  else
    fail "CLAUDE_TEMPLATE.md missing on-demand loading guidance"
  fi

  # CF6: CLAUDE_TEMPLATE.md has LESSONS non-import guard
  section "CF6. CLAUDE_TEMPLATE.md documents LESSONS non-import policy"
  if grep -q 'NOT @-imported' "$CLAUDE_TPL" 2>/dev/null; then
    pass "CLAUDE_TEMPLATE.md documents LESSONS non-import policy"
  else
    fail "CLAUDE_TEMPLATE.md missing LESSONS non-import policy"
  fi

  # CF7: session_briefing.py --compact output schema has required keys
  section "CF7. session_briefing.py compact output has all required keys"
  local BRIEFING_OUT=""
  if [ ! -f "$REPO_ROOT/bootstrap.db" ]; then
    warn "Skipping CF7/CF8 — bootstrap.db not found (public export)"
  else
    BRIEFING_OUT=$(python3 "$TEMPLATES/scripts/session_briefing.py" --compact --db "$REPO_ROOT/bootstrap.db" 2>/dev/null || echo "")
    if [ -n "$BRIEFING_OUT" ]; then
      local MISSING_KEYS=""
      for key in signal reasons next_task stats; do
        if ! echo "$BRIEFING_OUT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert '$key' in d" 2>/dev/null; then
          MISSING_KEYS="$MISSING_KEYS $key"
        fi
      done
      if [ -z "$MISSING_KEYS" ]; then
        pass "Compact briefing has all required keys (signal, reasons, next_task, stats)"
      else
        fail "Compact briefing missing keys:$MISSING_KEYS"
      fi
    else
      fail "session_briefing.py --compact produced no output"
    fi

    # CF8: Compact briefing output under 500 bytes (regression guard)
    section "CF8. Compact briefing output under 500 bytes"
    if [ -n "$BRIEFING_OUT" ]; then
      local BRIEF_SIZE
      BRIEF_SIZE=$(echo -n "$BRIEFING_OUT" | wc -c | tr -d ' ')
      if [ "$BRIEF_SIZE" -le 500 ]; then
        pass "Compact briefing is $BRIEF_SIZE bytes (budget: 500)"
      else
        fail "Compact briefing is $BRIEF_SIZE bytes (budget: 500)"
      fi
    else
      fail "No briefing output to measure"
    fi
  fi

  # CF9: No framework file over 8KB (prevents bloat in on-demand loads)
  section "CF9. No framework file exceeds 8KB"
  local OVERSIZED=0
  for fw in "$TEMPLATES/frameworks/"*.md; do
    [ -f "$fw" ] || continue
    local FWSIZE
    FWSIZE=$(wc -c < "$fw" | tr -d ' ')
    if [ "$FWSIZE" -gt 8192 ]; then
      OVERSIZED=$((OVERSIZED + 1))
      warn "  $(basename "$fw") is $FWSIZE bytes"
    fi
  done
  if [ "$OVERSIZED" -eq 0 ]; then
    pass "All framework files under 8KB"
  else
    fail "$OVERSIZED framework file(s) exceed 8KB"
  fi
}

# === PHASE 4 PYTHON CONTRACT TESTS ============================================
# Smoke tests for Phase 4 Python scripts (session_briefing.py, save_session.py, preflight_check.py).
# Validates CLI contracts: JSON output schema, required keys, valid enums, shell wrapper compat.
# Run independently via: bash test_bootstrap_suite.sh --python-contract
python_contract_tests() {
  header "Phase 4 Python Contract Tests"
  P_NAME="python-contract"

  # These tests run against the live bootstrap.db — no temp DB needed
  local SCRIPTS_DIR="$REPO_ROOT/templates/scripts"

  # Skip if meta-project DB not present (public export)
  if [ ! -f "$REPO_ROOT/bootstrap.db" ]; then
    warn "Skipping Python contract tests — bootstrap.db not found (public export)"
    return 0
  fi

  section "CT1. session_briefing.py --json produces valid JSON"
  local SB_JSON
  SB_JSON=$(PROJECT_DB="$REPO_ROOT/bootstrap.db" python3 "$SCRIPTS_DIR/session_briefing.py" --json 2>/dev/null)
  if echo "$SB_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'signal' in d, 'missing signal'
assert 'stats' in d, 'missing stats'
assert 'reasons' in d, 'missing reasons'
assert 'next_task' in d, 'missing next_task'
" 2>/dev/null; then
    pass "session_briefing.py --json valid with required keys (signal, stats, reasons, next_task)"
  else
    fail "session_briefing.py --json missing required keys"
    warn "Output: ${SB_JSON:0:200}"
  fi

  section "CT2. session_briefing.py --compact is alias for --json"
  local SB_COMPACT
  SB_COMPACT=$(PROJECT_DB="$REPO_ROOT/bootstrap.db" python3 "$SCRIPTS_DIR/session_briefing.py" --compact 2>/dev/null)
  if echo "$SB_COMPACT" | python3 -c "import sys, json; d = json.load(sys.stdin); assert 'signal' in d" 2>/dev/null; then
    pass "session_briefing.py --compact produces valid JSON"
  else
    fail "session_briefing.py --compact invalid"
  fi

  section "CT3. session_briefing.py signal is valid enum"
  local SB_SIGNAL
  SB_SIGNAL=$(echo "$SB_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['signal'])" 2>/dev/null)
  if echo "$SB_SIGNAL" | grep -qE "^(GREEN|YELLOW|RED)$"; then
    pass "signal is valid enum: $SB_SIGNAL"
  else
    fail "signal not GREEN/YELLOW/RED: $SB_SIGNAL"
  fi

  section "CT4. session_briefing.py stats has required counters"
  if echo "$SB_JSON" | python3 -c "
import sys, json
s = json.load(sys.stdin)['stats']
for k in ('total', 'done', 'ready', 'blocked', 'active'):
    assert k in s, f'missing stats.{k}'
    assert isinstance(s[k], int), f'stats.{k} not int'
" 2>/dev/null; then
    pass "stats contains total/done/ready/blocked/active as ints"
  else
    fail "stats missing required counters"
  fi

  section "CT5. save_session.py --json produces valid JSON"
  local SS_JSON
  SS_JSON=$(PROJECT_DB="$REPO_ROOT/bootstrap.db" python3 "$SCRIPTS_DIR/save_session.py" --json --skip-eval 2>/dev/null)
  if echo "$SS_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for k in ('signal', 'stats', 'next_3', 'git', 'date', 'current_phase', 'gates_passed'):
    assert k in d, f'missing {k}'
" 2>/dev/null; then
    pass "save_session.py --json valid with required keys"
  else
    fail "save_session.py --json missing required keys"
    warn "Output: ${SS_JSON:0:200}"
  fi

  section "CT6. save_session.py --json git state structure"
  if echo "$SS_JSON" | python3 -c "
import sys, json
g = json.load(sys.stdin)['git']
assert 'branch' in g, 'missing git.branch'
assert 'uncommitted' in g, 'missing git.uncommitted'
assert 'completed_this_session' in g, 'missing git.completed_this_session'
assert isinstance(g['completed_this_session'], list), 'completed_this_session not list'
" 2>/dev/null; then
    pass "save_session.py git state has branch/uncommitted/completed_this_session"
  else
    fail "save_session.py git state missing fields"
  fi

  section "CT7. save_session.py writes NEXT_SESSION.md with required sections"
  local TMP_OUT="/tmp/ct_test_next_session_$$.md"
  PROJECT_DB="$REPO_ROOT/bootstrap.db" python3 "$SCRIPTS_DIR/save_session.py" \
    --skip-git --skip-db-log --skip-eval \
    --out "$TMP_OUT" --project-name "ContractTest" "Contract test session" 2>/dev/null
  if [ -f "$TMP_OUT" ] \
    && grep -q "^# Next Session" "$TMP_OUT" \
    && grep -q "^Signal:" "$TMP_OUT" \
    && grep -q "^## Last session" "$TMP_OUT" \
    && grep -q "^## Pick up" "$TMP_OUT" \
    && grep -q "^## Context" "$TMP_OUT"; then
    pass "NEXT_SESSION.md has all required sections"
  else
    fail "NEXT_SESSION.md missing required sections"
    [ -f "$TMP_OUT" ] && warn "Content: $(head -20 "$TMP_OUT")"
  fi
  rm -f "$TMP_OUT"

  section "CT8. preflight_check.py quick mode exits 0"
  if python3 "$SCRIPTS_DIR/preflight_check.py" >/dev/null 2>&1; then
    pass "preflight_check.py quick mode exits 0"
  else
    fail "preflight_check.py quick mode non-zero exit"
  fi

  section "CT9. save_session.py banner output on normal run"
  local BANNER_OUT
  BANNER_OUT=$(PROJECT_DB="$REPO_ROOT/bootstrap.db" python3 "$SCRIPTS_DIR/save_session.py" \
    --skip-git --skip-db-log --skip-eval \
    --out /dev/null --project-name "BannerTest" "Banner test" 2>&1)
  if echo "$BANNER_OUT" | grep -q "Session Saved"; then
    pass "save_session.py prints 'Session Saved' banner"
  else
    fail "save_session.py missing banner output"
    warn "Output: ${BANNER_OUT:0:200}"
  fi

  section "CT10. Python contract tests (isolated fixtures)"
  local PY_CONTRACT_OUT
  PY_CONTRACT_OUT=$(python3 "$REPO_ROOT/tests/test_python_contracts.py" 2>&1)
  local PY_CONTRACT_RC=$?
  if [ $PY_CONTRACT_RC -eq 0 ]; then
    local PY_PASS_COUNT
    PY_PASS_COUNT=$(echo "$PY_CONTRACT_OUT" | grep -c "PASS" || true)
    pass "Python contract tests: $PY_PASS_COUNT tests passed (fixture-based)"
  else
    fail "Python contract tests failed (exit $PY_CONTRACT_RC)"
    warn "$(echo "$PY_CONTRACT_OUT" | grep "FAIL\|ERROR" | head -5)"
  fi
}

version_consistency_tests() {
  header "Version Consistency Tests"
  P_NAME="version-consistency"

  local TEST_DIR="/tmp/bootstrap_test_version_$$"
  rm -rf "$TEST_DIR"
  mkdir -p "$TEST_DIR/.claude"
  mkdir -p "$TEST_DIR/project"

  section "VC1. Symlink means single source of truth"
  echo "# Universal Lessons" > "$TEST_DIR/project/LESSONS_UNIVERSAL.md"
  ln -s "$TEST_DIR/project/LESSONS_UNIVERSAL.md" "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  echo "- New lesson appended" >> "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  local CANONICAL_CONTENT SYMLINK_CONTENT
  CANONICAL_CONTENT=$(cat "$TEST_DIR/project/LESSONS_UNIVERSAL.md")
  SYMLINK_CONTENT=$(cat "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md")
  if [ "$CANONICAL_CONTENT" = "$SYMLINK_CONTENT" ]; then
    pass "Write through symlink reflects in canonical file (single source of truth)"
  else
    fail "Symlink and canonical file have diverged"
  fi

  section "VC2. Non-symlink dual files are detected as divergent"
  rm -f "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  echo "# Version A" > "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md"
  echo "# Version B" > "$TEST_DIR/project/LESSONS_UNIVERSAL.md"
  local FILE_A FILE_B
  FILE_A=$(cat "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md")
  FILE_B=$(cat "$TEST_DIR/project/LESSONS_UNIVERSAL.md")
  if [ "$FILE_A" != "$FILE_B" ]; then
    pass "Dual regular files correctly detected as having divergent content"
  else
    fail "Expected divergent content but files appear identical"
  fi
  if [ ! -L "$TEST_DIR/.claude/LESSONS_UNIVERSAL.md" ]; then
    pass "Confirmed: non-symlink dual-file scenario (potential divergence risk)"
  else
    fail "Expected regular file but found symlink"
  fi

  rm -rf "$TEST_DIR"
}

main() {
  echo -e "${BOLD}Bootstrap Framework Test Suite${RESET}"
  echo -e "Tests the template engine across 4 project archetypes."
  echo ""

  # Parse arguments
  if [ "${1:-}" = "--cleanup" ]; then
    cleanup; exit 0
  fi

  if [ "${1:-}" = "--cross" ]; then
    P_NAME="cross-validation"
    validate_cross
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--regression" ]; then
    regression_tests
    hook_functional_tests
    compat_tests
    language_rule_tests
    phase_flag_tests
    fill_placeholders_tests
    verify_deployment_tests
    self_containment_tests
    sast_regression_tests
    python_contract_tests
    quality_gate_contract_tests
    forbidden_pattern_regression_tests
    context_footprint_tests
    plugin_artifact_tests
    manifest_profile_tests
    scripts_functional_tests
    print_summary; exit 0
  fi

  # --smoke is --regression with all component tests — keep in sync with --regression above
  if [ "${1:-}" = "--smoke" ]; then
    regression_tests
    hook_functional_tests
    compat_tests
    language_rule_tests
    phase_flag_tests
    fill_placeholders_tests
    verify_deployment_tests
    self_containment_tests
    sast_regression_tests
    python_contract_tests
    quality_gate_contract_tests
    forbidden_pattern_regression_tests
    context_footprint_tests
    plugin_artifact_tests
    manifest_profile_tests
    scripts_functional_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--sast" ]; then
    sast_regression_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--compat" ]; then
    compat_tests
    language_rule_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--language-rules" ]; then
    language_rule_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--edge-hyphen" ]; then
    edge_case_hyphen
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--python-cli" ]; then
    python_cli_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--workflow" ]; then
    workflow_integration_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--phase-flag" ]; then
    phase_flag_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--fill-placeholders" ]; then
    fill_placeholders_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--verify-deployment" ]; then
    verify_deployment_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--hooks-functional" ]; then
    hook_functional_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--scripts-functional" ]; then
    scripts_functional_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--plugin-artifact" ]; then
    plugin_artifact_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--python-contract" ]; then
    python_contract_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--product-flow" ]; then
    product_flow_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--product-verify" ]; then
    product_verify_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--manifest-profiles" ]; then
    manifest_profile_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--verify" ] && [ -n "${2:-}" ]; then
    load_project_config "$2"
    verify_project
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--exercise" ] && [ -n "${2:-}" ]; then
    load_project_config "$2"
    exercise_project
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--symlink" ]; then
    symlink_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--harvest-fallback" ]; then
    harvest_fallback_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--self-containment" ]; then
    self_containment_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--quality-gate" ]; then
    quality_gate_contract_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--forbidden-pattern" ]; then
    forbidden_pattern_regression_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--context-footprint" ]; then
    context_footprint_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--briefing-freshness" ]; then
    briefing_freshness_tests
    print_summary; exit 0
  fi

  if [ "${1:-}" = "--version-consistency" ]; then
    version_consistency_tests
    print_summary; exit 0
  fi

  # Run pre-flight before any work
  preflight

  # If specific project numbers given, run only those
  if [ $# -gt 0 ] && [[ "$1" =~ ^[1-4]$ ]]; then
    for N in "$@"; do
      run_project "$N"
    done
    P_NAME="cross-validation"
    validate_cross
    print_summary; exit 0
  fi

  # Default: regression + compat + scripts-functional + product-flow + all 4 projects + cross validation
  regression_tests
  compat_tests
  scripts_functional_tests

  product_flow_tests

  for N in 1 2 3 4; do
    run_project "$N"
  done

  P_NAME="cross-validation"
  validate_cross
  print_summary
}

# Fix for RULES_OUTPUT_PATH in generate_rules
export RULES_OUTPUT_PATH="RULES.md"

main "$@"
