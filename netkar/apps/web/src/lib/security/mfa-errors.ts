import { ApiError, describeApiError } from '@/lib/api/client';

/**
 * İki adımlı doğrulama ayarı hatalarını Türkçe cümleye çevirir.
 * Backend yeniden doğrulama hatalarında 403 verir (oturum geçerli olduğu için 401 değil):
 * `reauth-failed` parola, `invalid-code` kod hatasıdır. Kilit (429 `totp-locked`) süre bilgisini taşır.
 */
export function describeMfaError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.code === 'reauth-failed') return 'Parola hatalı. Güncel parolanızı yazın.';
    if (error.code === 'invalid-code') {
      return 'Kod hatalı. Doğrulama uygulamanızdaki güncel kodu ya da kullanılmamış bir kurtarma kodunu yazın.';
    }
    if (error.code === 'totp-locked') {
      const minutes = error.retryAfterSeconds ? Math.ceil(error.retryAfterSeconds / 60) : null;
      return minutes
        ? `Çok fazla hatalı deneme yapıldı. Yaklaşık ${minutes} dakika sonra tekrar deneyin.`
        : 'Çok fazla hatalı deneme yapıldı. Biraz sonra tekrar deneyin.';
    }
    if (error.code === 'totp-already-enabled') return 'İki adımlı doğrulama zaten açık.';
    if (error.code === 'totp-not-enabled') return 'İki adımlı doğrulama zaten kapalı.';
    if (error.code === 'totp-not-set-up') return 'Önce kurulumu baştan başlatın.';
  }
  return describeApiError(error, fallback);
}
