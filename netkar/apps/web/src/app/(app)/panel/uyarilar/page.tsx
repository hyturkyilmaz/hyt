import { BellRing } from 'lucide-react';
import type { Metadata } from 'next';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';

export const metadata: Metadata = { title: 'Uyarılar' };

export default function AlertsPage() {
  return (
    <>
      <PageHeader
        title="Uyarılar"
        description="Zarar, düşük hakediş ve komisyon değişikliği bildirimleri."
      />
      <EmptyState
        Icon={BellRing}
        title="Şu an bir uyarı yok"
        description="Bir ürün zarar etmeye başladığında burada görürsünüz. Mağazanızı bağlayınca uyarılar çalışmaya başlar."
        action={{ href: '/panel/ayarlar', label: 'Mağazayı bağla' }}
      />
    </>
  );
}
