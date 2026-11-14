// Uyarılar ekranının sunum kuralları (UX incelemesi §8.3, denetim §7 madde 7).
// Kod başına gruplu kartlar: sayı, bir cümle, tek eylem. Metinler docs/12 uyarı kodlarından türetilir ve
// satıcı dilindedir ("satış", "hakediş"); API metni yalnız tanınmayan kodda ve metin düğümü olarak gösterilir.
import type {
  AlertBreakdownItem,
  AlertCount,
  AlertItem,
  RangeName,
  UnavailableAlert,
} from '@/lib/api/profit';
import { compareDecimal } from '@/lib/profit/decimal-math';
import { compareCodePoints } from '@/lib/profit/present';
import { defaultOrderFor, ordersHref, productQueryString } from '@/lib/profit/query';

export type AlertGroupId = 'loss' | 'setup' | 'check' | 'other';
export type AlertTone = 'loss' | 'warning' | 'info' | 'neutral';

export type AlertAction =
  | {
      kind: 'link';
      label: string;
      /** Görüntüleyici rolünde yazma çağrısı yapan etiket yerine okuma etiketi gösterilir (SU-09). */
      viewerLabel?: string;
      href: (range: RangeName) => string;
    }
  | { kind: 'details'; label: string };

/** Görüntüleyici (salt okunur) rolünde yazma eyleminin yanına eklenen cümle. */
export const VIEWER_NOTE = 'Hesap yöneticiniz girebilir.';

interface AlertSpec {
  title: string;
  sentence: string;
  group: AlertGroupId;
  tone: AlertTone;
  action: AlertAction | null;
  /** Dönem geneli uyarı: sayı bir kalem sayısı değildir, "Dönem geneli" yazılır */
  periodLevel?: boolean;
  /**
   * Dönem geneli kod, aynı sorunun satır koduyla birlikte gelirse ayrı kart olmaz (SU-08): satır kartına
   * `partialNote` olarak katlanır. Satır kodu hiç yoksa dönem kartı kendi başına kalır.
   */
  foldInto?: string;
  /** Bu kartın dönem koduyla katlanınca eklenen cümle */
  partialNote?: string;
  /** Eylem yazma gerektiriyorsa görüntüleyiciye gösterilen cümle */
  viewerNote?: string;
}

// SU-06: ZARAR satır uyarısıdır; sipariş listesi sipariş toplamına göre süzer (ürün listesi ürün toplamına göre).
// Eylem sipariş düzeyine gider ve cümle sayının satır olduğunu açıkça söyler.
const lossOrdersHref = (range: RangeName) => ordersHref({ range, filter: 'loss' });

const missingCostHref = (range: RangeName) =>
  `/panel/urunler?${productQueryString({
    range,
    sort: 'net_profit',
    order: defaultOrderFor('missing_cost'),
    filter: 'missing_cost',
  })}`;

const missingCostAction: AlertAction = {
  kind: 'link',
  label: 'Maliyeti eksik ürünleri gör',
  href: missingCostHref,
};
const cargoAction: AlertAction = {
  kind: 'link',
  // SU-07: tarife girilmiş olsa da bu uyarı üretilebilir; eylem "gir" değil "kontrol et" der.
  label: 'Kargo tarifesini kontrol et',
  viewerLabel: 'Kargo tarifesini gör',
  href: () => '/panel/ayarlar#kargo',
};
const feeAction: AlertAction = {
  kind: 'link',
  label: 'Hizmet bedelini gir',
  viewerLabel: 'Hizmet bedelini gör',
  href: () => '/panel/ayarlar#hizmet-bedeli',
};
const PARTIAL = 'Dönem net kârı bu yüzden kısmi.';

/** Sıra önem sırasıdır: grup içinde kartlar bu sırayla dizilir. Anahtarlar WarningCode değerleridir. */
const CATALOG: Record<string, AlertSpec> = {
  ZARAR: {
    title: 'Zarar eden satışlar',
    sentence:
      'Bu satışların net kârı sıfırın altında; eksik gider varsa bilinen giderlerle bile zarar görünüyor. Sayı satış satırı sayısıdır; sipariş listesi sipariş toplamına göredir, tek satırı zararda olan sipariş kârlı görünebilir.',
    group: 'loss',
    tone: 'loss',
    action: { kind: 'link', label: 'Zarar eden siparişleri gör', href: lossOrdersHref },
  },
  BEKLENMEYEN_KESINTI: {
    title: 'Beklenmeyen kesintiler',
    // SU-05: fark komisyondan, kargodan ya da hizmet bedelinden doğabilir; desi ipucu kart cümlesinde yok,
    // sipariş satırında yalnız `default_desi_used` true ve kargo farkı en büyük kalemken çıkar.
    sentence:
      'Trendyol bu satışlarda beklediğimizden fazla kesti (komisyon, kargo ya da hizmet bedeli). Aşağıda hangi kalemin fazla kesildiği görünür.',
    group: 'loss',
    tone: 'loss',
    action: { kind: 'details', label: 'Etkilenen siparişleri göster' },
  },
  MALIYET_EKSIK: {
    title: 'Ürün maliyeti eksik',
    sentence: 'Maliyeti girilmemiş ürünlerin net kârı hesaplanamıyor.',
    group: 'setup',
    tone: 'warning',
    action: missingCostAction,
    partialNote: PARTIAL,
  },
  KARGO_TARIFESI_EKSIK: {
    title: 'Kargo tarifesi eksik',
    sentence:
      'Bu satışlar için tarifede uygun fiyat bulunamadı (tarife yok, desi tarifedeki en yüksek kademeyi aşıyor ya da desi bilinmiyor); net kâr hesaplanamıyor.',
    group: 'setup',
    tone: 'warning',
    action: cargoAction,
    viewerNote: VIEWER_NOTE,
    partialNote: PARTIAL,
  },
  HIZMET_BEDELI_TAHMINI_EKSIK: {
    title: 'Hizmet bedeli eksik',
    sentence:
      'Platform hizmet bedeli tahmini tanımlı olmadığı için bu satışların net kârı hesaplanamıyor.',
    group: 'setup',
    tone: 'warning',
    action: feeAction,
    viewerNote: VIEWER_NOTE,
    partialNote: PARTIAL,
  },
  MALIYET_EKSIK_SATIRLAR_VAR: {
    title: 'Dönem kârı kısmi: maliyet eksik',
    sentence: 'Dönemde maliyeti girilmemiş satışlar var; dönem net kârı bu yüzden kısmi.',
    group: 'setup',
    tone: 'warning',
    action: missingCostAction,
    periodLevel: true,
    foldInto: 'MALIYET_EKSIK',
  },
  KARGO_EKSIK_SATIRLAR_VAR: {
    title: 'Dönem kârı kısmi: kargo eksik',
    sentence: 'Dönemde gönderi kargosu eksik satışlar var; dönem net kârı bu yüzden kısmi.',
    group: 'setup',
    tone: 'warning',
    action: cargoAction,
    periodLevel: true,
    viewerNote: VIEWER_NOTE,
    foldInto: 'KARGO_TARIFESI_EKSIK',
  },
  HIZMET_BEDELI_EKSIK_SATIRLAR_VAR: {
    title: 'Dönem kârı kısmi: hizmet bedeli eksik',
    sentence: 'Dönemde hizmet bedeli eksik satışlar var; dönem net kârı bu yüzden kısmi.',
    group: 'setup',
    tone: 'warning',
    action: feeAction,
    periodLevel: true,
    viewerNote: VIEWER_NOTE,
    foldInto: 'HIZMET_BEDELI_TAHMINI_EKSIK',
  },
  KARGO_DESI_VARSAYILAN: {
    title: 'Varsayılan desi kullanıldı',
    sentence:
      'Siparişte desi olmadığı için hesabınızın varsayılan desisiyle kargo tarifesi arandı.',
    group: 'check',
    tone: 'info',
    action: {
      kind: 'link',
      label: 'Varsayılan desiyi gör',
      href: () => '/panel/ayarlar#desi',
    },
  },
  KARGO_DESI_FARKI: {
    title: 'Kargo desisi farklı',
    sentence: 'Kargo faturasındaki desi, siparişteki desiden farklı.',
    group: 'check',
    tone: 'warning',
    action: null,
  },
  KOMISYON_ORANI_FARKLI: {
    title: 'Komisyon oranı farklı',
    sentence: 'Ekstredeki komisyon oranı sipariş satışındakinden farklı.',
    group: 'check',
    tone: 'warning',
    action: null,
  },
  STOPAJ_EKSTRE_FARKI: {
    title: 'Stopaj farkı',
    sentence: 'Hesaplanan stopaj ile ekstredeki stopaj farklı.',
    group: 'check',
    tone: 'warning',
    action: null,
  },
  SINIFLANDIRILMAMIS_KESINTI: {
    title: 'Sınıflandırılamayan kesinti',
    sentence: 'Ekstrede türü belirlenemeyen bir kesinti var; ihtiyatla kâra yansıtıldı.',
    group: 'check',
    tone: 'warning',
    action: null,
    periodLevel: true,
  },
  ESLESMEMIS_HAKEDIS_DUZELTMESI: {
    title: 'Eşleşmeyen hakediş düzeltmesi',
    sentence: 'Bir hakediş düzeltmesi hiçbir satışla eşleşmedi.',
    group: 'check',
    tone: 'warning',
    action: null,
  },
  EKSTRE_IC_TUTARSIZLIK: {
    title: 'Ekstre tutarları tutmuyor',
    sentence: 'Ekstre satırının iç tutarları birbirini tutmuyor; veri sorunu olabilir.',
    group: 'check',
    tone: 'warning',
    action: null,
  },
  KARGO_FATURASI_KDV_BELIRSIZ: {
    title: 'Kargo faturası KDV durumu belirsiz',
    sentence:
      'Fatura tutarlarının KDV dahil mi hariç mi olduğu belirlenemedi; KDV hariç kabul edildi.',
    group: 'check',
    tone: 'warning',
    action: null,
  },
  IADE_KAYDI_BEKLENIYOR: {
    title: 'İade kaydı bekleniyor',
    sentence: 'İade kaydı henüz gelmedi; ürün maliyeti ihtiyatla gider bırakıldı.',
    group: 'check',
    tone: 'info',
    action: null,
    partialNote: 'Dönem rakamı bu yüzden ihtiyatlı hesaplandı.',
  },
  IADE_KAYDI_BEKLENEN_SATIRLAR_VAR: {
    title: 'Dönemde iade kaydı beklenen satışlar var',
    sentence: 'Bazı iadelerin kaydı henüz gelmedi; dönem rakamı bu yüzden ihtiyatlı hesaplandı.',
    group: 'check',
    tone: 'info',
    action: null,
    periodLevel: true,
    foldInto: 'IADE_KAYDI_BEKLENIYOR',
  },
};

const CATALOG_ORDER = Object.keys(CATALOG);

export const GROUP_TEXT: Record<AlertGroupId, { title: string; description: string }> = {
  loss: {
    title: 'Para kaybettirenler',
    description: 'Önce bunlara bakın: kâr azalıyor ya da zarar görünüyor.',
  },
  setup: {
    title: 'Kurulum',
    description: 'Eksik bilgiler girilince net kâr hesaplanır.',
  },
  check: {
    title: 'Bilgi ve kontrol',
    description: 'Rakamı etkileyebilecek notlar; çoğu için işlem gerekmez.',
  },
  other: {
    title: 'Diğer uyarılar',
    description: 'Bu uyarı türü ekranda henüz tanımlı değil; açıklama sistemden gelir.',
  },
};

const GROUP_ORDER: readonly AlertGroupId[] = ['loss', 'setup', 'check', 'other'];

/** Tanınmayan koddaki sistem metni en çok bu kadar karakter gösterilir (düz metin düğümü). */
const UNKNOWN_TEXT_LIMIT = 280;

export interface AlertCard {
  code: string;
  title: string;
  sentence: string;
  group: AlertGroupId;
  tone: AlertTone;
  count: number;
  periodLevel: boolean;
  action: AlertAction | null;
  known: boolean;
  /** Dönem geneli kodla katlanmış satır kartında "Dönem net kârı bu yüzden kısmi." gibi cümle */
  partialNote: string | null;
  /** Yazma eylemi içeren kartta görüntüleyiciye gösterilen cümle */
  viewerNote: string | null;
}

export interface AlertGroup {
  id: AlertGroupId;
  title: string;
  description: string;
  cards: AlertCard[];
}

function safeCount(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

/** Başlığa konan kod: sistemden gelir, uzunsa kırpılır (metin düğümü olarak basılır). */
function unknownCode(code: string): string {
  return code.length > 64 ? `${code.slice(0, 64)}...` : code;
}

function unknownSentence(message: unknown): string {
  if (typeof message !== 'string') return 'Bu uyarı için açıklama yok.';
  const text = message.trim();
  if (!text) return 'Bu uyarı için açıklama yok.';
  return text.length > UNKNOWN_TEXT_LIMIT ? `${text.slice(0, UNKNOWN_TEXT_LIMIT)}...` : text;
}

/**
 * Kod başına tek kart: bilinen kodlar katalog sırasıyla, tanınmayanlar sonda kod sırasıyla ("Diğer uyarılar").
 * Aynı kod birden çok gelirse sayılar toplanır; sayısı sıfır ya da geçersiz olanlar atılır. Bilinmeyen kod çökertmez.
 */
export function buildAlertGroups(counts: readonly AlertCount[]): AlertGroup[] {
  const merged = new Map<string, { count: number; message: unknown }>();
  for (const entry of counts) {
    const code = typeof entry?.code === 'string' ? entry.code : '';
    const count = safeCount(entry?.count);
    if (!code || count === 0) continue;
    const prev = merged.get(code);
    merged.set(code, {
      count: (prev?.count ?? 0) + count,
      message: prev?.message ?? entry.message,
    });
  }

  const cards: AlertCard[] = [];
  const folded = new Set<string>();
  for (const [code, { count, message }] of merged) {
    const spec = Object.hasOwn(CATALOG, code) ? CATALOG[code] : undefined;
    // SU-08: aynı sorunun dönem geneli kodu, satır kodu da geldiyse ayrı kart olmaz.
    if (spec?.foldInto && merged.has(spec.foldInto)) {
      folded.add(spec.foldInto);
      continue;
    }
    cards.push(
      spec
        ? {
            code,
            title: spec.title,
            sentence: spec.sentence,
            group: spec.group,
            tone: spec.tone,
            count,
            periodLevel: spec.periodLevel === true,
            action: spec.action,
            known: true,
            partialNote: null,
            viewerNote: spec.viewerNote ?? null,
          }
        : {
            code,
            title: `Tanınmayan uyarı: ${unknownCode(code)}`,
            sentence: unknownSentence(message),
            group: 'other',
            tone: 'neutral',
            count,
            periodLevel: false,
            action: null,
            known: false,
            partialNote: null,
            viewerNote: null,
          },
    );
  }
  for (const card of cards) {
    const note = card.known ? CATALOG[card.code]?.partialNote : undefined;
    if (note && folded.has(card.code)) card.partialNote = note;
  }

  // Tanınmayanlar katalogdan sonra gelir; kendi aralarında kod noktası sırası (API sıralamasıyla aynı).
  const rank = (card: AlertCard) =>
    card.known ? CATALOG_ORDER.indexOf(card.code) : CATALOG_ORDER.length;
  cards.sort((a, b) => {
    const diff = rank(a) - rank(b);
    if (diff !== 0) return diff;
    return compareCodePoints(a.code, b.code);
  });

  return GROUP_ORDER.map((id) => ({
    id,
    ...GROUP_TEXT[id],
    cards: cards.filter((card) => card.group === id),
  })).filter((group) => group.cards.length > 0);
}

/**
 * Uyarı TÜRÜ sayısı (kart sayısı). Satır sayıları toplanmaz: aynı sorun satır ve dönem koduyla iki kez
 * sayılıyor ve ayarsız hesapta binlere çıkıyordu (SU-08, UX §8.3 "uyarı yorgunluğu yaratmasın").
 */
export function alertKindCount(counts: readonly AlertCount[]): number {
  return buildAlertGroups(counts).reduce((sum, group) => sum + group.cards.length, 0);
}

const UNAVAILABLE_NAMES: Record<string, string> = {
  REKLAM_KARI_YIYOR: 'Reklam kârı yiyor',
  IADE_ORANI_ARTISI: 'İade oranı artışı',
};

/** Motorun henüz üretmediği uyarılar: sistem gerekçesi gösterilmez, ad ve tek cümle yeter. */
export function unavailableAlertNames(list: readonly UnavailableAlert[]): string[] {
  const names: string[] = [];
  for (const entry of list) {
    const code = typeof entry?.code === 'string' ? entry.code : '';
    const known = Object.hasOwn(UNAVAILABLE_NAMES, code) ? UNAVAILABLE_NAMES[code] : undefined;
    const name = known ?? 'Henüz hesaplanmayan uyarı';
    if (!names.includes(name)) names.push(name);
  }
  return names;
}

const BREAKDOWN_LABELS: Record<AlertBreakdownItem['item'], string> = {
  commission: 'Komisyon',
  outbound_shipping: 'Kargo',
  platform_service_fee: 'Hizmet bedeli',
};

export interface BreakdownRow {
  label: string;
  estimated: string | null;
  actual: string | null;
  difference: string | null;
  /** false: kalem fark toplamına girmedi (tahmini tanımsız ya da kesin değeri gelmemiş) */
  compared: boolean;
}

/** Beklenmeyen kesinti satırı: sipariş, barkod, fark ve (API verirse) kalem dökümü. */
export interface DeductionRow {
  key: string;
  orderNumber: string | null;
  barcode: string | null;
  difference: string | null;
  threshold: string | null;
  /** null: API kalem dökümü vermedi (eski API) */
  breakdown: BreakdownRow[] | null;
  /** Desi ipucu: yalnız varsayılan desi kullanıldıysa VE kargo farkı en büyük kalemse; dökümsüzde koşullu metin */
  desiHint: string | null;
}

const DESI_HINT = 'Tahmini kargo varsayılan desiyle hesaplandı; siparişin desisini kontrol edin.';
const DESI_HINT_CONDITIONAL =
  'Fark kargodaysa ve varsayılan desi kullanıldıysa siparişin desisini kontrol edin.';

function breakdownRows(list: readonly AlertBreakdownItem[]): BreakdownRow[] {
  return list.map((entry) => ({
    label: BREAKDOWN_LABELS[entry.item] ?? 'Diğer kalem',
    estimated: entry.estimated,
    actual: entry.actual,
    difference: entry.difference,
    compared: entry.compared === true,
  }));
}

/** Kargo, karşılaştırılan kalemler arasında en büyük farka sahip mi (eşitlikte evet). */
function shippingDominates(list: readonly AlertBreakdownItem[]): boolean {
  const compared = list.filter((e) => e.compared && e.difference !== null);
  const cargo = compared.find((e) => e.item === 'outbound_shipping');
  if (!cargo || cargo.difference === null) return false;
  return compared.every(
    (e) => e.difference === null || compareDecimal(cargo.difference!, e.difference) >= 0,
  );
}

export function deductionRows(items: readonly AlertItem[]): DeductionRow[] {
  return items.map((item, index) => {
    const list = Array.isArray(item.breakdown) ? item.breakdown : null;
    let desiHint: string | null;
    if (list === null) desiHint = item.default_desi_used === false ? null : DESI_HINT_CONDITIONAL;
    else desiHint = item.default_desi_used === true && shippingDominates(list) ? DESI_HINT : null;
    return {
      key: `${item.package_id ?? 'p'}-${item.line_id ?? index}-${index}`,
      orderNumber: item.order_number ?? null,
      barcode: item.barcode ?? null,
      difference: item.difference ?? null,
      threshold: item.threshold ?? null,
      breakdown: list === null ? null : breakdownRows(list),
      desiHint,
    };
  });
}
