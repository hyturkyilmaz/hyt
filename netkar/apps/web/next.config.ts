import type { NextConfig } from 'next';

// API_BASE_URL burada doğrudan okunur (next.config yükleme sırasında src/ takma adları yoktur).
// Şema doğrulaması src/config/env.ts içindedir ve uygulama açılışında çalışır.
const apiBaseUrl = (process.env.API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');

// CSP nonce tabanlıdır ve src/middleware.ts içinde üretilir; burada nonce gerektirmeyenler var.
const securityHeaders = [
  { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  {
    key: 'Permissions-Policy',
    value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()',
  },
  // CSP frame-ancestors 'none' ile aynı; eski tarayıcılar için
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
];

// Rapor zaman aşımı zinciri (içten dışa): PostgreSQL statement_timeout 40 sn, API rapor hesap sınırı 45 sn
// (PROFIT_REPORT_COMPUTE_TIMEOUT_SECONDS), tek uçuş bekleme sınırı 25 sn (PROFIT_REPORT_CACHE_WAIT_SECONDS),
// Next.js rewrite vekili 55 sn, Caddy yanıt sınırı 60 sn. Vekilin varsayılanı 30 sn'dir (next@15.5.29:
// `proxyTimeout || 30000`); varsayılan kalırsa 30 sn'den uzun rapor web katmanında kopar ve API'nin 503
// report-compute-timeout (problem+json) yanıtı kullanıcıya ulaşmaz.
// Bekleme (25 sn) ve hesap TEK toplam bütçeyi paylaşır (services/api report_cache.get_or_compute): bekleyen
// istek, hesaplayan başarısız olunca kendi hesabını yalnız KALAN bütçeyle (45 sn - geçen süre) başlatır;
// kalan 6 sn'nin altındaysa hesap başlamadan 503 report-compute-timeout döner. PostgreSQL statement_timeout da
// kalan süreden türetilir (kalan - 5 sn, en az 1 sn). Tipik yolda süre yaklaşık 45 sn artı istek öncesi işlerdir
// (bağlantı havuzu beklemesi en çok 5 sn) ve 55 sn vekilin altında kalır. İstisnalar bütçe dışındadır: ayar ve
// veri sürümü sorgularını yalnız statement_timeout sınırlar; veritabanı aşamasında asyncio iptali (DK-05)
// yaklaşık 10 sn ekleyebilir. Bu nadir yollarda vekil kesebilir (5xx).
// Vekil Caddy'nin 60 sn sınırından kısa kalmalıdır: bu değeri yükseltmeyin (guard testi: next.config.test.ts).
export const PROXY_TIMEOUT_MS = 55_000;

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // Docker imajı için .next/standalone çıktısı (apps/web/Dockerfile): yalnız gerekli node_modules izlenir.
  output: 'standalone',
  experimental: {
    proxyTimeout: PROXY_TIMEOUT_MS,
  },
  async rewrites() {
    // Backend yolları /v1/... biçimindedir (services/api: api_router prefix="/v1"; "/api" öneki yok).
    // Tarayıcı aynı kökende /api/v1/... çağırır; vekil önekteki "/api" kısmını atar.
    return [{ source: '/api/v1/:path*', destination: `${apiBaseUrl}/v1/:path*` }];
  },
  async redirects() {
    // Backend e-postalarındaki bağlantılar İngilizce yollar kullanır (WEB_BASE_URL + /login,
    // /forgot-password, /reset-password?token=...). Web yolları Türkçedir; sorgu dizesi korunur.
    return [
      { source: '/login', destination: '/giris', permanent: false },
      { source: '/forgot-password', destination: '/sifre-sifirla', permanent: false },
      { source: '/reset-password', destination: '/sifre-sifirla', permanent: false },
    ];
  },
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
};

export default nextConfig;
