import { NextResponse, type NextRequest } from 'next/server';

import { PATH_HEADER, SESSION_COOKIE_NAME } from '@/lib/auth/constants';
import { buildLoginUrl, isProtectedPath } from '@/lib/auth/redirect';
import { parseClientIpConfig, sanitizeClientIpHeaders } from '@/lib/client-ip';
import { buildCsp, createNonce } from '@/lib/csp';

// Her istekte yeni nonce üretir, CSP başlığını hem isteğe (Next.js betiklere nonce'u buradan
// okur) hem yanıta yazar. Kalan güvenlik başlıkları next.config.ts içindedir.
// Ek olarak /panel altında oturum çerezi yoksa /giris?sonra=<yol> adresine yönlendirir. Bu yalnız
// ilk (kaba) kapıdır: çerezin geçerli olup olmadığını panel layout'u `GET /v1/me` ile doğrular.
//
// /api/* istekleri (next.config.ts rewrites ile API'ye vekillenir) için asıl iş istemci IP
// başlıklarının temizlenmesidir (ADR-0002): istemcinin yazdığı X-Forwarded-For, X-Real-IP,
// CF-Connecting-IP vb. silinir; dağıtımın seçtiği tek kaynaktan doğrulanan IP tek bir
// X-Forwarded-For değeri olarak API'ye iletilir.
export function middleware(request: NextRequest) {
  // Geçersiz yapılandırma istisna fırlatır (500): sahte başlığa güvenmektense kapalı başarısız ol.
  const ipConfig = parseClientIpConfig(process.env);
  const sanitizedHeaders = sanitizeClientIpHeaders(request.headers, ipConfig);

  if (isApiProxyPath(request.nextUrl.pathname)) {
    return NextResponse.next({ request: { headers: sanitizedHeaders } });
  }

  const nonce = createNonce();
  const csp = buildCsp({ nonce, isDev: process.env.NODE_ENV !== 'production' });
  const { pathname, search } = request.nextUrl;

  if (isProtectedPath(pathname) && !request.cookies.get(SESSION_COOKIE_NAME)?.value) {
    const target = new URL(buildLoginUrl(`${pathname}${search}`), request.url);
    const redirect = NextResponse.redirect(target);
    redirect.headers.set('Content-Security-Policy', csp);
    redirect.headers.set('Cache-Control', 'no-store');
    return redirect;
  }

  const requestHeaders = new Headers(sanitizedHeaders);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', csp);
  // İstemciden gelen sahte değer ezilir; yalnız bu middleware yazar.
  requestHeaders.set(PATH_HEADER, `${pathname}${search}`);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

function isApiProxyPath(pathname: string): boolean {
  return pathname === '/api' || pathname.startsWith('/api/');
}

export const config = {
  matcher: [
    {
      // API vekili: koşulsuz çalışır. Prefetch başlığı (istemci yazabilir) bu yolda middleware'i
      // atlatmak için kullanılamaz; yoksa temizlenmemiş XFF API'ye ulaşırdı.
      source: '/api/:path*',
    },
    {
      // Sayfalar (CSP + oturum kapısı): statik dosyalar hariç; önceden getirme istekleri de atlanır.
      source: '/((?!api/|api$|_next/static|_next/image|favicon.ico).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
