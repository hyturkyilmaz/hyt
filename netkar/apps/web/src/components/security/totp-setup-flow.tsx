'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Check, Copy, Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';

import { FormError } from '@/components/auth/auth-card';
import { QrCode } from '@/components/security/qr-code';
import { RecoveryCodesPanel } from '@/components/security/recovery-codes-panel';
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
import { authApi, type TotpSetupResult } from '@/lib/api/endpoints';
import { describeMfaError } from '@/lib/security/mfa-errors';
import {
  reauthSchema,
  totpEnableSchema,
  type ReauthValues,
  type TotpEnableValues,
} from '@/lib/validation/auth';

type Step =
  | { kind: 'password' }
  // Parola yalnız bellekte tutulur (etkinleştirme isteği yeniden doğrulama ister); kod adımı bitince silinir.
  | { kind: 'scan'; password: string; setup: TotpSetupResult }
  | { kind: 'codes'; codes: string[] };

/** TOTP kurulum akışı: parola ile yeniden doğrulama, QR/anahtar, kod doğrulama, kurtarma kodları (bir kez). */
export function TotpSetupFlow({
  onCancel,
  onEnabled,
}: {
  onCancel: () => void;
  /** Kullanıcı kurtarma kodlarını kaydettiğini onaylayıp "Bitti" dediğinde */
  onEnabled: (recoveryCodeCount: number) => void;
}) {
  const [step, setStep] = useState<Step>({ kind: 'password' });

  if (step.kind === 'password') {
    return (
      <PasswordStep
        onCancel={onCancel}
        onDone={(password, setup) => setStep({ kind: 'scan', password, setup })}
      />
    );
  }
  if (step.kind === 'scan') {
    return (
      <ScanStep
        password={step.password}
        setup={step.setup}
        onCancel={onCancel}
        onEnabled={(codes) => setStep({ kind: 'codes', codes })}
      />
    );
  }
  return <RecoveryCodesPanel codes={step.codes} onDone={() => onEnabled(step.codes.length)} />;
}

function PasswordStep({
  onCancel,
  onDone,
}: {
  onCancel: () => void;
  onDone: (password: string, setup: TotpSetupResult) => void;
}) {
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<ReauthValues>({
    resolver: zodResolver(reauthSchema),
    defaultValues: { password: '' },
  });
  const { isSubmitting } = form.formState;
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), []);

  async function onSubmit(values: ReauthValues) {
    setServerError(null);
    try {
      const setup = await authApi.totpSetup({ password: values.password });
      onDone(values.password, setup);
    } catch (error) {
      setServerError(describeMfaError(error, 'Kurulum başlatılamadı. Lütfen tekrar deneyin.'));
    }
  }

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
        <h3 ref={headingRef} tabIndex={-1} className="text-lg font-semibold focus:outline-none">
          1. Parolanızı doğrulayın
        </h3>
        <p className="text-sm text-muted-foreground">
          Güvenlik ayarını değiştirmeden önce kimliğinizi yeniden doğruluyoruz.
        </p>
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
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Doğrulanıyor' : 'Devam et'}
          </Button>
          <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
            Vazgeç
          </Button>
        </div>
      </form>
    </Form>
  );
}

function ScanStep({
  password,
  setup,
  onCancel,
  onEnabled,
}: {
  password: string;
  setup: TotpSetupResult;
  onCancel: () => void;
  onEnabled: (codes: string[]) => void;
}) {
  const [serverError, setServerError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const form = useForm<TotpEnableValues>({
    resolver: zodResolver(totpEnableSchema),
    defaultValues: { code: '' },
  });
  const { isSubmitting } = form.formState;
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), []);

  async function onCopySecret() {
    try {
      await navigator.clipboard.writeText(setup.secret);
      setCopied(true);
      toast.success('Anahtar panoya kopyalandı.');
    } catch {
      toast.error('Kopyalanamadı. Anahtarı elle yazın.');
    }
  }

  async function onSubmit(values: TotpEnableValues) {
    setServerError(null);
    try {
      const result = await authApi.totpEnable({ code: values.code, password });
      onEnabled(result.recovery_codes);
    } catch (error) {
      setServerError(describeMfaError(error, 'Kod doğrulanamadı. Lütfen tekrar deneyin.'));
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <h3 ref={headingRef} tabIndex={-1} className="text-lg font-semibold focus:outline-none">
        2. Doğrulama uygulamasına ekleyin
      </h3>
      <p className="text-sm text-muted-foreground">
        Google Authenticator, Microsoft Authenticator ya da benzeri bir uygulamayla QR kodunu
        okutun. QR kod cihazınızda üretilir; hiçbir dış servise gönderilmez.
      </p>
      <div className="flex justify-center sm:justify-start">
        <QrCode
          value={setup.otpauth_uri}
          label="İki adımlı doğrulama QR kodu. Okutamıyorsanız altındaki anahtarı elle girin."
        />
      </div>
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium" id="totp-secret-label">
          QR kodu okutamıyor musunuz? Anahtarı elle girin
        </p>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <code
            aria-labelledby="totp-secret-label"
            className="num break-all rounded-md border border-border bg-surface-muted px-3 py-2 font-mono text-base tracking-wider"
          >
            {setup.secret}
          </code>
          <Button variant="secondary" size="sm" onClick={onCopySecret}>
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            {copied ? 'Kopyalandı' : 'Kopyala'}
          </Button>
        </div>
      </div>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          <FormError message={serverError} />
          <FormField
            control={form.control}
            name="code"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Uygulamadaki 6 haneli kod</FormLabel>
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
                <FormDescription>
                  Uygulamaya ekledikten sonra gösterdiği kodu yazın; kod 30 saniyede bir yenilenir.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <div className="flex flex-col gap-3 sm:flex-row">
            <Button type="submit" disabled={isSubmitting} aria-disabled={isSubmitting}>
              {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
              {isSubmitting ? 'Doğrulanıyor' : 'Doğrula ve etkinleştir'}
            </Button>
            <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
              Vazgeç
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
