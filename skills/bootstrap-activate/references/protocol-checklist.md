# Protocol Checklist

Verification checklist for all 28 sections of [PROJECT]_RULES.md after deployment.

---

## RULES.md Section Verification Table

| § | Section Name | Purpose | Verifies | Files | Check Command |
|---|---|---|---|---|---|
| 1 | Project North Star | Vision statement | One-liner exists, is meaningful | RULES.md | `grep -A1 "Project North Star" RULES.md` |
| 2 | Session Start Protocol | Startup sequence | All 4 bash commands present (handoff, phase, gate, briefing) | RULES.md | `bash session_briefing.sh` — should complete without errors |
| 3 | Phase Gate Protocol | Phase transition logic | Gate review process, verdict recording in DB | RULES.md | `bash db_queries.sh gate --help` — should be callable |
| 4 | Blocker Detection Rules | Blocker identification | What counts as blocker, when to present | RULES.md | `grep -c "blocker" RULES.md` — should be >10 |
| 5 | Pre-Task Check | Task readiness | check command syntax, STOP/CONFIRM/GO verdicts | RULES.md | `bash db_queries.sh check --help` — should be callable |
| 6 | Task Workflow | Task loop | done, quick, loopback, inbox, triage commands documented | RULES.md | `bash db_queries.sh done --help` — should be callable |
| 7 | Tech Stack & Environment | Stack documentation | %%TECH_STACK%% filled, setup steps present | RULES.md | `grep -c "Node.js\|Python\|Rust\|Swift\|Go" RULES.md` — check if tech stack mentioned |
| 8 | Git Branching | VCS strategy | dev branch rule, commit format %%COMMIT_FORMAT%% | RULES.md | `git branch` — should show current branch |
| 9 | Build & Test | Build commands | %%BUILD_TEST_INSTRUCTIONS%% filled, exact command | RULES.md | Run build command manually — should succeed |
| 10 | Code Standards | Code quality | %%CODE_STANDARDS%% filled, tools listed | RULES.md | `grep -c "ESLint\|Swift\|Black\|Clippy" RULES.md` — check for linter config |
| 11 | Progressive Disclosure | Ref files | refs/ subdirectory exists, files listed | RULES.md | `ls refs/*.md` — should list files |
| 12 | Tracking Files | Artifact files | LESSONS, LEARNING_LOG, PROJECT_MEMORY exist | RULES.md | `ls -1 LESSONS_*.md LEARNING_LOG.md [PROJECT]_PROJECT_MEMORY.md` |
| 13 | Coherence Check | Reference staleness | coherence_check.sh exists, registry seeded | RULES.md | `bash coherence_check.sh --quiet && echo "clean"` |
| 14 | .gitignore Audit | VCS patterns | %%GITIGNORE_TABLE%% filled, patterns relevant to tech stack | RULES.md | `git check-ignore -v node_modules/` — should match |
| 15 | Correction Detection Gate | Lesson capture | HARD GATE rule, LESSONS file update first | RULES.md | `grep -A2 "Correction Detection" RULES.md` |
| 16 | Delegation Gate | Multi-step planning | HARD GATE rule, delegation table shown before work | RULES.md | `grep -A2 "Delegation Gate" RULES.md` |
| 17 | Output Verification Gate | Visual testing | %%OUTPUT_VERIFICATION_GATE%% filled (or "N/A") | RULES.md | `grep -A3 "Output Verification" RULES.md` |
| 18 | Deployment Mode: Agent Tool | Sub-agent config | Model delegation table present, syntax documented | RULES.md | `grep -c "Haiku\|Sonnet\|Opus" RULES.md` — should be >5 |
| 19 | Sub-Agent Rules | Sub-agent behavior | File read/write scope, failure escalation | RULES.md | `grep -A5 "Sub-Agent Rules" RULES.md` |
| 20 | Budget Mode | Token awareness | opusplan model mentioned if cost-sensitive | RULES.md | `grep -i "opusplan" RULES.md` — may be empty (optional) |
| 21 | Deployment Mode: Agent Teams | Team coordination | "INACTIVE" by default, activation steps if used | RULES.md | `grep "Agent Teams" RULES.md` |
| 22 | Team Topology | Team structure | %%TEAM_TOPOLOGY%% filled or "INACTIVE" | RULES.md | `grep -A3 "Team Topology" RULES.md` |
| 23 | Coordination Protocol | Team handoff | Assignment, completion, conflict resolution rules | RULES.md | `grep -c "Assignment\|Completion\|conflict" RULES.md` — check present |
| 24 | MCP Servers & Plugins | Tool catalog | %%MCP_SERVERS%% filled, tools listed with capabilities | RULES.md | `grep -c "MCP\|Gemini\|Grok" RULES.md` — should be >3 |
| 25 | Cowork Quality Gates | Human workflow | %%EXTRA_MANDATORY_SKILLS%%, %%RECOMMENDED_SKILLS%% filled | RULES.md | `grep -B1 "Code review\|Skill" RULES.md` — check mandatory skills |
| 26 | Visual Verification | UI testing | %%VISUAL_VERIFICATION%% filled (checklist or "N/A") | RULES.md | `grep -A5 "Visual Verification" RULES.md` |
| 27 | Context Window Management | Bootstrap target | <25K token target, selective reading rules | RULES.md | `wc -w RULES.md AGENT_DELEGATION.md LESSONS_*.md` — total should be <25K |
| 28 | STOP Rules (Project-Specific) | Safety guardrails | %%PROJECT_STOP_RULES%% filled or "None beyond universal" | RULES.md | `grep -A3 "STOP Rules" RULES.md` |

---

## Enforcement Layer Verification

| Component | Check | Expected |
|-----------|-------|----------|
| `.claude/hooks/*.sh` | `ls .claude/hooks/*.sh \| wc -l` | 12+ files (11 universal + tech-stack-specific) |
| Hooks executable | `find .claude/hooks -name '*.sh' ! -perm -111 \| wc -l` | 0 (all executable) |
| `.delegation_state` | `cat .claude/hooks/.delegation_state` | Two lines: "0" and "0" |
| `protected-files.conf` | `wc -l .claude/hooks/protected-files.conf` | 15+ patterns |
| `.claude/agents/` | `ls .claude/agents/*/*.md \| wc -l` | 2 (implementer + worker) |
| `.claude/rules/` | `ls .claude/rules/*.md \| wc -l` | 3+ (2 universal + 1+ tech-specific) |
| `.claude/settings.json` | `python3 -c "import json; json.load(open('.claude/settings.json'))"` | Valid JSON, no error |
| Hook events wired | `grep -c '"command"' .claude/settings.json` | 7+ (one per hook event type) |
| No stray placeholders | `grep -rn '%%' .claude/ --include='*.sh' --include='*.md' --include='*.json'` | 0 matches |

---

## db_queries.sh Command Tiers

Verify all command groups are implemented in db_queries.sh:

### Daily Commands (6)
```bash
bash db_queries.sh next              # Next tasks in order
bash db_queries.sh done <id>         # Mark task complete
bash db_queries.sh check <id>        # Pre-task validation (GO/CONFIRM/STOP)
bash db_queries.sh quick "..."       # Quick capture
bash db_queries.sh phase             # Current phase
bash db_queries.sh status            # Phase + gate + blockers summary
```

**Verify:** `bash db_queries.sh next` should return task list (or "No tasks yet")

### Phase Transition (5)
```bash
bash db_queries.sh gate              # Gate status (passed/pending)
bash db_queries.sh gate-pass <phase> # Record gate pass
bash db_queries.sh confirm <id>      # Record milestone confirmation
bash db_queries.sh blockers          # List blocked tasks
bash db_queries.sh unblock <id>      # Clear resolved blocker
```

**Verify:** `bash db_queries.sh blockers` should return blocker list or "No blockers"

### Loopback (7)
```bash
bash db_queries.sh loopbacks              # View open loopback queue
bash db_queries.sh loopback-stats         # Analytics on loopbacks
bash db_queries.sh ack-breaker <id> "msg" # Acknowledge S1 circuit breaker
bash db_queries.sh loopback-lesson <id>   # Generate lesson from loopback
bash db_queries.sh skip <id> "reason"     # Mark loopback WONTFIX
bash db_queries.sh inbox                                      # View untriaged quick captures
bash db_queries.sh triage QK-1234 P3-IMPLEMENT sonnet         # Triage inbox → planned work
bash db_queries.sh triage QK-1234 loopback P2-DESIGN --severity 2  # Triage as loopback (slot 3 = origin phase)
```

**Verify:** `bash db_queries.sh loopbacks` should return loopback list or "None"

### Delegation (2)
```bash
bash db_queries.sh delegation-md        # Generate AGENT_DELEGATION.md from DB
bash db_queries.sh delegation           # Show delegation map
```

**Verify:** `bash db_queries.sh delegation` should show task → tier mapping

### Falsification (6)
```bash
bash db_queries.sh assume <id> "text"          # Register assumption
bash db_queries.sh verify-assumption <id>      # Verify one assumption
bash db_queries.sh verify-all <id>             # Verify all assumptions for task
bash db_queries.sh assumptions <id>            # List assumptions for task
bash db_queries.sh researched <id>             # Mark task as researched
bash db_queries.sh break-tested <id>           # Record deliberate breakage test
```

**Verify:** `bash db_queries.sh assumptions <first_task_id>` should return empty or assumption list

### Session & Logging (5)
```bash
bash db_queries.sh log "Agent" "Summary"        # Log session
bash db_queries.sh log-lesson "WHAT" "PATTERN" "RULE"  # Log lesson atomic
bash db_queries.sh sessions                     # List past sessions
bash db_queries.sh lessons                      # Show logged lessons
bash db_queries.sh promote <lesson>             # Promote to LESSONS_UNIVERSAL.md
```

**Verify:** `bash db_queries.sh sessions` should return empty or session list

### Diagnostic (20+)
```bash
bash db_queries.sh health                  # DB health check
bash db_queries.sh verify                  # Data integrity audit
bash db_queries.sh task <id>               # Show single task details
bash db_queries.sh master                  # List Master tasks
bash db_queries.sh board                   # Generate markdown board
bash db_queries.sh sync-check              # NEXT_SESSION.md ↔ DB sync
bash db_queries.sh backup                  # Backup DB
bash db_queries.sh restore <backup>        # Restore from backup
bash db_queries.sh snapshot <name>         # Create snapshot
bash db_queries.sh snapshot-list           # List snapshots
bash db_queries.sh snapshot-show <name>    # Show snapshot content
bash db_queries.sh snapshot-diff <s1> <s2> # Diff two snapshots
bash db_queries.sh add-task QK-9999 P2-DESIGN "Title" sonnet  # Manually add task (4 required positionals)
bash db_queries.sh tag-session <tag>       # Tag current session
bash db_queries.sh session-tags            # List session tags
bash db_queries.sh session-file <id>       # Export session to markdown
bash db_queries.sh tag-browser             # Launch tag browser UI
bash db_queries.sh start                   # Initialize DB from BLUEPRINT.md
bash db_queries.sh decisions               # List decisions made
bash db_queries.sh confirmations           # List milestone confirmations
```

**Verify:** `bash db_queries.sh health` should return health status

---

## Session Protocol Verification

### Startup Sequence Check

Run this at every session start:

```bash
echo "=== Step 1: Read State ==="
cat NEXT_SESSION.md
bash db_queries.sh phase
bash db_queries.sh blockers
bash db_queries.sh gate
bash db_queries.sh next

echo "=== Step 2: Briefing ==="
bash session_briefing.sh

echo "=== Step 3: Git Status ==="
git status --short
git log --oneline -5

echo "=== All steps complete ==="
```

**Verification:** All commands should complete without errors.

---

## Git Hooks Verification

Test both hooks work:

```bash
# Test pre-commit hook
touch test.txt
git add test.txt
git commit -m "test" 2>&1 | head -20
# Should run: lint, types, tests, coherence check

# Test pre-push hook (dry-run)
git push --dry-run origin dev 2>&1 | head -20
# Should run: production build
```

---

## Framework Files Verification

Verify all 9 frameworks are present and valid:

```bash
ls -1 frameworks/*.md | sort
# Expected output:
#   frameworks/coherence-system.md
#   frameworks/correction-protocol.md
#   frameworks/delegation.md
#   frameworks/falsification.md
#   frameworks/loopback-system.md
#   frameworks/phase-gates.md
#   frameworks/quality-gates.md
#   frameworks/session-protocol.md
#   frameworks/visual-verification.md

# Check each file is non-empty
wc -l frameworks/*.md | sort -rn
```

---

## refs/ Directory Verification

Verify starter reference files are scaffolded:

```bash
ls -1 refs/*.md | sort
# Expected minimum:
#   refs/README.md
#   refs/tool-inventory.md
#   refs/gotchas-workflow.md

# Check tool inventory has content
wc -l refs/tool-inventory.md
# Expected: >10 lines (at minimum the template headers)
```

---

## RULES.md Customization Checklist

Before first session, verify these customizations were completed:

| Placeholder | Check | Expected |
|---|---|---|
| %%PROJECT_NORTH_STAR%% | `grep "PROJECT_NORTH_STAR" RULES.md` | Should return 0 matches (replaced) |
| %%TECH_STACK%% | `grep "TECH_STACK" RULES.md` | Should return 0 matches (replaced) |
| %%COMMIT_FORMAT%% | `grep "COMMIT_FORMAT" RULES.md` | Should return 0 matches (replaced) |
| %%BUILD_TEST_INSTRUCTIONS%% | `grep "BUILD_TEST_INSTRUCTIONS" RULES.md` | Should return 0 matches (replaced) |
| %%CODE_STANDARDS%% | `grep "CODE_STANDARDS" RULES.md` | Should return 0 matches (replaced) |
| %%PROJECT_STOP_RULES%% | `grep "PROJECT_STOP_RULES" RULES.md` | Should return 0 matches (replaced) |
| `[developer-specific paths]` | `grep -r "/Users/" .` | Should return 0 matches (all paths updated) |
| Any remaining %% | `grep -rn '%%' *.md *.sh` | Should return 0 matches |

---

## Pre-Session Checklist (Final)

Before starting first Claude session, complete ALL of these:

- [ ] All 10 scripts copied and customized
- [ ] Database initialized (`bash db_queries.sh health` = OK)
- [ ] All 9 frameworks copied to `frameworks/`
- [ ] refs/ directory scaffolded with tool-inventory + gotchas-workflow
- [ ] CLAUDE.md present with @-imports
- [ ] [PROJECT]_RULES.md present with all 28 sections
- [ ] AGENT_DELEGATION.md present
- [ ] LESSONS_[PROJECT].md present and empty but structured
- [ ] LEARNING_LOG.md present and empty but structured
- [ ] [PROJECT]_PROJECT_MEMORY.md present with stub
- [ ] NEXT_SESSION.md present with template fields
- [ ] .gitignore present with %%GITIGNORE_TABLE%% contents
- [ ] Git hooks installed and executable
- [ ] `.claude/hooks/` deployed and executable (12+ hooks)
- [ ] `.claude/agents/` deployed (implementer + worker)
- [ ] `.claude/rules/` deployed (2+ rule files)
- [ ] `.claude/settings.json` valid JSON with 7 hook events wired
- [ ] `settings.local.json` present
- [ ] No remaining %% placeholders in any file
- [ ] No remaining hardcoded developer-machine paths (check: `grep -rn '/Users/' .`)
- [ ] Build command runs without errors
- [ ] Test command runs without errors
- [ ] `bash session_briefing.sh` completes without errors
- [ ] Git status is clean (no uncommitted files)
- [ ] Initial commit made with message: "bootstrap: initialize [project] infrastructure"

Only when ALL checks pass should the first Claude session begin.

