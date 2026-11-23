// Bileşen testleri için yöntem, gövde ve başlıkları da kaydeden fetch taklidi (api-mock.ts yalnız URL görür).
import { vi } from 'vitest';

export interface RecordedRequest {
  method: string;
  url: URL;
  body: unknown;
  headers: Headers;
  credentials: RequestCredentials | undefined;
}

export interface Reply {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
}

export type Route = (request: RecordedRequest) => Reply | undefined;

/** Yollar sırayla denenir; ilk yanıt veren kazanır. Eşleşme yoksa 404 problem+json. */
export function mockRequests(...routes: Route[]) {
  const requests: RecordedRequest[] = [];
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof init?.body === 'string' ? init.body : undefined;
    const request: RecordedRequest = {
      method: init?.method ?? 'GET',
      url: new URL(String(input), 'http://localhost'),
      body: raw === undefined ? undefined : (JSON.parse(raw) as unknown),
      headers: new Headers(init?.headers),
      credentials: init?.credentials,
    };
    requests.push(request);
    for (const route of routes) {
      const reply = route(request);
      if (reply) {
        const status = reply.status ?? 200;
        return Promise.resolve(
          new Response(JSON.stringify(reply.body ?? {}), {
            status,
            headers: {
              'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
              ...reply.headers,
            },
          }),
        );
      }
    }
    return Promise.resolve(
      new Response(JSON.stringify({ type: 'urn:netkar:problem:not-found', status: 404 }), {
        status: 404,
        headers: { 'Content-Type': 'application/problem+json' },
      }),
    );
  });
  vi.stubGlobal('fetch', fn);
  return { requests, fn };
}

export function problemReply(
  status: number,
  slug: string,
  headers?: Record<string, string>,
): Reply {
  return { status, body: { type: `urn:netkar:problem:${slug}`, title: slug, status }, headers };
}
