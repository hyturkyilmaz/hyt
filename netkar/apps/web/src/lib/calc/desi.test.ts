import { describe, expect, it } from 'vitest';

import { calculateDesi, shrinkOneCm, type DesiInput } from './desi';

// Ölçüler cm x 10, ağırlık gram.
function input(overrides: Partial<DesiInput> = {}): DesiInput {
  return {
    length: 300n,
    width: 200n,
    height: 100n,
    weightGrams: 1000n,
    divisor: 'domestic',
    ...overrides,
  };
}

describe('desi hesabı', () => {
  it('30 x 20 x 10 cm = 6000 cm3 / 3000 = 2,00 desi; ağırlık 1 kg ise hacim esas', () => {
    const r = calculateDesi(input());
    expect(r.volumetricHundredths).toBe(200n);
    expect(r.weightHundredths).toBe(100n);
    expect(r.billableHundredths).toBe(200n);
    expect(r.basis).toBe('volume');
    expect(r.billableRoundedUp).toBe(2n);
  });

  it('ağırlık desiden büyükse ağırlık esas alınır', () => {
    const r = calculateDesi(input({ weightGrams: 5500n }));
    expect(r.basis).toBe('weight');
    expect(r.billableHundredths).toBe(550n);
    expect(r.billableRoundedUp).toBe(6n);
  });

  it('eşitlikte hacim esas sayılır ve değer değişmez', () => {
    const r = calculateDesi(input({ weightGrams: 2000n }));
    expect(r.basis).toBe('volume');
    expect(r.billableHundredths).toBe(200n);
  });

  it('yurt dışı böleni 5.000: 6000 / 5000 = 1,20 desi', () => {
    const r = calculateDesi(input({ divisor: 'international', weightGrams: 500n }));
    expect(r.volumetricHundredths).toBe(120n);
    expect(r.billableRoundedUp).toBe(2n);
  });

  it('ondalıklı ölçü: 25,5 x 18,2 x 7,3 cm', () => {
    const r = calculateDesi(input({ length: 255n, width: 182n, height: 73n }));
    // 25,5 x 18,2 x 7,3 = 3387,93 cm3 / 3000 = 1,12931
    expect(r.volumetricHundredths).toBe(113n);
    expect(r.billableRoundedUp).toBe(2n);
  });

  it('tam desi değeri yukarı yuvarlanmaz: 3000 cm3 = 1 desi', () => {
    const r = calculateDesi(input({ length: 300n, width: 100n, height: 100n, weightGrams: 0n }));
    expect(r.volumetricHundredths).toBe(100n);
    expect(r.billableRoundedUp).toBe(1n);
  });

  it('bir ölçüyü 1 cm küçültmek desiyi azaltır', () => {
    const before = calculateDesi(input());
    const after = calculateDesi(input({ height: shrinkOneCm(100n) ?? 0n }));
    expect(after.volumetricHundredths).toBeLessThan(before.volumetricHundredths);
    expect(shrinkOneCm(10n)).toBeNull();
  });
});
