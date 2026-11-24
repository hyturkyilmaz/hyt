'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { CircleCheck, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';

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
import { PasswordInput } from '@/components/ui/password-input';
import { ApiError, describeApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';
import {
  PASSWORD_MIN_LENGTH,
  passwordResetConfirmSchema,
  passwordResetRequestSchema,
  type PasswordResetConfirmValues,
  type PasswordResetRequestValues,
} from '@/lib/validation/auth';

const backToLogin = (
  <Link href="/giris" className="font-medium text-primary underline underline-offset-4">
    Girişe geri dön
  </Link>
);

/** 1. adım: e-posta iste. Yanıt, hesap var olsa da olmasa da aynıdır (hesap sızdırmama). */
export function PasswordResetRequestForm() {
  const [serverError, setServerError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const form = useForm<PasswordResetRequestValues>({
    resolver: zodResolver(passwordResetRequestSchema),
    defaultValues: { email: '' },
  });
  const { isSubmitting } = form.formState;

  async function onSubmit(values: PasswordResetRequestValues) {
    setServerError(null);
    try {
      await authApi.requestPasswordReset(values);
      setSentTo(values.email);
    } catch (error) {
      setServerError(describeApiError(error, 'İstek gönderilemedi. Lütfen tekrar deneyin.'));
    }
  }

  if (sentTo) {
    return (
      <AuthCard title="E-postanızı kontrol edin" footer={backToLogin}>
        <p role="status" className="flex items-start gap-3 text-base">
          <CircleCheck className="mt-0.5 size-5 shrink-0 text-profit" aria-hidden="true" />
          <span>
            <strong className="font-semibold">{sentTo}</strong> adresi kayıtlıysa, parola sıfırlama
            bağlantısını gönderdik. Gelmezse spam klasörüne de bakın.
          </span>
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Parolanızı sıfırlayın"
      description="E-posta adresinizi yazın, size yeni parola belirleyeceğiniz bir bağlantı gönderelim."
      footer={backToLogin}
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
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Gönderiliyor' : 'Bağlantı gönder'}
          </Button>
        </form>
      </Form>
    </AuthCard>
  );
}

/** 2. adım: e-postadaki bağlantıdan gelen token ile yeni parola belirle. */
export function PasswordResetConfirmForm({ token }: { token: string }) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<PasswordResetConfirmValues>({
    resolver: zodResolver(passwordResetConfirmSchema),
    defaultValues: { password: '' },
  });
  const { isSubmitting } = form.formState;

  async function onSubmit(values: PasswordResetConfirmValues) {
    setServerError(null);
    try {
      await authApi.confirmPasswordReset({ token, new_password: values.password });
      toast.success('Parolanız güncellendi. Yeni parolanızla giriş yapabilirsiniz.');
      router.push('/giris');
    } catch (error) {
      const fallback =
        error instanceof ApiError && error.code === 'weak-password'
          ? 'Bu parola bilinen veri sızıntılarında görülmüş. Lütfen farklı bir parola seçin.'
          : error instanceof ApiError && error.code === 'invalid-reset-token'
            ? 'Bu bağlantının süresi dolmuş veya daha önce kullanılmış. Yeni bir bağlantı isteyin.'
            : 'Parola güncellenemedi. Lütfen tekrar deneyin.';
      setServerError(describeApiError(error, fallback));
    }
  }

  return (
    <AuthCard title="Yeni parola belirleyin" footer={backToLogin}>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          <FormError message={serverError} />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Yeni parola</FormLabel>
                <FormControl>
                  <PasswordInput autoComplete="new-password" {...field} />
                </FormControl>
                <FormDescription>En az {PASSWORD_MIN_LENGTH} karakter.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Güncelleniyor' : 'Parolayı güncelle'}
          </Button>
        </form>
      </Form>
    </AuthCard>
  );
}
