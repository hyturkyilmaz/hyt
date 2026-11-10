import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ProductDetailScreen } from '@/components/profit/product-detail';
import { ProductListScreen } from '@/components/profit/product-list';
import { SummaryScreen } from '@/components/profit/summary-view';
import { mockFetch, problem } from '@/test/api-mock';
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
} from '@/lib/profit/test-fixtures';

const navigation = vi.hoisted(() => ({ search: '', replace: vi.fn() }));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
  useRouter: () => ({ replace: navigation.replace, push: vi.fn() }),
  usePathname: () => '/panel',
}));

const accounts = (url: URL) =>
  url.pathname === '/api/v1/marketplace-accounts' ? { body: makeAccounts() } : undefined;
const base = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/profit`;

beforeEach(() => {
  navigation.search = '';
  navigation.replace.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Özet ekranı', () => {
  function renderSummary(totals = makeTotals(), alerts = makeAlerts(SAMPLE_ALERT_COUNTS)) {
    return mockFetch(
      accounts,
      (url) => (url.pathname === `${base}/summary` ? { body: makeSummary(totals) } : undefined),
      (url) => (url.pathname === `${base}/alerts` ? { body: alerts } : undefined),
    );
  }

  it('yüklenirken iskelet, sonra başlık kartları: net kâr, net satış, toplam gider, marj', async () => {
    renderSummary();
    render(<SummaryScreen />);
    expect(screen.getByRole('status')).toHaveTextContent('Yükleniyor');

    expect(await screen.findByText(/3\.120,45/)).toBeInTheDocument();
    expect(screen.getByText('Net kâr')).toBeInTheDocument();
    expect(screen.getByText(/18\.450,00/)).toBeInTheDocument();
    expect(screen.getByText('Toplam gider')).toBeInTheDocument();
    expect(screen.getByText(/15\.329,55/)).toBeInTheDocument();
    expect(screen.getByText(/%16,9/)).toBeInTheDocument();
    // Durum dağılımı ve uyarı sayıları
    const statuses = screen.getByText('Satır durumları').closest('div')?.parentElement;
    expect(statuses).toHaveTextContent('Ekstreli');
    expect(await screen.findByText(/Zararına satış/)).toBeInTheDocument();
    // Tahmini dönem: "Kesin" rozeti yok, "Tahmini" rozeti var
    expect(screen.getByText('Tahmini', { selector: 'span.inline-flex' })).toBeInTheDocument();
    expect(screen.queryByText('Kesin', { selector: 'span.inline-flex' })).not.toBeInTheDocument();
  });

  it('dönem seçici URL range parametresine bağlanır ve istek o dönemle yapılır', async () => {
    navigation.search = 'range=7d';
    const { calls } = renderSummary();
    render(<SummaryScreen />);
    await screen.findByText(/3\.120,45/);

    const nav = screen.getByRole('navigation', { name: 'Dönem' });
    expect(within(nav).getByRole('link', { name: '7 gün' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(within(nav).getByRole('link', { name: '30 gün' })).toHaveAttribute(
      'href',
      '/panel?range=30d',
    );
    expect(within(nav).getByRole('link', { name: 'Bugün' })).toHaveAttribute(
      'href',
      '/panel?range=today',
    );
    expect(
      calls.some((u) => u.pathname === `${base}/summary` && u.searchParams.get('range') === '7d'),
    ).toBe(true);
  });

  it('kurulum eksikliğinde net kâr asla 0,00 değil: hesaplanamadı, eksik kalemler ve bant', async () => {
    renderSummary(makeUnconfiguredTotals());
    render(<SummaryScreen />);

    await screen.findAllByText('Hesaplanamadı');
    const net = screen.getByText('Net kâr').closest('div')?.parentElement as HTMLElement;
    expect(net).toHaveTextContent('Hesaplanamadı');
    expect(net).toHaveTextContent('Eksik: ürün maliyeti, kargo, hizmet bedeli');
    expect(net).not.toHaveTextContent('0,00');
    // Tam satır sayısı 0: eksiksiz satır bloğu yok
    expect(screen.queryByText(/Eksiksiz \d+ satırın net kârı/)).not.toBeInTheDocument();
    // Kesin rozeti yok; kesinlik eksik
    expect(screen.queryByText('Kesin', { selector: 'span.inline-flex' })).not.toBeInTheDocument();
    expect(screen.getByText('Eksik', { selector: 'span.inline-flex' })).toBeInTheDocument();

    const banner = screen.getByRole('region', { name: 'Kurulum uyarısı' });
    expect(banner).toHaveTextContent(
      'Kargo tarifesi ve hizmet bedeli girilmedi: net kâr bu kalemler hariç hesaplanamaz',
    );
    expect(banner).toHaveTextContent(
      'Bu dönemde 12 satırda kargo, 12 satırda hizmet bedeli tahmini eksik.',
    );
    expect(within(banner).getByRole('link')).toHaveAttribute('href', '/panel/ayarlar');
  });

  it('eksik kalem yoksa kurulum bandı çıkmaz', async () => {
    renderSummary();
    render(<SummaryScreen />);
    await screen.findByText(/3\.120,45/);
    expect(screen.queryByRole('region', { name: 'Kurulum uyarısı' })).not.toBeInTheDocument();
  });

  it('dönemde sipariş yoksa boş durum gösterir', async () => {
    renderSummary(makeTotals({ satir_sayisi: 0, siparis_sayisi: 0 }));
    render(<SummaryScreen />);
    expect(await screen.findByText('Bu dönemde sipariş yok')).toBeInTheDocument();
  });

  it('mağaza bağlı değilse bağlantı çağrısı gösterir', async () => {
    mockFetch((url) =>
      url.pathname === '/api/v1/marketplace-accounts' ? { body: [] } : undefined,
    );
    render(<SummaryScreen />);
    expect(await screen.findByText(/Trendyol mağazanızı bağlayın/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Bağlantıya başla' })).toHaveAttribute(
      'href',
      '/panel/ayarlar',
    );
  });

  it('rapor hatasında ayrıntı sızdırmadan tekrar dene sunar ve yeniden dener', async () => {
    let failing = true;
    mockFetch(
      accounts,
      (url) => {
        if (url.pathname !== `${base}/summary`) return undefined;
        return failing ? problem(503, 'busy') : { body: makeSummary() };
      },
      (url) => (url.pathname === `${base}/alerts` ? { body: makeAlerts() } : undefined),
    );
    render(<SummaryScreen />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Rapor şu an yoğun');
    failing = false;
    await userEvent.click(screen.getByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByText(/3\.120,45/)).toBeInTheDocument();
  });
});

describe('Ürün kârlılık listesi', () => {
  const productsPath = `${base}/products`;

  it('satır: başlık metin olarak, barkod, adet, net satış, net kâr, marj ve rozetler', async () => {
    const items = [
      makeItem({ barcode: 'A1', title: '<img src=x onerror=alert(1)> Termos' }),
      makeItem({
        barcode: 'B2',
        title: 'Maliyetsiz Zarar',
        net_profit: null,
        net_margin_percent: null,
        loss_reason: 'contribution_before_cost',
        cost_missing: true,
        missing_items: ['urun_maliyeti'],
        contribution_excl_missing: '-12.00',
        certainty: 'eksik',
      }),
      makeItem({
        barcode: 'C3',
        title: 'Kesin Zarar',
        net_profit: '-30.00',
        net_margin_percent: '-8.0',
        loss_reason: 'net_profit',
      }),
      makeItem({
        barcode: 'D4',
        title: 'Bilinen Giderle Zarar',
        net_profit: null,
        net_margin_percent: null,
        loss_reason: 'known_expenses',
        shipping_missing: true,
        missing_items: ['kargo_gonderi', 'platform_hizmet_bedeli'],
        contribution_excl_missing: '-4.00',
        certainty: 'eksik',
      }),
      makeItem({
        barcode: 'E5',
        title: 'Belirsiz Ürün',
        net_profit: null,
        net_margin_percent: null,
        loss_reason: null,
        missing_items: ['kargo_gonderi'],
        contribution_excl_missing: '75.00',
        certainty: 'eksik',
      }),
      makeItem({
        barcode: 'F6',
        title: 'Yalnız İptal',
        net_profit: '0.00',
        net_margin_percent: null,
        certainty: 'yok',
      }),
    ];
    mockFetch(accounts, (url) =>
      url.pathname === productsPath ? { body: makeList(items) } : undefined,
    );
    const { container } = render(<ProductListScreen />);
    await screen.findAllByText('Maliyetsiz Zarar');

    // Başlık HTML olarak yorumlanmaz: img etiketi yok, metin olarak görünür
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getAllByText(/<img src=x onerror=alert\(1\)> Termos/).length).toBeGreaterThan(0);

    const cards = screen.getByRole('list', { name: 'Ürün listesi' });
    const card = (name: string) =>
      within(cards).getByRole('link', { name }).closest('li') as HTMLElement;

    // Üç zarar nedeni ayrı rozet
    expect(within(card('Kesin Zarar')).getByText('Zarar')).toBeInTheDocument();
    expect(within(card('Maliyetsiz Zarar')).getByText('Maliyetsiz bile zarar')).toBeInTheDocument();
    const known = card('Bilinen Giderle Zarar');
    expect(within(known).getByText('Bilinen giderlerle bile zarar')).toBeInTheDocument();
    expect(within(known).getByText('Kargo eksik')).toBeInTheDocument();
    // Belirsiz ürün kârlı değil
    expect(within(card('Belirsiz Ürün')).getByText('Belirsiz')).toBeInTheDocument();

    // Null net kâr: hesaplanamadı + eksik kalemler, asla 0,00
    const missing = card('Maliyetsiz Zarar');
    expect(missing).toHaveTextContent('Hesaplanamadı');
    expect(missing).toHaveTextContent('Eksik: ürün maliyeti');
    expect(missing).toHaveTextContent('Eksik giderler hariç kâr: -₺12,00');
    expect(missing).not.toHaveTextContent('₺0,00');
    expect(card('Bilinen Giderle Zarar')).toHaveTextContent('Eksik: kargo, hizmet bedeli');

    // İptal ürün 0,00 kâr değil
    const cancelled = card('Yalnız İptal');
    expect(cancelled).toHaveTextContent('İptal');
    expect(cancelled).not.toHaveTextContent('₺0,00 ');

    // Kesin rozeti yalnız kesinlik=kesin satırda
    expect(within(card('Kesin Zarar')).getByText('Kesin')).toBeInTheDocument();
    expect(within(missing).queryByText('Kesin')).not.toBeInTheDocument();

    // Barkod, adet, net satış
    const first = card('<img src=x onerror=alert(1)> Termos');
    expect(first).toHaveTextContent('Barkod: A1');
    expect(first).toHaveTextContent('₺1.250,00');
    expect(first).toHaveTextContent('%20,0');
  });

  it('satır bağlantısı ürün kırılımına gider (barkod kodlanır, dönem taşınır)', async () => {
    navigation.search = 'range=7d';
    mockFetch(accounts, (url) =>
      url.pathname === productsPath
        ? { body: makeList([makeItem({ barcode: 'A/B 1', title: 'Garip Barkod' })]) }
        : undefined,
    );
    render(<ProductListScreen />);
    const link = (await screen.findAllByRole('link', { name: 'Garip Barkod' }))[0];
    expect(link).toHaveAttribute('href', '/panel/urunler/A%2FB%201?range=7d');
  });

  it('sıralama ve süzgeç URL değerleriyle istek yapar; kontroller URL günceller', async () => {
    navigation.search = 'range=7d&sort=sales&order=asc&filter=missing_cost';
    const { calls } = mockFetch(accounts, (url) =>
      url.pathname === productsPath ? { body: makeList([makeItem()]) } : undefined,
    );
    render(<ProductListScreen />);
    await screen.findAllByText('Örnek Ürün Çelik Termos 500 ml');
    const call = calls.find((u) => u.pathname === productsPath);
    expect(Object.fromEntries(call?.searchParams ?? [])).toMatchObject({
      range: '7d',
      sort: 'sales',
      order: 'asc',
      filter: 'missing_cost',
    });
    expect(screen.getByRole('link', { name: 'Maliyeti eksik' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(screen.getByRole('link', { name: 'Zarar edenler' })).toHaveAttribute(
      'href',
      '/panel/urunler?range=7d&sort=sales&order=asc&filter=loss',
    );

    await userEvent.selectOptions(screen.getByLabelText('Sırala'), 'units');
    expect(navigation.replace).toHaveBeenCalledWith(
      '/panel/urunler?range=7d&sort=units&order=asc&filter=missing_cost',
      { scroll: false },
    );
  });

  it('daha fazla yükle: imleçle ikinci sayfayı ekler, imleç bitince düğme kalkar', async () => {
    const { calls } = mockFetch(accounts, (url) => {
      if (url.pathname !== productsPath) return undefined;
      return url.searchParams.get('cursor') === 'c1'
        ? { body: makeList([makeItem({ barcode: 'P2', title: 'İkinci Sayfa' })]) }
        : {
            body: makeList([makeItem({ barcode: 'P1', title: 'Birinci Sayfa' })], {
              next_cursor: 'c1',
              total_count: 2,
            }),
          };
    });
    render(<ProductListScreen />);
    await screen.findAllByText('Birinci Sayfa');
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla yükle' }));
    await screen.findAllByText('İkinci Sayfa');
    expect(screen.getAllByText('Birinci Sayfa').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Daha fazla yükle' })).not.toBeInTheDocument();
    expect(calls.filter((u) => u.searchParams.get('cursor') === 'c1')).toHaveLength(1);
  });

  it('imleç 422 cursor_invalid dönerse liste baştan yüklenir ve bildirilir', async () => {
    let firstPageServed = 0;
    const { calls } = mockFetch(accounts, (url) => {
      if (url.pathname !== productsPath) return undefined;
      if (url.searchParams.get('cursor') === 'eski') {
        return problem(422, 'validation-error', [{ field: 'cursor', code: 'cursor_invalid' }]);
      }
      firstPageServed += 1;
      return {
        body: makeList(
          [makeItem({ barcode: 'P1', title: firstPageServed === 1 ? 'Eski Liste' : 'Yeni Liste' })],
          { next_cursor: firstPageServed === 1 ? 'eski' : null },
        ),
      };
    });
    render(<ProductListScreen />);
    await screen.findAllByText('Eski Liste');
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla yükle' }));

    await screen.findAllByText('Yeni Liste');
    expect(screen.getByRole('status')).toHaveTextContent(
      'Liste güncellendiği için baştan yüklendi.',
    );
    expect(screen.queryByText('Eski Liste')).not.toBeInTheDocument();
    // Baştan: iki ilk sayfa isteği, bir imleçli istek
    expect(
      calls.filter((u) => u.pathname === productsPath && !u.searchParams.get('cursor')),
    ).toHaveLength(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('daha fazla yüklerken başka hata satır içinde kalır, liste korunur', async () => {
    mockFetch(accounts, (url) => {
      if (url.pathname !== productsPath) return undefined;
      return url.searchParams.get('cursor')
        ? problem(503, 'busy')
        : { body: makeList([makeItem({ title: 'Kalan Ürün' })], { next_cursor: 'c1' }) };
    });
    render(<ProductListScreen />);
    await screen.findAllByText('Kalan Ürün');
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla yükle' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Rapor şu an yoğun');
    expect(screen.getAllByText('Kalan Ürün').length).toBeGreaterThan(0);
  });

  it('boş liste süzgece uygun açıklama verir; hata durumunda tekrar dene sunar', async () => {
    navigation.search = 'filter=loss';
    mockFetch(accounts, (url) =>
      url.pathname === productsPath ? { body: makeList([]) } : undefined,
    );
    const { unmount } = render(<ProductListScreen />);
    expect(await screen.findByText('Zarar eden ürün yok')).toBeInTheDocument();
    unmount();

    mockFetch(accounts, (url) =>
      url.pathname === productsPath ? problem(500, 'internal-error') : undefined,
    );
    render(<ProductListScreen />);
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Rapor şu an hazırlanamadı'),
    );
    expect(screen.getByRole('button', { name: 'Tekrar dene' })).toBeInTheDocument();
  });
});

describe('Ürün kırılım sayfası', () => {
  const detailPath = `${base}/products/BRK-0001`;

  function renderDetail(lines = [makeLine()], over = {}) {
    mockFetch(accounts, (url) =>
      url.pathname === detailPath ? { body: makeDetail(lines, over) } : undefined,
    );
    return render(<ProductDetailScreen barcode="BRK-0001" />);
  }

  it('satır kırılımı ve kaynak etiketleri (kesin, tahmini, eksik); eksik kalem 0,00 değil', async () => {
    const line = makeLine({
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
    });
    renderDetail([line]);
    await screen.findByRole('heading', { level: 1, name: 'Örnek Ürün Çelik Termos 500 ml' });

    const table = screen.getByRole('table', { name: /kalem kırılımı/ });
    const cargo = within(table).getByRole('row', { name: /Kargo \(gönderi\)/ });
    expect(cargo).toHaveTextContent('Eksik');
    expect(cargo).not.toHaveTextContent('0,00');
    const fee = within(table).getByRole('row', { name: /Platform hizmet bedeli/ });
    expect(within(fee).getByText('Tahmini')).toBeInTheDocument();
    const commission = within(table).getByRole('row', { name: /Komisyon/ });
    expect(within(commission).getByText('Kesin')).toBeInTheDocument();

    expect(screen.getByText(/Net kâr:/).closest('p')).toHaveTextContent('Hesaplanamadı');
    expect(screen.getByText(/Net kâr:/).closest('p')).toHaveTextContent('Eksik: kargo');
  });

  it('IADE_KAYDI_BEKLENIYOR notu ve tahmini net kâr (net kâr + askıdaki maliyet)', async () => {
    renderDetail([
      makeLine({
        durum: 'adjusted',
        kesinlik: 'tahmini',
        uyarilar: ['IADE_KAYDI_BEKLENIYOR'],
        askidaki_urun_maliyeti: '50.00',
        kalemler: { ...makeLine().kalemler, net_kar: '-50.00' },
      }),
    ]);
    const note = await screen.findByRole('note');
    expect(note).toHaveTextContent('İade kaydı bekleniyor.');
    expect(note).toHaveTextContent('Ürün stoğa dönerse tahmini net kâr');
    expect(note).toHaveTextContent('₺0,00');
    expect(within(note).getByText('Tahmini')).toBeInTheDocument();
  });

  it('BEKLENMEYEN_KESINTI karşılaştırma dökümü ve varsayılan desi ipucu', async () => {
    renderDetail([
      makeLine({
        uyarilar: ['BEKLENMEYEN_KESINTI'],
        karsilastirma: {
          komisyon_tahmini: '10.00',
          komisyon_kesin: '10.00',
          kargo_gonderi_tahmini: '50.00',
          kargo_gonderi_kesin: '125.00',
          platform_hizmet_bedeli_tahmini: '8.00',
          platform_hizmet_bedeli_kesin: '8.00',
          kargo_tahmini_varsayilan_desi: true,
          karsilastirilan_tahmini_toplam: '68.00',
          karsilastirilan_kesin_toplam: '143.00',
          fark: '75.00',
          esik: '5.00',
        },
      }),
    ]);
    const block = await screen.findByRole('region', { name: 'Tahmini ve kesin karşılaştırması' });
    expect(within(block).getByRole('row', { name: /Kargo/ })).toHaveTextContent('₺50,00');
    expect(within(block).getByRole('row', { name: /Kargo/ })).toHaveTextContent('₺125,00');
    expect(block).toHaveTextContent('Fark: ₺75,00');
    expect(block).toHaveTextContent('Siparişte desi yoksa varsayılan desi farkı olabilir.');
  });

  it('iptal satırda rakam gösterilmez', async () => {
    renderDetail([
      makeLine({
        durum: 'cancelled',
        kesinlik: 'iptal',
        kalemler: { ...makeLine().kalemler, net_kar: '0.00' },
      }),
    ]);
    expect(await screen.findByText(/İptal: bu satır kâr hesabına girmez/)).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: /kalem kırılımı/ })).not.toBeInTheDocument();
  });

  it('daha fazla satır yükle ve imleç hatasında baştan yükler', async () => {
    let served = 0;
    mockFetch(accounts, (url) => {
      if (url.pathname !== detailPath) return undefined;
      if (url.searchParams.get('cursor')) {
        return problem(422, 'validation-error', [{ field: 'cursor', code: 'cursor_invalid' }]);
      }
      served += 1;
      return {
        body: makeDetail([makeLine({ orderNumber: served === 1 ? 'ESKI-1' : 'YENI-1' })], {
          next_cursor: served === 1 ? 'x' : null,
        }),
      };
    });
    render(<ProductDetailScreen barcode="BRK-0001" />);
    await screen.findByText('ESKI-1');
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla satır yükle' }));
    await screen.findByText('YENI-1');
    expect(screen.getByRole('status')).toHaveTextContent(
      'Liste güncellendiği için baştan yüklendi.',
    );
  });

  it('ürün bulunamazsa hata ve geri bağlantısı', async () => {
    mockFetch(accounts, (url) =>
      url.pathname === detailPath ? problem(404, 'not-found') : undefined,
    );
    render(<ProductDetailScreen barcode="BRK-0001" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('İstenen kayıt bulunamadı');
    expect(screen.getByRole('link', { name: /Ürünlere dön/ })).toHaveAttribute(
      'href',
      '/panel/urunler?range=30d',
    );
  });
});
