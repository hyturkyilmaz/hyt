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
  makePartialTotals,
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
  const LOSS_ITEMS = [
    makeItem({
      barcode: 'L1',
      title: 'Silikon Kek Kalıbı Set',
      net_profit: '-30.00',
      net_margin_percent: '-8.0',
      loss_reason: 'net_profit',
      certainty: 'tahmini',
    }),
    makeItem({
      barcode: 'L2',
      title: 'Kargo Tarifesi Eksik Ürün',
      net_profit: null,
      net_margin_percent: null,
      loss_reason: 'known_expenses',
      missing_items: ['kargo_gonderi', 'platform_hizmet_bedeli'],
      contribution_excl_missing: '-500.00',
      certainty: 'eksik',
    }),
  ];

  function renderSummary(
    totals = makeTotals(),
    alerts = makeAlerts(SAMPLE_ALERT_COUNTS),
    lossItems = LOSS_ITEMS,
  ) {
    return mockFetch(
      accounts,
      (url) => (url.pathname === `${base}/summary` ? { body: makeSummary(totals) } : undefined),
      (url) => (url.pathname === `${base}/alerts` ? { body: alerts } : undefined),
      (url) =>
        url.pathname === `${base}/products`
          ? { body: makeList(lossItems, { filter: 'loss' }) }
          : undefined,
    );
  }

  it('yüklenirken iskelet, sonra başlık kartları: net kâr, net satış, toplam gider, marj', async () => {
    renderSummary();
    render(<SummaryScreen />);
    expect(screen.getByRole('status')).toHaveTextContent('Yükleniyor');

    expect(await screen.findByText(/3\.120,45/)).toBeInTheDocument();
    // UX-14: etiket başlıktır, rakam başlık değildir
    expect(screen.getByRole('heading', { level: 2, name: 'Dönem net kârı' })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 2, name: 'Net satış (KDV hariç)' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Net kâr marjı' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /^₺/ })).not.toBeInTheDocument();
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

  it('durum C (G49): kısmi ve eksiksiz satır yok: hesaplanamadı, bilinen kâr kırmızı, 0,00 yok, gider ve marj kartı yok', async () => {
    renderSummary(makeUnconfiguredTotals());
    render(<SummaryScreen />);

    const heading = await screen.findByRole('heading', {
      level: 2,
      name: 'Dönem net kârı hesaplanamadı',
    });
    const card = heading.closest('div')?.parentElement as HTMLElement;
    expect(card).toHaveTextContent(
      'Bu dönemde 12 satırda kargo, 12 satırda hizmet bedeli tahmini eksik.',
    );
    expect(card).toHaveTextContent('2 satırın ürün maliyeti girilmedi.');
    expect(card).not.toHaveTextContent('₺0,00');
    // Y-4: bilinen kâr bloğu uyarı kutusunun üstünde (DOM sırası = dar ekranda görünen sıra)
    const known = within(card).getByRole('heading', {
      level: 3,
      name: 'Eksik giderler hariç dönem kârı',
    });
    const bannerRegion = within(card).getByRole('region', { name: 'Kurulum uyarısı' });
    expect(
      known.compareDocumentPosition(bannerRegion) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Bilinen kâr: ayrı, "net kâr" demeyen etiketle, negatif kırmızı ve zarar rozeti
    expect(
      within(card).getByRole('heading', { level: 3, name: 'Eksik giderler hariç dönem kârı' }),
    ).toBeInTheDocument();
    expect(card).toHaveTextContent('(ürün maliyeti, kargo ve hizmet bedeli hariç)');
    expect(card).toHaveTextContent('-₺17,35');
    expect(card.querySelector('[data-sign="negative"]')).not.toBeNull();
    expect(within(card).getByText('Bilinen giderlerle bile zarar')).toBeInTheDocument();
    // Eksiksiz satır bloğu, toplam gider ve marj kartları çizilmez
    expect(screen.queryByText(/Eksiksiz satırların net kârı/)).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Toplam gider' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Net kâr marjı' })).not.toBeInTheDocument();
    // Kesin rozeti yok; "Bilgi eksik" rozeti de basılmaz (eksik kalemler adıyla yazılı)
    expect(screen.queryByText('Kesin', { selector: 'span.inline-flex' })).not.toBeInTheDocument();
    expect(screen.queryByText('Bilgi eksik')).not.toBeInTheDocument();

    // Ayar formu açık: fayda dilli başlık ve her eksik kalem için ayar bölümüne derin bağlantı (UX-02)
    const banner = screen.getByRole('region', { name: 'Kurulum uyarısı' });
    expect(banner).toHaveTextContent(
      'Net kârı görmek için kargo tarifesini ve hizmet bedelini girin',
    );
    expect(banner).toHaveTextContent('Kargo tarifesi ve hizmet bedeli ayarlardan girilir.');
    expect(banner).toHaveTextContent('Girene kadar bu rakamlar bilinen giderlerle hesaplanıyor');
    expect(banner).not.toHaveTextContent('çok yakında');
    expect(within(banner).getByRole('link', { name: 'Kargo tarifesini gir' })).toHaveAttribute(
      'href',
      '/panel/ayarlar#kargo',
    );
    expect(within(banner).getByRole('link', { name: 'Hizmet bedelini gir' })).toHaveAttribute(
      'href',
      '/panel/ayarlar#hizmet-bedeli',
    );
  });

  it('durum B: kısmi, eksiksiz satır var: bilinen kâr nötr (yeşil değil), eksiksiz satır bloğu, etiketli marj', async () => {
    renderSummary(makePartialTotals());
    render(<SummaryScreen />);

    const heading = await screen.findByRole('heading', {
      level: 2,
      name: 'Dönem net kârı hesaplanamadı',
    });
    const card = heading.closest('div')?.parentElement as HTMLElement;
    expect(card).toHaveTextContent('Bu dönemde 4 satırda kargo tahmini eksik.');
    expect(card).toHaveTextContent('(kargo hariç)');
    expect(card).toHaveTextContent('₺1.240,00');
    // Bilinen kâr bloğunda yeşil/ok yok (net kâr sanılmasın); eksiksiz satırların gerçek net kârı ayrı blokta
    const knownBlock = within(card).getByRole('heading', {
      level: 3,
      name: 'Eksik giderler hariç dönem kârı',
    }).parentElement as HTMLElement;
    expect(knownBlock.querySelector('[data-sign]')).toBeNull();
    expect(card).toHaveTextContent('Kargo düşülünce bu rakam azalır.');
    expect(card).not.toHaveTextContent('Bilinen giderlerle bile zarar');
    // Y-7: etiket "Eksiksiz satırların net kârı"
    expect(
      within(card).getByRole('heading', { level: 3, name: 'Eksiksiz satırların net kârı' }),
    ).toBeInTheDocument();
    expect(card).toHaveTextContent('20 eksiksiz satır, dönem giderleri hariç.');
    expect(card).toHaveTextContent('₺800,00');
    expect(
      screen.getByText('Eksiksiz satırların marjı, dönem giderleri hariç'),
    ).toBeInTheDocument();
    expect(screen.getByText('Yalnız eksiksiz satırların gideri')).toBeInTheDocument();
    const banner = screen.getByRole('region', { name: 'Kurulum uyarısı' });
    expect(banner).toHaveTextContent('Net kârı görmek için kargo tarifesini girin');
    // Yalnız eksik kalemin bağlantısı vardır
    expect(within(banner).getAllByRole('link')).toHaveLength(1);
    expect(within(banner).getByRole('link', { name: 'Kargo tarifesini gir' })).toBeInTheDocument();
  });

  it('Y-2: eski API (bilinen kâr alanı yok) bandı "bu rakamlar" cümlesi olmadan çizer', async () => {
    const totals = makePartialTotals();
    delete totals.donem_eksik_giderler_haric_kar;
    renderSummary(totals);
    render(<SummaryScreen />);
    const banner = await screen.findByRole('region', { name: 'Kurulum uyarısı' });
    expect(banner).toHaveTextContent('Kargo tarifesi ayarlardan girilir.');
    expect(banner).not.toHaveTextContent('bilinen giderlerle');
  });

  it('durum A: tam dönemde Dönem net kârı rakamı, bilinen kâr bloğu ve kurulum çağrısı yok', async () => {
    renderSummary();
    render(<SummaryScreen />);
    await screen.findByText(/3\.120,45/);
    expect(screen.queryByText('Eksik giderler hariç dönem kârı')).not.toBeInTheDocument();
    expect(screen.queryByText('Dönem net kârı hesaplanamadı')).not.toBeInTheDocument();
  });

  it('eski API: yeni alanlar yoksa zarifçe düşer, 0,00 uydurulmaz ve ayar sürümü satırı çıkmaz', async () => {
    const totals = makeUnconfiguredTotals();
    delete totals.donem_eksik_giderler_haric_kar;
    mockFetch(
      accounts,
      (url) => {
        if (url.pathname !== `${base}/summary`) return undefined;
        const summary = makeSummary(totals);
        delete summary.settings_revision;
        return { body: summary };
      },
      (url) => (url.pathname === `${base}/alerts` ? { body: makeAlerts() } : undefined),
      (url) => (url.pathname === `${base}/products` ? { body: makeList([]) } : undefined),
    );
    render(<SummaryScreen />);
    await screen.findByRole('heading', { level: 2, name: 'Dönem net kârı hesaplanamadı' });
    expect(screen.queryByText('Eksik giderler hariç dönem kârı')).not.toBeInTheDocument();
    expect(screen.queryByText(/Ayar sürümü/)).not.toBeInTheDocument();
    expect(screen.queryByText('₺0,00')).not.toBeInTheDocument();
  });

  it('alt bilgi: "Ayar sürümü N" (ADR-0007 §5.2 madde 6)', async () => {
    renderSummary();
    render(<SummaryScreen />);
    expect(await screen.findByText('Ayar sürümü 7')).toBeInTheDocument();
  });

  it('zarar ettiren ürünler: en büyük zarar üstte, null net kârlı kesin zarar kaybolmaz, tümünü gör bağlantısı', async () => {
    const { calls } = renderSummary();
    render(<SummaryScreen />);
    const section = (await screen.findByRole('heading', { name: 'Zarar ettiren ürünler' })).closest(
      'section',
    ) as HTMLElement;
    const lossItems = await within(section).findAllByRole('listitem');
    // API sırası: -30 önce, null net kârlı -500 sonda; ekranda -500 üstte
    expect(lossItems[0]).toHaveTextContent('Kargo Tarifesi Eksik Ürün');
    expect(lossItems[0]).toHaveTextContent('En az');
    // Eksi işareti yok: yön ok, renk ve "zarar" sözcüğüyle; ekran okuyucu tek gizli metin okur
    expect(lossItems[0]).toHaveTextContent('En az ₺500,00 zarar');
    expect(lossItems[0]).not.toHaveTextContent('-₺500,00');
    const hidden = lossItems[0]?.querySelectorAll('[aria-hidden="true"]');
    expect(
      Array.from(hidden ?? []).some((node) => node.textContent === 'En az ₺500,00 zarar'),
    ).toBe(true);
    expect(lossItems[0]?.querySelectorAll('.sr-only')[0]).toHaveTextContent('En az ₺500,00 zarar');
    expect(lossItems[0]).toHaveTextContent('Bilinen giderlerle bile zarar');
    expect(lossItems[0]).toHaveTextContent('Kargo ve hizmet bedeli düşülünce bu rakam azalır.');
    expect(lossItems[1]).toHaveTextContent('Silikon Kek Kalıbı Set');
    expect(lossItems[1]).toHaveTextContent('-₺30,00');
    expect(within(lossItems[1] as HTMLElement).getByRole('link')).toHaveAttribute(
      'href',
      '/panel/urunler/L1?range=30d',
    );
    const all = within(section).getByRole('link', { name: /Tümünü gör/ });
    expect(all).toHaveAttribute('href', '/panel/urunler?range=30d&filter=loss');
    // İstek: zarar süzgeci, net kâr artan (en çok zarar önce), yalnız gösterilecek 3 ürün (Y-1)
    const call = calls.find((u) => u.pathname === `${base}/products`);
    expect(Object.fromEntries(call?.searchParams ?? [])).toMatchObject({
      filter: 'loss',
      sort: 'net_profit',
      order: 'asc',
      limit: '3',
    });
  });

  it('zarar eden ürün yoksa tek satır; kısmi dönemde belirsizlik uyarısı', async () => {
    renderSummary(makeTotals(), makeAlerts(), []);
    const { unmount } = render(<SummaryScreen />);
    expect(await screen.findByText('Bu dönemde zararı kesin olan ürün yok.')).toBeInTheDocument();
    expect(screen.queryByText(/kârı belirsiz olabilir/)).not.toBeInTheDocument();
    unmount();

    renderSummary(makePartialTotals(), makeAlerts(), []);
    render(<SummaryScreen />);
    expect(await screen.findByText('Bu dönemde zararı kesin olan ürün yok.')).toBeInTheDocument();
    // Y-9: neden dönemin eksik kalem adlarından kurulur (burada yalnız kargo)
    expect(
      screen.getByText('Kargo eksik olduğundan bazı ürünlerin kârı belirsiz olabilir.'),
    ).toBeInTheDocument();
  });

  it('Y-9: kısmi dönem notu yalnız eksik olan kalemi söyler', async () => {
    renderSummary(
      makePartialTotals({
        eksik_kalem_satir_sayilari: {
          urun_maliyeti: 0,
          kargo_gonderi: 0,
          platform_hizmet_bedeli: 3,
        },
      }),
      makeAlerts(),
      [],
    );
    render(<SummaryScreen />);
    expect(
      await screen.findByText(
        'Hizmet bedeli eksik olduğundan bazı ürünlerin kârı belirsiz olabilir.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Kargo/)).not.toBeInTheDocument();
  });

  it('Y-3: satışsız reklam yüzünden zarardaki ürün (kesinlik yok) zarar gösterir, İptal yazmaz', async () => {
    renderSummary(makeTotals(), makeAlerts(), [
      makeItem({
        barcode: 'R1',
        title: 'Yalnız Reklamlı Ürün',
        net_profit: '-25.00',
        net_margin_percent: null,
        loss_reason: 'net_profit',
        certainty: 'yok',
        contribution_excl_missing: '-25.00',
      }),
    ]);
    render(<SummaryScreen />);
    const section = (await screen.findByRole('heading', { name: 'Zarar ettiren ürünler' })).closest(
      'section',
    ) as HTMLElement;
    const item = (await within(section).findAllByRole('listitem'))[0] as HTMLElement;
    expect(item).toHaveTextContent('Yalnız Reklamlı Ürün');
    expect(item).toHaveTextContent('-₺25,00');
    expect(item.querySelector('[data-sign="negative"]')).not.toBeNull();
    expect(item).not.toHaveTextContent('İptal');
  });

  it('zarar listesi yüklenemezse özet çalışmaya devam eder', async () => {
    mockFetch(
      accounts,
      (url) => (url.pathname === `${base}/summary` ? { body: makeSummary() } : undefined),
      (url) => (url.pathname === `${base}/alerts` ? { body: makeAlerts() } : undefined),
      (url) => (url.pathname === `${base}/products` ? problem(503, 'busy') : undefined),
    );
    render(<SummaryScreen />);
    expect(await screen.findByText(/Zarar eden ürünler şu an yüklenemedi/)).toBeInTheDocument();
    expect(screen.getByText(/3\.120,45/)).toBeInTheDocument();
    // Y-8: zarar kartında kendi "Tekrar dene" düğmesi var
    expect(screen.getByRole('button', { name: 'Tekrar dene' })).toBeInTheDocument();
  });

  it('Y-8: zarar kartı "Tekrar dene" ile yeniden yükler', async () => {
    let failing = true;
    mockFetch(
      accounts,
      (url) => (url.pathname === `${base}/summary` ? { body: makeSummary() } : undefined),
      (url) => (url.pathname === `${base}/alerts` ? { body: makeAlerts() } : undefined),
      (url) =>
        url.pathname === `${base}/products`
          ? failing
            ? problem(503, 'busy')
            : { body: makeList(LOSS_ITEMS, { filter: 'loss' }) }
          : undefined,
    );
    render(<SummaryScreen />);
    await screen.findByText(/Zarar eden ürünler şu an yüklenemedi/);
    failing = false;
    await userEvent.click(screen.getByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByText('Silikon Kek Kalıbı Set')).toBeInTheDocument();
  });

  it('Y-8: zarar kartı 429 yanıtında Retry-After kadar bekleyip bir kez yeniden dener', async () => {
    let productCalls = 0;
    const { calls } = mockFetch(
      accounts,
      (url) => (url.pathname === `${base}/summary` ? { body: makeSummary() } : undefined),
      (url) => (url.pathname === `${base}/alerts` ? { body: makeAlerts() } : undefined),
      (url) => {
        if (url.pathname !== `${base}/products`) return undefined;
        productCalls += 1;
        return productCalls === 1
          ? { ...problem(429, 'rate-limited'), headers: { 'Retry-After': '1' } }
          : { body: makeList(LOSS_ITEMS, { filter: 'loss' }) };
      },
    );
    render(<SummaryScreen />);
    // Gerçek zamanlayıcı: 1 sn bekleme sonrası ikinci istek başarılı olur ve hata kartı hiç görünmez
    expect(
      await screen.findByText('Silikon Kek Kalıbı Set', {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(calls.filter((u) => u.pathname === `${base}/products`)).toHaveLength(2);
    expect(screen.queryByText(/Zarar eden ürünler şu an yüklenemedi/)).not.toBeInTheDocument();
  });

  it('"Tüm uyarılar (N)" bağlantısı uyarılar ekranına dönemi taşır (UX-08)', async () => {
    navigation.search = 'range=7d';
    renderSummary();
    render(<SummaryScreen />);
    await screen.findByText(/Zararına satış/);
    const link = screen.getByRole('link', { name: 'Tüm uyarılar (5)' });
    expect(link).toHaveAttribute('href', '/panel/uyarilar?range=7d');
  });

  it('uyarı yoksa "Tüm uyarılar" bağlantısı çıkmaz', async () => {
    renderSummary(makeTotals(), makeAlerts([]));
    render(<SummaryScreen />);
    await screen.findByText('Bu dönemde uyarı yok.');
    expect(screen.queryByRole('link', { name: /Tüm uyarılar/ })).not.toBeInTheDocument();
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
      makeItem({
        barcode: 'G7',
        title: 'Yalnız Reklamlı',
        net_profit: '-25.00',
        net_margin_percent: null,
        loss_reason: 'net_profit',
        certainty: 'yok',
        contribution_excl_missing: '-25.00',
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
    expect(
      within(card('Maliyetsiz Zarar')).getByText('Maliyet girilmese de zarar'),
    ).toBeInTheDocument();
    const known = card('Bilinen Giderle Zarar');
    expect(within(known).getByText('Bilinen giderlerle bile zarar')).toBeInTheDocument();
    // UX-10: eksik bilgi tek kaynakta; ayrıca "Kargo eksik" ya da "Bilgi eksik" rozeti yok
    expect(within(known).queryByText('Kargo eksik')).not.toBeInTheDocument();
    expect(within(known).queryByText('Bilgi eksik')).not.toBeInTheDocument();
    expect(within(card('Belirsiz Ürün')).queryByText('Bilgi eksik')).not.toBeInTheDocument();
    // Belirsiz ürün kârlı değil
    expect(within(card('Belirsiz Ürün')).getByText('Belirsiz')).toBeInTheDocument();

    // UX-07 ve Y-5: kesin zararlı ama net kârı null ürün nötr değil: kırmızı "En az ₺X zarar" (eksi işareti yok),
    // küçük "Net kâr hesaplanamadı" satırı ve eksik kalemler düşülünce rakamın azalacağı notu
    const missing = card('Maliyetsiz Zarar');
    expect(missing).toHaveTextContent('En az ₺12,00 zarar');
    expect(missing).not.toHaveTextContent('-₺12,00');
    expect(missing).toHaveTextContent('Net kâr hesaplanamadı');
    expect(missing).toHaveTextContent('Ürün maliyeti düşülünce bu rakam azalır.');
    expect(missing.querySelector('.text-loss')).not.toBeNull();
    expect(missing).not.toHaveTextContent('₺0,00');
    // Ekran okuyucu: görünen sözcükler aria-hidden, tek gizli metin; "zarar" iki kez okunmaz
    const hiddenLoss = Array.from(missing.querySelectorAll('[aria-hidden="true"]')).filter(
      (node) => node.textContent === 'En az ₺12,00 zarar',
    );
    expect(hiddenLoss).toHaveLength(1);
    expect(missing.querySelectorAll('.sr-only')[0]).toHaveTextContent('En az ₺12,00 zarar');
    expect(card('Bilinen Giderle Zarar')).toHaveTextContent(
      'Kargo ve hizmet bedeli düşülünce bu rakam azalır.',
    );
    expect(card('Bilinen Giderle Zarar')).toHaveTextContent('En az ₺4,00 zarar');

    // Belirsiz ürün: hesaplanamadı + eksik kalem adları (tek kaynak), bilinen kâr nötr
    const uncertain = card('Belirsiz Ürün');
    expect(uncertain).toHaveTextContent('Hesaplanamadı');
    expect(uncertain).toHaveTextContent('Eksik: kargo');
    expect(uncertain).toHaveTextContent('Eksik giderler hariç kâr: ₺75,00');
    expect(uncertain.querySelector('[data-sign]')).toBeNull();

    // İptal ürün 0,00 kâr değil
    const cancelled = card('Yalnız İptal');
    expect(cancelled).toHaveTextContent('İptal');
    expect(cancelled).not.toHaveTextContent('₺0,00 ');

    // Y-3: yalnız satışsız reklamı olan ürün (kesinlik yok, net kâr negatif, zarar nedeni dolu) zarardır
    const adOnly = card('Yalnız Reklamlı');
    expect(adOnly).not.toHaveTextContent('İptal');
    expect(adOnly).toHaveTextContent('-₺25,00');
    expect(adOnly.querySelector('[data-sign="negative"]')).not.toBeNull();
    expect(within(adOnly).getByText('Zarar')).toBeInTheDocument();

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
    // Zarar süzgecinde varsayılan yön artan (en çok zarar önce), bu yüzden bağlantıda order yok (UX-04)
    expect(screen.getByRole('link', { name: 'Zarar edenler' })).toHaveAttribute(
      'href',
      '/panel/urunler?range=7d&sort=sales&filter=loss',
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

  it('zarar süzgeci: yön verilmezse istek order=asc ile yapılır; yanlış "sonda" notu yok (Y-1)', async () => {
    navigation.search = 'range=7d&filter=loss';
    const { calls } = mockFetch(accounts, (url) =>
      url.pathname === productsPath
        ? { body: makeList([makeItem({ loss_reason: 'net_profit', net_profit: '-5.00' })]) }
        : undefined,
    );
    render(<ProductListScreen />);
    await screen.findAllByText('Örnek Ürün Çelik Termos 500 ml');
    const call = calls.find((u) => u.pathname === productsPath);
    expect(call?.searchParams.get('order')).toBe('asc');
    // Y-1: AD-04 ile eksikli zararlar bilinen tutarla doğru sıralanır; "listenin sonunda" notu yoktur
    expect(screen.queryByText(/listenin sonunda/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Tümü' })).toHaveAttribute(
      'href',
      '/panel/urunler?range=7d',
    );
    expect(screen.getByText('Ayar sürümü 7')).toBeInTheDocument();
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

describe('Ürün kırılımı özet kartı (UX-07, UX-09, UX-10, UX-14)', () => {
  const detailPath = `${base}/products/BRK-0001`;

  function renderWithProduct(over: Record<string, unknown>, detailOver = {}) {
    const detail = makeDetail([makeLine()], detailOver);
    detail.product = { ...detail.product!, ...over } as NonNullable<typeof detail.product>;
    mockFetch(accounts, (url) => (url.pathname === detailPath ? { body: detail } : undefined));
    return render(<ProductDetailScreen barcode="BRK-0001" />);
  }

  it('kargo iadesi, ceza, değişken gider ve reklam satırları gösterilir; satırlar toplamla tutar', async () => {
    renderWithProduct({
      net_satis_kdv_haric: '1000.00',
      urun_maliyeti: '400.00',
      komisyon: '150.00',
      kargo_gonderi: '100.00',
      kargo_iade: '20.00',
      platform_hizmet_bedeli: '30.00',
      ceza: '10.00',
      degisken_giderler: '15.00',
      reklam_satirlara_dagitilan: '25.00',
      net_kar: '250.00',
      eksik_giderler_haric_kar: '250.00',
    });
    const card = (await screen.findByRole('heading', { level: 2, name: 'Ürün net kârı' })).closest(
      'div',
    )?.parentElement as HTMLElement;
    for (const [label, value] of [
      ['Kargo iadesi', '₺20,00'],
      ['Ceza', '₺10,00'],
      ['Değişken giderler', '₺15,00'],
      ['Reklam', '₺25,00'],
    ] as const) {
      const term = within(card).getByText(label, { selector: 'dt' });
      expect(term.parentElement).toHaveTextContent(value);
    }
    // Toplam satırı: net kâr
    const total = within(card).getByText('Net kâr', { selector: 'dt' }).parentElement;
    expect(total).toHaveTextContent('₺250,00');
  });

  it('Y-6: kısmen eksik kalem bilinen tutarı da gösterir ("₺X + N satırda eksik")', async () => {
    renderWithProduct({
      kargo_gonderi: '225.00',
      net_kar: null,
      net_kar_marji_yuzde: null,
      eksik_kalem_satir_sayilari: { urun_maliyeti: 0, kargo_gonderi: 2, platform_hizmet_bedeli: 0 },
    });
    const card = (await screen.findByRole('heading', { level: 2, name: 'Ürün net kârı' })).closest(
      'div',
    )?.parentElement as HTMLElement;
    const term = within(card).getByText('Kargo (gönderi)', { selector: 'dt' });
    expect(term.parentElement).toHaveTextContent('₺225,00');
    expect(term.parentElement).toHaveTextContent('+ 2 satırda eksik');
  });

  it('Y-3: yalnız satışsız reklamı olan ürün (kesinlik yok) zarar gösterir, İptal yazmaz', async () => {
    renderWithProduct(
      {
        net_satis_kdv_haric: '0.00',
        urun_maliyeti: '0.00',
        komisyon: '0.00',
        kargo_gonderi: '0.00',
        platform_hizmet_bedeli: '0.00',
        reklam_satirlara_dagitilan: '0.00',
        reklam_satissiz: '25.00',
        net_kar: '-25.00',
        net_kar_marji_yuzde: null,
        eksik_giderler_haric_kar: '-25.00',
        kesinlik: 'yok',
      },
      { certainty: 'yok' },
    );
    const card = (await screen.findByRole('heading', { level: 2, name: 'Ürün net kârı' })).closest(
      'div',
    )?.parentElement as HTMLElement;
    expect(card).not.toHaveTextContent('İptal');
    expect(card).toHaveTextContent('-₺25,00');
    expect(card.querySelector('[data-sign="negative"]')).not.toBeNull();
    const term = within(card).getByText('Satış getirmeyen reklam', { selector: 'dt' });
    expect(term.parentElement).toHaveTextContent('₺25,00');
  });

  it('sıfır olan isteğe bağlı kalemler gizlenir', async () => {
    renderWithProduct({});
    const card = (await screen.findByRole('heading', { level: 2, name: 'Ürün net kârı' })).closest(
      'div',
    )?.parentElement as HTMLElement;
    expect(within(card).queryByText('Kargo iadesi')).not.toBeInTheDocument();
    expect(within(card).queryByText('Ceza')).not.toBeInTheDocument();
    expect(within(card).queryByText('Değişken giderler')).not.toBeInTheDocument();
    expect(within(card).queryByText(/^Reklam/)).not.toBeInTheDocument();
  });

  it('net kârı null kesin zarar: kırılımda da kırmızı bilinen kâr ve zarar rozeti, liste ile tutarlı', async () => {
    renderWithProduct(
      {
        net_kar: null,
        net_kar_marji_yuzde: null,
        eksik_giderler_haric_kar: '-4.00',
        eksik_kalem_satir_sayilari: {
          urun_maliyeti: 0,
          kargo_gonderi: 2,
          platform_hizmet_bedeli: 2,
        },
        kesinlik: 'eksik',
      },
      { certainty: 'eksik' },
    );
    const card = (await screen.findByRole('heading', { level: 2, name: 'Ürün net kârı' })).closest(
      'div',
    )?.parentElement as HTMLElement;
    expect(card).toHaveTextContent('Hesaplanamadı');
    expect(card).toHaveTextContent('Eksik: kargo, hizmet bedeli');
    expect(
      within(card).getByRole('heading', { level: 3, name: 'Eksik giderler hariç kâr' }),
    ).toBeInTheDocument();
    expect(card).toHaveTextContent('(kargo ve hizmet bedeli hariç)');
    expect(card).toHaveTextContent('-₺4,00');
    expect(card.querySelector('[data-sign="negative"]')).not.toBeNull();
    expect(within(card).getByText('Bilinen giderlerle bile zarar')).toBeInTheDocument();
    expect(card).toHaveTextContent('Kargo ve hizmet bedeli düşülünce bu rakam azalır.');
    // UX-10: ayrıca "Bilgi eksik" rozeti yok
    expect(within(card).queryByText('Bilgi eksik')).not.toBeInTheDocument();
  });

  it('net kârı null, bilinen kâr pozitif: nötr, yeşil ok yok ve "bu rakam azalır" notu (UX-21)', async () => {
    renderWithProduct({
      net_kar: null,
      net_kar_marji_yuzde: null,
      eksik_giderler_haric_kar: '80.00',
      eksik_kalem_satir_sayilari: { urun_maliyeti: 0, kargo_gonderi: 2, platform_hizmet_bedeli: 0 },
    });
    const card = (await screen.findByRole('heading', { level: 2, name: 'Ürün net kârı' })).closest(
      'div',
    )?.parentElement as HTMLElement;
    const block = within(card).getByRole('heading', { level: 3, name: 'Eksik giderler hariç kâr' })
      .parentElement as HTMLElement;
    expect(block).toHaveTextContent('₺80,00');
    expect(block.querySelector('[data-sign]')).toBeNull();
    expect(block).toHaveTextContent('Kargo düşülünce bu rakam azalır.');
    expect(within(card).queryByText('Bilinen giderlerle bile zarar')).not.toBeInTheDocument();
  });

  it('alt bilgide ayar sürümü gösterilir; alan yoksa gösterilmez', async () => {
    renderWithProduct({});
    expect(await screen.findByText('Ayar sürümü 7')).toBeInTheDocument();
  });

  it('eski API (settings_revision yok): alt bilgi çıkmaz', async () => {
    const detail = makeDetail([makeLine()]);
    delete detail.settings_revision;
    mockFetch(accounts, (url) => (url.pathname === detailPath ? { body: detail } : undefined));
    render(<ProductDetailScreen barcode="BRK-0001" />);
    await screen.findByRole('heading', { level: 2, name: 'Ürün net kârı' });
    expect(screen.queryByText(/Ayar sürümü/)).not.toBeInTheDocument();
  });
});
