---
name: design-review
description: Evaluate visual design quality across 7 categories with severity-rated findings
---

# Design Review

Evaluate web application visual design quality — aesthetics, not UX.

## When to Use
- After major visual changes
- Before phase gate merges (e.g. P5-DEPLOY, P5-SHIP)
- As complement to `/verify-visual` (which checks function; this checks beauty)
- When user says: "design review", "does this look good", "check the layout", "is this polished"

## Evaluation Categories

1. **Layout & Spacing** — consistency, alignment, whitespace balance, grid discipline
2. **Typography** — hierarchy, line length (45-75 chars), font scale, weight usage
3. **Color & Contrast** — semantic token usage, WCAG compliance, dark mode, theme consistency
4. **Visual Hierarchy** — primary action prominence, progressive disclosure, grouping
5. **Component Consistency** — buttons, cards, inputs, icons, shadows, border radii
6. **Interaction Design** — hover/focus states, transitions, loading indicators, feedback
7. **Responsive Quality** — mobile nav, image scaling, touch targets, tablet layout

## Severity Levels

- **High** — Broken appearance, misaligned layout, inaccessible contrast, missing states
- **Medium** — Unpolished spacing, inconsistent components, weak hierarchy
- **Low** — Nitpicks, minor alignment, could-be-better transitions

## Process

1. Take screenshots of the target page/component at multiple viewports (desktop 1440px, tablet 768px, mobile 375px)
2. Evaluate against all 7 categories
3. Generate markdown report with:
   - Overall impression (one paragraph)
   - Categorized findings with screenshots and severity
   - Positive patterns worth preserving
   - Top 3 recommended fixes (highest impact)
4. Save report to `refs/design-review.md` (or wherever your project keeps artifacts)

## Guiding Principle
> "Would a design-conscious person think 'this is well made' or 'this looks like a developer designed it?'"

## Project-Specific Context

> **Customize this section for your project.** Populate with aesthetic direction, fonts, color palette, motion conventions, and rendering stack. Example:
>
> - Aesthetic: <one-sentence visual direction>
> - Fonts: <display / body / monospace choices>
> - Colors: <token system or palette reference>
> - Motion: <library + reduced-motion policy>
> - Rendering: <SVG / Canvas / HTML-CSS tradeoffs>
