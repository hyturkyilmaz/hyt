import type { Metadata } from 'next';

import { SettingsContent } from '@/components/panel/settings-view';
import { PageHeader } from '@/components/panel/page-header';

export const metadata: Metadata = { title: 'Ayarlar' };

// Bağlantı durumu tarayıcıda gerçek hesap listesinden okunur; sabit durum yazılmaz.
export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Ayarlar" description="Mağaza bağlantınız ve hesap tercihleriniz." />
      <SettingsContent />
    </>
  );
}
