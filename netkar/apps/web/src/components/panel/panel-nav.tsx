'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { BrandMark, BrandName } from '@/components/brand/brand-mark';
import { LogoutButton } from '@/components/panel/logout-button';
import { NAV_ITEMS } from '@/components/panel/nav-items';
import { cn } from '@/lib/utils';

function useIsActive() {
  const pathname = usePathname();
  return (href: string) => (href === '/panel' ? pathname === href : pathname.startsWith(href));
}

/** Masaüstü: sol kenar çubuğu (lg ve üstü) */
export function Sidebar({ email, tenantName }: { email: string; tenantName: string }) {
  const isActive = useIsActive();
  return (
    <aside className="fixed inset-y-0 left-0 hidden w-sidebar flex-col border-r border-border bg-surface lg:flex">
      <div className="flex h-16 items-center gap-3 px-5">
        <BrandMark />
        <BrandName />
      </div>
      <nav aria-label="Ana gezinme" className="flex-1 px-3 py-2">
        <ul className="flex flex-col gap-1">
          {NAV_ITEMS.map(({ href, label, Icon }) => {
            const active = isActive(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex min-h-touch items-center gap-3 rounded-md px-3 text-base font-medium',
                    active ? 'bg-info-soft text-primary' : 'text-foreground hover:bg-surface-muted',
                  )}
                >
                  <Icon className="size-5" aria-hidden="true" />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="flex flex-col gap-3 border-t border-border p-4">
        <p className="min-w-0 text-sm">
          <span className="block truncate font-medium">{tenantName}</span>
          <span className="block truncate text-muted-foreground">{email}</span>
        </p>
        <LogoutButton />
      </div>
    </aside>
  );
}

/** Mobil: ekranın altında sabit gezinme (lg altı). Başparmakla ulaşılır, her hedef 44px üstü. */
export function BottomNav() {
  const isActive = useIsActive();
  return (
    <nav
      aria-label="Mobil gezinme"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
    >
      <ul className="mx-auto grid h-bottom-nav max-w-xl grid-cols-5">
        {NAV_ITEMS.map(({ href, label, Icon }) => {
          const active = isActive(href);
          return (
            <li key={href} className="contents">
              <Link
                href={href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex min-h-touch flex-col items-center justify-center gap-1 text-xs font-medium',
                  active ? 'text-primary' : 'text-muted-foreground',
                )}
              >
                <span
                  className={cn(
                    'flex h-7 w-14 items-center justify-center rounded-full',
                    active && 'bg-info-soft',
                  )}
                >
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
