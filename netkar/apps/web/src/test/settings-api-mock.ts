// Ayar paneli bileşen testleri için durumlu fetch taklidi: yöntem, yol, sorgu ve gövdeyi kaydeder.
// Üretim kodunda kullanılmaz.
import { vi } from 'vitest';

export interface RecordedCall {
  method: string;
  path: string;
  query: URLSearchParams;
  body: Record<string, unknown> | null;
}

export interface FakeResponse {
  status?: number;
  body?: unknown;
}

export type Responder = (call: RecordedCall) => FakeResponse | Promise<FakeResponse>;

/** Anahtar: "GET /yol" (yol, /api/v1 öneki olmadan). Eşleşmeyen istek 404 döner. */
export function installFakeApi(routes: Record<string, Responder | FakeResponse>) {
  const calls: RecordedCall[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const method = (init?.method ?? 'GET').toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, '');
    let body: Record<string, unknown> | null = null;
    if (typeof init?.body === 'string') body = JSON.parse(init.body) as Record<string, unknown>;
    const call: RecordedCall = { method, path, query: url.searchParams, body };
    calls.push(call);
    const route =
      path === '/auth/csrf' ? { body: { csrf_token: 'test' } } : routes[`${method} ${path}`];
    let result: FakeResponse = {
      status: 404,
      body: { type: 'urn:netkar:problem:not-found', status: 404 },
    };
    if (route) result = typeof route === 'function' ? await route(call) : route;
    const status = result.status ?? 200;
    return new Response(JSON.stringify(result.body ?? {}), {
      status,
      headers: {
        'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
      },
    });
  });
  vi.stubGlobal('fetch', fn);
  return {
    calls,
    writes: () => calls.filter((c) => c.method !== 'GET' && c.path !== '/auth/csrf'),
    count: (method: string, path: string) =>
      calls.filter((c) => c.method === method && c.path === path).length,
  };
}

export function problemBody(slug: string, extra: Record<string, unknown> = {}) {
  return { type: `urn:netkar:problem:${slug}`, title: slug, status: 409, ...extra };
}
