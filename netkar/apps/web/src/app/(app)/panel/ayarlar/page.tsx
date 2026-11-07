import { Link2 } from 'lucide-react';
import type { Metadata } from 'next';

import { ConnectStoreDialog } from '@/components/panel/connect-store-dialog';
import { PageHeader } from '@/components/panel/page-header';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export const metadata: Metadata = { title: 'Ayarlar' };

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Ayarlar" description="Mağaza bağlantınız ve hesap tercihleriniz." />
      <Card id="trendyol">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              <Link2 className="size-5 text-primary" aria-hidden="true" />
              Trendyol bağlantısı
            </CardTitle>
            <Badge>Bağlı değil</Badge>
          </div>
          <CardDescription>
            Trendyol mağazanızı bağlayın, ilk kârınızı 10 dakikada görün. Bağlantı yalnız okuma
            yapar.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ConnectStoreDialog />
        </CardContent>
      </Card>
    </>
  );
}
