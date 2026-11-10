'use client';

import { useCallback, useEffect, useState } from 'react';

import { profitApi } from '@/lib/api/profit';

export type AccountState =
  | { status: 'loading' }
  | { status: 'none' }
  | { status: 'error'; error: unknown }
  | { status: 'ready'; accountId: string };

/**
 * Rapor için kullanılacak pazaryeri hesabı: kiracının ilk AKTİF Trendyol bağlantısı.
 * Aktif bağlantı yoksa "none" (mağaza bağlı değil) döner.
 */
export function useReportAccount(): { state: AccountState; retry: () => void } {
  const [state, setState] = useState<AccountState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    profitApi
      .accounts(controller.signal)
      .then((accounts) => {
        const active = accounts.find((a) => a.status === 'active');
        setState(active ? { status: 'ready', accountId: active.id } : { status: 'none' });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: 'error', error });
      });
    return () => controller.abort();
  }, [attempt]);

  const retry = useCallback(() => {
    setState({ status: 'loading' });
    setAttempt((n) => n + 1);
  }, []);

  return { state, retry };
}
