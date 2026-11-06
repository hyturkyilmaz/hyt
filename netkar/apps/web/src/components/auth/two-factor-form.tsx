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
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { ApiError, describeApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';
import { twoFactorSchema, type TwoFactorValues } from '@/lib/validation/auth';

export function TwoFactorForm({ next = '/panel' }: { next?: string }) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<TwoFactorValues>({
    resolver: zodResolver(twoFactorSchema),
    defaultValues: { code: '' },
  });
  const { isSubmitting } = form.formState;

  async function onSubmit(values: TwoFactorValues) {
    setServerError(null);
    try {
      await authApi.verifyTotp({ code: values.code });
      router.replace(next);
      router.refresh();
    } catch (error) {
      // 401 "invalid-code": kod yanlış; 401 "unauthorized": bekleyen giriş çerezi yok veya süresi
      // doldu (5 dakika), yeniden parola ile giriş gerekir.
      const fallback =
        error instanceof ApiError && error.code === 'unauthorized'
          ? 'Doğrulama süresi doldu. Girişe dönüp parolanızı yeniden yazın.'
          : error instanceof ApiError && error.status === 401
            ? 'Kod hatalı. Doğrulama uygulamanızdaki güncel kodu yazın.'
            : 'Kod doğrulanamadı. Lütfen tekrar deneyin.';
      setServerError(describeApiError(error, fallback));
    }
  }

  return (
    <AuthCard
      title="İki adımlı doğrulama"
      description="Doğrulama uygulamanızdaki 6 haneli kodu yazın."
      footer={
        <Link href="/giris" className="font-medium text-primary underline underline-offset-4">
          Girişe geri dön
        </Link>
      }
    >
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          <FormError message={serverError} />
          <FormField
            control={form.control}
            name="code"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Doğrulama kodu</FormLabel>
                <FormControl>
                  <Input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    pattern="[0-9]*"
                    className="num text-center text-2xl tracking-[0.4em]"
                    {...field}
                  />
                </FormControl>
                <FormDescription>Kod 30 saniyede bir yenilenir.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Doğrulanıyor' : 'Doğrula'}
          </Button>
        </form>
      </Form>
    </AuthCard>
  );
}
