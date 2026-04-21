// visual-regression.spec.ts
//
// Baseline matching is already exercised by routes.spec.ts and components.spec.ts
// via toHaveScreenshot(). This file is a placeholder for project-specific cross-cut
// visual-regression scenarios (full-page diffs against a golden set, themed
// variants, print stylesheet checks, etc.).
//
// Add project-specific scenarios here if routes+components are not enough. Keep
// the shipped scenarios empty by default so a fresh bootstrap runs green.

import { test } from '@playwright/test';
import { loadContract } from './_contract';

const contract = loadContract();

test.describe('visual-regression (project extensions)', () => {
  test.skip(true, 'no project-specific regression scenarios declared');
  test('placeholder — extend here', async () => {
    // Write project-specific regression scenarios here.
    void contract;
  });
});
