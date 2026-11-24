import { pushApi } from '@/lib/api/push';
import { currentSubscription, pushSupported, toSubscriptionBody } from '@/lib/push/browser';

/**
 * Bu tarayıcının push aboneliğini bırakır: sunucuda iptal, sonra `subscription.unsubscribe()`.
 * Sunucu hatası olsa bile tarayıcı aboneliği HER ZAMAN bırakılır (paylaşılan cihazda sonraki kişi bildirim görmesin).
 *
 * Sunucuda uç noktayla tanımlanan `POST /me/push-subscriptions/release` kullanılır: kimlik aramak için abone
 * olma çağrısı yapılmaz (sahte denetim çifti ve kota harcaması olmaz). Sunucu uç noktayı kanonikleştirir ve
 * oturumdan bağımsız yalnız kullanıcının KENDİ etkin satırını iptal eder; yoksa da 204 döner.
 * `released`: tarayıcı aboneliği gerçekten bırakıldı mı (`unsubscribe()` sonucu).
 */
export async function releasePushSubscription(): Promise<{ released: boolean; error?: unknown }> {
  if (!pushSupported()) return { released: false };
  let subscription: PushSubscription | null;
  try {
    subscription = await currentSubscription();
  } catch (error) {
    return { released: false, error };
  }
  // Bırakılacak tarayıcı aboneliği yok (zaten kapalı): sonuç "bırakıldı" sayılır, sunucuya gidilmez.
  if (!subscription) return { released: true };
  let failure: unknown;
  try {
    const { endpoint } = toSubscriptionBody(subscription);
    await pushApi.release(endpoint);
  } catch (error) {
    failure = error;
  }
  const released = await subscription.unsubscribe().catch(() => false);
  return failure === undefined ? { released } : { released, error: failure };
}
