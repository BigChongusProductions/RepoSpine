---
name: research
description: >
  Multi-source research pipeline with self-correcting retrieval and confidence scoring.
  Fans out to up to four provider tiers in parallel (Tavily web search, Gemini academic,
  local Ollama, Grok social/real-time), reconciles contradictions, and outputs
  structured claims with per-fact confidence scores.

  Use when: the user says "research [topic]", "fact-check", "cross-reference",
  "gather sources on", or any task requiring multi-source synthesis with
  citation-grade confidence.
---

# /research — Multi-Source Research Pipeline

## Overview

Self-correcting research pipeline that:

1. Decomposes a topic into sub-questions
2. Probes which provider tiers are available (T1–T4)
3. Retrieves from all available tiers in parallel
4. Checks completeness and re-retrieves gaps (max 2 rounds)
5. Reconciles contradictions with 4-tier confidence scoring
6. Outputs structured JSON claims validated against a generic schema

## Cost envelope

Typical invocation runs ~**$0.01–$0.06** depending on which tiers are active:

| Tier | Provider | Per-call | Calls typical |
|------|----------|----------|---------------|
| T1 | Tavily | ~$0.004 | 1–3 |
| T2 | Gemini | ~$0.02 | 1–2 (default cap: 3) |
| T3 | Ollama local | $0 | 1–2 |
| T4 | Grok | ~$0.001 | 0–2 |

Cap Gemini via `PHASE_2_GEMINI_BUDGET` env var (default `3`).

## Provider configuration

Provider availability is **detected**, not assumed. Edit `.claude/research-providers.conf` (at the project root) to enable/disable tiers per your project's subscription/MCP setup.

**T1 (Tavily) is REQUIRED** — it is the primary retrieval tier. If `TAVILY_API_KEY` is not set the skill exits with a clear error. T2/T3/T4 are optional and silently skipped when missing.

---

## Phase 1: Scope & Decompose (orchestrator)

Read the user's research brief and produce:

1. **Sub-questions** (3–7): decompose the topic into answerable queries
2. **Known context**: check existing research output directory if it exists
3. **Budget allocation**: Gemini requests (default 2, max `PHASE_2_GEMINI_BUDGET`)
4. **Active tiers**: run the capability probe before fan-out

### Capability-detection preamble

**Always run the probe first:**

```bash
bash .claude/skills/research/scripts/probe-providers.sh
```

This writes `.claude/skills/research/.provider-status.json` with the availability of each tier. Example output:

```json
{
  "tavily":  { "available": true,  "reason": "TAVILY_API_KEY present" },
  "gemini":  { "available": false, "reason": "no GEMINI_API_KEY, MCP not configured" },
  "ollama":  { "available": true,  "reason": "ollama MCP registered" },
  "grok":    { "available": false, "reason": "GROK_API_KEY missing" }
}
```

If `tavily.available == false`, the skill stops with:

```
❌ research skill requires at least T1 (Tavily). Set TAVILY_API_KEY or configure the Tavily MCP.
```

For missing T2/T3/T4, the skill simply omits those tiers from Phase 2's fan-out. No silent failures — every skip gets a one-line log entry.

### Phase 1 output template

Output the decomposition before proceeding:

```
## Research Brief: [topic]
Sub-questions:
1. [question]
2. [question]
...
Known context: [any existing data for this topic]
Budget: [N] Gemini requests
Active tiers: T1 + [T2 if available] + [T3 if available] + [T4 if available]
Skipped tiers: [with reasons from probe]
```

**Gate**: Brief has enough specificity to spawn agents? If not, ask ONE clarifying question.

---

## Phase 2: Multi-Source Retrieval (parallel subagents)

Spawn one agent per available tier. Each writes to its own temp section.

| Tier | Provider | Tools | Role |
|------|----------|-------|------|
| **T1: Discovery** | Sonnet+Tavily | `tavily_search`, `tavily_research`, `tavily_extract`, `tavily_crawl`, WebFetch | Primary retrieval — deep multi-source search, structured extraction from discovered pages |
| **T2: Academic** | Gemini MCP | `gemini-deep-research` or `gemini-search` + `gemini-structured` | Scholarly depth, citation-rich source discovery |
| **T3: Local QA** | Ollama MCP | `ollama_chat` (configurable model, default `qwen3:14b`) | Domain QA, diacritics/spelling, cross-check — NOT primary authority |
| **T4: Social/Real-time** | Grok MCP | `search_x`, `search_web`, `ask` | Real-time web, social threads, primary-source citations posted by practitioners |

### Agent prompt templates

**T1 (Sonnet+Tavily):**
```
Research [topic]. For each claim found, extract per the generic claim schema at
templates/claim.schema.json:
- id, claim, confidence, evidence, sources[]
- domain_metadata: any project-specific fields (coordinates, dates, sides, etc.)

Use tavily_research for deep multi-source queries.
Use tavily_search for targeted queries on specific sub-questions.
Use tavily_extract to pull structured data from promising pages.
Use tavily_crawl to explore authoritative domains.
Use WebFetch as fallback.
Focus on: [sub-questions from Phase 1]
```

**T2 (Gemini):**
```
Use gemini-deep-research (or gemini-search + gemini-structured) to find scholarly
sources on [topic]. Focus on: primary/secondary academic sources, peer-reviewed
articles, established references. For each claim, extract the same fields as T1.
Pay special attention to: exact dates, cited numbers, named attributions.
```

**T3 (Ollama local):**
```
You are a domain specialist for [topic]. Cross-check these claims from T1/T2:
[list]. For each:
1. Verify spelling/terminology/names in the domain's native language
2. Check if the domain's own tradition differs from external sources
3. Flag items commonly confused or conflated
4. Suggest items missing from the list
Output corrections/additions in the claim format.
```

**T4 (Grok):**
```
Search X/Twitter and the web for discussions about [topic].
Use search_x to find: practitioner threads, institutional posts, primary-source
citations. Use search_web for real-time sources not yet indexed.
Use ask to synthesize findings into claims.
Note: T4 findings are weighted as "community/informal" — good for leads and
corroboration, not sole authority.
```

---

## Phase 3: Completeness Evaluation (self-correcting loop)

After all tiers return, check coverage:

```
For each sub-question from Phase 1:
  - Claims addressing it?  (count)
  - Min confidence?        (HIGH/MEDIUM/LOW)
  - Any gaps?              (0 claims = gap)

If gaps AND budget remains:
  → Generate targeted follow-up queries for gaps
  → Re-run the cheapest applicable tier (T1 first, then T3)
  → Max 2 re-retrieval rounds
  → After 2 rounds: flag remaining gaps in report, proceed
```

**Gate**: All sub-questions covered with ≥ 1 claim at MEDIUM+ confidence? If yes → Phase 4. If no after 2 rounds → proceed with gaps flagged.

---

## Phase 4: Reconciliation & Confidence Scoring

Build a per-claim reconciliation matrix using `templates/reconciliation-matrix.md`.

### Confidence algorithm

- **HIGH**: 3+/4 tiers agree, or 2/2 agree with primary source citation
- **MEDIUM**: 2/4 agree, or 1 source with cited primary/secondary source
- **LOW**: 1 source only, no citation, or weak provenance
- **DISPUTED**: 2+ sources contradict with citations on both sides → flag for human review

**T4 weighting**: Grok findings are weighted as "community/informal" — they corroborate or flag discrepancies but cannot be sole authority. T4-only claim stays LOW until confirmed by T1/T2/T3.

Contradictions get a `contradictions` array with: field, values from each source, resolution reasoning.

### Reconciliation rules

1. Sources disagree on dates → prefer the one citing a primary document
2. Sources disagree on quantitative facts → use the more conservative figure, note the range
3. Sources disagree on names/titles → include all variants with notes
4. Domain-specific reconciliation (language, location, etc.) → encoded in `domain_metadata`; project-owned merge scripts resolve

---

## Phase 5: Structured Output

Generate two artifacts:

### 1. Research markdown

Save to your project's research output directory (e.g. `refs/research/{topic-slug}.md` or whatever convention your project uses).

### 2. JSON report

Save to `.claude/skills/research/reports/{YYYY-MM-DD}-{topic-slug}.json`. Must conform to `templates/report.schema.json`.

### Post-output validation

Run `validate-claims.sh` automatically:

```bash
bash .claude/skills/research/scripts/validate-claims.sh reports/{filename}.json
```

If validation fails, fix and re-run (max 2 attempts). Do NOT mark research as complete until validation passes.

---

## Exit Criteria (all must pass)

- [ ] Capability probe ran before Phase 2
- [ ] Every claim has a confidence score
- [ ] All required fields present (id, claim, confidence, sources)
- [ ] `validate-claims.sh` passes
- [ ] Report saved to `reports/` with timestamp
- [ ] Reconciliation matrix included for any multi-source claims

---

## Report Format

Present a structured report when complete:

```
## /research Report — {date}

### Topic: [topic]
### Active tiers: T1 (Tavily) [+ T2] [+ T3] [+ T4]
### Skipped tiers: [list with reasons]
### Retrieval rounds: [1-3]

### Claims
- Total: X | HIGH: Y | MEDIUM: Z | LOW: W | DISPUTED: D

### Contradictions
- [field]: [source1 value] vs [source2 value] → resolved as [value] (reason)

### Gaps
- [any unanswered sub-questions]

### Validation
- validate-claims.sh: PASS/FAIL

### Files Created
- Research: [path to markdown]
- Report: .claude/skills/research/reports/[file].json
```

---

## Gotchas

See `gotchas.md` for the full list. Quick reference:

- Gemini deep-research can hallucinate precision — never sole source for primary facts
- Local Ollama models are for QA/verification, not authority
- Sub-agent self-reported confidence is irrelevant — use the reconciliation algorithm
- Grok T4 findings are "community/informal" — corroborate but don't authoritate
- Parallel agents must write to separate sections/files
- Action first, marker last — don't mark complete until validation passes

---

## Customizing for your project

1. Edit `.claude/research-providers.conf` — enable only the tiers your project has credentials for
2. Write a project-specific `merge-*.sh` script if you want `/research` output to feed downstream data files. This skill does NOT ship a merge script — it's domain-dependent and belongs in your project's `scripts/` directory.
3. Decide your `domain_metadata` schema. Populate it in each claim; validate it with your own merge script.
