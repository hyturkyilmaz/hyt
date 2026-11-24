import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';

import { cn } from '@/lib/utils';

// Rozet rengi tek başına anlam taşımaz; metin her zaman durumu söyler.
const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium',
  {
    variants: {
      variant: {
        neutral: 'border-border bg-surface-muted text-foreground',
        profit: 'border-transparent bg-profit-soft text-profit',
        loss: 'border-transparent bg-loss-soft text-loss',
        warning: 'border-transparent bg-warning-soft text-warning',
        info: 'border-transparent bg-info-soft text-info',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
