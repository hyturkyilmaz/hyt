import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { EmailVerifyView } from '@/components/auth/email-verify-view';
import { getSession } from '@/lib/api/server';
import { buildLoginUrl } from '@/lib/auth/redirect';

export const metadata: Metadata = {
  title: 'E-posta doğrulama',
  robots: { index: false },
  // Token URL'de taşınır: sızmaması için kaynak (referrer) hiç gönderilmez (HTTP başlığı next.config.ts'tedir).
  referrer: 'no-referrer',
};

// E-postadaki bağlantı ?token=... ile gelir. Doğrulama OTURUMLUDUR (API token'ı yalnız kaydeden oturumun
// kullanıcısına ait sayar): oturum yoksa girişe yönlendirilir ve girişten sonra aynı bağlantıya dönülür.
export default async function EmailVerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  const { token } = await searchParams;
  const value = Array.isArray(token) ? token[0] : token;
  // Backend token şeması 20-200 karakter; yalnız URL güvenli karakterler kabul edilir (şifre sıfırlama ile aynı kural).
  const valid = value && /^[A-Za-z0-9._~-]{20,200}$/.test(value) ? value : null;
  if (valid) {
    const session = await getSession();
    if (session.status === 'unauthenticated') {
      // Açık yönlendirme yok: hedef sabit yoldur ve buildLoginUrl içinde yeniden doğrulanır.
      redirect(buildLoginUrl(`/e-posta-dogrula?token=${valid}`));
    }
  }
  return <EmailVerifyView token={valid} />;
}
