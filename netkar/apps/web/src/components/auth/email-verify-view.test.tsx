import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  vi.restoreAllMocks();
  window.history.replaceState(null, '', '/');
  document.cookie = '__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure';
});

describe('EmailVerifyView', () => {
  it('sayfa açılınca istek ATMAZ; açık bir doğrulama düğmesi gösterir', async () => {
    const fetchMock = mockFetch(204);
    render(<EmailVerifyView token={TOKEN} />);

    expect(screen.getByRole('button', { name: 'E-postamı doğrula' })).toBeEnabled();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('token adres çubuğundan silinir (yol korunur)', async () => {
    window.history.replaceState(null, '', `/e-posta-dogrula?token=${TOKEN}`);
    render(<EmailVerifyView token={TOKEN} />);
    await waitFor(() => expect(window.location.search).toBe(''));
    expect(window.location.pathname).toBe('/e-posta-dogrula');
    expect(window.location.href).not.toContain(TOKEN);
  });

  it('düğmeye basınca token ile tek istek atar ve başarıyı bildirir', async () => {
    const fetchMock = mockFetch(204);
    const user = userEvent.setup();
    render(<EmailVerifyView token={TOKEN} />);

    await user.click(screen.getByRole('button', { name: 'E-postamı doğrula' }));

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

  it('yükleniyor durumunda düğme devre dışıdır', async () => {
    let release: (value: Response) => void = () => {};
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    );
    const user = userEvent.setup();
    render(<EmailVerifyView token={TOKEN} />);
    await user.click(screen.getByRole('button', { name: 'E-postamı doğrula' }));
    expect(await screen.findByRole('button', { name: 'Doğrulanıyor' })).toBeDisabled();
    release(new Response(null, { status: 204 }));
    expect(
      await screen.findByRole('heading', { name: 'E-postanız doğrulandı' }),
    ).toBeInTheDocument();
  });

  it('geçersiz, kullanılmış ya da başka hesaba ait bağlantıda anlaşılır hata gösterir', async () => {
    mockFetch(400, {
      type: 'urn:netkar:problem:invalid-verification-token',
      title: 'Geçersiz bağlantı',
      status: 400,
    });
    const user = userEvent.setup();
    render(<EmailVerifyView token={TOKEN} />);
    await user.click(screen.getByRole('button', { name: 'E-postamı doğrula' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('şu an giriş yaptığınız hesaba ait değil');
    expect(screen.getByRole('link', { name: 'Girişe git' })).toHaveAttribute('href', '/giris');
  });

  it('oturum düştüyse (401) girişe yönlendiren mesaj verir', async () => {
    mockFetch(401, { type: 'urn:netkar:problem:unauthorized', title: 'x', status: 401 });
    const user = userEvent.setup();
    render(<EmailVerifyView token={TOKEN} />);
    await user.click(screen.getByRole('button', { name: 'E-postamı doğrula' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Oturumunuz sona ermiş');
  });

  it('ağ hatasında genel hata gösterir', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('offline'))),
    );
    const user = userEvent.setup();
    render(<EmailVerifyView token={TOKEN} />);
    await user.click(screen.getByRole('button', { name: 'E-postamı doğrula' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Sunucuya ulaşılamadı');
  });

  it('token yoksa API çağrısı yapmadan hata gösterir', async () => {
    const fetchMock = mockFetch(204);
    render(<EmailVerifyView token={null} />);
    expect(screen.getByRole('alert')).toHaveTextContent('eksik ya da bozuk');
    expect(screen.queryByRole('button', { name: 'E-postamı doğrula' })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });
});
