'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CheckCircle2, Circle, Info } from 'lucide-react';
import { useEffect, useState } from 'react';

import { ConfirmPastChangeDialog } from '@/components/settings/confirm-dialog';
import { DefaultsSection } from '@/components/settings/defaults-section';
import { ExpensesSection } from '@/components/settings/expenses-section';
import { FeeSection } from '@/components/settings/fee-section';
import { HistorySection } from '@/components/settings/history-section';
import { SettingsWriterProvider } from '@/components/settings/settings-writer';
import { TariffSection } from '@/components/settings/tariff-section';
import {
  useCanEdit,
  useCarriersQuery,
  useSettingsQuery,
} from '@/components/settings/use-settings-data';
import { ReportError, ReportFooter, ReportSkeleton } from '@/components/profit/shared';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { SettingsOut } from '@/lib/api/profit-settings';
import { describeReportError } from '@/lib/profit/errors';
import { todayIstanbul } from '@/lib/profit/settings-input';
import { setupProgressText, setupSteps } from '@/lib/profit/settings-present';

const SECTION_LINKS = [
  { href: '#kargo', label: 'Kargo tarifesi' },
  { href: '#hizmet-bedeli', label: 'Hizmet bedeli' },
  { href: '#desi', label: 'Varsayılan desi' },
  { href: '#giderler', label: 'Değişken giderler' },
  { href: '#gecmis', label: 'Ayar geçmişi' },
] as const;

/**
 * Kâr ayarları formu (/panel/ayarlar): kargo tarifesi, hizmet bedeli tahmini, varsayılan desi, değişken giderler ve
 * ayar geçmişi. Okuma TanStack Query ile, yazma `SettingsWriterProvider` akışıyla yapılır (409 onayı, sürüm
 * çakışması). Sorgu istemcisi bu panele özgüdür.
 */
export function ProfitSettingsPanel({ accountId }: { accountId: string }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <PanelBody accountId={accountId} />
    </QueryClientProvider>
  );
}

function PanelBody({ accountId }: { accountId: string }) {
  const settings = useSettingsQuery(accountId);

  if (settings.isPending) {
    return (
      <section aria-label="Kâr ayarları">
        <ReportSkeleton rows={3} />
      </section>
    );
  }
  if (settings.isError) {
    return (
      <section aria-label="Kâr ayarları">
        <ReportError
          title="Kâr ayarları yüklenemedi"
          message={describeReportError(settings.error)}
          onRetry={() => void settings.refetch()}
        />
      </section>
    );
  }
  return (
    <SettingsWriterProvider accountId={accountId} revision={settings.data.revision}>
      <SettingsBody accountId={accountId} settings={settings.data} />
      <ConfirmPastChangeDialog />
    </SettingsWriterProvider>
  );
}

function SettingsBody({ accountId, settings }: { accountId: string; settings: SettingsOut }) {
  const carriersQuery = useCarriersQuery(accountId);
  const canEdit = useCanEdit();
  const [today] = useState(() => todayIstanbul());
  const steps = setupSteps(settings.completeness);

  // Özetteki bant /panel/ayarlar#kargo gibi bağlantı verir; içerik sonradan geldiği için kaydırma burada yapılır.
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (!id) return;
    document.getElementById(id)?.scrollIntoView({ block: 'start' });
  }, []);

  const carriers = {
    status: carriersQuery.isPending
      ? ('loading' as const)
      : carriersQuery.isError
        ? ('error' as const)
        : ('ready' as const),
    data: carriersQuery.data,
    retry: () => void carriersQuery.refetch(),
  };

  return (
    <>
      <section aria-labelledby="kurulum-baslik">
        <Card>
          <CardHeader>
            <CardTitle as="h2" id="kurulum-baslik">
              Kâr ayarları
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              Net kârın hesaplanması için kargo tarifenizi ve hizmet bedeli tahmininizi girin.
              Değişiklik yaptıkça rakamlar güncellenir.
            </p>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="num text-base font-semibold">{setupProgressText(steps)}</p>
            <ol className="flex list-none flex-col gap-2 p-0">
              {steps.map((step, index) => (
                <li key={step.id} className="flex items-center gap-2 text-base">
                  {step.done ? (
                    <CheckCircle2 className="size-5 shrink-0 text-info" aria-hidden="true" />
                  ) : (
                    <Circle className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  )}
                  <span>
                    {index + 1}. {step.label}:{' '}
                    <span className="font-medium">{step.done ? 'bugün geçerli' : 'eksik'}</span>
                  </span>
                </li>
              ))}
            </ol>
            <nav aria-label="Ayar bölümleri">
              <ul className="flex list-none flex-wrap gap-2 p-0">
                {SECTION_LINKS.map((link) => (
                  <li key={link.href}>
                    <a
                      href={link.href}
                      className="inline-flex min-h-touch items-center rounded-md border border-input-border bg-surface px-3 text-base font-medium text-primary hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
            {!canEdit ? (
              <p
                role="note"
                className="flex items-start gap-2 rounded-lg bg-info-soft p-3 text-sm font-medium text-info"
              >
                <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                Ayarları görüntüleyebilirsiniz. Değiştirmek için hesabın sahibi ya da yöneticisi
                olmalısınız.
              </p>
            ) : null}
          </CardContent>
        </Card>
      </section>

      <TariffSection
        accountId={accountId}
        settings={settings}
        carriers={carriers}
        canEdit={canEdit}
        today={today}
      />
      <FeeSection
        accountId={accountId}
        settings={settings}
        lookbackDays={carriersQuery.data?.lookback_days}
        canEdit={canEdit}
        today={today}
      />
      <DefaultsSection accountId={accountId} settings={settings} canEdit={canEdit} />
      <ExpensesSection
        accountId={accountId}
        settings={settings}
        lookbackDays={carriersQuery.data?.lookback_days}
        canEdit={canEdit}
        today={today}
      />
      <HistorySection accountId={accountId} revision={settings.revision} />
      <ReportFooter revision={settings.revision} />
    </>
  );
}
