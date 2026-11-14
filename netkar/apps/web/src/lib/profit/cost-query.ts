// Ürün maliyetleri ekranının URL sorgusu: `q` (barkod arama, en çok 100 karakter) ve `filtre=eksik`.
// Uyarıdaki "Maliyeti eksik ürünleri gör" eylemi bu ekrana `?filtre=eksik` ile gelir.
import { MAX_SEARCH_LENGTH } from '@/lib/api/product-costs';

export interface CostQuery {
  q: string;
  missingOnly: boolean;
}

export const COSTS_PATH = '/panel/maliyetler';

export function parseCostQuery(params: { get: (name: string) => string | null }): CostQuery {
  const raw = (params.get('q') ?? '').trim().slice(0, MAX_SEARCH_LENGTH);
  return { q: raw, missingOnly: params.get('filtre') === 'eksik' };
}

export function costsHref(query: Partial<CostQuery> = {}): string {
  const search = new URLSearchParams();
  if (query.missingOnly) search.set('filtre', 'eksik');
  if (query.q) search.set('q', query.q);
  const text = search.toString();
  return text ? `${COSTS_PATH}?${text}` : COSTS_PATH;
}

/** Süzgeç yalnız yüklenen sayfalara uygulanır (API'de maliyet eksik süzgeci yok): görünür satırlar */
export function visibleProducts<T extends { cost_missing: boolean }>(
  items: readonly T[],
  missingOnly: boolean,
): T[] {
  return missingOnly ? items.filter((item) => item.cost_missing) : [...items];
}
