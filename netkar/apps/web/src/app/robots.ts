import type { MetadataRoute } from 'next';

import { getEnv } from '@/config/env';

// Arama ve yapay zekâ arama botları pazarlama sayfalarını tarayabilir. Uygulama, API ve oturum
// adımları kapalıdır. Model eğitimi botları (GPTBot, Google-Extended vb.) için karar henüz yok
// (docs/research/06 §6.4); varsayılan "izin" bırakıldı, karar verilince kural eklenir.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: ['/panel', '/api/', '/iki-adim', '/sifre-sifirla'],
    },
    sitemap: `${getEnv().NEXT_PUBLIC_SITE_URL}/sitemap.xml`,
  };
}
