# NetKâr · İşletim Maliyeti ve Başabaş (v0.1, 5 Kasım 2026)

Kaynak: `calisma_dosyalari/maliyet_modeli.py` → `NetKar_Maliyet_Modeli.xlsx` (Python ile hesaplandı). Birim fiyatlar: `calisma_dosyalari/fiyatlar_2026-11-05.csv`. Kur: 1 USD = 50,0260 TL, 1 EUR = 56,2588 TL (TCMB gösterge, döviz satış, 5 Kasım 2026). Tutarlar KDV hariç.

## Özet
- **Nakit gider çok düşük.** Önerilen senaryo A'da (Hetzner AB, tek sunucu) MVP aylık 4.974 TL, yıllık 59.690 TL. Bu tutarın 4.453 TL'si mali müşavir, ön muhasebe ve alan adı.
- **Nakit başabaş:** 799 TL/ay fiyatla 7 ödeyen satıcı (MVP), 13 satıcı (büyüme kademesi), 22 satıcı (ölçek kademesi).
- **Gerçek başabaş kurucu emeğiyle hesaplanmalı.** Aylık 150.000 TL kurucu emeği ve geliştirme bütçesi varsayılırsa 799 TL fiyatla yaklaşık 202 ödeyen satıcı gerekir.
- **Dahil olmayanlar:** Kurucu emeği, Claude oturum maliyetleri, pazarlama zamanı.
- **Güven:** Altyapı fiyatları çoğunlukla WebSearch özetlerinden geliyor (orta güven); LLM fiyatı resmi sayfadan (yüksek güven); Türkiye VPS fiyatı düşük güven. Satın alma öncesi resmi sayfadan teyit edilmeli.

## Senaryolar (aylık / yıllık TL, KDV hariç; işletme gideri şahıs şirketi varsayımıyla)

| Senaryo | Kademe | Altyapı/ay | İşletme/ay | Toplam/ay | Toplam/yıl | Başabaş (499 / 799 / 1.199 TL) |
|---|---|---|---|---|---|---|
| A · Hetzner AB (önerilen) | MVP (0-100) | 521 | 4.453 | 4.974 | 59.690 | 11 / 7 / 5 |
| A | Büyüme (100-500) | 4.944 | 4.453 | 9.398 | 112.772 | 20 / 13 / 9 |
| A | Ölçek (500-2.000) | 11.994 | 4.453 | 16.448 | 197.374 | 35 / 22 / 15 |
| B · Türkiye VPS | MVP | 2.072 | 4.453 | 6.525 | 78.299 | 14 / 9 / 6 |
| B | Büyüme | 6.527 | 4.453 | 10.980 | 131.763 | 24 / 15 / 10 |
| B | Ölçek | 11.278 | 4.453 | 15.731 | 188.775 | 34 / 21 / 14 |
| C · Vercel + Supabase | MVP | 2.560 | 4.453 | 7.013 | 84.161 | 15 / 10 / 7 |
| C | Büyüme | 7.531 | 4.453 | 11.985 | 143.816 | 26 / 16 / 11 |
| C | Ölçek | 21.803 | 4.453 | 26.256 | 315.071 | 56 / 35 / 23 |

**Satıcı başı net katkı.** Fiyattan iyzico komisyonu (%2,79 + 0,25 TL), e-Arşiv kontörü (4 TL) ve AI maliyeti (4,50 TL/ay) düşülmüş hâli:
- 499 TL → 476,33 TL
- 799 TL → 767,96 TL
- 1.199 TL → 1.156,80 TL

**Limited şirket:** Mali müşavir ücreti 7.985 TL/ay olur, işletme gideri ayda yaklaşık 4.400 TL artar. Tek seferlik kuruluş maliyeti 30.000-42.500 TL; asgari sermaye 50.000 TL ayrıca.

**Faz 2 (mobil):** Apple Developer 99 USD/yıl (aylık yaklaşık 413 TL), Google Play 25 USD tek seferlik, Expo EAS ücretsiz katman yeterli.

## Öneri
- **Senaryo A** ile başla. B'ye göre aylık yaklaşık 1.550 TL ucuz, C'ye göre ölçekte 10.000 TL/ay ucuz.
- **KVKK:** A yurt dışı aktarım sayılıyor. KVKK m.9 standart sözleşme ve Kurum'a bildirim gerekiyor (research/03). Hasan yurt içi isterse B seçilir; fark küçük. Karar: K-N02.
- **Mimari:** Kod barındırma bağımsız (Docker Compose); A'dan B'ye geçiş birkaç saatlik iş.
