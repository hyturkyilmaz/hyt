import * as React from 'react';

import { cn } from '@/lib/utils';

// Yükleme yer tutucusu. Ekran okuyucudan gizlenir; bağlam "role=status" ile duyurulur.
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn('animate-pulse rounded-md bg-surface-muted', className)}
      {...props}
    />
  );
}

export { Skeleton };
