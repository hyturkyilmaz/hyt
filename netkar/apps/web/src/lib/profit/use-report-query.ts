'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type QueryState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; error: unknown };

/** Tek seferlik rapor sorgusu: `key` değişince yeniden çeker, eski yanıtı iptal eder, `retry` verir. */
export function useReportQuery<T>(
  enabled: boolean,
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
): { state: QueryState<T>; retry: () => void } {
  const [state, setState] = useState<QueryState<T>>({ status: enabled ? 'loading' : 'idle' });
  const [attempt, setAttempt] = useState(0);
  const latest = useRef(fetcher);
  useEffect(() => {
    latest.current = fetcher;
  });

  useEffect(() => {
    if (!enabled) {
      setState({ status: 'idle' });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    latest.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: 'ready', data });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setState({ status: 'error', error });
      },
    );
    return () => controller.abort();
  }, [enabled, key, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
