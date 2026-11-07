import { z } from 'zod';

import {
  EMAIL_MAX_LENGTH,
  ORDER_RANGE_IDS,
  PRIVACY_NOTICE_VERSION,
  STORE_CATEGORY_IDS,
} from './options';

export { PRIVACY_NOTICE_VERSION };

// Bekleme listesi form alanları. İstemci doğrulaması (validate.ts) ve sunucu şeması aynı seçenekleri
// kullanır. Son müşteri verisi veya sır alınmaz: yalnız e-posta ve iki segment alanı.

export const waitlistSchema = z.object({
  email: z.string().trim().toLowerCase().max(EMAIL_MAX_LENGTH).pipe(z.email()),
  storeCategory: z.enum(STORE_CATEGORY_IDS).optional(),
  monthlyOrders: z.enum(ORDER_RANGE_IDS),
  // Ticari ileti onayı: ayrı ve varsayılan işaretsiz. Yalnız true ise onay sayılır.
  marketingConsent: z.boolean(),
  // Bot tuzağı: gerçek kullanıcı bu alanı görmez, boş kalır.
  website: z.string().max(200).optional(),
  turnstileToken: z.string().max(2048).optional(),
});

export type WaitlistSubmission = z.infer<typeof waitlistSchema>;

export interface WaitlistEntry {
  email: string;
  storeCategory: string | null;
  monthlyOrders: string;
  marketingConsent: boolean;
  /** Onay verilmediyse null */
  marketingConsentAt: string | null;
  privacyNoticeVersion: string;
  createdAt: string;
}
