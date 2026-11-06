import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { ALL_PAGES } from './pages';
import { screenshotPath, waitForReady } from './helpers';

// WCAG 2.2 AA etiketleriyle taranır; 0 ihlal beklenir.
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`axe ve görüntü, ${scheme === 'light' ? 'açık' : 'koyu'} tema`, () => {
    test.use({ colorScheme: scheme });

    for (const entry of ALL_PAGES) {
      test(`${entry.path} render olur, axe 0 ihlal`, async ({ page }, testInfo) => {
        await page.goto(entry.path);
        await expect(page.getByRole('heading', { level: 1, name: entry.h1 })).toBeVisible();
        await waitForReady(page);

        const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
        expect(
          results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} düğüm)`),
        ).toEqual([]);

        // Yatay kaydırma olmamalı
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow).toBeLessThanOrEqual(0);

        await page.screenshot({
          path: screenshotPath(entry.name, testInfo, scheme === 'dark' ? 'koyu' : 'acik'),
          // Panelde sabit gezinme çubuğu tam sayfa görüntüde ortada kalır; panel için görünür alan alınır
          fullPage: !entry.path.startsWith('/panel'),
        });
      });
    }
  });
}
