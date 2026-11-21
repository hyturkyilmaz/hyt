import { describe, expect, it } from 'vitest';

import {
  divCeil,
  divRound,
  formatBps,
  formatKurus,
  formatScaled,
  parseDecimal,
  percentOf,
  splitExclusive,
  splitInclusive,
} from './money';

function parse(text: string, scale = 2) {
  const result = parseDecimal(text, scale);
  return result.ok ? result.value : result.error;
}

describe('divRound ve divCeil (K01)', () => {
  it('sıfırdan uzağa yarım yukarı yuvarlar', () => {
    expect(divRound(1n, 2n)).toBe(1n);
    expect(divRound(-1n, 2n)).toBe(-1n);
    expect(divRound(10025n, 1000n)).toBe(10n);
    expect(divRound(10025n, 100n)).toBe(100n);
    expect(divRound(-5n, 1000n)).toBe(0n);
    expect(divRound(0n, 7n)).toBe(0n);
  });

  it('pozitif olmayan bölende hata verir', () => {
    expect(() => divRound(1n, 0n)).toThrow(RangeError);
    expect(() => divCeil(1n, -1n)).toThrow(RangeError);
  });

  it('divCeil yukarı yuvarlar', () => {
    expect(divCeil(7n, 3n)).toBe(3n);
    expect(divCeil(6n, 3n)).toBe(2n);
    expect(divCeil(0n, 3n)).toBe(0n);
  });
});

describe('KDV ayrımı (K02)', () => {
  it('dahilden: 499,90 %20 -> 416,58 + 83,32 (G01)', () => {
    expect(splitInclusive(49990n, 20)).toEqual({ excl: 41658n, vat: 8332n, incl: 49990n });
  });

  it('dahilden: %10 ve %1 (G09, G10)', () => {
    expect(splitInclusive(27500n, 10)).toEqual({ excl: 25000n, vat: 2500n, incl: 27500n });
    expect(splitInclusive(18000n, 1)).toEqual({ excl: 17822n, vat: 178n, incl: 18000n });
  });

  it('yarım kuruş sınırı: 12,03 / 1,20 = 10,025 -> 10,03 (G33)', () => {
    expect(splitInclusive(1203n, 20).excl).toBe(1003n);
  });

  it('hariçten: kdv kuruşa yuvarlanır, toplam tutar', () => {
    expect(splitExclusive(4500n, 20)).toEqual({ excl: 4500n, vat: 900n, incl: 5400n });
    const split = splitExclusive(333n, 20);
    expect(split.excl + split.vat).toBe(split.incl);
  });

  it('percentOf oranı kuruşa yuvarlar', () => {
    expect(percentOf(41658n, 100n)).toBe(417n);
  });
});

describe('sayı girdisi ayrıştırma', () => {
  it('virgül ve nokta ondalığını kabul eder', () => {
    expect(parse('1234,56')).toBe(123456n);
    expect(parse('1234.56')).toBe(123456n);
    expect(parse('0,5')).toBe(50n);
    expect(parse('0.125', 3)).toBe(125n);
    expect(parse('12')).toBe(1200n);
    expect(parse(',5')).toBe(50n);
  });

  it('binlik ayracını tanır', () => {
    expect(parse('1.234,56')).toBe(123456n);
    expect(parse('1,234.56')).toBe(123456n);
    expect(parse('1.234.567')).toBe(123456700n);
    expect(parse('1.234')).toBe(123400n);
  });

  it('para ve yüzde simgelerini ve boşlukları yok sayar', () => {
    expect(parse('₺ 1.250,00')).toBe(125000n);
    expect(parse('15 %')).toBe(1500n);
    expect(parse('99,90 TL')).toBe(9990n);
  });

  it('geçersiz girdiyi anlaşılır kodla reddeder', () => {
    expect(parse('')).toBe('empty');
    expect(parse('   ')).toBe('empty');
    expect(parse('abc')).toBe('invalid');
    expect(parse('1,2,3')).toBe('invalid');
    expect(parse('1.23.4')).toBe('invalid');
    expect(parse('1,2.3,4')).toBe('invalid');
    expect(parse('-5')).toBe('negative');
    expect(parse('12,345')).toBe('too_many_decimals');
    expect(parse('1234567890123')).toBe('too_large');
  });
});

describe('biçimlendirme', () => {
  it('kuruşu tr-TR yazar', () => {
    expect(formatKurus(123456n)).toBe('1.234,56\u00a0TL');
    expect(formatKurus(-21240n)).toBe('-212,40\u00a0TL');
    expect(formatKurus(0n)).toBe('0,00\u00a0TL');
  });

  it('yüzdeyi ve ölçekli sayıyı yazar', () => {
    expect(formatBps(2859n)).toBe('%28,59');
    expect(formatBps(1500n, 0)).toBe('%15');
    expect(formatScaled(1234n, 2)).toBe('12,34');
    expect(formatScaled(1234567n, 2)).toBe('12.345,67');
    expect(formatScaled(-5n, 2)).toBe('-0,05');
    expect(formatScaled(7n, 0)).toBe('7');
  });
});
