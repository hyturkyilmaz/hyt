// Uyarı olayı, eşik ve tercih sahte verisi (vitest ve Playwright ortak). Alanlar D6 şemalarındadır
// (services/api/app/api/v1/alerts_schemas.py); tutarlar Decimal dizgesidir.
import type {
  AlertEvent,
  AlertEventList,
  AlertSettings,
  NotificationPreferences,
} from '@/lib/api/alerts';

export const EVENT_ID_1 = 'a1111111-1111-4111-8111-111111111111';
export const EVENT_ID_2 = 'a2222222-2222-4222-8222-222222222222';
export const EVENT_ID_3 = 'a3333333-3333-4333-8333-333333333333';

export function makeEvent(over: Partial<AlertEvent> = {}): AlertEvent {
  return {
    id: EVENT_ID_1,
    rule: 'ZARARINA_SATIS',
    scope: 'product',
    subject: 'urun:BRK-0001',
    severity: 'high',
    status: 'open',
    first_seen_at: '2026-11-10T09:05:00+03:00',
    last_seen_at: '2026-11-12T14:30:00+03:00',
    occurrence_count: 2,
    muted_until: null,
    resolved_at: null,
    // Gerçek yük biçimi: services/api alert_evaluation.py `event_payload` ({certainty, evidence})
    payload: {
      certainty: 'kesin',
      evidence: {
        loss_line_count: 3,
        total_loss: '412.30',
        worst_line_loss: '210.00',
        has_missing_items: false,
      },
    },
    payload_version: 1,
    data_revision: 5,
    settings_revision: 7,
    ...over,
  };
}

export function makeEventList(
  items: AlertEvent[] = [makeEvent()],
  over: Partial<AlertEventList> = {},
): AlertEventList {
  return {
    items,
    next_cursor: null,
    open_count: items.filter((e) => e.status === 'open').length,
    last_evaluated_at: '2026-11-13T06:47:00+03:00',
    data_revision: 5,
    settings_revision: 7,
    ...over,
  };
}

export const DEDUCTION_EVENT: AlertEvent = makeEvent({
  id: EVENT_ID_2,
  rule: 'BEKLENMEYEN_KESINTI',
  scope: 'order_line',
  subject: 'satir:7000123|pkg-1|line-1',
  severity: 'medium',
  payload: {
    certainty: 'kesin',
    evidence: { difference: '184.20', threshold: '10.00', default_desi_used: false },
  },
});

export const RETURN_EVENT: AlertEvent = makeEvent({
  id: EVENT_ID_3,
  rule: 'IADE_ORANI_ARTISI',
  scope: 'product',
  subject: 'urun:BRK-0002',
  severity: 'medium',
  payload: {
    // Backend iade olaylarını her zaman `tahmini` yazar (alert_evaluation.event_payload).
    certainty: 'tahmini',
    evidence: { base_rate_percent: '4.10', current_rate_percent: '11.30' },
  },
});

export const SETTINGS_ETAG = '"e-1"';

export function makeAlertSettings(over: Partial<AlertSettings> = {}): AlertSettings {
  return {
    loss_min_amount: '5.00',
    ad_share_percent: '100.00',
    ad_min_spend: '50.00',
    deduction_notify_min: '10.00',
    return_min_diff_points: '5.00',
    rules_enabled: [
      'ZARARINA_SATIS',
      'REKLAM_KARI_YIYOR',
      'BEKLENMEYEN_KESINTI',
      'IADE_ORANI_ARTISI',
    ],
    is_default: false,
    updated_at: '2026-11-01T10:00:00+03:00',
    ...over,
  };
}

export function makePreferences(
  over: Partial<NotificationPreferences> = {},
): NotificationPreferences {
  return {
    matrix: {
      ZARARINA_SATIS: { email: 'digest', push: 'instant' },
      REKLAM_KARI_YIYOR: { email: 'digest', push: 'off' },
      BEKLENMEYEN_KESINTI: { email: 'digest', push: 'instant' },
      IADE_ORANI_ARTISI: { email: 'digest', push: 'off' },
    },
    quiet_start: '22:00',
    quiet_end: '08:00',
    digest_hour: 8,
    show_amounts_email: true,
    show_amounts_push: false,
    ...over,
  };
}
