import { describe, expect, it } from 'vitest';

import { calculateCommission, splitCommission, type CommissionInput } from './commission';

// Beklenen değerler docs/12_kar_motoru.md ve services/api/tests/golden/ (G01, G02, G12, G09, G10)
// tahmini sonuçlarıdır.
function input(overrides: Partial<CommissionInput> = {}): CommissionInput {
  return {
    priceIncl: 49990n,
    vatRatePct: 20,
    commissionBps: 1500n,
    commissionIncludesVat: true,
    shipping: 0n,
    shippingIncludesVat: false,
    serviceFeeExcl: 0n,
    ...overrides,
  };
}

describe('komisyon hesabı', () => {
  it('K07 varsayılanı (KDV dahil): 499,90 x %15 = 74,99 -> 62,49 + 12,50 (G01, G02)', () => {
    const result = calculateCommission(input());
    expect(result.commissionIncl).toBe(7499n);
    expect(result.commissionExcl).toBe(6249n);
    expect(result.commissionVat).toBe(1250n);
    expect(result.price.excl).toBe(41658n);
    expect(result.price.vat).toBe(8332n);
  });

  it('K07 alternatifi (KDV üstüne eklenir): 74,99 + 15,00 (G12)', () => {
    const result = calculateCommission(input({ commissionIncludesVat: false }));
    expect(result.commissionExcl).toBe(7499n);
    expect(result.commissionVat).toBe(1500n);
    expect(result.commissionIncl).toBe(8999n);
    // G12 hakediş: 409,91
    expect(result.settlement).toBe(40991n);
  });

  it('iki varsayım arasındaki fark satır başına 12,50 TL (G02 ile G12)', () => {
    const base = calculateCommission(input());
    const alt = calculateCommission(input({ commissionIncludesVat: false }));
    expect(base.settlement - alt.settlement).toBe(1500n);
  });

  it('hakediş, stopaj ve beklenen tahsilat (G01: 424,91, 4,17, 354,74)', () => {
    const result = calculateCommission(input({ shipping: 4500n, serviceFeeExcl: 1000n }));
    expect(result.settlement).toBe(42491n);
    expect(result.invoiceDeductions).toBe(6600n);
    expect(result.withholding).toBe(417n);
    expect(result.expectedPayout).toBe(35474n);
  });

  it('kargo KDV dahil girilirse hariç ve KDV ayrılır', () => {
    const result = calculateCommission(input({ shipping: 5400n, shippingIncludesVat: true }));
    expect(result.shipping).toEqual({ excl: 4500n, vat: 900n, incl: 5400n });
  });

  it('%10 KDV oranlı ürün: 275,00 x %16 -> 36,67 + 7,33 (G09)', () => {
    const result = calculateCommission(
      input({ priceIncl: 27500n, vatRatePct: 10, commissionBps: 1600n }),
    );
    expect(result.commissionExcl).toBe(3667n);
    expect(result.commissionVat).toBe(733n);
    expect(result.settlement).toBe(23100n);
    expect(result.withholding).toBe(250n);
  });

  it('%1 KDV oranlı ürün: 180,00 x %10 -> 15,00 + 3,00 (G10)', () => {
    const result = calculateCommission(
      input({ priceIncl: 18000n, vatRatePct: 1, commissionBps: 1000n }),
    );
    expect(result.commissionExcl).toBe(1500n);
    expect(result.commissionVat).toBe(300n);
    expect(result.withholding).toBe(178n);
  });

  it('ondalıklı komisyon oranı: %12,75', () => {
    const parts = splitCommission(10000n, 1275n, true);
    expect(parts.incl).toBe(1275n);
    expect(parts.excl + parts.vat).toBe(parts.incl);
  });

  it('komisyon oranı sıfırsa komisyon sıfırdır', () => {
    const result = calculateCommission(input({ commissionBps: 0n }));
    expect(result.commissionIncl).toBe(0n);
    expect(result.settlement).toBe(49990n);
  });

  it('kalemler her zaman toplamı verir (KDV hariç + KDV = dahil)', () => {
    for (const price of [999n, 1001n, 12345n, 987654n]) {
      for (const bps of [100n, 725n, 1850n, 2150n]) {
        for (const includes of [true, false]) {
          const r = calculateCommission(
            input({ priceIncl: price, commissionBps: bps, commissionIncludesVat: includes }),
          );
          expect(r.commissionExcl + r.commissionVat).toBe(r.commissionIncl);
          expect(r.price.excl + r.price.vat).toBe(price);
        }
      }
    }
  });
});
