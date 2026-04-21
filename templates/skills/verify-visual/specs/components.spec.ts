import { test, expect } from '@playwright/test';
import {
  loadContract,
  viewportSize,
  routeUrl,
  routeById,
  componentViewports,
} from './_contract';

const contract = loadContract();

for (const comp of contract.components ?? []) {
  const route = routeById(contract, comp.route ?? contract.routes?.[0]?.id);
  if (!route) continue;
  for (const vp of componentViewports(contract, comp)) {
    test(`component:${comp.id} @ ${vp}`, async ({ page }) => {
      const size = viewportSize(contract, vp);
      await page.setViewportSize(size);
      await page.goto(routeUrl(contract, route.url));
      await page.waitForSelector(route.wait_for, { timeout: 10_000 });
      if (comp.trigger) {
        await page.click(comp.trigger);
      }
      const locator = page.locator(comp.selector);
      await locator.waitFor({ state: 'visible', timeout: 5_000 });
      await expect(locator).toHaveScreenshot(`${comp.id}-${vp}.png`, {
        threshold: contract.pixel_diff_threshold ?? 0.02,
      });
    });
  }
}
