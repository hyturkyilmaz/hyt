import { describe, expect, it } from 'vitest';

import { brand } from '@/config/brand';
import { allFaqEntries, FAQ_CATEGORIES, homeFaqEntries } from '@/content/faq';

import { formatDateTr } from './date';
import {
  breadcrumbJsonLd,
  faqPageJsonLd,
  softwareApplicationJsonLd,
  webApplicationJsonLd,
} from './jsonld';
import { pageMetadata } from './metadata';
import { INDEXABLE_PAGES, SITE_PAGES, type SitePageKey } from './pages';
import sitemap from '@/app/sitemap';
import robots from '@/app/robots';

const EM_DASH = String.fromCharCode(0x2014);
const KEYS = Object.keys(SITE_PAGES) as SitePageKey[];

describe('sayfa kayıt defteri', () => {
  it('başlık (şablonla) en fazla 60, açıklama en fazla 155 karakter', () => {
    for (const page of INDEXABLE_PAGES) {
      const fullTitle =
        page.title === '' ? `${brand.name}: ${brand.tagline}` : `${page.title} | ${brand.name}`;
      expect(Array.from(fullTitle).length, fullTitle).toBeLessThanOrEqual(60);
      expect(Array.from(page.description).length, page.path).toBeLessThanOrEqual(155);
      expect(page.description.length).toBeGreaterThan(50);
    }
  });

  it('yollar benzersiz, küçük harfli, Türkçe karaktersiz ve sonda eğik çizgisiz', () => {
    const paths = INDEXABLE_PAGES.map((page) => page.path);
    expect(new Set(paths).size).toBe(paths.length);
    for (const path of paths) {
      expect(path).toMatch(/^\/[a-z0-9-/]*$/);
      if (path !== '/') expect(path.endsWith('/')).toBe(false);
    }
  });

  it('başlıklar ve açıklamalar benzersiz; em dash içermez', () => {
    const titles = INDEXABLE_PAGES.map((page) => page.title);
    expect(new Set(titles).size).toBe(titles.length);
    const descriptions = INDEXABLE_PAGES.map((page) => page.description);
    expect(new Set(descriptions).size).toBe(descriptions.length);
    for (const page of INDEXABLE_PAGES) {
      expect(JSON.stringify(page)).not.toContain(EM_DASH);
    }
  });
});

describe('metadata', () => {
  it('kanonik adres, hreflang (tr ve x-default) ve Open Graph üretir', () => {
    for (const key of KEYS) {
      const meta = pageMetadata(key);
      const path = SITE_PAGES[key].path;
      expect(meta.alternates?.canonical).toBe(path);
      expect(meta.alternates?.languages).toEqual({ tr: path, 'x-default': path });
      expect(meta.openGraph).toMatchObject({ url: path, locale: 'tr_TR', siteName: brand.name });
    }
  });

  it('ana sayfa başlığı mutlak, diğerleri şablonla birleşir', () => {
    expect(pageMetadata('home').title).toEqual({ absolute: `${brand.name}: ${brand.tagline}` });
    expect(pageMetadata('faq').title).toBe(SITE_PAGES.faq.title);
  });
});

describe('JSON-LD', () => {
  const site = 'https://netkar.example';

  it('ekmek kırıntısı mutlak adres ve sıra numarası üretir', () => {
    const data = breadcrumbJsonLd(site, ['home', 'tools', 'desiTool']) as {
      itemListElement: { position: number; item: string; name: string }[];
    };
    expect(data.itemListElement.map((item) => item.position)).toEqual([1, 2, 3]);
    expect(data.itemListElement[0]?.item).toBe(site);
    expect(data.itemListElement[2]?.item).toBe(`${site}/araclar/desi-hesaplama`);
  });

  it('SoftwareApplication fiyat (offers) yazmaz', () => {
    const data = softwareApplicationJsonLd(site);
    expect(data['@type']).toBe('SoftwareApplication');
    expect(data).not.toHaveProperty('offers');
  });

  it('WebApplication ücretsiz ve 0 TL teklif içerir', () => {
    const data = webApplicationJsonLd(site, 'commissionTool');
    expect(data).toMatchObject({
      '@type': 'WebApplication',
      isAccessibleForFree: true,
      offers: { price: '0', priceCurrency: 'TRY' },
    });
  });

  it('FAQPage görünür SSS metniyle birebir aynıdır', () => {
    const entries = allFaqEntries();
    const data = faqPageJsonLd(
      entries.map((e) => ({ question: e.question, answer: e.answer })),
    ) as {
      mainEntity: { name: string; acceptedAnswer: { text: string } }[];
    };
    expect(data.mainEntity).toHaveLength(entries.length);
    expect(data.mainEntity.map((q) => q.name)).toEqual(entries.map((e) => e.question));
    expect(data.mainEntity.map((q) => q.acceptedAnswer.text)).toEqual(entries.map((e) => e.answer));
  });
});

describe('SSS içeriği', () => {
  it('kimlikler benzersiz, em dash yok, ana sayfa listesi geçerli', () => {
    const entries = allFaqEntries();
    expect(new Set(entries.map((e) => e.id)).size).toBe(entries.length);
    expect(JSON.stringify(FAQ_CATEGORIES)).not.toContain(EM_DASH);
    expect(homeFaqEntries()).toHaveLength(5);
  });

  it('her cevap ilk cümlede doğrudan yanıt verir (kısa ilk cümle)', () => {
    for (const entry of allFaqEntries()) {
      const first = entry.answer.split(/(?<=[.!?])\s/)[0] ?? '';
      expect(first.length, entry.id).toBeLessThanOrEqual(220);
    }
  });
});

describe('site haritası ve robots', () => {
  it('pazarlama sayfalarını son değişiklik tarihi ve dil alternatifiyle listeler', () => {
    const entries = sitemap();
    const urls = entries.map((entry) => entry.url);
    for (const page of INDEXABLE_PAGES) {
      expect(urls.some((url) => url.endsWith(page.path === '/' ? '' : page.path))).toBe(true);
    }
    const tool = entries.find((entry) => entry.url.endsWith('/araclar/desi-hesaplama'));
    expect(tool?.lastModified).toBeInstanceOf(Date);
    expect(tool?.alternates?.languages).toHaveProperty('x-default');
    // Taslak (noindex) yasal sayfalar haritada yok
    expect(
      urls.some((url) => url.includes('kvkk-aydinlatma') || url.includes('kullanim-kosullari')),
    ).toBe(false);
  });

  it('robots uygulamayı ve API’yi kapatır, site haritasını bildirir', () => {
    const result = robots();
    expect(result.sitemap).toMatch(/\/sitemap\.xml$/);
    const rules = Array.isArray(result.rules) ? result.rules[0] : result.rules;
    expect(rules?.disallow).toEqual(expect.arrayContaining(['/panel', '/api/']));
  });
});

describe('tarih biçimi', () => {
  it('ISO tarihi Türkçe yazar', () => {
    expect(formatDateTr('2026-11-07')).toBe('7 Kasım 2026');
    expect(formatDateTr('2027-01-01')).toBe('1 Ocak 2027');
    expect(() => formatDateTr('2026-13-01')).toThrow(RangeError);
    expect(() => formatDateTr('bozuk')).toThrow(RangeError);
  });
});
