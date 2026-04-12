---
framework: correction-protocol
version: 1.1
extracted_from: production project (2026-03-17)
---

# Correction Protocol Framework

## Why This Exists

The soft rule "log lessons immediately after corrections" failed 3+ times across sessions. Every failure followed the same pattern: understand problem → diagnose → fix → forget to log. Voluntary compliance doesn't work under cognitive load.

## Correction Detection Gate (MANDATORY)

Before responding to ANY user message, scan for correction signals:
- User says "didn't work", "failed", "wrong", "broken", "not right"
- User asks "why didn't you...", "why did you not..."
- User reports unexpected behavior
- User redirects from what you were doing
- User expresses frustration

**If correction signal detected → HARD GATE:**
1. **FIRST tool call** = write the correction to LESSONS file. Not second. Not after diagnosis. FIRST.
2. If unsure whether it's a correction → log anyway. False positives are cheap.
3. Only AFTER the lesson is written, proceed to diagnose and fix.

## Lesson Extraction (session end)

Before writing session handoff, scan the conversation for:
- Corrections and retries
- False assumptions
- New tools or techniques learned
- Violated existing lessons
- Patterns that recur across projects (promotion candidates)

Present proposed lessons categorized by type. Don't ask the user what to log — propose it yourself.

## Promotion Pipeline

```
Project LESSONS.md → "No" in promoted column → harvest.sh detects → promote to LESSONS_UNIVERSAL.md → mark "Yes" in source
```

Enforcement points that surface unpromoted patterns:
1. `session_briefing.sh` — at session start
2. `db_queries.sh done` — after every task (threshold: 3+)
3. Pre-commit hook — on every commit
4. `harvest.sh` — on-demand scanner

## Bootstrap Escalation

If a lesson affects how **new projects** are set up (template bug, missing guard, process gap, framework doc error):

**During lesson logging (zero friction):**
```bash
bash db_queries.sh log-lesson "what" "pattern" "rule" --bp template "templates/path/to/file"
```

**Standalone escalation:**
```bash
bash db_queries.sh escalate "description" category "templates/path/to/file" --priority P1
```

**Tagging for later harvest:**
Add `[BP:category]` inline in the lesson text (categories: template, framework, process, system).

**Enforcement:** `bash scripts/harvest.sh --bootstrap` scans all projects for unescalated template-affecting lessons.

**Consumption:** Backlog items are reviewed and applied to templates via `scripts/apply_backlog.sh`. During `/activate-engine`, pending P0/P1 items are surfaced as advisories.

## Changelog
- 1.1: Added Bootstrap Escalation tier (2026-03-24)
- 1.0: Initial extraction from production project
