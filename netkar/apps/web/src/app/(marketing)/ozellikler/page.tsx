import type { Metadata } from 'next';
import Link from 'next/link';

import { Container, PageIntro, UpdatedNote } from '@/components/marketing/page-parts';
import { PageJsonLd } from '@/components/seo/page-json-ld';
import { Badge } from '@/components/ui/badge';
import { WaitlistSection } from '@/components/waitlist/waitlist-section';
import { getEnv } from '@/config/env';
import { breadcrumbJsonLd } from '@/lib/seo/jsonld';
import { pageMetadata } from '@/lib/seo/metadata';
import { SITE_PAGES } from '@/lib/seo/pages';

export const metadata: Metadata = pageMetadata('features');

const FEATURES = [
  {
    title: 'Ürün bazında net kâr',
    text: 'Net kâr, KDV hariç net satıştan ürün maliyeti, komisyon, gönderi ve iade kargosu, platform hizmet bedeli ve reklam düşülerek bulunur. KDV ve stopaj kâra girmez, ayrı satırlarda gösterilir. Her kalem kuruşa yuvarlanır ve ekranda topladığınızda net kârı kuruşu kuruşuna bulursunuz.',
  },
  {
    title: 'Tahminden kesine',
    text: 'Sipariş geldiği anda komisyon, kargo ve hizmet bedeli tahmin edilir. Trendyol hakediş ekstresi geldikçe her kalem kendi kaynağından kesinleşir. Her rakamın yanında kaynağı yazar: ekstre, tahmin, sizin girdiğiniz maliyet veya yüklediğiniz reklam raporu.',
  },
  {
    title: 'Hakediş eşleştirme',
    text: 'Ekstre satırları siparişle ve ürünle eşleştirilir. Tahminle ekstre arasında beklenenden fazla fark çıkarsa, örneğin komisyon oranı farklıysa veya kargo desisi değiştiyse, o sipariş ayrıca işaretlenir.',
  },
  {
    title: 'İade ve kargo',
    text: 'Tam ve kısmi iade ayrı işlenir. Gönderi ve iade kargosu siparişe bağlanır, iade edilen ürünün stoğa dönüp dönmediğini siz belirtirsiniz. Çok ürünlü siparişte kargo, desiye veya satışa oranla ürünlere dağıtılır ve “dağıtım” diye etiketlenir.',
  },
  {
    title: 'Reklam ve ROAS',
    text: 'Reklam harcaması için şu an kullanabildiğimiz bir Trendyol API’si yok; panelden indirdiğiniz raporu yüklersiniz. Ürünle eşleşen harcama o ürüne yazılır, eşleşmeyen satışlara oranla dağıtılır ve “tahmini” diye işaretlenir. Her ürün için başabaş ROAS hesaplanır.',
  },
  {
    title: 'Ürün maliyeti',
    text: 'Maliyeti siz girersiniz ve geçerlilik tarihiyle tutarız: eski siparişler eski maliyetle hesaplanır. Maliyeti olmayan ürün için net kâr gösterilmez, sıfır maliyet varsayılmaz; maliyetten önceki katkı gösterilir ve ürün “maliyet eksik” diye işaretlenir.',
  },
  {
    title: 'Uyarılar',
    text: 'Zararına satılan ürünler, komisyon oranındaki farklar, kargo desisindeki değişiklikler ve sınıflandırılamayan kesintiler için uyarı üretilir. Uyarı eşikleri pilot verisiyle ayarlanacak; şimdiki öneri, tahmini tutarın yüzde 5’i ile 5 TL’den büyük olanıdır.',
  },
] as const;

const PLANNED = [
  { title: 'Mobil uygulama ve bildirimler', text: 'Günlük özet ve uyarıların telefona gelmesi.' },
  {
    title: 'Müşteri sorularına yanıt taslağı',
    text: 'Taslak hazırlanır; siz onaylamadan hiçbir yanıt gönderilmez.',
  },
  { title: 'Muhasebeci ve ajans erişimi', text: 'Kapsam ve fiyat henüz kesinleşmedi.' },
  {
    title: 'Diğer pazaryerleri',
    text: 'İlk sürüm yalnız Trendyol. Diğerleri için tarih vermiyoruz.',
  },
] as const;

const PENDING_CONFIRMATION = [
  'Komisyon tutarının KDV içerip içermediği. Şimdilik KDV dahil varsayıyoruz; gerçek komisyon faturalarıyla doğrulayacağız.',
  'Platform hizmet bedelinin sipariş başına mı, satış tutarına bağlı mı kesildiği ve iade edilen siparişte geri verilip verilmediği.',
  'Kargo faturası kalemlerindeki tutarın KDV dahil mi hariç mi geldiği. Hesap, her faturada ekstredeki toplamla karşılaştırarak bunu veriden anlamaya çalışır.',
  'Trendyol karşılamalı indirimlerin satıcı geliri ve stopaj matrahı üzerindeki etkisi.',
  'Reklam raporundaki sütunların adı ve harcamanın KDV durumu.',
] as const;

export default function FeaturesPage() {
  const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;
  return (
    <>
      <PageJsonLd blocks={[breadcrumbJsonLd(siteUrl, ['home', 'features'])]} />
      <Container className="flex flex-col gap-12 py-10 lg:py-14">
        <PageIntro
          trail={['home', 'features']}
          title="Her ürünün size ne bıraktığını gösteren özellikler"
          lead="Uygulama, Trendyol satışlarınızı hakediş ekstrenizle eşleştirir ve her ürünün komisyon, KDV, kargo, iade ve reklam sonrası net kârını gösterir. Aşağıda bunun hangi parçalardan oluştuğunu ve henüz neyin hazır olmadığını yazdık."
        >
          <UpdatedNote />
        </PageIntro>

        <section aria-labelledby="parcalar-baslik">
          <h2 id="parcalar-baslik" className="text-2xl font-bold">
            Ürünün parçaları
          </h2>
          <ul className="mt-6 grid gap-8 md:grid-cols-2">
            {FEATURES.map((feature) => (
              <li key={feature.title}>
                <h3 className="text-xl font-semibold">{feature.title}</h3>
                <p className="mt-2 text-base text-muted-foreground">{feature.text}</p>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="planlanan-baslik">
          <h2 id="planlanan-baslik" className="text-2xl font-bold">
            Planlanan, henüz hazır olmayanlar
          </h2>
          <ul className="mt-6 grid gap-6 md:grid-cols-2">
            {PLANNED.map((item) => (
              <li key={item.title} className="flex flex-col gap-1">
                <p className="flex flex-wrap items-center gap-2 text-lg font-semibold">
                  {item.title}
                  <Badge variant="neutral">Planlanıyor</Badge>
                </p>
                <p className="text-base text-muted-foreground">{item.text}</p>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="teyit-baslik">
          <h2 id="teyit-baslik" className="text-2xl font-bold">
            Teyit beklediğimiz noktalar
          </h2>
          <p className="mt-3 max-w-3xl text-base text-muted-foreground">
            Bazı Trendyol kesintilerinin tam davranışı belgelenmemiş. Bunları gerçek hesap verisiyle
            ve mali müşavir görüşüyle doğrulayana kadar varsayım olarak işaretliyoruz; sonuç
            değişirse hesap güncellenir ve açıkça duyurulur.
          </p>
          <ul className="mt-4 flex max-w-3xl list-disc flex-col gap-2 pl-6 text-base">
            {PENDING_CONFIRMATION.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="mt-6 text-base">
            Aynı kurallarla çalışan{' '}
            <Link
              href={SITE_PAGES.profitTool.path}
              className="text-primary underline underline-offset-4"
            >
              ücretsiz kâr hesaplayıcısını
            </Link>{' '}
            deneyerek hesabın nasıl yapıldığını görebilirsiniz.
          </p>
        </section>
      </Container>
      <WaitlistSection />
    </>
  );
}
