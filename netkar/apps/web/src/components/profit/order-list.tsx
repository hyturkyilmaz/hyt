'use client';

import { Receipt, SearchX, Store } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useId, useState, type FormEvent } from 'react';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import { LineCard } from '@/components/profit/product-detail';
import {
  FilterNav,
  LossAmount,
  Money,
  NetProfitCell,
  RangeSwitcher,
  ReportError,
  ReportFooter,
  ReportSkeleton,
  SpecBadge,
} from '@/components/profit/shared';
import { ProfitValue } from '@/components/profit-value';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  profitApi,
  type OrderDetail,
  type OrderListItem,
  type ReportPeriod,
} from '@/lib/api/profit';
import { formatCount } from '@/lib/format';
import { describeReportError } from '@/lib/profit/errors';
import {
  ORDER_EMPTY_TEXT,
  ORDER_SEARCH_EMPTY,
  orderBadges,
  orderNetView,
  orderProductTitle,
} from '@/lib/profit/orders';
import { periodLabel } from '@/lib/profit/present';
import {
  ORDER_FILTER_OPTIONS,
  ORDER_SEARCH_MAX,
  defaultOrderSortFor,
  isValidOrderSearch,
  orderQueryString,
  parseOrderQuery,
  type OrderQuery,
} from '@/lib/profit/query';
import { retryOnceOnRateLimit } from '@/lib/profit/rate-limit-retry';
import { useReportAccount } from '@/lib/profit/use-account';
import { usePagedList } from '@/lib/profit/use-paged-list';
import { useReportQuery } from '@/lib/profit/use-report-query';

/** Önbellek gelene dek (denetim SU-01) sayfa büyük tutulur: dönem başına motor çalışması azalır. */
const PAGE_SIZE = 100;

export function OrderListScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const query = parseOrderQuery(params);
  const { state: account, retry: retryAccount } = useReportAccount();
  const href = (next: Partial<OrderQuery>) => {
    const merged = { ...query, ...next };
    // Süzgeç değişince sıralama o süzgecin varsayılanına döner (zarar edenlerde en çok zarar önce).
    return `/panel/siparisler?${orderQueryString(
      next.filter !== undefined ? { ...merged, ...defaultOrderSortFor(next.filter) } : merged,
    )}`;
  };

  return (
    <>
      <PageHeader title="Siparişler" description="Sipariş bazında tahmini ve kesinleşmiş kâr." />
      <div className="flex flex-col gap-4">
        <RangeSwitcher range={query.range} hrefFor={(range) => href({ range })} />
        <FilterNav
          label="Sipariş süzgeci"
          options={ORDER_FILTER_OPTIONS}
          active={query.filter}
          hrefFor={(filter) => href({ filter })}
        />
        <OrderSearch
          key={query.q}
          value={query.q}
          rejected={query.qRejected}
          onSearch={(q) => router.replace(href({ q }), { scroll: false })}
        />
      </div>
      {account.status === 'loading' ? <ReportSkeleton rows={4} /> : null}
      {account.status === 'error' ? (
        <ReportError
          title="Siparişler yüklenemedi"
          message={describeReportError(account.error)}
          onRetry={retryAccount}
        />
      ) : null}
      {account.status === 'none' ? (
        <EmptyState
          Icon={Store}
          title="Mağaza bağlı değil"
          description="Trendyol mağazanızı bağladığınızda siparişleriniz burada görünür. Hakediş ekstresi geldikçe tahmini kâr kesinleşir."
          action={{ href: '/panel/ayarlar', label: 'Mağazayı bağla' }}
        />
      ) : null}
      {account.status === 'ready' ? (
        <OrderResults accountId={account.accountId} query={query} />
      ) : null}
    </>
  );
}

/**
 * Sipariş no ile TAM eşleşme araması (kısmi eşleşme yok). Girdi API'deki desenle doğrulanır; geçersizse istek
 * atılmaz ve neden satır içinde söylenir. Boş gönderim aramayı temizler.
 */
function OrderSearch({
  value,
  rejected,
  onSearch,
}: {
  value: string;
  /** Bağlantıdaki arama metni geçersizdi ve yok sayıldı */
  rejected: boolean;
  onSearch: (q: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const [invalid, setInvalid] = useState(false);
  const errorId = useId();
  const hintId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (text !== '' && !isValidOrderSearch(text)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    onSearch(text);
  };

  return (
    <form role="search" aria-label="Sipariş ara" onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor={`${hintId}-input`} className="text-sm font-medium">
        Sipariş no
      </label>
      <div className="flex flex-wrap gap-2">
        <Input
          id={`${hintId}-input`}
          type="search"
          name="q"
          value={draft}
          maxLength={ORDER_SEARCH_MAX}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          placeholder="Örn. 10004"
          aria-invalid={invalid ? true : undefined}
          aria-describedby={invalid ? `${errorId} ${hintId}` : hintId}
          onChange={(e) => setDraft(e.target.value)}
          className="min-w-0 flex-1 basis-48"
        />
        <Button type="submit">Ara</Button>
        {value ? (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setDraft('');
              setInvalid(false);
              onSearch('');
            }}
          >
            Aramayı temizle
          </Button>
        ) : null}
      </div>
      <p id={hintId} className="text-sm text-muted-foreground">
        Numara tam yazılmalıdır; kısmi eşleşme aranmaz.
      </p>
      {rejected && !invalid ? (
        <p role="status" className="text-base text-loss">
          Bağlantıdaki arama metni geçerli olmadığı için yok sayıldı; tüm siparişler gösteriliyor.
        </p>
      ) : null}
      {invalid ? (
        <p id={errorId} role="alert" className="text-base text-loss">
          Sipariş no harf ya da rakamla başlamalı; yalnız harf, rakam, nokta, tire ve alt çizgi
          içerebilir (en çok {ORDER_SEARCH_MAX} karakter).
        </p>
      ) : null}
    </form>
  );
}

function OrderResults({ accountId, query }: { accountId: string; query: OrderQuery }) {
  const key = `${accountId}|${orderQueryString(query)}`;
  const list = usePagedList({
    enabled: true,
    resetKey: key,
    fetchPage: (cursor, signal) =>
      retryOnceOnRateLimit(
        () =>
          profitApi.orders(
            accountId,
            {
              range: query.range,
              sort: query.sort,
              order: query.order,
              filter: query.filter,
              q: query.q,
              cursor,
              limit: PAGE_SIZE,
            },
            signal,
          ),
        signal,
      ),
    getItems: (page) => page.items,
  });

  if (list.status === 'loading') return <ReportSkeleton rows={4} />;
  if (list.status === 'error') {
    return (
      <ReportError
        title="Siparişler yüklenemedi"
        message={describeReportError(list.error)}
        onRetry={list.reload}
      />
    );
  }
  const first = list.first;
  const period = first?.period ?? null;
  const empty = query.q ? ORDER_SEARCH_EMPTY : ORDER_EMPTY_TEXT[query.filter];

  return (
    <>
      {list.restarted ? (
        <p
          role="status"
          className="rounded-md border border-border bg-info-soft px-4 py-3 text-base text-info"
        >
          Liste güncellendiği için baştan yüklendi.
        </p>
      ) : null}
      <div className="flex flex-col gap-1">
        <p className="text-sm text-muted-foreground" aria-live="polite">
          <span className="num">{formatCount(first?.total_count ?? 0)}</span> sipariş
          {query.q ? (
            <>
              , aranan: <span className="num break-all">{query.q}</span>
            </>
          ) : null}
          {period ? (
            <>
              , dönem: <span className="num">{periodLabel(period.start, period.end)}</span>
            </>
          ) : null}
        </p>
        <p className="text-sm text-muted-foreground">
          Tutarlar KDV hariçtir; dönem düzeyi giderler dahil değildir, bu yüzden toplamları Özet
          ekranındaki dönem rakamından farklı olabilir.
        </p>
      </div>
      {list.items.length === 0 ? (
        <EmptyState
          Icon={query.q ? SearchX : Receipt}
          title={empty.title}
          description={empty.description}
        />
      ) : (
        <ul role="list" aria-label="Sipariş listesi" className="flex list-none flex-col gap-3">
          {list.items.map((item) => (
            <li key={item.order_number}>
              <OrderCard item={item} accountId={accountId} period={period} />
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
            {list.loadingMore ? 'Yükleniyor' : 'Daha fazla yükle'}
          </Button>
        </div>
      ) : null}
      <ReportFooter revision={first?.settings_revision} />
    </>
  );
}

function NetCell({ item }: { item: OrderListItem }) {
  const view = orderNetView(item);
  switch (view.kind) {
    case 'cancelled':
      return <NetProfitCell display={{ kind: 'cancelled' }} />;
    case 'value':
      return <ProfitValue value={view.value} />;
    case 'loss':
      return (
        <>
          <LossAmount loss={view.loss} />
          <span className="block text-xs text-muted-foreground">Net kâr hesaplanamadı</span>
          {view.loss.note ? (
            <span className="block text-xs text-muted-foreground">{view.loss.note}</span>
          ) : null}
        </>
      );
    default:
      return (
        <>
          <NetProfitCell display={{ kind: 'uncomputable', missing: view.missing }} compact />
          {view.known !== null ? (
            <span className="block text-xs text-muted-foreground">
              Eksik giderler hariç kâr:{' '}
              <span className="num whitespace-nowrap">
                <Money value={view.known} />
              </span>
            </span>
          ) : null}
        </>
      );
  }
}

function OrderCard({
  item,
  accountId,
  period,
}: {
  item: OrderListItem;
  accountId: string;
  period: ReportPeriod | null;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const badges = orderBadges(item);
  const date = item.ordered_on ? periodLabel(item.ordered_on, item.ordered_on) : null;

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold">
          Sipariş <span className="num break-all">{item.order_number}</span>
        </h2>
        <p className="num text-sm text-muted-foreground">{date ?? 'Tarih yok'}</p>
      </div>
      {item.products.length > 0 ? (
        <ul
          role="list"
          aria-label="Siparişteki ürünler"
          className="flex list-none flex-col gap-0.5"
        >
          {item.products.map((product) => (
            <li key={product.barcode} className="break-words text-base">
              {orderProductTitle(product)}
            </li>
          ))}
          {item.more_product_count > 0 ? (
            <li className="text-sm text-muted-foreground">
              <span className="num">{formatCount(item.more_product_count)}</span> ürün daha
            </li>
          ) : null}
        </ul>
      ) : null}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-base">
        <div>
          <dt className="text-sm text-muted-foreground">Net kâr</dt>
          <dd>
            <NetCell item={item} />
          </dd>
        </div>
        {item.net_sales_excl_vat !== null ? (
          <div>
            <dt className="text-sm text-muted-foreground">Net satış</dt>
            <dd>
              <Money value={item.net_sales_excl_vat} />
            </dd>
          </div>
        ) : null}
      </dl>
      {item.cancelled ? (
        <p className="text-sm text-muted-foreground">Siparişin tüm satırları iptal edildi.</p>
      ) : item.cancelled_line_count > 0 ? (
        <p className="text-sm text-muted-foreground">
          <span className="num">{item.cancelled_line_count}</span> satır iptal; tutarlar yalnız
          aktif satırlardır.
        </p>
      ) : null}
      {badges.length > 0 ? (
        <ul role="list" aria-label="Sipariş durumu" className="flex list-none flex-wrap gap-1.5">
          {badges.map((badge) => (
            <li key={badge.label}>
              <SpecBadge spec={badge} />
            </li>
          ))}
        </ul>
      ) : null}
      <Button
        variant="secondary"
        className="w-full sm:w-auto sm:self-start"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? 'Kalem dökümünü gizle' : 'Kalem dökümünü göster'}
        <span className="sr-only"> (sipariş {item.order_number})</span>
      </Button>
      <div id={panelId} hidden={!open}>
        {open ? (
          <OrderLines accountId={accountId} orderNumber={item.order_number} period={period} />
        ) : null}
      </div>
    </Card>
  );
}

/**
 * Kalem dökümü: sipariş ucu, listedeki dönemle (start/end) çağrılır; böylece ortak giderlerin dağıtımı
 * listedeki tutarla aynı olur (denetim SU-02). Satır kartları ürün kırılımındaki bileşendir.
 */
function OrderLines({
  accountId,
  orderNumber,
  period,
}: {
  accountId: string;
  orderNumber: string;
  period: ReportPeriod | null;
}) {
  const start = period?.start;
  const end = period?.end;
  const { state, retry } = useReportQuery<OrderDetail>(
    start !== undefined && end !== undefined,
    `${accountId}|${orderNumber}|${start}|${end}`,
    (signal) =>
      retryOnceOnRateLimit(
        () =>
          profitApi.orderDetail(
            accountId,
            orderNumber,
            { start: start ?? '', end: end ?? '' },
            signal,
          ),
        signal,
      ),
  );

  if (state.status === 'loading' || state.status === 'idle') {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        Kalem dökümü yükleniyor
      </p>
    );
  }
  if (state.status === 'error') {
    return (
      <div className="flex flex-col items-start gap-3" role="alert">
        <p className="text-base text-muted-foreground">{describeReportError(state.error)}</p>
        <Button variant="secondary" onClick={retry}>
          Tekrar dene
        </Button>
      </div>
    );
  }
  const lines = state.data.lines;
  if (lines.length === 0) {
    return <p className="text-base">Bu siparişin satırı bulunamadı.</p>;
  }
  return (
    <ul
      role="list"
      aria-label={`Sipariş ${orderNumber} satırları`}
      className="flex list-none flex-col gap-3"
    >
      {lines.map((line) => (
        <li key={`${line.orderNumber}-${line.lineId}`}>
          <LineCard line={line} by="product" />
        </li>
      ))}
    </ul>
  );
}
