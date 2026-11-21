// Ayar formunun sunucudan aldığı bilgiler (GET profit-settings: earliest_order_day, today_istanbul, vat_rates) ve
// eski API'ye (alanlar yok) uyum için yedek değerler. Tarih hesabı takvim günü metni üzerindedir, oran Decimal
// dizgesidir (float yok).
import type { SettingsOut } from '@/lib/api/profit-settings';
import { addDays, formatLongDate, isDateText, MIN_VALID_FROM } from '@/lib/profit/settings-input';

/** Yedek KDV oranı (K02: genel oran %20); yalnız sunucu `vat_rates` göndermiyorsa kullanılır */
export const FALLBACK_VAT_RATE = '20';

export interface VatRates {
  shipping: string;
  serviceFee: string;
}

function validRate(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const [whole = '', fraction, ...rest] = value.split('.');
  const valid =
    rest.length === 0 &&
    /^\d{1,3}$/.test(whole) &&
    (fraction === undefined || /^\d{1,4}$/.test(fraction));
  return valid ? value : null;
}

/** Kargo ve hizmet bedeli KDV oranları: sunucudan, alan yoksa ya da bozuksa %20 */
export function resolveVatRates(settings: Pick<SettingsOut, 'vat_rates'>): VatRates {
  return {
    shipping: validRate(settings.vat_rates?.shipping) ?? FALLBACK_VAT_RATE,
    serviceFee: validRate(settings.vat_rates?.service_fee) ?? FALLBACK_VAT_RATE,
  };
}

/** "20" -> "20", "20.0000" -> "20", "0.5" -> "0,5" (görünen oran; tr-TR ondalık virgül) */
export function formatVatRate(rate: string): string {
  const [whole = '0', fraction = ''] = rate.split('.');
  const trimmed = fraction.replace(/0+$/, '');
  return trimmed === '' ? whole : `${whole},${trimmed}`;
}

/** Sunucu günü varsa o, yoksa verilen cihaz günü */
export function resolveToday(serverToday: string | null | undefined, deviceToday: string): string {
  return typeof serverToday === 'string' && isDateText(serverToday) ? serverToday : deviceToday;
}

const MS_PER_DAY = 86_400_000;

/** İki takvim günü arasındaki tam gün farkı (b - a) */
export function daysBetween(a: string, b: string): number {
  const toUtc = (text: string) => {
    const [y = 0, m = 1, d = 1] = text.split('-').map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((toUtc(b) - toUtc(a)) / MS_PER_DAY);
}

/**
 * Sunucu gününü cihaz saatiyle ilerletir: sunucu günü alındığında cihazın günü `deviceAtFetch` idi, şimdi
 * `deviceNow`. Cihaz saati yanlış olsa bile yalnız GEÇEN gün sayısı kullanılır (geriye gitmez); sekme gece yarısını
 * geçince "bugün" yenilenir (AF-12), sunucu gününden bağımsız bir saat okumasına güvenilmez.
 */
export function advanceServerDay(
  serverDay: string,
  deviceAtFetch: string,
  deviceNow: string,
): string {
  const elapsed = Math.max(0, daysBetween(deviceAtFetch, deviceNow));
  return elapsed === 0 ? serverDay : addDays(serverDay, elapsed);
}

export interface StartSuggestion {
  /** Önerilen başlangıç günü (YYYY-AA-GG) */
  day: string;
  /** true: hesabın ilk sipariş günü bilinmiyor, tarama penceresinden yaklaşık öneri */
  approximate: boolean;
  /** Bilinen en eski sipariş günü (yaklaşık öneride null) */
  earliestOrderDay: string | null;
}

/**
 * Yeni kaydın başlangıç tarihi önerisi (AB-01, AF-05): hesabın en eski sipariş gününden 1 gün ÖNCE, böylece geçmiş
 * siparişler de kapsanır. Sunucu `earliest_order_day` vermiyorsa (sipariş yok ya da eski API) bugünden
 * `lookbackDays` gün öncesi YAKLAŞIK öneridir. K33 alt sınırının (2000-01-01) altına inmez.
 */
export function suggestStartDay(options: {
  today: string;
  earliestOrderDay: string | null | undefined;
  lookbackDays: number;
}): StartSuggestion {
  const earliest =
    typeof options.earliestOrderDay === 'string' && isDateText(options.earliestOrderDay)
      ? options.earliestOrderDay
      : null;
  const raw =
    earliest !== null ? addDays(earliest, -1) : addDays(options.today, -options.lookbackDays);
  return {
    day: raw < MIN_VALID_FROM ? MIN_VALID_FROM : raw,
    approximate: earliest === null,
    earliestOrderDay: earliest,
  };
}

/**
 * Başlangıç alanının altındaki öneri notu. Yaklaşık öneride "yaklaşık" uyarısı kalır; sunucu en eski sipariş gününü
 * verdiyse öneri kesindir ve gün açıkça yazılır. `short`: gider formunun daha kısa metni.
 */
export function startSuggestionNote(
  suggestion: StartSuggestion,
  lookbackDays: number,
  variant: 'full' | 'short' = 'full',
): string {
  if (suggestion.earliestOrderDay !== null) {
    return `Önerilen tarih, hesabınızdaki en eski siparişten (${formatLongDate(suggestion.earliestOrderDay)}) bir gün öncedir; geçmiş siparişleriniz de hesaplanır.`;
  }
  return variant === 'short'
    ? `Önerilen tarih yaklaşıktır (bugünden ${lookbackDays} gün önce); geçmiş siparişleri de kapsamak için hesabınızdaki en eski siparişten ÖNCE bir tarih seçin.`
    : `Önerilen tarih yaklaşıktır (bugünden ${lookbackDays} gün önce). Geçmiş siparişlerinizi de hesaplatmak için tarihi hesabınızdaki en eski siparişten ÖNCE seçin; emin değilseniz daha eski bir tarih seçin.`;
}
