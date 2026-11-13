import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { OrderListScreen } from '@/components/profit/order-list';
import { mockFetch, problem } from '@/test/api-mock';
import {
  ACCOUNT_ID,
  PERIOD,
  makeAccounts,
  makeLine,
  makeOrderDetail,
  makeOrderItem,
  makeOrderList,
} from '@/lib/profit/test-fixtures';

const navigation = vi.hoisted(() => ({ search: '', replace: vi.fn() }));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
  useRouter: () => ({ replace: navigation.replace, push: vi.fn() }),
  usePathname: () => '/panel/siparisler',
}));

const accounts = (url: URL) =>
  url.pathname === '/api/v1/marketplace-accounts' ? { body: makeAccounts() } : undefined;
const base = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/profit`;

const ITEMS = [
  makeOrderItem({
    order_number: '10001',
    products: [
      { barcode: 'A', title: 'Çelik Termos' },
      { barcode: 'B', title: '<b>Kalın</b> Bardak' },
    ],
    more_product_count: 3,
    certainty: 'tahmini',
    awaiting_payout: true,
  }),
  makeOrderItem({
    order_number: '10002',
    cancelled: true,
    net_profit: null,
    net_sales_excl_vat: null,
    known_expenses_profit: null,
    certainty: 'iptal',
    line_count: 0,
    cancelled_line_count: 1,
  }),
  makeOrderItem({
    order_number: '10003',
    net_profit: null,
    known_expenses_profit: '75.00',
    missing_items: ['kargo_gonderi'],
    certainty: 'eksik',
    ordered_on: null,
  }),
  makeOrderItem({
    order_number: '10004',
    net_profit: '-30.00',
    loss_reason: 'net_profit',
    unexpected_deduction: true,
  }),
];

beforeEach(() => {
  navigation.search = '';
  navigation.replace.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Siparişler ekranı', () => {
  it('yükleniyor durumu duyurulur', async () => {
    mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders` ? { body: makeOrderList([]) } : undefined,
    );
    render(<OrderListScreen />);
    expect(screen.getByRole('status')).toHaveTextContent('Yükleniyor');
    await screen.findByText('Bu dönemde sipariş yok');
  });

  it('mağaza yoksa bağlama çağrısı gösterir, sipariş çağrısı yapmaz', async () => {
    const { calls } = mockFetch((url) =>
      url.pathname === '/api/v1/marketplace-accounts' ? { body: [] } : undefined,
    );
    render(<OrderListScreen />);
    expect(await screen.findByText('Mağaza bağlı değil')).toBeInTheDocument();
    expect(calls.some((u) => u.pathname === `${base}/orders`)).toBe(false);
  });

  it('kartlar: ilk 2 ürün + "N ürün daha", null net kâr, iptal, rozetler; HTML metin olarak basılır', async () => {
    const { calls } = mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders` ? { body: makeOrderList(ITEMS) } : undefined,
    );
    const { container } = render(<OrderListScreen />);
    const list = await screen.findByRole('list', { name: 'Sipariş listesi' });
    expect(
      within(list)
        .getAllByRole('heading', { level: 2 })
        .map((h) => h.textContent),
    ).toEqual(['Sipariş 10001', 'Sipariş 10002', 'Sipariş 10003', 'Sipariş 10004']);

    const first = within(list)
      .getByRole('heading', { name: 'Sipariş 10001' })
      .closest('div')!.parentElement!;
    expect(within(first).getByText('Çelik Termos')).toBeInTheDocument();
    expect(within(first).getByText('<b>Kalın</b> Bardak')).toBeInTheDocument();
    expect(first).toHaveTextContent('3 ürün daha');
    expect(first).toHaveTextContent('09.11.2026');
    expect(within(first).getByText('Tahmini')).toBeInTheDocument();
    expect(within(first).getByText('Ekstresi gelmedi')).toBeInTheDocument();
    expect(container.querySelector('b')).toBeNull();

    // İptal: rakam yok, "İptal"
    const cancelled = within(list)
      .getByRole('heading', { name: 'Sipariş 10002' })
      .closest('div')!.parentElement!;
    expect(within(cancelled).getByText('İptal')).toBeInTheDocument();
    expect(cancelled).not.toHaveTextContent('₺');
    expect(cancelled).not.toHaveTextContent('0,00');

    // Null net kâr: Hesaplanamadı + eksik kalemler + etiketli bilinen kâr, tarih yok
    const unknown = within(list)
      .getByRole('heading', { name: 'Sipariş 10003' })
      .closest('div')!.parentElement!;
    expect(unknown).toHaveTextContent('Hesaplanamadı');
    expect(unknown).toHaveTextContent('Eksik: kargo');
    expect(unknown).toHaveTextContent('Eksik giderler hariç kâr:');
    expect(unknown).toHaveTextContent('₺75,00');
    expect(unknown).toHaveTextContent('Tarih yok');

    // Zarar: kırmızı değer ve rozet; beklenmeyen kesinti rozeti
    const loss = within(list)
      .getByRole('heading', { name: 'Sipariş 10004' })
      .closest('div')!.parentElement!;
    expect(within(loss).getByText('Zarar', { exact: true })).toBeInTheDocument();
    expect(within(loss).getByText('Beklenmeyen kesinti')).toBeInTheDocument();
    expect(loss).toHaveTextContent('-₺30,00');

    const request = calls.find((u) => u.pathname === `${base}/orders`)!;
    expect(request.searchParams.get('range')).toBe('30d');
    expect(request.searchParams.get('sort')).toBe('date');
    expect(request.searchParams.get('order')).toBe('desc');
    expect(request.searchParams.get('filter')).toBe('all');
    expect(request.searchParams.has('q')).toBe(false);
    expect(screen.getByText('Ayar sürümü 7')).toBeInTheDocument();
  });

  it('süzgeç bağlantıları ve sorgu: zarar edenler net kâr artan; ekstresi gelmeyen etiketi', async () => {
    navigation.search = 'filter=loss&range=7d';
    const { calls } = mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders` ? { body: makeOrderList([ITEMS[3]!]) } : undefined,
    );
    render(<OrderListScreen />);
    await screen.findByRole('list', { name: 'Sipariş listesi' });
    const nav = screen.getByRole('navigation', { name: 'Sipariş süzgeci' });
    expect(within(nav).getByRole('link', { name: 'Zarar edenler' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(within(nav).getByRole('link', { name: 'Ekstresi gelmeyen' })).toHaveAttribute(
      'href',
      '/panel/siparisler?range=7d&filter=awaiting_payout',
    );
    expect(within(nav).getByRole('link', { name: 'Beklenmeyen kesinti' })).toHaveAttribute(
      'href',
      '/panel/siparisler?range=7d&filter=unexpected_deduction',
    );
    expect(within(nav).getByRole('link', { name: 'Tümü' })).toHaveAttribute(
      'href',
      '/panel/siparisler?range=7d',
    );
    expect(screen.queryByText(/hakediş bekleyen/i)).not.toBeInTheDocument();
    const request = calls.find((u) => u.pathname === `${base}/orders`)!;
    expect(request.searchParams.get('filter')).toBe('loss');
    expect(request.searchParams.get('sort')).toBe('net_profit');
    expect(request.searchParams.get('order')).toBe('asc');
    expect(request.searchParams.get('range')).toBe('7d');
  });

  it('arama: tam eşleşme isteği q ile gider; geçersiz girdide istek atılmaz', async () => {
    navigation.search = 'q=10004';
    const { calls } = mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders`
        ? { body: makeOrderList([ITEMS[3]!], { q: '10004' }) }
        : undefined,
    );
    render(<OrderListScreen />);
    await screen.findByRole('list', { name: 'Sipariş listesi' });
    expect(calls.find((u) => u.pathname === `${base}/orders`)!.searchParams.get('q')).toBe('10004');
    expect(screen.getByText(/aranan:/)).toBeInTheDocument();

    const input = screen.getByRole('searchbox', { name: 'Sipariş no' });
    expect(input).toHaveValue('10004');
    await userEvent.clear(input);
    await userEvent.type(input, 'a b');
    await userEvent.click(screen.getByRole('button', { name: 'Ara' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('harf ya da rakamla başlamalı');
    expect(input).toBeInvalid();
    expect(navigation.replace).not.toHaveBeenCalled();

    await userEvent.clear(input);
    await userEvent.type(input, '20002');
    await userEvent.click(screen.getByRole('button', { name: 'Ara' }));
    expect(navigation.replace).toHaveBeenCalledWith('/panel/siparisler?range=30d&q=20002', {
      scroll: false,
    });
    await userEvent.click(screen.getByRole('button', { name: 'Aramayı temizle' }));
    expect(navigation.replace).toHaveBeenLastCalledWith('/panel/siparisler?range=30d', {
      scroll: false,
    });
  });

  it('adı olmayan ürünler kartta barkoduyla ayırt edilir (OS-08)', async () => {
    mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders`
        ? {
            body: makeOrderList([
              makeOrderItem({
                order_number: '30001',
                products: [
                  { barcode: 'BRK-1', title: null },
                  { barcode: 'BRK-2', title: '' },
                ],
              }),
            ]),
          }
        : undefined,
    );
    render(<OrderListScreen />);
    expect(await screen.findByText('Başlıksız ürün (barkod BRK-1)')).toBeInTheDocument();
    expect(screen.getByText('Başlıksız ürün (barkod BRK-2)')).toBeInTheDocument();
  });

  it('bağlantıdaki geçersiz arama yok sayılır ve role=status ile söylenir (OS-09)', async () => {
    navigation.search = 'q=ab%20cd';
    const { calls } = mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders` ? { body: makeOrderList([ITEMS[3]!]) } : undefined,
    );
    render(<OrderListScreen />);
    await screen.findByRole('list', { name: 'Sipariş listesi' });
    expect(calls.find((u) => u.pathname === `${base}/orders`)!.searchParams.has('q')).toBe(false);
    expect(screen.getByText(/arama metni geçerli olmadığı için yok sayıldı/)).toHaveAttribute(
      'role',
      'status',
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('geçerli ya da boş aramada yok sayıldı bildirimi çıkmaz', async () => {
    navigation.search = 'q=10004';
    mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders`
        ? { body: makeOrderList([ITEMS[3]!], { q: '10004' }) }
        : undefined,
    );
    render(<OrderListScreen />);
    await screen.findByRole('list', { name: 'Sipariş listesi' });
    expect(screen.queryByText(/yok sayıldı/)).not.toBeInTheDocument();
  });

  it('arama sonucu boşsa numarayı bulamadığını söyler', async () => {
    navigation.search = 'q=99999';
    mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders` ? { body: makeOrderList([], { q: '99999' }) } : undefined,
    );
    render(<OrderListScreen />);
    expect(await screen.findByText('Bu numarada sipariş bulunamadı')).toBeInTheDocument();
  });

  it('boş durum süzgece göre', async () => {
    navigation.search = 'filter=awaiting_payout';
    mockFetch(accounts, (url) =>
      url.pathname === `${base}/orders` ? { body: makeOrderList([]) } : undefined,
    );
    render(<OrderListScreen />);
    expect(await screen.findByText('Ekstresi gelmeyen sipariş yok')).toBeInTheDocument();
  });

  it('hata durumunda ayrıntı yok, Tekrar dene çalışır', async () => {
    let fail = true;
    mockFetch(accounts, (url) => {
      if (url.pathname !== `${base}/orders`) return undefined;
      return fail ? problem(500, 'internal-error') : { body: makeOrderList(ITEMS) };
    });
    render(<OrderListScreen />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Siparişler yüklenemedi');
    expect(alert).not.toHaveTextContent('internal-error');
    fail = false;
    await userEvent.click(within(alert).getByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByRole('list', { name: 'Sipariş listesi' })).toBeInTheDocument();
  });

  it('imleçli sayfa: daha fazla yükle ikinci sayfayı imleçle ister ve ekler', async () => {
    const { calls } = mockFetch(accounts, (url) => {
      if (url.pathname !== `${base}/orders`) return undefined;
      return url.searchParams.get('cursor')
        ? { body: makeOrderList([ITEMS[3]!], { total_count: 2, next_cursor: null }) }
        : { body: makeOrderList([ITEMS[0]!], { total_count: 2, next_cursor: 'sonraki' }) };
    });
    render(<OrderListScreen />);
    await screen.findByRole('heading', { name: 'Sipariş 10001' });
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla yükle' }));
    expect(await screen.findByRole('heading', { name: 'Sipariş 10004' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sipariş 10001' })).toBeInTheDocument();
    const second = calls.filter((u) => u.pathname === `${base}/orders`)[1]!;
    expect(second.searchParams.get('cursor')).toBe('sonraki');
    expect(screen.queryByRole('button', { name: 'Daha fazla yükle' })).not.toBeInTheDocument();
  });

  it('imleç geçersizse liste baştan yüklenir ve haber verilir', async () => {
    let calls = 0;
    mockFetch(accounts, (url) => {
      if (url.pathname !== `${base}/orders`) return undefined;
      calls += 1;
      if (calls === 1) {
        return { body: makeOrderList([ITEMS[0]!], { total_count: 2, next_cursor: 'eski' }) };
      }
      if (calls === 2)
        return problem(422, 'validation', [{ field: 'cursor', code: 'cursor_invalid' }]);
      return { body: makeOrderList([ITEMS[0]!, ITEMS[3]!]) };
    });
    render(<OrderListScreen />);
    await screen.findByRole('heading', { name: 'Sipariş 10001' });
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla yükle' }));
    expect(
      await screen.findByText('Liste güncellendiği için baştan yüklendi.'),
    ).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Sipariş 10004' })).toBeInTheDocument();
  });

  it('429 yanıtında Retry-After kadar bekleyip bir kez yeniden dener', async () => {
    let orderCalls = 0;
    mockFetch(accounts, (url) => {
      if (url.pathname !== `${base}/orders`) return undefined;
      orderCalls += 1;
      return orderCalls === 1
        ? { ...problem(429, 'rate-limited'), headers: { 'Retry-After': '1' } }
        : { body: makeOrderList([ITEMS[0]!]) };
    });
    render(<OrderListScreen />);
    expect(
      await screen.findByRole('heading', { name: 'Sipariş 10001' }, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(orderCalls).toBe(2);
    expect(screen.queryByText('Siparişler yüklenemedi')).not.toBeInTheDocument();
  });

  it('kalem dökümü: listedeki dönemle (start/end) detay ucu çağrılır, satır kartı gösterilir', async () => {
    const { calls } = mockFetch(
      accounts,
      (url) =>
        url.pathname === `${base}/orders` ? { body: makeOrderList([ITEMS[0]!]) } : undefined,
      (url) =>
        url.pathname === `${base}/orders/10001`
          ? { body: makeOrderDetail([makeLine({ orderNumber: '10001', barcode: 'A' })]) }
          : undefined,
    );
    render(<OrderListScreen />);
    const button = await screen.findByRole('button', { name: /Kalem dökümünü göster/ });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(calls.some((u) => u.pathname === `${base}/orders/10001`)).toBe(false);
    await userEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByRole('heading', { level: 3, name: 'Ürün A' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /kalem kırılımı/ })).toBeInTheDocument();
    const detail = calls.find((u) => u.pathname === `${base}/orders/10001`)!;
    expect(detail.searchParams.get('start')).toBe(PERIOD.start);
    expect(detail.searchParams.get('end')).toBe(PERIOD.end);
    expect(detail.searchParams.has('range')).toBe(false);
  });

  it('kalem dökümü hatasında Tekrar dene sunulur, liste korunur', async () => {
    let fail = true;
    mockFetch(
      accounts,
      (url) =>
        url.pathname === `${base}/orders` ? { body: makeOrderList([ITEMS[0]!]) } : undefined,
      (url) => {
        if (url.pathname !== `${base}/orders/10001`) return undefined;
        return fail ? problem(404, 'not-found') : { body: makeOrderDetail([makeLine()]) };
      },
    );
    render(<OrderListScreen />);
    await userEvent.click(await screen.findByRole('button', { name: /Kalem dökümünü göster/ }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('İstenen kayıt bulunamadı.');
    fail = false;
    await userEvent.click(within(alert).getByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByRole('table', { name: /kalem kırılımı/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sipariş 10001' })).toBeInTheDocument();
  });
});
