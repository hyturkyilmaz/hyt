import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { redirect } from 'next/navigation';
import type { ReactNode } from 'react';

import { BrandMark, BrandName } from '@/components/brand/brand-mark';
import { LogoutButton } from '@/components/panel/logout-button';
import { BottomNav, Sidebar } from '@/components/panel/panel-nav';
import { Button } from '@/components/ui/button';
import { getSession } from '@/lib/api/server';
import { PATH_HEADER } from '@/lib/auth/constants';
import { buildLoginUrl, safeNextPath } from '@/lib/auth/redirect';

// Panel arama motorlarından gizlenir.
export const metadata: Metadata = { robots: { index: false, follow: false } };

// Oturum her istekte doğrulanır; önbelleğe alınmaz.
export const dynamic = 'force-dynamic';

export default async function AppLayout({ children }: { children: ReactNode }) {
  // İkinci ve asıl kapı: middleware yalnız çerezin varlığına bakar, burada GET /v1/me ile doğrulanır.
  const session = await getSession();
  const currentPath = (await headers()).get(PATH_HEADER);

  if (session.status === 'unauthenticated') {
    redirect(buildLoginUrl(currentPath));
  }

  if (session.status === 'unavailable') {
    // API ulaşılamıyorsa oturumu düşürmeyiz; kullanıcıya tekrar denemesini söyleriz.
    return (
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto flex min-h-dvh max-w-md flex-col items-start justify-center gap-4 px-gutter focus:outline-none"
      >
        <h1 className="text-2xl font-bold">Hesabınıza şu an ulaşılamıyor</h1>
        <p className="text-base text-muted-foreground">
          Sunucuya bağlanırken bir sorun oluştu. Oturumunuz açık kalır; birkaç saniye sonra tekrar
          deneyin.
        </p>
        <Button asChild>
          <a href={safeNextPath(currentPath)}>Tekrar dene</a>
        </Button>
      </main>
    );
  }

  const { me } = session;
  return (
    <div className="min-h-dvh">
      <Sidebar email={me.email} tenantName={me.tenant.name} />
      <div className="lg:pl-sidebar">
        <header className="flex h-14 items-center gap-3 border-b border-border bg-surface px-gutter lg:hidden">
          <BrandMark className="size-8 text-base" />
          <BrandName />
          <LogoutButton variant="icon" className="ml-auto" />
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
