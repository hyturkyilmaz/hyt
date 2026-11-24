import Link from 'next/link';

import { Button } from '@/components/ui/button';

export default function NotFound() {
  return (
    <main
      id="main"
      className="mx-auto flex min-h-dvh max-w-md flex-col items-start justify-center gap-4 px-gutter"
    >
      <h1 className="text-3xl font-bold">Sayfa bulunamadı</h1>
      <p className="text-base text-muted-foreground">
        Aradığınız sayfa taşınmış veya hiç olmamış olabilir.
      </p>
      <Button asChild>
        <Link href="/">Ana sayfaya dön</Link>
      </Button>
    </main>
  );
}
