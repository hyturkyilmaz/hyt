import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CostsScreen, applySavedCost, savedMessage } from '@/components/costs/costs-screen';
import {
  makeCost,
  makeHistory,
  makeMissingProduct,
  makeProduct,
  makeProductList,
  makeUpsertResult,
} from '@/lib/profit/cost-fixtures';
import { todayIstanbul, addDays } from '@/lib/profit/settings-input';
import { ACCOUNT_ID, makeAccounts } from '@/lib/profit/test-fixtures';
import { problemBody, stubApi, type Responder } from '@/test/cost-api-mock';

const navigation = vi.hoisted(() => ({ search: '', replace: vi.fn() }));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
  useRouter: () => ({ replace: navigation.replace, push: vi.fn() }),
  usePathname: () => '/panel/maliyetler',
}));

const base = `/api/v1/marketplace-accounts/${ACCOUNT_ID}`;
const TODAY = todayIstanbul();

const accounts: Responder = (c) =>
  c.path === '/api/v1/marketplace-accounts' ? { body: makeAccounts() } : undefined;
const me =
  (role: string): Responder =>
  (c) =>
    c.path === '/api/v1/me' ? { body: { role } } : undefined;
const products =
  (items = [makeProduct(), makeMissingProduct()], next: string | null = null): Responder =>
  (c) =>
    c.path === `${base}/products` ? { body: makeProductList(items, next) } : undefined;
const history =
  (barcode: string, items = [makeCost()]): Responder =>
  (c) =>
    c.path === `${base}/products/${barcode}/costs` && c.method === 'GET'
      ? { body: makeHistory(barcode, items) }
      : undefined;

beforeEach(() => {
  navigation.search = '';
  navigation.replace.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

async function openMissingDialog() {
  const user = userEvent.setup();
  render(<CostsScreen />);
  await user.click(await screen.findByRole('button', { name: /Maliyet gir: Cam Matara/ }));
  const dialog = await screen.findByRole('dialog', { name: 'Maliyet gir' });
  return { user, dialog };
}

describe('Ürün maliyetleri listesi', () => {
  it('maliyetli ürünü tutar ve tarihle, eksik ürünü rozetle gösterir', async () => {
    stubApi(accounts, me('owner'), products());
    render(<CostsScreen />);
    const list = await screen.findByRole('list', { name: 'Ürün maliyetleri' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Çelik Termos 500 ml');
    expect(rows[0]).toHaveTextContent('54,50');
    expect(rows[0]).toHaveTextContent('%20 KDV');
    expect(rows[0]).toHaveTextContent('1 Eylül 2026 tarihinden beri geçerli');
    expect(within(rows[0]!).getByRole('button', { name: /Düzenle: Çelik Termos/ })).toBeVisible();
    expect(rows[1]).toHaveTextContent('Maliyet yok');
    expect(rows[1]).toHaveTextContent('Net kâr hesaplanamaz.');
    expect(within(rows[1]!).getByRole('button', { name: /Maliyet gir: Cam Matara/ })).toBeVisible();
  });

  it('ürün başlığı HTML olarak yorumlanmaz', async () => {
    stubApi(
      accounts,
      me('owner'),
      products([makeMissingProduct({ title: '<b>Kalın</b> Bardak' })]),
    );
    render(<CostsScreen />);
    expect(await screen.findByText('<b>Kalın</b> Bardak')).toBeInTheDocument();
  });

  it('"Maliyeti eksik" süzgeci sunucuya missing=true gönderir ve gelen satırları gösterir', async () => {
    navigation.search = 'filtre=eksik';
    const { calls } = stubApi(accounts, me('owner'), products([makeMissingProduct()]));
    render(<CostsScreen />);
    const list = await screen.findByRole('list', { name: 'Ürün maliyetleri' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(list).toHaveTextContent('Cam Matara');
    const call = calls.find((c) => c.path === `${base}/products`);
    expect(call?.query.get('missing')).toBe('true');
    expect(screen.getByRole('link', { name: 'Maliyeti eksik' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(screen.getByRole('link', { name: 'Tüm ürünler' })).toHaveAttribute(
      'href',
      '/panel/maliyetler',
    );
  });

  it('süzgeç kapalıyken missing parametresi gönderilmez', async () => {
    const { calls } = stubApi(accounts, me('owner'), products());
    render(<CostsScreen />);
    await screen.findByRole('list', { name: 'Ürün maliyetleri' });
    const call = calls.find((c) => c.path === `${base}/products`);
    expect(call?.query.has('missing')).toBe(false);
  });

  it('süzgeçte sonraki sayfa da missing=true ile istenir; istemci tarama yapmaz', async () => {
    navigation.search = 'filtre=eksik';
    const { calls } = stubApi(accounts, me('owner'), (c) => {
      if (c.path !== `${base}/products`) return undefined;
      return c.query.get('after') === 'BRK-0002'
        ? { body: makeProductList([makeMissingProduct({ barcode: 'BRK-0009', title: 'Sürahi' })]) }
        : { body: makeProductList([makeMissingProduct()], 'BRK-0002') };
    });
    const user = userEvent.setup();
    render(<CostsScreen />);
    await user.click(await screen.findByRole('button', { name: 'Daha fazla yükle' }));
    expect(await screen.findByText('Sürahi')).toBeInTheDocument();
    const pages = calls.filter((c) => c.path === `${base}/products`);
    expect(pages).toHaveLength(2);
    expect(pages.every((c) => c.query.get('missing') === 'true')).toBe(true);
  });

  it('total_missing yanıttan gösterilir (listede görünen satır sayısından bağımsız)', async () => {
    stubApi(accounts, me('owner'), (c) =>
      c.path === `${base}/products`
        ? { body: makeProductList([makeProduct()], 'BRK-0001', 37) }
        : undefined,
    );
    render(<CostsScreen />);
    expect(await screen.findByTestId('total-missing')).toHaveTextContent(
      'Toplam 37 ürünün maliyeti eksik.',
    );
  });

  it('total_missing 0 ise sayı satırı gösterilmez', async () => {
    stubApi(accounts, me('owner'), products([makeProduct()]));
    render(<CostsScreen />);
    await screen.findByRole('list', { name: 'Ürün maliyetleri' });
    expect(screen.queryByTestId('total-missing')).not.toBeInTheDocument();
  });

  it('kayıt sonrası eksik sayısı bir azalır', async () => {
    stubApi(accounts, me('owner'), products(), history('BRK-0002', []), (c) =>
      c.method === 'PUT' && c.path === `${base}/products/BRK-0002/costs`
        ? { body: makeUpsertResult({ cost: makeCost({ valid_from: addDays(TODAY, -92) }) }) }
        : undefined,
    );
    const { user, dialog } = await openMissingDialog();
    expect(screen.getByTestId('total-missing')).toHaveTextContent('Toplam 1 ürünün');
    await user.type(within(dialog).getByLabelText(/Birim maliyet/), '54,5');
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    await waitFor(() => expect(screen.queryByTestId('total-missing')).not.toBeInTheDocument());
  });

  it('arama formu q adresini günceller', async () => {
    stubApi(accounts, me('owner'), products());
    const user = userEvent.setup();
    render(<CostsScreen />);
    await screen.findByRole('list', { name: 'Ürün maliyetleri' });
    await user.type(screen.getByRole('searchbox', { name: 'Barkod ya da ürün adı ara' }), 'matara');
    await user.click(screen.getByRole('button', { name: 'Ara' }));
    expect(navigation.replace).toHaveBeenCalledWith('/panel/maliyetler?q=matara', {
      scroll: false,
    });
  });

  it('arama sorgusu API q parametresine gider', async () => {
    navigation.search = 'q=matara';
    const { calls } = stubApi(accounts, me('owner'), products([makeMissingProduct()]));
    render(<CostsScreen />);
    await screen.findByText('Cam Matara');
    const call = calls.find((c) => c.path === `${base}/products`);
    expect(call?.query.get('q')).toBe('matara');
    expect(call?.query.get('limit')).toBe('50');
  });

  it('boş durum, hata ve yeniden deneme', async () => {
    let fail = true;
    stubApi(accounts, me('owner'), (c) => {
      if (c.path !== `${base}/products`) return undefined;
      return fail ? problemBody(500, 'internal-error') : { body: makeProductList([]) };
    });
    const user = userEvent.setup();
    render(<CostsScreen />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Ürünler yüklenemedi');
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByText('Henüz ürün yok')).toBeInTheDocument();
  });

  it('mağaza bağlı değilse bağlama yönlendirir', async () => {
    stubApi(
      (c) => (c.path === '/api/v1/marketplace-accounts' ? { body: [] } : undefined),
      me('owner'),
    );
    render(<CostsScreen />);
    expect(await screen.findByText('Önce mağazanızı bağlayın')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mağazayı bağla' })).toHaveAttribute(
      'href',
      '/panel/ayarlar',
    );
  });

  it('görüntüleyici: düğme ve toplu yükleme yok, açıklama var', async () => {
    stubApi(accounts, me('viewer'), products());
    render(<CostsScreen />);
    await screen.findByRole('list', { name: 'Ürün maliyetleri' });
    await waitFor(() => expect(screen.getByRole('note')).toHaveTextContent('yalnız okuyabilir'));
    expect(screen.queryByRole('button', { name: /Maliyet gir/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Toplu maliyet yükle' })).not.toBeInTheDocument();
  });
});

describe('Tek ürün maliyeti formu', () => {
  it('ilk girişte tarih 92 gün öncesi, KDV %20 gelir; geçmiş boş mesajı görünür', async () => {
    stubApi(accounts, me('owner'), products(), history('BRK-0002', []));
    const { dialog } = await openMissingDialog();
    expect(within(dialog).getByLabelText('Geçerlilik tarihi')).toHaveValue(addDays(TODAY, -92));
    expect(within(dialog).getByRole('radio', { name: '%20' })).toBeChecked();
    expect(await within(dialog).findByText('Bu ürün için henüz maliyet girilmedi.')).toBeVisible();
    expect(within(dialog).getByText(/Barkod: BRK-0002/)).toBeVisible();
  });

  it('mevcut maliyetle açılınca değerler dolu gelir ve geçmiş listelenir', async () => {
    stubApi(
      accounts,
      me('owner'),
      products(),
      history('BRK-0001', [
        makeCost({ valid_from: '2026-09-01' }),
        makeCost({ valid_from: '2026-01-01', unit_cost_excl_vat: '40.00', vat_rate: 10 }),
      ]),
    );
    const user = userEvent.setup();
    render(<CostsScreen />);
    await user.click(await screen.findByRole('button', { name: /Düzenle: Çelik Termos/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Maliyeti düzenle' });
    expect(within(dialog).getByLabelText(/Birim maliyet/)).toHaveValue('54,50');
    expect(within(dialog).getByLabelText('Geçerlilik tarihi')).toHaveValue(TODAY);
    expect(
      within(dialog).getByRole('radio', { name: /Bu tarihten itibaren yeni maliyet/ }),
    ).toBeChecked();
    await user.click(within(dialog).getByRole('radio', { name: /Mevcut kaydı düzelt/ }));
    // Düzeltme kipinde tarih alanı yok: mevcut kaydın tarihi kullanılır
    expect(within(dialog).queryByLabelText('Geçerlilik tarihi')).not.toBeInTheDocument();
    expect(within(dialog).getByText(/Düzeltilecek kayıt: 1 Eylül 2026/)).toBeVisible();
    await user.click(
      within(dialog).getByRole('radio', { name: /Bu tarihten itibaren yeni maliyet/ }),
    );
    expect(within(dialog).getByLabelText('Geçerlilik tarihi')).toHaveValue(TODAY);
    expect(await within(dialog).findByText(/40,00.*KDV hariç, %10 KDV/)).toBeVisible();
  });

  it('yazarken "Kaydedilecek:" yansıması görünür, belirsiz yazım uyarılır', async () => {
    stubApi(accounts, me('owner'), products(), history('BRK-0002', []));
    const { user, dialog } = await openMissingDialog();
    const input = within(dialog).getByLabelText(/Birim maliyet/);
    await user.type(input, '1.250,5');
    expect(within(dialog).getByText('Kaydedilecek: 1.250,50 TL KDV hariç, %20 KDV')).toBeVisible();
    await user.clear(input);
    await user.type(input, '12.5');
    expect(within(dialog).getByText(/Okunamadı: ondalık için virgül yazın/)).toBeVisible();
  });

  it('istemci doğrulaması: belirsiz tutar gönderilmez, hata alanın yanında', async () => {
    const { calls } = stubApi(accounts, me('owner'), products(), history('BRK-0002', []));
    const { user, dialog } = await openMissingDialog();
    await user.type(within(dialog).getByLabelText(/Birim maliyet/), '12.5');
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    expect(await within(dialog).findByText(/Ondalık için virgül kullanın/)).toBeVisible();
    expect(within(dialog).getByLabelText(/Birim maliyet/)).toHaveAttribute('aria-invalid', 'true');
    expect(calls.some((c) => c.method === 'PUT')).toBe(false);
  });

  it('kaydeder: doğru gövde, CSRF başlığı, başarı mesajı, satır güncellenir, form kapanır', async () => {
    const { calls } = stubApi(accounts, me('owner'), products(), history('BRK-0002', []), (c) =>
      c.method === 'PUT' && c.path === `${base}/products/BRK-0002/costs`
        ? {
            body: makeUpsertResult({
              cost: makeCost({
                valid_from: addDays(TODAY, -92),
                unit_cost_excl_vat: '54.50',
                vat_rate: 20,
              }),
            }),
          }
        : undefined,
    );
    const { user, dialog } = await openMissingDialog();
    await user.type(within(dialog).getByLabelText(/Birim maliyet/), '54,5');
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const put = calls.find((c) => c.method === 'PUT');
    expect(put?.json).toEqual({
      valid_from: addDays(TODAY, -92),
      unit_cost_excl_vat: '54.50',
      vat_rate: '20',
    });
    expect(put?.headers.get('X-CSRF-Token')).toBe('test-csrf');
    expect(
      await screen.findByText('Cam Matara: maliyet eklendi. Kâr rakamları güncellenir.'),
    ).toBeVisible();
    const row = screen.getByText('Cam Matara').closest('li');
    expect(row).toHaveTextContent('54,50');
    expect(row).not.toHaveTextContent('Maliyet yok');
    expect(
      within(row as HTMLElement).getByRole('button', { name: /Düzenle: Cam Matara/ }),
    ).toBeVisible();
  });

  it.each([
    ['unit_cost_excl_vat', 'cost_not_positive', "Maliyet 0'dan büyük olmalı."],
    ['unit_cost_excl_vat', 'cost_too_large', 'Maliyet en çok 10.000.000 TL olabilir.'],
    ['unit_cost_excl_vat', 'cost_too_many_decimals', 'Kuruş en fazla 2 hane olabilir (12,55).'],
    ['unit_cost_excl_vat', 'decimal_invalid', 'Maliyet geçerli bir sayı olmalı. Örnek: 54,50'],
    ['vat_rate', 'vat_rate_invalid', 'KDV oranı yüzde 0, 1, 10 ya da 20 olmalı.'],
    [
      'valid_from',
      'valid_from_out_of_range',
      'Geçerlilik tarihi 1 Ocak 2000 ile bugünden en çok 366 gün sonrası arasında olmalı.',
    ],
  ])('sunucu 422 (%s, %s) alanın yanında Türkçe gösterilir', async (field, code, message) => {
    stubApi(accounts, me('owner'), products(), history('BRK-0002', []), (c) =>
      c.method === 'PUT'
        ? problemBody(422, 'validation-error', { errors: [{ field, code }] })
        : undefined,
    );
    const { user, dialog } = await openMissingDialog();
    await user.type(within(dialog).getByLabelText(/Birim maliyet/), '54,50');
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    const alerts = await within(dialog).findAllByRole('alert');
    expect(alerts.map((a) => a.textContent).join(' ')).toContain(message);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('tanınmayan alan hatası form başında gösterilir', async () => {
    stubApi(accounts, me('owner'), products(), history('BRK-0002', []), (c) =>
      c.method === 'PUT'
        ? problemBody(422, 'validation-error', {
            errors: [{ field: 'x', code: 'extra_forbidden' }],
          })
        : undefined,
    );
    const { user, dialog } = await openMissingDialog();
    await user.type(within(dialog).getByLabelText(/Birim maliyet/), '54,50');
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    expect(await within(dialog).findByText(/Bu değeri kontrol edin/)).toBeVisible();
  });

  it('403 (görüntüleyici) ve ağ hatası formda açıklanır, form açık kalır', async () => {
    let reply: 'forbidden' | 'network' = 'forbidden';
    stubApi(accounts, me('owner'), products(), history('BRK-0002', []), (c) => {
      if (c.method !== 'PUT') return undefined;
      if (reply === 'network') throw new TypeError('fetch failed');
      return problemBody(403, 'forbidden');
    });
    const { user, dialog } = await openMissingDialog();
    await user.type(within(dialog).getByLabelText(/Birim maliyet/), '54,50');
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    expect(await within(dialog).findByText(/sahip ya da yönetici/)).toBeVisible();
    reply = 'network';
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    expect(await within(dialog).findByText(/Sunucuya ulaşılamadı/)).toBeVisible();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('Vazgeç formu kapatır, hiçbir şey göndermez', async () => {
    const { calls } = stubApi(accounts, me('owner'), products(), history('BRK-0002', []));
    const { user, dialog } = await openMissingDialog();
    await user.click(within(dialog).getByRole('button', { name: 'Vazgeç' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === 'PUT')).toBe(false);
  });
});

describe('düzeltme kipi ve rol/barkod güvenliği', () => {
  it('"Mevcut kaydı düzelt" mevcut tarihle PUT eder (üstüne yazar)', async () => {
    const { calls } = stubApi(accounts, me('owner'), products(), history('BRK-0001'), (c) =>
      c.method === 'PUT'
        ? {
            body: makeUpsertResult({
              barcode: 'BRK-0001',
              created: false,
              cost: makeCost({ unit_cost_excl_vat: '57.00' }),
            }),
          }
        : undefined,
    );
    const user = userEvent.setup();
    render(<CostsScreen />);
    await user.click(await screen.findByRole('button', { name: /Düzenle: Çelik Termos/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Maliyeti düzenle' });
    await user.click(within(dialog).getByRole('radio', { name: /Mevcut kaydı düzelt/ }));
    const input = within(dialog).getByLabelText(/Birim maliyet/);
    await user.clear(input);
    await user.type(input, '57');
    await user.click(within(dialog).getByRole('button', { name: 'Kaydet' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    expect(calls.find((c) => c.method === 'PUT')?.json).toMatchObject({
      valid_from: '2026-09-01',
      unit_cost_excl_vat: '57.00',
    });
  });

  it('rol yüklenirken yazma düğmeleri devre dışı, yüklenince açılır', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    stubApi(
      accounts,
      async (c) => {
        if (c.path !== '/api/v1/me') return undefined;
        await gate;
        return { body: { role: 'owner' } };
      },
      products(),
    );
    render(<CostsScreen />);
    const button = await screen.findByRole('button', { name: /Maliyet gir: Cam Matara/ });
    expect(button).toBeDisabled();
    expect(screen.getByLabelText(/Maliyet dosyası/)).toBeDisabled();
    release();
    await waitFor(() => expect(button).toBeEnabled());
  });

  it('rol alınamazsa (me hatası) yazma denetimleri gizlenir, açıklama çıkar', async () => {
    stubApi(
      accounts,
      (c) => (c.path === '/api/v1/me' ? problemBody(500, 'internal-error') : undefined),
      products(),
    );
    render(<CostsScreen />);
    await screen.findByRole('list', { name: 'Ürün maliyetleri' });
    await waitFor(() =>
      expect(screen.getByRole('note')).toHaveTextContent('Yetkiniz doğrulanamadı'),
    );
    expect(screen.queryByRole('button', { name: /Maliyet gir|Düzenle/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Maliyet dosyası/)).not.toBeInTheDocument();
  });

  it('desen dışı barkodlu üründe düğme yok, açıklama var, istek atılmaz', async () => {
    const { calls } = stubApi(
      accounts,
      me('owner'),
      products([makeMissingProduct({ barcode: 'ÇAY 007/A', title: 'Çay Bardağı' })]),
    );
    render(<CostsScreen />);
    expect(
      await screen.findByText(/Bu barkod biçimi maliyet girişinde desteklenmiyor/),
    ).toBeVisible();
    expect(screen.queryByRole('button', { name: /Maliyet gir/ })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.includes('/costs'))).toBe(false);
  });
});

describe('kayıt sonrası satır kuralı (sunucudaki "bugün geçerli en yeni kayıt")', () => {
  const item = makeProduct({ current_cost: makeCost({ valid_from: '2026-09-01' }) });

  it('bugünkü ya da daha yeni geçmiş tarih mevcut maliyetin yerini alır', () => {
    const saved = makeCost({ valid_from: '2026-10-01', unit_cost_excl_vat: '60.00' });
    expect(applySavedCost(item, saved, '2026-11-14').current_cost).toEqual(saved);
    const same = makeCost({ valid_from: '2026-09-01', unit_cost_excl_vat: '61.00' });
    expect(applySavedCost(item, same, '2026-11-14').current_cost).toEqual(same);
  });

  it('gelecek tarih ve mevcuttan eski tarih bugünkü maliyeti değiştirmez', () => {
    expect(applySavedCost(item, makeCost({ valid_from: '2026-12-01' }), '2026-11-14')).toBe(item);
    expect(applySavedCost(item, makeCost({ valid_from: '2026-01-01' }), '2026-11-14')).toBe(item);
  });

  it('maliyetsiz ürün geçmiş tarihli kayıtla eksik olmaktan çıkar', () => {
    const missing = makeMissingProduct();
    const result = applySavedCost(missing, makeCost({ valid_from: '2026-10-01' }), '2026-11-14');
    expect(result.cost_missing).toBe(false);
  });

  it('başarı cümlesi durumu doğru anlatır', () => {
    const missing = makeMissingProduct();
    expect(
      savedMessage(
        missing,
        makeUpsertResult({ created: false, cost: makeCost({ valid_from: '2026-10-01' }) }),
        '2026-11-14',
      ),
    ).toBe('Cam Matara: maliyet güncellendi. Kâr rakamları güncellenir.');
    expect(
      savedMessage(
        missing,
        makeUpsertResult({ cost: makeCost({ valid_from: '2026-12-01' }) }),
        '2026-11-14',
      ),
    ).toMatch(/1 Aralık 2026 tarihinden itibaren kullanılır, bugünkü maliyet değişmedi/);
    expect(
      savedMessage(
        item,
        makeUpsertResult({ cost: makeCost({ valid_from: '2026-01-01' }) }),
        '2026-11-14',
      ),
    ).toMatch(/daha yeni bir kayıt geçerli/);
  });
});
