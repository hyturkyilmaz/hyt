import type { MetadataRoute } from 'next';

import { getEnv } from '@/config/env';
import { INDEXABLE_PAGES, PUBLISHED_LOCALES } from '@/lib/seo/pages';

// Site haritası pazarlama sayfalarının kayıt defterinden (lib/seo/pages.ts) üretilir. Taslak yasal
// sayfalar (noindex) ve oturum gerektiren sayfalar girmez. Dil alternatifleri yalnız yayındaki
// dilleri içerir (şimdilik tr; İngilizce çevrilince PUBLISHED_LOCALES'e eklenir).
export default function sitemap(): MetadataRoute.Sitemap {
  const base = getEnv().NEXT_PUBLIC_SITE_URL;
  const url = (path: string) => `${base}${path === '/' ? '' : path}`;

  const marketing = INDEXABLE_PAGES.map((page) => ({
    url: url(page.path) || `${base}/`,
    lastModified: new Date(`${page.lastModified}T00:00:00+03:00`),
    changeFrequency: page.changeFrequency,
    priority: page.priority,
    alternates: {
      languages: {
        ...Object.fromEntries(PUBLISHED_LOCALES.map((locale) => [locale, url(page.path)])),
        'x-default': url(page.path),
      },
    },
  }));

  return [
    ...marketing,
    { url: `${base}/giris`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${base}/kayit`, changeFrequency: 'yearly', priority: 0.5 },
  ];
}
