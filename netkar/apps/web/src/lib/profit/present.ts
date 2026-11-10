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
  ProductTotals,
  ProfitLine,
  SourceCode,
} from '@/lib/api/profit';
import {
  absAtLeast,
  absDecimal,
  addDecimal,
  compareDecimal,
  decimalSign,
  subtractDecimal,
} from '@/lib/profit/decimal-math';

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

/** "a", "a ve b", "a, b ve c" */
export function joinNames(names: readonly string[]): string {
  if (names.length <= 1) return names.join('');
  return `${names.slice(0, -1).join(', ')} ve ${names[names.length - 1]}`;
}

function capitalize(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase('tr-TR') + text.slice(1) : text;
}

// --------------------------------------------------------------------------- net kâr

export type NetProfitDisplay =
  | { kind: 'value'; value: string }
  | { kind: 'uncomputable'; missing: string[] }
  | { kind: 'cancelled' };

/**
 * Kural 10 ve Y-3: "İptal" yalnız gerçekten iptal satırlı (kesinlik `iptal` ya da `yok`) ve zararsız ürün içindir.
 * Aktif satırı olmayıp yalnız satışsız reklamı olan ürün de kesinlikte `yok` alır ama net kârı negatiftir ve
 * `loss_reason` doludur: bu ürün zarar eder, iptal değildir. `lossReason` verilmezse (ürün kırılımı toplamında alan
 * yoktur) net kârın negatif olması yeterlidir; `null` zarar nedeni olmadığı anlamına gelir.
 */
export function shownAsCancelled(
  certainty: CertaintyLabel,
  netProfit: string | null,
  lossReason?: LossReason | null,
): boolean {
  if (certainty !== 'iptal' && certainty !== 'yok') return false;
  const losing = netProfit !== null && decimalSign(netProfit) < 0 && lossReason !== null;
  return !losing;
}

/** Kural 1 ve 10: null net kâr "Hesaplanamadı" (eksik kalem adlarıyla); iptal "İptal"; asla 0,00 değil. */
export function netProfitDisplay(
  netProfit: string | null,
  missing: readonly MissingItemCode[],
  certainty: CertaintyLabel,
  lossReason?: LossReason | null,
): NetProfitDisplay {
  if (shownAsCancelled(certainty, netProfit, lossReason)) return { kind: 'cancelled' };
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
      // Eksik veri zarar değildir: zarar kırmızısı kullanılmaz (UX-10).
      return { label: 'Bilgi eksik', tone: 'warning' };
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
      return { label: 'Eksik', tone: 'warning' };
    default:
      return { label: 'Yok', tone: 'neutral' };
  }
}

// --------------------------------------------------------------------------- zarar nedeni

const LOSS_REASON_BADGES: Record<LossReason, BadgeSpec> = {
  net_profit: { label: 'Zarar', tone: 'loss' },
  contribution_before_cost: { label: 'Maliyet girilmese de zarar', tone: 'loss' },
  known_expenses: { label: 'Bilinen giderlerle bile zarar', tone: 'loss' },
};

/**
 * Kural 5: `loss_reason` üç değeri ayrı rozet alır. Net kârı null olup zarar kesin değilse ürün
 * "Belirsiz"dir, "kârlı" değildir. İptal ürün rozet almaz.
 */
export function lossBadge(item: ProductProfitItem): BadgeSpec | null {
  if (shownAsCancelled(item.certainty, item.net_profit, item.loss_reason)) return null;
  if (item.loss_reason) return LOSS_REASON_BADGES[item.loss_reason];
  if (item.net_profit === null) return { label: 'Belirsiz', tone: 'warning' };
  return null;
}

// --------------------------------------------------------------------------- bilinen kâr (eksik giderler hariç)

export interface KnownProfitView {
  /** "Eksik giderler hariç dönem kârı" ya da ürün için "Eksik giderler hariç kâr"; "net kâr" geçmez */
  label: string;
  /** "(kargo ve hizmet bedeli hariç)"; eksik kalem yoksa null */
  scope: string | null;
  value: string;
  /** Değer sıfırın altı: kırmızı ve "bilinen giderlerle bile zarar" vurgusu */
  loss: boolean;
  badge: BadgeSpec | null;
  /** "Kargo ve hizmet bedeli düşülünce bu rakam azalır." (eksik kalemler gider olduğundan iki işarette de doğru) */
  note: string;
}

function decreaseNote(names: string): string {
  return `${names ? capitalize(names) : 'Eksik giderler'} düşülünce bu rakam azalır.`;
}

/**
 * ADR-0007 §5.2 madde 3 ve UX-21: eksik giderler hariç kâr, net kârın ÜST SINIRIDIR (eksik kalemler giderdir).
 * Pozitifken yeşil kullanılmaz (net kâr sanılmasın); negatifken kesin zarardır.
 */
export function knownProfitView(
  value: string,
  missing: readonly string[],
  scope: 'donem' | 'urun',
): KnownProfitView {
  const loss = decimalSign(value) < 0;
  const names = joinNames(missing);
  return {
    label: scope === 'donem' ? 'Eksik giderler hariç dönem kârı' : 'Eksik giderler hariç kâr',
    scope: names ? `(${names} hariç)` : null,
    value,
    loss,
    badge: loss ? LOSS_REASON_BADGES.known_expenses : null,
    note: decreaseNote(names),
  };
}

// --------------------------------------------------------------------------- dönem özeti

export interface BannerLink {
  /** Ayar formundaki ilgili bölüme derin bağlantı: /panel/ayarlar#kargo, /panel/ayarlar#hizmet-bedeli */
  href: string;
  label: string;
}

export interface SummaryBanner {
  /** Fayda diliyle başlık: "Net kârı görmek için kargo tarifesini girin" */
  title: string;
  detail: string;
  /** Yönlendirme cümlesi, yalnız eksik kalemler için; bilinen kâr rakamı varsa "bu rakamlar" cümlesi eklenir */
  body: string;
  /** Eksik kalem başına ayar formuna bağlantı (kargo, hizmet bedeli) */
  links: BannerLink[];
  /** Ürün maliyeti eksik satırlar için ayrı satır (ayar bandına karışmaz). */
  costLine: string | null;
}

export type MetricDisplay =
  { kind: 'value'; value: string } | { kind: 'uncomputable'; missing: string[] };

/** full: dönem net kârı var; partial: kısmi dönem; partial_no_full_lines: kısmi ve eksiksiz satır yok (G49). */
export type PeriodState = 'full' | 'partial' | 'partial_no_full_lines';

export interface SummaryView {
  /** Dönemde hiç aktif satır yok */
  empty: boolean;
  state: PeriodState;
  partial: boolean;
  /** Başlık net kâr: kısmi dönemde asla dönem net kârı değildir; null `donem_net_kar` da kısmi sayılır */
  netProfit: MetricDisplay;
  /** "Dönem net kârı" ya da "Dönem net kârı hesaplanamadı" */
  netProfitLabel: string;
  /** Eksik giderler hariç dönem kârı; alan yoksa (eski API) null, asla uydurulmaz */
  knownProfit: KnownProfitView | null;
  /** Marj ve etiketi: kısmi dönemde yalnız tam satırların marjı; eksiksiz satır yoksa kart yok */
  margin: (MetricDisplay & { label: string | null }) | null;
  /** Kısmi dönemde gösterilen "eksiksiz satırlar" bloğu; tam satır sayısı 0 ise null */
  fullLines: { count: number; netProfit: string } | null;
  /** Toplam gider yalnız tam satırlar bloğundan; eksiksiz satır yoksa kart yok */
  totalExpenses: (MetricDisplay & { scopeLabel: string | null }) | null;
  /** Dönem düzeyi giderler (ürüne dağıtılmayan); sıfırsa null */
  periodLevelExpenses: string | null;
  banner: SummaryBanner | null;
  /** Kısmi dönemde "bazı ürünlerin kârı belirsiz olabilir" notu; eksik kalem adlarından kurulur */
  partialNote: string | null;
  /** Ürün maliyeti eksik satır cümlesi (kargo ve hizmet bedeli bandından bağımsız) */
  costLine: string | null;
}

function plural(count: number, text: string): string {
  return `${count} satırda ${text}`;
}

/** Ayar formu açık: eksik kalemler için nereye gidileceğini söyler (UX-02), yalnız eksik kalemler için. */
export function setupPrompt(cargo: boolean, fee: boolean, hasKnownProfit: boolean): string {
  const subject =
    cargo && fee ? 'Kargo tarifesi ve hizmet bedeli' : cargo ? 'Kargo tarifesi' : 'Hizmet bedeli';
  const base = `${subject} ayarlardan girilir.`;
  // Bu cümle yalnız ekranda bilinen kâr rakamı gerçekten varken basılır (Y-2); yoksa "bu rakamlar" boşa kalır.
  return hasKnownProfit
    ? `${base} Girene kadar bu rakamlar bilinen giderlerle hesaplanıyor.`
    : base;
}

/** Kural 3: kurulum bandı `completeness`'e değil dönemin eksik kalem satır sayılarına bağlıdır. */
export function summaryBanner(
  counts: MissingLineCounts,
  hasKnownProfit = false,
): SummaryBanner | null {
  const cargo = counts.kargo_gonderi;
  const fee = counts.platform_hizmet_bedeli;
  const cost = counts.urun_maliyeti;
  if (cargo <= 0 && fee <= 0) return null;

  // Ayar formu açıldı: başlık fayda dilidir ve eylemi söyler (UX §2.1 UX-05, UX-02).
  let title: string;
  if (cargo > 0 && fee > 0) {
    title = 'Net kârı görmek için kargo tarifesini ve hizmet bedelini girin';
  } else if (cargo > 0) {
    title = 'Net kârı görmek için kargo tarifesini girin';
  } else {
    title = 'Net kârı görmek için hizmet bedelini girin';
  }
  const links: BannerLink[] = [];
  if (cargo > 0) links.push({ href: '/panel/ayarlar#kargo', label: 'Kargo tarifesini gir' });
  if (fee > 0) links.push({ href: '/panel/ayarlar#hizmet-bedeli', label: 'Hizmet bedelini gir' });

  const parts: string[] = [];
  if (cargo > 0) parts.push(plural(cargo, 'kargo'));
  if (fee > 0) parts.push(plural(fee, 'hizmet bedeli'));
  const detail = `Bu dönemde ${parts.join(', ')} tahmini eksik.`;

  return {
    title,
    detail,
    body: setupPrompt(cargo > 0, fee > 0, hasKnownProfit),
    links,
    costLine: cost > 0 ? `${cost} satırın ürün maliyeti girilmedi.` : null,
  };
}

/** Y-9: kısmi dönem notunun nedeni dönemin gerçek eksik kalem adlarından kurulur. */
export function partialPeriodNote(names: readonly string[]): string | null {
  const joined = joinNames(names);
  return joined
    ? `${capitalize(joined)} eksik olduğundan bazı ürünlerin kârı belirsiz olabilir.`
    : null;
}

export function summaryView(totals: PeriodTotals): SummaryView {
  const full = totals.tam_satirlar;
  const counts = totals.eksik_kalem_satir_sayilari;
  const missing = missingItemNamesFromCounts(counts);
  const hasFull = full.satir_sayisi > 0;
  // K39 Revizyon 1: null `donem_net_kar` kısmi dönemdir. Savunma: bayrak yanlış olsa da null asla değer olmaz.
  const partial = totals.net_kar_kismi || totals.donem_net_kar === null;
  const state: PeriodState = !partial ? 'full' : hasFull ? 'partial' : 'partial_no_full_lines';

  // Kural 2: kısmi dönemde dönem net kârı başlık olmaz; hesaplanamadı ve eksik kalem adları.
  const netProfit: MetricDisplay =
    partial || totals.donem_net_kar === null
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
    // ADR §5.2 madde 4 (UX-11): eksiksiz satır yoksa marj ve toplam gider kartı çizilmez.
    margin = null;
  }

  const totalExpenses: SummaryView['totalExpenses'] = hasFull
    ? {
        kind: 'value',
        value: full.toplam_gider,
        scopeLabel: partial ? 'Yalnız eksiksiz satırların gideri' : null,
      }
    : null;

  const known = totals.donem_eksik_giderler_haric_kar;
  const knownProfit =
    partial && typeof known === 'string' ? knownProfitView(known, missing, 'donem') : null;
  const cost = counts.urun_maliyeti;

  return {
    empty: totals.satir_sayisi === 0 && totals.siparis_sayisi === 0,
    state,
    partial,
    netProfit,
    netProfitLabel: partial ? 'Dönem net kârı hesaplanamadı' : 'Dönem net kârı',
    // Tam dönemde net kâr zaten bilinen kârdır; ayrı rakam yalnız kısmi dönemde gösterilir.
    knownProfit,
    margin,
    fullLines: partial && hasFull ? { count: full.satir_sayisi, netProfit: full.net_kar } : null,
    totalExpenses,
    periodLevelExpenses:
      decimalSign(totals.donem_duzeyi_giderler_toplami) === 0
        ? null
        : totals.donem_duzeyi_giderler_toplami,
    banner: summaryBanner(counts, knownProfit !== null),
    partialNote: partial ? partialPeriodNote(missing) : null,
    costLine: cost > 0 ? `${cost} satırın ürün maliyeti girilmedi.` : null,
  };
}

/** ADR-0007 §5.2 madde 6: rapor alt bilgisi. Alan yoksa (eski API) null; sayı uydurulmaz. */
export function settingsRevisionLabel(revision: number | null | undefined): string | null {
  return typeof revision === 'number' && Number.isInteger(revision) && revision >= 0
    ? `Ayar sürümü ${revision}`
    : null;
}

// --------------------------------------------------------------------------- zarar eden ürünler (özet ve liste)

export interface LossDisplay {
  /** Zarar tutarı, işaretsiz (mutlak değer): "₺4,00". Yön ok ve renkle, "zarar" sözcüğüyle anlatılır. */
  magnitude: string;
  /** Negatif tutar: net kâr ya da (null ise) eksik giderler hariç kâr; sıralama ve kırmızı ProfitValue için */
  amount: string;
  /** false: net kâr bilinmiyor, tutar "en az" zarardır */
  exact: boolean;
  /** Eksik kalemler düşülünce rakamın azalacağı notu; kesin zararda null */
  note: string | null;
}

/**
 * UX-07: kesin zarardaki ürün nötr görünmez. Net kâr null olsa da `loss_reason` doluysa bilinen giderlerle
 * bile zarar kesindir; eksik kalemler gider olduğundan bilinen rakam "en az" zarardır. Y-3: satışsız reklamı
 * yüzünden zarardaki ürün (kesinlik `yok`) da zarar gösterir.
 */
export function lossDisplay(item: ProductProfitItem): LossDisplay | null {
  if (shownAsCancelled(item.certainty, item.net_profit, item.loss_reason)) return null;
  if (item.net_profit !== null) {
    return item.loss_reason !== null && decimalSign(item.net_profit) < 0
      ? {
          magnitude: absDecimal(item.net_profit),
          amount: item.net_profit,
          exact: true,
          note: null,
        }
      : null;
  }
  if (item.loss_reason === null) return null;
  const names = joinNames(missingItemNames(item.missing_items));
  return {
    magnitude: absDecimal(item.contribution_excl_missing),
    amount: item.contribution_excl_missing,
    exact: false,
    note: decreaseNote(names),
  };
}

/** Kod noktası sırası (Python `str` karşılaştırması ve API sıralamasıyla aynı); `localeCompare` kullanılmaz. */
export function compareCodePoints(a: string, b: string): -1 | 0 | 1 {
  const left = Array.from(a);
  const right = Array.from(b);
  const length = Math.min(left.length, right.length);
  for (let i = 0; i < length; i += 1) {
    const x = left[i]!.codePointAt(0)!;
    const y = right[i]!.codePointAt(0)!;
    if (x !== y) return x < y ? -1 : 1;
  }
  return left.length === right.length ? 0 : left.length < right.length ? -1 : 1;
}

/**
 * UX-03 ve UX-04: en çok zarar ettiren ürünler, en büyük zarar üstte. API (AD-04) null net kârlı kesin zararı
 * bilinen tutarla zaten sıralar ve ekran `limit` ile yalnız ilk kayıtları ister; bu yeniden sıralama savunmadır.
 * Eşitlikte barkod kod noktasına göre artan.
 */
export function topLossItems(
  items: readonly ProductProfitItem[],
  limit: number,
): { item: ProductProfitItem; loss: LossDisplay }[] {
  const rows: { item: ProductProfitItem; loss: LossDisplay }[] = [];
  for (const item of items) {
    const loss = lossDisplay(item);
    if (loss) rows.push({ item, loss });
  }
  rows.sort(
    (a, b) =>
      compareDecimal(a.loss.amount, b.loss.amount) ||
      compareCodePoints(a.item.barcode, b.item.barcode),
  );
  return rows.slice(0, limit);
}

// --------------------------------------------------------------------------- ürün kırılımı özet kartı

/** `partial`: bilinen tutar ve eksik satır sayısı ("₺225,00 + 2 satırda eksik"); toplam eksiği kapatılmış gibi gösterilmez */
export type TotalsCellSpec =
  | { kind: 'value'; value: string }
  | { kind: 'partial'; value: string; count: number }
  | { kind: 'missing' };

export interface BreakdownRow {
  key: string;
  label: string;
  cell: TotalsCellSpec;
}

function counted(count: number, value: string): TotalsCellSpec {
  return count > 0 ? { kind: 'partial', value, count } : { kind: 'value', value };
}

/**
 * UX-09: ürün kırılımı kartı gider kalemlerinin hepsini listeler ki satırlar toplanınca net kâr tutsun.
 * Sıfır olan isteğe bağlı kalemler (kargo iadesi, ceza, değişken gider, reklam) gizlenir.
 */
export function productBreakdownRows(product: ProductTotals): BreakdownRow[] {
  const counts = product.eksik_kalem_satir_sayilari;
  const rows: BreakdownRow[] = [
    {
      key: 'satis',
      label: 'Net satış (KDV hariç)',
      cell: { kind: 'value', value: product.net_satis_kdv_haric },
    },
    {
      key: 'maliyet',
      label: 'Ürün maliyeti',
      cell:
        product.urun_maliyeti === null
          ? { kind: 'missing' }
          : counted(counts.urun_maliyeti, product.urun_maliyeti),
    },
    { key: 'komisyon', label: 'Komisyon', cell: { kind: 'value', value: product.komisyon } },
    {
      key: 'kargo',
      label: 'Kargo (gönderi)',
      cell: counted(counts.kargo_gonderi, product.kargo_gonderi),
    },
  ];
  const optional: [string, string, string | undefined][] = [
    ['kargo_iade', 'Kargo iadesi', product.kargo_iade],
  ];
  for (const [key, label, value] of optional) {
    if (value !== undefined && decimalSign(value) !== 0) {
      rows.push({ key, label, cell: { kind: 'value', value } });
    }
  }
  rows.push({
    key: 'hizmet',
    label: 'Platform hizmet bedeli',
    cell: counted(counts.platform_hizmet_bedeli, product.platform_hizmet_bedeli),
  });
  const tail: [string, string, string | undefined][] = [
    ['ceza', 'Ceza', product.ceza],
    ['degisken', 'Değişken giderler', product.degisken_giderler],
    ['reklam', 'Reklam', product.reklam_satirlara_dagitilan],
    ['reklam_satissiz', 'Satış getirmeyen reklam', product.reklam_satissiz],
  ];
  for (const [key, label, value] of tail) {
    if (value !== undefined && decimalSign(value) !== 0) {
      rows.push({ key, label, cell: { kind: 'value', value } });
    }
  }
  return rows;
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
