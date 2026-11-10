// Ürün adının tek kaynağı. Marka adı değiştiğinde yalnız bu dosya (veya
// NEXT_PUBLIC_PRODUCT_NAME ortam değişkeni) güncellenir.
const DEFAULT_PRODUCT_NAME = 'NetTablo';

const rawName = process.env.NEXT_PUBLIC_PRODUCT_NAME?.trim();
const name = rawName && rawName.length > 0 ? rawName : DEFAULT_PRODUCT_NAME;

export const brand = {
  name,
  // PWA ve favicon ikonlarında kullanılan baş harf (Türkçe büyük harf kurallarıyla)
  initial: (Array.from(name)[0] ?? 'N').toLocaleUpperCase('tr-TR'),
  tagline: 'Cironuzu değil, cebinize kalanı gösterir.',
  description:
    'Trendyol mağazanızı bağlayın. Her ürünün komisyon, KDV, kargo, iade ve reklam sonrası net kârını görün.',
  locale: 'tr-TR',
} as const;
