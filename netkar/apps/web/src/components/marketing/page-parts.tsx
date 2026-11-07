import { ChevronRight } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import type { FaqEntry } from '@/content/faq';
import { CONTENT_UPDATED, SITE_PAGES, type SitePageKey } from '@/lib/seo/pages';
import { formatDateTr } from '@/lib/seo/date';
import { cn } from '@/lib/utils';

/** İçerik sütunu: sayfa kenar boşluğu ve en büyük genişlik. */
export function Container({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('mx-auto max-w-content px-gutter lg:px-8', className)}>{children}</div>;
}

/** Ekmek kırıntısı (görünür). BreadcrumbList şeması ayrıca JSON-LD olarak yazılır. */
export function Breadcrumbs({ trail }: { trail: readonly SitePageKey[] }) {
  return (
    <nav aria-label="Ekmek kırıntısı" className="text-sm text-muted-foreground">
      <ol className="flex flex-wrap items-center gap-x-1">
        {trail.map((key, index) => {
          const page = SITE_PAGES[key];
          const last = index === trail.length - 1;
          return (
            <li key={key} className="flex items-center gap-1">
              {last ? (
                <span aria-current="page" className="text-foreground">
                  {page.crumb}
                </span>
              ) : (
                <>
                  <Link
                    href={page.path}
                    className="inline-flex min-h-6 items-center underline underline-offset-4"
                  >
                    {page.crumb}
                  </Link>
                  <ChevronRight className="size-4" aria-hidden="true" />
                </>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * Sayfa başlığı ve "önce cevap" paragrafı. `lead` sorunun cevabını ilk cümlede verir (GEO).
 */
export function PageIntro({
  trail,
  title,
  lead,
  children,
}: {
  trail?: readonly SitePageKey[];
  title: string;
  lead: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4">
      {trail ? <Breadcrumbs trail={trail} /> : null}
      <h1 className="text-3xl font-bold sm:text-4xl">{title}</h1>
      <p className="max-w-3xl text-lg text-foreground">{lead}</p>
      {children}
    </header>
  );
}

export function UpdatedNote({ date = CONTENT_UPDATED }: { date?: string }) {
  return (
    <p className="text-sm text-muted-foreground">
      Son güncelleme: <time dateTime={date}>{formatDateTr(date)}</time>
    </p>
  );
}

/** Kısa soru ve cevap listesi. Cevaplar görünürdür; FAQPage şeması yalnız /sss'de yazılır. */
export function FaqList({
  entries,
  headingLevel = 3,
}: {
  entries: readonly FaqEntry[];
  headingLevel?: 2 | 3;
}) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  return (
    <div className="flex flex-col gap-6">
      {entries.map((entry) => (
        <div key={entry.id} id={entry.id} className="scroll-mt-6">
          <Heading className="text-lg font-semibold">{entry.question}</Heading>
          <p className="mt-1.5 max-w-3xl text-base text-muted-foreground">{entry.answer}</p>
        </div>
      ))}
    </div>
  );
}

export function WaitlistLink({ children = 'Bekleme listesine katıl' }: { children?: ReactNode }) {
  return (
    <Button asChild>
      <Link href="#bekleme-listesi">{children}</Link>
    </Button>
  );
}
