// Backend sözleşmesi: services/api/app/api/v1/profit.py ve profit_schemas.py.
// Motor blokları KABLO adlarıyla (Türkçe) gelir; uç noktanın zarfı İngilizce snake_case'tir.
// Para ve oran alanları kuruş hassasiyetli Decimal DİZGESİDİR ("12.50"); float'a çevrilmez.
import { apiFetch } from '@/lib/api/client';

export type Money = string;

export type CertaintyLabel = 'kesin' | 'tahmini' | 'eksik' | 'iptal' | 'yok';
export type MissingItemCode = 'urun_maliyeti' | 'kargo_gonderi' | 'platform_hizmet_bedeli';
export type SourceCode =
  | 'kesin'
  | 'kesin_dagitim'
  | 'tahmini'
  | 'kullanici'
  | 'eslesen'
  | 'dagitim_tahmini'
  | 'eksik'
  | 'yok';
export type LineStatus = 'estimated' | 'settled' | 'adjusted' | 'cancelled';
export type LossReason = 'net_profit' | 'contribution_before_cost' | 'known_expenses';
export type StatementBasis = 'estimated' | 'settled' | 'mixed' | 'none';

export type RangeName = 'today' | '7d' | '30d';
export type ProductSort = 'net_profit' | 'net_margin' | 'sales' | 'units';
export type SortOrder = 'asc' | 'desc';
export type ProductFilter = 'all' | 'loss' | 'missing_cost';

export interface MarketplaceAccount {
  id: string;
  platform: string;
  seller_id: string;
  status: string;
}

export interface ReportPeriod {
  start: string;
  end: string;
  days: number;
}

export interface MissingLineCounts {
  urun_maliyeti: number;
  kargo_gonderi: number;
  platform_hizmet_bedeli: number;
}

export interface CertaintyLineCounts {
  kesin: number;
  tahmini: number;
  eksik: number;
}

export interface FullLinesTotals {
  satir_sayisi: number;
  net_satis_kdv_haric: Money;
  urun_maliyeti: Money;
  komisyon: Money;
  kargo_gonderi: Money;
  kargo_iade: Money;
  platform_hizmet_bedeli: Money;
  ceza: Money;
  reklam: Money;
  degisken_giderler: Money;
  toplam_gider: Money;
  net_kar: Money;
  net_kar_marji_yuzde: Money | null;
}

export interface PeriodTotals {
  siparis_sayisi: number;
  satir_sayisi: number;
  net_satis_kdv_haric: Money;
  donem_duzeyi_giderler_toplami: Money;
  donem_net_kar: Money;
  net_kar_kismi: boolean;
  maliyet_eksik_satir_sayisi: number;
  eksik_kalem_satir_sayilari: MissingLineCounts;
  net_kar_marji_yuzde: Money | null;
  tam_satirlar: FullLinesTotals;
  kesinlik: CertaintyLabel;
  kesinlik_satir_sayilari: CertaintyLineCounts;
  uyarilar: string[];
}

export interface StatusCounts {
  estimated: number;
  settled: number;
  adjusted: number;
  cancelled: number;
}

export interface ProfitSummary {
  period: ReportPeriod;
  totals: PeriodTotals;
  status_counts: StatusCounts;
  missing_cost_line_count: number;
}

export interface ProductProfitItem {
  barcode: string;
  title: string | null;
  line_count: number;
  quantity: number;
  refunded_quantity: number;
  net_sales_excl_vat: Money;
  product_cost: Money | null;
  total_expenses: Money | null;
  net_profit: Money | null;
  net_margin_percent: Money | null;
  cost_missing: boolean;
  certainty: CertaintyLabel;
  missing_items: MissingItemCode[];
  contribution_excl_missing: Money;
  loss_reason: LossReason | null;
  shipping_missing: boolean;
}

export interface ProductProfitList {
  period: ReportPeriod;
  sort: string;
  order: string;
  filter: string;
  total_count: number;
  items: ProductProfitItem[];
  next_cursor: string | null;
}

export interface ProductTotals {
  barcode: string;
  satir_sayisi: number;
  adet: number;
  adet_iade: number;
  net_satis_kdv_haric: Money;
  urun_maliyeti: Money | null;
  komisyon: Money;
  kargo_gonderi: Money;
  kargo_iade: Money;
  platform_hizmet_bedeli: Money;
  ceza: Money;
  degisken_giderler: Money;
  maliyet_haric_katki: Money;
  eksik_giderler_haric_kar: Money;
  net_kar: Money | null;
  net_kar_marji_yuzde: Money | null;
  maliyet_eksik: boolean;
  eksik_kalem_satir_sayilari: MissingLineCounts;
  kesinlik: CertaintyLabel;
}

export interface LineItems {
  net_satis_kdv_haric: Money;
  urun_maliyeti: Money | null;
  komisyon: Money;
  kargo_gonderi: Money;
  kargo_iade: Money;
  platform_hizmet_bedeli: Money;
  ceza: Money;
  reklam: Money;
  degisken_giderler: Money;
  toplam_gider: Money | null;
  eksik_giderler_haric_kar: Money;
  net_kar: Money | null;
  net_kar_marji_yuzde: Money | null;
}

export interface LineSources {
  satis: SourceCode;
  komisyon: SourceCode;
  urun_maliyeti: SourceCode;
  kargo_gonderi: SourceCode;
  kargo_iade: SourceCode;
  platform_hizmet_bedeli: SourceCode;
  ceza: SourceCode;
  degisken_giderler: SourceCode;
  reklam: SourceCode;
}

export interface LineComparison {
  komisyon_tahmini: Money;
  komisyon_kesin: Money;
  kargo_gonderi_tahmini: Money | null;
  kargo_gonderi_kesin: Money | null;
  platform_hizmet_bedeli_tahmini: Money | null;
  platform_hizmet_bedeli_kesin: Money | null;
  kargo_tahmini_varsayilan_desi: boolean;
  karsilastirilan_tahmini_toplam: Money;
  karsilastirilan_kesin_toplam: Money;
  fark: Money;
  esik: Money;
}

export interface ProfitLine {
  orderNumber: string;
  shipmentPackageId: number;
  lineId: number;
  barcode: string;
  durum: LineStatus;
  adet: number;
  adet_iade: number;
  iade_kaydi_bekleyen_adet: number;
  askidaki_urun_maliyeti: Money | null;
  kesinlik: CertaintyLabel;
  eksik_kalemler: MissingItemCode[];
  kalemler: LineItems;
  kaynaklar: LineSources;
  karsilastirma: LineComparison | null;
  uyarilar: string[];
}

export interface ComparisonSummary {
  compared_line_count: number;
  estimated_total: Money;
  actual_total: Money;
  difference: Money;
}

export interface ProductProfitDetail {
  period: ReportPeriod;
  barcode: string;
  title: string | null;
  product: ProductTotals | null;
  certainty: CertaintyLabel;
  comparison: ComparisonSummary;
  total_lines: number;
  lines: ProfitLine[];
  next_cursor: string | null;
}

export interface AlertCount {
  code: string;
  count: number;
  message: string;
}

export interface ProfitAlerts {
  period: ReportPeriod;
  counts: AlertCount[];
  total_count: number;
  next_cursor: string | null;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

function base(accountId: string): string {
  return `/marketplace-accounts/${encodeURIComponent(accountId)}/profit`;
}

export const profitApi = {
  accounts: (signal?: AbortSignal) =>
    apiFetch<MarketplaceAccount[]>('/marketplace-accounts', { signal }),

  summary: (accountId: string, range: RangeName, signal?: AbortSignal) =>
    apiFetch<ProfitSummary>(`${base(accountId)}/summary${query({ range })}`, { signal }),

  /** Yalnız sayımlar için `limit=1`; liste ekranı bu sürümün kapsamı dışındadır. */
  alertCounts: (accountId: string, range: RangeName, signal?: AbortSignal) =>
    apiFetch<ProfitAlerts>(`${base(accountId)}/alerts${query({ range, limit: 1 })}`, { signal }),

  products: (
    accountId: string,
    params: {
      range: RangeName;
      sort: ProductSort;
      order: SortOrder;
      filter: ProductFilter;
      cursor?: string | null;
      limit?: number;
    },
    signal?: AbortSignal,
  ) => apiFetch<ProductProfitList>(`${base(accountId)}/products${query(params)}`, { signal }),

  productDetail: (
    accountId: string,
    barcode: string,
    params: { range: RangeName; cursor?: string | null; limit?: number },
    signal?: AbortSignal,
  ) =>
    apiFetch<ProductProfitDetail>(
      `${base(accountId)}/products/${encodeURIComponent(barcode)}${query(params)}`,
      { signal },
    ),
};
