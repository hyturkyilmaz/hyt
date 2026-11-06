import { describe, expect, it } from 'vitest';

import {
  buildLoginUrl,
  buildTwoFactorUrl,
  isProtectedPath,
  safeNextPath,
} from '@/lib/auth/redirect';

describe('safeNextPath', () => {
  it('uygulama içi göreli yolları kabul eder (sorgu dizesiyle)', () => {
    expect(safeNextPath('/panel')).toBe('/panel');
    expect(safeNextPath('/panel/urunler?sayfa=2')).toBe('/panel/urunler?sayfa=2');
    expect(safeNextPath(['/panel/ayarlar', '/baska'])).toBe('/panel/ayarlar');
  });

  it('parça (hash) atılır', () => {
    expect(safeNextPath('/panel#x')).toBe('/panel');
  });

  it.each([
    ['https://evil.example/panel'],
    ['http://evil.example'],
    ['//evil.example'],
    ['///evil.example'],
    ['/\\evil.example'],
    ['\\\\evil.example'],
    ['/\t/evil.example'],
    ['/\n/evil.example'],
    ['/%2f/evil.example'],
    ['/%5cevil.example'],
    ['javascript:alert(1)'],
    ['data:text/html,x'],
    ['panel'],
    ['/%E0%A4%A'],
    ['/' + 'a'.repeat(600)],
    [''],
  ])('açık yönlendirme denemesini reddeder: %s', (value) => {
    expect(safeNextPath(value)).toBe('/panel');
  });

  it('boş, tanımsız ve dizi dışı girdide varsayılana döner', () => {
    expect(safeNextPath(undefined)).toBe('/panel');
    expect(safeNextPath(null)).toBe('/panel');
    expect(safeNextPath([])).toBe('/panel');
    expect(safeNextPath(undefined, '/x')).toBe('/x');
  });

  it('giriş sayfalarına yönlendirme döngüsü kurmaz', () => {
    for (const path of ['/giris', '/giris/', '/kayit', '/iki-adim', '/sifre-sifirla?token=x']) {
      expect(safeNextPath(path)).toBe('/panel');
    }
  });
});

describe('buildLoginUrl / buildTwoFactorUrl', () => {
  it('hedefi kodlayarak ekler', () => {
    expect(buildLoginUrl('/panel/urunler?a=1&b=2')).toBe(
      '/giris?sonra=%2Fpanel%2Furunler%3Fa%3D1%26b%3D2',
    );
  });

  it('geçersiz veya boş hedefte yalnız /giris döner', () => {
    expect(buildLoginUrl('//evil.example')).toBe('/giris');
    expect(buildLoginUrl(null)).toBe('/giris');
    expect(buildLoginUrl('/giris')).toBe('/giris');
  });

  it('ikinci adım adresi hedefi taşır; varsayılan hedefte sorgu eklemez', () => {
    expect(buildTwoFactorUrl('/panel')).toBe('/iki-adim');
    expect(buildTwoFactorUrl('/panel/urunler')).toBe('/iki-adim?sonra=%2Fpanel%2Furunler');
    expect(buildTwoFactorUrl('//evil.example')).toBe('/iki-adim');
  });
});

describe('isProtectedPath', () => {
  it('yalnız /panel ve altını korur', () => {
    expect(isProtectedPath('/panel')).toBe(true);
    expect(isProtectedPath('/panel/urunler')).toBe(true);
    expect(isProtectedPath('/%70anel/urunler')).toBe(true);
    expect(isProtectedPath('/panelci')).toBe(false);
    expect(isProtectedPath('/giris')).toBe(false);
    expect(isProtectedPath('/')).toBe(false);
  });
});
