import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { loadContract, viewportSize, routeUrl } from './_contract';

const contract = loadContract();
const desktop = Object.keys(contract.viewports ?? {})[0];

for (const route of contract.routes ?? []) {
  test(`a11y:${route.id}`, async ({ page }) => {
    if (desktop) {
      await page.setViewportSize(viewportSize(contract, desktop));
    }
    await page.goto(routeUrl(contract, route.url));
    await page.waitForSelector(route.wait_for, { timeout: 10_000 });
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    const blocking = results.violations.filter(
      v => v.impact === 'critical' || v.impact === 'serious'
    );
    expect(
      blocking,
      `axe found ${blocking.length} critical/serious violations on ${route.id}: ${blocking
        .map(v => v.id)
        .join(', ')}`
    ).toHaveLength(0);
  });
}
