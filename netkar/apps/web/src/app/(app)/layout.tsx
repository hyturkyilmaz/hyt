import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { BrandMark, BrandName } from '@/components/brand/brand-mark';
import { BottomNav, Sidebar } from '@/components/panel/panel-nav';

// Panel arama motorlarından gizlenir.
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh">
      <Sidebar />
      <div className="lg:pl-sidebar">
        <header className="flex h-14 items-center gap-3 border-b border-border bg-surface px-gutter lg:hidden">
          <BrandMark className="size-8 text-base" />
          <BrandName />
        </header>
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto flex max-w-content flex-col gap-6 px-gutter py-6 pb-[calc(var(--bottom-nav-height)+2rem)] focus:outline-none lg:px-8 lg:py-8 lg:pb-8"
        >
          {children}
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
