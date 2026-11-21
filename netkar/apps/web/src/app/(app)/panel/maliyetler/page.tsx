import type { Metadata } from 'next';
import { Suspense } from 'react';

import { CostsScreen } from '@/components/costs/costs-screen';
import { PanelSkeleton } from '@/components/panel/panel-skeleton';

export const metadata: Metadata = { title: 'Ürün maliyetleri' };

export default function CostsPage() {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <CostsScreen />
    </Suspense>
  );
}
