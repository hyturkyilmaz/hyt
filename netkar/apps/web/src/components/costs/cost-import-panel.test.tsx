import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CostImportPanel } from '@/components/costs/cost-import-panel';
import { makeImportReport } from '@/lib/profit/cost-fixtures';
import { ACCOUNT_ID } from '@/lib/profit/test-fixtures';
import { problemBody, stubApi, type Call, type Responder } from '@/test/cost-api-mock';

const importPath = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/product-costs/import`;

afterEach(() => {
  vi.unstubAllGlobals();
});

const csv = (name = 'maliyet.csv') =>
  new File(['barkod;birim_maliyet_kdv_haric;kdv_orani\nBRK-1;54,50;20\n'], name, {
    type: 'text/csv',
  });

function onImport(handler: (call: Call) => ReturnType<Responder>): Responder {
  return (call) => (call.path === importPath ? handler(call) : undefined);
}

const ERRORS = [
  {
    row: 3,
    column: 'kdv_orani',
    message: 'KDV oranı yüzde 0, 1, 10 veya 20 olmalıdır.',
    value: '18',
  },
  {
    row: 5,
    column: 'birim_maliyet_kdv_haric',
    message: 'Maliyet sıfırdan büyük olmalıdır.',
    value: '0',
  },
];

async function choose(file: File) {
  const user = userEvent.setup({ applyAccept: false });
  const onImported = vi.fn();
  render(<CostImportPanel accountId={ACCOUNT_ID} onImported={onImported} />);
  await user.upload(screen.getByLabelText(/Maliyet dosyası/), file);
  return { user, onImported };
}

describe('Toplu maliyet yükleme', () => {
  it('şablon indirme bağlantısı, sütun açıklamaları ve sınırlar görünür', () => {
    render(<CostImportPanel accountId={ACCOUNT_ID} onImported={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Şablonu indir/ })).toBeEnabled();
    const details = screen.getByText('Sütunlar ve dosya kuralları').closest('details');
    expect(details).toHaveTextContent('barkod');
    expect(details).toHaveTextContent('birim_maliyet_kdv_haric');
    expect(details).toHaveTextContent('kdv_orani');
    expect(details).toHaveTextContent('gecerlilik_tarihi');
    expect(details).toHaveTextContent('En çok 2 MB ve 10.000 veri satırı');
    expect(screen.getByRole('button', { name: 'Dosyayı kontrol et' })).toBeDisabled();
  });

  it('desteklenmeyen uzantıyı ve büyük dosyayı yüklemeden reddeder', async () => {
    const { calls } = stubApi();
    const { user } = await choose(new File(['x'], 'maliyet.xls'));
    expect(await screen.findByText('Yalnız .csv veya .xlsx dosyası yüklenebilir.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Dosyayı kontrol et' })).toBeDisabled();
    const big = new File(['x'], 'buyuk.csv');
    Object.defineProperty(big, 'size', { value: 2 * 1024 * 1024 + 1 });
    await user.upload(screen.getByLabelText(/Maliyet dosyası/), big);
    expect(await screen.findByText(/Dosya en fazla 2 MB olabilir/)).toBeVisible();
    expect(calls.some((c) => c.path === importPath)).toBe(false);
  });

  it('önce kuru deneme yapar (dry_run=true), kaydetmez; temiz dosyada tümünü kaydeder', async () => {
    const { calls } = stubApi(
      onImport((c) =>
        c.query.get('dry_run') === 'true'
          ? { body: makeImportReport({ total: 3, valid: 3 }) }
          : {
              body: makeImportReport({
                dry_run: false,
                committed: true,
                created: 2,
                updated: 1,
              }),
            },
      ),
    );
    const { user, onImported } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    const report = await screen.findByRole('region', { name: 'Dosya raporu' });
    expect(screen.getByRole('status')).toHaveTextContent(
      'Kontrol tamam, henüz kaydedilmedi. 3 satır kaydedilmeye hazır.',
    );
    // Odak sonuç bölümüne taşınır (düğme DOM'dan kalktı, odak body'ye düşmez)
    expect(report).toHaveFocus();
    expect(onImported).not.toHaveBeenCalled();
    const preview = calls.find((c) => c.path === importPath);
    expect(preview?.method).toBe('POST');
    expect(preview?.query.get('dry_run')).toBe('true');
    expect(preview?.query.get('allow_partial')).toBe('false');
    expect(preview?.file?.name).toBe('maliyet.csv');
    expect(preview?.headers.get('X-CSRF-Token')).toBe('test-csrf');
    // Çok parçalı gövdede Content-Type'ı tarayıcı koyar: elle JSON başlığı konmaz
    expect(preview?.headers.get('Content-Type')).toBeNull();

    await user.click(screen.getByRole('button', { name: '3 satırı kaydet' }));
    await waitFor(() => expect(onImported).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/Kaydedildi\. 2 yeni maliyet eklendi, 1 maliyet güncellendi\./),
    ).toBeVisible();
    const apply = calls.filter((c) => c.path === importPath)[1];
    expect(apply?.query.get('dry_run')).toBe('false');
    expect(apply?.query.get('allow_partial')).toBe('false');
    expect(screen.getByRole('button', { name: 'Başka dosya yükle' })).toBeVisible();
  });

  it('hatalı satırları listeler; tümünü kaydet düğmesi yok, yalnız geçerlileri kaydetme açıkça sorulur', async () => {
    const { calls } = stubApi(
      onImport((c) =>
        c.query.get('dry_run') === 'true'
          ? {
              body: makeImportReport({
                total: 4,
                valid: 2,
                invalid: 2,
                skipped: 0,
                unknown_barcodes: 1,
                errors: ERRORS,
                ignored_columns: ['Notlar'],
              }),
            }
          : {
              body: makeImportReport({
                dry_run: false,
                committed: true,
                created: 2,
                updated: 0,
                valid: 2,
                invalid: 2,
                errors: ERRORS,
              }),
            },
      ),
    );
    const { user, onImported } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    const list = await screen.findByRole('list', { name: 'Satır hataları' });
    const items = within(list).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Satır 3, KDV oranı');
    expect(items[0]).toHaveTextContent('KDV oranı yüzde 0, 1, 10 veya 20 olmalıdır.');
    expect(items[0]).toHaveTextContent('Girilen: 18');
    expect(items[1]).toHaveTextContent('Satır 5, Birim maliyet (KDV hariç)');
    const region = screen.getByRole('region', { name: 'Dosya raporu' });
    expect(screen.getByRole('status')).toHaveTextContent('2 satırda hata var, 2 satır geçerli.');
    expect(region).toHaveTextContent('1 barkod ürün listenizde yok');
    expect(region).toHaveTextContent('Tanınmayan sütunlar yok sayıldı: Notlar.');
    expect(screen.queryByRole('button', { name: '2 satırı kaydet' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Yalnız geçerli 2 satırı kaydet' }));
    await waitFor(() => expect(onImported).toHaveBeenCalled());
    const apply = calls.filter((c) => c.path === importPath)[1];
    expect(apply?.query.get('allow_partial')).toBe('true');
    expect(apply?.query.get('dry_run')).toBe('false');
  });

  it('hiç geçerli satır yoksa kaydet düğmesi çıkmaz', async () => {
    stubApi(
      onImport(() => ({
        body: makeImportReport({ total: 2, valid: 0, invalid: 2, errors: ERRORS }),
      })),
    );
    const { user } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    expect(
      await screen.findByText('Kaydedilecek geçerli satır yok. Dosyayı düzeltip yeniden seçin.'),
    ).toBeVisible();
    expect(screen.queryByRole('button', { name: /kaydet$/ })).not.toBeInTheDocument();
  });

  it('20 hatadan fazlası "Tüm hataları göster" ile açılır, kırpılma notu çıkar', async () => {
    const many = Array.from({ length: 25 }, (_, i) => ({
      row: i + 2,
      column: 'kdv_orani',
      message: 'KDV oranı yüzde 0, 1, 10 veya 20 olmalıdır.',
      value: '18',
    }));
    stubApi(
      onImport(() => ({
        body: makeImportReport({
          total: 25,
          valid: 0,
          invalid: 25,
          errors: many,
          errors_truncated: true,
        }),
      })),
    );
    const { user } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    const list = await screen.findByRole('list', { name: 'Satır hataları' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(20);
    await user.click(screen.getByRole('button', { name: 'Tüm hataları göster (25)' }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(25);
    expect(screen.getByText(/Hata listesi ilk 25 hatayla sınırlı/)).toBeVisible();
  });

  it('kayıt anında 422 import-validation-failed: rapor gösterilir, "hiçbir şey kaydedilmedi" denir', async () => {
    stubApi(
      onImport((c) =>
        c.query.get('dry_run') === 'true'
          ? { body: makeImportReport({ total: 3, valid: 3 }) }
          : problemBody(422, 'import-validation-failed', {
              report: makeImportReport({
                dry_run: false,
                total: 3,
                valid: 2,
                invalid: 1,
                errors: ERRORS.slice(0, 1),
              }),
            }),
      ),
    );
    const { user, onImported } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    await user.click(await screen.findByRole('button', { name: '3 satırı kaydet' }));
    expect(
      await screen.findByText(/Hatalı satırlar olduğu için hiçbir şey kaydedilmedi\./),
    ).toBeVisible();
    expect(screen.getByRole('list', { name: 'Satır hataları' })).toBeVisible();
    expect(onImported).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Yalnız geçerli 2 satırı kaydet' })).toBeVisible();
  });

  it.each([
    [
      problemBody(422, 'import-file-invalid', {
        detail: 'Zorunlu sütun(lar) bulunamadı: kdv_orani.',
      }),
      'Dosya okunamadı. Zorunlu sütun(lar) bulunamadı: kdv_orani.',
    ],
    [problemBody(415, 'import-unsupported-type'), 'Yalnız .csv veya .xlsx dosyası yüklenebilir.'],
    [
      problemBody(413, 'payload-too-large'),
      'Dosya en fazla 2 MB olabilir. Daha küçük parçalara bölün.',
    ],
    [
      problemBody(422, 'import-too-many-rows'),
      'Dosyada 10.000 veri satırından fazlası var. Dosyayı bölüp ayrı ayrı yükleyin.',
    ],
    [
      { ...problemBody(429, 'rate-limited'), headers: { 'Retry-After': '5' } },
      'Şu an çok fazla içe aktarma var. 5 saniye sonra tekrar deneyin.',
    ],
    [problemBody(403, 'forbidden'), 'Maliyet yüklemek için sahip ya da yönetici olmanız gerekir.'],
  ])('dosya düzeyi hata Türkçe gösterilir (%#)', async (reply, text) => {
    stubApi(onImport(() => reply));
    const { user } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
    // Hata sonrası yeniden deneme mümkün
    expect(screen.getByRole('button', { name: 'Dosyayı kontrol et' })).toBeEnabled();
  });

  it('Vazgeç: rapor temizlenir, dosya seçimi sıfırlanır', async () => {
    stubApi(onImport(() => ({ body: makeImportReport() })));
    const { user } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    await screen.findByRole('region', { name: 'Dosya raporu' });
    await user.click(screen.getByRole('button', { name: 'Vazgeç' }));
    expect(screen.queryByRole('region', { name: 'Dosya raporu' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dosyayı kontrol et' })).toBeDisabled();
  });

  it('yeni dosya seçilince eski rapor kalkar', async () => {
    stubApi(onImport(() => ({ body: makeImportReport() })));
    const { user } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    await screen.findByRole('region', { name: 'Dosya raporu' });
    await user.upload(screen.getByLabelText(/Maliyet dosyası/), csv('baska.csv'));
    expect(screen.queryByRole('region', { name: 'Dosya raporu' })).not.toBeInTheDocument();
  });

  it("canlı durum bölgesi baştan DOM'da (boş) ve görünür", () => {
    render(<CostImportPanel accountId={ACCOUNT_ID} onImported={vi.fn()} />);
    const status = screen.getByRole('status');
    expect(status).toBeVisible();
    expect(status).toBeEmptyDOMElement();
  });

  it('dosya okunamazsa ağ hatası değil, ayrı "Dosya okunamadı" iletisi çıkar', async () => {
    stubApi();
    const broken = csv('bozuk.csv');
    Object.defineProperty(broken, 'arrayBuffer', {
      value: () => Promise.reject(new Error('NotReadable')),
    });
    await choose(broken);
    expect(
      await screen.findByText(/Dosya okunamadı\. Dosya silinmiş ya da taşınmış/),
    ).toBeVisible();
    expect(screen.queryByText(/İnternet bağlantınızı/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dosyayı kontrol et' })).toBeDisabled();
  });

  it('kontrol ve kayıt AYNI anlık görüntüyü gönderir (dosya diskte değişse de)', async () => {
    let content = 'barkod;birim_maliyet_kdv_haric;kdv_orani\nBRK-1;54,50;20\n';
    const file = new File([content], 'maliyet.csv', { type: 'text/csv' });
    const sent: string[] = [];
    stubApi(
      onImport(async (c) => {
        sent.push(await c.file!.text());
        return c.query.get('dry_run') === 'true'
          ? { body: makeImportReport({ total: 1, valid: 1 }) }
          : {
              body: makeImportReport({
                dry_run: false,
                committed: true,
                created: 1,
                updated: 0,
                valid: 1,
                total: 1,
              }),
            };
      }),
    );
    const { user } = await choose(file);
    content = 'degisti';
    Object.defineProperty(file, 'arrayBuffer', {
      value: () => Promise.reject(new Error('changed')),
    });
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    await user.click(await screen.findByRole('button', { name: '1 satırı kaydet' }));
    await screen.findByText(/Kaydedildi/);
    expect(sent).toHaveLength(2);
    expect(sent[0]).toBe(sent[1]);
    expect(sent[0]).toContain('BRK-1');
  });

  it('200 yanıtı beklenen şekilde değilse sayı uydurmaz, hata gösterir', async () => {
    stubApi(onImport(() => ({ body: { dry_run: true } })));
    const { user } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Sunucu yanıtı beklenenden farklı');
    expect(screen.queryByRole('region', { name: 'Dosya raporu' })).not.toBeInTheDocument();
  });

  it.each([
    [
      problemBody(503, 'import-unavailable'),
      'XLSX içe aktarma şu an kapalı. Dosyanızı CSV olarak kaydedip yükleyin.',
    ],
    [
      { ...problemBody(429, 'import-in-progress'), headers: { 'Retry-After': '5' } },
      'Bu mağaza için bir içe aktarma zaten sürüyor. Bitmesini bekleyin; 5 saniye sonra tekrar deneyin.',
    ],
    [
      { ...problemBody(503, 'import-busy'), headers: { 'Retry-After': '5' } },
      'Şu an çok sayıda dosya işleniyor. 5 saniye sonra tekrar deneyin.',
    ],
    [
      { ...problemBody(429, 'rate-limited'), headers: { 'Retry-After': '3412' } },
      'Şu an çok fazla içe aktarma var. 57 dakika sonra tekrar deneyin.',
    ],
    [
      { ...problemBody(429, 'rate-limited'), headers: { 'Retry-After': '10800' } },
      'Şu an çok fazla içe aktarma var. 3 saat sonra tekrar deneyin.',
    ],
  ])('ayrı kod ve insan okur bekleme süresi (%#)', async (reply, text) => {
    stubApi(onImport(() => reply));
    const { user } = await choose(csv());
    await user.click(screen.getByRole('button', { name: 'Dosyayı kontrol et' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
  });
});

describe('Şablon indirme (fetch + Blob)', () => {
  const templatePath = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/product-costs/template.csv`;

  function stubDownload() {
    const create = vi.fn(() => 'blob:sablon');
    const revoke = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    return { create, revoke, click };
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('başarıda Blob indirir, sunucu dosya adını kullanır, URL serbest bırakılır', async () => {
    const dl = stubDownload();
    stubApi((c) =>
      c.path === templatePath
        ? {
            body: {},
            headers: { 'Content-Disposition': 'attachment; filename="maliyet_sablonu.csv"' },
          }
        : undefined,
    );
    const user = userEvent.setup();
    render(<CostImportPanel accountId={ACCOUNT_ID} onImported={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Şablonu indir/ }));
    await waitFor(() => expect(dl.click).toHaveBeenCalledTimes(1));
    expect(dl.create).toHaveBeenCalledTimes(1);
    expect(dl.revoke).toHaveBeenCalledWith('blob:sablon');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('X-Template-Truncated: true ise şablonun eksik olduğu söylenir', async () => {
    stubDownload();
    stubApi((c) =>
      c.path === templatePath
        ? { body: {}, headers: { 'X-Template-Truncated': 'true' } }
        : undefined,
    );
    const user = userEvent.setup();
    render(<CostImportPanel accountId={ACCOUNT_ID} onImported={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Şablonu indir/ }));
    expect(await screen.findByRole('note')).toHaveTextContent('Şablon ilk 10.000 ürünle sınırlı');
  });

  it.each([
    [problemBody(401, 'unauthorized'), 'Oturumunuz kapanmış'],
    [problemBody(404, 'not-found'), 'Mağaza hesabı bulunamadı'],
    [
      { ...problemBody(429, 'rate-limited'), headers: { 'Retry-After': '1800' } },
      'Şablon indirme sınırına ulaştınız. 30 dakika sonra tekrar deneyin.',
    ],
    [problemBody(500, 'internal-error'), 'Şablon şu an hazırlanamadı'],
  ])('hata durumunda dosya inmez, Türkçe ileti (%#)', async (reply, text) => {
    const dl = stubDownload();
    stubApi((c) => (c.path === templatePath ? reply : undefined));
    const user = userEvent.setup();
    render(<CostImportPanel accountId={ACCOUNT_ID} onImported={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Şablonu indir/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
    expect(dl.click).not.toHaveBeenCalled();
    expect(dl.create).not.toHaveBeenCalled();
  });
});
