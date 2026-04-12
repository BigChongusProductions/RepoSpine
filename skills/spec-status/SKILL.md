---
name: spec-status
description: >
  Show bootstrap progress and spec completion status. Use when the user runs /spec-status,
  says "check status", "where are we", "bootstrap status", or wants to see the current
  state of their project's bootstrap process.
version: 0.2.0
---

# Spec Status

Check and report the current bootstrap status for this project.

1. Read `.bootstrap_mode` if it exists. Report the current mode (DISCOVERY / SPECIFICATION / PLANNING / ENGINE_DEPLOY / COMPLETE / not found).

2. Check each spec file for completeness:
   - `specs/VISION.md` — exists? contains "TODO"?
   - `specs/RESEARCH.md` — exists? contains "TODO"?
   - `specs/BLUEPRINT.md` — exists? contains "TODO"?
   - `specs/INFRASTRUCTURE.md` — exists? contains "TODO"?
   - `specs/requirements.md` — exists? contains "> NOTE:"?
   - `specs/design.md` — exists? contains "> NOTE:"?

3. Check placeholder status: count remaining `%%` patterns across all `.md` and `.sh` files (excluding .git/).

4. Check engine deployment status:
   - `db_queries.sh` exists? Has tasks in DB?
   - `session_briefing.sh` exists?
   - `RULES.md` or `*_RULES.md` exists? Contains unfilled `%%` placeholders?
   - `frameworks/` directory exists? How many framework files?
   - `.claude/hooks/` exists? How many hook files? Are they executable?
   - `.claude/agents/` exists? How many agents defined?
   - `.claude/rules/` exists? How many rule files?
   - `.claude/settings.json` exists? Valid JSON? How many hook events wired?
   - Git hooks installed? (`pre-commit`, `pre-push`)
   - Tracking files exist? (LESSONS, PROJECT_MEMORY, LEARNING_LOG, NEXT_SESSION)

5. Present a compact status report:

```
Bootstrap Status: [MODE]

Specs:
  VISION.md          [DONE / X TODOs / MISSING]
  RESEARCH.md        [DONE / X TODOs / MISSING]
  BLUEPRINT.md       [DONE / X TODOs / MISSING]
  INFRASTRUCTURE.md  [DONE / X TODOs / MISSING]
  requirements.md    [DONE / X notes / MISSING]
  design.md          [DONE / X notes / MISSING]

Engine:
  Placeholders:    [0 remaining / X remaining]
  Database:        [X tasks / empty / no DB]
  Scripts:         [X/14 deployed]
  Frameworks:      [X/10 deployed]
  Hooks:           [X/19 deployed / missing]
  Agents:          [X/4 deployed / missing]
  Rules:           [X/3+ deployed / missing]
  Settings:        [deployed / missing]
  Git hooks:       [installed / missing]
  Tracking files:  [X/5 deployed]

Next step: [what to do based on current state]
```

6. Based on the state, recommend next action:
   - No specs → "Run /new-project in Cowork"
   - Specs have TODOs → "Complete specs (run /new-project in Cowork)"
   - Specs complete, no engine → "Run /activate-engine"
   - Engine partially deployed → "Run /activate-engine to complete deployment"
   - Engine deployed, placeholders remain → "Fill remaining placeholders (run /activate-engine)"
   - Everything deployed → "Ready to build. Run the session protocol."
