# %%PROJECT_NAME%% — Extended Rules Reference
> On-demand reference. Not @-imported every session.
> These rules are hook-enforced, conditional, or rarely referenced mid-session.
> Load with: `read refs/rules-extended.md`

## Code Standards
%%CODE_STANDARDS%%

## Progressive Disclosure (refs/ sub-files)

Reference material lives in `refs/*.md` — loaded on demand, not every session. This keeps the main rules file under the 25K token bootstrap target.

Create refs as sections in this file outgrow ~50 lines. Common examples:
- `refs/tool-inventory.md` — full MCP tool catalog with budget limits
- `refs/phase-gate-protocol.md` — detailed gate logic
- `refs/skills-catalog.md` — skill-to-task routing rules
- `refs/planned-integrations.md` — researched but not-yet-implemented integrations

**Rule:** If a section in this file grows beyond ~50 lines of reference material, extract it to `refs/` and replace with a one-line pointer: `> 📂 Moved to refs/<name>.md — read when [trigger].`

---

## Tracking Files
After each task:
- Mark task DONE in the database: `bash db_queries.sh done <task-id>`
- Update `%%PROJECT_MEMORY_FILE%%` if anything structural changed (new files, new systems, architecture)
- Update `LEARNING_LOG.md` when any new tool, technique, MCP, plugin, skill, or workflow is configured or learned
- Update `LESSONS.md` after any correction from Master (per CLAUDE.md §9)
- Commit all changed files to git with a descriptive message
- At end of session, log it: `bash db_queries.sh log "Claude Code" "Summary of what happened"`

**After triaging or adding tasks — sync the delegation map:**
```bash
bash db_queries.sh delegation-md          # regenerate AGENT_DELEGATION.md from DB
bash db_queries.sh delegation             # view current delegation map
bash db_queries.sh sync-check             # verify NEXT_SESSION.md matches DB state
```
Never edit AGENT_DELEGATION.md by hand. Run `delegation-md` after any `triage`, `quick`, `done`, or `gate-pass`.

## Coherence Check (automatic on commit + manual after core edits)
The pre-commit hook runs `coherence_check.sh` automatically on every `git commit`. It scans all markdown files for stale references defined in `coherence_registry.sh`. **Zero tokens — pure shell.**

**Run manually after editing any core logic file:**
```bash
bash %%PROJECT_PATH%%/coherence_check.sh --fix
```

**When architecture changes** (new system, renamed concept, migrated tool):
1. Make your changes to the relevant files
2. Add ONE entry to `coherence_registry.sh` mapping the old phrase → new canonical form
3. Run `coherence_check.sh --fix` to confirm the old phrase is gone everywhere
4. Commit all together

The registry is the audit trail of every architectural decision. Adding an entry takes 3 lines.

## .gitignore Audit (automatic — contextual to what was just built)
After completing any task that introduces a new file type, SDK, secret, or toolchain, immediately audit and update `.gitignore`. Do NOT front-load speculative entries — only add what's relevant to what was actually just built.

%%GITIGNORE_TABLE%%

**Audit process:**
1. After completing the task, list new files introduced: `git status --short`
2. Check if any match patterns above or contain secrets
3. If yes — update `.gitignore` immediately, before committing the task output
4. Run `git check-ignore -v <file>` to verify new entries work
5. Commit the `.gitignore` update in the same atomic commit as the task

**Never commit:** API keys, provisioning profiles, `.env` files, secret tokens, private keys.

---

## Milestone Merge Gate
When a phase is complete, Master runs the gate script to confirm readiness before merging:

```bash
bash %%PROJECT_PATH%%/milestone_check.sh <PHASE>
```

**What it checks (in order):**
1. All tasks in the phase are DONE in the DB (MASTER/SKIP tasks don't block)
2. Current branch is `dev`
3. Working tree is clean (no uncommitted changes)
4. Build + tests pass (runs `build_summarizer.sh test`)
5. Coherence check is clean

**On all-pass:** prints the exact merge commands to copy-paste.
**On any failure:** prints what to fix. Never touches `main`.

**Rule:** Run a code review (paste `git diff main..dev`) before merging any phase that contains source code changes.

---

## Deployment Mode: Agent Tool ✅ ACTIVE

### Model Delegation
> 📂 Full tier model and delegation rules: see `delegation` framework (@import in CLAUDE.md).

**Project-specific model mapping:**
%%EXTRA_MODEL_DELEGATION%%

### Sub-Agent Spawn Syntax
Use frontmatter to set the model:
```markdown
---
model: haiku
---
[Task instructions here]
```
Options: `haiku`, `sonnet`, `opus`, `inherit` (default = same as parent)

### Budget Mode (optional)
For token-conscious sessions, Master can start Claude Code with the `opusplan` model:
```bash
cd %%PROJECT_PATH%% && claude --model opusplan --dangerously-skip-permissions
```
This uses **Opus for planning** (reads code, creates plan) and **Sonnet for execution** (writes code). Same quality architecture decisions, ~60% cheaper on implementation.

---

## Deployment Mode: Agent Teams ⬜ INACTIVE

### Prerequisites
```json
// ~/.claude/settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "teammateMode": "tmux"
}
```
Install tmux: `brew install tmux`
Restart Claude Code after config change.

### Team Topology
%%TEAM_TOPOLOGY%%

### Coordination Protocol
- **Assignment:** Orchestrator assigns work via teammate messages — teammates don't self-assign
- **Completion:** Teammates report back to Orchestrator when done — Orchestrator reviews before committing
- **File conflicts:** Orchestrator resolves — teammates never merge independently
- **Dependencies:** Use inter-teammate messages for handoffs

### Cost Awareness
- Agent Teams runs ~3-4x the tokens of Agent Tool mode
- Only use Teams when parallelism actually saves wall-clock time
- Single-file sequential work should still use Agent Tool, even when Teams is active

---

%%GEMINI_MCP_TABLE%%

## Visual Verification
%%VISUAL_VERIFICATION%%

## Cowork Quality Gates
Master runs these in Cowork (the desktop app) at specific trigger points.

### Mandatory Skills (run every time the trigger fires)
| Trigger | Skill | What Master does |
|---------|-------|-----------------|
| **Before every dev→main merge** | Code review | Paste `git diff main..dev` → structured review → fix on `dev` before merging |
%%EXTRA_MANDATORY_SKILLS%%

### Recommended Skills (run when starting a new phase)
| Trigger | Skill | What Master does |
|---------|-------|-----------------|
%%RECOMMENDED_SKILLS%%

## MCP Servers & Plugins Available
%%MCP_SERVERS%%
