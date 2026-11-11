import type { Metadata } from 'next';
import { Suspense } from 'react';

import { PanelSkeleton } from '@/components/panel/panel-skeleton';
import { AlertsScreen } from '@/components/profit/alerts-view';

export const metadata: Metadata = { title: 'Uyarılar' };

export default function AlertsPage() {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <AlertsScreen />
    </Suspense>
  );
}
