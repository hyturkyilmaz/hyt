'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';

import { blockedClass, blockedProps } from '@/components/alerts/blocked';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { RULE_NAMES, type AlertSettings, type AlertSettingsBody } from '@/lib/api/alerts';
import { RULE_LABELS } from '@/lib/alerts/present';
import { formatPercent, formatTRY } from '@/lib/format';
import { formatPlainNumber } from '@/lib/profit/settings-input';
import {
  alertSettingsSchema,
  toAlertSettingsBody,
  toAlertSettingsForm,
  type AlertSettingsFormValues,
} from '@/lib/validation/alert-settings';
import { cn } from '@/lib/utils';

type NumericField =
  | 'loss_min_amount'
  | 'ad_share_percent'
  | 'ad_min_spend'
  | 'deduction_notify_min'
  | 'return_min_diff_points';

export const THRESHOLD_FIELDS: readonly {
  name: NumericField;
  label: string;
  suffix: string;
  hint: string;
}[] = [
  {
    name: 'loss_min_amount',
    label: 'Zarar bildirimi alt sınırı',
    suffix: 'TL',
    hint: 'Ürün başına toplam zarar bu tutarın altındaysa uyarı üretilmez.',
  },
  {
    name: 'ad_share_percent',
    label: 'Reklam payı eşiği',
    suffix: '%',
    hint: 'Reklam harcaması, reklam öncesi kârın bu oranına ulaşınca uyarılır (50 ile 100 arası).',
  },
  {
    name: 'ad_min_spend',
    label: 'Reklam en az harcama',
    suffix: 'TL',
    hint: 'Bundan az harcayan ürünler için reklam uyarısı üretilmez.',
  },
  {
    name: 'deduction_notify_min',
    label: 'Kesinti bildirimi alt sınırı',
    suffix: 'TL',
    hint: 'Beklenenden fazla kesinti bu tutarın altındaysa uyarı üretilmez.',
  },
  {
    name: 'return_min_diff_points',
    label: 'İade oranı en az fark',
    suffix: 'puan',
    hint: 'İade oranı önceki döneme göre en az bu kadar puan artınca uyarılır.',
  },
];

/** Eşik değerinin tr-TR gösterimi (salt okur görünüm ve çakışma özeti) */
export function formatThreshold(name: NumericField, value: string): string {
  if (name === 'ad_share_percent') return formatPercent(value, { fractionDigits: 2 });
  if (name === 'return_min_diff_points') return `${formatPlainNumber(value, 2)} puan`;
  return formatTRY(value, { style: 'code' });
}

/** Düzenleyemeyen kullanıcı (viewer) için değerler: yalnız okunur. */
export function ThresholdsReadOnly({ settings }: { settings: AlertSettings }) {
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid gap-3 sm:grid-cols-2">
        {THRESHOLD_FIELDS.map((field) => (
          <div key={field.name} className="flex flex-col gap-0.5">
            <dt className="text-sm text-muted-foreground">{field.label}</dt>
            <dd className="num text-base font-semibold">
              {formatThreshold(field.name, settings[field.name])}
            </dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col gap-2">
        <h3 className="text-base font-semibold">Etkin kurallar</h3>
        <ul role="list" className="flex list-none flex-wrap gap-2">
          {RULE_NAMES.map((rule) => (
            <li key={rule}>
              <Badge variant={settings.rules_enabled.includes(rule) ? 'info' : 'neutral'}>
                {RULE_LABELS[rule]}: {settings.rules_enabled.includes(rule) ? 'Açık' : 'Kapalı'}
              </Badge>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * Hesap eşikleri formu (owner/admin). PUT tam değiştirmedir ve `If-Match` ister: üst bileşen GET'teki ETag'i tutar
 * ve `onSubmit` içinde gönderir. Metin alanları tr-TR yazımıdır (ondalık virgül); doğrulama sunucudaki aralıklarla aynıdır.
 */
export function ThresholdsForm({
  settings,
  blocked,
  saving,
  onSubmit,
}: {
  settings: AlertSettings;
  /** Doğrulanmamış e-posta: kaydet aria-disabled */
  blocked: boolean;
  saving: boolean;
  onSubmit: (body: AlertSettingsBody) => void;
}) {
  const form = useForm<AlertSettingsFormValues>({
    resolver: zodResolver(alertSettingsSchema),
    defaultValues: toAlertSettingsForm(settings),
  });

  // Sunucudaki değer değişince (kayıt, yeniden yükleme) form onu gösterir
  useEffect(() => {
    form.reset(toAlertSettingsForm(settings));
  }, [settings, form]);

  function submit(values: AlertSettingsFormValues) {
    if (blocked || saving) return;
    onSubmit(toAlertSettingsBody(values));
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(submit)}
        noValidate
        aria-label="Hesap eşikleri"
        className="flex flex-col gap-5"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {THRESHOLD_FIELDS.map((field) => (
            <FormField
              key={field.name}
              control={form.control}
              name={field.name}
              render={({ field: input }) => (
                <FormItem>
                  <FormLabel>
                    {field.label} ({field.suffix})
                  </FormLabel>
                  <FormControl>
                    <Input {...input} inputMode="decimal" autoComplete="off" className="num" />
                  </FormControl>
                  <FormDescription>{field.hint}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </div>

        <FormField
          control={form.control}
          name="rules_enabled"
          render={({ field }) => (
            <fieldset className="flex min-w-0 flex-col gap-2">
              <legend className="mb-1 text-base font-semibold">Etkin kurallar</legend>
              {RULE_NAMES.map((rule) => (
                <label
                  key={rule}
                  className="flex min-h-touch cursor-pointer items-start gap-3 text-base"
                >
                  <input
                    type="checkbox"
                    checked={field.value.includes(rule)}
                    onChange={(e) =>
                      field.onChange(
                        e.target.checked
                          ? [...field.value, rule]
                          : field.value.filter((name) => name !== rule),
                      )
                    }
                    className="mt-1.5 size-4 accent-[var(--primary)]"
                  />
                  <span>{RULE_LABELS[rule]}</span>
                </label>
              ))}
              <p className="text-sm text-muted-foreground">
                Kapattığınız kural için bu hesapta yeni uyarı üretilmez.
              </p>
            </fieldset>
          )}
        />

        <div>
          <Button
            type="submit"
            {...blockedProps(blocked)}
            className={cn('w-full sm:w-auto', blockedClass(blocked, 'default'))}
            aria-busy={saving || undefined}
          >
            {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {saving ? 'Kaydediliyor' : 'Eşikleri kaydet'}
          </Button>
        </div>
      </form>
    </Form>
  );
}
