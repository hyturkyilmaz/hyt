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
