'use client';

import { ArrowLeft, Info, Store } from 'lucide-react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import {
  Money,
  NetProfitCell,
  RangeSwitcher,
  ReportError,
  ReportFooter,
  ReportSkeleton,
  SpecBadge,
} from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ProfitValue } from '@/components/profit-value';
import {
  profitApi,
  type LineStatus,
  type ProductProfitDetail,
  type ProductTotals,
  type ProfitLine,
  type RangeName,
} from '@/lib/api/profit';
import { describeReportError } from '@/lib/profit/errors';
import {
  certaintyBadge,
  comparisonRows,
  defaultDesiHint,
  expenseCell,
  knownProfitView,
  missingItemNames,
  netProfitDisplay,
  periodLabel,
  refundPending,
  shownAsCancelled,
  sourceBadge,
  productBreakdownRows,
  warningLabel,
  type ExpenseCell,
  type TotalsCellSpec,
} from '@/lib/profit/present';
import { parseRange } from '@/lib/profit/query';
import { useReportAccount } from '@/lib/profit/use-account';
import { usePagedList } from '@/lib/profit/use-paged-list';

const PAGE_SIZE = 50;

const STATUS_LABELS: Record<LineStatus, string> = {
  estimated: 'Ekstre bekleniyor',
  settled: 'Ekstreli',
  adjusted: 'Düzeltilmiş',
  cancelled: 'İptal',
};

export function ProductDetailScreen({ barcode }: { barcode: string }) {
  const range = parseRange(useSearchParams().get('range'));
  const { state: account, retry: retryAccount } = useReportAccount();
  const backHref = `/panel/urunler?range=${range}`;

  return (
    <>
      <Link
        href={backHref}
        className="inline-flex min-h-touch w-fit items-center gap-2 text-base text-primary underline underline-offset-4"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        Ürünlere dön
      </Link>
      {account.status === 'loading' ? (
        <>
          <PageHeader title="Ürün kırılımı" />
          <ReportSkeleton rows={3} />
        </>
      ) : null}
      {account.status === 'error' ? (
        <>
          <PageHeader title="Ürün kırılımı" />
          <ReportError message={describeReportError(account.error)} onRetry={retryAccount} />
        </>
      ) : null}
      {account.status === 'none' ? (
        <>
          <PageHeader title="Ürün kırılımı" />
          <EmptyState
            Icon={Store}
            title="Mağaza bağlı değil"
            description="Ürün kırılımını görmek için önce Trendyol mağazanızı bağlayın."
            action={{ href: '/panel/ayarlar', label: 'Mağazayı bağla' }}
          />
        </>
      ) : null}
      {account.status === 'ready' ? (
        <DetailBody accountId={account.accountId} barcode={barcode} range={range} />
      ) : null}
    </>
  );
}

function DetailBody({
  accountId,
  barcode,
  range,
}: {
  accountId: string;
  barcode: string;
  range: RangeName;
}) {
  const list = usePagedList({
    enabled: true,
    resetKey: `${accountId}|${barcode}|${range}`,
    fetchPage: (cursor, signal) =>
      profitApi.productDetail(accountId, barcode, { range, cursor, limit: PAGE_SIZE }, signal),
    getItems: (page) => page.lines,
  });
  const first = list.first;
  // Ürün başlığı metin düğümü olarak basılır (B-04).
  const heading = first?.title && first.title.trim() ? first.title : 'Ürün kırılımı';

  return (
    <>
      <PageHeader title={heading}>
        <p className="num break-all text-base text-muted-foreground">Barkod: {barcode}</p>
      </PageHeader>
      <RangeSwitcher
        range={range}
        hrefFor={(value) => `/panel/urunler/${encodeURIComponent(barcode)}?range=${value}`}
      />
      {list.status === 'loading' ? <ReportSkeleton rows={3} /> : null}
      {list.status === 'error' ? (
        <ReportError
          message={describeReportError(list.error)}
          onRetry={list.reload}
          title="Ürün kırılımı yüklenemedi"
        />
      ) : null}
      {list.status === 'ready' && first ? (
        <>
          {list.restarted ? (
            <p
              role="status"
              className="rounded-md border border-border bg-info-soft px-4 py-3 text-base text-info"
            >
              Liste güncellendiği için baştan yüklendi.
            </p>
          ) : null}
          <ProductSummary detail={first} />
          <section aria-labelledby="lines-heading" className="flex flex-col gap-3">
            <h2 id="lines-heading" className="text-xl font-semibold">
              Satırlar
            </h2>
            <p className="text-sm text-muted-foreground">
              <span className="num">{first.total_lines}</span> satır, dönem:{' '}
              <span className="num">{periodLabel(first.period.start, first.period.end)}</span>
            </p>
            {list.items.length === 0 ? (
              <EmptyState
                Icon={Info}
                title="Bu dönemde satır yok"
                description="Başka bir dönem seçebilirsiniz."
              />
            ) : (
              <ul className="flex list-none flex-col gap-4">
                {list.items.map((line) => (
                  <li key={`${line.orderNumber}-${line.lineId}`}>
                    <LineCard line={line} />
                  </li>
                ))}
              </ul>
            )}
            {list.moreError ? (
              <p role="alert" className="text-base text-loss">
                {describeReportError(list.moreError)}
              </p>
            ) : null}
            {list.hasMore ? (
              <div className="flex justify-center">
                <Button variant="secondary" onClick={list.loadMore} disabled={list.loadingMore}>
                  {list.loadingMore ? 'Yükleniyor' : 'Daha fazla satır yükle'}
                </Button>
              </div>
            ) : null}
          </section>
          <ReportFooter revision={first.settings_revision} />
        </>
      ) : null}
    </>
  );
}

function TotalsCell({ cell }: { cell: TotalsCellSpec }) {
  if (cell.kind === 'value') return <Money value={cell.value} />;
  if (cell.kind === 'partial') {
    // Y-6: bilinen tutar gizlenmez; eksik satırların henüz eklenmediği yanında söylenir.
    return (
      <span className="inline-flex flex-wrap items-baseline justify-end gap-x-1">
        <Money value={cell.value} />
        <span className="text-sm text-muted-foreground">
          + <span className="num">{cell.count}</span> satırda eksik
        </span>
      </span>
    );
  }
  return <span className="font-semibold">Eksik</span>;
}

function ProductSummary({ detail }: { detail: ProductProfitDetail }) {
  const product: ProductTotals | null = detail.product;
  // Eksik bilgi "Eksik: kargo" satırında adıyla yazılır; ayrıca "Bilgi eksik" rozeti basılmaz (UX-10).
  const certainty = detail.certainty === 'eksik' ? null : certaintyBadge(detail.certainty);
  if (!product) {
    return (
      <Card className="p-5 sm:p-6">
        <p className="text-base">
          Bu dönemde bu ürünün satışı yok; satırlar yalnız iptal kayıtlarından oluşuyor.
        </p>
      </Card>
    );
  }
  const counts = product.eksik_kalem_satir_sayilari;
  const missingCodes = (Object.keys(counts) as (keyof typeof counts)[]).filter(
    (k) => counts[k] > 0,
  );
  // Y-3: satışsız reklam yüzünden zarardaki ürün (kesinlik `yok`, net kâr negatif) iptal sayılmaz.
  const net = netProfitDisplay(product.net_kar, missingCodes, detail.certainty);
  const cancelled = shownAsCancelled(detail.certainty, product.net_kar);
  // UX-07: kırılım, liste ile aynı kuralı izler; net kâr null iken bilinen kâr ayrı, etiketli ve negatifse kırmızı.
  const known =
    product.net_kar === null && !cancelled
      ? knownProfitView(product.eksik_giderler_haric_kar, missingItemNames(missingCodes), 'urun')
      : null;
  const rows = productBreakdownRows(product);
  const comparison = detail.comparison;

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="text-sm font-normal text-muted-foreground">
          Ürün net kârı
        </CardTitle>
        <p className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
          <NetProfitCell display={net} />
          {certainty ? <SpecBadge spec={certainty} /> : null}
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {known ? (
          <div className="flex flex-col gap-1">
            <h3 className="text-base font-semibold">{known.label}</h3>
            {known.scope ? <p className="text-sm text-muted-foreground">{known.scope}</p> : null}
            <p className="flex flex-wrap items-center gap-2 text-xl font-semibold">
              {known.loss ? <ProfitValue value={known.value} /> : <Money value={known.value} />}
              {known.badge ? <SpecBadge spec={known.badge} /> : null}
            </p>
            <p className="text-sm text-muted-foreground">{known.note}</p>
          </div>
        ) : null}
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {rows.map((row) => (
            <div key={row.key} className="flex items-center justify-between gap-3">
              <dt className="text-base text-muted-foreground">{row.label}</dt>
              <dd className="text-base">
                <TotalsCell cell={row.cell} />
              </dd>
            </div>
          ))}
          {net.kind === 'value' ? (
            <div className="flex items-center justify-between gap-3 border-t border-border pt-2 sm:col-span-2">
              <dt className="text-base font-semibold">Net kâr</dt>
              <dd className="text-base">
                <NetProfitCell display={net} />
              </dd>
            </div>
          ) : null}
          <div className="flex items-center justify-between gap-3">
            <dt className="text-base text-muted-foreground">Net kâr marjı</dt>
            <dd className="text-base">
              {product.net_kar === null || product.net_kar_marji_yuzde === null ? (
                <span className="text-muted-foreground">Hesaplanamadı</span>
              ) : (
                <ProfitValue value={product.net_kar_marji_yuzde} kind="percent" hideIcon />
              )}
            </dd>
          </div>
        </dl>
        {comparison.compared_line_count > 0 ? (
          <p className="text-sm text-muted-foreground">
            Ekstresi gelen {comparison.compared_line_count} satırda tahmini giderler{' '}
            <Money value={comparison.estimated_total} />, kesin giderler{' '}
            <Money value={comparison.actual_total} /> (fark <Money value={comparison.difference} />
            ).
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

interface KalemRow {
  label: string;
  cell: ExpenseCell;
  source: ProfitLine['kaynaklar'][keyof ProfitLine['kaynaklar']];
}

function lineRows(line: ProfitLine): KalemRow[] {
  const items = line.kalemler;
  const src = line.kaynaklar;
  return [
    {
      label: 'Net satış',
      cell: expenseCell(items.net_satis_kdv_haric, src.satis),
      source: src.satis,
    },
    {
      label: 'Ürün maliyeti',
      cell: expenseCell(items.urun_maliyeti, src.urun_maliyeti),
      source: src.urun_maliyeti,
    },
    { label: 'Komisyon', cell: expenseCell(items.komisyon, src.komisyon), source: src.komisyon },
    {
      label: 'Kargo (gönderi)',
      cell: expenseCell(items.kargo_gonderi, src.kargo_gonderi),
      source: src.kargo_gonderi,
    },
    {
      label: 'Kargo (iade)',
      cell: expenseCell(items.kargo_iade, src.kargo_iade),
      source: src.kargo_iade,
    },
    {
      label: 'Platform hizmet bedeli',
      cell: expenseCell(items.platform_hizmet_bedeli, src.platform_hizmet_bedeli),
      source: src.platform_hizmet_bedeli,
    },
    { label: 'Ceza', cell: expenseCell(items.ceza, src.ceza), source: src.ceza },
    {
      label: 'Değişken giderler',
      cell: expenseCell(items.degisken_giderler, src.degisken_giderler),
      source: src.degisken_giderler,
    },
    { label: 'Reklam', cell: expenseCell(items.reklam, src.reklam), source: src.reklam },
  ];
}

function LineCard({ line }: { line: ProfitLine }) {
  const cancelled = line.durum === 'cancelled' || line.kesinlik === 'iptal';
  const certainty = certaintyBadge(line.kesinlik);
  const refund = refundPending(line);
  const net = netProfitDisplay(line.kalemler.net_kar, line.eksik_kalemler, line.kesinlik);

  return (
    <Card className="flex flex-col gap-4 p-4 sm:p-5">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold">
            Sipariş <span className="num break-all">{line.orderNumber}</span>
          </h3>
          {certainty ? <SpecBadge spec={certainty} /> : null}
          <Badge variant="neutral">{STATUS_LABELS[line.durum]}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          <span className="num">{line.adet}</span> adet
          {line.adet_iade > 0 ? (
            <>
              , <span className="num">{line.adet_iade}</span> adedi iade
            </>
          ) : null}
        </p>
      </header>

      {cancelled ? (
        <p className="text-base font-semibold text-muted-foreground">
          İptal: bu satır kâr hesabına girmez.
        </p>
      ) : (
        <>
          <p className="flex flex-wrap items-baseline gap-2 text-base">
            <span className="text-muted-foreground">Net kâr:</span>
            <NetProfitCell display={net} />
          </p>
          {net.kind === 'uncomputable' ? (
            <p className="text-sm text-muted-foreground">
              Eksik giderler hariç kâr: <Money value={line.kalemler.eksik_giderler_haric_kar} />
            </p>
          ) : null}

          {refund ? (
            <p role="note" className="rounded-md bg-warning-soft px-3 py-2 text-base text-warning">
              İade kaydı bekleniyor.
              {refund.estimate !== null ? (
                <>
                  {' '}
                  Ürün stoğa dönerse tahmini net kâr
                  {refund.excludesMissing ? ' (eksik giderler hariç)' : ''}:{' '}
                  <ProfitValue value={refund.estimate} className="text-base" />
                </>
              ) : null}{' '}
              <Badge variant="warning">Tahmini</Badge>
            </p>
          ) : null}

          <table className="w-full border-collapse text-left text-base">
            <caption className="sr-only">Sipariş {line.orderNumber} kalem kırılımı</caption>
            <thead>
              <tr className="border-b border-border text-sm text-muted-foreground">
                <th scope="col" className="py-2 pr-2 font-medium">
                  Kalem
                </th>
                <th scope="col" className="px-2 py-2 text-right font-medium">
                  Tutar (KDV hariç)
                </th>
                <th scope="col" className="py-2 pl-2 text-right font-medium">
                  Kaynak
                </th>
              </tr>
            </thead>
            <tbody>
              {lineRows(line).map((row) => (
                <tr key={row.label} className="border-b border-border last:border-b-0">
                  <th scope="row" className="py-2 pr-2 font-normal">
                    {row.label}
                  </th>
                  <td className="px-2 py-2 text-right">
                    {row.cell.kind === 'value' ? (
                      <Money value={row.cell.value} />
                    ) : (
                      <span className="font-semibold">Eksik</span>
                    )}
                  </td>
                  <td className="py-2 pl-2 text-right">
                    <SpecBadge spec={sourceBadge(row.source)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {line.uyarilar.length > 0 ? (
            <ul aria-label="Satır uyarıları" className="flex list-none flex-wrap gap-1.5">
              {line.uyarilar.map((code) => (
                <li key={code}>
                  <Badge variant="warning">{warningLabel(code)}</Badge>
                </li>
              ))}
            </ul>
          ) : null}

          {line.karsilastirma && line.uyarilar.includes('BEKLENMEYEN_KESINTI') ? (
            <ComparisonBlock line={line} />
          ) : null}
        </>
      )}
    </Card>
  );
}

function ComparisonBlock({ line }: { line: ProfitLine }) {
  const comparison = line.karsilastirma;
  if (!comparison) return null;
  const hint = defaultDesiHint(comparison);
  return (
    <section
      aria-label="Tahmini ve kesin karşılaştırması"
      className="flex flex-col gap-2 rounded-md border border-border p-3"
    >
      <h4 className="text-base font-semibold">Beklenmeyen kesinti: tahmini ve kesin</h4>
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="text-muted-foreground">
            <th scope="col" className="py-1 pr-2 font-medium">
              Kalem
            </th>
            <th scope="col" className="px-2 py-1 text-right font-medium">
              Tahmini
            </th>
            <th scope="col" className="py-1 pl-2 text-right font-medium">
              Kesin
            </th>
          </tr>
        </thead>
        <tbody>
          {comparisonRows(comparison).map((row) => (
            <tr key={row.label}>
              <th scope="row" className="py-1 pr-2 font-normal">
                {row.label}
              </th>
              <td className="px-2 py-1 text-right">
                {row.estimated === null ? '-' : <Money value={row.estimated} />}
              </td>
              <td className="py-1 pl-2 text-right">
                {row.actual === null ? '-' : <Money value={row.actual} />}
              </td>
            </tr>
          ))}
          <tr className="border-t border-border font-semibold">
            <th scope="row" className="py-1 pr-2">
              Toplam
            </th>
            <td className="px-2 py-1 text-right">
              <Money value={comparison.karsilastirilan_tahmini_toplam} />
            </td>
            <td className="py-1 pl-2 text-right">
              <Money value={comparison.karsilastirilan_kesin_toplam} />
            </td>
          </tr>
        </tbody>
      </table>
      <p className="text-sm">
        Fark: <Money value={comparison.fark} /> (eşik: <Money value={comparison.esik} />)
      </p>
      {hint ? <p className="text-sm text-muted-foreground">{hint}</p> : null}
    </section>
  );
}
