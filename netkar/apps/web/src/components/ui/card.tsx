import * as React from 'react';

import { cn } from '@/lib/utils';

// `as="section"`: adlandırılmış bölüm (region) olarak duyurulur; `aria-labelledby` yalnız rol taşıyan öğede geçerlidir.
const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { as?: 'div' | 'section' }
>(({ className, as: Tag = 'div', ...props }, ref) => (
  <Tag
    ref={ref}
    className={cn(
      'rounded-lg border border-border bg-surface text-foreground shadow-sm',
      className,
    )}
    {...props}
  />
));
Card.displayName = 'Card';

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex flex-col gap-1.5 p-5 sm:p-6', className)} {...props} />
  ),
);
CardHeader.displayName = 'CardHeader';

// Başlık düzeyi sayfaya göre seçilir (varsayılan h2); görünüm aynı kalır.
const CardTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement> & { as?: 'h1' | 'h2' | 'h3' }
>(({ className, as: Tag = 'h2', ...props }, ref) => (
  <Tag ref={ref} className={cn('text-xl font-semibold', className)} {...props} />
));
CardTitle.displayName = 'CardTitle';

const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p ref={ref} className={cn('text-sm text-muted-foreground', className)} {...props} />
));
CardDescription.displayName = 'CardDescription';

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-5 pt-0 sm:p-6 sm:pt-0', className)} {...props} />
  ),
);
CardContent.displayName = 'CardContent';

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex items-center p-5 pt-0 sm:p-6 sm:pt-0', className)}
      {...props}
    />
  ),
);
CardFooter.displayName = 'CardFooter';

export { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle };
