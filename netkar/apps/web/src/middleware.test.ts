import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';

import { middleware } from '@/middleware';

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
