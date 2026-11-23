// Backend sözleşmesi: services/api/app/api/v1/push.py ve push_schemas.py (ADR-0009 D8). Gövdeler `extra="forbid"`.
// Uç nokta ve anahtarlar yalnız POST gövdesinde gider; yanıtlar maskelidir (uç nokta dönmez).
import { apiFetch } from '@/lib/api/client';

/** Bayrak kapalıyken (ya da genel anahtar yokken) `enabled: false`; diğer alanlar null. */
export interface VapidKey {
  enabled: boolean;
  public_key: string | null;
  key_id: string | null;
}

export interface PushSubscriptionBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export interface PushSubscriptionInfo {
  id: string;
  endpoint_host: string;
  vapid_key_id: string;
  created_at: string;
  last_success_at: string | null;
}

export const pushApi = {
  vapidKey: (signal?: AbortSignal) => apiFetch<VapidKey>('/push/vapid-public-key', { signal }),

  /** 201 yeni, 200 aynı uç noktanın mevcut aboneliği (idempotent): ikinci çağrı mevcut kimliği verir. */
  subscribe: (body: PushSubscriptionBody) =>
    apiFetch<PushSubscriptionInfo>('/me/push-subscriptions', { method: 'POST', body }),

  /** Kendi aboneliğini iptal eder (silme yok); başkasının kimliği 404. */
  unsubscribe: (id: string) =>
    apiFetch<void>(`/me/push-subscriptions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};
