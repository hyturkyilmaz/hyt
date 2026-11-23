// Servis çalışanı (public/sw.js) testleri: statik kurallar (ADR-0009 §12 madde 30) ve gerçek betiğin vm içinde
// sahte `self` ile çalıştırılması. Playwright ile gerçek SW testi yapılmadı (aşağıdaki not): bu testler betiğin
// kendisini yükler, kopyası yoktur.
//
// Not: Playwright'ta servis çalışanı + push olayı (Push API yalnız gerçek tarayıcı ve push servisiyle tetiklenir)
// ve izin penceresi otomasyonu kırılgandır; bu yüzden birim ve statik testlerle yetinildi.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

const SW_PATH = join(process.cwd(), 'public', 'sw.js');
const source = readFileSync(SW_PATH, 'utf8');
// Yorum satırları dışındaki kod (yasak ifadeler başlık yorumunda anılabilir).
const code = source
  .split('\n')
  .filter((line) => !line.trim().startsWith('//'))
  .join('\n');
const ORIGIN = 'https://app.example';

describe('sw.js statik kurallar', () => {
  it('yalnız push, notificationclick ve pushsubscriptionchange dinler', () => {
    const events = [...code.matchAll(/addEventListener\(\s*['"]([a-z]+)['"]/g)].map((m) => m[1]);
    expect(events.sort()).toEqual(['notificationclick', 'push', 'pushsubscriptionchange']);
  });

  it('fetch dinleyicisi yok (addEventListener, onfetch, install/activate yok)', () => {
    expect(code).not.toMatch(/addEventListener\(\s*['"]fetch['"]/);
    expect(code).not.toMatch(/\bonfetch\b/);
    expect(code).not.toMatch(/addEventListener\(\s*['"](install|activate|message)['"]/);
  });

  it('önbellek ve betik içe aktarma yok', () => {
    expect(code).not.toMatch(/\bcaches\b/);
    expect(code).not.toMatch(/importScripts|\bimport\s*\(|skipWaiting|clients\.claim/);
  });

  it('openWindow yalnız doğrulanmış yoldan üretilen hedefle çağrılır', () => {
    const calls = [...code.matchAll(/openWindow\(([^)]*)\)/g)].map((m) => m[1]);
    expect(calls).toEqual(['target']);
    expect(source).toMatch(
      /var target = new URL\(safePath\(raw\), self\.location\.origin\)\.href;/,
    );
  });

  it('em dash (U+2014) ve U+2015 içermez', () => {
    expect(code).not.toMatch(/[\u2014\u2015]/);
  });
});

interface Harness {
  listeners: Record<string, (event: unknown) => void>;
  shown: { title: string; options: { body: string; data: { path: string } } }[];
  opened: string[];
  focused: string[];
  navigated: string[];
  fetches: { url: string; init?: RequestInit }[];
  subscribeCalls: unknown[];
  windows: { url: string }[];
}

function load(
  opts: {
    windows?: { url: string }[];
    fetchImpl?: (url: string, init?: RequestInit) => Promise<Response>;
  } = {},
): Harness {
  const h: Harness = {
    listeners: {},
    shown: [],
    opened: [],
    focused: [],
    navigated: [],
    fetches: [],
    subscribeCalls: [],
    windows: opts.windows ?? [],
  };
  const clientFor = (w: { url: string }) => ({
    url: w.url,
    focus: () => {
      h.focused.push(w.url);
      return Promise.resolve({
        navigate: (target: string) => {
          h.navigated.push(target);
          return Promise.resolve();
        },
      });
    },
  });
  const sandboxSelf = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, fn: (event: unknown) => void) => {
      h.listeners[type] = fn;
    },
    registration: {
      showNotification: (title: string, options: Harness['shown'][number]['options']) => {
        h.shown.push({ title, options });
        return Promise.resolve();
      },
      pushManager: {
        subscribe: (options: unknown) => {
          h.subscribeCalls.push(options);
          return Promise.resolve(fakeSubscription('https://fcm.googleapis.com/fcm/send/yeni'));
        },
      },
    },
    clients: {
      matchAll: () => Promise.resolve(h.windows.map(clientFor)),
      openWindow: (url: string) => {
        h.opened.push(url);
        return Promise.resolve(null);
      },
    },
  };
  const fetchImpl =
    opts.fetchImpl ??
    (() => Promise.resolve(new Response(JSON.stringify({ csrf_token: 'tok' }), { status: 200 })));
  vm.runInNewContext(source, {
    self: sandboxSelf,
    URL,
    Uint8Array,
    atob,
    btoa,
    Promise,
    fetch: (url: string, init?: RequestInit) => {
      h.fetches.push({ url, init });
      return fetchImpl(url, init);
    },
    JSON,
  });
  return h;
}

function fakeSubscription(endpoint: string) {
  const key = (n: number) => () => new Uint8Array(n).fill(7).buffer;
  return { endpoint, getKey: (name: string) => (name === 'p256dh' ? key(65)() : key(16)()) };
}

async function dispatch(h: Harness, type: string, event: Record<string, unknown>) {
  const waits: Promise<unknown>[] = [];
  h.listeners[type]!({ ...event, waitUntil: (p: Promise<unknown>) => waits.push(p) });
  await Promise.all(waits);
}

function pushEvent(payload: unknown) {
  return { data: { json: () => payload } };
}

function clickEvent(path: unknown) {
  const closed: boolean[] = [];
  return {
    notification: { data: { path }, close: () => closed.push(true) },
    closed,
  };
}

describe('sw.js push olayı', () => {
  it('başlık ve gövdeyi yalnız yükten alır, yolu doğrular', async () => {
    const h = load();
    await dispatch(
      h,
      'push',
      pushEvent({
        title: 'Zararına satış',
        body: '2 üründe zarar var',
        path: '/panel/uyarilar/abc',
        amount: '99.90',
      }),
    );
    expect(h.shown).toEqual([
      {
        title: 'Zararına satış',
        options: { body: '2 üründe zarar var', data: { path: '/panel/uyarilar/abc' } },
      },
    ]);
    // Yükteki ek alan (tutar) bildirime taşınmaz.
    expect(JSON.stringify(h.shown)).not.toContain('99.90');
  });

  it('yük yoksa ya da bozuksa genel başlıkla yine görünür bildirim gösterir', async () => {
    const h = load();
    await dispatch(h, 'push', { data: null });
    await dispatch(h, 'push', {
      data: {
        json: () => {
          throw new Error('bozuk');
        },
      },
    });
    await dispatch(h, 'push', pushEvent('metin'));
    expect(h.shown.map((s) => [s.title, s.options.body, s.options.data.path])).toEqual([
      ['NetKâr', '', '/panel/uyarilar'],
      ['NetKâr', '', '/panel/uyarilar'],
      ['NetKâr', '', '/panel/uyarilar'],
    ]);
  });

  it('kontrol karakterlerini temizler ve uzun metni keser', async () => {
    const h = load();
    await dispatch(
      h,
      'push',
      pushEvent({ title: 'A\nB\u0000' + 'x'.repeat(200), body: 'y'.repeat(400) }),
    );
    expect(h.shown[0]!.title).not.toMatch(/[\n\u0000]/);
    expect(h.shown[0]!.title.length).toBeLessThanOrEqual(80);
    expect(h.shown[0]!.options.body.length).toBeLessThanOrEqual(160);
  });

  it('dış ya da izin listesi dışı yolu varsayılan yola çevirir', async () => {
    const h = load();
    for (const path of [
      'https://evil.example/x',
      '//evil.example/x',
      '/panel/uyarilarx',
      '/panel/uyarilar/../x',
      '/baska',
      'javascript:alert(1)',
      '/panel/uyarilar\\x',
      '/panel/uyarilar/a b',
      42,
      null,
    ]) {
      await dispatch(h, 'push', pushEvent({ title: 't', path }));
    }
    expect(new Set(h.shown.map((s) => s.options.data.path))).toEqual(new Set(['/panel/uyarilar']));
  });
});

describe('sw.js notificationclick olayı', () => {
  it('bildirimi kapatır ve aynı kökenli yolu açar', async () => {
    const h = load();
    const event = clickEvent('/panel/uyarilar/olay-1');
    await dispatch(h, 'notificationclick', event);
    expect(event.closed).toEqual([true]);
    expect(h.opened).toEqual([`${ORIGIN}/panel/uyarilar/olay-1`]);
  });

  it('dış URL ya da izin listesi dışı yol ASLA açılmaz', async () => {
    const h = load();
    for (const path of [
      'https://evil.example/phish',
      '//evil.example',
      'http://evil.example',
      '/baska/yol',
      '/panel/uyarilar/../../ayarlar',
      'javascript:alert(1)',
      undefined,
    ]) {
      await dispatch(h, 'notificationclick', clickEvent(path));
    }
    expect(h.opened.length).toBe(7);
    for (const url of h.opened) {
      expect(url).toBe(`${ORIGIN}/panel/uyarilar`);
    }
  });

  it('açık aynı kökenli sekmeyi öne alır ve yönlendirir; yeni pencere açmaz', async () => {
    const h = load({ windows: [{ url: `${ORIGIN}/panel/kar` }] });
    await dispatch(h, 'notificationclick', clickEvent('/panel/uyarilar/o2'));
    expect(h.focused).toEqual([`${ORIGIN}/panel/kar`]);
    expect(h.navigated).toEqual([`${ORIGIN}/panel/uyarilar/o2`]);
    expect(h.opened).toEqual([]);
  });

  it('başka kökenli sekmeyi kullanmaz', async () => {
    const h = load({ windows: [{ url: 'https://evil.example/' }] });
    await dispatch(h, 'notificationclick', clickEvent('/panel/uyarilar'));
    expect(h.focused).toEqual([]);
    expect(h.opened).toEqual([`${ORIGIN}/panel/uyarilar`]);
  });
});

describe('sw.js pushsubscriptionchange olayı', () => {
  const okJson = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  it('eski seçeneklerle yeniden abone olur ve sunucuya bildirir (CSRF dahil)', async () => {
    const h = load({
      fetchImpl: (url) =>
        Promise.resolve(
          url.endsWith('/auth/csrf') ? okJson({ csrf_token: 'tok-1' }) : okJson({}, 201),
        ),
    });
    const key = new Uint8Array([1, 2, 3]);
    await dispatch(h, 'pushsubscriptionchange', {
      oldSubscription: { options: { applicationServerKey: key } },
    });
    expect(h.subscribeCalls).toEqual([{ userVisibleOnly: true, applicationServerKey: key }]);
    const post = h.fetches.find((f) => f.url === '/api/v1/me/push-subscriptions')!;
    expect(post.init?.method).toBe('POST');
    expect((post.init?.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok-1');
    const sent = JSON.parse(post.init!.body as string) as {
      endpoint: string;
      keys: Record<string, string>;
    };
    expect(sent.endpoint).toBe('https://fcm.googleapis.com/fcm/send/yeni');
    expect(Object.keys(sent.keys).sort()).toEqual(['auth', 'p256dh']);
    expect(sent.keys.p256dh).not.toMatch(/[+/=]/);
  });

  it('eski seçenek yoksa genel anahtarı sunucudan alır', async () => {
    const h = load({
      fetchImpl: (url) =>
        Promise.resolve(
          url.endsWith('/push/vapid-public-key')
            ? okJson({ enabled: true, public_key: 'AQID', key_id: 'k' })
            : url.endsWith('/auth/csrf')
              ? okJson({ csrf_token: 't' })
              : okJson({}, 201),
        ),
    });
    await dispatch(h, 'pushsubscriptionchange', { oldSubscription: null });
    expect(h.subscribeCalls).toHaveLength(1);
    const options = h.subscribeCalls[0] as { applicationServerKey: Uint8Array };
    expect(Array.from(options.applicationServerKey)).toEqual([1, 2, 3]);
  });

  it('push kapalıysa (enabled false) ya da ağ hatasında sessizce vazgeçer', async () => {
    const closed = load({ fetchImpl: () => Promise.resolve(okJson({ enabled: false })) });
    await dispatch(closed, 'pushsubscriptionchange', { oldSubscription: null });
    expect(closed.subscribeCalls).toEqual([]);
    const broken = load({ fetchImpl: () => Promise.reject(new Error('ağ yok')) });
    await expect(
      dispatch(broken, 'pushsubscriptionchange', { oldSubscription: null }),
    ).resolves.toBeUndefined();
  });
});
