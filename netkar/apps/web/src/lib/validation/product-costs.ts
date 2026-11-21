// Ürün maliyeti formunun Zod şeması ve sunucu hata kodu eşlemesi. Kurallar sunucudakilerle aynıdır
// (services/api/app/services/product_costs.py `check_unit_cost`, `check_vat_rate`, `check_valid_from`);
// sunucu doğrulaması esastır, burası hızlı geri bildirimdir. Form değerleri metindir (kullanıcının yazdığı biçim).
import { z } from 'zod';

import type { ApiFieldError } from '@/lib/api/client';
import type { CostUpsertBody } from '@/lib/api/product-costs';
import { compareDecimal } from '@/lib/profit/decimal-math';
import {
  MAX_FUTURE_DAYS,
  MIN_VALID_FROM,
  addDays,
  isDateText,
  parseDecimalInput,
  toMoneyString,
} from '@/lib/profit/settings-input';
import { describeParseFailure } from '@/lib/validation/profit-settings';

/** Sunucu `MAX_UNIT_COST` ve `ALLOWED_VAT_RATES` ile aynı */
export const MAX_UNIT_COST = '10000000';
export const COST_VAT_RATES = ['0', '1', '10', '20'] as const;
export type CostVatRate = (typeof COST_VAT_RATES)[number];

export interface CostFormValues {
  unitCost: string;
  vatRate: CostVatRate;
  validFrom: string;
}

export function costSchema(today: string) {
  return z.object({
    unitCost: z.string().superRefine((text, ctx) => {
      const parsed = parseDecimalInput(text, 2);
      if (!parsed.ok) {
        ctx.addIssue({
          code: 'custom',
          message: describeParseFailure(parsed.reason, {
            label: 'Maliyet',
            kind: 'money',
            maxFraction: 2,
            example: '54,50',
            empty: 'Birim maliyeti yazın.',
          }),
        });
        return;
      }
      if (compareDecimal(parsed.value, '0') <= 0) {
        ctx.addIssue({ code: 'custom', message: "Maliyet 0'dan büyük olmalı." });
      } else if (compareDecimal(parsed.value, MAX_UNIT_COST) > 0) {
        ctx.addIssue({ code: 'custom', message: 'Maliyet en çok 10.000.000 TL olabilir.' });
      }
    }),
    vatRate: z.enum(COST_VAT_RATES, { error: 'KDV oranını seçin.' }),
    validFrom: z.string().superRefine((text, ctx) => {
      if (!isDateText(text)) {
        ctx.addIssue({ code: 'custom', message: 'Geçerlilik tarihini seçin.' });
        return;
      }
      if (text < MIN_VALID_FROM || text > addDays(today, MAX_FUTURE_DAYS)) {
        ctx.addIssue({
          code: 'custom',
          message:
            'Geçerlilik tarihi 1 Ocak 2000 ile bugünden en çok 366 gün sonrası arasında olmalı.',
        });
      }
    }),
  });
}

/** Doğrulanmış form değerinden API gövdesi: tutar kuruş biçiminde dizge ("54.50"), oran tamsayı dizgesi */
export function toCostBody(values: CostFormValues): CostUpsertBody {
  const parsed = parseDecimalInput(values.unitCost, 2);
  if (!parsed.ok) throw new TypeError('Doğrulanmamış değer gönderilemez.');
  return {
    valid_from: values.validFrom,
    unit_cost_excl_vat: toMoneyString(parsed.value),
    vat_rate: values.vatRate,
  };
}

// --------------------------------------------------------------------------- sunucu 422 hataları

/** Sunucu hata kodu -> Türkçe cümle (girdi değeri hiçbir zaman yansıtılmaz). */
const CODE_MESSAGES: Record<string, string> = {
  cost_invalid: 'Maliyet geçerli bir sayı olmalı.',
  cost_not_positive: "Maliyet 0'dan büyük olmalı.",
  cost_too_large: 'Maliyet en çok 10.000.000 TL olabilir.',
  cost_too_many_decimals: 'Kuruş en fazla 2 hane olabilir (12,55).',
  decimal_invalid: 'Maliyet geçerli bir sayı olmalı. Örnek: 54,50',
  vat_rate_invalid: 'KDV oranı yüzde 0, 1, 10 ya da 20 olmalı.',
  valid_from_out_of_range:
    'Geçerlilik tarihi 1 Ocak 2000 ile bugünden en çok 366 gün sonrası arasında olmalı.',
  date_type: 'Geçerli bir tarih seçin.',
  date_parsing: 'Geçerli bir tarih seçin.',
  date_from_datetime_parsing: 'Geçerli bir tarih seçin.',
  date_from_datetime_inexact: 'Geçerli bir tarih seçin.',
  missing: 'Bu alanı doldurun.',
  string_pattern_mismatch: 'Bu barkod biçimi maliyet girişinde desteklenmiyor.',
  string_too_long: 'Bu barkod biçimi maliyet girişinde desteklenmiyor.',
};

export function describeCostCode(code: string): string {
  return CODE_MESSAGES[code] ?? 'Bu değeri kontrol edin.';
}

const FIELD_NAMES: Record<string, keyof CostFormValues> = {
  unit_cost_excl_vat: 'unitCost',
  vat_rate: 'vatRate',
  valid_from: 'validFrom',
};

export interface MappedCostError {
  /** Form alanı; null: gövde düzeyi hata (tanınmayan alan) */
  field: keyof CostFormValues | null;
  message: string;
}

/** Sunucunun 422 alan hatalarını form alanlarına ve Türkçe cümlelere çevirir. */
export function mapCostErrors(errors: readonly ApiFieldError[]): MappedCostError[] {
  return errors.map((error) => ({
    field: FIELD_NAMES[error.field] ?? null,
    message: describeCostCode(error.code),
  }));
}
