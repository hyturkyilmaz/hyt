import { describe, expect, it } from 'vitest';

import { formatPercent, formatTRY, getSign } from '@/lib/format';

const NBSP = ' ';

describe('formatTRY', () => {
  it('tr-TR biçiminde yazar: nokta binlik, virgül kuruş', () => {
    expect(formatTRY('1234.56')).toBe('₺1.234,56');
    expect(formatTRY('1234567.8')).toBe('₺1.234.567,80');
    expect(formatTRY('999')).toBe('₺999,00');
    expect(formatTRY('1000')).toBe('₺1.000,00');
  });

  it('sıfırı ve küçük tutarları doğru yazar', () => {
    expect(formatTRY('0')).toBe('₺0,00');
    expect(formatTRY('0.5')).toBe('₺0,50');
    expect(formatTRY('0.07')).toBe('₺0,07');
  });

  it('negatifte eksi işareti koyar', () => {
    expect(formatTRY('-1234.5')).toBe('-₺1.234,50');
    expect(formatTRY('-0.01')).toBe('-₺0,01');
  });

  it('kuruşa yarım yukarı yuvarlar (sıfırdan uzağa)', () => {
    expect(formatTRY('0.005')).toBe('₺0,01');
    expect(formatTRY('0.004')).toBe('₺0,00');
    expect(formatTRY('1.005')).toBe('₺1,01'); // float ile 1,00 çıkardı
    expect(formatTRY('-1.005')).toBe('-₺1,01');
    expect(formatTRY('2.675')).toBe('₺2,68');
    expect(formatTRY('99.995')).toBe('₺100,00');
  });

  it('sıfıra yuvarlanan negatif değerde eksi göstermez', () => {
    expect(formatTRY('-0.004')).toBe('₺0,00');
    expect(formatTRY('-0')).toBe('₺0,00');
  });

  it('çok büyük tutarlarda kuruş hassasiyetini korur', () => {
    expect(formatTRY('12345678901234567890.12')).toBe('₺12.345.678.901.234.567.890,12');
  });

  it('number ve bigint girdisini de kabul eder', () => {
    expect(formatTRY(1234.5)).toBe('₺1.234,50');
    expect(formatTRY(-0.1)).toBe('-₺0,10');
    expect(formatTRY(42n)).toBe('₺42,00');
  });

  it('stil seçeneklerini uygular', () => {
    expect(formatTRY('1234.5', { style: 'code' })).toBe(`1.234,50${NBSP}TL`);
    expect(formatTRY('1234.5', { style: 'none' })).toBe('1.234,50');
    expect(formatTRY('10', { signed: true })).toBe('+₺10,00');
    expect(formatTRY('0', { signed: true })).toBe('₺0,00');
    expect(formatTRY('-10', { signed: true })).toBe('-₺10,00');
  });

  it('geçersiz girdide hata verir, sessizce yanlış para yazmaz', () => {
    expect(() => formatTRY('abc')).toThrow(TypeError);
    expect(() => formatTRY('1,5')).toThrow(TypeError);
    expect(() => formatTRY('')).toThrow(TypeError);
    expect(() => formatTRY(Number.NaN)).toThrow(TypeError);
    expect(() => formatTRY(Number.POSITIVE_INFINITY)).toThrow(TypeError);
  });
});

describe('formatPercent', () => {
  it('yüzde puanını tr-TR biçiminde yazar', () => {
    expect(formatPercent('12.5')).toBe('%12,5');
    expect(formatPercent('0')).toBe('%0,0');
    expect(formatPercent('100')).toBe('%100,0');
    expect(formatPercent('1234.56', { fractionDigits: 2 })).toBe('%1.234,56');
  });

  it('negatifi ve işaretli gösterimi destekler', () => {
    expect(formatPercent('-3.25', { fractionDigits: 2 })).toBe('-%3,25');
    expect(formatPercent('4', { signed: true })).toBe('+%4,0');
    expect(formatPercent('-0.04')).toBe('%0,0');
  });

  it('ondalıksız ve yuvarlamalı kullanım', () => {
    expect(formatPercent('12.5', { fractionDigits: 0 })).toBe('%13');
    expect(formatPercent('12.45')).toBe('%12,5');
    expect(formatPercent('9.95')).toBe('%10,0');
  });
});

describe('getSign', () => {
  it('yuvarlamadan sonraki işareti verir', () => {
    expect(getSign('10')).toBe('positive');
    expect(getSign('-10')).toBe('negative');
    expect(getSign('0')).toBe('zero');
    expect(getSign('0.004')).toBe('zero');
    expect(getSign('-0.004')).toBe('zero');
    expect(getSign('-0.005')).toBe('negative');
  });
});
