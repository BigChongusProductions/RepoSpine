# Placeholder Registry

Complete registry of all %%PLACEHOLDER%% values and their derivation strategies.

**Token counts:** 12 auto-derivable + 4 user-provided + 12 sed `%%` tokens (rows 11-22) + 17 script-specific (incl. 3 Xcode-conditional, 2 pre-commit hook) + 2 framework-specific = **46 real substitution tokens**

Notes:
- `%%PLACEHOLDER%%` and `%%PLACEHOLDERS%%` appear in template files as meta-documentation tokens only — not substitution targets.
- `%%PERMISSION_DENY%%` is documented in the Orphaned section — not found in any current template file.
- Sed table rows 1-10 are string replacements (no `%%` wrapping); rows 11-22 are `%%` tokens.

---

## Auto-Derivable Placeholders (12 entries)

These can be extracted from context, documentation, or project structure without user input.

| # | Placeholder | Source | Files | Derivation |
|---|---|---|---|---|
| 1 | %%PROJECT_NORTH_STAR%% | Project specs | RULES_TEMPLATE.md (§ Project North Star) | Read spec.md or main README — the 1-line vision statement. If none exists, ask user: "What's this project's core purpose?" |
| 2 | %%TECH_STACK%% | package.json, setup.py, Cargo.toml, go.mod, swift files | RULES_TEMPLATE.md (§ Tech Stack) | Detect language/framework from root files. Format: "Node.js 20 + Next.js 15, TypeScript, Tailwind CSS" or equivalent for other stacks. |
| 3 | %%FIRST_PHASE%% | Task DB schema | RULES_TEMPLATE.md, AGENT_DELEGATION_TEMPLATE.md, db_queries.template.sh | Query DB: `SELECT DISTINCT phase FROM tasks ORDER BY phase_ordinal ASC LIMIT 1`. Fallback: "Phase 1" or read phase list from existing RULES.md. |
| 4 | %%MCP_SERVERS%% | Environment setup | RULES_EXTENDED_TEMPLATE.md (§ MCP Servers & Plugins) | Run: `env \| grep -i mcp` or check ~/.claude/settings.json. List connected MCPs with brief capability. Format: table with Name, Capability, Cost. |
| 5 | %%GEMINI_MCP_TABLE%% | MCP servers | RULES_EXTENDED_TEMPLATE.md (§ Gemini Integration) | Query which MCPs can delegate Gemini work (Sonnet context size, web search, image gen). Generate table: Task Type \| Gemini Tool \| When to Use. |
| 6 | %%VISUAL_VERIFICATION%% | Project type | RULES_EXTENDED_TEMPLATE.md (§ Visual Verification) | If project is CLI/backend: "Not applicable — CLI project." If web/desktop UI: generate visual verification checklist and Playwright commands. |
| 7 | %%EXTRA_MANDATORY_SKILLS%% | Skill catalog | RULES_EXTENDED_TEMPLATE.md (§ Cowork Quality Gates) | Query available skills matching project needs. List only skills that must run before merge. Format: Trigger \| Skill \| What Master Does. Default: "None additional" |
| 8 | %%RECOMMENDED_SKILLS%% | Skill catalog | RULES_EXTENDED_TEMPLATE.md (§ Cowork Quality Gates) | Query skills recommended for new phases. Format: Trigger \| Skill \| What Master Does. Default: "None additional" |
| 9 | %%EXTRA_MODEL_DELEGATION%% | Tier mapping | RULES_EXTENDED_TEMPLATE.md (§ Model Delegation) | If project uses Gemini/Grok/Ollama: add rows to delegation table. Default: leave empty (uses standard 6 tiers). |
| 10 | %%GITIGNORE_TABLE%% | Tech stack | RULES_EXTENDED_TEMPLATE.md (§ .gitignore Audit) | Generate table of file patterns to ignore: Pattern \| Reason. Include: build artifacts, dependencies, secrets, cache, language-specific. Use tech stack to customize. |
| 11 | %%OUTPUT_VERIFICATION_GATE%% | Project type | RULES_TEMPLATE.md (§ Output Verification Gate) | If project has visual output: define visual gate. If data pipeline: define data integrity gate. If API: define contract gate. If none: "Not applicable." |
| 12 | %%TEAM_TOPOLOGY%% | Agent Teams config | RULES_EXTENDED_TEMPLATE.md (§ Agent Teams) | If Agent Teams is INACTIVE: "Agent Teams mode is INACTIVE. Activate in ~/.claude/settings.json and restart." If ACTIVE: generate topology table. |

---

## User-Provided Placeholders (4 entries)

These require direct user input. Provide defaults if user doesn't answer.

| # | Placeholder | Question | Default | Files | Validation |
|---|---|---|---|---|---|
| 1 | %%COMMIT_FORMAT%% | "What commit message format does your team use?" | `type(scope): description\n\nBody (optional)\n\nCo-Authored-By: ...` | RULES_TEMPLATE.md (§ Git Branching) | Verify format includes type and scope. Run: `git log --oneline -5` to check existing commits. |
| 2 | %%BUILD_TEST_INSTRUCTIONS%% | "How do you build and test locally?" | Derive from tech stack. E.g., `npm run build && npm test` | RULES_TEMPLATE.md (§ Build & Test) | Run the command in a test session to verify it works. |
| 3 | %%CODE_STANDARDS%% | "What code quality tools do you use?" | Derive from tech stack. E.g., `ESLint, Prettier, TypeScript strict mode` | RULES_EXTENDED_TEMPLATE.md (§ Code Standards) | Verify tools exist in package.json or config. Run pre-commit hook test. |
| 4 | %%PROJECT_STOP_RULES%% | "Are there project-specific STOP rules beyond universal rules?" | Default: "None beyond universal (see CLAUDE.md §10)" | RULES_TEMPLATE.md (§ STOP Rules — Project Specific) | If any given: list them explicitly. Verify they don't conflict with universal rules. |

---

## Template Customization (22 entries via sed)

These are string replacements applied across all bootstrap files via sed. User provides the custom values once; sed applies them everywhere.

| # | Template | Replacement | Files Affected | sed Pattern |
|---|---|---|---|---|
| 1 | `master_dashboard.db` | `[project].db` | db_queries.sh, session_briefing.sh, build_summarizer.sh, all shell scripts | `sed -i 's/master_dashboard\.db/[project].db/g'` |
| 2 | `master_dashboard` | `[project]` (kebab-case) | RULES.md, AGENT_DELEGATION.md, LESSONS.md, db_queries.sh paths | `sed -i 's/master_dashboard/[project]/g'` |
| 3 | `ProjectName` | `[Project Name]` (title case) | RULES.md prose, NEXT_SESSION.md, PROJECT_MEMORY.md | `sed -i 's/ProjectName/[Project Name]/g'` |
| 4 | `LESSONS_MASTER_DASHBOARD.md` | `LESSONS_[PROJECT].md` | RULES.md @-import, db_queries.sh, git hooks | `sed -i 's/LESSONS_MASTER_DASHBOARD/LESSONS_[PROJECT]/g'` |
| 5 | `MASTER_DASHBOARD_PROJECT_MEMORY.md` | `[PROJECT]_PROJECT_MEMORY.md` | RULES.md @-import | `sed -i 's/MASTER_DASHBOARD_PROJECT_MEMORY/[PROJECT]_PROJECT_MEMORY/g'` |
| 6 | `MASTER_DASHBOARD_RULES.md` | `[PROJECT]_RULES.md` | RULES.md @-import | `sed -i 's/MASTER_DASHBOARD_RULES/[PROJECT]_RULES/g'` |
| 7 | `[absolute project path]` | `[actual project path]` (absolute) | All shell scripts (db_queries.sh, session_briefing.sh, etc.) | `sed -i 's\|[old-path]\|[new-path]\|g'` |
| 8 | `main` branch | Keep as-is | RULES.md (§ Git Branching) | If project uses different default: `sed -i 's/\bmain\b/[branch]/g'` |
| 9 | `dev` branch | Keep as-is OR customize | RULES.md (§ Git Branching) | If project uses different: `sed -i 's/\bdev\b/[branch]/g'` |
| 10 | "Master Dashboard" (title) | Project display name | README, RULES.md intro, NEXT_SESSION.md | `sed -i 's/Master Dashboard/[Display Name]/g'` |
| 11 | `%%OWN_DB_PATTERNS%%` | `project_name\.db` regex pattern | `.claude/hooks/protect-databases.template.sh` | Fill with project DB name(s) as grep regex, e.g. `my_project\.db\|news\.db` |
| 12 | `%%AGENT_NAMES%%` | Custom agent descriptions | `.claude/hooks/post-compact-recovery.template.sh` | Replace with formatted agent list for post-compaction recovery context |
| 13 | `%%TECH_STANDARDS%%` | Full tech standards block | `templates/agents/implementer.template.md` | Multi-line: concurrency rules, type safety, framework specifics for the tech stack |
| 14 | `%%TECH_STANDARDS_BRIEF%%` | Brief tech standards | `templates/agents/worker.template.md` | 3-4 key rules for single-file worker |
| 15 | `%%PERMISSION_ALLOW%%` | Permission allow array | `templates/settings/settings.template.json` | JSON array of tool permission patterns, tech-stack-specific |
| 16 | `%%LOCAL_PERMISSIONS%%` | Local permission overrides | `templates/settings/settings.local.template.json` | Empty array by default, user fills for local needs |
| 17 | `%%LESSON_LOG_COMMAND%%` | Lesson logging command | `templates/hooks/correction-detector.template.sh` | Default: `bash db_queries.sh log-lesson \"[what]\" \"[pattern]\" \"[rule]\"` |
| 18 | `%%TECH_STACK_HOOKS%%` | Tech-stack-specific hooks | `templates/agents/implementer.template.md` | Hooks specific to the tech stack (e.g., `check-pbxproj.sh` for Swift), placed in implementer agent frontmatter |
| 19 | `%%PROJECT_NAME%%` | Project name (display/slug form) | Many: implementer.template.md, worker.template.md, save_session.template.sh, fix.template.sh, work.template.sh, db_queries.template.sh, session_briefing.template.sh, all rule templates | Short identifier for the project. Used in script banners, agent prompts, and rules headers. |
| 20 | `%%PROJECT_PATH%%` | Absolute path to project root | save_session.template.sh, fix.template.sh, work.template.sh, RULES_TEMPLATE.md, RULES_EXTENDED_TEMPLATE.md | Absolute path with no trailing slash. E.g., `/Users/alice/projects/my-app`. |
| 21 | `%%PROJECT_DB%%` | SQLite database filename (with .db extension) | save_session.template.sh, db_queries.template.sh, milestone_check.template.sh, work.template.sh, session_briefing.template.sh, generate_board.template.py, protected-files.template.conf, database-safety.template.md | E.g., `my_project.db`. Used in DB_PATH construction and git-add commands. |
| 22 | `%%LESSONS_FILE%%` | Lessons/corrections log filename | db_queries.template.sh, session_briefing.template.sh, coherence_check.template.sh, harvest.template.sh, protected-files.template.conf, CLAUDE_TEMPLATE.md | E.g., `LESSONS_MY_PROJECT.md`. Matches the @-import in CLAUDE_TEMPLATE.md. |

---

## Script-Specific Substitutions (9 entries)

These tokens appear only in specific scripts and require careful derivation.

### db_queries.template.sh

| # | Placeholder | Replacement | Files Affected | How to Derive |
|---|---|---|---|---|
| 1 | `%%PHASES%%` | Space-separated phase list | db_queries.template.sh | E.g., `P1-DISCOVER P2-DESIGN P3-IMPLEMENT P4-VALIDATE`. Read from your project's planned phase structure. Used to initialize `DBQ_PHASES` env var. |
| 2 | `%%PROJECT_DB_NAME%%` | DB filename without `.db` extension | session_briefing.template.sh | E.g., `my_project` (from `my_project.db`). Used in backup filename construction. |

### dbq/tests/test_cli.py (test fixture)

| # | Placeholder | Replacement | Files Affected | How to Derive |
|---|---|---|---|---|
| 6 | `%%PROJECT_PHASES%%` | Space-separated phase list (same value as `%%PHASES%%`) | templates/scripts/dbq/tests/test_cli.py | Used in pytest monkeypatch to set the `DBQ_PHASES` env var during test runs. Same value as `%%PHASES%%` — e.g., `P1-DISCOVER P2-DESIGN P3-IMPLEMENT P4-VALIDATE`. |

### session_briefing.template.sh and related

| # | Placeholder | Replacement | Files Affected | How to Derive |
|---|---|---|---|---|
| 6 | `%%PROJECT_MEMORY_FILE%%` | Project memory markdown filename | session_briefing.template.sh, RULES_TEMPLATE.md, RULES_EXTENDED_TEMPLATE.md | E.g., `MY_PROJECT_PROJECT_MEMORY.md`. Matches the @-import in CLAUDE_TEMPLATE.md. |
| 7 | `%%RULES_FILE%%` | Project rules markdown filename | session_briefing.template.sh, CLAUDE_TEMPLATE.md, AGENT_DELEGATION_TEMPLATE.md | E.g., `MY_PROJECT_RULES.md`. Used in @-import directives and script DB_PATH lookups. |

### build-related

| # | Placeholder | Replacement | Files Affected | How to Derive |
|---|---|---|---|---|
| 8 | `%%BUILD_COMMAND%%` | Build/health-check command | templates/agents/implementer.template.md, templates/agents/verifier.template.md | The command sub-agents run after completing implementation. E.g., `bash db_queries.sh health` or `npm run build`. |
| 9 | `%%SAST_CONFIG%%` | Semgrep config for the project's tech stack | templates/rules/*-standards.template.md | Auto-derived from TechDetector. Maps primary language to Semgrep rule packs (e.g., `p/python + p/security`). Fallback: `semgrep --config=auto --severity=ERROR`. |
| 10 | `%%TECH_CONTEXT_BRIEF%%` | One-line tech stack summary | templates/agents/explorer.template.md | Brief orientation for the read-only research agent. E.g., `Python 3 + SQLite + Bash workflow engine. CLI at templates/scripts/dbq/.` |
| 11 | `%%TEST_COMMAND%%` | Test suite command | templates/agents/verifier.template.md | The test command the verifier runs after reading changes. E.g., `bash tests/test_bootstrap_suite.sh --regression` or `npm test`. |

### pre-commit hook

| # | Placeholder | Replacement | Files Affected | How to Derive |
|---|---|---|---|---|
| 11 | `%%LINT_COMMAND%%` | Linter invocation for the project's tech stack | templates/scripts/pre-commit.template.sh | Detect from root config files. E.g., `ruff check .` (Python), `eslint src/ --max-warnings 0` (Node.js), `golangci-lint run` (Go). fp_engine.py derives this from TechDetector. |
| 12 | `%%TYPE_CHECK_COMMAND%%` | Type-checker invocation for the project's tech stack | templates/scripts/pre-commit.template.sh | Detect from root config files. E.g., `mypy src/` (Python), `tsc --noEmit` (TypeScript). Set to `true` as a no-op for stacks without a type checker (e.g., plain Go). fp_engine.py derives this from TechDetector. |

### Xcode / Swift (conditional — only when .xcodeproj detected)

| # | Placeholder | Replacement | Files Affected | How to Derive |
|---|---|---|---|---|
| 9 | `%%XCODE_PROJECT_PATH%%` | Relative path to .xcodeproj | templates/scripts/build_summarizer_xcode.template.sh | E.g., `MyApp/MyApp.xcodeproj`. Auto-detected by `find . -maxdepth 2 -name "*.xcodeproj"` in bootstrap_project.sh. |
| 10 | `%%XCODE_SCHEME%%` | Xcode build scheme name | templates/scripts/build_summarizer_xcode.template.sh | E.g., `MyApp`. Auto-detected by `xcodebuild -list -project`. Fallback: ask user. |
| 11 | `%%XCODE_TEST_SCHEME%%` | Xcode test scheme name | templates/scripts/build_summarizer_xcode.template.sh | E.g., `MyAppTests`. Default: `${XCODE_SCHEME}Tests`. |

### hooks

| # | Placeholder | Replacement | Files Affected | How to Derive |
|---|---|---|---|---|
| 12 | `%%PROJECT_RULES_FILE%%` | Project rules markdown filename | templates/hooks/protected-files.template.conf | E.g., `MY_PROJECT_RULES.md`. Used as a comment reference in the protected-files config. |

---

## Framework-Specific Placeholders (2 entries)

### coherence_check.sh Skip Patterns

Replace %%SKIP_PATTERN_1%% and %%SKIP_PATTERN_2%% with project-specific paths to skip during coherence checks:

```bash
SKIP_PATTERNS=(
  "node_modules/*"
  ".git/*"
  "%%SKIP_PATTERN_1%%"     # Custom: e.g., "build/*", "dist/*"
  "%%SKIP_PATTERN_2%%"     # Custom: e.g., "coverage/*", ".next/*"
)
```

**Files:** `templates/scripts/coherence_check.template.sh`

**Common values by tech stack:**
- Node.js: `"build/*" "dist/*" ".next/*" "coverage/*"`
- Python: `"venv/*" "__pycache__/*" ".pytest_cache/*"`
- Rust: `"target/*"`
- Swift: `".build/*" "Xcode*"`

**Verification:**
```bash
bash coherence_check.sh --quiet   # Should not warn about skipped dirs
```

---

## Orphaned Registry Entries (not found in any template)

These entries were documented in prior versions but the corresponding token no longer appears in any template file. Kept here for historical reference.

| Placeholder | Last Documented Location | Status | Notes |
|---|---|---|---|
| `%%PERMISSION_DENY%%` | `.claude/settings.json` | **Orphaned** | Token not found in `templates/settings/settings.template.json`. The deny list may be hardcoded in the template now. Verify before removing. |

---

## Meta-Tokens (not substitution targets)

These tokens appear in template files as documentation examples or comments — they are NOT replaced by sed during bootstrap activation.

| Token | Location | Purpose |
|---|---|---|
| `%%PLACEHOLDER%%` | templates/scripts/README.md | Generic reference to "a placeholder token" in prose |

---

## Hardcoded Paths Section

Multiple scripts contain absolute paths that must be customized for each project:

**Files to update:**
- `db_queries.sh` — Line ~15: `DB_PATH="%%PROJECT_PATH%%/[project].db"`
- `session_briefing.sh` — Line ~8: Same DB_PATH
- `build_summarizer.sh` — Line ~10: Same DB_PATH, plus build command path
- `work.sh` — Line ~5: Project root path
- `fix.sh` — Line ~5: Project root path
- All references to `%%PROJECT_PATH%%/NEXT_SESSION.md` → `[project_path]/NEXT_SESSION.md`

**Verification command:**
```bash
grep -rn '%%PROJECT_PATH%%\|%%PROJECT_NAME%%' . --include="*.sh"
```

Should return zero results after `fill_placeholders.py` runs. Any matches indicate missed replacements.

---

## Quick Verification

After all replacements, run:

```bash
grep -rn '%%' . --include="*.md" --include="*.sh" --include="*.json" --include="*.conf"
```

Should return zero results (excluding this registry file itself and any `templates/` source files). If any remain, they are either:
1. Missed substitutions — fix them
2. In non-template files (skills, bootstrap_project.sh) — document separately
3. In the registry itself — expected

**Token count check:**
```bash
grep -roh '%%[A-Z_]*%%' templates/ | sort -u | grep -v -e '%%PLACEHOLDER%%' -e '%%PLACEHOLDERS%%' | wc -l
```

Should return **39** (the real substitution tokens). Discrepancies indicate new tokens were added to templates without being registered here.
