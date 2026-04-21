import { test, expect } from '@playwright/test';
import { loadContract, routesFor, viewportSize, routeUrl } from './_contract';

const contract = loadContract();

for (const route of contract.routes ?? []) {
  for (const vp of routesFor(route)) {
    test(`route:${route.id} @ ${vp}`, async ({ page }) => {
      const size = viewportSize(contract, vp);
      await page.setViewportSize(size);
      await page.goto(routeUrl(contract, route.url));
      await page.waitForSelector(route.wait_for, { timeout: 10_000 });
      await expect(page).toHaveScreenshot(`${route.id}-${vp}.png`, {
        threshold: contract.pixel_diff_threshold ?? 0.02,
        fullPage: true,
      });
    });
  }
}
