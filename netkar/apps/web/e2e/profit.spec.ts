import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import {
  ACCOUNT_ID,
  SAMPLE_ALERT_COUNTS,
  makeAccounts,
  makeAlerts,
  makeDetail,
  makeItem,
  makeLine,
  makeList,
  makeSummary,
  makeTotals,
  makeUnconfiguredTotals,
} from '../src/lib/profit/test-fixtures';
import { signIn, waitForReady } from './helpers';

// Rapor ekranları: tarayıcının /api/v1 istekleri Playwright route ile taklit edilir (sahte API yalnız
// oturum için /v1/me yanıtlar). Ekran görüntüleri PW_SHOTS_DIR verilirse oraya yazılır.
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const PROFIT = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/profit`;

interface Handlers {
  summary?: (url: URL) => unknown;
  products?: (url: URL) => { status?: number; body: unknown };
  detail?: (url: URL) => { status?: number; body: unknown };
}

const requests: URL[] = [];

async function fulfill(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: status >= 400 ? 'application/problem+json' : 'application/json',
    body: JSON.stringify(body),
  });
}

async function mockApi(page: Page, handlers: Handlers) {
  requests.length = 0;
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const path = url.pathname;
    if (path === '/api/v1/marketplace-accounts') return fulfill(route, 200, makeAccounts());
    if (path === `${PROFIT}/summary`) {
      return fulfill(route, 200, handlers.summary?.(url) ?? makeSummary());
    }
    if (path === `${PROFIT}/alerts`) {
      return fulfill(route, 200, makeAlerts(SAMPLE_ALERT_COUNTS));
    }
    if (path === `${PROFIT}/products` && handlers.products) {
      const result = handlers.products(url);
      return fulfill(route, result.status ?? 200, result.body);
    }
    if (path.startsWith(`${PROFIT}/products/`) && handlers.detail) {
      const result = handlers.detail(url);
      return fulfill(route, result.status ?? 200, result.body);
    }
    return fulfill(route, 404, {
      type: 'urn:netkar:problem:not-found',
      title: 'Bulunamadı',
      status: 404,
    });
  });
}

// Mobilde kart, masaüstünde tablo görünür; ikisi de DOM'da olduğu için yalnız görünen eşleşme alınır.
function visibleText(page: Page, text: string) {
  return page.getByText(text).filter({ visible: true }).first();
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
  if (path) await page.screenshot({ path });
}

const ITEMS = [
  makeItem({ barcode: 'BRK-0001', title: 'Örnek Ürün Çelik Termos 500 ml' }),
  makeItem({
    barcode: 'BRK-0002',
    title: 'Silikon Kek Kalıbı Set',
    net_profit: '-30.00',
    net_margin_percent: '-8.0',
    loss_reason: 'net_profit',
    certainty: 'tahmini',
  }),
  makeItem({
    barcode: 'BRK-0003',
    title: 'Maliyeti Girilmemiş Bardak',
    net_profit: null,
    net_margin_percent: null,
    loss_reason: 'contribution_before_cost',
    cost_missing: true,
    missing_items: ['urun_maliyeti'],
    contribution_excl_missing: '-12.00',
    certainty: 'eksik',
  }),
  makeItem({
    barcode: 'BRK-0004',
    title: 'Kargo Tarifesi Eksik Ürün',
    net_profit: null,
    net_margin_percent: null,
    loss_reason: 'known_expenses',
    shipping_missing: true,
    missing_items: ['kargo_gonderi', 'platform_hizmet_bedeli'],
    contribution_excl_missing: '-4.00',
    certainty: 'eksik',
  }),
  makeItem({
    barcode: 'BRK-0005',
    title: 'Belirsiz Kâr Ürünü',
    net_profit: null,
    net_margin_percent: null,
    missing_items: ['kargo_gonderi'],
    contribution_excl_missing: '75.00',
    shipping_missing: true,
    certainty: 'eksik',
  }),
];

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`rapor ekranları, ${scheme === 'light' ? 'açık' : 'koyu'} tema`, () => {
    test.use({ colorScheme: scheme });

    test.beforeEach(async ({ context }) => {
      await signIn(context);
    });

    test('özet: başlık kartları, durum dağılımı, uyarılar; axe temiz', async ({
      page,
    }, testInfo) => {
      await mockApi(page, {});
      await page.goto('/panel?range=7d');
      await expect(page.getByRole('heading', { level: 1, name: 'Özet' })).toBeVisible();
      await expect(page.getByText('3.120,45', { exact: false }).first()).toBeVisible();
      await expect(page.getByText('Satır durumları')).toBeVisible();
      await expect(page.getByText(/Zararına satış/)).toBeVisible();
      await expect(page.getByRole('region', { name: 'Kurulum uyarısı' })).toHaveCount(0);
      expect(
        requests.some(
          (u) => u.pathname.endsWith('/summary') && u.searchParams.get('range') === '7d',
        ),
      ).toBe(true);
      await checkPage(page, 'rapor-ozet', testInfo.project.name, scheme);
    });

    test('özet: ayarsız hesapta net kâr hesaplanamadı, 0,00 yok, kurulum bandı', async ({
      page,
    }, testInfo) => {
      await mockApi(page, { summary: () => makeSummary(makeUnconfiguredTotals()) });
      await page.goto('/panel');
      const banner = page.getByRole('region', { name: 'Kurulum uyarısı' });
      await expect(banner).toContainText(
        'Kargo tarifesi ve hizmet bedeli girilmedi: net kâr bu kalemler hariç hesaplanamaz',
      );
      await expect(banner.getByRole('link')).toHaveAttribute('href', '/panel/ayarlar');
      const netCard = page.getByText('Net kâr', { exact: true }).locator('xpath=ancestor::div[2]');
      await expect(netCard).toContainText('Hesaplanamadı');
      await expect(netCard).toContainText('Eksik: ürün maliyeti, kargo, hizmet bedeli');
      await expect(netCard).not.toContainText('0,00');
      await checkPage(page, 'rapor-ozet-ayarsiz', testInfo.project.name, scheme);
    });

    test('ürünler: liste, rozetler, mobilde kart ve masaüstünde tablo; axe temiz', async ({
      page,
    }, testInfo) => {
      await mockApi(page, { products: () => ({ body: makeList(ITEMS) }) });
      await page.goto('/panel/urunler');
      await expect(page.getByRole('heading', { level: 1, name: 'Ürünler' })).toBeVisible();

      if (testInfo.project.name === 'mobil') {
        await expect(page.getByRole('list', { name: 'Ürün listesi' })).toBeVisible();
        await expect(page.getByRole('table')).toBeHidden();
      } else {
        await expect(page.getByRole('table', { name: 'Ürün kârlılık tablosu' })).toBeVisible();
        await expect(page.getByRole('list', { name: 'Ürün listesi' })).toBeHidden();
      }
      const visible = page.locator(
        testInfo.project.name === 'mobil' ? 'ul[aria-label="Ürün listesi"]' : 'table',
      );
      await expect(visible.getByText('Zarar', { exact: true })).toBeVisible();
      await expect(visible.getByText('Maliyetsiz bile zarar')).toBeVisible();
      await expect(visible.getByText('Bilinen giderlerle bile zarar')).toBeVisible();
      await expect(visible.getByText('Belirsiz', { exact: true })).toBeVisible();
      await expect(visible.getByText('Kargo eksik').first()).toBeVisible();
      await checkPage(page, 'rapor-urunler', testInfo.project.name, scheme);
    });

    test('ürün kırılımı: satır, kaynaklar, iade notu, karşılaştırma; axe temiz', async ({
      page,
    }, testInfo) => {
      const lines = [
        makeLine(),
        makeLine({
          orderNumber: '10002',
          lineId: 9002,
          durum: 'adjusted',
          kesinlik: 'tahmini',
          uyarilar: ['IADE_KAYDI_BEKLENIYOR'],
          askidaki_urun_maliyeti: '120.00',
          kalemler: { ...makeLine().kalemler, net_kar: '-80.00' },
        }),
        makeLine({
          orderNumber: '10003',
          lineId: 9003,
          durum: 'estimated',
          kesinlik: 'eksik',
          eksik_kalemler: ['kargo_gonderi'],
          kalemler: {
            ...makeLine().kalemler,
            kargo_gonderi: '0.00',
            net_kar: null,
            toplam_gider: null,
            eksik_giderler_haric_kar: '84.17',
          },
          kaynaklar: {
            ...makeLine().kaynaklar,
            kargo_gonderi: 'eksik',
            platform_hizmet_bedeli: 'tahmini',
          },
        }),
        makeLine({
          orderNumber: '10004',
          lineId: 9004,
          uyarilar: ['BEKLENMEYEN_KESINTI', 'KARGO_DESI_VARSAYILAN'],
          karsilastirma: {
            komisyon_tahmini: '37.50',
            komisyon_kesin: '37.50',
            kargo_gonderi_tahmini: '45.00',
            kargo_gonderi_kesin: '120.00',
            platform_hizmet_bedeli_tahmini: '8.33',
            platform_hizmet_bedeli_kesin: '8.33',
            kargo_tahmini_varsayilan_desi: true,
            karsilastirilan_tahmini_toplam: '90.83',
            karsilastirilan_kesin_toplam: '165.83',
            fark: '75.00',
            esik: '5.00',
          },
        }),
      ];
      await mockApi(page, { detail: () => ({ body: makeDetail(lines) }) });
      await page.goto('/panel/urunler/BRK-0001?range=7d');
      await expect(
        page.getByRole('heading', { level: 1, name: 'Örnek Ürün Çelik Termos 500 ml' }),
      ).toBeVisible();
      await expect(page.getByRole('note')).toContainText('İade kaydı bekleniyor.');
      await expect(
        page.getByRole('region', { name: 'Tahmini ve kesin karşılaştırması' }),
      ).toContainText('Siparişte desi yoksa varsayılan desi farkı olabilir.');
      await checkPage(page, 'rapor-urun-kirilim', testInfo.project.name, scheme);
    });
  });
}

test.describe('rapor ekranları, davranış', () => {
  test.beforeEach(async ({ context }) => {
    await signIn(context);
  });

  test('dönem seçici URL range parametresini değiştirir', async ({ page }) => {
    await mockApi(page, {});
    await page.goto('/panel');
    await expect(page.getByText('Satır durumları')).toBeVisible();
    await page
      .getByRole('navigation', { name: 'Dönem' })
      .getByRole('link', { name: '7 gün' })
      .click();
    await expect(page).toHaveURL(/\/panel\?range=7d$/);
    await expect(
      page.getByRole('navigation', { name: 'Dönem' }).getByRole('link', { name: '7 gün' }),
    ).toHaveAttribute('aria-current', 'true');
    await expect
      .poll(() =>
        requests.some(
          (u) => u.pathname.endsWith('/summary') && u.searchParams.get('range') === '7d',
        ),
      )
      .toBe(true);
  });

  test('ürünler: sıralama ve süzgeç URL de tutulur; satıra tıklayınca kırılım açılır', async ({
    page,
  }) => {
    await mockApi(page, {
      products: () => ({ body: makeList(ITEMS) }),
      detail: () => ({ body: makeDetail([makeLine()]) }),
    });
    await page.goto('/panel/urunler?range=7d');
    await expect(page.getByRole('heading', { level: 1, name: 'Ürünler' })).toBeVisible();

    await page.getByLabel('Sırala').selectOption('sales');
    await expect(page).toHaveURL(/range=7d&sort=sales/);
    await page.getByLabel('Yön').selectOption('asc');
    await expect(page).toHaveURL(/range=7d&sort=sales&order=asc/);
    await page.getByRole('link', { name: 'Zarar edenler' }).click();
    await expect(page).toHaveURL(/range=7d&sort=sales&order=asc&filter=loss/);
    await expect
      .poll(() =>
        requests.some(
          (u) =>
            u.pathname.endsWith('/products') &&
            u.searchParams.get('sort') === 'sales' &&
            u.searchParams.get('order') === 'asc' &&
            u.searchParams.get('filter') === 'loss',
        ),
      )
      .toBe(true);

    await page.getByRole('link', { name: 'Örnek Ürün Çelik Termos 500 ml' }).first().click();
    await expect(page).toHaveURL(/\/panel\/urunler\/BRK-0001\?range=7d$/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Örnek Ürün Çelik Termos 500 ml' }),
    ).toBeVisible();
    await page.getByRole('link', { name: /Ürünlere dön/ }).click();
    await expect(page).toHaveURL(/\/panel\/urunler\?range=7d$/);
  });

  test('ürünler: daha fazla yükle ve imleç hatasında baştan yükleme', async ({ page }) => {
    let firstServed = 0;
    await mockApi(page, {
      products: (url) => {
        const cursor = url.searchParams.get('cursor');
        if (cursor === 'eski') {
          return {
            status: 422,
            body: {
              type: 'urn:netkar:problem:validation-error',
              title: 'Doğrulama hatası',
              status: 422,
              errors: [{ field: 'cursor', code: 'cursor_invalid' }],
            },
          };
        }
        firstServed += 1;
        return {
          body: makeList(
            [
              makeItem({
                barcode: 'S1',
                title: firstServed === 1 ? 'Eski Liste Ürünü' : 'Yeni Liste Ürünü',
              }),
            ],
            { next_cursor: firstServed === 1 ? 'eski' : null },
          ),
        };
      },
    });
    await page.goto('/panel/urunler');
    await expect(visibleText(page, 'Eski Liste Ürünü')).toBeVisible();
    await page.getByRole('button', { name: 'Daha fazla yükle' }).click();
    await expect(visibleText(page, 'Yeni Liste Ürünü')).toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: 'baştan yüklendi' })).toBeVisible();
    await expect(page.getByText('Eski Liste Ürünü')).toHaveCount(0);
  });

  test('hata durumunda ayrıntı yok, tekrar dene çalışır', async ({ page }) => {
    let fail = true;
    await mockApi(page, {
      products: () =>
        fail
          ? { status: 503, body: { type: 'urn:netkar:problem:busy', title: 'Meşgul', status: 503 } }
          : { body: makeList(ITEMS) },
    });
    await page.goto('/panel/urunler');
    await expect(page.getByRole('alert').filter({ hasText: 'Rapor şu an yoğun' })).toBeVisible();
    fail = false;
    await page.getByRole('button', { name: 'Tekrar dene' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Ürünler' })).toBeVisible();
    await expect(visibleText(page, 'Silikon Kek Kalıbı Set')).toBeVisible();
  });

  test('yükleniyor durumu duyurulur', async ({ page }) => {
    await mockApi(page, {
      products: () => ({ body: makeList(ITEMS) }),
    });
    await page.route('**/api/v1/marketplace-accounts', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 600));
      await fulfill(route, 200, makeAccounts());
    });
    await page.goto('/panel/urunler');
    await expect(page.getByRole('status').filter({ hasText: 'Yükleniyor' })).toBeVisible();
    await expect(visibleText(page, 'Silikon Kek Kalıbı Set')).toBeVisible();
  });

  test('özet kısmi dönem: eksiksiz satırlar bloğu ve etiketli marj', async ({ page }) => {
    const base = makeTotals();
    await mockApi(page, {
      summary: () =>
        makeSummary(
          makeTotals({
            net_kar_kismi: true,
            donem_net_kar: '-10.00',
            net_kar_marji_yuzde: '-5.45',
            eksik_kalem_satir_sayilari: {
              urun_maliyeti: 0,
              kargo_gonderi: 4,
              platform_hizmet_bedeli: 0,
            },
            tam_satirlar: {
              ...base.tam_satirlar,
              satir_sayisi: 20,
              net_kar: '800.00',
              net_kar_marji_yuzde: '12.5',
            },
          }),
        ),
    });
    await page.goto('/panel');
    await expect(page.getByText(/Eksiksiz 20 satırın net kârı/)).toBeVisible();
    await expect(page.getByText('Eksiksiz satırların marjı, dönem giderleri hariç')).toBeVisible();
    await expect(page.getByText('-5,5')).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Kurulum uyarısı' })).toContainText(
      'Kargo tarifesi girilmedi',
    );
  });
});
