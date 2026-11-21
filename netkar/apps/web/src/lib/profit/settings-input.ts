// Ayar formu girdi yardımcıları: tr-TR ondalık ayrıştırma, tarih (İstanbul takvim günü) ve sunum biçimleri.
// Para ve oran Decimal DİZGESİDİR; float kullanılmaz (K01). Doğrulama sunucudaki kurallarla tutarlıdır
// (docs/12 K33 doğrulama tablosu); sunucu doğrulaması esastır, bu yalnız hızlı geri bildirimdir.
import { groupThousands } from '@/lib/decimal';

// --------------------------------------------------------------------------- ondalık girdi

export type DecimalParse =
  | { ok: true; value: string }
  | { ok: false; reason: 'empty' | 'invalid' | 'too_many_decimals' | 'ambiguous' };

const MAX_INTEGER_DIGITS = 15;
const SPACES = '\\s\u00a0\u202f';
const EDGE_SPACES = new RegExp(`^[${SPACES}]+|[${SPACES}]+$`, 'g');
const INNER_SPACE = new RegExp(`[${SPACES}]`);
const ALLOWED_CHARS = new RegExp(`^[0-9.,${SPACES}]+$`);
const GROUP_SPLIT = new RegExp(`[.${SPACES}]`);

function stripLeadingZeros(digits: string): string {
  const stripped = digits.replace(/^0+(?=\d)/, '');
  return stripped === '' ? '0' : stripped;
}

/**
 * Kullanıcının yazdığı sayıyı kanonik Decimal dizgesine çevirir. TEK KURAL (para, desi ve oran alanlarının hepsi):
 *  - Ondalık ayracı yalnız VİRGÜLDÜR ("54,50"). Virgülden sonra hane sayısı sınırı aşarsa para alanında bile
 *    binlik sayılmaz, reddedilir ("12,550" -> too_many_decimals); sessizce 1000 kat değişen tutar olmaz.
 *  - Nokta (ya da boşluk) yalnız BİNLİK ayracıdır ve yalnız doğru gruplamayla kabul edilir: ilk grup 1-3 hane
 *    (başında 0 yok), sonrakiler tam 3 hane ("1.250", "1.250,50", "1.250.000").
 *  - Gruplamaya uymayan tek nokta ("12.5", "54.50", "0.500") belirsizdir (ondalık mı binlik mi) ve reddedilir
 *    (ambiguous); kullanıcıdan virgül istenir.
 * Negatif, üstel gösterim, harf ve İngilizce biçim ("1,250.50") reddedilir.
 */
export function parseDecimalInput(text: string, maxFraction: number): DecimalParse {
  const trimmed = text.replace(EDGE_SPACES, '');
  if (trimmed === '') return { ok: false, reason: 'empty' };
  if (!ALLOWED_CHARS.test(trimmed)) return { ok: false, reason: 'invalid' };

  const commaCount = trimmed.split(',').length - 1;
  if (commaCount > 1) return { ok: false, reason: 'invalid' };
  const commaAt = trimmed.indexOf(',');
  const integerRaw = commaAt >= 0 ? trimmed.slice(0, commaAt) : trimmed;
  const fraction = commaAt >= 0 ? trimmed.slice(commaAt + 1) : '';

  if (commaAt >= 0) {
    // "12," ve "1,5.3" geçersiz; hane sınırı aşımı ayrı nedenle bildirilir
    if (!/^\d+$/.test(fraction)) return { ok: false, reason: 'invalid' };
    if (fraction.length > maxFraction) return { ok: false, reason: 'too_many_decimals' };
  }

  let integer: string;
  if (/^\d*$/.test(integerRaw)) {
    integer = integerRaw;
  } else {
    // Binlik gruplama: nokta ya da boşluk (ikisi birlikte olamaz)
    if (integerRaw.includes('.') && INNER_SPACE.test(integerRaw)) {
      return { ok: false, reason: 'invalid' };
    }
    const groups = integerRaw.split(GROUP_SPLIT);
    const grouped = groups.every((group, index) =>
      index === 0 ? /^[1-9]\d{0,2}$/.test(group) : /^\d{3}$/.test(group),
    );
    if (!grouped) {
      const singleDot = commaAt < 0 && /^\d+\.\d+$/.test(integerRaw);
      return { ok: false, reason: singleDot ? 'ambiguous' : 'invalid' };
    }
    integer = groups.join('');
  }
  // Gruplamasız tek nokta ("12.5", "0.500") buraya gelmeden yukarıda ambiguous döner
  if (integer === '' && fraction === '') return { ok: false, reason: 'invalid' };
  if (integer.length > MAX_INTEGER_DIGITS) return { ok: false, reason: 'invalid' };
  const whole = stripLeadingZeros(integer === '' ? '0' : integer);
  return { ok: true, value: fraction ? `${whole}.${fraction}` : whole };
}

/** İki ondalığa tamamlar ("54" -> "54.00", "54.5" -> "54.50"); gönderilen tutar kuruş biçimindedir. */
export function toMoneyString(value: string): string {
  const [whole = '0', fraction = ''] = value.split('.');
  return `${whole}.${fraction.padEnd(2, '0').slice(0, 2)}`;
}

/** Kayıtlı değer ("54.50") düzenleme alanına tr-TR biçiminde konur ("54,50"). */
export function toInputText(value: string): string {
  return value.replace('.', ',');
}

/** Gösterim: binlik nokta, ondalık virgül; sondaki sıfırlar atılır, en az `minFraction` hane kalır. */
export function formatPlainNumber(value: string, maxFraction: number, minFraction = 0): string {
  const [whole = '0', rawFraction = ''] = value.replace(/^-/, '').split('.');
  let fraction = rawFraction.slice(0, maxFraction);
  fraction = fraction.replace(/0+$/, '').padEnd(minFraction, '0');
  const sign = value.startsWith('-') ? '-' : '';
  const grouped = groupThousands(whole === '' ? '0' : whole.replace(/^0+(?=\d)/, ''));
  return fraction ? `${sign}${grouped},${fraction}` : `${sign}${grouped}`;
}

/** Desi gösterimi: "2.00" -> "2", "2.50" -> "2,5" */
export function formatDesi(value: string): string {
  return formatPlainNumber(value, 2);
}

// --------------------------------------------------------------------------- tarih

const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/** YYYY-AA-GG ve gerçek bir takvim günü mü */
export function isDateText(text: string): boolean {
  const match = DATE_PATTERN.exec(text);
  if (!match) return false;
  const [, y, m, d] = match;
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
  return (
    date.getUTCFullYear() === Number(y) &&
    date.getUTCMonth() === Number(m) - 1 &&
    date.getUTCDate() === Number(d)
  );
}

export function addDays(text: string, days: number): string {
  const match = DATE_PATTERN.exec(text);
  if (!match) throw new TypeError('Geçersiz tarih');
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** İstanbul takvim günü (sunucudaki `today_istanbul` ile aynı gün kuralı) */
export function todayIstanbul(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Istanbul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${pick('year')}-${pick('month')}-${pick('day')}`;
}

/** K33: başlangıç `2000-01-01 <= tarih <= bugün + 366 gün` */
export const MIN_VALID_FROM = '2000-01-01';
export const MAX_FUTURE_DAYS = 366;

const MONTHS = [
  'Ocak',
  'Şubat',
  'Mart',
  'Nisan',
  'Mayıs',
  'Haziran',
  'Temmuz',
  'Ağustos',
  'Eylül',
  'Ekim',
  'Kasım',
  'Aralık',
];

/** "2026-10-01" -> "1 Ekim 2026" (ICU sürümüne bağlı olmayan sabit biçim) */
export function formatLongDate(text: string): string {
  const match = DATE_PATTERN.exec(text);
  if (!match) return text;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${Number(match[3])} ${month} ${match[1]}` : text;
}

/** ISO zaman damgası -> "10 Kasım 2026, 14:35" (İstanbul saati) */
export function formatDateTime(iso: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return iso;
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Istanbul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(instant);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  const month = MONTHS[Number(pick('month')) - 1] ?? pick('month');
  return `${Number(pick('day'))} ${month} ${pick('year')}, ${pick('hour')}:${pick('minute')}`;
}
