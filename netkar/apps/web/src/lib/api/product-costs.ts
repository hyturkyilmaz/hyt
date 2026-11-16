// Backend sözleşmesi: services/api/app/api/v1/product_costs.py ve product_cost_schemas.py.
// Para Decimal DİZGESİDİR ("12.50"); KDV oranı tamsayı yüzdedir (0, 1, 10, 20). Maliyet her zaman KDV HARİÇtir.
// Yazma yalnız owner/admin içindir (görüntüleyici 403 alır); okuma tüm roller içindir.
import { apiFetch, apiFetchResponse } from '@/lib/api/client';

export type Money = string;

/** Bir geçerlilik tarihli maliyet kaydı (`CostOut`) */
export interface CostOut {
  valid_from: string;
  unit_cost_excl_vat: Money;
  vat_rate: number;
}

/** `ProductItemOut`: `current_cost` bugün (İstanbul) geçerli maliyettir; yoksa `cost_missing` true */
export interface ProductCostItem {
  barcode: string;
  title: string | null;
  stock_code: string | null;
  current_cost: CostOut | null;
  cost_missing: boolean;
}

export interface ProductCostList {
  items: ProductCostItem[];
  next_cursor: string | null;
  /** Hesabın TÜM ürünleri içinde bugün geçerli maliyeti olmayanların sayısı (q, after ve missing'den bağımsız) */
  total_missing: number;
}

export interface CostHistory {
  barcode: string;
  /** Ürün henüz senkronlanmamış olabilir; kayıt yine de tutulur */
  product_known: boolean;
  items: CostOut[];
}

/** PUT gövdesi (`CostUpsertIn`, fazladan alan 422): tarih "YYYY-AA-GG", tutar ve oran dizge ya da sayı */
export interface CostUpsertBody {
  valid_from: string;
  unit_cost_excl_vat: Money;
  vat_rate: string;
}

export interface CostUpsertResult {
  barcode: string;
  product_known: boolean;
  /** true: yeni kayıt; false: aynı geçerlilik tarihli kayıt güncellendi */
  created: boolean;
  cost: CostOut;
}

export interface ImportIssue {
  row: number;
  column: string;
  message: string;
  value: string | null;
}

/** `ImportReportOut` */
export interface ImportReport {
  dry_run: boolean;
  committed: boolean;
  format: string;
  total: number;
  valid: number;
  invalid: number;
  skipped: number;
  unknown_barcodes: number;
  created: number | null;
  updated: number | null;
  errors: ImportIssue[];
  errors_truncated: boolean;
  ignored_columns: string[];
}

/** Sunucudaki sınırlar (config.py `max_cost_import_file_bytes`, cost_import.py `MAX_ROWS`) */
export const IMPORT_MAX_BYTES = 2 * 1024 * 1024;
export const IMPORT_MAX_ROWS = 10_000;
export const IMPORT_EXTENSIONS = ['.csv', '.xlsx'] as const;
export const PRODUCTS_PAGE_SIZE = 50;
export const MAX_SEARCH_LENGTH = 100;

function base(accountId: string): string {
  return `/marketplace-accounts/${encodeURIComponent(accountId)}`;
}

/**
 * Sunucudaki barkod deseni (product_costs.py `BARCODE_PATTERN`): yol parametresi ve içe aktarma yalnız buna izin verir.
 * Desen dışı barkodlu ürün için maliyet girilemez (sunucu 422 verir); arayüz istek atmaz, nedenini söyler.
 * Backend kararı bekliyor: senkron bu barkodları saklıyor ama maliyet ucu kabul etmiyor.
 */
const SUPPORTED_BARCODE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/;
export function isSupportedBarcode(barcode: string): boolean {
  return SUPPORTED_BARCODE.test(barcode);
}

export const TEMPLATE_FALLBACK_NAME = 'maliyet_sablonu.csv';

export interface TemplateDownload {
  blob: Blob;
  filename: string;
  /** `X-Template-Truncated: true`: ürün sayısı şablon sınırını aştı, şablon eksik */
  truncated: boolean;
}

function filenameFrom(disposition: string | null): string {
  const match = /filename="([A-Za-z0-9._-]{1,100})"/.exec(disposition ?? '');
  return match?.[1] ?? TEMPLATE_FALLBACK_NAME;
}

export const productCostsApi = {
  products: (
    accountId: string,
    params: { q?: string; cursor?: string | null; limit?: number; missing?: boolean },
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    if (params.q) search.set('q', params.q);
    if (params.cursor) search.set('after', params.cursor);
    // Sunucu süzgeci: yalnız bugün geçerli maliyeti olmayan ürünler (sayfalamadan önce uygulanır)
    if (params.missing) search.set('missing', 'true');
    search.set('limit', String(params.limit ?? PRODUCTS_PAGE_SIZE));
    return apiFetch<ProductCostList>(`${base(accountId)}/products?${search.toString()}`, {
      signal,
    });
  },

  history: (accountId: string, barcode: string, signal?: AbortSignal) =>
    apiFetch<CostHistory>(`${base(accountId)}/products/${encodeURIComponent(barcode)}/costs`, {
      signal,
    }),

  upsert: (accountId: string, barcode: string, body: CostUpsertBody) =>
    apiFetch<CostUpsertResult>(`${base(accountId)}/products/${encodeURIComponent(barcode)}/costs`, {
      method: 'PUT',
      body,
    }),

  /** Şablon CSV'si (GET, aynı köken). Hata durumunda `ApiError` (401, 404, 429, 5xx) atılır. */
  template: async (accountId: string, signal?: AbortSignal): Promise<TemplateDownload> => {
    const response = await apiFetchResponse(`${base(accountId)}/product-costs/template.csv`, {
      signal,
    });
    return {
      blob: await response.blob(),
      filename: filenameFrom(response.headers.get('Content-Disposition')),
      truncated: response.headers.get('X-Template-Truncated') === 'true',
    };
  },

  /** `dryRun` true (varsayılan sunucu davranışı): yalnız rapor, hiçbir şey yazılmaz */
  importFile: (
    accountId: string,
    file: File,
    options: { dryRun: boolean; allowPartial: boolean },
    signal?: AbortSignal,
  ) => {
    const formData = new FormData();
    formData.append('file', file);
    const search = new URLSearchParams({
      dry_run: String(options.dryRun),
      allow_partial: String(options.allowPartial),
    });
    return apiFetch<ImportReport>(`${base(accountId)}/product-costs/import?${search.toString()}`, {
      method: 'POST',
      formData,
      signal,
    });
  },
};
