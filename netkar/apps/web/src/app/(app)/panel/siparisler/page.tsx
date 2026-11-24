import type { Metadata } from 'next';
import { Suspense } from 'react';

import { PanelSkeleton } from '@/components/panel/panel-skeleton';
import { OrderListScreen } from '@/components/profit/order-list';

export const metadata: Metadata = { title: 'Siparişler' };

export default function OrdersPage() {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <OrderListScreen />
    </Suspense>
  );
}
