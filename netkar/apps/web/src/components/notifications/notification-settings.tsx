'use client';

import { useEffect, useRef, useState } from 'react';

import { AccessErrorNote, VerifyNote } from '@/components/alerts/verify-note';
import { PreferencesForm } from '@/components/notifications/preferences-form';
import { PushToggle } from '@/components/notifications/push-toggle';
import {
  THRESHOLD_FIELDS,
  ThresholdsForm,
  ThresholdsReadOnly,
  formatThreshold,
} from '@/components/notifications/thresholds-form';
import { NoticeBox, type NoticeTone } from '@/components/panel/notice-box';
import { ReportError, ReportSkeleton } from '@/components/profit/shared';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  alertsApi,
  type AlertSettings,
  type AlertSettingsBody,
  type AlertSettingsRead,
  type RuleName,
  type NotificationPreferences,
} from '@/lib/api/alerts';
import { ApiError } from '@/lib/api/client';
import { describeRateLimitWait } from '@/lib/api/retry-after';
import { RULE_LABELS, describeAlertError } from '@/lib/alerts/present';
import { useAlertAccess, type AlertAccess } from '@/lib/alerts/use-access';
import { formatDateTime } from '@/lib/profit/settings-input';
import { describeReportError } from '@/lib/profit/errors';
import { useReportAccount } from '@/lib/profit/use-account';
import { useReportQuery } from '@/lib/profit/use-report-query';

interface Notice {
  tone: NoticeTone;
  text: string;
}

/** Bölüme bağlı satır içi bildirim (hata `alert`, başarı `status`); yalnız toast'a bırakılmaz. */
function Notices({ notice, onDismiss }: { notice: Notice | null; onDismiss: () => void }) {
  const urgent = notice?.tone === 'error';
  const box = notice ? (
    <NoticeBox tone={notice.tone} text={notice.text} onDismiss={onDismiss} />
  ) : null;
  return (
    <>
      <div role="status">{notice && !urgent ? box : null}</div>
      {urgent ? <div role="alert">{box}</div> : null}
    </>
  );
}

function describeLoadError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return (
      describeRateLimitWait(error.retryAfterSeconds) ??
      'Çok fazla deneme yaptınız. Birkaç dakika sonra tekrar deneyin.'
    );
  }
  return describeReportError(error);
}

/**
 * Ayarlar > Bildirimler (ADR-0009 D7): kullanıcı tercihleri ve hesap eşikleri. Eşikleri yalnız owner/admin
 * yazar; viewer salt okur görür. Doğrulanmamış e-postada yazma düğmeleri aria-disabled kalır.
 */
export function NotificationSettings() {
  const access = useAlertAccess();
  const { state: account } = useReportAccount();

  return (
    <>
      {access.status === 'error' ? <AccessErrorNote /> : null}
      <ChannelsSection access={access} />
      <PreferencesSection />
      <ThresholdsSection access={access} account={account} />
    </>
  );
}

/** Kanallar: e-posta adresi ve doğrulama durumu (GET /v1/me) ve bu tarayıcıda web push (bayrak kapalıyken "Yakında"). */
function ChannelsSection({ access }: { access: AlertAccess }) {
  return (
    <Card as="section" aria-labelledby="kanallar-baslik">
      <CardHeader>
        <CardTitle id="kanallar-baslik">Kanallar</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <dt className="text-sm text-muted-foreground">E-posta</dt>
            <dd className="flex flex-wrap items-center gap-2 text-base">
              {access.email ? <span className="break-all font-medium">{access.email}</span> : null}
              {access.status === 'ready' ? (
                <Badge variant={access.verified ? 'profit' : 'warning'}>
                  {access.verified ? 'Doğrulandı' : 'Doğrulanmadı'}
                </Badge>
              ) : (
                <span className="text-sm text-muted-foreground">
                  {access.status === 'loading' ? 'Okunuyor' : 'Okunamadı'}
                </span>
              )}
            </dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-sm text-muted-foreground">Anlık bildirim (bu cihaz)</dt>
            <dd>
              <PushToggle />
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function PreferencesSection() {
  const { state, retry } = useReportQuery(true, 'notification-preferences', (signal) =>
    alertsApi.preferences(signal),
  );
  const [saved, setSaved] = useState<NotificationPreferences | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const savingRef = useRef(false);

  async function save(next: NotificationPreferences) {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setNotice(null);
    try {
      const result = await alertsApi.putPreferences(next);
      setSaved(result);
      setNotice({ tone: 'success', text: 'Bildirim tercihleriniz kaydedildi.' });
    } catch (error) {
      setNotice({ tone: 'error', text: describePreferencesError(error) });
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  if (state.status === 'loading' || state.status === 'idle') {
    return (
      <section aria-label="Bildirim tercihleriniz">
        <ReportSkeleton rows={3} />
      </section>
    );
  }
  if (state.status === 'error') {
    return (
      <ReportError
        title="Tercihler yüklenemedi"
        message={describeLoadError(state.error)}
        onRetry={retry}
      />
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <PreferencesForm
        initial={saved ?? state.data}
        saving={saving}
        onSave={(next) => void save(next)}
      />
      <Notices notice={notice} onDismiss={() => setNotice(null)} />
    </div>
  );
}

function describePreferencesError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return 'Tercihler kaydedilemedi; değerleri kontrol edip tekrar deneyin.';
  }
  return describeAlertError(error).text;
}

function ThresholdsSection({
  access,
  account,
}: {
  access: AlertAccess;
  account: ReturnType<typeof useReportAccount>['state'];
}) {
  return (
    <Card as="section" aria-labelledby="esikler-baslik">
      <CardHeader>
        <CardTitle id="esikler-baslik">Hesap eşikleri</CardTitle>
        <p className="text-sm text-muted-foreground">
          Mağazanızın tüm kullanıcıları için geçerlidir. Değiştirmek yalnız hesap sahibine ve
          yöneticisine açıktır.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {account.status === 'loading' ? <ReportSkeleton rows={2} /> : null}
        {account.status === 'error' ? (
          <p role="alert" className="text-base text-muted-foreground">
            {describeReportError(account.error)}
          </p>
        ) : null}
        {account.status === 'none' ? (
          <p className="text-base text-muted-foreground">
            Eşikler Trendyol mağazanızı bağlayınca açılır.
          </p>
        ) : null}
        {account.status === 'ready' ? (
          <ThresholdsLoader accountId={account.accountId} access={access} />
        ) : null}
      </CardContent>
    </Card>
  );
}

/** 412 sonrası: kullanıcının gönderemediği değerler ile sunucudaki güncel değerler yan yana. */
interface Conflict {
  rows: { label: string; mine: string; current: string }[];
}

function describeConflict(mine: AlertSettingsBody, current: AlertSettings): Conflict {
  const rows: Conflict['rows'] = [];
  for (const field of THRESHOLD_FIELDS) {
    if (mine[field.name] !== current[field.name]) {
      rows.push({
        label: field.label,
        mine: formatThreshold(field.name, mine[field.name]),
        current: formatThreshold(field.name, current[field.name]),
      });
    }
  }
  const same =
    mine.rules_enabled.length === current.rules_enabled.length &&
    mine.rules_enabled.every((rule) => current.rules_enabled.includes(rule));
  if (!same) {
    const names = (list: readonly RuleName[]) =>
      list.length === 0 ? 'Hiçbiri' : list.map((rule) => RULE_LABELS[rule]).join(', ');
    rows.push({
      label: 'Etkin kurallar',
      mine: names(mine.rules_enabled),
      current: names(current.rules_enabled),
    });
  }
  return { rows };
}

function ThresholdsLoader({ accountId, access }: { accountId: string; access: AlertAccess }) {
  const { state, retry } = useReportQuery(true, `${accountId}|alert-settings`, (signal) =>
    alertsApi.settings(accountId, signal),
  );
  // Gösterilen kayıt ve ETag'i: PUT yanıtı ve 412 sonrası yeniden okuma yenisini verir. İlk yükleme dışında
  // ekran iskelete dönmez; eski veri ekranda kalır ve yeni veri gelince değişir.
  const [current, setCurrent] = useState<AlertSettingsRead | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const savingRef = useRef(false);

  useEffect(() => {
    if (state.status === 'ready') setCurrent(state.data);
  }, [state]);

  function announce(next: Notice) {
    setNotice(next);
    // Bildirim bölgesi sabittir; odak oraya alınır (ekran okuyucu ve klavye kullanıcısı sonucu bulur).
    requestAnimationFrame(() => noticeRef.current?.focus());
  }

  async function save(body: AlertSettingsBody) {
    if (!current || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setNotice(null);
    setConflict(null);
    try {
      const next = await alertsApi.putSettings(accountId, body, current.etag);
      setCurrent(next);
      announce({
        tone: 'success',
        text: 'Eşikler kaydedildi. Uyarılar yeni değerlerle yeniden değerlendirilecek.',
      });
    } catch (error) {
      const described = describeAlertError(error);
      announce({ tone: 'error', text: described.text });
      // 412: başka biri değiştirdi. Güncel değerler ve yeni ETag arka planda okunur; eski veri ekranda kalır.
      if (error instanceof ApiError && error.status === 412) {
        try {
          const fresh = await alertsApi.settings(accountId);
          setCurrent(fresh);
          setConflict(describeConflict(body, fresh.settings));
        } catch (reloadError) {
          announce({
            tone: 'error',
            text: `${described.text} Güncel değerler okunamadı: ${describeAlertError(reloadError).text}`,
          });
        }
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  if (state.status === 'loading' || state.status === 'idle') return <ReportSkeleton rows={3} />;
  if (state.status === 'error' && current === null) {
    return (
      <ReportError
        title="Eşikler yüklenemedi"
        message={describeLoadError(state.error)}
        onRetry={retry}
      />
    );
  }
  const view = current ?? (state.status === 'ready' ? state.data : null);
  if (!view) return null;
  const { settings } = view;
  const editable = access.status === 'ready' && access.canAdmin;
  return (
    <>
      {editable && !access.verified ? (
        <VerifyNote text="E-posta adresinizi doğrulayana dek eşikleri kaydedemezsiniz. Sayfanın üstündeki uyarıdan doğrulama e-postasını yeniden isteyebilirsiniz." />
      ) : null}
      <div ref={noticeRef} tabIndex={-1} className="focus:outline-none">
        <Notices notice={notice} onDismiss={() => setNotice(null)} />
      </div>
      {conflict && conflict.rows.length > 0 ? (
        <section
          aria-label="Sizin değerleriniz ve güncel değerler"
          className="flex flex-col gap-2 rounded-md border border-warning bg-warning-soft p-3 text-sm"
        >
          <h3 className="text-base font-semibold">Sizin değeriniz ve güncel değer</h3>
          <ul role="list" className="flex list-none flex-col gap-1">
            {conflict.rows.map((row) => (
              <li key={row.label}>
                <span className="font-medium">{row.label}:</span> sizin değeriniz{' '}
                <span className="num font-semibold">{row.mine}</span>, güncel değer{' '}
                <span className="num font-semibold">{row.current}</span>
              </li>
            ))}
          </ul>
          <p>Formda güncel değerler var; değişikliğinizi kontrol edip tekrar kaydedin.</p>
        </section>
      ) : null}
      {settings.is_default ? (
        <p className="text-sm text-muted-foreground">
          Henüz kaydedilmiş eşik yok; varsayılan değerler gösteriliyor.
        </p>
      ) : settings.updated_at ? (
        <p className="text-sm text-muted-foreground">
          Son güncelleme:{' '}
          <time dateTime={settings.updated_at}>{formatDateTime(settings.updated_at)}</time>
        </p>
      ) : null}
      {access.status === 'loading' ? null : editable ? (
        <ThresholdsForm
          settings={settings}
          blocked={!access.verified}
          saving={saving}
          onSubmit={(body) => void save(body)}
        />
      ) : access.status === 'ready' ? (
        <>
          <p className="text-sm text-muted-foreground">
            Bu eşikleri hesap sahibi ya da yöneticisi değiştirebilir. Siz yalnız
            görüntüleyebilirsiniz.
          </p>
          <ThresholdsReadOnly settings={settings} />
        </>
      ) : (
        <ThresholdsReadOnly settings={settings} />
      )}
    </>
  );
}
