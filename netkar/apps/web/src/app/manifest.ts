import type { MetadataRoute } from 'next';

import { brand } from '@/config/brand';

// Servis çalışanı bu aşamada yoktur (bkz. docs/60_tasarim_sistemi.md, "PWA"). Manifest yalnız
// "ana ekrana ekle" deneyimi içindir.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${brand.name}: net kâr takibi`,
    short_name: brand.name,
    description: brand.description,
    lang: 'tr',
    dir: 'ltr',
    start_url: '/panel',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: '#faf8f4',
    theme_color: '#23409a',
    categories: ['business', 'finance'],
    icons: [
      { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
      { src: '/maskable-icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable' },
    ],
  };
}
