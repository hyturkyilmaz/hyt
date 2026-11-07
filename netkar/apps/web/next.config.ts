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

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
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
