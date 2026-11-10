import { describe, expect, it } from 'vitest';

import { addDecimal, absAtLeast, decimalSign, subtractDecimal } from '@/lib/profit/decimal-math';
import {
  certaintyBadge,
  defaultDesiHint,
  expenseCell,
  lossBadge,
  missingItemNames,
  netProfitDisplay,
  periodLabel,
  refundPending,
  sourceBadge,
  summaryBanner,
  summaryView,
} from '@/lib/profit/present';
import {
  DEFAULT_RANGE,
  parseProductQuery,
  parseRange,
  productQueryString,
} from '@/lib/profit/query';
import { makeItem, makeLine, makeTotals, makeUnconfiguredTotals } from '@/lib/profit/test-fixtures';

describe('decimal-math', () => {
  it('float kullanmadan toplar ve çıkarır', () => {
    expect(addDecimal('0.1', '0.2')).toBe('0.3');
    expect(addDecimal('-10.50', '2.25')).toBe('-8.25');
    expect(addDecimal('5', '0.005')).toBe('5.005');
    expect(subtractDecimal('10.00', '12.50')).toBe('-2.50');
    expect(decimalSign('0.00')).toBe(0);
    expect(decimalSign('-0.01')).toBe(-1);
    expect(absAtLeast('-5.00', '3.00')).toBe(true);
    expect(absAtLeast('1.00', '-3.00')).toBe(false);
  });

  it('geçersiz girdide hata fırlatır', () => {
    expect(() => addDecimal('abc', '1')).toThrow(TypeError);
    expect(() => addDecimal('1.2.3', '1')).toThrow(TypeError);
  });
});

describe('netProfitDisplay (kural 1 ve 10)', () => {
  it('null net kâr asla değer değil, hesaplanamadı ve eksik kalem adlarıdır', () => {
    const display = netProfitDisplay(null, ['urun_maliyeti', 'kargo_gonderi'], 'eksik');
    expect(display).toEqual({ kind: 'uncomputable', missing: ['ürün maliyeti', 'kargo'] });
    expect(JSON.stringify(display)).not.toContain('0.00');
  });

  it('değer varsa değeri taşır', () => {
    expect(netProfitDisplay('12.30', [], 'kesin')).toEqual({ kind: 'value', value: '12.30' });
  });

  it('iptal ve satışsız ürün 0,00 değil iptal olarak gösterilir', () => {
    expect(netProfitDisplay('0.00', [], 'yok')).toEqual({ kind: 'cancelled' });
    expect(netProfitDisplay('0.00', [], 'iptal')).toEqual({ kind: 'cancelled' });
  });

  it('eksik kalem adları kanonik sırada', () => {
    expect(missingItemNames(['platform_hizmet_bedeli', 'urun_maliyeti'])).toEqual([
      'ürün maliyeti',
      'hizmet bedeli',
    ]);
  });
});

describe('summaryView', () => {
  it('kısmi olmayan dönemde dönem net kârı başlık rakamıdır', () => {
    const view = summaryView(makeTotals());
    expect(view.netProfit).toEqual({ kind: 'value', value: '3120.45' });
    expect(view.margin).toMatchObject({ kind: 'value', value: '16.9' });
    expect(view.fullLines).toBeNull();
    expect(view.banner).toBeNull();
  });

  it('kısmi dönemde dönem net kârı başlık olmaz (AO-03): hesaplanamadı ve eksik kalemler', () => {
    const view = summaryView(makeUnconfiguredTotals());
    expect(view.partial).toBe(true);
    expect(view.netProfit).toEqual({
      kind: 'uncomputable',
      missing: ['ürün maliyeti', 'kargo', 'hizmet bedeli'],
    });
    expect(JSON.stringify(view)).not.toContain('"0.00"');
  });

  it('tam satır sayısı 0 ise eksiksiz satırlar bloğu, marj ve toplam gider gösterilmez', () => {
    const view = summaryView(makeUnconfiguredTotals());
    expect(view.fullLines).toBeNull();
    expect(view.margin.kind).toBe('uncomputable');
    expect(view.totalExpenses.kind).toBe('uncomputable');
  });

  it('kısmi dönemde marj yalnız tam satırların marjıdır ve etiketlenir', () => {
    const base = makeTotals();
    const view = summaryView(
      makeTotals({
        net_kar_kismi: true,
        donem_net_kar: '-10.00',
        net_kar_marji_yuzde: '-5.45',
        eksik_kalem_satir_sayilari: {
          urun_maliyeti: 0,
          kargo_gonderi: 3,
          platform_hizmet_bedeli: 0,
        },
        tam_satirlar: {
          ...base.tam_satirlar,
          satir_sayisi: 7,
          net_kar: '210.00',
          net_kar_marji_yuzde: '14.2',
          toplam_gider: '900.00',
        },
      }),
    );
    expect(view.netProfit.kind).toBe('uncomputable');
    expect(view.margin).toEqual({
      kind: 'value',
      value: '14.2',
      label: 'Eksiksiz satırların marjı, dönem giderleri hariç',
    });
    expect(JSON.stringify(view)).not.toContain('-5.45');
    expect(view.fullLines).toEqual({ count: 7, netProfit: '210.00' });
    expect(view.totalExpenses).toMatchObject({ kind: 'value', value: '900.00' });
    expect(view.totalExpenses).toHaveProperty('scopeLabel', 'Yalnız eksiksiz satırların gideri');
  });

  it('dönem düzeyi giderler ayrı satırdır, sıfırsa gösterilmez', () => {
    expect(summaryView(makeTotals()).periodLevelExpenses).toBeNull();
    expect(
      summaryView(makeTotals({ donem_duzeyi_giderler_toplami: '125.00' })).periodLevelExpenses,
    ).toBe('125.00');
  });

  it('dönemde satır yoksa boş durum', () => {
    expect(summaryView(makeTotals({ satir_sayisi: 0, siparis_sayisi: 0 })).empty).toBe(true);
    expect(summaryView(makeTotals()).empty).toBe(false);
  });
});

describe('summaryBanner (kural 3)', () => {
  it('eksik kalem satır sayılarına bağlıdır, completeness alanına değil', () => {
    expect(
      summaryBanner({ urun_maliyeti: 0, kargo_gonderi: 0, platform_hizmet_bedeli: 0 }),
    ).toBeNull();
    // Yalnız ürün maliyeti eksikse kurulum bandı çıkmaz.
    expect(
      summaryBanner({ urun_maliyeti: 4, kargo_gonderi: 0, platform_hizmet_bedeli: 0 }),
    ).toBeNull();
  });

  it('ikisi de eksikse tam metni ve sayıları verir', () => {
    const banner = summaryBanner({
      urun_maliyeti: 1,
      kargo_gonderi: 5,
      platform_hizmet_bedeli: 3,
    });
    expect(banner?.title).toBe(
      'Kargo tarifesi ve hizmet bedeli girilmedi: net kâr bu kalemler hariç hesaplanamaz',
    );
    expect(banner?.detail).toBe(
      'Bu dönemde 5 satırda kargo, 3 satırda hizmet bedeli tahmini eksik.',
    );
    expect(banner?.costLine).toBe('1 satırın ürün maliyeti girilmedi.');
  });

  it('yalnız kargo eksikse yalnız kargoyu söyler', () => {
    const banner = summaryBanner({ urun_maliyeti: 0, kargo_gonderi: 2, platform_hizmet_bedeli: 0 });
    expect(banner?.title).toContain('Kargo tarifesi girilmedi');
    expect(banner?.detail).toBe('Bu dönemde 2 satırda kargo tahmini eksik.');
  });
});

describe('kesinlik ve kaynak rozetleri (kural 4)', () => {
  it('"Kesin" yalnız kesinlik alanından gelir', () => {
    expect(certaintyBadge('kesin')?.label).toBe('Kesin');
    expect(certaintyBadge('tahmini')?.label).toBe('Tahmini');
    expect(certaintyBadge('eksik')?.label).toBe('Eksik');
    expect(certaintyBadge('iptal')?.label).toBe('İptal');
    expect(certaintyBadge('yok')).toBeNull();
  });

  it('kaynak etiketleri kesin, tahmini ve eksik ayrıdır', () => {
    expect(sourceBadge('kesin').label).toBe('Kesin');
    expect(sourceBadge('dagitim_tahmini').label).toBe('Tahmini');
    expect(sourceBadge('eksik').label).toBe('Eksik');
  });
});

describe('lossBadge (kural 5)', () => {
  it('loss_reason üç değeri ayrı rozet alır', () => {
    expect(lossBadge(makeItem({ loss_reason: 'net_profit', net_profit: '-5.00' }))?.label).toBe(
      'Zarar',
    );
    expect(
      lossBadge(makeItem({ loss_reason: 'contribution_before_cost', net_profit: null }))?.label,
    ).toBe('Maliyetsiz bile zarar');
    expect(lossBadge(makeItem({ loss_reason: 'known_expenses', net_profit: null }))?.label).toBe(
      'Bilinen giderlerle bile zarar',
    );
  });

  it('net kârı null ve zararı kesin olmayan ürün belirsizdir, kârlı değildir', () => {
    const badge = lossBadge(
      makeItem({ net_profit: null, loss_reason: null, contribution_excl_missing: '75.00' }),
    );
    expect(badge?.label).toBe('Belirsiz');
  });

  it('kârlı ya da iptal ürün rozet almaz', () => {
    expect(lossBadge(makeItem())).toBeNull();
    expect(lossBadge(makeItem({ certainty: 'yok', net_profit: '0.00' }))).toBeNull();
  });
});

describe('refundPending (kural 6)', () => {
  it('net kâr ile askıdaki ürün maliyetini toplar', () => {
    const line = makeLine({
      uyarilar: ['IADE_KAYDI_BEKLENIYOR'],
      askidaki_urun_maliyeti: '50.00',
      kalemler: { ...makeLine().kalemler, net_kar: '-50.00' },
    });
    expect(refundPending(line)).toEqual({ estimate: '0.00', excludesMissing: false });
  });

  it('net kâr null ise eksik giderler hariç kâr üzerinden hesaplar ve bunu işaretler', () => {
    const line = makeLine({
      uyarilar: ['IADE_KAYDI_BEKLENIYOR'],
      askidaki_urun_maliyeti: '50.00',
      kalemler: { ...makeLine().kalemler, net_kar: null, eksik_giderler_haric_kar: '-20.00' },
    });
    expect(refundPending(line)).toEqual({ estimate: '30.00', excludesMissing: true });
  });

  it('uyarı yoksa null', () => {
    expect(refundPending(makeLine())).toBeNull();
  });
});

describe('expenseCell (kural 1)', () => {
  it('eksik kaynaklı kalem eksik yazar, 0,00 değil', () => {
    expect(expenseCell('0.00', 'eksik')).toEqual({ kind: 'missing' });
    expect(expenseCell(null, 'kullanici')).toEqual({ kind: 'missing' });
    expect(expenseCell('45.00', 'kesin')).toEqual({ kind: 'value', value: '45.00' });
  });
});

describe('defaultDesiHint (kural 7)', () => {
  const comparison = {
    komisyon_tahmini: '10.00',
    komisyon_kesin: '10.00',
    kargo_gonderi_tahmini: '50.00',
    kargo_gonderi_kesin: '125.00',
    platform_hizmet_bedeli_tahmini: '8.00',
    platform_hizmet_bedeli_kesin: '8.00',
    kargo_tahmini_varsayilan_desi: true,
    karsilastirilan_tahmini_toplam: '68.00',
    karsilastirilan_kesin_toplam: '143.00',
    fark: '75.00',
    esik: '5.00',
  };

  it('varsayılan desi ve baskın kargo farkında ipucu verir', () => {
    expect(defaultDesiHint(comparison)).toContain('varsayılan desi');
  });

  it('varsayılan desi değilse ipucu vermez', () => {
    expect(defaultDesiHint({ ...comparison, kargo_tahmini_varsayilan_desi: false })).toBeNull();
  });

  it('fark kargodan değil komisyondan geliyorsa ipucu vermez', () => {
    expect(
      defaultDesiHint({ ...comparison, komisyon_kesin: '200.00', kargo_gonderi_kesin: '52.00' }),
    ).toBeNull();
  });
});

describe('sorgu parametreleri', () => {
  it('geçersiz değer varsayılana düşer', () => {
    expect(parseRange('90d')).toBe(DEFAULT_RANGE);
    expect(parseRange('today')).toBe('today');
    const q = parseProductQuery(new URLSearchParams('range=7d&sort=hack&order=up&filter=loss'));
    expect(q).toEqual({ range: '7d', sort: 'net_profit', order: 'desc', filter: 'loss' });
  });

  it('dönem her zaman, sıralama ve süzgeç yalnız varsayılandan farklıysa yazılır', () => {
    expect(
      productQueryString({ range: '30d', sort: 'net_profit', order: 'desc', filter: 'all' }),
    ).toBe('range=30d');
    expect(
      productQueryString({ range: '7d', sort: 'sales', order: 'asc', filter: 'missing_cost' }),
    ).toBe('range=7d&sort=sales&order=asc&filter=missing_cost');
  });

  it('dönem etiketi', () => {
    expect(periodLabel('2026-11-01', '2026-11-07')).toBe('01.11.2026 - 07.11.2026');
    expect(periodLabel('2026-11-10', '2026-11-10')).toBe('10.11.2026');
  });
});
