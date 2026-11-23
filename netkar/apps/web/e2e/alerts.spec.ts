import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import {
  DEDUCTION_EVENT,
  EVENT_ID_1,
  RETURN_EVENT,
  makeAlertSettings,
  makeEvent,
  makeEventList,
  makePreferences,
} from '../src/lib/alerts/test-fixtures';
import { ACCOUNT_ID, makeAccounts } from '../src/lib/profit/test-fixtures';
import { signIn, waitForReady } from './helpers';

// Uyarılar (/panel/uyarilar), Ayarlar > Bildirimler (/panel/ayarlar/bildirimler) ve bildirim kapatma
// (/bildirim-kapat): tarayıcının /api/v1 istekleri Playwright route ile taklit edilir (sahte API yalnız oturum için
// /v1/me yanıtlar). ADR-0009 test listesi madde 29: axe 390 ve 1280 px, açık ve koyu tema 0 ihlal.
// Ekran görüntüleri PW_SHOTS_DIR verilirse oraya yazılır.
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const BASE = `/api/v1/marketplace-accounts/${ACCOUNT_ID}`;
const TOKEN = 'eyJ2IjoxfQ.' + 'S'.repeat(43);

interface Seen {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: Record<string, string>;
  body: unknown;
}

type Reply = { status?: number; body: unknown; headers?: Record<string, string> };

interface Options {
  role?: string;
  verified?: boolean;
  /** durum -> yanıt */
  events?: (status: string, seen: Seen) => Reply;
  transition?: (seen: Seen) => Reply;
  settingsPut?: (seen: Seen) => Reply;
}

const seen: Seen[] = [];

function problem(status: number, slug: string, headers?: Record<string, string>): Reply {
  return { status, headers, body: { type: `urn:netkar:problem:${slug}`, title: slug, status } };
}

async function mockApi(page: Page, options: Options = {}) {
  seen.length = 0;
  await page.route('**/api/v1/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const raw = request.postData();
    const record: Seen = {
      method: request.method(),
      path: url.pathname,
      query: url.searchParams,
      headers: request.headers(),
      body: raw ? (JSON.parse(raw) as unknown) : undefined,
    };
    seen.push(record);
    const reply = (r: Reply) => {
      const status = r.status ?? 200;
      return route.fulfill({
        status,
        contentType: status >= 400 ? 'application/problem+json' : 'application/json',
        headers: r.headers,
        body: JSON.stringify(r.body),
      });
    };
    const { path, method } = record;
    if (path === '/api/v1/auth/csrf') return reply({ body: { csrf_token: 'e2e-csrf' } });
    if (path === '/api/v1/me') {
      return reply({
        body: {
          role: options.role ?? 'owner',
          email: 'ad@ornek.com',
          email_verified: options.verified ?? true,
        },
      });
    }
    if (path === '/api/v1/marketplace-accounts') return reply({ body: makeAccounts() });
    if (path === `${BASE}/alert-events` && method === 'GET') {
      const status = url.searchParams.get('status') ?? '';
      return reply(
        options.events?.(status, record) ?? {
          body:
            status === 'open'
              ? makeEventList([makeEvent(), DEDUCTION_EVENT, RETURN_EVENT], { open_count: 3 })
              : makeEventList(
                  [
                    makeEvent({
                      status: status as 'read',
                      muted_until: status === 'muted' ? '2026-11-20T10:00:00+03:00' : null,
                      resolved_at: status === 'resolved' ? '2026-11-12T20:00:00+03:00' : null,
                    }),
                  ],
                  { open_count: 3 },
                ),
        },
      );
    }
    if (path.endsWith('/transitions') && method === 'POST') {
      return reply(
        options.transition?.(record) ?? {
          body: { event: makeEvent({ status: 'read' }), transition_id: 't1' },
        },
      );
    }
    if (path === `${BASE}/alert-events/read-all`) {
      return reply({ body: { updated: 3, remaining_open: 0 } });
    }
    if (path === `${BASE}/alert-settings` && method === 'GET') {
      return reply({ body: makeAlertSettings(), headers: { ETag: '"e-1"' } });
    }
    if (path === `${BASE}/alert-settings` && method === 'PUT') {
      return reply(
        options.settingsPut?.(record) ?? {
          body: makeAlertSettings({ loss_min_amount: '12.50' }),
          headers: { ETag: '"e-2"' },
        },
      );
    }
    if (path === '/api/v1/me/notification-preferences') {
      return reply({ body: method === 'PUT' ? record.body : makePreferences() });
    }
    if (path === '/api/v1/notifications/unsubscribe') {
      return reply({ body: { rules: ['ZARARINA_SATIS'], channel: 'email', mode: 'off' } });
    }
    return reply(problem(404, 'not-found'));
  });
}

function shotPath(name: string, project: string, scheme: string): string | undefined {
  const dir = process.env.PW_SHOTS_DIR;
  if (!dir) return undefined;
  mkdirSync(dir, { recursive: true });
  const device = project === 'mobil' ? 'mobil-390' : 'masaustu-1280';
  return join(dir, `${name}-${device}${scheme === 'dark' ? '-koyu' : ''}.png`);
}

async function checkPage(page: Page, name: string, project: string, scheme: string) {
  await waitForReady(page);
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} düğüm)`)).toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const path = shotPath(name, project, scheme);
  if (path) await page.screenshot({ path, fullPage: true });
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`uyarılar ve bildirimler, ${scheme === 'light' ? 'açık' : 'koyu'} tema`, () => {
    test.use({ colorScheme: scheme, deviceScaleFactor: 2 });

    test.describe('oturumlu sayfalar', () => {
      test.beforeEach(async ({ context }) => {
        await signIn(context);
      });

      test('açık sekme: kartlar, eylemler ve sekme bağlantıları; axe temiz', async ({
        page,
      }, testInfo) => {
        await mockApi(page);
        await page.goto('/panel/uyarilar');
        await expect(page.getByRole('heading', { level: 1, name: 'Uyarılar' })).toBeVisible();
        const card = page.getByRole('region', { name: /Zararına satış/ });
        await expect(card).toContainText('3 satırda zarar var.');
        await expect(card).toContainText('₺412,30');
        await expect(card).toContainText('10 Kasım 2026, 09:05');
        await expect(page.getByRole('link', { name: 'Açık (3)' })).toHaveAttribute(
          'aria-current',
          'true',
        );
        await expect(page.getByRole('button', { name: 'Tümünü okundu yap' })).toBeVisible();
        await checkPage(page, 'panel-uyarilar-acik', testInfo.project.name, scheme);
      });

      test('susturma formu açıkken ve hata durumunda axe temiz', async ({ page }, testInfo) => {
        await mockApi(page);
        await page.goto('/panel/uyarilar');
        await page.getByRole('button', { name: 'Sustur' }).first().click();
        const input = page.getByLabel('Susturma süresi (gün)');
        await input.fill('120');
        await page.getByRole('button', { name: 'Uyarıyı sustur' }).click();
        await expect(page.locator('main').getByRole('alert')).toContainText('1 ile 90 arasında');
        await checkPage(page, 'panel-uyarilar-sustur', testInfo.project.name, scheme);
      });

      test('okundu işaretle: POST gövdesi ve bildirim; kart listeden çıkar', async ({ page }) => {
        await mockApi(page);
        await page.goto('/panel/uyarilar');
        await page.getByRole('button', { name: 'Okundu işaretle' }).first().click();
        await expect(page.getByText('Uyarı okundu olarak işaretlendi.')).toBeVisible();
        const post = seen.find((s) => s.path === `${BASE}/alert-events/${EVENT_ID_1}/transitions`);
        expect(post?.body).toEqual({ to: 'read' });
        await expect(page.getByRole('region', { name: /Zararına satış/ })).toHaveCount(0);
      });

      test('409: Türkçe ileti ve liste yeniden yüklenir', async ({ page }) => {
        await mockApi(page, { transition: () => problem(409, 'alert-event-changed') });
        await page.goto('/panel/uyarilar');
        await page.getByRole('button', { name: 'Okundu işaretle' }).first().click();
        await expect(page.locator('main').getByRole('alert')).toContainText(
          'başka bir yerde değişmiş olabilir',
        );
        await expect
          .poll(
            () =>
              seen.filter((s) => s.path === `${BASE}/alert-events` && s.method === 'GET').length,
          )
          .toBeGreaterThanOrEqual(2);
      });

      test('429: bekleme süresi gösterilir', async ({ page }) => {
        await mockApi(page, {
          transition: () => problem(429, 'rate-limited', { 'Retry-After': '120' }),
        });
        await page.goto('/panel/uyarilar');
        await page.getByRole('button', { name: 'Okundu işaretle' }).first().click();
        await expect(page.locator('main').getByRole('alert')).toContainText(
          'Yaklaşık 2 dakika sonra tekrar deneyin.',
        );
      });

      test('viewer: susturma yerine not; susturulmuş sekmede yeniden açma yok; axe temiz', async ({
        page,
      }, testInfo) => {
        await mockApi(page, { role: 'viewer' });
        await page.goto('/panel/uyarilar?sekme=susturulmus');
        await expect(
          page.getByRole('heading', { level: 2, name: 'Susturulmuş uyarılar' }),
        ).toBeVisible();
        await expect(page.getByText('Hesap yöneticiniz yeniden açabilir.')).toBeVisible();
        await expect(page.getByRole('button', { name: 'Yeniden aç' })).toHaveCount(0);
        await checkPage(page, 'panel-uyarilar-viewer', testInfo.project.name, scheme);
      });

      test('doğrulanmamış e-posta: düğmeler aria-disabled; axe temiz', async ({
        page,
      }, testInfo) => {
        await mockApi(page, { verified: false });
        await page.goto('/panel/uyarilar');
        const read = page.getByRole('button', { name: 'Okundu işaretle' }).first();
        await expect(read).toHaveAttribute('aria-disabled', 'true');
        // aria-disabled düğme Playwright'ta "etkin değil" sayılır; kullanıcı gibi tıklamak için zorlanır
        await read.click({ force: true });
        expect(seen.some((s) => s.method === 'POST')).toBe(false);
        await checkPage(page, 'panel-uyarilar-dogrulanmamis', testInfo.project.name, scheme);
      });

      test('boş ve çözülmüş sekmeler; axe temiz', async ({ page }, testInfo) => {
        await mockApi(page, { events: () => ({ body: makeEventList([]) }) });
        await page.goto('/panel/uyarilar');
        await expect(page.getByRole('heading', { name: 'Açık uyarı yok' })).toBeVisible();
        await checkPage(page, 'panel-uyarilar-bos', testInfo.project.name, scheme);
        await page.goto('/panel/uyarilar?sekme=cozuldu');
        await expect(page.getByRole('heading', { name: 'Çözüldü uyarı yok' })).toBeVisible();
        await checkPage(page, 'panel-uyarilar-cozuldu-bos', testInfo.project.name, scheme);
      });

      test('dönem dökümü sekmesi eski içeriği korur; axe temiz', async ({ page }, testInfo) => {
        await mockApi(page);
        await page.route(`**${BASE}/profit/alerts*`, (route) =>
          route.fulfill({
            contentType: 'application/json',
            body: JSON.stringify({
              period: { start: '2026-10-12', end: '2026-11-10', days: 30 },
              counts: [],
              items: [],
              next_cursor: null,
              settings_revision: 7,
            }),
          }),
        );
        await page.goto('/panel/uyarilar?sekme=donem');
        await expect(page.getByText('Bu dönemde uyarı yok')).toBeVisible();
        await checkPage(page, 'panel-uyarilar-donem', testInfo.project.name, scheme);
      });

      test('bildirim ayarları: tercihler ve eşikler; axe temiz', async ({ page }, testInfo) => {
        await mockApi(page);
        await page.goto('/panel/ayarlar/bildirimler');
        await expect(page.getByRole('heading', { level: 1, name: 'Bildirimler' })).toBeVisible();
        await expect(page.getByRole('form', { name: 'Hesap eşikleri' })).toBeVisible();
        await expect(
          page.getByRole('combobox', { name: /Zararına satış Anlık bildirim/ }),
        ).toBeDisabled();
        await checkPage(page, 'panel-bildirimler', testInfo.project.name, scheme);
      });

      test('eşik kaydı: If-Match gönderilir; hata ve başarı iletisi; axe temiz', async ({
        page,
      }, testInfo) => {
        await mockApi(page);
        await page.goto('/panel/ayarlar/bildirimler');
        const form = page.getByRole('form', { name: 'Hesap eşikleri' });
        const share = form.getByLabel(/Reklam payı eşiği/);
        await share.fill('10');
        await form.getByRole('button', { name: 'Eşikleri kaydet' }).click();
        await expect(form).toContainText('%50 ile %100 arasında olmalı.');
        await checkPage(page, 'panel-bildirimler-hata', testInfo.project.name, scheme);
        await share.fill('100');
        await form.getByLabel(/Zarar bildirimi alt sınırı/).fill('12,5');
        await form.getByRole('button', { name: 'Eşikleri kaydet' }).click();
        await expect(page.getByText(/Eşikler kaydedildi/)).toBeVisible();
        const put = seen.find((s) => s.path === `${BASE}/alert-settings` && s.method === 'PUT');
        expect(put?.headers['if-match']).toBe('"e-1"');
      });

      test('eşik 412: başka biri değiştirdi iletisi ve yeniden yükleme', async ({ page }) => {
        await mockApi(page, { settingsPut: () => problem(412, 'alert-settings-changed') });
        await page.goto('/panel/ayarlar/bildirimler');
        const form = page.getByRole('form', { name: 'Hesap eşikleri' });
        await form.getByRole('button', { name: 'Eşikleri kaydet' }).click();
        await expect(page.locator('main').getByRole('alert')).toContainText(
          'başka biri tarafından değiştirildi',
        );
        await expect
          .poll(
            () =>
              seen.filter((s) => s.path === `${BASE}/alert-settings` && s.method === 'GET').length,
          )
          .toBeGreaterThanOrEqual(2);
      });

      test('viewer: eşikler salt okur; axe temiz', async ({ page }, testInfo) => {
        await mockApi(page, { role: 'viewer' });
        await page.goto('/panel/ayarlar/bildirimler');
        await expect(page.getByText(/yalnız görüntüleyebilirsiniz/)).toBeVisible();
        await expect(page.getByRole('form', { name: 'Hesap eşikleri' })).toHaveCount(0);
        await checkPage(page, 'panel-bildirimler-viewer', testInfo.project.name, scheme);
      });
    });

    test.describe('bildirim kapatma (oturumsuz)', () => {
      test('açılınca istek atmaz; düğmeyle POST; sonuç ekranı; axe temiz', async ({
        page,
      }, testInfo) => {
        await mockApi(page);
        const getUrls: string[] = [];
        page.on('request', (request) => {
          if (request.method() === 'GET') getUrls.push(request.url());
        });
        await page.goto(`/bildirim-kapat#token=${TOKEN}`);
        await expect(
          page.getByRole('heading', { level: 1, name: 'Bildirimi kapatın' }),
        ).toBeVisible();
        await expect(page.getByRole('button', { name: 'Bildirimi kapat' })).toBeEnabled();
        await checkPage(page, 'bildirim-kapat', testInfo.project.name, scheme);
        expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0);
        // Token adres çubuğundan silinir ve sayfada görünmez
        await expect.poll(() => page.url()).not.toContain(TOKEN);
        // URL parçası sunucuya gitmez: sayfa HTML'inde, RSC verisinde ve hiçbir GET isteğinde token yok
        expect(await page.content()).not.toContain(TOKEN);
        expect(getUrls.filter((u) => u.includes(TOKEN))).toEqual([]);
        await page.getByRole('button', { name: 'Bildirimi kapat' }).click();
        await expect(page.getByRole('heading', { name: 'Bildirim kapatıldı' })).toBeVisible();
        const posts = seen.filter((s) => s.method === 'POST');
        expect(posts).toHaveLength(1);
        expect(posts[0]?.path).toBe('/api/v1/notifications/unsubscribe');
        expect(posts[0]?.query.get('token')).toBe(TOKEN);
        expect(posts[0]?.headers['x-csrf-token']).toBeUndefined();
        await checkPage(page, 'bildirim-kapat-basarili', testInfo.project.name, scheme);
      });

      test('geçersiz bağlantı (400) ve çok fazla deneme (429)', async ({ page }, testInfo) => {
        await mockApi(page);
        await page.route('**/api/v1/notifications/unsubscribe*', (route) =>
          route.fulfill({
            status: 400,
            contentType: 'application/problem+json',
            body: JSON.stringify(problem(400, 'invalid-unsubscribe-token').body),
          }),
        );
        await page.goto(`/bildirim-kapat#token=${TOKEN}`);
        await page.getByRole('button', { name: 'Bildirimi kapat' }).click();
        await expect(page.getByRole('heading', { name: 'Bağlantı geçersiz' })).toBeVisible();
        await checkPage(page, 'bildirim-kapat-gecersiz', testInfo.project.name, scheme);

        await page.unroute('**/api/v1/notifications/unsubscribe*');
        await page.route('**/api/v1/notifications/unsubscribe*', (route) =>
          route.fulfill({
            status: 429,
            headers: { 'Retry-After': '1800' },
            contentType: 'application/problem+json',
            body: JSON.stringify(problem(429, 'rate-limited').body),
          }),
        );
        // Yalnız parçası farklı aynı adres belge yenilemez; temiz sayfadan açılır
        await page.goto('about:blank');
        await page.goto(`/bildirim-kapat#token=${TOKEN}`);
        await page.getByRole('button', { name: 'Bildirimi kapat' }).click();
        await expect(page.getByRole('heading', { name: 'Çok fazla deneme' })).toBeVisible();
        await expect(page.locator('main').getByRole('alert')).toContainText(
          'Yaklaşık 30 dakika sonra',
        );
        await checkPage(page, 'bildirim-kapat-429', testInfo.project.name, scheme);
      });

      test('token yoksa geçersiz bağlantı gösterilir', async ({ page }) => {
        await mockApi(page);
        await page.goto('/bildirim-kapat');
        await expect(page.getByRole('heading', { name: 'Bağlantı geçersiz' })).toBeVisible();
        expect(seen.filter((s) => s.method === 'POST')).toHaveLength(0);
      });
    });
  });
}

test.describe('bildirim kapatma sayfası başlıkları', () => {
  test('Referrer-Policy no-referrer, no-store ve noindex', async ({ request, page }) => {
    const response = await request.get('/bildirim-kapat');
    expect(response.status()).toBe(200);
    expect(response.headers()['referrer-policy']).toBe('no-referrer');
    expect(response.headers()['cache-control']).toContain('no-store');
    expect(response.headers()['x-robots-tag']).toBe('noindex, nofollow');
    await page.goto(`/bildirim-kapat#token=${TOKEN}`);
    await expect(page.locator('meta[name="robots"]').first()).toHaveAttribute('content', /noindex/);
    // Next akışlı metadata, etiketi zaman zaman head'e ve body'ye birer kez yazar; HER kopya no-referrer olmalı.
    const referrerMetas = page.locator('meta[name="referrer"]');
    await expect(referrerMetas.first()).toHaveAttribute('content', 'no-referrer');
    for (const meta of await referrerMetas.all()) {
      await expect(meta).toHaveAttribute('content', 'no-referrer');
    }
  });
});
