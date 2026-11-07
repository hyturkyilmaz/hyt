import { Check } from 'lucide-react';
import type { Metadata } from 'next';
import Link from 'next/link';

import { Container, FaqList, PageIntro, UpdatedNote } from '@/components/marketing/page-parts';
import { PageJsonLd } from '@/components/seo/page-json-ld';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { WaitlistSection } from '@/components/waitlist/waitlist-section';
import { allFaqEntries } from '@/content/faq';
import { getEnv } from '@/config/env';
import { breadcrumbJsonLd } from '@/lib/seo/jsonld';
import { pageMetadata } from '@/lib/seo/metadata';
import { SITE_PAGES } from '@/lib/seo/pages';

export const metadata: Metadata = pageMetadata('pricing');

// Plan adları ve kapsam taslaktır. Fiyat, deneme süresi ve limitler (K-N05) kesinleşmediği için
// rakam yazılmaz; yalnız kimin için olduğu ve planlanan kapsam anlatılır.
const PLANS = [
  {
    name: 'Başlangıç',
    audience: 'Tek mağaza işleten ve kârını ürün bazında görmek isteyen satıcı için.',
    items: ['Ürün bazında net kâr', 'Hakediş eşleştirme', 'Temel uyarılar'],
  },
  {
    name: 'Pro',
    audience: 'Reklam harcayan ve birden çok ürün grubunu yöneten satıcı için.',
    items: [
      'Başlangıç planındaki her şey',
      'Reklam ve başabaş ROAS analizi',
      'Tüm uyarılar',
      'Muhasebeci erişimi (planlanıyor)',
    ],
  },
  {
    name: 'Ajans',
    audience: 'Birden çok müşterinin mağazasını yöneten ajans ve danışman için.',
    items: [
      'Pro planındaki her şey',
      'Çok mağaza yönetimi (planlanıyor)',
      'Müşteri raporları (planlanıyor)',
    ],
  },
] as const;

export default function PricingPage() {
  const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;
  const pricingFaq = allFaqEntries().filter((entry) =>
    ['fiyat', 'acik-mi', 'muhasebeci'].includes(entry.id),
  );
  return (
    <>
      <PageJsonLd blocks={[breadcrumbJsonLd(siteUrl, ['home', 'pricing'])]} />
      <Container className="flex flex-col gap-12 py-10 lg:py-14">
        <PageIntro
          trail={['home', 'pricing']}
          title="Fiyatlar"
          lead="Lansman fiyatı henüz kesinleşmedi, bu yüzden bu sayfada rakam yok. Aşağıda plan taslaklarını görebilir, bekleme listesine katılırsanız fiyatlar belli olduğunda ilk siz öğrenirsiniz."
        >
          <UpdatedNote />
        </PageIntro>

        <section aria-labelledby="planlar-baslik">
          <h2 id="planlar-baslik" className="text-2xl font-bold">
            Plan taslakları
          </h2>
          <p className="mt-2 max-w-3xl text-base text-muted-foreground">
            Plan adları ve kapsam lansmandan önce değişebilir. Fiyatlandırma açıklandığında KDV
            durumunu da açıkça yazacağız.
          </p>
          <ul className="mt-6 grid gap-6 lg:grid-cols-3">
            {PLANS.map((plan) => (
              <li key={plan.name}>
                <Card className="flex h-full flex-col">
                  <CardHeader>
                    <CardTitle as="h3">{plan.name}</CardTitle>
                    <CardDescription className="text-base">{plan.audience}</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col gap-4">
                    <p>
                      <Badge variant="warning">Lansman fiyatı yakında</Badge>
                    </p>
                    <ul className="flex flex-col gap-2 text-base">
                      {plan.items.map((item) => (
                        <li key={item} className="flex items-start gap-2">
                          <Check
                            className="mt-0.5 size-5 shrink-0 text-profit"
                            aria-hidden="true"
                          />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                  <CardFooter>
                    <Button asChild variant="secondary" className="w-full sm:w-auto">
                      <Link href="#bekleme-listesi">Bekleme listesine katıl</Link>
                    </Button>
                  </CardFooter>
                </Card>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="bilinenler-baslik">
          <h2 id="bilinenler-baslik" className="text-2xl font-bold">
            Fiyat hakkında bildiklerimiz
          </h2>
          <ul className="mt-4 flex max-w-3xl list-disc flex-col gap-2 pl-6 text-base">
            <li>
              Hesaplayıcılar şu an ücretsizdir ve kayıt istemez:{' '}
              <Link
                href={SITE_PAGES.tools.path}
                className="text-primary underline underline-offset-4"
              >
                ücretsiz araçlar
              </Link>
              .
            </li>
            <li>Deneme süresi, plan limitleri ve ödeme koşulları henüz kesinleşmedi.</li>
            <li>Uygulama kapalı beta aşamasında; bu yüzden şu an ödeme alınmıyor.</li>
          </ul>
        </section>

        <section aria-labelledby="fiyat-sss-baslik">
          <h2 id="fiyat-sss-baslik" className="text-2xl font-bold">
            Kısa sorular
          </h2>
          <div className="mt-6">
            <FaqList entries={pricingFaq} />
          </div>
          <p className="mt-6">
            <Link href={SITE_PAGES.faq.path} className="text-primary underline underline-offset-4">
              Tüm sık sorulan sorular
            </Link>
          </p>
        </section>
      </Container>
      <WaitlistSection
        title="Fiyatlar belli olunca haber alın"
        lead="E-postanızı bırakın. Lansman fiyatı ve açılış tarihi netleştiğinde size ilk biz yazalım."
      />
    </>
  );
}
