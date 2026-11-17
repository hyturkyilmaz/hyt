'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';

import { FormError } from '@/components/auth/auth-card';
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
import { describeMfaError } from '@/lib/security/mfa-errors';
import { mfaChangeSchema, mfaTotpOnlySchema, type MfaChangeValues } from '@/lib/validation/auth';

/**
 * TOTP açıkken yapılan değişiklikler (kapatma, kurtarma kodlarını yenileme) için ortak form:
 * güncel parola + güncel kod (uygulama kodu ya da kurtarma kodu). Başarıyı üst bileşen işler.
 */
export function TotpManageForm({
  title,
  description,
  submitLabel,
  pendingLabel,
  failureMessage,
  onSubmit,
  onCancel,
  totpOnly = false,
}: {
  title: string;
  description: string;
  submitLabel: string;
  pendingLabel: string;
  failureMessage: string;
  onSubmit: (values: MfaChangeValues) => Promise<void>;
  onCancel: () => void;
  /** true: yalnız uygulamadaki 6 haneli kod kabul edilir (kurtarma kodu yenileme) */
  totpOnly?: boolean;
}) {
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<MfaChangeValues>({
    resolver: zodResolver(totpOnly ? mfaTotpOnlySchema : mfaChangeSchema),
    defaultValues: { password: '', code: '' },
  });
  const { isSubmitting } = form.formState;
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), []);

  async function submit(values: MfaChangeValues) {
    setServerError(null);
    try {
      await onSubmit(values);
    } catch (error) {
      setServerError(describeMfaError(error, failureMessage));
    }
  }

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(submit)} noValidate className="flex flex-col gap-5">
        <h3 ref={headingRef} tabIndex={-1} className="text-lg font-semibold focus:outline-none">
          {title}
        </h3>
        <p className="text-sm text-muted-foreground">{description}</p>
        <FormError message={serverError} />
        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Güncel parola</FormLabel>
              <FormControl>
                <PasswordInput autoComplete="current-password" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="code"
          render={({ field }) => (
            <FormItem>
              <FormLabel>
                {totpOnly ? 'Doğrulama uygulaması kodu' : 'Doğrulama ya da kurtarma kodu'}
              </FormLabel>
              <FormControl>
                <Input
                  autoComplete="one-time-code"
                  autoCapitalize="characters"
                  spellCheck={false}
                  maxLength={totpOnly ? 6 : 20}
                  inputMode={totpOnly ? 'numeric' : undefined}
                  className="num"
                  {...field}
                />
              </FormControl>
              <FormDescription>
                {totpOnly
                  ? 'Uygulamadaki güncel 6 haneli kodu yazın (kurtarma kodu burada kabul edilmez).'
                  : 'Uygulamadaki 6 haneli kodu ya da kullanılmamış bir kurtarma kodunu yazın.'}
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? pendingLabel : submitLabel}
          </Button>
          <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
            Vazgeç
          </Button>
        </div>
      </form>
    </Form>
  );
}
