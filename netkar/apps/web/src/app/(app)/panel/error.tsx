'use client';

import { Button } from '@/components/ui/button';

// Beklenmeyen hata: ayrıntı gösterilmez (güvenlik), kullanıcıya tekrar deneme sunulur.
export default function PanelError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-4">
      <h1 className="text-2xl font-bold">Bir şeyler ters gitti</h1>
      <p className="text-base text-muted-foreground">
        Sayfa yüklenemedi. Tekrar deneyebilirsiniz; sorun sürerse biraz sonra yeniden bakın.
      </p>
      <Button onClick={reset}>Tekrar dene</Button>
    </div>
  );
}
