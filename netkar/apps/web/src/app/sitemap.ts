import type { MetadataRoute } from 'next';

import { getEnv } from '@/config/env';

export default function sitemap(): MetadataRoute.Sitemap {
  const base = getEnv().NEXT_PUBLIC_SITE_URL;
  return [
    { url: `${base}/`, changeFrequency: 'weekly', priority: 1 },
    { url: `${base}/giris`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${base}/kayit`, changeFrequency: 'yearly', priority: 0.5 },
  ];
}
