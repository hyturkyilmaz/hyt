'use client';

import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';
import type { FieldValues, UseFormReturn } from 'react-hook-form';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { decimalSign, exclusiveOfVat } from '@/lib/profit/decimal-math';
import { parseDecimalInput, toMoneyString } from '@/lib/profit/settings-input';
import { formatTRY } from '@/lib/format';
import { mapFieldErrors } from '@/lib/validation/profit-settings';

/** Sistem parametresi (K02): kargo ve hizmet bedeli KDV oranı %20. Yazımdan sonra liste sunucunun hesabını gösterir. */
export const SHIPPING_VAT_RATE = 20;
export const SERVICE_FEE_VAT_RATE = 20;

/**
 * Girilen tutarın KDV hariç karşılığı (UX §8.1): "54,00 TL KDV dahil = 45,00 TL KDV hariç". Hariç girişte ya da
 * tutar geçerli değilse null. Hesap Decimal ile yapılır (float yok).
 */
export function vatEquivalentText(text: string, includesVat: boolean, rate: number): string | null {
  if (!includesVat) return null;
  const parsed = parseDecimalInput(text, 2);
  if (!parsed.ok) return null;
  const money = toMoneyString(parsed.value);
  return `${formatTRY(money, { style: 'code' })} KDV dahil = ${formatTRY(exclusiveOfVat(money, rate), { style: 'code' })} KDV hariç`;
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
