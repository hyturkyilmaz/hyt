'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useForm } from 'react-hook-form';

import { AuthCard, FormError } from '@/components/auth/auth-card';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { PasswordInput } from '@/components/ui/password-input';
import { describeApiError, ApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';
import { loginSchema, type LoginValues } from '@/lib/validation/auth';

export function LoginForm() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });
  const { isSubmitting } = form.formState;

  async function onSubmit(values: LoginValues) {
    setServerError(null);
    try {
      const result = await authApi.login(values);
      router.push(result?.two_factor_required ? '/iki-adim' : '/panel');
    } catch (error) {
      // Hesap var mı yok mu sızdırmamak için tek mesaj
      const fallback =
        error instanceof ApiError && (error.status === 401 || error.status === 400)
          ? 'E-posta veya parola hatalı. Kontrol edip tekrar deneyin.'
          : 'Giriş yapılamadı. Lütfen tekrar deneyin.';
      setServerError(describeApiError(error, fallback));
    }
  }

  return (
    <AuthCard
      title="Giriş yapın"
      description="Hesabınıza e-posta ve parolanızla girin."
      footer={
        <>
          Hesabınız yok mu?{' '}
          <Link href="/kayit" className="font-medium text-primary underline underline-offset-4">
            Kayıt olun
          </Link>
        </>
      }
    >
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          <FormError message={serverError} />
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>E-posta</FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    inputMode="email"
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Parola</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="current-password" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <div className="flex justify-end">
            <Link
              href="/sifre-sifirla"
              className="inline-flex min-h-touch items-center text-sm font-medium text-primary underline underline-offset-4"
            >
              Parolamı unuttum
            </Link>
          </div>
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Giriş yapılıyor' : 'Giriş yap'}
          </Button>
        </form>
      </Form>
    </AuthCard>
  );
}
