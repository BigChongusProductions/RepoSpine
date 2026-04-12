---
framework: phase-gates
version: 2.0
extracted_from: production project (2026-03-21)
---

# Phase Gate Framework

## When Phase Gates Trigger

A phase gate triggers automatically when the next task to be worked on belongs to a phase beyond the last gated phase. This applies at session start AND mid-session.

## Gate Review Process

1. **Audit the completed phase** — List all tasks. For each: was it completed? Does implementation match intent? Any shortcuts taken?

2. **Categorize findings:**
   - **Must-fix** — Issues that will cause problems in later phases. MUST resolve before gate passes.
   - **Follow-up** — Desirable improvements that won't block later work. Create a task, tag, defer.

3. **Present the gate review:**
```
Phase Gate Review: [Phase Name]
Completed: [X/Y tasks]
Must-fix items: [list, or "None"]
Follow-up items: [list, or "None"]
```

4. **Record the gate result** — Once passed, persist in two places:
   - The `phase_gates` DB table (source of truth): `bash db_queries.sh gate-pass <PHASE>`
   - NEXT_SESSION.md (written by save-session for fast startup reads)
   Once recorded, the gate is never re-audited.

## Pre-Task Check Verdicts

`db_queries.sh check <task-id>` returns one of three verdicts:

### GO
All clear. Proceed with the task (or spawn a sub-agent).

### CONFIRM
A milestone moment was detected. Present reasons to Master and wait for explicit approval before proceeding.

**CONFIRM triggers:**
- First Claude task in a new phase
- Prior task in sort order belongs to Master/Gemini (handoff point)
- Last remaining Claude task in the phase
- 5+ tasks completed since last structural checkpoint

**Protocol:** Present summary of recent progress + milestone reasons → wait for "go" → run `db_queries.sh confirm <task-id>` to record → proceed.

If Master says "skip gate," proceed without recording. Log the override.

### STOP
Hard blocker detected. Do NOT proceed.

**STOP triggers:**
- Task is assigned to another owner (Master/Gemini)
- Prior phase has incomplete tasks
- Prior phase gate not passed
- Cross-phase `blocked_by` dependency unresolved

**Note:** Same-phase `blocked_by` is advisory only (WARN, not STOP). Stale references (nonexistent task) produce a WARN with fix command, not a STOP.

## Blocker Detection Rules

### What counts as a blocker
- Any task assigned to another owner that is a prerequisite for the current task
- Any task with `blocked_by` where the blocker is not DONE
- Any unresolved decision that downstream work depends on
- Any external action required (device testing, asset creation, etc.)

### When a blocker is detected
- Do NOT silently skip it or work around it
- Present clearly: what it is, who owns it, what depends on it
- Offer alternatives: resolve now, reprioritize, or explicit override

### Override mechanism
- Log the override in the session
- The save-session skill captures it in NEXT_SESSION.md under "Overrides (active)"
- The override does NOT clear the blocker — it remains flagged until resolved

## Milestone Gate Integration with Sub-Agents

The orchestrator MUST run `check` before spawning a sub-agent:
- **GO** → spawn the sub-agent
- **CONFIRM** → handle the checkpoint BEFORE spawning
- **STOP** → do not spawn, present blockers

Sub-agents that independently run `check` and receive CONFIRM must return to the orchestrator without proceeding. They should never autonomously bypass a CONFIRM gate.

## Changelog
- 2.0: Added CONFIRM verdict, milestone gate triggers, sub-agent integration rules, same-phase vs cross-phase blocker distinction, stale reference handling
- 1.0: Initial extraction from production project
