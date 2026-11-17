import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EmailVerifyView } from '@/components/auth/email-verify-view';

const TOKEN = 'A'.repeat(43);

function mockFetch(status: number, body: unknown = {}) {
  const fn = vi.fn(
    async () =>
      new Response(status === 204 ? null : JSON.stringify(body), {
        status,
        headers: {
          'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
        },
      }),
  );
  vi.stubGlobal('fetch', fn);
  return fn;
}

beforeEach(() => {
  document.cookie = '__Host-nk_csrf=tok-test; path=/; Secure';
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = '__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure';
});

describe('EmailVerifyView', () => {
  it('yükleniyor durumunu gösterir, sonra token ile tek istek atar ve başarıyı bildirir', async () => {
    const fetchMock = mockFetch(204);
    render(<EmailVerifyView token={TOKEN} />);

    expect(screen.getByRole('status')).toHaveTextContent('bağlantı kontrol ediliyor');
    expect(
      await screen.findByRole('heading', { name: 'E-postanız doğrulandı' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Panele git' })).toHaveAttribute('href', '/panel');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/auth/email/verify');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ token: TOKEN });
    expect((init.headers as Headers).get('X-CSRF-Token')).toBe('tok-test');
  });

  it('geçersiz ya da kullanılmış bağlantıda anlaşılır hata ve girişe bağlantı gösterir', async () => {
    mockFetch(400, {
      type: 'urn:netkar:problem:invalid-verification-token',
      title: 'Geçersiz bağlantı',
      status: 400,
    });
    render(<EmailVerifyView token={TOKEN} />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('süresi dolmuş veya daha önce kullanılmış');
    expect(screen.getByRole('heading', { name: 'E-posta doğrulanamadı' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Girişe git' })).toHaveAttribute('href', '/giris');
  });

  it('ağ hatasında genel hata gösterir', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('offline'))),
    );
    render(<EmailVerifyView token={TOKEN} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Sunucuya ulaşılamadı');
  });

  it('token yoksa API çağrısı yapmadan hata gösterir', async () => {
    const fetchMock = mockFetch(204);
    render(<EmailVerifyView token={null} />);
    expect(screen.getByRole('alert')).toHaveTextContent('eksik ya da bozuk');
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });
});
