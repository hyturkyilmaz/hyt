// Kimlik doğrulama uç noktaları. Yollar ve gövde alanları API sözleşmesiyle henüz
// doğrulanmadı (services/api paralel geliştiriliyor); değişirse yalnız bu dosya güncellenir.
import { apiFetch } from '@/lib/api/client';

export interface LoginResult {
  /** Doğrulanmadı: 2FA açık hesaplarda API'nin ikinci adım istediğini belirten alan */
  two_factor_required?: boolean;
}

export const authApi = {
  login: (body: { email: string; password: string }) =>
    apiFetch<LoginResult>('/auth/login', { method: 'POST', body }),

  register: (body: { email: string; password: string; accept_terms: true }) =>
    apiFetch<void>('/auth/register', { method: 'POST', body }),

  verifyTwoFactor: (body: { code: string }) =>
    apiFetch<void>('/auth/2fa/verify', { method: 'POST', body }),

  requestPasswordReset: (body: { email: string }) =>
    apiFetch<void>('/auth/password-reset/request', { method: 'POST', body }),

  confirmPasswordReset: (body: { token: string; password: string }) =>
    apiFetch<void>('/auth/password-reset/confirm', { method: 'POST', body }),
};
