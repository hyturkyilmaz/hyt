// Hesaplayıcılar için tamsayı (BigInt) kuruş aritmetiği. Float kullanılmaz.
// Kurallar docs/12_kar_motoru.md K01 (tek yuvarlama noktası, sıfırdan uzağa yarım yukarı) ve
// K02 (KDV dahil/hariç dönüşümü) ile aynıdır.

import { groupThousands } from '@/lib/decimal';
import { formatPercent, formatTRY } from '@/lib/format';

/** Kuruş cinsinden tutar (1 TL = 100). */
export type Kurus = bigint;

/** Yüzdelik değerler yüzde puanının yüzde biri olarak tutulur: %15,25 -> 1525n. */
export type Bps = bigint;

/** `n / d` değerini sıfırdan uzağa yarım yukarı yuvarlar. `d` pozitif olmalıdır. */
export function divRound(n: bigint, d: bigint): bigint {
  if (d <= 0n) throw new RangeError('Bölen pozitif olmalı.');
  const negative = n < 0n;
  const abs = negative ? -n : n;
  const q = (abs * 2n + d) / (2n * d);
  return negative ? -q : q;
}

/** Pozitif `n / d` değerini yukarı yuvarlar (tavan). */
export function divCeil(n: bigint, d: bigint): bigint {
  if (d <= 0n) throw new RangeError('Bölen pozitif olmalı.');
  if (n <= 0n) return -(-n / d);
  return (n + d - 1n) / d;
}

export interface VatSplit {
  /** KDV hariç tutar */
  excl: Kurus;
  /** KDV tutarı */
  vat: Kurus;
  /** KDV dahil tutar (girdi) */
  incl: Kurus;
}

/** K02 (dahilden): haric = rnd(dahil / (1 + r/100)), kdv = dahil - haric. */
export function splitInclusive(incl: Kurus, ratePct: number): VatSplit {
  const excl = divRound(incl * 100n, 100n + BigInt(ratePct));
  return { excl, vat: incl - excl, incl };
}

/** K02 (hariçten): kdv = rnd(haric x r/100), dahil = haric + kdv. */
export function splitExclusive(excl: Kurus, ratePct: number): VatSplit {
  const vat = divRound(excl * BigInt(ratePct), 100n);
  return { excl, vat, incl: excl + vat };
}

/** `tutar x oran` (oran yüzde puanının yüzde biri cinsinden) değerini kuruşa yuvarlar. */
export function percentOf(amount: Kurus, bps: Bps): Kurus {
  return divRound(amount * bps, 10000n);
}

export type ParseError = 'empty' | 'invalid' | 'negative' | 'too_many_decimals' | 'too_large';

export type ParseResult = { ok: true; value: bigint } | { ok: false; error: ParseError };

const MAX_INTEGER_DIGITS = 12;
const ONLY_DIGITS = /^\d+$/;

// Binlik gruplarını doğrular: ilk grup 1-3 hane, sonrakiler tam 3 hane.
function groupsAreThousands(groups: string[]): boolean {
  if (groups.length < 2) return true;
  const [first, ...rest] = groups;
  return (
    first !== undefined &&
    first.length >= 1 &&
    first.length <= 3 &&
    ONLY_DIGITS.test(first) &&
    rest.every((group) => group.length === 3 && ONLY_DIGITS.test(group))
  );
}

/**
 * Kullanıcının yazdığı sayıyı `scale` ondalık haneli tamsayıya çevirir (para için 2, yüzde için 2).
 * Hem virgül hem nokta ondalık ayracı kabul edilir ("1234,56", "1234.56", "1.234,56", "1,234.56").
 * Tek noktadan sonra tam 3 hane geliyorsa ("1.234") binlik ayracı sayılır; "0.125" ondalıktır.
 * Negatif değer, harf ve `scale` haneden fazla ondalık reddedilir (sessizce yuvarlanmaz).
 */
export function parseDecimal(input: string, scale: number): ParseResult {
  const cleaned = input
    .replace(/[\s  ]/g, '')
    .replace(/(?:₺|TL|tl|%)/g, '')
    .trim();
  if (cleaned === '') return { ok: false, error: 'empty' };
  if (cleaned.startsWith('-')) return { ok: false, error: 'negative' };
  if (!/^[\d.,]+$/.test(cleaned)) return { ok: false, error: 'invalid' };

  const lastDot = cleaned.lastIndexOf('.');
  const lastComma = cleaned.lastIndexOf(',');
  let integerText: string;
  let fractionText = '';

  if (lastDot !== -1 && lastComma !== -1) {
    // İkisi de var: sonuncusu ondalık, diğeri binlik ayracıdır.
    const decimalIsComma = lastComma > lastDot;
    const decimalSep = decimalIsComma ? ',' : '.';
    const thousandSep = decimalIsComma ? '.' : ',';
    const parts = cleaned.split(decimalSep);
    if (parts.length !== 2) return { ok: false, error: 'invalid' };
    const integerPart = parts[0] ?? '';
    fractionText = parts[1] ?? '';
    if (integerPart.includes(decimalSep) || fractionText.includes(thousandSep)) {
      return { ok: false, error: 'invalid' };
    }
    const groups = integerPart.split(thousandSep);
    if (!groupsAreThousands(groups)) return { ok: false, error: 'invalid' };
    integerText = groups.join('');
  } else if (lastComma !== -1) {
    const parts = cleaned.split(',');
    if (parts.length !== 2) return { ok: false, error: 'invalid' };
    integerText = parts[0] ?? '';
    fractionText = parts[1] ?? '';
  } else if (lastDot !== -1) {
    const parts = cleaned.split('.');
    if (parts.length > 2) {
      // Birden çok nokta yalnız binlik ayracı olabilir.
      if (!groupsAreThousands(parts)) return { ok: false, error: 'invalid' };
      integerText = parts.join('');
    } else {
      const integerPart = parts[0] ?? '';
      const fractionPart = parts[1] ?? '';
      const looksLikeThousands =
        fractionPart.length === 3 &&
        integerPart.length >= 1 &&
        integerPart.length <= 3 &&
        !integerPart.startsWith('0');
      if (looksLikeThousands) {
        integerText = integerPart + fractionPart;
      } else {
        integerText = integerPart;
        fractionText = fractionPart;
      }
    }
  } else {
    integerText = cleaned;
  }

  if (integerText === '') integerText = '0';
  if (!ONLY_DIGITS.test(integerText) || (fractionText !== '' && !ONLY_DIGITS.test(fractionText))) {
    return { ok: false, error: 'invalid' };
  }
  if (fractionText.length > scale) return { ok: false, error: 'too_many_decimals' };
  if (integerText.replace(/^0+/, '').length > MAX_INTEGER_DIGITS) {
    return { ok: false, error: 'too_large' };
  }
  return { ok: true, value: BigInt(integerText + fractionText.padEnd(scale, '0')) };
}

/** Tamsayıyı `scale` ondalıklı düz metne çevirir: (123456n, 2) -> "1234.56". */
export function scaledToDecimalString(value: bigint, scale: number): string {
  const negative = value < 0n;
  const digits = (negative ? -value : value).toString().padStart(scale + 1, '0');
  const integer = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale);
  const body = scale > 0 ? `${integer}.${fraction}` : integer;
  return negative ? `-${body}` : body;
}

/** Kuruşu "1.234,56 TL" biçiminde yazar (lib/format ile aynı kural). */
export function formatKurus(value: Kurus): string {
  return formatTRY(scaledToDecimalString(value, 2), { style: 'code' });
}

/** Kuruşu para birimi eki olmadan yazar: "1.234,56". */
export function formatKurusPlain(value: Kurus): string {
  return formatTRY(scaledToDecimalString(value, 2), { style: 'none' });
}

/** Yüzde puanının yüzde biri değerini "%12,5" biçiminde yazar. */
export function formatBps(value: Bps, fractionDigits = 2): string {
  return formatPercent(scaledToDecimalString(value, 2), { fractionDigits });
}

/** Ondalıklı tamsayıyı (ör. desi x 100) tr-TR yazar: (1234n, 2) -> "12,34". */
export function formatScaled(value: bigint, scale: number): string {
  const text = scaledToDecimalString(value, scale);
  const negative = text.startsWith('-');
  const [integer = '0', fraction = ''] = (negative ? text.slice(1) : text).split('.');
  return `${negative ? '-' : ''}${groupThousands(integer)}${fraction ? `,${fraction}` : ''}`;
}
