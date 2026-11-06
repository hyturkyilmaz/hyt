import { describe, expect, it } from 'vitest';

import { parseEnv } from '@/config/env';

describe('parseEnv', () => {
  it('varsayılanları uygular', () => {
    const env = parseEnv({});
    expect(env.API_BASE_URL).toBe('http://localhost:8000');
    expect(env.NEXT_PUBLIC_SITE_URL).toBe('http://localhost:3000');
    expect(env.NODE_ENV).toBe('development');
    expect(env.NEXT_PUBLIC_PRODUCT_NAME).toBeUndefined();
  });

  it('sondaki eğik çizgiyi atar ve boş değerleri yok sayar', () => {
    const env = parseEnv({ API_BASE_URL: 'https://api.ornek.com/', NEXT_PUBLIC_PRODUCT_NAME: '' });
    expect(env.API_BASE_URL).toBe('https://api.ornek.com');
    expect(env.NEXT_PUBLIC_PRODUCT_NAME).toBeUndefined();
  });

  it('geçersiz URL için anlaşılır hata verir', () => {
    expect(() => parseEnv({ API_BASE_URL: 'api yok' })).toThrow(
      /Ortam değişkenleri geçersiz.*API_BASE_URL/,
    );
  });

  it('çok uzun ürün adını reddeder', () => {
    expect(() => parseEnv({ NEXT_PUBLIC_PRODUCT_NAME: 'a'.repeat(41) })).toThrow();
  });
});
