import { describe, expect, it } from 'vitest';

import { calculateProfit, type ProfitInput } from './profit';

// Girdiler ve beklenen değerler services/api/tests/golden/ içindeki TAHMİNİ (estimated) sonuçlardır
// (docs/12_kar_motoru.md). Kargo tarifesi kurgusaldır; kullanıcı kendi tutarını girer.
function base(overrides: Partial<ProfitInput> = {}): ProfitInput {
  return {
    priceIncl: 49990n,
    vatRatePct: 20,
    cost: 18000n,
    costIncludesVat: false,
    costVatRatePct: 20,
    commissionBps: 1500n,
    commissionIncludesVat: true,
    shipping: 4500n,
    shippingIncludesVat: false,
    returnShipping: 4500n,
    serviceFeeExcl: 1000n,
    ad: { kind: 'amount', amount: 0n },
    returnRateBps: 0n,
    unsellableBps: 0n,
    ...overrides,
  };
}

describe('net kâr: golden tahminleriyle karşılaştırma', () => {
  it('G01: 499,90 TL, %15 komisyon, maliyet 180 -> net kâr 119,09, marj %28,59', () => {
    const r = calculateProfit(base());
    expect(r.salesExcl).toBe(41658n);
    expect(r.commissionExcl).toBe(6249n);
    expect(r.commissionVat).toBe(1250n);
    expect(r.netProfit).toBe(11909n);
    expect(r.marginBps).toBe(2859n);
    expect(r.withholding).toBe(417n);
    expect(r.vatEffect).toBe(2382n);
  });

  it('G03: satıcı indirimi sonrası 297,50 TL, %18 komisyon -> net kâr 28,29, marj %11,41', () => {
    const r = calculateProfit(base({ priceIncl: 29750n, commissionBps: 1800n, cost: 12000n }));
    expect(r.salesExcl).toBe(24792n);
    expect(r.commissionExcl).toBe(4463n);
    expect(r.netProfit).toBe(2829n);
    expect(r.marginBps).toBe(1141n);
    expect(r.vatEffect).toBe(566n);
  });

  it('G09: %10 KDV, alış KDV %10 -> net kâr 28,33, marj %11,33, KDV etkisi -6,33', () => {
    const r = calculateProfit(
      base({
        priceIncl: 27500n,
        vatRatePct: 10,
        costVatRatePct: 10,
        cost: 13000n,
        commissionBps: 1600n,
      }),
    );
    expect(r.commissionExcl).toBe(3667n);
    expect(r.netProfit).toBe(2833n);
    expect(r.marginBps).toBe(1133n);
    expect(r.vatEffect).toBe(-633n);
    expect(r.withholding).toBe(250n);
  });

  it('G10: %1 KDV -> net kâr 13,22, marj %7,42, KDV etkisi -13,17', () => {
    const r = calculateProfit(
      base({
        priceIncl: 18000n,
        vatRatePct: 1,
        costVatRatePct: 1,
        cost: 9500n,
        commissionBps: 1000n,
      }),
    );
    expect(r.netProfit).toBe(1322n);
    expect(r.marginBps).toBe(742n);
    expect(r.vatEffect).toBe(-1317n);
  });

  it('G12: komisyon tutarı KDV hariç varsayımı -> net kâr 106,59, marj %25,59', () => {
    const r = calculateProfit(base({ commissionIncludesVat: false }));
    expect(r.commissionExcl).toBe(7499n);
    expect(r.commissionVat).toBe(1500n);
    expect(r.netProfit).toBe(10659n);
    expect(r.marginBps).toBe(2559n);
    expect(r.vatEffect).toBe(2132n);
  });

  it('G24: 40,00 TL reklam harcaması -> net kâr 79,09, marj %18,99', () => {
    const r = calculateProfit(base({ ad: { kind: 'amount', amount: 4000n } }));
    expect(r.netProfit).toBe(7909n);
    expect(r.marginBps).toBe(1899n);
    expect(r.vatEffect).toBe(1582n);
  });

  it('G31: net kâr tam sıfır', () => {
    const r = calculateProfit(
      base({
        priceIncl: 24000n,
        cost: 12000n,
        commissionBps: 1500n,
        shipping: 4000n,
        serviceFeeExcl: 1000n,
      }),
    );
    expect(r.netProfit).toBe(0n);
    expect(r.marginBps).toBe(0n);
    expect(r.vatEffect).toBe(0n);
  });

  it('G32: ucuz üründe sabit kargo kârı siler -> net kâr -35,06, marj -%70,23', () => {
    const r = calculateProfit(
      base({
        priceIncl: 5990n,
        cost: 2500n,
        commissionBps: 2000n,
        shipping: 4000n,
      }),
    );
    expect(r.netProfit).toBe(-3506n);
    expect(r.marginBps).toBe(-7023n);
  });
});

describe('maliyet KDV girişi', () => {
  it('maliyet KDV dahil girilirse hariçleştirilir: 216,00 dahil %20 = 180,00', () => {
    const r = calculateProfit(base({ cost: 21600n, costIncludesVat: true }));
    expect(r.cost).toBe(18000n);
    expect(r.netProfit).toBe(11909n);
    expect(r.vatEffect).toBe(2382n);
  });
});

describe('iade payı (K10, G16, G17)', () => {
  it('iade oranı sıfırsa iade payı yoktur', () => {
    const r = calculateProfit(base());
    expect(r.returnCost).toBe(0n);
    expect(r.netProfit).toBe(r.profitBeforeReturns);
  });

  it('%100 iade, ürün stoğa döner: kayıp kargo + iade kargo + hizmet bedeli = -100,00 (G16)', () => {
    const r = calculateProfit(base({ returnRateBps: 10000n }));
    expect(r.netProfit).toBe(-10000n);
  });

  it('%100 iade, ürün satılamaz: kayıp -280,00 (G17)', () => {
    const r = calculateProfit(base({ returnRateBps: 10000n, unsellableBps: 10000n }));
    expect(r.netProfit).toBe(-28000n);
  });

  it('%10 iade: beklenen değer = %90 x 119,09 + %10 x (-100,00)', () => {
    const r = calculateProfit(base({ returnRateBps: 1000n }));
    // iade kaybı = (119,09 + 100,00) x %10 = 21,909 -> 21,91
    expect(r.returnCost).toBe(2191n);
    expect(r.netProfit).toBe(11909n - 2191n);
  });

  it('reklam iadede de harcanmış sayılır', () => {
    const withAd = calculateProfit(
      base({ ad: { kind: 'amount', amount: 4000n }, returnRateBps: 10000n }),
    );
    expect(withAd.netProfit).toBe(-14000n);
  });

  it('iade kargo KDV dahil girilirse hariçleştirilir', () => {
    const r = calculateProfit(
      base({
        shipping: 5400n,
        returnShipping: 5400n,
        shippingIncludesVat: true,
        returnRateBps: 10000n,
      }),
    );
    expect(r.netProfit).toBe(-10000n);
  });
});

describe('reklam: ROAS girişi', () => {
  it('ROAS 5,00 ise harcama = KDV dahil satış / 5 = 99,98 (KDV hariç sayılır)', () => {
    const r = calculateProfit(base({ ad: { kind: 'roas', roasHundredths: 500n } }));
    expect(r.ad).toBe(9998n);
    expect(r.netProfit).toBe(11909n - 9998n);
  });

  it('başabaş ROAS: KDV hariç satış / reklam öncesi net kâr', () => {
    const r = calculateProfit(base({ ad: { kind: 'amount', amount: 4000n } }));
    // reklam öncesi kâr 119,09; 416,58 / 119,09 = 3,4979 -> 3,50
    expect(r.breakEvenRoasExcl).toBe(350n);
    // KDV dahil ciro: 499,90 / 119,09 = 4,1977 -> 4,20
    expect(r.breakEvenRoasIncl).toBe(420n);
  });

  it('reklam öncesi kâr sıfır veya negatifse başabaş ROAS yoktur', () => {
    const r = calculateProfit(base({ cost: 40000n }));
    expect(r.breakEvenRoasExcl).toBeNull();
    expect(r.breakEvenRoasIncl).toBeNull();
  });
});

describe('başabaş satış fiyatı', () => {
  it('bulunan fiyatta net kâr >= 0, bir kuruş altında < 0', () => {
    const cases: Partial<ProfitInput>[] = [
      {},
      { commissionIncludesVat: false },
      { returnRateBps: 1500n, unsellableBps: 2000n },
      { ad: { kind: 'amount', amount: 2500n } },
      { ad: { kind: 'roas', roasHundredths: 800n }, returnRateBps: 500n },
      { vatRatePct: 10, costVatRatePct: 10, commissionBps: 1275n },
    ];
    for (const overrides of cases) {
      const r = calculateProfit(base(overrides));
      const price = r.breakEvenPrice;
      expect(price).not.toBeNull();
      expect(
        calculateProfit(base({ ...overrides, priceIncl: price! })).netProfit,
      ).toBeGreaterThanOrEqual(0n);
      expect(
        calculateProfit(base({ ...overrides, priceIncl: price! - 1n })).netProfit,
      ).toBeLessThan(0n);
    }
  });

  it('G01 girdileriyle başabaş fiyatı 499,90 TL altında ve makul', () => {
    const r = calculateProfit(base());
    // 180 + 45 + 10 = 235 sabit gider; birim payı (1 - 0,15) / 1,2 = 0,70833; 235 / 0,70833 = 331,76
    // 331,76 TL'de net kâr tam 0,00 olur (kalemler kuruşa yuvarlanmış).
    expect(r.breakEvenPrice).toBe(33176n);
  });

  it('komisyon ve KDV payı satışı aşıyorsa hiçbir fiyatta kâr yoktur', () => {
    const r = calculateProfit(base({ commissionBps: 9000n, commissionIncludesVat: false }));
    expect(r.breakEvenPrice).toBeNull();
  });

  it('%100 iade oranında başabaş yoktur', () => {
    expect(calculateProfit(base({ returnRateBps: 10000n })).breakEvenPrice).toBeNull();
  });
});

describe('uç durumlar', () => {
  it('maliyet sıfır: net kâr = net satış - gider', () => {
    const r = calculateProfit(base({ cost: 0n }));
    expect(r.netProfit).toBe(29909n);
  });

  it('net satış sıfırsa marj yoktur', () => {
    const r = calculateProfit(base({ priceIncl: 0n }));
    expect(r.marginBps).toBeNull();
  });

  it('yarım kuruş sınırında KDV ayrımı (G33): 12,03 TL, %20', () => {
    const r = calculateProfit(
      base({ priceIncl: 1203n, cost: 0n, shipping: 0n, serviceFeeExcl: 0n, commissionBps: 0n }),
    );
    expect(r.salesExcl).toBe(1003n);
    expect(r.salesVat).toBe(200n);
  });
});
