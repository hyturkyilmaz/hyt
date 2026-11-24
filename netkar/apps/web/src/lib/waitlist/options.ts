// Bekleme listesi seçenekleri. Zod içermez: istemci paketine zod girmesin diye şemadan ayrıdır.

export const STORE_CATEGORIES = [
  { id: 'giyim', label: 'Giyim, ayakkabı ve aksesuar' },
  { id: 'ev-yasam', label: 'Ev ve yaşam' },
  { id: 'kozmetik', label: 'Kozmetik ve kişisel bakım' },
  { id: 'anne-bebek', label: 'Anne ve bebek' },
  { id: 'elektronik', label: 'Elektronik ve aksesuar' },
  { id: 'spor', label: 'Spor ve outdoor' },
  { id: 'diger', label: 'Diğer' },
] as const;

export const ORDER_RANGES = [
  { id: 'yok', label: 'Henüz satış yapmıyorum' },
  { id: '0-100', label: 'Ayda 0 ile 100 arası' },
  { id: '100-1000', label: 'Ayda 100 ile 1.000 arası' },
  { id: '1000-10000', label: 'Ayda 1.000 ile 10.000 arası' },
  { id: '10000+', label: 'Ayda 10.000 üzeri' },
] as const;

export const STORE_CATEGORY_IDS = STORE_CATEGORIES.map((item) => item.id) as [
  (typeof STORE_CATEGORIES)[number]['id'],
  ...(typeof STORE_CATEGORIES)[number]['id'][],
];
export const ORDER_RANGE_IDS = ORDER_RANGES.map((item) => item.id) as [
  (typeof ORDER_RANGES)[number]['id'],
  ...(typeof ORDER_RANGES)[number]['id'][],
];

/** Kayıt sırasında gösterilen aydınlatma metni sürümü (taslak; hukuki inceleme bekliyor). */
export const PRIVACY_NOTICE_VERSION = 'taslak-2026-11';

export const EMAIL_MAX_LENGTH = 254;
