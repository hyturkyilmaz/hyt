import * as React from 'react';

import { cn } from '@/lib/utils';

// 16px yazı boyutu: iOS Safari odaklanınca sayfayı yakınlaştırmasın.
const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        'flex min-h-touch w-full rounded-md border border-input-border bg-surface px-3 py-2 text-base text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-2 aria-[invalid=true]:border-loss',
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = 'Input';

export { Input };
