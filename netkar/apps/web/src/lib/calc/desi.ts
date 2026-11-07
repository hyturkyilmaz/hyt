// Desi hesabı: desi = en x boy x yükseklik (cm) / bölen. Yurt içi bölen 3.000, yurt dışı 5.000.
// Ücretlendirmeye esas değer, desi ile gerçek ağırlıktan (kg) büyük olanıdır.
// Ölçüler 1 ondalık cm, ağırlık 3 ondalık kg olarak tamsayıya çevrilip BigInt ile hesaplanır.

import { DESI_DIVISORS, type DesiDivisorKey } from './constants';
import { divCeil, divRound } from './money';

export interface DesiInput {
  /** cm x 10 (1 ondalık hane) */
  length: bigint;
  width: bigint;
  height: bigint;
  /** gram (kg x 1000) */
  weightGrams: bigint;
  divisor: DesiDivisorKey;
}

export interface DesiResult {
  /** Hacimsel desi x 100 (2 ondalık hane) */
  volumetricHundredths: bigint;
  /** Gerçek ağırlık, kg x 100 */
  weightHundredths: bigint;
  /** Ücretlendirmeye esas değer x 100 */
  billableHundredths: bigint;
  /** Esas değeri belirleyen: hacim mi ağırlık mı */
  basis: 'volume' | 'weight';
  /** Esas değerin yukarı yuvarlanmış tam sayısı (tarifeler tam desi basamağıyla yazılır) */
  billableRoundedUp: bigint;
}

export function calculateDesi(input: DesiInput): DesiResult {
  const divisor = DESI_DIVISORS[input.divisor];
  // En x boy x yükseklik, birimi 0,001 cm³
  const volume = input.length * input.width * input.height;
  // 1 cm³ / bölen = 1 desi. Desi x 100 = volume / (1000 x bölen) x 100 = volume / (10 x bölen)
  const volumetricHundredths = divRound(volume, 10n * divisor);
  const weightHundredths = divRound(input.weightGrams, 10n);

  // Karşılaştırma yuvarlamadan önce, tam değerlerle yapılır: hacim/(1000 x bölen) kg-eşdeğeri.
  const volumeWins = volume >= input.weightGrams * divisor;
  const billableHundredths = volumeWins ? volumetricHundredths : weightHundredths;
  const billableRoundedUp = volumeWins
    ? divCeil(volume, 1000n * divisor)
    : divCeil(input.weightGrams, 1000n);

  return {
    volumetricHundredths,
    weightHundredths,
    billableHundredths,
    basis: volumeWins ? 'volume' : 'weight',
    billableRoundedUp,
  };
}

/** "Koli 1 cm küçülürse ne değişir" tablosu için bir ölçüyü 1 cm azaltır (10 birim). */
export function shrinkOneCm(value: bigint): bigint | null {
  return value > 10n ? value - 10n : null;
}
