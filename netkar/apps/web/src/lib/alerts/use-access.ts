'use client';

import { authApi } from '@/lib/api/endpoints';
import { useReportQuery } from '@/lib/profit/use-report-query';

export interface AlertAccess {
  /** Rol okunurken "loading": yönetici eylemleri ne gösterilir ne de not düşülür (yanıp sönme olmaz). */
  status: 'loading' | 'ready' | 'error';
  /** owner ve admin: susturma, susturmayı kaldırma, eşik yazma. Alınamazsa false (güvenli varsayılan). */
  canAdmin: boolean;
  /** E-posta doğrulandı mı; eski API'de alan yoktur ve yalnız açıkça false olan hesap doğrulanmamış sayılır. */
  verified: boolean;
  email: string | null;
}

/**
 * Oturumdaki kullanıcının rolü ve e-posta doğrulama durumu (GET /v1/me). Yalnız denetimleri göstermek ve
 * devre dışı bırakmak içindir; asıl yetki ve doğrulama kapısı sunucudadır (403).
 */
export function useAlertAccess(): AlertAccess {
  const { state } = useReportQuery(true, 'me-alert-access', () => authApi.me());
  if (state.status === 'ready') {
    const role = state.data.role;
    return {
      status: 'ready',
      canAdmin: role === 'owner' || role === 'admin',
      verified: state.data.email_verified !== false,
      email: typeof state.data.email === 'string' ? state.data.email : null,
    };
  }
  if (state.status === 'error') {
    return { status: 'error', canAdmin: false, verified: true, email: null };
  }
  return { status: 'loading', canAdmin: false, verified: true, email: null };
}
