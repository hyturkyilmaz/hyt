import type { Metadata } from 'next';

import { TwoFactorForm } from '@/components/auth/two-factor-form';

export const metadata: Metadata = { title: 'İki adımlı doğrulama', robots: { index: false } };

export default function TwoFactorPage() {
  return <TwoFactorForm />;
}
