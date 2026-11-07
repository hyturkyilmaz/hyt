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
import { PasswordInput } from '@/components/ui/password-input';
import { ApiError, describeApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';
import {
  PASSWORD_MIN_LENGTH,
  TENANT_NAME_MAX_LENGTH,
  registerSchema,
  type RegisterValues,
} from '@/lib/validation/auth';

export function RegisterForm() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: '', tenantName: '', password: '', acceptTerms: false },
  });
  const { isSubmitting } = form.formState;

  async function onSubmit(values: RegisterValues) {
    setServerError(null);
    try {
      // Kullanım koşulları onayı yalnız arayüzde zorunludur; API'nin böyle bir alanı yoktur
      // (gövde extra="forbid"). Onay sürümü kaydı backend'de henüz yok (bkz. rapor).
      await authApi.register({
        email: values.email,
        password: values.password,
        tenant_name: values.tenantName,
      });
      // Kayıt oturum açmaz (202, hesap varlığı sızdırılmaz): girişe yönlendirilir.
      router.push('/giris?kayit=1');
    } catch (error) {
      // 422 "weak-password": parola sızmış listesinde; diğer 422'ler alan doğrulamasıdır.
      const fallback =
        error instanceof ApiError && error.code === 'weak-password'
          ? 'Bu parola bilinen veri sızıntılarında görülmüş. Lütfen farklı bir parola seçin.'
          : error instanceof ApiError && error.status === 422
            ? 'Bilgilerinizi kontrol edin. E-posta, işletme adı ve parola kurallarına uyduğundan emin olun.'
            : 'Kayıt tamamlanamadı. Lütfen tekrar deneyin.';
      setServerError(describeApiError(error, fallback));
    }
  }

  return (
    <AuthCard
      title="Hesap oluşturun"
      description="Birkaç bilgiyle başlayın. Kart bilgisi istemiyoruz."
      footer={
        <>
          Zaten hesabınız var mı?{' '}
          <Link href="/giris" className="font-medium text-primary underline underline-offset-4">
            Giriş yapın
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
            name="tenantName"
            render={({ field }) => (
              <FormItem>
                <FormLabel>İşletme veya mağaza adı</FormLabel>
                <FormControl>
                  <Input
                    autoComplete="organization"
                    maxLength={TENANT_NAME_MAX_LENGTH}
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
                  <PasswordInput autoComplete="new-password" {...field} />
                </FormControl>
                <FormDescription>
                  En az {PASSWORD_MIN_LENGTH} karakter. Uzun bir cümle iyi bir paroladır.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="acceptTerms"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-start gap-3">
                  <FormControl>
                    <input
                      type="checkbox"
                      checked={field.value}
                      onChange={(event) => field.onChange(event.target.checked)}
                      onBlur={field.onBlur}
                      name={field.name}
                      ref={field.ref}
                      className="mt-0.5 size-6 shrink-0 accent-[var(--primary)]"
                    />
                  </FormControl>
                  <FormLabel className="font-normal leading-normal">
                    <Link
                      href="/kullanim-kosullari"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-primary underline underline-offset-4"
                    >
                      Kullanım koşullarını
                      <span className="sr-only"> (yeni sekmede açılır)</span>
                    </Link>{' '}
                    okudum, kabul ediyorum.
                  </FormLabel>
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
          {/* Aydınlatma bir bilgilendirmedir, onay kutusuna bağlı değildir (KVKK m.10). */}
          <p className="text-sm text-muted-foreground">
            Kişisel verilerinizin nasıl işleneceğini{' '}
            <Link
              href="/kvkk-aydinlatma-metni"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-primary underline underline-offset-4"
            >
              aydınlatma metninde
              <span className="sr-only"> (yeni sekmede açılır)</span>
            </Link>{' '}
            okuyabilirsiniz.
          </p>
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Hesap oluşturuluyor' : 'Hesap oluştur'}
          </Button>
        </form>
      </Form>
    </AuthCard>
  );
}
