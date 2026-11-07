import { PRIVACY_NOTICE_VERSION, waitlistSchema, type WaitlistEntry } from './schema';
import type { RateLimiter } from './rate-limit';
import type { WaitlistSink } from './sink';
import { verifyTurnstile, type TurnstileConfig } from './turnstile';

const MAX_BODY_BYTES = 4096;

export interface WaitlistDeps {
  /** Kanonik site kökeni (https://alan.adi); Origin başlığı bununla eşleşmeli */
  siteOrigin: string;
  sink: WaitlistSink | null;
  turnstile: TurnstileConfig;
  limiter: RateLimiter;
  now?: () => Date;
  fetchImpl?: typeof fetch;
}

function problem(status: number, slug: string, extra: Record<string, unknown> = {}, headers = {}) {
  return new Response(JSON.stringify({ type: `urn:netkar:problem:${slug}`, status, ...extra }), {
    status,
    headers: {
      'Content-Type': 'application/problem+json',
      'Cache-Control': 'no-store',
      ...headers,
    },
  });
}

function ok() {
  return new Response(JSON.stringify({ status: 'ok' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

// Aynı site dışından gelen tarayıcı isteklerini reddeder (CSRF). Tarayıcı dışı istemciler
// Origin göndermez; bu uç nokta yalnız sitenin kendi formu içindir.
function isSameSite(request: Request, siteOrigin: string): boolean {
  const origin = request.headers.get('origin');
  if (origin) return origin === siteOrigin;
  return request.headers.get('sec-fetch-site') === 'same-origin';
}

// Rate limit anahtarı: middleware'in ADR-0002'ye göre yazdığı tek X-Forwarded-For değeri.
function clientKey(request: Request): string {
  return request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'anonim';
}

export async function handleWaitlistRequest(
  request: Request,
  deps: WaitlistDeps,
): Promise<Response> {
  if (!isSameSite(request, deps.siteOrigin)) return problem(403, 'forbidden-origin');

  const contentType = request.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().startsWith('application/json')) {
    return problem(415, 'unsupported-media-type');
  }

  const limit = deps.limiter.check(clientKey(request));
  if (!limit.allowed) {
    return problem(429, 'rate-limited', {}, { 'Retry-After': String(limit.retryAfterSeconds) });
  }

  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES)
    return problem(413, 'payload-too-large');

  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch {
    return problem(400, 'invalid-json');
  }

  const parsed = waitlistSchema.safeParse(json);
  if (!parsed.success) {
    const errors = parsed.error.issues.map((issue) => ({
      field: String(issue.path[0] ?? ''),
      code: issue.code,
    }));
    return problem(422, 'validation-error', { errors });
  }
  const data = parsed.data;

  // Bot tuzağı doluysa başarılı gibi yanıtla, kaydetme.
  if (data.website && data.website.length > 0) return ok();

  const outcome = await verifyTurnstile(deps.turnstile, data.turnstileToken, deps.fetchImpl);
  if (outcome === 'misconfigured') return problem(503, 'verification-unavailable');
  if (outcome === 'failed') return problem(400, 'verification-failed');

  if (!deps.sink) return problem(503, 'waitlist-unavailable');

  const now = (deps.now ?? (() => new Date()))().toISOString();
  const entry: WaitlistEntry = {
    email: data.email,
    storeCategory: data.storeCategory ?? null,
    monthlyOrders: data.monthlyOrders,
    marketingConsent: data.marketingConsent,
    marketingConsentAt: data.marketingConsent ? now : null,
    privacyNoticeVersion: PRIVACY_NOTICE_VERSION,
    createdAt: now,
  };
  try {
    // Kayıt zaten varsa da aynı yanıt verilir: e-posta var mı yok mu sızdırılmaz.
    await deps.sink.add(entry);
  } catch {
    return problem(503, 'waitlist-unavailable');
  }
  return ok();
}
