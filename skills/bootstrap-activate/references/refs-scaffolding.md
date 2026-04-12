# refs/ Scaffolding Guide

How to set up the progressive disclosure directory with starter reference files during engine deployment.

---

## Purpose

The `refs/` directory holds on-demand reference material that Claude loads only when relevant. This saves ~70% context at startup vs loading everything into RULES.md. The principle: RULES.md stays under ~350 lines of core protocol; anything that grows beyond ~50 lines gets extracted to a ref file.

---

## Mandatory Starter Refs (created during D1)

Every project gets these skeleton refs during engine deployment:

### refs/tool-inventory.md

Master inventory of all tools available to the project. Created with detected tools, expanded as new tools are configured.

```markdown
# Tool Inventory
> Quick reference for delegation decisions. Read before assigning tiers.
> Last updated: [deployment date]

## Claude Models
| Model | Cost | When to Use |
|-------|------|-------------|
| Opus (claude-opus-4-6) | $$$$ | Architecture, gate reviews, judgment calls |
| Sonnet (claude-sonnet-4-6) | $$ | Multi-file features, cross-file reasoning |
| Haiku (claude-haiku-4-5) | $ | Single-file, config, clear spec |

## MCP Servers
[Auto-detect from environment and list here]
| Server | Tools | Rate Limits | When to Use |
|--------|-------|-------------|-------------|

## Plugins
[List installed plugins]
| Plugin | Skills | Commands |
|--------|--------|----------|

## External Tools
[List any external APIs, services, or tools the project uses]
| Tool | Purpose | Access |
|------|---------|--------|

## Budget Dashboard
| Tier | Sessions Today | Estimated Cost |
|------|---------------|----------------|
| Opus | — | — |
| Sonnet | — | — |
| Haiku | — | — |
| MCP tools | — | — |
```

### refs/skills-catalog.md (if project uses custom skills)

```markdown
# Skills Catalog
> Routing rules for skills. Read when choosing how to execute a task.

## Available Skills
| Skill | Trigger | What It Does | Chain After |
|-------|---------|-------------|-------------|
[Populated from detected skills or left as template]

## Skill Chains
Composition rules — which skill follows which:

| Chain Name | Sequence | When to Use |
|------------|----------|-------------|
| Pre-merge | /code-review → fix issues → /code-review | Before any dev→main merge |
| Post-correction | Log lesson → /code-review on affected area | After any correction from Master |
[Add project-specific chains as they emerge]
```

### refs/gotchas-workflow.md

```markdown
# Workflow Gotchas
> Point-of-use warnings distilled from LESSONS. Read before session/workflow tasks.
> Auto-generated from correction patterns. Update when new patterns emerge.

## Active Gotchas
[Empty at deployment — populated by gotcha generation protocol]

## Template
When adding a gotcha:
- **Gotcha:** [What can go wrong]
- **Why:** [Root cause / how it was discovered]
- **Prevention:** [What to do instead]
- **Source:** [LESSONS entry or loopback ID]
```

---

## Conditional Starter Refs (based on INFRASTRUCTURE.md)

### refs/gotchas-frontend.md (if project has UI)

Same template as gotchas-workflow.md but for frontend-specific issues (SSR guards, animation pitfalls, responsive edge cases).

### refs/planned-integrations.md (if BLUEPRINT.md lists deferred integrations)

```markdown
# Planned Integrations
> Researched but not-yet-implemented integrations. Read when reaching integration phases.

| Integration | Phase | Status | Notes |
|-------------|-------|--------|-------|
[Populated from BLUEPRINT.md "Deferred to v2+" section]
```

### refs/visual-verification.md (if visual verification is active)

```markdown
# Visual Verification Reference
> Targeted query templates for screenshot verification. Read when needs_browser=1.

## Verification Templates
[Populated based on project type — web, desktop, mobile]

## Known Visual States
[Empty — populated as visual verification runs]
```

---

## How Refs Grow Over Time

The initial scaffolding is minimal. Refs grow through two mechanisms:

### 1. Section Extraction from RULES.md

When any RULES.md section exceeds ~50 lines:
1. Extract the content to `refs/[section-name].md`
2. Replace in RULES.md with: `> 📂 Moved to refs/[section-name].md — read when [trigger].`
3. Add to coherence_registry.sh if renaming concepts

### 2. Gotcha Generation from LESSONS

When corrections accumulate in a domain (see session-protocol gotcha generation):
1. Create `refs/gotchas-[domain].md`
2. Distill each correction into point-of-use format
3. Reference from RULES.md near the relevant section

---

## Deployment Step (in D1)

During engine deployment, create refs/ with these files:

```bash
mkdir -p refs/
# Always create:
# - refs/README.md (directory index)
# - refs/tool-inventory.md (detected tools)
# - refs/gotchas-workflow.md (empty template)

# Conditionally create (based on INFRASTRUCTURE.md):
# - refs/skills-catalog.md (if custom skills)
# - refs/gotchas-frontend.md (if UI project)
# - refs/planned-integrations.md (if deferred integrations exist)
# - refs/visual-verification.md (if visual verification active)
```

After creating, add refs/ to the RULES.md "Progressive Disclosure" section with one-line pointers to each file.

---

## Changelog
- 1.0: Initial creation for project-bootstrap v0.3.0
