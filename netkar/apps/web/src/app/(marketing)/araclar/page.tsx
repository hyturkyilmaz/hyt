import { Calculator } from 'lucide-react';
import type { Metadata } from 'next';
import Link from 'next/link';

import { Container, PageIntro, UpdatedNote } from '@/components/marketing/page-parts';
import { PageJsonLd } from '@/components/seo/page-json-ld';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { WaitlistSection } from '@/components/waitlist/waitlist-section';
import { getEnv } from '@/config/env';
import { breadcrumbJsonLd } from '@/lib/seo/jsonld';
import { pageMetadata } from '@/lib/seo/metadata';
import { SITE_PAGES } from '@/lib/seo/pages';

export const metadata: Metadata = pageMetadata('tools');

const TOOLS = [
  {
    page: SITE_PAGES.commissionTool,
    text: 'Satış fiyatı ve komisyon oranından komisyonu, komisyonun KDV’sini, stopajı ve hesabınıza geçecek tutarı hesaplar.',
  },
  {
    page: SITE_PAGES.profitTool,
    text: 'Maliyet, kargo, iade payı ve reklamı da katarak ürün başına net kârı, marjı ve başabaş fiyatını verir.',
  },
  {
    page: SITE_PAGES.desiTool,
    text: 'Koli ölçülerinden ve ağırlığından desiyi, ücretlendirmeye esas değeri ve küçültmenin etkisini gösterir.',
  },
] as const;

export default function ToolsPage() {
  const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;
  return (
    <>
      <PageJsonLd blocks={[breadcrumbJsonLd(siteUrl, ['home', 'tools'])]} />
      <Container className="flex flex-col gap-10 py-10 lg:py-14">
        <PageIntro
          trail={['home', 'tools']}
          title="Ücretsiz Trendyol satıcı araçları"
          lead="Komisyon, net kâr ve desi için üç hesaplayıcı, kayıt istemeden kullanılabilir. Girdiğiniz rakamlar tarayıcınızda hesaplanır, sunucuya gönderilmez. Formüller ve örnek hesaplar her sayfada açıkça yazılıdır, teyit bekleyen varsayımlar ayrıca işaretlenir."
        >
          <UpdatedNote />
        </PageIntro>
        <ul className="grid gap-6 md:grid-cols-3">
          {TOOLS.map(({ page, text }) => (
            <li key={page.path}>
              <Card className="h-full">
                <CardHeader>
                  <Calculator className="size-6 text-primary" aria-hidden="true" />
                  <CardTitle as="h2" className="text-lg">
                    <Link href={page.path} className="underline-offset-4 hover:underline">
                      {page.crumb}
                    </Link>
                  </CardTitle>
                  <CardDescription className="text-base">{text}</CardDescription>
                </CardHeader>
              </Card>
            </li>
          ))}
        </ul>
        <p className="max-w-3xl text-base text-muted-foreground">
          Hesaplayıcılar bir ürünün olması gereken kârını tahmin eder. Geçen ay gerçekte ne
          kaldığını Trendyol hakediş ekstreniz gösterir; uygulamanın amacı o ekstreyi ürün bazında
          okumaktır.
        </p>
      </Container>
      <WaitlistSection />
    </>
  );
}
