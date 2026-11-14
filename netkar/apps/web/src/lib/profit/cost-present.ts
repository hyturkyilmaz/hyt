// Ürün maliyeti ekranı sunum ve hata yardımcıları: Türkçe cümleler koddan üretilir, sunucu metni (dosya geçersiz
// ayrıntısı dışında) arayüze taşınmaz.
import { ApiError, NetworkError } from '@/lib/api/client';
import {
  IMPORT_EXTENSIONS,
  IMPORT_MAX_BYTES,
  IMPORT_MAX_ROWS,
  type CostOut,
  type ImportIssue,
  type ImportReport,
} from '@/lib/api/product-costs';
import { parsedEcho, type ParsedEcho } from '@/components/settings/settings-forms';
import { formatTRY } from '@/lib/format';
import { formatLongDate } from '@/lib/profit/settings-input';

// --------------------------------------------------------------------------- maliyet gösterimi

/** "54,50 TL KDV hariç, %20 KDV" */
export function costSummary(cost: CostOut): string {
  return `${formatTRY(cost.unit_cost_excl_vat, { style: 'code' })} KDV hariç, %${cost.vat_rate} KDV`;
}

/** "1 Kasım 2026 tarihinden beri geçerli" */
export function costSince(cost: CostOut): string {
  return `${formatLongDate(cost.valid_from)} tarihinden beri geçerli`;
}

/**
 * Yazılan tutarın yansıması: "Kaydedilecek: 54,50 TL KDV hariç, %20 KDV". Okunamayan ya da belirsiz yazım (12.5,
 * 12,550) uyarı olarak döner; böylece "12.550" sessizce başka bir tutara dönüşmez. Boş metinde null.
 */
export function costEcho(text: string, vatRate: string): ParsedEcho | null {
  const echo = parsedEcho(text, { kind: 'money', includesVat: false, vatRate });
  if (!echo || echo.tone === 'warn') return echo;
  return { tone: 'ok', text: `${echo.text}, %${vatRate} KDV` };
}

// --------------------------------------------------------------------------- tek kayıt hataları

/** 422 dışındaki kayıt hataları (422 alan hataları alanın yanına gider). */
export function describeCostSaveError(error: unknown): string {
  if (error instanceof NetworkError) {
    return 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin. Maliyet kaydedilmedi.';
  }
  if (error instanceof ApiError) {
    if (error.status === 403 && error.code === 'csrf-failed') {
      return 'İstek doğrulanamadı. Sayfayı yenileyip tekrar deneyin.';
    }
    if (error.status === 403) {
      return 'Maliyet girmek için sahip ya da yönetici olmanız gerekir. Görüntüleyici hesabı yalnız okuyabilir.';
    }
    if (error.status === 404) {
      return 'Mağaza hesabı bulunamadı. Sayfayı yenileyip tekrar deneyin.';
    }
    if (error.status === 429) {
      return 'Çok fazla kayıt yaptınız. Birkaç dakika sonra tekrar deneyin.';
    }
    if (error.status >= 500) {
      return 'Bir sorun oluştu, maliyet kaydedilmedi. Lütfen biraz sonra tekrar deneyin.';
    }
  }
  return 'Maliyet kaydedilemedi. Tekrar deneyin.';
}

export function describeCostLoadError(error: unknown): string {
  if (error instanceof NetworkError) {
    return 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.';
  }
  if (error instanceof ApiError && error.status === 429) {
    return 'Şu an çok fazla istek var. Birkaç saniye sonra tekrar deneyin.';
  }
  if (error instanceof ApiError && error.status === 404) {
    return 'Mağaza hesabı bulunamadı.';
  }
  return 'Ürünler yüklenemedi. Tekrar deneyin.';
}

// --------------------------------------------------------------------------- toplu içe aktarma

export type FileCheck = { ok: true } | { ok: false; message: string };

function megabytes(bytes: number): string {
  return String(Math.floor(bytes / (1024 * 1024)));
}

/** Yüklemeden önce hızlı denetim: uzantı ve boyut (sunucu yine de denetler: imza ve içerik). */
export function checkImportFile(file: { name: string; size: number }): FileCheck {
  const name = file.name.toLowerCase();
  if (!IMPORT_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return { ok: false, message: 'Yalnız .csv veya .xlsx dosyası yüklenebilir.' };
  }
  if (file.size === 0) return { ok: false, message: 'Seçtiğiniz dosya boş.' };
  if (file.size > IMPORT_MAX_BYTES) {
    return {
      ok: false,
      message: `Dosya en fazla ${megabytes(IMPORT_MAX_BYTES)} MB olabilir. Daha küçük parçalara bölün.`,
    };
  }
  return { ok: true };
}

/** Bekleme süresi insan okur biçimde: 120 sn'ye kadar saniye, 2 saate kadar dakika, sonrası saat (yukarı yuvarlanır). */
export function formatWait(seconds: number): string {
  if (seconds < 120) return `${seconds} saniye`;
  if (seconds < 7200) return `${Math.ceil(seconds / 60)} dakika`;
  return `${Math.ceil(seconds / 3600)} saat`;
}

function waitSentence(error: ApiError, fallback: string): string {
  const wait = error.retryAfterSeconds;
  return wait ? `${formatWait(wait)} sonra tekrar deneyin.` : fallback;
}

/** Dosya tarayıcıda okunamadı (silindi, taşındı, izin yok); ağ hatası DEĞİLDİR. */
export class FileReadError extends Error {
  constructor() {
    super('Dosya okunamadı');
    this.name = 'FileReadError';
  }
}

export const FILE_READ_MESSAGE =
  'Dosya okunamadı. Dosya silinmiş ya da taşınmış olabilir; yeniden seçin.';

/** Seçilen dosyayı bir kez belleğe alır: kontrol ve kayıt AYNI içeriği gönderir (diskte değişse de). */
export async function snapshotFile(file: File): Promise<File> {
  try {
    const buffer =
      typeof file.arrayBuffer === 'function'
        ? await file.arrayBuffer()
        : await new Promise<ArrayBuffer>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as ArrayBuffer);
            reader.onerror = () => reject(reader.error);
            reader.readAsArrayBuffer(file);
          });
    return new File([buffer], file.name, { type: file.type });
  } catch {
    throw new FileReadError();
  }
}

/** Sunucu içe aktarma hatası -> Türkçe cümle. `import-file-invalid` ayrıntısı sunucunun sabit metnidir. */
export function describeImportError(error: unknown): string {
  if (error instanceof FileReadError) return FILE_READ_MESSAGE;
  if (error instanceof NetworkError) {
    return 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin. Hiçbir şey kaydedilmedi.';
  }
  if (!(error instanceof ApiError)) return 'Dosya işlenemedi. Tekrar deneyin.';
  switch (error.code) {
    case 'payload-too-large':
      return `Dosya en fazla ${megabytes(IMPORT_MAX_BYTES)} MB olabilir. Daha küçük parçalara bölün.`;
    case 'import-unsupported-type':
      return 'Yalnız .csv veya .xlsx dosyası yüklenebilir.';
    case 'import-unavailable':
      return 'XLSX içe aktarma şu an kapalı. Dosyanızı CSV olarak kaydedip yükleyin.';
    case 'import-in-progress':
      return `Bu mağaza için bir içe aktarma zaten sürüyor. Bitmesini bekleyin; ${waitSentence(error, 'bitince tekrar deneyin.')}`;
    case 'import-busy':
      return `Şu an çok sayıda dosya işleniyor. ${waitSentence(error, 'Kısa süre sonra tekrar deneyin.')}`;
    case 'import-file-invalid':
      return error.detail ? `Dosya okunamadı. ${error.detail}` : 'Dosya okunamadı.';
    case 'import-too-many-rows':
      return `Dosyada ${IMPORT_MAX_ROWS.toLocaleString('tr-TR')} veri satırından fazlası var. Dosyayı bölüp ayrı ayrı yükleyin.`;
    case 'csrf-failed':
      return 'İstek doğrulanamadı. Sayfayı yenileyip tekrar deneyin.';
    default:
      break;
  }
  if (error.status === 403) {
    return 'Maliyet yüklemek için sahip ya da yönetici olmanız gerekir.';
  }
  if (error.status === 429 || error.status === 503) {
    return `Şu an çok fazla içe aktarma var. ${waitSentence(error, 'Biraz sonra tekrar deneyin.')}`;
  }
  if (error.status === 422) return 'Dosya geçerli değil. Şablondaki sütunları kullanın.';
  if (error.status >= 500)
    return 'Bir sorun oluştu, hiçbir şey kaydedilmedi. Biraz sonra tekrar deneyin.';
  return 'Dosya işlenemedi. Tekrar deneyin.';
}

/** Şablon indirme hatası -> Türkçe cümle (401, 404, 429, 5xx ve ağ). */
export function describeTemplateError(error: unknown): string {
  if (error instanceof NetworkError) {
    return 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.';
  }
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Oturumunuz kapanmış. Sayfayı yenileyip yeniden giriş yapın.';
    if (error.status === 403) return 'Şablonu indirmek için yetkiniz yok.';
    if (error.status === 404) return 'Mağaza hesabı bulunamadı. Sayfayı yenileyip tekrar deneyin.';
    if (error.status === 429) {
      return `Şablon indirme sınırına ulaştınız. ${waitSentence(error, 'Biraz sonra tekrar deneyin.')}`;
    }
    if (error.status >= 500) return 'Şablon şu an hazırlanamadı. Biraz sonra tekrar deneyin.';
  }
  return 'Şablon indirilemedi. Tekrar deneyin.';
}

export const TEMPLATE_TRUNCATED_NOTE = `Şablon ilk ${IMPORT_MAX_ROWS.toLocaleString('tr-TR')} ürünle sınırlı; ürün sayınız daha fazla. Listede olmayan ürünlerin maliyetini ürün listesinden girin ya da kendi dosyanızı aynı sütunlarla hazırlayın.`;

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isIssue(value: unknown): value is ImportIssue {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return (
    isCount(v.row) &&
    typeof v.column === 'string' &&
    typeof v.message === 'string' &&
    (v.value === null || typeof v.value === 'string')
  );
}

/** Ham yanıtı doğrular; şekil beklenenden farklıysa null (arayüz uydurma sayı göstermez). */
export function parseImportReport(raw: unknown): ImportReport | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (
    typeof r.dry_run !== 'boolean' ||
    typeof r.committed !== 'boolean' ||
    typeof r.format !== 'string' ||
    !isCount(r.total) ||
    !isCount(r.valid) ||
    !isCount(r.invalid) ||
    !isCount(r.skipped) ||
    !isCount(r.unknown_barcodes) ||
    !(r.created === null || isCount(r.created)) ||
    !(r.updated === null || isCount(r.updated)) ||
    !Array.isArray(r.errors) ||
    !r.errors.every(isIssue) ||
    typeof r.errors_truncated !== 'boolean' ||
    !Array.isArray(r.ignored_columns) ||
    !r.ignored_columns.every((c) => typeof c === 'string')
  ) {
    return null;
  }
  return r as unknown as ImportReport;
}

/** Sunucunun kanonik sütun adları -> okunur ad */
const COLUMN_LABELS: Record<string, string> = {
  barkod: 'Barkod',
  birim_maliyet_kdv_haric: 'Birim maliyet (KDV hariç)',
  kdv_orani: 'KDV oranı',
  gecerlilik_tarihi: 'Geçerlilik tarihi',
};

export function columnLabel(column: string): string {
  return COLUMN_LABELS[column] ?? column;
}

/** Şablonun sütunları (cost_import.py `TEMPLATE_HEADER`, zorunlu olanlar işaretli) */
export const TEMPLATE_COLUMNS: readonly { name: string; required: boolean; help: string }[] = [
  {
    name: 'barkod',
    required: true,
    help: 'Ürün barkodu (harf ve rakamla başlar, en çok 200 karakter).',
  },
  { name: 'baslik', required: false, help: 'Yalnız bilgi için; içe aktarmada yok sayılır.' },
  {
    name: 'birim_maliyet_kdv_haric',
    required: true,
    help: "KDV hariç birim maliyet, TL. 0'dan büyük, en çok 2 ondalık (54,50).",
  },
  { name: 'kdv_orani', required: true, help: 'Yüzde olarak 0, 1, 10 veya 20 (%20 için 20).' },
  {
    name: 'gecerlilik_tarihi',
    required: false,
    help: 'GG.AA.YYYY veya YYYY-AA-GG. Boşsa bugün sayılır.',
  },
];

/** Raporun tek cümlelik özeti (ekran okuyucu ve başlık için) */
export function reportHeadline(report: ImportReport): string {
  if (report.committed) {
    return `${report.created ?? 0} yeni maliyet eklendi, ${report.updated ?? 0} maliyet güncellendi.`;
  }
  if (report.invalid === 0) return `${report.valid} satır kaydedilmeye hazır.`;
  return `${report.invalid} satırda hata var, ${report.valid} satır geçerli.`;
}
