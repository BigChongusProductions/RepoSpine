---
name: verify-visual
description: >
  Automated visual verification suite driven by a project-owned
  visual-contract.json. Runs Playwright e2e (routes, components, interactions,
  a11y, visual regression, performance) across configured viewports, and
  optionally runs AI vision analysis on captured screenshots.

  Use when: completing a visual task, before marking a visual component DONE,
  after a rendering change, before a phase gate with visual components, or
  when the user says "visual check", "screenshot", "verify UI", "does this
  look right".
---

# verify-visual — Skill Runbook

**Cost envelope:** Pixel-diff only is free ($0, runs locally via Playwright + Chromium; ~30–90s per run). Adding Gemini vision analysis bills per image: ~$0.15 for 30 images, ~$1.00 for 200, ~$4.50 for 900. Default contract sets `vision_check.provider: none` — opt-in, not opt-out. `vision_check.budget_per_run` caps analyzed images; if the matrix exceeds budget the skill samples N random cells.

## Pixel-diff threshold guidance

- DOM-only apps: `pixel_diff_threshold: 0.01` (1%) is usually safe.
- Canvas / SVG-heavy apps: start at 0.02 (2%).
- WebGL apps (MapLibre, three.js, etc.): 0.02–0.05 — GPU drivers and ANGLE backends introduce per-pixel variance that a stricter threshold treats as regression.

## Contract-driven — zero hardcoded selectors

All routes, components, interactions, viewports, and thresholds come from
`.claude/skills/verify-visual/visual-contract.json`. The shipped example
(`visual-contract.example.json`) is a copy target — fill in selectors for your
project, save as `visual-contract.json`, and run.

## Quick Run

```bash
# 1. Copy the example contract and fill in your selectors
cp .claude/skills/verify-visual/visual-contract.example.json \
   .claude/skills/verify-visual/visual-contract.json
$EDITOR .claude/skills/verify-visual/visual-contract.json

# 2. Preflight check
bash .claude/skills/verify-visual/scripts/validate-contract.sh

# 3. Run the suite (dev server must be running separately)
bash .claude/skills/verify-visual/scripts/run-suite.sh

# 4. Update baselines after intentional visual changes
bash .claude/skills/verify-visual/scripts/run-suite.sh --update
```

### What the suite covers

| Spec | What it tests |
|------|---------------|
| `routes.spec.ts` | Each route navigates, waits for `wait_for` selector, takes full-viewport screenshot at each configured viewport |
| `components.spec.ts` | Each component is screenshotted in isolation (element-level) at each configured viewport |
| `interactions.spec.ts` | For each interaction, runs the step sequence and asserts the final `expect` selector resolves |
| `a11y.spec.ts` | axe-core scan on every route at desktop viewport — critical/serious violations fail the run |
| `visual-regression.spec.ts` | `toMatchSnapshot()` for each screenshot; threshold from the contract |
| `performance.spec.ts` | Web Vitals budgets (LCP, CLS) — thresholds from contract |

## Mid-Implementation Quick Check

Between visual change units during multi-unit visual implementation, use a lighter check:

1. Ensure dev server running
2. Navigate via Playwright MCP to the most-affected route
3. Single screenshot at the relevant viewport
4. If Gemini vision configured: 1 focused request (NOT the full matrix)
5. If issue found → fix before next unit

Budget: 1–2 vision requests per mid-check vs 30–900 for full verification.

## Pass/fail semantics

Two independent axes:

### Axis 1 — Pixel diff (cheap, deterministic, no API cost)

- Threshold: `pixel_diff_threshold` from the contract (default 0.02)
- Pass: diff ≤ threshold. Fail: diff > threshold
- Uses Playwright's built-in `toMatchSnapshot({ threshold })`
- SKIPPED (no baseline found) on first run → warn, write baseline, pass

### Axis 2 — Vision check (expensive, subjective, optional)

Runs only when `vision_check.provider ∈ {gemini, manual}`:

| Mode | When | Pass/fail rule |
|---|---|---|
| `none` | Default | Skipped entirely |
| `gemini` | Project configured Gemini MCP + key | Vision model scores each prompt PASS/FAIL |
| `manual` | Interactive | Operator yes/no determines outcome |

Failure policy:
- Pixel-diff fail → hard fail, exit 1
- Vision fail → hard fail ONLY if `vision_check.blocking: true` (default false — advisory)
- Gemini unreachable but contract requires vision → hard fail with actionable message
- Gemini quota exceeded mid-run → skip remaining vision checks, continue pixel-diff, warn in report

## What counts as "done"

A visual task is verified when:
1. All route screenshots match (or are updated against) baselines
2. All component screenshots match (or are updated against) baselines
3. All interaction sequences complete with `expect` selectors resolving
4. a11y scans emit no critical/serious violations
5. (optional) Vision check passes if configured as blocking

## Step 3 — Report

The run script writes a structured report to `reports/YYYY-MM-DD-HHmm/report.md`:

```
## verify-visual Report — {date} {time}
### Contract: {name}
### Viewports: {list}
### Routes tested: N | Components tested: M | Interactions: K
### Pixel-diff: pass=X fail=Y skip=Z
### a11y: violations critical=A serious=B
### Vision: provider={gemini|manual|none} pass=P fail=Q
### Failures (with screenshots)
- ...
### Recommendation: READY TO MARK DONE / NEEDS FIXES
```

## Self-Correction Loop

If a spec fails and the failure is in your code:
1. Fix the issue (max 3 attempts)
2. Re-run only the failing spec: `npx playwright test specs/<name>.spec.ts`
3. If still failing after 3 attempts, surface to the user with full diagnosis
4. Do NOT mark the task DONE until all specs pass

## Gotchas

See `gotchas.md`. Quick reference:
- WebGL/canvas apps blank in headless — detect and degrade gracefully
- Animations must complete before screenshot — use `wait_for` or explicit delays
- Baselines are platform-specific (`*-darwin.png`, `*-linux.png`)
- Vision AI has confirmation bias — always supplement with pixel-diff
- Reduced-motion mode tests a different code path than most users see

---

## Customizing for your project

1. **Write a contract** — `.claude/skills/verify-visual/visual-contract.json`. See `visual-contract.example.json` for the shape.
2. **Decide your viewports** — minimum desktop; add mobile/tablet as your project needs them.
3. **Tune the pixel threshold** — DOM-only starts at 0.01; add headroom for canvas/WebGL.
4. **Decide vision check posture** — `none` (default, free) / `manual` (interactive) / `gemini` (billed).
5. **Update the performance budgets** — defaults are conservative for modern SPA; tune for your tech stack.
