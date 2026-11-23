'use client';

import { Store } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { useCallback, useState } from 'react';

import { EventsPanel } from '@/components/alerts/events-panel';
import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import { PeriodAlerts } from '@/components/profit/alerts-view';
import { FilterNav, ReportError, ReportSkeleton } from '@/components/profit/shared';
import { TAB_LABELS, TAB_ORDER, TAB_STATUS, parseTab, type AlertTab } from '@/lib/alerts/present';
import { useAlertAccess } from '@/lib/alerts/use-access';
import { formatCount } from '@/lib/format';
import { describeReportError } from '@/lib/profit/errors';
import { useReportAccount } from '@/lib/profit/use-account';

/**
 * Uyarılar sayfası (ADR-0009 D7): birincil içerik uyarı OLAYLARIdır (açık, okundu, susturulmuş, çözülmüş ve tümü sekmeleri);
 * eski rapor tabanlı uyarılar "Dönem dökümü" sekmesinde olduğu gibi durur. Sekme URL'de (`?sekme=`) tutulur:
 * bağlantı paylaşılabilir ve yenilemede korunur. Sekme geçişi `replace` ile yapılır (FilterNav deseni), geçmişe
 * yeni kayıt eklemez.
 */
export function AlertsScreen() {
  const tab = parseTab(useSearchParams().get('sekme'));
  const { state: account, retry: retryAccount } = useReportAccount();
  const access = useAlertAccess();
  const [openCount, setOpenCount] = useState<number | null>(null);
  const onOpenDelta = useCallback(
    (delta: number) =>
      setOpenCount((count) => (count === null ? count : Math.max(0, count + delta))),
    [],
  );

  return (
    <>
      <PageHeader
        title="Uyarılar"
        description="Dikkat etmeniz gerekenler: önce para kaybettirenler, sonra eksik kurulum."
      />
      {account.status === 'loading' ? <ReportSkeleton rows={4} /> : null}
      {account.status === 'error' ? (
        <ReportError
          title="Uyarılar yüklenemedi"
          message={describeReportError(account.error)}
          onRetry={retryAccount}
        />
      ) : null}
      {account.status === 'none' ? (
        <EmptyState
          Icon={Store}
          title="Trendyol mağazanızı bağlayın"
          description="Mağaza bağlandığında zarar, eksik kurulum ve beklenmeyen kesintiler burada listelenir."
          action={{ href: '/panel/ayarlar', label: 'Bağlantıya başla' }}
        />
      ) : null}
      {account.status === 'ready' ? (
        <>
          <FilterNav<AlertTab>
            label="Uyarı sekmeleri"
            active={tab}
            options={TAB_ORDER.map((value) => ({
              value,
              label:
                value === 'acik' && openCount !== null
                  ? `${TAB_LABELS[value]} (${formatCount(openCount)})`
                  : TAB_LABELS[value],
            }))}
            hrefFor={(value) => `/panel/uyarilar?sekme=${value}`}
          />
          {tab === 'donem' ? (
            <PeriodAlerts accountId={account.accountId} />
          ) : (
            <EventsPanel
              key={`${account.accountId}|${tab}`}
              accountId={account.accountId}
              status={TAB_STATUS[tab]}
              access={access}
              onOpenCount={setOpenCount}
              onOpenDelta={onOpenDelta}
            />
          )}
        </>
      ) : null}
    </>
  );
}
