import type { Metadata } from 'next';
import { Suspense } from 'react';

import { PanelSkeleton } from '@/components/panel/panel-skeleton';
import { SummaryScreen } from '@/components/profit/summary-view';

export const metadata: Metadata = { title: 'Özet' };

// Rakamlar tarayıcıda oturum çerezi ile /api/v1 üzerinden çekilir; dönem URL'deki `range` parametresidir.
export default function PanelHomePage() {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <SummaryScreen />
    </Suspense>
  );
}
