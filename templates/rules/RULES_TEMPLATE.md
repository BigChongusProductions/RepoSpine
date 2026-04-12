# %%PROJECT_NAME%% — Project Rules
> Auto-imported by CLAUDE.md. Contains all project-specific rules, workflows, and configurations.
> Cognitive rules (planning, thinking, quality, self-healing, etc.) live in CLAUDE.md — do NOT duplicate them here.

## Project North Star
> **%%PROJECT_NORTH_STAR%%**

## Session Start Protocol
> 📂 Core protocol in `frameworks/session-protocol.md`. Project-specific additions below.

- Also read `%%PROJECT_MEMORY_FILE%%` for technical context (focus on architecture sections — briefing covers status)
- Task details: `bash db_queries.sh task <id>`

---

## Phase Gate Protocol
> 📂 Moved to `refs/phase-gate-protocol.md` — read before any phase transition.

---

## Pre-Task Check
> 📂 Verdict logic (GO/CONFIRM/STOP) in `frameworks/phase-gates.md`.

```bash
bash %%PROJECT_PATH%%/db_queries.sh check <task-id>
```

**Do NOT evaluate conditions yourself. Run the script and follow its verdict.**

On CONFIRM approval: `bash db_queries.sh confirm <task-id>`

---

## Task Workflow
Work through tasks returned by `db_queries.sh next`, top to bottom.
- `next` shows: **circuit breaker** (S1), **S2 loopbacks**, **FORWARD (ready)**, **S3/S4**, **BLOCKED**
- If ALL remaining Claude tasks are blocked on Master work, STOP and report
- Mark done immediately: `bash %%PROJECT_PATH%%/db_queries.sh done <task-id>`

### Task Commands
```bash
# Quick capture (creates INBOX item with QK-xxxx ID):
bash db_queries.sh quick "Fix layout bug on mobile" %%FIRST_PHASE%% bug
# Loopback (S1=critical/circuit-breaker, S2=major, S3=minor, S4=cosmetic):
bash db_queries.sh quick "Fix regex" %%FIRST_PHASE%% bug --loopback %%FIRST_PHASE%% --severity 2 --reason "logic error"
# Triage:
bash db_queries.sh inbox                                             # view untriaged
bash db_queries.sh triage QK-1234 <PHASE> sonnet                     # promote to planned
bash db_queries.sh triage QK-1234 loopback <ORIGIN> --severity 2     # triage as loopback
bash db_queries.sh loopbacks                                         # view open queue
bash db_queries.sh ack-breaker LB-xxxx "reason"                      # acknowledge S1
bash db_queries.sh delegation-md                                     # regenerate AGENT_DELEGATION.md
```
**Never edit the delegation map by hand.** DB is source of truth.

**Tier 2 (periodic) — full syntax in `refs/dbq-commands.md`:**
```bash
bash db_queries.sh gate-pass P2-DESIGN MASTER "notes"     # record phase gate passage
bash db_queries.sh confirm <task-id>                       # confirm before execution
bash db_queries.sh unblock <task-id>                       # clear resolved blocker
bash db_queries.sh log-lesson "WHAT" "PATTERN" "RULE"      # log correction atomically
bash db_queries.sh assume <task-id> "assumption" "cmd"     # register + verify assumption
bash db_queries.sh gate                                    # show current gate status
bash db_queries.sh health                                  # DB health check
```

## Tech Stack & Environment
%%TECH_STACK%%

## Git Branching
- **Always work on `dev`** — NEVER commit directly to `main`
- Before starting work, verify: `git branch` → should show `* dev`
- If on `main`, switch: `git checkout dev`
- Commit message format: %%COMMIT_FORMAT%%
- After completing the last task in a batch: `git log --oneline main..dev` to show Master what's ready
- **Do NOT merge dev → main** — that's Master's job after reviewing your work

## Build & Test
%%BUILD_TEST_INSTRUCTIONS%%

## Correction Detection Gate
> 📂 Full correction protocol: see `correction-protocol` framework (@import in CLAUDE.md).
> Use `bash db_queries.sh log-lesson "WHAT" "PATTERN" "RULE"` for atomic logging.

### Delegation Gate
> 📂 Full delegation rules: see `delegation` framework (@import in CLAUDE.md).

### Output Verification Gate (OPTIONAL — customize per project type)

%%OUTPUT_VERIFICATION_GATE%%

---

### Lesson Extraction (session end)

> Full extraction protocol: see `session-protocol` and `correction-protocol` frameworks.

Use `bash db_queries.sh log-lesson "WHAT" "PATTERN" "RULE"` for atomic logging.
Bootstrap escalation: `bash db_queries.sh log-lesson "WHAT" "PATTERN" "RULE" --bp template "templates/path"`

---

## STOP Rules (Project-Specific)
In addition to universal STOP rules in CLAUDE.md §10:
%%PROJECT_STOP_RULES%%

---

> **Extended rules** (blocker detection, deployment modes, milestone merge gate, coherence, .gitignore audit, code standards, tracking files, cowork gates, MCP servers): load `refs/rules-extended.md` when needed for these topics.
