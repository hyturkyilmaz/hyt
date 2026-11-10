'use client';

import { History } from 'lucide-react';

import { SectionHeading } from '@/components/settings/fields';
import { ReportError } from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { profitSettingsApi, type HistoryOut } from '@/lib/api/profit-settings';
import { describeReportError } from '@/lib/profit/errors';
import { historyEntryView } from '@/lib/profit/settings-present';
import { usePagedList } from '@/lib/profit/use-paged-list';

const PAGE_SIZE = 20;

/**
 * Ayar geçmişi (ADR-0007 §5.2 madde 2): `GET /history`, yeniden eskiye, mühürlü imleçle sayfalı. Ayar sürümü
 * değişince (her yazım) liste baştan yüklenir. Kişi olarak rol gösterilir; ad ve e-posta yoktur (YT-08).
 */
export function HistorySection({ accountId, revision }: { accountId: string; revision: number }) {
  const list = usePagedList<HistoryOut, HistoryOut['items'][number]>({
    enabled: true,
    resetKey: `${accountId}:${revision}`,
    fetchPage: (cursor, signal) =>
      profitSettingsApi.history(accountId, { limit: PAGE_SIZE, cursor }, signal),
    getItems: (page) => page.items,
  });

  return (
    <Card as="section" id="gecmis" aria-labelledby="gecmis-baslik" className="scroll-mt-4">
      <CardHeader>
        <SectionHeading
          id="gecmis"
          title="Ayar geçmişi"
          description="Ayarlarda yapılan her değişiklik burada saklanır; önceki değerler silinmez."
        />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {list.restarted ? (
          <p
            role="status"
            className="rounded-md border border-border bg-info-soft px-4 py-3 text-base text-info"
          >
            Liste güncellendiği için baştan yüklendi.
          </p>
        ) : null}
        {list.status === 'loading' ? (
          <div role="status" aria-live="polite" className="flex flex-col gap-3">
            <span className="sr-only">Yükleniyor</span>
            <div aria-hidden="true" className="flex flex-col gap-3">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          </div>
        ) : null}
        {list.status === 'error' ? (
          <ReportError
            title="Ayar geçmişi yüklenemedi"
            message={describeReportError(list.error)}
            onRetry={list.reload}
          />
        ) : null}
        {list.status === 'ready' && list.items.length === 0 ? (
          <p className="flex items-center gap-2 text-base text-muted-foreground">
            <History className="size-5 shrink-0" aria-hidden="true" />
            Henüz ayar değişikliği yok. Kargo tarifesi ya da hizmet bedeli girdiğinizde burada
            görünür.
          </p>
        ) : null}
        {list.status === 'ready' && list.items.length > 0 ? (
          <ol aria-label="Ayar değişiklikleri" className="flex list-none flex-col gap-3 p-0">
            {list.items.map((entry) => {
              const view = historyEntryView(entry);
              return (
                <li
                  key={view.key}
                  className="flex flex-col gap-1.5 rounded-lg border border-border p-4"
                >
                  <p className="text-sm text-muted-foreground">
                    {view.when}, {view.who}
                  </p>
                  <p className="text-base font-medium">{view.headline}</p>
                  {view.details.length > 0 ? (
                    <ul className="num flex list-disc flex-col gap-0.5 pl-5 text-sm">
                      {view.details.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  ) : null}
                  {view.badges.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {view.badges.map((badge) => (
                        <Badge key={badge.label} variant={badge.tone}>
                          {badge.label}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : null}
        {list.moreError ? (
          <p role="alert" className="text-base text-loss">
            {describeReportError(list.moreError)}
          </p>
        ) : null}
        {list.hasMore ? (
          <div className="flex justify-center">
            <Button variant="secondary" onClick={list.loadMore} disabled={list.loadingMore}>
              {list.loadingMore ? 'Yükleniyor' : 'Daha fazla göster'}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
