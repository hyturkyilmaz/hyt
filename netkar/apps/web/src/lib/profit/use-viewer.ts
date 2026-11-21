'use client';

import { authApi } from '@/lib/api/endpoints';
import { useReportQuery } from '@/lib/profit/use-report-query';

/**
 * Oturumdaki kullanıcı görüntüleyici (salt okunur) rolünde mi. Yalnız metin ve etiket seçimi içindir (esas
 * yetki sunucudadır). Rol yüklenirken ya da alınamazsa false: geçici bir hata etiketleri değiştirmez.
 */
export function useIsViewer(): boolean {
  const { state } = useReportQuery(true, 'me-role', () => authApi.me());
  return state.status === 'ready' && state.data.role === 'viewer';
}

export type WriteAccess = 'loading' | 'editor' | 'viewer' | 'unknown';

/**
 * Yazma denetimleri için üç durumlu rol: yüklenirken "loading" (denetimler devre dışı görünür), alınamazsa
 * "unknown" (güvenli varsayılan: gizlenir), `owner` ve `admin` "editor", diğer her rol "viewer". Esas yetki sunucudadır.
 */
export function useWriteAccess(): { access: WriteAccess; retry: () => void } {
  const { state, retry } = useReportQuery(true, 'me-role', () => authApi.me());
  if (state.status === 'error') return { access: 'unknown', retry };
  if (state.status !== 'ready') return { access: 'loading', retry };
  const role = state.data.role;
  return { access: role === 'owner' || role === 'admin' ? 'editor' : 'viewer', retry };
}
