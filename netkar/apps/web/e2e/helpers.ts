import type { Page, TestInfo } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

// Ekran görüntüleri test-results altına değil, repodaki docs/ux/ekranlar klasörüne yazılır.
const SCREENSHOT_DIR = join(__dirname, '..', '..', '..', 'docs', 'ux', 'ekranlar');

export function screenshotPath(name: string, testInfo: TestInfo, scheme: 'acik' | 'koyu' = 'acik') {
  mkdirSync(SCREENSHOT_DIR, { recursive: true });
  const device = testInfo.project.name === 'mobil' ? 'mobil-390' : 'masaustu-1280';
  return join(SCREENSHOT_DIR, `${name}-${device}${scheme === 'koyu' ? '-koyu' : ''}.png`);
}

export async function waitForReady(page: Page) {
  await page.waitForLoadState('load');
  // Yazı tipi yüklenmeden görüntü alma
  await page.evaluate(() => document.fonts.ready);
}
