import { describe, expect, it } from 'vitest';

import {
  addDecimal,
  absAtLeast,
  absDecimal,
  compareDecimal,
  decimalSign,
  subtractDecimal,
} from '@/lib/profit/decimal-math';
import {
  certaintyBadge,
  defaultDesiHint,
  expenseCell,
  joinNames,
  compareCodePoints,
  knownProfitView,
  lossBadge,
  lossDisplay,
  missingItemNames,
  netProfitDisplay,
  partialPeriodNote,
  periodLabel,
  productBreakdownRows,
  refundPending,
  settingsRevisionLabel,
  shownAsCancelled,
  sourceBadge,
  summaryBanner,
  summaryView,
  topLossItems,
} from '@/lib/profit/present';
import {
  DEFAULT_RANGE,
  defaultOrderFor,
  parseProductQuery,
  parseRange,
  productQueryString,
} from '@/lib/profit/query';
import {
  makeDetail,
  makeItem,
  makeLine,
  makePartialTotals,
  makeTotals,
  makeUnconfiguredTotals,
} from '@/lib/profit/test-fixtures';

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
    expect(compareDecimal('-30.00', '-4.5')).toBe(-1);
    expect(compareDecimal('2', '2.00')).toBe(0);
    expect(compareDecimal('0.10', '-0.10')).toBe(1);
    expect(absDecimal('-4.00')).toBe('4.00');
    expect(absDecimal('0.50')).toBe('0.50');
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

  it('G49: tam satır sayısı 0 ise eksiksiz satırlar bloğu, marj ve toplam gider kartı yoktur', () => {
    const view = summaryView(makeUnconfiguredTotals());
    expect(view.state).toBe('partial_no_full_lines');
    expect(view.fullLines).toBeNull();
    expect(view.margin).toBeNull();
    expect(view.totalExpenses).toBeNull();
  });

  it('UX-01 durum A: tam dönemde başlık dönem net kârı ve marj; bilinen kâr ayrı gösterilmez', () => {
    const view = summaryView(makeTotals());
    expect(view.state).toBe('full');
    expect(view.netProfitLabel).toBe('Dönem net kârı');
    expect(view.knownProfit).toBeNull();
    expect(view.totalExpenses).toMatchObject({ kind: 'value', value: '15329.55' });
  });

  it('UX-01 durum B: kısmi dönem, eksiksiz satır var: hesaplanamadı, bilinen kâr nötr, eksiksiz blok', () => {
    const view = summaryView(makePartialTotals());
    expect(view.state).toBe('partial');
    expect(view.netProfitLabel).toBe('Dönem net kârı hesaplanamadı');
    expect(view.netProfit).toEqual({ kind: 'uncomputable', missing: ['kargo'] });
    expect(view.knownProfit).toMatchObject({
      label: 'Eksik giderler hariç dönem kârı',
      scope: '(kargo hariç)',
      value: '1240.00',
      loss: false,
      badge: null,
      note: 'Kargo düşülünce bu rakam azalır.',
    });
    // Etiket "net kâr" demez (ADR §5.2 madde 3)
    expect(view.knownProfit?.label.toLowerCase()).not.toContain('net kâr');
    expect(view.fullLines).toEqual({ count: 20, netProfit: '800.00' });
    expect(view.margin).toMatchObject({ kind: 'value', value: '12.5' });
    expect(view.totalExpenses).toMatchObject({ kind: 'value', value: '5600.00' });
  });

  it('UX-01 durum C: kısmi, eksiksiz satır yok, bilinen kâr negatif: kırmızı vurgu ve zarar rozeti', () => {
    const view = summaryView(makeUnconfiguredTotals());
    expect(view.netProfitLabel).toBe('Dönem net kârı hesaplanamadı');
    expect(view.knownProfit).toMatchObject({
      value: '-17.35',
      scope: '(ürün maliyeti, kargo ve hizmet bedeli hariç)',
      loss: true,
      badge: { label: 'Bilinen giderlerle bile zarar', tone: 'loss' },
      note: 'Ürün maliyeti, kargo ve hizmet bedeli düşülünce bu rakam azalır.',
    });
    expect(view.costLine).toBe('2 satırın ürün maliyeti girilmedi.');
  });

  it('null donem_net_kar bayrak yanlış olsa da asla değer olmaz, 0,00 uydurulmaz', () => {
    const view = summaryView(makeTotals({ donem_net_kar: null, net_kar_kismi: false }));
    expect(view.partial).toBe(true);
    expect(view.netProfit.kind).toBe('uncomputable');
    expect(JSON.stringify(view.netProfit)).not.toContain('0.00');
  });

  it('kısmi dönemde donem_net_kar dolu gelse bile başlık olmaz', () => {
    const view = summaryView(makeTotals({ net_kar_kismi: true, donem_net_kar: '0.00' }));
    expect(view.netProfit.kind).toBe('uncomputable');
  });

  it('eski API: donem_eksik_giderler_haric_kar alanı yoksa bilinen kâr bloğu yok, sayı uydurulmaz', () => {
    const totals = makeUnconfiguredTotals();
    delete totals.donem_eksik_giderler_haric_kar;
    const view = summaryView(totals);
    expect(view.knownProfit).toBeNull();
    expect(view.netProfit.kind).toBe('uncomputable');
    expect(JSON.stringify(view)).not.toContain('"0.00"');
  });

  it('pozitif bilinen kâr yeşil ve zarar rozeti taşımaz (UX-21)', () => {
    const view = knownProfitView('50.00', ['kargo', 'hizmet bedeli'], 'donem');
    expect(view.loss).toBe(false);
    expect(view.badge).toBeNull();
    expect(view.note).toBe('Kargo ve hizmet bedeli düşülünce bu rakam azalır.');
    expect(knownProfitView('0.00', [], 'urun').note).toBe(
      'Eksik giderler düşülünce bu rakam azalır.',
    );
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
    // Y-2: ayar formu yokken başlık durumu söyler, "girin" demez
    expect(banner?.title).toBe('Net kâr için kargo tarifesi ve hizmet bedeli gerekiyor');
    expect(banner?.body).toBe('Kargo tarifesi ve hizmet bedeli girişi çok yakında.');
    expect(banner?.detail).toBe(
      'Bu dönemde 5 satırda kargo, 3 satırda hizmet bedeli tahmini eksik.',
    );
    expect(banner?.costLine).toBe('1 satırın ürün maliyeti girilmedi.');
  });

  it('yalnız kargo eksikse yalnız kargoyu söyler', () => {
    const banner = summaryBanner({ urun_maliyeti: 0, kargo_gonderi: 2, platform_hizmet_bedeli: 0 });
    expect(banner?.title).toBe('Net kâr için kargo tarifesi gerekiyor');
    expect(banner?.body).toBe('Kargo tarifesi girişi çok yakında.');
    expect(banner?.detail).toBe('Bu dönemde 2 satırda kargo tahmini eksik.');
  });

  it('yalnız hizmet bedeli eksikse yalnız onu söyler', () => {
    const banner = summaryBanner({ urun_maliyeti: 0, kargo_gonderi: 0, platform_hizmet_bedeli: 6 });
    expect(banner?.title).toBe('Net kâr için hizmet bedeli gerekiyor');
    expect(banner?.body).toBe('Hizmet bedeli girişi çok yakında.');
  });

  it('"bu rakamlar bilinen giderlerle hesaplanıyor" yalnız bilinen kâr rakamı varken basılır', () => {
    const counts = { urun_maliyeti: 0, kargo_gonderi: 2, platform_hizmet_bedeli: 0 };
    expect(summaryBanner(counts, true)?.body).toBe(
      'Kargo tarifesi girişi çok yakında. Bu rakamlar bilinen giderlerle hesaplanıyor.',
    );
    expect(summaryBanner(counts, false)?.body).not.toContain('bilinen giderlerle');
    // summaryView: eski API'de alan yoksa cümle yoktur; alan varsa vardır
    const legacy = makeUnconfiguredTotals();
    delete legacy.donem_eksik_giderler_haric_kar;
    expect(summaryView(legacy).banner?.body).not.toContain('bilinen giderlerle');
    expect(summaryView(makeUnconfiguredTotals()).banner?.body).toContain('bilinen giderlerle');
  });
});

describe('partialPeriodNote (Y-9)', () => {
  it('nedeni eksik kalem adlarından kurar, hep kargo ve hizmet bedeli demez', () => {
    expect(partialPeriodNote(['kargo'])).toBe(
      'Kargo eksik olduğundan bazı ürünlerin kârı belirsiz olabilir.',
    );
    expect(partialPeriodNote(['ürün maliyeti', 'hizmet bedeli'])).toBe(
      'Ürün maliyeti ve hizmet bedeli eksik olduğundan bazı ürünlerin kârı belirsiz olabilir.',
    );
    expect(partialPeriodNote([])).toBeNull();
    expect(summaryView(makePartialTotals()).partialNote).toBe(
      'Kargo eksik olduğundan bazı ürünlerin kârı belirsiz olabilir.',
    );
    expect(summaryView(makeTotals()).partialNote).toBeNull();
  });
});

describe('kesinlik ve kaynak rozetleri (kural 4)', () => {
  it('"Kesin" yalnız kesinlik alanından gelir', () => {
    expect(certaintyBadge('kesin')?.label).toBe('Kesin');
    expect(certaintyBadge('tahmini')?.label).toBe('Tahmini');
    // UX-10: eksik veri zarar değildir, zarar kırmızısı (loss) kullanılmaz
    expect(certaintyBadge('eksik')).toEqual({ label: 'Bilgi eksik', tone: 'warning' });
    expect(certaintyBadge('iptal')?.label).toBe('İptal');
    expect(certaintyBadge('yok')).toBeNull();
  });

  it('kaynak etiketleri kesin, tahmini ve eksik ayrıdır', () => {
    expect(sourceBadge('kesin').label).toBe('Kesin');
    expect(sourceBadge('dagitim_tahmini').label).toBe('Tahmini');
    expect(sourceBadge('eksik')).toEqual({ label: 'Eksik', tone: 'warning' });
  });
});

describe('lossBadge (kural 5)', () => {
  it('loss_reason üç değeri ayrı rozet alır', () => {
    expect(lossBadge(makeItem({ loss_reason: 'net_profit', net_profit: '-5.00' }))?.label).toBe(
      'Zarar',
    );
    expect(
      lossBadge(makeItem({ loss_reason: 'contribution_before_cost', net_profit: null }))?.label,
    ).toBe('Maliyet girilmese de zarar');
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
    // Geçersiz yön, süzgecin varsayılan yönüne düşer: zarar süzgecinde en çok zarar önce (UX-04)
    expect(q).toEqual({ range: '7d', sort: 'net_profit', order: 'asc', filter: 'loss' });
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

describe('zarar süzgeci yönü (UX-04)', () => {
  it('zarar süzgecinde varsayılan yön artan (en çok zarar önce), diğerlerinde azalan', () => {
    expect(defaultOrderFor('loss')).toBe('asc');
    expect(defaultOrderFor('all')).toBe('desc');
    expect(defaultOrderFor('missing_cost')).toBe('desc');
    expect(parseProductQuery(new URLSearchParams('filter=loss')).order).toBe('asc');
    expect(parseProductQuery(new URLSearchParams('filter=loss&order=desc')).order).toBe('desc');
    expect(parseProductQuery(new URLSearchParams('order=asc')).order).toBe('asc');
  });

  it('yön yalnız süzgecin varsayılanından farklıysa yazılır', () => {
    expect(
      productQueryString({ range: '30d', sort: 'net_profit', order: 'asc', filter: 'loss' }),
    ).toBe('range=30d&filter=loss');
    expect(
      productQueryString({ range: '30d', sort: 'net_profit', order: 'desc', filter: 'loss' }),
    ).toBe('range=30d&order=desc&filter=loss');
  });
});

describe('lossDisplay ve topLossItems (UX-03, UX-04, UX-07, AD-04)', () => {
  const certainLoss = (barcode: string, net: string) =>
    makeItem({ barcode, net_profit: net, loss_reason: 'net_profit', certainty: 'tahmini' });
  const knownLoss = (barcode: string, known: string) =>
    makeItem({
      barcode,
      net_profit: null,
      net_margin_percent: null,
      loss_reason: 'known_expenses',
      missing_items: ['kargo_gonderi', 'platform_hizmet_bedeli'],
      contribution_excl_missing: known,
      certainty: 'eksik',
    });

  it('net kârı null olan kesin zarar nötr değil: en az zarar ve eksik kalem notu', () => {
    expect(lossDisplay(knownLoss('A', '-4.00'))).toEqual({
      magnitude: '4.00',
      amount: '-4.00',
      exact: false,
      note: 'Kargo ve hizmet bedeli düşülünce bu rakam azalır.',
    });
  });

  it('kesin zararda tutar net kârdır; kârlı, belirsiz ve iptal ürün zarar göstermez', () => {
    expect(lossDisplay(certainLoss('A', '-30.00'))).toEqual({
      magnitude: '30.00',
      amount: '-30.00',
      exact: true,
      note: null,
    });
    expect(lossDisplay(makeItem())).toBeNull();
    expect(
      lossDisplay(makeItem({ net_profit: null, loss_reason: null, certainty: 'eksik' })),
    ).toBeNull();
    expect(
      lossDisplay(makeItem({ certainty: 'yok', net_profit: '0.00', loss_reason: 'net_profit' })),
    ).toBeNull();
  });

  // Y-3: aktif satırı olmayıp yalnız satışsız reklamı olan ürün backend'de kesinlik `yok`, negatif net kâr ve
  // `loss_reason = net_profit` alır (aggregate.py); zarardır, iptal değildir.
  const adOnlyLoss = () =>
    makeItem({
      barcode: 'R1',
      net_profit: '-25.00',
      net_margin_percent: null,
      loss_reason: 'net_profit',
      certainty: 'yok',
      contribution_excl_missing: '-25.00',
    });

  it('Y-3: kesinlik yok iken net kâr negatif ve zarar nedeni doluysa zarar gösterilir, İptal yazılmaz', () => {
    const item = adOnlyLoss();
    expect(
      netProfitDisplay(item.net_profit, item.missing_items, item.certainty, item.loss_reason),
    ).toEqual({
      kind: 'value',
      value: '-25.00',
    });
    expect(lossBadge(item)).toEqual({ label: 'Zarar', tone: 'loss' });
    expect(lossDisplay(item)).toEqual({
      magnitude: '25.00',
      amount: '-25.00',
      exact: true,
      note: null,
    });
    expect(topLossItems([item], 3).map((row) => row.item.barcode)).toEqual(['R1']);
    expect(shownAsCancelled('yok', '-25.00', 'net_profit')).toBe(false);
  });

  it('Y-3: İptal yalnız iptal satırlı ve zararsız ürün için; zarar nedeni yoksa negatif sayı da iptal sayılır', () => {
    expect(shownAsCancelled('yok', '0.00', null)).toBe(true);
    expect(shownAsCancelled('iptal', null, null)).toBe(true);
    expect(shownAsCancelled('iptal', '0.00', 'net_profit')).toBe(true);
    expect(shownAsCancelled('yok', '-5.00', null)).toBe(true);
    // Ürün kırılımında zarar nedeni alanı yoktur: negatif net kâr yeterlidir
    expect(shownAsCancelled('yok', '-5.00')).toBe(false);
    expect(shownAsCancelled('kesin', '0.00')).toBe(false);
    expect(netProfitDisplay('0.00', [], 'iptal', null)).toEqual({ kind: 'cancelled' });
    expect(
      lossBadge(makeItem({ certainty: 'iptal', net_profit: '0.00', loss_reason: null })),
    ).toBeNull();
  });

  it('en büyük zarar üstte; net kârı null kesin zarar API sırasında sonda olsa da kaybolmaz', () => {
    // API asc sırası: değerli zararlar önde, null net kârlı kesin zarar sonda
    const apiOrder = [
      certainLoss('B', '-30.00'),
      certainLoss('C', '-5.00'),
      knownLoss('D', '-500.00'),
      knownLoss('E', '-4.00'),
    ];
    const top = topLossItems(apiOrder, 3);
    expect(top.map((row) => row.item.barcode)).toEqual(['D', 'B', 'C']);
    expect(top[0]?.loss.exact).toBe(false);
  });

  it('eşit zararda barkoda göre kararlı sıralar ve sınırı uygular', () => {
    const rows = topLossItems([certainLoss('Z', '-1.00'), certainLoss('A', '-1.00')], 1);
    expect(rows.map((row) => row.item.barcode)).toEqual(['A']);
    expect(topLossItems([], 3)).toEqual([]);
  });

  it('eşitlikte barkod kod noktasına göre sıralanır, localeCompare gibi büyük küçük harf yok saymaz', () => {
    // Kod noktası: "B" (66) < "a" (97); localeCompare ("a" < "B") bunun tersini verirdi
    const rows = topLossItems(
      [certainLoss('a1', '-1.00'), certainLoss('B1', '-1.00'), certainLoss('B', '-1.00')],
      3,
    );
    expect(rows.map((row) => row.item.barcode)).toEqual(['B', 'B1', 'a1']);
    expect(compareCodePoints('B', 'a')).toBe(-1);
    expect(compareCodePoints('a', 'a')).toBe(0);
    expect(compareCodePoints('ab', 'a')).toBe(1);
    // BMP dışı karakter (vekil çift) kod noktası olarak kıyaslanır: U+1F600 > U+FF5E
    expect(compareCodePoints('\u{1F600}', '\uFF5E')).toBe(1);
  });
});

describe('productBreakdownRows (UX-09)', () => {
  function rowsOf(over: Record<string, string> = {}) {
    const product = { ...makeDetail([makeLine()]).product!, ...over };
    return productBreakdownRows(product);
  }

  it('sıfır olan isteğe bağlı kalemler gizlenir', () => {
    expect(rowsOf().map((row) => row.key)).toEqual([
      'satis',
      'maliyet',
      'komisyon',
      'kargo',
      'hizmet',
    ]);
  });

  it('kargo iadesi, ceza, değişken gider ve reklam sıfırdan farklıysa satır olur', () => {
    const rows = rowsOf({
      kargo_iade: '12.00',
      ceza: '5.00',
      degisken_giderler: '3.50',
      reklam_satirlara_dagitilan: '20.00',
      reklam_satissiz: '4.00',
    });
    expect(rows.map((row) => row.key)).toEqual([
      'satis',
      'maliyet',
      'komisyon',
      'kargo',
      'kargo_iade',
      'hizmet',
      'ceza',
      'degisken',
      'reklam',
      'reklam_satissiz',
    ]);
  });

  it('satırlar toplamla tutar: net satış eksi giderler = fikstürün net_kar alanı', () => {
    // Backend formülü (aggregate.py): ürün net kârı = Σ satır net kârı - satışsız reklam.
    // Satır net kârı = net satış - maliyet - komisyon - kargo - kargo iadesi - hizmet bedeli - ceza - değişken - dağıtılan reklam.
    const lineNetProfits = ['120.00', '130.00']; // Σ = 250.00
    const lineSum = lineNetProfits.reduce((sum, v) => addDecimal(sum, v), '0.00');
    const product = {
      ...makeDetail([makeLine()]).product!,
      net_satis_kdv_haric: '1000.00',
      urun_maliyeti: '400.00',
      komisyon: '150.00',
      kargo_gonderi: '100.00',
      kargo_iade: '20.00',
      platform_hizmet_bedeli: '30.00',
      ceza: '10.00',
      degisken_giderler: '15.00',
      reklam_satirlara_dagitilan: '25.00',
      reklam_satissiz: '10.00',
      net_kar: subtractDecimal(lineSum, '10.00'),
    };
    const rows = productBreakdownRows(product);
    let net = '0.00';
    for (const row of rows) {
      if (row.cell.kind !== 'value') throw new Error('değer bekleniyordu');
      net =
        row.key === 'satis'
          ? addDecimal(net, row.cell.value)
          : subtractDecimal(net, row.cell.value);
    }
    expect(product.net_kar).toBe('240.00');
    expect(net).toBe(product.net_kar);
  });

  it('etiketler: Reklam ve Satış getirmeyen reklam', () => {
    const labels = rowsOf({ reklam_satirlara_dagitilan: '5.00', reklam_satissiz: '4.00' }).map(
      (row) => row.label,
    );
    expect(labels).toContain('Reklam');
    expect(labels).toContain('Satış getirmeyen reklam');
    expect(labels.join('|')).not.toContain('satırlara dağıtılan');
    expect(labels.join('|')).not.toContain('(satışsız)');
  });

  it('eksik kalem sayısı olan kalem değer değil eksik gösterir, ürün maliyeti null ise eksik', () => {
    const rows = rowsOf({ urun_maliyeti: '0.00' });
    expect(rows.find((r) => r.key === 'maliyet')?.cell).toEqual({ kind: 'value', value: '0.00' });
    const product = {
      ...makeDetail([makeLine()]).product!,
      urun_maliyeti: null,
      eksik_kalem_satir_sayilari: { urun_maliyeti: 2, kargo_gonderi: 3, platform_hizmet_bedeli: 0 },
    };
    const missing = productBreakdownRows(product);
    expect(missing.find((r) => r.key === 'maliyet')?.cell).toEqual({ kind: 'missing' });
    // Y-6: kısmen eksik kalem bilinen tutarı da taşır
    expect(missing.find((r) => r.key === 'kargo')?.cell).toEqual({
      kind: 'partial',
      value: '225.00',
      count: 3,
    });
  });
});

describe('ayar sürümü ve metin yardımcıları', () => {
  it('ayar sürümü etiketi; alan yoksa (eski API) null', () => {
    expect(settingsRevisionLabel(7)).toBe('Ayar sürümü 7');
    expect(settingsRevisionLabel(0)).toBe('Ayar sürümü 0');
    expect(settingsRevisionLabel(undefined)).toBeNull();
    expect(settingsRevisionLabel(null)).toBeNull();
    expect(settingsRevisionLabel(1.5)).toBeNull();
  });

  it('joinNames', () => {
    expect(joinNames([])).toBe('');
    expect(joinNames(['kargo'])).toBe('kargo');
    expect(joinNames(['kargo', 'hizmet bedeli'])).toBe('kargo ve hizmet bedeli');
    expect(joinNames(['a', 'b', 'c'])).toBe('a, b ve c');
  });
});
