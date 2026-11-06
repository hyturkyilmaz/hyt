import { NextResponse, type NextRequest } from 'next/server';

import { buildCsp, createNonce } from '@/lib/csp';

// Her istekte yeni nonce üretir, CSP başlığını hem isteğe (Next.js betiklere nonce'u buradan
// okur) hem yanıta yazar. Kalan güvenlik başlıkları next.config.ts içindedir.
export function middleware(request: NextRequest) {
  const nonce = createNonce();
  const csp = buildCsp({ nonce, isDev: process.env.NODE_ENV !== 'production' });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

export const config = {
  matcher: [
    {
      // API proxy'si ve statik dosyalar hariç; önceden getirme (prefetch) istekleri de atlanır.
      source: '/((?!api/|_next/static|_next/image|favicon.ico).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
