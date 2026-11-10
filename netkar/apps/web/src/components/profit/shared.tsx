import { CircleHelp, TriangleAlert } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ProfitValue } from '@/components/profit-value';
import { Skeleton } from '@/components/ui/skeleton';
import { formatPercent, formatTRY } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  settingsRevisionLabel,
  type BadgeSpec,
  type LossDisplay,
  type MetricDisplay,
  type NetProfitDisplay,
} from '@/lib/profit/present';
import { RANGE_OPTIONS } from '@/lib/profit/query';
import type { RangeName } from '@/lib/api/profit';

export function SpecBadge({ spec, className }: { spec: BadgeSpec; className?: string }) {
  return (
    <Badge variant={spec.tone} className={className}>
      {spec.label}
    </Badge>
  );
}

function Uncomputable({ missing, compact }: { missing: readonly string[]; compact?: boolean }) {
  return (
    <span className="inline-flex flex-col items-start">
      <span className="inline-flex items-center gap-1 font-semibold text-foreground">
        <CircleHelp className="size-[1em] shrink-0" aria-hidden="true" />
        Hesaplanamadı
      </span>
      {missing.length > 0 ? (
        <span className={cn('text-muted-foreground', compact ? 'text-xs' : 'text-sm')}>
          Eksik: {missing.join(', ')}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Net kâr hücresi. Null değer "Hesaplanamadı" (eksik kalem adlarıyla), iptal "İptal" yazar;
 * hiçbir koşulda 0,00 üretmez (denetim kuralları 1 ve 10).
 */
export function NetProfitCell({
  display,
  compact,
  className,
}: {
  display: NetProfitDisplay;
  compact?: boolean;
  className?: string;
}) {
  if (display.kind === 'value') return <ProfitValue value={display.value} className={className} />;
  if (display.kind === 'cancelled') {
    return <span className="font-semibold text-muted-foreground">İptal</span>;
  }
  return <Uncomputable missing={display.missing} compact={compact} />;
}

/** Özet kartı değeri: hesaplanamıyorsa "Hesaplanamadı"; para ya da yüzde. */
export function MetricValue({
  metric,
  kind,
  coloured = false,
}: {
  metric: MetricDisplay;
  kind: 'money' | 'percent';
  coloured?: boolean;
}) {
  if (metric.kind === 'uncomputable') return <Uncomputable missing={metric.missing} />;
  if (coloured) return <ProfitValue value={metric.value} kind={kind} />;
  return (
    <span className="num font-semibold">
      {kind === 'money' ? formatTRY(metric.value) : formatPercent(metric.value)}
    </span>
  );
}

/**
 * Kesin zarardaki ürünün rakamı (UX-07): kırmızı, aşağı ok ve eksi işaretiyle. Net kâr bilinmiyorsa
 * bilinen giderlerle hesaplanan tutar "en az" zarardır.
 */
export function LossAmount({ loss }: { loss: LossDisplay }) {
  if (loss.exact) return <ProfitValue value={loss.amount} />;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1">
      <span className="font-semibold text-loss">En az</span>
      <ProfitValue value={loss.amount} />
      <span className="font-semibold text-loss">zarar</span>
    </span>
  );
}

/** Rapor alt bilgisi: "Ayar sürümü N". Alan yoksa (eski API) hiçbir şey çizilmez. */
export function ReportFooter({ revision }: { revision: number | null | undefined }) {
  const label = settingsRevisionLabel(revision);
  if (!label) return null;
  return <p className="num text-sm text-muted-foreground">{label}</p>;
}

/**
 * Metrik kartı: etiket başlıktır (ekran okuyucu başlık listesinde "Net kâr" duyulur), rakam paragraftır.
 * Görünüm eski düzenle aynıdır: küçük etiket üstte, büyük rakam altta (UX-14).
 */
export function MetricCard({
  label,
  children,
  footer,
  className,
}: {
  label: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle as="h2" className="text-sm font-normal text-muted-foreground">
          {label}
        </CardTitle>
        <p className="flex flex-wrap items-center gap-2 text-2xl font-semibold">{children}</p>
      </CardHeader>
      {footer ? (
        <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
          {footer}
        </CardContent>
      ) : null}
    </Card>
  );
}

export function Money({ value, className }: { value: string; className?: string }) {
  return <span className={cn('num', className)}>{formatTRY(value)}</span>;
}

/** Dönem seçici: bağlantılar URL'deki `range` parametresini değiştirir (geri düğmesi ve paylaşım çalışır). */
export function RangeSwitcher({
  range,
  hrefFor,
}: {
  range: RangeName;
  hrefFor: (range: RangeName) => string;
}) {
  return (
    <nav aria-label="Dönem">
      <ul className="inline-flex list-none gap-1 rounded-lg border border-border bg-surface p-1">
        {RANGE_OPTIONS.map((option) => {
          const active = option.value === range;
          return (
            <li key={option.value}>
              <Link
                href={hrefFor(option.value)}
                replace
                scroll={false}
                aria-current={active ? 'true' : undefined}
                className={cn(
                  'flex min-h-touch min-w-touch items-center justify-center rounded-md px-4 text-base font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  active
                    ? 'bg-primary text-primary-foreground'
                    : 'text-foreground hover:bg-surface-muted',
                )}
              >
                {option.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function ReportError({
  message,
  onRetry,
  title = 'Rapor yüklenemedi',
}: {
  message: string;
  onRetry: () => void;
  title?: string;
}) {
  return (
    <Card role="alert" className="flex flex-col items-start gap-3 p-5 sm:p-6">
      <h2 className="flex items-center gap-2 text-xl font-semibold">
        <TriangleAlert className="size-5 text-loss" aria-hidden="true" />
        {title}
      </h2>
      <p className="text-base text-muted-foreground">{message}</p>
      <Button onClick={onRetry}>Tekrar dene</Button>
    </Card>
  );
}

export function ReportSkeleton({ rows = 3, children }: { rows?: number; children?: ReactNode }) {
  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-4">
      <span className="sr-only">Yükleniyor</span>
      {children}
      <div aria-hidden="true" className="flex flex-col gap-3">
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    </div>
  );
}
