'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ApiError, describeApiError } from '@/lib/api/client';
import { pushApi, type VapidKey } from '@/lib/api/push';
import { releasePushSubscription } from '@/lib/push/release';
import {
  SERVICE_WORKER_URL,
  currentSubscription,
  pushSupported,
  toSubscriptionBody,
  urlBase64ToUint8Array,
} from '@/lib/push/browser';

type Phase =
  | { kind: 'loading' }
  // Bayrak kapalı ya da anahtar okunamadı: eski "Yakında" görünümü.
  | { kind: 'soon' }
  | { kind: 'unsupported' }
  | { kind: 'ready'; vapid: VapidKey; subscribed: boolean };

function describePushError(error: unknown): string {
  if (error instanceof ApiError && error.code === 'push-disabled') {
    return 'Anlık bildirim şu an etkin değil.';
  }
  if (error instanceof ApiError && error.code === 'push-subscription-limit') {
    return 'En çok 10 cihazda anlık bildirim açabilirsiniz; önce başka bir cihazda kapatın.';
  }
  if (error instanceof ApiError && error.code === 'push-endpoint-in-use') {
    return 'Bu tarayıcı başka bir kullanıcıya bağlı görünüyor; o kullanıcı çıkış yapınca tekrar deneyin.';
  }
  if (error instanceof ApiError && error.status === 422) {
    return 'Bu tarayıcının anlık bildirim servisi desteklenmiyor.';
  }
  return describeApiError(error, 'Anlık bildirim ayarı değiştirilemedi. Tekrar deneyin.');
}

/**
 * Ayarlar > Bildirimler > Kanallar: bu tarayıcıda anlık bildirimi aç/kapat (ADR-0009 D8). Sunucu bayrağı
 * (`GET /v1/push/vapid-public-key` -> `enabled`) kapalıysa ya da okunamadıysa "Yakında" kalır.
 * İzin isteme ve abonelik YALNIZ düğmeye tıklanınca yapılır; sayfa yüklenirken hiçbir izin istenmez.
 */
export function PushToggle() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      let vapid: VapidKey;
      try {
        vapid = await pushApi.vapidKey(controller.signal);
      } catch {
        if (!controller.signal.aborted) setPhase({ kind: 'soon' });
        return;
      }
      if (controller.signal.aborted) return;
      if (!vapid.enabled || !vapid.public_key) {
        setPhase({ kind: 'soon' });
        return;
      }
      if (!pushSupported()) {
        setPhase({ kind: 'unsupported' });
        return;
      }
      let subscribed = false;
      try {
        subscribed = (await currentSubscription()) !== null;
      } catch {
        subscribed = false;
      }
      if (!controller.signal.aborted) setPhase({ kind: 'ready', vapid, subscribed });
    })();
    return () => controller.abort();
  }, []);

  const enable = useCallback(async (vapid: VapidKey) => {
    if (!vapid.public_key) return;
    // İzin penceresi yalnız bu tıklamadan açılır.
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      setMessage(
        permission === 'denied'
          ? 'Tarayıcı bildirim iznini engelledi. Adres çubuğundaki site ayarlarından izin verip tekrar deneyin.'
          : 'Bildirim izni verilmedi; anlık bildirim açılmadı.',
      );
      return;
    }
    const registration = await navigator.serviceWorker.register(SERVICE_WORKER_URL);
    await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapid.public_key),
    });
    try {
      await pushApi.subscribe(toSubscriptionBody(subscription));
    } catch (error) {
      // Sunucuda kayıt yoksa tarayıcı aboneliği de bırakılır (tutarsız durum kalmasın).
      await subscription.unsubscribe().catch(() => false);
      throw error;
    }
    setPhase({ kind: 'ready', vapid, subscribed: true });
    setMessage('Bu tarayıcıda anlık bildirim açıldı.');
  }, []);

  const disable = useCallback(async (vapid: VapidKey) => {
    // Sunucu hatası olsa da tarayıcı aboneliği bırakılır; hata ayrıca gösterilir.
    const { error } = await releasePushSubscription();
    setPhase({ kind: 'ready', vapid, subscribed: false });
    if (error !== undefined) throw error;
    setMessage('Bu tarayıcıda anlık bildirim kapatıldı.');
  }, []);

  async function toggle() {
    if (phase.kind !== 'ready' || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setMessage(null);
    try {
      if (phase.subscribed) await disable(phase.vapid);
      else await enable(phase.vapid);
    } catch (error) {
      setMessage(describePushError(error));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  if (phase.kind === 'loading')
    return <span className="text-sm text-muted-foreground">Okunuyor</span>;
  if (phase.kind === 'soon') return <Badge variant="neutral">Yakında</Badge>;
  if (phase.kind === 'unsupported') {
    return (
      <p className="text-sm text-muted-foreground">
        Bu tarayıcı anlık bildirimi desteklemiyor. iPhone ve iPad&apos;de yalnız ana ekrana eklenmiş
        uygulamada çalışır.
      </p>
    );
  }
  return (
    <div className="flex flex-col items-start gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={phase.subscribed ? 'profit' : 'neutral'}>
          {phase.subscribed ? 'Açık' : 'Kapalı'}
        </Badge>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void toggle()}
          aria-disabled={busy || undefined}
          disabled={busy}
        >
          {phase.subscribed
            ? 'Bu tarayıcıda anlık bildirimi kapat'
            : 'Bu tarayıcıda anlık bildirimi aç'}
        </Button>
      </div>
      <div role="status" className="text-sm text-muted-foreground">
        {message}
      </div>
    </div>
  );
}
