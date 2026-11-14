// Bileşen testleri için fetch taklidi: yol ve sorguya göre yanıt döndürür, istekleri kaydeder.
import { vi } from 'vitest';

export interface MockResponse {
  status?: number;
  body?: unknown;
  /** Ek yanıt başlıkları (ör. Retry-After) */
  headers?: Record<string, string>;
}

export type Handler = (url: URL) => MockResponse | undefined;

export function problem(status: number, slug: string, errors?: { field: string; code: string }[]) {
  return {
    status,
    body: {
      type: `urn:netkar:problem:${slug}`,
      title: slug,
      status,
      ...(errors ? { errors } : {}),
    },
  };
}

/** Handler'lar sırayla denenir; ilk yanıt veren kazanır. Eşleşme yoksa 404. */
export function mockFetch(...handlers: Handler[]) {
  const calls: URL[] = [];
  const fn = vi.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    calls.push(url);
    for (const handler of handlers) {
      const result = handler(url);
      if (result) {
        const status = result.status ?? 200;
        return Promise.resolve(
          new Response(JSON.stringify(result.body ?? {}), {
            status,
            headers: {
              'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
              ...result.headers,
            },
          }),
        );
      }
    }
    return Promise.resolve(
      new Response(JSON.stringify(problem(404, 'not-found').body), {
        status: 404,
        headers: { 'Content-Type': 'application/problem+json' },
      }),
    );
  });
  vi.stubGlobal('fetch', fn);
  return { calls, fn };
}
