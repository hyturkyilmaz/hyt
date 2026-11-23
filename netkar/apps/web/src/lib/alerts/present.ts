// Uyarı olaylarının sunum kuralları (ADR-0009 §8.3, D7). Yalnız D6 şemasındaki alanlar okunur
// (`rule`, `subject`, `payload` kanıt alanları). Payload tutarları metindir; tanınmayan ya da bozuk değer
// sessizce 0 yazılmaz, o satır hiç gösterilmez.
import { ApiError, NetworkError, describeApiError } from '@/lib/api/client';
import type { AlertEvent, EventStatus, RuleName } from '@/lib/api/alerts';
import { describeRateLimitWait } from '@/lib/api/retry-after';
import { formatCount, formatPercent } from '@/lib/format';
import { ordersHref, parseRange } from '@/lib/profit/query';

export const RULE_LABELS: Record<RuleName, string> = {
  ZARARINA_SATIS: 'Zararına satış',
  REKLAM_KARI_YIYOR: 'Reklam kârı yiyor',
  BEKLENMEYEN_KESINTI: 'Beklenmeyen kesinti',
  IADE_ORANI_ARTISI: 'İade oranı artışı',
};

export const STATUS_LABELS: Record<EventStatus, string> = {
  open: 'Açık',
  read: 'Okundu',
  muted: 'Susturuldu',
  resolved: 'Çözüldü',
};

export type AlertTab = 'acik' | 'okundu' | 'susturulmus' | 'cozuldu' | 'tumu' | 'donem';

export const TAB_ORDER: readonly AlertTab[] = [
  'acik',
  'okundu',
  'susturulmus',
  'cozuldu',
  'tumu',
  'donem',
];

/** Sekme -> durum süzgeci; `tumu` süzgeçsizdir (undefined). */
export const TAB_STATUS: Record<Exclude<AlertTab, 'donem'>, EventStatus | undefined> = {
  acik: 'open',
  okundu: 'read',
  susturulmus: 'muted',
  cozuldu: 'resolved',
  tumu: undefined,
};

export const TAB_LABELS: Record<AlertTab, string> = {
  acik: 'Açık',
  okundu: 'Okundu',
  susturulmus: 'Susturulmuş',
  cozuldu: 'Çözülmüş',
  tumu: 'Tümü',
  donem: 'Dönem dökümü',
};

/** URL'deki `sekme` değeri; tanınmayan değer varsayılan sekmeye (açık) düşer. */
export function parseTab(value: string | null): AlertTab {
  return TAB_ORDER.find((tab) => tab === value) ?? 'acik';
}

export const MUTE_MIN_DAYS = 1;
export const MUTE_MAX_DAYS = 90;
export const MUTE_DEFAULT_DAYS = 7;

/** Susturma süresi metni (1-90 tam sayı); hata iletisi ya da geçerli sayı. */
export function parseMuteDays(
  text: string,
): { ok: true; days: number } | { ok: false; message: string } {
  const trimmed = text.trim();
  if (trimmed === '') return { ok: false, message: 'Gün sayısını yazın.' };
  if (!/^\d{1,3}$/.test(trimmed)) {
    return { ok: false, message: 'Gün sayısı tam sayı olmalı. Örnek: 7' };
  }
  const days = Number(trimmed);
  if (days < MUTE_MIN_DAYS || days > MUTE_MAX_DAYS) {
    return {
      ok: false,
      message: `Gün sayısı ${MUTE_MIN_DAYS} ile ${MUTE_MAX_DAYS} arasında olmalı.`,
    };
  }
  return { ok: true, days };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Olay yükü iç içedir: `{certainty, evidence: {...}}` (services/api alert_evaluation.py `event_payload`). Kanıt
 * alanları `evidence` altından okunur; geriye uyum için düz yük (alanlar doğrudan payload'da) da kabul edilir.
 */
export function eventEvidence(event: AlertEvent): Record<string, unknown> {
  const nested = event.payload.evidence;
  return isPlainObject(nested) ? nested : event.payload;
}

/** Kesinlik: `tahmini` ise karta "Tahmini" rozeti konur (ADR §3 K40, §8.3); `kesin` ve bilinmeyen için false. */
export function isEstimated(event: AlertEvent): boolean {
  return event.payload.certainty === 'tahmini';
}

/** Kısa dürüstlük notları: varsayılan desi kullanıldı, eksik maliyet kalemi var. Kanıt alanı yoksa not yok. */
export function eventNotes(event: AlertEvent): string[] {
  const evidence = eventEvidence(event);
  const notes: string[] = [];
  if (event.rule === 'BEKLENMEYEN_KESINTI' && evidence.default_desi_used === true) {
    notes.push('Siparişte desi bilgisi yoktu; varsayılan desi kullanıldı.');
  }
  if (event.rule === 'ZARARINA_SATIS' && evidence.has_missing_items === true) {
    notes.push('Bazı satırlarda maliyet kalemi eksik; gerçek zarar farklı olabilir.');
  }
  return notes;
}

/** Payload'daki sayısal değer: JSON sayısı ya da sade Decimal dizgesi; yoksa null. */
function decimalOf(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'string' && value.length <= 27) {
    const [whole = '', fraction, extra] = value.replace(/^-/, '').split('.');
    const digits = (part: string) => part.length > 0 && /^[0-9]+$/.test(part);
    if (extra === undefined && digits(whole) && (fraction === undefined || digits(fraction))) {
      return value;
    }
  }
  return null;
}

export interface EventAmount {
  label: string;
  value: string;
}

/** Karttaki tek tutar: kuralın en anlamlı kanıt alanı. İade oranında tutar yoktur. */
export function eventAmount(event: AlertEvent): EventAmount | null {
  const pick = (label: string, key: string): EventAmount | null => {
    const value = decimalOf(eventEvidence(event), key);
    return value === null ? null : { label, value };
  };
  switch (event.rule) {
    case 'ZARARINA_SATIS':
      return pick('Toplam zarar', 'total_loss');
    case 'REKLAM_KARI_YIYOR':
      return pick('Reklam harcaması', 'ad_spend');
    case 'BEKLENMEYEN_KESINTI':
      return pick('Fazla kesinti', 'difference');
    default:
      return null;
  }
}

function safePercent(value: string | null): string | null {
  if (value === null) return null;
  try {
    return formatPercent(value, { fractionDigits: 1 });
  } catch {
    return null;
  }
}

/** Kural başına tek cümle; eksik kanıt alanında genel cümleye düşer. */
export function eventSentence(event: AlertEvent): string {
  const p = eventEvidence(event);
  switch (event.rule) {
    case 'ZARARINA_SATIS': {
      const lines = decimalOf(p, 'loss_line_count');
      return lines !== null && Number.isInteger(Number(lines))
        ? `${formatCount(Number(lines))} satırda zarar var.`
        : 'Bu üründe satış zararına gidiyor.';
    }
    case 'REKLAM_KARI_YIYOR': {
      const share = safePercent(decimalOf(p, 'ad_share_percent'));
      return share
        ? `Reklam harcaması, reklam öncesi kârın ${share} düzeyinde.`
        : 'Reklam harcaması kârın büyük kısmını yiyor.';
    }
    case 'BEKLENMEYEN_KESINTI':
      return 'Trendyol beklediğimizden fazla kesinti yaptı.';
    case 'IADE_ORANI_ARTISI': {
      const before = safePercent(decimalOf(p, 'base_rate_percent'));
      const now = safePercent(decimalOf(p, 'current_rate_percent'));
      return before && now
        ? `İade oranı ${before} düzeyinden ${now} düzeyine çıktı.`
        : 'İade oranı önceki döneme göre arttı.';
    }
  }
}

export interface SubjectInfo {
  /** Kısa konu satırı: "Ürün <barkod>" ya da "Sipariş <no>" */
  label: string;
  href: string | null;
  linkLabel: string | null;
}

/** `subject` önekli dizgedir (ADR §4.1): ürün, sipariş satırı ya da hesap. Paket ve satır kimliği gösterilmez. */
export function subjectInfo(event: AlertEvent): SubjectInfo | null {
  const separator = event.subject.indexOf(':');
  if (separator < 0) return null;
  const kind = event.subject.slice(0, separator);
  const rest = event.subject.slice(separator + 1);
  if (kind === 'hesap') return { label: 'Tüm hesap', href: null, linkLabel: null };
  if (kind === 'urun' && rest) {
    return {
      label: `Ürün ${rest}`,
      href: `/panel/urunler/${encodeURIComponent(rest)}`,
      linkLabel: 'Ürünü gör',
    };
  }
  if (kind === 'satir') {
    const orderNumber = rest.split('|')[0] ?? '';
    if (orderNumber) {
      return {
        label: `Sipariş ${orderNumber}`,
        href: ordersHref({ range: parseRange(null), q: orderNumber }),
        linkLabel: 'Siparişi gör',
      };
    }
  }
  return null;
}

/** Eylem hatası: kullanıcıya gösterilecek Türkçe cümle ve listenin yeniden yüklenmesi gerekip gerekmediği. */
export function describeAlertError(error: unknown): { text: string; reload: boolean } {
  if (error instanceof NetworkError) {
    return { text: describeApiError(error, ''), reload: false };
  }
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return {
        text: 'Bu uyarı başka bir yerde değişmiş olabilir. Liste yenilendi; durumu kontrol edip tekrar deneyin.',
        reload: true,
      };
    }
    if (error.status === 412) {
      return {
        text: 'Eşikler siz düzenlerken başka biri tarafından değiştirildi. Güncel değerler yüklendi; değişikliğinizi kontrol edip tekrar kaydedin.',
        reload: true,
      };
    }
    if (error.status === 404) {
      return { text: 'Bu uyarı artık bulunamıyor. Liste yenilendi.', reload: true };
    }
    if (error.status === 429) {
      return {
        text:
          describeRateLimitWait(error.retryAfterSeconds) ??
          'Çok fazla deneme yaptınız. Birkaç dakika sonra tekrar deneyin.',
        reload: false,
      };
    }
    if (error.status === 401) {
      return { text: 'Oturumunuz sona erdi. Yeniden giriş yapın.', reload: false };
    }
    if (error.status === 403 && error.code === 'forbidden') {
      return {
        text: 'Bu işlem için yetkiniz yok. Susturma ve eşikler hesap yöneticisine aittir.',
        reload: false,
      };
    }
    if (error.status === 422) {
      return { text: 'Girilen değer geçerli değil. Kontrol edip tekrar deneyin.', reload: false };
    }
  }
  return { text: describeApiError(error, 'İşlem tamamlanamadı. Tekrar deneyin.'), reload: false };
}
