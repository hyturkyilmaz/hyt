import { expect, test, type Page } from '@playwright/test';
import { randomBytes } from 'node:crypto';

import { totpCode } from './totp';

// Gerçek backend ile uçtan uca akış (sahte API yok):
// kayıt -> giriş -> panel -> çıkış -> korumalı rota -> yeniden giriş -> TOTP etkinleştirme
// -> çıkış -> giriş (ikinci adım) -> panel.
// Hesap bu çalıştırmaya özgüdür (rastgele e-posta); geçici veritabanı sonda silinir.
const suffix = randomBytes(4).toString('hex');
const EMAIL = `e2e-${suffix}@ornek.com`;
const TENANT = `E2E Mağaza ${suffix}`;
// Test parolası yalnız bu geçici veritabanı için üretilir; sabit bir sır değildir.
const PASSWORD = `e2e-${randomBytes(9).toString('hex')}-parola`;

test.describe.configure({ mode: 'serial' });

async function login(page: Page, next?: string) {
  await page.goto(next ? `/giris?sonra=${encodeURIComponent(next)}` : '/giris');
  await page.getByLabel('E-posta').fill(EMAIL);
  await page.getByLabel('Parola', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Giriş yap' }).click();
}

async function logout(page: Page) {
  await page.getByRole('button', { name: 'Çıkış yap' }).click();
  await expect(page).toHaveURL(/\/giris$/);
}

/** Tarayıcının kendi çerez kabına güvenmek için istek sayfa bağlamında atılır. */
async function browserPost(page: Page, path: string, body?: unknown) {
  return page.evaluate(
    async ({ path, body }) => {
      const csrf = /(?:^|; )__Host-nk_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? '';
      const res = await fetch(`/api/v1${path}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': decodeURIComponent(csrf),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await res.text();
      return {
        status: res.status,
        json: text ? (JSON.parse(text) as Record<string, string>) : null,
      };
    },
    { path, body },
  );
}

test('oturumsuz kullanıcı panele giremez', async ({ page }) => {
  await page.goto('/panel/ayarlar');
  await expect(page).toHaveURL(/\/giris\?sonra=%2Fpanel%2Fayarlar$/);
});

test('çerezi kurcalanmış (geçersiz) oturum API 401 ile girişe döner', async ({ page, context }) => {
  await context.addCookies([
    {
      name: '__Host-nk_session',
      value: 'sahte-oturum-degeri-0123456789abcdef',
      url: 'https://127.0.0.1:3101',
      secure: true,
    },
  ]);
  await page.goto('/panel');
  // Middleware çerezi görür (kaba kapı), panel layout'u GET /v1/me ile reddeder.
  await expect(page).toHaveURL(/\/giris\?sonra=%2Fpanel$/);
});

test('kayıt: API 202 verir, kullanıcı girişe yönlenir', async ({ page }) => {
  await page.goto('/kayit');
  await page.getByLabel('E-posta').fill(EMAIL);
  await page.getByLabel('İşletme veya mağaza adı').fill(TENANT);
  await page.getByLabel('Parola', { exact: true }).fill(PASSWORD);
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await expect(page).toHaveURL(/\/giris\?kayit=1$/);
  await expect(page.getByRole('status')).toContainText('Kaydınız alındı');
});

test('yanlış parola hesap sızdırmayan mesaj gösterir', async ({ page }) => {
  await page.goto('/giris');
  await page.getByLabel('E-posta').fill(EMAIL);
  await page.getByLabel('Parola', { exact: true }).fill('yanlis-parola-0000');
  await page.getByRole('button', { name: 'Giriş yap' }).click();
  await expect(
    page.getByRole('alert').filter({ hasText: 'E-posta veya parola hatalı' }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/giris$/);
});

test('giriş: panel açılır, işletme adı görünür, çerez bayrakları doğru', async ({
  page,
  context,
}) => {
  await login(page);
  await expect(page).toHaveURL(/\/panel$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Özet' })).toBeVisible();
  const sidebar = page.getByRole('complementary');
  await expect(sidebar.getByText(TENANT)).toBeVisible();
  await expect(sidebar.getByText(EMAIL)).toBeVisible();

  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === '__Host-nk_session');
  const csrf = cookies.find((c) => c.name === '__Host-nk_csrf');
  expect(session, 'oturum çerezi').toBeDefined();
  expect(session).toMatchObject({ httpOnly: true, secure: true, path: '/', sameSite: 'Lax' });
  expect(csrf).toMatchObject({ httpOnly: false, secure: true, path: '/' });
  // HttpOnly: JS oturum çerezini okuyamaz
  expect(await page.evaluate(() => document.cookie)).not.toContain('__Host-nk_session');
});

test('çıkış: oturum iptal olur, geri dönüşte panel girişe yönlendirir', async ({
  page,
  context,
}) => {
  await login(page);
  await expect(page).toHaveURL(/\/panel$/);
  const oldSession = (await context.cookies()).find((c) => c.name === '__Host-nk_session');
  await logout(page);
  expect((await context.cookies()).find((c) => c.name === '__Host-nk_session')).toBeUndefined();

  await page.goto('/panel');
  await expect(page).toHaveURL(/\/giris\?sonra=%2Fpanel$/);

  // Sunucu tarafında iptal: eski çerez geri konsa bile /v1/me 401 döner
  await context.addCookies([
    {
      name: '__Host-nk_session',
      value: oldSession!.value,
      url: 'https://127.0.0.1:3101',
      secure: true,
    },
  ]);
  await page.goto('/panel');
  await expect(page).toHaveURL(/\/giris\?sonra=%2Fpanel$/);
});

test('giriş sonrası sonra hedefine gider; dış adres hedefi reddedilir', async ({ page }) => {
  await login(page, '/panel/ayarlar');
  await expect(page).toHaveURL(/\/panel\/ayarlar$/);
  await logout(page);

  await login(page, 'https://evil.example/panel');
  await expect(page).toHaveURL(/127\.0\.0\.1:3101\/panel$/);
});

test('TOTP: etkinleştir, çıkış yap, ikinci adımla giriş yap', async ({ page }) => {
  await login(page);
  await expect(page).toHaveURL(/\/panel$/);

  // Arayüzde henüz TOTP kurulum ekranı yok: aynı oturum ve CSRF ile API doğrudan çağrılır.
  const setup = await browserPost(page, '/auth/totp/setup');
  expect(setup.status).toBe(200);
  const secret = setup.json?.secret ?? '';
  expect(secret).toMatch(/^[A-Z2-7]{16,}$/);
  const enable = await browserPost(page, '/auth/totp/enable', { code: totpCode(secret) });
  expect(enable.status).toBe(204);
  await logout(page);

  // Parola doğru ama TOTP açık: ikinci adım sayfası
  await login(page, '/panel/urunler');
  await expect(page).toHaveURL(/\/iki-adim\?sonra=%2Fpanel%2Furunler$/);
  await expect(page.getByRole('heading', { level: 1, name: 'İki adımlı doğrulama' })).toBeVisible();

  // Henüz oturum yok: panel hâlâ kapalı
  await page.goto('/panel');
  await expect(page).toHaveURL(/\/giris\?sonra=%2Fpanel$/);

  await login(page, '/panel/urunler');
  await expect(page).toHaveURL(/\/iki-adim\?sonra=%2Fpanel%2Furunler$/);

  // Yanlış kod
  const wrong = totpCode(secret) === '000000' ? '111111' : '000000';
  await page.getByLabel('Doğrulama kodu').fill(wrong);
  await page.getByRole('button', { name: 'Doğrula' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Kod hatalı' })).toBeVisible();

  // Doğru kod
  await page.getByLabel('Doğrulama kodu').fill(totpCode(secret));
  await page.getByRole('button', { name: 'Doğrula' }).click();
  await expect(page).toHaveURL(/\/panel\/urunler$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Ürünler' })).toBeVisible();
  await logout(page);
});
