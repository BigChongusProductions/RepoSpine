---
framework: development-discipline
version: 1.0
source: Adapted from Superpowers plugin (Jesse Vincent / @obra)
---

# Development Discipline Framework

## TDD Iron Law

NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.

Code written before its test? Delete it. Not "set aside." Not "keep as reference." Delete. Implement fresh from tests.

**Cycle:** Write failing test → Verify RED (fails for expected reason, not typo) → Implement minimal code to pass → Verify GREEN → Refactor (keep tests green) → Repeat.

**Carveouts — TDD does not apply to:**
- Configuration files, generated code, documentation
- Test infrastructure improvements (when the test IS the deliverable)
- Exploratory spikes and temporary diagnostic instrumentation — but spikes must be thrown away before starting the real implementation. If spike code survives into production, it was not a spike.

When uncertain whether TDD applies, ask Master.

### Anti-Rationalization Table

| Rationalization | Reality |
|---|---|
| "Too simple to test" | Simple code breaks. A test takes 30 seconds. |
| "I'll write tests after" | Tests written after verify what you built, not what was required. You only catch what you remembered. |
| "Keep code as reference, write tests first" | You will adapt it. That is testing after. Delete means delete. |
| "Need to explore the approach first" | Fine — throw away the exploration, then start fresh with TDD. |
| "TDD will slow me down" | TDD finds bugs at write time instead of debug time. The investment is always repaid. |

## Debugging Discipline

NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.

### Before Proposing Any Fix:
1. **Read error messages completely** — they often contain the answer
2. **Reproduce consistently** — if you cannot trigger it reliably, you cannot fix it
3. **Check recent changes** — git diff, recent commits, new dependencies, config changes
4. **For multi-component bugs** — instrument every component boundary, run once, analyze WHERE it breaks:
   - Log what data enters each component
   - Log what data exits each component
   - Verify environment/config propagation at each boundary
   - Identify the failing layer BEFORE proposing a fix

### Anti-Rationalization Table

| Red Flag | Action |
|---|---|
| "Quick fix for now, investigate later" | STOP. Later never comes. Investigate now. |
| "Just try changing X and see" | STOP. Form a hypothesis first. One variable at a time. |
| "Multiple changes at once to save time" | STOP. Cannot isolate what worked. Causes new bugs. |
| "I don't fully understand but this might work" | STOP. Understanding IS the prerequisite for a real fix. |

### 3-Fix Architectural Pause (Advisory)

If 3 fix attempts fail on the same problem — counted TOTAL across all tiers, not per-tier — pause and question the architecture.

This is a behavioral heuristic. No hook currently tracks cross-tier attempt totals. Count mentally or in session notes. If each fix reveals a new problem in a different place, the pattern itself may be fundamentally unsound.

Present architectural concerns to Master before attempting fix #4. See also: delegation.md §Step 2.5.

## Completion Self-Check

For **sub-agent work**: use the verifier agent (`.claude/agents/verifier.md`). It has a concrete PASS/FAIL contract — do not duplicate or override it.

For **self-review** before marking a task done:
- Tests exist for every new behavior and were written before implementation
- Implementation is minimal — nothing beyond what the tests require
- No scope creep beyond the assigned task
- Failure cases are handled explicitly, not silently swallowed
- No unexpected warnings or errors in test/build output (environment-level warnings such as SAST startup issues are acceptable if documented in quality-gates.md)

## Changelog
- 1.0: Initial version. TDD iron law, debugging discipline, 3-fix advisory, completion self-check. Adapted from Superpowers plugin.
