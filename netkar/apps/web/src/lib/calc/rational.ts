// Başabaş fiyatı gibi kesirli denklemler için küçük BigInt kesir türü (float yok).

export interface Frac {
  n: bigint;
  /** Her zaman pozitif */
  d: bigint;
}

function gcd(a: bigint, b: bigint): bigint {
  let x = a < 0n ? -a : a;
  let y = b < 0n ? -b : b;
  while (y !== 0n) {
    [x, y] = [y, x % y];
  }
  return x;
}

export function frac(n: bigint, d: bigint = 1n): Frac {
  if (d === 0n) throw new RangeError('Payda sıfır olamaz.');
  const sign = d < 0n ? -1n : 1n;
  const g = gcd(n, d) || 1n;
  return { n: (sign * n) / g, d: (sign * d) / g };
}

export const add = (a: Frac, b: Frac): Frac => frac(a.n * b.d + b.n * a.d, a.d * b.d);
export const sub = (a: Frac, b: Frac): Frac => frac(a.n * b.d - b.n * a.d, a.d * b.d);
export const mul = (a: Frac, b: Frac): Frac => frac(a.n * b.n, a.d * b.d);

export function div(a: Frac, b: Frac): Frac {
  if (b.n === 0n) throw new RangeError('Sıfıra bölme.');
  return frac(a.n * b.d, a.d * b.n);
}

export const isPositive = (a: Frac): boolean => a.n > 0n;

/** Pozitif kesrin tavanı */
export function ceil(a: Frac): bigint {
  if (a.n <= 0n) return -(-a.n / a.d);
  return (a.n + a.d - 1n) / a.d;
}
