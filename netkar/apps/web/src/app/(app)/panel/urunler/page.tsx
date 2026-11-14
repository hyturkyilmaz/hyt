import type { Metadata } from 'next';
import { Suspense } from 'react';

import { PanelSkeleton } from '@/components/panel/panel-skeleton';
import { ProductListScreen } from '@/components/profit/product-list';

export const metadata: Metadata = { title: 'Ürünler' };

export default function ProductsPage() {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <ProductListScreen />
    </Suspense>
  );
}
