---
name: bootstrap-activate
command: /activate-engine
description: >
  Use this skill when the user runs /activate-engine, or says "activate the engine",
  "set up the workflow", "fill placeholders", "generate requirements", or any phrase
  indicating they want to transition from discovery specs to a working project with
  a populated task database and fully operational workflow engine. Prerequisites:
  VISION.md, BLUEPRINT.md, and INFRASTRUCTURE.md must exist in specs/ with no TODO
  placeholders. Typically triggered after bootstrap-discovery completes in Cowork.
version: 0.2.0
---

# Bootstrap Activate

Transform completed discovery specs into a fully operational project with populated task database, filled configuration, generated requirements/design documents, active workflow engine, quality gates, Claude Code hooks, and all protocol documentation.

## Prerequisites Check (Phase A)

Before doing anything, verify ALL of these:

0. **Environment preflight:** Run the prerequisite checker:
   ```bash
   bash "$CLAUDE_PLUGIN_ROOT/skills/bootstrap-activate/references/hooks/preflight-check.sh" --full --project-dir "$(pwd)"
   ```
   - Exit code 1 → STOP. Show the failure report and install commands to the user. Do not proceed.
   - Exit code 2 → Show warnings to the user but proceed with bootstrap.
   - Exit code 0 → All prerequisites met. Continue to step 1.

1. `specs/VISION.md` exists and contains no "TODO" text
2. `specs/BLUEPRINT.md` exists and contains no "TODO" text
3. `specs/RESEARCH.md` exists and contains no "TODO" text
4. `specs/INFRASTRUCTURE.md` exists and contains no "TODO" text
5. `.bootstrap_mode` file exists and contains `SPECIFICATION`

If `NEXT_SESSION.md` exists with `Handoff Source: COWORK`, read it for context about what was decided during discovery.

---

## Phase B: Specification

### B1: Project Scaffolding

Read BLUEPRINT.md to extract the tech stack and project structure. Create:

1. The directory structure specified in BLUEPRINT.md "Project Structure" section
2. A `.gitignore` appropriate for the chosen tech stack
3. `refs/README.md` — progressive disclosure directory
4. `backups/` directory for DB backups
5. Copy `frameworks/` directory from `$CLAUDE_PLUGIN_ROOT/engine/templates/frameworks/`
6. Initialize git repo if not already initialized, create `dev` branch, make initial commit

### B2: Fill Placeholders

Read `references/placeholder-registry.md` for the complete list of `%%PLACEHOLDER%%` values and where each gets its value.

For each placeholder:
1. Check if the value can be auto-derived from BLUEPRINT.md or INFRASTRUCTURE.md (most can)
2. For values that require user input, ask using AskUserQuestion (batch related questions)
3. Perform the replacement across all files that contain the placeholder
4. After all replacements, verify: `grep -rn '%%' *.md *.sh` across all project files — must be zero matches

Present a summary of what was filled and ask user to confirm.

### B3: Generate requirements.md

Read all four spec files. Generate `specs/requirements.md` using EARS format:
- "When [trigger], the system shall [behavior]"
- "The system shall [behavior] [constraint]"

Every requirement must be:
- Directly testable (you can write a test for it)
- Traced to a scope item in BLUEPRINT.md
- Assigned a unique ID (FR-01, FR-02, NFR-01, etc.)

Present requirements.md to the user for review. Address any `> NOTE:` annotations they add. Iterate until clean (zero unresolved notes).

### B4: Generate design.md

Read requirements.md + BLUEPRINT.md. Generate `specs/design.md` covering:
- System architecture (expand on the diagram from BLUEPRINT.md)
- Data models with field types and constraints
- Component breakdown mapped to requirements (FR-XX)
- Key technical decisions with rationale
- Error handling strategy
- Testing strategy

Present design.md to the user for review. Address all annotations. Iterate until clean.

### B5: Specification Gate

Before proceeding to planning, verify:
- requirements.md has zero open questions
- design.md has zero `> NOTE:` annotations
- All placeholders are filled (zero `%%` matches)
- User explicitly says "approved" or "go"

---

## Phase C: Planning

### C1: Generate Task Breakdown

Read design.md. Break it into implementation phases. For each phase, create atomic tasks.

**Phase naming:** Use a prefix-name format. See `references/phase-planning-guide.md` for templates by project type (Web/Desktop, CLI, API).

**Task format:**
```
| ID | Phase | Title | Assignee | Tier | Blocked By |
```

**Pre-phase delegation map is MANDATORY.** Before presenting tasks, produce a delegation table mapping every task to a tier with justification:

| Tier | Model | Cost | When to Use |
|------|-------|------|-------------|
| **Opus** | claude-opus-4-6 | $$$$ | Architecture, gate reviews, judgment calls, anything that failed at lower tier |
| **Sonnet** | claude-sonnet-4-6 | $$ | Multi-file features, cross-file reasoning, non-trivial state/animation |
| **Haiku** | claude-haiku-4-5 | $ | Single-file, config, clear spec, no judgment needed |
| **MASTER** | Human | — | Design decisions, external config, device testing, final review, asset creation |
| **Gemini** | via MCP | varies | Large context, web research, image gen, translation (if in tech stack) |
| **Grok** | via MCP | $ | X/Twitter search, real-time web, Aurora image gen, cheap inference (if in tech stack) |
| **Ollama** | local | free | Local LLM tasks, semantic similarity (if in tech stack) |

**Never assign Haiku to:** tasks where wrong = significant rework, complex state logic, or 3+ file context.

**Failure escalation rule:** Haiku fails 2x → Sonnet. Sonnet fails 2x → Opus direct. Log every escalation.

Present the full delegation table to the user. **Wait for approval before proceeding.**

### C2: Populate Database

1. **Copy db_queries.sh** from `$CLAUDE_PLUGIN_ROOT/engine/templates/scripts/dbq/db_queries.template.sh`
2. **Customize** — run sed replacements for project-specific values (DB name, project name, LESSONS file name). See `references/placeholder-registry.md` "Template Customization" section.
3. **Create the database** — `touch [project].db && bash db_queries.sh init-db` (creates all tables: tasks, phase_gates, milestone_confirmations, loopback_acks, assumptions, db_snapshots, decisions, sessions). Then run `bash db_queries.sh health` to verify. **Do NOT use `health` to create the schema** — `health` only checks tables, it does not create them.
4. **INSERT all tasks** with full metadata: id, phase, assignee, title, priority, tier, skill, needs_browser, sort_order, blocked_by, track='forward'
5. **Fill `phase_ordinal()` function** — derive ordinals from task breakdown:
   ```bash
   # Collect unique phases in order, assign 0, 1, 2, ...
   phase_ordinal() {
       case "$1" in
           P0-FOUNDATION) echo 0 ;;
           P1-CORE) echo 1 ;;
           # ... one line per phase
           *) echo 99 ;;
       esac
   }
   ```
   The `%%PHASE_ORDINALS%%` marker appears in **3 places** in db_queries.sh, but only **2 need case blocks filled**:
   - Location 1 (~line 88): the `phase_ordinal()` bash function body
   - Location 2 (~line 807): the `(N - CASE t.phase ...)` SQL scoring formula — set `N` = number of phases (e.g. `6` for 6-phase, `5` for 5-phase)
   - Location 3 (~line 1744): uses `SELECT DISTINCT phase FROM phase_gates` — dynamic, no filling needed

   Always search `%%PHASE_ORDINALS%%` and verify all three locations are handled.
6. **Verify:** `bash db_queries.sh verify` (DB integrity) + `bash db_queries.sh health` (pipeline) + `bash db_queries.sh next` (task queue)

### C3: Activate Delegation Map

Run `bash db_queries.sh delegation-md` to generate the delegation map in AGENT_DELEGATION.md from the database. This replaces any placeholder content.

---

## Phase D: Engine Deployment

Deploy the full project infrastructure in 7 steps. Steps 1, 5, 6, 7 are programmatic (single commands). Steps 2, 3, 4 require LLM reasoning.

**Prerequisites:** Phase C complete (DB populated, delegation map generated).

### Step 1: Deploy Database + Scripts (Programmatic)

```bash
bash "$CLAUDE_PLUGIN_ROOT/engine/bootstrap_project.sh" "$PROJECT_NAME" "$PROJECT_PATH" \
  --phase database,scripts \
  --lifecycle full \
  --non-interactive
```

Deploys: SQLite DB with schema + seed, specs/, all workflow scripts (db_queries.sh, session_briefing.sh, build_summarizer.sh, etc.), refs/ scaffolding.

**Verify:** `bash db_queries.sh health && bash db_queries.sh next`

**Post-step:** Customize `build_summarizer.sh` for the project's actual tech stack. The template deploys a stub — replace with real build/test commands. See `references/quality-gates-guide.md`.

### Step 2: Generate RULES.md (LLM Reasoning)

Generate `[PROJECT]_RULES.md` from template at `$CLAUDE_PLUGIN_ROOT/engine/templates/rules/RULES_TEMPLATE.md`.

**All 29 sections must be present (28 numbered + §13b Loopback System):**

1. **Project North Star** — from `%%PROJECT_NORTH_STAR%%`
2. **Session Start Protocol** — mandatory. References: `db_queries.sh phase/blockers/gate/next`, `session_briefing.sh`, `NEXT_SESSION.md`, `PROJECT_MEMORY.md`. Signal interpretation (GREEN/YELLOW/RED). Hook-enforced via session-start-check.sh (deployed in Step 5).
3. **Phase Gate Protocol** — mandatory. Audit process, must-fix/follow-up categorization, `db_queries.sh gate-pass`.
4. **Blocker Detection Rules** — mandatory. Continuous detection, override mechanism, logging.
5. **Pre-Task Check** — mandatory. `bash db_queries.sh check <task-id>` with GO/CONFIRM/STOP verdicts.
6. **Task Workflow** — mandatory. `db_queries.sh next` queue (FORWARD/loopback/BLOCKED sections), marking done immediately.
7. **Adding New Tasks** — mandatory. Quick capture (`db_queries.sh quick`), loopback capture with severity S1-S4, triage from inbox.
8. **Tech Stack & Environment** — from `%%TECH_STACK%%`
9. **Git Branching** — mandatory. Always dev, never main, commit format from `%%COMMIT_FORMAT%%`, atomic commits.
10. **Milestone Merge Gate** — mandatory. `bash milestone_check.sh <PHASE>`.
11. **Build & Test** — from `%%BUILD_TEST_INSTRUCTIONS%%`
12. **Code Standards** — from `%%CODE_STANDARDS%%`. Path-specific rules in `.claude/rules/` auto-inject on matching files.
13. **Tracking Files** — mandatory. After each task: mark DONE in DB, update PROJECT_MEMORY, update LEARNING_LOG, update LESSONS, commit.
13b. **Loopback System** — mandatory. Severity S1-S4, circuit breaker, gate-critical loopbacks, loopback commands in db_queries.sh. See `frameworks/loopback-system.md`.
14. **Coherence Check** — mandatory. Pre-commit hook runs `coherence_check.sh --quiet`. How to add entries to `coherence_registry.sh`.
15. **.gitignore Audit** — mandatory. Post-task audit for new file types, secrets check.
16. **Correction Detection Gate** — mandatory HARD gate. Hook-enforced (`.claude/hooks/correction-detector.sh`). FIRST tool call = log the lesson.
17. **Delegation Gate** — mandatory HARD gate. Hook-enforced (`.claude/hooks/delegation-reminder.sh`). Produce delegation table before any multi-step task.
18. **Output Verification Gate** — conditional. From `%%OUTPUT_VERIFICATION_GATE%%`.
19. **Lesson Extraction + Gotcha Generation** — mandatory. Before session end: scan for corrections, retries, false assumptions, new tools. Propose lessons. Gotcha trigger: 2+ corrections in same domain → update `refs/gotchas-[domain].md`.
20. **STOP Rules** — mandatory. Universal rules + project-specific from `%%PROJECT_STOP_RULES%%`.
21. **Deployment Mode: Agent Tool** — mandatory. 6-tier model table, sub-agent spawn syntax, sub-agent rules.
22. **Deployment Mode: Agent Teams** — conditional (inactive by default). From `%%TEAM_TOPOLOGY%%`.
23. **Gemini MCP Table** — conditional. From `%%GEMINI_MCP_TABLE%%`. If no Gemini: "N/A".
24. **Visual Verification** — conditional. From `%%VISUAL_VERIFICATION%%`. If no UI: "N/A".
25. **Cowork Quality Gates** — mandatory. Code review before every dev→main merge. From `%%EXTRA_MANDATORY_SKILLS%%` and `%%RECOMMENDED_SKILLS%%`.
26. **Context Window Management** — mandatory. Read files selectively, status from DB not prose, suggest new session if degrading.
27. **MCP Servers & Plugins Available** — from `%%MCP_SERVERS%%`
28. **Progressive Disclosure** — mandatory. refs/ directory usage. Extract sections >50 lines to refs/.

**For content placeholders** (%%PROJECT_NORTH_STAR%%, %%TECH_STACK%%, %%COMMIT_FORMAT%%, etc.): read specs/ and derive values, or ask user. **Leave mechanical placeholders** (%%PROJECT_NAME%%, %%PROJECT_PATH%%, etc.) — Step 6 fills those.

**Verify:** `grep -c '%%' [PROJECT]_RULES.md` — should show only mechanical placeholders.

**Critical:** Also customize `build_summarizer.sh` for the project's actual tech stack (see Step 1 post-step note). The template is a stub — an uncustomized build_summarizer means pre-commit hooks silently pass. See `references/quality-gates-guide.md` for per-language templates.

### Step 3: Generate CLAUDE.md (LLM Reasoning)

Generate CLAUDE.md using the on-demand framework loading pattern (1 @-import only at startup):

```markdown
# [Project Name] — Project Entry Point
> Cognitive rules auto-loaded from ~/.claude/CLAUDE.md (global).
> Frameworks load on demand via hooks — do NOT @-import them at startup.

@frameworks/session-protocol.md
@[PROJECT]_RULES.md
@AGENT_DELEGATION.md
@ROUTER.md

> **On-demand frameworks** (loaded automatically by hooks when triggered):
> - `correction-protocol.md` — injected by correction-detector hook on correction signal
> - `delegation.md` — injected by pre-edit-check hook at delegation gate
> - `phase-gates.md` — load manually before pre-task check (`db_queries.sh check <id>`)
>
> **Optional frameworks** (add @import lines above to enable):
> `coherence-system`, `falsification`, `loopback-system`, `quality-gates`, `visual-verification`

> LESSONS file (LESSONS_[PROJECT].md) is NOT @-imported — it grows unboundedly.
> The session-start hook injects recent lessons. Read full file on demand for correction protocol.
> Path-specific rules in `.claude/rules/` auto-inject when touching matching files.
> Hooks in `.claude/hooks/` enforce behavioral gates. Custom agents in `.claude/agents/`.
> ROUTER.md lists all on-demand frameworks with their load triggers. Hooks inject routing hints automatically; ROUTER.md is a fallback reference.
```

Replace `[Project Name]` and `[PROJECT]` with actual values.

**Also create `ROUTER.md`** with a routing table listing on-demand frameworks and their trigger mechanisms (hook name or manual). See `templates/rules/ROUTER_TEMPLATE.md` if available, or model after the bootstrap project's `ROUTER.md`.

### Step 4: Create Tracking Files (LLM Reasoning)

Create from templates, filling skeleton content from specs:

| File | Content |
|------|---------|
| `LESSONS_[PROJECT].md` | Empty corrections/insights/universal tables |
| `LEARNING_LOG.md` | Empty table: Date, What, Category, Notes |
| `[PROJECT]_PROJECT_MEMORY.md` | §1-4 from specs (vision, architecture, file structure) |
| `AGENT_DELEGATION.md` | Already populated by Phase C (delegation-md command) |
| `NEXT_SESSION.md` | Bootstrap handoff: signal=GREEN, first task from DB |

### Step 5: Deploy Hooks, Agents, Settings, Init, Git (Programmatic)

```bash
bash "$CLAUDE_PLUGIN_ROOT/engine/bootstrap_project.sh" "$PROJECT_NAME" "$PROJECT_PATH" \
  --phase hooks,agents,settings,init,git \
  --lifecycle full \
  --non-interactive
```

Deploys: .claude/hooks/ (11+ enforcement hooks, chmod +x, protected-files.conf generated), .claude/agents/ (implementer + worker), .claude/settings.json (hook wiring for 7+ event types), .claude/settings.local.json, .claude/rules/ (database-safety + workflow-scripts + tech-stack-specific), .gitignore, refs/ directory, git init + dev branch.

### Step 6: Fill All Placeholders (Programmatic)

```bash
python3 fill_placeholders.py "$PROJECT_PATH" \
  --project-name "$PROJECT_NAME" \
  --specs-dir "$PROJECT_PATH/specs" \
  --lifecycle full \
  --non-interactive \
  --json
```

Fills all 41 placeholder tokens across all project files in one pass. Reads specs for auto-derivation, uses defaults for user-provided tokens in non-interactive mode. Outputs JSON report showing resolved/unresolved counts.

**Verify:** `grep -rn '%%' *.md *.sh .claude/ 2>/dev/null | grep -v '.git/'` — should return zero.

### Step 7: Verify Deployment (Programmatic)

```bash
python3 verify_deployment.py "$PROJECT_PATH"
```

Runs 18 deployment checks. Exit 0 = GREEN (all pass), exit 2 = YELLOW (warnings), exit 1 = RED (critical failures).

**If GREEN:**
```
Bootstrap complete.
Signal: GREEN
Engine: ALL SYSTEMS OPERATIONAL (enforcement layer active)
Launch: bash work.sh
```

Commit: `bootstrap: full engine deployment complete`

**If RED:** Report failures, fix, re-run Step 7.

---

## Gotchas

These are failure modes discovered through real usage. Read before running activation.

- **Engine not bundled.** Activation requires the bundled engine at `$CLAUDE_PLUGIN_ROOT/engine/`. If missing, the preflight check (Phase A step 0) will catch it. Ensure the plugin was installed from a properly built artifact (`build_plugin.sh`).
- **Hardcoded paths leaking into new project.** Source project paths can survive sed replacements. The C17 hardcoded-refs check catches this, but you should also grep for the source project name after every script copy.
- **`init-db` vs `health` confusion.** `bash db_queries.sh health` checks for existing tables but does NOT create them. If you run `health` on a fresh empty database, it will report missing tables but leave them missing. Always run `init-db` first, then `health` to verify.
- **`grep -c` double-output in pre-commit hook.** `grep -c` returns exit code 1 when there are zero matches — this triggers `|| echo 0`, producing `"0\n0"` = `"0 0"` as the variable value. `[ "0 0" -gt 3 ]` then fails with "integer expression expected". The fix (already in the template): remove `|| echo 0` and use `UNPROMOTED="${UNPROMOTED:-0}"` bash default instead. The canonical pre-commit pattern is: `UNPROMOTED=$(grep -cE "..." "$DIR/LESSONS_*.md" 2>/dev/null)` then `UNPROMOTED="${UNPROMOTED:-0}"`.
- **phase_ordinal() not updated.** The `%%PHASE_ORDINALS%%` marker appears in 3 places in db_queries.sh — only 2 need case blocks filled (the bash function and the SQL CASE). Location 3 uses a dynamic phase_gates query. Missing even one of the first two causes `db_queries.sh check` to return wrong verdicts. Always search `%%PHASE_ORDINALS%%` and verify all three locations are handled.
- **Empty build_summarizer.sh.** The template is a stub — you MUST generate real build commands for the project's tech stack. An empty build summarizer means pre-commit hooks silently pass, defeating the entire quality gate system.
- **Generating RULES.md without filling all placeholders.** If even one `%%PLACEHOLDER%%` survives, session_briefing.sh may error or produce garbage output. The C06 placeholder scan is non-negotiable.
- **sqlite3 not available.** In some environments (Cowork sandbox, minimal containers), sqlite3 isn't installed. db_queries.sh will fail silently. Check `which sqlite3` in Phase A.
- **Skipping Step 7 verification.** Every time verification was skipped ("it should work"), something was broken. Run all 18 checks. The 3 minutes it takes saves hours of debugging in the first session.
- **Not making scripts executable.** `chmod +x *.sh` is easy to forget. If pre-commit hook isn't executable, git commit silently skips it — you think you have quality gates but you don't.
- **settings.json not generated.** Without this file, no hooks fire. This is the single most impactful failure mode — the entire enforcement layer is silently disabled. Step 5 settings deployment is non-negotiable.
- **Hooks not executable.** `chmod +x .claude/hooks/*.sh` is easy to forget after copying templates. Hooks that aren't executable fail silently — Claude proceeds without enforcement, and you won't know until a gate is violated.
- **protect-databases.sh still has hardcoded DB names.** The `%%OWN_DB_PATTERNS%%` placeholder must be filled with the project's actual DB name(s) as a grep regex. If left unfilled, the hook blocks ALL DB writes including the project's own DB operations via db_queries.sh.

## On-Demand Hooks (Future Enhancement)

Skills can register hooks that activate only when the skill is called. Consider adding:

- **PreToolUse guard during Steps 1-7:** Block any Write/Edit to files outside the project directory — prevents accidentally modifying templates or other projects during engine deployment.
- **Skill usage logger:** A PreToolUse hook that logs when bootstrap-activate is invoked, helping measure plugin adoption and identify undertriggering.

Note: The core enforcement hooks (correction detection, delegation gate, architecture protection, DB safety, session lifecycle) are now fully deployed in D5. The items above are additional per-skill hooks, not yet implemented.

## Rules

- **Never skip the user review** of requirements.md and design.md. The annotation cycle is where ambiguity gets resolved.
- **The DB is the source of truth** for task state. Never manually edit markdown task lists.
- **The delegation map is mandatory** before any implementation begins.
- **All verification checks in Step 7 must pass.** The bootstrap is not complete until the engine is verified end-to-end.
