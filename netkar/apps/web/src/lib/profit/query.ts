// URL sorgu parametreleri: dönem, sıralama ve süzgeç. Geçersiz değer sessizce varsayılana düşer.
import type {
  OrderFilter,
  OrderSort,
  ProductFilter,
  ProductSort,
  RangeName,
  SortOrder,
} from '@/lib/api/profit';

export const DEFAULT_RANGE: RangeName = '30d';
export const DEFAULT_SORT: ProductSort = 'net_profit';
export const DEFAULT_ORDER: SortOrder = 'desc';
export const DEFAULT_FILTER: ProductFilter = 'all';

/** UX-04: zarar süzgecinde varsayılan yön "en çok zarar önce" (net kâr artan); diğerlerinde çoktan aza. */
export function defaultOrderFor(filter: ProductFilter): SortOrder {
  return filter === 'loss' ? 'asc' : DEFAULT_ORDER;
}

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
  const filter = pick(params.get('filter'), FILTER_OPTIONS, DEFAULT_FILTER);
  const rawOrder = params.get('order');
  return {
    range: parseRange(params.get('range')),
    sort: pick(params.get('sort'), SORT_OPTIONS, DEFAULT_SORT),
    order: rawOrder === 'asc' || rawOrder === 'desc' ? rawOrder : defaultOrderFor(filter),
    filter,
  };
}

/** Dönem her zaman yazılır; sıralama, yön ve süzgeç yalnız varsayılandan farklıysa. */
export function productQueryString(q: ProductQuery): string {
  const search = new URLSearchParams({ range: q.range });
  if (q.sort !== DEFAULT_SORT) search.set('sort', q.sort);
  if (q.order !== defaultOrderFor(q.filter)) search.set('order', q.order);
  if (q.filter !== DEFAULT_FILTER) search.set('filter', q.filter);
  return search.toString();
}

// --------------------------------------------------------------------------- siparişler

export const ORDER_FILTER_OPTIONS: readonly { value: OrderFilter; label: string }[] = [
  { value: 'all', label: 'Tümü' },
  { value: 'loss', label: 'Zarar edenler' },
  // SU-03: "hakediş bekleyen" ödeme beklentisi çağrıştırır; tanım "ekstre kaydı henüz gelmemiş"tir.
  { value: 'awaiting_payout', label: 'Ekstresi gelmeyen' },
  { value: 'unexpected_deduction', label: 'Beklenmeyen kesinti' },
];

const ORDER_SORTS: readonly { value: OrderSort }[] = [{ value: 'date' }, { value: 'net_profit' }];

/** Sipariş no araması: API deseniyle aynı (services/api profit.py `q`): harf/rakamla başlar, 1-64 karakter. */
export const ORDER_SEARCH_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
export const ORDER_SEARCH_MAX = 64;

export function isValidOrderSearch(value: string): boolean {
  return value.length <= ORDER_SEARCH_MAX && ORDER_SEARCH_PATTERN.test(value);
}

/** Süzgece göre varsayılan sıralama: zarar edenlerde en çok zarar önce (net kâr artan), diğerlerinde yeni önce. */
export function defaultOrderSortFor(filter: OrderFilter): { sort: OrderSort; order: SortOrder } {
  return filter === 'loss' ? { sort: 'net_profit', order: 'asc' } : { sort: 'date', order: 'desc' };
}

export interface OrderQuery {
  range: RangeName;
  sort: OrderSort;
  order: SortOrder;
  filter: OrderFilter;
  /** Geçerli arama metni; boş ise arama yok */
  q: string;
  /** URL'de `q` vardı ama geçersizdi ve yok sayıldı; ekran bunu kullanıcıya söyler (OS-09). */
  qRejected: boolean;
}

export function parseOrderQuery(params: { get(name: string): string | null }): OrderQuery {
  const filter = pick(params.get('filter'), ORDER_FILTER_OPTIONS, 'all');
  const fallback = defaultOrderSortFor(filter);
  const rawOrder = params.get('order');
  const rawQ = (params.get('q') ?? '').trim();
  return {
    range: parseRange(params.get('range')),
    sort: pick(params.get('sort'), ORDER_SORTS, fallback.sort),
    order: rawOrder === 'asc' || rawOrder === 'desc' ? rawOrder : fallback.order,
    filter,
    // Geçersiz arama istek olarak gönderilmez (API 422 verirdi); `qRejected` ile ekran bunu bildirir.
    q: isValidOrderSearch(rawQ) ? rawQ : '',
    qRejected: rawQ !== '' && !isValidOrderSearch(rawQ),
  };
}

/** Dönem her zaman yazılır; sıralama, yön ve süzgeç yalnız süzgecin varsayılanından farklıysa, `q` doluysa. */
export function orderQueryString(q: OrderQuery): string {
  const search = new URLSearchParams({ range: q.range });
  const fallback = defaultOrderSortFor(q.filter);
  if (q.sort !== fallback.sort) search.set('sort', q.sort);
  if (q.order !== fallback.order) search.set('order', q.order);
  if (q.filter !== 'all') search.set('filter', q.filter);
  if (q.q) search.set('q', q.q);
  return search.toString();
}

/** Başka ekranlardan (uyarılar) sipariş listesine bağlantı. */
export function ordersHref(partial: Partial<OrderQuery> & { range: RangeName }): string {
  const filter = partial.filter ?? 'all';
  const fallback = defaultOrderSortFor(filter);
  return `/panel/siparisler?${orderQueryString({
    sort: fallback.sort,
    order: fallback.order,
    filter,
    q: '',
    qRejected: false,
    ...partial,
  })}`;
}
