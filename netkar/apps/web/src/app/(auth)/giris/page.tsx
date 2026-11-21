import type { Metadata } from 'next';

import { LoginForm } from '@/components/auth/login-form';
import { safeNextPath } from '@/lib/auth/redirect';

export const metadata: Metadata = { title: 'Giriş yap' };

// ?sonra=<yol>: giriş sonrası dönülecek uygulama içi yol (açık yönlendirme için doğrulanır).
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ sonra?: string | string[]; kayit?: string | string[] }>;
}) {
  const { sonra, kayit } = await searchParams;
  return <LoginForm next={safeNextPath(sonra)} registered={kayit === '1'} />;
}
