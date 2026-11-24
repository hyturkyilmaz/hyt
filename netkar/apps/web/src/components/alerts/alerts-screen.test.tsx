import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AlertsScreen } from '@/components/alerts/alerts-screen';
import {
  DEDUCTION_EVENT,
  EVENT_ID_1,
  EVENT_ID_2,
  makeEvent,
  makeEventList,
} from '@/lib/alerts/test-fixtures';
import { ACCOUNT_ID, makeAccounts } from '@/lib/profit/test-fixtures';
import { mockRequests, problemReply, type Route } from '@/test/request-mock';

const navigation = vi.hoisted(() => ({ search: '' }));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => '/panel/uyarilar',
}));

const base = `/api/v1/marketplace-accounts/${ACCOUNT_ID}`;
const EVENTS = `${base}/alert-events`;

const accounts: Route = (r) =>
  r.url.pathname === '/api/v1/marketplace-accounts' ? { body: makeAccounts() } : undefined;
const me =
  (role: string, verified = true): Route =>
  (r) =>
    r.url.pathname === '/api/v1/me'
      ? { body: { role, email: 'ad@ornek.com', email_verified: verified } }
      : undefined;
const csrf: Route = (r) =>
  r.url.pathname === '/api/v1/auth/csrf' ? { body: { csrf_token: 'test-csrf' } } : undefined;
const events =
  (build: (status: string | null, cursor: string | null) => unknown): Route =>
  (r) =>
    r.method === 'GET' && r.url.pathname === EVENTS
      ? {
          body: build(r.url.searchParams.get('status'), r.url.searchParams.get('cursor')),
        }
      : undefined;

beforeEach(() => {
  navigation.search = '';
  document.cookie = '__Host-nk_csrf=test-csrf; path=/';
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function transitions(requests: { method: string; url: URL }[]) {
  return requests.filter((r) => r.method === 'POST');
}

describe('Uyarılar sayfası: sekmeler', () => {
  it('varsayılan sekme açık: durum süzgeci open ile D6 listesini ister, kart içeriği görünür', async () => {
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([makeEvent()])),
    );
    render(<AlertsScreen />);
    const card = await screen.findByRole('region', { name: /Zararına satış/ });
    expect(
      requests.some(
        (r) => r.url.pathname === EVENTS && r.url.searchParams.get('status') === 'open',
      ),
    ).toBe(true);
    expect(within(card).getByText('Ürün BRK-0001')).toBeVisible();
    expect(within(card).getByText('3 satırda zarar var.')).toBeVisible();
    expect(within(card).getByText('₺412,30')).toBeVisible();
    expect(within(card).getByText('10 Kasım 2026, 09:05')).toBeVisible();
    expect(within(card).getByText('12 Kasım 2026, 14:30')).toBeVisible();
    expect(screen.getByRole('heading', { level: 1, name: 'Uyarılar' })).toBeVisible();
    expect(screen.getByRole('heading', { level: 2, name: 'Açık uyarılar' })).toBeVisible();
  });

  it('beş sekme bağlantısı vardır; açık sekme etkin ve etiketinde açık sayısı yazar', async () => {
    mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([makeEvent()], { open_count: 3 })),
    );
    render(<AlertsScreen />);
    const nav = await screen.findByRole('navigation', { name: 'Uyarı sekmeleri' });
    await within(nav).findByRole('link', { name: 'Açık (3)' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((l) => l.textContent)).toEqual([
      'Açık (3)',
      'Okundu',
      'Susturulmuş',
      'Çözülmüş',
      'Tümü',
      'Dönem dökümü',
    ]);
    expect(links[0]).toHaveAttribute('aria-current', 'true');
    expect(links[1]).toHaveAttribute('href', '/panel/uyarilar?sekme=okundu');
    expect(links[4]).toHaveAttribute('href', '/panel/uyarilar?sekme=tumu');
    expect(links[5]).toHaveAttribute('href', '/panel/uyarilar?sekme=donem');
  });

  it.each([
    ['okundu', 'read'],
    ['susturulmus', 'muted'],
    ['cozuldu', 'resolved'],
  ])('%s sekmesi durum süzgecini %s olarak gönderir', async (tab, status) => {
    navigation.search = `sekme=${tab}`;
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([])),
    );
    render(<AlertsScreen />);
    await waitFor(() =>
      expect(
        requests.some(
          (r) => r.url.pathname === EVENTS && r.url.searchParams.get('status') === status,
        ),
      ).toBe(true),
    );
  });

  it('dönem dökümü sekmesi eski rapor içeriğini gösterir ve olay listesini istemez', async () => {
    navigation.search = 'sekme=donem';
    const { requests } = mockRequests(accounts, me('owner'), (r) =>
      r.url.pathname === `${base}/profit/alerts`
        ? {
            body: {
              period: { start: '2026-10-12', end: '2026-11-10', days: 30 },
              counts: [],
              items: [],
              next_cursor: null,
              settings_revision: 7,
            },
          }
        : undefined,
    );
    render(<AlertsScreen />);
    expect(await screen.findByText('Bu dönemde uyarı yok')).toBeVisible();
    expect(requests.some((r) => r.url.pathname === EVENTS)).toBe(false);
  });

  it('boş açık sekme: son değerlendirme zamanını söyler', async () => {
    mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([])),
    );
    render(<AlertsScreen />);
    expect(await screen.findByRole('heading', { name: 'Açık uyarı yok' })).toBeVisible();
    expect(screen.getByText('Son değerlendirme: 13 Kasım 2026, 06:47.')).toBeVisible();
  });

  it('boş çözülmüş sekme kendi açıklamasını verir', async () => {
    navigation.search = 'sekme=cozuldu';
    mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([])),
    );
    render(<AlertsScreen />);
    expect(await screen.findByRole('heading', { name: 'Çözüldü uyarı yok' })).toBeVisible();
  });

  it('mağaza yoksa bağlama çağrısı gösterir, olay listesi istemez', async () => {
    const { requests } = mockRequests(
      (r) => (r.url.pathname === '/api/v1/marketplace-accounts' ? { body: [] } : undefined),
      me('owner'),
    );
    render(<AlertsScreen />);
    expect(await screen.findByText('Trendyol mağazanızı bağlayın')).toBeVisible();
    expect(requests.some((r) => r.url.pathname === EVENTS)).toBe(false);
  });

  it('imleçle daha fazla yükle: ikinci istek next_cursor ile gider, kartlar eklenir', async () => {
    const second = makeEvent({ id: EVENT_ID_2, subject: 'urun:BRK-0099' });
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      events((_status, cursor) =>
        cursor === null
          ? makeEventList([makeEvent()], { next_cursor: 'imlec-1', open_count: 2 })
          : makeEventList([second], { open_count: 2 }),
      ),
    );
    render(<AlertsScreen />);
    await screen.findByText('Ürün BRK-0001');
    await userEvent.click(screen.getByRole('button', { name: 'Daha fazla yükle' }));
    expect(await screen.findByText('Ürün BRK-0099')).toBeVisible();
    const cursorCalls = requests.filter((r) => r.url.searchParams.get('cursor') === 'imlec-1');
    expect(cursorCalls).toHaveLength(1);
    expect(cursorCalls[0]?.url.searchParams.get('status')).toBe('open');
    expect(screen.queryByRole('button', { name: 'Daha fazla yükle' })).not.toBeInTheDocument();
  });

  it('liste 429 verirse Retry-After süresi gösterilir', async () => {
    mockRequests(accounts, me('owner'), (r) =>
      r.url.pathname === EVENTS
        ? problemReply(429, 'rate-limited', { 'Retry-After': '600' })
        : undefined,
    );
    render(<AlertsScreen />);
    expect(
      await screen.findByText(
        'Çok fazla deneme yaptınız. Yaklaşık 10 dakika sonra tekrar deneyin.',
      ),
    ).toBeVisible();
  });
});

describe('Uyarılar sayfası: eylemler', () => {
  it('okundu işaretle: geçiş gövdesi {to: read}, kart listeden çıkar, sayaç düşer', async () => {
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      csrf,
      events(() => makeEventList([makeEvent()], { open_count: 1 })),
      (r) =>
        r.method === 'POST' && r.url.pathname === `${EVENTS}/${EVENT_ID_1}/transitions`
          ? { body: { event: makeEvent({ status: 'read' }), transition_id: 't1' } }
          : undefined,
    );
    render(<AlertsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Okundu işaretle' }));
    expect(await screen.findByText('Uyarı okundu olarak işaretlendi.')).toBeVisible();
    const posts = transitions(requests);
    expect(posts).toHaveLength(1);
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({ to: 'read' });
    expect(screen.queryByRole('region', { name: /Zararına satış/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Açık (0)' })).toBeVisible();
  });

  it('susturma formu: 1-90 dışı değer isteği göndermez, geçerli değer muted_days ile gider', async () => {
    const { requests } = mockRequests(
      accounts,
      me('admin'),
      csrf,
      events(() => makeEventList([makeEvent()])),
      (r) =>
        r.method === 'POST'
          ? { body: { event: makeEvent({ status: 'muted' }), transition_id: 't2' } }
          : undefined,
    );
    render(<AlertsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Sustur' }));
    const input = screen.getByLabelText('Susturma süresi (gün)');
    expect(input).toHaveValue('7');

    await userEvent.clear(input);
    await userEvent.type(input, '91');
    await userEvent.click(screen.getByRole('button', { name: 'Uyarıyı sustur' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('1 ile 90 arasında');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(transitions(requests)).toHaveLength(0);

    await userEvent.clear(input);
    await userEvent.type(input, '14');
    await userEvent.click(screen.getByRole('button', { name: 'Uyarıyı sustur' }));
    expect(await screen.findByText('Uyarı 14 gün susturuldu.')).toBeVisible();
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({
      to: 'muted',
      muted_days: 14,
    });
  });

  it('viewer: susturma düğmesi yerine not, okundu işaretleme açık', async () => {
    mockRequests(
      accounts,
      me('viewer'),
      events(() => makeEventList([makeEvent()])),
    );
    render(<AlertsScreen />);
    expect(await screen.findByRole('button', { name: 'Okundu işaretle' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Sustur' })).not.toBeInTheDocument();
    expect(screen.getByText('Hesap yöneticiniz susturabilir.')).toBeVisible();
  });

  it('susturulmuş sekme: yönetici yeniden açabilir, viewer yalnız not görür', async () => {
    navigation.search = 'sekme=susturulmus';
    const muted = makeEvent({ status: 'muted', muted_until: '2026-11-20T10:00:00+03:00' });
    mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([muted], { open_count: 0 })),
    );
    const { unmount } = render(<AlertsScreen />);
    expect(await screen.findByRole('button', { name: 'Yeniden aç' })).toBeVisible();
    expect(screen.getByText('20 Kasım 2026, 10:00')).toBeVisible();
    unmount();

    mockRequests(
      accounts,
      me('viewer'),
      events(() => makeEventList([muted], { open_count: 0 })),
    );
    render(<AlertsScreen />);
    await screen.findByRole('region', { name: /Zararına satış/ });
    expect(screen.queryByRole('button', { name: 'Yeniden aç' })).not.toBeInTheDocument();
    expect(await screen.findByText('Hesap yöneticiniz yeniden açabilir.')).toBeVisible();
  });

  it('okundu sekmesi: yeniden aç geçişi {to: open} gönderir', async () => {
    navigation.search = 'sekme=okundu';
    const read = makeEvent({ status: 'read' });
    const { requests } = mockRequests(
      accounts,
      me('viewer'),
      csrf,
      events(() => makeEventList([read], { open_count: 0 })),
      (r) =>
        r.method === 'POST' ? { body: { event: makeEvent(), transition_id: 't3' } } : undefined,
    );
    render(<AlertsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yeniden aç' }));
    expect(await screen.findByText('Uyarı yeniden açıldı.')).toBeVisible();
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({ to: 'open' });
  });

  it('çözülmüş uyarıda eylem yoktur', async () => {
    navigation.search = 'sekme=cozuldu';
    const resolved = makeEvent({ status: 'resolved', resolved_at: '2026-11-12T20:00:00+03:00' });
    mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([resolved], { open_count: 0 })),
    );
    render(<AlertsScreen />);
    const card = await screen.findByRole('region', { name: /Zararına satış/ });
    expect(within(card).queryByRole('button')).not.toBeInTheDocument();
    expect(within(card).getByText('12 Kasım 2026, 20:00')).toBeVisible();
  });

  it('doğrulanmamış e-posta: düğmeler aria-disabled, tıklama istek göndermez, not açıklama olarak bağlı', async () => {
    const { requests } = mockRequests(
      accounts,
      me('owner', false),
      csrf,
      events(() => makeEventList([makeEvent()])),
    );
    render(<AlertsScreen />);
    const read = await screen.findByRole('button', { name: 'Okundu işaretle' });
    await waitFor(() => expect(read).toHaveAttribute('aria-disabled', 'true'));
    expect(read).not.toBeDisabled();
    expect(read.getAttribute('aria-describedby')).toBe('eposta-dogrulama-notu');
    expect(document.getElementById('eposta-dogrulama-notu')).toHaveTextContent(/doğrulayana dek/);
    await userEvent.click(read);
    const all = screen.getByRole('button', { name: 'Tümünü okundu yap' });
    expect(all).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(all);
    expect(transitions(requests)).toHaveLength(0);
  });

  it('tümünü okundu yap: read-all çağrılır, kalan varsa tekrar basılacağı söylenir, liste yenilenir', async () => {
    let calls = 0;
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      csrf,
      events(() => {
        calls += 1;
        return makeEventList([makeEvent()], { open_count: calls === 1 ? 800 : 300 });
      }),
      (r) =>
        r.method === 'POST' && r.url.pathname === `${EVENTS}/read-all`
          ? { body: { updated: 500, remaining_open: 300 } }
          : undefined,
    );
    render(<AlertsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Tümünü okundu yap' }));
    expect(await screen.findByText(/500 uyarı okundu olarak işaretlendi/)).toHaveTextContent(
      'Kalan 300 açık uyarı için tekrar basın (her seferde en çok 500).',
    );
    expect(requests.filter((r) => r.url.pathname === `${EVENTS}/read-all`)).toHaveLength(1);
    await waitFor(() => expect(calls).toBe(2));
  });

  it('409: Türkçe ileti gösterilir ve liste yeniden yüklenir', async () => {
    let calls = 0;
    mockRequests(
      accounts,
      me('owner'),
      csrf,
      events(() => {
        calls += 1;
        return makeEventList([makeEvent()]);
      }),
      (r) => (r.method === 'POST' ? problemReply(409, 'alert-transition-invalid') : undefined),
    );
    render(<AlertsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Okundu işaretle' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Bu uyarı başka bir yerde değişmiş olabilir. Liste yenilendi',
    );
    await waitFor(() => expect(calls).toBe(2));
  });

  it('429: Retry-After süresi söylenir, liste yeniden yüklenmez', async () => {
    let calls = 0;
    mockRequests(
      accounts,
      me('owner'),
      csrf,
      events(() => {
        calls += 1;
        return makeEventList([makeEvent()]);
      }),
      (r) =>
        r.method === 'POST'
          ? problemReply(429, 'rate-limited', { 'Retry-After': '120' })
          : undefined,
    );
    render(<AlertsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Okundu işaretle' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Çok fazla deneme yaptınız. Yaklaşık 2 dakika sonra tekrar deneyin.',
    );
    expect(calls).toBe(1);
    expect(screen.getByRole('region', { name: /Zararına satış/ })).toBeVisible();
  });

  it('tahmini olay "Tahmini" rozeti ve kısa notlar taşır; hesap kapsamı "Tüm hesap" yazar', async () => {
    const estimated = makeEvent({
      subject: 'hesap:*',
      payload: {
        certainty: 'tahmini',
        evidence: { total_loss: '10.00', loss_line_count: 1, has_missing_items: true },
      },
    });
    mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([estimated])),
    );
    render(<AlertsScreen />);
    const card = await screen.findByRole('region', { name: /Zararına satış/ });
    expect(within(card).getByText('Tahmini')).toBeVisible();
    expect(within(card).getByText('Tüm hesap')).toBeVisible();
    expect(within(card).getByText(/maliyet kalemi eksik/)).toBeVisible();
  });

  it('Tümü sekmesi süzgeçsiz ister; eylem sonrası kart yerinde güncellenir (listeden çıkmaz)', async () => {
    navigation.search = 'sekme=tumu';
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      csrf,
      events(() => makeEventList([makeEvent()], { open_count: 1 })),
      (r) =>
        r.method === 'POST'
          ? { body: { event: makeEvent({ status: 'read' }), transition_id: 't9' } }
          : undefined,
    );
    render(<AlertsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Okundu işaretle' }));
    await screen.findByText('Uyarı okundu olarak işaretlendi.');
    const list = requests.find((r) => r.url.pathname === EVENTS);
    expect(list?.url.searchParams.has('status')).toBe(false);
    const card = screen.getByRole('region', { name: /Zararına satış/ });
    expect(within(card).getByText('Okundu', { selector: 'span' })).toBeVisible();
    expect(within(card).getByRole('button', { name: 'Yeniden aç' })).toBeVisible();
  });

  it('çift tıklama tek istek gönderir (ref kilidi)', async () => {
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      csrf,
      events(() => makeEventList([makeEvent()])),
      (r) =>
        r.method === 'POST'
          ? {
              body: { event: makeEvent({ status: 'read' }), transition_id: 't' },
            }
          : undefined,
    );
    render(<AlertsScreen />);
    const button = await screen.findByRole('button', { name: 'Okundu işaretle' });
    button.click();
    button.click();
    await screen.findByText('Uyarı okundu olarak işaretlendi.');
    expect(requests.filter((r) => r.method === 'POST')).toHaveLength(1);
  });

  it('rol okunamazsa (/me hatası) "yetki okunamadı" notu çıkar, yanlış viewer notu değil', async () => {
    mockRequests(
      accounts,
      (r) => (r.url.pathname === '/api/v1/me' ? problemReply(500, 'internal-error') : undefined),
      events(() => makeEventList([makeEvent()])),
    );
    render(<AlertsScreen />);
    expect(await screen.findByText(/Yetkiniz okunamadı/)).toBeVisible();
    expect(screen.queryByText('Hesap yöneticiniz susturabilir.')).not.toBeInTheDocument();
  });

  it('sipariş satırı kartı: sipariş bağlantısı ve fark tutarı', async () => {
    mockRequests(
      accounts,
      me('owner'),
      events(() => makeEventList([DEDUCTION_EVENT])),
    );
    render(<AlertsScreen />);
    const card = await screen.findByRole('region', { name: /Beklenmeyen kesinti/ });
    expect(within(card).getByText('₺184,20')).toBeVisible();
    expect(within(card).getByRole('link', { name: 'Siparişi gör' })).toHaveAttribute(
      'href',
      expect.stringContaining('q=7000123'),
    );
  });
});
