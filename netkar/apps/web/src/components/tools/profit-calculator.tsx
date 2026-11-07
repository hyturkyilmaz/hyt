'use client';

import { useMemo } from 'react';

import { ProfitValue } from '@/components/profit-value';
import { deriveProfitInput, type ProfitFormValues } from '@/lib/calc/forms';
import { formatBps, formatKurus, formatScaled, scaledToDecimalString } from '@/lib/calc/money';
import { calculateProfit } from '@/lib/calc/profit';

import { AMOUNT_VAT_OPTIONS, COMMISSION_VAT_OPTIONS, VAT_OPTIONS } from './commission-calculator';
import { Callout, NumberField, ResultTable, SelectField } from './fields';
import { EstimateNote, ToolLayout } from './tool-layout';
import { useFormValues } from './use-form-values';

export const PROFIT_DEFAULTS: ProfitFormValues = {
  price: '600',
  vatRate: '20',
  cost: '250',
  costVat: 'excl',
  costVatRate: 'same',
  commissionRate: '21',
  commissionVat: 'incl',
  shipping: '60',
  returnShipping: '60',
  shippingVat: 'excl',
  serviceFee: '',
  adMode: 'amount',
  adAmount: '',
  roas: '',
  returnRate: '5',
  unsellableRate: '',
};

const COST_VAT_RATE_OPTIONS = [
  { value: 'same', label: 'Satış KDV oranıyla aynı' },
  ...VAT_OPTIONS,
] as const;

const AD_MODE_OPTIONS = [
  { value: 'amount', label: 'Sipariş başı harcama (TL)' },
  { value: 'roas', label: 'ROAS' },
] as const;

function Group({ legend, children }: { legend: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-4 border-t border-border pt-4 first:border-t-0 first:pt-0">
      <legend className="mb-1 text-base font-semibold">{legend}</legend>
      {children}
    </fieldset>
  );
}

export function ProfitCalculator() {
  const { values, set, dirty } = useFormValues(PROFIT_DEFAULTS);
  const derived = useMemo(() => deriveProfitInput(values), [values]);
  const result = useMemo(() => (derived.input ? calculateProfit(derived.input) : null), [derived]);
  const errors: Partial<Record<keyof ProfitFormValues, string>> = derived.errors;

  return (
    <ToolLayout
      isExample={!dirty}
      inputs={
        <>
          <Group legend="Satış ve maliyet">
            <NumberField
              label="Satış fiyatı (KDV dahil)"
              suffix="TL"
              value={values.price}
              onChange={(v) => set('price', v)}
              error={errors.price}
              hint="Satıcı indirimi düşüldükten sonraki fiyat."
            />
            <SelectField
              label="Ürün KDV oranı"
              value={values.vatRate}
              onChange={(v) => set('vatRate', v)}
              options={VAT_OPTIONS}
              error={errors.vatRate}
            />
            <NumberField
              label="Alış maliyeti (birim)"
              suffix="TL"
              value={values.cost}
              onChange={(v) => set('cost', v)}
              error={errors.cost}
              hint="Boş bırakırsanız maliyet düşülmez."
            />
            <SelectField
              label="Maliyet KDV"
              value={values.costVat}
              onChange={(v) => set('costVat', v)}
              options={AMOUNT_VAT_OPTIONS}
              error={errors.costVat}
              hint="Girdiğiniz maliyet fatura tutarıysa KDV dahil seçin."
            />
            <SelectField
              label="Alış KDV oranı"
              value={values.costVatRate}
              onChange={(v) => set('costVatRate', v)}
              options={COST_VAT_RATE_OPTIONS}
              error={errors.costVatRate}
            />
          </Group>

          <Group legend="Trendyol kesintileri">
            <NumberField
              label="Komisyon oranı"
              suffix="%"
              value={values.commissionRate}
              onChange={(v) => set('commissionRate', v)}
              error={errors.commissionRate}
              hint="Oranı Trendyol satıcı panelinden, kategorinizin komisyon tablosundan alın."
            />
            <SelectField
              label="Komisyon tutarı"
              value={values.commissionVat}
              onChange={(v) => set('commissionVat', v)}
              options={COMMISSION_VAT_OPTIONS}
              error={errors.commissionVat}
              hint="Teyit bekleyen varsayım: ayrıntı aşağıda."
            />
            <NumberField
              label="Platform hizmet bedeli (KDV hariç)"
              suffix="TL"
              optional
              value={values.serviceFee}
              onChange={(v) => set('serviceFee', v)}
              error={errors.serviceFee}
              hint="Sipariş başına; güncel tutarı Trendyol faturanızdan alın."
            />
          </Group>

          <Group legend="Kargo ve iade">
            <NumberField
              label="Gönderi kargo bedeli"
              suffix="TL"
              optional
              value={values.shipping}
              onChange={(v) => set('shipping', v)}
              error={errors.shipping}
            />
            <NumberField
              label="İade kargo bedeli"
              suffix="TL"
              optional
              value={values.returnShipping}
              onChange={(v) => set('returnShipping', v)}
              error={errors.returnShipping}
            />
            <SelectField
              label="Kargo tutarları"
              value={values.shippingVat}
              onChange={(v) => set('shippingVat', v)}
              options={AMOUNT_VAT_OPTIONS}
              error={errors.shippingVat}
            />
            <NumberField
              label="İade oranı"
              suffix="%"
              optional
              value={values.returnRate}
              onChange={(v) => set('returnRate', v)}
              error={errors.returnRate}
              hint="Geçmişte her 100 siparişin kaçı iade oldu? Yaklaşık bir değer yeterli."
            />
            <NumberField
              label="İade edilenlerden satılamayan pay"
              suffix="%"
              optional
              value={values.unsellableRate}
              onChange={(v) => set('unsellableRate', v)}
              error={errors.unsellableRate}
              hint="Hasarlı veya yeniden satılamayan iadelerde ürün maliyeti gider kalır."
            />
          </Group>

          <Group legend="Reklam">
            <SelectField
              label="Reklam girişi"
              value={values.adMode}
              onChange={(v) => set('adMode', v)}
              options={AD_MODE_OPTIONS}
              error={errors.adMode}
            />
            {values.adMode === 'roas' ? (
              <NumberField
                label="ROAS"
                value={values.roas}
                onChange={(v) => set('roas', v)}
                error={errors.roas}
                hint="Harcama, KDV dahil satış fiyatının ROAS’a bölünmesiyle bulunur ve KDV hariç sayılır."
              />
            ) : (
              <NumberField
                label="Sipariş başı reklam harcaması (KDV hariç)"
                suffix="TL"
                optional
                value={values.adAmount}
                onChange={(v) => set('adAmount', v)}
                error={errors.adAmount}
              />
            )}
          </Group>

          {derived.warnings.length > 0 ? (
            <Callout title="Kontrol edin" tone="warning">
              {derived.warnings.map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
            </Callout>
          ) : null}
        </>
      }
      results={
        result ? (
          <>
            <p className="text-sm text-muted-foreground">Ürün başına tahmini net kâr</p>
            <p className="mb-4 text-3xl">
              <ProfitValue
                value={scaledToDecimalString(result.netProfit, 2)}
                currencyStyle="code"
              />
            </p>
            <ResultTable
              caption="Net kâr kırılımı"
              rows={[
                { label: 'Satış (KDV hariç)', value: formatKurus(result.salesExcl) },
                {
                  label: 'Ürün maliyeti',
                  value: formatKurus(-result.cost),
                  kind: 'deduction',
                },
                {
                  label: 'Komisyon (KDV hariç)',
                  value: formatKurus(-result.commissionExcl),
                  kind: 'deduction',
                },
                {
                  label: 'Gönderi kargo (KDV hariç)',
                  value: formatKurus(-result.shipping),
                  kind: 'deduction',
                },
                {
                  label: 'Platform hizmet bedeli (KDV hariç)',
                  value: formatKurus(-result.serviceFee),
                  kind: 'deduction',
                },
                {
                  label: 'Reklam (KDV hariç)',
                  value: formatKurus(-result.ad),
                  kind: 'deduction',
                },
                {
                  label: 'İade öncesi net kâr',
                  value: formatKurus(result.profitBeforeReturns),
                  kind: 'total',
                },
                {
                  label: 'Beklenen iade payı',
                  value: formatKurus(-result.returnCost),
                  kind: 'deduction',
                  note: 'İade olursa kargo, iade kargosu, hizmet bedeli ve reklam geri alınmaz.',
                },
                { label: 'Net kâr', value: formatKurus(result.netProfit), kind: 'total' },
                {
                  label: 'Net kâr marjı',
                  value: result.marginBps === null ? 'Hesaplanamadı' : formatBps(result.marginBps),
                  note: 'Net kârın KDV hariç satışa oranı.',
                },
                {
                  label: 'Başabaş satış fiyatı (KDV dahil)',
                  value:
                    result.breakEvenPrice === null
                      ? 'Bu oranlarla yok'
                      : formatKurus(result.breakEvenPrice),
                  note: 'Diğer girdiler sabitken net kârın sıfır olduğu fiyat.',
                },
                {
                  label: 'Başabaş ROAS (ciro KDV hariç)',
                  value:
                    result.breakEvenRoasExcl === null
                      ? 'Reklam öncesi kâr yok'
                      : formatScaled(result.breakEvenRoasExcl, 2),
                  note: 'KDV hariç satış bölü reklam öncesi net kâr.',
                },
                {
                  label: 'Başabaş ROAS (ciro KDV dahil)',
                  value:
                    result.breakEvenRoasIncl === null
                      ? 'Reklam öncesi kâr yok'
                      : formatScaled(result.breakEvenRoasIncl, 2),
                  note: 'Panel ROAS’ı KDV dahil ciroyla hesaplanıyorsa bununla karşılaştırın (teyit bekliyor).',
                },
                {
                  label: 'KDV etkisi (iade öncesi, bilgi)',
                  value: formatKurus(result.vatEffect),
                  kind: 'info',
                },
                {
                  label: 'E-ticaret stopajı (nakit akışı, kâra girmez)',
                  value: formatKurus(result.withholding),
                  kind: 'info',
                },
              ]}
            />
            <EstimateNote />
          </>
        ) : (
          <Callout title="Sonucu görmek için alanları düzeltin" tone="warning">
            <p>Kırmızı hata mesajı olan alanları düzelttiğinizde sonuç burada görünür.</p>
          </Callout>
        )
      }
    />
  );
}
