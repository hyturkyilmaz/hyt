import type { Metadata } from 'next';
import { Suspense } from 'react';

import { PanelSkeleton } from '@/components/panel/panel-skeleton';
import { ProductDetailScreen } from '@/components/profit/product-detail';

export const metadata: Metadata = { title: 'Ürün kırılımı' };

// Segment yüzde kodlu gelebilir; bozuk kodlamada ham değer kullanılır (hata fırlatılmaz).
function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export default async function ProductDetailPage({
  params,
}: {
  params: Promise<{ barkod: string }>;
}) {
  const { barkod } = await params;
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <ProductDetailScreen barcode={safeDecode(barkod)} />
    </Suspense>
  );
}
