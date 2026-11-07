import type { BrowserContext, Page, TestInfo } from '@playwright/test';
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

export const SESSION_COOKIE = '__Host-nk_session';
export const CSRF_COOKIE = '__Host-nk_csrf';

/**
 * Sahte API (e2e/fake-api.mjs) için oturum çerezi koyar. `__Host-` öneki Secure + Path=/ ve
 * Domain yok ister; Chromium 127.0.0.1 üzerinde Secure çerezi http'de de kabul eder.
 * Değer "gecersiz" ise sahte API /v1/me için 401 döner.
 */
export async function signIn(context: BrowserContext, value = 'e2e-oturum') {
  await context.addCookies([
    { name: SESSION_COOKIE, value, url: 'https://127.0.0.1:3100', secure: true },
  ]);
}
