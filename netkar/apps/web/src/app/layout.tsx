import type { Metadata, Viewport } from 'next';
import localFont from 'next/font/local';
import { headers } from 'next/headers';
import type { ReactNode } from 'react';

import { JsonLd } from '@/components/brand/json-ld';
import { Toaster } from '@/components/ui/sonner';
import { brand } from '@/config/brand';
import { getEnv } from '@/config/env';

import '@/styles/globals.css';

// Yerelden yüklenen Inter (değişken ağırlık). Türkçe karakterler latin-ext alt kümesindedir.
// Harici font CDN'i kullanılmaz.
const inter = localFont({
  src: [
    {
      path: './fonts/inter-latin-ext-wght-normal.woff2',
      style: 'normal',
      weight: '100 900',
    },
    {
      path: './fonts/inter-latin-wght-normal.woff2',
      style: 'normal',
      weight: '100 900',
    },
  ],
  variable: '--font-sans',
  display: 'swap',
});

const siteUrl = getEnv().NEXT_PUBLIC_SITE_URL;

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: `${brand.name}: ${brand.tagline}`, template: `%s | ${brand.name}` },
  description: brand.description,
  applicationName: brand.name,
  icons: { icon: [{ url: '/icon.svg', type: 'image/svg+xml' }], apple: '/icon.svg' },
  openGraph: {
    type: 'website',
    locale: 'tr_TR',
    siteName: brand.name,
    title: `${brand.name}: ${brand.tagline}`,
    description: brand.description,
    url: '/',
  },
  twitter: {
    card: 'summary',
    title: `${brand.name}: ${brand.tagline}`,
    description: brand.description,
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#faf8f4' },
    { media: '(prefers-color-scheme: dark)', color: '#12120f' },
  ],
};

// CSP nonce'u middleware üretir. Next.js betiklere nonce'u isteğin CSP başlığından alır; bu
// yüzden tüm sayfalar istek anında (dinamik) üretilir. headers() çağrısı bunu garanti eder.
export default async function RootLayout({ children }: { children: ReactNode }) {
  const nonce = (await headers()).get('x-nonce') ?? undefined;

  return (
    <html lang="tr" className={inter.variable}>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-3 focus:text-primary-foreground"
        >
          İçeriğe geç
        </a>
        {children}
        <Toaster />
        <JsonLd
          nonce={nonce}
          data={{
            '@context': 'https://schema.org',
            '@type': 'Organization',
            name: brand.name,
            url: siteUrl,
            logo: `${siteUrl}/icon.svg`,
            description: brand.description,
          }}
        />
      </body>
    </html>
  );
}
