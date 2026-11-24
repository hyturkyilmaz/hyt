import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LegalReacceptanceBanner } from '@/components/panel/legal-reacceptance-banner';
import type { LegalPending } from '@/lib/api/endpoints';

const refresh = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
vi.mock('sonner', () => ({
  toast: { error: (m: string) => toastError(m), success: (m: string) => toastSuccess(m) },
}));

const TERMS: LegalPending = {
  doc_type: 'terms',
  version: '2026-12-a',
  published_at: '2026-12-01T00:00:00Z',
};
const NOTICE: LegalPending = {
  doc_type: 'privacy_notice',
  version: '2026-12-a',
  published_at: '2026-12-01T00:00:00Z',
};

function mockFetch(status: number, body: unknown) {
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

describe('LegalReacceptanceBanner', () => {
  it('bekleyen sürüm yoksa hiçbir şey çizmez', () => {
    const { container } = render(<LegalReacceptanceBanner pending={[]} enforced={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('bekleyen belgeleri sürümüyle, var olan sayfalara bağlantıyla listeler', () => {
    render(<LegalReacceptanceBanner pending={[TERMS, NOTICE]} enforced={false} />);
    expect(screen.getByRole('link', { name: 'Kullanım koşulları' })).toHaveAttribute(
      'href',
      '/kullanim-kosullari',
    );
    expect(screen.getByRole('link', { name: 'Aydınlatma metni' })).toHaveAttribute(
      'href',
      '/kvkk-aydinlatma-metni',
    );
    expect(screen.getAllByText(/yeni sekmede açılır; sürüm 2026-12-a/)).toHaveLength(2);
    // Aydınlatma yalnız "okudum"; açık rıza ya da kabul dili yoktur.
    const notice = screen.getByRole('checkbox', { name: /Aydınlatma metni/ });
    expect(notice.closest('li')).not.toHaveTextContent('kabul');
    expect(screen.getByRole('checkbox', { name: /Kullanım koşulları/ })).toHaveAttribute(
      'aria-required',
      'true',
    );
  });

  it('kapı açıkken veri yazmanın kapalı olduğunu söyler, kapalıyken söylemez', () => {
    const { rerender } = render(<LegalReacceptanceBanner pending={[TERMS]} enforced />);
    expect(screen.getByText(/mağaza bağlama ve veri girişi kapalıdır/)).toBeInTheDocument();
    rerender(<LegalReacceptanceBanner pending={[TERMS]} enforced={false} />);
    expect(screen.queryByText(/veri girişi kapalıdır/)).not.toBeInTheDocument();
  });

  it('tüm kutular işaretlenmeden onay düğmesi kapalıdır; sürüm numarasıyla gönderir ve yeniler', async () => {
    const fetchMock = mockFetch(200, { pending: [], enforced: false });
    const user = userEvent.setup();
    render(<LegalReacceptanceBanner pending={[TERMS, NOTICE]} enforced={false} />);
    const button = screen.getByRole('button', { name: 'Onayla' });
    expect(button).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /Kullanım koşulları/ }));
    expect(button).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /Aydınlatma metni/ }));
    expect(button).toBeEnabled();
    await user.click(button);

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/legal/accept');
    expect(init.method).toBe('POST');
    expect((init.headers as Headers).get('X-CSRF-Token')).toBe('tok-test');
    expect(JSON.parse(String(init.body))).toEqual({
      documents: [
        { doc_type: 'terms', version: '2026-12-a' },
        { doc_type: 'privacy_notice', version: '2026-12-a' },
      ],
    });
    expect(toastSuccess).toHaveBeenCalled();
  });

  it('sürüm bu arada değiştiyse (409) kutuları sıfırlar, sayfayı yeniler ve kabul saymaz', async () => {
    mockFetch(409, { type: 'urn:netkar:problem:legal-version-stale', title: 'x', status: 409 });
    const user = userEvent.setup();
    render(<LegalReacceptanceBanner pending={[TERMS]} enforced={false} />);
    await user.click(screen.getByRole('checkbox', { name: /Kullanım koşulları/ }));
    await user.click(screen.getByRole('button', { name: 'Onayla' }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(toastError).toHaveBeenCalledWith(expect.stringContaining('güncellendi'));
    expect(screen.getByRole('checkbox', { name: /Kullanım koşulları/ })).not.toBeChecked();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it('başka bir hatada bildirir ve düğmeyi yeniden açar', async () => {
    mockFetch(500, { type: 'urn:netkar:problem:internal', title: 'x', status: 500 });
    const user = userEvent.setup();
    render(<LegalReacceptanceBanner pending={[TERMS]} enforced={false} />);
    await user.click(screen.getByRole('checkbox', { name: /Kullanım koşulları/ }));
    await user.click(screen.getByRole('button', { name: 'Onayla' }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Onayla' })).toBeEnabled();
  });
});
