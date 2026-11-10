'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { isCursorInvalid } from '@/lib/profit/errors';

interface Page {
  next_cursor: string | null;
}

export interface PagedListState<TPage extends Page, TItem> {
  status: 'loading' | 'ready' | 'error';
  /** İlk sayfa (üst düzey alanlar için: toplam sayı, ürün toplamı vb.) */
  first: TPage | null;
  items: TItem[];
  hasMore: boolean;
  loadingMore: boolean;
  /** Daha fazla yüklerken oluşan (cursor_invalid dışı) hata */
  moreError: unknown;
  /** Hata, ilk sayfa yüklenemediyse */
  error: unknown;
  /** İmleç geçersiz olduğu için liste baştan yüklendi */
  restarted: boolean;
  loadMore: () => void;
  reload: () => void;
}

interface Options<TPage extends Page, TItem> {
  enabled: boolean;
  /** Sorgu anahtarı: değişince liste baştan yüklenir */
  resetKey: string;
  fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<TPage>;
  getItems: (page: TPage) => TItem[];
}

interface Core<TPage, TItem> {
  status: 'loading' | 'ready' | 'error';
  first: TPage | null;
  items: TItem[];
  nextCursor: string | null;
  error: unknown;
}

/**
 * Keyset imleçli liste: ilk sayfa + "daha fazla yükle". Daha fazla yüklerken 422 `cursor_invalid` gelirse
 * (imleç eskidi ya da bozuk) liste baştan yüklenir ve `restarted` işaretlenir; başka hatalar satır içi kalır.
 */
export function usePagedList<TPage extends Page, TItem>(
  options: Options<TPage, TItem>,
): PagedListState<TPage, TItem> {
  const { enabled, resetKey } = options;
  const [core, setCore] = useState<Core<TPage, TItem>>({
    status: 'loading',
    first: null,
    items: [],
    nextCursor: null,
    error: null,
  });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<unknown>(null);
  const [restarted, setRestarted] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // En güncel işlevler ve geçerli yükleme kuşağı (eski yanıtlar yok sayılır).
  const latest = useRef(options);
  const generation = useRef(0);
  const cursorRef = useRef<string | null>(null);
  const busyRef = useRef(false);
  useEffect(() => {
    latest.current = options;
  });

  // Sorgu değişince bildirim sıfırlanır; elle yenilemede ve cursor_invalid yeniden başlatmasında korunur.
  const lastKey = useRef(resetKey);
  useEffect(() => {
    if (lastKey.current !== resetKey) {
      lastKey.current = resetKey;
      setRestarted(false);
    }
  }, [resetKey]);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const mine = ++generation.current;
    cursorRef.current = null;
    busyRef.current = false;
    setLoadingMore(false);
    setMoreError(null);
    setCore({ status: 'loading', first: null, items: [], nextCursor: null, error: null });
    latest.current
      .fetchPage(null, controller.signal)
      .then((page) => {
        if (generation.current !== mine) return;
        cursorRef.current = page.next_cursor;
        setCore({
          status: 'ready',
          first: page,
          items: latest.current.getItems(page),
          nextCursor: page.next_cursor,
          error: null,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || generation.current !== mine) return;
        setCore({ status: 'error', first: null, items: [], nextCursor: null, error });
      });
    return () => controller.abort();
  }, [enabled, resetKey, attempt]);

  const loadMore = useCallback(() => {
    const cursor = cursorRef.current;
    if (cursor === null || busyRef.current) return;
    busyRef.current = true;
    const mine = generation.current;
    setLoadingMore(true);
    setMoreError(null);
    latest.current
      .fetchPage(cursor, new AbortController().signal)
      .then((page) => {
        if (generation.current !== mine) return;
        cursorRef.current = page.next_cursor;
        setCore((prev) => ({
          ...prev,
          items: [...prev.items, ...latest.current.getItems(page)],
          nextCursor: page.next_cursor,
        }));
      })
      .catch((error: unknown) => {
        if (generation.current !== mine) return;
        if (isCursorInvalid(error)) {
          // İmleç eskidi: listeyi baştan yükle ve kullanıcıya haber ver.
          setRestarted(true);
          setAttempt((n) => n + 1);
          return;
        }
        setMoreError(error);
      })
      .finally(() => {
        if (generation.current !== mine) return;
        busyRef.current = false;
        setLoadingMore(false);
      });
  }, []);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return {
    status: core.status,
    first: core.first,
    items: core.items,
    hasMore: core.nextCursor !== null,
    loadingMore,
    moreError,
    error: core.error,
    restarted,
    loadMore,
    reload,
  };
}
