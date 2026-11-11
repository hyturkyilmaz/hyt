'use client';

import {
  CircleCheck,
  CircleHelp,
  Info,
  Store,
  TrendingDown,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useId, useState } from 'react';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import {
  Money,
  RangeSwitcher,
  ReportError,
  ReportFooter,
  ReportSkeleton,
} from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { profitApi, type ProfitAlerts, type RangeName } from '@/lib/api/profit';
import {
  buildAlertGroups,
  deductionRows,
  unavailableAlertNames,
  type AlertCard,
  type AlertGroup,
  type AlertTone,
} from '@/lib/profit/alerts';
import { describeReportError } from '@/lib/profit/errors';
import { periodLabel } from '@/lib/profit/present';
import { parseRange } from '@/lib/profit/query';
import { retryOnceOnRateLimit } from '@/lib/profit/rate-limit-retry';
import { useReportAccount } from '@/lib/profit/use-account';
import { usePagedList } from '@/lib/profit/use-paged-list';
import { useReportQuery } from '@/lib/profit/use-report-query';

/** "Etkilenen siparişler" listesi sayfa boyu */
const DETAIL_PAGE_SIZE = 20;

// Renk tek başına anlam taşımaz: her tonun simgesi ve görünür başlığı vardır.
const TONE_ICON: Record<AlertTone, LucideIcon> = {
  loss: TrendingDown,
  warning: TriangleAlert,
  info: Info,
  neutral: CircleHelp,
};
const TONE_TEXT: Record<AlertTone, string> = {
  loss: 'text-loss',
  warning: 'text-warning',
  info: 'text-info',
  neutral: 'text-muted-foreground',
};

export function AlertsScreen() {
  const range = parseRange(useSearchParams().get('range'));
  const { state: account, retry: retryAccount } = useReportAccount();

  return (
    <>
      <PageHeader
        title="Uyarılar"
        description="Bu dönemde dikkat etmeniz gerekenler: önce para kaybettirenler, sonra eksik kurulum."
      />
      <RangeSwitcher range={range} hrefFor={(value) => `/panel/uyarilar?range=${value}`} />
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
        <AlertsBody accountId={account.accountId} range={range} />
      ) : null}
    </>
  );
}

function AlertsBody({ accountId, range }: { accountId: string; range: RangeName }) {
  // Sayımlar süzgeçsizdir ve tüm dönemi sayar; ayrıntı listesi kart açılınca ayrıca istenir (limit=1 yeter).
  const alerts = useReportQuery(true, `${accountId}|${range}|alerts-page`, (signal) =>
    retryOnceOnRateLimit(() => profitApi.alerts(accountId, { range, limit: 1 }, signal), signal),
  );

  if (alerts.state.status === 'loading' || alerts.state.status === 'idle') {
    return <ReportSkeleton rows={4} />;
  }
  if (alerts.state.status === 'error') {
    return (
      <ReportError
        title="Uyarılar yüklenemedi"
        message={describeReportError(alerts.state.error)}
        onRetry={alerts.retry}
      />
    );
  }
  return <AlertsContent accountId={accountId} range={range} data={alerts.state.data} />;
}

function AlertsContent({
  accountId,
  range,
  data,
}: {
  accountId: string;
  range: RangeName;
  data: ProfitAlerts;
}) {
  const groups = buildAlertGroups(data.counts);
  const pending = unavailableAlertNames(data.not_yet_available ?? []);

  return (
    <>
      <p className="text-sm text-muted-foreground">
        Dönem: <span className="num">{periodLabel(data.period.start, data.period.end)}</span>
      </p>

      {groups.length === 0 ? (
        <EmptyState
          Icon={CircleCheck}
          title="Bu dönemde uyarı yok"
          description="Zarar, eksik kurulum ya da beklenmeyen kesinti görünmüyor. Başka bir dönem seçebilirsiniz."
        />
      ) : (
        groups.map((group) => (
          <GroupSection key={group.id} group={group} accountId={accountId} range={range} />
        ))
      )}

      {pending.length > 0 ? <PendingAlerts names={pending} /> : null}
      <ReportFooter revision={data.settings_revision} />
    </>
  );
}

function GroupSection({
  group,
  accountId,
  range,
}: {
  group: AlertGroup;
  accountId: string;
  range: RangeName;
}) {
  const headingId = `alert-group-${group.id}`;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="text-2xl font-semibold">
          {group.title}
        </h2>
        <p className="text-base text-muted-foreground">{group.description}</p>
      </div>
      <ul className="grid list-none items-start gap-4 lg:grid-cols-2">
        {group.cards.map((card) => (
          <li key={card.code} className="flex">
            <AlertCardView card={card} accountId={accountId} range={range} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function AlertCardView({
  card,
  accountId,
  range,
}: {
  card: AlertCard;
  accountId: string;
  range: RangeName;
}) {
  const Icon = TONE_ICON[card.tone];
  const badgeVariant = card.tone === 'neutral' ? 'neutral' : card.tone;
  const action = card.action;
  return (
    <Card className="flex w-full flex-col">
      <CardHeader className="gap-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle as="h3" className="flex items-start gap-2 text-lg">
            <Icon className={`mt-0.5 size-5 shrink-0 ${TONE_TEXT[card.tone]}`} aria-hidden="true" />
            <span className="break-words">{card.title}</span>
          </CardTitle>
          <Badge variant={badgeVariant} className="num shrink-0">
            {card.periodLevel ? (
              'Dönem geneli'
            ) : (
              <>
                {card.count}
                <span className="sr-only"> uyarı</span>
              </>
            )}
          </Badge>
        </div>
        <p className="break-words text-base text-muted-foreground">{card.sentence}</p>
        {card.known ? null : (
          <p className="break-all text-xs text-muted-foreground">
            Uyarı kodu: <code>{card.code}</code>
          </p>
        )}
      </CardHeader>
      {action ? (
        <CardContent className="mt-auto flex flex-col gap-3">
          {action.kind === 'link' ? (
            <Button asChild variant="secondary" className="w-full sm:w-auto sm:self-start">
              <Link href={action.href(range)}>{action.label}</Link>
            </Button>
          ) : (
            <DeductionDetails
              label={action.label}
              code={card.code}
              accountId={accountId}
              range={range}
            />
          )}
        </CardContent>
      ) : null}
    </Card>
  );
}

/** Etkilenen siparişler: düğmeyle açılır, açılınca kod süzgeçli uyarı listesi istenir (imleçli sayfalama). */
function DeductionDetails({
  label,
  code,
  accountId,
  range,
}: {
  label: string;
  code: string;
  accountId: string;
  range: RangeName;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <>
      <Button
        variant="secondary"
        className="w-full sm:w-auto sm:self-start"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? 'Siparişleri gizle' : label}
      </Button>
      <div id={panelId} hidden={!open}>
        {open ? <DeductionList code={code} accountId={accountId} range={range} /> : null}
      </div>
    </>
  );
}

function DeductionList({
  code,
  accountId,
  range,
}: {
  code: string;
  accountId: string;
  range: RangeName;
}) {
  const list = usePagedList({
    enabled: true,
    resetKey: `${accountId}|${range}|${code}`,
    fetchPage: (cursor, signal) =>
      retryOnceOnRateLimit(
        () => profitApi.alerts(accountId, { range, code, cursor, limit: DETAIL_PAGE_SIZE }, signal),
        signal,
      ),
    getItems: (page) => page.items,
  });

  if (list.status === 'loading') {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        Siparişler yükleniyor
      </p>
    );
  }
  if (list.status === 'error') {
    return (
      <div className="flex flex-col items-start gap-3" role="alert">
        <p className="text-base text-muted-foreground">{describeReportError(list.error)}</p>
        <Button variant="secondary" onClick={list.reload}>
          Tekrar dene
        </Button>
      </div>
    );
  }
  const rows = deductionRows(list.items);
  if (rows.length === 0) {
    return <p className="text-base">Bu uyarıya bağlı sipariş bulunamadı.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {list.restarted ? (
        <p className="text-sm text-muted-foreground" role="status">
          Liste güncellendi, baştan yüklendi.
        </p>
      ) : null}
      <ul className="flex list-none flex-col gap-3" aria-label="Etkilenen siparişler">
        {rows.map((row) => (
          <li key={row.key} className="flex flex-col gap-1 border-t border-border pt-3">
            <span className="text-base font-semibold">
              {row.orderNumber ? (
                <>
                  Sipariş <span className="num break-all">{row.orderNumber}</span>
                </>
              ) : (
                'Sipariş bilgisi yok'
              )}
            </span>
            {row.barcode ? (
              <Link
                href={`/panel/urunler/${encodeURIComponent(row.barcode)}?range=${range}`}
                className="inline-flex min-h-touch items-center break-all text-base text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Ürün: {row.barcode}
              </Link>
            ) : null}
            {row.difference ? (
              <span className="text-sm text-muted-foreground">
                Trendyol beklediğimizden <Money value={row.difference} className="font-semibold" />{' '}
                fazla kesti.
                {row.threshold ? (
                  <>
                    {' '}
                    <Money value={row.threshold} /> altındaki farkları göstermiyoruz.
                  </>
                ) : null}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {list.moreError ? (
        <p className="text-sm text-muted-foreground" role="alert">
          {describeReportError(list.moreError)}
        </p>
      ) : null}
      {list.hasMore ? (
        <Button
          variant="secondary"
          className="w-full sm:w-auto sm:self-start"
          onClick={list.loadMore}
          disabled={list.loadingMore}
        >
          {list.loadingMore ? 'Yükleniyor' : 'Daha fazla yükle'}
        </Button>
      ) : null}
    </div>
  );
}

/** Motorun henüz üretmediği uyarılar: dürüstçe "henüz hesaplanmıyor" denir, sayı gösterilmez. */
function PendingAlerts({ names }: { names: readonly string[] }) {
  return (
    <section aria-labelledby="alert-pending" className="flex flex-col gap-2">
      <h2 id="alert-pending" className="text-lg font-semibold">
        Henüz hesaplanmayan uyarılar
      </h2>
      <p className="text-base text-muted-foreground">
        Bu uyarılar için veri henüz hazır değil; şu an görünmemeleri sorun olmadığını göstermez.
      </p>
      <ul className="flex list-none flex-wrap gap-2">
        {names.map((name) => (
          <li key={name}>
            <Badge variant="neutral">{name}</Badge>
          </li>
        ))}
      </ul>
    </section>
  );
}
