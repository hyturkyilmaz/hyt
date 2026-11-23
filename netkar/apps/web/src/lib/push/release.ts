import { pushApi } from '@/lib/api/push';
import { currentSubscription, pushSupported, toSubscriptionBody } from '@/lib/push/browser';

/**
 * Bu tarayıcının push aboneliğini bırakır: sunucuda iptal, sonra `subscription.unsubscribe()`.
 * Sunucu hatası olsa bile tarayıcı aboneliği HER ZAMAN bırakılır (paylaşılan cihazda sonraki kişi bildirim görmesin).
 *
 * Kimlik, aynı uç noktayla idempotent `POST` ile bulunur: liste maskelidir (uç nokta dönmez), eşleştirme yapılamaz.
 * Sunucu bu çağrıyı geçerli oturuma bağlar (eski oturumda açılmış satır iptal edilip yenilenir), böylece
 * süresi dolmuş eski oturumdan kalan abonelik de bırakılır.
 */
export async function releasePushSubscription(): Promise<{ released: boolean; error?: unknown }> {
  if (!pushSupported()) return { released: false };
  let subscription: PushSubscription | null;
  try {
    subscription = await currentSubscription();
  } catch (error) {
    return { released: false, error };
  }
  if (!subscription) return { released: false };
  let failure: unknown;
  try {
    const existing = await pushApi.subscribe(toSubscriptionBody(subscription));
    await pushApi.unsubscribe(existing.id);
  } catch (error) {
    failure = error;
  }
  const released = await subscription.unsubscribe().catch(() => false);
  return failure === undefined ? { released } : { released, error: failure };
}
