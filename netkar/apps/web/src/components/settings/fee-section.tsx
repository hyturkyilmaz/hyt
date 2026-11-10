'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';

import { ChoiceGroup, SectionHeading, SectionNotice } from '@/components/settings/fields';
import { useSettingsWriter } from '@/components/settings/settings-writer';
import {
  FormActions,
  FormRootError,
  SERVICE_FEE_VAT_RATE,
  ZeroEnteredNote,
  applyServerErrors,
  isZeroText,
  vatEquivalentText,
} from '@/components/settings/settings-forms';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
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
import type { ApiError } from '@/lib/api/client';
import { profitSettingsApi, type ServiceFeeOut, type SettingsOut } from '@/lib/api/profit-settings';
import { addDays, formatLongDate, toInputText } from '@/lib/profit/settings-input';
import { isZeroAmount, vatPair } from '@/lib/profit/settings-present';
import { feeSchema, toFeeBody, type FeeFormValues } from '@/lib/validation/profit-settings';

const DEFAULT_LOOKBACK_DAYS = 92;

type FormMode = { kind: 'new' } | { kind: 'edit'; fee: ServiceFeeOut };

export function FeeSection({
  accountId,
  settings,
  lookbackDays,
  canEdit,
  today,
}: {
  accountId: string;
  settings: SettingsOut;
  lookbackDays: number | undefined;
  canEdit: boolean;
  today: string;
}) {
  const writer = useSettingsWriter();
  const [mode, setMode] = useState<FormMode | null>(null);
  const fees = settings.service_fee_estimates;
  const complete = settings.completeness.service_fee_estimate_defined;

  function retract(fee: ServiceFeeOut) {
    void writer.run({
      scope: 'hizmet-bedeli',
      topic: 'retract-other',
      successText: () => 'Hizmet bedeli sürümü geri çekildi.',
      send: (g) =>
        profitSettingsApi.deleteServiceFee(accountId, fee.id, {
          expected_revision: g.expectedRevision,
          confirm_affects_from: g.confirmAffectsFrom,
        }),
      onStale: () => setMode(null),
    });
  }

  return (
    <Card id="hizmet-bedeli" aria-labelledby="hizmet-bedeli-baslik" className="scroll-mt-4">
      <CardHeader>
        <SectionHeading
          id="hizmet-bedeli"
          title="Platform hizmet bedeli tahmini"
          badge={
            <Badge variant={complete ? 'info' : 'warning'}>
              {complete ? 'Bugün geçerli tahmin var' : 'Bugün geçerli tahmin yok'}
            </Badge>
          }
          description="Trendyol'un sipariş başına kestiği hizmet bedelinin tahmini. Kesin fatura gelince o kullanılır; gelene kadar bu tahmin kullanılır."
          action={
            canEdit && mode === null ? (
              <Button variant="secondary" onClick={() => setMode({ kind: 'new' })}>
                <Plus aria-hidden="true" />
                Tahmin ekle
              </Button>
            ) : null
          }
        />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SectionNotice scope="hizmet-bedeli" />
        {mode ? (
          <FeeForm
            key={mode.kind === 'edit' ? mode.fee.id : 'new'}
            accountId={accountId}
            mode={mode}
            lookbackDays={lookbackDays ?? DEFAULT_LOOKBACK_DAYS}
            today={today}
            onClose={() => setMode(null)}
          />
        ) : null}
        {fees.length === 0 && mode === null ? (
          <p className="text-base text-muted-foreground">
            Henüz hizmet bedeli tahmini girmediniz. Tahmin yokken hizmet bedeli &quot;eksik&quot;
            görünür ve net kâr hesaplanamaz. Hizmet bedeli kesilmiyorsa 0 girebilirsiniz.
          </p>
        ) : null}
        {fees.length > 0 ? (
          <ul className="flex list-none flex-col gap-3 p-0">
            {fees.map((fee) => (
              <li key={fee.id} className="flex flex-col gap-3 rounded-lg border border-border p-4">
                <div className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="num text-base font-semibold">
                      {vatPair(fee.amount, fee.amount_excl_vat, fee.amount_includes_vat)}
                    </p>
                    {isZeroAmount(fee.amount) ? <Badge variant="warning">0 girildi</Badge> : null}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Sipariş başına. {formatLongDate(fee.valid_from)} tarihinden itibaren geçerli. Bu
                    tarihten sonraki siparişlerde kullanılır.
                  </p>
                </div>
                {canEdit && mode === null ? (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setMode({ kind: 'edit', fee })}
                      disabled={writer.pending}
                    >
                      Düzenle
                      <span className="sr-only">
                        : {formatLongDate(fee.valid_from)} başlangıçlı tahmin
                      </span>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => retract(fee)}
                      disabled={writer.pending}
                    >
                      Geri çek
                      <span className="sr-only">
                        : {formatLongDate(fee.valid_from)} başlangıçlı tahmin
                      </span>
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}

function FeeForm({
  accountId,
  mode,
  lookbackDays,
  today,
  onClose,
}: {
  accountId: string;
  mode: FormMode;
  lookbackDays: number;
  today: string;
  onClose: () => void;
}) {
  const writer = useSettingsWriter();
  const editing = mode.kind === 'edit' ? mode.fee : null;
  const schema = useMemo(() => feeSchema(today), [today]);
  const form = useForm<FeeFormValues>({
    resolver: zodResolver(schema),
    defaultValues: editing
      ? {
          validFrom: editing.valid_from,
          vatMode: editing.amount_includes_vat ? 'dahil' : 'haric',
          amount: toInputText(editing.amount),
        }
      : { validFrom: addDays(today, -lookbackDays), vatMode: 'dahil', amount: '' },
  });
  const watched = useWatch({ control: form.control });
  const includesVat = (watched.vatMode ?? 'dahil') === 'dahil';
  const amountText = watched.amount ?? '';
  const equivalent = vatEquivalentText(amountText, includesVat, SERVICE_FEE_VAT_RATE);

  function submit(values: FeeFormValues) {
    const body = toFeeBody(values);
    void writer.run({
      scope: 'hizmet-bedeli',
      topic: 'dated',
      successText: (info) =>
        info.action === 'created'
          ? 'Hizmet bedeli tahmini eklendi. Kâr rakamları güncellenir.'
          : 'Hizmet bedeli tahmini güncellendi. Kâr rakamları güncellenir.',
      send: (g) =>
        profitSettingsApi.putServiceFee(accountId, {
          ...body,
          expected_revision: g.expectedRevision,
          confirm_affects_from: g.confirmAffectsFrom,
        }),
      sendFromToday:
        body.valid_from < today
          ? (g) =>
              profitSettingsApi.putServiceFee(accountId, {
                ...body,
                valid_from: today,
                expected_revision: g.expectedRevision,
              })
          : undefined,
      onDone: onClose,
      onInvalid: (error: ApiError) =>
        applyServerErrors(form, error, ['validFrom', 'vatMode', 'amount']),
      onStale: (reason) => {
        if (reason === 'record-ended') onClose();
      },
    });
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(submit)}
        noValidate
        aria-label={editing ? 'Hizmet bedeli tahminini düzenle' : 'Yeni hizmet bedeli tahmini'}
        className="flex flex-col gap-5 rounded-lg border-2 border-primary bg-surface-muted p-4"
      >
        <h3 className="text-lg font-semibold">
          {editing ? 'Hizmet bedeli tahminini düzenle' : 'Yeni hizmet bedeli tahmini'}
        </h3>
        {editing ? (
          <p className="text-sm text-muted-foreground">
            {formatLongDate(editing.valid_from)} başlangıçlı sürüm. Başlangıç tarihi bu sürümde
            değişmez; başka bir tarihten geçerli tutar için &quot;Tahmin ekle&quot; ile yeni sürüm
            girin.
          </p>
        ) : (
          <FormField
            control={form.control}
            name="validFrom"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Başlangıç tarihi</FormLabel>
                <FormControl>
                  <Input type="date" {...field} />
                </FormControl>
                <FormDescription>
                  Bu tarihten sonraki siparişlerde kullanılır. Geçmiş siparişlerinizi de hesaplatmak
                  için hesabınızın ilk siparişinden önceki bir tarih seçin.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
        <FormField
          control={form.control}
          name="vatMode"
          render={({ field }) => (
            <ChoiceGroup
              legend="Tutarı nasıl giriyorsunuz?"
              name="feeVatMode"
              value={field.value}
              onChange={field.onChange}
              options={[
                {
                  value: 'dahil',
                  label: 'KDV dahil',
                  hint: 'KDV hariç karşılığı yanında görünür.',
                },
                { value: 'haric', label: 'KDV hariç', hint: 'Girdiğiniz tutar aynen kullanılır.' },
              ]}
              description={`Hizmet bedeli KDV oranı %${SERVICE_FEE_VAT_RATE}.`}
            />
          )}
        />
        <FormField
          control={form.control}
          name="amount"
          render={({ field }) => (
            <FormItem>
              <FormLabel>
                Sipariş başına tutar ({includesVat ? 'KDV dahil' : 'KDV hariç'}, TL)
              </FormLabel>
              <FormControl>
                <Input inputMode="decimal" autoComplete="off" {...field} />
              </FormControl>
              {isZeroText(amountText) ? (
                <FormDescription>
                  <ZeroEnteredNote>
                    Hizmet bedeli bilerek 0 TL hesaplanır, &quot;eksik&quot; sayılmaz.
                  </ZeroEnteredNote>
                </FormDescription>
              ) : equivalent ? (
                <FormDescription className="num">{equivalent}</FormDescription>
              ) : (
                <FormDescription>Hizmet bedeli kesilmiyorsa 0 yazabilirsiniz.</FormDescription>
              )}
              <FormMessage />
            </FormItem>
          )}
        />
        <FormRootError message={form.formState.errors.root?.message} />
        <FormActions
          submitLabel="Kaydet ve rakamları güncelle"
          pending={writer.pending}
          onCancel={onClose}
        />
      </form>
    </Form>
  );
}
