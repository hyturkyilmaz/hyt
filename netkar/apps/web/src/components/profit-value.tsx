import { Minus, TrendingDown, TrendingUp } from 'lucide-react';

import { formatPercent, formatTRY, getSign } from '@/lib/format';
import type { DecimalInput } from '@/lib/decimal';
import { cn } from '@/lib/utils';

export interface ProfitValueProps {
  /** Decimal string önerilir ("-124.50") */
  value: DecimalInput;
  /** money: ₺ biçimi, percent: yüzde puanı biçimi */
  kind?: 'money' | 'percent';
  /** Para için: ₺ simgesi mi, "TL" metni mi */
  currencyStyle?: 'symbol' | 'code';
  /** Pozitif değerlerde + işareti */
  signed?: boolean;
  /** İkonu gizle (yoğun tablolarda renk + işaret + metin yeterli kalır) */
  hideIcon?: boolean;
  className?: string;
}

const STATES = {
  positive: { label: 'Kâr', Icon: TrendingUp, tone: 'text-profit' },
  negative: { label: 'Zarar', Icon: TrendingDown, tone: 'text-loss' },
  zero: { label: 'Kâr zarar yok', Icon: Minus, tone: 'text-muted-foreground' },
} as const;

/**
 * Kâr, zarar ve sıfırı üç kanalla gösterir: renk, ikon ve ekran okuyucu metni.
 * Renk körlüğünde ve gri tonlamada anlam kaybolmaz.
 */
export function ProfitValue({
  value,
  kind = 'money',
  currencyStyle = 'symbol',
  signed = false,
  hideIcon = false,
  className,
}: ProfitValueProps) {
  const sign = getSign(value, kind === 'money' ? 2 : 1);
  const { label, Icon, tone } = STATES[sign];

  const text =
    kind === 'money'
      ? formatTRY(value, { style: currencyStyle, signed })
      : formatPercent(value, { signed });

  return (
    <span
      className={cn(
        'num inline-flex items-center gap-1 whitespace-nowrap font-semibold',
        tone,
        className,
      )}
      data-sign={sign}
    >
      {hideIcon ? null : <Icon className="size-[1em] shrink-0" aria-hidden="true" />}
      <span className="sr-only">{label}: </span>
      <span>{text}</span>
    </span>
  );
}
