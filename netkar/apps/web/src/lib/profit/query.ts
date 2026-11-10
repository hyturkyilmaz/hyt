// URL sorgu parametreleri: dönem, sıralama ve süzgeç. Geçersiz değer sessizce varsayılana düşer.
import type { ProductFilter, ProductSort, RangeName, SortOrder } from '@/lib/api/profit';

export const DEFAULT_RANGE: RangeName = '30d';
export const DEFAULT_SORT: ProductSort = 'net_profit';
export const DEFAULT_ORDER: SortOrder = 'desc';
export const DEFAULT_FILTER: ProductFilter = 'all';

export const RANGE_OPTIONS: readonly { value: RangeName; label: string }[] = [
  { value: 'today', label: 'Bugün' },
  { value: '7d', label: '7 gün' },
  { value: '30d', label: '30 gün' },
];

export const SORT_OPTIONS: readonly { value: ProductSort; label: string }[] = [
  { value: 'net_profit', label: 'Net kâr' },
  { value: 'net_margin', label: 'Marj' },
  { value: 'sales', label: 'Net satış' },
  { value: 'units', label: 'Adet' },
];

export const FILTER_OPTIONS: readonly { value: ProductFilter; label: string }[] = [
  { value: 'all', label: 'Tümü' },
  { value: 'loss', label: 'Zarar edenler' },
  { value: 'missing_cost', label: 'Maliyeti eksik' },
];

function pick<T extends string>(
  value: string | null | undefined,
  allowed: readonly { value: T }[],
  fallback: T,
): T {
  return allowed.find((option) => option.value === value)?.value ?? fallback;
}

export function parseRange(value: string | null | undefined): RangeName {
  return pick(value, RANGE_OPTIONS, DEFAULT_RANGE);
}

export interface ProductQuery {
  range: RangeName;
  sort: ProductSort;
  order: SortOrder;
  filter: ProductFilter;
}

export function parseProductQuery(params: { get(name: string): string | null }): ProductQuery {
  return {
    range: parseRange(params.get('range')),
    sort: pick(params.get('sort'), SORT_OPTIONS, DEFAULT_SORT),
    order: params.get('order') === 'asc' ? 'asc' : DEFAULT_ORDER,
    filter: pick(params.get('filter'), FILTER_OPTIONS, DEFAULT_FILTER),
  };
}

/** Dönem her zaman yazılır; sıralama ve süzgeç yalnız varsayılandan farklıysa. */
export function productQueryString(q: ProductQuery): string {
  const search = new URLSearchParams({ range: q.range });
  if (q.sort !== DEFAULT_SORT) search.set('sort', q.sort);
  if (q.order !== DEFAULT_ORDER) search.set('order', q.order);
  if (q.filter !== DEFAULT_FILTER) search.set('filter', q.filter);
  return search.toString();
}
