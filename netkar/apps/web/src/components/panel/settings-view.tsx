'use client';

import { Link2, Store, Truck } from 'lucide-react';
import dynamic from 'next/dynamic';

import { EmptyState } from '@/components/panel/empty-state';
import { ReportError, ReportSkeleton } from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { describeReportError } from '@/lib/profit/errors';
import { useReportAccount, type AccountState } from '@/lib/profit/use-account';

// Bağlantı diyaloğu (Radix Dialog) ilk boyamayı geciktirmesin diye ayrı pakette yüklenir. Paket gelene kadar
// aynı görünümde düğme gösterilir; tıklama diyalog yüklendikten sonra açılır, yerleşim değişmez.
const ConnectStoreDialog = dynamic(
  () => import('@/components/panel/connect-store-dialog').then((m) => m.ConnectStoreDialog),
  {
    ssr: false,
    loading: () => (
      <Button disabled>
        <Store aria-hidden="true" />
        Trendyol mağazasını bağla
      </Button>
    ),
  },
);

// Kâr ayarları formu (form kütüphanesi, doğrulama, geçmiş listesi) yalnız bağlı mağazada çizilir. Bağlı
// olmayan ya da hâlâ kontrol edilen kullanıcıya bu paketi yollamamak için istek üzerine yüklenir.
const ProfitSettingsPanel = dynamic(
  () => import('@/components/settings/profit-settings-panel').then((m) => m.ProfitSettingsPanel),
  {
    ssr: false,
    loading: () => (
      <section aria-label="Kâr ayarları">
        <ReportSkeleton rows={3} />
      </section>
    ),
  },
);

/** Bağlantı rozeti gerçek hesap durumundan gelir; sabit "Bağlı değil" yazılmaz (UX-02). */
function connectionBadge(state: AccountState): { label: string; variant: 'neutral' | 'info' } {
  if (state.status === 'ready') return { label: 'Bağlı', variant: 'info' };
  if (state.status === 'none') return { label: 'Bağlı değil', variant: 'neutral' };
  return { label: 'Kontrol ediliyor', variant: 'neutral' };
}

function connectionDescription(state: AccountState): string {
  if (state.status === 'ready') return 'Mağazanız bağlı. Bağlantı yalnız okuma yapar.';
  if (state.status === 'none') {
    return 'Trendyol mağazanızı bağlayın, ilk kârınızı 10 dakikada görün. Bağlantı yalnız okuma yapar.';
  }
  return 'Bağlantı durumu kontrol ediliyor.';
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
          {/* Y-10: hata durumunda "mağazanızı bağlayın" denmez; bağlı bir kullanıcıya yanlış yönlendirme olur. */}
          {state.status === 'error' ? null : (
            <CardDescription>{connectionDescription(state)}</CardDescription>
          )}
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

      {state.status === 'ready' ? <ProfitSettingsPanel accountId={state.accountId} /> : null}
      {state.status === 'loading' ? (
        <section aria-label="Kâr ayarları">
          <ReportSkeleton rows={2} />
        </section>
      ) : null}
      {state.status === 'none' ? (
        <section id="kargo" aria-label="Kâr ayarları">
          <EmptyState
            Icon={Truck}
            title="Kâr ayarları mağazanızı bağlayınca açılır"
            description="Kargo tarifenizi ve platform hizmet bedelinizi, Trendyol mağazanız bağlandıktan sonra buradan girersiniz."
          />
        </section>
      ) : null}
    </>
  );
}
