# 01. Trendyol API: Teknik ve Sözleşmesel Fizibilite (NetKâr go/no-go)

Hazırlanma tarihi: 5 Kasım 2026
Kapsam: Trendyol satıcısının kendi API anahtarıyla bağlanıp sipariş, iade, komisyon, kargo, reklam ve hakediş verisini çeken "ürün bazında gerçek net kâr" SaaS/mobil uygulaması (çalışma adı NetKâr).
Yöntem: developers.trendyol.com sayfaları doğrudan okundu (sitenin `llms.txt` dizini üzerinden markdown kaynakları indirildi, sayfaların `updatedAt` damgaları not edildi). Trendyol satıcı sözleşmesinin Trendyol CDN'inde yayımlanan PDF sürümü okundu. Trendyol Akademi, rakip/entegratör blogları ve GitHub'daki açık kaynak istemciler ikincil kaynak olarak kullanıldı.

Güven düzeyi ölçeği:
- **Yüksek**: Resmi Trendyol dokümanında veya sözleşme metninde birebir okundu.
- **Orta**: Resmi kaynağın arama özetinden veya güvenilir ikincil kaynaktan (Trendyol Akademi özeti, büyük entegratörün kılavuzu, açık kaynak istemci kodu) geliyor.
- **Düşük**: Tek bir ticari blog, çelişkili kaynaklar veya çıkarım.
- **Doğrulanmadı**: Kaynak bulunamadı; Trendyol'a sorulmalı veya canlı hesapla test edilmeli.

Erişim notları (şeffaflık için):
- developers.trendyol.com bu oturumun ağ politikasında başta kapalıydı; araştırma için ayrı bir kişisel ortam ("hyt (marketplace API research)") açılarak erişildi. Tüm resmi sayfalar bu şekilde birebir okundu.
- akademi.trendyol.com sayfaları istemci tarafında (JavaScript) render edildiği için metin doğrudan okunamadı; bu sayfalardaki bilgiler arama motoru özetlerinden alındı (Orta güven).
- developers.hepsiburada.com otomatik isteklere 403 döndüğü için okunamadı; Hepsiburada bölümü arama özetlerine dayanıyor.

---

## 1. Yönetici Özeti

- **Erişim serbest ve dokümante:** Trendyol, satıcının "aracı firma" (entegratör) üzerinden API kullanmasını açıkça öngörüyor. Üçüncü taraf, satıcının panelden aldığı `sellerId`, `API Key`, `API Secret` ile Basic Auth yapıyor ve `User-Agent: "{sellerId} - {FirmaAdı}"` gönderiyor (NetKâr için örn. `"123456 - NetKar"`). Resmi dokümanda ayrı bir "onaylı entegratör" başvuru süreci veya IP whitelist (canlı ortam) şartı bulunmadı. (Güven: Yüksek, "başvuru yok" kısmı Orta, çünkü yokluk kanıtı.)
- **Kâr hesabının omurgası API'de var:** Sipariş satırlarında brüt fiyat, satıcı indirimi, Trendyol indirimi, KDV oranı ve **komisyon oranı**; Cari Hesap Ekstresi `settlements` servisinde satır bazında **komisyon tutarı, satıcı hakedişi, barkod, sipariş numarası ve paket numarası**; `cargo-invoice` servisinde **sipariş numarası bazında gönderi ve iade kargo bedeli ile desi** dönüyor. Ürün bazında net kâr için gereken Trendyol tarafı kalemlerin büyük kısmı API'den alınabiliyor. (Güven: Yüksek)
- **En büyük veri boşluğu reklam:** developers.trendyol.com dizininde reklam/ads API'si yok. Reklam bakiyesi alımı faturalanıp hakedişten mahsup ediliyor ve Cari Hesap Ekstresi'nde görünüyor, fakat **ürün bazında reklam harcaması yalnızca satıcı panelindeki Excel raporundan** alınabiliyor. Ürün bazında reklam maliyeti v1'de ya kullanıcı Excel yüklemesi ya da dağıtım (allocation) kuralıyla çözülmeli. (Güven: API yokluğu Yüksek, panel/Excel bilgisi Orta)
- **Platform hizmet bedeli, ceza, erken ödeme bedeli gibi kesintiler fatura düzeyinde:** `otherfinancials` içinde `DeductionInvoices` (Trendyol'un satıcıya kestiği faturalar, `PlatformServiceFee` alt tipiyle filtrelenebiliyor), `CashAdvance`, `Stoppage` (%1 e-ticaret stopajı) vb. var; bu kalemlerin sipariş/ürün kırılımı dokümante değil. Dağıtım kuralı gerekecek. (Güven: Yüksek, kırılım yokluğu Orta)
- **Geçmiş veri sınırlı:** Sipariş akış servisi (`orders/stream`) yalnızca **son 3 ay**, sayfalı `v2/orders` ise **son 1 ay** ve **10.000 paket** penceresi veriyor. Onboarding'de satıcıya en fazla 3 aylık sipariş geçmişi gösterilebilir. Finans servislerinde geriye dönük bir üst sınır yazmıyor, ancak her istek en fazla 15 günlük pencere alıyor. (Güven: Yüksek, finans geriye dönük sınır Doğrulanmadı)
- **Rate limit yönetilebilir:** Finans 100 istek/dk, iade 1000 istek/dk, soru-cevap 1000/500 istek/dk, sipariş çekme listeleme seviyesine göre 30 ile 100 istek/dk; genel kural "aynı endpoint'e 10 saniyede 50 istek". Tek satıcı başına günlük senkron bu limitlerin çok altında kalır; asıl ölçek riski çok sayıda satıcıyı tek IP'den çekmek (limitlerin satıcı bazlı mı IP bazlı mı olduğu Doğrulanmadı). (Güven: Yüksek, kapsam belirsizliği Doğrulanmadı)
- **Webhook sadece sipariş paketleri için:** 13 sipariş statüsü için webhook var (satıcı başına en fazla 15 webhook, at-least-once, 5 dakikada bir retry, 13 hatada pasife alma). İade, finans ve soru-cevap için webhook yok; polling gerekli. Trendyol webhook olsa bile periyodik eşitleme yapılmasını tavsiye ediyor. (Güven: Yüksek)
- **KVKK ve sözleşme en ciddi risk alanı:** Sipariş yanıtında müşterinin adı, soyadı, teslimat ve fatura adresi, telefon alanı ve bazı siparişlerde TCKN dönüyor; e-posta Trendyol relay adresi (`...@trendyolmail.com`) olarak maskeli. Satıcı sözleşmesinin KVKK protokolü (EK-6) satıcının müşteri verisiyle "veri tabanı/rehber oluşturmasını ve kendi sistemine indirmesini" yasaklıyor, üçüncü tarafla paylaşımda protokol hükümlerini içeren sözleşme zorunlu tutuyor ve ihlal için **500.000 TL (yeniden değerlemeli) cezai şart** öngörüyor. NetKâr kişisel veriyi hiç saklamayacak şekilde (ingest anında atma) tasarlanmalı ve satıcıyla EK-6'yı yansıtan bir veri işleme sözleşmesi imzalanmalı. (Güven: Yüksek; okunan sözleşme sürümü 2022_V37, güncel panel sürümü Doğrulanmadı)
- **Platform politika riski orta:** Trendyol API'yi sık ve kısa önceden haberle değiştiriyor (2025 base URL değişimi, Haziran 2026 sipariş limiti, Eylül 2026 ürün limitleri, 15 Ekim 2026 zorunlu Order V2). Sözleşme Trendyol'a tek taraflı değişiklik ve "bilgi güvenliği riski" gerekçesiyle askıya alma yetkisi veriyor. Rekabet Kurulu 2023'te Trendyol'a satıcı verisini kendi lehine kullanma nedeniyle 61,34 milyon TL ceza verdi; bu, platformun satıcı verisi konusundaki hassasiyetini ve olası "kendi kârlılık aracını çıkarma" rekabet riskini gösteriyor. (Güven: Yüksek/Orta)
- **Soru-cevap API'si AI taslak özelliğine uygun:** Listeleme ve cevap gönderme endpoint'leri var; cevap 10 ile 2000 karakter, yasaklı kelime kontrolü var, yanlış cevap tekrarları soruyu kalıcı kapatabiliyor. AI yanıtı "taslak + insan onayı" olarak tasarlanmalı. (Güven: Yüksek)

**KARAR: KOŞULLU GO**

Gerekçe: Teknik olarak ürün bazında net kârın Trendyol tarafındaki ana bileşenleri (satış, indirimler, komisyon, iade, kargo/desi, hakediş, stopaj, platform hizmet bedeli) resmi ve dokümante API'lerden çekilebiliyor; üçüncü taraf yazılımın satıcı adına API kullanması dokümanda açıkça öngörülmüş. "Rahatça mümkün" demeyi engelleyen dört koşul var:
1. **Sözleşmesel teyit:** Trendyol'dan (Taleplerim/entegrasyon destek kanalı üzerinden) "salt-okuma amaçlı, entegratör adıyla User-Agent gönderen üçüncü taraf analitik SaaS" kullanımının uygun olduğuna ve mümkünse salt-okuma rolüyle API anahtarı oluşturulabileceğine dair yazılı yanıt alınmalı.
2. **KVKK tasarımı:** Müşteri kişisel verisi saklanmamalı; satıcıyla EK-6 uyumlu veri işleme sözleşmesi, silme/iade ve 48 saat ihlal bildirimi süreçleri hazır olmalı.
3. **Reklam ve fatura düzeyi kesintiler:** Ürün bazında reklam maliyeti için Excel yükleme veya dağıtım modeli; platform hizmet bedeli ve benzeri kesintiler için şeffaf dağıtım kuralı kabul edilmeli. Ürün "gerçek net kârı" bu kalemlerde tahmini (allocated) olacak, kullanıcıya böyle etiketlenmeli.
4. **Canlı hesapla doğrulama:** Bir pilot satıcının gerçek verisiyle `DeductionInvoices` satırlarının (reklam, ceza, platform hizmet bedeli) hangi `transactionType` metinleriyle ve sipariş numarası taşıyıp taşımadığı test edilmeli.

Bu dört koşuldan herhangi biri olumsuz çıkarsa (özellikle 1. ve 2.), karar NO-GO'ya değil "dar kapsamlı GO"ya (yalnızca satıcının kendi ekranında, veri saklamadan hesap) dönmeli.

---

## 2. Bulgular (başlık başlık)

### 2.1 Erişim

| Konu | Bulgu | Kaynak | Güven |
|---|---|---|---|
| Anahtar nereden alınır | `supplierId`/`sellerId`, `API KEY`, `API SECRET KEY`: Satıcı Paneli > Hesap Bilgilerim > **Entegrasyon Bilgileri** (`partner.trendyol.com/account/info?tab=integrationInformation`). Yalnızca **master user (admin rolü)** ile girişte görünüyor. | Trendyol (2026a), Trendyol (2026e) | Yüksek |
| Entegratör başına ayrı anahtar ve rol | Paraşüt kılavuzu, Entegrasyon Bilgileri ekranında "yeni API oluşturulurken entegratör adı girilip seçilebilir rollerin verildiği" bir akış tarif ediyor. Bu, entegratör bazında ayrı anahtar ve rol (yetki kapsamı) seçimi olabileceğini gösteriyor. Resmi dokümanda rol listesi yok. | Paraşüt (t.y.) | Orta (rol detayları Doğrulanmadı) |
| Üçüncü tarafın satıcı adına kullanımı | Resmi doküman: "Eğer bir aracı firma ile çalışılıyorsa User-Agent bilgisi olarak `Satıcı Id - {Entegrasyon Firması İsmi}`, entegrasyon yazılımı firmaya aitse `Satıcı Id - SelfIntegration` gönderilmelidir." Sözleşme md. 4.6 da satıcının bilgileri "başta entegratörler olmak üzere üçüncü kişilerle" paylaşmasını öngörüyor. Yani üçüncü taraf kullanım platformca öngörülmüş. | Trendyol (2026a), DSM Grup (2022) | Yüksek |
| "Onaylı entegratör" şartı | Resmi dokümanda entegratör kayıt/onay/başvuru süreci, onaylı entegratör listesi veya sertifikasyon bulunamadı. Destek için satıcı panelinde "Entegrasyon Referans Kodu" var; entegratörün Trendyol'dan destek alması için bu kodu kullanması zorunlu. | Trendyol (2026f) | Orta (yokluk kanıtı; Trendyol'a sorulmalı) |
| User-Agent zorunluluğu | Tüm isteklerde Auth ve User-Agent header'da olmalı; User-Agent olmayan istekler **403** ile engelleniyor. Entegratör adı alfanumerik, **en fazla 30 karakter**. NetKâr için önerilen: `"{sellerId} - NetKar"` (Türkçe karakter kullanılmamalı). | Trendyol (2026a) | Yüksek |
| IP kısıtı (canlı) | Canlı ortamda **IP yetkilendirmesi gerekmiyor**, ancak "IP'niz bazı nedenlerden dolayı engellenmiş olabilir"; bu durumda IP ile bildirim açılıyor. | Trendyol (2026c) | Yüksek |
| Test (stage) ortamı | `https://stageapigw.trendyol.com`, panel `https://stagepartner.trendyol.com`. Stage hesap ve API bilgileri canlıdan tamamen farklı. Erişim **IP whitelist** gerektiriyor (çağrı merkezi 0850 258 58 00 veya panel bildirimi; IP 24 saat içinde tanımlanıyor). IP tanımsızsa **503**. Ortak test hesabı veya özel test hesabı (e-posta, telefon, TCKN/VKN ile talep) alınabiliyor. Dokümanda "Statik IP'ler için yetkilendirme sağlanamamaktadır" cümlesi geçiyor; anlamı belirsiz (muhtemelen yazım hatası), Trendyol'a sorulmalı. | Trendyol (2026c), Trendyol (2026f) | Yüksek (statik IP cümlesi Doğrulanmadı) |
| Canlı URL | Güncel: **`https://apigw.trendyol.com`** (ör. `/integration/order/sellers/{sellerId}/...`). Eski `https://api.trendyol.com/sapigw/` ve `stageapi.trendyol.com/stagesapigw/` 2025'te kapatıldı (changelog 25-26.02.2025: "Eski servisler ... kapatılacaktır", tüm servisler yeni base url'de). Bazı eski açık kaynak kütüphaneler (örn. Python SDK) hâlâ eski URL'yi kullanıyor, kullanılmamalı. | Trendyol (2026c), Trendyol (2026g), altuntasmuhammet (2023) | Yüksek |
| Test siparişi | Stage'de test siparişi oluşturma ve statü güncelleme servisleri var (`createtestorder`, `updatetestorderstatus`). | Trendyol (2026e) | Yüksek |

### 2.2 Kimlik doğrulama

| Konu | Bulgu | Kaynak | Güven |
|---|---|---|---|
| Yöntem | **HTTP Basic Auth**: username = API Key, password = API Secret. Token akışı yok. | Trendyol (2026a), Trendyol (2026f) | Yüksek |
| Token süresi | Basic Auth olduğu için token/expiry kavramı yok; anahtar geçerli olduğu sürece çalışır. Bir ticari blog (Zunapro) "OAuth 2.0 client_credentials" akışından söz ediyor; resmi dokümanda karşılığı yok. | Trendyol (2026a), Zunapro (t.y.) | Yüksek (OAuth iddiası Düşük, büyük olasılıkla yanlış) |
| Hatalı yetki | `401`, `"exception": "ClientApiAuthenticationException"`. | Trendyol (2026a) | Yüksek |
| Anahtar değişince | Resmi dokümanda anahtar yenileme/iptal davranışı yazmıyor. Basic Auth mantığıyla eski anahtar geçersizleşirse NetKâr çağrıları 401 alır; uygulama 401'de bağlantıyı "yeniden bağlan" durumuna almalı ve kullanıcıyı uyarmalı. Entegratör bazlı ayrı anahtar mümkünse satıcı NetKâr erişimini diğer entegratörleri bozmadan iptal edebilir. | Çıkarım; Paraşüt (t.y.) | Doğrulanmadı |
| Gizlilik | Doküman API key'in açık platformlarda paylaşılmamasını özellikle vurguluyor. Sözleşme md. 4.8: şifre ve kullanıcı adı güvenliği tamamen satıcının sorumluluğunda; satıcı hesabından yapılan işlemlerin "yetkisiz" olduğunu ileri sürme hakkından feragat ediyor. Yani NetKâr'daki bir sızıntının sonuçları satıcıya, dolayısıyla sözleşmesel olarak NetKâr'a döner. Anahtarlar KMS ile şifrelenmeli. | Trendyol (2026a), DSM Grup (2022) | Yüksek |

### 2.3 Rate limit ve sayfalama

| Servis | Limit | Sayfalama / pencere | Kaynak | Güven |
|---|---|---|---|---|
| Genel kural | Aynı endpoint'e **10 saniyede en fazla 50 istek**, 51. istek `429 too.many.requests`. | | Trendyol (2026a) | Yüksek |
| Sipariş Paketlerini Çekme (`v2/orders`) | Listeleme limitine göre: 50.000 ürün: **30/dk**, 75.000: 40/dk, 150.000: 50/dk, 500.000 ve limitsiz: **100/dk**. Aynı sayfanın başka yerinde "1 dakikada en fazla 1000 istek" yazıyor (eski bilgi, çelişki). | `size` en fazla **200**; tarih yoksa son 1 hafta, verilirse en fazla **2 hafta**; en fazla **1 ay** geriye; **10.000 shipmentPackageId** erişim penceresi (`page` 0 ile 49 arası güvenli). `totalElements > 10000` ise tarih aralığı daraltılmalı veya stream kullanılmalı. | Trendyol (2026b), Trendyol (2026d) | Yüksek (çelişki not edildi) |
| Order V2 zorunluluğu | Eski `/orders` endpoint'i **15 Ekim 2026** itibarıyla kullanım dışı; geçiş dönemi boyunca günde 3 kez 10'ar dakika `426` döndürüldü. | | Trendyol (2026g) | Yüksek |
| Sipariş Paketlerini Akış ile Çekme (`orders/stream`) | Ayrı limit tablosunda yok; "en az 5 saniye aralıkla istek" önerisi var. | Cursor tabanlı (`nextCursor`, `hasMore`); **son 3 ay** verisi; `lastModifiedStartDate/EndDate` en fazla **14 gün**; `size` varsayılan 50, en fazla 200; sıralama sabit (lastModified DESC); cursor ile filtre değişirse 400. | Trendyol (2026h) | Yüksek (stream'in kendi rate limiti Doğrulanmadı) |
| İade (`claims`) | Çekme **1000/dk**, onay ve ret talebi **5/dk**, audit 1000/dk. | `size` en fazla 200; tarih filtresi `lastModifiedDate` üzerinden; tarih aralığı üst sınırı dokümante değil. | Trendyol (2026d), Trendyol (2026i) | Yüksek (aralık sınırı Doğrulanmadı) |
| Finans (Cari Hesap Ekstresi) | **100/dk** | `startDate`-`endDate` en fazla **15 gün**; `size` 500 veya 1000; alternatif olarak `paymentDate` veya `paymentOrderId`; `payment-order` listesinde sayfa başına en fazla 10. | Trendyol (2026d), Trendyol (2026j) | Yüksek |
| Kargo Faturası Detayları | **100/dk** | `size` varsayılan 500. | Trendyol (2026d), Trendyol (2026k) | Yüksek |
| Soru-cevap | Çekme **1000/dk**, cevaplama **500/dk** (27 Mart 2026'dan itibaren). | `size` varsayılan 20, en fazla 50; tarih yoksa son 1 hafta, en fazla 2 hafta aralık. | Trendyol (2026d), Trendyol (2026l) | Yüksek |
| Ürün (14 Eylül 2026 sonrası) | Grup bazlı: **Product Integration Read** 1000 ile 2000/dk, **Write** 200 ile 600/dk, **Inventory & Price Write** 350 ile 2000/dk (listeleme limitine göre). Buybox Kontrol servisi Write grubunda sayılıyor. Aynı barkod için fiyat güncellemesi 30/dk. | Onaylı ürün v2: `size` en fazla 100, `page x size` en fazla 10.000, fazlası için `nextPageToken`. | Trendyol (2026d), Trendyol (2026m) | Yüksek |
| Limitin kapsamı | Limitlerin satıcı (sellerId) bazında mı, IP bazında mı, API anahtarı bazında mı sayıldığı yazmıyor. Çok satıcılı SaaS için kritik. | | | Doğrulanmadı |

Kapasite notu (çıkarım): Ayda 10.000 paketlik bir satıcının günlük stream senkronu birkaç düzine istekle biter; 12 aylık finans backfill'i (24 pencere x birkaç transactionTypes x sayfa) 100/dk limitte dakikalar sürer. Asıl darboğaz, limitler IP bazlıysa yüzlerce satıcıyı aynı çıkış IP'sinden çekmek olur; bu Trendyol'a sorulmalı.

### 2.4 Kâr hesabı için veriler

#### a) Siparişler / paketler

- **Endpoint:** `GET https://apigw.trendyol.com/integration/order/sellers/{sellerId}/v2/orders` ve `GET .../orders/stream`. (Trendyol, 2026b; 2026h) Güven: Yüksek.
- **Paket seviyesi alanlar:** `orderNumber`, `shipmentPackageId` (paket id), `packageGrossAmount` (indirimsiz brüt), `packageSellerDiscount`, `packageTyDiscount`, `packageTotalDiscount`, `packageTotalPrice` (faturalanacak net tutar), `discountDisplays[]` (kampanya adı ve tutarı), `cargoProviderName`, `cargoDeci`, `deci`, `boxQuantity`, `whoPays` (1 ise satıcı kargo anlaşması), `status`, `packageHistories[]`, `orderDate` (GMT+3 ms), `lastModifiedDate`, `commercial` (kurumsal fatura), `micro` (mikro ihracat), `is4P`, `3pByTrendyol`, `channelId` (1 TR core, 25 luxury), `createdBy` (order-creation/cancel/split/transfer), `originPackageIds`, `paymentMethod`. Güven: Yüksek.
- **Satır seviyesi (`lines[]`):** `barcode`, `stockCode`, `contentId`, `productCategoryId`, `quantity`, `lineGrossAmount`, `lineSellerDiscount`, `lineTyDiscount`, `lineTotalDiscount`, `lineUnitPrice`, `vatRate`, **`commission` (komisyon oranı, %)**, `salesCampaignId`, `cancelledBy`, `cancelReason`, `businessUnit`, `laborCost` (changelog'a göre). **Komisyon tutarı siparişte yok, yalnızca oran var**; tutar finans `settlements` servisinden gelir. Güven: Yüksek.
- **Kalem seviyesi (`discountDetails[]`):** Her adet için `lineItemPrice`, `lineItemSellerDiscount`, `lineItemTyDiscount`. Temel kural: `lineItemPrice = lineGrossAmount - lineItemSellerDiscount - lineItemTyDiscount`. Satıcı karşılamalı ve Trendyol karşılamalı indirim ayrı alanlarda. Güven: Yüksek. (Trendyol, 2026n)
- **Çelişki:** İndirim kılavuzu "Trendyol kuponu ... satıcıya yansıtılmaz" ve senaryolarda `packageTyDiscount` dolu gösteriyor, ama aynı sayfa "`packageTyDiscount` yalnızca `commercial=true` siparişlerde dolu gelebilir" diyor. Bireysel siparişlerde Trendyol indiriminin satır alanlarında görünüp görünmediği canlı veriyle test edilmeli. Güven: Doğrulanmadı.
- **Kısmi iptal ve bölme:** Bir kalem iptal olursa paket bozulur, aynı `orderNumber` ile yeni paket id ve kargo barkodu oluşur. Kâr motoru paket değil **satır/kalem (`lineId`, `lineItemId`)** anahtarıyla çalışmalı. Güven: Yüksek.
- **Zamanlama:** Finansal kayıtlar sipariş **teslim edildikten sonra** oluşuyor. Teslim edilmemiş siparişler için kâr, sipariş satırındaki `commission` oranı ve tahmini kargo ile "öngörülen kâr" olarak gösterilmeli, settlement gelince "kesinleşmiş kâr"a dönüşmeli. Güven: Yüksek. (Trendyol, 2026j)

#### b) İadeler (claims)

- **Endpoint:** `GET https://apigw.trendyol.com/integration/order/sellers/{sellerId}/claims`. Parametreler: `claimIds`, `claimItemStatus`, `startDate`/`endDate` (lastModifiedDate), `orderNumber`, `page`, `size` (en fazla 200). Güven: Yüksek. (Trendyol, 2026i)
- **Önemli alanlar:** `claimId`, `orderNumber`, `orderShipmentPackageId`, `claimDate` (GMT), `cargoTrackingNumber`, `cargoProviderName`, `items[].orderLine` (`barcode`, `merchantSku`, `price`, `vatRate`, `productCategory`), `claimItems[]` (`customerClaimItemReason` ve `trendyolClaimItemReason`: `id`, `name`, `code` ör. `UNFIT`; `claimItemStatus`; `autoAccepted` (48 saat aksiyon alınmazsa otomatik kabul); `acceptedBySeller`; `customerNote`), `rejectedPackageInfo`, `replacementOutboundpackageinfo` (değişim). Statüler: Created, WaitingInAction, WaitingFraudCheck, Accepted, Rejected, Cancelled, Unresolved, InAnalysis. Güven: Yüksek.
- **İade nedeni:** Var (müşteri ve Trendyol nedeni ayrı; ayrıca `iade-sebepleri` sayfasında kod listesi). Güven: Yüksek.
- **İade kargo bedeli:** `claims` yanıtında **yok**. İade kargo bedeli Kargo Faturası Detayları servisinde `shipmentPackageType = "İade Kargo Bedeli"` satırı olarak, `orderNumber` ve `amount`, `desi` ile geliyor. Güven: Yüksek. (Trendyol, 2026k)
- **İadenin finansal etkisi:** `settlements` içinde `Return` (iade), `DiscountCancel`, `CouponCancel`, `ManualRefund` (kısmi iade), `DeliveryFeeCancel` satırları; iade satırında komisyon geri yazılıyor (comissionAmount +, sellerRevenue -). Güven: Yüksek.
- **Ek:** Sipariş satırında `defectiveClaimListingInsight` alanı, kusurlu/eksik/yanlış nedenli iade geçmişi olan üründe uyarı metni döndürüyor; ürün kalite içgörüsü için kullanılabilir. TEX kargoda kayıp/hasar tazminleri `GET .../integration/tex/compensation/sellers/{sellerId}/tickets` ile izlenebiliyor. Güven: Yüksek. (Trendyol, 2026b; 2026o)

#### c) Finans: Cari Hesap Ekstresi

Base: `https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/` (Trendyol, 2026j). Güven: Yüksek.

- **`settlements`**: satış, iade, indirim, kupon, provizyon ve düzeltme kayıtları.
  - `transactionType`/`transactionTypes` (zorunlu): `Sale`, `Return`, `Discount`, `DiscountCancel`, `Coupon`, `CouponCancel`, `ProvisionPositive`, `ProvisionNegative`, `ManualRefund`, `ManualRefundCancel`, `TyDiscount`, `TyDiscountCancel`, `TyCoupon`, `TyCouponCancel`, `SellerRevenuePositive`, `SellerRevenueNegative`, `CommissionPositive`, `CommissionNegative`, `SellerRevenuePositiveCancel`, `SellerRevenueNegativeCancel`, `CommissionPositiveCancel`, `CommissionNegativeCancel`, `DeliveryFee`, `DeliveryFeeCancel`, `PayByLink`.
  - Satır alanları: `id`, `transactionDate`, **`barcode`**, `transactionType` (Türkçe metin, ör. "Satış"), `receiptId` (dekont no), `debt`, `credit`, `paymentPeriod` (vade günü), **`commissionRate`**, **`commissionAmount`**, `commissionInvoiceSerialNumber`, **`sellerRevenue`** (satıcı hakedişi), **`orderNumber`**, `paymentOrderId`, `paymentDate`, `orderDate`, `affiliate` (`TRENDYOLTR`/`TRENDYOLAZJV`), **`shipmentPackageId`** (Mart 2025'te eklendi).
  - **Sipariş/ürün eşleşmesi:** Evet; satış satırı `orderNumber` + `shipmentPackageId` + `barcode` taşıyor. Aynı siparişte aynı barkoddan birden fazla adet varsa satırın adet mi yoksa satır toplamı mı olduğu dokümante değil (örnekte adet alanı yok). Güven: Eşleşme Yüksek, adet granülerliği Doğrulanmadı.
  - İşaret kuralları dokümanda tablo halinde var (ör. `Sale`: komisyon -, hakediş +; `Return`: komisyon +, hakediş -; `Discount`: satıcı karşılamalı indirim). `TyDiscount`/`TyCoupon` yalnızca kurumsal faturalı alışverişlerde ve ay sonu faturayla satıcıya ödeniyor.
- **`otherfinancials`**: sipariş dışı kayıtlar.
  - `transactionType`: `Stoppage` (e-ticaret stopajı ve iptali; 1 Ocak 2025'ten itibaren %1), `CashAdvance` (erken ödeme), `WireTransfer` (virman), `IncomingTransfer`, `ReturnInvoice` (satıcıdan Trendyol'a iade faturası), `CommissionAgreementInvoice` (komisyon mutabakat faturası), `PaymentOrder` (hakediş ödemesi), **`DeductionInvoices`** ("Trendyol tarafından sağlanan hizmetler için tedarikçiye kesilen fatura"), `FinancialItem` (Trendyol düzeltme kayıtları).
  - `transactionSubType=PlatformServiceFee` (18.03.2026'dan beri) yalnızca `DeductionInvoices` ile birlikte: **platform hizmet bedeli** faturaları.
  - Kargo faturaları da `DeductionInvoices` içinde, `transactionType` metni "Kargo Faturası"/"Kargo Fatura" olan satırlar; bu satırın `id` değeri kargo faturası seri numarası.
  - Örnek yanıtta `orderNumber` null, `shipmentPackageId` dolu görünüyor (PaymentOrder örneği); fatura türü satırların sipariş taşıyıp taşımadığı belirsiz. Güven: Doğrulanmadı.
- **`payment-order`**: Satıcının PAID ödeme emirleri (`id`, `amount`, `payoutDate`, `paymentType`); `id` -> `paymentOrderId` ile o hakediş dönemine ait tüm `settlements`/`otherfinancials` çekilebiliyor. Ödeme emirleri istisnalar hariç her **çarşamba** oluşuyor; settlement verisinin güncellenmesi zaman alabildiği için "bir sonraki gün sorgulayın" öneriliyor.
- **Tarih aralığı:** `startDate`-`endDate` en fazla **15 gün**; ya da `paymentDate` (yyyy-MM-dd, Europe/Istanbul) ya da `paymentOrderId`. Geriye dönük maksimum süre yazmıyor (Doğrulanmadı).
- **Ceza:** Dokümanda "ceza" adında bir transactionType yok. Gecikme/operasyon cezalarının `DeductionInvoices` veya `FinancialItem` altında gelmesi muhtemel. Güven: Doğrulanmadı.
- **Erken ödeme:** `CashAdvance` erken ödeme kaydı; erken ödeme hizmet bedelinin hangi satırda geldiği yazmıyor. Sözleşmede ayrı bir "Kesinti ve Erken Ödeme" eki var. Güven: Doğrulanmadı.

#### d) Kargo faturası / desi bedeli

- **Akış:** (1) `otherfinancials?transactionType=DeductionInvoices` ile kargo faturası satırlarını bul, `id` = `invoiceSerialNumber`; (2) `GET .../finance/che/sellers/{sellerId}/cargo-invoice/{invoiceSerialNumber}/items`. Güven: Yüksek. (Trendyol, 2026k)
- **Alanlar:** `shipmentPackageType` ("Gönderi Kargo Bedeli", "İade Kargo Bedeli"), `parcelUniqueId`, **`orderNumber`**, **`amount`**, **`desi`**.
- **Sipariş bazına iner mi:** Evet, **sipariş numarası bazında**. Ürün bazına inmez; çok ürünlü siparişte dağıtım (desi oranı, tutar oranı veya adet) gerekir. Fatura gelene kadar siparişteki `cargoDeci`/`deci` ve kargo firması ile tahmini kargo hesaplanabilir ("Bu bilgi sonradan değişebilmektedir" notu var). Güven: Yüksek.
- `parcelUniqueId` siparişteki `cargoTrackingNumber` ile eşleşiyor gibi görünüyor (örnek değer formatı benzer). Güven: Doğrulanmadı.

#### e) Reklam harcaması

- **API:** developers.trendyol.com dizininde (`llms.txt`, 2026 güncel) reklam, sponsorlu ürün, mağaza reklamı veya influencer reklamı için **hiçbir endpoint yok**. Tüm doküman metinlerinde "reklam"/"advert" kelimesi geçmiyor. Güven: Yüksek (resmi dizin taranarak).
- **Ekstrede görünüm:** Trendyol Akademi'ye göre reklam bakiyesi satın alımında bakiye tutarı kadar fatura kesiliyor ve tutar bir sonraki hakedişten mahsup ediliyor; bakiye hakedişten aktarılabiliyor ya da kredi kartıyla alınabiliyor; Cari Hesap Ekstresi'nde "Satıcı Reklamı Satın Alma" olarak görünüyor; reklam bakiyesine aktarılan tutar iade edilmiyor. Güven: Orta (Akademi metni doğrudan okunamadı, arama özetinden).
- **API'de hangi satır:** Reklam faturasının `otherfinancials` içinde `DeductionInvoices` olarak mı başka tipte mi geldiği hiçbir resmi kaynakta yok. Güven: Doğrulanmadı (pilot hesapla test edilmeli).
- **Ürün bazında kırılım:** Satıcı panelinde "Oluşturulan Reklamlar" sayfasında reklam bazında metrikler (harcama, reklamdan gelen ciro, ROAS) ve "Excel İndir" ile rapor var; veriler saatlik yenileniyor; atıf penceresi reklamı gören müşterinin 7 gün içindeki alımı. Ürün reklamı ürün bazında kurulduğu için bu Excel ürün bazında harcama verir, ama **yalnızca panelden manuel indirme** ile. Güven: Orta.
- **Önemli:** Ekstrede görünen tutar "bakiye yükleme" anındaki tutardır, harcanan tutar değil. Muhasebe gideri ile dönemsel reklam harcaması farklı olacak; NetKâr ürün kârlılığında **harcanan** tutarı (Excel) kullanmalı, nakit akışında **yüklenen** tutarı göstermeli. Güven: Orta (çıkarım).
- **Yasak alan:** Panel ekranlarını otomatik kazımak (scraping/RPA) sözleşme md. 4.10 (platforma teknik zarar vermeme) ve md. 4.13 (bilgi güvenliği riski gerekçesiyle askıya alma) kapsamında hesap riskine yol açar; önerilmez.

#### f) Ürün kataloğu

- **Onaylı ürünler v2:** `GET https://apigw.trendyol.com/integration/product/sellers/{sellerId}/products/approved`. Alanlar: `contentId`, `productMainId`, `brand`, **`category` (`id`, `name`)**, `title`, `attributes`, `variants[]`: **`barcode`**, `stockCode`, **`commission`** (varyant komisyon oranı), `price` (`salePrice`, `listPrice`, **`priceSeenByCustomer`**), `stock.quantity`, `onSale`, `channels` (CORE/LUXE), `productUrl`. Filtreler: `barcode`, `barcodes` (en fazla 50), `stockCode`, tarih ve `dateQueryType`. Güven: Yüksek. (Trendyol, 2026m)
- **Stok ve fiyat odaklı v2** sorgusu ayrıca var (`filterapprovedproductsinventoryandprice`).
- **Buybox:** `POST .../integration/product/sellers/{sellerId}/products/buybox-information`, istek başına en fazla **10 barkod**; yanıt `buyboxOrder`, `buyboxPrice`, `hasMultipleSeller`, `secondBuyboxPrice`, `thirdBuyboxPrice`. Güven: Yüksek. (Trendyol, 2026p)
- **Komisyon oranı ve KDV:** Sözleşme ekindeki komisyon tablosu oranları "KDV Dahil" olarak tanımlıyor. API'deki `commission` alanının KDV dahil oran olduğu açıkça yazmıyor. Güven: Orta (sözleşme), API alanı için Doğrulanmadı.

#### g) Müşteri soruları

- **Listeleme:** `GET https://apigw.trendyol.com/integration/qna/sellers/{sellerId}/questions/filter` (`barcode`, `status`: WAITING_FOR_ANSWER, ANSWERED, REPORTED, REJECTED, UNANSWERED; `startDate`/`endDate` en fazla 2 hafta; `size` en fazla 50; sıralama `LastModifiedDate`/`CreatedDate`). Tekil: `GET .../questions/{id}`. Yanıt: `id`, `text`, `productName`, `customerId`, `userName`, `showUserName`, `public`, `answer` (`hasPrivateInfo`), `rejectedAnswer`, `webUrl`, `imageUrl`. Güven: Yüksek. (Trendyol, 2026l)
- **Cevap gönderme:** `POST .../questions/{id}/answers`, gövde `{"text": "..."}`; **10 ile 2000 karakter**; yasaklı kelime kontrolü; yalnızca `WAITING_FOR_ANSWER` cevaplanabilir; reddedilen cevap soruyu bekleme statüsüne döndürür, belirli sayıda yasaklı kelimeli cevap soruyu **UNANSWERED** yapar ve bir daha cevaplanamaz; 3 iş günü içinde yanıtlanmayan sorular kapanır. Güven: Yüksek. (Trendyol, 2026q)
- **Tasarım sonucu:** AI yanıtı otomatik gönderilmemeli; "taslak + satıcı onayı" akışı ve gönderim öncesi yerel yasaklı kelime/kişisel veri filtresi gerekli. Sözleşme md. 4.17 platform dışı iletişimi yasakladığı için AI taslağı müşteriyi site dışına yönlendirmemeli.

### 2.5 Webhook ve polling

- **Var:** `POST https://apigw.trendyol.com/integration/webhook/sellers/{sellerId}/webhooks` (listeleme, güncelleme, silme, aktif/pasif servisleri de var). Abone olunabilen statüler: CREATED, PICKING, INVOICED, SHIPPED, CANCELLED, DELIVERED, UNDELIVERED, RETURNED, UNSUPPLIED, AWAITING, UNPACKED, AT_COLLECTION_POINT, VERIFIED. Payload, `getShipmentPackages` ile aynı tam sipariş modelidir (müşteri adresleri dahil). Güven: Yüksek. (Trendyol, 2026r; 2026s)
- **Kurallar:** Webhook URL'sinde "Trendyol", "Dolap", "Localhost" geçmemeli; endpoint yetkilendirmesi `BASIC_AUTHENTICATION` veya `API_KEY` (`x-api-key` header); satıcı başına **en fazla 15 webhook** (pasifler dahil); **at-least-once** teslim (idempotent alıcı zorunlu); başarısızlıkta 5 dakikada bir yeniden deneme; **13 hatada** otomatik pasife alma ve iki bilgilendirme e-postası; 06.10.2026'da yaşanan kesinti gibi olaylar changelog'da duyuruluyor. Trendyol, webhook kullanılsa bile `getShipmentPackages` ile periyodik eşitleme yapılmasını tavsiye ediyor. Güven: Yüksek.
- **Yok:** İade, finans, soru-cevap, ürün ve reklam için webhook yok. Güven: Yüksek (dizinde yalnızca sipariş paketi webhook'u var).
- **Önerilen strateji (çıkarım):**
  - Siparişler: webhook (CREATED, CANCELLED, DELIVERED, RETURNED, UNSUPPLIED, UNPACKED) + her 15 ile 30 dakikada bir `orders/stream` artımlı eşitleme (`lastModifiedStartDate` = son başarılı senkron - güvenlik payı). Webhook kotası satıcının diğer entegratörleriyle paylaşıldığı için webhook opsiyonel olmalı.
  - İadeler: 30 ile 60 dakikada bir `claims` (lastModifiedDate penceresi).
  - Finans: günde 1 kez son 15 gün `settlements` + `otherfinancials`; ayrıca her perşembe `payment-order` ile yeni ödeme emri tespit edilip `paymentOrderId` ile tam dönem mutabakatı.
  - Kargo faturası: yeni `DeductionInvoices` kargo satırı görüldüğünde detay çekimi.
  - Soru-cevap: 5 ile 15 dakikada bir `WAITING_FOR_ANSWER`.
  - Ürün/buybox: günde 1 ile 4 kez.

### 2.6 Kişisel veri (KVKK veri minimizasyonu)

Sipariş/webhook yanıtında dönen kişisel veriler (Trendyol, 2026b; 2026r). Güven: Yüksek (alan varlığı); doluluk durumu kısmen Doğrulanmadı.

| Alan | Dönüyor mu | Maskeleme / not |
|---|---|---|
| `customerFirstName`, `customerLastName` | Evet | Maskesiz. Trendyol Yurt Dışı Aracılığı siparişlerinde DSM bilgisi. |
| `customerEmail` | Evet | **Maskeli/relay**: örnekte `pf+j2jm8x99@trendyolmail.com`. |
| `customerId` | Evet | Trendyol müşteri hesabına özgü sabit id (takma ad niteliğinde kişisel veri). |
| `shipmentAddress` (ad, soyad, açık adres, il/ilçe/mahalle, posta kodu, `phone`, `fullAddress`) | Evet | Maskesiz. Telefon alanının gerçek numarayla dolu gelip gelmediği belirsiz: sözleşme EK-6 md. 4.1 "telefon ve/veya e-posta gibi iletişim bilgileri kural olarak paylaşılmaz" diyor (yalnızca drone, kendi teslimatı, dijital ürün gibi istisnalar). Güven: Doğrulanmadı. |
| `invoiceAddress` (aynı alanlar + `latitude`, `longitude`; kurumsalda `company`, `taxNumber`, `taxOffice`) | Evet | Maskesiz. Kurumsal siparişte vergi no. |
| `identityNumber` (TCKN) | Koşullu | Altın, gübre veya 5000 TL üzeri siparişlerde. |
| `claims` yanıtı | Evet | Müşteri adı/soyadı, red paketinde teslimat adresi. |
| Soru-cevap | Evet | `customerId`, `userName` (görünürlük `showUserName`). |

**Sözleşmesel kısıtlar (DSM Grup, 2022, EK-6):**
- md. 3.2: Satıcı kişisel verileri yalnızca Ana Sözleşme'deki hizmet amacıyla işleyebilir ve aktarabilir.
- md. 3.3: Üçüncü tarafla paylaşımda veri aktarımının güvenliğinden satıcı sorumlu; üçüncü kişiyle **en az bu Protokol hükümlerini içeren sözleşme** zorunlu. -> NetKâr, satıcıyla EK-6'yı yansıtan bir veri işleme sözleşmesi (DPA) imzalamalı.
- md. 3.5: Bilgi güvenliği ihlalinde **en geç 48 saat** içinde DSM'ye bilgi (ikincil bir 2026 kaynağı ek hizmetler sözleşmesinde 24 saatten söz ediyor; Doğrulanmadı).
- md. 3.7: Sözleşme sona erdiğinde veya **DSM gerekçesiz talep ettiğinde** veriler (yedekleri dahil) iade veya geri döndürülemez şekilde silinmeli ve **denetim raporu** sunulmalı.
- md. 3.10: DSM'nin denetim yetkisi (satıcının iş ortaklarına yansır).
- md. 4.2: Satıcı, elde ettiği kişisel verileri "kendisine ya da başka bir kişiye ait **veri tabanı, kayıt veya rehber yaratmak** ... ve **kendi sistemine indirmek** amacıyla işlemeyeceğini" taahhüt eder.
- md. 4.3: Özel düzenlemeler ihlalinde **500.000 TL cezai şart** (her yıl yeniden değerleme oranıyla artırılarak), satıcı ödemelerinden mahsup edilebilir.

**NetKâr tasarım önerisi:** Ingest katmanında `shipmentAddress`, `invoiceAddress`, `customerFirstName/LastName`, `customerEmail`, `identityNumber`, `phone`, koordinatlar ve `taxNumber` alanları **diske yazılmadan atılmalı** (allowlist yaklaşımı: yalnızca finansal ve ürün alanları saklanır). Bölgesel analiz isteniyorsa yalnızca il kodu tutulabilir. `customerId` tekrar eden müşteri analizi için gerekiyorsa satıcı bazlı tuzlu hash ile tutulabilir, ancak md. 4.2'nin "kayıt yaratma" yasağı karşısında hukukçu onayı olmadan önerilmez. Webhook payload'ı da tam müşteri verisi taşıdığı için webhook alıcısı ham gövdeyi loglamamalı.

### 2.7 Kurallar ve riskler

| Risk | Bulgu | Kaynak | Güven |
|---|---|---|---|
| Ayrı bir "API kullanım koşulları" metni | developers.trendyol.com'da ayrı bir API ToS/kullanım koşulları sayfası bulunamadı; bağlayıcı kurallar satıcı sözleşmesi ve doküman notlarından geliyor. | Trendyol (2026e) | Orta (yokluk kanıtı) |
| Gizlilik maddesi | Sözleşme md. 6.1: "alıcı ve piyasa bilgileri" dahil ticari ilişkide öğrenilen bilgiler "Gizli Bilgi"; taraflar bunları üçüncü kişilerle paylaşmamayı ve ticari ilişkinin amaçları dışında kullanmamayı taahhüt eder. Entegratör kullanımı md. 4.6 ve dokümanla öngörüldüğü için satıcının kendi işi için hizmet sağlayıcı kullanması makul yorumla ticari ilişkinin amacı içinde; ancak **NetKâr'ın bir satıcının verisini başka satıcılara kıyas (benchmark) amacıyla kullanması** bu maddeyle çatışabilir. | DSM Grup (2022) | Yüksek (metin), yorum Orta |
| Veri saklama ve silme | EK-6 md. 3.7: talep halinde silme/iade + denetim raporu. Retention politikası ve "satıcı ayrılınca 30 gün içinde silme" gibi bir süreç kurgulanmalı. | DSM Grup (2022) | Yüksek |
| Scraping | Trendyol tüketici sitesi kullanım koşullarında otomatik veri toplama yasağı metni bu araştırmada doğrulanamadı. Satıcı sözleşmesi md. 4.10 (platforma teknik zarar vermeme, zararlı yazılım) ve md. 4.13 (bilgi güvenliği riski tespitinde ön ihtarsız askıya alma/fesih) panel otomasyonu için yeterli caydırıcı risk. NetKâr yalnızca resmi API kullanmalı. | DSM Grup (2022) | Orta |
| Hesap kapatılma riski | md. 4.13: mevzuata aykırılık, sözleşmeye uymama, "hukuki, teknik ve özellikle bilgi güvenliği anlamında risk" tespitinde ilanlar durdurulabilir, üyelik askıya alınabilir, sözleşme tazminatsız feshedilebilir. md. 4.15: ihlal halinde ödemelerin askıya alınması. Risk satıcıya ait ama NetKâr kaynaklı bir olay müşteri kaybı ve tazmin talebi doğurur. | DSM Grup (2022) | Yüksek |
| Tek taraflı değişiklik | md. 4.11 (hizmet ve içerikleri bildirimsiz değiştirme), md. 5.1 (sözleşmeyi platformda ilan ederek değiştirme). API tarafında 2025 ile 2026 arasında base URL değişimi, sipariş limitleri (8 Haziran 2026), ürün limitleri (14 Eylül 2026), Order V2 zorunluluğu (15 Ekim 2026), 10.000 kayıt sınırı ve "ilerleyen dönemlerde bu limit daha da düşürülebilir" notu. Changelog takibi ve kontrat testleri zorunlu. | DSM Grup (2022), Trendyol (2026g) | Yüksek |
| Sözleşme sürümü | Okunan PDF dosya adı `trendyol_sozlesme_2020_v5.pdf`, sayfa altlığı **2022_V37**. Panelde onaylanan güncel sürüm farklı olabilir. | DSM Grup (2022) | Yüksek (sürüm farkı Doğrulanmadı) |
| Rekabet hukuku / platform politikası | Rekabet Kurulu 26.07.2023'te DSM Grup'a (Trendyol) 4054 s. Kanun md. 6 ihlali (kendi perakende faaliyetini kayırma, üçüncü taraf satıcı verisini kullanma, algoritma müdahalesi) nedeniyle **61.342.847,73 TL** ceza verdi ve pazaryeri verisini kendi markalı ürünler için kullanmamasını istedi. 19.10.2023'te otomatik fiyatlandırma mekanizması için yeni soruşturma açıldı, 03.10.2024'te taahhütlerle kapatıldı. 2025 ile 2026'ya ait yeni karar bu araştırmada bulunamadı. NetKâr için anlamı: (i) platform satıcı verisi konusunda regülatör baskısı altında, bu da API erişiminin keyfi kapatılmasını zorlaştırır; (ii) Trendyol kendi kârlılık/analitik aracını panele ekleyerek rakip olabilir. | Rekabet Kurumu (2024), CNN Türk (2023), CNBC-e (2024) | Orta |
| 6563 s. Kanun / 7416 s. değişiklik | 2022 değişikliği aracı hizmet sağlayıcıların elde ettiği veriyi yalnızca aracılık hizmeti için kullanmasını öngören hükümler içeriyor; madde numarası ve veri taşınabilirliği hükmü bu araştırmada doğrulanamadı. Hukuk dokümanında (03_hukuk_ve_uyum.md) ayrıca ele alınmalı. | Erdem & Erdem (2022) | Düşük |

### 2.8 Yol haritası notu: diğer pazaryerleri

- **Hepsiburada:** Resmi geliştirici portalı (developers.hepsiburada.com) var ve satıcıya açık. Portalde "Entegratöre Servis Anahtarı Ekleme/Görüntüleme" sayfası bulunması, entegratör bazlı anahtar modelinin resmi olarak desteklendiğini gösteriyor; satıcı panelindeki Entegrasyon sayfasından gizli anahtar üretiliyor. Portal arama özetlerinde "Muhasebe Entegrasyonu" altında "Kayıt Bazlı Muhasebe Servisi" ve "Performans Servisi" ile gelen kutusu faturaları (`GetInboxInvoicesData`, `GetInboxInvoicePdf`) görünüyor; hakediş/komisyon satır detayının kapsamı doğrulanamadı. İkincil kaynaklar Basic Auth ve `{MerchantId} - {AppName}` biçiminde User-Agent zorunluluğundan söz ediyor. Portal otomatik isteklere 403 döndüğü için doğrudan okunamadı. (Hepsiburada, t.y.; Zunapro, t.y.) Güven: Orta.
- **n11:** Resmi portal developer.n11.com doğrudan okundu. REST sipariş servisi `GET https://api.n11.com/rest/delivery/v1/shipmentPackages`, header'da `appKey` ve `appSecret`, **1000 istek/dk**, tarih penceresi **15 gün**, **Kasım 2024 öncesi sipariş verisi yok**; satırda `sellerInvoiceAmount` ve `(price * quantity) - (sellerDiscount + sellerCouponDiscount)` formülü veriliyor. Menüde ürün, sipariş, iade/iptal, ürün soru-cevap, n11faturam, n11depom ve mikro ihracat servisleri var; **hakediş/cari hesap/komisyon tutarı servisi menüde görünmüyor** (Doğrulanmadı). Kâr hesabı için n11'de finans verisi muhtemelen eksik kalır. (n11, 2021/2026) Güven: Orta ile Yüksek.
- **Amazon TR:** Amazon Selling Partner API Türkiye pazar yerini destekliyor (marketplaceId `A33AVAJ2PDY3EV`, Avrupa bölgesi). Üçüncü taraf SaaS'ın **Solution Provider Portal'da public developer olarak kayıt olup inceleme geçmesi** gerekiyor (Acceptable Use Policy, Data Protection Policy); kişisel veri (PII) için "restricted role" başvurusu ve veri güvenliği değerlendirmesi zorunlu. Finances API küresel olarak mevcut; TR'de işlem olaylarının kapsamı doğrulanamadı. Trendyol'dan farklı olarak resmi bir uygulama onay süreci var; daha uzun ama sözleşmesel olarak daha net. (Amazon, t.y.) Güven: Orta.
- **Pazarama:** Satıcı panelinde Hesap Bilgileri > Entegrasyon Bilgileri altında API Key/Secret (bazı kaynaklarda Client ID/Secret) veriliyor ve entegratörler (BirFatura, Entegra, Paraşüt) bağlanıyor; ikincil kaynağa göre base URL `isortagimapi.pazarama.com`, dokümanlar `/docs` altında. Kimlik doğrulama (token var mı yok mu) kaynaklar arasında çelişkili; finans/hakediş servisi doğrulanamadı. (BirFatura, t.y.; Zunapro, t.y.) Güven: Düşük.

---

## 3. Kâr Hesabı Veri Eşleme Tablosu

| Maliyet / gelir kalemi | Kaynak endpoint | Alan adı | Ürün/sipariş bazına inebilir mi | Not |
|---|---|---|---|---|
| Brüt satış fiyatı | `v2/orders`, `orders/stream`, webhook | `lines[].lineGrossAmount`, `quantity` | Ürün (satır/kalem) | KDV dahil. Güven: Yüksek |
| Satıcı karşılamalı indirim | Aynı | `lines[].discountDetails[].lineItemSellerDiscount`, `lineSellerDiscount` | Ürün (kalem) | Settlements `Discount`/`Coupon` ile mutabakat. Güven: Yüksek |
| Trendyol karşılamalı indirim | Aynı | `lineItemTyDiscount`, `packageTyDiscount` | Ürün (kalem) | Satıcı gelirini düşürmez; `packageTyDiscount` yalnızca `commercial=true`'da dolu olabilir (çelişki). Güven: Doğrulanmadı |
| Net satış (faturalanacak) | Aynı | `lineItemPrice`, `lineUnitPrice`, `packageTotalPrice` | Ürün | Güven: Yüksek |
| KDV | Aynı | `lines[].vatRate` | Ürün | Kâr hesabı KDV hariç yapılmalı. Güven: Yüksek |
| Komisyon oranı (öngörü) | Sipariş satırı; ürün filtreleme | `lines[].commission`; `variants[].commission` | Ürün | Teslim öncesi tahmin için. KDV dahil olduğu sözleşmeden çıkarım. Güven: Yüksek (alan), KDV Orta |
| Komisyon tutarı (kesin) | `finance/che/.../settlements` (`Sale`, `Return`, `Commission*` düzeltmeleri) | `commissionRate`, `commissionAmount` | Ürün + sipariş (`barcode`, `orderNumber`, `shipmentPackageId`) | Teslimden sonra oluşur. Adet granülerliği Doğrulanmadı. Güven: Yüksek |
| Satıcı hakedişi | `settlements` | `sellerRevenue`, `paymentPeriod`, `paymentOrderId`, `paymentDate` | Ürün + sipariş | Nakit akışı ve vade. Güven: Yüksek |
| Satıcı kuponu / indirim muhasebe kaydı | `settlements` (`Discount`, `DiscountCancel`, `Coupon`, `CouponCancel`) | `debt`, `credit`, `barcode`, `orderNumber` | Ürün + sipariş | Güven: Yüksek |
| Teslimat ücreti | `settlements` (`DeliveryFee`, `DeliveryFeeCancel`) | `credit`/`debt` | Sipariş (muhtemelen) | Kapsamı (kim öder) dokümanda tek cümle; Doğrulanmadı |
| İade (gelir tersine çevirme) | `settlements` (`Return`, `ManualRefund`, `ManualRefundCancel`) | `debt`, `commissionAmount`, `sellerRevenue` | Ürün + sipariş | Komisyon iadesi dahil. Güven: Yüksek |
| İade nedeni ve durumu | `order/.../claims` | `claimItems[].customerClaimItemReason`, `trendyolClaimItemReason`, `claimItemStatus`, `autoAccepted` | Ürün (satır) | Güven: Yüksek |
| Gönderi kargo bedeli | `otherfinancials` (`DeductionInvoices`, "Kargo Faturası") -> `cargo-invoice/{seri}/items` | `shipmentPackageType="Gönderi Kargo Bedeli"`, `orderNumber`, `amount`, `desi` | Sipariş (ürüne dağıtım gerekir) | Fatura gelene kadar `cargoDeci` ile tahmin. Güven: Yüksek |
| İade kargo bedeli | Aynı | `shipmentPackageType="İade Kargo Bedeli"`, `orderNumber`, `amount`, `desi` | Sipariş (ürüne dağıtım; iade satırına bağlanabilir) | Güven: Yüksek |
| Platform hizmet bedeli | `otherfinancials?transactionType=DeductionInvoices&transactionSubType=PlatformServiceFee` | `debt`, `transactionDate`, `id` | Hayır (fatura düzeyi); dağıtım gerekir | Sipariş başına sabit bedel mi olduğu ve satırda `orderNumber` taşıyıp taşımadığı Doğrulanmadı |
| Reklam (ürün/mağaza/influencer) | API yok; `otherfinancials` içinde bakiye alım faturası (tipi Doğrulanmadı) + panel Excel ("Oluşturulan Reklamlar") | Excel kolonları (Doğrulanmadı) | Excel ile ürün bazında; API ile hayır | Ekstre = yükleme anı tutarı, Excel = harcama. Güven: Orta |
| Ceza / operasyonel kesinti | `otherfinancials` (`DeductionInvoices` veya `FinancialItem` olası) | `debt`, `description` | Doğrulanmadı | Pilot hesapla test |
| Erken ödeme | `otherfinancials` (`CashAdvance`) | `credit`/`debt` | Hayır (dönem düzeyi) | Finansman maliyeti satırı Doğrulanmadı |
| E-ticaret stopajı (%1) | `otherfinancials` (`Stoppage`) | `debt` | Dönem/ödeme düzeyi | Gider değil, mahsup edilebilir vergi alacağı olarak gösterilmeli (muhasebe yorumu). Güven: Yüksek (alan) |
| Kurumsal faturada TY indirim/kupon | `settlements` (`TyDiscount`, `TyCoupon` ve iptalleri) | `debt`, `credit` | Ürün + sipariş | Ay sonu faturayla satıcıya ödenir. Güven: Yüksek |
| Gramaj farkı provizyonu | `settlements` (`ProvisionPositive/Negative`) | | Ürün + sipariş | Altın vb. kategoriler. Güven: Yüksek |
| Komisyon mutabakat / iade faturaları | `otherfinancials` (`CommissionAgreementInvoice`, `ReturnInvoice`) | | Dönem düzeyi | Güven: Yüksek |
| Hakediş ödemesi (nakit) | `payment-order`; `otherfinancials` (`PaymentOrder`) | `amount`, `payoutDate` | Dönem | Mutabakat için. Güven: Yüksek |
| Kargo tazmini (gelir) | `tex/compensation/.../tickets` | `orderNumber`, `compensateReason`, `currentState`, `totalItemsAmount` | Sipariş | Yalnızca TEX. Güven: Yüksek |
| Ürün alış maliyeti (COGS), ambalaj, işçilik | Trendyol'da yok | | Kullanıcı girişi / ERP / Excel | NetKâr'ın kendi veri girişi. `laborCost` yalnızca stopaj için bildirilen işçilik bedeli |
| Kategori, barkod, buybox | `products/approved`, `products/buybox-information` | `category`, `barcode`, `buyboxOrder`, `buyboxPrice` | Ürün | Güven: Yüksek |

---

## 4. Açık Sorular / Trendyol'a Sorulması Gerekenler

1. Satıcı adına salt-okuma analitik hizmeti veren, `"{sellerId} - NetKar"` User-Agent'ı ile çağrı yapan bir SaaS için ayrı bir entegratör kaydı, onay veya sözleşme gerekiyor mu? "Entegrasyon Referans Kodu" ile destek alabilmek için entegratörün kayıtlı olması şart mı?
2. Entegrasyon Bilgileri ekranında entegratör bazlı ayrı API anahtarı ve **rol** seçimi var mı? Salt-okuma (sipariş, iade, finans, soru okuma) rolü tanımlanabiliyor mu? Rol listesi nedir?
3. Satıcı anahtarı yenilediğinde veya entegratör anahtarını sildiğinde eski anahtar anında mı geçersizleşiyor? Diğer entegratör anahtarları etkileniyor mu?
4. Rate limitler `sellerId` bazında mı, API anahtarı bazında mı, kaynak IP bazında mı? Çok satıcılı bir SaaS'ın tek çıkış IP'si kullanması sorun yaratır mı? Çok sayıda satıcı adına istek atan IP'lerin "engellenmesi" kriteri nedir?
5. `orders/stream` servisinin kendi rate limiti nedir? Neden `getShipmentPackages` sayfasında "1000 istek/dk", servis limitleri sayfasında 30 ile 100 istek/dk yazıyor; hangisi güncel?
6. `settlements` ve `otherfinancials` için geriye dönük maksimum kaç ay veri çekilebilir?
7. `settlements` `Sale` satırı bir sipariş satırının (adet x fiyat) toplamı mı, yoksa her adet için ayrı satır mı? Aynı barkoddan 2 adet olan siparişte kaç satır döner?
8. Reklam bakiyesi alım faturası, reklam harcama mahsubu, influencer (TMS) bedelleri, operasyonel cezalar ve erken ödeme hizmet bedeli `otherfinancials` içinde hangi `transactionType` ve `description` metinleriyle gelir? Bu satırlar `orderNumber`/`barcode` taşır mı?
9. Ürün/mağaza reklamlarının ürün bazında harcama verisi için API veya planlanan bir servis var mı? Panel Excel raporunun kolon yapısı sabit mi?
10. Platform hizmet bedeli sipariş başına mı hesaplanıyor; sipariş kırılımına erişim var mı?
11. `packageTyDiscount` ve `lineItemTyDiscount` bireysel (commercial=false) siparişlerde dolu gelir mi?
12. Sipariş yanıtındaki `shipmentAddress.phone` ve `invoiceAddress.phone` alanları gerçek müşteri telefonu mu, maskeli mi, boş mu?
13. Satıcı sözleşmesinin güncel sürümünde (2022_V37 sonrası) entegratör/üçüncü taraf yazılım, veri saklama ve kişisel veri maddelerinde değişiklik var mı? Ek Hizmetler Sözleşmesi (2026) ihlal bildirim süresini 24 saate indirdi mi?
14. Gizli Bilgi maddesi (md. 6.1) karşısında, satıcıların anonimleştirilmiş/toplulaştırılmış verisinin kategori ortalaması (benchmark) için kullanılması kabul edilebilir mi?
15. Stage ortamı için "Statik IP'ler için yetkilendirme sağlanamamaktadır" cümlesinin anlamı nedir? Bulut (dinamik/NAT) IP'lerle stage erişimi nasıl sağlanır?
16. Webhook kotasının (15) entegratörler arasında paylaşılması: satıcı başka entegratör kullanıyorsa NetKâr'ın webhook açması önerilir mi?

---

## 5. Kaynaklar (APA 7)

Resmi Trendyol dokümanları (developers.trendyol.com; sayfa güncelleme tarihleri sayfaların `updatedAt` damgasından):

- Trendyol. (2026a, 27 Nisan). *2. Authorization*. Trendyol Integration Documentation. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/2-authorization
- Trendyol. (2026b, 2 Kasım). *Sipariş paketlerini çekme (getShipmentPackages)*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/sipariş-paketlerini-çekme-getshipmentpackages
- Trendyol. (2026c, 13 Temmuz). *3. Canlı-test ortam bilgileri*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/3-canlı-test-ortam-bilgileri
- Trendyol. (2026d, 25 Ağustos). *1. Servis limitleri*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/1-servis-limitleri
- Trendyol. (2026e). *Integration documentation: Proje dizini (llms.txt)*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/llms.txt
- Trendyol. (2026f, 9 Mart). *5. Nasıl bildirim oluşturabilirim*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/6-nasıl-bildirim-oluşturabilirim
- Trendyol. (2026g). *Changelog*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/changelog/changelog
- Trendyol. (2026h, 2 Kasım). *Sipariş paketlerini akış ile çekme (getShipmentPackagesStream)*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/sipariş-paketlerini-akış-ile-çekme
- Trendyol. (2026i, 14 Ekim). *İadesi oluşturulan siparişleri çekme (getClaims)*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/iadesi-oluşturulan-siparişleri-çekme-getclaims
- Trendyol. (2026j, 2 Eylül). *Cari hesap ekstresi entegrasyonu*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/cari-hesap-ekstresi-entegrasyonu
- Trendyol. (2026k, 29 Temmuz). *Kargo faturası detayları*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/kargo-faturası-detayları
- Trendyol. (2026l, 14 Ağustos). *Müşteri sorularını çekme*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/müşteri-sorularını-çekme
- Trendyol. (2026m, 11 Eylül). *Ürün filtreleme: Onaylı ürün v2*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/ürün-filtreleme-onaylı-ürün-v2
- Trendyol. (2026n, 20 Temmuz). *Sipariş paketlerini çekme servisindeki indirim gösterimleri*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/sipariş-paketlerini-çekme-servisindeki-indirim-gösterimleri
- Trendyol. (2026o, 22 Ocak). *Tazmin entegrasyonu*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/tazmin-entegrasyonu
- Trendyol. (2026p, 20 Temmuz). *Ürün buybox kontrol servisi*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/ürün-buybox-kontrol-servisi
- Trendyol. (2026q, 31 Mart). *Müşteri sorularını cevaplama*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/müşteri-sorularını-cevaplama
- Trendyol. (2026r, 2 Kasım). *Webhook model*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/webhook-model
- Trendyol. (2026s, 22 Ocak). *Webhook yaratma*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/webhook-yaratma
- Trendyol. (2026t, 9 Nisan). *4. Sıkça sorulan sorular*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/docs/5-sıkça-sorulan-sorular
- Trendyol. (2026u, 18 Şubat). *Kargo faturası detayları servisi (getCargoInvoiceItems) [OpenAPI referansı]*. Erişim tarihi 5 Kasım 2026, https://developers.trendyol.com/reference/getcargoinvoiceitems

Sözleşme ve resmi/yarı resmi kaynaklar:

- DSM Grup Danışmanlık İletişim ve Satış Ticaret A.Ş. (2022). *Satıcı ve iş ortaklığı sözleşmesi ve ekleri (EK-5 Komisyon ve vade tablosu, EK-6 Kişisel verilerin korunmasına yönelik protokol)* (Sürüm 2022_V37) [PDF]. Erişim tarihi 5 Kasım 2026, https://tymp.mncdn.com/prod/documents/engagement/yasal_surecler/trendyol_sozlesme_2020_v5.pdf
- Trendyol Akademi. (t.y.-a). *Reklam bakiyesi satın alma*. Satıcı Bilgi Merkezi. Erişim tarihi 5 Kasım 2026, https://akademi.trendyol.com/satici-bilgi-merkezi/detay/72 (içerik arama özeti üzerinden)
- Trendyol Akademi. (t.y.-b). *Reklam raporları*. Satıcı Bilgi Merkezi. Erişim tarihi 5 Kasım 2026, https://akademi.trendyol.com/satici-bilgi-merkezi/detay/79 (içerik arama özeti üzerinden)
- Trendyol Akademi. (t.y.-c). *Trendyol içi ürün reklamı*. Satıcı Bilgi Merkezi. Erişim tarihi 5 Kasım 2026, https://akademi.trendyol.com/satici-bilgi-merkezi/detay/285 (içerik arama özeti üzerinden)
- Rekabet Kurumu. (2024). *Tarihte bugün: Algoritmaya müdahaleye Rekabet Kurumu müdahale etti*. Erişim tarihi 5 Kasım 2026, https://haber.rekabet.gov.tr/haber/tarihte-bugun-algoritmaya-mudahaleye-rekabet-kurumu-mudahale-etti
- CNN Türk. (2023, 27 Temmuz). *Rekabet Kurulu'ndan Trendyol'a 61.3 milyon TL ceza*. Erişim tarihi 5 Kasım 2026, https://www.cnnturk.com/ekonomi/rekabet-kurulundan-trendyola-61-3-milyon-tl-ceza-2028839
- CNBC-e. (2024). *Rekabet Kurulu, Trendyol soruşturmasını sonlandırdı: Taahhütler yeterli görüldü*. Erişim tarihi 5 Kasım 2026, https://www.cnbce.com/haberler/rekabet-kurulu-trendyol-sorusturmasini-sonlandirdi-taahhutler-yeterli-goruldu-h7051
- Erdem & Erdem. (2022). *Elektronik Ticaretin Düzenlenmesi Hakkında Kanun'da değişiklik yapılmasına dair kanun Resmî Gazete'de yayımlandı*. Erişim tarihi 5 Kasım 2026, https://www.erdem-erdem.av.tr/bilgi-bankasi/elektronik-ticaretin-duzenlenmesi-hakkinda-kanunda-degisiklik-yapilmasina-dair-kanun-resmi-gazetede-yayimlandi

Diğer pazaryerleri:

- n11. (2021, güncelleme 2026). *Sipariş listeleme servisi*. n11 Developer. Erişim tarihi 5 Kasım 2026, https://developer.n11.com/documentation/elements/siparis-listeleme-servisi/
- n11. (2026). *n11 Developer: API dokümantasyonu ana sayfa*. Erişim tarihi 5 Kasım 2026, https://developer.n11.com/
- Hepsiburada. (t.y.). *Entegratöre servis anahtarı ekleme/görüntüleme*. Hepsiburada Developers. Erişim tarihi 5 Kasım 2026, https://developers.hepsiburada.com/hepsiburada/docs/entegratöre-servis-anahtarı-eklemegörüntüleme (içerik arama özeti üzerinden)
- Hepsiburada. (t.y.). *GetInboxInvoicesData*. Hepsiburada Developers. Erişim tarihi 5 Kasım 2026, https://developers.hepsiburada.com/hepsiburada/reference/getinboxinvoicesdata (içerik arama özeti üzerinden)
- Amazon. (t.y.-a). *Marketplace IDs*. Selling Partner API Documentation. Erişim tarihi 5 Kasım 2026, https://developer-docs.amazon.com/sp-api/docs/marketplace-ids (içerik arama özeti üzerinden)
- Amazon. (t.y.-b). *Register as a public SP-API developer*. Selling Partner API Documentation. Erişim tarihi 5 Kasım 2026, https://developer-docs.amazon.com/sp-api/lang-US/docs/register-as-a-public-developer (içerik arama özeti üzerinden)

İkincil kaynaklar (entegratör blogları, açık kaynak):

- Paraşüt. (t.y.). *Trendyol API bilgilerini Paraşüt e-Ticaret'e bağlamak*. Erişim tarihi 5 Kasım 2026, https://www.parasut.com/kullanim-kilavuzu/e-ticaret-trendyol-entegrasyonu (içerik arama özeti üzerinden)
- Zunapro. (t.y.). *Trendyol integration guide*. Erişim tarihi 5 Kasım 2026, https://www.zunapro.com/turkey/en/blog/trendyol-integration-guide (ticari kaynak; resmi dokümanla çelişen iddialar içeriyor)
- Zunapro. (t.y.). *Pazarama*. Erişim tarihi 5 Kasım 2026, https://www.zunapro.com/turkey/tr/pazaryeri/pazarama
- BirFatura. (t.y.). *Pazarama entegrasyonu*. Erişim tarihi 5 Kasım 2026, https://birfatura.com/pazarama-entegrasyonu/
- bberka. (2026). *TrendyolClient.Sharp: Trendyol API client for .NET using Refit* [Kaynak kod]. GitHub. Erişim tarihi 5 Kasım 2026, https://github.com/bberka/TrendyolClient.Sharp
- actuallyzefe. (2025). *n8n-trendyol: n8n community node for Trendyol* [Kaynak kod]. GitHub. Erişim tarihi 5 Kasım 2026, https://github.com/actuallyzefe/n8n-trendyol
- altuntasmuhammet. (2023). *trendyol-api-python-sdk: Unofficial Trendyol API Python SDK* [Kaynak kod]. GitHub. Erişim tarihi 5 Kasım 2026, https://github.com/altuntasmuhammet/trendyol-api-python-sdk (eski `api.trendyol.com/sapigw` URL'sini kullanıyor; güncel değil)
