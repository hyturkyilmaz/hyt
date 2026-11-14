import { beforeEach, describe, expect, it, vi } from 'vitest';

const cookieStore = { get: vi.fn() };
vi.mock('next/headers', () => ({ cookies: async () => cookieStore }));

import { getSession } from '@/lib/api/server';

const ME = {
  user_id: '3f1b2c1e-0000-4000-8000-000000000001',
  email: 'ad@ornek.com',
  role: 'owner',
  totp_enabled: false,
  tenant: {
    id: '3f1b2c1e-0000-4000-8000-000000000002',
    name: 'Örnek Mağaza',
    plan: 'trial',
    status: 'active',
    trial_ends_at: null,
    currency: 'TRY',
    locale: 'tr-TR',
  },
};

function withCookie(value: string | undefined) {
  cookieStore.get.mockReturnValue(value === undefined ? undefined : { value });
}

describe('getSession', () => {
  beforeEach(() => {
    cookieStore.get.mockReset();
  });

  it('çerez yoksa API çağrılmadan unauthenticated döner', async () => {
    withCookie(undefined);
    const fetchMock = vi.fn();
    await expect(getSession(fetchMock as unknown as typeof fetch)).resolves.toEqual({
      status: 'unauthenticated',
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('yalnız oturum çerezini /v1/me ye iletir ve kullanıcıyı döndürür', async () => {
    withCookie('tok-abc');
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(ME), { status: 200 }));
    const result = await getSession(fetchMock as unknown as typeof fetch);
    expect(result).toEqual({ status: 'authenticated', me: ME });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/v1/me');
    expect((init.headers as Record<string, string>).Cookie).toBe('__Host-nk_session=tok-abc');
    expect(init.cache).toBe('no-store');
  });

  it('401 geçersiz oturumdur', async () => {
    withCookie('eski');
    const fetchMock = vi.fn(async () => new Response('{}', { status: 401 }));
    await expect(getSession(fetchMock as unknown as typeof fetch)).resolves.toEqual({
      status: 'unauthenticated',
    });
  });

  it('ağ hatası, 5xx ve bozuk gövde unavailable döner (oturum düşürülmez)', async () => {
    withCookie('tok');
    const cases: (() => Promise<Response>)[] = [
      async () => Promise.reject(new TypeError('fetch failed')),
      async () => new Response('{}', { status: 503 }),
      async () => new Response('html', { status: 200 }),
      async () => new Response(JSON.stringify({ email: 1 }), { status: 200 }),
    ];
    for (const impl of cases) {
      await expect(getSession(vi.fn(impl) as unknown as typeof fetch)).resolves.toEqual({
        status: 'unavailable',
      });
    }
  });
});
