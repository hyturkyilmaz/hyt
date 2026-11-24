import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { config, middleware } from '@/middleware';

function request(path: string, cookie?: string, headers: Record<string, string> = {}) {
  return new NextRequest(`http://127.0.0.1:3100${path}`, {
    headers: { ...(cookie ? { cookie } : {}), ...headers },
  });
}

describe('middleware oturum koruması', () => {
  it('oturum çerezi yoksa /panel için /giris?sonra=<yol> yönlendirmesi yapar', () => {
    const response = middleware(request('/panel/urunler?sayfa=2'));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get('location') ?? '');
    expect(location.pathname).toBe('/giris');
    expect(location.searchParams.get('sonra')).toBe('/panel/urunler?sayfa=2');
    expect(location.port).toBe('3100');
    expect(response.headers.get('content-security-policy')).toContain("frame-ancestors 'none'");
  });

  it('boş çerez değeri oturum sayılmaz', () => {
    const response = middleware(request('/panel', '__Host-nk_session='));
    expect(response.status).toBe(307);
  });

  it('yüzde kodlu yolla kapıyı atlatamaz', () => {
    expect(middleware(request('/%70anel')).status).toBe(307);
  });

  it('yalnız benzer adlı çerez (başka ad) oturum sayılmaz', () => {
    expect(middleware(request('/panel', 'nk_session=abc')).status).toBe(307);
  });

  it('oturum çerezi varsa geçirir ve yolu başlıkla taşır; istemci başlığını ezer', () => {
    const response = middleware(
      request('/panel/ayarlar', '__Host-nk_session=abc', { 'x-nk-path': '//evil.example' }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get('x-middleware-request-x-nk-path')).toBe('/panel/ayarlar');
    expect(response.headers.get('x-middleware-request-x-nonce')).toBeTruthy();
  });

  it('herkese açık sayfalar çerezsiz geçer', () => {
    for (const path of ['/', '/giris', '/kayit', '/kullanim-kosullari', '/kvkk-aydinlatma-metni']) {
      expect(middleware(request(path)).status).toBe(200);
    }
  });
});

// ADR-0002 / denetim Y-01: API vekili isteklerinde istemci IP başlıklarının temizlenmesi.
// NextResponse.next({ request: { headers } }) çıktısında yazılan istek başlıkları
// `x-middleware-request-<ad>` olarak, kalan tüm başlık adları `x-middleware-override-headers`
// içinde listelenir; listede olmayan başlık API'ye iletilmez.
describe('middleware /api istemci IP başlıkları', () => {
  afterEach(() => vi.unstubAllEnvs());

  const spoofed = {
    'x-forwarded-for': '6.6.6.6',
    'x-real-ip': '6.6.6.6',
    'cf-connecting-ip': '6.6.6.6',
    'true-client-ip': '6.6.6.6',
    forwarded: 'for=6.6.6.6',
    cookie: '__Host-nk_csrf=abc',
    'x-csrf-token': 'abc',
  };

  function forwarded(response: Response): string[] {
    return (response.headers.get('x-middleware-override-headers') ?? '').split(',').filter(Boolean);
  }

  it('varsayılan (none): istemcinin tüm IP başlıkları API isteğinden silinir', () => {
    const response = middleware(request('/api/v1/auth/login', undefined, spoofed));
    expect(response.status).toBe(200);
    const kept = forwarded(response);
    for (const name of [
      'x-forwarded-for',
      'x-real-ip',
      'cf-connecting-ip',
      'true-client-ip',
      'forwarded',
    ]) {
      expect(kept).not.toContain(name);
    }
    expect(kept).toEqual(expect.arrayContaining(['cookie', 'x-csrf-token']));
    expect(response.headers.get('x-middleware-request-x-forwarded-for')).toBeNull();
    // API yanıtına sayfa CSP'si veya nonce eklenmez
    expect(response.headers.get('content-security-policy')).toBeNull();
    expect(kept).not.toContain('x-nonce');
  });

  it('cf-connecting-ip kaynağı: doğrulanan IP tek X-Forwarded-For olarak yazılır, sahtesi ezilir', () => {
    vi.stubEnv('CLIENT_IP_SOURCE', 'cf-connecting-ip');
    const response = middleware(
      request('/api/v1/auth/login', undefined, { ...spoofed, 'cf-connecting-ip': '203.0.113.9' }),
    );
    expect(response.headers.get('x-middleware-request-x-forwarded-for')).toBe('203.0.113.9');
    expect(forwarded(response)).not.toContain('x-real-ip');
    expect(forwarded(response)).not.toContain('cf-connecting-ip');
  });

  it('cf-connecting-ip kaynağı: başlık yoksa sahte XFF yine de iletilmez', () => {
    vi.stubEnv('CLIENT_IP_SOURCE', 'cf-connecting-ip');
    const { 'cf-connecting-ip': _unused, ...rest } = spoofed;
    void _unused;
    const response = middleware(request('/api/v1/auth/login', undefined, rest));
    expect(forwarded(response)).not.toContain('x-forwarded-for');
  });

  it('x-forwarded-for kaynağı: sağdaki güvenilir girdi yazılır, sol taraf atılır', () => {
    vi.stubEnv('CLIENT_IP_SOURCE', 'x-forwarded-for');
    const response = middleware(
      request('/api/v1/auth/login', undefined, { 'x-forwarded-for': '6.6.6.6, 203.0.113.9' }),
    );
    expect(response.headers.get('x-middleware-request-x-forwarded-for')).toBe('203.0.113.9');
  });

  it('API yolu oturum kapısına ve yönlendirmeye takılmaz', () => {
    expect(middleware(request('/api/v1/me')).status).toBe(200);
    expect(middleware(request('/api')).status).toBe(200);
  });

  it('sayfa isteklerinde de sahte IP başlıkları temizlenir', () => {
    const response = middleware(request('/', undefined, spoofed));
    expect(forwarded(response)).not.toContain('x-forwarded-for');
    expect(forwarded(response)).not.toContain('x-real-ip');
    expect(forwarded(response)).toContain('x-nonce');
  });

  it('geçersiz CLIENT_IP_SOURCE kapalı başarısız olur', () => {
    vi.stubEnv('CLIENT_IP_SOURCE', 'herkese-guven');
    expect(() => middleware(request('/api/v1/auth/login'))).toThrow(/CLIENT_IP_SOURCE/);
  });

  it('eşleyici: API yolu prefetch başlığıyla atlatılamaz, sayfa yolu önceden getirmeyi atlar', () => {
    const [api, pages] = config.matcher as { source: string; missing?: unknown[] }[];
    expect(api).toEqual({ source: '/api/:path*' });
    expect(api!.missing).toBeUndefined();
    expect(pages!.missing).toHaveLength(2);
    expect(pages!.source).toContain('api/');
  });
});
