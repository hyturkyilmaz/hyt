import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';

// Gerçek API ile uçtan uca senaryo: services/api, geçici bir yerel PostgreSQL kümesiyle ayağa
// kalkar (e2e/real-api/serve_api.py) ve web uygulaması ona bağlanır. Sahte API KULLANILMAZ.
// Çalıştırma: npm run e2e:gercek-api  (gereksinim: uv, /usr/lib/postgresql/16/bin, Chromium)
const WEB_PORT = 3101;
const API_PORT = 8100;

const customPath = process.env.PW_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium';
const executablePath = existsSync(customPath) ? customPath : undefined;

export default defineConfig({
  testDir: './e2e/real-api',
  outputDir: './test-results/real-api',
  // Senaryo adımları aynı veritabanını ve hesabı paylaşır: sıralı çalışır.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'retain-on-failure',
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
    viewport: { width: 1280, height: 800 },
    launchOptions: { executablePath, args: ['--no-sandbox'] },
  },
  projects: [{ name: 'gercek-api' }],
  webServer: [
    {
      // Geçici PostgreSQL + migrasyonlar + uvicorn. Süreç sonlanınca küme ve tmp dizin silinir.
      command: 'uv run python ../../apps/web/e2e/real-api/serve_api.py',
      cwd: '../../services/api',
      url: `http://127.0.0.1:${API_PORT}/v1/health/ready`,
      reuseExistingServer: false,
      timeout: 120_000,
      // SIGKILL yerine SIGTERM: başlatıcı PostgreSQL kümesini kapatıp tmp dizinini silebilsin.
      gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 },
      env: { E2E_API_PORT: String(API_PORT) },
    },
    {
      command: `npm run build && npm run start -- -p ${WEB_PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 240_000,
      env: {
        API_BASE_URL: `http://127.0.0.1:${API_PORT}`,
        NEXT_PUBLIC_SITE_URL: `http://127.0.0.1:${WEB_PORT}`,
        // Cloudflare arkasındaki üretim topolojisinin benzeri: istemci kimliği yalnız
        // CF-Connecting-IP'den alınır, istemcinin yazdığı X-Forwarded-For atılır (ADR-0002).
        CLIENT_IP_SOURCE: 'cf-connecting-ip',
      },
    },
  ],
});
