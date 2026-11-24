// Tarayıcı push yardımcıları. İzin isteme ve abonelik YALNIZ kullanıcı tıklamasından çağrılır (bileşen sözleşmesi).

/** Servis çalışanı betiği (apps/web/public/sw.js); kapsam kök. */
export const SERVICE_WORKER_URL = '/sw.js';

/** Push için gereken üç API var mı (iOS'ta yalnız ana ekrana eklenmiş uygulamada bulunur). */
export function pushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

/** VAPID genel anahtarı (base64url) -> `applicationServerKey` baytları. Biçim bozuksa hata atar. */
export function urlBase64ToUint8Array(value: string): Uint8Array<ArrayBuffer> {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error('VAPID anahtarı geçersiz');
  const padded =
    value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (value.length % 4)) % 4);
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** Tarayıcı aboneliğini API gövdesine çevirir (`toJSON()` anahtarları dolgusuz base64url verir). */
export function toSubscriptionBody(subscription: PushSubscription): {
  endpoint: string;
  keys: { p256dh: string; auth: string };
} {
  const json = subscription.toJSON();
  const p256dh = json.keys?.p256dh;
  const auth = json.keys?.auth;
  if (!json.endpoint || !p256dh || !auth) throw new Error('Abonelik eksik');
  return { endpoint: json.endpoint, keys: { p256dh, auth } };
}

/** Kayıtlı servis çalışanı varsa onun aboneliği; yoksa null (burada yeni kayıt YAPILMAZ). */
export async function currentSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.getRegistration(SERVICE_WORKER_URL);
  return registration ? registration.pushManager.getSubscription() : null;
}
