import { z } from 'zod';

import { CLIENT_IP_SOURCES } from '@/lib/client-ip';

// Ortam değişkeni şeması. Hatalı değer varsa uygulama açılışta anlaşılır bir mesajla durur.
const urlWithoutTrailingSlash = (fallback: string) =>
  z
    .url()
    .default(fallback)
    .transform((value) => value.replace(/\/+$/, ''));

const envSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  // /api/v1 isteklerinin yönlendirileceği adres (yalnız sunucu tarafı)
  API_BASE_URL: urlWithoutTrailingSlash('http://localhost:8000'),
  NEXT_PUBLIC_SITE_URL: urlWithoutTrailingSlash('http://localhost:3000'),
  NEXT_PUBLIC_PRODUCT_NAME: z.string().trim().min(1).max(40).optional(),
  // Gerçek istemci IP'sinin kaynağı (ADR-0002); middleware aynı değerleri doğrudan okur.
  CLIENT_IP_SOURCE: z.enum(CLIENT_IP_SOURCES).default('none'),
  CLIENT_IP_TRUSTED_HOPS: z.coerce.number().int().min(1).max(10).default(1),
});

export type Env = z.infer<typeof envSchema>;

export function parseEnv(source: Record<string, string | undefined>): Env {
  // Boş string ortam değişkenlerini tanımsız say (.env dosyalarında sık görülür)
  const cleaned = Object.fromEntries(
    Object.entries(source).filter(([, value]) => value !== undefined && value !== ''),
  );
  const result = envSchema.safeParse(cleaned);
  if (!result.success) {
    const details = result.error.issues
      .map((issue) => `${issue.path.join('.') || '(kök)'}: ${issue.message}`)
      .join('; ');
    throw new Error(`Ortam değişkenleri geçersiz: ${details}`);
  }
  return result.data;
}

let cached: Env | undefined;

// Yalnız sunucuda çağrılmalıdır; API_BASE_URL istemci paketine sızmamalı.
export function getEnv(): Env {
  cached ??= parseEnv(process.env);
  return cached;
}
