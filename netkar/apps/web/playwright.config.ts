import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';

const PORT = 3100;
// Sahte API: panel layout'unun sunucu tarafı GET /v1/me çağrısı için (bkz. e2e/fake-api.mjs).
const FAKE_API_PORT = 9101;

// Bu makinede Chromium /opt/pw-browsers/chromium altındadır (playwright install çalıştırılmaz).
// Başka ortamda PW_CHROMIUM_PATH ile ezilir; yoksa Playwright kendi tarayıcısını kullanır.
const customPath = process.env.PW_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium';
const executablePath = existsSync(customPath) ? customPath : undefined;

export default defineConfig({
  testDir: './e2e',
  // Gerçek API ile çalışan senaryo ayrı yapılandırmayla koşar: playwright.real-api.config.ts
  testIgnore: '**/real-api/**',
  // test-results klasörü git dışıdır; ekran görüntüleri docs/ux/ekranlar altına testin içinden yazılır.
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
    launchOptions: {
      executablePath,
      args: ['--no-sandbox'],
    },
  },
  projects: [
    {
      name: 'mobil',
      use: {
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: 'masaustu',
      use: { viewport: { width: 1280, height: 800 } },
    },
  ],
  webServer: [
    {
      command: 'node e2e/fake-api.mjs',
      url: `http://127.0.0.1:${FAKE_API_PORT}/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: { FAKE_API_PORT: String(FAKE_API_PORT) },
    },
    {
      // Üretim derlemesi üzerinde çalışır: CSP nonce ve başlıklar gerçekte olduğu gibi sınanır.
      // API_BASE_URL derleme sırasında rewrites içine gömülür; bu yüzden build komutu da env alır.
      command: `npm run build && npm run start -- -p ${PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: {
        API_BASE_URL: `http://127.0.0.1:${FAKE_API_PORT}`,
        NEXT_PUBLIC_SITE_URL: `http://127.0.0.1:${PORT}`,
      },
    },
  ],
});
