import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AlertsScreen } from '@/components/profit/alerts-view';
import { mockFetch, problem } from '@/test/api-mock';
import { ACCOUNT_ID, makeAccounts, makeAlertItem, makeAlerts } from '@/lib/profit/test-fixtures';

const navigation = vi.hoisted(() => ({ search: '' }));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => '/panel/uyarilar',
}));

const accounts = (url: URL) =>
  url.pathname === '/api/v1/marketplace-accounts' ? { body: makeAccounts() } : undefined;
const alertsPath = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/profit/alerts`;

const MANY = [
  { code: 'MALIYET_EKSIK', count: 2, message: 'm' },
  { code: 'ZARAR', count: 3, message: 'z' },
  { code: 'BEKLENMEYEN_KESINTI', count: 2, message: 'b' },
  { code: 'KARGO_TARIFESI_EKSIK', count: 4, message: 'k' },
  { code: 'HIZMET_BEDELI_TAHMINI_EKSIK', count: 4, message: 'h' },
  { code: 'IADE_KAYDI_BEKLENIYOR', count: 1, message: 'i' },
  { code: 'KARGO_EKSIK_SATIRLAR_VAR', count: 1, message: 'p' },
];

beforeEach(() => {
  navigation.search = '';
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Uyarılar ekranı', () => {
  it('yükleniyor durumu duyurulur', async () => {
    mockFetch(accounts, (url) =>
      url.pathname === alertsPath ? { body: makeAlerts([]) } : undefined,
    );
    render(<AlertsScreen />);
    expect(screen.getByRole('status')).toHaveTextContent('Yükleniyor');
    await screen.findByText('Bu dönemde uyarı yok');
  });

  it('mağaza yoksa bağlama çağrısı gösterir, uyarı çağrısı yapmaz', async () => {
    const { calls } = mockFetch((url) =>
      url.pathname === '/api/v1/marketplace-accounts' ? { body: [] } : undefined,
    );
    render(<AlertsScreen />);
    expect(await screen.findByText('Trendyol mağazanızı bağlayın')).toBeInTheDocument();
    expect(calls.some((u) => u.pathname === alertsPath)).toBe(false);
  });

  it('boş durum: uyarı yok ve henüz hesaplanmayanlar', async () => {
    mockFetch(accounts, (url) =>
      url.pathname === alertsPath
        ? {
            body: makeAlerts([], {
              not_yet_available: [
                { code: 'REKLAM_KARI_YIYOR', reason: 'ad_spend yok' },
                { code: 'IADE_ORANI_ARTISI', reason: 'S6' },
              ],
            }),
          }
        : undefined,
    );
    render(<AlertsScreen />);
    expect(await screen.findByRole('heading', { name: 'Bu dönemde uyarı yok' })).toBeVisible();
    expect(screen.getByText('Reklam kârı yiyor')).toBeInTheDocument();
    expect(screen.getByText('İade oranı artışı')).toBeInTheDocument();
    // Sistem gerekçesi kullanıcıya gösterilmez
    expect(screen.queryByText(/ad_spend/)).not.toBeInTheDocument();
    expect(screen.getByText('Ayar sürümü 7')).toBeInTheDocument();
  });

  it('hata durumunda ayrıntı yok, Tekrar dene çalışır', async () => {
    let fail = true;
    mockFetch(accounts, (url) => {
      if (url.pathname !== alertsPath) return undefined;
      return fail ? problem(500, 'internal-error') : { body: makeAlerts([]) };
    });
    render(<AlertsScreen />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Uyarılar yüklenemedi');
    expect(alert).not.toHaveTextContent('internal-error');
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByText('Bu dönemde uyarı yok')).toBeInTheDocument();
  });

  it('çok kodlu durum: gruplar sırayla, kartlarda sayı, cümle ve tek eylem', async () => {
    navigation.search = 'range=7d';
    const { calls } = mockFetch(accounts, (url) =>
      url.pathname === alertsPath ? { body: makeAlerts(MANY) } : undefined,
    );
    render(<AlertsScreen />);
    await screen.findByRole('heading', { name: 'Para kaybettirenler' });
    const groupHeadings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(groupHeadings).toEqual(['Para kaybettirenler', 'Kurulum', 'Bilgi ve kontrol']);

    const loss = screen.getByRole('region', { name: 'Para kaybettirenler' });
    const cardTitles = within(loss)
      .getAllByRole('heading', { level: 3 })
      .map((h) => h.textContent);
    expect(cardTitles).toEqual(['Zarar eden satışlar', 'Beklenmeyen kesintiler']);
    expect(within(loss).getByText('3')).toBeInTheDocument();
    expect(within(loss).getByRole('link', { name: 'Zarar eden ürünleri gör' })).toHaveAttribute(
      'href',
      '/panel/urunler?range=7d&filter=loss',
    );

    const setup = screen.getByRole('region', { name: 'Kurulum' });
    expect(
      within(setup).getByRole('link', { name: 'Maliyeti eksik ürünleri gör' }),
    ).toHaveAttribute('href', '/panel/urunler?range=7d&filter=missing_cost');
    expect(
      within(setup)
        .getAllByRole('link', { name: 'Kargo tarifesini gir' })
        .map((a) => a.getAttribute('href')),
    ).toEqual(['/panel/ayarlar#kargo', '/panel/ayarlar#kargo']);
    expect(within(setup).getByRole('link', { name: 'Hizmet bedelini gir' })).toHaveAttribute(
      'href',
      '/panel/ayarlar#hizmet-bedeli',
    );
    // Dönem geneli uyarıda sayı yerine "Dönem geneli" yazar
    expect(within(setup).getByText('Dönem geneli')).toBeInTheDocument();

    // İade kaydı: bilgi tonu, eylem yok
    const check = screen.getByRole('region', { name: 'Bilgi ve kontrol' });
    expect(within(check).getByText('İade kaydı bekleniyor')).toBeInTheDocument();
    expect(within(check).queryByRole('link')).not.toBeInTheDocument();
    expect(within(check).queryByRole('button')).not.toBeInTheDocument();

    // Ayrıntı listesi kart açılmadan istenmez
    expect(calls.filter((u) => u.searchParams.has('code'))).toHaveLength(0);
    expect(calls.find((u) => u.pathname === alertsPath)?.searchParams.get('range')).toBe('7d');
  });

  it('beklenmeyen kesinti: sipariş, ürün bağlantısı, fark; daha fazla yükle', async () => {
    mockFetch(accounts, (url) => {
      if (url.pathname !== alertsPath) return undefined;
      if (url.searchParams.get('code') === 'BEKLENMEYEN_KESINTI') {
        const cursor = url.searchParams.get('cursor');
        return {
          body: makeAlerts(MANY, {
            items: cursor
              ? [makeAlertItem({ order_number: '20002', line_id: 2, barcode: 'B/2' })]
              : [makeAlertItem()],
            next_cursor: cursor ? null : 'sonraki',
          }),
        };
      }
      return { body: makeAlerts(MANY) };
    });
    render(<AlertsScreen />);
    const button = await screen.findByRole('button', { name: 'Etkilenen siparişleri göster' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    const list = await screen.findByRole('list', { name: 'Etkilenen siparişler' });
    expect(within(list).getByText('10004')).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: 'Ürün: BRK-0001' })).toHaveAttribute(
      'href',
      '/panel/urunler/BRK-0001?range=30d',
    );
    expect(list).toHaveTextContent('₺75,00');
    expect(list).toHaveTextContent('₺5,00 altındaki farkları göstermiyoruz');
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla yükle' }));
    expect(await screen.findByText('20002')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ürün: B/2' })).toHaveAttribute(
      'href',
      '/panel/urunler/B%2F2?range=30d',
    );
    expect(screen.queryByRole('button', { name: 'Daha fazla yükle' })).not.toBeInTheDocument();
  });

  it('ayrıntı listesi hatasında Tekrar dene ve kart sayımları korunur', async () => {
    let fail = true;
    mockFetch(accounts, (url) => {
      if (url.pathname !== alertsPath) return undefined;
      if (url.searchParams.get('code')) {
        return fail
          ? problem(503, 'busy')
          : { body: makeAlerts(MANY, { items: [makeAlertItem()] }) };
      }
      return { body: makeAlerts(MANY) };
    });
    render(<AlertsScreen />);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Etkilenen siparişleri göster' }),
    );
    expect(await screen.findByText(/Rapor şu an yoğun/)).toBeInTheDocument();
    fail = false;
    const retry = screen.getAllByRole('button', { name: 'Tekrar dene' });
    await userEvent.click(retry[retry.length - 1]!);
    expect(await screen.findByText('10004')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Zarar eden satışlar' })).toBeInTheDocument();
  });

  it('bilinmeyen kod genel kartta, HTML metin olarak basılır, çökmez', async () => {
    mockFetch(accounts, (url) =>
      url.pathname === alertsPath
        ? {
            body: makeAlerts([
              { code: 'ZARAR', count: 1, message: 'z' },
              { code: 'YENI_UYARI', count: 7, message: '<b>kalın</b> yeni uyarı' },
            ]),
          }
        : undefined,
    );
    const { container } = render(<AlertsScreen />);
    const other = await screen.findByRole('region', { name: 'Diğer uyarılar' });
    expect(within(other).getByRole('heading', { name: 'Tanınmayan uyarı' })).toBeInTheDocument();
    expect(within(other).getByText('<b>kalın</b> yeni uyarı')).toBeInTheDocument();
    expect(within(other).getByText('YENI_UYARI')).toBeInTheDocument();
    expect(container.querySelector('b')).toBeNull();
    expect(within(other).queryByRole('link')).not.toBeInTheDocument();
  });
});
