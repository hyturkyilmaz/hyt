import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LogoutButton } from '@/components/panel/logout-button';

const replace = vi.fn();
const refresh = vi.fn();
const toastError = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace, refresh }) }));
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

beforeEach(() => {
  replace.mockReset();
  refresh.mockReset();
  toastError.mockReset();
  document.cookie = '__Host-nk_csrf=tok-test; path=/; Secure';
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = '__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure';
});

describe('LogoutButton', () => {
  it('POST /auth/logout çağırır (CSRF başlığıyla) ve girişe yönlendirir', async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<LogoutButton />);

    await user.click(screen.getByRole('button', { name: 'Çıkış yap' }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/giris'));
    expect(refresh).toHaveBeenCalled();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/auth/logout');
    expect(init.method).toBe('POST');
    expect((init.headers as Headers).get('X-CSRF-Token')).toBe('tok-test');
  });

  it('simge sürümünde erişilebilir ad taşır', () => {
    render(<LogoutButton variant="icon" />);
    expect(screen.getByRole('button', { name: 'Çıkış yap' })).toBeInTheDocument();
  });

  it('hata olursa yönlendirmez, bildirim gösterir ve düğmeyi açar', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('offline'))),
    );
    const user = userEvent.setup();
    render(<LogoutButton />);
    await user.click(screen.getByRole('button', { name: 'Çıkış yap' }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Çıkış yap' })).toBeEnabled();
  });
});
