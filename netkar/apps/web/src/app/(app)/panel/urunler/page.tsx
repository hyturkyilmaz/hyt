import { Package } from 'lucide-react';
import type { Metadata } from 'next';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';

export const metadata: Metadata = { title: 'Ürünler' };

export default function ProductsPage() {
  return (
    <>
      <PageHeader
        title="Ürünler"
        description="Her ürünün komisyon, kargo, iade ve reklam sonrası net kârı."
      />
      <EmptyState
        Icon={Package}
        title="Henüz ürün yok"
        description="Trendyol mağazanızı bağladığınızda ürünleriniz burada listelenir. Zarar ettirenler en üstte görünür."
        action={{ href: '/panel/ayarlar', label: 'Mağazayı bağla' }}
      />
    </>
  );
}
