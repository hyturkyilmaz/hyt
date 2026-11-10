// Decimal dizgeleri üzerinde float kullanmadan toplama ve işaret.
// Yalnız "[-]rakamlar[.rakamlar]" biçimini kabul eder; aksi halde hata fırlatır.

interface Scaled {
  value: bigint;
  scale: number;
}

function parse(text: string): Scaled {
  const trimmed = text.trim();
  const negative = trimmed.startsWith('-');
  const unsigned = negative || trimmed.startsWith('+') ? trimmed.slice(1) : trimmed;
  const parts = unsigned.split('.');
  const integer = parts[0] ?? '';
  const fraction = parts[1] ?? '';
  const valid = /^\d+$/.test(integer) && (parts.length === 1 || /^\d+$/.test(fraction));
  if (parts.length > 2 || !valid) {
    throw new TypeError(`Geçersiz ondalık değer: "${text}"`);
  }
  const magnitude = BigInt(integer + fraction);
  return { value: negative ? -magnitude : magnitude, scale: fraction.length };
}

function format(value: bigint, scale: number): string {
  const negative = value < 0n;
  const digits = (negative ? -value : value).toString().padStart(scale + 1, '0');
  const integer = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale);
  return `${negative ? '-' : ''}${integer}${scale > 0 ? `.${fraction}` : ''}`;
}

/** İki Decimal dizgesini tam hassasiyetle toplar: addDecimal("-10.50", "2.25") === "-8.25" */
export function addDecimal(a: string, b: string): string {
  const left = parse(a);
  const right = parse(b);
  const scale = Math.max(left.scale, right.scale);
  const lift = (x: Scaled) => x.value * 10n ** BigInt(scale - x.scale);
  return format(lift(left) + lift(right), scale);
}

/** a - b, tam hassasiyetle. */
export function subtractDecimal(a: string, b: string): string {
  const right = parse(b);
  return addDecimal(a, format(-right.value, right.scale));
}

/** İşaret: -1 negatif, 0 sıfır, 1 pozitif (yuvarlama yapılmaz). */
export function decimalSign(a: string): -1 | 0 | 1 {
  const { value } = parse(a);
  if (value === 0n) return 0;
  return value < 0n ? -1 : 1;
}

/** |a| değerinin |b| değerinden büyük ya da eşit olup olmadığı (karşılaştırma farklarında). */
export function absAtLeast(a: string, b: string): boolean {
  const left = parse(a);
  const right = parse(b);
  const scale = Math.max(left.scale, right.scale);
  const lift = (x: Scaled) => {
    const v = x.value * 10n ** BigInt(scale - x.scale);
    return v < 0n ? -v : v;
  };
  return lift(left) >= lift(right);
}

/** Sıralama için karşılaştırma: -1 (a < b), 0 (eşit), 1 (a > b); yuvarlama yapılmaz. */
export function compareDecimal(a: string, b: string): -1 | 0 | 1 {
  return decimalSign(subtractDecimal(a, b));
}

/** Mutlak değer: absDecimal("-4.00") === "4.00". Biçim ve hassasiyet korunur. */
export function absDecimal(a: string): string {
  const { value, scale } = parse(a);
  return format(value < 0n ? -value : value, scale);
}

/**
 * KDV dahil tutardan KDV hariç karşılığı (K02): `rnd(dahil / (1 + oran/100))`, kuruşa yarım yukarı.
 * Float yok: tam sayı kuruş üzerinden BigInt ile hesaplanır. Yalnız negatif olmayan tutar ve tamsayı oran.
 * exclusiveOfVat("54.00", 20) === "45.00"; exclusiveOfVat("50.00", 20) === "41.67".
 */
export function exclusiveOfVat(inclusive: string, ratePercent: number): string {
  const { value, scale } = parse(inclusive);
  if (value < 0n || !Number.isInteger(ratePercent) || ratePercent < 0) {
    throw new TypeError('KDV hariç hesabı için negatif olmayan tutar ve tamsayı oran gerekir.');
  }
  // tutar = value / 10^scale; sonuç kuruş: value * 100 / (10^scale * (100 + oran) / 100) = value*10^4 / (10^scale*(100+oran))
  const numerator = value * 10_000n;
  const denominator = 10n ** BigInt(scale) * BigInt(100 + ratePercent);
  const cents = (numerator * 2n + denominator) / (denominator * 2n);
  return format(cents, 2);
}
