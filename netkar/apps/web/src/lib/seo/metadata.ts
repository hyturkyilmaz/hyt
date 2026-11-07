import type { Metadata } from 'next';

import { brand } from '@/config/brand';

import { SITE_PAGES, type SitePageKey } from './pages';

/**
 * Sayfa metadata'sı: başlık, açıklama, kanonik adres, hreflang (tr ve x-default) ve Open Graph.
 * Kanonik adres göreli verilir; kök düzendeki metadataBase mutlak adrese çevirir.
 * Yalnız yayında olan diller hreflang'e girer (İngilizce çevrilene kadar eklenmez).
 */
export function pageMetadata(key: SitePageKey): Metadata {
  const page = SITE_PAGES[key];
  const title = page.title === '' ? `${brand.name}: ${brand.tagline}` : page.title;
  const fullTitle = page.title === '' ? title : `${title} | ${brand.name}`;
  return {
    title: page.title === '' ? { absolute: title } : title,
    description: page.description,
    alternates: {
      canonical: page.path,
      languages: { tr: page.path, 'x-default': page.path },
    },
    openGraph: {
      type: 'website',
      locale: 'tr_TR',
      siteName: brand.name,
      title: fullTitle,
      description: page.description,
      url: page.path,
    },
    twitter: { card: 'summary', title: fullTitle, description: page.description },
  };
}
