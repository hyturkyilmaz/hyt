import type { Metadata } from 'next';
import Link from 'next/link';

import { Container, PageIntro, UpdatedNote } from '@/components/marketing/page-parts';
import { PageJsonLd } from '@/components/seo/page-json-ld';
import { Badge } from '@/components/ui/badge';
import { WaitlistSection } from '@/components/waitlist/waitlist-section';
import { getEnv } from '@/config/env';
import { breadcrumbJsonLd } from '@/lib/seo/jsonld';
import { pageMetadata } from '@/lib/seo/metadata';

export const metadata: Metadata = pageMetadata('security');

// İçerik docs/50_guvenlik.md, docs/adr/0001, 0003, 0004 ve services/api kodundaki gerçek
// kontrollerden alınmıştır. Henüz yapılmayanlar ayrı bölümde açıkça yazılır.
const SECTIONS = [
  {
    id: 'erisim',
    title: 'Hangi veriye erişiyoruz?',
    body: [
      'Trendyol’dan sipariş, ürün, iade ve finans (hakediş ve cari hesap) verilerini okuruz. Trendyol’a yalnızca okuma isteği (GET) gönderiliyor; ürün, fiyat veya stok değiştirmiyoruz.',
      'Trendyol’un yanıtlarında müşteriye ait alanlar da bulunur. Bu alanları uygulamamız hiç modele almaz ve kaydetmez: son müşterinin adı, soyadı, e-postası, telefonu, adresi, kimlik veya vergi numarası saklanmaz. Teslimat adresinden yalnızca il bilgisi alınır. Kâr hesabı bunlara ihtiyaç duymaz.',
    ],
  },
  {
    id: 'api-bilgileri',
    title: 'API bilgileriniz nasıl saklanıyor?',
    body: [
      'API anahtarınız ve sırrınız veritabanında düz metin olarak durmaz. Zarf şifreleme kullanıyoruz: her kayıt için rastgele bir veri anahtarı üretilir, değer bu anahtarla AES-256-GCM ile şifrelenir, veri anahtarının kendisi de ayrı bir ana anahtarla şifrelenip yanında saklanır. Ana anahtar veritabanında değil, sunucu ortamında tutulur ve döndürülebilir.',
      'Şifreli değer, ait olduğu kiracıya, mağazaya ve alana bağlıdır. Bir değer başka bir kiracının kaydına kopyalanırsa çözülemez. Anahtarınızın tamamı arayüzde gösterilmez.',
      'Trendyol’un “entegrasyon referans kodunu” istemiyoruz ve saklamıyoruz.',
    ],
  },
  {
    id: 'kiraci-izolasyonu',
    title: 'Mağazaların verisi birbirinden nasıl ayrılıyor?',
    body: [
      'Her müşteri hesabı ayrı bir kiracıdır. Uygulama kodundaki her sorgu kiracıya göre süzülür; buna ek olarak PostgreSQL’in satır düzeyi güvenliği (RLS) ikinci bir kilit olarak çalışır. Kodda bir süzgeç unutulsa bile veritabanı, başka kiracının satırını uygulamaya vermez.',
      'Bu davranış otomatik testlerle sınanır: bir kiracının başka bir kiracının kaynağına erişmeye çalışması 404 ile sonuçlanmalıdır.',
    ],
  },
  {
    id: 'hesap-guvenligi',
    title: 'Hesabınız nasıl korunuyor?',
    body: [
      'Parolalar argon2id ile özetlenir, düz metin saklanmaz. Kayıt sırasında parola, bilinen sızıntı listelerine karşı k-anonimlik yöntemiyle (parolanın kendisi gönderilmeden) kontrol edilir.',
      'Oturum çerezi HttpOnly ve Secure işaretlidir. Durum değiştiren isteklerde CSRF jetonu istenir. Giriş, kayıt ve parola sıfırlama gibi uç noktalarda deneme sayısı sınırlıdır. Sayfalar nonce tabanlı içerik güvenlik politikası (CSP) ve HSTS gibi güvenlik başlıklarıyla sunulur.',
    ],
  },
  {
    id: 'baglanti-kesme',
    title: 'Bağlantıyı nasıl kesersiniz?',
    body: [
      'API bilgileri Trendyol satıcı panelinizde Hesap Bilgilerim altındaki Entegrasyon Bilgileri bölümünde yönetilir. Orada anahtarı yenilediğinizde eski anahtar çalışmaz ve bağlantı o anda sona erer. Uygulama içinden bağlantıyı kaldırma ekranı da açılıştan önce hazır olacak.',
    ],
  },
] as const;

const PENDING = [
  'Bağımsız güvenlik denetimi ve dış sızma testi lansmandan önce yapılacak; henüz yapılmadı.',
  'Ana anahtar şu an sunucu ortamında tutuluyor. Anahtar yönetim hizmetine (KMS) geçiş planlı ama henüz yapılmadı.',
  'İki adımlı doğrulamanın (TOTP) sunucu tarafı hazır; kullanıcı arayüzü henüz yok.',
  'Barındırma bölgesi, alt işleyenler listesi, yurt dışına aktarım dayanağı, saklama ve silme süreleri henüz kesinleşmedi. Kesinleştiğinde bu sayfada ve aydınlatma metninde yazılacak.',
  'KVKK aydınlatma metni ve kullanım koşulları taslaktır; avukat incelemesi bekliyor.',
  'Güvenlik bildirimi için iletişim adresi ve güvenlik.txt lansmandan önce eklenecek.',
] as const;

export default function SecurityPage() {
  const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;
  return (
    <>
      <PageJsonLd blocks={[breadcrumbJsonLd(siteUrl, ['home', 'security'])]} />
      <Container className="flex flex-col gap-12 py-10 lg:py-14">
        <PageIntro
          trail={['home', 'security']}
          title="Verileriniz nasıl korunuyor?"
          lead="Trendyol’dan yalnızca okuyoruz, API bilgilerinizi zarf şifrelemeyle saklıyoruz, mağazaların verisini veritabanı düzeyinde ayırıyoruz ve son müşterinin kişisel verisini hiç kaydetmiyoruz. Bu sayfa bugün gerçekten uygulananları, ayrıca henüz tamamlanmayanları yazar."
        >
          <UpdatedNote />
        </PageIntro>

        {SECTIONS.map((section) => (
          <section
            key={section.id}
            id={section.id}
            aria-labelledby={`${section.id}-baslik`}
            className="scroll-mt-6"
          >
            <h2 id={`${section.id}-baslik`} className="text-2xl font-bold">
              {section.title}
            </h2>
            <div className="mt-3 flex max-w-3xl flex-col gap-3 text-base text-muted-foreground">
              {section.body.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </section>
        ))}

        <section id="henuz-yok" aria-labelledby="henuz-yok-baslik" className="scroll-mt-6">
          <h2
            id="henuz-yok-baslik"
            className="flex flex-wrap items-center gap-3 text-2xl font-bold"
          >
            Henüz tamamlanmayanlar
            <Badge variant="warning">Açık işler</Badge>
          </h2>
          <ul className="mt-4 flex max-w-3xl list-disc flex-col gap-2 pl-6 text-base">
            {PENDING.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>

        <section id="kvkk" aria-labelledby="kvkk-baslik" className="scroll-mt-6">
          <h2 id="kvkk-baslik" className="text-2xl font-bold">
            KVKK
          </h2>
          <div className="mt-3 flex max-w-3xl flex-col gap-3 text-base text-muted-foreground">
            <p>
              Bu sitede yalnızca bekleme listesi için e-posta adresinizi, isteğe bağlı mağaza
              kategorinizi ve aylık sipariş aralığınızı alırız. Ticari elektronik ileti onayı ayrı
              bir kutudur, varsayılan olarak işaretsizdir ve onay vermeseniz de listeye
              katılabilirsiniz.
            </p>
            <p>
              Ayrıntılar için{' '}
              <Link
                href="/kvkk-aydinlatma-metni"
                className="text-primary underline underline-offset-4"
              >
                KVKK aydınlatma metnine
              </Link>{' '}
              bakın. Metin taslaktır ve hukuki inceleme bekliyor.
            </p>
          </div>
        </section>
      </Container>
      <WaitlistSection />
    </>
  );
}
