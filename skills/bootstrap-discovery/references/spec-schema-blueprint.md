# BLUEPRINT.md — Output Schema

**Purpose:** Record the product architecture and technical decisions. Answer "how is the product built?"

**Audience:** Project team and future maintainers

---

## Required Sections

### System Architecture

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

### Tech Stack

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

### Data Model

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

### Cost Constraint Summary

**Template:**
```markdown
## Constraints

**Development budget:** [$X or "unbounded"]
**Monthly operations:** [$X or "unbounded"]
**Key limitations:** [specific tool/service restrictions]
**Available tools:** [confirmed available — cloud, auth, DB, etc.]
**Forbidden tools:** [explicitly cannot use]
```

### Scope In / Scope Out

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

### Key Decisions Log

**Template:**
```markdown
## Decision Log

| Decision | Options Considered | Chosen | Why | Source |
|----------|-------------------|--------|-----|--------|
| [Decision] | [Options] | [Choice] | [Justification] | [RESEARCH.md section or constraint] |
```

### Project Structure

**Template:**
```markdown
## Project Structure

[Directory tree showing planned project layout]
```
