import type { Metadata } from 'next';

import { UnsubscribeView } from '@/components/auth/unsubscribe-view';

export const metadata: Metadata = {
  title: 'Bildirimi kapat',
  robots: { index: false, follow: false },
  // Token URL'de taşınır: sızmaması için kaynak (referrer) hiç gönderilmez (HTTP başlığı next.config.ts'tedir).
  referrer: 'no-referrer',
};

// E-postadaki "bildirimi kapat" bağlantısı. OTURUM GEREKTİRMEZ: yetki yalnız imzalı token'dan gelir. Sayfa
// açılınca hiçbir istek atılmaz; kapatma kullanıcı düğmeye basınca yapılır. Token sunucuda okunmaz ve bileşene
// prop olarak geçmez; tarayıcıdaki bileşen adresten okur. `#token=` biçiminde token sunucuya hiç gitmez; eski
// `?token=` biçiminde ise istek adresiyle sunucuya gider ve Next ilk RSC verisine girer (ayrıntı:
// components/auth/unsubscribe-view.tsx).
export default function UnsubscribePage() {
  return <UnsubscribeView />;
}
