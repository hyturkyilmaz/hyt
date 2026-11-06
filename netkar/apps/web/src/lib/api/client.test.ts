import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NetworkError, apiFetch, describeApiError } from '@/lib/api/client';
import { readCookie, readCsrfToken } from '@/lib/api/csrf';

function mockFetch(response: Response | Error) {
  const fn = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function setCookie(value: string) {
  document.cookie = value;
}

describe('csrf çerez okuma', () => {
  afterEach(() => {
    setCookie('csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/');
  });

  it('verilen çerez metninden değeri çözer', () => {
    expect(readCookie('csrf_token', 'a=1; csrf_token=abc%2Bdef; b=2')).toBe('abc+def');
    expect(readCookie('yok', 'a=1')).toBeUndefined();
  });

  it('benzer adlı çerezle karışmaz', () => {
    expect(readCookie('csrf_token', 'x_csrf_token=zzz; csrf_token_old=yyy')).toBeUndefined();
  });

  it('belge çerezinden okur', () => {
    setCookie('csrf_token=tok123; path=/');
    expect(readCsrfToken()).toBe('tok123');
  });
});

describe('apiFetch', () => {
  beforeEach(() => {
    setCookie('csrf_token=tok123; path=/');
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setCookie('csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/');
  });

  it('POST isteğinde X-CSRF-Token başlığını ve aynı köken çerezini kullanır', async () => {
    const fetchMock = mockFetch(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    await apiFetch('/auth/login', { method: 'POST', body: { email: 'a@b.co' } });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(url).toBe('/api/v1/auth/login');
    expect(headers.get('X-CSRF-Token')).toBe('tok123');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(init.credentials).toBe('same-origin');
    expect(init.body).toBe(JSON.stringify({ email: 'a@b.co' }));
  });

  it('GET isteğinde CSRF başlığı eklemez', async () => {
    const fetchMock = mockFetch(new Response('{}', { status: 200 }));
    await apiFetch('/me');
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Headers).has('X-CSRF-Token')).toBe(false);
  });

  it('204 yanıtta undefined döner', async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(apiFetch('/auth/logout', { method: 'POST' })).resolves.toBeUndefined();
  });

  it('hata yanıtında yalnız durum ve makine kodunu taşır, sunucu ayrıntısını taşımaz', async () => {
    mockFetch(
      new Response(JSON.stringify({ code: 'invalid_credentials', detail: 'SELECT * FROM users' }), {
        status: 401,
      }),
    );
    const error = await apiFetch('/auth/login', { method: 'POST' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).code).toBe('invalid_credentials');
    expect((error as ApiError).message).not.toContain('SELECT');
  });

  it('ağ hatasını NetworkError olarak yükseltir', async () => {
    mockFetch(new TypeError('Failed to fetch'));
    await expect(apiFetch('/me')).rejects.toBeInstanceOf(NetworkError);
  });
});

describe('describeApiError', () => {
  it('duruma göre Türkçe mesaj üretir', () => {
    expect(describeApiError(new NetworkError(), 'x')).toContain('ulaşılamadı');
    expect(describeApiError(new ApiError({ status: 429 }), 'x')).toContain('Çok fazla');
    expect(describeApiError(new ApiError({ status: 500 }), 'x')).toContain('sorun');
    expect(describeApiError(new ApiError({ status: 401 }), 'yedek')).toBe('yedek');
    expect(describeApiError(new Error('?'), 'yedek')).toBe('yedek');
  });
});
