import { Store } from 'lucide-react';
import type { Metadata } from 'next';

import { EmptyState } from '@/components/panel/empty-state';
import { PageHeader } from '@/components/panel/page-header';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export const metadata: Metadata = { title: 'Özet' };

const STEPS = [
  'Trendyol mağazanızı bağlayın.',
  'Ürün maliyetlerinizi Excel ile yükleyin veya tek tek girin.',
  'Geçmiş siparişlerinizin ürün bazında net kârını görün.',
];

export default function PanelHomePage() {
  return (
    <>
      <PageHeader
        title="Özet"
        description="Bugün ne kazandığınız ve hangi ürünün zarar ettirdiği burada görünür."
      />

      <section aria-label="Günlük özet" className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardDescription>Bugünkü net kâr</CardDescription>
            <CardTitle as="h2" className="text-muted-foreground">
              Veri bekleniyor
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Mağazanız bağlanınca ilk rakam burada olacak.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Zarar ettiren ürünler</CardDescription>
            <CardTitle as="h2" className="text-muted-foreground">
              Veri bekleniyor
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Zararına satan ürünler burada öne çıkarılacak.
          </CardContent>
        </Card>
      </section>

      <EmptyState
        Icon={Store}
        title="Trendyol mağazanızı bağlayın, ilk kârınızı 10 dakikada görün"
        description="Bağlantı yalnız okuma yapar. Sipariş, komisyon ve kargo bilgileriniz ürün bazında net kâra çevrilir."
        action={{ href: '/panel/ayarlar', label: 'Bağlantıya başla' }}
      >
        <ol className="flex w-full max-w-md list-none flex-col gap-3 text-left">
          {STEPS.map((step, index) => (
            <li key={step} className="flex items-start gap-3 text-base">
              <span
                aria-hidden="true"
                className="flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-muted text-sm font-semibold"
              >
                {index + 1}
              </span>
              <span>
                <span className="sr-only">{index + 1}. adım: </span>
                {step}
              </span>
            </li>
          ))}
        </ol>
      </EmptyState>
    </>
  );
}
