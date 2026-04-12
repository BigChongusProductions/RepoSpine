# Bootstrap Discovery Guide

Internal reference for the `bootstrap-discovery` skill. Contains the information extraction checklist, research protocol, collaboration guidelines, and phase transition signals.

**This is not shown to the user.** It guides Claude's behavior during the collaborative discovery process.

---

## Section 1: Information Areas (Internal Tracking)

These 12 areas must be covered before specs can be written. Track them silently through natural conversation — never expose as a questionnaire. Fill gaps by weaving questions into the discussion naturally.

### Area 1: Project Type & Platform
**What to listen for:** "app", "website", "tool", "API", "CLI", platform names (iOS, web, desktop)
**Extraction signals:** Project classification emerges naturally from the idea description
**Default if delegated:** Infer from tech stack discussion or research findings
**Maps to:** VISION.md

### Area 2: Audience & Scale
**What to listen for:** Mentions of users, customers, "for me", "for my team", numbers, usage patterns
**Extraction signals:** Who uses it and how many
**Default if delegated:** "Solo developer / small team" unless scope suggests otherwise
**Maps to:** VISION.md

### Area 3: Deployment Target
**What to listen for:** Hosting mentions, cloud providers, "local", "serverless", "self-hosted"
**Extraction signals:** Where the software runs in production
**Default if delegated:** Recommend based on tech stack and scale during architecture discussion
**Maps to:** BLUEPRINT.md

### Area 4: Problem / Replacement
**What to listen for:** "currently we use", "no tool exists", "replacing X", pain points
**Extraction signals:** What this replaces or enables that doesn't exist
**Default if delegated:** Infer from the idea description — if nothing exists, note that
**Maps to:** VISION.md

### Area 5: V1 Scope & Features
**What to listen for:** Feature lists, workflow descriptions, "must have", "MVP", priorities
**Extraction signals:** What the first version must do to be useful
**Default if delegated:** Propose based on research — "based on similar products, v1 typically needs X, Y, Z"
**Maps to:** VISION.md

### Area 6: Platform Constraints
**What to listen for:** Browser support, OS versions, compatibility requirements
**Extraction signals:** Technical limitations on where the software must work
**Default if delegated:** "Modern browsers/latest OS" unless user specifies otherwise
**Maps to:** BLUEPRINT.md

### Area 7: Cost Constraints
**What to listen for:** Budget mentions, "free tier", "cheap", spending limits, hosting costs
**Extraction signals:** Hard limits on development and operational costs
**Default if delegated:** Assume moderate budget, recommend cost-efficient options
**Maps to:** BLUEPRINT.md

### Area 8: Available Tools & Integrations
**What to listen for:** Specific tools mentioned ("we use AWS", "I have a Stripe account"), existing infrastructure
**Extraction signals:** What the user already has access to
**Critical rule:** NEVER assume availability. Verify: "which of these do you already have?"
**Default if delegated:** Research and recommend; confirm before finalizing
**Maps to:** BLUEPRINT.md

### Area 9: Tech Stack
**What to listen for:** Language preferences, framework mentions, "I know React", database preferences
**Extraction signals:** Any stated technology preferences or expertise
**Default if delegated:** Research and recommend based on project needs — this is the PRIMARY research output
**Maps to:** BLUEPRINT.md

### Area 10: Scope Boundaries
**What to listen for:** "not for v1", "later", "won't include", explicit exclusions
**Extraction signals:** What's deliberately out of scope
**Default if delegated:** Propose boundaries based on research and scope trimming
**Maps to:** BLUEPRINT.md

### Area 11: Development Systems Config
**What to listen for:** Rarely volunteered — surface during dev architecture discussion
**Extraction signals:** Preferences about development workflow, CI/CD, monitoring
**Default if delegated:** Deploy full standard set; recommend project-specific additions based on architecture
**Maps to:** INFRASTRUCTURE.md

### Area 12: STOP Rules
**What to listen for:** "never", "don't touch", "avoid", restrictions
**Extraction signals:** Hard rules for what Claude must not do
**Default if delegated:** Suggest based on architecture: "Given your data model, I'd add 'never modify migration files without explicit approval'"
**Maps to:** INFRASTRUCTURE.md

### Gap Filling Rules

- After the conversation naturally winds down but gaps remain, weave them in: "Before we lock specs, a couple things I need to nail down — [natural question]."
- Maximum 3 attempts to fill any single gap. After that, use a reasonable default and flag it in the spec for user review.
- Group related gaps into single questions. Don't ask 12 separate things.
- Never present the checklist to the user. They should feel like they're having a conversation, not filling out a form.

---

## Section 2: Research Protocol

### When to Research
- **Immediately after understanding the idea** (Phase 3). Don't wait.
- **When the user mentions a technology** you need to evaluate
- **When debating architecture** and you need real-world evidence
- **When the user pushes back** on a recommendation — research their alternative

### What to Search For

**Prior art searches:**
- "[idea] tool" / "[idea] app" / "[idea] open source"
- "[category] comparison 2025/2026"
- Look for: pricing, features, architecture (if open source), user reviews

**Feasibility searches:**
- "[tech stack] [project type] production" / "[tech stack] scale"
- "[specific challenge] solution" / "[specific challenge] best practices"
- Look for: blog posts, postmortems, Stack Overflow discussions, GitHub repos

**Tech evaluation searches:**
- "[library/framework] maintenance status" / "[library] vs [alternative]"
- "[library] GitHub" (check stars, recent commits, open issues)
- Look for: last release date, contributor activity, breaking changes, migration stories

**Architecture searches:**
- "[product type] architecture" / "[product type] system design"
- "[scale level] [tech] deployment"
- Look for: diagrams, component breakdowns, data flow descriptions

### Research Depth

- **Minimum:** 2 web searches per major decision (tech stack, architecture, database)
- **Ideal:** 4-6 searches covering different angles (viability, alternatives, pitfalls, scale)
- **When to go deeper:** If initial results are contradictory, if the user challenges your recommendation, if the project has unusual requirements
- **Stop when:** You can recommend with specific evidence from multiple sources

### How to Evaluate Tech Stacks

For each technology being considered:

1. **Is it maintained?** Check last release date, open PRs, contributor count
2. **Does it fit the scale?** Search for projects at similar scale using it
3. **What's the ecosystem?** Libraries, tools, hosting support
4. **What are the failure modes?** Search for common problems, migration horror stories
5. **What does the community say?** Recent discussions, satisfaction levels
6. **Does it match the team?** User's stated expertise or learning curve

---

## Section 3: Collaboration Guidelines

### When to Suggest Improvements
- User describes a feature that has a well-known better pattern → suggest the pattern
- Research reveals a simpler approach → offer it with evidence
- User's scope is too large for v1 → propose trimming with reasoning
- Architecture has a known weakness → flag it proactively

### When to Challenge Assumptions
- User says "no backend" but features require server state
- User chooses a technology that doesn't fit their constraints (budget, scale, team)
- User's v1 scope contradicts their timeline or resources
- User dismisses a concern that research shows is significant

### When to Research Deeper
- Your initial recommendation feels uncertain
- The user raises a valid counterpoint you can't address from memory
- A technology you're recommending might have changed recently
- The architecture has a component you're not confident about

### Handling "You Decide"
If the user says "I don't care" or "you pick":
1. Make the decision based on research and constraints
2. State the decision with clear reasoning
3. Document it as "Delegated decision" in the spec
4. Flag for user review: "I chose X because Y — does this match your thinking?"

### Handling Contradictions
If the user gives contradictory answers (e.g., "tight budget" + "use premium SaaS"):
1. Surface the conflict directly: "You mentioned keeping costs low but also using [expensive tool]. Which is the real constraint?"
2. Don't resolve it yourself — let the user decide
3. Document the resolution

### Handling One-Sentence Brain Dumps
If the user says very little ("I want to build a todo app"):
- Reflect what you have, then ask ONE natural follow-up: "Interesting — what's different about this from the hundred todo apps out there? What's the specific problem you're solving?"
- Let the conversation draw out details organically
- Don't launch into 10 questions

### Handling "Just Ask Me Questions"
If the user wants a more structured approach:
- Respect it. Shift to a guided conversation style
- Ask in clusters of 2-3 related questions, not a single long form
- Still do research between clusters — don't just collect answers

### Handling Existing Specs or PRDs
If the user says "I have a PRD" or pastes a document:
- Treat it as the brain dump (Phase 1 input)
- Extract what you can, reflect back understanding
- Research based on what's described — verify feasibility
- Challenge anything that doesn't hold up under research

---

## Section 4: Spec Quality Rules

Apply these before presenting any spec to the user.

### Universal Rules (all specs)

1. **No TODOs or placeholders** — zero `%%TAG%%` or `[TBD]` remaining
2. **No vague language** — scan for: "might", "could", "probably", "seems", "if we", "later", "possibly". Replace with specific decisions.
3. **Every tech choice references a constraint or research** — no orphaned decisions
4. **Scope has no ambiguity** — every feature clearly in or out
5. **No forward references** — don't reference tasks or phases not yet defined

### VISION.md Specific
6. Pitch is customer-facing (non-expert readable)
7. Done criteria are measurable ("users can X" not "UI is polished")
8. Exclusions section has 3+ explicit items

### RESEARCH.md Specific
9. Prior art table has 3+ real products (not made up)
10. Claims cite sources (URLs from web research)
11. Tech evaluations include maintenance status evidence

### BLUEPRINT.md Specific
12. Tech stack table has "Why" and "Trade-off" columns
13. Architecture diagram present for non-trivial projects
14. Data model includes core entities with relationships
15. Decision log traces each choice to research or constraint

### INFRASTRUCTURE.md Specific
16. Every standard system has a project-specific explanation (not generic)
17. Delegation model maps tiers to actual project components
18. STOP rules are specific to the architecture (not just "don't break things")
19. Any project-specific additions are justified by research findings

### Correction Pass Process
Before presenting specs:
1. Review every rule above
2. Fix violations
3. Verify no `%%TAGS%%` remain
4. Present corrected specs as summaries

---

## Section 5: Phase Transition Signals

### Phase 2 → Phase 3 (Understand → Research)
**Ready when:** Claude can articulate what the project is, who it's for, and roughly what it does. The user has confirmed the reflection.
**Not ready when:** The idea is still too vague to research (can't tell what to search for).

### Phase 3 → Phase 4 (Research → Architecture)
**Ready when:** Prior art is mapped, tech stack has a clear recommendation, feasibility is confirmed, major risks are identified.
**Not ready when:** Key technical questions are unanswered, user hasn't responded to research findings, alternative approaches haven't been evaluated.

### Phase 4A → Phase 4B (Product Arch → Dev Arch)
**Ready when:** Architecture diagram exists, tech stack is locked, scope is defined, hard decisions are made.
**Not ready when:** User is still debating core architecture choices or scope.

### Phase 4 → Phase 5 (Architecture → Spec Review)
**Ready when:** Both product and dev architecture are discussed, user seems satisfied with the direction, internal checklist shows no critical gaps.
**Not ready when:** Major architectural questions remain open, dev infrastructure hasn't been discussed, user has unresolved concerns.

### General Rule
If you're unsure whether to move on, **don't.** Going deeper is always cheaper than going back. This is where the "90% of the work" lives.

---

## Changelog

- 2.0: Complete rewrite — replaced structured interview rounds with collaborative discovery process, added research protocol, restructured from 4 to new 4-file spec output (VISION, RESEARCH, BLUEPRINT, INFRASTRUCTURE)
- 1.0: Initial creation with Rounds 1-4, Correction Pass rules, Adaptive Rules, and Interview Flow Order
