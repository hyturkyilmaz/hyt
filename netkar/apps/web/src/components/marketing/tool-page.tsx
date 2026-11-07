import Link from 'next/link';
import type { ReactNode } from 'react';

import { PageJsonLd } from '@/components/seo/page-json-ld';
import { WaitlistSection } from '@/components/waitlist/waitlist-section';
import { getEnv } from '@/config/env';
import { breadcrumbJsonLd, webApplicationJsonLd } from '@/lib/seo/jsonld';
import { SITE_PAGES, type SitePageKey } from '@/lib/seo/pages';

import { Container, PageIntro, UpdatedNote } from './page-parts';

/** Hesaplayıcı sayfası iskeleti: başlık ve ilk paragrafta cevap, araç, açıklamalar, bekleme listesi. */
export function ToolPage({
  pageKey,
  title,
  lead,
  tool,
  children,
  related,
}: {
  pageKey: SitePageKey;
  title: string;
  lead: ReactNode;
  tool: ReactNode;
  children: ReactNode;
  related: readonly SitePageKey[];
}) {
  const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;
  return (
    <>
      <PageJsonLd
        blocks={[
          breadcrumbJsonLd(siteUrl, ['home', 'tools', pageKey]),
          webApplicationJsonLd(siteUrl, pageKey),
        ]}
      />
      <Container className="flex flex-col gap-10 py-10 lg:py-14">
        <PageIntro trail={['home', 'tools', pageKey]} title={title} lead={lead} />
        {tool}
        {children}
        <section aria-labelledby="ilgili-baslik">
          <h2 id="ilgili-baslik" className="text-2xl font-bold">
            İlgili araçlar
          </h2>
          <ul className="mt-3 flex flex-wrap gap-x-6">
            {related.map((key) => (
              <li key={key}>
                <Link
                  href={SITE_PAGES[key].path}
                  className="inline-flex min-h-touch items-center text-primary underline underline-offset-4"
                >
                  {SITE_PAGES[key].crumb}
                </Link>
              </li>
            ))}
          </ul>
        </section>
        <UpdatedNote />
      </Container>
      <WaitlistSection
        title="Gerçek rakamlarınız bu tahmine ne kadar yakın?"
        lead="Hesaplayıcı tek bir ürün için tahmin verir. Bekleme listesine katılın; uygulama açıldığında mağazanızı bağlayıp geçen ayın gerçek rakamlarını ürün bazında görün."
      />
    </>
  );
}

export function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-baslik`} className="scroll-mt-6">
      <h2 id={`${id}-baslik`} className="text-2xl font-bold">
        {title}
      </h2>
      <div className="mt-3 flex max-w-3xl flex-col gap-3 text-base text-muted-foreground">
        {children}
      </div>
    </section>
  );
}

/** Adım adım örnek hesap: her satır bir işlem ve sonucudur. */
export function WorkedExample({ steps }: { steps: readonly { label: string; value: string }[] }) {
  return (
    <ol className="flex flex-col gap-2 text-base text-foreground">
      {steps.map((step, index) => (
        <li
          key={step.label}
          className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-border pb-2"
        >
          <span>
            <span className="num text-muted-foreground">{index + 1}. </span>
            {step.label}
          </span>
          <span className="num font-medium">{step.value}</span>
        </li>
      ))}
    </ol>
  );
}
