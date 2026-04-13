# Bootstrap Discovery — Spec Output Schemas

Reference file for `bootstrap-discovery` skill. Contains output format templates for all four spec files, quality rules, and validation checklist.

---

## Overview

The discovery process produces four spec files:

1. **VISION.md** — What and why (product vision, audience, scope)
2. **RESEARCH.md** — Evidence base (prior art, feasibility, tech evaluation)
3. **BLUEPRINT.md** — Product architecture (tech stack, data model, architecture, decisions)
4. **INFRASTRUCTURE.md** — Development architecture (systems, delegation, hooks, monitoring)

Each has a specific structure, quality standards, and validation rules.

---

## File 1: VISION.md

**Purpose:** Pitch the project to someone unfamiliar with it. Answer "what is this and why does it matter?"

**Audience:** Any reader (customer, stakeholder, developer new to project)

### Required Sections

#### Pitch (50-150 words)

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

#### Audience & Scale

Who uses this and how many.

**Template:**
```markdown
## Audience

**Primary users:** [role] (approximately [count])
**Usage pattern:** [frequency and context]
**Geographic/platform scope:** [if relevant]
```

#### Done Criteria (3-5 measurable outcomes)

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

#### V1 Scope (Feature List with Priorities)

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

#### What This Does NOT Do (Exclusions)

Explicit list of out-of-scope features or use cases.

**Template:**
```markdown
## Out of Scope (v1)

- [Feature] — why it's deferred
- [Use case] — why it's excluded
- [Integration] — why it's not included
```

**Quality gate:** At least 3 explicit exclusions.

#### What It Replaces or Improves

**Template:**
```markdown
## What Changes

**Before:** [Current situation or tool]
**Problem with that:** [Gap or limitation]
**After:** [This project's solution]
**How it's better:** [Specific advantages]
```

---

## File 2: RESEARCH.md

**Purpose:** Ground decisions in evidence from real research. Answer "what exists, what's viable, and what are the risks?"

**Audience:** Project team (technical and non-technical)

### Required Sections

#### Prior Art & Competitive Analysis

**Template:**
```markdown
## Existing Solutions

| Product | How it works | Strengths | Weaknesses | Price | Source |
|---------|-------------|----------|-----------|-------|--------|
| [Tool A] | [Brief description] | [Why it's good] | [Gap it leaves] | [Cost] | [URL] |
| [Tool B] | [Brief description] | [Why it's good] | [Gap it leaves] | [Cost] | [URL] |
| [Tool C] | [Brief description] | [Why it's good] | [Gap it leaves] | [Cost] | [URL] |

### What We Learn From These
- [Lesson from Tool A's approach]
- [Lesson from Tool B's failure mode]
- [Pattern that works across all of them]
```

**Quality gates:**
- Minimum 3 entries (real products, not made up)
- Each weakness is specific (not "not as good")
- Sources cited (URLs from web research)

#### Technical Feasibility

**Template:**
```markdown
## Feasibility Assessment

### What's Proven
- [Aspect] — evidence: [source/finding from research]

### What's Hard
- [Challenge] — how others solved it: [research findings]
- [Challenge] — risk level: [assessment with evidence]

### What's Unknown
- [Unknown] — how to resolve: [prototype, research, or ask expert]
```

#### Tech Landscape

**Template:**
```markdown
## Technology Evaluation

### Recommended Stack
| Component | Choice | Why | Maintenance Status | Alternatives Considered |
|-----------|--------|-----|-------------------|------------------------|
| [Language] | [Choice] | [Reason tied to constraints] | [Last release, activity] | [What else was evaluated] |
| [Framework] | [Choice] | [Reason] | [Status] | [Alternatives] |
| [Database] | [Choice] | [Reason] | [Status] | [Alternatives] |

### Evaluation Evidence
- [Technology]: [specific findings from web research — community health, recent issues, ecosystem]
- [Technology]: [specific findings]
```

**Quality gate:** Each technology has maintenance status evidence, not just opinion.

#### Architecture Patterns

**Template:**
```markdown
## Architecture Analysis

### How Similar Products Are Built
- [Product/pattern] at [scale]: [architecture description, source]
- [Product/pattern] at [scale]: [architecture description, source]

### Recommended Pattern
[Why this pattern fits our constraints and scale]

### Common Failure Modes
- [Failure mode] — how to avoid: [mitigation]
- [Failure mode] — how to avoid: [mitigation]
```

#### Risks and Unknowns

**Template:**
```markdown
## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk] | [High/Med/Low] | [What breaks] | [How to handle] |

## Open Questions
1. [Question] — how to resolve: [action]
2. [Question] — how to resolve: [action]
```

#### Sources

```markdown
## Research Sources

- [Description] — [URL]
- [Description] — [URL]
```

**Quality gate:** Every factual claim in this document has a corresponding source.

---

## File 3: BLUEPRINT.md

**Purpose:** Record the product architecture and technical decisions. Answer "how is the product built?"

**Audience:** Project team and future maintainers

### Required Sections

#### System Architecture

**Template:**
```markdown
## System Architecture

[ASCII or Mermaid diagram showing major components and data flow]

### Components
- **[Component]:** [What it does, key responsibilities]
- **[Component]:** [What it does, key responsibilities]

### Data Flow
[Description of how data moves through the system]
```

**Quality gate:** Diagram shows all major components, data flows are clear, external systems visible.

#### Tech Stack

**Template:**
```markdown
## Tech Stack

| Component | Choice | Why | Trade-off Accepted |
|-----------|--------|-----|--------------------|
| [Language] | [Choice] | [Traced to research/constraint] | [What was rejected and why] |
| [Frontend] | [Choice] | [Traced to research/constraint] | [Alternatives rejected] |
| [Database] | [Choice] | [Traced to research/constraint] | [Alternatives rejected] |
| [Hosting] | [Choice] | [Traced to research/constraint] | [Alternatives rejected] |
```

**Quality gate:** Every row has "Why" tracing to RESEARCH.md or a stated constraint.

#### Data Model

**Template:**
```markdown
## Data Model

### Core Entities
| Entity | Key Fields | Relationships |
|--------|-----------|--------------|
| [Entity] | [field: type, field: type] | [belongs to X, has many Y] |

### Key Constraints
- [Constraint, e.g., "email must be unique per tenant"]
```

#### Cost Constraint Summary

**Template:**
```markdown
## Constraints

**Development budget:** [$X or "unbounded"]
**Monthly operations:** [$X or "unbounded"]
**Key limitations:** [specific tool/service restrictions]
**Available tools:** [confirmed available — cloud, auth, DB, etc.]
**Forbidden tools:** [explicitly cannot use]
```

#### Scope In / Scope Out

**Template:**
```markdown
## Scope Definition

### In Scope (v1)
- [Feature] — [what it includes]

### Deferred (future phases)
- [Feature] — why: [reason]

### Explicitly Excluded
- [Feature] — why: [design decision]
```

**Quality gate:** Nothing ambiguous. Every feature clearly in or out.

#### Key Decisions Log

**Template:**
```markdown
## Decision Log

| Decision | Options Considered | Chosen | Why | Source |
|----------|-------------------|--------|-----|--------|
| [Decision] | [Options] | [Choice] | [Justification] | [RESEARCH.md section or constraint] |
```

#### Project Structure

**Template:**
```markdown
## Project Structure

[Directory tree showing planned project layout]
```

---

## File 4: INFRASTRUCTURE.md

**Purpose:** Define the development architecture — how the project is built safely and efficiently. Answer "what systems protect and accelerate development?"

**Audience:** Project orchestrator, Claude Code, and development team

### Required Sections

#### Standard Systems

**Template:**
```markdown
## Standard Development Systems

All systems below are active. Each is configured for this project's specific needs.

### Quality Gates
**What they check:** [project-specific — e.g., "cargo clippy, cargo test, rustfmt check"]
**Thresholds:** [project-specific — e.g., "zero warnings, all tests pass, coverage > 80%"]
**Why for this project:** [specific reason tied to architecture]

### Phase Gates
**Phase structure:**
| Phase | Focus | Gate Criteria |
|-------|-------|--------------|
| [Phase name] | [What gets built] | [What must be true to advance] |

### Correction Protocol & Learning
**How it works here:** [project-specific — what kinds of mistakes to watch for given the architecture]
**Lesson log:** LESSONS_[PROJECT].md

### Loopback Tracking
**What to watch for:** [project-specific — e.g., "data model changes that require migration rewrites"]

### Project Memory
**Critical knowledge:** [what matters for this codebase — e.g., "auth flow uses refresh tokens, never access tokens for API calls"]

### Coherence System
**Cross-file consistency points:** [project-specific — e.g., "API route names must match frontend service methods"]

### Session Protocol
**Startup checklist:** [project-specific items]
**Shutdown checklist:** [project-specific items]

### Falsification Protocol
**How to verify claims:** [project-specific — e.g., "always check API responses against the contract, not just status codes"]
```

#### Delegation Model

**Template:**
```markdown
## Delegation Model

### Hierarchy
- **Orchestrator (Opus):** Architecture, gate reviews, judgment calls, cross-component coordination
- **Implementer (Sonnet):** Multi-file features, cross-file reasoning, state management
- **Worker (Haiku):** Single-file tasks, config, clear-spec implementation

### Component → Tier Mapping
| Component/Area | Default Tier | Why |
|---------------|-------------|-----|
| [Component] | [Tier] | [Reason — e.g., "cross-file state" or "single config file"] |

### Sub-Agent Spawning Rules
- [When to spawn parallel agents — e.g., "independent UI components can be built in parallel"]
- [Escalation rules — e.g., "Haiku fails 2x → Sonnet, Sonnet fails 2x → Opus direct"]

### Orchestrator Model
**Primary:** claude-opus-4-6 (Opus)
**Reason:** [project-specific — complexity level, judgment requirements]
```

#### Optional Systems

**Template:**
```markdown
## Optional Systems

### Visual Verification: [ACTIVE / INACTIVE]
**Reason:** [why enabled/disabled for this project]
[If active:]
**What to screenshot:** [specific pages/components]
**What to check:** [layout, spacing, colors, responsiveness, etc.]
**Tools:** Playwright MCP + Claude Vision

### Agent Teams: [ACTIVE / INACTIVE]
**Reason:** [why enabled/disabled — cost vs parallelism benefit]
[If active:]
**Parallel workstreams:** [which components can be built simultaneously]
**Cost estimate:** ~[X]x token usage
```

#### Project-Specific Additions

**Template:**
```markdown
## Project-Specific Systems

[Only include if research identified needs beyond the standard set]

### [System Name]
**What it does:** [description]
**Why this project needs it:** [traced to research finding or architecture characteristic]
**Implementation:** [how it hooks into the workflow]
```

**Examples of project-specific additions:**
- Contract testing hooks (API projects)
- Migration validation gates (complex data models)
- Performance regression monitoring (real-time features)
- Deployment staging gates (multi-environment)
- Secret scanning hooks (security-sensitive)

#### External Tools

**Template:**
```markdown
## Recommended External Tools

| Tool | Purpose | Why for This Project |
|------|---------|---------------------|
| [Tool] | [What it does] | [Specific reason] |
```

#### STOP Rules

**Template:**
```markdown
## STOP Rules

### Universal (always active)
- Never delete production data without backup
- Never force-push to main
- Never commit secrets

### Project-Specific
- [Rule] — why: [tied to architecture]
- [Rule] — why: [tied to architecture]
```

#### Hook Configuration Summary

**Template:**
```markdown
## Hook Configuration

| Hook | Trigger | What It Does |
|------|---------|-------------|
| [hook name] | [when it fires] | [what it checks/enforces] |
```

---

## Quality Rules (Apply to All Spec Files)

### Rule 1: No TODOs or Placeholders
Every `%%TAG%%` must be replaced with actual content. If you can't fill a section, delete it.

### Rule 2: No Vague Language
Scan for: "might", "could", "probably", "seems", "if we", "later", "possibly", "eventually"
Replace with specific decisions.

### Rule 3: Every Tech Choice References a Constraint
No orphaned technology decisions. Each "why" must trace to a constraint or RESEARCH.md.

### Rule 4: Scope Has No Ambiguity
Every feature is clearly in-scope or out-of-scope.

### Rule 5: Architecture Diagrams Required
Non-trivial projects must include system architecture diagrams.

### Rule 6: Prior Art Must Be Researched
Claims about existing tools or market trends must cite sources (URLs).

### Rule 7: Decisions Are Traceable
Every decision in BLUEPRINT.md has a "why" that traces to research or constraints.

### Rule 8: No Forward References
Don't reference tasks, phases, or features not yet defined.

### Rule 9: Dev Systems Are Project-Specific
INFRASTRUCTURE.md descriptions must reference this project's actual architecture, not generic descriptions.

### Rule 10: Correction Pass Must Be Run
Before presenting specs, review every rule, fix violations, verify zero tags remain.

---

## Validation Checklist

Use before marking specs complete:

```markdown
## Pre-Approval Checklist

- [ ] VISION.md: Pitch is customer-facing (non-expert readable)
- [ ] VISION.md: Done criteria are measurable (not subjective)
- [ ] VISION.md: Exclusions section has 3+ items
- [ ] VISION.md: V1 scope has clear priority tiers
- [ ] RESEARCH.md: Prior art table has 3+ real products with sources
- [ ] RESEARCH.md: All claims cite URLs
- [ ] RESEARCH.md: Tech evaluations include maintenance status
- [ ] RESEARCH.md: Risks are identified with mitigations
- [ ] BLUEPRINT.md: Tech stack table has "Why" and "Trade-off" columns
- [ ] BLUEPRINT.md: Architecture diagram present
- [ ] BLUEPRINT.md: Data model includes core entities
- [ ] BLUEPRINT.md: Scope In/Out is comprehensive
- [ ] BLUEPRINT.md: Decision log traces all choices
- [ ] INFRASTRUCTURE.md: Every standard system has project-specific explanation
- [ ] INFRASTRUCTURE.md: Delegation model maps tiers to components
- [ ] INFRASTRUCTURE.md: STOP rules are architecture-specific
- [ ] INFRASTRUCTURE.md: No %%TAGS%% remain
- [ ] All spec files follow Quality Rules 1-10
- [ ] Correction Pass has been run

GATE RULE: All checkboxes must be true to present to user.
```

---

## Changelog

- 2.0: Complete restructure — 4 new spec files (VISION, RESEARCH, BLUEPRINT, INFRASTRUCTURE), added research-backed quality gates, project-specific infrastructure requirements
- 1.0: Initial creation with ENVISION, RESEARCH, DECISIONS, FRAMEWORK schemas
