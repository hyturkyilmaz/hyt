// Ürün maliyeti ekranı için test ve e2e örnek yanıtları (alan adları services/api product_cost_schemas.py ile aynı).
// Üretim kodunda kullanılmaz. Yalnız tür içe aktarımı yapılır: Playwright de bu dosyayı doğrudan yükler.
import type {
  CostHistory,
  CostOut,
  CostUpsertResult,
  ImportReport,
  ProductCostItem,
  ProductCostList,
} from '../api/product-costs';

export function makeCost(over: Partial<CostOut> = {}): CostOut {
  return { valid_from: '2026-09-01', unit_cost_excl_vat: '54.50', vat_rate: 20, ...over };
}

export function makeProduct(over: Partial<ProductCostItem> = {}): ProductCostItem {
  const base: ProductCostItem = {
    barcode: 'BRK-0001',
    title: 'Çelik Termos 500 ml',
    stock_code: 'TRM-500',
    current_cost: makeCost(),
    cost_missing: false,
  };
  const merged = { ...base, ...over };
  return { ...merged, cost_missing: merged.current_cost === null };
}

export function makeMissingProduct(over: Partial<ProductCostItem> = {}): ProductCostItem {
  return makeProduct({
    barcode: 'BRK-0002',
    title: 'Cam Matara',
    stock_code: null,
    current_cost: null,
    ...over,
  });
}

export function makeProductList(
  items: ProductCostItem[],
  nextCursor: string | null = null,
  totalMissing: number = items.filter((item) => item.cost_missing).length,
): ProductCostList {
  return { items, next_cursor: nextCursor, total_missing: totalMissing };
}

export function makeHistory(barcode: string, items: CostOut[] = [makeCost()]): CostHistory {
  return { barcode, product_known: true, items };
}

export function makeUpsertResult(over: Partial<CostUpsertResult> = {}): CostUpsertResult {
  return {
    barcode: 'BRK-0002',
    product_known: true,
    created: true,
    cost: makeCost({ valid_from: '2026-08-14' }),
    ...over,
  };
}

export function makeImportReport(over: Partial<ImportReport> = {}): ImportReport {
  return {
    dry_run: true,
    committed: false,
    format: 'csv',
    total: 3,
    valid: 3,
    invalid: 0,
    skipped: 0,
    unknown_barcodes: 0,
    created: null,
    updated: null,
    errors: [],
    errors_truncated: false,
    ignored_columns: [],
    ...over,
  };
}
