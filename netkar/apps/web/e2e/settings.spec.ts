import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import {
  EXPENSE_ID,
  TARIFF_ID,
  makeCarriers,
  makeEmptySettings,
  makeExpense,
  makeHistory,
  makeHistoryItem,
  makeSettings,
  makeTariff,
  makeWriteInfo,
} from '../src/lib/profit/settings-fixtures';
import {
  ACCOUNT_ID,
  makeAccounts,
  makeSummary,
  makeUnconfiguredTotals,
} from '../src/lib/profit/test-fixtures';
import { signIn, waitForReady } from './helpers';

// Kâr ayarları formu (/panel/ayarlar): tarayıcının /api/v1 istekleri Playwright route ile taklit edilir (sahte API
// yalnız oturum için /v1/me yanıtlar). Ekran görüntüleri PW_SHOTS_DIR verilirse oraya yazılır.
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const SETTINGS = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/profit-settings`;

interface Seen {
  method: string;
  path: string;
  query: URLSearchParams;
  body: Record<string, unknown> | null;
}

type Reply = { status?: number; body: unknown };
type Responder = (seen: Seen) => Reply | Promise<Reply>;

interface Handlers {
  settings?: Responder;
  carriers?: Responder;
  history?: Responder;
  /** "METHOD yol" (SETTINGS sonrası) -> yanıt */
  writes?: Record<string, Responder>;
  summary?: Responder;
  /** Yanıtları geciktirir (yükleniyor durumu) */
  delayMs?: number;
}

const seen: Seen[] = [];

async function fulfill(route: Route, reply: Reply) {
  const status = reply.status ?? 200;
  await route.fulfill({
    status,
    contentType: status >= 400 ? 'application/problem+json' : 'application/json',
    body: JSON.stringify(reply.body),
  });
}

function problem(status: number, slug: string, extra: Record<string, unknown> = {}) {
  return { status, body: { type: `urn:netkar:problem:${slug}`, title: slug, status, ...extra } };
}

async function mockApi(page: Page, handlers: Handlers = {}) {
  seen.length = 0;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;
    const raw = request.postData();
    const record: Seen = {
      method,
      path,
      query: url.searchParams,
      body: raw ? (JSON.parse(raw) as Record<string, unknown>) : null,
    };
    seen.push(record);
    if (handlers.delayMs) await new Promise((r) => setTimeout(r, handlers.delayMs));
    if (path === '/api/v1/auth/csrf') return fulfill(route, { body: { csrf_token: 'e2e-csrf' } });
    if (path === '/api/v1/me') return fulfill(route, { body: { role: 'owner' } });
    if (path === '/api/v1/marketplace-accounts') return fulfill(route, { body: makeAccounts() });
    if (path.endsWith('/profit/summary')) {
      return fulfill(
        route,
        (await handlers.summary?.(record)) ?? { body: makeSummary(makeUnconfiguredTotals()) },
      );
    }
    if (path === SETTINGS && method === 'GET') {
      return fulfill(route, (await handlers.settings?.(record)) ?? { body: makeSettings() });
    }
    if (path === `${SETTINGS}/carriers`) {
      return fulfill(route, (await handlers.carriers?.(record)) ?? { body: makeCarriers() });
    }
    if (path === `${SETTINGS}/history`) {
      return fulfill(route, (await handlers.history?.(record)) ?? { body: makeHistory() });
    }
    if (path.startsWith(SETTINGS)) {
      const responder = handlers.writes?.[`${method} ${path.slice(SETTINGS.length)}`];
      if (responder) return fulfill(route, await responder(record));
    }
    return fulfill(route, problem(404, 'not-found'));
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

async function openTariffForm(page: Page) {
  await page.getByRole('button', { name: 'Tarife ekle' }).click();
  const form = page.getByRole('form', { name: 'Yeni kargo tarifesi' });
  await expect(form).toBeVisible();
  await form.getByLabel('Kargo firması').selectOption('Yurtiçi Kargo');
  await form.getByLabel('1. kademe, en çok desi').fill('2');
  await form.getByLabel(/1\. kademe fiyatı/).fill('54');
  return form;
}

const PAST_409 = (affectsFrom: string | null, revision = 9) =>
  problem(409, 'settings-past-change-unconfirmed', {
    affects_from: affectsFrom,
    affects_past: true,
    current_revision: revision,
  });

// Her iki dönem ve iki temada görünüm, erişilebilirlik ve ekran görüntüsü
for (const scheme of ['light', 'dark'] as const) {
  test.describe(`kâr ayarları, ${scheme === 'light' ? 'açık' : 'koyu'} tema`, () => {
    test.use({ colorScheme: scheme, deviceScaleFactor: 2 });

    test.beforeEach(async ({ context }) => {
      await signIn(context);
    });

    test('dolu hesap: bölümler, KDV dahil ve hariç karşılığı, ayar geçmişi; axe temiz', async ({
      page,
    }, testInfo) => {
      await mockApi(page);
      await page.goto('/panel/ayarlar');
      await expect(page.getByRole('heading', { level: 1, name: 'Ayarlar' })).toBeVisible();
      await expect(page.getByText("2 adımdan 2'si tamam")).toBeVisible();
      const table = page.getByRole('table', { name: /Trendyol Express desi kademeleri/ });
      await expect(table).toContainText('54,00 TL KDV dahil = 45,00 TL KDV hariç');
      await expect(
        page.getByText('Bu tarihten sonraki siparişlerde kullanılır.').first(),
      ).toBeVisible();
      await expect(page.getByRole('heading', { level: 2, name: 'Varsayılan desi' })).toBeVisible();
      await expect(page.getByRole('heading', { level: 3, name: 'Paketleme' })).toBeVisible();
      const history = page.getByRole('list', { name: 'Ayar değişiklikleri' });
      await expect(history).toContainText('Yönetici');
      await expect(history).toContainText('2 desi 54,00 → 60,00 (KDV dahil)');
      await expect(history).toContainText('Geçmişi etkiledi (onaylı)');
      await expect(page.getByText('Ayar sürümü 7')).toBeVisible();
      await checkPage(page, 'panel-ayarlar-form', testInfo.project.name, scheme);
    });

    test('boş hesap: boş durumlar ve "0 adım tamam"; axe temiz', async ({ page }, testInfo) => {
      await mockApi(page, {
        settings: () => ({ body: makeEmptySettings() }),
        history: () => ({ body: makeHistory([]) }),
      });
      await page.goto('/panel/ayarlar');
      await expect(page.getByText("2 adımdan 0'ı tamam")).toBeVisible();
      await expect(page.getByText(/Henüz kargo tarifesi girmediniz/)).toBeVisible();
      await expect(page.getByText(/Henüz ayar değişikliği yok/)).toBeVisible();
      await checkPage(page, 'panel-ayarlar-bos', testInfo.project.name, scheme);
    });

    test('tarife formu: firma yalnız listeden, KDV hariç karşılığı, "0 girildi"; axe temiz', async ({
      page,
    }, testInfo) => {
      await mockApi(page, { settings: () => ({ body: makeEmptySettings() }) });
      await page.goto('/panel/ayarlar');
      const form = await openTariffForm(page);
      await expect(form.getByText('54,00 TL KDV dahil = 45,00 TL KDV hariç')).toBeVisible();
      await form.getByRole('button', { name: 'Kademe ekle' }).click();
      await form.getByLabel('2. kademe, en çok desi').fill('5');
      await form.getByLabel(/2\. kademe fiyatı/).fill('0');
      await expect(form.getByText('0 girildi')).toBeVisible();
      const options = await form.getByLabel('Kargo firması').locator('option').allTextContents();
      expect(options).toContain('Diğer firmalar (listede olmayan her firma)');
      expect(options.join('|')).not.toContain('Kendi Kuryem');
      await checkPage(page, 'panel-ayarlar-kargo-form', testInfo.project.name, scheme);
    });

    test('geçmişi etkileyen yazım: onay penceresi ADR metniyle açılır; axe temiz', async ({
      page,
    }, testInfo) => {
      await mockApi(page, { writes: { 'PUT /cargo-tariffs': () => PAST_409('2026-08-10') } });
      await page.goto('/panel/ayarlar');
      const form = await openTariffForm(page);
      await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
      const dialog = page.getByRole('dialog', { name: 'Geçmiş raporlar değişecek' });
      await expect(dialog).toBeVisible();
      await expect(dialog).toContainText(
        'Bu değişiklik 10 Ağustos 2026 ve sonrasındaki siparişlerin kâr hesabını değiştirir. Daha önce indirdiğiniz ya da paylaştığınız raporlardaki rakamlar artık farklı olabilir. Önceki değer ayar geçmişinde saklanır.',
      );
      await expect(dialog.getByRole('button', { name: 'Değişikliği uygula' })).toBeVisible();
      await expect(
        dialog.getByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
      ).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'Vazgeç' })).toBeVisible();
      const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
      expect(results.violations.map((v) => v.id)).toEqual([]);
      const path = shotPath('panel-ayarlar-onay', testInfo.project.name, scheme);
      if (path) await page.screenshot({ path });
    });

    test('ayar geçmişi: sayfalı liste, rozetler; axe temiz', async ({ page }, testInfo) => {
      await mockApi(page, {
        history: (request) =>
          request.query.get('cursor')
            ? { body: makeHistory([makeHistoryItem({ revision: 3, action: 'geri_cek' })]) }
            : {
                body: makeHistory(
                  [
                    makeHistoryItem(),
                    makeHistoryItem({
                      revision: 6,
                      item: 'defaults',
                      action: 'degistir',
                      record: null,
                      replaced_record: null,
                      default_desi_before: '2.00',
                      default_desi_after: '3.00',
                      affects_from: null,
                    }),
                  ],
                  { next_cursor: 'sonraki' },
                ),
              },
      });
      await page.goto('/panel/ayarlar');
      const history = page.getByRole('list', { name: 'Ayar değişiklikleri' });
      await expect(history).toContainText('Varsayılan desi değiştirildi');
      await expect(history).toContainText('2 → 3');
      await page.getByRole('button', { name: 'Daha fazla göster' }).click();
      await expect(history).toContainText('Geri çekildi');
      await expect(page.getByRole('button', { name: 'Daha fazla göster' })).toHaveCount(0);
      await checkPage(page, 'panel-ayarlar-gecmis', testInfo.project.name, scheme);
    });

    test('hata durumu: ayrıntı yok, tekrar dene; axe temiz', async ({ page }, testInfo) => {
      await mockApi(page, { settings: () => problem(503, 'busy') });
      await page.goto('/panel/ayarlar');
      const alert = page.getByRole('alert').filter({ hasText: 'Kâr ayarları yüklenemedi' });
      await expect(alert).toBeVisible();
      await expect(alert).toContainText('Rapor şu an yoğun');
      await expect(alert.getByRole('button', { name: 'Tekrar dene' })).toBeVisible();
      await checkPage(page, 'panel-ayarlar-hata', testInfo.project.name, scheme);
    });
  });
}

test.describe('kâr ayarları, davranış', () => {
  test.beforeEach(async ({ context }) => {
    await signIn(context);
  });

  test('yükleniyor durumu duyurulur', async ({ page }) => {
    await mockApi(page, { delayMs: 500 });
    await page.goto('/panel/ayarlar');
    await expect(page.getByRole('status').filter({ hasText: 'Yükleniyor' }).first()).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Kargo tarifesi' })).toBeVisible();
  });

  test('ilk giriş istisnası: onay penceresi çıkmaz, onay alanı gönderilmez', async ({ page }) => {
    let saved = false;
    await mockApi(page, {
      settings: () => ({
        body: saved
          ? makeSettings({ revision: 1, cargo_tariffs: [makeTariff({ carrier: 'Yurtiçi Kargo' })] })
          : makeEmptySettings(),
      }),
      writes: {
        'PUT /cargo-tariffs': () => {
          saved = true;
          return {
            body: {
              ...makeWriteInfo({ revision: 1, affects_past: true }),
              created: true,
              tariff: makeTariff({ carrier: 'Yurtiçi Kargo' }),
            },
          };
        },
      },
    });
    await page.goto('/panel/ayarlar');
    const form = await openTariffForm(page);
    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    await expect(page.getByText(/Tarife eklendi/)).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const put = seen.find((s) => s.method === 'PUT');
    expect(put?.body).toMatchObject({ carrier: 'Yurtiçi Kargo', expected_revision: 0 });
    expect(put?.body).not.toHaveProperty('confirm_affects_from');
    expect(put?.body).not.toHaveProperty('confirm_past_change');
    await expect(page.getByRole('heading', { level: 4, name: 'Yurtiçi Kargo' })).toBeVisible();
  });

  test('409 onay: "Değişikliği uygula" etki tarihi ve sürümle yeniden gönderir', async ({
    page,
  }) => {
    let attempt = 0;
    await mockApi(page, {
      writes: {
        'PUT /cargo-tariffs': () => {
          attempt += 1;
          if (attempt === 1) return PAST_409('2026-08-10', 12);
          return {
            body: {
              ...makeWriteInfo({ revision: 13, affects_past: true }),
              created: true,
              tariff: makeTariff(),
            },
          };
        },
      },
    });
    await page.goto('/panel/ayarlar');
    const form = await openTariffForm(page);
    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    const dialog = page.getByRole('dialog', { name: 'Geçmiş raporlar değişecek' });
    await dialog.getByRole('button', { name: 'Değişikliği uygula' }).click();
    await expect(page.getByText(/Tarife eklendi/)).toBeVisible();
    await expect(dialog).toBeHidden();
    const puts = seen.filter((s) => s.method === 'PUT');
    expect(puts).toHaveLength(2);
    expect(puts[1]?.body).toMatchObject({
      confirm_affects_from: '2026-08-10',
      expected_revision: 12,
    });
  });

  test('409 onay: vazgeç yeni istek göndermez, Escape ile de kapanır', async ({ page }) => {
    await mockApi(page, { writes: { 'PUT /cargo-tariffs': () => PAST_409('2026-08-10') } });
    await page.goto('/panel/ayarlar');
    const form = await openTariffForm(page);
    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    const dialog = page.getByRole('dialog', { name: 'Geçmiş raporlar değişecek' });
    await dialog.getByRole('button', { name: 'Vazgeç' }).click();
    await expect(dialog).toBeHidden();
    expect(seen.filter((s) => s.method === 'PUT')).toHaveLength(1);
    await expect(form).toBeVisible();

    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    expect(seen.filter((s) => s.method === 'PUT')).toHaveLength(2);
  });

  test('409 onay: "Yalnız bugünden itibaren uygula" başlangıcı bugün olan sürümü gönderir', async ({
    page,
  }) => {
    let attempt = 0;
    await mockApi(page, {
      writes: {
        'PUT /cargo-tariffs': () => {
          attempt += 1;
          if (attempt === 1) return PAST_409('2026-08-10');
          return {
            body: { ...makeWriteInfo({ revision: 10 }), created: true, tariff: makeTariff() },
          };
        },
      },
    });
    await page.goto('/panel/ayarlar');
    const form = await openTariffForm(page);
    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    await page
      .getByRole('dialog', { name: 'Geçmiş raporlar değişecek' })
      .getByRole('button', { name: 'Yalnız bugünden itibaren uygula' })
      .click();
    await expect(page.getByText(/Tarife eklendi/)).toBeVisible();
    const second = seen.filter((s) => s.method === 'PUT')[1];
    const today = await page.evaluate(() =>
      new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul' }).format(new Date()),
    );
    expect(second?.body?.valid_from).toBe(today);
    expect(second?.body).not.toHaveProperty('confirm_affects_from');
  });

  test('geri çekme: DELETE sorgusunda onay ve sürüm, geri çekme metni', async ({ page }) => {
    let attempt = 0;
    await mockApi(page, {
      writes: {
        [`DELETE /cargo-tariffs/${TARIFF_ID}`]: () => {
          attempt += 1;
          if (attempt === 1) return PAST_409('2026-10-01', 7);
          return { body: makeWriteInfo({ revision: 8, action: 'retracted' }) };
        },
      },
    });
    await page.goto('/panel/ayarlar');
    await page.getByRole('button', { name: /Geri çek\s*: Trendyol Express/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Geçmiş raporlar değişecek' });
    await expect(dialog).toContainText(
      "Bu sürüm geri çekilirse 1 Ekim 2026 sonrası siparişlerde kargo önceki sürümden ya da 'diğer firmalar' tarifesinden hesaplanır",
    );
    await dialog.getByRole('button', { name: 'Değişikliği uygula' }).click();
    await expect(page.getByText(/Trendyol Express tarifesi geri çekildi/)).toBeVisible();
    const deletes = seen.filter((s) => s.method === 'DELETE');
    expect(deletes[1]?.query.get('confirm_affects_from')).toBe('2026-10-01');
    expect(deletes[1]?.query.get('expected_revision')).toBe('7');
  });

  test('settings-record-ended: ekran yenilenir, satır içi uyarı role="alert"', async ({ page }) => {
    await mockApi(page, {
      writes: {
        [`PUT /variable-expenses/${EXPENSE_ID}`]: () =>
          problem(409, 'settings-record-ended', { current_id: null }),
      },
    });
    await page.goto('/panel/ayarlar');
    await page.getByRole('button', { name: /Düzenle\s*: Paketleme/ }).click();
    const form = page.getByRole('form', { name: 'Değişken gideri düzenle' });
    await form.getByLabel(/Tutar \(KDV hariç/).fill('7');
    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    const alert = page
      .getByRole('alert')
      .filter({ hasText: 'Bu kayıt başka bir değişiklikle güncellendi. Ekranı yeniledik.' });
    await expect(alert).toBeVisible();
    await expect(form).toBeHidden();
    // Ayarlar yeniden okundu
    expect(
      seen.filter((s) => s.method === 'GET' && s.path === SETTINGS).length,
    ).toBeGreaterThanOrEqual(2);
  });

  test('422: sunucu alan hatası alanın yanında gösterilir', async ({ page }) => {
    await mockApi(page, {
      settings: () => ({ body: makeEmptySettings() }),
      writes: {
        'PUT /cargo-tariffs': () =>
          problem(422, 'validation-error', {
            errors: [{ field: 'brackets.0.price', code: 'price_out_of_range' }],
          }),
      },
    });
    await page.goto('/panel/ayarlar');
    const form = await openTariffForm(page);
    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    await expect(
      form.getByText('Fiyat 0 ile 100.000 arasında ve en çok 2 ondalıklı olmalı.'),
    ).toBeVisible();
    await expect(form.getByLabel(/1\. kademe fiyatı/)).toHaveAttribute('aria-invalid', 'true');
    await expect(form).toBeVisible();
  });

  test('değişken gider eklenir ve varsayılan desi kaydedilir', async ({ page }) => {
    await mockApi(page, {
      writes: {
        'POST /variable-expenses': () => ({
          status: 201,
          body: { ...makeWriteInfo({ revision: 8 }), expense: makeExpense() },
        }),
        'PUT /defaults': () => ({
          body: { ...makeWriteInfo({ revision: 9, action: 'replaced' }), default_desi: '4.00' },
        }),
      },
    });
    await page.goto('/panel/ayarlar');
    await page.getByRole('button', { name: 'Gider ekle' }).click();
    const form = page.getByRole('form', { name: 'Yeni değişken gider' });
    await form.getByLabel('Gider adı').fill('E-fatura');
    await form.getByLabel(/Tutar \(KDV hariç/).fill('1,5');
    await form.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }).click();
    await expect(page.getByText('Gider eklendi.')).toBeVisible();
    expect(seen.find((s) => s.method === 'POST')?.body).toMatchObject({
      name: 'E-fatura',
      amount_excl_vat: '1.50',
      kind: 'siparis_basi',
    });

    const desi = page.getByRole('form', { name: 'Varsayılan desi' });
    await desi.getByLabel('Varsayılan desi').fill('4');
    await desi.getByRole('button', { name: 'Kaydet' }).click();
    await expect(page.getByText('Varsayılan desi kaydedildi.')).toBeVisible();
  });

  test('özet bandındaki bağlantı ayar bölümüne iner (#kargo)', async ({ page }) => {
    await mockApi(page);
    await page.goto('/panel');
    const banner = page.getByRole('region', { name: 'Kurulum uyarısı' });
    await banner.getByRole('link', { name: 'Kargo tarifesini gir' }).click();
    await expect(page).toHaveURL(/\/panel\/ayarlar#kargo$/);
    const heading = page.getByRole('heading', { level: 2, name: 'Kargo tarifesi' });
    await expect(heading).toBeInViewport();
  });

  test('görüntüleyici yalnız okur', async ({ page }) => {
    await mockApi(page);
    await page.route('**/api/v1/me', (route) => fulfill(route, { body: { role: 'viewer' } }));
    await page.goto('/panel/ayarlar');
    await expect(page.getByText(/Ayarları görüntüleyebilirsiniz/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Tarife ekle' })).toHaveCount(0);
  });
});
