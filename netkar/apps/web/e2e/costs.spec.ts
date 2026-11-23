import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { makeAlerts } from '../src/lib/profit/test-fixtures';
import { signIn, waitForReady } from './helpers';

// Ürün maliyetleri (/panel/maliyetler): sahte API (e2e/fake-api.mjs + fake-costs.mjs) GERÇEK sözleşme ve
// doğrulama kurallarıyla durum tutar; `maliyet-<ad>` oturumu hesap başına yalıtılmış bir tohum veri açar.
// Her test kendi adını kullanır (paralel koşuda birbirini etkilemez). Ekran görüntüleri yalnız PW_SHOTS_DIR
// verilirse yazılır (docs/ux/ekranlar altındaki kayıtlı görüntülere dokunulmaz).
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

function sessionFor(testInfo: TestInfo, key: string, prefix = ''): string {
  return `maliyet-${prefix}${key}-${testInfo.project.name}-${testInfo.retry}`;
}

async function open(page: Page, testInfo: TestInfo, key: string, path = '/panel/maliyetler') {
  await signIn(page.context(), sessionFor(testInfo, key));
  await page.goto(path);
  await expect(page.getByRole('heading', { level: 1, name: 'Ürün maliyetleri' })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Ürün maliyetleri' })).toBeVisible();
}

async function shot(page: Page, name: string, testInfo: TestInfo) {
  const dir = process.env.PW_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const device = testInfo.project.name === 'mobil' ? 'mobil-390' : 'masaustu-1280';
  await page.screenshot({ path: join(dir, `${name}-${device}.png`), fullPage: true });
}

async function expectClean(page: Page) {
  await waitForReady(page);
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} düğüm)`)).toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

const rowOf = (page: Page, title: string) =>
  page
    .getByRole('listitem')
    .filter({ hasText: title })
    .filter({ has: page.getByRole('button') });

const CSV_HEADER = 'barkod;birim_maliyet_kdv_haric;kdv_orani;gecerlilik_tarihi';

async function chooseFile(page: Page, name: string, content: string) {
  await page
    .getByLabel(/Maliyet dosyası/)
    .setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(content, 'utf8') });
}

test.describe('ürün maliyetleri', () => {
  test('liste: maliyetli ve eksik ürünler ayırt edilir, axe 0', async ({ page }, testInfo) => {
    await open(page, testInfo, 'liste');
    const termos = rowOf(page, 'Çelik Termos 500 ml');
    await expect(termos).toContainText('54,50');
    await expect(termos).toContainText('%20 KDV');
    await expect(termos).toContainText('1 Eylül 2026 tarihinden beri geçerli');
    const matara = rowOf(page, 'Cam Matara 1 L');
    await expect(matara).toContainText('Maliyet yok');
    await expect(matara.getByRole('button', { name: /Maliyet gir/ })).toBeVisible();
    // Ürün başlığındaki HTML yorumlanmaz
    await expect(page.getByText('<b>Kalın</b> Bardak', { exact: true })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Ürün süzgeci' })).toBeVisible();
    await shot(page, 'panel-maliyetler', testInfo);
    await expectClean(page);
  });

  test('süzgeç: "Maliyeti eksik" yalnız eksik ürünleri bırakır, arama çalışır', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'suzgec', '/panel/maliyetler?filtre=eksik');
    const list = page.getByRole('list', { name: 'Ürün maliyetleri' });
    // Tohum veride 6 ürünün 3'ünün maliyeti yok (BRK-0002, BRK-0005, BRK-0006)
    await expect(list.getByRole('listitem')).toHaveCount(3);
    // Süzgeç sunucuda (missing=true); toplam eksik sayısı yanıttaki total_missing değeridir
    await expect(page.getByTestId('total-missing')).toContainText('Toplam 3 ürünün maliyeti eksik');
    await expect(list).not.toContainText('Çelik Termos');
    await expect(page.getByRole('link', { name: 'Maliyeti eksik' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    await expectClean(page);
    await page.getByRole('link', { name: 'Tüm ürünler' }).click();
    await expect(page).toHaveURL(/\/panel\/maliyetler$/);
    await expect(list.getByRole('listitem')).toHaveCount(6);
    await page.getByRole('searchbox', { name: 'Barkod ya da ürün adı ara' }).fill('spatula');
    await page.getByRole('button', { name: 'Ara', exact: true }).click();
    await expect(page).toHaveURL(/q=spatula/);
    await expect(list.getByRole('listitem')).toHaveCount(1);
    await expect(list).toContainText('Silikon Spatula Seti');
  });

  test('uyarı eylemi "Maliyeti eksik ürünleri gör" maliyet ekranına süzgeçle iner', async ({
    page,
  }, testInfo) => {
    await page.route('**/api/v1/marketplace-accounts/*/profit/alerts*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          makeAlerts([{ code: 'MALIYET_EKSIK', count: 2, message: 'sistem metni' }]),
        ),
      }),
    );
    await signIn(page.context(), sessionFor(testInfo, 'uyari'));
    await page.goto('/panel/uyarilar?sekme=donem');
    await page.getByRole('link', { name: 'Maliyeti eksik ürünleri gör' }).click();
    await expect(page).toHaveURL(/\/panel\/maliyetler\?filtre=eksik$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Ürün maliyetleri' })).toBeVisible();
    await expect(page.getByRole('list', { name: 'Ürün maliyetleri' })).toContainText(
      'Cam Matara 1 L',
    );
  });

  test('tek ürün: maliyet girilir, yansıma görünür, satır ve kayıt güncellenir', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'tek');
    await page.getByRole('button', { name: /Maliyet gir\s?: Cam Matara/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Maliyet gir' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('Bu ürün için henüz maliyet girilmedi.')).toBeVisible();
    await dialog.getByLabel(/Birim maliyet/).fill('1.250,5');
    await expect(dialog.getByText(/Kaydedilecek: 1\.250,50.TL KDV hariç, %20 KDV/)).toBeVisible();
    await dialog.getByRole('radio', { name: '%10' }).check();
    await expect(dialog.getByText(/%10 KDV/).first()).toBeVisible();
    await shot(page, 'panel-maliyetler-form', testInfo);
    await expectClean(page);
    await dialog.getByRole('button', { name: 'Kaydet' }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('status').filter({ hasText: 'maliyet eklendi' })).toContainText(
      'Cam Matara 1 L: maliyet eklendi. Kâr rakamları güncellenir.',
    );
    const row = rowOf(page, 'Cam Matara 1 L');
    await expect(row).toContainText('1.250,50');
    await expect(row).toContainText('%10 KDV');
    await expect(row).not.toContainText('Maliyet yok');
    await expect(row.getByRole('button', { name: /Düzenle\s?: Cam Matara/ })).toBeVisible();
    // Sunucuda kalıcı: sayfa yenilenince de görünür
    await page.reload();
    await expect(rowOf(page, 'Cam Matara 1 L')).toContainText('1.250,50');
    await expectClean(page);
  });

  test('düzenleme: aynı tarihli kayıt düzeltilir, geçmiş listelenir', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'duzenle');
    await page.getByRole('button', { name: /Düzenle\s?: Çelik Termos/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Maliyeti düzenle' });
    await expect(dialog.getByLabel(/Birim maliyet/)).toHaveValue('54,50');
    await expect(dialog.getByText(/48,00.*KDV hariç, %20 KDV/)).toBeVisible();
    await dialog.getByRole('radio', { name: /Mevcut kaydı düzelt/ }).check();
    await expect(dialog.getByText(/Düzeltilecek kayıt: 1 Eylül 2026/)).toBeVisible();
    await expectClean(page);
    await dialog.getByLabel(/Birim maliyet/).fill('57');
    await dialog.getByRole('button', { name: 'Kaydet' }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('status').filter({ hasText: 'güncellendi' })).toContainText(
      'maliyet güncellendi',
    );
    await expect(rowOf(page, 'Çelik Termos 500 ml')).toContainText('57,00');
  });

  test('doğrulama: belirsiz tutar gönderilmez, hata alanın yanında ve axe 0', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'dogrulama');
    let puts = 0;
    page.on('request', (r) => {
      if (r.method() === 'PUT') puts += 1;
    });
    await page.getByRole('button', { name: /Maliyet gir\s?: Cam Matara/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Maliyet gir' });
    const input = dialog.getByLabel(/Birim maliyet/);
    await input.fill('12.5');
    await expect(dialog.getByText(/Okunamadı: ondalık için virgül yazın/)).toBeVisible();
    await dialog.getByRole('button', { name: 'Kaydet' }).click();
    await expect(dialog.getByText(/Ondalık için virgül kullanın/)).toBeVisible();
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await shot(page, 'panel-maliyetler-hata', testInfo);
    await expectClean(page);
    await input.fill('0');
    await dialog.getByRole('button', { name: 'Kaydet' }).click();
    await expect(dialog.getByText("Maliyet 0'dan büyük olmalı.")).toBeVisible();
    expect(puts).toBe(0);
  });

  test('sunucu 422 kodları alanın yanında Türkçe gösterilir (istek gövdesi doğru)', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'sunucu422');
    let body: unknown = null;
    await page.route('**/api/v1/marketplace-accounts/*/products/*/costs', async (route) => {
      if (route.request().method() !== 'PUT') return route.fallback();
      body = route.request().postDataJSON();
      return route.fulfill({
        status: 422,
        contentType: 'application/problem+json',
        body: JSON.stringify({
          type: 'urn:netkar:problem:validation-error',
          title: 'Doğrulama hatası',
          status: 422,
          errors: [
            { field: 'unit_cost_excl_vat', code: 'cost_too_large' },
            { field: 'vat_rate', code: 'vat_rate_invalid' },
          ],
        }),
      });
    });
    await page.getByRole('button', { name: /Maliyet gir\s?: Cam Matara/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Maliyet gir' });
    await dialog.getByLabel(/Birim maliyet/).fill('54,50');
    await dialog.getByRole('button', { name: 'Kaydet' }).click();
    await expect(dialog.getByText('Maliyet en çok 10.000.000 TL olabilir.')).toBeVisible();
    await expect(dialog.getByText('KDV oranı yüzde 0, 1, 10 ya da 20 olmalı.')).toBeVisible();
    expect(body).toMatchObject({ unit_cost_excl_vat: '54.50', vat_rate: '20' });
    expect(Object.keys(body as object).sort()).toEqual([
      'unit_cost_excl_vat',
      'valid_from',
      'vat_rate',
    ]);
    await expectClean(page);
  });

  test('toplu yükleme: kuru deneme raporu hatalı satırı gösterir, yalnız geçerliler kaydedilir', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'toplu');
    await expect(page.getByRole('button', { name: /Şablonu indir/ })).toBeVisible();
    await chooseFile(
      page,
      'maliyet.csv',
      [
        CSV_HEADER,
        'BRK-0002;54,50;20;',
        'BRK-0004;40;18;',
        'BRK-0005;1.250,00;10;01.11.2026',
        'BRK-9999;12,5;1;',
        'BRK-0006;;;',
      ].join('\n'),
    );
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    const report = page.getByRole('region', { name: 'Dosya raporu' });
    await expect(page.getByRole('status').filter({ hasText: 'Kontrol tamam' })).toContainText(
      'Kontrol tamam, henüz kaydedilmedi.',
    );
    await expect(
      page.getByRole('region', { name: 'Toplu maliyet yükle' }).getByRole('status'),
    ).toContainText('1 satırda hata var, 3 satır geçerli.');
    await expect(report).toBeFocused();
    const errors = report.getByRole('list', { name: 'Satır hataları' });
    await expect(errors.getByRole('listitem')).toHaveCount(1);
    await expect(errors).toContainText('Satır 3, KDV oranı');
    await expect(errors).toContainText('KDV oranı yüzde olarak 0, 1, 10 veya 20 olmalıdır');
    await expect(errors).toContainText('Girilen: 18');
    await expect(report).toContainText('1 barkod ürün listenizde yok');
    // Kuru denemede hiçbir şey yazılmadı
    await expect(rowOf(page, 'Cam Matara 1 L')).toContainText('Maliyet yok');
    await expect(page.getByRole('button', { name: /^\d+ satırı kaydet$/ })).toHaveCount(0);
    await shot(page, 'panel-maliyetler-onizleme', testInfo);
    await expectClean(page);

    await page.getByRole('button', { name: 'Yalnız geçerli 3 satırı kaydet' }).click();
    await expect(
      page.getByText(/Kaydedildi\. 3 yeni maliyet eklendi, 0 maliyet güncellendi\./),
    ).toBeVisible();
    // Liste yenilendi: eklenen maliyetler satırlarda
    await expect(rowOf(page, 'Cam Matara 1 L')).toContainText('54,50');
    await expect(rowOf(page, 'Cam Matara 1 L')).not.toContainText('Maliyet yok');
    await expect(rowOf(page, 'Kalın')).toContainText('1.250,00');
    await expect(rowOf(page, 'Silikon Spatula')).toContainText('35,90');
    await expectClean(page);
  });

  test('toplu yükleme: hatasız dosya "N satırı kaydet" ile uygulanır', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'toplutemiz');
    await chooseFile(
      page,
      'temiz.csv',
      [CSV_HEADER, 'BRK-0002;54,50;20;', 'BRK-0001;57;20;'].join('\n'),
    );
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    await expect(
      page.getByRole('region', { name: 'Toplu maliyet yükle' }).getByRole('status'),
    ).toContainText('2 satır kaydedilmeye hazır.');
    await page.getByRole('button', { name: '2 satırı kaydet' }).click();
    await expect(page.getByText(/2 yeni maliyet eklendi, 0 maliyet güncellendi/)).toBeVisible();
    await expect(rowOf(page, 'Cam Matara 1 L')).toContainText('54,50');
    // Aynı barkod ve tarih tekrar yüklenince "güncellendi" sayılır
    await page.getByRole('button', { name: 'Başka dosya yükle' }).click();
    await chooseFile(page, 'tekrar.csv', [CSV_HEADER, 'BRK-0002;60;20;'].join('\n'));
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    await page.getByRole('button', { name: '1 satırı kaydet' }).click();
    await expect(page.getByText(/0 yeni maliyet eklendi, 1 maliyet güncellendi/)).toBeVisible();
    await expect(rowOf(page, 'Cam Matara 1 L')).toContainText('60,00');
  });

  test('toplu yükleme: dosya düzeyi hatalar Türkçe ve yeniden denenebilir', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'dosyahata');
    // İstemci denetimi: uzantı
    await page.getByLabel(/Maliyet dosyası/).setInputFiles({
      name: 'notlar.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('x'),
    });
    await expect(page.getByText('Yalnız .csv veya .xlsx dosyası yüklenebilir.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Dosyayı kontrol et' })).toBeDisabled();
    // Sunucu: zorunlu sütun yok
    await chooseFile(page, 'eksik-sutun.csv', 'barkod;birim_maliyet_kdv_haric\nBRK-0002;54,50\n');
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Dosya okunamadı.' })).toContainText(
      'Zorunlu sütun(lar) bulunamadı: kdv_orani.',
    );
    await expectClean(page);
    // Sunucu: hız sınırı
    await chooseFile(page, 'hiz-siniri.csv', [CSV_HEADER, 'BRK-0002;54,50;20;'].join('\n'));
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    await expect(
      page.getByRole('alert').filter({ hasText: 'çok fazla içe aktarma' }),
    ).toContainText('57 dakika sonra tekrar deneyin.');
    // Sunucu: 2 MB üstü (istemci denetimi atlanamaz; boyut sahte nesneyle değil gerçek içerikle)
    await page.getByLabel(/Maliyet dosyası/).setInputFiles({
      name: 'cok-buyuk.csv',
      mimeType: 'text/csv',
      buffer: Buffer.alloc(2 * 1024 * 1024 + 10, 'a'),
    });
    await expect(page.getByText(/Dosya en fazla 2 MB olabilir/)).toBeVisible();
  });

  test('toplu yükleme: XLSX kapalıysa CSV önerilir, süren içe aktarma ayrı anlatılır', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'ayrikodlar');
    await page.getByLabel(/Maliyet dosyası/).setInputFiles({
      name: 'maliyet.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('PK\u0003\u0004x'),
    });
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'XLSX içe aktarma' })).toContainText(
      'Dosyanızı CSV olarak kaydedip yükleyin.',
    );
    await chooseFile(page, 'devam-ediyor.csv', [CSV_HEADER, 'BRK-0002;54,50;20;'].join('\n'));
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'zaten sürüyor' })).toContainText(
      '5 saniye sonra tekrar deneyin.',
    );
    await expectClean(page);
  });

  test('şablon: sunucu hatası ve kesilme uyarısı kullanıcıya söylenir', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'sablon-429');
    await page.getByRole('button', { name: /Şablonu indir/ }).click();
    await expect(
      page.getByRole('alert').filter({ hasText: 'Şablon indirme sınırına' }),
    ).toContainText('30 dakika sonra tekrar deneyin.');
    await expectClean(page);
  });

  test('şablon: X-Template-Truncated başlığı okunur, eksik şablon uyarılır', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'sablon-kesik');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: /Şablonu indir/ }).click(),
    ]);
    expect(download.suggestedFilename()).toBe('maliyet_sablonu.csv');
    await expect(
      page.getByRole('note').filter({ hasText: 'Şablon ilk 10.000 ürünle sınırlı' }),
    ).toBeVisible();
    await expectClean(page);
  });

  test('desen dışı barkodlu üründe düğme yerine açıklama çıkar', async ({ page }, testInfo) => {
    await open(page, testInfo, 'desenli');
    const row = page.getByRole('listitem').filter({ hasText: 'Çay Bardağı' });
    await expect(row).toContainText('Bu barkod biçimi maliyet girişinde desteklenmiyor');
    await expect(row.getByRole('button')).toHaveCount(0);
    await expectClean(page);
  });

  test('şablon indirilir: sütunlar ve hesabın ürünleri dolu', async ({ page }, testInfo) => {
    await open(page, testInfo, 'sablon');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: /Şablonu indir/ }).click(),
    ]);
    expect(download.suggestedFilename()).toBe('maliyet_sablonu.csv');
    const path = await download.path();
    const text = readFileSync(path, 'utf8');
    expect(text.charCodeAt(0)).toBe(0xfeff);
    expect(text).toContain(
      '"barkod";"baslik";"birim_maliyet_kdv_haric";"kdv_orani";"gecerlilik_tarihi"',
    );
    expect(text).toContain('"BRK-0002";"Cam Matara 1 L";"";"";""');
  });

  test('görüntüleyici: yalnız okur, düğme ve toplu yükleme yok', async ({ page }, testInfo) => {
    await signIn(page.context(), sessionFor(testInfo, 'okur', 'goruntuleyici-'));
    await page.goto('/panel/maliyetler');
    await expect(page.getByRole('list', { name: 'Ürün maliyetleri' })).toBeVisible();
    await expect(page.getByRole('note')).toContainText('yalnız okuyabilir');
    await expect(page.getByRole('button', { name: /Maliyet gir|Düzenle/ })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Toplu maliyet yükle' })).toHaveCount(0);
    await expectClean(page);
  });

  test('menüde Ürünler etkin kalır, ürünler ekranından maliyete gidilir', async ({
    page,
  }, testInfo) => {
    await open(page, testInfo, 'menu');
    const nav = testInfo.project.name === 'mobil' ? 'Mobil gezinme' : 'Ana gezinme';
    await expect(
      page.getByRole('navigation', { name: nav }).getByRole('link', { name: 'Ürünler' }),
    ).toHaveAttribute('aria-current', 'page');
    await page.goto('/panel/urunler');
    await page.getByRole('link', { name: 'Ürün maliyetlerini gir' }).click();
    await expect(page).toHaveURL(/\/panel\/maliyetler$/);
  });
});

test.describe('ürün maliyetleri, koyu tema', () => {
  test.use({ colorScheme: 'dark' });

  test('liste, form ve toplu yükleme raporu: axe 0', async ({ page }, testInfo) => {
    await open(page, testInfo, 'koyu');
    await expectClean(page);
    await page.getByRole('button', { name: /Maliyet gir\s?: Cam Matara/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Maliyet gir' });
    await dialog.getByLabel(/Birim maliyet/).fill('12.5');
    await dialog.getByRole('button', { name: 'Kaydet' }).click();
    await expect(dialog.getByText(/Ondalık için virgül kullanın/)).toBeVisible();
    await expectClean(page);
    await dialog.getByRole('button', { name: 'Vazgeç' }).click();
    await chooseFile(
      page,
      'karisik.csv',
      [CSV_HEADER, 'BRK-0002;54,50;20;', 'BRK-0004;40;18;'].join('\n'),
    );
    await page.getByRole('button', { name: 'Dosyayı kontrol et' }).click();
    await expect(
      page.getByRole('region', { name: 'Toplu maliyet yükle' }).getByRole('status'),
    ).toContainText('1 satırda hata var');
    await expectClean(page);
  });
});
