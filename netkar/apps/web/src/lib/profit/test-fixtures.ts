// Test ve e2e için rapor API örnek yanıtları (alan adları services/api profit_schemas.py ile aynı).
// Üretim kodunda kullanılmaz. Yalnız tür içe aktarımı yapılır: Playwright de bu dosyayı doğrudan yükler.
import type {
  AlertCount,
  MarketplaceAccount,
  PeriodTotals,
  ProductProfitDetail,
  ProductProfitItem,
  ProductProfitList,
  ProfitAlerts,
  ProfitLine,
  ProfitSummary,
} from '../api/profit';

export const ACCOUNT_ID = '11111111-1111-4111-8111-111111111111';

export const PERIOD = { start: '2026-10-12', end: '2026-11-10', days: 30 };

export function makeAccounts(): MarketplaceAccount[] {
  return [{ id: ACCOUNT_ID, platform: 'trendyol', seller_id: '123456', status: 'active' }];
}

export function makeTotals(over: Partial<PeriodTotals> = {}): PeriodTotals {
  return {
    siparis_sayisi: 42,
    satir_sayisi: 50,
    net_satis_kdv_haric: '18450.00',
    donem_duzeyi_giderler_toplami: '0.00',
    donem_net_kar: '3120.45',
    net_kar_kismi: false,
    maliyet_eksik_satir_sayisi: 0,
    eksik_kalem_satir_sayilari: { urun_maliyeti: 0, kargo_gonderi: 0, platform_hizmet_bedeli: 0 },
    net_kar_marji_yuzde: '16.9',
    tam_satirlar: {
      satir_sayisi: 50,
      net_satis_kdv_haric: '18450.00',
      urun_maliyeti: '9000.00',
      komisyon: '2600.00',
      kargo_gonderi: '2100.00',
      kargo_iade: '0.00',
      platform_hizmet_bedeli: '500.00',
      ceza: '0.00',
      reklam: '1129.55',
      degisken_giderler: '0.00',
      toplam_gider: '15329.55',
      net_kar: '3120.45',
      net_kar_marji_yuzde: '16.9',
    },
    kesinlik: 'tahmini',
    kesinlik_satir_sayilari: { kesin: 30, tahmini: 20, eksik: 0 },
    uyarilar: [],
    ...over,
  };
}

/** Kargo ve hizmet bedeli girilmemiş, kısmi dönem (net kâr_kismi = true, tam satır yok) */
export function makeUnconfiguredTotals(over: Partial<PeriodTotals> = {}): PeriodTotals {
  return makeTotals({
    siparis_sayisi: 10,
    satir_sayisi: 12,
    net_satis_kdv_haric: '4200.00',
    // Başlık rakamı OLMAMALI: API'nin döndürdüğü sayı yalnız alt kümeden gelir ve 0,00 görünür.
    donem_net_kar: '0.00',
    net_kar_kismi: true,
    maliyet_eksik_satir_sayisi: 2,
    eksik_kalem_satir_sayilari: { urun_maliyeti: 2, kargo_gonderi: 12, platform_hizmet_bedeli: 12 },
    net_kar_marji_yuzde: null,
    tam_satirlar: {
      satir_sayisi: 0,
      net_satis_kdv_haric: '0.00',
      urun_maliyeti: '0.00',
      komisyon: '0.00',
      kargo_gonderi: '0.00',
      kargo_iade: '0.00',
      platform_hizmet_bedeli: '0.00',
      ceza: '0.00',
      reklam: '0.00',
      degisken_giderler: '0.00',
      toplam_gider: '0.00',
      net_kar: '0.00',
      net_kar_marji_yuzde: null,
    },
    kesinlik: 'eksik',
    kesinlik_satir_sayilari: { kesin: 0, tahmini: 0, eksik: 12 },
    uyarilar: ['KARGO_EKSIK_SATIRLAR_VAR'],
    ...over,
  });
}

export function makeSummary(totals: PeriodTotals = makeTotals()): ProfitSummary {
  return {
    period: PERIOD,
    totals,
    status_counts: { estimated: 20, settled: 24, adjusted: 4, cancelled: 2 },
    missing_cost_line_count: totals.maliyet_eksik_satir_sayisi,
  };
}

export function makeAlerts(counts: AlertCount[] = []): ProfitAlerts {
  return {
    period: PERIOD,
    counts,
    total_count: counts.reduce((sum, c) => sum + c.count, 0),
    next_cursor: null,
  };
}

export const SAMPLE_ALERT_COUNTS: AlertCount[] = [
  { code: 'ZARAR', count: 3, message: 'Zararına satış: satırın net kârı sıfırın altında.' },
  { code: 'MALIYET_EKSIK', count: 2, message: 'Ürün maliyeti girilmemiş; net kâr hesaplanamıyor.' },
];

export function makeItem(over: Partial<ProductProfitItem> = {}): ProductProfitItem {
  return {
    barcode: 'BRK-0001',
    title: 'Örnek Ürün Çelik Termos 500 ml',
    line_count: 8,
    quantity: 10,
    refunded_quantity: 0,
    net_sales_excl_vat: '1250.00',
    product_cost: '600.00',
    total_expenses: '1000.00',
    net_profit: '250.00',
    net_margin_percent: '20.0',
    cost_missing: false,
    certainty: 'kesin',
    missing_items: [],
    contribution_excl_missing: '250.00',
    loss_reason: null,
    shipping_missing: false,
    ...over,
  };
}

export function makeList(
  items: ProductProfitItem[],
  over: Partial<ProductProfitList> = {},
): ProductProfitList {
  return {
    period: PERIOD,
    sort: 'net_profit',
    order: 'desc',
    filter: 'all',
    total_count: items.length,
    items,
    next_cursor: null,
    ...over,
  };
}

export function makeLine(over: Partial<ProfitLine> = {}): ProfitLine {
  return {
    orderNumber: '10001',
    shipmentPackageId: 5001,
    lineId: 9001,
    barcode: 'BRK-0001',
    durum: 'settled',
    adet: 2,
    adet_iade: 0,
    iade_kaydi_bekleyen_adet: 0,
    askidaki_urun_maliyeti: null,
    kesinlik: 'kesin',
    eksik_kalemler: [],
    kalemler: {
      net_satis_kdv_haric: '250.00',
      urun_maliyeti: '120.00',
      komisyon: '37.50',
      kargo_gonderi: '45.00',
      kargo_iade: '0.00',
      platform_hizmet_bedeli: '8.33',
      ceza: '0.00',
      reklam: '0.00',
      degisken_giderler: '0.00',
      toplam_gider: '210.83',
      eksik_giderler_haric_kar: '39.17',
      net_kar: '39.17',
      net_kar_marji_yuzde: '15.7',
    },
    kaynaklar: {
      satis: 'kesin',
      komisyon: 'kesin',
      urun_maliyeti: 'kullanici',
      kargo_gonderi: 'kesin',
      kargo_iade: 'yok',
      platform_hizmet_bedeli: 'kesin',
      ceza: 'yok',
      degisken_giderler: 'yok',
      reklam: 'yok',
    },
    karsilastirma: null,
    uyarilar: [],
    ...over,
  };
}

export function makeDetail(
  lines: ProfitLine[],
  over: Partial<ProductProfitDetail> = {},
): ProductProfitDetail {
  return {
    period: PERIOD,
    barcode: 'BRK-0001',
    title: 'Örnek Ürün Çelik Termos 500 ml',
    product: {
      barcode: 'BRK-0001',
      satir_sayisi: lines.length,
      adet: 10,
      adet_iade: 0,
      net_satis_kdv_haric: '1250.00',
      urun_maliyeti: '600.00',
      komisyon: '187.50',
      kargo_gonderi: '225.00',
      kargo_iade: '0.00',
      platform_hizmet_bedeli: '41.65',
      ceza: '0.00',
      degisken_giderler: '0.00',
      maliyet_haric_katki: '795.85',
      eksik_giderler_haric_kar: '195.85',
      net_kar: '195.85',
      net_kar_marji_yuzde: '15.7',
      maliyet_eksik: false,
      eksik_kalem_satir_sayilari: { urun_maliyeti: 0, kargo_gonderi: 0, platform_hizmet_bedeli: 0 },
      kesinlik: 'kesin',
    },
    certainty: 'kesin',
    comparison: {
      compared_line_count: 0,
      estimated_total: '0.00',
      actual_total: '0.00',
      difference: '0.00',
    },
    total_lines: lines.length,
    lines,
    next_cursor: null,
    ...over,
  };
}
