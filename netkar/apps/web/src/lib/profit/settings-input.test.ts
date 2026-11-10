import { describe, expect, it } from 'vitest';

import { exclusiveOfVat } from '@/lib/profit/decimal-math';
import {
  addDays,
  formatDateTime,
  formatDesi,
  formatLongDate,
  formatPlainNumber,
  isDateText,
  parseDecimalInput,
  todayIstanbul,
  toInputText,
  toMoneyString,
} from '@/lib/profit/settings-input';

describe('exclusiveOfVat (K02, float yok)', () => {
  it('KDV dahil tutarı kuruşa yarım yukarı hariçleştirir', () => {
    expect(exclusiveOfVat('54.00', 20)).toBe('45.00');
    expect(exclusiveOfVat('50.00', 20)).toBe('41.67');
    expect(exclusiveOfVat('12.00', 20)).toBe('10.00');
    expect(exclusiveOfVat('0.00', 20)).toBe('0.00');
    // 10,025 / 1,0 = 10,025 -> yarım yukarı 10,03 (float'ta 10,02 çıkardı)
    expect(exclusiveOfVat('10.025', 0)).toBe('10.03');
    expect(exclusiveOfVat('100000.00', 20)).toBe('83333.33');
    expect(exclusiveOfVat('54', 10)).toBe('49.09');
  });

  it('negatif tutarı ve kesirli oranı reddeder', () => {
    expect(() => exclusiveOfVat('-1.00', 20)).toThrow(TypeError);
    expect(() => exclusiveOfVat('1.00', 12.5)).toThrow(TypeError);
  });
});

// AF-01: tek kural. Ondalık ayracı yalnız virgül; nokta yalnız doğru gruplanmış binlik; belirsiz biçim reddedilir.
// Para (en çok 2 hane) ve oran (en çok 4 hane) alanları AYNI kuralı kullanır.
describe('parseDecimalInput, kabul edilenler (tablo)', () => {
  it.each([
    // [metin, en çok ondalık, beklenen]
    ['54,50', 2, '54.50'],
    ['54', 2, '54'],
    ['0', 2, '0'],
    ['0,5', 2, '0.5'],
    [',5', 2, '0.5'],
    ['007,5', 2, '7.5'],
    ['1250', 2, '1250'],
    ['1250,00', 2, '1250.00'],
    ['1.250,00', 2, '1250.00'],
    ['1.250,5', 2, '1250.5'],
    ['1.250', 2, '1250'],
    ['12.345', 2, '12345'],
    ['1.250.000', 2, '1250000'],
    ['1 250', 2, '1250'],
    ['1 250,75', 2, '1250.75'],
    [' 12,5 ', 2, '12.5'],
    ['123456789012345', 2, '123456789012345'],
    ['123.456.789.012.345', 2, '123456789012345'],
    // oran alanı (4 hane): virgül yine ondalıktır
    ['2,5', 4, '2.5'],
    ['2,5000', 4, '2.5000'],
    ['1,255', 4, '1.255'],
    ['12,550', 4, '12.550'],
    ['1.250', 4, '1250'],
  ])('%s (en çok %i ondalık) -> %s', (text, maxFraction, expected) => {
    expect(parseDecimalInput(text, maxFraction)).toEqual({ ok: true, value: expected });
  });
});

describe('parseDecimalInput, reddedilenler (tablo)', () => {
  it.each([
    // boş
    ['', 'empty'],
    ['   ', 'empty'],
    // eksi, harf, üstel gösterim
    ['-5', 'invalid'],
    ['-0', 'invalid'],
    ['abc', 'invalid'],
    ['1e3', 'invalid'],
    ['12 TL', 'invalid'],
    // 1000 kat değişebilecek belirsiz noktalar: ondalık mı binlik mi belli değil
    ['12.5', 'ambiguous'],
    ['54.50', 'ambiguous'],
    ['0.500', 'ambiguous'],
    ['1.2345', 'ambiguous'],
    ['1234.50', 'ambiguous'],
    ['12.50', 'ambiguous'],
    // virgülden sonra fazla hane: para alanında binlik SAYILMAZ
    ['1,255', 'too_many_decimals'],
    ['1,250', 'too_many_decimals'],
    ['12,550', 'too_many_decimals'],
    ['0,125', 'too_many_decimals'],
    ['12,5555', 'too_many_decimals'],
    // bozuk gruplama ve ayraçlar
    ['1.25.0', 'invalid'],
    ['1.2345.678', 'invalid'],
    ['.250', 'invalid'],
    ['1..250', 'invalid'],
    ['1.250 000', 'invalid'],
    ['12 5', 'invalid'],
    ['1,5.3', 'invalid'],
    ['1,250.50', 'invalid'],
    ['1,2,3', 'invalid'],
    ['12,', 'invalid'],
    [',', 'invalid'],
    ['.', 'invalid'],
    // tam sayı çok büyük
    ['1234567890123456', 'invalid'],
    ['1.234.567.890.123.456', 'invalid'],
  ])('"%s" -> %s (para, en çok 2 ondalık)', (text, reason) => {
    expect(parseDecimalInput(text, 2)).toEqual({ ok: false, reason });
  });

  it('oran alanı (4 hane) para alanıyla aynı kuralı izler: nokta binlik ya da belirsiz', () => {
    expect(parseDecimalInput('2.5', 4)).toEqual({ ok: false, reason: 'ambiguous' });
    expect(parseDecimalInput('12.50', 4)).toEqual({ ok: false, reason: 'ambiguous' });
    expect(parseDecimalInput('1,23456', 4)).toEqual({ ok: false, reason: 'too_many_decimals' });
    expect(parseDecimalInput('1,250.50', 4)).toEqual({ ok: false, reason: 'invalid' });
  });

  it('sessiz 1000 kat değişim yok: virgüllü yazım hiçbir koşulda binlik sayılmaz', () => {
    for (const text of ['1,255', '12,550', '54,500', '100,000']) {
      const parsed = parseDecimalInput(text, 2);
      expect(parsed.ok).toBe(false);
    }
  });
});

describe('biçim yardımcıları', () => {
  it('toMoneyString kuruş biçimine tamamlar', () => {
    expect(toMoneyString('54')).toBe('54.00');
    expect(toMoneyString('54.5')).toBe('54.50');
    expect(toMoneyString('54.55')).toBe('54.55');
  });

  it('toInputText ondalık virgül koyar', () => {
    expect(toInputText('54.50')).toBe('54,50');
  });

  it('formatDesi ve formatPlainNumber tr-TR gösterir', () => {
    expect(formatDesi('2.00')).toBe('2');
    expect(formatDesi('2.50')).toBe('2,5');
    expect(formatDesi('1000.00')).toBe('1.000');
    expect(formatPlainNumber('54.00', 2, 2)).toBe('54,00');
    expect(formatPlainNumber('2.5000', 4)).toBe('2,5');
    expect(formatPlainNumber('0.50', 2)).toBe('0,5');
  });
});

describe('tarih', () => {
  it('isDateText gerçek takvim günlerini kabul eder', () => {
    expect(isDateText('2026-10-01')).toBe(true);
    expect(isDateText('2026-02-30')).toBe(false);
    expect(isDateText('2026-13-01')).toBe(false);
    expect(isDateText('01.10.2026')).toBe(false);
    expect(isDateText('')).toBe(false);
  });

  it('addDays ay ve yıl sınırını geçer', () => {
    expect(addDays('2026-11-10', -92)).toBe('2026-08-10');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addDays('2026-11-10', 366)).toBe('2027-11-11');
  });

  it('todayIstanbul gün sınırını İstanbul saatine göre alır', () => {
    // 21:30 UTC = 00:30 İstanbul (ertesi gün)
    expect(todayIstanbul(new Date('2026-11-10T21:30:00Z'))).toBe('2026-11-11');
    expect(todayIstanbul(new Date('2026-11-10T20:30:00Z'))).toBe('2026-11-10');
  });

  it('formatLongDate ve formatDateTime sabit tr-TR biçimindedir', () => {
    expect(formatLongDate('2026-10-01')).toBe('1 Ekim 2026');
    expect(formatLongDate('2026-12-25')).toBe('25 Aralık 2026');
    expect(formatDateTime('2026-11-10T11:35:00Z')).toBe('10 Kasım 2026, 14:35');
    expect(formatDateTime('2026-11-10T21:05:00Z')).toBe('11 Kasım 2026, 00:05');
  });
});
