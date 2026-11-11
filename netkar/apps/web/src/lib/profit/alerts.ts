// Uyarılar ekranının sunum kuralları (UX incelemesi §8.3, denetim §7 madde 7).
// Kod başına gruplu kartlar: sayı, bir cümle, tek eylem. Metinler docs/12 uyarı kodlarından türetilir ve
// satıcı dilindedir ("satış", "hakediş"); API metni yalnız tanınmayan kodda ve metin düğümü olarak gösterilir.
import type { AlertCount, AlertItem, RangeName, UnavailableAlert } from '@/lib/api/profit';
import { compareCodePoints } from '@/lib/profit/present';
import { defaultOrderFor, productQueryString } from '@/lib/profit/query';

export type AlertGroupId = 'loss' | 'setup' | 'check' | 'other';
export type AlertTone = 'loss' | 'warning' | 'info' | 'neutral';

export type AlertAction =
  | { kind: 'link'; label: string; href: (range: RangeName) => string }
  | { kind: 'details'; label: string };

interface AlertSpec {
  title: string;
  sentence: string;
  group: AlertGroupId;
  tone: AlertTone;
  action: AlertAction | null;
  /** Dönem geneli uyarı: sayı bir kalem sayısı değildir, "Dönem geneli" yazılır */
  periodLevel?: boolean;
}

const lossProductsHref = (range: RangeName) =>
  `/panel/urunler?${productQueryString({
    range,
    sort: 'net_profit',
    order: defaultOrderFor('loss'),
    filter: 'loss',
  })}`;

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
  label: 'Kargo tarifesini gir',
  href: () => '/panel/ayarlar#kargo',
};
const feeAction: AlertAction = {
  kind: 'link',
  label: 'Hizmet bedelini gir',
  href: () => '/panel/ayarlar#hizmet-bedeli',
};

/** Sıra önem sırasıdır: grup içinde kartlar bu sırayla dizilir. Anahtarlar WarningCode değerleridir. */
const CATALOG: Record<string, AlertSpec> = {
  ZARAR: {
    title: 'Zarar eden satışlar',
    sentence:
      'Bu satışların net kârı sıfırın altında. Eksik gider varsa bilinen giderlerle bile zarar görünüyor.',
    group: 'loss',
    tone: 'loss',
    action: { kind: 'link', label: 'Zarar eden ürünleri gör', href: lossProductsHref },
  },
  BEKLENMEYEN_KESINTI: {
    title: 'Beklenmeyen kesintiler',
    sentence:
      'Trendyol ekstrede beklediğimizden fazla kesinti yaptı. Siparişte desi yoksa fark varsayılan desiden kaynaklanabilir.',
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
  },
  KARGO_TARIFESI_EKSIK: {
    title: 'Kargo tarifesi eksik',
    sentence: 'Kargo tarifesi tanımlı olmadığı için tahmini kargo bedeli hesaplanamadı.',
    group: 'setup',
    tone: 'warning',
    action: cargoAction,
  },
  HIZMET_BEDELI_TAHMINI_EKSIK: {
    title: 'Hizmet bedeli eksik',
    sentence:
      'Platform hizmet bedeli tahmini tanımlı olmadığı için bu satışların net kârı hesaplanamıyor.',
    group: 'setup',
    tone: 'warning',
    action: feeAction,
  },
  MALIYET_EKSIK_SATIRLAR_VAR: {
    title: 'Dönem kârı kısmi: maliyet eksik',
    sentence: 'Dönemde maliyeti girilmemiş satışlar var; dönem net kârı bu yüzden kısmi.',
    group: 'setup',
    tone: 'warning',
    action: missingCostAction,
    periodLevel: true,
  },
  KARGO_EKSIK_SATIRLAR_VAR: {
    title: 'Dönem kârı kısmi: kargo eksik',
    sentence: 'Dönemde gönderi kargosu eksik satışlar var; dönem net kârı bu yüzden kısmi.',
    group: 'setup',
    tone: 'warning',
    action: cargoAction,
    periodLevel: true,
  },
  HIZMET_BEDELI_EKSIK_SATIRLAR_VAR: {
    title: 'Dönem kârı kısmi: hizmet bedeli eksik',
    sentence: 'Dönemde hizmet bedeli eksik satışlar var; dönem net kârı bu yüzden kısmi.',
    group: 'setup',
    tone: 'warning',
    action: feeAction,
    periodLevel: true,
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
  },
  IADE_KAYDI_BEKLENEN_SATIRLAR_VAR: {
    title: 'Dönemde iade kaydı beklenen satışlar var',
    sentence: 'Bazı iadelerin kaydı henüz gelmedi; dönem rakamı bu yüzden ihtiyatlı hesaplandı.',
    group: 'check',
    tone: 'info',
    action: null,
    periodLevel: true,
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
  for (const [code, { count, message }] of merged) {
    const spec = Object.hasOwn(CATALOG, code) ? CATALOG[code] : undefined;
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
          }
        : {
            code,
            title: 'Tanınmayan uyarı',
            sentence: unknownSentence(message),
            group: 'other',
            tone: 'neutral',
            count,
            periodLevel: false,
            action: null,
            known: false,
          },
    );
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

/** Kartlardaki uyarıların toplamı; dönem geneli uyarılar da birer uyarı sayılır. */
export function totalAlertCount(counts: readonly AlertCount[]): number {
  return buildAlertGroups(counts).reduce(
    (sum, group) => sum + group.cards.reduce((inner, card) => inner + card.count, 0),
    0,
  );
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

/** Beklenmeyen kesinti satırı: sipariş, barkod ve fark (ekstredeki kesinti tahmini bu kadar aştı). */
export interface DeductionRow {
  key: string;
  orderNumber: string | null;
  barcode: string | null;
  difference: string | null;
  threshold: string | null;
}

export function deductionRows(items: readonly AlertItem[]): DeductionRow[] {
  return items.map((item, index) => ({
    key: `${item.package_id ?? 'p'}-${item.line_id ?? index}-${index}`,
    orderNumber: item.order_number ?? null,
    barcode: item.barcode ?? null,
    difference: item.difference ?? null,
    threshold: item.threshold ?? null,
  }));
}
