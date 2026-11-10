'use client';

import { CircleHelp, Info, Store, TriangleAlert } from 'lucide-react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import {
  LossAmount,
  MetricCard,
  MetricValue,
  Money,
  RangeSwitcher,
  ReportError,
  ReportFooter,
  ReportSkeleton,
  SpecBadge,
} from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ProfitValue } from '@/components/profit-value';
import {
  profitApi,
  type ProductProfitList,
  type ProfitSummary,
  type RangeName,
} from '@/lib/api/profit';
import { describeReportError } from '@/lib/profit/errors';
import {
  SETUP_COMING_SOON,
  certaintyBadge,
  lossBadge,
  periodLabel,
  summaryView,
  topLossItems,
  type SummaryView,
} from '@/lib/profit/present';
import { parseRange, productQueryString } from '@/lib/profit/query';
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

/** Özetteki "zarar ettiren ürünler" bölümü kaç ürün gösterir */
const TOP_LOSS_COUNT = 3;
/** API en çok 200 ürün döndürür; null net kârlı kesin zararlar sıralamada sona düştüğünden hepsi çekilir (AD-04) */
const LOSS_FETCH_LIMIT = 200;

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
        <ReportFooter revision={data.settings_revision} />
      </>
    );
  }

  return (
    <>
      <p className="text-sm text-muted-foreground">
        Dönem: <span className="num">{period}</span>
      </p>

      <HeadlineCard view={view} data={data} />

      <TopLosses accountId={accountId} range={range} partial={view.partial} />

      <section aria-label="Diğer rakamlar" className="grid gap-4 sm:grid-cols-2">
        <MetricCard
          label="Net satış (KDV hariç)"
          footer={
            <p>
              <span className="num">{data.totals.siparis_sayisi}</span> sipariş,{' '}
              <span className="num">{data.totals.satir_sayisi}</span> satır
            </p>
          }
        >
          <Money value={data.totals.net_satis_kdv_haric} />
        </MetricCard>

        {view.totalExpenses ? (
          <MetricCard
            label="Toplam gider"
            footer={
              view.totalExpenses.scopeLabel || view.periodLevelExpenses ? (
                <>
                  {view.totalExpenses.scopeLabel ? <p>{view.totalExpenses.scopeLabel}</p> : null}
                  {view.periodLevelExpenses ? (
                    <p>
                      Ürüne dağıtılmayan dönem giderleri ayrıca:{' '}
                      <Money value={view.periodLevelExpenses} />
                    </p>
                  ) : null}
                </>
              ) : null
            }
          >
            <MetricValue metric={view.totalExpenses} kind="money" />
          </MetricCard>
        ) : null}

        {view.margin ? (
          <MetricCard
            label="Net kâr marjı"
            footer={view.margin.label ? <p>{view.margin.label}</p> : null}
          >
            <MetricValue metric={view.margin} kind="percent" coloured />
          </MetricCard>
        ) : null}
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

      <ReportFooter revision={data.settings_revision} />
    </>
  );
}

/**
 * Baş kart (ADR-0007 §5.2, rapor §5.2 üç durum): tam dönemde dönem net kârı; kısmi dönemde "hesaplanamadı",
 * eksik kalemler, kurulum çağrısı ve "eksik giderler hariç dönem kârı"; eksiksiz satır yoksa (G49) yalnız bunlar.
 */
function HeadlineCard({ view, data }: { view: SummaryView; data: ProfitSummary }) {
  const certainty = certaintyBadge(data.totals.kesinlik);
  const lineCounts = data.totals.kesinlik_satir_sayilari;

  if (view.netProfit.kind === 'value') {
    return (
      <MetricCard
        label={view.netProfitLabel}
        footer={
          <p>
            Kesin <span className="num">{lineCounts.kesin}</span>, tahmini{' '}
            <span className="num">{lineCounts.tahmini}</span>, eksik{' '}
            <span className="num">{lineCounts.eksik}</span> satır
          </p>
        }
      >
        <ProfitValue value={view.netProfit.value} />
        {certainty ? <SpecBadge spec={certainty} /> : null}
      </MetricCard>
    );
  }

  const known = view.knownProfit;
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="flex items-center gap-2 text-xl">
          <CircleHelp className="size-5 shrink-0" aria-hidden="true" />
          {view.netProfitLabel}
        </CardTitle>
        {view.banner ? (
          <p className="text-base text-muted-foreground">{view.banner.detail}</p>
        ) : null}
        {view.costLine ? <p className="text-base text-muted-foreground">{view.costLine}</p> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {view.banner ? (
          <section
            aria-label="Kurulum uyarısı"
            className="flex flex-col gap-2 rounded-lg border border-transparent bg-warning-soft p-4 text-warning"
          >
            <h3 className="flex items-start gap-2 text-lg font-semibold">
              <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
              {view.banner.title}
            </h3>
            <p className="text-base">{SETUP_COMING_SOON}</p>
          </section>
        ) : null}

        {known ? (
          <div className="flex flex-col gap-1 border-t border-border pt-4">
            <h3 className="text-base font-semibold">{known.label}</h3>
            {known.scope ? <p className="text-sm text-muted-foreground">{known.scope}</p> : null}
            <p className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
              {known.loss ? <ProfitValue value={known.value} /> : <Money value={known.value} />}
              {known.badge ? <SpecBadge spec={known.badge} /> : null}
            </p>
            <p className="text-sm text-muted-foreground">{known.note}</p>
          </div>
        ) : null}

        {view.fullLines ? (
          <div className="flex flex-col gap-1 rounded-lg border border-border bg-surface-muted p-4">
            <h3 className="text-base font-semibold">
              Eksiksiz <span className="num">{view.fullLines.count}</span> satır
            </h3>
            <p className="text-base">
              Net kâr: <ProfitValue value={view.fullLines.netProfit} className="text-base" />
            </p>
            <p className="text-sm text-muted-foreground">Dönem giderleri hariç.</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** UX-03 ve UX-04: "hangi ürün zarar ettiriyor" sorusunun cevabı baş kartın hemen altında, en büyük zarar üstte. */
function TopLosses({
  accountId,
  range,
  partial,
}: {
  accountId: string;
  range: RangeName;
  partial: boolean;
}) {
  const losses = useReportQuery(true, `${accountId}|${range}|losses`, (signal) =>
    profitApi.products(
      accountId,
      { range, sort: 'net_profit', order: 'asc', filter: 'loss', limit: LOSS_FETCH_LIMIT },
      signal,
    ),
  );
  const allHref = `/panel/urunler?${productQueryString({
    range,
    sort: 'net_profit',
    order: 'asc',
    filter: 'loss',
  })}`;

  return (
    <section aria-labelledby="losses-heading">
      <Card>
        <CardHeader>
          <CardTitle as="h2" id="losses-heading">
            Zarar ettiren ürünler
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {losses.state.status === 'loading' || losses.state.status === 'idle' ? (
            <p className="text-sm text-muted-foreground" role="status">
              Zarar eden ürünler yükleniyor
            </p>
          ) : null}
          {losses.state.status === 'error' ? (
            <p className="text-base text-muted-foreground">
              Zarar eden ürünler şu an yüklenemedi. Biraz sonra tekrar deneyin.
            </p>
          ) : null}
          {losses.state.status === 'ready' ? (
            <LossList
              items={losses.state.data.items}
              total={losses.state.data.total_count}
              range={range}
              partial={partial}
              allHref={allHref}
            />
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}

function LossList({
  items,
  total,
  range,
  partial,
  allHref,
}: {
  items: ProductProfitList['items'];
  total: number;
  range: RangeName;
  partial: boolean;
  allHref: string;
}) {
  const rows = topLossItems(items, TOP_LOSS_COUNT);
  if (rows.length === 0) {
    return (
      <>
        <p className="text-base">Bu dönemde zararı kesin olan ürün yok.</p>
        {partial ? (
          <p className="text-sm text-muted-foreground">
            Kargo ya da hizmet bedeli eksik olduğundan bazı ürünlerin kârı belirsiz olabilir.
          </p>
        ) : null}
      </>
    );
  }
  return (
    <>
      <ul className="flex list-none flex-col gap-3">
        {rows.map(({ item, loss }) => {
          const badge = lossBadge(item);
          return (
            <li key={item.barcode} className="flex flex-col gap-1">
              <Link
                href={`/panel/urunler/${encodeURIComponent(item.barcode)}?range=${range}`}
                className="inline-flex min-h-touch items-center break-words text-base font-semibold text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {item.title && item.title.trim() ? item.title : 'Başlıksız ürün'}
              </Link>
              <span className="flex flex-wrap items-center gap-2 text-lg">
                <LossAmount loss={loss} />
                {badge ? <SpecBadge spec={badge} /> : null}
              </span>
              {loss.note ? (
                <span className="text-sm text-muted-foreground">{loss.note}</span>
              ) : null}
            </li>
          );
        })}
      </ul>
      <Link
        href={allHref}
        className="inline-flex min-h-touch items-center text-base text-primary underline underline-offset-4"
      >
        Tümünü gör (<span className="num">{total}</span>)
      </Link>
    </>
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
            Uyarı sayıları şu an yüklenemedi. Biraz sonra tekrar deneyin.
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
        {/* UX-08: uyarılar ekranı yazılana kadar "Tüm uyarılar" bağlantısı yok; yer tutucu sayfa
            "uyarı yok" diyerek bu kartla çelişiyordu. */}
      </CardContent>
    </Card>
  );
}
