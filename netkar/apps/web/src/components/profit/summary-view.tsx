'use client';

import { Info, Store, TriangleAlert } from 'lucide-react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import {
  MetricValue,
  Money,
  NetProfitCell,
  RangeSwitcher,
  ReportError,
  ReportSkeleton,
  SpecBadge,
} from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ProfitValue } from '@/components/profit-value';
import { profitApi, type ProfitSummary, type RangeName } from '@/lib/api/profit';
import { describeReportError } from '@/lib/profit/errors';
import { certaintyBadge, periodLabel, summaryView, type SummaryView } from '@/lib/profit/present';
import { parseRange } from '@/lib/profit/query';
import { useReportAccount } from '@/lib/profit/use-account';
import { useReportQuery } from '@/lib/profit/use-report-query';

const STATUS_LABELS = [
  { key: 'estimated', label: 'Tahmini (ekstresiz)' },
  { key: 'settled', label: 'Ekstreli' },
  { key: 'adjusted', label: 'Düzeltilmiş' },
  { key: 'cancelled', label: 'İptal' },
] as const;

const HEADER_TEXT = {
  title: 'Özet',
  description: 'Seçtiğiniz dönemde ne kazandığınız ve hangi kalemlerin eksik olduğu.',
};

export function SummaryScreen() {
  const range = parseRange(useSearchParams().get('range'));
  const { state: account, retry: retryAccount } = useReportAccount();
  const accountId = account.status === 'ready' ? account.accountId : null;

  return (
    <>
      <PageHeader {...HEADER_TEXT} />
      <RangeSwitcher range={range} hrefFor={(value) => `/panel?range=${value}`} />
      {account.status === 'loading' ? <ReportSkeleton rows={4} /> : null}
      {account.status === 'error' ? (
        <ReportError message={describeReportError(account.error)} onRetry={retryAccount} />
      ) : null}
      {account.status === 'none' ? <NoStore /> : null}
      {accountId ? <SummaryBody accountId={accountId} range={range} /> : null}
    </>
  );
}

function NoStore() {
  return (
    <EmptyState
      Icon={Store}
      title="Trendyol mağazanızı bağlayın, ilk kârınızı 10 dakikada görün"
      description="Bağlantı yalnız okuma yapar. Sipariş, komisyon ve kargo bilgileriniz ürün bazında net kâra çevrilir."
      action={{ href: '/panel/ayarlar', label: 'Bağlantıya başla' }}
    />
  );
}

function SummaryBody({ accountId, range }: { accountId: string; range: RangeName }) {
  const summary = useReportQuery(true, `${accountId}|${range}`, (signal) =>
    profitApi.summary(accountId, range, signal),
  );

  if (summary.state.status === 'loading' || summary.state.status === 'idle') {
    return <ReportSkeleton rows={4} />;
  }
  if (summary.state.status === 'error') {
    return (
      <ReportError message={describeReportError(summary.state.error)} onRetry={summary.retry} />
    );
  }
  return <SummaryContent accountId={accountId} range={range} data={summary.state.data} />;
}

function SummaryContent({
  accountId,
  range,
  data,
}: {
  accountId: string;
  range: RangeName;
  data: ProfitSummary;
}) {
  const view = summaryView(data.totals);
  const period = periodLabel(data.period.start, data.period.end);

  if (view.empty) {
    return (
      <>
        <p className="text-sm text-muted-foreground">Dönem: {period}</p>
        <EmptyState
          Icon={Info}
          title="Bu dönemde sipariş yok"
          description="Başka bir dönem seçebilirsiniz. Siparişler geldikçe net kâr burada görünür."
        />
      </>
    );
  }

  const certainty = certaintyBadge(data.totals.kesinlik);
  const lineCounts = data.totals.kesinlik_satir_sayilari;

  return (
    <>
      <p className="text-sm text-muted-foreground">
        Dönem: <span className="num">{period}</span>
      </p>

      <SetupBanner view={view} />

      <section aria-label="Başlık rakamlar" className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardDescription>Net kâr</CardDescription>
            <CardTitle as="h2" className="flex flex-wrap items-center gap-2 text-2xl">
              {view.netProfit.kind === 'value' ? (
                <ProfitValue value={view.netProfit.value} />
              ) : (
                <NetProfitCell display={view.netProfit} />
              )}
              {certainty ? <SpecBadge spec={certainty} /> : null}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
            {view.partial ? (
              <p>
                Bazı satırlarda gider kalemleri eksik olduğu için dönemin net kârı hesaplanamıyor.
              </p>
            ) : null}
            {view.fullLines ? (
              <p>
                Eksiksiz {view.fullLines.count} satırın net kârı, dönem giderleri hariç:{' '}
                <ProfitValue value={view.fullLines.netProfit} className="text-base" />
              </p>
            ) : null}
            <p>
              Kesin <span className="num">{lineCounts.kesin}</span>, tahmini{' '}
              <span className="num">{lineCounts.tahmini}</span>, eksik{' '}
              <span className="num">{lineCounts.eksik}</span> satır
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>Net satış (KDV hariç)</CardDescription>
            <CardTitle as="h2" className="text-2xl">
              <Money value={data.totals.net_satis_kdv_haric} />
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <span className="num">{data.totals.siparis_sayisi}</span> sipariş,{' '}
            <span className="num">{data.totals.satir_sayisi}</span> satır
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>Toplam gider</CardDescription>
            <CardTitle as="h2" className="text-2xl">
              <MetricValue metric={view.totalExpenses} kind="money" />
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1 text-sm text-muted-foreground">
            {view.totalExpenses.scopeLabel ? <p>{view.totalExpenses.scopeLabel}</p> : null}
            {view.periodLevelExpenses ? (
              <p>
                Ürüne dağıtılmayan dönem giderleri ayrıca:{' '}
                <Money value={view.periodLevelExpenses} />
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>Net kâr marjı</CardDescription>
            <CardTitle as="h2" className="text-2xl">
              <MetricValue metric={view.margin} kind="percent" coloured />
            </CardTitle>
          </CardHeader>
          {view.margin.label ? (
            <CardContent className="text-sm text-muted-foreground">{view.margin.label}</CardContent>
          ) : null}
        </Card>
      </section>

      <section aria-label="Durum ve uyarılar" className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle as="h2">Satır durumları</CardTitle>
            <CardDescription>Ekstresi gelen satırlar kesinleşir.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="flex flex-col gap-2">
              {STATUS_LABELS.map(({ key, label }) => (
                <div key={key} className="flex items-center justify-between gap-3">
                  <dt className="text-base">{label}</dt>
                  <dd className="num text-base font-semibold">{data.status_counts[key]}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <AlertsCard accountId={accountId} range={range} />
      </section>

      <p>
        <Button asChild variant="secondary">
          <Link href={`/panel/urunler?range=${range}&filter=loss`}>Zarar ettiren ürünleri gör</Link>
        </Button>
      </p>
    </>
  );
}

function SetupBanner({ view }: { view: SummaryView }) {
  const banner = view.banner;
  if (!banner) return null;
  return (
    <section
      aria-label="Kurulum uyarısı"
      className="flex flex-col gap-3 rounded-lg border border-transparent bg-warning-soft p-5 text-warning"
    >
      <h2 className="flex items-start gap-2 text-lg font-semibold">
        <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        {banner.title}
      </h2>
      <p className="text-base">{banner.detail}</p>
      {banner.costLine ? <p className="text-base">{banner.costLine}</p> : null}
      <p>
        <Button asChild>
          <Link href="/panel/ayarlar">Kargo ve hizmet bedelini gir</Link>
        </Button>
      </p>
    </section>
  );
}

function AlertsCard({ accountId, range }: { accountId: string; range: RangeName }) {
  // Motor kapısı beklemez; bu yüzden özetten SONRA ve ayrı çağrıyla istenir. Hata kartı sessizce düşürür.
  const alerts = useReportQuery(true, `${accountId}|${range}|alerts`, (signal) =>
    profitApi.alertCounts(accountId, range, signal),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Uyarılar</CardTitle>
        <CardDescription>Dönemde motorun işaretlediği durumlar.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {alerts.state.status === 'loading' || alerts.state.status === 'idle' ? (
          <p className="text-sm text-muted-foreground" role="status">
            Uyarılar yükleniyor
          </p>
        ) : null}
        {alerts.state.status === 'error' ? (
          <p className="text-sm text-muted-foreground">
            Uyarı sayıları şu an yüklenemedi. Uyarılar sayfasından bakabilirsiniz.
          </p>
        ) : null}
        {alerts.state.status === 'ready' && alerts.state.data.counts.length === 0 ? (
          <p className="text-base">Bu dönemde uyarı yok.</p>
        ) : null}
        {alerts.state.status === 'ready' && alerts.state.data.counts.length > 0 ? (
          <ul className="flex list-none flex-col gap-2">
            {alerts.state.data.counts.map((item) => (
              <li key={item.code} className="flex items-start justify-between gap-3">
                <span className="text-base">{item.message}</span>
                <Badge variant="warning" className="num shrink-0">
                  {item.count}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}
        <Link
          href="/panel/uyarilar"
          className="inline-flex min-h-touch items-center text-base text-primary underline underline-offset-4"
        >
          Tüm uyarılar
        </Link>
      </CardContent>
    </Card>
  );
}
