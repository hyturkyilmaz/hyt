# NetKâr · Yönetici Özeti ve S0 Kapı Kararı (6 Kasım 2026)

## Karar: KOŞULLU GO
- **Teknik erişim var.** Satıcı kendi panelinden API anahtarını alıyor. Trendyol dokümanı aracı yazılım kullanımını öngörüyor. Sipariş, iade, ekstre (settlements, otherfinancials), kargo faturası, ürün ve soru-cevap verisi resmi API'de mevcut (research/01).
- **Kârlılık eşiği düşük.** Nakit giderler önerilen kurulumda MVP aşamasında ayda yaklaşık 5.000-6.500 TL. 799 TL fiyatla nakit başabaş 7-9 satıcı. Kurucu emeği (150.000 TL/ay varsayımı) dahil edilince yaklaşık 202 satıcı (docs/20_maliyet.md).
- **Talep ölçülebilir.** Aylık arama hacimleri: "trendyol komisyon hesaplama" 18.100, "desi hesaplama" 14.800, "trendyol kar hesaplama" 6.600 (OpenSEO, research/05). Trendyol'da 250 binden fazla iş ortağı var.
- **Pazar kalabalık.**
  - Net kâr vaat eden en az 6-8 yerli ürün var: EZV, Melontik, TrendHesap, SellerIQ, Biliyo, Cirometre, Pazarus, KarPanel.
  - Ücretsiz hesaplayıcılar arama sonuçlarını dolduruyor.
  - Entegratörler (Sentos, Entegra) hakediş kontrolünü yan özellik olarak sunuyor.
- **Fark burada aranmalı:**
  - Gerçek ekstre mutabakatı ("kaçak kesinti" tespiti)
  - Ürün bazında reklam dahil kâr ve "reklam kârı yiyor" uyarısı
  - Mobil anlık bildirim
  - Sade, Türkçe, hızlı kurulum

## GO koşulları (hepsi sağlanmadan prod'a gerçek satıcı verisi alınmaz)
1. **Trendyol yazılı teyidi (K-N07):** "Salt okuma amaçlı aracı SaaS" kullanımı uygun mu, salt okuma rolü var mı, rate limit satıcı başına mı sayılıyor? Sorular research/01 bölüm 4'te.
2. **Kişisel veri mimarisi:** Son müşteri ad, adres, telefon ve TCKN alanları ilk alım anında atılır. Satıcıyla Trendyol sözleşmesi EK-6 ile uyumlu veri işleme sözleşmesi (DPA) imzalanır. EK-6 müşteri verisiyle veri tabanı oluşturmayı yasaklıyor; ihlalin cezai şartı 500.000 TL (yeniden değerlemeli).
3. **Reklam ve fatura düzeyi kesintiler:** API'de reklam harcaması yok. Satıcı panelden aldığı reklam Excel'ini yükler; dağıtım modeli uygulanır; bu kalemler "tahmini" etiketiyle gösterilir.
4. **Pilot doğrulama:** Bir gerçek satıcı hesabıyla `DeductionInvoices` ve kargo faturası satırları test edilir; elle mutabakat farkı %1'in altında olmalı.

## Kritik riskler
| Risk | Etki | Önlem |
|---|---|---|
| Trendyol API ya da politika değişikliği, erişim askıya alma | Yüksek | Yazılı teyit, resmi uç noktalar, kazıma (scraping) yok, adaptör katmanı, Hepsiburada'yı erken ekleme |
| Kalabalık pazar, rakipler ucuz veya ücretsiz | Yüksek | Mutabakat ve uyarılarla fark, kurucu 50 programı, fiyat testi, ortaklık kanalları |
| KVKK yurt dışı aktarım | Orta | Barındırma Türkiye'de (öneri), yurt dışı servislere kişisel veri gönderilmez, standart sözleşme gerekirse bildirim |
| "NetKâr" adı App Store'da dolu, tanımlayıcı sayılıp marka reddi | Orta | İsim değişikliği (K-N01), marka vekili görüşü |
| Komisyon KDV ve işaret kuralı belirsizlikleri | Orta | Altın testler, gerçek ekstreyle doğrulama, mali müşavir teyidi |

## Hasan'ın yapacakları (öncelik sırasıyla)
1. **K-N07:** Trendyol Partner/Entegrasyon destek kanalına research/01 bölüm 4'teki soruları gönder (taslak koordinatör tarafından hazırlanacak, gönderim sende).
Güncel durum (2026-11-07): K-N03, K-N04, K-N05, K-N06, K-N07, K-N08 kapandı; K-N01 ve K-N02 açık. Ayrıntı: docs/karar_kaydi.md.

2. **K-N01:** Yeni isim seçimi (adaylar karar kartında).
3. **K-N02:** Barındırma yeri. Öneri: Türkiye (KVKK ve EK-6 nedeniyle). Fark ayda yaklaşık 1.550 TL.
4. **K-N06:** 1 pilot ve 5 beta satıcı. Pilot satıcının API anahtarı yalnız staging ortamına, şifreli olarak ve onayıyla girilir.
5. **K-N03 / K-N04:** Şirket türü ve ödeme kuruluşu (S8'den önce).

## Sonraki adımlar
- S1 (temel altyapı) koşullardan bağımsız; 9 Kasım haftası başlar.
- S2 senkron, stage ve test verisiyle ilerler. Gerçek satıcı verisi yalnızca koşul 1 ve 2 sağlanınca kullanılır.
- Web sitesi ve bekleme listesi paralel yürür ve isim kararına bağlıdır.

Kaynaklar: research/01-06 (her dosyanın sonunda APA 7 kaynakça). Fiyatların çoğu WebSearch özetlerinden geliyor (orta güven); satın almadan önce resmi sayfadan teyit edilmeli.
