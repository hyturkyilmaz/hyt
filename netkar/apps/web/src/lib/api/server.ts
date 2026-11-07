import { cookies } from 'next/headers';

import { getEnv } from '@/config/env';
import type { MeResponse } from '@/lib/api/endpoints';
import { SESSION_COOKIE_NAME } from '@/lib/auth/constants';

// Yalnız sunucu bileşenlerinde ve route handler'larda kullanılır (next/headers).
// Tarayıcıdaki /api/v1 vekili yerine API_BASE_URL'e doğrudan gider.
const ME_TIMEOUT_MS = 5000;

export type SessionResult =
  | { status: 'authenticated'; me: MeResponse }
  | { status: 'unauthenticated' }
  // API'ye ulaşılamadı veya beklenmeyen yanıt verdi: oturum geçerli sayılmaz ama çıkış da yaptırılmaz.
  | { status: 'unavailable' };

function isMeResponse(value: unknown): value is MeResponse {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.user_id === 'string' &&
    typeof record.email === 'string' &&
    typeof record.role === 'string' &&
    typeof record.tenant === 'object' &&
    record.tenant !== null
  );
}

/**
 * Oturum çerezini `GET /v1/me` ile doğrular. Yalnız oturum çerezi API'ye iletilir (diğer çerezler
 * ve başlıklar değil). 401 geçersiz/süresi dolmuş oturumdur; ağ hatası ve 5xx "unavailable" döner.
 */
export async function getSession(fetchImpl: typeof fetch = fetch): Promise<SessionResult> {
  const token = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!token) return { status: 'unauthenticated' };

  let response: Response;
  try {
    response = await fetchImpl(`${getEnv().API_BASE_URL}/v1/me`, {
      method: 'GET',
      headers: { Accept: 'application/json', Cookie: `${SESSION_COOKIE_NAME}=${token}` },
      cache: 'no-store',
      redirect: 'manual',
      signal: AbortSignal.timeout(ME_TIMEOUT_MS),
    });
  } catch {
    return { status: 'unavailable' };
  }

  if (response.status === 401) return { status: 'unauthenticated' };
  if (!response.ok) return { status: 'unavailable' };

  try {
    const data: unknown = await response.json();
    return isMeResponse(data) ? { status: 'authenticated', me: data } : { status: 'unavailable' };
  } catch {
    return { status: 'unavailable' };
  }
}
