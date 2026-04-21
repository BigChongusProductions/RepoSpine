import { test, expect } from '@playwright/test';
import {
  loadContract,
  viewportSize,
  routeUrl,
  routeById,
} from './_contract';

const contract = loadContract();

for (const inter of contract.interactions ?? []) {
  const route = routeById(contract, inter.route ?? contract.routes?.[0]?.id);
  if (!route) continue;
  const vp = inter.viewport ?? Object.keys(contract.viewports ?? {})[0];
  if (!vp) continue;

  test(`interaction:${inter.id}`, async ({ page }) => {
    await page.setViewportSize(viewportSize(contract, vp));
    await page.goto(routeUrl(contract, route.url));
    await page.waitForSelector(route.wait_for, { timeout: 10_000 });

    for (const step of inter.steps) {
      if (step.focus)  await page.focus(step.focus);
      if (step.click)  await page.click(step.click);
      if (step.type !== undefined && step.type !== null) {
        await page.keyboard.type(step.type);
      }
      if (step.key)    await page.keyboard.press(step.key);
      if (step.wait)   await page.waitForTimeout(step.wait);
      if (step.expect) {
        await expect(page.locator(step.expect)).toBeVisible({ timeout: 5_000 });
      }
    }
  });
}
