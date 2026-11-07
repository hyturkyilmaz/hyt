// Pazarlama sayfalarının tek kaynağı: başlık, açıklama, site haritası ve ekmek kırıntısı bunlardan
// üretilir. Başlık sınırı: şablonla birlikte en fazla 60 karakter; açıklama en fazla 155 karakter.
// Ürün adı brand.ts'ten okunur; burada adı yazılmaz.

export interface SitePage {
  path: string;
  /** Sayfa başlığı; kök düzen şablonu "| Ürün adı" ekler (ana sayfada eklenmez) */
  title: string;
  description: string;
  /** Ekmek kırıntısında görünen ad */
  crumb: string;
  /** Gerçek son değişiklik tarihi (YYYY-AA-GG) */
  lastModified: string;
  changeFrequency: 'weekly' | 'monthly' | 'yearly';
  priority: number;
}

/** Sayfalar en son bu tarihte gözden geçirildi (sayfa altındaki "Son güncelleme" ile aynı). */
export const CONTENT_UPDATED = '2026-11-07';

export const SITE_PAGES = {
  home: {
    path: '/',
    title: '',
    description:
      'Trendyol mağazanızın her ürünü için komisyon, KDV, kargo, iade ve reklam sonrası net kârı gösteren uygulama. Bekleme listesi açık.',
    crumb: 'Ana sayfa',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'weekly',
    priority: 1,
  },
  features: {
    path: '/ozellikler',
    title: 'Özellikler: ürün bazında net kâr ve hakediş',
    description:
      'Ürün bazında net kâr, hakediş eşleştirme, iade ve kargo kırılımı, reklam ve uyarılar. Neyin hazır, neyin planda olduğunu açıkça yazdık.',
    crumb: 'Özellikler',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.8,
  },
  pricing: {
    path: '/fiyatlar',
    title: 'Fiyatlar ve bekleme listesi',
    description:
      'Lansman fiyatı henüz açıklanmadı. Plan taslaklarına bakın, bekleme listesine katılın; fiyatlar belli olunca ilk siz öğrenin.',
    crumb: 'Fiyatlar',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.7,
  },
  security: {
    path: '/guvenlik-ve-kvkk',
    title: 'Güvenlik ve KVKK: verileriniz nasıl korunuyor',
    description:
      'API bilgilerinin zarf şifrelemeyle saklanması, kiracı izolasyonu, son müşteri verisinin tutulmaması ve henüz tamamlanmayan işler. Abartısız anlatım.',
    crumb: 'Güvenlik ve KVKK',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.7,
  },
  faq: {
    path: '/sss',
    title: 'Sık sorulan sorular',
    description:
      'Kurulum, veri güvenliği, kâr hesabının yöntemi, fiyat, muhasebeci erişimi ve mobil uygulama hakkında kısa ve doğrudan cevaplar.',
    crumb: 'Sık sorulan sorular',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.6,
  },
  tools: {
    path: '/araclar',
    title: 'Ücretsiz Trendyol satıcı araçları',
    description:
      'Komisyon, net kâr ve desi hesaplayıcıları. Kayıt istemez, girdiğiniz rakamlar tarayıcınızdan çıkmaz, formüller açıkça yazılıdır.',
    crumb: 'Ücretsiz araçlar',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.8,
  },
  commissionTool: {
    path: '/araclar/trendyol-komisyon-hesaplama',
    title: 'Trendyol komisyon hesaplama (2026)',
    description:
      'Satış fiyatı ve komisyon oranını girin; komisyonu, komisyon KDV’sini, stopajı ve hesabınıza geçecek tutarı ayrı ayrı görün. Ücretsiz, kayıtsız.',
    crumb: 'Komisyon hesaplama',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.9,
  },
  profitTool: {
    path: '/araclar/trendyol-kar-hesaplama',
    title: 'Trendyol kâr hesaplama: reklam ve iade dahil',
    description:
      'Satış fiyatı, maliyet, komisyon, kargo, iade payı ve reklamı girin; ürün başına net kârı, marjı ve başabaş fiyatı görün. Ücretsiz, kayıtsız.',
    crumb: 'Kâr hesaplama',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.9,
  },
  desiTool: {
    path: '/araclar/desi-hesaplama',
    title: 'Desi hesaplama: koli ölçülerinden desi',
    description:
      'En, boy, yükseklik ve ağırlığı girin; desiyi ve ücretlendirmeye esas değeri görün. Koli bir santim küçülürse desinin ne olacağını da gösterir.',
    crumb: 'Desi hesaplama',
    lastModified: CONTENT_UPDATED,
    changeFrequency: 'monthly',
    priority: 0.8,
  },
} as const satisfies Record<string, SitePage>;

export type SitePageKey = keyof typeof SITE_PAGES;

export const INDEXABLE_PAGES: readonly SitePage[] = Object.values(SITE_PAGES);

/** Dil ve bölge hazırlığı: yalnız Türkçe yayında. İngilizce sayfalar çevrilince `en` buraya eklenir. */
export const PUBLISHED_LOCALES = ['tr'] as const;
