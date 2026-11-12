'use client';

import { Package, Store } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
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
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ProfitValue } from '@/components/profit-value';
import { profitApi, type ProductProfitItem, type RangeName } from '@/lib/api/profit';
import { describeReportError } from '@/lib/profit/errors';
import {
  certaintyBadge,
  lossBadge,
  lossDisplay,
  netProfitDisplay,
  periodLabel,
  shownAsCancelled,
} from '@/lib/profit/present';
import {
  FILTER_OPTIONS,
  defaultOrderFor,
  SORT_OPTIONS,
  parseProductQuery,
  productQueryString,
  type ProductQuery,
} from '@/lib/profit/query';
import { useReportAccount } from '@/lib/profit/use-account';
import { usePagedList } from '@/lib/profit/use-paged-list';
import { formatTRY } from '@/lib/format';

const PAGE_SIZE = 50;

const EMPTY_TEXT: Record<ProductQuery['filter'], { title: string; description: string }> = {
  all: {
    title: 'Bu dönemde satılan ürün yok',
    description: 'Başka bir dönem seçebilirsiniz. Siparişler geldikçe ürünler burada listelenir.',
  },
  loss: {
    title: 'Zarar eden ürün yok',
    description: 'Bu dönemde zararı kesin olan bir ürün bulunmadı.',
  },
  missing_cost: {
    title: 'Maliyeti eksik ürün yok',
    description: 'Bu dönemde satılan tüm ürünlerin maliyeti girilmiş.',
  },
};

export function ProductListScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const query = parseProductQuery(params);
  const { state: account, retry: retryAccount } = useReportAccount();
  const href = (next: Partial<ProductQuery>) =>
    `/panel/urunler?${productQueryString({ ...query, ...next })}`;

  return (
    <>
      <PageHeader
        title="Ürünler"
        description="Her ürünün komisyon, kargo, iade ve reklam sonrası net kârı."
      />
      <div className="flex flex-col gap-4">
        <RangeSwitcher range={query.range} hrefFor={(range) => href({ range })} />
        <FilterNav
          label="Ürün süzgeci"
          options={FILTER_OPTIONS}
          active={query.filter}
          hrefFor={(filter) => href({ filter, order: defaultOrderFor(filter) })}
        />
        <SortControls
          sort={query.sort}
          order={query.order}
          onChange={(next) => router.replace(href(next), { scroll: false })}
        />
      </div>
      {account.status === 'loading' ? <ReportSkeleton rows={4} /> : null}
      {account.status === 'error' ? (
        <ReportError message={describeReportError(account.error)} onRetry={retryAccount} />
      ) : null}
      {account.status === 'none' ? (
        <EmptyState
          Icon={Store}
          title="Henüz ürün yok"
          description="Trendyol mağazanızı bağladığınızda ürünleriniz burada listelenir. Zarar ettirenleri tek dokunuşla süzebilirsiniz."
          action={{ href: '/panel/ayarlar', label: 'Mağazayı bağla' }}
        />
      ) : null}
      {account.status === 'ready' ? (
        <ProductResults accountId={account.accountId} query={query} />
      ) : null}
    </>
  );
}

const SELECT_CLASS =
  'min-h-touch rounded-md border border-input-border bg-surface px-3 text-base text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function SortControls({
  sort,
  order,
  onChange,
}: {
  sort: ProductQuery['sort'];
  order: ProductQuery['order'];
  onChange: (next: Partial<ProductQuery>) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-sm font-medium">
        Sırala
        <select
          className={SELECT_CLASS}
          value={sort}
          onChange={(e) => onChange({ sort: e.target.value as ProductQuery['sort'] })}
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium">
        Yön
        <select
          className={SELECT_CLASS}
          value={order}
          onChange={(e) => onChange({ order: e.target.value === 'asc' ? 'asc' : 'desc' })}
        >
          <option value="desc">Çoktan aza</option>
          <option value="asc">Azdan çoğa</option>
        </select>
      </label>
    </div>
  );
}

function ProductResults({ accountId, query }: { accountId: string; query: ProductQuery }) {
  const key = `${accountId}|${productQueryString(query)}`;
  const list = usePagedList({
    enabled: true,
    resetKey: key,
    fetchPage: (cursor, signal) =>
      profitApi.products(accountId, { ...query, cursor, limit: PAGE_SIZE }, signal),
    getItems: (page) => page.items,
  });

  if (list.status === 'loading') return <ReportSkeleton rows={5} />;
  if (list.status === 'error') {
    return <ReportError message={describeReportError(list.error)} onRetry={list.reload} />;
  }
  const first = list.first;
  const period = first ? periodLabel(first.period.start, first.period.end) : '';

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
      <p className="text-sm text-muted-foreground" aria-live="polite">
        <span className="num">{first?.total_count ?? 0}</span> ürün, dönem:{' '}
        <span className="num">{period}</span>
      </p>
      {list.items.length === 0 ? (
        <EmptyState
          Icon={Package}
          title={EMPTY_TEXT[query.filter].title}
          description={EMPTY_TEXT[query.filter].description}
        />
      ) : (
        <>
          <ProductCards items={list.items} range={query.range} />
          <ProductTable items={list.items} range={query.range} />
        </>
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

function detailHref(item: ProductProfitItem, range: RangeName): string {
  return `/panel/urunler/${encodeURIComponent(item.barcode)}?range=${range}`;
}

/** Ürün başlığı metin düğümü olarak basılır (HTML yorumlanmaz, denetim B-04). */
function productTitle(item: ProductProfitItem): string {
  return item.title && item.title.trim() ? item.title : 'Başlıksız ürün';
}

/** Y-3: "İptal" yalnız iptal satırlı ve zararsız ürün; satışsız reklam yüzünden zarardaki ürün iptal sayılmaz. */
function isCancelled(item: ProductProfitItem): boolean {
  return shownAsCancelled(item.certainty, item.net_profit, item.loss_reason);
}

function netDisplay(item: ProductProfitItem) {
  return netProfitDisplay(item.net_profit, item.missing_items, item.certainty, item.loss_reason);
}

function MarginCell({ item }: { item: ProductProfitItem }) {
  if (isCancelled(item)) return <span className="text-muted-foreground">-</span>;
  if (item.net_profit === null) {
    return <span className="text-sm text-muted-foreground">Hesaplanamadı</span>;
  }
  if (item.net_margin_percent === null) return <span className="text-muted-foreground">-</span>;
  return <ProfitValue value={item.net_margin_percent} kind="percent" hideIcon />;
}

/** Kural 1: net kâr null iken eksik giderler hariç kâr yalnız etiketli ve ayrı satırda görünür. */
function KnownExpensesNote({ item }: { item: ProductProfitItem }) {
  if (item.net_profit !== null || isCancelled(item)) return null;
  return (
    <span className="block text-xs text-muted-foreground">
      Eksik giderler hariç kâr:{' '}
      <span className="num whitespace-nowrap">{formatTRY(item.contribution_excl_missing)}</span>
    </span>
  );
}

/**
 * Net kâr hücresi. Kesin zarardaki ama net kârı null olan ürün nötr görünmez: kırmızı "En az ₺X zarar", küçük
 * "Net kâr hesaplanamadı" satırı ve eksik kalemler düşülünce rakamın azalacağı notu (UX-07, Y-5); ürün
 * kırılımındaki bilinen kâr bloğuyla aynı dil. Diğer null değerler "Hesaplanamadı" + eksik kalem adları.
 */
function NetCell({ item }: { item: ProductProfitItem }) {
  const loss = lossDisplay(item);
  if (item.net_profit === null && loss) {
    return (
      <>
        <LossAmount loss={loss} />
        <span className="block text-xs text-muted-foreground">Net kâr hesaplanamadı</span>
        {loss.note ? (
          <span className="block text-xs text-muted-foreground">{loss.note}</span>
        ) : null}
      </>
    );
  }
  return (
    <>
      <NetProfitCell display={netDisplay(item)} compact />
      <KnownExpensesNote item={item} />
    </>
  );
}

/**
 * Rozetler: zarar nedeni, sonra kesinlik. Eksik bilgi "Eksik: kargo, hizmet bedeli" satırında zaten adıyla
 * yazıldığından ayrıca "Kargo eksik" ve "Bilgi eksik" rozeti basılmaz (UX-10, tek kaynak).
 */
function ItemBadges({ item }: { item: ProductProfitItem }) {
  const loss = lossBadge(item);
  const certainty = item.certainty === 'eksik' ? null : certaintyBadge(item.certainty);
  if (!loss && !certainty) return null;
  return (
    <span className="flex flex-wrap gap-1.5">
      {loss ? <SpecBadge spec={loss} /> : null}
      {certainty ? <SpecBadge spec={certainty} /> : null}
    </span>
  );
}

function ProductCards({ items, range }: { items: ProductProfitItem[]; range: RangeName }) {
  return (
    <ul aria-label="Ürün listesi" className="flex list-none flex-col gap-3 lg:hidden">
      {items.map((item) => (
        <li key={item.barcode}>
          <Card className="relative flex flex-col gap-3 p-4">
            <div className="flex flex-col gap-1">
              <Link
                href={detailHref(item, range)}
                className="break-words text-lg font-semibold text-primary after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {productTitle(item)}
              </Link>
              <span className="num break-all text-sm text-muted-foreground">
                Barkod: {item.barcode}
              </span>
            </div>
            <ItemBadges item={item} />
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-base">
              <div>
                <dt className="text-sm text-muted-foreground">Net kâr</dt>
                <dd>
                  <NetCell item={item} />
                </dd>
              </div>
              <div>
                <dt className="text-sm text-muted-foreground">Marj</dt>
                <dd>
                  <MarginCell item={item} />
                </dd>
              </div>
              <div>
                <dt className="text-sm text-muted-foreground">Net satış</dt>
                <dd>
                  <Money value={item.net_sales_excl_vat} />
                </dd>
              </div>
              <div>
                <dt className="text-sm text-muted-foreground">Adet</dt>
                <dd className="num">{item.quantity}</dd>
              </div>
            </dl>
          </Card>
        </li>
      ))}
    </ul>
  );
}

function ProductTable({ items, range }: { items: ProductProfitItem[]; range: RangeName }) {
  return (
    <Card className="hidden overflow-x-auto lg:block">
      <table className="w-full border-collapse text-left text-base">
        <caption className="sr-only">Ürün kârlılık tablosu</caption>
        <thead>
          <tr className="border-b border-border text-sm text-muted-foreground">
            <th scope="col" className="px-4 py-3 font-medium">
              Ürün
            </th>
            <th scope="col" className="px-4 py-3 text-right font-medium">
              Adet
            </th>
            <th scope="col" className="px-4 py-3 text-right font-medium">
              Net satış
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Net kâr
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Marj
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Durum
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.barcode}
              className="relative border-b border-border last:border-b-0 hover:bg-surface-muted"
            >
              <td className="max-w-xs px-4 py-3 align-top">
                <Link
                  href={detailHref(item, range)}
                  className="break-words font-semibold text-primary after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {productTitle(item)}
                </Link>
                <span className="num block break-all text-sm text-muted-foreground">
                  Barkod: {item.barcode}
                </span>
              </td>
              <td className="num px-4 py-3 text-right align-top">{item.quantity}</td>
              <td className="px-4 py-3 text-right align-top">
                <Money value={item.net_sales_excl_vat} />
              </td>
              <td className="px-4 py-3 align-top">
                <NetCell item={item} />
              </td>
              <td className="px-4 py-3 align-top">
                <MarginCell item={item} />
              </td>
              <td className="px-4 py-3 align-top">
                <ItemBadges item={item} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
