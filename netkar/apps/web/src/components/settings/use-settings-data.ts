'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { authApi } from '@/lib/api/endpoints';
import { profitSettingsApi } from '@/lib/api/profit-settings';
import { advanceServerDay, resolveToday } from '@/lib/profit/settings-server-facts';
import { isDateText, todayIstanbul } from '@/lib/profit/settings-input';

export const settingsKeys = {
  settings: (accountId: string) => ['profit-settings', accountId, 'settings'] as const,
  carriers: (accountId: string) => ['profit-settings', accountId, 'carriers'] as const,
  me: ['me'] as const,
};

export function useSettingsQuery(accountId: string) {
  return useQuery({
    queryKey: settingsKeys.settings(accountId),
    queryFn: ({ signal }) => profitSettingsApi.read(accountId, signal),
  });
}

export function useCarriersQuery(accountId: string) {
  return useQuery({
    queryKey: settingsKeys.carriers(accountId),
    queryFn: ({ signal }) => profitSettingsApi.carriers(accountId, signal),
  });
}

/**
 * Yazma yetkisi: görüntüleyici (`viewer`) yazamaz, sunucu 403 döner (esas olan sunucudur). Rol yüklenirken yazma
 * düğmeleri GÖSTERİLMEZ ve görüntüleyici notu da çıkmaz (AF-10); rol alınamazsa (/me hatası) arayüz engellemez,
 * böylece geçici bir hata formu gizlemez ve yetkisiz yazım sunucuda 403 alır.
 */
export function useEditAccess(): { canEdit: boolean; readOnly: boolean } {
  const me = useQuery({
    queryKey: settingsKeys.me,
    queryFn: () => authApi.me(),
  });
  if (me.isPending) return { canEdit: false, readOnly: false };
  const viewer = me.data?.role === 'viewer';
  return { canEdit: !viewer, readOnly: viewer };
}

/**
 * "Bugün" (İstanbul günü): sunucunun günü (`today_istanbul`) varsa o, yoksa cihaz saati (eski API). Sunucu günü
 * alındığı andaki cihaz günüyle birlikte tutulur; sekme açık kalıp gece yarısı geçince ya da sekmeye dönülünce
 * yalnız geçen gün sayısı kadar ilerler (AF-12); sunucu günü değişince (yeni okuma) demir yenilenir.
 */
export function useTodayIstanbul(serverToday?: string | null): string {
  const [device, setDevice] = useState(() => todayIstanbul());
  const [anchor, setAnchor] = useState<{ server: string; device: string } | null>(null);
  useEffect(() => {
    const update = () => setDevice(todayIstanbul());
    const timer = window.setInterval(update, 60_000);
    document.addEventListener('visibilitychange', update);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', update);
    };
  }, []);
  useEffect(() => {
    setAnchor(
      typeof serverToday === 'string' && isDateText(serverToday)
        ? { server: serverToday, device: todayIstanbul() }
        : null,
    );
  }, [serverToday]);
  // Demir henüz kurulmadıysa (ilk çizim) sunucu günü doğrudan kullanılır
  if (anchor === null) return resolveToday(serverToday, device);
  return advanceServerDay(anchor.server, anchor.device, device);
}
