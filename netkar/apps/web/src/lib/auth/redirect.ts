import { DEFAULT_AFTER_LOGIN_PATH, LOGIN_PATH, NEXT_PARAM } from '@/lib/auth/constants';

// Giriş sonrası yönlendirme hedefi kullanıcıdan (sorgu dizesi) gelir; açık yönlendirme
// (open redirect) açığı olmaması için yalnız uygulama içi, göreli yollar kabul edilir.
const MAX_LENGTH = 512;
const PLACEHOLDER_ORIGIN = 'http://netkar.invalid';
// Giriş akışının kendi sayfalarına geri yönlendirme döngü yaratır.
const AUTH_PATHS = new Set(['/giris', '/kayit', '/iki-adim', '/sifre-sifirla']);

function hasControlOrBackslash(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    // Denetim karakterleri (tab ve satır sonu tarayıcıda silinip "//" oluşturabilir) ve ters eğik çizgi
    if (code <= 0x1f || code === 0x7f || char === '\\') return true;
  }
  return false;
}

/**
 * Giriş sonrası gidilecek yolu doğrular. Geçersizse `fallback` döner.
 * Kabul: "/" ile başlayan, "//" veya "/\" ile başlamayan, aynı kökende kalan, giriş sayfaları dışındaki yollar.
 */
export function safeNextPath(
  raw: string | string[] | null | undefined,
  fallback: string = DEFAULT_AFTER_LOGIN_PATH,
): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_LENGTH) return fallback;
  if (!value.startsWith('/') || value.startsWith('//')) return fallback;
  if (hasControlOrBackslash(value)) return fallback;

  let url: URL;
  try {
    url = new URL(value, PLACEHOLDER_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== PLACEHOLDER_ORIGIN) return fallback;

  // Yüzde kodlu biçimle gizlenmiş "//" veya "\" denemelerini de reddet.
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch {
    return fallback;
  }
  if (decodedPath.startsWith('//') || hasControlOrBackslash(decodedPath)) return fallback;
  if (AUTH_PATHS.has(url.pathname.replace(/\/+$/, ''))) return fallback;

  return `${url.pathname}${url.search}`;
}

/** /giris?sonra=<yol> adresi; hedef doğrulanır, geçersizse yalnız /giris döner. */
export function buildLoginUrl(target?: string | null): string {
  const safe = safeNextPath(target, '');
  if (!safe) return LOGIN_PATH;
  return `${LOGIN_PATH}?${NEXT_PARAM}=${encodeURIComponent(safe)}`;
}

/** /iki-adim adresine hedefi taşır (varsayılan hedefse sorgu eklenmez). */
export function buildTwoFactorUrl(next: string): string {
  const safe = safeNextPath(next);
  return safe === DEFAULT_AFTER_LOGIN_PATH
    ? '/iki-adim'
    : `/iki-adim?${NEXT_PARAM}=${encodeURIComponent(safe)}`;
}

/** Yolun oturum gerektiren panel alanında olup olmadığı (/panel ve altı). */
export function isProtectedPath(pathname: string): boolean {
  let path = pathname;
  try {
    path = decodeURIComponent(pathname);
  } catch {
    // Çözülemeyen yol aynen değerlendirilir.
  }
  return path === '/panel' || path.startsWith('/panel/');
}
