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
        description="Zarar, düşük hakediş ve komisyon değişikliği bildirimleri burada listelenecek."
      />
      <EmptyState
        Icon={BellRing}
        title="Uyarılar ekranı yakında"
        description="Bu ekran henüz açılmadı. Dönemde motorun işaretlediği durumların sayısını Özet ekranında görebilirsiniz."
        action={{ href: '/panel', label: 'Özete git' }}
      />
    </>
  );
}
