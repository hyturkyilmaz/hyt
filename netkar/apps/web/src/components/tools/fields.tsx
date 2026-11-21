'use client';

import { useId, type ReactNode } from 'react';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

interface FieldFrameProps {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
  optional?: boolean | undefined;
  children: (aria: { describedBy: string | undefined; invalid: boolean }) => ReactNode;
}

// Etiket her zaman görünür; ipucu ve hata aria-describedby ile alana bağlanır (WCAG 3.3.1, 3.3.3).
function FieldFrame({ id, label, hint, error, optional, children }: FieldFrameProps) {
  const hintId = hint ? `${id}-ipucu` : undefined;
  const errorId = error ? `${id}-hata` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>
        {label}
        {optional ? (
          <span className="font-normal text-muted-foreground"> (isteğe bağlı)</span>
        ) : null}
      </Label>
      {children({ describedBy, invalid: Boolean(error) })}
      {error ? (
        <p id={errorId} className="flex items-start gap-1 text-sm font-medium text-loss">
          <span aria-hidden="true">!</span>
          <span>
            <span className="sr-only">Hata: </span>
            {error}
          </span>
        </p>
      ) : null}
      {hint ? (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export interface NumberFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | undefined;
  hint?: string | undefined;
  /** Girdinin sağında gösterilen birim: TL, %, cm, kg */
  suffix?: string | undefined;
  optional?: boolean | undefined;
  autoComplete?: string;
  name?: string;
}

export function NumberField({
  label,
  value,
  onChange,
  error,
  hint,
  suffix,
  optional,
  name,
}: NumberFieldProps) {
  const id = useId();
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error} optional={optional}>
      {({ describedBy, invalid }) => (
        <div className="relative">
          <Input
            id={id}
            name={name}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className={cn('num', suffix ? 'pr-12' : undefined)}
          />
          {suffix ? (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground"
            >
              {suffix}
            </span>
          ) : null}
        </div>
      )}
    </FieldFrame>
  );
}

export interface SelectFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  hint?: string | undefined;
  error?: string | undefined;
}

export function SelectField({ label, value, onChange, options, hint, error }: SelectFieldProps) {
  const id = useId();
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error}>
      {({ describedBy, invalid }) => (
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className="min-h-touch w-full rounded-md border border-input-border bg-surface px-3 py-2 text-base text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background aria-[invalid=true]:border-2 aria-[invalid=true]:border-loss"
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </FieldFrame>
  );
}

export type ResultRowKind = 'plain' | 'deduction' | 'total' | 'info';

export interface ResultRow {
  label: string;
  value: ReactNode;
  kind?: ResultRowKind;
  note?: string;
}

/** Sonuç kırılımı tablosu: etiketler satır başlığıdır, tutarlar sağa yaslıdır. */
export function ResultTable({ caption, rows }: { caption: string; rows: readonly ResultRow[] }) {
  return (
    <table className="w-full border-collapse text-base">
      <caption className="sr-only">{caption}</caption>
      <tbody>
        {rows.map((row) => {
          const kind = row.kind ?? 'plain';
          return (
            <tr
              key={row.label}
              className={cn(
                'border-b border-border last:border-b-0',
                kind === 'total' ? 'bg-surface-muted' : undefined,
              )}
            >
              <th
                scope="row"
                className={cn(
                  'py-2.5 pr-3 text-left align-top font-normal',
                  kind === 'total' ? 'pl-3 font-semibold' : undefined,
                  kind === 'info' ? 'text-sm text-muted-foreground' : undefined,
                )}
              >
                {row.label}
                {row.note ? (
                  <span className="mt-0.5 block text-sm font-normal text-muted-foreground">
                    {row.note}
                  </span>
                ) : null}
              </th>
              <td
                className={cn(
                  'num py-2.5 text-right align-top',
                  kind === 'total' ? 'pr-3 font-semibold' : undefined,
                  kind === 'info' ? 'text-sm text-muted-foreground' : undefined,
                )}
              >
                {row.value}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Kenarlıklı bilgi kutusu: renk tek başına anlam taşımaz, başlık metni durumu söyler. */
export function Callout({
  title,
  tone = 'info',
  children,
}: {
  title: string;
  tone?: 'info' | 'warning';
  children: ReactNode;
}) {
  return (
    <aside
      aria-label={title}
      className={cn(
        'rounded-md border border-border p-4 text-base',
        tone === 'warning' ? 'bg-warning-soft' : 'bg-info-soft',
      )}
    >
      <p className="font-semibold">{title}</p>
      <div className="mt-1 flex flex-col gap-2">{children}</div>
    </aside>
  );
}
