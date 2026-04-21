# /research — Known Gotchas and Failure Modes

Confirmed failure modes from past research sessions. Read before running the pipeline.

---

## Gotcha 1 — Gemini Deep-Research Hallucinates Precision

**What happens:** Gemini deep-research invents precise dates, numbers, or names when only approximate or partial information exists. It can also conflate similarly-named events or people into one.

**Symptom:** Output has suspiciously precise numbers (exact day-of-month for a medieval event, a round-number troop count cited without a source), or a description mixes details from two different underlying items.

**Fix:** Never use Gemini as the sole source for primary facts. Always cross-reference with T1 (Tavily) and T3 (local). Mark any claim sourced only from Gemini as LOW confidence. Use Gemini for source discovery — finding which books/articles to look at — not as ground truth.

---

## Gotcha 2 — Local Ollama Models Are QA, Not Authority

**What happens:** A local Ollama model (Qwen3, Llama, DeepSeek, etc. via `ollama_chat`) is excellent for domain-native spelling, terminology, and checking against domain-specific conventions. But it hallucinates detailed facts when asked to be a primary source.

**Symptom:** The local model provides plausible but unverifiable figures, invents named attributions, or presents domain-tradition interpretations as universal consensus.

**Fix:** Use local models strictly for: (1) spelling/diacritics verification, (2) native-language term checks, (3) cross-checking if the domain's own tradition disagrees with external sources, (4) identifying items missing from an externally-sourced list. Never use as sole source for dates, quantities, or analytic claims.

---

## Gotcha 3 — Domain Metadata Must Be Validated Per-Project

**What happens:** The generic `claim.schema.json` shipped with the skill validates only core fields (id, claim, confidence, sources). Domain-specific fields live in `domain_metadata` as an opaque object — validators here do NOT enforce shape on them.

**Symptom:** Your downstream merge script explodes on a missing domain field that the skill didn't catch because it's not in the core schema.

**Fix:** Write a project-specific merge/validation script that checks `domain_metadata` against your domain's schema. Run it after `validate-claims.sh` passes. The two-step design is intentional: the skill owns correctness of the retrieval/reconciliation pipeline; your project owns correctness of domain data.

---

## Gotcha 4 — Sub-Agent Findings Are Suggestions

**What happens:** Every claim from any tier is a hypothesis until verified by a second source. Past sessions accepted single-source claims at face value and later discovered errors.

**Symptom:** A claim appears in the final output with only one source but HIGH confidence because the agent was "confident."

**Fix:** Confidence scoring must be based on the reconciliation algorithm, not the agent's self-reported certainty. 1 source = LOW unless it cites a primary document. 2 agreeing sources = MEDIUM. 3 agreeing sources = HIGH. Agent says "I'm sure" = irrelevant to confidence.

---

## Gotcha 5 — Match Your Project's Output Format

**What happens:** The skill generates research markdown in one format, but your project already has a convention in its research directory. Downstream tooling (merge scripts, doc generators) breaks on format mismatch.

**Symptom:** `merge-*.sh` fails to parse the research file. Field names don't match expected patterns.

**Fix:** Before writing research markdown for the first time in a project, read one or two existing research files in your project and match their format exactly: header style, field ordering, section structure. Update the SKILL.md output template to match rather than forcing your project to match the skill.

---

## Gotcha 6 — Gemini Budget Is Shared Across Skills

**What happens:** Gemini request caps (e.g. 20/day on the free tier) are shared across all skills — `/research`, visual verification, code review, image generation. Using 5+ Gemini requests for research leaves nothing for other tasks.

**Symptom:** Later in the session, `gemini-analyze-image` or another Gemini call returns a rate-limit error.

**Fix:** Default to 2 Gemini requests per research session (`PHASE_2_GEMINI_BUDGET=2`). If the topic is large (10+ sub-questions), allocate up to 3. Prefer `gemini-search` (cheaper) over `gemini-deep-research` (expensive) when possible. Offload deep-research load onto Tavily's `tavily_research`.

---

## Gotcha 7 — Parallel Agents Must Write Separate Sections

**What happens:** Two research agents write to the same temp file or variable, causing race conditions and data loss.

**Symptom:** Research output is missing one tier's results entirely, or results are interleaved/corrupted.

**Fix:** Each tier writes to its own subagent response (T1 in one response, T2 in another, T3 in another, T4 in another). The orchestrator merges them in Phase 4. Never have two agents write to the same file concurrently.

---

## Gotcha 8 — Action First, Marker Last

**What happens:** Research is marked "complete" in the task system before the report file exists and validation passes. This is the Intent ≠ Fact pattern.

**Symptom:** Your task tracker shows the research task as DONE, but no report file exists in `reports/`, or `validate-claims.sh` was never run.

**Fix:** The completion sequence is: (1) write report file, (2) run `validate-claims.sh` → PASS, (3) write research markdown, (4) THEN mark task done. Never reverse this order. If validation fails, the task is not done — fix and retry.
