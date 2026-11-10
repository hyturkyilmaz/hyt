import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  NetworkError,
  apiFetch,
  describeApiError,
  ensureCsrfToken,
} from '@/lib/api/client';
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
    setCookie('__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure');
  });

  it('verilen çerez metninden değeri çözer', () => {
    expect(readCookie('__Host-nk_csrf', 'a=1; __Host-nk_csrf=abc%2Bdef; b=2')).toBe('abc+def');
    expect(readCookie('yok', 'a=1')).toBeUndefined();
  });

  it('benzer adlı çerezle karışmaz', () => {
    expect(
      readCookie('__Host-nk_csrf', 'x___Host-nk_csrf=zzz; csrf_token_old=yyy'),
    ).toBeUndefined();
  });

  it('belge çerezinden okur', () => {
    setCookie('__Host-nk_csrf=tok123; path=/; Secure');
    expect(readCsrfToken()).toBe('tok123');
  });
});

describe('apiFetch', () => {
  beforeEach(() => {
    setCookie('__Host-nk_csrf=tok123; path=/; Secure');
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setCookie('__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure');
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
      new Response(
        JSON.stringify({
          type: 'urn:netkar:problem:invalid-credentials',
          title: 'Geçersiz kimlik bilgileri',
          status: 401,
          detail: 'SELECT * FROM users',
        }),
        { status: 401, headers: { 'Content-Type': 'application/problem+json' } },
      ),
    );
    const error = await apiFetch('/auth/login', { method: 'POST' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).code).toBe('invalid-credentials');
    expect((error as ApiError).message).not.toContain('SELECT');
  });

  it('429 yanıtında Retry-After saniyesini taşır; geçersiz biçimi yok sayar', async () => {
    mockFetch(new Response('{}', { status: 429, headers: { 'Retry-After': '3' } }));
    const limited = await apiFetch('/x').catch((e: unknown) => e);
    expect((limited as ApiError).retryAfterSeconds).toBe(3);
    mockFetch(
      new Response('{}', {
        status: 429,
        headers: { 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' },
      }),
    );
    const dated = await apiFetch('/x').catch((e: unknown) => e);
    expect((dated as ApiError).retryAfterSeconds).toBeUndefined();
  });

  it('422 doğrulama hatasında alan yolu ve kural kodunu taşır', async () => {
    mockFetch(
      new Response(
        JSON.stringify({
          type: 'urn:netkar:problem:validation-error',
          status: 422,
          errors: [{ field: 'tenant_name', code: 'string_too_short' }, { bozuk: 1 }],
        }),
        { status: 422 },
      ),
    );
    const error = await apiFetch('/auth/register', { method: 'POST', body: {} }).catch(
      (e: unknown) => e,
    );
    expect((error as ApiError).code).toBe('validation-error');
    expect((error as ApiError).errors).toEqual([
      { field: 'tenant_name', code: 'string_too_short' },
    ]);
  });

  it('urn:netkar dışındaki type değerini makine kodu saymaz', async () => {
    mockFetch(new Response(JSON.stringify({ type: 'https://evil.example/x' }), { status: 400 }));
    const error = await apiFetch('/x', { method: 'POST' }).catch((e: unknown) => e);
    expect((error as ApiError).code).toBeUndefined();
  });

  it('CSRF çerezi okunamıyorsa önce GET /auth/csrf çağırır ve gövdedeki token ı kullanır', async () => {
    setCookie('__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure');
    const fn = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: 'taze-token' }), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }));
    vi.stubGlobal('fetch', fn);

    await apiFetch('/auth/login', { method: 'POST', body: { email: 'a@b.co' } });

    const [csrfUrl, csrfInit] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(csrfUrl).toBe('/api/v1/auth/csrf');
    expect(csrfInit.method).toBe('GET');
    const [, loginInit] = fn.mock.calls[1] as unknown as [string, RequestInit];
    expect((loginInit.headers as Headers).get('X-CSRF-Token')).toBe('taze-token');
  });

  it('CSRF token alınamazsa istek atılmadan hata verir', async () => {
    setCookie('__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure');
    const fn = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fn);
    await expect(ensureCsrfToken()).rejects.toBeInstanceOf(ApiError);
    await expect(apiFetch('/auth/logout', { method: 'POST' })).rejects.toBeInstanceOf(ApiError);
    expect(fn.mock.calls.every(([url]) => url === '/api/v1/auth/csrf')).toBe(true);
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
