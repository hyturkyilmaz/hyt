import Link from 'next/link';
import type { ReactNode } from 'react';

import { BrandMark, BrandName } from '@/components/brand/brand-mark';
import { Button } from '@/components/ui/button';
import { brand } from '@/config/brand';

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border">
        <div className="mx-auto flex h-16 max-w-content items-center justify-between px-gutter lg:px-8">
          <Link href="/" className="inline-flex min-h-touch items-center gap-3">
            <BrandMark />
            <BrandName />
          </Link>
          <nav aria-label="Hesap" className="flex items-center gap-1">
            <Button asChild variant="ghost">
              <Link href="/giris">Giriş yap</Link>
            </Button>
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-content flex-col gap-2 px-gutter py-8 text-sm text-muted-foreground lg:px-8">
          <nav aria-label="Yasal" className="flex flex-wrap gap-x-6">
            <Link
              href="/kullanim-kosullari"
              className="inline-flex min-h-touch items-center underline underline-offset-4"
            >
              Kullanım koşulları
            </Link>
            <Link
              href="/kvkk-aydinlatma-metni"
              className="inline-flex min-h-touch items-center underline underline-offset-4"
            >
              KVKK aydınlatma metni
            </Link>
          </nav>
          <p>
            © {new Date().getFullYear()} {brand.name}
          </p>
          <p>
            Bu sayfa geçicidir. Fiyatlar, yasal metinler ve iletişim bilgileri lansman öncesi
            eklenecek.
          </p>
        </div>
      </footer>
    </div>
  );
}
