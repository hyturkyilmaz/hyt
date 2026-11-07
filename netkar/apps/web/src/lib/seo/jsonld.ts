// Yapılandırılmış veri üreticileri (schema.org). İçerik yalnız koddaki sabitlerden gelir.
import { brand } from '@/config/brand';

import { SITE_PAGES, type SitePageKey } from './pages';

type JsonObject = Record<string, unknown>;

const absolute = (siteUrl: string, path: string) => `${siteUrl}${path === '/' ? '' : path}`;

export function breadcrumbJsonLd(siteUrl: string, keys: readonly SitePageKey[]): JsonObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: keys.map((key, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: SITE_PAGES[key].crumb,
      item: absolute(siteUrl, SITE_PAGES[key].path),
    })),
  };
}

/** Fiyat bilgisi kesin olmadığı için `offers` yazılmaz. */
export function softwareApplicationJsonLd(siteUrl: string): JsonObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: brand.name,
    applicationCategory: 'BusinessApplication',
    operatingSystem: 'Web',
    inLanguage: 'tr',
    url: absolute(siteUrl, '/'),
    description: brand.description,
  };
}

/** Ücretsiz hesaplayıcı sayfaları. */
export function webApplicationJsonLd(siteUrl: string, key: SitePageKey): JsonObject {
  const page = SITE_PAGES[key];
  return {
    '@context': 'https://schema.org',
    '@type': 'WebApplication',
    name: page.crumb,
    applicationCategory: 'BusinessApplication',
    operatingSystem: 'Web',
    inLanguage: 'tr',
    url: absolute(siteUrl, page.path),
    description: page.description,
    isAccessibleForFree: true,
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'TRY' },
  };
}

export interface FaqItem {
  question: string;
  answer: string;
}

/** Yalnız /sss sayfasında kullanılır; görünür metinle birebir aynı olmalıdır. */
export function faqPageJsonLd(items: readonly FaqItem[]): JsonObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: items.map((item) => ({
      '@type': 'Question',
      name: item.question,
      acceptedAnswer: { '@type': 'Answer', text: item.answer },
    })),
  };
}
