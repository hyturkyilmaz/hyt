import { describe, expect, it } from 'vitest';

import {
  CLIENT_IP_HEADERS,
  normalizeIp,
  parseClientIpConfig,
  resolveClientIp,
  sanitizeClientIpHeaders,
  type ClientIpConfig,
} from '@/lib/client-ip';

const none: ClientIpConfig = { source: 'none', hops: 1 };
const cloudflare: ClientIpConfig = { source: 'cf-connecting-ip', hops: 1 };
const xff = (hops: number): ClientIpConfig => ({ source: 'x-forwarded-for', hops });
const headers = (init: Record<string, string>) => new Headers(init);

describe('parseClientIpConfig', () => {
  it('varsayılan: none ve 1 hop', () => {
    expect(parseClientIpConfig({})).toEqual({ source: 'none', hops: 1 });
    expect(parseClientIpConfig({ CLIENT_IP_SOURCE: '', CLIENT_IP_TRUSTED_HOPS: '' })).toEqual(none);
  });

  it('kaynağı ve hop sayısını okur (büyük küçük harf duyarsız)', () => {
    expect(parseClientIpConfig({ CLIENT_IP_SOURCE: 'CF-Connecting-IP' }).source).toBe(
      'cf-connecting-ip',
    );
    expect(
      parseClientIpConfig({ CLIENT_IP_SOURCE: 'x-forwarded-for', CLIENT_IP_TRUSTED_HOPS: '2' }),
    ).toEqual(xff(2));
  });

  it('geçersiz kaynağı ve hop değerini reddeder', () => {
    expect(() => parseClientIpConfig({ CLIENT_IP_SOURCE: 'x-real-ip' })).toThrow(
      /CLIENT_IP_SOURCE/,
    );
    for (const bad of ['0', '11', '-1', '1.5', 'iki']) {
      expect(() => parseClientIpConfig({ CLIENT_IP_TRUSTED_HOPS: bad })).toThrow(
        /CLIENT_IP_TRUSTED_HOPS/,
      );
    }
  });
});

describe('normalizeIp', () => {
  it('geçerli IPv4 ve IPv6 adreslerini kabul eder', () => {
    expect(normalizeIp('203.0.113.9')).toBe('203.0.113.9');
    expect(normalizeIp(' 203.0.113.9 ')).toBe('203.0.113.9');
    expect(normalizeIp('2001:DB8::1')).toBe('2001:db8::1');
    expect(normalizeIp('::ffff:203.0.113.9')).not.toBeNull();
  });

  it('port, ad, kötü biçim ve ek içeriği reddeder', () => {
    for (const bad of [
      '',
      null,
      undefined,
      '256.1.1.1',
      '1.2.3',
      '01.2.3.4',
      '203.0.113.9:80',
      '[2001:db8::1]',
      'evil.example',
      '1.2.3.4, 5.6.7.8',
      '1.2.3.4\r\nX-Evil: 1',
      ':::',
      '2001:db8::zz',
      'a'.repeat(60),
    ]) {
      expect(normalizeIp(bad as string | null | undefined)).toBeNull();
    }
  });
});

describe('resolveClientIp', () => {
  it('none: hiçbir başlığa güvenmez', () => {
    const h = headers({ 'x-forwarded-for': '6.6.6.6', 'cf-connecting-ip': '6.6.6.6' });
    expect(resolveClientIp(h, none)).toBeNull();
  });

  it('cf-connecting-ip: yalnız bu başlığı okur', () => {
    const h = headers({ 'cf-connecting-ip': '203.0.113.9', 'x-forwarded-for': '6.6.6.6' });
    expect(resolveClientIp(h, cloudflare)).toBe('203.0.113.9');
    expect(resolveClientIp(headers({ 'x-forwarded-for': '6.6.6.6' }), cloudflare)).toBeNull();
    expect(resolveClientIp(headers({ 'cf-connecting-ip': 'bozuk' }), cloudflare)).toBeNull();
  });

  it('x-forwarded-for: sağdan hop sayısı; sol (sahte) değerler hiç okunmaz', () => {
    const h = headers({ 'x-forwarded-for': '6.6.6.6, 203.0.113.9, 104.16.0.1' });
    expect(resolveClientIp(h, xff(1))).toBe('104.16.0.1');
    expect(resolveClientIp(h, xff(2))).toBe('203.0.113.9');
    expect(resolveClientIp(h, xff(3))).toBe('6.6.6.6'); // hop 3 yapılandırmışsa operatör o adrese güveniyor
    expect(resolveClientIp(h, xff(4))).toBeNull(); // zincir yapılandırmadan kısa: belirlenemez
    expect(resolveClientIp(headers({ 'x-forwarded-for': 'a, b' }), xff(1))).toBeNull();
    expect(resolveClientIp(headers({}), xff(1))).toBeNull();
  });
});

describe('sanitizeClientIpHeaders', () => {
  const spoofed = headers({
    'x-forwarded-for': '6.6.6.6',
    'x-real-ip': '6.6.6.6',
    'cf-connecting-ip': '6.6.6.6',
    'true-client-ip': '6.6.6.6',
    'x-client-ip': '6.6.6.6',
    'x-cluster-client-ip': '6.6.6.6',
    'fastly-client-ip': '6.6.6.6',
    forwarded: 'for=6.6.6.6',
    cookie: '__Host-nk_session=abc',
    'x-csrf-token': 'tok',
  });

  it('none: tüm IP başlıkları silinir, başka başlıklar korunur', () => {
    const clean = sanitizeClientIpHeaders(spoofed, none);
    for (const name of CLIENT_IP_HEADERS) expect(clean.has(name)).toBe(false);
    expect(clean.get('cookie')).toBe('__Host-nk_session=abc');
    expect(clean.get('x-csrf-token')).toBe('tok');
  });

  it('cf-connecting-ip: sahte başlıklar silinir, yalnız doğrulanan IP tek XFF olarak yazılır', () => {
    const h = new Headers(spoofed);
    h.set('cf-connecting-ip', '203.0.113.9');
    const clean = sanitizeClientIpHeaders(h, cloudflare);
    expect(clean.get('x-forwarded-for')).toBe('203.0.113.9');
    for (const name of CLIENT_IP_HEADERS.filter((n) => n !== 'x-forwarded-for')) {
      expect(clean.has(name)).toBe(false);
    }
  });

  it('girdi başlıklarını değiştirmez', () => {
    const before = [...spoofed.entries()].join('|');
    sanitizeClientIpHeaders(spoofed, none);
    expect([...spoofed.entries()].join('|')).toBe(before);
  });
});
