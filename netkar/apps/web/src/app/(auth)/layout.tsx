import Link from 'next/link';
import type { ReactNode } from 'react';

import { BrandMark, BrandName } from '@/components/brand/brand-mark';

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center px-gutter py-8 sm:justify-center">
      <Link href="/" className="mb-8 inline-flex min-h-touch items-center gap-3 rounded-md">
        <BrandMark />
        <BrandName />
      </Link>
      <main id="main" tabIndex={-1} className="w-full max-w-md focus:outline-none">
        {children}
      </main>
    </div>
  );
}
