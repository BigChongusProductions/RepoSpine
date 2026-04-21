# verify-visual — Known Gotchas and False Positives

Confirmed failure modes from past sessions. Read before running the suite.

---

## Gotcha 1 — Viewport/Transform State Carries Between Tests

**What happens:** If a previous test or step left a transformed state (zoom, scroll, CSS transform), subsequent measurements or screenshots run in that transformed space. Distances may be systematically off, or an element may be partially out of view.

**Symptom:** Element-level screenshot has unexpected cropping; position assertions fail by a constant offset.

**Fix:** Reset state explicitly at the start of each test — fresh navigation, reset zoom, scroll to top:
```ts
await page.goto(route.url);
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForSelector(route.wait_for, { timeout: 5000 });
```
For apps with app-specific zoom/transform state, expose a reset hook in dev mode (e.g. `window.__resetView()`) that tests can call.

---

## Gotcha 2 — Animation Timing

**What happens:** Screenshotting or asserting immediately after navigation/interaction captures an intermediate animation frame. Counts are wrong, positions are interpolated, text appears blurry.

**Timing budget:**
- Page first load: wait for `wait_for` selector (most reliable)
- Post-interaction transitions: 300–800ms depending on stack
- Complex staggered animations: 1.5–2.5s
- WebGL / canvas re-render: 1.5s+ after camera changes

**Symptom:** Pixel-diff flakes intermittently; some runs pass, others fail with small diffs.

**Fix:** Always prefer `waitForSelector` with a stable post-animation marker (e.g. `[data-animation="done"]`) over fixed delays. If you must use delays, err upward — false failures cost more time than waits.

---

## Gotcha 3 — Vision AI Confirmation Bias

**What happens:** Vision models (Gemini, GPT-4V, Claude Vision) tend toward confirmation bias — they find what the prompt primes them to find. In past sessions, vision declared screens clean while real rendering artifacts were present (seams, bleed, z-order issues).

**Specific blind spots observed:**
- Subpixel seams between adjacent polygonal regions
- Fills bleeding slightly outside boundaries
- Z-order inversions (interactive elements rendered behind decorative ones)
- Water/land boundary gaps

**Fix:** Always pair vision with pixel-diff (free, deterministic). Use targeted vision prompts that list specific failure modes rather than open "does this look good" prompts. Example:

```
"Examine this screenshot. Check for each of the following and report any that are present:
1. GAPS: White lines or seams between adjacent colored regions?
2. BOUNDARIES: Fills bleeding outside region boundaries?
3. Z-ORDER: Elements incorrectly layered?
Report each found issue with approximate screen location."
```

Budget: default 3–5 vision requests per session. Do not skip pixel-diff.

---

## Gotcha 4 — Element Count vs Visible Count

**What happens:** Clustering, virtualization, or conditional rendering makes DOM element counts diverge from what's visually on screen. Tests that count DOM nodes may undercount or overcount.

**Symptom:** Test expects N items, sees M ≠ N, fails — but the app is actually rendering correctly (e.g. 3 items collapsed into a "3 more" cluster).

**Fix:** Test visible behavior, not DOM topology. Use visibility + bounding-box checks:
```ts
const pills = page.locator('[data-testid=pill]:visible');
expect(await pills.count()).toBeGreaterThanOrEqual(minVisible);
```
For virtualized lists, test that scrolling reveals expected items, not that all exist simultaneously.

---

## Gotcha 5 — Reduced Motion Changes Code Path

**What happens:** Setting `prefers-reduced-motion: reduce` in the test environment suppresses animations. This changes what's visible in screenshots and can cause timing checks to fail (an element appears "open" before the animation would have finished).

**Why this matters:** If your app has a `useReducedMotion` hook or `@media (prefers-reduced-motion)` CSS, reduced-motion mode tests a different code path than most users see.

**Fix:** Do NOT set `prefers-reduced-motion` by default. Test the default animated state. If you need to test reduced-motion behavior specifically, run it as a separate named check and clearly label it in the report.

---

## Gotcha 6 — SSR / Data-Load Timing

**What happens:** Apps with SSR or async data loading may briefly render a loading/skeleton state before becoming interactive. Assertions during that window produce false failures.

**Symptom:** Element count returns 0. Buttons are unresponsive. Screenshots show a skeleton.

**Fix:** Every route in your contract should specify a `wait_for` selector that only appears once the page is ready — e.g. `[data-loaded="true"]` on the main content, or a specific stable element. The skill fails fast if the `wait_for` selector doesn't resolve within the timeout, surfacing "page failed to load" rather than cascading downstream failures.

---

## Gotcha 7 — Tablet Viewport Often Missing from Matrix

**What happens:** Many projects test only desktop + mobile. Tablet (768×1024) is where layout breakpoint bugs cluster most often — elements designed for either end of the range collide here.

**Symptom:** Suite passes 100% but the app looks broken on iPad or small tablets.

**Fix:** Add a `tablet` viewport to your contract if your project ships in that form factor. Allocate at least a routes-level smoke screenshot for tablet; components add cost so be selective.

---

## Gotcha 8 — Headless WebGL Blank Canvas

**What happens:** In headless Chromium, WebGL (MapLibre, three.js, Mapbox) may render as a blank canvas — tiles/overlays/3D scene are invisible. Only HTML/SVG UI chrome renders.

**Symptom:** Screenshots show all UI controls but the canvas area is solid gray or black. Vision reports "canvas content missing" on every screenshot.

**Detection:**
```js
const canvas = document.querySelector('canvas');
if (canvas) {
  const ctx = canvas.getContext('webgl2') || canvas.getContext('webgl');
  const pixels = new Uint8Array(4);
  ctx.readPixels(canvas.width/2, canvas.height/2, 1, 1, ctx.RGBA, ctx.UNSIGNED_BYTE, pixels);
  return { hasContent: pixels[0] + pixels[1] + pixels[2] > 10 };
}
```

**Degraded mode when headless is detected:**
- Routes screenshots still work (UI chrome captured)
- Canvas-content screenshots are SKIPPED with a warning
- Interactions that don't depend on canvas content still work
- Report MUST note: "⚠️ Headless mode — canvas content not verified. UI chrome inspection only."

Alternative: run the suite with `--headed` or use `playwright test --project=chromium-headed`.
