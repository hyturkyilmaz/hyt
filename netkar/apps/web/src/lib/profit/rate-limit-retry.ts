import { ApiError } from '@/lib/api/client';

/** `Retry-After` bu kadar saniyeden uzunsa beklenmez; kullanıcı "Tekrar dene" düğmesiyle karar verir. */
const MAX_WAIT_SECONDS = 30;
/** Başlık yoksa ya da geçersizse bu kadar beklenir. */
const DEFAULT_WAIT_SECONDS = 1;

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('İptal edildi', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new DOMException('İptal edildi', 'AbortError'));
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * Y-8: 429 yanıtında `Retry-After` kadar bekleyip isteği BİR kez yeniden dener. Diğer hatalar, ikinci 429 ve
 * uzun beklemeler olduğu gibi yükselir (ekran "Tekrar dene" düğmesi sunar). Bekleme `signal` ile iptal edilir.
 */
export async function retryOnceOnRateLimit<T>(
  request: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  try {
    return await request();
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 429) throw error;
    const seconds = error.retryAfterSeconds ?? DEFAULT_WAIT_SECONDS;
    if (seconds > MAX_WAIT_SECONDS) throw error;
    await sleep(seconds * 1000, signal);
    return request();
  }
}
