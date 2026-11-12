// Siparişler ekranının sunum kuralları (UX incelemesi §8.2). Saf fonksiyonlar: bileşenler yalnız bu çıktıyı çizer.
import type { OrderFilter, OrderListItem, OrderProduct } from '@/lib/api/profit';
import { absDecimal, decimalSign } from '@/lib/profit/decimal-math';
import {
  certaintyBadge,
  decreaseNote,
  joinNames,
  lossReasonBadge,
  missingItemNames,
  type BadgeSpec,
  type LossDisplay,
} from '@/lib/profit/present';

export type OrderNetView =
  | { kind: 'cancelled' }
  | { kind: 'value'; value: string }
  /** Net kâr bilinmiyor ama bilinen giderlerle bile zarar kesin: "En az ₺X zarar" */
  | { kind: 'loss'; loss: LossDisplay }
  /** Net kâr hesaplanamadı; eksik kalem adları ve (etiketli) eksik giderler hariç kâr */
  | { kind: 'uncomputable'; missing: string[]; known: string | null };

/**
 * Kural 1 ve 10: iptal siparişte rakam yok ("İptal", asla 0,00 değil); null net kâr "Hesaplanamadı".
 * `known_expenses_profit` yalnız net kâr null iken ve etiketle gösterilir ("Eksik giderler hariç").
 */
export function orderNetView(item: OrderListItem): OrderNetView {
  if (item.cancelled) return { kind: 'cancelled' };
  if (item.net_profit !== null) return { kind: 'value', value: item.net_profit };
  const known = item.known_expenses_profit;
  if (item.loss_reason !== null && known !== null && decimalSign(known) < 0) {
    const names = joinNames(missingItemNames(item.missing_items));
    return {
      kind: 'loss',
      loss: {
        magnitude: absDecimal(known),
        amount: known,
        exact: false,
        note: decreaseNote(names),
      },
    };
  }
  return { kind: 'uncomputable', missing: missingItemNames(item.missing_items), known };
}

/** Ürün adı metin düğümü olarak basılır (HTML yorumlanmaz); katalogda yoksa barkod gösterilir. */
export function orderProductTitle(product: OrderProduct): string {
  return product.title && product.title.trim() ? product.title : 'Başlıksız ürün';
}

/**
 * Rozetler: zarar nedeni, kesinlik, ekstre ve beklenmeyen kesinti. İptalde yalnız "İptal" rakamın yerindedir;
 * eksik bilgi adıyla "Eksik: ..." satırında yazıldığından "Bilgi eksik" rozeti basılmaz (UX-10).
 */
export function orderBadges(item: OrderListItem): BadgeSpec[] {
  if (item.cancelled) return [];
  const badges: BadgeSpec[] = [];
  if (item.loss_reason) badges.push(lossReasonBadge(item.loss_reason));
  const certainty = item.certainty === 'eksik' ? null : certaintyBadge(item.certainty);
  if (certainty) badges.push(certainty);
  // SU-03: "Ekstresi gelmeyen" ekstre kaydı yok demektir; ödeme durumu değildir.
  if (item.awaiting_payout) badges.push({ label: 'Ekstresi gelmedi', tone: 'neutral' });
  if (item.unexpected_deduction) badges.push({ label: 'Beklenmeyen kesinti', tone: 'warning' });
  return badges;
}

export const ORDER_EMPTY_TEXT: Record<OrderFilter, { title: string; description: string }> = {
  all: {
    title: 'Bu dönemde sipariş yok',
    description:
      'Başka bir dönem seçebilirsiniz. Siparişler geldikçe kâr durumlarıyla burada listelenir.',
  },
  loss: {
    title: 'Zarar eden sipariş yok',
    description: 'Bu dönemde zararı kesin olan bir sipariş bulunmadı.',
  },
  awaiting_payout: {
    title: 'Ekstresi gelmeyen sipariş yok',
    description: 'Bu dönemdeki siparişlerin tümünün ekstre kaydı gelmiş.',
  },
  unexpected_deduction: {
    title: 'Beklenmeyen kesintili sipariş yok',
    description: 'Bu dönemde Trendyol beklediğimizden fazla kesinti yapmadı.',
  },
};

export const ORDER_SEARCH_EMPTY = {
  title: 'Bu numarada sipariş bulunamadı',
  description:
    'Sipariş no tam yazılmalıdır (kısmi eşleşme yok). Seçili dönemde bu numaralı sipariş yoksa başka bir dönem deneyin.',
};
