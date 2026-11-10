'use client';

import { Link2, Truck } from 'lucide-react';

import { ConnectStoreDialog } from '@/components/panel/connect-store-dialog';
import { EmptyState } from '@/components/panel/empty-state';
import { ReportError } from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { describeReportError } from '@/lib/profit/errors';
import { useReportAccount, type AccountState } from '@/lib/profit/use-account';

/** Bağlantı rozeti gerçek hesap durumundan gelir; sabit "Bağlı değil" yazılmaz (UX-02). */
function connectionBadge(state: AccountState): { label: string; variant: 'neutral' | 'profit' } {
  if (state.status === 'ready') return { label: 'Bağlı', variant: 'profit' };
  if (state.status === 'none') return { label: 'Bağlı değil', variant: 'neutral' };
  return { label: 'Kontrol ediliyor', variant: 'neutral' };
}

export function SettingsContent() {
  const { state, retry } = useReportAccount();
  const badge = connectionBadge(state);

  return (
    <>
      <Card id="trendyol">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              <Link2 className="size-5 text-primary" aria-hidden="true" />
              Trendyol bağlantısı
            </CardTitle>
            {state.status === 'error' ? null : (
              <Badge variant={badge.variant} role="status">
                {badge.label}
              </Badge>
            )}
          </div>
          <CardDescription>
            {state.status === 'ready'
              ? 'Mağazanız bağlı. Bağlantı yalnız okuma yapar.'
              : 'Trendyol mağazanızı bağlayın, ilk kârınızı 10 dakikada görün. Bağlantı yalnız okuma yapar.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {state.status === 'ready' ? (
            <p className="text-base">
              Satıcı numarası: <span className="num font-semibold">{state.sellerId}</span>
            </p>
          ) : null}
          {state.status === 'none' ? <ConnectStoreDialog /> : null}
          {state.status === 'error' ? (
            <ReportError
              title="Bağlantı durumu alınamadı"
              message={describeReportError(state.error)}
              onRetry={retry}
            />
          ) : null}
        </CardContent>
      </Card>

      <section id="kargo" aria-label="Kargo tarifesi ve hizmet bedeli">
        <EmptyState
          Icon={Truck}
          title="Kargo tarifesi ve hizmet bedeli girişi çok yakında"
          description="Bu bölüm henüz açılmadı. O zamana kadar özet ekranı kargo ve hizmet bedeli hariç, bilinen giderlerle hesaplanan kârınızı gösterir."
        />
      </section>
    </>
  );
}
