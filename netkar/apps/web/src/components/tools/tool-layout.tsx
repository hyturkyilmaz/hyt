import type { ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

/**
 * Hesaplayıcı yerleşimi: solda girdiler, sağda sonuç. Sonuç kartının yüksekliği baştan ayrılır,
 * böylece değerler değişince sayfa kaymaz (CLS).
 */
export function ToolLayout({
  inputs,
  results,
  isExample,
}: {
  inputs: ReactNode;
  results: ReactNode;
  isExample: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
      <Card aria-labelledby="girdiler-baslik">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle id="girdiler-baslik" className="text-lg">
              Rakamlarınız
            </CardTitle>
            {isExample ? <Badge variant="warning">Örnek değerler</Badge> : null}
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">{inputs}</CardContent>
      </Card>
      <Card aria-labelledby="sonuc-baslik">
        <CardHeader>
          <CardTitle id="sonuc-baslik" className="text-lg">
            Sonuç
          </CardTitle>
        </CardHeader>
        <CardContent>
          {/* Durum mesajı: sonuç değişince ekran okuyucuya bildirilir (WCAG 4.1.3) */}
          <div aria-live="polite" className="min-h-[32rem] lg:min-h-[36rem]">
            {results}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function EstimateNote() {
  return (
    <p className="mt-4 border-t border-border pt-4 text-sm text-muted-foreground">
      Bu bir tahmindir. Gerçek kesintileriniz Trendyol hakediş ekstrenizde yazar. Ekstreden, ürün ve
      sipariş bazında hesap için aşağıdaki bekleme listesine katılın.
    </p>
  );
}
