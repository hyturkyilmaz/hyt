// Backend sözleşmesi: services/api/app/api/v1/auth.py, me.py ve schemas.py (RFC 9457 hatalar).
// Tarayıcı `/api/v1/...` çağırır; next.config.ts rewrites bunu backend'in `/v1/...` yoluna iletir.
// Alanlar backend şemalarıyla birebir aynıdır (gövdeler `extra="forbid"`: fazladan alan 422 döner).
import { apiFetch } from '@/lib/api/client';

/** Giriş yanıtı: parola doğruysa "ok" (oturum çerezi set edilir); TOTP açıksa "totp_required". */
export interface LoginResult {
  status: 'ok' | 'totp_required';
}

/** Kayıt ve parola sıfırlama isteği yanıtı (202): hesap varlığı sızdırılmaz. */
export interface AcceptedResult {
  status: 'accepted';
}

export interface TenantInfo {
  id: string;
  name: string;
  plan: string;
  status: string;
  trial_ends_at: string | null;
  currency: string;
  locale: string;
}

/** GET /v1/me yanıtı (MeResponse) */
export interface MeResponse {
  user_id: string;
  email: string;
  role: string;
  totp_enabled: boolean;
  /** E-posta doğrulandı mı; false iken mağaza bağlama ve veri yazma uçları 403 email-not-verified döner. */
  email_verified: boolean;
  /** Kullanılabilir kurtarma kodu sayısı (TOTP etkin değilse 0). Düz metin kodlar yalnız üretildiği yanıtta döner. */
  recovery_codes_remaining: number;
  /** Güncel belge sürümleri kabul durumu; eski API'de alan yoktur (bekleyen yok sayılır). */
  legal?: LegalStatus;
  tenant: TenantInfo;
}

export type LegalDocType = 'terms' | 'privacy_notice';

export interface LegalPending {
  doc_type: LegalDocType;
  version: string;
  published_at: string;
}

/** `pending`: kabul edilmemiş güncel sürümler; `enforced`: sunucu kabule kadar yazma uçlarını 403 ile kapatıyor mu. */
export interface LegalStatus {
  pending: LegalPending[];
  enforced: boolean;
}

export interface TotpSetupResult {
  secret: string;
  otpauth_uri: string;
}

/** TOTP etkinleştirme ve kurtarma kodu yenileme yanıtı: 10 tek kullanımlık kod, YALNIZ bir kez döner. */
export interface RecoveryCodesResult {
  recovery_codes: string[];
}

export const authApi = {
  login: (body: { email: string; password: string }) =>
    apiFetch<LoginResult>('/auth/login', { method: 'POST', body }),

  /** Kayıt oturum AÇMAZ (202); kullanıcı ardından giriş yapar. tenant_name 1-120 karakter. */
  register: (body: {
    email: string;
    password: string;
    tenant_name: string;
    /** Kullanım koşulları açık onayı (yalnız `true` kabul edilir; eksikse 422). */
    accept_terms: true;
    /** Aydınlatma metni "okudum" bilgisi (açık rıza değildir; yalnız `true` kabul edilir). */
    acknowledge_privacy_notice: true;
  }) => apiFetch<AcceptedResult>('/auth/register', { method: 'POST', body }),

  /**
   * Girişte ikinci adım: `__Host-nk_pending` çerezi + 6 haneli TOTP kodu YA DA tek kullanımlık kurtarma kodu
   * (12 karakter; tire ve boşluk serbest, büyük/küçük harf fark etmez).
   */
  verifyTotp: (body: { code: string }) =>
    apiFetch<{ status: 'ok' }>('/auth/totp/verify', { method: 'POST', body }),

  /** Oturumu iptal eder (204, idempotent). CSRF zorunlu. */
  logout: () => apiFetch<void>('/auth/logout', { method: 'POST' }),

  me: () => apiFetch<MeResponse>('/me'),

  /** Yeni TOTP sırrı; yeniden doğrulama için GÜNCEL PAROLA ister (yanlışsa 403 `reauth-failed`). */
  totpSetup: (body: { password: string }) =>
    apiFetch<TotpSetupResult>('/auth/totp/setup', { method: 'POST', body }),

  /** Parola + uygulamadaki ilk kod; başarıda 10 kurtarma kodu döner (bir kez gösterilir). */
  totpEnable: (body: { code: string; password: string }) =>
    apiFetch<RecoveryCodesResult>('/auth/totp/enable', { method: 'POST', body }),

  /** TOTP'yi kapatır (204): güncel parola + güncel TOTP ya da kurtarma kodu; diğer oturumlar iptal edilir. */
  totpDisable: (body: { password: string; code: string }) =>
    apiFetch<void>('/auth/totp/disable', { method: 'POST', body }),

  /** Kurtarma kodlarını yeniler (eskiler geçersiz olur): parola + kod; diğer oturumlar iptal edilir. */
  regenerateRecoveryCodes: (body: { password: string; code: string }) =>
    apiFetch<RecoveryCodesResult>('/auth/totp/recovery-codes', { method: 'POST', body }),

  requestPasswordReset: (body: { email: string }) =>
    apiFetch<AcceptedResult>('/auth/password-reset/request', { method: 'POST', body }),

  /** E-postadaki bağlantıdaki token (20-200 karakter) ile doğrular; oturum gerekmez. Başarıda 204. */
  verifyEmail: (body: { token: string }) =>
    apiFetch<void>('/auth/email/verify', { method: 'POST', body }),

  /** Oturumdaki kullanıcıya doğrulama bağlantısını yeniden gönderir (202; saatlik sınır, 429). */
  resendEmailVerification: () => apiFetch<AcceptedResult>('/auth/email/resend', { method: 'POST' }),

  /** Backend alan adı `new_password` (token 20-200 karakter). Başarıda 204. */
  confirmPasswordReset: (body: { token: string; new_password: string }) =>
    apiFetch<void>('/auth/password-reset/confirm', { method: 'POST', body }),
};

export const legalApi = {
  /**
   * Gördüğünüz güncel belge sürümlerini kabul eder. Sürüm güncel değilse 409 `legal-version-stale`
   * (sayfa yenilenip yeni sürüm okunmalı). Yanıt: kalan bekleyenler.
   */
  accept: (documents: { doc_type: LegalDocType; version: string }[]) =>
    apiFetch<LegalStatus>('/legal/accept', { method: 'POST', body: { documents } }),
};
