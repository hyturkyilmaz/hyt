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
  tenant: TenantInfo;
}

export interface TotpSetupResult {
  secret: string;
  otpauth_uri: string;
}

export const authApi = {
  login: (body: { email: string; password: string }) =>
    apiFetch<LoginResult>('/auth/login', { method: 'POST', body }),

  /** Kayıt oturum AÇMAZ (202); kullanıcı ardından giriş yapar. tenant_name 1-120 karakter. */
  register: (body: { email: string; password: string; tenant_name: string }) =>
    apiFetch<AcceptedResult>('/auth/register', { method: 'POST', body }),

  /** Girişte ikinci adım: `__Host-nk_pending` çerezi + 6 haneli TOTP kodu. */
  verifyTotp: (body: { code: string }) =>
    apiFetch<{ status: 'ok' }>('/auth/totp/verify', { method: 'POST', body }),

  /** Oturumu iptal eder (204, idempotent). CSRF zorunlu. */
  logout: () => apiFetch<void>('/auth/logout', { method: 'POST' }),

  me: () => apiFetch<MeResponse>('/me'),

  totpSetup: () => apiFetch<TotpSetupResult>('/auth/totp/setup', { method: 'POST' }),

  totpEnable: (body: { code: string }) =>
    apiFetch<void>('/auth/totp/enable', { method: 'POST', body }),

  requestPasswordReset: (body: { email: string }) =>
    apiFetch<AcceptedResult>('/auth/password-reset/request', { method: 'POST', body }),

  /** Backend alan adı `new_password` (token 20-200 karakter). Başarıda 204. */
  confirmPasswordReset: (body: { token: string; new_password: string }) =>
    apiFetch<void>('/auth/password-reset/confirm', { method: 'POST', body }),
};
