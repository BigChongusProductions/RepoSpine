import { test, expect } from '@playwright/test';
import { loadContract, viewportSize, routeUrl } from './_contract';

const contract = loadContract();
const budgets = contract.performance_budgets ?? {};
const lcpMs = budgets.lcp_ms ?? 4000;
const cls = budgets.cls ?? 0.1;
const desktop = Object.keys(contract.viewports ?? {})[0];

for (const route of contract.routes ?? []) {
  test(`perf:${route.id}`, async ({ page }) => {
    if (desktop) {
      await page.setViewportSize(viewportSize(contract, desktop));
    }
    await page.goto(routeUrl(contract, route.url));
    await page.waitForSelector(route.wait_for, { timeout: 10_000 });

    const metrics = await page.evaluate(() => {
      return new Promise<{ lcp: number; cls: number }>((resolve) => {
        let lcp = 0;
        let cumulativeLayoutShift = 0;

        try {
          const lcpObserver = new PerformanceObserver((list) => {
            const entries = list.getEntries();
            const last = entries[entries.length - 1] as PerformanceEntry & { startTime: number };
            if (last) lcp = last.startTime;
          });
          lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true });
        } catch { /* unsupported */ }

        try {
          const clsObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries() as Array<PerformanceEntry & { value: number; hadRecentInput: boolean }>) {
              if (!entry.hadRecentInput) cumulativeLayoutShift += entry.value;
            }
          });
          clsObserver.observe({ type: 'layout-shift', buffered: true });
        } catch { /* unsupported */ }

        setTimeout(() => resolve({ lcp, cls: cumulativeLayoutShift }), 2000);
      });
    });

    expect(metrics.lcp, `LCP ${metrics.lcp}ms exceeds budget ${lcpMs}ms`).toBeLessThanOrEqual(lcpMs);
    expect(metrics.cls, `CLS ${metrics.cls} exceeds budget ${cls}`).toBeLessThanOrEqual(cls);
  });
}
