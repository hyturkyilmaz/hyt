'use client';

import { useMemo } from 'react';

import { calculateDesi, shrinkOneCm } from '@/lib/calc/desi';
import { deriveDesiInput, type DesiFormValues } from '@/lib/calc/forms';
import { formatScaled } from '@/lib/calc/money';

import { Callout, NumberField, ResultTable, SelectField } from './fields';
import { ToolLayout } from './tool-layout';
import { useFormValues } from './use-form-values';

export const DESI_DEFAULTS: DesiFormValues = {
  length: '30',
  width: '20',
  height: '10',
  weight: '1',
  divisor: 'domestic',
};

const DIVISOR_OPTIONS = [
  { value: 'domestic', label: 'Yurt içi (bölen 3.000)' },
  { value: 'international', label: 'Yurt dışı (bölen 5.000)' },
] as const;

export function DesiCalculator() {
  const { values, set, dirty } = useFormValues(DESI_DEFAULTS);
  const derived = useMemo(() => deriveDesiInput(values), [values]);
  const errors: Partial<Record<keyof DesiFormValues, string>> = derived.errors;

  const outcome = useMemo(() => {
    const input = derived.input;
    if (!input) return null;
    const main = calculateDesi(input);
    // "Koli 1 cm küçülürse": her ölçü tek tek ve üçü birden
    const shrink = (
      label: string,
      length: bigint | null,
      width: bigint | null,
      height: bigint | null,
    ) =>
      length !== null && width !== null && height !== null
        ? { label, desi: calculateDesi({ ...input, length, width, height }) }
        : null;
    const variants = [
      shrink('En 1 cm küçülürse', shrinkOneCm(input.length), input.width, input.height),
      shrink('Boy 1 cm küçülürse', input.length, shrinkOneCm(input.width), input.height),
      shrink('Yükseklik 1 cm küçülürse', input.length, input.width, shrinkOneCm(input.height)),
      shrink(
        'Üçü de 1 cm küçülürse',
        shrinkOneCm(input.length),
        shrinkOneCm(input.width),
        shrinkOneCm(input.height),
      ),
    ].filter((item): item is NonNullable<typeof item> => item !== null);
    return { main, variants };
  }, [derived]);

  return (
    <ToolLayout
      isExample={!dirty}
      inputs={
        <>
          <NumberField
            label="En"
            suffix="cm"
            value={values.length}
            onChange={(v) => set('length', v)}
            error={errors.length}
          />
          <NumberField
            label="Boy"
            suffix="cm"
            value={values.width}
            onChange={(v) => set('width', v)}
            error={errors.width}
          />
          <NumberField
            label="Yükseklik"
            suffix="cm"
            value={values.height}
            onChange={(v) => set('height', v)}
            error={errors.height}
          />
          <NumberField
            label="Ağırlık"
            suffix="kg"
            optional
            value={values.weight}
            onChange={(v) => set('weight', v)}
            error={errors.weight}
            hint="Paketlenmiş koli ağırlığı. Boş bırakırsanız yalnız hacim hesaba girer."
          />
          <SelectField
            label="Bölen"
            value={values.divisor}
            onChange={(v) => set('divisor', v)}
            options={DIVISOR_OPTIONS}
            error={errors.divisor}
            hint="Firmanızın kullandığı böleni kontrol edin."
          />
        </>
      }
      results={
        outcome ? (
          <>
            <ResultTable
              caption="Desi sonucu"
              rows={[
                {
                  label: 'Hacimsel desi',
                  value: formatScaled(outcome.main.volumetricHundredths, 2),
                  note: 'En x boy x yükseklik, bölene bölünür.',
                },
                {
                  label: 'Gerçek ağırlık (kg)',
                  value: formatScaled(outcome.main.weightHundredths, 2),
                },
                {
                  label: 'Ücretlendirmeye esas değer',
                  value: formatScaled(outcome.main.billableHundredths, 2),
                  kind: 'total',
                  note:
                    outcome.main.basis === 'volume'
                      ? 'Hacimsel desi, gerçek ağırlıktan büyük veya eşit: desi esas alınır.'
                      : 'Gerçek ağırlık hacimsel desiden büyük: ağırlık esas alınır.',
                },
                {
                  label: 'Yukarı yuvarlanmış desi',
                  value: String(outcome.main.billableRoundedUp),
                  note: 'Tarifeler tam desi basamaklarıyla yazılır. Firmanızın yuvarlama kuralını teyit edin.',
                },
              ]}
            />
            {outcome.variants.length > 0 ? (
              <div className="mt-6">
                <h3 className="text-base font-semibold">Koli 1 cm küçülürse ne değişir?</h3>
                <ResultTable
                  caption="Koli küçülürse desi değişimi"
                  rows={outcome.variants.map((variant) => ({
                    label: variant.label,
                    value: `${formatScaled(variant.desi.billableHundredths, 2)} (yukarı yuvarlanmış ${variant.desi.billableRoundedUp})`,
                  }))}
                />
              </div>
            ) : null}
            <p className="mt-4 border-t border-border pt-4 text-sm text-muted-foreground">
              Kargo maliyeti gösterilmiyor: Trendyol anlaşmalı kargo tarifesini doğrulayabildiğimiz
              kaynaktan alamadık. Tarifenizdeki tutarı kâr hesaplayıcısına yazabilirsiniz.
            </p>
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
