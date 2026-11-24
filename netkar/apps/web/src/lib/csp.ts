// İçerik Güvenlik Politikası (CSP) üretici. middleware.ts her istekte yeni bir nonce ile çağırır.

export interface CspOptions {
  nonce: string;
  isDev: boolean;
}

export function buildCsp({ nonce, isDev }: CspOptions): string {
  const directives: Record<string, string[]> = {
    'default-src': ["'self'"],
    // strict-dynamic: nonce'lu betiğin yüklediği betikler de çalışır, host listesi gerekmez.
    // Geliştirmede React'in hata yığını için eval gerekir; üretimde yoktur.
    'script-src': [
      "'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      ...(isDev ? ["'unsafe-eval'"] : []),
    ],
    // Sonner ve Radix çalışma anında satır içi stil yazar; stil enjeksiyonu betik enjeksiyonu kadar
    // riskli değildir ve nonce bu kitaplıklarda desteklenmez. Betikler nonce ile korunur.
    'style-src': ["'self'", "'unsafe-inline'"],
    'img-src': ["'self'", 'data:', 'blob:'],
    'font-src': ["'self'"],
    'connect-src': ["'self'"],
    'manifest-src': ["'self'"],
    'worker-src': ["'self'"],
    'object-src': ["'none'"],
    'base-uri': ["'self'"],
    'form-action': ["'self'"],
    'frame-ancestors': ["'none'"],
  };

  const parts = Object.entries(directives).map(([name, values]) => `${name} ${values.join(' ')}`);
  if (!isDev) parts.push('upgrade-insecure-requests');
  return parts.join('; ');
}

export function createNonce(): string {
  // Edge çalışma zamanında da bulunan Web Crypto ile 128 bit rastgele değer
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
