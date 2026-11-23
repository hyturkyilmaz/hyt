// Uyarı eşikleri formunun Zod şeması. Aralıklar sunucudakilerle aynıdır (services/api alerts_schemas.py,
// migrasyon 0025 CHECK kısıtları): tutar 0-1.000.000, reklam payı 50-100, iade farkı 0-100 puan, en çok 2 ondalık.
// Sunucu doğrulaması esastır; burası hızlı geri bildirimdir. Form değerleri metindir (kullanıcının yazdığı biçim,
// ondalık virgül); API gövdesine `toAlertSettingsBody` ile Decimal dizgesi olarak çevrilir.
import { z } from 'zod';

import {
  RULE_NAMES,
  type AlertSettings,
  type AlertSettingsBody,
  type RuleName,
} from '@/lib/api/alerts';
import { compareDecimal } from '@/lib/profit/decimal-math';
import { parseDecimalInput, toInputText, toMoneyString } from '@/lib/profit/settings-input';
import { describeParseFailure } from '@/lib/validation/profit-settings';

function bounded(options: {
  label: string;
  min: string;
  max: string;
  rangeText: string;
  kind: 'money' | 'percent';
  example: string;
}) {
  return z.string().superRefine((text, ctx) => {
    const parsed = parseDecimalInput(text, 2);
    if (!parsed.ok) {
      ctx.addIssue({
        code: 'custom',
        message: describeParseFailure(parsed.reason, {
          label: options.label,
          kind: options.kind,
          maxFraction: 2,
          example: options.example,
          empty: `${options.label} yazın.`,
        }),
      });
      return;
    }
    if (
      compareDecimal(parsed.value, options.min) < 0 ||
      compareDecimal(parsed.value, options.max) > 0
    ) {
      ctx.addIssue({ code: 'custom', message: `${options.label} ${options.rangeText}` });
    }
  });
}

const money = (label: string) =>
  bounded({
    label,
    min: '0',
    max: '1000000',
    rangeText: '0 ile 1.000.000 TL arasında olmalı.',
    kind: 'money',
    example: '5,00',
  });

export const alertSettingsSchema = z.object({
  loss_min_amount: money('Zarar alt sınırı'),
  ad_share_percent: bounded({
    label: 'Reklam payı eşiği',
    min: '50',
    max: '100',
    rangeText: '%50 ile %100 arasında olmalı.',
    kind: 'percent',
    example: '100',
  }),
  ad_min_spend: money('Reklam en az harcama'),
  deduction_notify_min: money('Kesinti alt sınırı'),
  return_min_diff_points: bounded({
    label: 'İade farkı',
    min: '0',
    max: '100',
    rangeText: '0 ile 100 puan arasında olmalı.',
    kind: 'percent',
    example: '5',
  }),
  rules_enabled: z.array(z.enum(RULE_NAMES as [RuleName, ...RuleName[]])),
});

export type AlertSettingsFormValues = z.infer<typeof alertSettingsSchema>;

/** Sunucudaki değerler -> form metinleri (ondalık virgül, iki hane). */
export function toAlertSettingsForm(settings: AlertSettings): AlertSettingsFormValues {
  const text = (value: string) => toInputText(toMoneyString(value));
  return {
    loss_min_amount: text(settings.loss_min_amount),
    ad_share_percent: text(settings.ad_share_percent),
    ad_min_spend: text(settings.ad_min_spend),
    deduction_notify_min: text(settings.deduction_notify_min),
    return_min_diff_points: text(settings.return_min_diff_points),
    rules_enabled: [...settings.rules_enabled],
  };
}

/** Doğrulanmış form -> PUT gövdesi (tam değiştirme, Decimal dizgeleri). */
export function toAlertSettingsBody(values: AlertSettingsFormValues): AlertSettingsBody {
  const dec = (text: string) => {
    const parsed = parseDecimalInput(text, 2);
    if (!parsed.ok) throw new Error('Doğrulanmamış değer gönderilemez.');
    return toMoneyString(parsed.value);
  };
  return {
    loss_min_amount: dec(values.loss_min_amount),
    ad_share_percent: dec(values.ad_share_percent),
    ad_min_spend: dec(values.ad_min_spend),
    deduction_notify_min: dec(values.deduction_notify_min),
    return_min_diff_points: dec(values.return_min_diff_points),
    // Kanonik sıra: sunucu da böyle sıralar
    rules_enabled: RULE_NAMES.filter((name) => values.rules_enabled.includes(name)),
  };
}
