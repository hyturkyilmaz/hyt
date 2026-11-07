// Hesaplayıcıların varsayımları. Kaynak ve güven düzeyi: docs/12_kar_motoru.md.

/** Ürün KDV oranları (CBK 7346, Trendyol duyurusu 10.07.2023): %1, %10, %20. K02 */
export const VAT_RATES = [1, 10, 20] as const;
export type VatRate = (typeof VAT_RATES)[number];

/** Komisyon, kargo, hizmet bedeli ve reklam faturalarının KDV oranı (genel oran). K02, §8 */
export const SERVICE_VAT_RATE = 20;

/** E-ticaret stopajı: %1 (9284 sayılı CBK, 01.01.2025). Gider değil, nakit akışı kalemi. K18 */
export const WITHHOLDING_BPS = 100n;

/** Desi bölenleri: yurt içi 3.000, yurt dışı 5.000. */
export const DESI_DIVISORS = { domestic: 3000n, international: 5000n } as const;
export type DesiDivisorKey = keyof typeof DESI_DIVISORS;
