'use client';

import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';
import type { FieldValues, UseFormReturn } from 'react-hook-form';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { decimalSign, exclusiveOfVat } from '@/lib/profit/decimal-math';
import {
  formatDesi,
  formatPlainNumber,
  parseDecimalInput,
  toMoneyString,
} from '@/lib/profit/settings-input';
import { formatTRY } from '@/lib/format';
import { cn } from '@/lib/utils';
import { mapFieldErrors } from '@/lib/validation/profit-settings';

export interface ParsedEcho {
  /** ok: ayrıştırılan değer; warn: yazılan metin okunamadı ya da belirsiz */
  tone: 'ok' | 'warn';
  text: string;
}

/**
 * Yazılan sayının ayrıştırılmış halini tr-TR biçimiyle yansıtır (AF-01): "Kaydedilecek: 12,55 TL". Böylece
 * "12.550" gibi bir yazım sessizce başka bir tutara dönüşmez, kullanıcı değeri kaydetmeden görür. Boş metinde null.
 * Para alanında KDV dahil girişte hariç karşılığı da eklenir ("54,00 TL KDV dahil = 45,00 TL KDV hariç").
 * Hesap Decimal ile yapılır (float yok). Belirsiz ya da fazla haneli metin `warn` olarak bildirilir.
 */
export function parsedEcho(
  text: string,
  options:
    | { kind: 'money'; includesVat: boolean; vatRate: number | string }
    | { kind: 'desi' }
    | { kind: 'percent' },
): ParsedEcho | null {
  if (text.trim() === '') return null;
  const maxFraction = options.kind === 'money' ? 2 : options.kind === 'desi' ? 2 : 4;
  const parsed = parseDecimalInput(text, maxFraction);
  if (!parsed.ok) {
    if (parsed.reason === 'ambiguous') {
      return {
        tone: 'warn',
        text: 'Okunamadı: ondalık için virgül yazın (12,5). Nokta yalnız binlik ayracıdır (1.250).',
      };
    }
    if (parsed.reason === 'too_many_decimals') {
      return {
        tone: 'warn',
        text:
          options.kind === 'money'
            ? 'Okunamadı: kuruş en fazla 2 hane olabilir (12,55). Binlik için nokta kullanın (1.250,00).'
            : `Okunamadı: en çok ${maxFraction} ondalık hane yazılabilir.`,
      };
    }
    return null;
  }
  if (options.kind === 'desi') {
    return { tone: 'ok', text: `Kaydedilecek: ${formatDesi(parsed.value)} desi` };
  }
  if (options.kind === 'percent') {
    return { tone: 'ok', text: `Kaydedilecek: %${formatPlainNumber(parsed.value, 4)}` };
  }
  const money = toMoneyString(parsed.value);
  const entered = formatTRY(money, { style: 'code' });
  if (!options.includesVat) return { tone: 'ok', text: `Kaydedilecek: ${entered} KDV hariç` };
  return {
    tone: 'ok',
    text: `Kaydedilecek: ${entered} KDV dahil = ${formatTRY(exclusiveOfVat(money, options.vatRate), { style: 'code' })} KDV hariç`,
  };
}

/** Alanın altındaki yansıma satırı (aria-live yok: her tuş vuruşunda duyurulmaz; alan bu satıra bağlıdır). */
export function EchoLine({ echo }: { echo: ParsedEcho }) {
  return (
    <span className={cn('num', echo.tone === 'warn' && 'font-medium text-warning')}>
      {echo.text}
    </span>
  );
}

/** Girilen metin geçerli ve 0 mu ("0 girildi" rozeti, AB-07) */
export function isZeroText(text: string): boolean {
  const parsed = parseDecimalInput(text, 2);
  return parsed.ok && decimalSign(parsed.value) === 0;
}

export function ZeroEnteredNote({ children }: { children: ReactNode }) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Badge variant="warning">0 girildi</Badge>
      <span>{children}</span>
    </span>
  );
}

/**
 * Sunucu 422 alan hatalarını form alanlarının yanına koyar; tanınmayan ya da gövde düzeyi hata form başında
 * gösterilir. Sunucu girdi değerini yansıtmaz; metinler koddan Türkçe üretilir.
 */
export function applyServerErrors<T extends FieldValues>(
  form: UseFormReturn<T>,
  error: ApiError,
  knownFields: readonly string[],
): void {
  const mapped = mapFieldErrors(error.errors ?? []);
  let rootMessage: string | null = null;
  for (const item of mapped) {
    const base = item.path.split('.')[0] ?? '';
    if (item.path !== '' && knownFields.includes(base)) {
      const path = item.path === 'brackets' ? 'brackets.root' : item.path;
      form.setError(path as never, { type: 'server', message: item.message });
    } else {
      rootMessage = item.message;
    }
  }
  if (mapped.length === 0) {
    rootMessage = 'İstek geçerli değil. Girdiğiniz değerleri kontrol edip tekrar deneyin.';
  }
  if (rootMessage) form.setError('root', { type: 'server', message: rootMessage });
}

/** Form gövde düzeyi hata satırı */
export function FormRootError({ message }: { message: string | undefined }) {
  if (!message) return null;
  return (
    <p role="alert" className="flex items-start gap-1.5 text-sm font-medium text-loss">
      <span aria-hidden="true" className="mt-0.5 font-bold">
        !
      </span>
      <span>
        <span className="sr-only">Hata: </span>
        {message}
      </span>
    </p>
  );
}

export function FormActions({
  submitLabel,
  pending,
  onCancel,
}: {
  submitLabel: string;
  pending: boolean;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      <Button variant="secondary" onClick={onCancel} disabled={pending}>
        Vazgeç
      </Button>
      <Button type="submit" disabled={pending}>
        {pending ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
        {submitLabel}
      </Button>
    </div>
  );
}
