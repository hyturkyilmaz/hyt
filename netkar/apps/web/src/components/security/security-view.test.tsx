import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SecurityView } from '@/components/security/security-view';

const refresh = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
vi.mock('sonner', () => ({
  toast: { success: (m: string) => toastSuccess(m), error: (m: string) => toastError(m) },
}));

const SECRET = 'JBSWY3DPEHPK3PXP';
const URI = `otpauth://totp/NetKar:ornek%40example.com?secret=${SECRET}&issuer=NetKar`;
const CODES = Array.from(
  { length: 10 },
  (_, i) => `ABCD-EFGH-${String.fromCharCode(74 + i)}K${i + 2}M`,
);

interface Reply {
  status: number;
  body?: unknown;
  headers?: Record<string, string>;
}
type Routes = Record<string, Reply | ((body: Record<string, unknown>) => Reply)>;

/** Yol bazlı fetch taklidi; her isteğin yolunu ve gövdesini kaydeder. */
function mockApi(routes: Routes) {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    calls.push({ path, body });
    const route = routes[path];
    const reply: Reply = route
      ? typeof route === 'function'
        ? route(body)
        : route
      : { status: 404, body: { type: 'urn:netkar:problem:not-found' } };
    return new Response(reply.status === 204 ? null : JSON.stringify(reply.body ?? {}), {
      status: reply.status,
      headers: {
        'Content-Type': reply.status >= 400 ? 'application/problem+json' : 'application/json',
        ...reply.headers,
      },
    });
  });
  vi.stubGlobal('fetch', fn);
  return { fn, calls };
}

function problem(status: number, slug: string, headers?: Record<string, string>): Reply {
  return { status, body: { type: `urn:netkar:problem:${slug}`, status }, headers };
}

beforeEach(() => {
  refresh.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  document.cookie = '__Host-nk_csrf=tok-test; path=/; Secure';
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.cookie = '__Host-nk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; Secure';
});

describe('Güvenlik ayarları: kurulum', () => {
  it('kapalıyken durum "Kapalı" ve kurulum düğmesi görünür', () => {
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    expect(screen.getByRole('status')).toHaveTextContent('Kapalı');
    expect(screen.getByRole('button', { name: 'Kurulumu başlat' })).toBeInTheDocument();
  });

  it('parola olmadan kurulum istenmez; Türkçe hata gösterir', async () => {
    const { fn } = mockApi({});
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    expect(await screen.findByText('Güncel parolanızı yazın.')).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it('yanlış parolada "Parola hatalı" der ve QR adımına geçmez', async () => {
    mockApi({ '/api/v1/auth/totp/setup': problem(403, 'reauth-failed') });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'yanlis-parola-1234');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Parola hatalı');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('kilitliyken (429) bekleme süresini söyler', async () => {
    mockApi({ '/api/v1/auth/totp/setup': problem(429, 'totp-locked', { 'Retry-After': '600' }) });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('10 dakika');
  });

  it('doğrulanmamış e-postada açıklayıcı hata verir', async () => {
    mockApi({ '/api/v1/auth/totp/setup': problem(403, 'email-not-verified') });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('e-posta adresinizi doğrulamanız');
  });

  it('tam akış: parola, QR + elle anahtar, kod, kurtarma kodları, "kaydettim" onayı, bitti', async () => {
    const { calls } = mockApi({
      '/api/v1/auth/totp/setup': { status: 200, body: { secret: SECRET, otpauth_uri: URI } },
      '/api/v1/auth/totp/enable': { status: 200, body: { recovery_codes: CODES } },
    });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);

    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));

    // QR (istemcide üretilmiş SVG) ve elle girilecek anahtar
    const qr = await screen.findByRole('img', { name: /QR kodu/ });
    expect(qr.tagName.toLowerCase()).toBe('svg');
    expect(qr.querySelector('path')?.getAttribute('d')?.length ?? 0).toBeGreaterThan(100);
    expect(screen.getByText(SECRET)).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull(); // dış görsel yok

    // Yanlış biçimli kod ağ isteği yapmaz
    await user.type(screen.getByLabelText('Uygulamadaki 6 haneli kod'), '12');
    await user.click(screen.getByRole('button', { name: 'Doğrula ve etkinleştir' }));
    expect(await screen.findByText(/6 haneli olmalı/)).toBeInTheDocument();
    expect(calls.filter((c) => c.path.endsWith('/enable'))).toHaveLength(0);

    await user.clear(screen.getByLabelText('Uygulamadaki 6 haneli kod'));
    await user.type(screen.getByLabelText('Uygulamadaki 6 haneli kod'), '123456');
    await user.click(screen.getByRole('button', { name: 'Doğrula ve etkinleştir' }));

    // Kurtarma kodları bir kez gösterilir
    const list = await screen.findByRole('list', { name: 'Kurtarma kodları' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(10);
    expect(screen.getByText(/bir daha\s+gösterilmez/)).toBeInTheDocument();

    // Enable isteği parolayı ve kodu taşır
    const enable = calls.find((c) => c.path.endsWith('/auth/totp/enable'));
    expect(enable?.body).toEqual({ code: '123456', password: 'dogru-at-pil-kalem-42' });

    // "Kaydettim" onayı olmadan "Bitti" kapalı
    const done = screen.getByRole('button', { name: 'Bitti' });
    expect(done).toBeDisabled();
    await user.click(screen.getByLabelText('Kodları güvenli bir yere kaydettim'));
    expect(done).toBeEnabled();
    await user.click(done);

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Açık'));
    expect(screen.getByText('10', { selector: 'span.num' })).toBeInTheDocument();
    // Kodlar ekrandan kalktı ve toast/log'a düşmedi
    expect(screen.queryByRole('list', { name: 'Kurtarma kodları' })).not.toBeInTheDocument();
    expect(JSON.stringify(toastSuccess.mock.calls)).not.toContain('ABCD');
    expect(refresh).toHaveBeenCalled();
  });

  it('yanlış kodda hata gösterir ve kurtarma kodları göstermez', async () => {
    mockApi({
      '/api/v1/auth/totp/setup': { status: 200, body: { secret: SECRET, otpauth_uri: URI } },
      '/api/v1/auth/totp/enable': problem(400, 'invalid-code'),
    });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    await user.type(await screen.findByLabelText('Uygulamadaki 6 haneli kod'), '000000');
    await user.click(screen.getByRole('button', { name: 'Doğrula ve etkinleştir' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Kod hatalı');
    expect(screen.queryByRole('list', { name: 'Kurtarma kodları' })).not.toBeInTheDocument();
  });

  it('gönderim sürerken düğme kilitlenir ve yükleniyor metni görünür', async () => {
    let release: (value: Response) => void = () => undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      ),
    );
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    const busy = await screen.findByRole('button', { name: 'Doğrulanıyor' });
    expect(busy).toBeDisabled();
    release(new Response(JSON.stringify({ secret: SECRET, otpauth_uri: URI }), { status: 200 }));
  });

  it('kurtarma kodları kopyalanır ve dosya olarak indirilir; indirme metni yalnız kodları içerir', async () => {
    mockApi({
      '/api/v1/auth/totp/setup': { status: 200, body: { secret: SECRET, otpauth_uri: URI } },
      '/api/v1/auth/totp/enable': { status: 200, body: { recovery_codes: CODES } },
    });
    const blobs: Blob[] = [];
    URL.createObjectURL = (blob: Blob | MediaSource) => {
      blobs.push(blob as Blob);
      return 'blob:test';
    };
    URL.revokeObjectURL = vi.fn();
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    await user.type(await screen.findByLabelText('Uygulamadaki 6 haneli kod'), '123456');
    await user.click(screen.getByRole('button', { name: 'Doğrula ve etkinleştir' }));
    await screen.findByRole('list', { name: 'Kurtarma kodları' });

    await user.click(screen.getByRole('button', { name: 'Kopyala' }));
    expect(await navigator.clipboard.readText()).toBe(CODES.join('\n'));

    await user.click(screen.getByRole('button', { name: 'Dosya olarak indir' }));
    expect(click).toHaveBeenCalledTimes(1);
    const text = await blobs[0]!.text();
    expect(text).toContain(CODES[0]);
    expect(text).toContain('BİR kez');
    expect(text).not.toContain('@');
  });
});

describe('Güvenlik ayarları: açıkken', () => {
  it('kalan kod sayısını gösterir; azalınca uyarır', () => {
    const { unmount } = render(
      <SecurityView initialTotpEnabled initialRecoveryCodesRemaining={8} />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Açık');
    expect(screen.getByText('8', { selector: 'span.num' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    unmount();
    render(<SecurityView initialTotpEnabled initialRecoveryCodesRemaining={2} />);
    expect(screen.getByRole('alert')).toHaveTextContent('kodlarınız azaldı');
  });

  it('kapatma: parola + kod gönderir, başarıda durum "Kapalı" olur', async () => {
    const { calls } = mockApi({ '/api/v1/auth/totp/disable': { status: 204 } });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled initialRecoveryCodesRemaining={5} />);
    await user.click(screen.getByRole('button', { name: 'İki adımlı doğrulamayı kapat' }));
    expect(screen.getByText(/dışındaki tüm oturumlar kapatılır/)).toBeInTheDocument();
    // Boş gönderimde istek yok
    await user.click(screen.getByRole('button', { name: 'Doğrulamayı kapat' }));
    expect(await screen.findByText('Güncel parolanızı yazın.')).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.type(screen.getByLabelText('Doğrulama ya da kurtarma kodu'), '123456');
    await user.click(screen.getByRole('button', { name: 'Doğrulamayı kapat' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Kapalı'));
    expect(calls.at(-1)?.body).toEqual({ password: 'dogru-at-pil-kalem-42', code: '123456' });
    expect(refresh).toHaveBeenCalled();
  });

  it('kapatma: kurtarma kodu da ikinci faktör olarak kabul edilir (biçim)', async () => {
    const { calls } = mockApi({ '/api/v1/auth/totp/disable': { status: 204 } });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled initialRecoveryCodesRemaining={5} />);
    await user.click(screen.getByRole('button', { name: 'İki adımlı doğrulamayı kapat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.type(screen.getByLabelText('Doğrulama ya da kurtarma kodu'), 'abcd-efgh-jk2m');
    await user.click(screen.getByRole('button', { name: 'Doğrulamayı kapat' }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.body.code).toBe('abcd-efgh-jk2m');
  });

  it('kapatma hatası: kod hatalıysa açık kalır ve Türkçe hata verir', async () => {
    mockApi({ '/api/v1/auth/totp/disable': problem(403, 'invalid-code') });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled initialRecoveryCodesRemaining={5} />);
    await user.click(screen.getByRole('button', { name: 'İki adımlı doğrulamayı kapat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.type(screen.getByLabelText('Doğrulama ya da kurtarma kodu'), '000000');
    await user.click(screen.getByRole('button', { name: 'Doğrulamayı kapat' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Kod hatalı');
    expect(screen.getByRole('status')).toHaveTextContent('Açık');
  });

  it('yenileme: yeni kodlar bir kez gösterilir, onaydan sonra kapanır; sayı 10 olur', async () => {
    mockApi({
      '/api/v1/auth/totp/recovery-codes': { status: 200, body: { recovery_codes: CODES } },
    });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled initialRecoveryCodesRemaining={1} />);
    await user.click(screen.getByRole('button', { name: 'Kurtarma kodlarını yenile' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.type(screen.getByLabelText('Doğrulama ya da kurtarma kodu'), '123456');
    await user.click(screen.getByRole('button', { name: 'Yeni kodlar üret' }));
    const list = await screen.findByRole('list', { name: 'Kurtarma kodları' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(10);
    await user.click(screen.getByLabelText('Kodları güvenli bir yere kaydettim'));
    await user.click(screen.getByRole('button', { name: 'Bitti' }));
    expect(screen.getByText('10', { selector: 'span.num' })).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Kurtarma kodları' })).not.toBeInTheDocument();
  });

  it('hiçbir istek dış bir adrese gitmez (yalnız /api/v1)', async () => {
    const { fn } = mockApi({
      '/api/v1/auth/totp/setup': { status: 200, body: { secret: SECRET, otpauth_uri: URI } },
    });
    const user = userEvent.setup();
    render(<SecurityView initialTotpEnabled={false} initialRecoveryCodesRemaining={0} />);
    await user.click(screen.getByRole('button', { name: 'Kurulumu başlat' }));
    await user.type(screen.getByLabelText('Güncel parola'), 'dogru-at-pil-kalem-42');
    await user.click(screen.getByRole('button', { name: 'Devam et' }));
    await screen.findByRole('img', { name: /QR kodu/ });
    for (const call of fn.mock.calls) expect(String(call[0])).toMatch(/^\/api\/v1\//);
  });
});
