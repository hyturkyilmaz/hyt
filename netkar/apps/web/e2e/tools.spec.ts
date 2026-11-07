import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import { screenshotPath, waitForReady } from './helpers';

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

// Girdilerin sunucuya gitmediğini kanıtlamak için: sayfa yüklendikten sonra POST veya /api çağrısı olmamalı
function trackOutgoing(page: Page) {
  const calls: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (request.method() !== 'GET' || url.pathname.startsWith('/api/')) {
      calls.push(`${request.method()} ${url.pathname}`);
    }
  });
  return calls;
}

test.describe('komisyon hesaplayıcısı', () => {
  test('örnek sonuç sunucuda hazır gelir; yazınca güncellenir, hiçbir veri gönderilmez', async ({
    page,
  }, testInfo) => {
    // JavaScript çalışmadan da örnek sonuç HTML'de bulunur (arama motoru ve GEO)
    const html = await (await page.request.get('/araclar/trendyol-komisyon-hesaplama')).text();
    expect(html).toContain('Hakediş (satış eksi komisyon)');
    expect(html).toContain('474,00');

    await page.goto('/araclar/trendyol-komisyon-hesaplama');
    await waitForReady(page);
    const calls = trackOutgoing(page);
    const table = () => page.getByRole('table', { name: 'Komisyon ve kesinti kırılımı' });
    await expect(page.getByText('Örnek değerler')).toBeVisible();
    await page.screenshot({
      path: screenshotPath('arac-komisyon-ornek', testInfo),
      fullPage: true,
    });

    await page.getByLabel('Satış fiyatı (KDV dahil)').fill('1.000,00');
    await expect(table().getByRole('row', { name: /Toplam komisyon/ })).toContainText('-210,00');
    await page.getByLabel('Komisyon oranı').fill('15,5');
    await expect(table().getByRole('row', { name: /Toplam komisyon/ })).toContainText('-155,00');
    await expect(page.getByText('Örnek değerler')).toBeHidden();

    // KDV varsayımı karşılaştırması
    await page.getByLabel('Komisyon tutarı').selectOption('excl');
    await expect(table().getByRole('row', { name: /Toplam komisyon/ })).toContainText('-186,00');
    expect(calls).toEqual([]);
    await expectNoAxeViolations(page);
  });

  test('hatalı girdide alan hatası ve boş sonuç mesajı; axe temiz', async ({ page }, testInfo) => {
    await page.goto('/araclar/trendyol-komisyon-hesaplama');
    const price = page.getByLabel('Satış fiyatı (KDV dahil)');
    await price.fill('12abc');
    await expect(price).toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByText('Sayı olarak yazın. Örnek: 1.250,50')).toBeVisible();
    await expect(page.getByText('Sonucu görmek için alanları düzeltin')).toBeVisible();
    await expectNoAxeViolations(page);
    await page.screenshot({ path: screenshotPath('arac-komisyon-hata', testInfo), fullPage: true });
    await price.fill('250,75');
    await expect(price).not.toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByRole('table', { name: 'Komisyon ve kesinti kırılımı' })).toBeVisible();
  });

  test('sonuç alanının yüksekliği ayrılmıştır: değerler değişince sayfa kaymaz (CLS)', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      (window as unknown as { __cls: number }).__cls = 0;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries() as unknown as {
          value: number;
          hadRecentInput: boolean;
        }[]) {
          if (!entry.hadRecentInput) (window as unknown as { __cls: number }).__cls += entry.value;
        }
      }).observe({ type: 'layout-shift', buffered: true });
    });
    await page.goto('/araclar/trendyol-komisyon-hesaplama');
    await waitForReady(page);
    await page.getByLabel('Satış fiyatı (KDV dahil)').fill('1999');
    await page.getByLabel('Gönderi kargo bedeli').fill('45');
    await page.getByLabel('Platform hizmet bedeli (KDV hariç)').fill('10');
    const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
    expect(cls).toBeLessThanOrEqual(0.05);
  });
});

test.describe('kâr hesaplayıcısı', () => {
  test('örnek sonuç, ROAS girişi, iade payı ve başabaş değerleri', async ({ page }, testInfo) => {
    await page.goto('/araclar/trendyol-kar-hesaplama');
    await waitForReady(page);
    const calls = trackOutgoing(page);
    const table = () => page.getByRole('table', { name: 'Net kâr kırılımı' });
    // 600 TL, maliyet 250, komisyon %21, kargo 60: iade öncesi net kâr 85,00
    await expect(table().getByRole('row', { name: /İade öncesi net kâr/ })).toContainText('85,00');

    await page.getByLabel('İade oranı').fill('0');
    await expect(table().getByRole('row', { name: /Beklenen iade payı/ })).toContainText('0,00');
    await page.getByLabel('İade oranı').fill('100');
    // %100 iade, ürün stoğa döner: kayıp = kargo + iade kargo = -120,00
    await expect(page.locator('div[aria-live=polite]')).toContainText('-120,00');

    await page.getByLabel('İade oranı').fill('5');
    await page.getByLabel('Reklam girişi').selectOption('roas');
    await page.getByLabel('ROAS', { exact: true }).fill('6');
    await expect(table().getByRole('row', { name: /Reklam \(KDV hariç\)/ })).toContainText(
      '-100,00',
    );
    await expect(
      table().getByRole('row', { name: /Başabaş ROAS \(ciro KDV hariç\)/ }),
    ).toBeVisible();
    expect(calls).toEqual([]);
    await expectNoAxeViolations(page);
    await page.screenshot({ path: screenshotPath('arac-kar-roas', testInfo), fullPage: true });
  });

  test('maliyet satıştan yüksekse uyarı çıkar, zarar işaret ve metinle belirtilir', async ({
    page,
  }, testInfo) => {
    await page.goto('/araclar/trendyol-kar-hesaplama');
    await page.getByLabel(/Alış maliyeti/).fill('900');
    await expect(page.getByText(/Alış maliyeti satış fiyatının/)).toBeVisible();
    await expect(page.getByText(/Zarar:/).first()).toBeAttached();
    await expectNoAxeViolations(page);
    await page.screenshot({ path: screenshotPath('arac-kar-zarar', testInfo), fullPage: true });
  });

  test('açıklayıcı bölümler: formül, varsayımlar ve örnek hesap görünür', async ({ page }) => {
    await page.goto('/araclar/trendyol-kar-hesaplama');
    await expect(page.getByRole('heading', { level: 2, name: 'Formül' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Varsayımlar' })).toBeVisible();
    await expect(page.getByText(/Bu bir tahmindir/).first()).toBeVisible();
    await expect(
      page.getByRole('heading', { name: /Gerçek rakamlarınız bu tahmine/ }),
    ).toBeVisible();
  });
});

test.describe('desi hesaplayıcısı', () => {
  test('hacim ve ağırlık karşılaştırması, küçültme tablosu', async ({ page }, testInfo) => {
    await page.goto('/araclar/desi-hesaplama');
    await waitForReady(page);
    const table = () => page.getByRole('table', { name: 'Desi sonucu' });
    await expect(table().getByRole('row', { name: /Ücretlendirmeye esas/ })).toContainText('2,00');
    await page.getByLabel(/Ağırlık/).fill('7,5');
    await expect(table().getByRole('row', { name: /Ücretlendirmeye esas/ })).toContainText('7,50');
    await expect(table().getByRole('row', { name: /Ücretlendirmeye esas/ })).toContainText(
      'ağırlık esas alınır',
    );
    await page.getByLabel('Bölen').selectOption('international');
    await expect(table().getByRole('row', { name: /^Hacimsel desi/ })).toContainText('1,20');
    await expect(page.getByRole('table', { name: 'Koli küçülürse desi değişimi' })).toBeVisible();
    await expectNoAxeViolations(page);
    await page.screenshot({ path: screenshotPath('arac-desi-guncel', testInfo), fullPage: true });
  });
});
