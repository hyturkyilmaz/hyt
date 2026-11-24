'use client';

import { Loader2 } from 'lucide-react';
import { useId, useState, type FormEvent } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SELECT_CLASS } from '@/components/ui/select-class';
import {
  RULE_NAMES,
  type DeliveryMode,
  type NotificationPreferences,
  type RuleName,
} from '@/lib/api/alerts';
import { RULE_LABELS } from '@/lib/alerts/present';

const CLOCK = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

const MODE_LABELS: Record<DeliveryMode, string> = {
  off: 'Kapalı',
  instant: 'Anında',
  digest: 'Günlük özet',
};
const MODES: readonly DeliveryMode[] = ['off', 'instant', 'digest'];

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const hourLabel = (hour: number) => `${String(hour).padStart(2, '0')}:00`;

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="flex items-start gap-1.5 text-sm font-medium text-loss">
      <span aria-hidden="true" className="mt-0.5 font-bold">
        !
      </span>
      <span>
        <span className="sr-only">Hata: </span>
        {message}
      </span>
    </p>
  );
}

/**
 * Kullanıcı bildirim tercihleri (PUT /v1/me/notification-preferences): 4 kural x e-posta modu, sessiz saatler,
 * özet saati ve e-postada tutar. Anlık bildirim (web push) henüz yok: seçiciler devre dışı ve "Yakında" etiketlidir; sunucudan
 * gelen push değerleri değiştirilmeden geri gönderilir (PUT tam değiştirmedir).
 */
export function PreferencesForm({
  initial,
  saving,
  onSave,
}: {
  initial: NotificationPreferences;
  saving: boolean;
  onSave: (next: NotificationPreferences) => void;
}) {
  const [draft, setDraft] = useState<NotificationPreferences>(initial);
  const [errors, setErrors] = useState<{ quiet_start?: string; quiet_end?: string }>({});
  const ids = {
    quietStart: useId(),
    quietEnd: useId(),
    quietStartErr: useId(),
    quietEndErr: useId(),
    digest: useId(),
    amountsEmail: useId(),
    amountsPush: useId(),
  };

  function setMode(rule: RuleName, mode: DeliveryMode) {
    setDraft((prev) => ({
      ...prev,
      matrix: { ...prev.matrix, [rule]: { ...prev.matrix[rule], email: mode } },
    }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    const next: typeof errors = {};
    if (!CLOCK.test(draft.quiet_start))
      next.quiet_start = 'Başlangıç saatini SS:DD biçiminde yazın. Örnek: 22:00';
    if (!CLOCK.test(draft.quiet_end))
      next.quiet_end = 'Bitiş saatini SS:DD biçiminde yazın. Örnek: 08:00';
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    onSave(draft);
  }

  return (
    <Card as="section" aria-labelledby="tercihler-baslik">
      <CardHeader>
        <CardTitle id="tercihler-baslik">Bildirim tercihleriniz</CardTitle>
        <p className="text-sm text-muted-foreground">
          Yalnız sizin hesabınız için geçerlidir. Uygulama içi uyarılar her zaman açıktır.
        </p>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={submit}
          noValidate
          aria-label="Bildirim tercihleri"
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col gap-4">
            <h3 className="text-lg font-semibold">Kurallar ve kanallar</h3>
            {RULE_NAMES.map((rule) => (
              <RuleRow
                key={rule}
                rule={rule}
                email={draft.matrix[rule].email}
                push={draft.matrix[rule].push}
                onEmail={(mode) => setMode(rule, mode)}
              />
            ))}
          </div>

          <div className="flex flex-col gap-4">
            <h3 className="text-lg font-semibold">Zamanlama</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor={ids.quietStart}>Sessiz saatler: başlangıç</Label>
                <Input
                  id={ids.quietStart}
                  type="time"
                  value={draft.quiet_start}
                  onChange={(e) => setDraft({ ...draft, quiet_start: e.target.value })}
                  aria-invalid={errors.quiet_start ? true : undefined}
                  aria-describedby={errors.quiet_start ? ids.quietStartErr : undefined}
                  className="num"
                />
                <FieldError id={ids.quietStartErr} message={errors.quiet_start} />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor={ids.quietEnd}>Sessiz saatler: bitiş</Label>
                <Input
                  id={ids.quietEnd}
                  type="time"
                  value={draft.quiet_end}
                  onChange={(e) => setDraft({ ...draft, quiet_end: e.target.value })}
                  aria-invalid={errors.quiet_end ? true : undefined}
                  aria-describedby={errors.quiet_end ? ids.quietEndErr : undefined}
                  className="num"
                />
                <FieldError id={ids.quietEndErr} message={errors.quiet_end} />
              </div>
            </div>
            <p className="text-sm text-muted-foreground">
              Saatler İstanbul saatidir. Bu aralıktaki anlık bildirimler aralık bitince tek iletide
              gelir.
            </p>
            <div className="flex max-w-xs flex-col gap-2">
              <Label htmlFor={ids.digest}>Günlük özet saati</Label>
              <select
                id={ids.digest}
                className={SELECT_CLASS}
                value={draft.digest_hour}
                onChange={(e) => setDraft({ ...draft, digest_hour: Number(e.target.value) })}
              >
                {HOURS.map((hour) => (
                  <option key={hour} value={hour}>
                    {hourLabel(hour)}
                  </option>
                ))}
              </select>
              <p className="text-sm text-muted-foreground">
                Yeni uyarı yoksa özet e-postası gönderilmez.
              </p>
            </div>
          </div>

          <fieldset className="flex min-w-0 flex-col gap-3">
            <legend className="mb-1 text-lg font-semibold">Tutar gösterimi</legend>
            <label
              htmlFor={ids.amountsEmail}
              className="flex min-h-touch cursor-pointer items-start gap-3 text-base"
            >
              <input
                id={ids.amountsEmail}
                type="checkbox"
                checked={draft.show_amounts_email}
                onChange={(e) => setDraft({ ...draft, show_amounts_email: e.target.checked })}
                className="mt-1.5 size-4 accent-[var(--primary)]"
              />
              <span>E-postada tutar göster</span>
            </label>
            <label
              htmlFor={ids.amountsPush}
              className="flex min-h-touch items-start gap-3 text-base opacity-60"
            >
              <input
                id={ids.amountsPush}
                type="checkbox"
                checked={draft.show_amounts_push}
                disabled
                className="mt-1.5 size-4 accent-[var(--primary)]"
              />
              <span className="flex flex-wrap items-center gap-2">
                Bildirimde tutar göster (kilit ekranında görünür)
                <Badge variant="neutral">Yakında</Badge>
              </span>
            </label>
          </fieldset>

          <div>
            <Button type="submit" className="w-full sm:w-auto" aria-busy={saving || undefined}>
              {saving ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
              {saving ? 'Kaydediliyor' : 'Tercihleri kaydet'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function RuleRow({
  rule,
  email,
  push,
  onEmail,
}: {
  rule: RuleName;
  email: DeliveryMode;
  push: DeliveryMode;
  onEmail: (mode: DeliveryMode) => void;
}) {
  const legendId = useId();
  const emailId = useId();
  const pushId = useId();
  return (
    <fieldset className="flex min-w-0 flex-col gap-3 border-t border-border pt-4">
      <legend id={legendId} className="text-base font-semibold">
        {RULE_LABELS[rule]}
      </legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label id={emailId} htmlFor={`${emailId}-select`}>
            E-posta
          </Label>
          <select
            id={`${emailId}-select`}
            aria-labelledby={`${legendId} ${emailId}`}
            className={SELECT_CLASS}
            value={email}
            onChange={(e) => onEmail(e.target.value as DeliveryMode)}
          >
            {MODES.map((mode) => (
              <option key={mode} value={mode}>
                {MODE_LABELS[mode]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-2">
          <Label id={pushId} htmlFor={`${pushId}-select`} className="flex items-center gap-2">
            Anlık bildirim
            <Badge variant="neutral">Yakında</Badge>
          </Label>
          <select
            id={`${pushId}-select`}
            aria-labelledby={`${legendId} ${pushId}`}
            className={SELECT_CLASS}
            value={push}
            disabled
          >
            <option value={push}>{MODE_LABELS[push]}</option>
          </select>
        </div>
      </div>
    </fieldset>
  );
}
