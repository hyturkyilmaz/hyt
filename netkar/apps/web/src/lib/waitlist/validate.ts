// Hafif istemci tarafı doğrulama (zod istemci paketine girmesin diye ayrı tutulur).
import { EMAIL_MAX_LENGTH, ORDER_RANGE_IDS } from './options';

export type WaitlistField = 'email' | 'monthlyOrders';

export interface WaitlistFormValues {
  email: string;
  storeCategory: string;
  monthlyOrders: string;
  marketingConsent: boolean;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateWaitlistForm(
  values: WaitlistFormValues,
): Partial<Record<WaitlistField, string>> {
  const errors: Partial<Record<WaitlistField, string>> = {};
  const email = values.email.trim();
  if (email === '') {
    errors.email = 'E-posta adresinizi yazın.';
  } else if (email.length > EMAIL_MAX_LENGTH || !EMAIL_PATTERN.test(email)) {
    errors.email = 'E-posta adresi geçerli görünmüyor. Örnek: ad@sirket.com';
  }
  if (!(ORDER_RANGE_IDS as readonly string[]).includes(values.monthlyOrders)) {
    errors.monthlyOrders = 'Aylık sipariş aralığınızı seçin.';
  }
  return errors;
}
