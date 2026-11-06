import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LoginForm } from '@/components/auth/login-form';
import {
  PasswordResetConfirmForm,
  PasswordResetRequestForm,
} from '@/components/auth/password-reset-forms';
import { RegisterForm } from '@/components/auth/register-form';
import { TwoFactorForm } from '@/components/auth/two-factor-form';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function mockFetch(status: number, body: unknown = {}) {
  const fn = vi.fn(
    async () => new Response(status === 204 ? null : JSON.stringify(body), { status }),
  );
  vi.stubGlobal('fetch', fn);
  return fn;
}

function lastRequest(fn: ReturnType<typeof vi.fn>) {
  const [url, init] = fn.mock.calls.at(-1) as unknown as [string, RequestInit];
  return { url, init, body: JSON.parse(String(init.body)) as Record<string, unknown> };
}

beforeEach(() => {
  push.mockReset();
  document.cookie = 'csrf_token=tok-test; path=/';
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
});

describe('LoginForm', () => {
  it('boş gönderimde Türkçe hata mesajlarını gösterir ve ağ çağrısı yapmaz', async () => {
    const fetchMock = mockFetch(200);
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));

    expect(await screen.findByText('E-posta adresinizi yazın.')).toBeInTheDocument();
    expect(screen.getByText('Parolanızı yazın.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByLabelText('E-posta')).toHaveAttribute('aria-invalid', 'true');
  });

  it('etiketler alanlara bağlıdır ve hata açıklaması aria-describedby ile bağlanır', async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText('E-posta'), 'gecersiz');
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));
    const email = screen.getByLabelText('E-posta');
    await waitFor(() => expect(email).toHaveAttribute('aria-invalid', 'true'));
    const describedBy = email.getAttribute('aria-describedby') ?? '';
    const message = describedBy
      .split(' ')
      .map((id) => document.getElementById(id))
      .find((node) => node?.textContent?.includes('Geçerli bir e-posta'));
    expect(message).toBeTruthy();
  });

  it('parolayı göster/gizle düğmesi türü değiştirir', async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    const input = screen.getByLabelText('Parola');
    expect(input).toHaveAttribute('type', 'password');

    await user.click(screen.getByRole('button', { name: 'Parolayı göster' }));
    expect(input).toHaveAttribute('type', 'text');
    expect(screen.getByRole('button', { name: 'Parolayı gizle' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await user.click(screen.getByRole('button', { name: 'Parolayı gizle' }));
    expect(input).toHaveAttribute('type', 'password');
  });

  it('geçerli girişte /api/v1/auth/login a CSRF başlığıyla gönderir ve panele yönlendirir', async () => {
    const fetchMock = mockFetch(200, {});
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText('E-posta'), ' ad@ornek.com ');
    await user.type(screen.getByLabelText('Parola'), 'gizli-parola');
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/panel'));
    const { url, init, body } = lastRequest(fetchMock);
    expect(url).toBe('/api/v1/auth/login');
    expect(init.method).toBe('POST');
    expect((init.headers as Headers).get('X-CSRF-Token')).toBe('tok-test');
    expect(body).toEqual({ email: 'ad@ornek.com', password: 'gizli-parola' });
  });

  it('ikinci adım gerekiyorsa /iki-adim a yönlendirir', async () => {
    mockFetch(200, { two_factor_required: true });
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'gizli-parola');
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/iki-adim'));
  });

  it('yükleniyor durumunda düğmeyi kilitler ve metni değiştirir', async () => {
    let release: (response: Response) => void = () => {};
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    );
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'gizli-parola');
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));

    const busy = await screen.findByRole('button', { name: 'Giriş yapılıyor' });
    expect(busy).toBeDisabled();
    release(new Response('{}', { status: 200 }));
    await waitFor(() => expect(push).toHaveBeenCalled());
  });

  it('401 yanıtında hesap var mı yok mu belli etmeyen tek mesaj gösterir', async () => {
    mockFetch(401, { detail: 'Kullanıcı bulunamadı' });
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'yanlis-parola');
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));

    const alert = await screen.findByText(
      'E-posta veya parola hatalı. Kontrol edip tekrar deneyin.',
    );
    expect(alert.closest('[role="alert"]')).not.toBeNull();
    expect(screen.queryByText(/bulunamadı/)).toBeNull();
    expect(push).not.toHaveBeenCalled();
  });

  it('429 ve ağ hatasında anlaşılır mesaj gösterir', async () => {
    mockFetch(429);
    const user = userEvent.setup();
    const { unmount } = render(<LoginForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'x');
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));
    expect(await screen.findByText(/Çok fazla deneme/)).toBeInTheDocument();
    unmount();

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('offline'))),
    );
    render(<LoginForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'x');
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }));
    expect(await screen.findByText(/Sunucuya ulaşılamadı/)).toBeInTheDocument();
  });
});

describe('RegisterForm', () => {
  it('kısa parola ve koşul onayı eksikliğini bildirir', async () => {
    const fetchMock = mockFetch(200);
    const user = userEvent.setup();
    render(<RegisterForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'kisa');
    await user.click(screen.getByRole('button', { name: 'Hesap oluştur' }));

    expect(await screen.findByText('Parola en az 12 karakter olmalı.')).toBeInTheDocument();
    expect(
      screen.getByText('Devam etmek için kullanım koşullarını kabul etmelisiniz.'),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('geçerli girdiyi gönderir', async () => {
    const fetchMock = mockFetch(201);
    const user = userEvent.setup();
    render(<RegisterForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'uzun bir parola cümlesi');
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Hesap oluştur' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/panel'));
    const { url, body } = lastRequest(fetchMock);
    expect(url).toBe('/api/v1/auth/register');
    expect(body).toEqual({
      email: 'ad@ornek.com',
      password: 'uzun bir parola cümlesi',
      accept_terms: true,
    });
  });

  it('kayıt çakışmasında e-posta var mı yok mu açıkça söylemez', async () => {
    mockFetch(409);
    const user = userEvent.setup();
    render(<RegisterForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.type(screen.getByLabelText('Parola'), 'uzun bir parola cümlesi');
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Hesap oluştur' }));
    expect(await screen.findByText(/kayıt tamamlanamadı/)).toBeInTheDocument();
  });
});

describe('TwoFactorForm', () => {
  it('rakam dışı kodu reddeder, geçerli kodu gönderir', async () => {
    const fetchMock = mockFetch(200);
    const user = userEvent.setup();
    render(<TwoFactorForm />);
    const input = screen.getByLabelText('Doğrulama kodu');
    expect(input).toHaveAttribute('autocomplete', 'one-time-code');
    expect(input).toHaveAttribute('inputmode', 'numeric');

    await user.type(input, '12ab');
    await user.click(screen.getByRole('button', { name: 'Doğrula' }));
    expect(
      await screen.findByText('Kod 6 haneli olmalı ve yalnız rakam içermeli.'),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.clear(input);
    await user.type(input, '123456');
    await user.click(screen.getByRole('button', { name: 'Doğrula' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/panel'));
    expect(lastRequest(fetchMock).body).toEqual({ code: '123456' });
  });

  it('hatalı kodda mesaj gösterir', async () => {
    mockFetch(401);
    const user = userEvent.setup();
    render(<TwoFactorForm />);
    await user.type(screen.getByLabelText('Doğrulama kodu'), '000000');
    await user.click(screen.getByRole('button', { name: 'Doğrula' }));
    expect(await screen.findByText(/Kod hatalı veya süresi dolmuş/)).toBeInTheDocument();
  });
});

describe('Parola sıfırlama', () => {
  it('e-posta isteğinden sonra hesap sızdırmayan onay gösterir', async () => {
    const fetchMock = mockFetch(202);
    const user = userEvent.setup();
    render(<PasswordResetRequestForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ad@ornek.com');
    await user.click(screen.getByRole('button', { name: 'Bağlantı gönder' }));

    expect(await screen.findByText(/adresi kayıtlıysa/)).toBeInTheDocument();
    expect(lastRequest(fetchMock).url).toBe('/api/v1/auth/password-reset/request');
  });

  it('yeni parolayı token ile gönderir ve girişe yönlendirir', async () => {
    const fetchMock = mockFetch(204);
    const user = userEvent.setup();
    render(<PasswordResetConfirmForm token="abcdefghijklmnop1234" />);
    await user.type(screen.getByLabelText('Yeni parola'), 'yeni uzun parola cümlesi');
    await user.click(screen.getByRole('button', { name: 'Parolayı güncelle' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/giris'));
    const { url, body } = lastRequest(fetchMock);
    expect(url).toBe('/api/v1/auth/password-reset/confirm');
    expect(body).toEqual({ token: 'abcdefghijklmnop1234', password: 'yeni uzun parola cümlesi' });
  });

  it('süresi dolmuş bağlantıda açıklayıcı mesaj gösterir', async () => {
    mockFetch(410);
    const user = userEvent.setup();
    render(<PasswordResetConfirmForm token="abcdefghijklmnop1234" />);
    await user.type(screen.getByLabelText('Yeni parola'), 'yeni uzun parola cümlesi');
    await user.click(screen.getByRole('button', { name: 'Parolayı güncelle' }));
    expect(await screen.findByText(/süresi dolmuş veya daha önce kullanılmış/)).toBeInTheDocument();
  });
});
