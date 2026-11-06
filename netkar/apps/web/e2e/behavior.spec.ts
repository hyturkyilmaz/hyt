import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { screenshotPath, waitForReady } from './helpers';

test.describe('panel kabuğu', () => {
  test('mobilde alt gezinme, masaüstünde kenar çubuğu görünür', async ({ page }, testInfo) => {
    await page.goto('/panel');
    const bottom = page.getByRole('navigation', { name: 'Mobil gezinme' });
    const side = page.getByRole('navigation', { name: 'Ana gezinme' });

    if (testInfo.project.name === 'mobil') {
      await expect(bottom).toBeVisible();
      await expect(side).toBeHidden();
      // Her gezinme hedefi en az 44px
      for (const link of await bottom.getByRole('link').all()) {
        const box = await link.boundingBox();
        expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
        expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
      }
    } else {
      await expect(side).toBeVisible();
      await expect(bottom).toBeHidden();
    }
  });

  test('menü öğeleri ve geçerli sayfa işareti', async ({ page }, testInfo) => {
    await page.goto('/panel/urunler');
    const nav = page.getByRole('navigation', {
      name: testInfo.project.name === 'mobil' ? 'Mobil gezinme' : 'Ana gezinme',
    });
    for (const label of ['Özet', 'Ürünler', 'Siparişler', 'Uyarılar', 'Ayarlar']) {
      await expect(nav.getByRole('link', { name: label })).toBeVisible();
    }
    await expect(nav.getByRole('link', { name: 'Ürünler' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await nav.getByRole('link', { name: 'Siparişler' }).click();
    await expect(page).toHaveURL(/\/panel\/siparisler$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Siparişler' })).toBeVisible();
  });

  test('Ayarlar: bağlantı diyaloğu açılır, klavyeyle kapanır, axe temiz', async ({
    page,
  }, testInfo) => {
    await page.goto('/panel/ayarlar');
    await page.getByRole('button', { name: 'Trendyol mağazasını bağla' }).click();
    const dialog = page.getByRole('dialog', { name: 'Trendyol bağlantısı yakında' });
    await expect(dialog).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze();
    expect(results.violations).toEqual([]);
    await page.screenshot({ path: screenshotPath('panel-ayarlar-dialog', testInfo) });
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
  });
});

test.describe('giriş formu', () => {
  test('boş gönderimde Türkçe hata gösterir ve odak halkası görünür', async ({
    page,
  }, testInfo) => {
    await page.goto('/giris');
    await page.getByRole('button', { name: 'Giriş yap' }).click();
    await expect(page.getByText('E-posta adresinizi yazın.')).toBeVisible();
    await expect(page.getByText('Parolanızı yazın.')).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze();
    expect(results.violations).toEqual([]);
    await waitForReady(page);
    await page.screenshot({ path: screenshotPath('giris-hatali', testInfo), fullPage: true });
  });

  test('parola göster/gizle çalışır', async ({ page }) => {
    await page.goto('/giris');
    const input = page.getByLabel('Parola', { exact: true });
    await expect(input).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: 'Parolayı göster' }).click();
    await expect(input).toHaveAttribute('type', 'text');
  });

  test('API sahte yanıtıyla gönderir: CSRF başlığı eklenir, 401 hata mesajı gösterilir', async ({
    page,
    context,
  }) => {
    await context.addCookies([
      { name: 'csrf_token', value: 'e2e-token', url: 'http://127.0.0.1:3100' },
    ]);
    let seenHeader: string | undefined;
    await page.route('**/api/v1/auth/login', async (route) => {
      seenHeader = route.request().headers()['x-csrf-token'];
      await route.fulfill({
        status: 401,
        contentType: 'application/problem+json',
        body: JSON.stringify({ status: 401, title: 'Unauthorized' }),
      });
    });
    await page.goto('/giris');
    await page.getByLabel('E-posta').fill('ad@ornek.com');
    await page.getByLabel('Parola', { exact: true }).fill('yanlis-parola');
    await page.getByRole('button', { name: 'Giriş yap' }).click();
    await expect(
      page.getByRole('alert').filter({ hasText: 'E-posta veya parola hatalı' }),
    ).toBeVisible();
    expect(seenHeader).toBe('e2e-token');
  });

  test('başarılı girişte panele gider', async ({ page }) => {
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
    );
    await page.goto('/giris');
    await page.getByLabel('E-posta').fill('ad@ornek.com');
    await page.getByLabel('Parola', { exact: true }).fill('dogru-parola-123');
    await page.getByRole('button', { name: 'Giriş yap' }).click();
    await expect(page).toHaveURL(/\/panel$/);
  });
});

test.describe('parola sıfırlama', () => {
  test('geçerli token ile yeni parola formu açılır', async ({ page }) => {
    await page.goto('/sifre-sifirla?token=abcdefghijklmnop1234');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Yeni parola belirleyin' }),
    ).toBeVisible();
  });

  test('bozuk token e-posta formuna düşer', async ({ page }) => {
    await page.goto('/sifre-sifirla?token=<script>');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Parolanızı sıfırlayın' }),
    ).toBeVisible();
  });
});

test.describe('güvenlik başlıkları ve PWA', () => {
  test('CSP nonce, HSTS ve diğer başlıklar var; X-Powered-By yok', async ({ request }) => {
    const response = await request.get('/');
    const headers = response.headers();
    expect(headers['x-powered-by']).toBeUndefined();
    expect(headers['strict-transport-security']).toContain('max-age=');
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['referrer-policy']).toBe('strict-origin-when-cross-origin');
    expect(headers['permissions-policy']).toContain('camera=()');
    expect(headers['x-frame-options']).toBe('DENY');
    const csp = headers['content-security-policy'] ?? '';
    expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toContain("script-src 'self' 'unsafe-inline'");

    // Aynı nonce HTML içindeki betiklerde kullanılmalı
    const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
    const html = await response.text();
    expect(html).toContain(`nonce="${nonce}"`);
  });

  test('her istekte farklı nonce üretilir', async ({ request }) => {
    const a = (await request.get('/giris')).headers()['content-security-policy'];
    const b = (await request.get('/giris')).headers()['content-security-policy'];
    expect(a).not.toBe(b);
  });

  test('CSP ihlali olmadan sayfa çalışır (konsolda CSP hatası yok)', async ({ page }) => {
    const violations: string[] = [];
    page.on('console', (message) => {
      if (/content security policy/i.test(message.text())) violations.push(message.text());
    });
    await page.goto('/giris');
    await page.getByRole('button', { name: 'Parolayı göster' }).click();
    await page.goto('/panel/ayarlar');
    await page.getByRole('button', { name: 'Trendyol mağazasını bağla' }).click();
    await waitForReady(page);
    expect(violations).toEqual([]);
  });

  test('manifest ve ikonlar sunulur', async ({ request }) => {
    const manifest = await request.get('/manifest.webmanifest');
    expect(manifest.ok()).toBe(true);
    const json = (await manifest.json()) as {
      short_name: string;
      display: string;
      icons: { src: string }[];
    };
    expect(json.short_name).toBe('NetKâr');
    expect(json.display).toBe('standalone');
    for (const icon of json.icons) {
      const res = await request.get(icon.src);
      expect(res.ok()).toBe(true);
      expect(res.headers()['content-type']).toContain('image/svg+xml');
      expect(await res.text()).toContain('>N</text>');
    }
  });

  test('ana sayfada metadata ve JSON-LD Organization bulunur', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/NetKâr/);
    await expect(page.locator('meta[property="og:locale"]')).toHaveAttribute('content', 'tr_TR');
    await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /Trendyol/);
    const raw = await page.locator('script[type="application/ld+json"]').first().textContent();
    const data = JSON.parse(raw ?? '{}') as { '@type': string; name: string };
    expect(data['@type']).toBe('Organization');
    expect(data.name).toBe('NetKâr');
    await expect(page.getByRole('link', { name: 'Bekleme listesine katıl' })).toHaveAttribute(
      'href',
      '#bekleme-listesi',
    );
  });

  test('API proxy yolu rewrite edilir (ulaşılamayan arka uç 5xx döner, 404 değil)', async ({
    request,
  }) => {
    const res = await request.get('/api/v1/saglik');
    expect(res.status()).not.toBe(404);
  });
});
