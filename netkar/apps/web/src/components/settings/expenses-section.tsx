'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';

import { SELECT_CLASS, SectionHeading, SectionNotice } from '@/components/settings/fields';
import { useSettingsWriter } from '@/components/settings/settings-writer';
import {
  FormActions,
  FormRootError,
  EchoLine,
  ZeroEnteredNote,
  applyServerErrors,
  isZeroText,
  parsedEcho,
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
import {
  profitSettingsApi,
  type ExpenseKind,
  type SettingsOut,
  type VariableExpenseOut,
} from '@/lib/api/profit-settings';
import { formatLongDate, isDateText, toInputText } from '@/lib/profit/settings-input';
import { startSuggestionNote, suggestStartDay } from '@/lib/profit/settings-server-facts';
import {
  EXPENSE_KIND_LABELS,
  describeExpenseAmount,
  describeValidity,
} from '@/lib/profit/settings-present';
import {
  ALLOWED_VAT_RATES,
  expenseSchema,
  toExpenseBody,
  type ExpenseFormValues,
} from '@/lib/validation/profit-settings';

const DEFAULT_LOOKBACK_DAYS = 92;

type FormMode = { kind: 'new' } | { kind: 'edit'; expense: VariableExpenseOut };

export function ExpensesSection({
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
  const expenses = settings.variable_expenses;

  function retract(expense: VariableExpenseOut) {
    void writer.run({
      scope: 'giderler',
      topic: 'retract-other',
      successText: () => `${expense.name} gideri geri çekildi.`,
      clientConfirm: {
        title: `${expense.name} gideri geri çekilsin mi?`,
        body: 'Önceki değer ayar geçmişinde kalır.',
        applyLabel: 'Geri çek',
      },
      send: (g) =>
        profitSettingsApi.deleteExpense(accountId, expense.id, {
          expected_revision: g.expectedRevision,
          confirm_affects_from: g.confirmAffectsFrom,
        }),
      onStale: () => setMode(null),
    });
  }

  return (
    <Card as="section" id="giderler" aria-labelledby="giderler-baslik" className="scroll-mt-4">
      <CardHeader>
        <SectionHeading
          id="giderler"
          title="Değişken giderler"
          description="Paketleme, e-fatura gibi satış başına değişen giderler. Net kârdan düşülür. Hiç gider girmemek, bu giderlerin 0 olduğu anlamına gelir."
          action={
            canEdit && mode === null ? (
              <Button variant="secondary" onClick={() => setMode({ kind: 'new' })}>
                <Plus aria-hidden="true" />
                Gider ekle
              </Button>
            ) : null
          }
        />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SectionNotice scope="giderler" />
        {mode ? (
          <ExpenseForm
            key={mode.kind === 'edit' ? mode.expense.id : 'new'}
            accountId={accountId}
            mode={mode}
            lookbackDays={lookbackDays ?? DEFAULT_LOOKBACK_DAYS}
            today={today}
            earliestOrderDay={settings.earliest_order_day}
            onClose={() => setMode(null)}
          />
        ) : null}
        {expenses.length === 0 && mode === null ? (
          <p className="text-base text-muted-foreground">Henüz değişken gider girmediniz.</p>
        ) : null}
        {expenses.length > 0 ? (
          <ul className="flex list-none flex-col gap-3 p-0">
            {expenses.map((expense) => (
              <li
                key={expense.id}
                className="flex flex-col gap-3 rounded-lg border border-border p-4"
              >
                <div className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold">{expense.name}</h3>
                    <Badge variant="neutral">{EXPENSE_KIND_LABELS[expense.kind]}</Badge>
                    {expense.kind !== 'satis_yuzdesi' &&
                    isZeroText(expense.amount_excl_vat ?? '') ? (
                      <Badge variant="warning">0 girildi</Badge>
                    ) : null}
                  </div>
                  <p className="num text-base">
                    {describeExpenseAmount(expense)}, KDV oranı %{expense.vat_rate}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {describeValidity(expense.valid_from, expense.valid_to)}.
                  </p>
                </div>
                {canEdit && mode === null ? (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setMode({ kind: 'edit', expense })}
                      disabled={writer.pending}
                    >
                      Düzenle
                      <span className="sr-only">: {expense.name}</span>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => retract(expense)}
                      disabled={writer.pending}
                    >
                      Geri çek
                      <span className="sr-only">: {expense.name}</span>
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

const KIND_OPTIONS: readonly ExpenseKind[] = ['siparis_basi', 'adet_basi', 'satis_yuzdesi'];

function ExpenseForm({
  accountId,
  mode,
  lookbackDays,
  today,
  earliestOrderDay,
  onClose,
}: {
  accountId: string;
  mode: FormMode;
  lookbackDays: number;
  today: string;
  /** Sunucudaki en eski sipariş günü; yoksa (sipariş yok ya da eski API) yaklaşık öneri kullanılır */
  earliestOrderDay: string | null | undefined;
  onClose: () => void;
}) {
  const writer = useSettingsWriter();
  const editing = mode.kind === 'edit' ? mode.expense : null;
  const schema = useMemo(() => expenseSchema(today), [today]);
  const suggestion = suggestStartDay({ today, earliestOrderDay, lookbackDays });
  const form = useForm<ExpenseFormValues>({
    resolver: zodResolver(schema),
    defaultValues: editing
      ? {
          name: editing.name,
          kind: editing.kind,
          amount: editing.amount_excl_vat === null ? '' : toInputText(editing.amount_excl_vat),
          percent: editing.percent === null ? '' : toInputText(editing.percent),
          vatRate: String(editing.vat_rate),
          validFrom: editing.valid_from,
          validTo: editing.valid_to ?? '',
        }
      : {
          name: '',
          kind: 'siparis_basi',
          amount: '',
          percent: '',
          vatRate: '20',
          validFrom: suggestion.day,
          validTo: '',
        },
  });
  const watched = useWatch({ control: form.control });
  const kind = watched.kind ?? 'siparis_basi';
  const percentKind = kind === 'satis_yuzdesi';
  const amountText = watched.amount ?? '';
  const amountEcho = parsedEcho(amountText, {
    kind: 'money',
    includesVat: false,
    vatRate: Number(watched.vatRate ?? '20'),
  });
  const percentEcho = parsedEcho(watched.percent ?? '', { kind: 'percent' });

  function submit(values: ExpenseFormValues) {
    const body = toExpenseBody(values);
    const isNew = editing === null;
    const guards = (g: { expectedRevision?: number; confirmAffectsFrom?: string }) => ({
      ...body,
      expected_revision: g.expectedRevision,
      confirm_affects_from: g.confirmAffectsFrom,
    });
    void writer.run({
      scope: 'giderler',
      topic: 'dated',
      successText: () => (isNew ? 'Gider eklendi.' : 'Gider güncellendi.'),
      send: (g) =>
        isNew
          ? profitSettingsApi.createExpense(accountId, guards(g))
          : profitSettingsApi.updateExpense(accountId, editing.id, guards(g)),
      // ADR-0007 §5.2: ikincil düğme yalnız ekleme için (değiştirmede eski satırın başlangıcı da etkiyi belirler)
      sendFromToday:
        // Bugünden önce biten gider bugünden başlatılamaz (bitiş başlangıçtan önce olamaz): düğme yok
        isNew && body.valid_from < today && (body.valid_to === null || body.valid_to >= today)
          ? (g) =>
              profitSettingsApi.createExpense(accountId, {
                ...body,
                valid_from: today,
                expected_revision: g.expectedRevision,
              })
          : undefined,
      onDone: onClose,
      onInvalid: (error: ApiError) =>
        applyServerErrors(form, error, [
          'name',
          'kind',
          percentKind ? 'percent' : 'amount',
          'vatRate',
          'validFrom',
          'validTo',
        ]),
      // Düzenlemede sürüm çakışırsa form kapanır; güncel değerlerle yeniden açılır (AF-11)
      onStale: (reason) => {
        if (reason === 'record-ended' || (reason === 'revision-conflict' && !isNew)) onClose();
      },
    });
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(submit)}
        noValidate
        aria-label={editing ? 'Değişken gideri düzenle' : 'Yeni değişken gider'}
        className="flex flex-col gap-5 rounded-lg border-2 border-primary bg-surface-muted p-4"
      >
        <h3 className="text-lg font-semibold">
          {editing ? `${editing.name} giderini düzenle` : 'Yeni değişken gider'}
        </h3>
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Gider adı</FormLabel>
              <FormControl>
                <Input autoComplete="off" maxLength={120} {...field} />
              </FormControl>
              <FormDescription>Örnek: Paketleme, E-fatura.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="kind"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Nasıl hesaplanır?</FormLabel>
              <FormControl>
                <select {...field} className={SELECT_CLASS}>
                  {KIND_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {EXPENSE_KIND_LABELS[value]}
                    </option>
                  ))}
                </select>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {percentKind ? (
          <FormField
            control={form.control}
            name="percent"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Oran (satış tutarının yüzdesi)</FormLabel>
                <FormControl>
                  <Input inputMode="decimal" autoComplete="off" {...field} />
                </FormControl>
                <FormDescription>
                  En çok 100, en çok 4 ondalık. Ondalık için virgül kullanın. Örnek: 2,5
                </FormDescription>
                {percentEcho ? (
                  <FormDescription>
                    <EchoLine echo={percentEcho} />
                  </FormDescription>
                ) : null}
                <FormMessage />
              </FormItem>
            )}
          />
        ) : (
          <FormField
            control={form.control}
            name="amount"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Tutar (KDV hariç, TL)</FormLabel>
                <FormControl>
                  <Input inputMode="decimal" autoComplete="off" {...field} />
                </FormControl>
                {isZeroText(amountText) ? (
                  <FormDescription>
                    <ZeroEnteredNote>Bu gider bilerek 0 TL hesaplanır.</ZeroEnteredNote>
                  </FormDescription>
                ) : (
                  <FormDescription>
                    {kind === 'adet_basi' ? 'Satılan her adet için' : 'Her sipariş için'} KDV hariç
                    tutarı yazın. Ondalık için virgül kullanın (12,50).
                  </FormDescription>
                )}
                {amountEcho ? (
                  <FormDescription>
                    <EchoLine echo={amountEcho} />
                  </FormDescription>
                ) : null}
                <FormMessage />
              </FormItem>
            )}
          />
        )}
        <FormField
          control={form.control}
          name="vatRate"
          render={({ field }) => (
            <FormItem>
              <FormLabel>KDV oranı</FormLabel>
              <FormControl>
                <select {...field} className={SELECT_CLASS}>
                  {ALLOWED_VAT_RATES.map((rate) => (
                    <option key={rate} value={String(rate)}>
                      %{rate}
                    </option>
                  ))}
                </select>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className="grid gap-4 sm:grid-cols-2">
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
                  {field.value && isDateText(field.value)
                    ? `${formatLongDate(field.value)} ve sonrasındaki siparişlerde kullanılır.`
                    : 'Bu tarihten sonraki siparişlerde kullanılır.'}
                  {editing === null
                    ? ` ${startSuggestionNote(suggestion, lookbackDays, 'short')}`
                    : ''}
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="validTo"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Bitiş tarihi (isteğe bağlı)</FormLabel>
                <FormControl>
                  <Input type="date" {...field} />
                </FormControl>
                <FormDescription>
                  {field.value
                    ? `${formatLongDate(field.value)} tarihine kadar kullanılır.`
                    : 'Boş bırakırsanız süresiz kullanılır.'}
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
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
