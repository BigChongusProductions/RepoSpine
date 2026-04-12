#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# bootstrap_project.sh — Create a new project with the full workflow engine
#
# Usage:
#   bash bootstrap_project.sh "Project Name" /path/to/project
#
# What it creates:
#   - CLAUDE.md (project entry point with @imports)
#   - PROJECT_RULES.md (from template, with placeholders)
#   - LESSONS.md, PROJECT_MEMORY.md, LEARNING_LOG.md, NEXT_SESSION.md
#   - project.db (SQLite with full schema)
#   - db_queries.sh, session_briefing.sh, coherence_check.sh, coherence_registry.sh
#   - milestone_check.sh, build_summarizer.sh, work.sh, fix.sh
#   - generate_board.py
#   - .gitignore, .claude/settings.local.json
#   - Git repo with master + dev branches
#   - Framework files in frameworks/ (bundled at activation, loaded via @imports)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Platform-aware in-place sed (macOS uses -i '', GNU/Linux uses -i)
sedi() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# Run SQL against a DB — prefers sqlite3 CLI, falls back to python3
# CRITICAL: Uses env vars (not string interpolation) to pass SQL safely —
# triple-quote '''$sql''' breaks when SQL contains single quotes (e.g. VALUES('x'))
_run_sql() {
    local db="$1"
    local sql="$2"
    if command -v sqlite3 &> /dev/null; then
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
        echo "ERROR: No sqlite3 or python3 available" >&2
        return 1
    fi
}

# Seed initial tasks and phase gates into a freshly created DB
_seed_db() {
    local db="$1"
    local lifecycle="$2"

    # Bootstrap session log
    _run_sql "$db" "INSERT INTO sessions (session_type, summary)
        VALUES ('Setup', 'Project bootstrapped with workflow engine');"

    if [ "$lifecycle" = "full" ]; then
        _run_sql "$db" "
INSERT OR IGNORE INTO tasks (id, phase, assignee, title, status, sort_order, tier)
VALUES
  ('ENV-01', 'P1-ENVISION', 'MASTER', 'Complete ENVISION spec — pitch, audience, done criteria, exclusions', 'TODO', 10, 'master'),
  ('RES-01', 'P2-RESEARCH', 'MASTER', 'Complete RESEARCH spec — prior art, options, constraints, open questions', 'TODO', 20, 'master'),
  ('DEC-01', 'P3-DECIDE', 'MASTER', 'Complete DECISIONS spec — lock stack, scope, architecture', 'TODO', 30, 'master'),
  ('SPE-01', 'P4-SPECIFY', 'CLAUDE', 'Generate requirements.md from ENVISION + RESEARCH + DECISIONS', 'TODO', 40, 'opus'),
  ('SPE-02', 'P4-SPECIFY', 'MASTER', 'Review and annotate requirements.md', 'TODO', 41, 'master'),
  ('SPE-03', 'P4-SPECIFY', 'CLAUDE', 'Generate design.md from requirements.md', 'TODO', 42, 'opus'),
  ('SPE-04', 'P4-SPECIFY', 'MASTER', 'Review and annotate design.md', 'TODO', 43, 'master'),
  ('PLN-01', 'P5-PLAN', 'CLAUDE', 'Generate task breakdown from design.md', 'TODO', 50, 'opus');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P1-ENVISION');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P2-RESEARCH');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P3-DECIDE');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P4-SPECIFY');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P5-PLAN');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P6-BUILD');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P7-VALIDATE');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P8-SHIP');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P9-EVOLVE');
"
        echo "✅ Seeded 9-phase lifecycle (P1-ENVISION through P9-EVOLVE)"
    else
        _run_sql "$db" "
INSERT OR IGNORE INTO tasks (id, phase, assignee, title, status, sort_order, tier)
VALUES ('PLN-01', 'P1-PLAN', 'CLAUDE', 'Generate task breakdown from project specs', 'TODO', 10, 'opus');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P1-PLAN');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P2-BUILD');
INSERT OR IGNORE INTO phase_gates (phase) VALUES ('P3-SHIP');
"
        echo "✅ Seeded 3-phase lifecycle (P1-PLAN → P2-BUILD → P3-SHIP)"
    fi
}

if [ $# -lt 2 ]; then
    echo "Usage: bash bootstrap_project.sh \"Project Name\" /path/to/project [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --lifecycle full|quick   Project lifecycle mode (default: full)"
    echo "  --deployment standard|extended  Deployment profile (default: standard)"
    echo "  --non-interactive        Skip all prompts, use defaults"
    echo "  --phase PHASES           Run only specified phases (comma-separated)"
    echo "  --rollback               Remove all bootstrap-created files (uses .bootstrap_manifest)"
    echo ""
    echo "Phase groups:"
    echo "  database     SQLite DB, schema, seed data, specs/"
    echo "  scripts      All shell/Python scripts (db_queries, session_briefing, etc.)"
    echo "  rules        CLAUDE.md, RULES, LESSONS, MEMORY, DELEGATION"
    echo "  hooks        .claude/hooks/ from templates"
    echo "  agents       .claude/agents/ (implementer + worker)"
    echo "  settings     .claude/settings.json + settings.local.json"
    echo "  init         .gitignore, refs/, framework verification, knowledge harvest"
    echo "  placeholders Universal %%PLACEHOLDER%% sweep (legacy — prefer fill_placeholders.py)"
    echo "  git          Git init + branch creation"
    echo ""
    echo "Examples:"
    echo "  bash bootstrap_project.sh \"My Project\" ~/Desktop/MyProject"
    echo "  bash bootstrap_project.sh \"My Project\" ~/path --lifecycle quick --non-interactive"
    echo "  bash bootstrap_project.sh \"My Project\" ~/path --deployment extended"
    echo "  bash bootstrap_project.sh \"My Project\" ~/path --phase database,scripts --non-interactive"
    echo "  bash bootstrap_project.sh \"My Project\" ~/path --rollback"
    exit 1
fi

PROJECT_NAME="$1"
PROJECT_PATH="$2"

# Parse flags
LIFECYCLE_MODE=""
DEPLOYMENT_PROFILE=""
_LIFECYCLE_EXPLICIT=false
NON_INTERACTIVE=false
PHASE_LIST=""
ROLLBACK_MODE=false
shift 2
while [ $# -gt 0 ]; do
    case "$1" in
        --deployment) DEPLOYMENT_PROFILE="${2:-standard}"; shift 2 ;;
        --lifecycle) LIFECYCLE_MODE="${2:-full}"; _LIFECYCLE_EXPLICIT=true; shift 2 ;;
        --non-interactive) NON_INTERACTIVE=true; shift ;;
        --phase) PHASE_LIST="${2:-}"; shift 2 ;;
        --rollback) ROLLBACK_MODE=true; shift ;;
        *) shift ;;
    esac
done

# ── Rollback mode ───────────────────────────────────────────────────────────
if [ "$ROLLBACK_MODE" = true ]; then
    MANIFEST="$PROJECT_PATH/.bootstrap_manifest"
    if [ ! -f "$MANIFEST" ]; then
        echo "❌ No .bootstrap_manifest found in $PROJECT_PATH"
        echo "   Rollback requires a manifest from a previous bootstrap run."
        exit 1
    fi

    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ⏪ Rolling back bootstrap: $PROJECT_NAME"
    echo "║  📁 Location: $PROJECT_PATH"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    # Read the pre-bootstrap snapshot (files that existed BEFORE bootstrap)
    # Everything in the project dir NOT in this list was created by bootstrap
    REMOVED=0

    # Build list of all current files, remove those not in the pre-bootstrap snapshot
    cd "$PROJECT_PATH"
    while IFS= read -r file; do
        [ -e "$file" ] || continue
        if ! grep -qxF "$file" "$MANIFEST"; then
            rm -f "$file"
            REMOVED=$((REMOVED + 1))
        fi
    done < <(find . -type f -not -path './.git/*' -not -name '.bootstrap_manifest' | sort)

    # Remove empty directories left behind (bottom-up), excluding .git
    find . -mindepth 1 -type d -not -path './.git/*' -not -path './.git' -empty -delete 2>/dev/null || true

    # If .git was created by bootstrap (not in pre-snapshot), remove it
    if [ -d ".git" ] && ! grep -qxF "./.git" "$MANIFEST"; then
        rm -rf .git
        echo "✅ Removed .git/ (created by bootstrap)"
    fi

    # Clean up the manifest itself
    rm -f "$MANIFEST"

    echo "✅ Rollback complete: removed $REMOVED bootstrap-created files"
    echo "   Pre-existing files preserved."
    exit 0
fi

# ── Computed values (global — used by all phase functions) ───────────────────
PROJECT_NAME_UPPER=$(echo "$PROJECT_NAME" | tr '[:lower:]' '[:upper:]' | tr ' ' '_')
PROJECT_NAME_LOWER=$(echo "$PROJECT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '_')
DB_NAME="${PROJECT_NAME_LOWER}.db"
MAC_USER=$(whoami)
RULES_FILE="${PROJECT_NAME_UPPER}_RULES.md"
LESSONS_FILE="LESSONS_${PROJECT_NAME_UPPER}.md"
MEMORY_FILE="${PROJECT_NAME_UPPER}_PROJECT_MEMORY.md"
DB_NAME_BASE="${DB_NAME%.db}"

BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$BOOTSTRAP_DIR/templates" ]; then
    _TMPL_BASE="$BOOTSTRAP_DIR/templates"
else
    echo "ERROR: Cannot find templates directory." >&2
    echo "  Expected: $BOOTSTRAP_DIR/templates" >&2
    echo "  Fix: Run from the project-bootstrap repo root." >&2
    exit 1
fi
SCRIPT_TEMPLATES="$_TMPL_BASE/scripts"
HOOK_TEMPLATES="$_TMPL_BASE/hooks"
AGENT_TEMPLATES="$_TMPL_BASE/agents"
TEMPLATE="$_TMPL_BASE/rules/RULES_TEMPLATE.md"

# ── Lifecycle mode resolution ────────────────────────────────────────────────
# When --phase is specified without --lifecycle, auto-detect from existing DB
if [ -n "$PHASE_LIST" ] && [ -z "$LIFECYCLE_MODE" ]; then
    if [ -f "$PROJECT_PATH/$DB_NAME" ]; then
        QUICK_CHECK=$(_run_sql "$PROJECT_PATH/$DB_NAME" "SELECT COUNT(*) FROM phase_gates WHERE phase='P1-PLAN'" 2>/dev/null || echo "0")
        if [ "$QUICK_CHECK" -gt 0 ]; then
            LIFECYCLE_MODE="quick"
        else
            LIFECYCLE_MODE="full"
        fi
    else
        LIFECYCLE_MODE="full"
    fi
fi

# If no lifecycle mode specified, ask interactively (unless --non-interactive)
if [ -z "$LIFECYCLE_MODE" ]; then
    if [ "$NON_INTERACTIVE" = true ]; then
        LIFECYCLE_MODE="full"
    else
        echo ""
        echo "  Choose project lifecycle mode:"
        echo ""
        echo "  [1] FULL (9-phase) — ENVISION → RESEARCH → DECIDE → SPECIFY → PLAN → BUILD → VALIDATE → SHIP → EVOLVE"
        echo "      Best for: serious projects, new domains, unfamiliar stacks"
        echo ""
        echo "  [2] QUICK (3-phase) — PLAN → BUILD → SHIP"
        echo "      Best for: small projects, known stack, clear scope already decided"
        echo ""
        read -p "  Enter 1 or 2 (default: 1): " LIFECYCLE_CHOICE
        case "$LIFECYCLE_CHOICE" in
            2) LIFECYCLE_MODE="quick" ;;
            *) LIFECYCLE_MODE="full" ;;
        esac
    fi
fi

# ── Deployment profile resolution ───────────────────────────────────────────
if [ -z "$DEPLOYMENT_PROFILE" ]; then
    DEPLOYMENT_PROFILE="standard"
fi

case "$DEPLOYMENT_PROFILE" in
    standard|extended) ;;
    *)
        echo "❌ Invalid deployment profile: $DEPLOYMENT_PROFILE (valid: standard, extended)" >&2
        exit 1
        ;;
esac

if [ "$_LIFECYCLE_EXPLICIT" = true ]; then
    echo "⚠️  --lifecycle is deprecated. Use --deployment standard|extended instead." >&2
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  🚀 Bootstrapping: $PROJECT_NAME"
echo "║  📁 Location: $PROJECT_PATH"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Directory handling ───────────────────────────────────────────────────────
if [ -z "$PHASE_LIST" ]; then
    # Full run: create directory if needed (existing behavior)
    if [ -d "$PROJECT_PATH" ]; then
        if [ "$NON_INTERACTIVE" = true ]; then
            echo "⚠️  Directory already exists: $PROJECT_PATH (continuing — non-interactive mode)"
        else
            echo "⚠️  Directory already exists: $PROJECT_PATH"
            read -p "   Continue anyway? (y/N) " CONFIRM
            if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
                echo "Aborted."
                exit 0
            fi
        fi
    else
        mkdir -p "$PROJECT_PATH"
        echo "✅ Created directory: $PROJECT_PATH"
    fi
fi

# Always validate directory exists before cd
if [ ! -d "$PROJECT_PATH" ]; then
    echo "❌ Project directory does not exist: $PROJECT_PATH"
    echo "   Run without --phase first, or create the directory manually."
    exit 1
fi

# ── Phase functions ──────────────────────────────────────────────────────────

phase_rules() {
    # Steps 1, 2, 3-6, 22: CLAUDE.md, RULES, tracking files, DELEGATION
    # ── 1. CLAUDE.md (project entry point) ──────────────────────────────────────
    cat > CLAUDE.md << 'CLAUDEEOF'
# %%PROJECT_NAME%% — Project Entry Point
> Frameworks load on demand via hooks — do NOT @-import them at startup.

@frameworks/session-protocol.md
@%%PROJECT_NAME_UPPER%%_RULES.md
@AGENT_DELEGATION.md
@ROUTER.md

> **On-demand frameworks** (loaded automatically by hooks when triggered):
> - `correction-protocol.md` — injected by correction-detector hook on correction signal
> - `delegation.md` — injected by pre-edit-check hook at delegation gate
> - `phase-gates.md` — load manually before pre-task check (`db_queries.sh check <id>`)
>
> **Optional frameworks** (add @import lines above to enable):
> `coherence-system`, `falsification`, `loopback-system`, `quality-gates`, `visual-verification`

> LESSONS file (%%PROJECT_NAME_UPPER%%_LESSONS.md) is NOT @-imported — it grows unboundedly.
> The session-start hook injects recent lessons. Read full file on demand for correction protocol.
> Path-specific rules in `.claude/rules/` auto-inject when touching matching files.
> Hooks in `.claude/hooks/` enforce behavioral gates. Custom agents in `.claude/agents/`.
CLAUDEEOF

    echo "✅ CLAUDE.md"

    # ── 2. PROJECT_RULES.md (from template) ─────────────────────────────────────
    if [ -f "$TEMPLATE" ]; then
        cp "$TEMPLATE" "$RULES_FILE"
        echo "✅ $RULES_FILE (from template — customize %%PLACEHOLDERS%%)"
    else
        echo "⚠️  Template not found at $TEMPLATE"
        echo "   Creating minimal rules file — copy template later for full version"
        cat > "$RULES_FILE" << RULESEOF
# $PROJECT_NAME — Project Rules
> Auto-imported by CLAUDE.md. Re-run bootstrap with templates for the full version.

## Project North Star
> **TODO: Define your project's north star here.**

## Tech Stack & Environment
TODO: Define your tech stack here.

## MCP Servers & Plugins Available
TODO: List your MCP servers here.
RULESEOF
        echo "✅ $RULES_FILE (minimal — install template for full version)"
    fi

    # ── 3. LESSONS file ──────────────────────────────────────────────────────────
    [ -f "$LESSONS_FILE" ] || cat > "$LESSONS_FILE" << 'EOF'
# Lessons Learned
> Updated after every correction from Master. Reviewed at session start.
> **Rule:** After ANY correction, add a row to the Corrections Log before continuing work.

## Corrections Log
| Date | What Went Wrong | Pattern | Prevention Rule |
|------|----------------|---------|-----------------|
| | | | |

## Insights
> Things discovered during development that aren't corrections but are worth remembering.

| Date | Insight | Context |
|------|---------|---------|
| | | |

## Universal Patterns
> Patterns that appear across multiple projects. Candidates for promotion into CLAUDE.md.

| Date | Pattern | Promoted to CLAUDE.md? |
|------|---------|----------------------|
| | | |
EOF
    echo "✅ $LESSONS_FILE"

    # ── 4. PROJECT_MEMORY.md ────────────────────────────────────────────────────
    [ -f "${PROJECT_NAME_UPPER}_PROJECT_MEMORY.md" ] || cat > "${PROJECT_NAME_UPPER}_PROJECT_MEMORY.md" << MEMEOF
# $PROJECT_NAME — Project Memory
> Living document. Updated when architecture changes. Read selectively per task.

## §1 — Project Overview
**What:** TODO
**Why:** TODO
**Status:** Phase 1 — Setup

## §2 — Section Lookup
| Need to know about... | Read section |
|----------------------|-------------|
| Project overview | §1 |
| Architecture | §3 |
| File structure | §4 |

## §3 — Architecture
TODO: Document your architecture here.

## §4 — File Structure
TODO: Document key files here.
MEMEOF
    echo "✅ ${PROJECT_NAME_UPPER}_PROJECT_MEMORY.md"

    # ── 5. LEARNING_LOG.md ──────────────────────────────────────────────────────
    [ -f "LEARNING_LOG.md" ] || cat > LEARNING_LOG.md << 'EOF'
# Learning Log
> Track new tools, techniques, MCPs, plugins, skills, and workflows as they're configured.

| Date | What | Category | Notes |
|------|------|----------|-------|
| | | | |
EOF
    echo "✅ LEARNING_LOG.md"

    # ── 6. NEXT_SESSION.md ──────────────────────────────────────────────────────
    [ -f "NEXT_SESSION.md" ] || cat > NEXT_SESSION.md << NSEOF
# Next Session Handoff
> Auto-generated by save-session skill. Pre-computed startup context.

## Last Session
- **Date:** $(date '+%b %d, %Y')
- **Type:** Setup
- **Summary:** Project bootstrapped. Ready for phase planning.

## Phase Gates Passed
None yet.

## Next Tasks
Define phases and populate the task database.

## Blockers
None.

## Overrides (active)
None.
NSEOF
    echo "✅ NEXT_SESSION.md"

    # ── 22. AGENT_DELEGATION.md ─────────────────────────────────────────────────
    DELEG_TEMPLATE="$_TMPL_BASE/rules/AGENT_DELEGATION_TEMPLATE.md"
    if [ -f "$DELEG_TEMPLATE" ]; then
        cp "$DELEG_TEMPLATE" AGENT_DELEGATION.md
        echo "✅ AGENT_DELEGATION.md (from template)"
    else
        echo "⚠️  Template not found at $DELEG_TEMPLATE — creating minimal version"
        cat > AGENT_DELEGATION.md << DELEGEOF
# Agent Delegation Logic
> Authoritative reference for model selection, sub-agent spawning, and failure escalation.
> 📂 Tier definitions and delegation rules in \`frameworks/delegation.md\`.

## §7 — Delegation Map
<!-- DELEGATION-START -->
No tasks defined yet. Populate the DB and run: \`bash db_queries.sh delegation-md\`
<!-- DELEGATION-END -->
DELEGEOF
        echo "✅ AGENT_DELEGATION.md (minimal)"
    fi

    # ── 23. ROUTER.md ──────────────────────────────────────────────────────────
    ROUTER_TEMPLATE="$_TMPL_BASE/rules/ROUTER_TEMPLATE.md"
    if [ -f "$ROUTER_TEMPLATE" ]; then
        cp "$ROUTER_TEMPLATE" ROUTER.md
        echo "✅ ROUTER.md (from template)"
    else
        echo "⚠️  Template not found at $ROUTER_TEMPLATE — creating minimal ROUTER.md"
        cat > ROUTER.md << ROUTEREOF
# Context Router — Reference
> This table lists on-demand context files. You don't need to memorize this.
> Hooks will remind you when to load these. Consult this table if unsure.

## On-Demand Frameworks

| Framework | File | Loaded By |
|-----------|------|-----------|
| Correction protocol | \`frameworks/correction-protocol.md\` | Hook: correction-detector.sh |
| Delegation rules | \`frameworks/delegation.md\` | Hook: pre-edit-check.sh (delegation gate) |
| Loopback system | \`frameworks/loopback-system.md\` | Hook: session-start (when loopbacks exist) |
| Phase gates | \`frameworks/phase-gates.md\` | Manual: before pre-task check |

## On-Demand Project Context

| Context | Source | When |
|---------|--------|------|
| Active delegation map | \`bash db_queries.sh delegation-md --active-only\` | Before assigning tasks |
| Architecture context | \`$MEMORY_FILE\` | Architectural questions |
| Recent lessons | \`$LESSONS_FILE\` (tail -50) | Before similar work |
ROUTEREOF
        echo "✅ ROUTER.md (minimal)"
    fi
}

phase_database() {
    # Steps 7, 7b: SQLite database + schema + seed, specs/ directory
    # ── 7. SQLite Database ──────────────────────────────────────────────────────
    # Try Python dbq init-db first (uses db.py schema — single source of truth)
    # Fall back to sqlite3 CLI if Python/dbq unavailable
    _db_created=0
    if python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
        if DB_OVERRIDE="$(pwd)/$DB_NAME" \
           DBQ_PROJECT_NAME="$PROJECT_NAME" \
           DBQ_LESSONS_FILE="$LESSONS_FILE" \
           DBQ_PHASES="" \
           PYTHONPATH="$SCRIPT_TEMPLATES" \
           python3 -m dbq init-db >/dev/null 2>&1 && [ -f "$DB_NAME" ]; then
            _db_created=1
        fi
    fi

    if [ "$_db_created" -eq 0 ]; then
        # Fallback: create schema via _run_sql (supports both sqlite3 CLI and Python)
        _SCHEMA_SQL="$(cat << 'SQLEOF'
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    queue TEXT DEFAULT 'A',
    assignee TEXT DEFAULT 'CLAUDE',
    title TEXT NOT NULL,
    priority TEXT DEFAULT 'P1',
    status TEXT DEFAULT 'TODO',
    blocked_by TEXT,
    details TEXT,
    completed_on TEXT,
    sort_order INTEGER DEFAULT 0,
    track TEXT DEFAULT 'forward',
    origin_phase TEXT,
    discovered_in TEXT,
    severity INTEGER,
    gate_critical INTEGER DEFAULT 0,
    loopback_reason TEXT,
    tier TEXT,
    skill TEXT,
    needs_browser INTEGER DEFAULT 0,
    researched INTEGER DEFAULT 0,
    breakage_tested INTEGER DEFAULT 0,
    notes TEXT,
    research_notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS phase_gates (
    phase TEXT PRIMARY KEY,
    gated_on TEXT,
    gated_by TEXT DEFAULT 'MASTER',
    notes TEXT
);
CREATE TABLE IF NOT EXISTS milestone_confirmations (
    task_id TEXT PRIMARY KEY,
    confirmed_on TEXT NOT NULL,
    confirmed_by TEXT DEFAULT 'MASTER',
    reasons TEXT
);
CREATE TABLE IF NOT EXISTS loopback_acks (
    loopback_id TEXT NOT NULL,
    acked_on TEXT NOT NULL,
    acked_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE(loopback_id)
);
CREATE TABLE IF NOT EXISTS assumptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    assumption TEXT NOT NULL,
    verify_cmd TEXT,
    verified INTEGER DEFAULT 0,
    verified_on TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS db_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,
    git_sha TEXT,
    task_summary TEXT,
    phase_gates TEXT,
    stats TEXT,
    phase TEXT,
    snapshot_at TEXT DEFAULT (datetime('now')),
    task_count INTEGER,
    file_paths TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    options TEXT,
    choice TEXT,
    rationale TEXT,
    decided_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_type TEXT DEFAULT 'Claude Code',
    summary TEXT,
    logged_at TEXT DEFAULT (datetime('now'))
)
SQLEOF
)"
        if _run_sql "$DB_NAME" "$_SCHEMA_SQL"; then
            _seed_db "$DB_NAME" "$LIFECYCLE_MODE"
            echo "✅ $DB_NAME (SQLite — 8 tables, lifecycle: $LIFECYCLE_MODE)"
        else
            echo "⚠️  Neither sqlite3 nor Python 3 available — cannot create DB"
        fi
    elif [ "$_db_created" -eq 1 ]; then
        # Python init-db created schema; seed via _seed_db
        _seed_db "$DB_NAME" "$LIFECYCLE_MODE"
        echo "✅ $DB_NAME (SQLite via Python — schema + seed, lifecycle: $LIFECYCLE_MODE)"
    fi

    # ── 7b. specs/ directory ─────────────────────────────────────────────────────
    # Always create specs/ as scaffolding — discovery skill seeds it dynamically.
    # If template specs exist, copy them; otherwise the empty dir is valid.
    mkdir -p specs
    SPEC_TEMPLATES="$_TMPL_BASE/specs"
    if [ "$LIFECYCLE_MODE" = "full" ] && [ -d "$SPEC_TEMPLATES" ]; then
        for spec in "$SPEC_TEMPLATES"/*.template.md; do
            [ -f "$spec" ] || continue
            BASENAME=$(basename "$spec" .template.md)
            TARGET="specs/${BASENAME}.md"
            cp "$spec" "$TARGET"
        done
        echo "✅ specs/ directory (from templates)"
    elif [ "$LIFECYCLE_MODE" = "quick" ] && [ -d "$SPEC_TEMPLATES" ]; then
        for spec in requirements design; do
            if [ -f "$SPEC_TEMPLATES/${spec}.template.md" ]; then
                cp "$SPEC_TEMPLATES/${spec}.template.md" "specs/${spec}.md"
            fi
        done
        echo "✅ specs/ directory (requirements, design — quick mode)"
    else
        echo "✅ specs/ directory (empty — discovery skill seeds later)"
    fi
}

phase_scripts() {
    # Steps 8-16, 24c, 26: All shell/Python scripts
    # ── 8. db_queries.sh (from template) ─────────────────────────────────────
    # Deploy from template — bundled engine handles all logic
    if [ -f "$SCRIPT_TEMPLATES/db_queries.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/db_queries.template.sh" db_queries.sh
        chmod +x db_queries.sh
        echo "✅ db_queries.sh (53 commands — from template)"
    else
        echo "⚠️  Template not found at $SCRIPT_TEMPLATES/db_queries.template.sh"
        echo "   Creating minimal db_queries.sh — update later"
        cat > db_queries.sh << DBEOF_FALLBACK
#!/usr/bin/env bash
DB="\$(dirname "\$0")/$DB_NAME"
echo "Minimal db_queries.sh — re-run bootstrap with templates for full version"
DBEOF_FALLBACK
        chmod +x db_queries.sh
    fi

    # ── 9. session_briefing.sh (from template) ───────────────────────────────────
    if [ -f "$SCRIPT_TEMPLATES/session_briefing.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/session_briefing.template.sh" session_briefing.sh
        chmod +x session_briefing.sh
        echo "✅ session_briefing.sh (from template)"
    else
        echo "⚠️  session_briefing.template.sh not found — skipping"
    fi

    # ── 10. coherence_check.sh (from template) ──────────────────────────────────
    if [ -f "$SCRIPT_TEMPLATES/coherence_check.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/coherence_check.template.sh" coherence_check.sh
        chmod +x coherence_check.sh
        echo "✅ coherence_check.sh (from template)"
    else
        echo "⚠️  coherence_check.template.sh not found — skipping"
    fi

    # ── 11. coherence_registry.sh (from template — empty starter) ───────────────
    if [ -f "$SCRIPT_TEMPLATES/coherence_registry.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/coherence_registry.template.sh" coherence_registry.sh
        chmod +x coherence_registry.sh
        echo "✅ coherence_registry.sh (empty starter — add entries as architecture evolves)"
    else
        echo "⚠️  coherence_registry.template.sh not found — skipping"
    fi

    # ── 12. milestone_check.sh (from template) ──────────────────────────────────
    if [ -f "$SCRIPT_TEMPLATES/milestone_check.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/milestone_check.template.sh" milestone_check.sh
        chmod +x milestone_check.sh
        echo "✅ milestone_check.sh (from template)"
    else
        echo "⚠️  milestone_check.template.sh not found — skipping"
    fi

    # ── 13. build_summarizer.sh (from template or stub) ──────────────────────────
    BUILD_TEMPLATE="$SCRIPT_TEMPLATES/build_summarizer.template.sh"
    if [ -f "$BUILD_TEMPLATE" ]; then
        cp "$BUILD_TEMPLATE" build_summarizer.sh
        chmod +x build_summarizer.sh
        echo "✅ build_summarizer.sh (from template — customize build commands)"
    else
        cat > build_summarizer.sh << 'BUILDEOF'
#!/usr/bin/env bash
# Build Summarizer — customize this for your project's build system
# Usage: bash build_summarizer.sh [build|test|clean]
MODE="${1:-build}"
echo "── Build Summarizer ($MODE) ──"
echo "⚠️  Stub. Copy full version from your bootstrap repo templates/scripts/"
BUILDEOF
        chmod +x build_summarizer.sh
        echo "✅ build_summarizer.sh (stub — template not found)"
    fi

    # ── 14. generate_board.py ───────────────────────────────────────────────────
    cat > generate_board.py << BOARDEOF
#!/usr/bin/env python3
"""Generate TASK_BOARD.md from the SQLite database."""
import sqlite3, os, sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "$DB_NAME")
OUTPUT = os.path.join(DIR, "TASK_BOARD.md")

if not os.path.exists(DB):
    print(f"❌ {DB} not found")
    sys.exit(1)

conn = sqlite3.connect(DB)
c = conn.cursor()

lines = [f"# $PROJECT_NAME — Task Board", f"> Generated: {datetime.now().strftime('%b %d, %Y %H:%M')}", ""]

# Get phases
c.execute("SELECT DISTINCT phase FROM tasks ORDER BY phase")
phases = [r[0] for r in c.fetchall()]

for phase in phases:
    c.execute("SELECT COUNT(*) FROM tasks WHERE phase=?", (phase,))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tasks WHERE phase=? AND status='DONE'", (phase,))
    done = c.fetchone()[0]

    # Check gate
    c.execute("SELECT gated_on FROM phase_gates WHERE phase=?", (phase,))
    gate = c.fetchone()
    gate_str = f" — GATED {gate[0]}" if gate else ""

    lines.append(f"## {phase} ({done}/{total} done{gate_str})")
    lines.append("")
    lines.append("| ID | P | Assignee | Status | Title | Blocked By |")
    lines.append("|---|---|----------|--------|-------|------------|")

    c.execute("""
        SELECT id, priority, assignee, status, title, COALESCE(blocked_by, '')
        FROM tasks WHERE phase=?
        ORDER BY sort_order, id
    """, (phase,))
    for row in c.fetchall():
        status_icon = {"DONE": "✅", "TODO": "⬜", "IN_PROGRESS": "🔵", "SKIP": "⏭️"}.get(row[3], row[3])
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {status_icon} | {row[4]} | {row[5]} |")
    lines.append("")

conn.close()

with open(OUTPUT, "w") as f:
    f.write("\\n".join(lines))
print(f"✅ TASK_BOARD.md generated ({len(phases)} phases)")
BOARDEOF
    chmod +x generate_board.py
    echo "✅ generate_board.py"

    # ── 15. work.sh ─────────────────────────────────────────────────────────────
    cat > work.sh << WORKEOF
#!/usr/bin/env bash
# $PROJECT_NAME — WORK MODE

set -euo pipefail

PROJECT="$PROJECT_PATH"
DB="\$PROJECT/$DB_NAME"

BOLD="\033[1m" GREEN="\033[32m" YELLOW="\033[33m" CYAN="\033[36m" RED="\033[31m" RESET="\033[0m"

clear
echo ""
echo -e "\${BOLD}╔══════════════════════════════════════════════════════════════╗\${RESET}"
echo -e "\${BOLD}║  🎯  $PROJECT_NAME — WORK MODE                              ║\${RESET}"
echo -e "\${BOLD}║  \$(date '+%A, %B %d, %Y')                                  ║\${RESET}"
echo -e "\${BOLD}╚══════════════════════════════════════════════════════════════╝\${RESET}"
echo ""

# Check DB
if [ ! -f "\$DB" ]; then
    echo -e "\${RED}❌ Database not found\${RESET}"
    exit 1
fi

# Backup DB
cp "\$DB" "\$DB.bak"
echo -e "\${GREEN}✅\${RESET} Database backed up"

# Clean journal
[ -f "\$DB-journal" ] && rm -f "\$DB-journal" && echo -e "\${YELLOW}⚠️\${RESET}  Cleaned stale journal"

# Git state
cd "\$PROJECT"
BRANCH=\$(git branch --show-current 2>/dev/null || echo "unknown")
if [ "\$BRANCH" != "dev" ]; then
    echo -e "\${RED}⚠️  On branch '\$BRANCH' — should be 'dev'\${RESET}"
else
    echo -e "\${GREEN}✅\${RESET} Branch: dev"
fi

# Show tasks
echo ""
bash "\$PROJECT/db_queries.sh" next
bash "\$PROJECT/db_queries.sh" master

# Signal check
BRIEFING_OUTPUT=\$(bash "\$PROJECT/session_briefing.sh" 2>&1)
if echo "\$BRIEFING_OUTPUT" | grep -q "🛑 RED"; then
    echo -e "\${RED}\${BOLD}  🛑 SESSION SIGNAL: RED — BLOCKERS\${RESET}"
    echo "\$BRIEFING_OUTPUT" | grep "❌" | sed 's/^/  /'
    echo ""
    read -p "  Launch Claude Code anyway? (y/N) " OVERRIDE
    [[ ! "\$OVERRIDE" =~ ^[Yy]$ ]] && exit 0
elif echo "\$BRIEFING_OUTPUT" | grep -q "YELLOW"; then
    echo -e "\${YELLOW}⚠️  Signal: YELLOW\${RESET}"
else
    echo -e "\${GREEN}✅ Signal: GREEN\${RESET}"
fi

# Launch
echo ""
echo -e "\${CYAN}Launching Claude Code (opusplan)...\${RESET}"
osascript -e "
tell application \"Terminal\"
    activate
    do script \"cd $PROJECT_PATH && claude --model opusplan --dangerously-skip-permissions\"
end tell
"
echo -e "\${GREEN}✅ Claude Code launched\${RESET}"
WORKEOF
    chmod +x work.sh
    echo "✅ work.sh"

    # ── 16. fix.sh ──────────────────────────────────────────────────────────────
    cat > fix.sh << FIXEOF
#!/usr/bin/env bash
# $PROJECT_NAME — FIX MODE

set -euo pipefail

PROJECT="$PROJECT_PATH"
PROBLEM="\${1:-}"

BOLD="\033[1m" GREEN="\033[32m" YELLOW="\033[33m" CYAN="\033[36m" RED="\033[31m" RESET="\033[0m"

clear
echo -e "\${RED}\${BOLD}╔══════════════════════════════════════════════════════════════╗\${RESET}"
echo -e "\${RED}\${BOLD}║  🔧  $PROJECT_NAME — FIX MODE                                ║\${RESET}"
echo -e "\${RED}\${BOLD}╚══════════════════════════════════════════════════════════════╝\${RESET}"
echo ""

cd "\$PROJECT"
BRANCH=\$(git branch --show-current 2>/dev/null || echo "unknown")
echo "  Branch: \$BRANCH"
git log --oneline -5 2>/dev/null | sed 's/^/  /'
echo ""

if [ -n "\$PROBLEM" ]; then
    INITIAL_PROMPT="Fix this issue: \$PROBLEM"
    osascript -e "
    tell application \"Terminal\"
        activate
        do script \"cd $PROJECT_PATH && claude --model claude-opus-4-6 --dangerously-skip-permissions -p \\\"\$INITIAL_PROMPT\\\"\"
    end tell
    "
else
    osascript -e '
    tell application "Terminal"
        activate
        do script "cd $PROJECT_PATH && claude --model claude-opus-4-6 --dangerously-skip-permissions"
    end tell
    '
fi
echo -e "\${GREEN}✅ Opus launched\${RESET}"
FIXEOF
    chmod +x fix.sh
    echo "✅ fix.sh"

    # ── 24c. Deploy test_protocol.sh (always) ────────────────────────────────────
    if [ -f "$SCRIPT_TEMPLATES/test_protocol.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/test_protocol.template.sh" test_protocol.sh
        chmod +x test_protocol.sh
        echo "✅ test_protocol.sh (signal validation — 8 scenarios)"
    fi

    # ── 26. Deploy missing workflow scripts ───────────────────────────────────────
    # save_session.sh
    if [ -f "$SCRIPT_TEMPLATES/save_session.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/save_session.template.sh" save_session.sh
        chmod +x save_session.sh
        echo "✅ save_session.sh (from template)"
    fi

    # shared_signal.sh
    if [ -f "$SCRIPT_TEMPLATES/shared_signal.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/shared_signal.template.sh" shared_signal.sh
        chmod +x shared_signal.sh
        echo "✅ shared_signal.sh (from template)"
    fi

    # harvest.sh
    if [ -f "$SCRIPT_TEMPLATES/harvest.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/harvest.template.sh" harvest.sh
        chmod +x harvest.sh
        echo "✅ harvest.sh (from template)"
    fi

    # db_queries_legacy.sh (bash fallback for systems without Python 3.10+)
    if [ -f "$SCRIPT_TEMPLATES/db_queries_legacy.template.sh" ]; then
        cp "$SCRIPT_TEMPLATES/db_queries_legacy.template.sh" db_queries_legacy.sh
        chmod +x db_queries_legacy.sh
        echo "✅ db_queries_legacy.sh (bash fallback — 135KB)"
    fi

    # ── 26a. verify_deployment.py (post-deploy quality check) ─────────────────────
    mkdir -p scripts
    if [ -f "$SCRIPT_TEMPLATES/verify_deployment.py" ]; then
        cp "$SCRIPT_TEMPLATES/verify_deployment.py" scripts/verify_deployment.py
        echo "✅ scripts/verify_deployment.py (18 deployment checks)"
    fi

    # ── 26a3. preflight_check.py (pre-bootstrap validation) ───────────────────────
    if [ -f "$SCRIPT_TEMPLATES/preflight_check.py" ]; then
        cp "$SCRIPT_TEMPLATES/preflight_check.py" scripts/preflight_check.py
        echo "✅ scripts/preflight_check.py (prerequisite validation)"
    fi

    # ── 26a4. session_briefing.py (signal computation + compact JSON) ─────────────
    if [ -f "$SCRIPT_TEMPLATES/session_briefing.py" ]; then
        cp "$SCRIPT_TEMPLATES/session_briefing.py" scripts/session_briefing.py
        echo "✅ scripts/session_briefing.py (signal computation + JSON output)"
    fi

    # ── 26a2. Placeholder engine (for re-running fill_placeholders) ────────────────
    for fp_file in fill_placeholders.py fp_engine.py fp_registry.py fp_replacer.py; do
        if [ -f "$SCRIPT_TEMPLATES/$fp_file" ]; then
            cp "$SCRIPT_TEMPLATES/$fp_file" "scripts/$fp_file"
        fi
    done
    echo "✅ scripts/fill_placeholders engine (4 modules)"

    # ── mark_delegation_approved.sh (delegation gate helper — root wrapper) ───────
    cat > mark_delegation_approved.sh << 'MDAEOF'
#!/bin/bash
# Wrapper — delegates to the actual script in .claude/hooks/
exec bash "$(dirname "$0")/.claude/hooks/mark_delegation_approved.sh" "$@"
MDAEOF
    chmod +x mark_delegation_approved.sh
    echo "✅ mark_delegation_approved.sh (delegation gate helper)"

    # ── 26b. dbq Python CLI engine (bundled runtime) ─────────────────────────────
    if [ -d "$SCRIPT_TEMPLATES/dbq" ]; then
        mkdir -p scripts/dbq/commands
        cp -r "$SCRIPT_TEMPLATES/dbq/"* scripts/dbq/
        rm -rf scripts/dbq/__pycache__ scripts/dbq/tests scripts/dbq/test_output_parity.py scripts/dbq/commands/__pycache__
        PY_COUNT=$(find scripts/dbq -name "*.py" 2>/dev/null | wc -l | tr -d ' ')
        echo "✅ scripts/dbq/ ($PY_COUNT Python modules — bundled CLI engine)"
    else
        echo "⚠️  dbq/ not found at $SCRIPT_TEMPLATES/dbq/ — generated project will lack CLI engine"
    fi
}

phase_frameworks() {
    # Step 26c: Copy frameworks/ into generated project (local-first, no global dependencies)
    if [ -d "$_TMPL_BASE/frameworks" ]; then
        mkdir -p frameworks
        cp "$_TMPL_BASE/frameworks/"*.md frameworks/
        FW_COUNT=$(ls frameworks/*.md 2>/dev/null | wc -l | tr -d ' ')
        echo "✅ frameworks/ ($FW_COUNT bundled — local-first, no global dependencies)"
    else
        echo "⚠️  frameworks/ not found at $_TMPL_BASE/frameworks/ — CLAUDE.md @imports will fail"
    fi
}

phase_hooks() {
    # Steps 23, 24b: Hook scripts + Xcode conditional wiring
    # ── 23. Deploy hook scripts (.claude/hooks/) ─────────────────────────────────
    if [ -d "$HOOK_TEMPLATES" ]; then
        mkdir -p .claude/hooks
        HOOK_COUNT=0
        for hook_template in "$HOOK_TEMPLATES"/*.template.sh "$HOOK_TEMPLATES"/*.template.conf; do
            [ -f "$hook_template" ] || continue
            BASENAME=$(basename "$hook_template" | sed 's/\.template\././')
            cp "$hook_template" ".claude/hooks/$BASENAME"
            chmod +x ".claude/hooks/$BASENAME" 2>/dev/null || true
            HOOK_COUNT=$((HOOK_COUNT + 1))
        done
        # Deploy .semgrepignore (doesn't match *.template.sh glob)
        if [ -f "$HOOK_TEMPLATES/.semgrepignore.template" ]; then
            cp "$HOOK_TEMPLATES/.semgrepignore.template" .claude/hooks/.semgrepignore
            HOOK_COUNT=$((HOOK_COUNT + 1))
        fi
        echo "✅ .claude/hooks/ ($HOOK_COUNT hook scripts deployed)"
    else
        echo "⚠️  Hook templates not found at $HOOK_TEMPLATES — skipping"
    fi

    # ── 24b. Xcode project detection & conditional wiring ────────────────────────
    XCODEPROJ=$(find . -maxdepth 2 -name "*.xcodeproj" -type d 2>/dev/null | head -1)
    if [ -n "$XCODEPROJ" ]; then
        echo "🔧 Xcode project detected: $XCODEPROJ"

        # Auto-detect scheme name
        XCODE_SCHEME=$(xcodebuild -list -project "$XCODEPROJ" 2>/dev/null | awk '/Schemes:/{found=1; next} found && /^$/{exit} found{gsub(/^[ \t]+/,""); print; exit}') || XCODE_SCHEME=""
        XCODE_TEST_SCHEME="${XCODE_SCHEME}Tests"
        XCODE_PROJECT_PATH="${XCODEPROJ#./}"

        if [ -n "$XCODE_SCHEME" ]; then
            echo "  Scheme: $XCODE_SCHEME | Test: $XCODE_TEST_SCHEME"
        else
            echo "  ⚠️  Could not auto-detect scheme — set %%XCODE_SCHEME%% manually"
            XCODE_SCHEME="%%XCODE_SCHEME%%"
            XCODE_TEST_SCHEME="%%XCODE_TEST_SCHEME%%"
        fi

        # Deploy Xcode build summarizer (replaces stub)
        if [ -f "$SCRIPT_TEMPLATES/build_summarizer_xcode.template.sh" ]; then
            cp "$SCRIPT_TEMPLATES/build_summarizer_xcode.template.sh" build_summarizer.sh
            chmod +x build_summarizer.sh
            echo "  ✅ build_summarizer.sh (Xcode version — auto-detect simulator)"
        fi

        # Wire check-pbxproj PostToolUse hook in settings.json
        if [ -f .claude/settings.json ] && command -v jq >/dev/null 2>&1; then
            # Add PostToolUse hook for Write events
            jq '.hooks.PostToolUse = [{"matcher": "Write", "hooks": [{"type": "command", "command": ".claude/hooks/check-pbxproj.sh", "timeout": 5}]}]' \
                .claude/settings.json > .claude/settings.json.tmp && mv .claude/settings.json.tmp .claude/settings.json
            echo "  ✅ PostToolUse hook wired for check-pbxproj.sh"
        fi
    else
        echo "ℹ️  No Xcode project found — stub build_summarizer.sh deployed"
    fi

    # ── Semgrep custom rules ──────────────────────────────────────────────────────
    if [ -d "$_TMPL_BASE/semgrep-rules" ]; then
        mkdir -p .claude/semgrep-rules
        cp "$_TMPL_BASE/semgrep-rules/"*.yaml .claude/semgrep-rules/ 2>/dev/null || true
        RULE_COUNT=$(ls .claude/semgrep-rules/*.yaml 2>/dev/null | wc -l | tr -d ' ')
        echo "✅ .claude/semgrep-rules/ ($RULE_COUNT custom rules)"
    fi
}

phase_agents() {
    # Step 25: .claude/agents/ (implementer + worker + explorer + verifier)
    # ── 25. Deploy .claude/agents/ (4 agent templates) ───────────────────────────
    if [ -d "$AGENT_TEMPLATES" ]; then
        local AGENT_COUNT=0
        for agent in implementer worker explorer verifier; do
            if [ -f "$AGENT_TEMPLATES/${agent}.template.md" ]; then
                mkdir -p ".claude/agents/${agent}"
                cp "$AGENT_TEMPLATES/${agent}.template.md" ".claude/agents/${agent}/${agent}.md"
                AGENT_COUNT=$((AGENT_COUNT + 1))
            fi
        done
        echo "✅ .claude/agents/ ($AGENT_COUNT agent configs deployed)"
    else
        echo "⚠️  Agent templates not found — skipping"
    fi
}

phase_settings() {
    # Steps 18, 24: settings.local.json + settings.json (hook wiring)
    # ── .claude/rules/ (path-specific rule injection) ────────────────────────────
    mkdir -p .claude/rules
    # ── 18. .claude/settings.local.json ─────────────────────────────────────────
    mkdir -p .claude
    cat > .claude/settings.local.json << 'SETTEOF'
{
  "permissions": {
    "allow": [],
    "deny": []
  }
}
SETTEOF
    echo "✅ .claude/settings.local.json"

    # ── 24. Deploy .claude/settings.json (hook wiring) ───────────────────────────
    SETTINGS_TEMPLATE="$_TMPL_BASE/settings/settings.template.json"
    if [ -f "$SETTINGS_TEMPLATE" ]; then
        cp "$SETTINGS_TEMPLATE" .claude/settings.json
        echo "✅ .claude/settings.json (hook wiring: 12 event hooks across 10 event types)"
    else
        echo "⚠️  Settings template not found — hooks will not be wired"
    fi
}

phase_init() {
    # Steps 17, 19, 20, 21: .gitignore, knowledge harvest, frameworks verify, refs/
    # ── 17. .gitignore ──────────────────────────────────────────────────────────
    cat > .gitignore << 'GITEOF'
# OS
.DS_Store
Thumbs.db

# Editor
.vscode/
.idea/
*.swp
*.swo

# Environment
.env
.env.local
.env*.local

# Database backups
*.db.bak
*.db-journal
*.db-wal
*.db-shm

# Node (if applicable)
node_modules/
.next/
dist/
build/

# Python (if applicable)
__pycache__/
*.pyc
.venv/
venv/
GITEOF
    echo "✅ .gitignore"

    # ── 19. Knowledge harvest (forces promotion before new project) ──────────────
    if [ -f "harvest.sh" ]; then
        echo ""
        echo "→ Running knowledge harvest before new project setup..."
        bash harvest.sh 2>&1 | grep -E "📚|✅|━━━" || true
    fi

    # ── 20. Verify local frameworks (bundled by phase_frameworks) ──
    if [ -d "frameworks" ]; then
        FW_COUNT=$(ls frameworks/*.md 2>/dev/null | wc -l | tr -d ' ')
        echo "✅ Local frameworks verified: $FW_COUNT files in frameworks/ (loaded via @import in CLAUDE.md)"
    else
        echo "⚠️  No frameworks/ directory — run with --phase frameworks or full bootstrap to bundle them"
    fi

    # ── 20b. Verify LESSONS_UNIVERSAL.md symlink ────────────────────────────────
    UNIVERSAL_SYMLINK="$HOME/.claude/LESSONS_UNIVERSAL.md"
    UNIVERSAL_CANONICAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/LESSONS_UNIVERSAL.md"
    if [ -L "$UNIVERSAL_SYMLINK" ]; then
        echo "✅ LESSONS_UNIVERSAL.md symlink verified at ~/.claude/"
    elif [ -f "$UNIVERSAL_SYMLINK" ]; then
        echo "⚠️  ~/.claude/LESSONS_UNIVERSAL.md is a regular file, not a symlink"
        echo "   To version-control it: mv ~/.claude/LESSONS_UNIVERSAL.md $UNIVERSAL_CANONICAL && ln -s $UNIVERSAL_CANONICAL $UNIVERSAL_SYMLINK"
    elif [ -f "$UNIVERSAL_CANONICAL" ]; then
        ln -s "$UNIVERSAL_CANONICAL" "$UNIVERSAL_SYMLINK"
        echo "✅ LESSONS_UNIVERSAL.md symlink created: ~/.claude/ → bootstrap repo"
    else
        echo "⚠️  No LESSONS_UNIVERSAL.md found — will be created on first promote"
    fi

    # ── 21. refs/ directory (progressive disclosure) ────────────────────────────
    mkdir -p refs
    cat > refs/README.md << 'REFSEOF'
# Reference Sub-files

This directory contains detailed reference material loaded on demand.
The main RULES file stays compact; details live here.

Add new refs as sections in RULES outgrow ~50 lines.
Replace the section with: `> 📂 Moved to refs/<name>.md — read when [trigger].`
REFSEOF
    echo "✅ refs/ directory"
}

phase_placeholders() {
    # Step 27: Placeholder resolution via fill_placeholders.py
    local FP_SCRIPT="$SCRIPT_TEMPLATES/fill_placeholders.py"
    if [ ! -f "$FP_SCRIPT" ]; then
        echo "⚠️  fill_placeholders.py not found at $FP_SCRIPT — skipping"
        return 0
    fi

    # Build --set overrides for tokens not derivable from specs
    local FP_ARGS=(
        "$PROJECT_PATH"
        --project-name "$PROJECT_NAME"
        --non-interactive
    )

    # Pass values already computed by bootstrap
    [ -n "${DB_NAME:-}" ] && FP_ARGS+=(--set DB_NAME "$DB_NAME")
    [ -n "${DB_NAME:-}" ] && FP_ARGS+=(--set PROJECT_DB "$DB_NAME")
    [ -n "${DB_NAME_BASE:-}" ] && FP_ARGS+=(--set DB_NAME_BASE "$DB_NAME_BASE")
    [ -n "${LESSONS_FILE:-}" ] && FP_ARGS+=(--set LESSONS_FILE "$LESSONS_FILE")
    [ -n "${LIFECYCLE_MODE:-}" ] && FP_ARGS+=(--lifecycle "$LIFECYCLE_MODE")
    # PERMISSION_ALLOW includes the project DB name — must be passed explicitly
    local ALLOW_LIST="Bash(bash db_queries.sh *),Bash(bash session_briefing.sh*),Bash(bash coherence_check.sh*),Bash(bash milestone_check.sh*),Bash(bash build_summarizer.sh*),Bash(python3 generate_board.py*),Bash(sqlite3 ${DB_NAME}*),Bash(git *)"
    FP_ARGS+=(--set PERMISSION_ALLOW "$ALLOW_LIST")

    python3 "$FP_SCRIPT" "${FP_ARGS[@]}" || {
        echo "⚠️  fill_placeholders.py exited with $? — some placeholders may remain"
    }

    REMAINING=$(grep -rn '%%[A-Z_]*%%' *.sh .claude/hooks/*.sh .claude/hooks/*.conf 2>/dev/null | grep -v '^#\|comment\|^.*:#' | grep -c '%%' || echo 0)
    echo "✅ Placeholder sweep complete ($REMAINING remaining in scripts)"
}

phase_git() {
    # Step 28: Git init + branches
    # ── 28. Git init ─────────────────────────────────────────────────────────────
    if [ ! -d ".git" ]; then
        git init -q
        git add -A
        git commit -q -m "Bootstrap: $PROJECT_NAME project with workflow engine"
        git branch dev 2>/dev/null || true
        git checkout -q dev
        echo "✅ Git initialized (master + dev branches, on dev)"
    else
        echo "⚠️  Git already initialized — skipping"
    fi
}

install_report() {
    local manifest="$BOOTSTRAP_DIR/SYSTEMS_MANIFEST.json"
    if [ ! -f "$manifest" ] || ! command -v jq >/dev/null 2>&1; then
        return 0  # Skip silently if no manifest or no jq
    fi

    echo ""
    echo "── Install Report (from SYSTEMS_MANIFEST.json) ──"
    echo ""

    # Count what the manifest expects vs what's on disk
    # Use a single jq call to extract all counts
    local manifest_hooks manifest_scripts manifest_agents manifest_rules manifest_settings manifest_frameworks
    eval "$(jq -r '
        "manifest_hooks=\(.summary.hooks)",
        "manifest_scripts=\(.summary.scripts.template)",
        "manifest_agents=\(.summary.agents)",
        "manifest_rules=\(.summary.rules)",
        "manifest_settings=\(.summary.settings)",
        "manifest_frameworks=\(.summary.frameworks)"
    ' "$manifest")"

    # Count installed files per category
    local installed_hooks=0 installed_scripts=0 installed_agents=0
    local installed_settings=0 installed_frameworks=0 installed_rules=0

    # Hooks: .claude/hooks/*.sh and *.conf
    if [ -d .claude/hooks ]; then
        installed_hooks=$(find .claude/hooks -maxdepth 1 \( -name '*.sh' -o -name '*.conf' \) -type f 2>/dev/null | wc -l | tr -d ' ')
    fi

    # Template scripts deployed to project root (*.sh files that came from templates)
    # Count .sh files in root that have corresponding templates
    installed_scripts=0
    for tpath in $(jq -r '.scripts[] | select(.type == "template") | .path' "$manifest" 2>/dev/null); do
        local dest_name
        dest_name=$(basename "$tpath" | sed 's/\.template\././')
        if [ -f "./$dest_name" ]; then
            installed_scripts=$((installed_scripts + 1))
        fi
    done

    # Agents: .claude/agents/*/*.md
    if [ -d .claude/agents ]; then
        installed_agents=$(find .claude/agents -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
    fi

    # Settings: .claude/settings*.json
    if [ -d .claude ]; then
        installed_settings=$(find .claude -maxdepth 1 -name 'settings*.json' -type f 2>/dev/null | wc -l | tr -d ' ')
    fi

    # Frameworks: frameworks/*.md (bundled)
    if [ -d "frameworks" ]; then
        installed_frameworks=$(find "frameworks" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
    fi

    # Rules: count .claude/rules/*.md files + project root *_RULES.md, CLAUDE.md, etc.
    installed_rules=0
    if [ -d .claude/rules ]; then
        installed_rules=$(find .claude/rules -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
    fi
    # Also count project-level rule files (CLAUDE.md, *_RULES.md, ROUTER.md, AGENT_DELEGATION.md, refs/)
    for f in CLAUDE.md *_RULES.md ROUTER.md AGENT_DELEGATION.md refs/rules-extended.md; do
        [ -f "$f" ] && installed_rules=$((installed_rules + 1))
    done

    # Print the table
    printf "  %-20s %5s %9s\n" "Category" "Avail" "Installed"
    printf "  %-20s %5s %9s\n" "────────────────────" "─────" "─────────"

    _report_line() {
        local name="$1" avail="$2" installed="$3"
        local icon="✅"
        if [ "$installed" -eq 0 ]; then
            icon="⬚ "
        elif [ "$installed" -lt "$avail" ]; then
            icon="◐ "
        fi
        printf "  %s %-18s %5d %9d\n" "$icon" "$name" "$avail" "$installed"
    }

    _report_line "Hooks"      "$manifest_hooks"       "$installed_hooks"
    _report_line "Scripts"    "$manifest_scripts"     "$installed_scripts"
    _report_line "Agents"     "$manifest_agents"      "$installed_agents"
    _report_line "Rules"      "$manifest_rules"       "$installed_rules"
    _report_line "Settings"   "$manifest_settings"    "$installed_settings"
    _report_line "Frameworks" "$manifest_frameworks"  "$installed_frameworks"

    local total_avail total_installed
    total_avail=$((manifest_hooks + manifest_scripts + manifest_agents + manifest_rules + manifest_settings + manifest_frameworks))
    total_installed=$((installed_hooks + installed_scripts + installed_agents + installed_rules + installed_settings + installed_frameworks))
    echo ""
    printf "  Total: %d / %d components installed\n" "$total_installed" "$total_avail"
}

phase_report() {
    install_report    # manifest-backed install report

    # Placeholder inventory + done banner
    # ── Placeholder inventory ─────────────────────────────────────────────────────
    echo ""
    echo "── Remaining %%PLACEHOLDERS%% to customize ──"
    PLACEHOLDER_COUNT=$(grep -rn '%%' "$RULES_FILE" 2>/dev/null | wc -l | tr -d ' ') || true
    if [ "$PLACEHOLDER_COUNT" -gt 0 ]; then
        echo "  $RULES_FILE has $PLACEHOLDER_COUNT placeholders:"
        grep -oE '%%[A-Z_]+%%' "$RULES_FILE" 2>/dev/null | sort -u | while read -r ph; do
            case "$ph" in
                %%PROJECT_NORTH_STAR%%)   echo "    $ph — your project's vision statement" ;;
                %%TECH_STACK%%)           echo "    $ph — tech stack table (framework, language, tools)" ;;
                %%COMMIT_FORMAT%%)        echo "    $ph — git commit message format" ;;
                %%BUILD_TEST_INSTRUCTIONS%%) echo "    $ph — npm/cargo/make commands for build+test" ;;
                %%OUTPUT_VERIFICATION_GATE%%) echo "    $ph — what to verify after each task" ;;
                %%PROJECT_STOP_RULES%%)   echo "    $ph — project-specific STOP conditions" ;;
                %%PROJECT_MEMORY_FILE%%)  echo "    $ph — auto: ${PROJECT_NAME_UPPER}_PROJECT_MEMORY.md" ;;
                %%FIRST_PHASE%%)          echo "    $ph — first phase name (e.g., P1-PLAN)" ;;
                *)                        echo "    $ph" ;;
            esac
        done
    else
        echo "  ✅ No placeholders remaining"
    fi

    # ── Done ─────────────────────────────────────────────────────────────────────
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ✅ $PROJECT_NAME — Bootstrap Complete!"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║                                                              ║"
    echo "║  Next steps:                                                 ║"
    echo "║  1. Edit ${RULES_FILE} — customize %%PLACEHOLDERS%%         ║"
    echo "║  2. Define phases & tasks (SQL inserts into $DB_NAME)       ║"
    echo "║  3. Open Cowork, mount this folder, brainstorm your phases  ║"
    echo "║  4. Run: bash work.sh  to start your first session          ║"
    echo "║                                                              ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
}

# ── Dispatcher ───────────────────────────────────────────────────────────────
run_phases() {
    if [ -z "$PHASE_LIST" ]; then
        # No --phase flag: run everything (backward compat)
        phase_database
        phase_scripts
        phase_frameworks
        phase_rules
        phase_hooks
        phase_agents
        phase_settings
        phase_init
        phase_placeholders
        phase_git
        phase_report
    else
        IFS=',' read -ra PHASES <<< "$PHASE_LIST"
        for phase in "${PHASES[@]}"; do
            case "$phase" in
                database)     phase_database ;;
                scripts)      phase_scripts ;;
                frameworks)   phase_frameworks ;;
                rules)        phase_rules ;;
                hooks)        phase_hooks ;;
                agents)       phase_agents ;;
                settings)     phase_settings ;;
                init)         phase_init ;;
                placeholders) phase_placeholders ;;
                git)          phase_git ;;
                *)
                    echo "⚠️  Unknown phase: $phase"
                    echo "   Available: database,scripts,frameworks,rules,hooks,agents,settings,init,placeholders,git"
                    exit 1
                    ;;
            esac
        done
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────
cd "$PROJECT_PATH"

# Capture pre-bootstrap file snapshot for rollback support
# Records all files that exist BEFORE bootstrap creates anything
_MANIFEST_FILE="$PROJECT_PATH/.bootstrap_manifest"
if [ -z "$PHASE_LIST" ]; then
    # Full run: snapshot everything currently in the directory
    find . -type f -not -path './.git/*' -not -name '.bootstrap_manifest' 2>/dev/null | sort > "$_MANIFEST_FILE"
    # Also record whether .git existed
    if [ -d ".git" ]; then
        echo "./.git" >> "$_MANIFEST_FILE"
    fi
fi

run_phases

# Write deployment profile marker (only on full runs, not --phase partial runs)
if [ -z "$PHASE_LIST" ]; then
    echo "$DEPLOYMENT_PROFILE" > .bootstrap_profile
    echo "📝 Deployment profile: $DEPLOYMENT_PROFILE (.bootstrap_profile)"
fi

# Keep the manifest for future --rollback (only on full runs)
if [ -z "$PHASE_LIST" ] && [ -f "$_MANIFEST_FILE" ]; then
    echo "📋 Rollback manifest saved (.bootstrap_manifest)"
fi
