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

describe('parseDecimalInput', () => {
  it.each([
    ['54,50', 2, '54.50'],
    ['54.50', 2, '54.50'],
    ['54', 2, '54'],
    ['0', 2, '0'],
    ['0,5', 2, '0.5'],
    ['007,5', 2, '7.5'],
    ['1.250,50', 2, '1250.50'],
    ['1,250.50', 2, '1250.50'],
    ['1.250', 2, '1250'],
    ['1,250', 2, '1250'],
    ['1.250.000', 2, '1250000'],
    [' 12,5 ', 2, '12.5'],
    ['2,5', 4, '2.5'],
    ['2,5000', 4, '2.5000'],
  ])('%s -> %s', (text, maxFraction, expected) => {
    expect(parseDecimalInput(text, maxFraction)).toEqual({ ok: true, value: expected });
  });

  it.each([
    ['', 'empty'],
    ['   ', 'empty'],
    ['abc', 'invalid'],
    ['-5', 'invalid'],
    ['1e3', 'invalid'],
    ['1,5.3', 'invalid'],
    ['12,', 'invalid'],
    [',', 'invalid'],
    ['1234567890123456', 'invalid'],
    ['1.2345.678', 'invalid'],
  ])('%s geçersiz sayılır', (text, reason) => {
    expect(parseDecimalInput(text, 2)).toEqual({ ok: false, reason });
  });

  it('izin verilenden fazla ondalığı ayrı nedenle reddeder', () => {
    expect(parseDecimalInput('1,255', 2)).toEqual({ ok: true, value: '1255' });
    expect(parseDecimalInput('0,125', 2)).toEqual({ ok: false, reason: 'too_many_decimals' });
    expect(parseDecimalInput('12,5555', 2)).toEqual({ ok: false, reason: 'too_many_decimals' });
    expect(parseDecimalInput('1,23456', 4)).toEqual({ ok: false, reason: 'too_many_decimals' });
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
