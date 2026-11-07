// Cloudflare Turnstile sunucu doğrulaması. Anahtar yok ve bayrak kapalı: bu aşamada devre dışıdır.
// Açılırken: TURNSTILE_ENABLED=true, TURNSTILE_SECRET_KEY, NEXT_PUBLIC_TURNSTILE_SITE_KEY; ayrıca
// istemcide betik yüklenmeli ve CSP'ye challenges.cloudflare.com (script ve frame) eklenmelidir.

const VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';

export type TurnstileOutcome = 'skipped' | 'passed' | 'failed' | 'misconfigured';

export interface TurnstileConfig {
  enabled: boolean;
  secret?: string | undefined;
}

export async function verifyTurnstile(
  config: TurnstileConfig,
  token: string | undefined,
  fetchImpl: typeof fetch = fetch,
): Promise<TurnstileOutcome> {
  if (!config.enabled) return 'skipped';
  // Etkin ama anahtar yoksa kapalı başarısız ol: doğrulamasız kabul etme.
  if (!config.secret) return 'misconfigured';
  if (!token) return 'failed';
  try {
    const body = new URLSearchParams({ secret: config.secret, response: token });
    const response = await fetchImpl(VERIFY_URL, { method: 'POST', body, redirect: 'error' });
    if (!response.ok) return 'failed';
    const data = (await response.json()) as { success?: unknown };
    return data.success === true ? 'passed' : 'failed';
  } catch {
    return 'failed';
  }
}
