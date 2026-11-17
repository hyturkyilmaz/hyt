import { z } from 'zod';

// Parola kuralları docs/50_guvenlik.md G02 ile uyumludur: en az 12 karakter.
// Üst sınır, çok uzun girdiyle sunucuyu yormayı (argon2id) engeller.
export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 128;

const email = z
  .string()
  .trim()
  .min(1, 'E-posta adresinizi yazın.')
  .max(254, 'E-posta adresi çok uzun.')
  .pipe(z.email('Geçerli bir e-posta adresi yazın. Örnek: ad@ornek.com'));

const newPassword = z
  .string()
  .min(1, 'Bir parola belirleyin.')
  .min(PASSWORD_MIN_LENGTH, `Parola en az ${PASSWORD_MIN_LENGTH} karakter olmalı.`)
  .max(PASSWORD_MAX_LENGTH, `Parola en fazla ${PASSWORD_MAX_LENGTH} karakter olabilir.`);

export const loginSchema = z.object({
  email,
  password: z.string().min(1, 'Parolanızı yazın.').max(PASSWORD_MAX_LENGTH, 'Parola çok uzun.'),
});

// Backend RegisterRequest.tenant_name: boşluklar kırpılır, 1-120 karakter.
export const TENANT_NAME_MAX_LENGTH = 120;

export const registerSchema = z.object({
  email,
  tenantName: z
    .string()
    .trim()
    .min(1, 'İşletme veya mağaza adınızı yazın.')
    .max(TENANT_NAME_MAX_LENGTH, `Ad en fazla ${TENANT_NAME_MAX_LENGTH} karakter olabilir.`),
  password: newPassword,
  acceptTerms: z.boolean().refine((value) => value, {
    message: 'Devam etmek için kullanım koşullarını kabul etmelisiniz.',
  }),
  // Aydınlatma "okudum" bilgisidir, açık rıza değildir (KVKK m.10); yine de kayıt için işaretlenmesi zorunludur.
  acknowledgePrivacy: z.boolean().refine((value) => value, {
    message: 'Devam etmek için aydınlatma metnini okuduğunuzu işaretleyin.',
  }),
});

export const twoFactorSchema = z.object({
  code: z
    .string()
    .trim()
    .min(1, 'Doğrulama kodunu yazın.')
    .regex(/^\d{6}$/, 'Kod 6 haneli olmalı ve yalnız rakam içermeli.'),
});

export const passwordResetRequestSchema = z.object({ email });

export const passwordResetConfirmSchema = z.object({ password: newPassword });

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
export type TwoFactorValues = z.infer<typeof twoFactorSchema>;
export type PasswordResetRequestValues = z.infer<typeof passwordResetRequestSchema>;
export type PasswordResetConfirmValues = z.infer<typeof passwordResetConfirmSchema>;

// Giriş kodu: 6 haneli TOTP ya da 12 karakterlik kurtarma kodu (tire/boşluk serbest). Backend `LoginCode` ile aynı kural.
export const RECOVERY_CODE_LENGTH = 12;
const loginCode = z
  .string()
  .trim()
  .min(1, 'Kodu yazın.')
  .refine((value) => {
    if (/^\d{6}$/.test(value)) return true;
    const compact = value.replace(/[- ]/g, '');
    return compact.length === RECOVERY_CODE_LENGTH && /^[A-Za-z0-9]+$/.test(compact);
  }, 'Doğrulama uygulamasındaki 6 haneli kodu ya da 12 karakterlik bir kurtarma kodunu yazın.');

export const recoveryCodeSchema = z.object({
  code: z
    .string()
    .trim()
    .min(1, 'Kurtarma kodunu yazın.')
    .refine(
      (value) =>
        value.replace(/[- ]/g, '').length === RECOVERY_CODE_LENGTH &&
        /^[A-Za-z0-9 -]+$/.test(value),
      'Kurtarma kodu 12 karakterdir. Örnek: ABCD-EFGH-JKLM',
    ),
});

/** Yeniden doğrulama: güncel parola. */
export const reauthSchema = z.object({
  password: z
    .string()
    .min(1, 'Güncel parolanızı yazın.')
    .max(PASSWORD_MAX_LENGTH, 'Parola çok uzun.'),
});

/** TOTP etkinleştirme: uygulamadaki 6 haneli kod (parola önceki adımda alınmıştır). */
export const totpEnableSchema = z.object({
  code: twoFactorSchema.shape.code,
});

/** TOTP kapatma: parola + güncel kod (TOTP ya da kurtarma kodu). */
export const mfaChangeSchema = z.object({
  password: reauthSchema.shape.password,
  code: loginCode,
});

/** Kurtarma kodu yenileme: parola + YALNIZ güncel TOTP kodu (backend kurtarma kodunu kabul etmez). */
export const mfaTotpOnlySchema = z.object({
  password: reauthSchema.shape.password,
  code: twoFactorSchema.shape.code,
});

export type RecoveryCodeValues = z.infer<typeof recoveryCodeSchema>;
export type ReauthValues = z.infer<typeof reauthSchema>;
export type TotpEnableValues = z.infer<typeof totpEnableSchema>;
export type MfaChangeValues = z.infer<typeof mfaChangeSchema>;
