# Changelog

All notable changes to project-bootstrap are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

### v1.0.0
- **Public release as RepoSpine** — sanitized public repo export via `export_public.sh` with whitelist manifest (`public_manifest.txt`), 33 verification checks, neutral git identity, path safety blocklist
- **4-model adversarial review** — pre-release validation with Gemini Pro, Ollama gemma4, Opus code-reviewer, and code-simplifier. 8 findings fixed: YAML colon-space parse failure, path injection, V07 coverage gap, developer identity leak
- **111 integrated components** — 10 frameworks, 19 hooks, 4 agents, 18 deployment checks, 12 rules, 15 dbq commands, 29 scripts, 2 settings templates
- **264 tasks completed** across 12 phases (P1-DISCOVER through P4-VALIDATE)
- **Documentation suite** — getting-started, workflow, how-it-works, components, migration, troubleshooting
- **CI pipeline** — regression (172 checks), Python CLI (5), validate_build (7), plugin build, product-flow lifecycle

### v0.16.0
- **Development discipline framework** — TDD iron law, debugging methodology, anti-rationalization tables, 3-fix architectural pause (advisory). New `development-discipline.md` framework (10th), surfaced via `db_queries.sh check` advisory on GO/CONFIRM/loopback tasks. Verifier agent updated with discipline-informed inspection.
- **Semgrep hardening** — resilient env setup for trust-store/X509 and path failures across all SAST call sites (health.py, pre-commit, build summarizer, static-analysis gate, session-start prewarm). Local `.semgrep/` config replaces `--config=auto` in automation. Targeted startup warnings replace generic error blobs.
- **Bug fixes** — cmd_confirm test signature drift (6 failures), ROUTER.md drift vs template, cmd_check framework path references

### v0.15.1
- **Cross-project promote** — `promote --source-file <path> --source-project <name>` marks entries as promoted in any project's LESSONS file, not just the current project. Closes the harvest-global/promote-local gap
- **`harvest --mark-dupes`** — Auto-marks entries that score above the dedup threshold as promoted in source files
- **`No — project-specific` triage status** — New convention for entries reviewed but intentionally not promoted. All scanners (check_all_projects.sh, harvest.sh, dbq harvest) now skip these entries
- **Lesson triage** — 50 unpromoted lessons across RomaniaBattles (39) and MasterDashboard (11) triaged: 4 promoted to universal, 17 marked as already-in-universal, 29 marked project-specific

### v0.15.0
- **LESSONS injection into sub-agents** — `agent-spawn-gate.sh` injects tail of project LESSONS file into sub-agent context via `additionalContext`, preventing repeated mistakes across spawns. Size-aware: 30 lines for normal files, 15 lines for >20KB
- **Parallel-work guard** — Agent spawn gate detects recent (<5min) prior spawns and injects `--files` reminder to prevent auto-commit cross-contamination
- **`dbq lint` command** — 6 structural checks: dead glob patterns (L1), wrong field names (L2), broken @-imports (L3), unfilled placeholders (L4), missing test modules (L5), agent tool contradictions (L6). `quick_lint()` (L1-L3) integrated into `dbq health`
- **Verify signal in `cmd_done`** — Sonnet/Opus-tier tasks print `VERIFY RECOMMENDED` with file list on completion; also fires for any task touching 4+ files
- **ROUTER.md template** — New `ROUTER_TEMPLATE.md` with placeholder substitution; `bootstrap_project.sh` and test suite now generate ROUTER.md during setup (fixes 16 test failures from missing @-import)
- **Drift checker fixes** — C1 path-ref scanner now skips blockquote lines and @-import prefixes (eliminates false positives on documentation text)
- **Lint placeholder filter** — L4 check strips backtick-quoted content before scanning (prevents false positives on placeholder documentation)
- **64 new pytest tests** — `test_lint.py` (44 tests across L1-L6 + integration), `test_verify_signal.py` (20 tests for tier/file-count thresholds)
- **299/299 E2E + 423 pytest** — Zero pre-existing failures

### v0.14.0
- **SAST integration** — PostToolUse hook (`static-analysis-gate.template.sh`) scans edited files with Semgrep + Gitleaks in ~1s. Pre-commit template implements Gate 1. 2 custom rules (`no-bare-exit`, `no-direct-sqlite`) with zero false positives on dbq. `.semgrepignore` template, session-start rule warmup, quality-gates v3.0 with SAST rows
- **Build summarizer rewrite** — Stub replaced with 180-line implementation; SAST as first-class build step
- **Health SAST signal** — `health.py` integrates 3-state SAST check (clean/findings/error)
- **README drift hook** — `readme-drift-check.sh` auto-validates version, systems count, hooks count, and verification count on VERSION edit
- **Harvest automation** — Briefing shows per-project breakdown when >20 unpromoted, signal escalates to YELLOW at >50. Provenance tags on promote command (`--method correction|audit|harvest|manual`)
- **`done --files` flag** — Stages only specified files, prevents cross-contamination in parallel sub-agent work. Mandatory for all parallel agent workflows
- **Sub-agent delegation pre-approval** — `agent-spawn-gate.sh` auto-resets delegation state when allowing spawn; `pre-edit-check.sh` detects worktree context and downgrades to advisory
- **Worktree isolation documented** — Investigation confirmed `isolation: "worktree"` is git-branch isolation only, not filesystem isolation. Leak vectors and mitigations documented in lessons
- **Briefing dependency-aware counts** — "ready" and "blocked" now match `next` output
- **8 SAST regression tests** — 80/80 Bash regression, 359 pytest, 67 dbq commands, 18 template hooks, 2 custom Semgrep rules

### v0.13.2
- **Lesson harvest & enforcement** — Promoted 6 new + strengthened 3 existing patterns in LESSONS_UNIVERSAL.md (45 → 51). Three lessons implemented as code: `sync-check` scans git log for reverse drift (committed but not DONE), `done` cleans agent worktrees before auto-commit, `done` prints delegation reminder at task boundary
- **INBOX phantom fix** — `done` now normalizes `queue` field on completion; INBOX queries filter by status consistently across `inbox`, `sync-check`, and `delegation-md`
- **Collision avoidance hardened** — `quick`/`quick --loopback` now loop a-z suffixes instead of single 'a' append (prevents PK crash on rapid creation)
- **git add error handling** — Auto-commit checks `git add` return code and rolls back DB on staging failure
- **WONTFIX filter alignment** — All delegation.py status filters now include WONTFIX consistently with tasks.py

### v0.13.0
- **Prerequisite system** — Three-layer environment validation: plugin-level quick check (SessionStart hook), pre-bootstrap full preflight (`preflight-check.sh --full`), and post-deploy health check (`post-bootstrap-health.sh`). Checks 13 conditions across tools, versions, environment, structure, and platform.
- **`prerequisites.json` manifest** — Machine-readable dependency declaration with per-platform install commands, structural requirements, and platform compatibility notes
- **Fixed broken plugin hooks** — `hooks.json` referenced two non-existent scripts (`delegation-reminder.sh`, `session-start-check.sh`); replaced with working `preflight-check.sh`. Removed superseded PreToolUse hook (delegation checking is per-project).
- **Build-time hook validation** — `build_plugin.sh` now verifies all hooks.json script references exist before packaging, preventing silent hook failures
- **Actionable error messages** — `bootstrap_project.sh` template-not-found error now shows all 3 searched paths and fix instructions
- **66 dbq commands** (was 51), 17 template hooks (was 8), 72/72 Bash + 42/42 pytest passing

### v0.12.1
- **C11 version drift checker** — `check_version_consistency()` compares VERSION vs plugin.json, reports `VERSION_MISMATCH` as error (10-point penalty)
- **Post-version-bump auto-sync** — `post-version-bump.sh` hook updates plugin.json in-place before building zip

### v0.12.0
- **JSON export/import** — `dbq export` (full DB to JSON, `--table` filter, `--pretty`), `dbq import` (merge or `--replace` mode), column intersection handles schema drift
- **Portability hardening** — `sedi()` helper for cross-platform `sed -i`, jq/python3/git prerequisite checks in session-start hook, `grep -P` eliminated from templates
- **New tests** — C3a (sedi multi-line insertion), H18 (prerequisite check JSON validity); 72/72 Bash, 42/42 pytest

### v0.11.0
- **Delegation enforcement** — 4 new hooks enforcing 9 delegation rules: agent-spawn-gate, subagent-delegation-check, pre-edit-check (delegation gate with edit counter), escalation-tracker
- **Tier-up workflow** — `dbq tier-up` records escalations with reason taxonomy (prompt/context/ceiling/environment)

### v0.10.0
- **Sub-agent infrastructure** — 2 new agent types: explorer (read-only research, Haiku) and verifier (post-implementation review, Haiku with Bash); templates + meta-project instances for both
- **Escalation tracking** — `tier-up` command records tier escalations with reason taxonomy (prompt/context/ceiling/environment), `original_tier` column preserves initial triage assignment, eval P8 "Escalation Rate" metric added to Layer 2
- **Bug fixes** — worker agent Bash drift (meta-project frontmatter aligned with template), missing SubagentStart hook added to meta-project settings.json, inbox `cmd_inbox` now filters SKIP/DONE/WONTFIX items, pre-existing lesson test fixture missing header row
- **Test coverage** — 15 new Python tests (11 tier-up, 3 P8 eval, 1 triage original_tier), 331/331 Python tests passing, 70/70 Bash regression
- **Placeholder registry** — 2 new tokens registered (%%TECH_CONTEXT_BRIEF%%, %%TEST_COMMAND%%), count updated to 43

### v0.9.2
- **Context routing** — ROUTER.md reference table, BOOTSTRAP_RULES.md slimmed from 400+ to 285 lines, 4 new `.claude/rules/` files for path-specific injection, CLAUDE.md reduced to 3 core @-imports (frameworks loaded on-demand via hooks)
- **Hook enhancements** — correction-detector, task-intake-detector, pre-edit-check, session-start, and end-of-turn hooks with routing hints pointing to on-demand frameworks; delegation gate with edit counter and approval tracking
- **Drift detection** — `bash db_queries.sh drift` with 5 checkers (path-refs, framework-sync, placeholder-registry, staleness, delegation-coherence), `--json`/`--quiet` modes, session-start warning when score < 80
- **Automated hook tests** — 17 functional I/O contract tests (H1-H17) covering all 5 routing hooks, wired into `--regression` suite
- **dbq commands** — `loopback-count`, `loopback-summary`, `delegation-md --active-only`, `drift`

### v0.9.1
- **Code review fixes** — manifest snapshot no longer includes itself (self-reference bug), C17 contamination filter tightened to only skip absolute paths (relative path contamination like `Foo/bar` now correctly flagged), removed dead variable

### v0.9.0
- **3-layer eval system** — `bash db_queries.sh eval` scores projects across deployment quality (D1-D8), process health (P1-P7), and improvement velocity (V1-V4) with composite scoring, remediation engine, and eval-compare for tracking progress over time
- **fill_placeholders.py** — 41-token registry, `re.sub` engine, `--dry-run` / `--json` modes, split into 4 modules (registry, engine, replacer, cli)
- **verify_deployment.py** — 17 deployment checks with JSON output, `--check` filtering, exit codes; E2E tests now pass 17/17 across all 4 archetypes
- **bootstrap_project.sh refactored** — 28 phases extracted into functions, `--phase` flag for selective re-runs, `--rollback` flag with snapshot-based manifest for clean undo
- **SKILL.md Phase D rewrite** — 11 steps compressed to 7, programmatic + LLM hybrid approach
- **CLAUDE_TEMPLATE @-import reduction** — 4 startup imports reduced to 1, frameworks now injected on-demand via hooks
- **Test suite expanded** — 296 E2E checks across 4 archetypes, pytest coverage for 31+ dbq commands, parametrized tests with 2+ assertions/test, cross-project compat tests for 7 language rule templates
- **6-phase codebase audit** — sqlite3 CLI portability, stale hardcoded paths, 14 script smoke tests, dead code removal, platform guards (osascript), hook command validation
- **Bug fixes** — init-db without pre-existing DB, --phase database flag, --phase scripts preserving DB, C17 path-only match filtering, BASH_SOURCE resolution in verify_project

### v0.6.1
- **Audit fixes** — added YAML header to loopback-system.md, removed dead `--frameworks` flag, fixed apply_backlog.sh path resolution, standardized framework source attribution, documented optional frameworks in CLAUDE_TEMPLATE.md
- **Non-interactive mode** — added `--non-interactive` flag to bootstrap_project.sh for unattended bootstrapping
- **E2E test** — added test_bootstrap_e2e.sh for full + quick lifecycle validation

### v0.6.0
- **Standalone repo** — extracted from ~/.claude/ into git-tracked repository with symlinks
- **Framework deduplication** — RULES_TEMPLATE.md now @imports frameworks instead of inlining (-56%, 285→126 lines)
- **RULES_EXTENDED_TEMPLATE.md** trimmed — removed blocker detection, context management, sub-agent rules now in frameworks (-25%, 216→163 lines)
- **CLAUDE_TEMPLATE.md** adds 4 framework @imports (session-protocol, phase-gates, correction-protocol, delegation)
- **New AGENT_DELEGATION_TEMPLATE.md** — extracted from production Romania Battles project (50 lines, fully deduped)
- **Removed Lite engine tier** — unified to single Full engine for all projects
- **Removed 5 Lite template files** (RULES_TEMPLATE_LITE, CLAUDE_TEMPLATE_LITE, db_queries_lite, settings_lite, session-start-check-lite)
- **Synced loopback-system.md** template to match deployed version (-45 lines)
- **bootstrap_project.sh** moved into repo (was only in ~/.claude/templates/)
- Description updated: mentions Python CLI and consolidated pre-edit hooks
- Added keywords: hooks, agents, settings, rules

### v0.5.0
- bootstrap-activate SKILL.md expanded (425→608 lines) — hooks, agents, settings, rules deployment
- 3 commands updated (activate-engine, setup-templates, spec-status)
- 4 reference files updated
- Plugin keywords expanded

### v0.4.0
- Removed end-session skill
- Updated placeholder-registry.md (+6 entries)

### v0.3.0
- Added loopback-system.md as 9th framework file
- Added refs-scaffolding.md for progressive disclosure
- Added gotcha generation protocol
- D7 verification expanded to 12 checks
- 100% coverage against Battles framework reference

### v0.2.0
- Added Phase D (Engine Deployment) with 7 sub-steps
- Added FRAMEWORK.md as 4th spec file (now INFRASTRUCTURE.md in v0.7.0)
- Added Round 4 (Framework Configuration) to discovery interview
- Added `/setup-templates` command
- 33/33 systems coverage
- 30 %%PLACEHOLDER%% values documented, 51 db_queries.sh commands

### v0.1.0
- Initial release: discovery interview + basic activate flow
