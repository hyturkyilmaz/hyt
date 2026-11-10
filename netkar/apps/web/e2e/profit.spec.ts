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
  makePartialTotals,
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
    if (path === `${PROFIT}/products`) {
      // Özetin "zarar ettiren ürünler" bölümü de bu uca düşer; senaryo vermezse zarar listesi döner.
      const result = handlers.products?.(url) ?? { body: makeList(ITEMS.slice(1, 4)) };
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
  // Y-3: aktif satırı olmayıp yalnız satışsız reklamı olan ürün (kesinlik yok, net kâr negatif)
  makeItem({
    barcode: 'BRK-0006',
    title: 'Yalnız Reklamlı Ürün',
    net_profit: '-25.00',
    net_margin_percent: null,
    loss_reason: 'net_profit',
    certainty: 'yok',
    contribution_excl_missing: '-25.00',
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
      await expect(page.getByRole('heading', { level: 2, name: 'Dönem net kârı' })).toBeVisible();
      await expect(page.getByText('Satır durumları')).toBeVisible();
      await expect(page.getByText(/Zararına satış/)).toBeVisible();
      await expect(page.getByRole('region', { name: 'Kurulum uyarısı' })).toHaveCount(0);
      await expect(page.getByText('Ayar sürümü 7')).toBeVisible();
      // UX-08: yer tutucu uyarılar sayfasına bağlantı yok
      await expect(page.getByRole('link', { name: 'Tüm uyarılar' })).toHaveCount(0);
      // UX-03 ve UX-04: en büyük zarar üstte; net kârı null kesin zarar (-12) da listede, "en az" ile
      const losses = page.getByRole('region', { name: 'Zarar ettiren ürünler' });
      await expect(losses.getByRole('listitem').first()).toContainText('Silikon Kek Kalıbı Set');
      await expect(losses.getByRole('listitem').nth(1)).toContainText('Maliyeti Girilmemiş Bardak');
      await expect(losses.getByRole('listitem').nth(1)).toContainText('En az ₺12,00 zarar');
      expect(
        requests.some(
          (u) => u.pathname.endsWith('/summary') && u.searchParams.get('range') === '7d',
        ),
      ).toBe(true);
      await checkPage(page, 'rapor-ozet', testInfo.project.name, scheme);
    });

    test('özet: ayarsız hesapta (durum C) net kâr hesaplanamadı, 0,00 yok, bilinen kâr kırmızı, ayar çıkmazı yok', async ({
      page,
    }, testInfo) => {
      await mockApi(page, { summary: () => makeSummary(makeUnconfiguredTotals()) });
      await page.goto('/panel');
      const heading = page.getByRole('heading', { level: 2, name: 'Dönem net kârı hesaplanamadı' });
      await expect(heading).toBeVisible();
      const card = heading.locator('xpath=ancestor::div[2]');
      await expect(card).toContainText('12 satırda kargo, 12 satırda hizmet bedeli tahmini eksik.');
      await expect(card).not.toContainText('0,00');
      await expect(card).toContainText('Eksik giderler hariç dönem kârı');
      await expect(card).toContainText('-₺17,35');
      await expect(card.getByText('Bilinen giderlerle bile zarar')).toBeVisible();
      // Gider ve marj kartları, eksiksiz satır bloğu çizilmez
      await expect(page.getByRole('heading', { name: 'Toplam gider' })).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'Net kâr marjı' })).toHaveCount(0);
      // UX-05 ve UX-02: yeni başlık, boş ayar sayfasına götüren bağlantı yok
      const banner = page.getByRole('region', { name: 'Kurulum uyarısı' });
      await expect(banner).toContainText('Net kâr için kargo tarifesi ve hizmet bedeli gerekiyor');
      await expect(banner).toContainText('girişi çok yakında');
      await expect(banner).toContainText('Bu rakamlar bilinen giderlerle hesaplanıyor');
      // Y-4: bilinen kâr bloğu uyarı kutusunun üstünde (mobilde de rakam önce görünür)
      const knownBox = await card
        .getByRole('heading', { name: 'Eksik giderler hariç dönem kârı' })
        .boundingBox();
      const bannerBox = await banner.boundingBox();
      expect(knownBox!.y).toBeLessThan(bannerBox!.y);
      await expect(banner.getByRole('link')).toHaveCount(0);
      await checkPage(page, 'rapor-ozet-ayarsiz', testInfo.project.name, scheme);
    });

    test('özet: kısmi dönem, eksiksiz satır var (durum B); bilinen kâr nötr; axe temiz', async ({
      page,
    }, testInfo) => {
      await mockApi(page, { summary: () => makeSummary(makePartialTotals()) });
      await page.goto('/panel');
      const heading = page.getByRole('heading', { level: 2, name: 'Dönem net kârı hesaplanamadı' });
      await expect(heading).toBeVisible();
      const card = heading.locator('xpath=ancestor::div[2]');
      await expect(card).toContainText('Eksik giderler hariç dönem kârı');
      await expect(card).toContainText('(kargo hariç)');
      await expect(card).toContainText('1.240,00');
      await expect(card).toContainText('Kargo düşülünce bu rakam azalır.');
      await expect(
        card.getByRole('heading', { name: 'Eksiksiz satırların net kârı' }),
      ).toBeVisible();
      await expect(card).toContainText('20 eksiksiz satır, dönem giderleri hariç.');
      await expect(
        page.getByText('Eksiksiz satırların marjı, dönem giderleri hariç'),
      ).toBeVisible();
      await checkPage(page, 'rapor-ozet-kismi', testInfo.project.name, scheme);
    });

    test('ayarlar: gerçek hesap durumu ve kargo tarifesi bölümünün yakında olduğu; axe temiz', async ({
      page,
    }, testInfo) => {
      await mockApi(page, {});
      await page.goto('/panel/ayarlar');
      await expect(page.getByRole('heading', { level: 1, name: 'Ayarlar' })).toBeVisible();
      await expect(page.getByText('Bağlı', { exact: true })).toBeVisible();
      await expect(page.getByText('Bağlı değil')).toHaveCount(0);
      await expect(page.getByText('Satıcı numarası:')).toBeVisible();
      await expect(
        page.getByRole('region', { name: 'Kargo tarifesi ve hizmet bedeli' }),
      ).toContainText('girişi çok yakında');
      await checkPage(page, 'panel-ayarlar-bagli', testInfo.project.name, scheme);
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
      await expect(visible.getByText('Zarar', { exact: true }).first()).toBeVisible();
      await expect(visible.getByText('Maliyet girilmese de zarar')).toBeVisible();
      await expect(visible.getByText('Bilinen giderlerle bile zarar')).toBeVisible();
      await expect(visible.getByText('Belirsiz', { exact: true })).toBeVisible();
      // UX-07 ve Y-5: kesin zarardaki ama net kârı null ürün kırmızı "En az ₺... zarar" ve "Net kâr hesaplanamadı" gösterir
      await expect(visible.getByText('En az ₺4,00 zarar').first()).toBeVisible();
      await expect(visible.getByText('Net kâr hesaplanamadı').first()).toBeVisible();
      // Y-3: yalnız satışsız reklamı olan ürün zarardır, İptal değil
      await expect(visible.getByText('Yalnız Reklamlı Ürün')).toBeVisible();
      await expect(visible.getByText('İptal', { exact: true })).toHaveCount(0);
      await expect(
        visible.getByText('Kargo ve hizmet bedeli düşülünce bu rakam azalır.'),
      ).toBeVisible();
      // UX-10: tekrar eden "Kargo eksik" ve "Bilgi eksik" rozetleri yok
      await expect(visible.getByText('Kargo eksik')).toHaveCount(0);
      await expect(visible.getByText('Bilgi eksik')).toHaveCount(0);
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

    test('ürün kırılımı: kesin zarar, tüm gider satırları ve ayar sürümü; axe temiz', async ({
      page,
    }, testInfo) => {
      const base = makeDetail([makeLine()]);
      // Görünen satırlar bilinen kârla tutar: 1250 - 729,85 - 187,50 - 225 - 20 - 41,65 - 10 - 15 - 25 = -4,00
      const product = {
        ...base.product!,
        urun_maliyeti: '729.85',
        kargo_iade: '20.00',
        ceza: '10.00',
        degisken_giderler: '15.00',
        reklam_satirlara_dagitilan: '25.00',
        net_kar: null,
        net_kar_marji_yuzde: null,
        eksik_giderler_haric_kar: '-4.00',
        eksik_kalem_satir_sayilari: {
          urun_maliyeti: 0,
          kargo_gonderi: 2,
          platform_hizmet_bedeli: 2,
        },
        kesinlik: 'eksik' as const,
      };
      await mockApi(page, {
        detail: () => ({ body: { ...base, product, certainty: 'eksik' as const } }),
      });
      await page.goto('/panel/urunler/BRK-0001');
      const card = page
        .getByRole('heading', { level: 2, name: 'Ürün net kârı' })
        .locator('xpath=ancestor::div[2]');
      await expect(card).toContainText('Kargo iadesi');
      await expect(card.getByText('Reklam', { exact: true })).toBeVisible();
      // Y-6: kısmen eksik kalem bilinen tutarı da gösterir
      await expect(card).toContainText('₺225,00');
      await expect(card).toContainText('+ 2 satırda eksik');
      await expect(card).toContainText('Bilinen giderlerle bile zarar');
      await expect(card).toContainText('-₺4,00');
      await expect(page.getByText('Ayar sürümü 7')).toBeVisible();
      await checkPage(page, 'rapor-urun-kirilim-zarar', testInfo.project.name, scheme);
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
    // Zarar süzgecinde varsayılan yön artan (en çok zarar önce); URL'de order yazılmaz (UX-04)
    await expect(page).toHaveURL(/range=7d&sort=sales&filter=loss$/);
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
    await expect(page.getByText('20 eksiksiz satır, dönem giderleri hariç.')).toBeVisible();
    await expect(page.getByText('Eksiksiz satırların marjı, dönem giderleri hariç')).toBeVisible();
    await expect(page.getByText('-5,5')).toHaveCount(0);
    // Eski biçimde kısmi dönemde dolu gelen donem_net_kar asla gösterilmez
    await expect(page.getByText('-₺10,00')).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Kurulum uyarısı' })).toContainText(
      'Net kâr için kargo tarifesi gerekiyor',
    );
    // Y-7: eksiksiz satır bloğu etiketi
    await expect(page.getByRole('heading', { name: 'Eksiksiz satırların net kârı' })).toBeVisible();
  });

  test('özet: zarar ettiren ürünler "Tümünü gör" zarar süzgecini en çok zarar önce açar', async ({
    page,
  }) => {
    await mockApi(page, {
      products: (url) => ({
        body: makeList(url.searchParams.get('limit') === '3' ? ITEMS.slice(1, 4) : ITEMS, {
          filter: url.searchParams.get('filter') ?? 'all',
        }),
      }),
    });
    await page.goto('/panel?range=7d');
    const losses = page.getByRole('region', { name: 'Zarar ettiren ürünler' });
    await expect(losses.getByRole('listitem').first()).toContainText('Silikon Kek Kalıbı Set');
    await losses.getByRole('link', { name: /Tümünü gör/ }).click();
    await expect(page).toHaveURL(/\/panel\/urunler\?range=7d&filter=loss$/);
    await expect(page.getByRole('link', { name: 'Zarar edenler' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    await expect
      .poll(() =>
        requests.some(
          (u) =>
            u.pathname.endsWith('/products') &&
            u.searchParams.get('filter') === 'loss' &&
            u.searchParams.get('order') === 'asc' &&
            u.searchParams.get('limit') === '50',
        ),
      )
      .toBe(true);
    // Y-1: AD-04 ile eksikli zararlar doğru sıralanır; "listenin sonunda" notu yok
    await expect(page.getByText(/listenin sonunda/)).toHaveCount(0);
  });

  test('uyarılar: yer tutucu dürüst "yakında" der, mağaza bağlama çağrısı yapmaz', async ({
    page,
  }) => {
    await mockApi(page, {});
    await page.goto('/panel/uyarilar');
    await expect(
      page.getByRole('heading', { level: 2, name: 'Uyarılar ekranı yakında' }),
    ).toBeVisible();
    await expect(page.getByText(/Mağazanızı bağlayınca/)).toHaveCount(0);
    await expect(page.getByText('Şu an bir uyarı yok')).toHaveCount(0);
  });
});
