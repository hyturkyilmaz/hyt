import { brand } from '@/config/brand';
import { cn } from '@/lib/utils';

// Geçici logo: marka adının baş harfi. Gerçek logo gelince yalnız bu bileşen değişir.
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex size-9 items-center justify-center rounded-md bg-primary text-lg font-bold text-primary-foreground',
        className,
      )}
    >
      {brand.initial}
    </span>
  );
}

export function BrandName({ className }: { className?: string }) {
  return (
    <span className={cn('text-lg font-semibold tracking-tight', className)}>{brand.name}</span>
  );
}
