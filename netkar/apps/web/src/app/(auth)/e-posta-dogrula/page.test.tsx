import { beforeEach, describe, expect, it, vi } from 'vitest';

const redirect = vi.fn((target: string) => {
  throw new Error(`REDIRECT:${target}`);
});
const getSession = vi.fn();
vi.mock('next/navigation', () => ({ redirect: (t: string) => redirect(t) }));
vi.mock('@/lib/api/server', () => ({ getSession: () => getSession() }));

import EmailVerifyPage from './page';

const TOKEN = 'B'.repeat(43);

beforeEach(() => {
  redirect.mockClear();
  getSession.mockReset();
});

describe('/e-posta-dogrula sayfası', () => {
  it('oturum yoksa girişe yönlendirir ve token ile bu sayfaya dönmeyi taşır', async () => {
    getSession.mockResolvedValue({ status: 'unauthenticated' });
    await expect(
      EmailVerifyPage({ searchParams: Promise.resolve({ token: TOKEN }) }),
    ).rejects.toThrow('REDIRECT:');
    const target = String(redirect.mock.calls[0]?.[0]);
    expect(target.startsWith('/giris?sonra=')).toBe(true);
    expect(decodeURIComponent(target.split('sonra=')[1] ?? '')).toBe(
      `/e-posta-dogrula?token=${TOKEN}`,
    );
  });

  it('oturum açıksa yönlendirmez ve bileşeni token ile kurar', async () => {
    getSession.mockResolvedValue({ status: 'authenticated', me: {} });
    const element = await EmailVerifyPage({ searchParams: Promise.resolve({ token: TOKEN }) });
    expect(redirect).not.toHaveBeenCalled();
    expect((element as { props: { token: string | null } }).props.token).toBe(TOKEN);
  });

  it('biçimi bozuk token için oturum sorgulamaz ve token geçirmez', async () => {
    const element = await EmailVerifyPage({
      searchParams: Promise.resolve({ token: '<script>' }),
    });
    expect(getSession).not.toHaveBeenCalled();
    expect((element as { props: { token: string | null } }).props.token).toBeNull();
  });

  it('API ulaşılamıyorsa yönlendirmez (oturum düşürülmez)', async () => {
    getSession.mockResolvedValue({ status: 'unavailable' });
    await EmailVerifyPage({ searchParams: Promise.resolve({ token: TOKEN }) });
    expect(redirect).not.toHaveBeenCalled();
  });
});
