import type { Metadata } from 'next';

import { LoginForm } from '@/components/auth/login-form';

export const metadata: Metadata = { title: 'Giriş yap' };

export default function LoginPage() {
  return <LoginForm />;
}
