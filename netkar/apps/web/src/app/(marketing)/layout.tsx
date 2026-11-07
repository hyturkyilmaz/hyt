import { Menu } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { BrandMark, BrandName } from '@/components/brand/brand-mark';
import { Button } from '@/components/ui/button';
import { brand } from '@/config/brand';
import { SITE_PAGES } from '@/lib/seo/pages';

const NAV_LINKS = [
  { href: SITE_PAGES.features.path, label: 'Özellikler' },
  { href: SITE_PAGES.tools.path, label: 'Ücretsiz araçlar' },
  { href: SITE_PAGES.pricing.path, label: 'Fiyatlar' },
  { href: SITE_PAGES.security.path, label: 'Güvenlik' },
  { href: SITE_PAGES.faq.path, label: 'SSS' },
] as const;

const LINK_CLASS =
  'inline-flex min-h-touch items-center rounded-md px-3 text-base text-foreground hover:bg-surface-muted';

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border">
        <div className="mx-auto flex h-16 max-w-content items-center justify-between gap-3 px-gutter lg:px-8">
          <Link href="/" className="inline-flex min-h-touch items-center gap-3">
            <BrandMark />
            <BrandName />
          </Link>

          <nav aria-label="Ana menü" className="hidden items-center gap-1 lg:flex">
            {NAV_LINKS.map((link) => (
              <Link key={link.href} href={link.href} className={LINK_CLASS}>
                {link.label}
              </Link>
            ))}
          </nav>

          <div className="hidden items-center gap-2 lg:flex">
            <Button asChild variant="ghost">
              <Link href="/giris">Giriş yap</Link>
            </Button>
            <Button asChild>
              <Link href={`${SITE_PAGES.pricing.path}#bekleme-listesi`}>Bekleme listesi</Link>
            </Button>
          </div>

          {/* Küçük ekranda betiksiz açılır menü */}
          <details className="group relative lg:hidden">
            <summary className="inline-flex min-h-touch cursor-pointer list-none items-center gap-2 rounded-md border border-input-border px-4 text-base font-medium [&::-webkit-details-marker]:hidden">
              <Menu className="size-5" aria-hidden="true" />
              Menü
            </summary>
            <nav
              aria-label="Mobil menü"
              className="absolute right-0 top-full z-50 mt-2 flex w-64 flex-col gap-1 rounded-lg border border-border bg-surface p-2 shadow-md"
            >
              {NAV_LINKS.map((link) => (
                <Link key={link.href} href={link.href} className={LINK_CLASS}>
                  {link.label}
                </Link>
              ))}
              <Link href="/giris" className={LINK_CLASS}>
                Giriş yap
              </Link>
              <Link
                href={`${SITE_PAGES.pricing.path}#bekleme-listesi`}
                className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary px-3 text-base font-medium text-primary-foreground"
              >
                Bekleme listesi
              </Link>
            </nav>
          </details>
        </div>
      </header>

      <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto grid max-w-content gap-8 px-gutter py-10 text-sm text-muted-foreground sm:grid-cols-2 lg:grid-cols-4 lg:px-8">
          <div className="flex flex-col gap-2">
            <p className="text-base font-semibold text-foreground">{brand.name}</p>
            <p>{brand.tagline}</p>
            <p>Ürün kapalı beta aşamasındadır.</p>
          </div>
          <nav aria-label="Ürün" className="flex flex-col">
            <p className="mb-1 text-base font-semibold text-foreground">Ürün</p>
            {[SITE_PAGES.features, SITE_PAGES.pricing, SITE_PAGES.security, SITE_PAGES.faq].map(
              (page) => (
                <Link
                  key={page.path}
                  href={page.path}
                  className="inline-flex min-h-touch items-center underline underline-offset-4"
                >
                  {page.crumb}
                </Link>
              ),
            )}
          </nav>
          <nav aria-label="Ücretsiz araçlar" className="flex flex-col">
            <p className="mb-1 text-base font-semibold text-foreground">Ücretsiz araçlar</p>
            {[SITE_PAGES.commissionTool, SITE_PAGES.profitTool, SITE_PAGES.desiTool].map((page) => (
              <Link
                key={page.path}
                href={page.path}
                className="inline-flex min-h-touch items-center underline underline-offset-4"
              >
                {page.crumb}
              </Link>
            ))}
          </nav>
          <nav aria-label="Yasal" className="flex flex-col">
            <p className="mb-1 text-base font-semibold text-foreground">Yasal</p>
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
        </div>
        <div className="mx-auto max-w-content px-gutter pb-8 text-sm text-muted-foreground lg:px-8">
          <p>
            © {new Date().getFullYear()} {brand.name}. Şirket ve iletişim bilgileri ile yasal
            metinler lansman öncesi eklenecek.
          </p>
        </div>
      </footer>
    </div>
  );
}
