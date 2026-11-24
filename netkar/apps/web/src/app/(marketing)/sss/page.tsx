import type { Metadata } from 'next';

import { Container, FaqList, PageIntro, UpdatedNote } from '@/components/marketing/page-parts';
import { PageJsonLd } from '@/components/seo/page-json-ld';
import { WaitlistSection } from '@/components/waitlist/waitlist-section';
import { getEnv } from '@/config/env';
import { FAQ_CATEGORIES, allFaqEntries } from '@/content/faq';
import { breadcrumbJsonLd, faqPageJsonLd } from '@/lib/seo/jsonld';
import { pageMetadata } from '@/lib/seo/metadata';

export const metadata: Metadata = pageMetadata('faq');

export default function FaqPage() {
  const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;
  // FAQPage şeması yalnız bu sayfada ve görünür metinle birebir aynı içerikle yazılır.
  const faqJson = faqPageJsonLd(
    allFaqEntries().map((entry) => ({ question: entry.question, answer: entry.answer })),
  );
  return (
    <>
      <PageJsonLd blocks={[breadcrumbJsonLd(siteUrl, ['home', 'faq']), faqJson]} />
      <Container className="flex flex-col gap-12 py-10 lg:py-14">
        <PageIntro
          trail={['home', 'faq']}
          title="Sık sorulan sorular"
          lead="Bu sayfada kurulum, veri güvenliği, kâr hesabının yöntemi, fiyat, muhasebeci erişimi ve mobil uygulama hakkındaki soruların cevapları var. Her cevap sorunun yanıtını ilk cümlede verir. Henüz yapılmamış ya da kesinleşmemiş bir şey varsa bunu açıkça yazdık."
        >
          <UpdatedNote />
        </PageIntro>

        <nav aria-label="Soru kategorileri">
          <ul className="flex flex-wrap gap-x-6">
            {FAQ_CATEGORIES.map((category) => (
              <li key={category.id}>
                <a
                  href={`#${category.id}`}
                  className="inline-flex min-h-touch items-center text-primary underline underline-offset-4"
                >
                  {category.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        {FAQ_CATEGORIES.map((category) => (
          <section
            key={category.id}
            id={category.id}
            aria-labelledby={`${category.id}-baslik`}
            className="scroll-mt-6"
          >
            <h2 id={`${category.id}-baslik`} className="text-2xl font-bold">
              {category.title}
            </h2>
            <div className="mt-5">
              <FaqList entries={category.items} />
            </div>
          </section>
        ))}
      </Container>
      <WaitlistSection />
    </>
  );
}
