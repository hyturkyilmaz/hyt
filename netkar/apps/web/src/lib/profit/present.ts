// Panel sunum kuralları (denetim 2026-11-09 kâr ayarları raporu §7). Saf fonksiyonlar: bileşenler yalnız
// bu çıktıyı çizer, böylece "net kâr null ise asla 0,00 yazılmaz" gibi kurallar tek yerde ve testle korunur.
import type {
  CertaintyLabel,
  LineComparison,
  LossReason,
  MissingItemCode,
  MissingLineCounts,
  PeriodTotals,
  ProductProfitItem,
  ProfitLine,
  SourceCode,
} from '@/lib/api/profit';
import { absAtLeast, addDecimal, decimalSign, subtractDecimal } from '@/lib/profit/decimal-math';

export type BadgeTone = 'neutral' | 'profit' | 'loss' | 'warning' | 'info';

export interface BadgeSpec {
  label: string;
  tone: BadgeTone;
}

// --------------------------------------------------------------------------- eksik kalemler

const MISSING_ITEM_LABELS: Record<MissingItemCode, string> = {
  urun_maliyeti: 'ürün maliyeti',
  kargo_gonderi: 'kargo',
  platform_hizmet_bedeli: 'hizmet bedeli',
};

const MISSING_ORDER: readonly MissingItemCode[] = [
  'urun_maliyeti',
  'kargo_gonderi',
  'platform_hizmet_bedeli',
];

export function missingItemNames(codes: readonly MissingItemCode[]): string[] {
  return MISSING_ORDER.filter((code) => codes.includes(code)).map(
    (code) => MISSING_ITEM_LABELS[code],
  );
}

/** Dönem sayımlarından (kalem başına eksik satır sayısı) eksik kalem adları, kanonik sırada. */
export function missingItemNamesFromCounts(counts: MissingLineCounts): string[] {
  return missingItemNames(MISSING_ORDER.filter((code) => counts[code] > 0));
}

// --------------------------------------------------------------------------- net kâr

export type NetProfitDisplay =
  | { kind: 'value'; value: string }
  | { kind: 'uncomputable'; missing: string[] }
  | { kind: 'cancelled' };

/** Kural 1 ve 10: null net kâr "Hesaplanamadı" (eksik kalem adlarıyla); iptal "İptal"; asla 0,00 değil. */
export function netProfitDisplay(
  netProfit: string | null,
  missing: readonly MissingItemCode[],
  certainty: CertaintyLabel,
): NetProfitDisplay {
  if (certainty === 'iptal' || certainty === 'yok') return { kind: 'cancelled' };
  if (netProfit === null) return { kind: 'uncomputable', missing: missingItemNames(missing) };
  return { kind: 'value', value: netProfit };
}

// --------------------------------------------------------------------------- kesinlik ve kaynak

/** "Kesin" rozeti yalnız kesinlik alanından gelir (kural 4). */
export function certaintyBadge(certainty: CertaintyLabel): BadgeSpec | null {
  switch (certainty) {
    case 'kesin':
      return { label: 'Kesin', tone: 'info' };
    case 'tahmini':
      return { label: 'Tahmini', tone: 'warning' };
    case 'eksik':
      return { label: 'Eksik', tone: 'loss' };
    case 'iptal':
      return { label: 'İptal', tone: 'neutral' };
    default:
      return null;
  }
}

/** Kalem kaynağı etiketi (satır kırılımındaki "Kaynak" sütunu). */
export function sourceBadge(source: SourceCode): BadgeSpec {
  switch (source) {
    case 'kesin':
    case 'kesin_dagitim':
      return { label: 'Kesin', tone: 'info' };
    case 'tahmini':
    case 'dagitim_tahmini':
      return { label: 'Tahmini', tone: 'warning' };
    case 'kullanici':
      return { label: 'Girdiğiniz', tone: 'neutral' };
    case 'eslesen':
      return { label: 'Eşleşen', tone: 'neutral' };
    case 'eksik':
      return { label: 'Eksik', tone: 'loss' };
    default:
      return { label: 'Yok', tone: 'neutral' };
  }
}

// --------------------------------------------------------------------------- zarar nedeni

const LOSS_REASON_BADGES: Record<LossReason, BadgeSpec> = {
  net_profit: { label: 'Zarar', tone: 'loss' },
  contribution_before_cost: { label: 'Maliyetsiz bile zarar', tone: 'loss' },
  known_expenses: { label: 'Bilinen giderlerle bile zarar', tone: 'loss' },
};

/**
 * Kural 5: `loss_reason` üç değeri ayrı rozet alır. Net kârı null olup zarar kesin değilse ürün
 * "Belirsiz"dir, "kârlı" değildir. İptal ürün rozet almaz.
 */
export function lossBadge(item: ProductProfitItem): BadgeSpec | null {
  if (item.certainty === 'iptal' || item.certainty === 'yok') return null;
  if (item.loss_reason) return LOSS_REASON_BADGES[item.loss_reason];
  if (item.net_profit === null) return { label: 'Belirsiz', tone: 'warning' };
  return null;
}

// --------------------------------------------------------------------------- dönem özeti

export interface SummaryBanner {
  title: string;
  detail: string;
  /** Ürün maliyeti eksik satırlar için ayrı satır (ayar bandına karışmaz). */
  costLine: string | null;
}

export type MetricDisplay =
  { kind: 'value'; value: string } | { kind: 'uncomputable'; missing: string[] };

export interface SummaryView {
  /** Dönemde hiç aktif satır yok */
  empty: boolean;
  partial: boolean;
  /** Başlık net kâr: kısmi dönemde asla dönem net kârı değildir */
  netProfit: MetricDisplay;
  /** Marj ve etiketi: kısmi dönemde yalnız tam satırların marjı */
  margin: MetricDisplay & { label: string | null };
  /** Kısmi dönemde gösterilen "eksiksiz satırlar" bloğu; tam satır sayısı 0 ise null */
  fullLines: { count: number; netProfit: string } | null;
  /** Toplam gider yalnız tam satırlar bloğundan */
  totalExpenses: MetricDisplay & { scopeLabel: string | null };
  /** Dönem düzeyi giderler (ürüne dağıtılmayan); sıfırsa null */
  periodLevelExpenses: string | null;
  banner: SummaryBanner | null;
}

function plural(count: number, text: string): string {
  return `${count} satırda ${text}`;
}

/** Kural 3: kurulum bandı `completeness`'e değil dönemin eksik kalem satır sayılarına bağlıdır. */
export function summaryBanner(counts: MissingLineCounts): SummaryBanner | null {
  const cargo = counts.kargo_gonderi;
  const fee = counts.platform_hizmet_bedeli;
  const cost = counts.urun_maliyeti;
  if (cargo <= 0 && fee <= 0) return null;

  let title: string;
  if (cargo > 0 && fee > 0) {
    title = 'Kargo tarifesi ve hizmet bedeli girilmedi: net kâr bu kalemler hariç hesaplanamaz';
  } else if (cargo > 0) {
    title = 'Kargo tarifesi girilmedi: net kâr bu kalem hariç hesaplanamaz';
  } else {
    title = 'Hizmet bedeli girilmedi: net kâr bu kalem hariç hesaplanamaz';
  }

  const parts: string[] = [];
  if (cargo > 0) parts.push(plural(cargo, 'kargo'));
  if (fee > 0) parts.push(plural(fee, 'hizmet bedeli'));
  const detail = `Bu dönemde ${parts.join(', ')} tahmini eksik.`;

  return { title, detail, costLine: cost > 0 ? `${cost} satırın ürün maliyeti girilmedi.` : null };
}

export function summaryView(totals: PeriodTotals): SummaryView {
  const partial = totals.net_kar_kismi;
  const full = totals.tam_satirlar;
  const counts = totals.eksik_kalem_satir_sayilari;
  const missing = missingItemNamesFromCounts(counts);
  const hasFull = full.satir_sayisi > 0;

  // Kural 2: kısmi dönemde dönem net kârı başlık olmaz; hesaplanamadı ve eksik kalem adları.
  const netProfit: MetricDisplay = partial
    ? { kind: 'uncomputable', missing }
    : { kind: 'value', value: totals.donem_net_kar };

  let margin: SummaryView['margin'];
  if (!partial) {
    margin =
      totals.net_kar_marji_yuzde === null
        ? { kind: 'uncomputable', missing: [], label: null }
        : { kind: 'value', value: totals.net_kar_marji_yuzde, label: null };
  } else if (hasFull && full.net_kar_marji_yuzde !== null) {
    margin = {
      kind: 'value',
      value: full.net_kar_marji_yuzde,
      label: 'Eksiksiz satırların marjı, dönem giderleri hariç',
    };
  } else {
    margin = { kind: 'uncomputable', missing: [], label: null };
  }

  const totalExpenses: SummaryView['totalExpenses'] = hasFull
    ? {
        kind: 'value',
        value: full.toplam_gider,
        scopeLabel: partial ? 'Yalnız eksiksiz satırların gideri' : null,
      }
    : { kind: 'uncomputable', missing: [], scopeLabel: null };

  return {
    empty: totals.satir_sayisi === 0 && totals.siparis_sayisi === 0,
    partial,
    netProfit,
    margin,
    fullLines: partial && hasFull ? { count: full.satir_sayisi, netProfit: full.net_kar } : null,
    totalExpenses,
    periodLevelExpenses:
      decimalSign(totals.donem_duzeyi_giderler_toplami) === 0
        ? null
        : totals.donem_duzeyi_giderler_toplami,
    banner: summaryBanner(counts),
  };
}

// --------------------------------------------------------------------------- satır kırılımı

const WARNING_LABELS: Record<string, string> = {
  MALIYET_EKSIK: 'Maliyet eksik',
  ZARAR: 'Zarar',
  KARGO_DESI_FARKI: 'Kargo desisi farklı',
  BEKLENMEYEN_KESINTI: 'Beklenmeyen kesinti',
  KOMISYON_ORANI_FARKLI: 'Komisyon oranı farklı',
  EKSTRE_IC_TUTARSIZLIK: 'Ekstre tutarsız',
  ESLESMEMIS_HAKEDIS_DUZELTMESI: 'Eşleşmeyen hakediş düzeltmesi',
  KARGO_FATURASI_KDV_BELIRSIZ: 'Kargo faturası KDV durumu belirsiz',
  KARGO_TARIFESI_EKSIK: 'Kargo tarifesi eksik',
  SINIFLANDIRILMAMIS_KESINTI: 'Sınıflandırılmamış kesinti',
  HIZMET_BEDELI_TAHMINI_EKSIK: 'Hizmet bedeli tahmini eksik',
  KARGO_DESI_VARSAYILAN: 'Varsayılan desi kullanıldı',
  IADE_KAYDI_BEKLENIYOR: 'İade kaydı bekleniyor',
};

export function warningLabel(code: string): string {
  return WARNING_LABELS[code] ?? 'Uyarı';
}

export type ExpenseCell = { kind: 'value'; value: string } | { kind: 'missing' };

/** Kural 1: kaynağı `eksik` olan kalem hücresi "eksik" yazar, 0,00 değil. */
export function expenseCell(value: string | null, source: SourceCode): ExpenseCell {
  if (value === null || source === 'eksik') return { kind: 'missing' };
  return { kind: 'value', value };
}

export interface RefundPending {
  /** Ürün stoğa dönerse tahmini net kâr; askıdaki maliyet bilinmiyorsa null */
  estimate: string | null;
  /** Net kâr null ise tahmin eksik giderler hariç kâr üzerindendir ve aynı etiketle gösterilir */
  excludesMissing: boolean;
}

/** Kural 6: IADE_KAYDI_BEKLENIYOR satırında `net_kar + askidaki_urun_maliyeti`. */
export function refundPending(line: ProfitLine): RefundPending | null {
  if (!line.uyarilar.includes('IADE_KAYDI_BEKLENIYOR')) return null;
  const excludesMissing = line.kalemler.net_kar === null;
  const base = line.kalemler.net_kar ?? line.kalemler.eksik_giderler_haric_kar;
  const suspended = line.askidaki_urun_maliyeti;
  return {
    estimate: suspended === null ? null : addDecimal(base, suspended),
    excludesMissing,
  };
}

export interface ComparisonRow {
  label: string;
  estimated: string | null;
  actual: string | null;
}

export function comparisonRows(c: LineComparison): ComparisonRow[] {
  return [
    { label: 'Komisyon', estimated: c.komisyon_tahmini, actual: c.komisyon_kesin },
    { label: 'Kargo', estimated: c.kargo_gonderi_tahmini, actual: c.kargo_gonderi_kesin },
    {
      label: 'Hizmet bedeli',
      estimated: c.platform_hizmet_bedeli_tahmini,
      actual: c.platform_hizmet_bedeli_kesin,
    },
  ];
}

function diff(row: ComparisonRow): string | null {
  if (row.estimated === null || row.actual === null) return null;
  return subtractDecimal(row.actual, row.estimated);
}

/** Kural 7: kargo farkı baskınsa ve tahmin varsayılan desiyle yapıldıysa ipucu. */
export function defaultDesiHint(c: LineComparison): string | null {
  if (!c.kargo_tahmini_varsayilan_desi) return null;
  const [commission, cargo, fee] = comparisonRows(c);
  const cargoDiff = cargo ? diff(cargo) : null;
  if (cargoDiff !== null) {
    const others = [commission, fee]
      .map((row) => (row ? diff(row) : null))
      .filter((d): d is string => d !== null);
    if (!others.every((other) => absAtLeast(cargoDiff, other))) return null;
  }
  return 'Siparişte desi yoksa varsayılan desi farkı olabilir.';
}

// --------------------------------------------------------------------------- dönem etiketi

function dayLabel(iso: string): string {
  const [year, month, day] = iso.split('-');
  return year && month && day ? `${day}.${month}.${year}` : iso;
}

/** "2026-11-01" ve "2026-11-07" için "01.11.2026 - 07.11.2026" (tek gün ise yalnız tarih). */
export function periodLabel(start: string, end: string): string {
  return start === end ? dayLabel(start) : `${dayLabel(start)} - ${dayLabel(end)}`;
}
