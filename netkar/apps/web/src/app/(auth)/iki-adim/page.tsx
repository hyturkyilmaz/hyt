import type { Metadata } from 'next';

import { TwoFactorForm } from '@/components/auth/two-factor-form';
import { safeNextPath } from '@/lib/auth/redirect';

export const metadata: Metadata = { title: 'İki adımlı doğrulama', robots: { index: false } };

export default async function TwoFactorPage({
  searchParams,
}: {
  searchParams: Promise<{ sonra?: string | string[] }>;
}) {
  const { sonra } = await searchParams;
  return <TwoFactorForm next={safeNextPath(sonra)} />;
}
