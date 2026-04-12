---
framework: visual-verification
version: 1.0
extracted_from: production project (2026-03-17)
---

# Visual Verification Framework

## When It Applies

Tasks tagged `needs_browser=1` trigger the visual verification pipeline.

## Automated Flow (Playwright MCP)

```
1. Ensure dev server running
2. Playwright: navigate to app URL
3. Playwright: take screenshot
4. Claude Vision: analyze screenshot for issues
5. If issues AND iterations < 5 → fix → wait 2s → step 2
6. If clean or iterations >= 5 → present to Master
```

## Visual Verification Checklist

Check ALL visible elements, not just the feature being verified:
- Layout and spacing correct
- Colors and typography match design
- Interactive elements positioned correctly
- Animations and transitions working
- Responsive behavior (if applicable)
- Known dependent features noted if absent

**Anti-pattern:** Checking only what you expect to see (confirmation bias). Instead, ask "is anything wrong?" across the entire viewport.

## Presenting Results

Report:
- What was checked (which visual aspects)
- What was fixed during self-correction
- Screenshot presented inline
- Ask for confirmation at the live URL

**Approval → mark DONE. Changes requested → re-enter loop.**

## Changelog
- 1.0: Initial extraction from production project
