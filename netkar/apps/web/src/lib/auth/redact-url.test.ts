import { afterEach, describe, expect, it } from 'vitest';

import { nextCarriesToken, stripTokenCarryingNext } from '@/lib/auth/redact-url';

afterEach(() => window.history.replaceState(null, '', '/'));

describe('nextCarriesToken', () => {
  it('yalnız sorgu dizesinde token parametresi taşıyan hedefi yakalar', () => {
    expect(nextCarriesToken('/e-posta-dogrula?token=abc')).toBe(true);
    expect(nextCarriesToken('/x?a=1&token=abc')).toBe(true);
    expect(nextCarriesToken('/panel/urunler')).toBe(false);
    expect(nextCarriesToken('/panel?durum=1')).toBe(false);
    expect(nextCarriesToken(null)).toBe(false);
  });
});

describe('stripTokenCarryingNext', () => {
  it('token taşıyan sonra parametresini adres çubuğundan siler, diğerlerini korur', () => {
    const next = encodeURIComponent('/e-posta-dogrula?token=GIZLI_TOKEN_DEGERI_123456');
    window.history.pushState({ k: 1 }, '', `/giris?sonra=${next}&kayit=1`);
    const before = window.history.length;
    stripTokenCarryingNext();
    expect(window.location.search).toBe('?kayit=1');
    expect(window.location.href).not.toContain('GIZLI_TOKEN');
    expect(window.history.length).toBe(before); // yeni kayıt eklenmez, mevcut kayıt değiştirilir
    expect(window.history.state).toEqual({ k: 1 });
  });

  it('token yoksa adrese dokunmaz', () => {
    window.history.pushState(null, '', '/giris?sonra=%2Fpanel%2Furunler');
    stripTokenCarryingNext();
    expect(window.location.search).toBe('?sonra=%2Fpanel%2Furunler');
  });
});
