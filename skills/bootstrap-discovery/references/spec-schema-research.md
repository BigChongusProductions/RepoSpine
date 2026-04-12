# RESEARCH.md — Output Schema

**Purpose:** Ground decisions in evidence from real research. Answer "what exists, what's viable, and what are the risks?"

**Audience:** Project team (technical and non-technical)

---

## Required Sections

### Prior Art & Competitive Analysis

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

### Technical Feasibility

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

### Tech Landscape

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

### Architecture Patterns

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

### Risks and Unknowns

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

### Sources

```markdown
## Research Sources

- [Description] — [URL]
- [Description] — [URL]
```

**Quality gate:** Every factual claim in this document has a corresponding source.
