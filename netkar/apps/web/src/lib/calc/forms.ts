// Form metinlerini (kullanıcının yazdığı string) hesap girdilerine çevirir ve alan bazlı hata
// mesajı üretir. Saf fonksiyonlar: arayüz yalnız sonucu gösterir.

import type { CommissionInput } from './commission';
import { DESI_DIVISORS, VAT_RATES, type DesiDivisorKey } from './constants';
import type { DesiInput } from './desi';
import { parseDecimal, type Bps, type Kurus, type ParseError } from './money';
import type { ProfitInput } from './profit';

type Field<T> = { ok: true; value: T } | { ok: false; error: string };

const PARSE_MESSAGES: Record<ParseError, string> = {
  empty: 'Bu alanı doldurun.',
  invalid: 'Sayı olarak yazın. Örnek: 1.250,50',
  negative: 'Negatif değer yazılamaz.',
  too_many_decimals: 'En fazla {scale} ondalık hane yazın.',
  too_large: 'Değer çok büyük.',
};

function describe(error: ParseError, scale: number): string {
  return PARSE_MESSAGES[error].replace('{scale}', String(scale));
}

interface MoneyOptions {
  /** Boş bırakılabilir (0 sayılır) */
  optional?: boolean;
  /** 0'dan büyük olmalı */
  positive?: boolean;
}

function readScaled(text: string, scale: number, options: MoneyOptions): Field<bigint> {
  const parsed = parseDecimal(text, scale);
  if (!parsed.ok) {
    if (parsed.error === 'empty' && options.optional) return { ok: true, value: 0n };
    return { ok: false, error: describe(parsed.error, scale) };
  }
  if (options.positive && parsed.value <= 0n) {
    return { ok: false, error: 'Sıfırdan büyük bir değer yazın.' };
  }
  return { ok: true, value: parsed.value };
}

export const readMoney = (text: string, options: MoneyOptions = {}): Field<Kurus> =>
  readScaled(text, 2, options);

export function readPercent(
  text: string,
  options: MoneyOptions & { max?: number } = {},
): Field<Bps> {
  const result = readScaled(text, 2, options);
  if (!result.ok) return result;
  const max = BigInt(options.max ?? 100) * 100n;
  if (result.value > max) return { ok: false, error: `En fazla %${options.max ?? 100} yazın.` };
  return result;
}

function readSelect<T extends string>(text: string, allowed: readonly T[]): Field<T> {
  const found = allowed.find((item) => item === text);
  return found !== undefined
    ? { ok: true, value: found }
    : { ok: false, error: 'Listeden bir seçenek seçin.' };
}

function readVatRate(text: string): Field<number> {
  const result = readSelect(text, VAT_RATES.map(String));
  return result.ok ? { ok: true, value: Number(result.value) } : result;
}

/** Alan hatalarını toplar; hata yoksa değerleri döndürür. */
function collect<K extends string>(fields: Record<K, Field<unknown>>) {
  const errors: Partial<Record<K, string>> = {};
  for (const key of Object.keys(fields) as K[]) {
    const field = fields[key];
    if (!field.ok) errors[key] = field.error;
  }
  return errors;
}

const value = <T>(field: Field<T>): T => (field as { ok: true; value: T }).value;

// ---------- Komisyon ----------

export interface CommissionFormValues {
  price: string;
  vatRate: string;
  commissionRate: string;
  commissionVat: string;
  shipping: string;
  shippingVat: string;
  serviceFee: string;
}

export type CommissionFormResult =
  | { input: CommissionInput; errors: Record<string, never> }
  | { input: null; errors: Partial<Record<keyof CommissionFormValues, string>> };

export function deriveCommissionInput(values: CommissionFormValues): CommissionFormResult {
  const fields = {
    price: readMoney(values.price, { positive: true }),
    vatRate: readVatRate(values.vatRate),
    commissionRate: readPercent(values.commissionRate, { positive: true }),
    commissionVat: readSelect(values.commissionVat, ['incl', 'excl'] as const),
    shipping: readMoney(values.shipping, { optional: true }),
    shippingVat: readSelect(values.shippingVat, ['excl', 'incl'] as const),
    serviceFee: readMoney(values.serviceFee, { optional: true }),
  };
  const errors = collect(fields);
  if (Object.keys(errors).length > 0) return { input: null, errors };
  return {
    errors: {},
    input: {
      priceIncl: value(fields.price),
      vatRatePct: value(fields.vatRate),
      commissionBps: value(fields.commissionRate),
      commissionIncludesVat: value(fields.commissionVat) === 'incl',
      shipping: value(fields.shipping),
      shippingIncludesVat: value(fields.shippingVat) === 'incl',
      serviceFeeExcl: value(fields.serviceFee),
    },
  };
}

// ---------- Kâr ----------

export interface ProfitFormValues {
  price: string;
  vatRate: string;
  cost: string;
  costVat: string;
  /** "same" (satış KDV oranıyla aynı) veya 1, 10, 20 */
  costVatRate: string;
  commissionRate: string;
  commissionVat: string;
  shipping: string;
  returnShipping: string;
  shippingVat: string;
  serviceFee: string;
  adMode: string;
  adAmount: string;
  roas: string;
  returnRate: string;
  unsellableRate: string;
}

export type ProfitFormResult =
  | { input: ProfitInput; errors: Record<string, never>; warnings: string[] }
  | { input: null; errors: Partial<Record<keyof ProfitFormValues, string>>; warnings: string[] };

export function deriveProfitInput(values: ProfitFormValues): ProfitFormResult {
  const adMode = readSelect(values.adMode, ['amount', 'roas'] as const);
  const costVatRate =
    values.costVatRate === 'same'
      ? ({ ok: true, value: 0 } as const)
      : readVatRate(values.costVatRate);

  const fields = {
    price: readMoney(values.price, { positive: true }),
    vatRate: readVatRate(values.vatRate),
    cost: readMoney(values.cost, { optional: true }),
    costVat: readSelect(values.costVat, ['excl', 'incl'] as const),
    costVatRate,
    commissionRate: readPercent(values.commissionRate, { positive: true }),
    commissionVat: readSelect(values.commissionVat, ['incl', 'excl'] as const),
    shipping: readMoney(values.shipping, { optional: true }),
    returnShipping: readMoney(values.returnShipping, { optional: true }),
    shippingVat: readSelect(values.shippingVat, ['excl', 'incl'] as const),
    serviceFee: readMoney(values.serviceFee, { optional: true }),
    adMode,
    // Yalnız seçili reklam girişi doğrulanır
    adAmount:
      values.adMode === 'roas'
        ? ({ ok: true, value: 0n } as const)
        : readMoney(values.adAmount, { optional: true }),
    roas:
      values.adMode === 'roas'
        ? readScaled(values.roas, 2, { positive: true })
        : ({ ok: true, value: 0n } as const),
    returnRate: readPercent(values.returnRate, { optional: true }),
    unsellableRate: readPercent(values.unsellableRate, { optional: true }),
  };
  const errors = collect(fields);
  if (Object.keys(errors).length > 0) return { input: null, errors, warnings: [] };

  const vatRatePct = value(fields.vatRate);
  const input: ProfitInput = {
    priceIncl: value(fields.price),
    vatRatePct,
    cost: value(fields.cost),
    costIncludesVat: value(fields.costVat) === 'incl',
    costVatRatePct: values.costVatRate === 'same' ? vatRatePct : value(fields.costVatRate),
    commissionBps: value(fields.commissionRate),
    commissionIncludesVat: value(fields.commissionVat) === 'incl',
    shipping: value(fields.shipping),
    shippingIncludesVat: value(fields.shippingVat) === 'incl',
    returnShipping: value(fields.returnShipping),
    serviceFeeExcl: value(fields.serviceFee),
    ad:
      value(fields.adMode) === 'roas'
        ? { kind: 'roas', roasHundredths: value(fields.roas) }
        : { kind: 'amount', amount: value(fields.adAmount) },
    returnRateBps: value(fields.returnRate),
    unsellableBps: value(fields.unsellableRate),
  };

  // Engellemeyen uyarılar (WCAG 3.3.3: hata önerisi)
  const warnings: string[] = [];
  const priceExcl = (input.priceIncl * 100n) / (100n + BigInt(vatRatePct));
  const costExcl = input.costIncludesVat
    ? (input.cost * 100n) / (100n + BigInt(input.costVatRatePct))
    : input.cost;
  if (costExcl > priceExcl) {
    warnings.push(
      'Alış maliyeti satış fiyatının KDV hariç tutarından yüksek görünüyor. Maliyeti KDV dahil yazdıysanız “Maliyet KDV” seçeneğini kontrol edin.',
    );
  }
  if (input.cost === 0n) {
    warnings.push('Alış maliyetini yazmadığınız için sonuç, maliyet düşülmemiş kârı gösterir.');
  }
  return { input, errors: {}, warnings };
}

// ---------- Desi ----------

export interface DesiFormValues {
  length: string;
  width: string;
  height: string;
  weight: string;
  divisor: string;
}

export type DesiFormResult =
  | { input: DesiInput; errors: Record<string, never> }
  | { input: null; errors: Partial<Record<keyof DesiFormValues, string>> };

export function deriveDesiInput(values: DesiFormValues): DesiFormResult {
  const fields = {
    length: readScaled(values.length, 1, { positive: true }),
    width: readScaled(values.width, 1, { positive: true }),
    height: readScaled(values.height, 1, { positive: true }),
    // Ağırlık isteğe bağlıdır: boşsa yalnız hacim hesaba girer
    weight: readScaled(values.weight, 3, { optional: true }),
    divisor: readSelect(values.divisor, Object.keys(DESI_DIVISORS) as DesiDivisorKey[]),
  };
  const errors = collect(fields);
  if (Object.keys(errors).length > 0) return { input: null, errors };
  return {
    errors: {},
    input: {
      length: value(fields.length),
      width: value(fields.width),
      height: value(fields.height),
      weightGrams: value(fields.weight),
      divisor: value(fields.divisor),
    },
  };
}
