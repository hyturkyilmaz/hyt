// Kâr ayarları formlarının Zod şemaları. Kurallar sunucudakilerle aynıdır (docs/12 K33 doğrulama tablosu,
// services/api/app/services/profit_settings.py `check_*`); sunucu doğrulaması esastır, burası hızlı geri
// bildirimdir. Form değerleri metindir (kullanıcının yazdığı biçim); API gövdesine `to*Body` ile çevrilir.
import { z } from 'zod';

import type { ApiFieldError } from '@/lib/api/client';
import type {
  Agreement,
  CargoTariffIn,
  DefaultsIn,
  ExpenseKind,
  ServiceFeeIn,
  VariableExpenseIn,
} from '@/lib/api/profit-settings';
import { compareDecimal } from '@/lib/profit/decimal-math';
import {
  MAX_FUTURE_DAYS,
  MIN_VALID_FROM,
  addDays,
  isDateText,
  parseDecimalInput,
  toMoneyString,
} from '@/lib/profit/settings-input';

export const MAX_BRACKETS = 50;
export const MAX_CARRIER_LENGTH = 100;
export const MAX_EXPENSE_NAME = 80;
export const ALLOWED_VAT_RATES = [0, 1, 10, 20] as const;

const MAX_DESI = '1000';
const MAX_PRICE = '100000';
const MAX_SERVICE_FEE = '10000';
const MAX_EXPENSE_AMOUNT = '100000';

// Kontrol, biçim ve birleştirici karakterler (sunucu `unicodedata.category` C* ile aynı amaç)
const CONTROL_CHARS = /[\p{C}]/u;

// --------------------------------------------------------------------------- ortak parçalar

type NumberKind = 'money' | 'desi' | 'percent';

/**
 * Ayrıştırma hatası -> Türkçe cümle. Para ve oran alanları AYNI kuralı kullanır (parseDecimalInput): ondalık
 * ayracı virgüldür; nokta yalnız doğru gruplanmış binlik ayracıdır.
 */
export function describeParseFailure(
  reason: 'empty' | 'invalid' | 'too_many_decimals' | 'ambiguous',
  options: { label: string; kind: NumberKind; maxFraction: number; example: string; empty: string },
): string {
  switch (reason) {
    case 'empty':
      return options.empty;
    case 'too_many_decimals':
      return options.kind === 'money'
        ? 'Kuruş en fazla 2 hane olabilir. Binlik ayracı için nokta kullanın: 1.250,00'
        : `${options.label} en çok ${options.maxFraction} ondalıklı olabilir.`;
    case 'ambiguous':
      return `Ondalık için virgül kullanın (örnek: ${options.example}). Nokta yalnız binlik ayracıdır: 1.250`;
    default:
      return `${options.label} geçerli bir sayı olmalı. Örnek: ${options.example}`;
  }
}

/** Metin alanı bir Decimal sınırına uyuyor mu; hata iletisi Türkçe ve alan yanında gösterilir. */
function decimalField(
  label: string,
  options: {
    maxFraction: number;
    min: string;
    minExclusive?: boolean;
    max: string;
    rangeText: string;
    kind: NumberKind;
    example: string;
  },
) {
  return z.string().superRefine((text, ctx) => {
    const parsed = parseDecimalInput(text, options.maxFraction);
    if (!parsed.ok) {
      ctx.addIssue({
        code: 'custom',
        message: describeParseFailure(parsed.reason, {
          label,
          kind: options.kind,
          maxFraction: options.maxFraction,
          example: options.example,
          empty: `${label} yazın.`,
        }),
      });
      return;
    }
    const below = compareDecimal(parsed.value, options.min);
    const above = compareDecimal(parsed.value, options.max);
    if (below < 0 || (options.minExclusive && below === 0) || above > 0) {
      ctx.addIssue({ code: 'custom', message: `${label} ${options.rangeText}` });
    }
  });
}

const desiText = decimalField('Desi', {
  maxFraction: 2,
  min: '0',
  minExclusive: true,
  max: MAX_DESI,
  rangeText: "0'dan büyük, en çok 1.000 olmalı.",
  kind: 'desi',
  example: '2,5',
});

function startDate(today: string) {
  return z.string().superRefine((text, ctx) => {
    if (!isDateText(text)) {
      ctx.addIssue({ code: 'custom', message: 'Başlangıç tarihini seçin.' });
      return;
    }
    if (text < MIN_VALID_FROM || text > addDays(today, MAX_FUTURE_DAYS)) {
      ctx.addIssue({
        code: 'custom',
        message:
          'Başlangıç tarihi 1 Ocak 2000 ile bugünden en çok 366 gün sonrası arasında olmalı.',
      });
    }
  });
}

const VAT_MODE = z.enum(['dahil', 'haric']);
export type VatMode = z.infer<typeof VAT_MODE>;

// --------------------------------------------------------------------------- kargo tarifesi

export interface TariffFormValues {
  agreement: Agreement;
  carrier: string;
  validFrom: string;
  vatMode: VatMode;
  brackets: { maxDesi: string; price: string }[];
}

export function tariffSchema(today: string) {
  return z.object({
    agreement: z.enum(['trendyol', 'seller']),
    carrier: z
      .string()
      .min(1, 'Kargo firmasını seçin.')
      .max(MAX_CARRIER_LENGTH, 'Firma adı en fazla 100 karakter olabilir.'),
    validFrom: startDate(today),
    vatMode: VAT_MODE,
    brackets: z
      .array(
        z.object({
          maxDesi: desiText,
          price: decimalField('Fiyat', {
            maxFraction: 2,
            min: '0',
            max: MAX_PRICE,
            rangeText: '0 ile 100.000 arasında olmalı.',
            kind: 'money',
            example: '54,50',
          }),
        }),
      )
      .min(1, 'En az bir desi kademesi ekleyin.')
      .max(MAX_BRACKETS, `En çok ${MAX_BRACKETS} kademe girilebilir.`)
      .superRefine((rows, ctx) => {
        // Üst desi kesin artan olmalı (sunucu `brackets_not_increasing`); geçersiz satırlar atlanır.
        let previous: string | null = null;
        rows.forEach((row, index) => {
          const parsed = parseDecimalInput(row.maxDesi, 2);
          if (!parsed.ok) return;
          if (previous !== null && compareDecimal(parsed.value, previous) <= 0) {
            ctx.addIssue({
              code: 'custom',
              path: [index, 'maxDesi'],
              message: 'Üst desi bir önceki kademeden büyük olmalı.',
            });
          }
          previous = parsed.value;
        });
      }),
  });
}

function parsedOrThrow(text: string, maxFraction: number): string {
  const parsed = parseDecimalInput(text, maxFraction);
  if (!parsed.ok) throw new TypeError('Doğrulanmamış değer gönderilemez.');
  return parsed.value;
}

export function toTariffBody(values: TariffFormValues): CargoTariffIn {
  return {
    agreement: values.agreement,
    carrier: values.carrier,
    valid_from: values.validFrom,
    price_includes_vat: values.vatMode === 'dahil',
    brackets: values.brackets.map((row) => ({
      max_desi: parsedOrThrow(row.maxDesi, 2),
      price: toMoneyString(parsedOrThrow(row.price, 2)),
    })),
  };
}

// --------------------------------------------------------------------------- hizmet bedeli

export interface FeeFormValues {
  validFrom: string;
  vatMode: VatMode;
  amount: string;
}

export function feeSchema(today: string) {
  return z.object({
    validFrom: startDate(today),
    vatMode: VAT_MODE,
    amount: decimalField('Tutar', {
      maxFraction: 2,
      min: '0',
      max: MAX_SERVICE_FEE,
      rangeText: '0 ile 10.000 arasında olmalı.',
      kind: 'money',
      example: '12,50',
    }),
  });
}

export function toFeeBody(values: FeeFormValues): ServiceFeeIn {
  return {
    valid_from: values.validFrom,
    amount: toMoneyString(parsedOrThrow(values.amount, 2)),
    amount_includes_vat: values.vatMode === 'dahil',
  };
}

// --------------------------------------------------------------------------- varsayılan desi

export interface DefaultsFormValues {
  desi: string;
}

/** Boş alan "varsayılan desiyi kaldır" demektir (null). */
export const defaultsSchema = z.object({
  desi: z.string().superRefine((text, ctx) => {
    if (text.trim() === '') return;
    const parsed = parseDecimalInput(text, 2);
    if (!parsed.ok) {
      ctx.addIssue({
        code: 'custom',
        message: describeParseFailure(parsed.reason, {
          label: 'Desi',
          kind: 'desi',
          maxFraction: 2,
          example: '2,5',
          empty: 'Desi yazın.',
        }),
      });
      return;
    }
    if (compareDecimal(parsed.value, '0') <= 0 || compareDecimal(parsed.value, MAX_DESI) > 0) {
      ctx.addIssue({ code: 'custom', message: "Desi 0'dan büyük, en çok 1.000 olmalı." });
    }
  }),
});

export function toDefaultsBody(values: DefaultsFormValues): DefaultsIn {
  const text = values.desi.trim();
  return { default_desi: text === '' ? null : parsedOrThrow(text, 2) };
}

// --------------------------------------------------------------------------- değişken gider

export interface ExpenseFormValues {
  name: string;
  kind: ExpenseKind;
  amount: string;
  percent: string;
  vatRate: string;
  validFrom: string;
  validTo: string;
}

export function expenseSchema(today: string) {
  return z
    .object({
      name: z
        .string()
        .trim()
        .min(1, 'Gider adını yazın.')
        .max(MAX_EXPENSE_NAME, 'Ad en fazla 80 karakter olabilir.')
        .refine((value) => !CONTROL_CHARS.test(value), 'Ad kontrol karakteri içeremez.'),
      kind: z.enum(['siparis_basi', 'adet_basi', 'satis_yuzdesi']),
      amount: z.string(),
      percent: z.string(),
      vatRate: z
        .string()
        .refine((value) => ['0', '1', '10', '20'].includes(value), 'KDV oranını seçin.'),
      validFrom: startDate(today),
      validTo: z.string(),
    })
    .superRefine((values, ctx) => {
      // Tip ile tutar/oran uyumu (sunucu `kind_amount_mismatch`): yalnız ilgili alan doğrulanır.
      if (values.kind === 'satis_yuzdesi') {
        const parsed = parseDecimalInput(values.percent, 4);
        if (!parsed.ok) {
          ctx.addIssue({
            code: 'custom',
            path: ['percent'],
            message: describeParseFailure(parsed.reason, {
              label: 'Oran',
              kind: 'percent',
              maxFraction: 4,
              example: '2,5',
              empty: 'Oranı yazın.',
            }),
          });
        } else if (
          compareDecimal(parsed.value, '0') <= 0 ||
          compareDecimal(parsed.value, '100') > 0
        ) {
          ctx.addIssue({
            code: 'custom',
            path: ['percent'],
            message: "Oran 0'dan büyük, en çok 100 olmalı.",
          });
        }
      } else {
        const parsed = parseDecimalInput(values.amount, 2);
        if (!parsed.ok) {
          ctx.addIssue({
            code: 'custom',
            path: ['amount'],
            message: describeParseFailure(parsed.reason, {
              label: 'Tutar',
              kind: 'money',
              maxFraction: 2,
              example: '12,50',
              empty: 'Tutarı yazın.',
            }),
          });
        } else if (
          compareDecimal(parsed.value, '0') < 0 ||
          compareDecimal(parsed.value, MAX_EXPENSE_AMOUNT) > 0
        ) {
          ctx.addIssue({
            code: 'custom',
            path: ['amount'],
            message: 'Tutar 0 ile 100.000 arasında olmalı.',
          });
        }
      }
      if (values.validTo !== '') {
        if (!isDateText(values.validTo)) {
          ctx.addIssue({ code: 'custom', path: ['validTo'], message: 'Bitiş tarihini seçin.' });
        } else if (isDateText(values.validFrom) && values.validTo < values.validFrom) {
          ctx.addIssue({
            code: 'custom',
            path: ['validTo'],
            message: 'Bitiş tarihi başlangıçtan önce olamaz.',
          });
        }
      }
    });
}

export function toExpenseBody(values: ExpenseFormValues): VariableExpenseIn {
  const percentKind = values.kind === 'satis_yuzdesi';
  return {
    name: values.name.trim(),
    kind: values.kind,
    amount_excl_vat: percentKind ? null : toMoneyString(parsedOrThrow(values.amount, 2)),
    percent: percentKind ? parsedOrThrow(values.percent, 4) : null,
    vat_rate: Number(values.vatRate),
    valid_from: values.validFrom,
    valid_to: values.validTo === '' ? null : values.validTo,
  };
}

// --------------------------------------------------------------------------- sunucu 422 hataları

/** Sunucu hata kodu -> Türkçe cümle (girdi değeri hiçbir zaman yansıtılmaz). */
const CODE_MESSAGES: Record<string, string> = {
  carrier_invalid: 'Bu kargo firması kullanılamaz. Listeden seçin.',
  desi_out_of_range: "Desi 0'dan büyük, en çok 1.000 ve en çok 2 ondalıklı olmalı.",
  price_out_of_range: 'Fiyat 0 ile 100.000 arasında ve en çok 2 ondalıklı olmalı.',
  brackets_empty: 'En az bir desi kademesi ekleyin.',
  too_many_brackets: 'En çok 50 kademe girilebilir.',
  brackets_not_increasing: 'Kademelerin üst desisi artan sırada olmalı.',
  amount_out_of_range: 'Tutar izin verilen aralıkta ve en çok 2 ondalıklı olmalı.',
  percent_out_of_range: "Oran 0'dan büyük, en çok 100 ve en çok 4 ondalıklı olmalı.",
  vat_rate_invalid: 'KDV oranı yüzde 0, 1, 10 ya da 20 olmalı.',
  name_invalid: 'Ad 1-80 karakter olmalı.',
  kind_amount_mismatch: 'Satış yüzdesinde yalnız oran, diğer türlerde yalnız tutar girilir.',
  valid_to_before_valid_from: 'Bitiş tarihi başlangıçtan önce olamaz.',
  valid_from_out_of_range:
    'Başlangıç tarihi 1 Ocak 2000 ile bugünden en çok 366 gün sonrası arasında olmalı.',
  decimal_invalid: 'Geçerli bir sayı yazın.',
  date_type: 'Geçerli bir tarih seçin.',
  date_invalid: 'Geçerli bir tarih seçin.',
  too_many_tariff_versions: 'Bu hesapta en çok 200 tarife sürümü tutulabilir.',
  too_many_service_fee_versions: 'Bu hesapta en çok 200 hizmet bedeli sürümü tutulabilir.',
  too_many_expenses: 'Bu hesapta en çok 50 değişken gider tutulabilir.',
};

export function describeFieldCode(code: string): string {
  return CODE_MESSAGES[code] ?? 'Bu değeri kontrol edin.';
}

const FIELD_NAMES: Record<string, string> = {
  max_desi: 'maxDesi',
  valid_from: 'validFrom',
  valid_to: 'validTo',
  vat_rate: 'vatRate',
  default_desi: 'desi',
  amount_excl_vat: 'amount',
  price_includes_vat: 'vatMode',
  amount_includes_vat: 'vatMode',
};

/** Sunucunun alan yolu ("brackets.0.max_desi") -> form alan yolu ("brackets.0.maxDesi"). */
export function formFieldPath(serverField: string): string {
  return serverField
    .split('.')
    .map((segment) => FIELD_NAMES[segment] ?? segment)
    .join('.');
}

export interface MappedFieldError {
  /** Form alan yolu; boş: gövde düzeyi hata */
  path: string;
  message: string;
}

export function mapFieldErrors(errors: readonly ApiFieldError[]): MappedFieldError[] {
  return errors.map((error) => ({
    path: formFieldPath(error.field),
    message: describeFieldCode(error.code),
  }));
}
