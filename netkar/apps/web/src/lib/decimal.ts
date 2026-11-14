// Ondalık sayıları string olarak, float kullanmadan yuvarlayan küçük yardımcılar.
// Backend Decimal döndürür ve JSON'da string gelir; burada kuruş hassasiyeti kaybolmaz.

export type DecimalInput = string | number | bigint;

export interface RoundedDecimal {
  negative: boolean;
  /** Tam kısım rakamları (baştaki sıfırlar atılmış, en az "0") */
  integer: string;
  /** Tam olarak `digits` haneli kesir kısmı ("" olabilir) */
  fraction: string;
  /** Yuvarlamadan sonra değer sıfır mı */
  isZero: boolean;
}

const DIGITS_ONLY = /^\d+$/;

// Düz ondalık metni ayrıştırır: [+-]rakamlar[.rakamlar]. Regex yerine bölme kullanılır
// (yeniden-ifade ReDoS riski olmaz).
function parseDecimal(text: string): { sign: string; integer: string; fraction: string } | null {
  const sign = text.startsWith('-') || text.startsWith('+') ? text.charAt(0) : '';
  const unsigned = sign ? text.slice(1) : text;
  const parts = unsigned.split('.');
  if (parts.length > 2) return null;
  const integer = parts[0] ?? '';
  const fraction = parts[1] ?? '';
  if (!DIGITS_ONLY.test(integer)) return null;
  if (parts.length === 2 && !DIGITS_ONLY.test(fraction)) return null;
  return { sign, integer, fraction };
}

function toPlainString(input: DecimalInput): string {
  if (typeof input === 'bigint') return input.toString();
  if (typeof input === 'number') {
    if (!Number.isFinite(input)) {
      throw new TypeError('Geçersiz sayı: sonlu bir değer bekleniyordu.');
    }
    // Üstel gösterimi (1e21, 1e-7) düz yazıya çevir; toFixed üst sınırı 1e21'dir.
    if (Math.abs(input) >= 1e21) return BigInt(input).toString();
    return input.toFixed(12).replace(/\.?0+$/, '') || '0';
  }
  return input.trim();
}

/**
 * Ondalık değeri `digits` haneye "sıfırdan uzağa yarım yukarı" kuralıyla yuvarlar.
 * Para ve yüzdeler için tek yuvarlama noktası burasıdır.
 */
export function roundDecimal(input: DecimalInput, digits: number): RoundedDecimal {
  const text = toPlainString(input);
  const parsed = parseDecimal(text);
  if (!parsed) {
    throw new TypeError(`Geçersiz ondalık değer: "${text}"`);
  }
  const { sign, integer: integerPart, fraction: fractionPart } = parsed;

  const padded = fractionPart.padEnd(digits + 1, '0');
  const keptFraction = padded.slice(0, digits);
  const nextDigit = Number(padded.charAt(digits));

  // Tüm rakamları tek BigInt olarak topla; yarım ve üstünde ise son haneye 1 ekle.
  let scaled = BigInt(integerPart + keptFraction);
  if (nextDigit >= 5) scaled += 1n;

  const scaledText = scaled.toString().padStart(digits + 1, '0');
  const integer = scaledText.slice(0, scaledText.length - digits);
  const fraction = scaledText.slice(scaledText.length - digits);
  const isZero = scaled === 0n;

  return { negative: sign === '-' && !isZero, integer, fraction, isZero };
}

/** Binlik ayracı olarak nokta ekler (tr-TR): 1234567 -> 1.234.567 */
export function groupThousands(integerDigits: string): string {
  const groups: string[] = [];
  for (let end = integerDigits.length; end > 0; end -= 3) {
    groups.unshift(integerDigits.slice(Math.max(0, end - 3), end));
  }
  return groups.join('.');
}
