// Cloudflare Turnstile için ayrılmış yer. Anahtar yok ve bayrak kapalı olduğu için şu an hiçbir
// şey çizmez ve betik yüklemez. Açarken: NEXT_PUBLIC_TURNSTILE_SITE_KEY ile widget burada
// bağlanır, `onToken` çağrılır; sunucuda TURNSTILE_ENABLED=true ve TURNSTILE_SECRET_KEY ayarlanır;
// CSP'ye challenges.cloudflare.com eklenir (src/lib/csp.ts). Bkz. src/lib/waitlist/turnstile.ts.

export const TURNSTILE_ENABLED = process.env.NEXT_PUBLIC_TURNSTILE_ENABLED === 'true';

export function TurnstileSlot({ onToken }: { onToken: (token: string) => void }) {
  void onToken;
  if (!TURNSTILE_ENABLED) return null;
  return <div data-turnstile-slot className="min-h-16" />;
}
