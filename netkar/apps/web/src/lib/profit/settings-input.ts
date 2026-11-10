// Ayar formu girdi yardımcıları: tr-TR ondalık ayrıştırma, tarih (İstanbul takvim günü) ve sunum biçimleri.
// Para ve oran Decimal DİZGESİDİR; float kullanılmaz (K01). Doğrulama sunucudaki kurallarla tutarlıdır
// (docs/12 K33 doğrulama tablosu); sunucu doğrulaması esastır, bu yalnız hızlı geri bildirimdir.
import { groupThousands } from '@/lib/decimal';

// --------------------------------------------------------------------------- ondalık girdi

export type DecimalParse =
  { ok: true; value: string } | { ok: false; reason: 'empty' | 'invalid' | 'too_many_decimals' };

const MAX_INTEGER_DIGITS = 15;

function stripLeadingZeros(digits: string): string {
  const stripped = digits.replace(/^0+(?=\d)/, '');
  return stripped === '' ? '0' : stripped;
}

/**
 * Kullanıcının yazdığı sayıyı kanonik Decimal dizgesine çevirir ("54,50" ve "54.50" -> "54.50").
 * Virgül ve nokta ondalık ayracı olarak kabul edilir. İkisi birlikte varsa son geçen ondalıktır, diğeri binlik
 * ayracıdır ("1.250,50"). Tek ayraç ve tam üç hane sonrası ("1.250") binliktir (ondalık en çok 2 ya da 4 hane).
 * Negatif, üstel gösterim ve harf reddedilir.
 */
export function parseDecimalInput(text: string, maxFraction: number): DecimalParse {
  const compact = text.replace(/[\s ]/g, '');
  if (compact === '') return { ok: false, reason: 'empty' };
  if (!/^[0-9.,]+$/.test(compact)) return { ok: false, reason: 'invalid' };

  const lastDot = compact.lastIndexOf('.');
  const lastComma = compact.lastIndexOf(',');
  let decimalAt = -1;
  let thousands = '';
  if (lastDot >= 0 && lastComma >= 0) {
    decimalAt = Math.max(lastDot, lastComma);
    thousands = lastDot > lastComma ? ',' : '.';
  } else if (lastDot >= 0 || lastComma >= 0) {
    const sep = lastDot >= 0 ? '.' : ',';
    const at = Math.max(lastDot, lastComma);
    const count = compact.split(sep).length - 1;
    const after = compact.length - at - 1;
    const before = compact.slice(0, at);
    if (count > 1) {
      thousands = sep;
    } else if (after === 3 && maxFraction < 3 && before !== '' && before !== '0') {
      thousands = sep;
    } else {
      decimalAt = at;
    }
  }

  // Binlik ayracı ondalık ayracından sonra gelemez ("1,5.3")
  if (thousands && decimalAt >= 0 && compact.lastIndexOf(thousands) > decimalAt) {
    return { ok: false, reason: 'invalid' };
  }
  const integerPart = decimalAt >= 0 ? compact.slice(0, decimalAt) : compact;
  const fractionPart = decimalAt >= 0 ? compact.slice(decimalAt + 1) : '';
  // Binlik gruplar: ilk grup 1-3 hane, diğerleri tam 3 hane ("1.250", "12.345.678")
  if (thousands) {
    const groups = integerPart.split(thousands);
    const valid = groups.every((group, index) =>
      index === 0 ? /^\d{1,3}$/.test(group) : /^\d{3}$/.test(group),
    );
    if (!valid) return { ok: false, reason: 'invalid' };
  }
  const integer = thousands ? integerPart.split(thousands).join('') : integerPart;
  // Ondalık ayracı ikinci kez geçemez ve kalan metin yalnız rakam olmalı
  if (!/^\d*$/.test(integer) || !/^\d*$/.test(fractionPart))
    return { ok: false, reason: 'invalid' };
  if (integer === '' && fractionPart === '') return { ok: false, reason: 'invalid' };
  if (decimalAt >= 0 && fractionPart === '') return { ok: false, reason: 'invalid' };
  if (integer.length > MAX_INTEGER_DIGITS) return { ok: false, reason: 'invalid' };
  if (fractionPart.length > maxFraction) return { ok: false, reason: 'too_many_decimals' };
  const whole = stripLeadingZeros(integer === '' ? '0' : integer);
  return { ok: true, value: fractionPart ? `${whole}.${fractionPart}` : whole };
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
