import { groupThousands, roundDecimal, type DecimalInput } from '@/lib/decimal';

export type CurrencyStyle = 'symbol' | 'code' | 'none';

export interface FormatTRYOptions {
  /**
   * symbol: ₺1.234,56 (varsayılan, tr-TR yerel biçimi)
   * code: 1.234,56 TL (metin ve sözleşme dili)
   * none: 1.234,56
   */
  style?: CurrencyStyle;
  /** Pozitif değerlere de + işareti koy */
  signed?: boolean;
}

const NBSP = ' ';

/**
 * Türk lirasını tr-TR biçiminde yazar. Girdi string (Decimal) önerilir; kuruş hassasiyeti
 * korunur ve 2 haneye yarım yukarı yuvarlanır. Negatifte eksi işareti her zaman görünür.
 */
export function formatTRY(amount: DecimalInput, options: FormatTRYOptions = {}): string {
  const { style = 'symbol', signed = false } = options;
  const { negative, integer, fraction, isZero } = roundDecimal(amount, 2);

  const number = `${groupThousands(integer)},${fraction}`;
  const sign = negative ? '-' : signed && !isZero ? '+' : '';

  switch (style) {
    case 'code':
      return `${sign}${number}${NBSP}TL`;
    case 'none':
      return `${sign}${number}`;
    default:
      return `${sign}₺${number}`;
  }
}

export interface FormatPercentOptions {
  /** Ondalık hane sayısı (varsayılan 1) */
  fractionDigits?: number;
  signed?: boolean;
}

/**
 * Yüzdeyi tr-TR biçiminde yazar. Girdi yüzde puanıdır: "12.5" -> "%12,5".
 * (Oran değil; 0.125 değeri "%0,1" olur.)
 */
export function formatPercent(value: DecimalInput, options: FormatPercentOptions = {}): string {
  const { fractionDigits = 1, signed = false } = options;
  const { negative, integer, fraction, isZero } = roundDecimal(value, fractionDigits);

  const number =
    fractionDigits > 0 ? `${groupThousands(integer)},${fraction}` : groupThousands(integer);
  const sign = negative ? '-' : signed && !isZero ? '+' : '';

  return `${sign}%${number}`;
}

/** Yuvarlamadan sonraki işareti verir; renk ve metin kararları için. */
export function getSign(value: DecimalInput, digits = 2): 'positive' | 'negative' | 'zero' {
  const { negative, isZero } = roundDecimal(value, digits);
  if (isZero) return 'zero';
  return negative ? 'negative' : 'positive';
}

/** Tam sayıyı tr-TR binlik ayırıcıyla yazar: 5231 -> "5.231". Geçersiz ya da negatif değer "0" olur. */
export function formatCount(value: number): string {
  const safe = Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  return groupThousands(String(safe));
}
