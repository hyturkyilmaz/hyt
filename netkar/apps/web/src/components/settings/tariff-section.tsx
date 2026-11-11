'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Plus, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useFieldArray, useForm, useWatch } from 'react-hook-form';

import {
  ChoiceGroup,
  SELECT_CLASS,
  SectionHeading,
  SectionNotice,
} from '@/components/settings/fields';
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
  OTHER_CARRIERS,
  profitSettingsApi,
  type Agreement,
  type CargoTariffOut,
  type CarriersOut,
  type SettingsOut,
} from '@/lib/api/profit-settings';
import { formatDesi, formatLongDate, isDateText, toInputText } from '@/lib/profit/settings-input';
import {
  formatVatRate,
  resolveVatRates,
  startSuggestionNote,
  suggestStartDay,
} from '@/lib/profit/settings-server-facts';
import {
  AGREEMENT_LABELS,
  carrierLabel,
  carrierValue,
  isZeroAmount,
  vatPair,
} from '@/lib/profit/settings-present';
import {
  MAX_BRACKETS,
  tariffSchema,
  toTariffBody,
  type TariffFormValues,
} from '@/lib/validation/profit-settings';

const DEFAULT_LOOKBACK_DAYS = 92;

interface CarriersState {
  status: 'loading' | 'error' | 'ready';
  data: CarriersOut | undefined;
  retry: () => void;
}

type FormMode = { kind: 'new' } | { kind: 'edit'; tariff: CargoTariffOut };

export function TariffSection({
  accountId,
  settings,
  carriers,
  canEdit,
  today,
}: {
  accountId: string;
  settings: SettingsOut;
  carriers: CarriersState;
  canEdit: boolean;
  today: string;
}) {
  const writer = useSettingsWriter();
  const [mode, setMode] = useState<FormMode | null>(null);
  const tariffs = settings.cargo_tariffs;
  const complete = settings.completeness.cargo_tariff_defined;

  function retract(tariff: CargoTariffOut) {
    void writer.run({
      scope: 'kargo',
      topic: 'retract-cargo',
      successText: () => `${carrierLabel(tariff.carrier)} tarifesi geri çekildi.`,
      clientConfirm: {
        title: `${carrierLabel(tariff.carrier)} tarifesi (${formatLongDate(tariff.valid_from)} başlangıçlı) geri çekilsin mi?`,
        body: 'Önceki değer ayar geçmişinde kalır.',
        applyLabel: 'Geri çek',
      },
      send: (g) =>
        profitSettingsApi.deleteCargoTariff(accountId, tariff.id, {
          expected_revision: g.expectedRevision,
          confirm_affects_from: g.confirmAffectsFrom,
        }),
      onStale: () => setMode(null),
    });
  }

  return (
    <Card as="section" id="kargo" aria-labelledby="kargo-baslik" className="scroll-mt-4">
      <CardHeader>
        <SectionHeading
          id="kargo"
          title="Kargo tarifesi"
          badge={
            <Badge variant={complete ? 'info' : 'warning'}>
              {complete ? 'Bugün geçerli tarife var' : 'Bugün geçerli tarife yok'}
            </Badge>
          }
          description="Siparişlerinizin kargo giderini bu tarifeden hesaplarız. Her kademe, yazdığınız desiye kadar olan paketler için geçerlidir (o desi dahil)."
          action={
            canEdit && mode === null ? (
              <Button variant="secondary" onClick={() => setMode({ kind: 'new' })}>
                <Plus aria-hidden="true" />
                Tarife ekle
              </Button>
            ) : null
          }
        />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SectionNotice scope="kargo" />
        {mode ? (
          <TariffForm
            key={mode.kind === 'edit' ? mode.tariff.id : 'new'}
            accountId={accountId}
            mode={mode}
            carriers={carriers}
            existing={tariffs}
            today={today}
            earliestOrderDay={settings.earliest_order_day}
            vatRate={resolveVatRates(settings).shipping}
            onClose={() => setMode(null)}
          />
        ) : null}
        {tariffs.length === 0 && mode === null ? (
          <p className="text-base text-muted-foreground">
            Henüz kargo tarifesi girmediniz. Tarife yokken kargo gideri &quot;eksik&quot; görünür ve
            net kâr hesaplanamaz.
          </p>
        ) : null}
        {(['trendyol', 'seller'] as const).map((agreement) => {
          const group = tariffs.filter((t) => t.agreement === agreement);
          if (group.length === 0) return null;
          return (
            <div key={agreement} className="flex flex-col gap-3">
              <h3 className="text-base font-semibold">{AGREEMENT_LABELS[agreement]} tarifeler</h3>
              <ul className="flex list-none flex-col gap-3 p-0">
                {group.map((tariff) => (
                  <TariffItem
                    key={tariff.id}
                    tariff={tariff}
                    canEdit={canEdit && mode === null}
                    pending={writer.pending}
                    onEdit={() => setMode({ kind: 'edit', tariff })}
                    onRetract={() => retract(tariff)}
                  />
                ))}
              </ul>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function TariffItem({
  tariff,
  canEdit,
  pending,
  onEdit,
  onRetract,
}: {
  tariff: CargoTariffOut;
  canEdit: boolean;
  pending: boolean;
  onEdit: () => void;
  onRetract: () => void;
}) {
  const hasZero = tariff.brackets.some((b) => isZeroAmount(b.price));
  const name = carrierLabel(tariff.carrier);
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-base font-semibold">{name}</h4>
          <Badge variant="neutral">
            {tariff.price_includes_vat ? 'KDV dahil girildi' : 'KDV hariç girildi'}
          </Badge>
          {hasZero ? <Badge variant="warning">0 girildi</Badge> : null}
        </div>
        <p className="text-sm text-muted-foreground">
          {formatLongDate(tariff.valid_from)} tarihinden itibaren geçerli. Bu tarihten sonraki
          siparişlerde kullanılır.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[18rem] border-collapse text-left text-sm">
          <caption className="sr-only">
            {name} desi kademeleri ve fiyatları ({formatLongDate(tariff.valid_from)} başlangıçlı)
          </caption>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th scope="col" className="py-1.5 pr-3 font-medium">
                En çok desi
              </th>
              <th scope="col" className="py-1.5 font-medium">
                Fiyat
              </th>
            </tr>
          </thead>
          <tbody>
            {tariff.brackets.map((bracket) => (
              <tr key={bracket.max_desi} className="border-b border-border last:border-0">
                <th scope="row" className="num py-2 pr-3 font-medium">
                  {formatDesi(bracket.max_desi)}
                </th>
                <td className="num py-2">
                  {vatPair(bracket.price, bracket.price_excl_vat, tariff.price_includes_vat)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={onEdit} disabled={pending}>
            Düzenle
            <span className="sr-only">: {name}</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={onRetract} disabled={pending}>
            Geri çek
            <span className="sr-only">: {name}</span>
          </Button>
        </div>
      ) : null}
    </li>
  );
}

// --------------------------------------------------------------------------- form

function TariffForm({
  accountId,
  mode,
  carriers,
  existing,
  today,
  earliestOrderDay,
  vatRate,
  onClose,
}: {
  accountId: string;
  mode: FormMode;
  carriers: CarriersState;
  /** Kayıtlı sürümler: "bugünden itibaren" gönderimi aynı anahtarlı bugünkü sürümü ezecekse sunulmaz (AF-07) */
  existing: readonly CargoTariffOut[];
  today: string;
  /** Sunucudaki en eski sipariş günü; yoksa (sipariş yok ya da eski API) yaklaşık öneri kullanılır */
  earliestOrderDay: string | null | undefined;
  /** Kargo KDV oranı (yüzde, Decimal dizgesi); sunucudan gelir, yoksa %20 */
  vatRate: string;
  onClose: () => void;
}) {
  const writer = useSettingsWriter();
  const editing = mode.kind === 'edit' ? mode.tariff : null;
  const lookback = carriers.data?.lookback_days ?? DEFAULT_LOOKBACK_DAYS;
  const schema = useMemo(() => tariffSchema(today), [today]);
  const suggestion = suggestStartDay({ today, earliestOrderDay, lookbackDays: lookback });

  const form = useForm<TariffFormValues>({
    resolver: zodResolver(schema),
    defaultValues: editing
      ? {
          agreement: editing.agreement,
          carrier: editing.carrier,
          validFrom: editing.valid_from,
          vatMode: editing.price_includes_vat ? 'dahil' : 'haric',
          brackets: editing.brackets.map((b) => ({
            maxDesi: toInputText(b.max_desi),
            price: toInputText(b.price),
          })),
        }
      : {
          agreement: 'trendyol',
          carrier: '',
          // AB-01, AF-05: ilk siparişten önce bir başlangıç: en eski sipariş gününden 1 gün önce; sunucu günü
          // vermiyorsa YAKLAŞIK öneri (tarama penceresi kadar geri)
          validFrom: suggestion.day,
          vatMode: 'dahil',
          brackets: [{ maxDesi: '', price: '' }],
        },
  });
  const { fields, append, remove } = useFieldArray({ control: form.control, name: 'brackets' });
  const watched = useWatch({ control: form.control });
  const agreement = watched.agreement ?? 'trendyol';
  const vatMode = watched.vatMode ?? 'dahil';
  const selectedCarrier = watched.carrier ?? '';
  const includesVat = vatMode === 'dahil';
  const arrayError = form.formState.errors.brackets;
  const bracketsMessage = arrayError?.root?.message ?? arrayError?.message;

  const carrierOptions = useMemo(() => {
    const items = (carriers.data?.items ?? []).filter((c) => c.agreement === agreement);
    const seen = new Set<string>([OTHER_CARRIERS]);
    const options: { value: string; label: string; status?: string }[] = [];
    for (const item of items) {
      const value = carrierValue(item.carrier);
      if (seen.has(value)) continue;
      seen.add(value);
      options.push({
        value,
        label: `${carrierLabel(item.carrier)} (son ${lookback} günde ${item.line_count} satır${item.covered ? '' : ', tarifesi yok'})`,
        status: item.covered
          ? `${carrierLabel(item.carrier)}: son ${lookback} günde ${item.line_count} satır, tarifesi var.`
          : `${carrierLabel(item.carrier)}: son ${lookback} günde ${item.line_count} satır, henüz tarifesi yok.`,
      });
    }
    // Düzenlenen kaydın firması listede yoksa yine seçilebilir kalır
    if (selectedCarrier && !seen.has(selectedCarrier)) {
      options.push({ value: selectedCarrier, label: carrierLabel(selectedCarrier) });
    }
    options.push({ value: OTHER_CARRIERS, label: 'Diğer firmalar (listede olmayan her firma)' });
    return options;
  }, [carriers.data, agreement, lookback, selectedCarrier]);

  // Kapalı `select` dar ekranda "tarifesi yok" bilgisini kesebilir: seçili firmanın durumu açıklamaya da yazılır (AF-14)
  const selectedStatus = carrierOptions.find((o) => o.value === selectedCarrier)?.status;

  function submit(values: TariffFormValues) {
    const body = toTariffBody(values);
    const todayVersionExists = existing.some(
      (t) => t.valid_from === today && t.agreement === body.agreement && t.carrier === body.carrier,
    );
    void writer.run({
      scope: 'kargo',
      topic: 'dated',
      successText: (info) =>
        info.action === 'created'
          ? 'Tarife eklendi. Kâr rakamları yeni tarifeyle güncellenir.'
          : 'Tarife güncellendi. Kâr rakamları yeni tarifeyle güncellenir.',
      send: (g) =>
        profitSettingsApi.putCargoTariff(accountId, {
          ...body,
          expected_revision: g.expectedRevision,
          confirm_affects_from: g.confirmAffectsFrom,
        }),
      // ADR-0007 §5.2: ikincil düğme yalnız eklemede (düzenlemede 1 Ekim sürümünü düzeltmek isteyen kullanıcı yanlışlıkla
      // yeni sürüm eklerdi). Aynı anahtarlı (anlaşma, firma) bugün başlayan sürüm varsa o sessizce ezilirdi: düğme yok.
      sendFromToday:
        editing === null && body.valid_from < today && !todayVersionExists
          ? (g) =>
              profitSettingsApi.putCargoTariff(accountId, {
                ...body,
                valid_from: today,
                expected_revision: g.expectedRevision,
              })
          : undefined,
      onDone: onClose,
      // Yalnız çizilen alanların hatası alanın yanına gider; kalanı form başındaki hata satırına düşer (AF-08)
      onInvalid: (error: ApiError) =>
        applyServerErrors(
          form,
          error,
          editing
            ? ['vatMode', 'brackets']
            : ['agreement', 'carrier', 'validFrom', 'vatMode', 'brackets'],
        ),
      // Düzenlemede kayıt ya da sürüm değişti: form eski değerlerle açık kalıp başkasının değişikliğini ezmesin
      // (AF-11); yeni değerlerle yeniden açmak için bildirimdeki yönerge izlenir
      onStale: (reason) => {
        if (reason === 'record-ended' || (reason === 'revision-conflict' && editing)) onClose();
      },
    });
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(submit)}
        noValidate
        aria-label={editing ? 'Kargo tarifesini düzenle' : 'Yeni kargo tarifesi'}
        className="flex flex-col gap-5 rounded-lg border-2 border-primary bg-surface-muted p-4"
      >
        <h3 className="text-lg font-semibold">
          {editing ? `${carrierLabel(editing.carrier)} tarifesini düzenle` : 'Yeni kargo tarifesi'}
        </h3>

        {editing ? (
          <p className="text-sm text-muted-foreground">
            {AGREEMENT_LABELS[editing.agreement]}, {carrierLabel(editing.carrier)},{' '}
            {formatLongDate(editing.valid_from)} başlangıçlı sürüm. Firma ve başlangıç tarihi bu
            sürümde değişmez; başka bir tarihten geçerli fiyat için &quot;Tarife ekle&quot; ile yeni
            sürüm girin.
          </p>
        ) : (
          <>
            <FormField
              control={form.control}
              name="agreement"
              render={({ field }) => (
                <ChoiceGroup<Agreement>
                  error={form.formState.errors.agreement?.message}
                  legend="Kargo anlaşması"
                  name="agreement"
                  value={field.value}
                  onChange={(next) => {
                    field.onChange(next);
                    // Anlaşma değişince firma listesi değişir; eski seçim geçersiz kalabilir
                    form.setValue('carrier', '');
                  }}
                  options={[
                    {
                      value: 'trendyol',
                      label: AGREEMENT_LABELS.trendyol,
                      hint: "Trendyol'un anlaştığı kargo firmaları. Bedel, kargo faturasıyla hakedişinizden düşülür.",
                    },
                    {
                      value: 'seller',
                      label: AGREEMENT_LABELS.seller,
                      hint: 'Kendi anlaşmanızla gönderdiğiniz siparişler. Trendyol kargo faturası kesmez.',
                    },
                  ]}
                />
              )}
            />
            <FormField
              control={form.control}
              name="carrier"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Kargo firması</FormLabel>
                  <FormControl>
                    <select {...field} className={SELECT_CLASS}>
                      <option value="">Firma seçin</option>
                      {carrierOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </FormControl>
                  <FormDescription>
                    {carriers.status === 'loading'
                      ? 'Siparişlerinizdeki firmalar yükleniyor.'
                      : carriers.status === 'error'
                        ? 'Firma listesi alınamadı; şimdilik yalnız "Diğer firmalar" seçilebilir.'
                        : 'Firma adlarını siparişlerinizden getiririz; yazım farkı olmasın diye elle yazılmaz.'}
                    {selectedStatus ? <span className="mt-1 block">{selectedStatus}</span> : null}
                    {carriers.status === 'error' ? (
                      <>
                        {' '}
                        <button
                          type="button"
                          onClick={carriers.retry}
                          className="font-medium text-primary underline underline-offset-4"
                        >
                          Listeyi tekrar yükle
                        </button>
                      </>
                    ) : null}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
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
                      : 'Bu tarihten sonraki siparişlerde kullanılır.'}{' '}
                    {startSuggestionNote(suggestion, lookback)}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </>
        )}

        <FormField
          control={form.control}
          name="vatMode"
          render={({ field }) => (
            <ChoiceGroup
              error={form.formState.errors.vatMode?.message}
              legend="Fiyatları nasıl giriyorsunuz?"
              name="vatMode"
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
              description={`Kargo KDV oranı %${formatVatRate(vatRate)}.`}
            />
          )}
        />

        <div className="flex flex-col gap-3">
          <h4 className="text-base font-semibold">Desi kademeleri</h4>
          <ul className="flex list-none flex-col gap-3 p-0">
            {fields.map((row, index) => {
              const priceText = watched.brackets?.[index]?.price ?? '';
              const equivalent = parsedEcho(priceText, {
                kind: 'money',
                includesVat,
                vatRate,
              });
              const desiEcho = parsedEcho(watched.brackets?.[index]?.maxDesi ?? '', {
                kind: 'desi',
              });
              return (
                <li
                  key={row.id}
                  aria-label={`${index + 1}. kademe`}
                  className="grid grid-cols-1 items-start gap-x-3 gap-y-3 rounded-md border border-border bg-surface p-3 sm:grid-cols-[1fr_1fr_auto]"
                >
                  <FormField
                    control={form.control}
                    name={`brackets.${index}.maxDesi`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{index + 1}. kademe, en çok desi</FormLabel>
                        <FormControl>
                          <Input
                            inputMode="decimal"
                            autoComplete="off"
                            placeholder="2"
                            {...field}
                          />
                        </FormControl>
                        {desiEcho ? (
                          <FormDescription>
                            <EchoLine echo={desiEcho} />
                          </FormDescription>
                        ) : null}
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name={`brackets.${index}.price`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          {index + 1}. kademe fiyatı ({includesVat ? 'KDV dahil' : 'KDV hariç'}, TL)
                        </FormLabel>
                        <FormControl>
                          <Input inputMode="decimal" autoComplete="off" {...field} />
                        </FormControl>
                        {isZeroText(priceText) ? (
                          <FormDescription>
                            <ZeroEnteredNote>
                              Bu kademe bilerek 0 TL hesaplanır, kargo &quot;eksik&quot; sayılmaz.
                            </ZeroEnteredNote>
                          </FormDescription>
                        ) : equivalent ? (
                          <FormDescription>
                            <EchoLine echo={equivalent} />
                          </FormDescription>
                        ) : null}
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  {/* DOM sırası görsel sırayla aynı: desi, fiyat, sil (WCAG 1.3.2, 2.4.3) */}
                  <div className="flex justify-end sm:pt-7">
                    <Button
                      variant="ghost"
                      onClick={() => remove(index)}
                      disabled={fields.length <= 1}
                    >
                      <Trash2 aria-hidden="true" />
                      <span aria-hidden="true">Kademeyi sil</span>
                      <span className="sr-only">{index + 1}. kademeyi sil</span>
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
          {bracketsMessage ? (
            <p role="alert" className="flex items-start gap-1.5 text-sm font-medium text-loss">
              <span aria-hidden="true" className="mt-0.5 font-bold">
                !
              </span>
              <span>
                <span className="sr-only">Hata: </span>
                {bracketsMessage}
              </span>
            </p>
          ) : null}
          <div>
            <Button
              variant="secondary"
              onClick={() => append({ maxDesi: '', price: '' })}
              disabled={fields.length >= MAX_BRACKETS}
            >
              <Plus aria-hidden="true" />
              Kademe ekle
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            Desiler artan sırada olmalı. Ondalık için virgül kullanın (54,50); nokta yalnız binlik
            ayracıdır (1.250,00).
          </p>
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
