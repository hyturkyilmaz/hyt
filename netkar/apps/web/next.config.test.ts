import { describe, expect, it } from 'vitest';

import nextConfig, { PROXY_TIMEOUT_MS } from './next.config';

describe('next.config', () => {
  it('rewrite vekil zaman aşımı 55 sn (API hesap sınırı 45 sn ile Caddy 60 sn arasında)', () => {
    expect(PROXY_TIMEOUT_MS).toBe(55_000);
    expect(nextConfig.experimental?.proxyTimeout).toBe(55_000);
    // Zincir: API hesap sınırı < vekil < Caddy
    expect(nextConfig.experimental?.proxyTimeout).toBeGreaterThan(45_000);
    expect(nextConfig.experimental?.proxyTimeout).toBeLessThan(60_000);
  });

  it('Docker imajı için standalone çıktısı açık', () => {
    expect(nextConfig.output).toBe('standalone');
  });

  it('/api/v1 rewrite kuralı korunur', async () => {
    const rules = await nextConfig.rewrites?.();
    expect(rules).toEqual([
      { source: '/api/v1/:path*', destination: expect.stringMatching(/\/v1\/:path\*$/) },
    ]);
  });

  it('e-posta doğrulama yolu no-referrer ve no-store başlıkları taşır', async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const rule = rules.find((r) => r.source === '/e-posta-dogrula');
    expect(rule?.headers).toEqual(
      expect.arrayContaining([
        { key: 'Referrer-Policy', value: 'no-referrer' },
        { key: 'Cache-Control', value: 'no-store' },
        { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
      ]),
    );
  });

  it('bildirim kapatma yolu no-referrer ve no-store başlıkları taşır', async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const rule = rules.find((r) => r.source === '/bildirim-kapat');
    expect(rule?.headers).toEqual(
      expect.arrayContaining([
        { key: 'Referrer-Policy', value: 'no-referrer' },
        { key: 'Cache-Control', value: 'no-store' },
        { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
      ]),
    );
  });
});
