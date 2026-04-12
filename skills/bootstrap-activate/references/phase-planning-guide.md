# Phase Planning Guide

How to break a design into phases, tasks, and a delegation map.

## Phase Design Principles

1. **Each phase produces something testable.** After P0, you should be able to run the project (even if it does nothing useful). After P1, core features work. After P2, the main value proposition is delivered.

2. **Phases are sequential, tasks within a phase can be parallel.** Phase N depends on Phase N-1 being complete. But tasks T-01 and T-02 within the same phase can be worked in any order unless explicitly blocked.

3. **Front-load risk.** Put uncertain or technically challenging work in early phases. If something is going to fail, find out before you've built the rest of the app on top of it.

4. **Maximum 5-7 phases.** If you need more, your project scope is too large for v1. Push features to v2.

## Common Phase Templates

### Web/Desktop Application
```
P0-FOUNDATION  — Project setup, dependencies, base config, dev environment
P1-CORE        — Data models, core services, basic UI shell
P2-FEATURES    — Main feature implementation (the value proposition)
P3-INTEGRATION — External services, API connections, data pipelines
P4-POLISH      — Error handling, edge cases, UI refinement, accessibility
P5-DEPLOY      — Build optimization, testing, deployment, documentation
```

### CLI Tool
```
P0-FOUNDATION  — Project setup, argument parsing, basic I/O
P1-CORE        — Core logic implementation
P2-COMMANDS    — All user-facing commands
P3-POLISH      — Error messages, help text, edge cases
P4-RELEASE     — Testing, packaging, documentation
```

### API/Backend Service
```
P0-FOUNDATION  — Project setup, database schema, base middleware
P1-CORE        — Core endpoints, business logic, data access
P2-AUTH        — Authentication, authorization, security
P3-INTEGRATION — External API connections, webhooks, queues
P4-OPERATIONS  — Logging, monitoring, error handling, deployment
```

## Task Breakdown Rules

### Atomic Tasks
One task = one commit. If describing the commit message is hard, the task is too big. Split it.

**Good tasks:**
- "Create ProjectTask.swift data model with GRDB mapping"
- "Build TaskBoardView with grouped-by-project layout"
- "Add polling timer to ProjectManager (5s interval, mtime check)"

**Bad tasks (too big):**
- "Build the task board" (multiple files, multiple concerns)
- "Set up the project" (what exactly?)
- "Fix bugs" (which bugs?)

### Task Fields
| Field | Description |
|---|---|
| ID | Phase prefix + number: P0-01, P1-03, etc. |
| Phase | Which phase this belongs to |
| Title | Imperative verb + specific noun: "Create X", "Add Y to Z", "Connect A to B" |
| Assignee | CLAUDE, MASTER, or specific model (GEMINI, QWEN) |
| Tier | opus, sonnet, haiku — see delegation rules below |
| Blocked By | Task ID that must complete first (same-phase = advisory, cross-phase = hard block) |
| Priority | P0 (critical), P1 (important), P2 (nice-to-have) |

### Delegation Tier Rules

**Haiku** (single-file, mechanical, clear spec):
- Config file creation
- Single data model with no complex logic
- Boilerplate scaffolding
- Markdown documentation
- Simple utility functions

**Sonnet** (multi-file, non-trivial logic):
- Features spanning 2+ files
- Components with state management
- Service classes with business logic
- Tasks requiring cross-file reasoning

**Opus** (architecture, judgment, ambiguity):
- Architecture decisions during implementation
- Complex debugging across multiple systems
- Trade-off evaluation with no clear answer
- Anything that failed at a lower tier

**Gemini** (specialist — large context, research, images):
- Web research and factual cross-referencing
- Large file/document analysis
- Image generation and analysis
- Translation quality checks
- Python computation on data

**Grok** (specialist — X/Twitter, cheap inference, images):
- X/Twitter search for real-time context
- Real-time web search
- Cheap code review / second opinions
- Aurora image generation
- Sandboxed Python execution

**Ollama/local** (specialist — unlimited, local GPU):
- Language QA (e.g., Qwen3 for non-English text)
- Semantic similarity via embeddings
- Grounded local inference with web search

**MASTER** (human tasks):
- Design decisions requiring visual judgment
- External service configuration (API keys, accounts)
- Device-specific testing
- Final approval and review
- Asset creation (icons, images)

## Phase Gates

Every phase ends with a gate check before the next phase begins. The gate verifies:

1. All tasks in the phase are DONE (or explicitly SKIP'd with reason)
2. Implementation matches the spec intent (not just "code compiles")
3. No shortcuts were taken that will compound in later phases

**Gate format:**
```
Phase Gate: [Phase Name]
Completed: [X/Y tasks]
Must-fix: [issues that block next phase]
Follow-up: [improvements to defer]
Verdict: PASS / FAIL
```

## CLAUDE.md Template

Generate this for the project root using the **load-on-demand** pattern. Frameworks are NOT @-imported — they load when their protocol triggers. LESSONS is also NOT @-imported — it grows unboundedly and is injected by the session-start hook.

```markdown
# [Project Name] — Project Entry Point
> Cognitive rules auto-loaded from ~/.claude/CLAUDE.md (global).
> Project-specific rules imported below.

@[PROJECT]_RULES.md
@AGENT_DELEGATION.md

> LESSONS file (LESSONS_[PROJECT].md) is NOT @-imported — it grows unboundedly.
> The session-start hook injects recent lessons. Read full file on demand for correction protocol.
> Frameworks live in `frameworks/`. Load on demand — see RULES §Frameworks.
> Path-specific rules in `.claude/rules/` auto-inject when touching matching files.
> Hooks in `.claude/hooks/` enforce behavioral gates. Custom agents in `.claude/agents/`.
```

Generate this for the project root:

```markdown
# [Project Name] — Project Rules
> Auto-imported by CLAUDE.md. Contains all project-specific rules.
> Cognitive rules live in CLAUDE.md — do NOT duplicate them here.

## Project North Star
> %%PROJECT_NORTH_STAR%%

## Session Start Protocol
[Copy from MASTER_DASHBOARD_RULES.md § Session Start Protocol and customize]

## Phase Gate Protocol
[Copy from framework or inline if customized]

## Blocker Detection Rules
[Copy from framework or inline if customized]

## Pre-Task Check
[Copy from framework]

## Task Workflow
[Copy from framework]

## Tech Stack & Environment
%%TECH_STACK%%

## Git Branching
- **Always work on `dev`** — NEVER commit directly to `main`
- Commit message format: %%COMMIT_FORMAT%%

## Build & Test
%%BUILD_TEST_INSTRUCTIONS%%

## Code Standards
%%CODE_STANDARDS%%

## .gitignore Audit
%%GITIGNORE_TABLE%%

## STOP Rules (Project-Specific)
%%PROJECT_STOP_RULES%%

## Deployment Mode: Agent Tool ✅ ACTIVE

### Model Delegation
| Task Type | Model | Why |
|-----------|-------|-----|
| Architecture, code review, complex debugging | **You (Opus)** | Needs full-project reasoning |
| Feature implementation, new files from clear spec | **Sonnet sub-agent** | Good code quality, 5x cheaper |
| Repetitive edits, boilerplate, formatting | **Haiku sub-agent** | Fast, 20x cheaper, bounded tasks |
%%EXTRA_MODEL_DELEGATION%%

## Build & Test Commands
[Generate from tech stack]

## MCP Servers & Plugins Available
%%MCP_SERVERS%%
```

## Integration with Framework Files

When creating CLAUDE.md and [PROJECT]_RULES.md, ensure:
1. Root CLAUDE.md @-imports RULES and AGENT_DELEGATION only — frameworks use load-on-demand (NOT @-imported)
2. LESSONS_[PROJECT].md is NOT @-imported — it grows unboundedly. Session-start hook injects recent lessons.
3. All 9 frameworks are copied to `frameworks/` directory at project root (loaded on demand via RULES §Frameworks)
4. AGENT_DELEGATION.md uses pre-phase delegation map table format (| Task ID | Title | Tier | Why |)
5. LESSONS_[PROJECT].md has three sections: Corrections Log, Insights, Universal Patterns
