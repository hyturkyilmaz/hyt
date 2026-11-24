import { describe, expect, it } from 'vitest';

import { buildCsp, createNonce } from '@/lib/csp';
import { serializeJsonLd } from '@/lib/json-ld';

describe('buildCsp', () => {
  it('üretimde nonce, strict-dynamic ve frame-ancestors none içerir; eval içermez', () => {
    const csp = buildCsp({ nonce: 'abc123', isDev: false });
    expect(csp).toContain("script-src 'self' 'nonce-abc123' 'strict-dynamic'");
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain('upgrade-insecure-requests');
  });

  it('geliştirmede eval izni verir', () => {
    const csp = buildCsp({ nonce: 'abc123', isDev: true });
    expect(csp).toContain("'unsafe-eval'");
    expect(csp).not.toContain('upgrade-insecure-requests');
  });

  it('script-src içinde unsafe-inline yoktur', () => {
    const script = buildCsp({ nonce: 'n', isDev: false })
      .split('; ')
      .find((d) => d.startsWith('script-src'));
    expect(script).not.toContain('unsafe-inline');
  });
});

describe('createNonce', () => {
  it('her çağrıda farklı, base64 biçiminde değer üretir', () => {
    const a = createNonce();
    const b = createNonce();
    expect(a).not.toBe(b);
    expect(a).toMatch(/^[A-Za-z0-9+/]+=*$/);
    expect(a.length).toBeGreaterThanOrEqual(22);
  });
});

describe('serializeJsonLd', () => {
  it('</script> kapatmasını etkisizleştirir', () => {
    const text = serializeJsonLd({ name: '</script><script>alert(1)</script>' });
    expect(text).not.toContain('<');
    expect(text).not.toContain('>');
    expect(JSON.parse(text)).toEqual({ name: '</script><script>alert(1)</script>' });
  });
});
