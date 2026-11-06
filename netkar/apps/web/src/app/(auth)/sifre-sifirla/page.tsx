import type { Metadata } from 'next';

import {
  PasswordResetConfirmForm,
  PasswordResetRequestForm,
} from '@/components/auth/password-reset-forms';

export const metadata: Metadata = { title: 'Parola sıfırla', robots: { index: false } };

// E-postadaki bağlantı ?token=... ile gelir; token varsa yeni parola formu, yoksa e-posta formu.
export default async function PasswordResetPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  const { token } = await searchParams;
  const value = Array.isArray(token) ? token[0] : token;
  // Backend token şeması 20-200 karakter; makul uzunlukta ve yalnız URL güvenli karakterler içeren token kabul edilir.
  if (value && /^[A-Za-z0-9._~-]{20,200}$/.test(value)) {
    return <PasswordResetConfirmForm token={value} />;
  }
  return <PasswordResetRequestForm />;
}
