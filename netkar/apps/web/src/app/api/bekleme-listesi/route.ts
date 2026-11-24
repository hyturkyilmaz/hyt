import { getEnv } from '@/config/env';
import { handleWaitlistRequest } from '@/lib/waitlist/handler';
import { createRateLimiter } from '@/lib/waitlist/rate-limit';
import { resolveSink } from '@/lib/waitlist/sink';

// Bekleme listesi kaydı. Şimdilik API'ye değil, WaitlistSink arayüzüne yazar (bellek veya dosya).
// E-posta gönderimi yoktur. Gerçek kayıt uç noktası sonraki turda API'ye taşınır.
export const dynamic = 'force-dynamic';

// Aynı kaynaktan 10 dakikada en fazla 20 kayıt denemesi
const limiter = createRateLimiter({ limit: 20, windowMs: 10 * 60 * 1000 });

export async function POST(request: Request): Promise<Response> {
  const env = getEnv();
  return handleWaitlistRequest(request, {
    siteOrigin: new URL(env.NEXT_PUBLIC_SITE_URL).origin,
    sink: resolveSink(env),
    turnstile: { enabled: env.TURNSTILE_ENABLED, secret: env.TURNSTILE_SECRET_KEY },
    limiter,
  });
}
