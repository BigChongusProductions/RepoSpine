# Spec Quality Rules & Validation

Shared quality rules that apply to all four spec files (VISION, RESEARCH, BLUEPRINT, INFRASTRUCTURE).

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
