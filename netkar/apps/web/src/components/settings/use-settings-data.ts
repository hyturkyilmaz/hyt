'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { authApi } from '@/lib/api/endpoints';
import { profitSettingsApi } from '@/lib/api/profit-settings';
import { todayIstanbul } from '@/lib/profit/settings-input';

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
 * "Bugün" (İstanbul günü): sekme açık kalıp gece yarısı geçince ya da sekmeye dönülünce yenilenir (AF-12). Sunucunun
 * bugünü `SettingsOut` içinde gelince oradan beslenmelidir; o zamana kadar istemci saati kullanılır.
 */
export function useTodayIstanbul(): string {
  const [today, setToday] = useState(() => todayIstanbul());
  useEffect(() => {
    const update = () => setToday(todayIstanbul());
    const timer = window.setInterval(update, 60_000);
    document.addEventListener('visibilitychange', update);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', update);
    };
  }, []);
  return today;
}
