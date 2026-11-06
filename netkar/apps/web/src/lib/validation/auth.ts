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

export const registerSchema = z.object({
  email,
  password: newPassword,
  acceptTerms: z.boolean().refine((value) => value, {
    message: 'Devam etmek için kullanım koşullarını kabul etmelisiniz.',
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
