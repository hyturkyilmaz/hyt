// Backend sözleşmesi: services/api/app/api/v1/alerts.py ve alerts_schemas.py (ADR-0009 D6) ile
// notify_unsubscribe.py. Alan adları şemalarla birebir aynıdır (gövdeler `extra="forbid"`).
// Para ve oranlar Decimal DİZGESİDİR ("5.00"); float'a çevrilmez. Girdide de dizge gönderilir.
import { ApiError, apiFetch, apiFetchResponse, postUnsubscribe } from '@/lib/api/client';

export type RuleName =
  'ZARARINA_SATIS' | 'REKLAM_KARI_YIYOR' | 'BEKLENMEYEN_KESINTI' | 'IADE_ORANI_ARTISI';
export const RULE_NAMES: readonly RuleName[] = [
  'ZARARINA_SATIS',
  'REKLAM_KARI_YIYOR',
  'BEKLENMEYEN_KESINTI',
  'IADE_ORANI_ARTISI',
];

export type EventStatus = 'open' | 'read' | 'muted' | 'resolved';
export type Severity = 'high' | 'medium';
export type Scope = 'product' | 'order_line' | 'account';
export type DeliveryMode = 'off' | 'instant' | 'digest';

export interface AlertEvent {
  id: string;
  rule: RuleName;
  scope: Scope;
  /** `urun:<barkod>`, `satir:<sipariş no>|<paket>|<satır>`, `hesap:*` */
  subject: string;
  severity: Severity;
  status: EventStatus;
  first_seen_at: string;
  last_seen_at: string;
  occurrence_count: number;
  muted_until: string | null;
  resolved_at: string | null;
  /**
   * `{certainty: 'kesin' | 'tahmini', evidence: {...kural kanıt alanları}}` (alert_evaluation.py `event_payload`).
   * Tutarlar metindir; son müşteri verisi içermez.
   */
  payload: Record<string, unknown>;
  payload_version: number;
  data_revision: number;
  settings_revision: number;
}

export interface AlertEventList {
  items: AlertEvent[];
  next_cursor: string | null;
  /** Süzgeçten bağımsız: hesabın açık olay sayısı */
  open_count: number;
  last_evaluated_at: string | null;
  data_revision: number | null;
  settings_revision: number | null;
}

export type TransitionBody = { to: 'read' | 'open' } | { to: 'muted'; muted_days: number };

export interface TransitionResult {
  event: AlertEvent;
  transition_id: string;
}

export interface ReadAllResult {
  updated: number;
  remaining_open: number;
}

export interface AlertSettings {
  loss_min_amount: string;
  ad_share_percent: string;
  ad_min_spend: string;
  deduction_notify_min: string;
  return_min_diff_points: string;
  rules_enabled: RuleName[];
  is_default: boolean;
  updated_at: string | null;
}

export type AlertSettingsBody = Omit<AlertSettings, 'is_default' | 'updated_at'>;

/** GET yanıtı ve `ETag` başlığı: PUT'ta `If-Match` olarak geri gönderilir. */
export interface AlertSettingsRead {
  settings: AlertSettings;
  etag: string;
}

export interface ChannelModes {
  email: DeliveryMode;
  push: DeliveryMode;
}

export type PreferenceMatrix = Record<RuleName, ChannelModes>;

export interface NotificationPreferences {
  matrix: PreferenceMatrix;
  /** Europe/Istanbul duvar saati, `SS:DD` */
  quiet_start: string;
  quiet_end: string;
  digest_hour: number;
  show_amounts_email: boolean;
  show_amounts_push: boolean;
}

export interface UnsubscribeResult {
  rules: string[];
  channel: string;
  mode: string;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

function base(accountId: string): string {
  return `/marketplace-accounts/${encodeURIComponent(accountId)}`;
}

export const alertsApi = {
  events: (
    accountId: string,
    params: { status?: EventStatus; rule?: RuleName; cursor?: string | null; limit?: number },
    signal?: AbortSignal,
  ) => apiFetch<AlertEventList>(`${base(accountId)}/alert-events${query(params)}`, { signal }),

  /** `open`/`read`: tüm roller; `muted` ve `muted -> open`: yalnız owner/admin. Yazma doğrulanmış e-posta ister. */
  transition: (accountId: string, eventId: string, body: TransitionBody) =>
    apiFetch<TransitionResult>(
      `${base(accountId)}/alert-events/${encodeURIComponent(eventId)}/transitions`,
      { method: 'POST', body },
    ),

  /** Açık olayların hepsine `read` ekler (en çok 500; kalan varsa `remaining_open` > 0). */
  readAll: (accountId: string) =>
    apiFetch<ReadAllResult>(`${base(accountId)}/alert-events/read-all`, { method: 'POST' }),

  settings: async (accountId: string, signal?: AbortSignal): Promise<AlertSettingsRead> => {
    const response = await apiFetchResponse(`${base(accountId)}/alert-settings`, { signal });
    const etag = response.headers.get('ETag');
    let settings: AlertSettings;
    try {
      settings = (await response.json()) as AlertSettings;
    } catch {
      throw new ApiError({ status: response.status });
    }
    // ETag'siz yanıt If-Match üretemez: PUT 428 verirdi; yüklemeyi hata sayarız.
    if (!etag) throw new ApiError({ status: response.status });
    return { settings, etag };
  },

  /** Tam değiştirme. `etag` GET'ten gelir; uyuşmazsa 412 `alert-settings-changed`. Yanıtın ETag'i döner. */
  putSettings: async (
    accountId: string,
    body: AlertSettingsBody,
    etag: string,
  ): Promise<AlertSettingsRead> => {
    const response = await apiFetchResponse(`${base(accountId)}/alert-settings`, {
      method: 'PUT',
      body,
      headers: { 'If-Match': etag },
    });
    const next = response.headers.get('ETag');
    let settings: AlertSettings;
    try {
      settings = (await response.json()) as AlertSettings;
    } catch {
      throw new ApiError({ status: response.status });
    }
    if (!next) throw new ApiError({ status: response.status });
    return { settings, etag: next };
  },

  preferences: (signal?: AbortSignal) =>
    apiFetch<NotificationPreferences>('/me/notification-preferences', { signal }),

  putPreferences: (body: NotificationPreferences) =>
    apiFetch<NotificationPreferences>('/me/notification-preferences', { method: 'PUT', body }),
};

export const notificationsApi = {
  /** Tek tık kapatma (oturumsuz, çerezsiz, CSRF'siz); ayrıntı `postUnsubscribe` içinde. */
  unsubscribe: (token: string, signal?: AbortSignal) =>
    postUnsubscribe<UnsubscribeResult>(token, signal),
};
