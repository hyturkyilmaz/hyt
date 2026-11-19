import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { PageHeader } from '@/components/panel/page-header';
import { SecurityView } from '@/components/security/security-view';
import { getSession } from '@/lib/api/server';
import { buildLoginUrl } from '@/lib/auth/redirect';

export const metadata: Metadata = { title: 'Güvenlik' };

// Oturum her istekte okunur (panel layout'u gibi); durum sunucudan gelir, tarayıcıda varsayılmaz.
export const dynamic = 'force-dynamic';

export default async function SecurityPage() {
  const session = await getSession();
  if (session.status === 'unauthenticated') redirect(buildLoginUrl('/panel/guvenlik'));
  // API ulaşılamıyorsa panel layout'u zaten hata ekranını gösterir; burada durum bilinmeden form çizilmez.
  if (session.status !== 'authenticated') redirect('/panel/ayarlar');
  const { me } = session;
  return (
    <>
      <PageHeader title="Güvenlik" description="İki adımlı doğrulama ve kurtarma kodlarınız." />
      <SecurityView
        initialTotpEnabled={me.totp_enabled}
        initialRecoveryCodesRemaining={me.recovery_codes_remaining ?? 0}
        emailVerified={me.email_verified}
      />
    </>
  );
}
