import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

export interface EmptyStateProps {
  Icon: LucideIcon;
  title: string;
  description: string;
  action?: { href: string; label: string };
  children?: ReactNode;
}

// Boş durum: ne olduğunu, neden boş olduğunu ve bir sonraki adımı söyler.
export function EmptyState({ Icon, title, description, action, children }: EmptyStateProps) {
  return (
    <Card className="flex flex-col items-center gap-4 px-6 py-10 text-center">
      <span
        aria-hidden="true"
        className="flex size-14 items-center justify-center rounded-full bg-info-soft text-primary"
      >
        <Icon className="size-7" />
      </span>
      <div className="flex max-w-md flex-col gap-2">
        <h2 className="text-xl font-semibold">{title}</h2>
        <p className="text-base text-muted-foreground">{description}</p>
      </div>
      {children}
      {action ? (
        <Button asChild>
          <Link href={action.href}>{action.label}</Link>
        </Button>
      ) : null}
    </Card>
  );
}
