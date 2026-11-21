// Maliyet ekranı testleri için fetch taklidi: yöntem, yol, sorgu ve gövdeyi (JSON ya da multipart) kaydeder.
import { vi } from 'vitest';

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  json: Record<string, unknown> | null;
  file: File | null;
  headers: Headers;
}

export interface Reply {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
}

export type Responder = (call: Call) => Reply | undefined | Promise<Reply | undefined>;

export function stubApi(...responders: Responder[]) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const body = init?.body;
    const call: Call = {
      method: init?.method ?? 'GET',
      path: url.pathname,
      query: url.searchParams,
      json: typeof body === 'string' ? (JSON.parse(body) as Record<string, unknown>) : null,
      file: body instanceof FormData ? (body.get('file') as File | null) : null,
      headers: new Headers(init?.headers),
    };
    calls.push(call);
    if (call.path === '/api/v1/auth/csrf') {
      return new Response(JSON.stringify({ csrf_token: 'test-csrf' }), { status: 200 });
    }
    for (const responder of responders) {
      const reply = await responder(call);
      if (reply) {
        const status = reply.status ?? 200;
        return new Response(JSON.stringify(reply.body ?? {}), {
          status,
          headers: {
            'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
            ...reply.headers,
          },
        });
      }
    }
    return new Response(
      JSON.stringify({ type: 'urn:netkar:problem:not-found', title: 'Bulunamadı', status: 404 }),
      { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
    );
  });
  vi.stubGlobal('fetch', fn);
  return { calls, fn };
}

export function problemBody(
  status: number,
  slug: string,
  extra: Record<string, unknown> = {},
): Reply {
  return { status, body: { type: `urn:netkar:problem:${slug}`, title: slug, status, ...extra } };
}
