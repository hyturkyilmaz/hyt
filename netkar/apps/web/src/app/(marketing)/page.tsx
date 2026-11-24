import {
  ArrowRight,
  Bell,
  Calculator,
  Database,
  KeyRound,
  Megaphone,
  Package,
  Percent,
  ReceiptText,
  ShieldCheck,
  Truck,
  UserX,
} from 'lucide-react';
import type { Metadata } from 'next';
import Link from 'next/link';

import { Container, FaqList, WaitlistLink } from '@/components/marketing/page-parts';
import { ProfitValue } from '@/components/profit-value';
import { PageJsonLd } from '@/components/seo/page-json-ld';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { WaitlistSection } from '@/components/waitlist/waitlist-section';
import { brand } from '@/config/brand';
import { getEnv } from '@/config/env';
import { homeFaqEntries } from '@/content/faq';
import { softwareApplicationJsonLd } from '@/lib/seo/jsonld';
import { pageMetadata } from '@/lib/seo/metadata';
import { SITE_PAGES } from '@/lib/seo/pages';

export const metadata: Metadata = pageMetadata('home');

// Yalnız arayüzü göstermek için uydurma örnek veri; sayfada "Örnek veri" etiketiyle işaretlidir.
const SAMPLE_PRODUCTS = [
  { name: 'Pamuklu nevresim takımı', profit: '1842.30' },
  { name: 'Bambu kesme tahtası', profit: '96.75' },
  { name: 'Seramik kupa, 6 lı set', profit: '-212.40' },
] as const;

const PROBLEMS = [
  {
    Icon: Percent,
    title: 'Kesintiler ayrı ayrı yapılıyor',
    text: 'Komisyon, komisyonun KDV’si, platform hizmet bedeli ve stopaj ayrı kalemler halinde düşülüyor. Hesaba yatan tutarı tek bakışta çıkarmak zor.',
  },
  {
    Icon: Truck,
    title: 'İade, kargoyu iki kez ödetebiliyor',
    text: 'İade gelen siparişte gidiş ve dönüş kargosu sizde kalabiliyor. Hangi ürünün iadesi size kaça mal oluyor, ekstrede ayrıca aramak gerekiyor.',
  },
  {
    Icon: Megaphone,
    title: 'Reklam, hangi ürünün kârını yiyor?',
    text: 'Reklam satış getiriyor ama ürün bazında kâra bağlanmadığında hangi ürünün zarara girdiği görünmüyor.',
  },
] as const;

const STEPS = [
  {
    title: 'Trendyol’u salt okuma bağlayın',
    text: 'Satıcı panelinizden aldığınız API bilgileriyle bağlanırsınız. Ürün, fiyat veya stok değiştirmeyiz, yalnızca okuruz.',
  },
  {
    title: 'Ürün maliyetlerinizi girin',
    text: 'Trendyol alış maliyetinizi bilmez, bu yüzden bu rakamı siz yazarsınız. Maliyeti olmayan ürün için sıfır varsaymayız.',
  },
  {
    title: 'Her ürünün net kârını görün',
    text: 'Sipariş geldiği anda tahmin görünür. Hakediş ekstresi geldikçe rakamlar kesinleşir ve her kalemin kaynağı yazılır.',
  },
] as const;

const FEATURES = [
  {
    Icon: Package,
    title: 'Ürün bazında net kâr',
    text: 'Komisyon, KDV, kargo, iade ve reklam düşüldükten sonra kalan tutar.',
  },
  {
    Icon: ReceiptText,
    title: 'Hakediş eşleştirme',
    text: 'Ekstre satırları siparişe bağlanır; beklenenden fazla kesinti ayrıca işaretlenir.',
  },
  {
    Icon: Megaphone,
    title: 'Reklam ve ROAS',
    text: 'Reklam harcaması ürüne yazılır, başabaş ROAS hesaplanır.',
  },
  {
    Icon: Bell,
    title: 'Uyarılar',
    text: 'Zararına satış, komisyon oranı farkı ve beklenmeyen kesinti için uyarı.',
  },
] as const;

const TOOLS = [
  { page: SITE_PAGES.commissionTool, text: 'Komisyonu, KDV’sini ve stopajı ayrı ayrı görün.' },
  {
    page: SITE_PAGES.profitTool,
    text: 'Reklam ve iade payı dahil ürün başına net kâr ve başabaş fiyatı.',
  },
  { page: SITE_PAGES.desiTool, text: 'Koli ölçülerinden desi ve ücretlendirmeye esas değer.' },
] as const;

const SECURITY_POINTS = [
  { Icon: ShieldCheck, title: 'Salt okuma', text: 'Trendyol’a yalnızca okuma isteği gider.' },
  {
    Icon: KeyRound,
    title: 'Şifreli saklama',
    text: 'API bilgileri zarf şifrelemeyle (AES-256-GCM) saklanır.',
  },
  {
    Icon: Database,
    title: 'Kiracı izolasyonu',
    text: 'Her mağazanın verisi veritabanı düzeyinde ayrılır (RLS).',
  },
  {
    Icon: UserX,
    title: 'Müşteri verisi yok',
    text: 'Son müşterinin ad, adres, telefon ve e-postası saklanmaz.',
  },
] as const;

export default function HomePage() {
  const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;

  return (
    <>
      <PageJsonLd blocks={[softwareApplicationJsonLd(siteUrl)]} />

      <section className="mx-auto grid max-w-content gap-10 px-gutter py-10 sm:py-14 lg:grid-cols-2 lg:items-center lg:gap-16 lg:px-8 lg:py-20">
        <div className="flex flex-col items-start gap-5">
          <Badge variant="info">Trendyol satıcıları için</Badge>
          <h1 className="text-4xl font-bold sm:text-5xl">{brand.tagline}</h1>
          <p className="max-w-xl text-lg text-muted-foreground">
            Trendyol mağazanızı salt okuma bağlantısıyla bağlayın. Her ürünün komisyon, KDV, kargo,
            iade ve reklam sonrası net kârını, hakediş ekstrenizle eşleşmiş olarak görün.
          </p>
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
            <WaitlistLink />
            <Button asChild variant="ghost">
              <Link href={SITE_PAGES.profitTool.path}>
                Önce ücretsiz kâr hesaplayıcısını deneyin
              </Link>
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            Salt okuma bağlantı; istediğiniz an kesersiniz. Ürün kapalı beta aşamasındadır, bu
            yüzden şimdilik bekleme listesi açık.{' '}
            <Link href="/kvkk-aydinlatma-metni" className="underline underline-offset-4">
              KVKK aydınlatma metni
            </Link>
            .
          </p>
        </div>

        <Card aria-labelledby="ornek-baslik">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle id="ornek-baslik" className="text-lg">
                Bu ayın ürünleri
              </CardTitle>
              <Badge variant="warning">Örnek veri</Badge>
            </div>
            <CardDescription>Net kâr, tüm kesintilerden sonra.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border">
              {SAMPLE_PRODUCTS.map((product) => (
                <li key={product.name} className="flex items-center justify-between gap-4 py-3">
                  <span className="text-base">{product.name}</span>
                  <ProfitValue value={product.profit} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </section>

      <section aria-labelledby="sorun-baslik" className="border-t border-border bg-surface">
        <Container className="py-12 lg:py-16">
          <h2 id="sorun-baslik" className="text-2xl font-bold sm:text-3xl">
            Satış artıyor ama hesaba yatan tutar aynı kalıyor mu?
          </h2>
          <ul className="mt-8 grid gap-6 md:grid-cols-3">
            {PROBLEMS.map(({ Icon, title, text }) => (
              <li key={title} className="flex flex-col gap-3">
                <span
                  aria-hidden="true"
                  className="flex size-11 items-center justify-center rounded-md bg-info-soft text-primary"
                >
                  <Icon className="size-6" />
                </span>
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="text-base text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      <section aria-labelledby="nasil-baslik">
        <Container className="py-12 lg:py-16">
          <h2 id="nasil-baslik" className="text-2xl font-bold sm:text-3xl">
            Üç adımda ilk raporunuz
          </h2>
          <ol className="mt-8 grid gap-6 md:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="flex flex-col gap-2">
                <span
                  aria-hidden="true"
                  className="num flex size-9 items-center justify-center rounded-full bg-primary text-base font-semibold text-primary-foreground"
                >
                  {index + 1}
                </span>
                <h3 className="text-lg font-semibold">{step.title}</h3>
                <p className="text-base text-muted-foreground">{step.text}</p>
              </li>
            ))}
          </ol>
        </Container>
      </section>

      <section aria-labelledby="ozellik-baslik" className="border-t border-border bg-surface">
        <Container className="py-12 lg:py-16">
          <h2 id="ozellik-baslik" className="text-2xl font-bold sm:text-3xl">
            Ürünün parçaları
          </h2>
          <ul className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map(({ Icon, title, text }) => (
              <li key={title} className="flex flex-col gap-2">
                <Icon className="size-6 text-primary" aria-hidden="true" />
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="text-base text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
          <p className="mt-6">
            <Link
              href={SITE_PAGES.features.path}
              className="inline-flex min-h-touch items-center gap-1 text-primary underline underline-offset-4"
            >
              Tüm özellikler ve neyin hazır olduğu
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </p>
        </Container>
      </section>

      <section aria-labelledby="arac-baslik">
        <Container className="py-12 lg:py-16">
          <h2 id="arac-baslik" className="text-2xl font-bold sm:text-3xl">
            Hesap yapmak için kayıt gerekmez
          </h2>
          <p className="mt-3 max-w-2xl text-base text-muted-foreground">
            Üç hesaplayıcı şimdiden açık. Girdiğiniz rakamlar tarayıcınızda hesaplanır, sunucuya
            gönderilmez.
          </p>
          <ul className="mt-8 grid gap-6 md:grid-cols-3">
            {TOOLS.map(({ page, text }) => (
              <li key={page.path}>
                <Card className="h-full">
                  <CardHeader>
                    <Calculator className="size-6 text-primary" aria-hidden="true" />
                    <CardTitle as="h3" className="text-lg">
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
        </Container>
      </section>

      <section aria-labelledby="guvenlik-baslik" className="border-t border-border bg-surface">
        <Container className="py-12 lg:py-16">
          <h2 id="guvenlik-baslik" className="text-2xl font-bold sm:text-3xl">
            Verileriniz nasıl korunuyor?
          </h2>
          <ul className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {SECURITY_POINTS.map(({ Icon, title, text }) => (
              <li key={title} className="flex flex-col gap-2">
                <Icon className="size-6 text-primary" aria-hidden="true" />
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="text-base text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
          <p className="mt-6">
            <Link
              href={SITE_PAGES.security.path}
              className="inline-flex min-h-touch items-center gap-1 text-primary underline underline-offset-4"
            >
              Güvenlik sayfası: neler uygulanıyor, neler henüz yok
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </p>
        </Container>
      </section>

      <section aria-labelledby="fiyat-baslik">
        <Container className="py-12 lg:py-16">
          <h2 id="fiyat-baslik" className="text-2xl font-bold sm:text-3xl">
            Lansman fiyatı yakında
          </h2>
          <p className="mt-3 max-w-2xl text-base text-muted-foreground">
            Planlar ve fiyatlar henüz kesinleşmedi. Açıklandığında bekleme listesindekilere önce
            haber vereceğiz.
          </p>
          <p className="mt-4">
            <Button asChild variant="secondary">
              <Link href={SITE_PAGES.pricing.path}>Plan taslaklarına bakın</Link>
            </Button>
          </p>
        </Container>
      </section>

      <section aria-labelledby="sss-baslik" className="border-t border-border bg-surface">
        <Container className="py-12 lg:py-16">
          <h2 id="sss-baslik" className="text-2xl font-bold sm:text-3xl">
            Sık sorulanlar
          </h2>
          <div className="mt-8">
            <FaqList entries={homeFaqEntries()} />
          </div>
          <p className="mt-6">
            <Link
              href={SITE_PAGES.faq.path}
              className="inline-flex min-h-touch items-center gap-1 text-primary underline underline-offset-4"
            >
              Tüm sorular
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </p>
        </Container>
      </section>

      <WaitlistSection
        title="Geçen ay gerçekte ne kazandığınızı görün"
        lead="Ürün kapalı beta aşamasında. E-postanızı bırakın, açılışa hazır olduğumuzda size haber verelim."
      />
    </>
  );
}
