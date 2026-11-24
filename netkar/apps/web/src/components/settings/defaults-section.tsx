'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import { useEffect } from 'react';
import { useForm, useWatch } from 'react-hook-form';

import { SectionHeading, SectionNotice } from '@/components/settings/fields';
import { useSettingsWriter } from '@/components/settings/settings-writer';
import {
  EchoLine,
  FormRootError,
  applyServerErrors,
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
import { profitSettingsApi, type SettingsOut } from '@/lib/api/profit-settings';
import { formatDesi, toInputText } from '@/lib/profit/settings-input';
import {
  defaultsSchema,
  toDefaultsBody,
  type DefaultsFormValues,
} from '@/lib/validation/profit-settings';

/** Varsayılan desi: tarihsizdir ("tüm dönemler"); değiştirmek geçmiş siparişlerin kargo tahminini etkiler (K43). */
export function DefaultsSection({
  accountId,
  settings,
  canEdit,
}: {
  accountId: string;
  settings: SettingsOut;
  canEdit: boolean;
}) {
  const writer = useSettingsWriter();
  const current = settings.default_desi;
  const form = useForm<DefaultsFormValues>({
    resolver: zodResolver(defaultsSchema),
    defaultValues: { desi: current === null ? '' : toInputText(current) },
  });

  const desiEcho = parsedEcho(useWatch({ control: form.control, name: 'desi' }) ?? '', {
    kind: 'desi',
  });

  // Sunucudaki değer değişince (kayıt, yenileme) alan onu gösterir
  useEffect(() => {
    form.reset({ desi: current === null ? '' : toInputText(current) });
  }, [current, form]);

  function submit(values: DefaultsFormValues) {
    const body = toDefaultsBody(values);
    void writer.run({
      scope: 'desi',
      topic: 'defaults',
      successText: () =>
        body.default_desi === null ? 'Varsayılan desi kaldırıldı.' : 'Varsayılan desi kaydedildi.',
      send: (g) =>
        profitSettingsApi.putDefaults(accountId, {
          ...body,
          expected_revision: g.expectedRevision,
          confirm_affects_from: g.confirmAffectsFrom,
        }),
      onInvalid: (error: ApiError) => applyServerErrors(form, error, ['desi']),
    });
  }

  return (
    <Card as="section" id="desi" aria-labelledby="desi-baslik" className="scroll-mt-4">
      <CardHeader>
        <SectionHeading
          id="desi"
          title="Varsayılan desi"
          badge={
            <Badge variant={current === null ? 'neutral' : 'info'}>
              {current === null ? 'Tanımsız' : `${formatDesi(current)} desi`}
            </Badge>
          }
          description="Siparişte desi bilgisi yoksa bu kullanılır."
        />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SectionNotice scope="desi" />
        {canEdit ? (
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(submit)}
              noValidate
              aria-label="Varsayılan desi"
              className="flex flex-col gap-4"
            >
              <FormField
                control={form.control}
                name="desi"
                render={({ field }) => (
                  <FormItem className="max-w-xs">
                    <FormLabel>Varsayılan desi</FormLabel>
                    <FormControl>
                      <Input inputMode="decimal" autoComplete="off" {...field} />
                    </FormControl>
                    <FormDescription>
                      Boş bırakıp kaydederseniz varsayılan desi kaldırılır. Değiştirmek, siparişinde
                      desi olmayan geçmiş siparişlerin kargo tahminini de etkiler.
                    </FormDescription>
                    {desiEcho ? (
                      <FormDescription>
                        <EchoLine echo={desiEcho} />
                      </FormDescription>
                    ) : null}
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormRootError message={form.formState.errors.root?.message} />
              <div>
                <Button type="submit" disabled={writer.pending}>
                  {writer.pending ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
                  Kaydet
                </Button>
              </div>
            </form>
          </Form>
        ) : (
          <p className="text-base text-muted-foreground">
            {current === null
              ? 'Varsayılan desi tanımlı değil.'
              : `Varsayılan desi: ${formatDesi(current)}`}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
