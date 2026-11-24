'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';

import { ChoiceGroup } from '@/components/settings/fields';
import { EchoLine, FormActions, FormRootError } from '@/components/settings/settings-forms';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
import { ApiError } from '@/lib/api/client';
import {
  productCostsApi,
  type CostUpsertResult,
  type ProductCostItem,
} from '@/lib/api/product-costs';
import { costEcho, costSince, costSummary, describeCostSaveError } from '@/lib/profit/cost-present';
import { addDays, formatLongDate, isDateText, toInputText } from '@/lib/profit/settings-input';
import { useReportQuery } from '@/lib/profit/use-report-query';
import {
  COST_VAT_RATES,
  costSchema,
  mapCostErrors,
  toCostBody,
  type CostFormValues,
  type CostVatRate,
} from '@/lib/validation/product-costs';

/** İlk maliyette geçmiş siparişleri de kapsamak için önerilen geri bakış (ayar ekranlarıyla aynı 92 gün) */
const FIRST_COST_LOOKBACK_DAYS = 92;

export function productLabel(item: ProductCostItem): string {
  return item.title && item.title.trim() ? item.title : 'Başlıksız ürün';
}

function isVatRate(value: number): value is 0 | 1 | 10 | 20 {
  return value === 0 || value === 1 || value === 10 || value === 20;
}

export function CostFormDialog({
  accountId,
  item,
  today,
  onSaved,
  onClose,
}: {
  accountId: string;
  item: ProductCostItem;
  today: string;
  onSaved: (result: CostUpsertResult) => void;
  onClose: () => void;
}) {
  const current = item.current_cost;
  const schema = useMemo(() => costSchema(today), [today]);
  const firstDay = addDays(today, -FIRST_COST_LOOKBACK_DAYS);
  const [pending, setPending] = useState(false);
  const form = useForm<CostFormValues>({
    resolver: zodResolver(schema),
    defaultValues: current
      ? {
          unitCost: toInputText(current.unit_cost_excl_vat),
          vatRate: isVatRate(current.vat_rate) ? (String(current.vat_rate) as CostVatRate) : '20',
          validFrom: today,
        }
      : { unitCost: '', vatRate: '20', validFrom: firstDay },
  });
  const [mode, setMode] = useState<'yeni' | 'duzelt'>('yeni');
  function chooseMode(next: 'yeni' | 'duzelt') {
    setMode(next);
    if (current) {
      form.setValue('validFrom', next === 'duzelt' ? current.valid_from : today, {
        shouldValidate: true,
      });
    }
  }
  const watched = useWatch({ control: form.control });
  const echo = costEcho(watched.unitCost ?? '', watched.vatRate ?? '20');
  const history = useReportQuery(true, `${accountId}|${item.barcode}`, (signal) =>
    productCostsApi.history(accountId, item.barcode, signal),
  );

  async function submit(values: CostFormValues) {
    setPending(true);
    form.clearErrors('root');
    try {
      const result = await productCostsApi.upsert(accountId, item.barcode, toCostBody(values));
      onSaved(result);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422 && error.code === 'validation-error') {
        const mapped = mapCostErrors(error.errors ?? []);
        let root: string | null = null;
        for (const entry of mapped) {
          if (entry.field) form.setError(entry.field, { type: 'server', message: entry.message });
          else root = entry.message;
        }
        if (mapped.length === 0) {
          root = 'İstek geçerli değil. Girdiğiniz değerleri kontrol edip tekrar deneyin.';
        }
        if (root) form.setError('root', { type: 'server', message: root });
      } else {
        form.setError('root', { type: 'server', message: describeCostSaveError(error) });
      }
    } finally {
      setPending(false);
    }
  }

  const dateValue = watched.validFrom ?? '';
  return (
    <Dialog open onOpenChange={(open) => (!open && !pending ? onClose() : undefined)}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto" aria-busy={pending}>
        <DialogHeader>
          <DialogTitle>{current ? 'Maliyeti düzenle' : 'Maliyet gir'}</DialogTitle>
          <DialogDescription>
            <span className="break-words font-medium text-foreground">{productLabel(item)}</span>
            <span className="num block break-all">Barkod: {item.barcode}</span>
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(submit)}
            noValidate
            aria-label="Ürün maliyeti"
            className="flex flex-col gap-5"
          >
            <FormField
              control={form.control}
              name="unitCost"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Birim maliyet (KDV hariç, TL)</FormLabel>
                  <FormControl>
                    <Input inputMode="decimal" autoComplete="off" placeholder="54,50" {...field} />
                  </FormControl>
                  <FormDescription>
                    {echo ? (
                      <EchoLine echo={echo} />
                    ) : (
                      'Ondalık için virgül yazın (54,50). Nokta yalnız binlik ayracıdır (1.250).'
                    )}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="vatRate"
              render={({ field }) => (
                <ChoiceGroup
                  legend="KDV oranı"
                  name="costVatRate"
                  value={field.value}
                  onChange={field.onChange}
                  error={form.formState.errors.vatRate?.message}
                  options={COST_VAT_RATES.map((rate) => ({ value: rate, label: `%${rate}` }))}
                  description="Ürünün alış KDV oranı. %20 için 20 seçin."
                />
              )}
            />
            {current ? (
              <ChoiceGroup
                legend="Bu değişiklik nasıl kaydedilsin?"
                name="costEditMode"
                value={mode}
                onChange={chooseMode}
                options={[
                  {
                    value: 'yeni',
                    label: 'Bu tarihten itibaren yeni maliyet',
                    hint: 'Maliyet gerçekten değişti. Eski kayıt geçmişte kalır, seçeceğiniz tarihten sonraki siparişler yeni maliyetle hesaplanır.',
                  },
                  {
                    value: 'duzelt',
                    label: 'Mevcut kaydı düzelt (aynı tarih)',
                    hint: `Yanlış girdim. ${formatLongDate(current.valid_from)} tarihli kaydın üstüne yazılır; o tarihten sonraki siparişlerin kârı da değişir.`,
                  },
                ]}
              />
            ) : null}
            {mode === 'duzelt' && current ? (
              <p className="text-sm text-muted-foreground">
                Düzeltilecek kayıt: {formatLongDate(current.valid_from)} tarihli.
              </p>
            ) : (
              <FormField
                control={form.control}
                name="validFrom"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Geçerlilik tarihi</FormLabel>
                    <FormControl>
                      <Input type="date" {...field} />
                    </FormControl>
                    <FormDescription>
                      {isDateText(dateValue)
                        ? `${formatLongDate(dateValue)} ve sonrasındaki siparişlerde kullanılır${current ? '.' : '; öncesi eksik kalır.'}`
                        : 'Bu tarihten sonraki siparişlerde kullanılır.'}{' '}
                      {current
                        ? 'Mevcut kaydın tarihini seçerseniz o kayıt düzeltilir.'
                        : 'Geçmiş siparişlerin kârı da hesaplansın diye ilk girişte 92 gün öncesi önerilir.'}
                    </FormDescription>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => form.setValue('validFrom', today, { shouldValidate: true })}
                      >
                        Bugün
                      </Button>
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            <FormRootError message={form.formState.errors.root?.message} />
            <FormActions submitLabel="Kaydet" pending={pending} onCancel={onClose} />
          </form>
        </Form>
        <section aria-labelledby="maliyet-gecmisi" className="flex flex-col gap-2">
          <h3 id="maliyet-gecmisi" className="text-base font-semibold">
            Maliyet geçmişi
          </h3>
          {history.state.status === 'loading' ? (
            <p role="status" className="text-sm text-muted-foreground">
              Geçmiş yükleniyor
            </p>
          ) : null}
          {history.state.status === 'error' ? (
            <p className="text-sm text-muted-foreground">
              Geçmiş yüklenemedi.{' '}
              <button
                type="button"
                onClick={history.retry}
                className="text-primary underline underline-offset-4"
              >
                Tekrar dene
              </button>
            </p>
          ) : null}
          {history.state.status === 'ready' && history.state.data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">Bu ürün için henüz maliyet girilmedi.</p>
          ) : null}
          {history.state.status === 'ready' && history.state.data.items.length > 0 ? (
            <ul role="list" className="flex list-none flex-col gap-1 p-0 text-sm">
              {history.state.data.items.map((cost) => (
                <li key={cost.valid_from} className="num">
                  {costSummary(cost)}
                  <span className="block text-muted-foreground">{costSince(cost)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </DialogContent>
    </Dialog>
  );
}
