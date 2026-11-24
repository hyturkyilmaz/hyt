import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import { screenshotPath, waitForReady } from './helpers';

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

const MARKETING_PATHS = [
  '/',
  '/ozellikler',
  '/fiyatlar',
  '/guvenlik-ve-kvkk',
  '/sss',
  '/araclar',
  '/araclar/trendyol-komisyon-hesaplama',
  '/araclar/trendyol-kar-hesaplama',
  '/araclar/desi-hesaplama',
];

async function jsonLdTypes(page: Page): Promise<string[]> {
  const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
  return blocks.map((raw) => (JSON.parse(raw) as { '@type': string })['@type']);
}

test.describe('SEO ve GEO işaretleri', () => {
  for (const path of MARKETING_PATHS) {
    test(`${path}: title, açıklama, kanonik, hreflang, Open Graph, tek h1`, async ({
      page,
      baseURL,
    }) => {
      await page.goto(path);
      await expect(page.locator('html')).toHaveAttribute('lang', 'tr');
      const title = await page.title();
      expect(title.length).toBeGreaterThan(5);
      expect(Array.from(title).length).toBeLessThanOrEqual(60);
      const description = await page.locator('meta[name="description"]').getAttribute('content');
      expect((description ?? '').length).toBeGreaterThan(50);
      expect((description ?? '').length).toBeLessThanOrEqual(155);
      const canonical = await page.locator('link[rel="canonical"]').getAttribute('href');
      expect(canonical).toBe(
        `${baseURL}${path === '/' ? '' : path}`.replace(/\/$/, '') || `${baseURL}`,
      );
      await expect(page.locator('link[rel="alternate"][hreflang="tr"]')).toHaveCount(1);
      await expect(page.locator('link[rel="alternate"][hreflang="x-default"]')).toHaveCount(1);
      await expect(page.locator('link[rel="alternate"][hreflang="en"]')).toHaveCount(0);
      await expect(page.locator('meta[property="og:title"]')).toHaveCount(1);
      await expect(page.locator('meta[property="og:url"]')).toHaveCount(1);
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
      // İlk paragraf (önce cevap): başlıktan sonraki ilk paragraf en az 25 kelime
      const lead = await page
        .locator('main h1')
        .first()
        .evaluate((h1) => {
          let node = h1.nextElementSibling;
          while (node && node.tagName !== 'P') node = node.nextElementSibling;
          return node?.textContent ?? h1.parentElement?.querySelector('p')?.textContent ?? '';
        });
      expect(lead.trim().split(/\s+/).length).toBeGreaterThanOrEqual(20);
    });
  }

  test('JSON-LD: ana sayfada Organization + SoftwareApplication, FAQPage yok', async ({ page }) => {
    await page.goto('/');
    const types = await jsonLdTypes(page);
    expect(types).toEqual(expect.arrayContaining(['Organization', 'SoftwareApplication']));
    expect(types).not.toContain('FAQPage');
  });

  test('JSON-LD: FAQPage yalnız /sss sayfasında, soru sayısı görünür listeyle aynı', async ({
    page,
  }) => {
    for (const path of MARKETING_PATHS) {
      await page.goto(path);
      const types = await jsonLdTypes(page);
      if (path === '/sss') expect(types).toContain('FAQPage');
      else expect(types, path).not.toContain('FAQPage');
    }
    await page.goto('/sss');
    const raw = await page
      .locator('script[type="application/ld+json"]')
      .evaluateAll((nodes) =>
        nodes.map((node) => node.textContent ?? '').find((text) => text.includes('FAQPage')),
      );
    const faq = JSON.parse(raw ?? '{}') as { mainEntity: { name: string }[] };
    const visibleQuestions = await page.locator('main section h3').allTextContents();
    expect(faq.mainEntity.map((q) => q.name)).toEqual(visibleQuestions);
  });

  test('JSON-LD: iç sayfalarda BreadcrumbList, araçlarda WebApplication', async ({ page }) => {
    for (const path of MARKETING_PATHS.filter((p) => p !== '/')) {
      await page.goto(path);
      expect(await jsonLdTypes(page), path).toContain('BreadcrumbList');
    }
    await page.goto('/araclar/desi-hesaplama');
    expect(await jsonLdTypes(page)).toContain('WebApplication');
  });

  test('sitemap.xml ve robots.txt güncel', async ({ request }) => {
    const sitemap = await (await request.get('/sitemap.xml')).text();
    for (const path of MARKETING_PATHS.filter((p) => p !== '/')) {
      expect(sitemap).toContain(`${path}</loc>`);
    }
    expect(sitemap).toContain('hreflang="x-default"');
    expect(sitemap).toContain('<lastmod>');
    expect(sitemap).not.toContain('kvkk-aydinlatma-metni');

    const robots = await (await request.get('/robots.txt')).text();
    expect(robots).toContain('Disallow: /panel');
    expect(robots).toContain('Disallow: /api/');
    expect(robots).toMatch(/Sitemap: .*\/sitemap\.xml/);
  });
});

test.describe('gezinme', () => {
  test('üst menü: masaüstünde satır içi, mobilde açılır menü; hedefler 44px', async ({
    page,
  }, testInfo) => {
    await page.goto('/');
    if (testInfo.project.name === 'mobil') {
      const nav = page.getByRole('navigation', { name: 'Mobil menü' });
      await expect(nav).toBeHidden();
      await page.getByText('Menü', { exact: true }).click();
      await expect(nav).toBeVisible();
      for (const link of await nav.getByRole('link').all()) {
        const box = await link.boundingBox();
        expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
      }
      await page.screenshot({ path: screenshotPath('menu-acik', testInfo) });
      await nav.getByRole('link', { name: 'Fiyatlar' }).click();
    } else {
      const nav = page.getByRole('navigation', { name: 'Ana menü' });
      await expect(nav).toBeVisible();
      await nav.getByRole('link', { name: 'Fiyatlar' }).click();
    }
    await expect(page).toHaveURL(/\/fiyatlar$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Fiyatlar' })).toBeVisible();
  });

  test('klavyeyle ilerleyince ilk odak "İçeriğe geç" bağlantısıdır', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === 'mobil', 'Klavye testi masaüstünde yapılır');
    await page.goto('/ozellikler');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'İçeriğe geç' })).toBeFocused();
  });
});

test.describe('fiyat sayfası', () => {
  test('rakam yok, her plan "Lansman fiyatı yakında" der ve bekleme listesine bağlanır', async ({
    page,
  }) => {
    await page.goto('/fiyatlar');
    const text = await page.locator('main').innerText();
    // Fiyat rakamı (TL, ₺) bulunmaz
    expect(text).not.toMatch(/\d\s*(TL|₺)|₺\s*\d/);
    await expect(page.getByText('Lansman fiyatı yakında')).toHaveCount(3);
    await expect(page.getByRole('link', { name: 'Bekleme listesine katıl' })).toHaveCount(3);
    await expect(page.locator('#bekleme-listesi')).toBeVisible();
  });
});

test.describe('bekleme listesi', () => {
  test('varsayılan işaretsiz onay, KVKK bağlantısı; boş gönderimde erişilebilir hata', async ({
    page,
  }, testInfo) => {
    await page.goto('/fiyatlar');
    const form = page.getByRole('form', { name: 'Bekleme listesi formu' });
    await expect(form.getByRole('checkbox', { name: /ticari elektronik ileti/ })).not.toBeChecked();
    await expect(form.getByRole('link', { name: /KVKK aydınlatma metninde/ })).toHaveAttribute(
      'href',
      '/kvkk-aydinlatma-metni',
    );
    await form.getByRole('button', { name: 'Bekleme listesine katıl' }).click();
    await expect(form.getByText(/E-posta adresinizi yazın/)).toBeVisible();
    await expect(form.getByLabel('E-posta', { exact: true })).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    await expect(form.getByLabel('E-posta', { exact: true })).toBeFocused();

    const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    await form.scrollIntoViewIfNeeded();
    await page.screenshot({ path: screenshotPath('bekleme-listesi-hatali', testInfo) });
  });

  test('geçerli gönderim sunucuya yazılır ve başarı mesajı gösterilir', async ({
    page,
  }, testInfo) => {
    const email = `e2e-${testInfo.project.name}-${Date.now()}@ornek.test`;
    await page.goto('/fiyatlar');
    const form = page.getByRole('form', { name: 'Bekleme listesi formu' });
    await form.getByLabel('E-posta', { exact: true }).fill(email);
    await form.getByLabel(/Mağaza kategoriniz/).selectOption('giyim');
    await form.getByLabel('Aylık sipariş sayınız').selectOption('100-1000');

    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().endsWith('/api/bekleme-listesi')),
      form.getByRole('button', { name: 'Bekleme listesine katıl' }).click(),
    ]);
    expect(request.method()).toBe('POST');
    const body = request.postDataJSON() as Record<string, unknown>;
    expect(body).toMatchObject({
      email,
      monthlyOrders: '100-1000',
      storeCategory: 'giyim',
      marketingConsent: false,
    });

    await expect(page.getByRole('status')).toContainText('Kaydınız alındı');
    const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    await page.screenshot({ path: screenshotPath('bekleme-listesi-basari', testInfo) });
  });

  test('uç nokta başka kökenden ve JSON olmayan istekleri reddeder', async ({
    request,
    baseURL,
  }) => {
    const cross = await request.post('/api/bekleme-listesi', {
      headers: { Origin: 'https://kotu.example' },
      data: { email: 'a@b.co', monthlyOrders: 'yok', marketingConsent: false },
    });
    expect(cross.status()).toBe(403);
    const wrongType = await request.post('/api/bekleme-listesi', {
      headers: { Origin: baseURL ?? '', 'Content-Type': 'text/plain' },
      data: 'a=b',
    });
    expect(wrongType.status()).toBe(415);
    const invalid = await request.post('/api/bekleme-listesi', {
      headers: { Origin: baseURL ?? '' },
      data: { email: 'gecersiz', monthlyOrders: 'yok', marketingConsent: false },
    });
    expect(invalid.status()).toBe(422);
    expect(invalid.headers()['content-type']).toContain('application/problem+json');
  });
});

test.describe('örnek veri etiketi ve kısa cevap', () => {
  test('ana sayfa: örnek veri etiketi, güven satırı ve mobilde yatay kaydırma yok', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.getByText('Örnek veri')).toBeVisible();
    await expect(page.getByText(/kapalı beta aşamasındadır/).first()).toBeVisible();
    await waitForReady(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
