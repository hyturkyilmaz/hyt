import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PushToggle } from '@/components/notifications/push-toggle';
import { mockRequests, problemReply, type Route } from '@/test/request-mock';

const KEY = 'AQIDBAUGBwgJCg';
const SUB_INFO = {
  id: 'sub-1',
  endpoint_host: 'fcm.googleapis.com',
  vapid_key_id: 'k1',
  created_at: '2026-11-23T10:00:00Z',
  last_success_at: null,
};
const vapid =
  (enabled: boolean): Route =>
  (r) =>
    r.url.pathname === '/api/v1/push/vapid-public-key'
      ? {
          body: enabled
            ? { enabled, public_key: KEY, key_id: 'k1' }
            : { enabled: false, public_key: null, key_id: null },
        }
      : undefined;
const csrf: Route = (r) =>
  r.url.pathname === '/api/v1/auth/csrf' ? { body: { csrf_token: 'test-csrf' } } : undefined;
const subscribeOk: Route = (r) =>
  r.method === 'POST' && r.url.pathname === '/api/v1/me/push-subscriptions'
    ? { status: 201, body: SUB_INFO }
    : undefined;
const releaseOk: Route = (r) =>
  r.method === 'POST' && r.url.pathname === '/api/v1/me/push-subscriptions/release'
    ? { status: 204 }
    : undefined;

const BROWSER_SUB = {
  endpoint: 'https://fcm.googleapis.com/fcm/send/GIZLI',
  toJSON: () => ({
    endpoint: 'https://fcm.googleapis.com/fcm/send/GIZLI',
    expirationTime: null,
    keys: { p256dh: 'p256dh-degeri', auth: 'auth-degeri' },
  }),
  unsubscribe: vi.fn(() => Promise.resolve(true)),
};

interface Env {
  requestPermission: ReturnType<typeof vi.fn>;
  subscribe: ReturnType<typeof vi.fn>;
  register: ReturnType<typeof vi.fn>;
  getSubscription: ReturnType<typeof vi.fn>;
}

/** jsdom'da Push API yok: serviceWorker, PushManager ve Notification taklit edilir. */
function stubBrowser(over: { permission?: NotificationPermission; existing?: boolean } = {}): Env {
  const subscribe = vi.fn(() => Promise.resolve(BROWSER_SUB));
  const getSubscription = vi.fn(() => Promise.resolve(over.existing ? BROWSER_SUB : null));
  const registration = { pushManager: { subscribe, getSubscription } };
  const register = vi.fn(() => Promise.resolve(registration));
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      register,
      ready: Promise.resolve(registration),
      getRegistration: vi.fn(() => Promise.resolve(over.existing ? registration : undefined)),
    },
  });
  vi.stubGlobal('PushManager', class {});
  const requestPermission = vi.fn(() => Promise.resolve(over.permission ?? 'granted'));
  vi.stubGlobal('Notification', { requestPermission, permission: 'default' });
  return { requestPermission, subscribe, register, getSubscription };
}

beforeEach(() => {
  document.cookie = '__Host-nk_csrf=test-csrf; path=/';
  BROWSER_SUB.unsubscribe.mockClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, 'serviceWorker');
});

describe('PushToggle', () => {
  it('bayrak kapalıyken "Yakında" gösterir, düğme ve izin isteği yok', async () => {
    const env = stubBrowser();
    mockRequests(vapid(false));
    render(<PushToggle />);
    expect(await screen.findByText('Yakında')).toBeVisible();
    expect(screen.queryByRole('button')).toBeNull();
    expect(env.requestPermission).not.toHaveBeenCalled();
  });

  it('anahtar okunamazsa (hata) "Yakında" kalır', async () => {
    stubBrowser();
    mockRequests((r) =>
      r.url.pathname === '/api/v1/push/vapid-public-key'
        ? problemReply(500, 'server-error')
        : undefined,
    );
    render(<PushToggle />);
    expect(await screen.findByText('Yakında')).toBeVisible();
  });

  it('bayrak açık ama tarayıcı desteklemiyorsa açıklama gösterir', async () => {
    mockRequests(vapid(true));
    render(<PushToggle />);
    expect(await screen.findByText(/Bu tarayıcı anlık bildirimi desteklemiyor/)).toBeVisible();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('bayrak açıkken düğme gösterir; sayfa yüklenirken izin İSTEMEZ', async () => {
    const env = stubBrowser();
    mockRequests(vapid(true));
    render(<PushToggle />);
    expect(
      await screen.findByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' }),
    ).toBeEnabled();
    expect(screen.getByText('Kapalı')).toBeVisible();
    expect(env.requestPermission).not.toHaveBeenCalled();
    expect(env.register).not.toHaveBeenCalled();
    expect(env.subscribe).not.toHaveBeenCalled();
  });

  it('tıklayınca izin ister, abone olur ve uç nokta ile anahtarları POST eder', async () => {
    const env = stubBrowser();
    const { requests } = mockRequests(vapid(true), csrf, subscribeOk);
    render(<PushToggle />);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' }),
    );
    expect(await screen.findByText('Bu tarayıcıda anlık bildirim açıldı.')).toBeVisible();
    expect(env.requestPermission).toHaveBeenCalledTimes(1);
    expect(env.register).toHaveBeenCalledWith('/sw.js');
    const options = env.subscribe.mock.calls[0]![0] as {
      userVisibleOnly: boolean;
      applicationServerKey: Uint8Array;
    };
    expect(options.userVisibleOnly).toBe(true);
    expect(Array.from(options.applicationServerKey.slice(0, 3))).toEqual([1, 2, 3]);
    const post = requests.find(
      (r) => r.method === 'POST' && r.url.pathname.endsWith('/push-subscriptions'),
    )!;
    expect(post.body).toEqual({
      endpoint: 'https://fcm.googleapis.com/fcm/send/GIZLI',
      keys: { p256dh: 'p256dh-degeri', auth: 'auth-degeri' },
    });
    expect(
      screen.getByRole('button', { name: 'Bu tarayıcıda anlık bildirimi kapat' }),
    ).toBeVisible();
    expect(screen.getByText('Açık')).toBeVisible();
  });

  it('izin reddedilirse abone olmaz ve sunucuya yazmaz', async () => {
    const env = stubBrowser({ permission: 'denied' });
    const { requests } = mockRequests(vapid(true), csrf, subscribeOk);
    render(<PushToggle />);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' }),
    );
    expect(await screen.findByText(/Tarayıcı bildirim iznini engelledi/)).toBeVisible();
    expect(env.subscribe).not.toHaveBeenCalled();
    expect(requests.some((r) => r.method === 'POST')).toBe(false);
    expect(screen.getByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' })).toBeEnabled();
  });

  it('sunucu kaydı başarısızsa tarayıcı aboneliği geri alınır ve hata gösterilir', async () => {
    stubBrowser();
    mockRequests(vapid(true), csrf, (r) =>
      r.method === 'POST' ? problemReply(409, 'push-subscription-limit') : undefined,
    );
    render(<PushToggle />);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' }),
    );
    expect(await screen.findByText(/En çok 10 cihazda/)).toBeVisible();
    expect(BROWSER_SUB.unsubscribe).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' })).toBeEnabled();
  });

  it('açık abonelikte kapat: uç noktayla release çağırır (abone olma POST yok), tarayıcıdan çıkar', async () => {
    stubBrowser({ existing: true });
    const { requests } = mockRequests(vapid(true), csrf, subscribeOk, releaseOk);
    render(<PushToggle />);
    const off = await screen.findByRole('button', { name: 'Bu tarayıcıda anlık bildirimi kapat' });
    expect(screen.getByText('Açık')).toBeVisible();
    await userEvent.click(off);
    expect(await screen.findByText('Bu tarayıcıda anlık bildirim kapatıldı.')).toBeVisible();
    expect(
      requests.filter((r) => r.method !== 'GET').map((r) => `${r.method} ${r.url.pathname}`),
    ).toEqual(['POST /api/v1/me/push-subscriptions/release']);
    const release = requests.find((r) => r.url.pathname.endsWith('/release'))!;
    expect(release.body).toEqual({ endpoint: 'https://fcm.googleapis.com/fcm/send/GIZLI' });
    expect(BROWSER_SUB.unsubscribe).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' }),
      ).toBeEnabled(),
    );
  });
  it('kapatırken sunucu hatası olsa da tarayıcı aboneliği bırakılır ve hata gösterilir', async () => {
    stubBrowser({ existing: true });
    mockRequests(vapid(true), csrf, (r) =>
      r.url.pathname.endsWith('/release') ? problemReply(500, 'server-error') : undefined,
    );
    render(<PushToggle />);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Bu tarayıcıda anlık bildirimi kapat' }),
    );
    expect(await screen.findByText(/Sunucuya ulaşılamadı|Bir sorun oluştu/)).toBeVisible();
    expect(BROWSER_SUB.unsubscribe).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Bu tarayıcıda anlık bildirimi aç' })).toBeEnabled();
  });

  it('tarayıcı unsubscribe() false dönerse "kapatıldı" denmez, hata gösterilir ve durum açık kalır', async () => {
    stubBrowser({ existing: true });
    BROWSER_SUB.unsubscribe.mockImplementationOnce(() => Promise.resolve(false));
    mockRequests(vapid(true), csrf, releaseOk);
    render(<PushToggle />);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Bu tarayıcıda anlık bildirimi kapat' }),
    );
    expect(await screen.findByText(/Anlık bildirim ayarı değiştirilemedi/)).toBeVisible();
    expect(screen.queryByText('Bu tarayıcıda anlık bildirim kapatıldı.')).toBeNull();
    expect(screen.getByText('Açık')).toBeVisible();
    expect(
      screen.getByRole('button', { name: 'Bu tarayıcıda anlık bildirimi kapat' }),
    ).toBeEnabled();
  });
});
