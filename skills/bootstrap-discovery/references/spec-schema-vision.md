# VISION.md — Output Schema

**Purpose:** Pitch the project to someone unfamiliar with it. Answer "what is this and why does it matter?"

**Audience:** Any reader (customer, stakeholder, developer new to project)

---

## Required Sections

### Pitch (50-150 words)

One sentence summary + 2-3 sentences explaining the problem and solution.

**Template:**
```markdown
## The Pitch

[One-liner summarizing what this is]

[Problem statement: What does this solve or enable?]
[Who does it help?]
[Why now?]
```

**Quality gates:**
- No jargon (or jargon is explained)
- Customer-facing language (not technical)
- A non-technical reader would understand the value

### Audience & Scale

Who uses this and how many.

**Template:**
```markdown
## Audience

**Primary users:** [role] (approximately [count])
**Usage pattern:** [frequency and context]
**Geographic/platform scope:** [if relevant]
```

### Done Criteria (3-5 measurable outcomes)

What success looks like for v1. **Must be observable and measurable.**

**Template:**
```markdown
## Done Criteria

v1 is complete when:
- [ ] Users can [specific action] (verified by [test or observation])
- [ ] System handles [scale or edge case]
- [ ] Performance meets [threshold] (e.g., load time < 2s, 99.9% uptime)
- [ ] [Other critical outcome]
```

**Anti-patterns:**
- "UI is polished" ❌ (not measurable)
- "Users can create accounts" ✓ (observable)

### V1 Scope (Feature List with Priorities)

**Template:**
```markdown
## V1 Scope

### Critical (app is broken without these)
- [Feature] — [brief description]
- [Feature] — [brief description]

### Core (app is useful without these, but they add major value)
- [Feature] — [brief description]

### Deferred to v2+
- [Feature] — why deferred: [reason]
- [Feature] — why deferred: [reason]
```

### What This Does NOT Do (Exclusions)

Explicit list of out-of-scope features or use cases.

**Template:**
```markdown
## Out of Scope (v1)

- [Feature] — why it's deferred
- [Use case] — why it's excluded
- [Integration] — why it's not included
```

**Quality gate:** At least 3 explicit exclusions.

### What It Replaces or Improves

**Template:**
```markdown
## What Changes

**Before:** [Current situation or tool]
**Problem with that:** [Gap or limitation]
**After:** [This project's solution]
**How it's better:** [Specific advantages]
```
