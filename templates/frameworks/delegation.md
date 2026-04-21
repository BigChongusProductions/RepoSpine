---
framework: delegation
version: 2.0
extracted_from: production project (2026-03-21)
---

# Agent Delegation Framework

## The 6-Tier Model

| Tier | Model / Tool | Cost | Use When |
|------|-------------|------|----------|
| **Opus** (orchestrator) | `claude-opus-4-6` | $$$$ | Architecture decisions, gate reviews, ambiguous trade-offs, judgment calls, anything that failed at a lower tier |
| **Sonnet** (implementer) | `claude-sonnet-4-6` | $$ | Multi-file features from clear spec, components with non-trivial state/animation, tasks requiring cross-file reasoning |
| **Haiku** (mechanic) | `claude-haiku-4-5` | $ | Single-file bounded tasks, display-only components, config edits, JSON updates, mechanical wiring, clear spec with no judgment needed |
| **Gemini** (specialist) | via MCP | varies | Large context analysis, web research, factual cross-referencing, image generation, translation quality, second opinions |
| **Grok** (specialist) | via MCP | $ | X/Twitter search, real-time web search, cheap code review, Aurora image gen, second-opinion research, sandboxed Python |
| **Ollama** (local) | via MCP | free | Local language QA, semantic similarity, local inference. Unlimited (local GPU). Model varies by project needs. |
| **Skills** (workflow) | `/skill-name` | — | Structured workflows: `/frontend-design` for UI, `/feature-dev` for architecture, `/simplify` for cleanup, `/code-review` for PRs. Add project-specific verification skills as needed. |

## Pre-Phase Delegation Map (MANDATORY)

Before touching any file in a new phase or task batch, produce this table:

| Task ID | Title | Tier | Why |
|---------|-------|------|-----|
| X-01 | ... | Sonnet | multi-file, non-trivial state |
| X-02 | ... | Haiku | single display component |

**Rules:**
- **Haiku** if: single file, no imports from files being written in same batch, pure display or config, spec is 100% unambiguous
- **Sonnet** if: multiple files, uses store/hooks/animation, needs to reason across files
- **Opus** if: architectural decision, debugging unclear failure, trade-off with no obvious answer
- **Gemini** if: needs web/real-world knowledge, large file analysis, image generation, translation
- **Grok** if: X/Twitter search, real-time web, cheap fast inference, image gen
- **Ollama** if: local language QA, semantic similarity, zero-cost inference

**Never assign Haiku to:**
- Tasks where getting it wrong requires significant rework
- Tasks with complex animation or state logic
- Anything where context across 3+ files matters

## Milestone Gate Integration

The orchestrator MUST run `db_queries.sh check <task-id>` **before** spawning any sub-agent. The check returns three verdicts:
- **GO** → spawn the sub-agent
- **CONFIRM** → present milestone reasons + recent progress to Master, wait for "go", then spawn
- **STOP** → do not spawn, present blockers to Master

Sub-agents that independently run `check` and receive CONFIRM must return to the orchestrator without proceeding. They should never autonomously bypass a CONFIRM gate.

## Failure Escalation Protocol

### Step 1 — Diagnose the failure type

| Failure type | Signs | Action |
|---|---|---|
| Bad prompt | Agent did the wrong thing correctly | Rewrite instructions, retry same tier |
| Missing context | Agent referenced a file/type it couldn't find | Add missing file paths, retry same tier |
| Capability ceiling | Type errors, wrong architecture, logic mistakes | Escalate one tier up |
| Environment failure | Build failed, tool error | Fix environment, then retry |

### Step 2 — Escalation ladder

```
Haiku fails once  → diagnose → retry Haiku with better prompt
Haiku fails twice → escalate to Sonnet
Sonnet fails once → diagnose → retry Sonnet with better prompt
Sonnet fails twice → escalate to Opus (direct)
Opus handles it directly — no further sub-agents
```

### Step 2.5 — Architectural Review Pause (Advisory)

If 3+ fix attempts on the same problem across all tiers, pause.
This is a behavioral heuristic — v1 does not structurally track cross-tier totals.
Question: is the approach architecturally sound, or should it be redesigned?
Present concerns to Master. See `development-discipline.md` §3-Fix Architectural Pause.

### Step 3 — Log it

After any escalation, log: what task failed, which tier failed and why, what the correct tier was, whether the prompt or the model ceiling was the issue.

## Programmatic Escalation Enforcement

The escalation ladder is enforced by three hooks working together:

1. **agent-spawn-gate** (PreToolUse → Agent): blocks spawns when a tier has
   2+ failures. Returns `permissionDecision: "deny"` with next-tier guidance.
   Also enforces: delegation approval freshness, pre-task check requirement,
   CONFIRM gate compliance.

2. **escalation-tracker** (SubagentStop): detects sub-agent failures from
   `last_assistant_message` and increments the per-tier failure counter.
   Also flags completion claims without test evidence.

3. **permission-denied-tracker** (PermissionDenied): catches auto-mode denials
   during sub-agent execution and increments the failure counter.

State files (in `.claude/hooks/`, reset on session start):
- `.escalation_state` — per-tier failure counts (`tier|count|epoch|reason`)
- `.last_spawn_tier` — tier of most recently spawned sub-agent
- `.last_check_result` — verdict from last `db_queries.sh check` call
- `.last_confirm_timestamp` — timestamp of last `db_queries.sh confirm` call

Manual escalation (persists in DB across sessions):
```bash
bash db_queries.sh tier-up <TASK-ID> <NEW-TIER> <REASON>
# REASON: prompt | context | ceiling | environment
```

## Context-Aware Shortcut (Token Economics)

Before spawning a sub-agent, check whether direct execution is cheaper:

| Condition | Action |
|-----------|--------|
| Orchestrator already has target file in context AND change is <10 lines | **Do it directly** — skip sub-agent |
| Task requires reading 3+ files orchestrator hasn't seen | Delegate — sub-agent absorbs the context |
| Task is >50 lines across multiple files | Delegate — work-to-overhead ratio justifies it |
| Multiple independent tasks can run in parallel | Delegate — wall-clock savings matter |

**Why:** Sub-agents aren't free. Each spawn costs: (1) Opus tokens writing the prompt, (2) sub-agent re-reading files the orchestrator already has, (3) Opus tokens verifying the result. For a 2-line config edit, Haiku delegation costs ~40x more than Opus direct because of re-read overhead.

**Override DB tier when context makes it cheaper:** If `db_queries.sh` says tier=haiku but the orchestrator already has all needed context, execute directly and note "direct — context shortcut" in the done log.

## Parallelism Rules

Sub-agents can run in parallel **only if** they write to different files.

**Safe:** Two agents writing different components. Research + implementation (different file paths).
**Never:** Two agents touching the same file. Agent B depends on Agent A's output. Two agents that both run the build (race condition on build cache).

## Human/AI Role Division

| Human (Master) Owns | AI (Claude) Owns |
|---|---|
| Vision — what to build and why | Research — gather options, compare trade-offs |
| Architecture — how components connect | Specs — formalize decisions into documents |
| Quality bar — decide what's good enough | Plans — break specs into atomic tasks |
| Scope decisions — what's in, what's out | Code — implement tasks from plans faithfully |
| Review every plan — annotate before approving | Tests — verify implementation matches spec |
| Say "no" often — to features, complexity, scope creep | Boilerplate — config, scaffolding, documentation |

**Key principle:** Human reviews plan, AI executes plan. Human owns the "what" and "why", AI owns the "how."

## Changelog
- 2.3: Added Step 2.5 — Architectural Review Pause (advisory, cross-ref to development-discipline.md)
- 2.2: Added programmatic escalation enforcement section (3 hooks, 5 state files)
- 2.1: Added Human/AI role division
- 2.0: Added Grok/Ollama tiers, milestone gate integration with GO/CONFIRM/STOP, parallelism build cache note
- 1.0: Initial extraction from production project
