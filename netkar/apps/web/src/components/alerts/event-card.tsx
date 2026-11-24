'use client';

import { Megaphone, ReceiptText, Undo2, TrendingDown, type LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { useId, useState, type FormEvent } from 'react';

import { blockedClass, blockedProps } from '@/components/alerts/blocked';
import { Money } from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { AlertEvent, RuleName, TransitionBody } from '@/lib/api/alerts';
import {
  MUTE_DEFAULT_DAYS,
  MUTE_MAX_DAYS,
  MUTE_MIN_DAYS,
  RULE_LABELS,
  STATUS_LABELS,
  eventAmount,
  eventNotes,
  eventSentence,
  isEstimated,
  parseMuteDays,
  subjectInfo,
} from '@/lib/alerts/present';
import type { AlertAccess } from '@/lib/alerts/use-access';
import { formatDateTime } from '@/lib/profit/settings-input';
import { cn } from '@/lib/utils';

const RULE_ICON: Record<RuleName, LucideIcon> = {
  ZARARINA_SATIS: TrendingDown,
  REKLAM_KARI_YIYOR: Megaphone,
  BEKLENMEYEN_KESINTI: ReceiptText,
  IADE_ORANI_ARTISI: Undo2,
};

const STATUS_VARIANT = {
  open: 'info',
  read: 'neutral',
  muted: 'warning',
  resolved: 'profit',
} as const;

export const VIEWER_MUTE_NOTE = 'Hesap yöneticiniz susturabilir.';
export const VIEWER_REOPEN_NOTE = 'Hesap yöneticiniz yeniden açabilir.';

function Time({ iso }: { iso: string }) {
  return (
    <time dateTime={iso} className="num">
      {formatDateTime(iso)}
    </time>
  );
}

/**
 * Tek uyarı olayı kartı. Eylemler durum geçişleridir (D6): açık -> okundu | susturulmuş; okundu -> açık |
 * susturulmuş; susturulmuş -> açık (yalnız owner/admin); çözülmüş değişmez. Viewer'a susturma düğmesi yerine
 * not gösterilir; doğrulanmamış e-postada düğmeler aria-disabled kalır.
 */
export function EventCard({
  event,
  access,
  busy,
  onTransition,
}: {
  event: AlertEvent;
  access: AlertAccess;
  /** Bu kartın (ya da toplu) bir isteği sürüyor */
  busy: boolean;
  /** Başarılıysa true döner (susturma formu kapanır) */
  onTransition: (event: AlertEvent, body: TransitionBody) => Promise<boolean>;
}) {
  const Icon = RULE_ICON[event.rule];
  const subject = subjectInfo(event);
  const amount = eventAmount(event);
  const blocked = !access.verified;
  const inactive = blocked || busy;
  const [muteOpen, setMuteOpen] = useState(false);
  const titleId = useId();

  const act = (body: TransitionBody) => {
    if (inactive) return;
    void onTransition(event, body);
  };

  const canRead = event.status === 'open';
  const canReopen = event.status === 'read' || event.status === 'muted';
  const canMute = event.status === 'open' || event.status === 'read';
  const adminReady = access.status === 'ready' && access.canAdmin;
  // Rol okunamadıysa (error) not yok: panel üstündeki "yetki okunamadı" uyarısı geçerlidir.
  const adminNote = access.status === 'ready' && !access.canAdmin;

  return (
    <Card as="section" aria-labelledby={titleId} className="flex w-full flex-col">
      <CardHeader className="gap-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle as="h3" id={titleId} className="flex items-start gap-2 text-lg">
            <Icon
              className={`mt-0.5 size-5 shrink-0 ${event.severity === 'high' ? 'text-loss' : 'text-warning'}`}
              aria-hidden="true"
            />
            <span className="break-words">{RULE_LABELS[event.rule]}</span>
          </CardTitle>
          <div className="flex shrink-0 flex-wrap justify-end gap-1">
            <Badge variant={event.severity === 'high' ? 'loss' : 'warning'}>
              {event.severity === 'high' ? 'Yüksek öncelik' : 'Orta öncelik'}
            </Badge>
            {isEstimated(event) ? <Badge variant="warning">Tahmini</Badge> : null}
            <Badge variant={STATUS_VARIANT[event.status]}>{STATUS_LABELS[event.status]}</Badge>
          </div>
        </div>
        {subject ? <p className="break-all text-base font-medium">{subject.label}</p> : null}
        <p className="break-words text-base text-muted-foreground">{eventSentence(event)}</p>
        {amount ? (
          <p className="text-base">
            {amount.label}: <Money value={amount.value} className="font-semibold" />
          </p>
        ) : null}
        {eventNotes(event).map((note) => (
          <p key={note} className="text-sm text-muted-foreground">
            {note}
          </p>
        ))}
        <p className="text-sm text-muted-foreground">
          İlk görülme: <Time iso={event.first_seen_at} />
        </p>
        <p className="text-sm text-muted-foreground">
          Son görülme: <Time iso={event.last_seen_at} />
        </p>
        {event.status === 'muted' && event.muted_until ? (
          <p className="text-sm text-muted-foreground">
            Susturma bitişi: <Time iso={event.muted_until} />
          </p>
        ) : null}
        {event.status === 'resolved' && event.resolved_at ? (
          <p className="text-sm text-muted-foreground">
            Çözülme: <Time iso={event.resolved_at} />
          </p>
        ) : null}
      </CardHeader>
      <CardContent className="mt-auto flex flex-col gap-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          {subject?.href && subject.linkLabel ? (
            <Button asChild variant="secondary" className="w-full sm:w-auto">
              <Link href={subject.href}>{subject.linkLabel}</Link>
            </Button>
          ) : null}
          {canRead ? (
            <Button
              variant="secondary"
              className={cn('w-full sm:w-auto', blockedClass(blocked))}
              onClick={() => act({ to: 'read' })}
              {...blockedProps(blocked)}
              aria-busy={busy || undefined}
            >
              Okundu işaretle
            </Button>
          ) : null}
          {canReopen && (event.status === 'read' || adminReady) ? (
            <Button
              variant="secondary"
              className={cn('w-full sm:w-auto', blockedClass(blocked))}
              onClick={() => act({ to: 'open' })}
              {...blockedProps(blocked)}
              aria-busy={busy || undefined}
            >
              Yeniden aç
            </Button>
          ) : null}
          {canMute && adminReady ? (
            <Button
              variant="secondary"
              className="w-full sm:w-auto"
              aria-expanded={muteOpen}
              onClick={() => setMuteOpen((value) => !value)}
            >
              Sustur
            </Button>
          ) : null}
        </div>
        {canMute && adminNote ? (
          <p className="text-sm text-muted-foreground">{VIEWER_MUTE_NOTE}</p>
        ) : null}
        {event.status === 'muted' && adminNote ? (
          <p className="text-sm text-muted-foreground">{VIEWER_REOPEN_NOTE}</p>
        ) : null}
        {muteOpen && canMute && adminReady ? (
          <MuteForm
            blocked={blocked}
            busy={busy}
            onCancel={() => setMuteOpen(false)}
            onSubmit={async (days) => {
              if (inactive) return;
              const done = await onTransition(event, { to: 'muted', muted_days: days });
              if (done) setMuteOpen(false);
            }}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

function MuteForm({
  blocked,
  busy,
  onSubmit,
  onCancel,
}: {
  blocked: boolean;
  busy: boolean;
  onSubmit: (days: number) => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState(String(MUTE_DEFAULT_DAYS));
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const hintId = useId();
  const errorId = useId();

  function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = parseMuteDays(text);
    if (!parsed.ok) {
      setError(parsed.message);
      return;
    }
    setError(null);
    void onSubmit(parsed.days);
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label="Uyarıyı sustur"
      className="flex flex-col gap-3 border-t border-border pt-3"
    >
      <div className="flex max-w-xs flex-col gap-2">
        <Label htmlFor={inputId}>Susturma süresi (gün)</Label>
        <Input
          id={inputId}
          inputMode="numeric"
          autoComplete="off"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${hintId} ${errorId}` : hintId}
          className="num"
        />
        <p id={hintId} className="text-sm text-muted-foreground">
          {MUTE_MIN_DAYS} ile {MUTE_MAX_DAYS} gün arasında. Süre dolunca uyarı yeniden açılır.
        </p>
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
      </div>
      <div className="flex flex-col-reverse gap-2 sm:flex-row">
        <Button variant="secondary" onClick={onCancel}>
          Vazgeç
        </Button>
        <Button
          type="submit"
          {...blockedProps(blocked)}
          className={blockedClass(blocked, 'default')}
          aria-busy={busy || undefined}
        >
          Uyarıyı sustur
        </Button>
      </div>
    </form>
  );
}
