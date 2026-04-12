# Agent Delegation Logic
> Authoritative reference for model selection, sub-agent spawning, and failure escalation.
> Auto-imported by CLAUDE.md via %%RULES_FILE%%.
> Reference catalogs (Gemini tools, skills, integrations) live in `refs/`.
> **MANDATORY:** Map every task batch to tiers BEFORE executing. Never default to doing work directly.
> **MANDATORY:** The orchestrator must be Opus or opusplan. If you are Sonnet or Haiku, you must not act as orchestrator. Self-report your model at session start and gate on it — see %%RULES_FILE%% Step 3.

---

## §1 — Tier Model & Delegation Rules
> 📂 Tier definitions, assignment rules, and delegation map template in `frameworks/delegation.md`.
> Project-specific tool catalogs: `refs/tool-inventory.md`, `refs/gemini-catalog.md`, `refs/grok-catalog.md`, `refs/skills-catalog.md`.

### Milestone gate integration
The orchestrator MUST run `db_queries.sh check <task-id>` **before** spawning any sub-agent (GO/CONFIRM/STOP).

---

## §2 — Gemini MCP Tool Catalog
> 📂 Moved to `refs/gemini-catalog.md` — read when using any Gemini tool.

---

## §3 — Sub-Agent Failure Escalation Protocol
> 📂 Full escalation ladder in `frameworks/delegation.md`.

---

## §4 — Visual Verification Pipeline
> 📂 Moved to `refs/visual-verification.md` — read when doing visual verification.

---

## §5 — Parallelism Rules & Role Division
> 📂 Parallelism rules and Human/AI role division in `frameworks/delegation.md`.

---

## §6 — Skills & Plugins Catalog
> 📂 Moved to `refs/skills-catalog.md` — read when routing a task to a skill.

---

## §7 — Delegation Map for Remaining Phases

Pre-computed. Auto-regenerate from DB: `bash db_queries.sh delegation-md`

<!-- DELEGATION-START -->
<!-- Populated by db_queries.sh delegation-md after task database is seeded -->
<!-- DELEGATION-END -->
