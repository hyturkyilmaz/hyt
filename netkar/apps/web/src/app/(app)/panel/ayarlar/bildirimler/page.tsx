import { ChevronLeft } from 'lucide-react';
import type { Metadata } from 'next';
import Link from 'next/link';

import { NotificationSettings } from '@/components/notifications/notification-settings';
import { PageHeader } from '@/components/panel/page-header';

export const metadata: Metadata = { title: 'Bildirimler' };

// Rol ve e-posta doğrulama durumu tarayıcıda GET /v1/me ile okunur; yetki sunucuda da denetlenir.
export default function NotificationSettingsPage() {
  return (
    <>
      <Link
        href="/panel/ayarlar"
        className="inline-flex min-h-touch items-center gap-1 self-start text-base text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronLeft className="size-5" aria-hidden="true" />
        Ayarlar
      </Link>
      <PageHeader
        title="Bildirimler"
        description="Hangi uyarıyı hangi kanaldan, ne zaman almak istediğinizi seçin."
      />
      <NotificationSettings />
    </>
  );
}
