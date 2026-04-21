---
name: web-design-guidelines
author: Vercel
version: 1.0.0
description: Review UI code for Web Interface Guidelines compliance
---

# Web Design Guidelines

Review UI code against Vercel's Web Interface Guidelines for design and accessibility compliance.

## When to Use
- Before deploy
- After any accessibility task
- After i18n implementation
- When user says: "review my UI", "check accessibility", "audit design", "review UX"

## Workflow

1. **Fetch current guidelines** from:
   `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md`
   Use WebFetch to retrieve the latest ruleset before every review.

2. **Read target files** — user provides file paths or glob patterns (e.g., `src/components/**/*.tsx`)

3. **Validate** every file against the fetched rules

4. **Report findings** in terse `file:line` format:
   ```
   src/components/Button.tsx:42 — missing aria-label on interactive SVG element
   src/components/Selector.tsx:18 — focus ring not visible on keyboard navigation
   ```

5. If no files specified, prompt user: "Which files or patterns should I review?"

## Key Rule Categories (from Web Interface Guidelines)
- Proper ARIA attributes on all interactive elements
- Visible focus states (not just outline: none)
- All inputs have visible labels (not just placeholder)
- Touch targets >= 44x44px
- prefers-reduced-motion respected
- Semantic HTML (landmarks, headings hierarchy)
- Keyboard navigation for all interactive flows
- Color contrast meets WCAG AA
- i18n-ready (Intl APIs for dates/numbers, lang attribute, no text in images)
- URL state reflects app state (deep linking)
- Safe areas respected on mobile
- Dark/light mode transitions handled
