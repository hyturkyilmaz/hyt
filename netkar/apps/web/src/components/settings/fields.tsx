'use client';

import { CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';
import { useId, type ReactNode } from 'react';

import {
  useSettingsWriter,
  type SettingsNotice,
  type SettingsScope,
} from '@/components/settings/settings-writer';
import { cn } from '@/lib/utils';

/** Yerel `<select>` görünümü (ürün listesindeki sıralama seçicisiyle aynı) */
export const SELECT_CLASS =
  'min-h-touch w-full rounded-md border border-input-border bg-surface px-3 text-base text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-2 aria-[invalid=true]:border-loss';

const NOTICE_TONES = {
  success: { Icon: CheckCircle2, className: 'bg-profit-soft text-profit' },
  info: { Icon: Info, className: 'bg-info-soft text-info' },
  warning: { Icon: TriangleAlert, className: 'bg-warning-soft text-warning' },
  error: { Icon: TriangleAlert, className: 'bg-loss-soft text-loss' },
} as const;

/**
 * Bölüme bağlı satır içi bildirim (yalnız toast değil, UX §8.1). Hata ve uyarı `role="alert"`, başarı ve bilgi
 * `role="status"` olarak duyurulur; renk tek başına anlam taşımaz (ikon ve metin).
 */
export function SectionNotice({ scope }: { scope: SettingsScope }) {
  const { notice, dismissNotice } = useSettingsWriter();
  const visible = notice !== null && notice.scope === scope;
  const urgent = visible && (notice.tone === 'error' || notice.tone === 'warning');
  const box = visible ? (
    <NoticeBox tone={notice.tone} text={notice.text} onDismiss={dismissNotice} />
  ) : null;
  return (
    <>
      {/* Boş canlı bölge sayfada kalıcıdır; metin sonradan konunca ekran okuyucular okur (AF-15). Boşken akışa
          boşluk eklemesin diye alttaki eksi kenar boşluğu `gap` aralığını geri alır. */}
      <div role="status" className={visible && !urgent ? undefined : '-mb-4'}>
        {visible && !urgent ? box : null}
      </div>
      {urgent ? <div role="alert">{box}</div> : null}
    </>
  );
}

function NoticeBox({
  tone,
  text,
  onDismiss,
}: {
  tone: SettingsNotice['tone'];
  text: string;
  onDismiss: () => void;
}) {
  const { Icon, className } = NOTICE_TONES[tone];
  return (
    <div className={cn('flex items-start gap-2 rounded-lg p-3 text-sm font-medium', className)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p className="flex-1">{text}</p>
      <button
        type="button"
        onClick={onDismiss}
        className="-m-2 inline-flex size-touch shrink-0 items-center justify-center rounded-md hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="size-4" aria-hidden="true" />
        <span className="sr-only">Bildirimi kapat</span>
      </button>
    </div>
  );
}

export interface ChoiceOption<T extends string> {
  value: T;
  label: string;
  hint?: string;
}

/** Seçenek grubu: yerel radyo düğmeleri, `fieldset` + `legend` ile adlandırılır. */
export function ChoiceGroup<T extends string>({
  legend,
  name,
  value,
  options,
  onChange,
  disabled,
  description,
  error,
}: {
  legend: string;
  name: string;
  value: T;
  options: readonly ChoiceOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  description?: ReactNode;
  /** Sunucu 422 hatası ya da doğrulama iletisi (AF-08); seçeneklere `aria-invalid` ve açıklama bağı konur */
  error?: string;
}) {
  const descriptionId = useId();
  const errorId = useId();
  const describedBy = [error ? errorId : null, description ? descriptionId : null]
    .filter(Boolean)
    .join(' ');
  return (
    <fieldset
      className="flex min-w-0 flex-col gap-2"
      disabled={disabled}
      aria-describedby={describedBy || undefined}
    >
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <label
            key={option.value}
            className="flex min-h-touch cursor-pointer items-start gap-3 rounded-md border border-input-border bg-surface px-3 py-2 text-base has-[:disabled]:cursor-not-allowed has-[:checked]:border-2 has-[:checked]:border-primary has-[:disabled]:opacity-60 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="mt-1.5 size-4 accent-[var(--primary)]"
            />
            <span className="flex flex-col">
              <span>{option.label}</span>
              {option.hint ? (
                <span className="text-sm text-muted-foreground">{option.hint}</span>
              ) : null}
            </span>
          </label>
        ))}
      </div>
      {error ? (
        <p
          id={errorId}
          role="alert"
          className="flex items-start gap-1.5 text-sm font-medium text-loss"
        >
          <span aria-hidden="true" className="mt-0.5 font-bold">
            !
          </span>
          <span>
            <span className="sr-only">Hata: </span>
            {error}
          </span>
        </p>
      ) : null}
      {description ? (
        <p id={descriptionId} className="text-sm text-muted-foreground">
          {description}
        </p>
      ) : null}
    </fieldset>
  );
}

/** Bölüm başlığı: anahtar bağlantılar (`#kargo`) başlığa iner; üst çubuğa yapışmaz. */
export function SectionHeading({
  id,
  title,
  description,
  badge,
  action,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  badge?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          {/* tabIndex -1: yazım sonrası odak buraya döner (settings-writer restoreFocus) */}
          <h2
            id={`${id}-baslik`}
            tabIndex={-1}
            className="rounded-sm text-xl font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {title}
          </h2>
          {badge}
        </div>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
