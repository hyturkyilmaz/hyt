// Çift gönderim (double submit) CSRF: API `GET /v1/auth/csrf` ile `__Host-nk_csrf` çerezini
// (JS ile okunabilir, HttpOnly değil) set eder; biz aynı değeri X-CSRF-Token başlığında geri
// yollarız. Oturum çerezi (`__Host-nk_session`) HttpOnly'dir ve JS tarafından okunamaz.
// Adlar backend'deki services/api/app/core/middleware.py ve cookies.py ile birebir aynıdır.
export const CSRF_COOKIE_NAME = '__Host-nk_csrf';
export const CSRF_HEADER_NAME = 'X-CSRF-Token';

export function readCookie(name: string, cookieString?: string): string | undefined {
  const source = cookieString ?? (typeof document === 'undefined' ? '' : document.cookie);
  for (const part of source.split(';')) {
    const separator = part.indexOf('=');
    if (separator === -1) continue;
    if (part.slice(0, separator).trim() !== name) continue;
    const value = part.slice(separator + 1).trim();
    try {
      return decodeURIComponent(value);
    } catch {
      return undefined;
    }
  }
  return undefined;
}

export function readCsrfToken(cookieString?: string): string | undefined {
  return readCookie(CSRF_COOKIE_NAME, cookieString);
}
