import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { UnsubscribeView } from '@/components/auth/unsubscribe-view';
import { mockRequests, problemReply } from '@/test/request-mock';

const navigation = vi.hoisted(() => {
  const replace = vi.fn();
  return { replace, router: { replace } };
});

vi.mock('next/navigation', () => ({
  useRouter: () => navigation.router,
  usePathname: () => '/bildirim-kapat',
}));

const TOKEN = 'eyJ2IjoxfQ.' + 'S'.repeat(43);

beforeEach(() => {
  navigation.replace.mockClear();
  window.history.replaceState(null, '', `/bildirim-kapat#token=${TOKEN}`);
  document.cookie = '__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Bildirim kapatma sayfası', () => {
  it('sayfa açılınca OTOMATİK istek atmaz; açık bir düğme gösterir', async () => {
    const { fn } = mockRequests(() => ({
      body: { rules: ['ZARARINA_SATIS'], channel: 'email', mode: 'off' },
    }));
    render(<UnsubscribeView />);
    expect(screen.getByRole('heading', { level: 1, name: 'Bildirimi kapatın' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Bildirimi kapat' })).toBeEnabled();
    // Efektlerin ve zamanlayıcıların çalışması için bir tur beklenir
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fn).not.toHaveBeenCalled();
  });

  it('düğmeye basınca POST /notifications/unsubscribe?token= gider; CSRF başlığı ve gövde yok', async () => {
    const { requests } = mockRequests((r) =>
      r.method === 'POST' && r.url.pathname === '/api/v1/notifications/unsubscribe'
        ? { body: { rules: ['ZARARINA_SATIS'], channel: 'email', mode: 'off' } }
        : undefined,
    );
    render(<UnsubscribeView />);
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    expect(await screen.findByRole('heading', { name: 'Bildirim kapatıldı' })).toBeVisible();
    expect(requests).toHaveLength(1);
    const call = requests[0];
    expect(call?.method).toBe('POST');
    expect(call?.url.searchParams.get('token')).toBe(TOKEN);
    expect(call?.headers.has('X-CSRF-Token')).toBe(false);
    expect(call?.credentials).toBe('omit');
    expect(call?.body).toBeUndefined();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Zararına satış için e-posta bildirimi artık gönderilmeyecek.',
    );
  });

  it('token sayfada yazılmaz; okunur okunmaz router.replace ile adresten silinir', () => {
    const { container } = render(<UnsubscribeView />);
    expect(container.innerHTML).not.toContain(TOKEN);
    expect(navigation.replace).toHaveBeenCalledWith('/bildirim-kapat', { scroll: false });
  });

  it('e-postadaki biçim: token URL parçasından okunur (sunucuya gitmez) ve istekte kullanılır', async () => {
    const { requests } = mockRequests(() => ({
      body: { rules: ['ZARARINA_SATIS'], channel: 'email', mode: 'off' },
    }));
    render(<UnsubscribeView />);
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    await screen.findByRole('heading', { name: 'Bildirim kapatıldı' });
    expect(requests[0]?.url.searchParams.get('token')).toBe(TOKEN);
  });

  it('geriye uyum: eski ?token= bağlantısı da okunur ve adresten silinir', async () => {
    window.history.replaceState(null, '', `/bildirim-kapat?token=${TOKEN}`);
    const { requests } = mockRequests(() => ({
      body: { rules: ['ZARARINA_SATIS'], channel: 'email', mode: 'off' },
    }));
    render(<UnsubscribeView />);
    expect(navigation.replace).toHaveBeenCalledWith('/bildirim-kapat', { scroll: false });
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    await screen.findByRole('heading', { name: 'Bildirim kapatıldı' });
    expect(requests[0]?.url.searchParams.get('token')).toBe(TOKEN);
  });

  it('sonuç ekranı gelince odak sayfa gövdesine (main) taşınır', async () => {
    mockRequests(() => ({ body: { rules: ['ZARARINA_SATIS'], channel: 'email', mode: 'off' } }));
    render(
      <main id="main" tabIndex={-1}>
        <UnsubscribeView />
      </main>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    await screen.findByRole('heading', { name: 'Bildirim kapatıldı' });
    await waitFor(() => expect(document.getElementById('main')).toHaveFocus());
  });

  it('token günlüğe yazılmaz (konsol)', async () => {
    const spies = (['log', 'info', 'warn', 'error'] as const).map((name) =>
      vi.spyOn(console, name).mockImplementation(() => undefined),
    );
    mockRequests(() => problemReply(400, 'invalid-unsubscribe-token'));
    render(<UnsubscribeView />);
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    await screen.findByRole('heading', { name: 'Bağlantı geçersiz' });
    for (const spy of spies) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(TOKEN);
      spy.mockRestore();
    }
  });

  it('400: geçersiz ya da süresi dolmuş bağlantı iletisi', async () => {
    mockRequests(() => problemReply(400, 'invalid-unsubscribe-token'));
    render(<UnsubscribeView />);
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Bağlantı geçersiz ya da süresi dolmuş.',
    );
    expect(screen.queryByRole('button', { name: 'Bildirimi kapat' })).not.toBeInTheDocument();
  });

  it('429: çok fazla deneme ve Retry-After süresi', async () => {
    mockRequests(() => problemReply(429, 'rate-limited', { 'Retry-After': '1800' }));
    render(<UnsubscribeView />);
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    expect(await screen.findByRole('heading', { name: 'Çok fazla deneme' })).toBeVisible();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Çok fazla deneme yaptınız. Yaklaşık 30 dakika sonra tekrar deneyin.',
    );
  });

  it('sunucu hatası: yeniden denenebilir', async () => {
    let calls = 0;
    mockRequests(() => {
      calls += 1;
      return calls === 1
        ? problemReply(500, 'internal-error')
        : {
            body: { rules: ['ZARARINA_SATIS', 'IADE_ORANI_ARTISI'], channel: 'email', mode: 'off' },
          };
    });
    render(<UnsubscribeView />);
    await userEvent.click(screen.getByRole('button', { name: 'Bildirimi kapat' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByRole('heading', { name: 'Bildirim kapatıldı' })).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Zararına satış, İade oranı artışı');
  });

  it('token yoksa ya da biçimi bozuksa istek atmadan geçersiz bağlantı gösterir', () => {
    const { fn } = mockRequests(() => ({ body: {} }));
    window.history.replaceState(null, '', '/bildirim-kapat#token=%3Cscript%3E');
    render(<UnsubscribeView />);
    expect(screen.getByRole('heading', { name: 'Bağlantı geçersiz' })).toBeVisible();
    expect(fn).not.toHaveBeenCalled();
  });
});
