import type { LegalDocType } from '@/lib/api/endpoints';

/**
 * Sürüm kaydı tutulan belgeler ve web sayfaları. Metin içeriği burada YOKTUR: sayfalar avukat onayı bekleyen
 * taslaktır; sürüm kodu ve içerik özeti backend'de (`legal_documents`) tutulur.
 */
export const LEGAL_DOCS: Record<
  LegalDocType,
  { label: string; href: string; confirm: string; confirmed: string }
> = {
  terms: {
    label: 'Kullanım koşulları',
    href: '/kullanim-kosullari',
    confirm: 'okudum, kabul ediyorum',
    confirmed: 'Kullanım koşullarının güncel sürümünü okudum, kabul ediyorum.',
  },
  privacy_notice: {
    label: 'Aydınlatma metni',
    href: '/kvkk-aydinlatma-metni',
    confirm: 'okudum',
    confirmed: 'Aydınlatma metninin güncel sürümünü okudum.',
  },
};
