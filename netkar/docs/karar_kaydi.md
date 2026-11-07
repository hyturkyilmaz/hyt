# NetKâr · Karar kaydı

Kaynak: Trello karar kartı (https://trello.com/c/oaiNNqhe). Bu dosyaya yalnız Hasan'ın etiketsiz yorumları karar olarak yazılır. "[Claude]" yorumları öneridir.
Biçim: tarih, karar, uygulama notu, açık kalan. Eski kayıtlar silinmez; değişen karar yeni satırla eklenir.

## 2026-11-07 (Hasan yorumu, 15:56 İstanbul)

| No | Karar (Hasan'ın sözüyle özet) | Durum | Uygulama notu |
|---|---|---|---|
| K-N01 | "NetEticaret, NetTablo gibi bir şey kullanılabilir, alternatif de üretebilirsin." | **Açık** (aday listesi) | NetEticaret önerilmedi (jenerik, tescil riski, "kâr" yok; karta gerekçe yazıldı). NetTablo daha güçlü aday: "net bir tablo" deyimiyle çift anlam, yurt dışında okunabilir. Alan adı, App Store ve TÜRKPATENT kontrolü yapılmadı (oturumda ağ kısıtı). Seçim Hasan'da. |
| K-N02 | "Guzel.net.tr'den hizmet alabiliriz ama Hetzner ucuzsa ona bakalım." | **Açık** (KVKK onayı gerekli) | Hesap (calisma_dosyalari/karar_hesap_2026-11-07.py): Hetzner A toplam 4.974 TL/ay, Güzel Hosting Private Cloud 3 ile 5.818 TL/ay. Fark 844 TL/ay, 10.130 TL/yıl. Hetzner yurt dışı aktarım (KVKK m.9: standart sözleşme + 5 iş günü içinde Kurum'a bildirim) ve Trendyol EK-6 riski taşır. Güzel fiyatı üçüncü taraf listeden (karekod.org, Mart 2026), resmi sayfadan doğrulanmadı. |
| K-N03 | "Şahıs şirketim var." | **Kapandı** | Maliyet modeli zaten şahıs varsayımıyla (mali müşavir 3.593 TL/ay). Fatura: e-Arşiv. |
| K-N04 | "Ödeme iyzico olacakmış gibi bakalım." | **Kapandı** (geçici) | S8 abonelik modülü iyzico barındırılan ödeme sayfası + kart saklama tokenı ile tasarlanır (PCI DSS SAQ-A). Komisyon modelde %2,79 + 0,25 TL. |
| K-N05 | "Rakip fiyatlamasının yarısı doğrultusunda gidelim, sınırlı süre diyerek." | **Kapandı** (öneriyle) | Doğrudan TR rakiplerinin (EZV, Melontik, Biliyo) fiyatı bulunamadı. Referans: Sentos Basic 792 TL/ay (yıllık/12), Sellerboard giriş 19 USD = 950 TL. Yarısı 396-475 TL. Öneri aşağıda. |
| K-N06 | "1 test satıcı: ben kendim olurum, 1 de beta satıcı bulurum." | **Kapandı** | Pilot hesap Hasan'ın kendi Trendyol mağazası. Anahtar yalnız staging'e, şifreli. Beta: 1 satıcı (önceki plan 5'ti). |
| K-N07 | "E-postayı sen hazırla, ben yollarım." | **Kapandı** | Metin hazır: docs/taslaklar/trendyol_teyit_talebi.md. Ürün adı seçilince yer tutucular doldurulur. Kanal önerisi: Hasan'ın kendi master hesabından satıcı paneli destek talebi (doğrulanmış e-posta adresi yok). |
| K-N08 | "BYOK ile AI'ı aktif edebilirler, benden almasınlar henüz. Sonra kredi satışıyla sunabilirim." | **Kapandı** (faz 2) | Satıcı kendi LLM anahtarını girer (BYOK). Anahtar zarf şifrelemeyle saklanır (ADR-0004 deseni). KVKK notu: çağrı sunucumuzdan giderse yurt dışı aktarımı biz yaparız; son müşteri kişisel verisi maskelenmeden gönderilmez. Mimari ADR faz 2'de yazılır. Kredi satışı ileride ayrı karar. |
| K-N09 | Yanıt yok | Açık | Ortam yerinde kalır. |

### K-N05 fiyat önerisi (KDV hariç, aylık)

| Plan | Liste fiyatı | Kurucu üye fiyatı (sınırlı süre) |
|---|---|---|
| Başlangıç | 499 TL | 249 TL |
| Pro | 799 TL | 399 TL |
| Ajans | 1.499 TL | 749 TL |

- **Süre ve kapsam:** İlk 100 ödeyen satıcı veya 31 Mart 2027'ye kadar kayıt, hangisi önce dolarsa. Kurucu fiyatı 12 ay sabit, sonra liste fiyatına geçer (önceden yazılı bildirim).
- **Başabaş (nakit, kurucu emeği hariç):** Pro 399 TL ile Hetzner'de 14, Güzel Hosting'de 16 satıcı. 799 TL ile 7 ve 8 satıcıydı. Kurucu emeğiyle gerçek başabaş eşiği yaklaşık iki katına çıkar.
- **Risk:** Düşük çapa fiyatı sonradan artırmayı zorlaştırır; 12. ay sonunda kayıp riski. Kurucu fiyatının süresi sözleşmede açık yazılmalı.
- **Hukuk notu (emin değilim, madde numarası doğrulanmadı):** Ticari Reklam ve Haksız Ticari Uygulamalar Yönetmeliği, indirim duyurusunda önceki fiyatın son 30 günde fiilen uygulanmış en düşük fiyat olmasını istiyor. Liste fiyatı hiç uygulanmadan "%50 indirim" yazmak yanıltıcı sayılabilir. Bu yüzden "indirim" yerine "kurucu üye fiyatı" ifadesi önerilir. Yayın öncesi hukukçu kontrolü.
