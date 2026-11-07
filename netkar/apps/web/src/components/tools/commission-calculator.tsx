'use client';

import { useMemo } from 'react';

import { calculateCommission } from '@/lib/calc/commission';
import { deriveCommissionInput, type CommissionFormValues } from '@/lib/calc/forms';
import { formatKurus } from '@/lib/calc/money';

import { Callout, NumberField, ResultTable, SelectField } from './fields';
import { EstimateNote, ToolLayout } from './tool-layout';
import { useFormValues } from './use-form-values';

export const COMMISSION_DEFAULTS: CommissionFormValues = {
  price: '600',
  vatRate: '20',
  commissionRate: '21',
  commissionVat: 'incl',
  shipping: '',
  shippingVat: 'excl',
  serviceFee: '',
};

export const VAT_OPTIONS = [
  { value: '20', label: '%20' },
  { value: '10', label: '%10' },
  { value: '1', label: '%1' },
] as const;

export const COMMISSION_VAT_OPTIONS = [
  { value: 'incl', label: 'KDV dahil (varsayılan)' },
  { value: 'excl', label: 'KDV hariç, üstüne KDV eklenir' },
] as const;

export const AMOUNT_VAT_OPTIONS = [
  { value: 'excl', label: 'KDV hariç' },
  { value: 'incl', label: 'KDV dahil' },
] as const;

export function CommissionCalculator() {
  const { values, set, dirty } = useFormValues(COMMISSION_DEFAULTS);
  const derived = useMemo(() => deriveCommissionInput(values), [values]);

  const outcome = useMemo(() => {
    if (!derived.input) return null;
    const main = calculateCommission(derived.input);
    const alt = calculateCommission({
      ...derived.input,
      commissionIncludesVat: !derived.input.commissionIncludesVat,
    });
    return { main, alt, input: derived.input };
  }, [derived]);

  const errors: Partial<Record<keyof CommissionFormValues, string>> = derived.errors;

  return (
    <ToolLayout
      isExample={!dirty}
      inputs={
        <>
          <NumberField
            label="Satış fiyatı (KDV dahil)"
            suffix="TL"
            value={values.price}
            onChange={(v) => set('price', v)}
            error={errors.price}
            hint="Satıcı indirimi düşüldükten sonraki fiyat. Trendyol karşılamalı kuponlar komisyon matrahını düşürmez."
          />
          <SelectField
            label="Ürün KDV oranı"
            value={values.vatRate}
            onChange={(v) => set('vatRate', v)}
            options={VAT_OPTIONS}
            error={errors.vatRate}
          />
          <NumberField
            label="Komisyon oranı"
            suffix="%"
            value={values.commissionRate}
            onChange={(v) => set('commissionRate', v)}
            error={errors.commissionRate}
            hint="Oranı Trendyol satıcı panelinden, ürün kategorinizin komisyon tablosundan alın. Burada hazır oran listesi yok."
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
            label="Gönderi kargo bedeli"
            suffix="TL"
            optional
            value={values.shipping}
            onChange={(v) => set('shipping', v)}
            error={errors.shipping}
            hint="Desiye göre kargo faturanızdaki tutar. Desiyi bulmak için desi aracını kullanın."
          />
          <SelectField
            label="Kargo tutarı"
            value={values.shippingVat}
            onChange={(v) => set('shippingVat', v)}
            options={AMOUNT_VAT_OPTIONS}
            error={errors.shippingVat}
          />
          <NumberField
            label="Platform hizmet bedeli (KDV hariç)"
            suffix="TL"
            optional
            value={values.serviceFee}
            onChange={(v) => set('serviceFee', v)}
            error={errors.serviceFee}
            hint="Sipariş başına bedel; güncel tutarı Trendyol faturanızdan alın."
          />
        </>
      }
      results={
        outcome ? (
          <>
            <ResultTable
              caption="Komisyon ve kesinti kırılımı"
              rows={[
                { label: 'Satış fiyatı (KDV dahil)', value: formatKurus(outcome.main.price.incl) },
                {
                  label: 'Satışın KDV hariç tutarı',
                  value: formatKurus(outcome.main.price.excl),
                  kind: 'info',
                },
                {
                  label: 'Komisyon (KDV hariç)',
                  value: formatKurus(-outcome.main.commissionExcl),
                  kind: 'deduction',
                },
                {
                  label: 'Komisyonun KDV’si',
                  value: formatKurus(-outcome.main.commissionVat),
                  kind: 'deduction',
                },
                {
                  label: 'Toplam komisyon (KDV dahil)',
                  value: formatKurus(-outcome.main.commissionIncl),
                  kind: 'deduction',
                },
                {
                  label: 'Hakediş (satış eksi komisyon)',
                  value: formatKurus(outcome.main.settlement),
                  kind: 'total',
                },
                ...(outcome.main.shipping.incl > 0n
                  ? [
                      {
                        label: 'Gönderi kargo (KDV dahil)',
                        value: formatKurus(-outcome.main.shipping.incl),
                        kind: 'deduction' as const,
                      },
                    ]
                  : []),
                ...(outcome.main.serviceFee.incl > 0n
                  ? [
                      {
                        label: 'Platform hizmet bedeli (KDV dahil)',
                        value: formatKurus(-outcome.main.serviceFee.incl),
                        kind: 'deduction' as const,
                      },
                    ]
                  : []),
                {
                  label: 'E-ticaret stopajı (%1)',
                  value: formatKurus(-outcome.main.withholding),
                  kind: 'deduction',
                  note: 'KDV hariç satıştan hesaplanır. Gider değil, peşin kesilen vergidir.',
                },
                {
                  label: 'Hesabınıza geçecek tutar (tahmini)',
                  value: formatKurus(outcome.main.expectedPayout),
                  kind: 'total',
                },
              ]}
            />
            <p className="mt-4 text-sm text-muted-foreground">
              Komisyon tutarı KDV’yi içermiyorsa (ve KDV üstüne ekleniyorsa) hesabınıza geçen tutar{' '}
              <span className="num font-medium text-foreground">
                {formatKurus(outcome.alt.expectedPayout)}
              </span>{' '}
              olur; aradaki fark{' '}
              <span className="num font-medium text-foreground">
                {formatKurus(
                  outcome.main.expectedPayout > outcome.alt.expectedPayout
                    ? outcome.main.expectedPayout - outcome.alt.expectedPayout
                    : outcome.alt.expectedPayout - outcome.main.expectedPayout,
                )}
              </span>
              .
            </p>
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
