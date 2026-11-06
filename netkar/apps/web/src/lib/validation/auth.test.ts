import { describe, expect, it } from 'vitest';

import {
  loginSchema,
  passwordResetConfirmSchema,
  passwordResetRequestSchema,
  registerSchema,
  twoFactorSchema,
} from '@/lib/validation/auth';

function firstMessage(result: { success: boolean; error?: { issues: { message: string }[] } }) {
  return result.error?.issues[0]?.message;
}

describe('loginSchema', () => {
  it('geçerli girdiyi kabul eder ve e-postayı kırpar', () => {
    const result = loginSchema.safeParse({ email: '  ad@ornek.com ', password: 'x' });
    expect(result.success).toBe(true);
    expect(result.data?.email).toBe('ad@ornek.com');
  });

  it('boş alanlarda Türkçe mesaj verir', () => {
    const result = loginSchema.safeParse({ email: '', password: '' });
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((i) => i.message)).toEqual(
      expect.arrayContaining(['E-posta adresinizi yazın.', 'Parolanızı yazın.']),
    );
  });

  it('geçersiz e-postayı reddeder', () => {
    const result = loginSchema.safeParse({ email: 'ad@', password: 'x' });
    expect(firstMessage(result)).toContain('Geçerli bir e-posta');
  });
});

describe('registerSchema', () => {
  const valid = { email: 'ad@ornek.com', password: 'on iki karakter parola', acceptTerms: true };

  it('geçerli girdiyi kabul eder', () => {
    expect(registerSchema.safeParse(valid).success).toBe(true);
  });

  it('12 karakterden kısa parolayı reddeder', () => {
    const result = registerSchema.safeParse({ ...valid, password: '12345678901' });
    expect(firstMessage(result)).toBe('Parola en az 12 karakter olmalı.');
  });

  it('12 karakterlik parolayı kabul eder (sınır)', () => {
    expect(registerSchema.safeParse({ ...valid, password: '123456789012' }).success).toBe(true);
  });

  it('çok uzun parolayı reddeder', () => {
    const result = registerSchema.safeParse({ ...valid, password: 'a'.repeat(129) });
    expect(firstMessage(result)).toContain('en fazla 128');
  });

  it('koşulları kabul etmeden geçmez', () => {
    const result = registerSchema.safeParse({ ...valid, acceptTerms: false });
    expect(firstMessage(result)).toContain('kullanım koşullarını kabul');
  });
});

describe('twoFactorSchema', () => {
  it('yalnız 6 haneli rakam kabul eder', () => {
    expect(twoFactorSchema.safeParse({ code: '123456' }).success).toBe(true);
    expect(twoFactorSchema.safeParse({ code: '12345' }).success).toBe(false);
    expect(twoFactorSchema.safeParse({ code: '12345a' }).success).toBe(false);
    expect(twoFactorSchema.safeParse({ code: '1234567' }).success).toBe(false);
    expect(firstMessage(twoFactorSchema.safeParse({ code: '' }))).toBe('Doğrulama kodunu yazın.');
  });
});

describe('parola sıfırlama şemaları', () => {
  it('e-posta ve yeni parolayı doğrular', () => {
    expect(passwordResetRequestSchema.safeParse({ email: 'ad@ornek.com' }).success).toBe(true);
    expect(passwordResetRequestSchema.safeParse({ email: 'x' }).success).toBe(false);
    expect(passwordResetConfirmSchema.safeParse({ password: 'kısa' }).success).toBe(false);
    expect(
      passwordResetConfirmSchema.safeParse({ password: 'yeterince uzun parola' }).success,
    ).toBe(true);
  });
});
