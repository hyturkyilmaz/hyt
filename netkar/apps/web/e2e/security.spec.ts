import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { readFileSync } from 'node:fs';

import { signIn, waitForReady } from './helpers';

// Güvenlik ekranı (/panel/guvenlik): sahte API (e2e/fake-api.mjs + fake-security.mjs) auth.py sözleşmesiyle durum
// tutar; `guvenlik-<işaretler>-<ad>` oturumu hesap başına yalıtılmış bir başlangıç durumu açar (işaretler için bkz.
// fake-security.mjs). Her test kendi adını kullanır, paralel koşuda birbirini etkilemez.
// Tüm senaryolar mobil (390) ve masaüstü (1280) projelerinde koşar.
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const PATH = '/panel/guvenlik';
// Sahte API'nin kabul ettiği değerler (e2e/fake-security.mjs ile aynı olmalı; .mjs tür bildirimi olmadığından kopyalanır)
const FAKE_PASSWORD = 'Dogru-Parola-1';
const FAKE_TOTP_CODE = '482916';
const FAKE_SECRET = 'NKSAHTE2ETSECRET';
const RECOVERY_CODE = /^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/;

function sessionFor(testInfo: TestInfo, flags: string[], key: string): string {
  return ['guvenlik', ...flags, key, testInfo.project.name, String(testInfo.retry)].join('-');
}

/** Konsol iletilerini ve sayfa hatalarını toplar; gizli değerlerin sızmadığı sonda denetlenir. */
interface Watch {
  logs: string[];
}

function watch(page: Page): Watch {
  const state: Watch = { logs: [] };
  page.on('console', (message) => state.logs.push(`${message.type()}: ${message.text()}`));
  page.on('pageerror', (error) => state.logs.push(`pageerror: ${error.message}`));
  return state;
}

async function open(page: Page, testInfo: TestInfo, flags: string[], key: string) {
  const state = watch(page);
  await signIn(page.context(), sessionFor(testInfo, flags, key));
  await page.goto(PATH);
  await expect(page.getByRole('heading', { level: 1, name: 'Güvenlik' })).toBeVisible();
  return state;
}

async function expectClean(page: Page) {
  await waitForReady(page);
  // Bildirim (sonner) belirirken saydamlık animasyonu sürer; o anda kontrast yanlış ölçülür. Animasyon bitince
  // sonuç oturur: kalıcı bir ihlal zaman aşımına kadar sürer ve test yine başarısız olur.
  await expect
    .poll(
      async () => {
        const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
        return results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} düğüm)`);
      },
      { timeout: 5000, intervals: [100, 250, 500] },
    )
    .toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

/** Gizli değerler (anahtar, kurtarma kodları, parola, kod) adreste, konsolda ve tarayıcı depolarında yok. */
async function expectNoLeaks(page: Page, watcher: Watch, secrets: string[]) {
  const url = decodeURIComponent(page.url());
  const stores = await page.evaluate(() => ({
    local: JSON.stringify({ ...localStorage }),
    session: JSON.stringify({ ...sessionStorage }),
    cookie: document.cookie,
  }));
  const haystacks = [url, watcher.logs.join('\n'), stores.local, stores.session, stores.cookie];
  for (const secret of secrets) {
    for (const haystack of haystacks) expect(haystack).not.toContain(secret);
  }
  // Adres sade kalır: sorgu ve parça yok
  const parsed = new URL(page.url());
  expect(parsed.search).toBe('');
  expect(parsed.hash).toBe('');
}

const card = (page: Page) => page.getByRole('region', { name: 'İki adımlı doğrulama' });

async function startSetup(page: Page, password = FAKE_PASSWORD) {
  await page.getByRole('button', { name: 'Kurulumu başlat' }).click();
  await expect(page.getByRole('heading', { name: '1. Parolanızı doğrulayın' })).toBeVisible();
  await page.getByLabel('Güncel parola').fill(password);
  await page.getByRole('button', { name: 'Devam et' }).click();
}

async function readCodes(page: Page): Promise<string[]> {
  const items = page.getByRole('list', { name: 'Kurtarma kodları' }).getByRole('listitem');
  await expect(items).toHaveCount(10);
  return (await items.allTextContents()).map((text) => text.trim());
}

test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

test.describe('güvenlik: iki adımlı doğrulama kurulumu', () => {
  test('kapalı hesap: parola, QR ve anahtar, kod, 10 kurtarma kodu, kopyala ve indir', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, [], 'kurulum');
    await expect(card(page).getByRole('status')).toHaveText('Kapalı');
    await expectClean(page);

    // 1. adım: parola
    await page.getByRole('button', { name: 'Kurulumu başlat' }).click();
    await expect(page.getByRole('heading', { name: '1. Parolanızı doğrulayın' })).toBeFocused();
    await expectClean(page);
    await page.getByLabel('Güncel parola').fill(FAKE_PASSWORD);
    await page.getByRole('button', { name: 'Devam et' }).click();

    // 2. adım: QR ve elle giriş anahtarı
    await expect(
      page.getByRole('heading', { name: '2. Doğrulama uygulamasına ekleyin' }),
    ).toBeFocused();
    await expect(page.getByRole('img', { name: /İki adımlı doğrulama QR kodu/ })).toBeVisible();
    await expect(page.getByText(FAKE_SECRET, { exact: true })).toBeVisible();
    await expectClean(page);

    // Anahtarı kopyala
    await page.getByRole('button', { name: 'Kopyala' }).click();
    await expect(page.getByRole('button', { name: 'Kopyalandı' })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(FAKE_SECRET);

    // Kod gir, etkinleştir
    await page.getByLabel('Uygulamadaki 6 haneli kod').fill(FAKE_TOTP_CODE);
    await page.getByRole('button', { name: 'Doğrula ve etkinleştir' }).click();

    // 3. adım: kurtarma kodları (bir kez)
    const heading = page.getByRole('heading', { name: 'Kurtarma kodlarınızı kaydedin' });
    await expect(heading).toBeFocused();
    const codes = await readCodes(page);
    expect(new Set(codes).size).toBe(10);
    for (const code of codes) expect(code).toMatch(RECOVERY_CODE);
    await expect(page.getByText('Bu kodlar bir daha gösterilmez.')).toBeVisible();
    await expectClean(page);

    // Kaydettim denmeden "Bitti" kapalıdır
    const done = page.getByRole('button', { name: 'Bitti' });
    await expect(done).toBeDisabled();

    // Kopyala: pano içeriği tüm kodlar, satır satır
    await page.getByRole('button', { name: 'Kopyala' }).click();
    await expect(page.getByRole('button', { name: 'Kopyalandı' })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(codes.join('\n'));

    // İndir: dosya adı ve içerik
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Dosya olarak indir' }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe('netkar-kurtarma-kodlari.txt');
    const filePath = await download.path();
    const text = readFileSync(filePath, 'utf8');
    for (const code of codes) expect(text).toContain(code);
    expect(text).toContain('NetKâr kurtarma kodları');

    // Onay kutusu ile "Bitti" açılır
    await page.getByLabel('Kodları güvenli bir yere kaydettim').check();
    await expect(done).toBeEnabled();
    await done.click();

    // Durum açık; sunucudan gelen sayı 10
    await expect(card(page).getByRole('status')).toHaveText('Açık');
    await expect(page.getByText(/Kalan kurtarma kodu:/)).toContainText('10');
    await expect(page.getByRole('list', { name: 'Kurtarma kodları' })).toHaveCount(0);
    await expectClean(page);

    // Yenilemede kodlar bir daha gösterilmez, sunucu durumu açık kalır
    await page.reload();
    await expect(card(page).getByRole('status')).toHaveText('Açık');
    await expect(page.getByRole('list', { name: 'Kurtarma kodları' })).toHaveCount(0);

    await expectNoLeaks(page, watcher, [FAKE_SECRET, FAKE_PASSWORD, FAKE_TOTP_CODE, ...codes]);
  });

  test('yanlış parola ve yanlış kod anlaşılır hata verir, istemci doğrulaması boş ve kısa kodu yakalar', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, [], 'yanlis');

    // Yanlış parola (403 reauth-failed)
    await startSetup(page, 'Yanlis-Parola-9');
    const alert = page.getByRole('alert').filter({ hasText: 'Parola hatalı' });
    await expect(alert).toContainText('Güncel parolanızı yazın.');
    await expectClean(page);

    // Boş parola istemcide yakalanır, istek gitmez
    await page.getByLabel('Güncel parola').fill('');
    await page.getByRole('button', { name: 'Devam et' }).click();
    await expect(page.getByText('Güncel parolanızı yazın.').first()).toBeVisible();

    // Doğru parola: kod adımı
    await page.getByLabel('Güncel parola').fill(FAKE_PASSWORD);
    await page.getByRole('button', { name: 'Devam et' }).click();
    await expect(
      page.getByRole('heading', { name: '2. Doğrulama uygulamasına ekleyin' }),
    ).toBeVisible();

    // Kısa/yanlış biçimli kod istemcide yakalanır
    const code = page.getByLabel('Uygulamadaki 6 haneli kod');
    await code.fill('12ab');
    await page.getByRole('button', { name: 'Doğrula ve etkinleştir' }).click();
    await expect(page.getByText('Kod 6 haneli olmalı ve yalnız rakam içermeli.')).toBeVisible();
    await code.fill('');
    await page.getByRole('button', { name: 'Doğrula ve etkinleştir' }).click();
    await expect(page.getByText('Doğrulama kodunu yazın.')).toBeVisible();

    // Biçimi doğru ama yanlış kod: sunucu 403 invalid-code
    await code.fill('000000');
    await page.getByRole('button', { name: 'Doğrula ve etkinleştir' }).click();
    const wrong = page.getByRole('alert').filter({ hasText: 'Kod hatalı' });
    await expect(wrong).toContainText('güncel kodu');
    // Hata sonrası kullanıcı aynı adımda kalır, anahtar hâlâ görünür
    await expect(page.getByText(FAKE_SECRET, { exact: true })).toBeVisible();
    await expectClean(page);

    // Vazgeç: başa döner
    await page.getByRole('button', { name: 'Vazgeç' }).click();
    await expect(page.getByRole('button', { name: 'Kurulumu başlat' })).toBeVisible();
    await expect(card(page).getByRole('status')).toHaveText('Kapalı');

    await expectNoLeaks(page, watcher, [FAKE_SECRET, FAKE_PASSWORD]);
  });

  test('kurtarma kodları ekranındayken sayfa yenileme tarayıcı uyarısı verir ve kodlar kalıcı olmaz', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, [], 'uyari');
    await startSetup(page);
    await page.getByLabel('Uygulamadaki 6 haneli kod').fill(FAKE_TOTP_CODE);
    await page.getByRole('button', { name: 'Doğrula ve etkinleştir' }).click();
    const codes = await readCodes(page);

    const dialogs: string[] = [];
    page.on('dialog', (dialog) => {
      dialogs.push(dialog.type());
      void dialog.accept();
    });
    await page.reload();
    expect(dialogs).toContain('beforeunload');
    await expect(card(page).getByRole('status')).toHaveText('Açık');
    await expect(page.getByRole('list', { name: 'Kurtarma kodları' })).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(codes[0] ?? 'yok');

    await expectNoLeaks(page, watcher, [FAKE_SECRET, FAKE_PASSWORD, ...codes]);
  });
});

test.describe('güvenlik: iki adım açık hesap', () => {
  test('kurtarma kodları azaldığında uyarı çıkar; yenileme güncel TOTP kodu ister ve 10 yeni kod verir', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, ['acik', 'az'], 'yenile');
    await expect(card(page).getByRole('status')).toHaveText('Açık');
    await expect(page.getByRole('alert').filter({ hasText: 'Kalan kurtarma kodu' })).toContainText(
      'kodlarınız azaldı',
    );
    await expectClean(page);

    await page.getByRole('button', { name: 'Kurtarma kodlarını yenile' }).click();
    await expect(page.getByRole('heading', { name: 'Kurtarma kodlarını yenile' })).toBeFocused();
    // Yenilemede kurtarma kodu kabul edilmez: etiket ve açıklama bunu söyler
    await expect(page.getByLabel('Doğrulama uygulaması kodu')).toBeVisible();
    await expect(page.getByText('kurtarma kodu burada kabul edilmez')).toBeVisible();
    await expectClean(page);

    // Kurtarma kodu biçimi istemcide reddedilir (yalnız 6 hane)
    await page.getByLabel('Güncel parola').fill(FAKE_PASSWORD);
    await page.getByLabel('Doğrulama uygulaması kodu').fill('ABCD-EFGH');
    await page.getByRole('button', { name: 'Yeni kodlar üret' }).click();
    await expect(page.getByText('Kod 6 haneli olmalı ve yalnız rakam içermeli.')).toBeVisible();

    // Yanlış kod
    await page.getByLabel('Doğrulama uygulaması kodu').fill('000000');
    await page.getByRole('button', { name: 'Yeni kodlar üret' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Kod hatalı' })).toBeVisible();

    // Yanlış parola
    await page.getByLabel('Güncel parola').fill('Yanlis-Parola-9');
    await page.getByLabel('Doğrulama uygulaması kodu').fill(FAKE_TOTP_CODE);
    await page.getByRole('button', { name: 'Yeni kodlar üret' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Parola hatalı' })).toBeVisible();

    // Doğru parola ve kod
    await page.getByLabel('Güncel parola').fill(FAKE_PASSWORD);
    await page.getByLabel('Doğrulama uygulaması kodu').fill(FAKE_TOTP_CODE);
    await page.getByRole('button', { name: 'Yeni kodlar üret' }).click();
    await expect(
      page.getByRole('heading', { name: 'Kurtarma kodlarınızı kaydedin' }),
    ).toBeFocused();
    const codes = await readCodes(page);
    for (const code of codes) expect(code).toMatch(RECOVERY_CODE);
    await expectClean(page);

    await page.getByLabel('Kodları güvenli bir yere kaydettim').check();
    await page.getByRole('button', { name: 'Bitti' }).click();
    // Sayı 2'den 10'a çıkar, düşük kod uyarısı kalkar
    await expect(page.getByText(/Kalan kurtarma kodu:/)).toContainText('10');
    await expect(card(page).getByRole('alert')).toHaveCount(0);

    await expectNoLeaks(page, watcher, [FAKE_PASSWORD, FAKE_TOTP_CODE, ...codes]);
  });

  test('kapatma parola ve kod ister; yanlış girdide hesap açık kalır, doğru girdide kapanır', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, ['acik'], 'kapat');
    await page.getByRole('button', { name: 'İki adımlı doğrulamayı kapat' }).click();
    await expect(page.getByRole('heading', { name: 'İki adımlı doğrulamayı kapat' })).toBeFocused();
    await expect(page.getByLabel('Doğrulama ya da kurtarma kodu')).toBeVisible();
    await expectClean(page);

    // Boş gönderim istemcide yakalanır
    await page.getByRole('button', { name: 'Doğrulamayı kapat' }).click();
    await expect(page.getByText('Güncel parolanızı yazın.')).toBeVisible();
    await expect(page.getByText('Kodu yazın.')).toBeVisible();

    // Yanlış kod: hesap açık kalır
    await page.getByLabel('Güncel parola').fill(FAKE_PASSWORD);
    await page.getByLabel('Doğrulama ya da kurtarma kodu').fill('000000');
    await page.getByRole('button', { name: 'Doğrulamayı kapat' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Kod hatalı' })).toBeVisible();
    await expectClean(page);

    // Doğru parola + kod: kapanır
    await page.getByLabel('Doğrulama ya da kurtarma kodu').fill(FAKE_TOTP_CODE);
    await page.getByRole('button', { name: 'Doğrulamayı kapat' }).click();
    await expect(card(page).getByRole('status')).toHaveText('Kapalı');
    await expect(page.getByRole('button', { name: 'Kurulumu başlat' })).toBeVisible();
    await expectClean(page);

    // Sunucu durumu kalıcıdır
    await page.reload();
    await expect(card(page).getByRole('status')).toHaveText('Kapalı');

    await expectNoLeaks(page, watcher, [FAKE_PASSWORD, FAKE_TOTP_CODE]);
  });
});

test.describe('güvenlik: hata durumları', () => {
  test('e-postası doğrulanmamış hesapta kurulum engellenir ve nedeni söylenir (403 email-not-verified)', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, ['dogrulanmamis'], 'eposta');
    await expect(page.getByRole('region', { name: 'E-posta doğrulama uyarısı' })).toBeVisible();
    await startSetup(page);
    const alert = page
      .getByRole('alert')
      .filter({ hasText: 'e-posta adresinizi doğrulamanız gerekir' });
    await expect(alert).toBeVisible();
    // Yanlış parola mesajına çevrilmez; kullanıcı parola formunda kalır
    await expect(page.getByText('Parola hatalı')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '1. Parolanızı doğrulayın' })).toBeVisible();
    await expectClean(page);
    await expectNoLeaks(page, watcher, [FAKE_PASSWORD]);
  });

  test('günlük yeniden doğrulama sınırı (429 rate-limited) kurulumda anlaşılır mesaj verir', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, ['gunluk'], 'gunluk');
    await startSetup(page);
    const alert = page.getByRole('alert').filter({ hasText: 'Çok fazla deneme' });
    await expect(alert).toBeVisible();
    // Parola formunda kalır, parola alanı doldurulmuş değil hatalı sanılmaz
    await expect(page.getByText('Parola hatalı')).toHaveCount(0);
    await expectClean(page);
    await expectNoLeaks(page, watcher, [FAKE_PASSWORD]);
  });

  test('sayaç servisi yoğunken (503 rate-limit-busy) kapatma "sorun oluştu, tekrar deneyin" der', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, ['acik', 'yogun'], 'yogun');
    await page.getByRole('button', { name: 'İki adımlı doğrulamayı kapat' }).click();
    await page.getByLabel('Güncel parola').fill(FAKE_PASSWORD);
    await page.getByLabel('Doğrulama ya da kurtarma kodu').fill(FAKE_TOTP_CODE);
    await page.getByRole('button', { name: 'Doğrulamayı kapat' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Bir sorun oluştu' })).toContainText(
      'tekrar deneyin',
    );
    // Hesap açık kalır
    await expect(card(page).getByRole('status')).toHaveText('Açık');
    await expectClean(page);
    await expectNoLeaks(page, watcher, [FAKE_PASSWORD, FAKE_TOTP_CODE]);
  });

  test('ikinci faktör kilidi (429 totp-locked) bekleme süresini dakika olarak söyler', async ({
    page,
  }, testInfo) => {
    const watcher = await open(page, testInfo, ['acik', 'kilit'], 'kilit');
    await page.getByRole('button', { name: 'Kurtarma kodlarını yenile' }).click();
    await page.getByLabel('Güncel parola').fill(FAKE_PASSWORD);
    await page.getByLabel('Doğrulama uygulaması kodu').fill(FAKE_TOTP_CODE);
    await page.getByRole('button', { name: 'Yeni kodlar üret' }).click();
    await expect(
      page.getByRole('alert').filter({ hasText: 'Çok fazla hatalı deneme' }),
    ).toContainText('Yaklaşık 15 dakika sonra tekrar deneyin');
    await expectClean(page);
    await expectNoLeaks(page, watcher, [FAKE_PASSWORD, FAKE_TOTP_CODE]);
  });
});
