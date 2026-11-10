'use client';

import { useQuery } from '@tanstack/react-query';

import { authApi } from '@/lib/api/endpoints';
import { profitSettingsApi } from '@/lib/api/profit-settings';

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
 * Yazma yetkisi: görüntüleyici (`viewer`) yazamaz, sunucu 403 döner. Rol alınamazsa arayüz engellemez
 * (sunucu doğrulaması esastır); böylece geçici bir /me hatası formu gizlemez.
 */
export function useCanEdit(): boolean {
  const me = useQuery({
    queryKey: settingsKeys.me,
    queryFn: () => authApi.me(),
  });
  return me.data?.role !== 'viewer';
}
