'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
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
import { stripTokenCarryingNext } from '@/lib/auth/redact-url';
import {
  recoveryCodeSchema,
  twoFactorSchema,
  type RecoveryCodeValues,
  type TwoFactorValues,
} from '@/lib/validation/auth';

type Mode = 'totp' | 'recovery';

export function TwoFactorForm({ next = '/panel' }: { next?: string }) {
  const [mode, setMode] = useState<Mode>('totp');

  // /iki-adim?sonra=/e-posta-dogrula?token=... : token geçmişte kalmasın (hedef props'ta tutulur).
  useEffect(() => {
    stripTokenCarryingNext();
  }, []);

  return mode === 'totp' ? (
    <TotpCodeForm next={next} onUseRecovery={() => setMode('recovery')} />
  ) : (
    <RecoveryCodeForm next={next} onUseTotp={() => setMode('totp')} />
  );
}

/** İkinci adım hatasını Türkçe cümleye çevirir (kilit 429 describeApiError içinde). */
function describeSecondStepError(error: unknown, invalidMessage: string): string {
  // 401 "invalid-code": kod yanlış; 401 "unauthorized": bekleyen giriş çerezi yok veya süresi
  // doldu (5 dakika), yeniden parola ile giriş gerekir.
  if (error instanceof ApiError && error.code === 'totp-locked') {
    const minutes = error.retryAfterSeconds ? Math.ceil(error.retryAfterSeconds / 60) : null;
    return minutes
      ? `Çok fazla hatalı deneme yapıldı. Yaklaşık ${minutes} dakika sonra tekrar deneyin.`
      : 'Çok fazla hatalı deneme yapıldı. Biraz sonra tekrar deneyin.';
  }
  const fallback =
    error instanceof ApiError && error.code === 'unauthorized'
      ? 'Doğrulama süresi doldu. Girişe dönüp parolanızı yeniden yazın.'
      : error instanceof ApiError && error.status === 401
        ? invalidMessage
        : 'Kod doğrulanamadı. Lütfen tekrar deneyin.';
  return describeApiError(error, fallback);
}

function BackToLogin() {
  return (
    <Link href="/giris" className="font-medium text-primary underline underline-offset-4">
      Girişe geri dön
    </Link>
  );
}

function TotpCodeForm({ next, onUseRecovery }: { next: string; onUseRecovery: () => void }) {
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
      setServerError(
        describeSecondStepError(error, 'Kod hatalı. Doğrulama uygulamanızdaki güncel kodu yazın.'),
      );
    }
  }

  return (
    <AuthCard
      title="İki adımlı doğrulama"
      description="Doğrulama uygulamanızdaki 6 haneli kodu yazın."
      footer={<BackToLogin />}
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
          <Button variant="link" onClick={onUseRecovery} className="min-h-touch self-center">
            Kurtarma kodu kullan
          </Button>
        </form>
      </Form>
    </AuthCard>
  );
}

function RecoveryCodeForm({ next, onUseTotp }: { next: string; onUseTotp: () => void }) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<RecoveryCodeValues>({
    resolver: zodResolver(recoveryCodeSchema),
    defaultValues: { code: '' },
  });
  const { isSubmitting } = form.formState;

  async function onSubmit(values: RecoveryCodeValues) {
    setServerError(null);
    try {
      await authApi.verifyTotp({ code: values.code });
      router.replace(next);
      router.refresh();
    } catch (error) {
      setServerError(
        describeSecondStepError(
          error,
          'Kurtarma kodu hatalı ya da daha önce kullanılmış. Kayıtlı kodlarınızdan kullanılmamış birini yazın.',
        ),
      );
    }
  }

  return (
    <AuthCard
      title="Kurtarma kodu ile giriş"
      description="Kurulum sırasında kaydettiğiniz kurtarma kodlarından birini yazın. Her kod yalnız bir kez çalışır."
      footer={<BackToLogin />}
    >
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          <FormError message={serverError} />
          <FormField
            control={form.control}
            name="code"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Kurtarma kodu</FormLabel>
                <FormControl>
                  <Input
                    autoComplete="off"
                    autoCapitalize="characters"
                    spellCheck={false}
                    maxLength={20}
                    placeholder="ABCD-EFGH-JKLM"
                    className="num text-center text-xl tracking-widest"
                    {...field}
                  />
                </FormControl>
                <FormDescription>Büyük/küçük harf ve tire fark etmez.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Doğrulanıyor' : 'Kodu doğrula'}
          </Button>
          <Button variant="link" onClick={onUseTotp} className="min-h-touch self-center">
            Doğrulama uygulaması kodu kullan
          </Button>
        </form>
      </Form>
    </AuthCard>
  );
}
