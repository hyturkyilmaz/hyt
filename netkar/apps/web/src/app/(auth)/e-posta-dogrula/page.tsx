import type { Metadata } from 'next';

import { EmailVerifyView } from '@/components/auth/email-verify-view';

export const metadata: Metadata = { title: 'E-posta doğrulama', robots: { index: false } };

// E-postadaki bağlantı ?token=... ile gelir. Token biçimi yanlışsa ya da yoksa API'ye gitmeden hata gösterilir.
export default async function EmailVerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  const { token } = await searchParams;
  const value = Array.isArray(token) ? token[0] : token;
  // Backend token şeması 20-200 karakter; yalnız URL güvenli karakterler kabul edilir (şifre sıfırlama ile aynı kural).
  const valid = value && /^[A-Za-z0-9._~-]{20,200}$/.test(value) ? value : null;
  return <EmailVerifyView token={valid} />;
}
