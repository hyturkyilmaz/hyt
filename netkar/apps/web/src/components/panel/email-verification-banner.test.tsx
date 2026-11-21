import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EmailVerificationBanner } from '@/components/panel/email-verification-banner';

const refresh = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
vi.mock('sonner', () => ({
  toast: { error: (m: string) => toastError(m), success: (m: string) => toastSuccess(m) },
}));

function mockFetch(status: number, body: unknown = { status: 'accepted' }) {
  const fn = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
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
  refresh.mockReset();
  toastError.mockReset();
  toastSuccess.mockReset();
  document.cookie = '__Host-nk_csrf=tok-test; path=/; Secure';
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = '__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure';
});

describe('EmailVerificationBanner', () => {
  it('doğrulanmış hesapta hiçbir şey çizmez', () => {
    const { container } = render(<EmailVerificationBanner verified email="a@ornek.com" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('doğrulanmamış hesapta nedeni söyler ve yeniden gönder düğmesi sunar', async () => {
    const fetchMock = mockFetch(202);
    const user = userEvent.setup();
    render(<EmailVerificationBanner verified={false} email="a@ornek.com" />);

    expect(screen.getByText('E-posta adresinizi doğrulayın.')).toBeInTheDocument();
    expect(screen.getByText(/mağaza bağlama ve maliyet girişi kapalıdır/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Yeniden gönder' }));

    expect(await screen.findByRole('status')).toHaveTextContent('yeni bir bağlantı gönderdik');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/auth/email/resend');
    expect(init.method).toBe('POST');
    expect((init.headers as Headers).get('X-CSRF-Token')).toBe('tok-test');
    expect(toastSuccess).toHaveBeenCalled();
  });

  it('hız sınırında (429) hata bildirir ve düğmeyi yeniden açar', async () => {
    mockFetch(429, { type: 'urn:netkar:problem:rate-limited', title: 'x', status: 429 });
    const user = userEvent.setup();
    render(<EmailVerificationBanner verified={false} email="a@ornek.com" />);
    await user.click(screen.getByRole('button', { name: 'Yeniden gönder' }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(expect.stringContaining('Çok fazla')),
    );
    expect(screen.getByRole('button', { name: 'Yeniden gönder' })).toBeEnabled();
  });

  it('başka yerde zaten doğrulanmışsa sayfayı yeniler', async () => {
    mockFetch(409, { type: 'urn:netkar:problem:email-already-verified', title: 'x', status: 409 });
    const user = userEvent.setup();
    render(<EmailVerificationBanner verified={false} email="a@ornek.com" />);
    await user.click(screen.getByRole('button', { name: 'Yeniden gönder' }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(toastError).not.toHaveBeenCalled();
  });
});
