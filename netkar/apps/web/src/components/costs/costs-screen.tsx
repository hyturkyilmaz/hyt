'use client';

import { CheckCircle2, Package, Search, Store } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';

import { CostFormDialog, productLabel } from '@/components/costs/cost-form-dialog';
import { CostImportPanel } from '@/components/costs/cost-import-panel';
import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import { FilterNav, ReportError, ReportSkeleton } from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  MAX_SEARCH_LENGTH,
  PRODUCTS_PAGE_SIZE,
  productCostsApi,
  type CostOut,
  type CostUpsertResult,
  isSupportedBarcode,
  type ProductCostItem,
} from '@/lib/api/product-costs';
import { costSince, costSummary, describeCostLoadError } from '@/lib/profit/cost-present';
import { costsHref, parseCostQuery, type CostQuery } from '@/lib/profit/cost-query';
import { formatLongDate, todayIstanbul } from '@/lib/profit/settings-input';
import { useReportAccount } from '@/lib/profit/use-account';
import { usePagedList } from '@/lib/profit/use-paged-list';
import { useWriteAccess } from '@/lib/profit/use-viewer';

const FILTER_OPTIONS = [
  { value: 'all', label: 'Tüm ürünler' },
  { value: 'missing', label: 'Maliyeti eksik' },
] as const;

/**
 * Kayıt sonrası listedeki satırın yeni hâli: bugün geçerli maliyet, geçerlilik tarihi bugünden büyük olmayan en yeni
 * kayıttır (sunucudaki kural). Yeni kayıt bugünden ilerideyse ya da mevcut kayıttan eskiyse bugünkü maliyet değişmez.
 */
export function applySavedCost(
  item: ProductCostItem,
  saved: CostOut,
  today: string,
): ProductCostItem {
  const current = item.current_cost;
  const takesOver =
    saved.valid_from <= today && (current === null || saved.valid_from >= current.valid_from);
  if (!takesOver) return item;
  return { ...item, current_cost: saved, cost_missing: false };
}

export function savedMessage(
  item: ProductCostItem,
  result: CostUpsertResult,
  today: string,
): string {
  const name = productLabel(item);
  const verb = result.created ? 'eklendi' : 'güncellendi';
  const base = `${name}: maliyet ${verb}. Kâr rakamları güncellenir.`;
  if (result.cost.valid_from > today) {
    return `${name}: maliyet ${verb}; ${formatLongDate(result.cost.valid_from)} tarihinden itibaren kullanılır, bugünkü maliyet değişmedi.`;
  }
  const after = applySavedCost(item, result.cost, today);
  if (after === item) {
    return `${name}: maliyet ${verb}; daha yeni bir kayıt geçerli olduğu için bugünkü maliyet değişmedi.`;
  }
  return base;
}

export function CostsScreen() {
  const params = useSearchParams();
  const query = parseCostQuery(params);
  const { state: account, retry } = useReportAccount();
  const { access } = useWriteAccess();
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <>
      <PageHeader
        title="Ürün maliyetleri"
        description="Net kâr için her ürünün KDV hariç birim maliyetini girin. Trendyol bu bilgiyi tutmaz."
      />
      {account.status === 'loading' ? <ReportSkeleton rows={3} /> : null}
      {account.status === 'error' ? (
        <ReportError
          title="Mağaza bilgisi alınamadı"
          message={describeCostLoadError(account.error)}
          onRetry={retry}
        />
      ) : null}
      {account.status === 'none' ? (
        <EmptyState
          Icon={Store}
          title="Önce mağazanızı bağlayın"
          description="Ürünleriniz mağaza bağlandıktan sonra senkronlanır ve maliyetlerini buradan girersiniz."
          action={{ href: '/panel/ayarlar', label: 'Mağazayı bağla' }}
        />
      ) : null}
      {account.status === 'ready' ? (
        <>
          {access === 'viewer' ? (
            <p role="note" className="rounded-lg bg-info-soft p-3 text-sm font-medium text-info">
              Görüntüleyici hesabı maliyetleri yalnız okuyabilir. Girmek için sahip ya da yönetici
              olmanız gerekir.
            </p>
          ) : null}
          {access === 'unknown' ? (
            <p
              role="note"
              className="rounded-lg bg-warning-soft p-3 text-sm font-medium text-warning"
            >
              Yetkiniz doğrulanamadı, bu yüzden maliyet girişi gizlendi. Sayfayı yenileyip tekrar
              deneyin.
            </p>
          ) : null}
          {access === 'editor' || access === 'loading' ? (
            <CostImportPanel
              accountId={account.accountId}
              onImported={() => setReloadKey((n) => n + 1)}
              disabled={access === 'loading'}
            />
          ) : null}
          <ProductCosts
            accountId={account.accountId}
            query={query}
            canEdit={access === 'editor'}
            pending={access === 'loading'}
            reloadKey={reloadKey}
          />
        </>
      ) : null}
    </>
  );
}

function SearchForm({ query }: { query: CostQuery }) {
  const router = useRouter();
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get('q');
    const q = typeof value === 'string' ? value.trim() : '';
    router.replace(costsHref({ ...query, q }), { scroll: false });
  }
  return (
    // key: adres çubuğundan q değişince alan yeniden başlar
    <form
      key={query.q}
      role="search"
      aria-label="Ürün ara"
      onSubmit={submit}
      className="flex gap-2"
    >
      <label className="sr-only" htmlFor="maliyet-ara">
        Barkod ya da ürün adı ara
      </label>
      <Input
        id="maliyet-ara"
        name="q"
        type="search"
        defaultValue={query.q}
        maxLength={MAX_SEARCH_LENGTH}
        placeholder="Barkod ya da ürün adı"
        autoComplete="off"
      />
      <Button type="submit" variant="secondary">
        <Search aria-hidden="true" />
        Ara
      </Button>
    </form>
  );
}

function ProductCosts({
  accountId,
  query,
  canEdit,
  pending,
  reloadKey,
}: {
  accountId: string;
  query: CostQuery;
  canEdit: boolean;
  /** Rol yükleniyor: yazma düğmeleri devre dışı görünür */
  pending: boolean;
  reloadKey: number;
}) {
  // Her çizimde hesaplanır (ucuz): gece yarısını geçen oturumda form ve satır kuralı eski günü kullanmaz (ME-11)
  const today = todayIstanbul();
  const listKey = `${accountId}|${query.q}|${query.missingOnly}|${reloadKey}`;
  const list = usePagedList({
    enabled: true,
    resetKey: listKey,
    fetchPage: (cursor, signal) =>
      productCostsApi.products(
        accountId,
        {
          q: query.q || undefined,
          cursor,
          limit: PRODUCTS_PAGE_SIZE,
          // "Maliyeti eksik" süzgeci sunucuda (missing=true): sayfalama süzülmüş liste üzerinden işler
          missing: query.missingOnly,
        },
        signal,
      ),
    getItems: (page) => page.items,
  });
  // Kayıt sonrası satırların yeni hâli; liste yeniden yüklenince (sorgu, içe aktarma) sıfırlanır.
  const [saved, setSaved] = useState<{ key: string; items: Record<string, ProductCostItem> }>({
    key: listKey,
    items: {},
  });
  const overrides = useMemo(() => (saved.key === listKey ? saved.items : {}), [saved, listKey]);
  const [editing, setEditing] = useState<ProductCostItem | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // Kayıt iletisi zamanlayıcısı: bileşen kaldırılınca ya da yeni kayıtta temizlenir (kaldırılmış
  // bileşende durum güncellemesi ve test ortamı kapandıktan sonra çalışan zamanlayıcı olmasın).
  const messageTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (messageTimer.current !== null) clearTimeout(messageTimer.current);
    },
    [],
  );

  // Sunucu süzgeci uygular; kaydedilen satır oturum boyunca yerinde kalır (hızlı giriş).
  const rows = useMemo(
    () => list.items.map((item) => overrides[item.barcode] ?? item),
    [list.items, overrides],
  );

  // `total_missing` ilk sayfa yanıtındaki hesap geneli sayıdır; bu oturumda maliyeti girilen eksik ürünler düşülür.
  const totalMissing = useMemo(() => {
    if (!list.first) return null;
    const fixed = list.items.filter(
      (item) => item.cost_missing && overrides[item.barcode]?.cost_missing === false,
    ).length;
    return Math.max(0, list.first.total_missing - fixed);
  }, [list.first, list.items, overrides]);

  const onSaved = useCallback(
    (item: ProductCostItem, result: CostUpsertResult) => {
      setSaved((prev) => ({
        key: listKey,
        items: {
          ...(prev.key === listKey ? prev.items : {}),
          [item.barcode]: applySavedCost(overrides[item.barcode] ?? item, result.cost, today),
        },
      }));
      // Aynı iletinin art arda gelmesi de duyurulsun: bölge önce boşalır, sonra yazılır (ME-06)
      const text = savedMessage(overrides[item.barcode] ?? item, result, today);
      setMessage(null);
      if (messageTimer.current !== null) clearTimeout(messageTimer.current);
      messageTimer.current = setTimeout(() => {
        messageTimer.current = null;
        setMessage(text);
      }, 80);
      setEditing(null);
    },
    [listKey, overrides, today],
  );

  return (
    <>
      <div className="flex flex-col gap-4">
        <SearchForm query={query} />
        <FilterNav
          label="Ürün süzgeci"
          options={FILTER_OPTIONS}
          active={query.missingOnly ? 'missing' : 'all'}
          hrefFor={(value) => costsHref({ q: query.q, missingOnly: value === 'missing' })}
        />
      </div>
      {/* Canlı bölge baştan DOM'da ve görünür; metin sonradan yazılır (ME-06). Boşken boşluk bırakmaz. */}
      <div role="status" className={message ? undefined : '-mb-4'}>
        {message ? (
          <p className="flex items-start gap-2 rounded-lg bg-profit-soft p-3 text-sm font-medium text-profit">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>{message}</span>
          </p>
        ) : null}
      </div>
      {list.status === 'loading' ? <ReportSkeleton rows={4} /> : null}
      {list.status === 'error' ? (
        <ReportError
          title="Ürünler yüklenemedi"
          message={describeCostLoadError(list.error)}
          onRetry={list.reload}
        />
      ) : null}
      {list.status === 'ready' ? (
        <>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            <span className="num">{rows.length}</span> ürün gösteriliyor
            {query.missingOnly ? ' (maliyeti eksik)' : ''}
            {list.hasMore ? ', devamı var' : ''}.
          </p>
          {totalMissing !== null && totalMissing > 0 ? (
            <p
              className="text-sm text-muted-foreground"
              aria-live="polite"
              data-testid="total-missing"
            >
              Toplam <span className="num">{totalMissing}</span> ürünün maliyeti eksik.
            </p>
          ) : null}
          {rows.length === 0 ? (
            <EmptyState
              Icon={Package}
              title={emptyTitle(query)}
              description={emptyDescription(query)}
            />
          ) : (
            <ul
              role="list"
              aria-label="Ürün maliyetleri"
              className="flex list-none flex-col gap-3 p-0"
            >
              {rows.map((item) => (
                <li key={item.barcode}>
                  <ProductRow
                    item={item}
                    canEdit={canEdit}
                    pending={pending}
                    onEdit={() => setEditing(item)}
                  />
                </li>
              ))}
            </ul>
          )}
          {list.moreError ? (
            <p role="alert" className="text-base text-loss">
              {describeCostLoadError(list.moreError)}
            </p>
          ) : null}
          {list.hasMore ? (
            <div className="flex justify-center">
              <Button variant="secondary" onClick={list.loadMore} disabled={list.loadingMore}>
                {list.loadingMore ? 'Yükleniyor' : 'Daha fazla yükle'}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
      {editing ? (
        <CostFormDialog
          accountId={accountId}
          item={overrides[editing.barcode] ?? editing}
          today={today}
          onSaved={(result) => onSaved(editing, result)}
          onClose={() => setEditing(null)}
        />
      ) : null}
      <p className="text-sm text-muted-foreground">
        Maliyetler silinmez: değişiklik yeni sürüm olarak eklenir ve sipariş gününde geçerli maliyet
        kullanılır.{' '}
        <Link href="/panel/urunler" className="text-primary underline underline-offset-4">
          Ürün kârlılığına git
        </Link>
      </p>
    </>
  );
}

function emptyTitle(query: CostQuery): string {
  if (query.q) return 'Aramanızla eşleşen ürün yok';
  if (query.missingOnly) return 'Maliyeti eksik ürün yok';
  return 'Henüz ürün yok';
}

function emptyDescription(query: CostQuery): string {
  if (query.q) return 'Barkod ya da ürün adını kontrol edip yeniden arayın.';
  if (query.missingOnly) return 'Tüm ürünlerin maliyeti girilmiş.';
  return 'Ürünler mağazanızdan senkronlanınca burada listelenir.';
}

function ProductRow({
  item,
  canEdit,
  pending,
  onEdit,
}: {
  item: ProductCostItem;
  canEdit: boolean;
  pending: boolean;
  onEdit: () => void;
}) {
  const cost = item.current_cost;
  return (
    <Card className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex min-w-0 flex-col gap-1 lg:flex-1">
        <span className="break-words text-lg font-semibold">{productLabel(item)}</span>
        <span className="num break-all text-sm text-muted-foreground">Barkod: {item.barcode}</span>
        {item.stock_code ? (
          <span className="num break-all text-sm text-muted-foreground">
            Stok kodu: {item.stock_code}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-1 lg:w-72">
        {cost ? (
          <>
            <span className="num text-base font-medium">{costSummary(cost)}</span>
            <span className="text-sm text-muted-foreground">{costSince(cost)}</span>
          </>
        ) : (
          <span>
            <Badge variant="warning">Maliyet yok</Badge>
            <span className="mt-1 block text-sm text-muted-foreground">Net kâr hesaplanamaz.</span>
          </span>
        )}
      </div>
      {!isSupportedBarcode(item.barcode) && (canEdit || pending) ? (
        <p className="text-sm text-muted-foreground lg:w-64">
          Bu barkod biçimi maliyet girişinde desteklenmiyor (yalnız harf, rakam, nokta, alt çizgi ve
          tire; harf ya da rakamla başlamalı). Barkodu Trendyol panelinden düzeltin ya da destekle
          iletişime geçin.
        </p>
      ) : canEdit || pending ? (
        <Button variant={cost ? 'secondary' : 'default'} onClick={onEdit} disabled={pending}>
          {cost ? 'Düzenle' : 'Maliyet gir'}
          <span className="sr-only">: {productLabel(item)}</span>
        </Button>
      ) : null}
    </Card>
  );
}
