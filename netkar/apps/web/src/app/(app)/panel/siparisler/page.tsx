import { Receipt } from 'lucide-react';
import type { Metadata } from 'next';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';

export const metadata: Metadata = { title: 'Siparişler' };

export default function OrdersPage() {
  return (
    <>
      <PageHeader title="Siparişler" description="Sipariş bazında tahmini ve kesinleşmiş kâr." />
      <EmptyState
        Icon={Receipt}
        title="Henüz sipariş yok"
        description="Mağazanız bağlanınca siparişleriniz burada görünür. Hakediş ekstresi geldikçe tahmini kâr kesinleşir."
        action={{ href: '/panel/ayarlar', label: 'Mağazayı bağla' }}
      />
    </>
  );
}
