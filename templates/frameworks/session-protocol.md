---
framework: session-protocol
version: 2.0
extracted_from: production project (2026-03-21)
---

# Session Protocol Framework

## Session Start Protocol (MANDATORY)

Every session begins with orientation. No code until this completes.

### Step 1 — Read State (silent)

```bash
cat NEXT_SESSION.md                    # Handoff from last session
bash db_queries.sh phase               # Current phase
bash db_queries.sh blockers            # What's blocked
bash db_queries.sh gate                # Gate status
bash db_queries.sh next                # Next tasks
bash session_briefing.sh               # Full briefing with signal
git status --short && git log --oneline -5
```

### Step 2 — Read the Signal

The session signal (GREEN/YELLOW/RED) is computed by `session_briefing.sh`. Do NOT evaluate it yourself.

Signal logic checks:
- Whether any prior phase has incomplete tasks when next Claude task is in a later phase → RED
- Whether the phase before the next Claude task's phase has been gated → RED if not
- Whether Master/Gemini tasks block Claude work → RED if all blocked, YELLOW if some
- Whether the next specific Claude task has an unresolved **cross-phase** `blocked_by` → YELLOW (same-phase is advisory only)

### Step 3 — Present Status Brief

**First line is always the model self-report.**

```
Model: [your actual model — e.g. claude-opus-4-6 or claude-sonnet-4-6]
Phase: [from briefing] | Gate: [from briefing]
Next up: [from briefing]
Signal: [from briefing — GREEN / YELLOW / RED]

[If YELLOW or RED: copy the reasons from the briefing output]
```

### Model Gate (runs before anything else)

- If model is the designated orchestrator (e.g. `claude-opus-4-6`) → proceed normally
- If model is anything else → **STOP.** State that you should not act as orchestrator. Wait for model switch.

This prevents lower-tier models from making orchestration decisions they're not qualified for.

### Step 4 — Wait for confirmation

**On GREEN:** Present brief and recommended task. Wait for "go."
**On YELLOW:** Flag items, recommend action. Wait for decision.
**On RED:** Present blockers. State what cannot proceed and why. Offer options:
1. Resolve the blocker now
2. Reprioritize to unblocked work
3. Explicitly override (logged in NEXT_SESSION.md)

## The 7 Session Rules

1. **Plan before you type.** Never write code without an approved plan or spec.
2. **Fresh session per task.** Start new for each task. Context degrades over long sessions.
3. **First prompt reads specs.** Always start with: "Read CLAUDE.md and specs/. Begin task T-XX."
4. **Tests before code.** Write the failing test first. Then implement until it passes.
5. **Commit after each task.** Small atomic commits. You can always roll back.
6. **If Claude goes off-track, restart.** Don't spend 10 minutes correcting. Clear, start fresh.
7. **Specs are living.** When code changes, specs must update. When specs update, code must follow.

## Context Window Management

1. Read files selectively — only sections relevant to current task
2. Status lives in DB and NEXT_SESSION.md, not prose files
3. Sub-agents get minimal context: task description + specific files + constraints
4. After phase gates, compress completed phase details to 3-line summaries
5. Keep instruction files stable for prompt caching (90% discount on stable prefixes)
6. If responses degrade, suggest starting a new session

## Lesson Extraction (session end)

Before writing the save-session report:
1. Scan conversation for corrections, retries, false assumptions, new tools, violated existing lessons, promotion candidates
2. Present proposed lessons categorized by type
3. Don't ask what to log — propose it yourself

**Completeness gate:** Save-session report must verify these files exist and are non-empty:
- Project LESSONS file
- `LESSONS_UNIVERSAL.md`
- `LEARNING_LOG.md`

## Changelog
- 2.1: Added The 7 Session Rules (from lifecycle framework)
- 2.0: Added model self-report gate, cross-phase vs same-phase blocker distinction, lesson extraction protocol, prompt caching note
- 1.0: Initial extraction from production project
