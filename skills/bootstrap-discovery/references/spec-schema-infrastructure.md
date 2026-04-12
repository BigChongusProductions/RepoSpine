# INFRASTRUCTURE.md — Output Schema

**Purpose:** Define the development architecture — how the project is built safely and efficiently. Answer "what systems protect and accelerate development?"

**Audience:** Project orchestrator, Claude Code, and development team

---

## Required Sections

### Standard Systems

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

### Delegation Model

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

### Optional Systems

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

### Project-Specific Additions

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

### External Tools

**Template:**
```markdown
## Recommended External Tools

| Tool | Purpose | Why for This Project |
|------|---------|---------------------|
| [Tool] | [What it does] | [Specific reason] |
```

### STOP Rules

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

### Hook Configuration Summary

**Template:**
```markdown
## Hook Configuration

| Hook | Trigger | What It Does |
|------|---------|-------------|
| [hook name] | [when it fires] | [what it checks/enforces] |
```
