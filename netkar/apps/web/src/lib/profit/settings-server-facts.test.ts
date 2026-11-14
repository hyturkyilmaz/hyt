import { describe, expect, it } from 'vitest';

import { makeSettings, makeSettingsWithServerFacts } from '@/lib/profit/settings-fixtures';
import { addDays, todayIstanbul } from '@/lib/profit/settings-input';
import {
  advanceServerDay,
  daysBetween,
  formatVatRate,
  resolveToday,
  resolveVatRates,
  startSuggestionNote,
  suggestStartDay,
} from '@/lib/profit/settings-server-facts';
import { settingsResponseViolations } from '@/test/profit-settings-contract';

// Tarih beklentileri bugünden hesaplanır (sabit takvim tarihi yok).
const TODAY = todayIstanbul();

describe('resolveVatRates', () => {
  it('sunucu oranlarını kullanır', () => {
    const settings = makeSettings({ vat_rates: { shipping: '10', service_fee: '0.5' } });
    expect(resolveVatRates(settings)).toEqual({ shipping: '10', serviceFee: '0.5' });
  });

  it('eski API (alan yok) ya da bozuk değerde %20 yedeği', () => {
    expect(resolveVatRates(makeSettings())).toEqual({ shipping: '20', serviceFee: '20' });
    const bad = makeSettings({ vat_rates: { shipping: '-3', service_fee: 'abc' } });
    expect(resolveVatRates(bad)).toEqual({ shipping: '20', serviceFee: '20' });
  });

  it('görünen oran: sondaki sıfırlar atılır, ondalık virgüldür', () => {
    expect(formatVatRate('20')).toBe('20');
    expect(formatVatRate('20.0000')).toBe('20');
    expect(formatVatRate('0.5')).toBe('0,5');
  });
});

describe('bugün', () => {
  it('sunucu günü varsa o, yoksa cihaz günü', () => {
    expect(resolveToday('2030-05-06', TODAY)).toBe('2030-05-06');
    expect(resolveToday(undefined, TODAY)).toBe(TODAY);
    expect(resolveToday('bozuk', TODAY)).toBe(TODAY);
  });

  it('gün farkı ve sunucu gününü geçen gün kadar ilerletme', () => {
    expect(daysBetween('2026-02-27', '2026-03-02')).toBe(3);
    expect(advanceServerDay('2030-05-06', TODAY, TODAY)).toBe('2030-05-06');
    expect(advanceServerDay('2030-05-06', TODAY, addDays(TODAY, 2))).toBe('2030-05-08');
    // Cihaz saati geri giderse sunucu günü geriye gitmez
    expect(advanceServerDay('2030-05-06', TODAY, addDays(TODAY, -4))).toBe('2030-05-06');
  });
});

describe('başlangıç önerisi', () => {
  it('en eski sipariş gününden bir gün önce, kesin', () => {
    const earliest = addDays(TODAY, -200);
    const suggestion = suggestStartDay({
      today: TODAY,
      earliestOrderDay: earliest,
      lookbackDays: 92,
    });
    expect(suggestion).toEqual({
      day: addDays(earliest, -1),
      approximate: false,
      earliestOrderDay: earliest,
    });
    expect(startSuggestionNote(suggestion, 92)).not.toContain('yaklaşık');
  });

  it('sipariş yok ya da eski API: bugünden tarama penceresi kadar geri, yaklaşık', () => {
    for (const earliestOrderDay of [null, undefined]) {
      const suggestion = suggestStartDay({ today: TODAY, earliestOrderDay, lookbackDays: 92 });
      expect(suggestion.day).toBe(addDays(TODAY, -92));
      expect(suggestion.approximate).toBe(true);
      expect(startSuggestionNote(suggestion, 92)).toContain('Önerilen tarih yaklaşıktır');
    }
  });

  it('K33 alt sınırının (2000-01-01) altına inmez', () => {
    const suggestion = suggestStartDay({
      today: TODAY,
      earliestOrderDay: '2000-01-01',
      lookbackDays: 92,
    });
    expect(suggestion.day).toBe('2000-01-01');
  });
});

describe('yanıt sözleşmesi (SettingsOut)', () => {
  it('yeni API yanıtı uyumlu, eski API yanıtı da (alanlar isteğe bağlı)', () => {
    const modern = makeSettingsWithServerFacts({ earliest_order_day: null, today_istanbul: TODAY });
    expect(settingsResponseViolations(modern as unknown as Record<string, unknown>)).toEqual([]);
    expect(
      settingsResponseViolations(makeSettings() as unknown as Record<string, unknown>),
    ).toEqual([]);
  });

  it('bozuk yeni alanlar ve şemada olmayan alan yakalanır', () => {
    const bad = {
      ...makeSettings(),
      earliest_order_day: '10/09/2026',
      vat_rates: { shipping: 20 },
      extra: 1,
    };
    const problems = settingsResponseViolations(bad as unknown as Record<string, unknown>);
    expect(problems).toEqual(
      expect.arrayContaining([
        'earliest_order_day: YYYY-AA-GG ya da null olmalı',
        'vat_rates.shipping: sade ondalık dizge olmalı (float değil)',
        'vat_rates.service_fee: sade ondalık dizge olmalı (float değil)',
        'extra: yanıt şemasında yok',
      ]),
    );
  });
});
