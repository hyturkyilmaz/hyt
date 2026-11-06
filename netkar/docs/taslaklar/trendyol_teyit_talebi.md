# Trendyol'a yazılı teyit talebi (TASLAK, gönderilmedi)

Durum: Taslak. Gönderim Hasan Yasin Türkyılmaz tarafından yapılacak.
Kaynak: docs/research/01_trendyol_api.md (5 Kasım 2026), bölüm 4 "Açık Sorular".
Not: Metindeki `[ÜRÜN ADI]`, `[AD SOYAD]` vb. yer tutucular gönderimden önce doldurulmalı. Soru numaraları (S1 ile S16) araştırma dosyasındaki sıralamayı izler.

---

## 1. Nereye gönderilir

Araştırma dosyasında geçen kanallar şunlar:

- **Satıcı panelinden bildirim/talep oluşturma.** Trendyol entegrasyon dokümanında "Nasıl bildirim oluşturabilirim" sayfası var (Trendyol, 2026f); entegrasyon sorunları ve stage IP tanımı için panel üzerinden bildirim açılıyor. Araştırmada bu kanal "Taleplerim/entegrasyon destek kanalı" olarak geçiyor. Panelde sayfanın tam menü adı doğrulanmadı.
- **Entegrasyon Referans Kodu.** Satıcı panelinde bulunan bu kod, entegratörün Trendyol'dan destek alırken kullanması gereken kod olarak dokümanda geçiyor. Talebin açılacağı satıcı hesabındaki kodun talebe yazılması gerekir.
- **Çağrı merkezi (0850 258 58 00).** Kaynakta yalnızca stage ortamı için IP tanımlatma bağlamında geçiyor. Bu soruların kanalı olarak önerildiği yazmıyor; sadece "talebin hangi başlık altında açılacağını öğrenmek" için aranabilir.

Kaynakta bulunmayanlar: entegrasyon/partner ekibine ait bir e-posta adresi, ayrı bir "entegratör başvuru" formu veya iş ortaklığı birimi. Araştırmada resmi bir entegratör kayıt süreci de bulunamadı.

**Sonuç:** Doğrulanmış bir e-posta kanalı yok. Kanal doğrulanmadı; satıcı panelinden destek talebi önerilir. Talep, NetKâr'ı kullanacak bir pilot satıcının (veya Hasan'ın kendi) master user hesabından açılmalı, çünkü Entegrasyon Bilgileri ekranı ve referans kodu yalnızca admin rolünde görünüyor. Yanıt yazılı kalacağı için talep numarası ve tarihi saklanmalı. Panel talebi yanıtsız veya genel kalırsa, aynı metin Trendyol'un resmi iletişim adreslerinden biri doğrulandıktan sonra e-postayla da gönderilebilir (adres bu taslakta uydurulmadı).

---

## 2. Talep metni

Konu: Üçüncü taraf salt-okuma analitik yazılım için API kullanımı hakkında yazılı teyit talebi (Satıcı No: [SATICI ID], Entegrasyon Referans Kodu: [KOD])

Merhaba,

[ŞİRKET / AD SOYAD] olarak [ÜRÜN ADI] adıyla bir yazılım geliştiriyoruz. Ürün, Trendyol satıcılarının kendi API anahtarlarıyla bağlanmasıyla çalışıyor ve yalnızca okuma yapıyor: sipariş, iade, cari hesap ekstresi, kargo faturası ve ürün verisini çekerek satıcıya ürün bazında net kârını gösteriyor, ileride müşteri sorularını da okumayı planlıyoruz. Ürün sipariş, ürün veya fiyat tarafında herhangi bir yazma işlemi yapmıyor. Son müşteriye ait kişisel veriler (ad, adres, telefon, T.C. kimlik no) sistemimizde saklanmıyor, alındığı anda atılıyor; her satıcıyla Satıcı Sözleşmesi EK-6 ile uyumlu bir veri işleme sözleşmesi imzalıyoruz. İstekleri `User-Agent: "{sellerId} - [ÜRÜN ADI]"` biçiminde gönderiyoruz. Canlıya almadan önce aşağıdaki noktalarda yazılı yanıtınıza ihtiyacımız var:

1. Satıcı adına yalnızca okuma yapan bu tür bir yazılım için ayrı bir entegratör kaydı, onayı veya sözleşmesi gerekiyor mu? Entegrasyon Referans Kodu ile destek alabilmek için entegratörün kayıtlı olması şart mı?
2. Satıcı panelindeki Entegrasyon Bilgileri ekranında entegratör bazında ayrı API anahtarı oluşturulup rol seçilebiliyor mu? Yalnızca okuma yetkisi (sipariş, iade, finans, soru okuma) verilebiliyorsa rol listesi nedir?
3. Rate limitler sellerId, API anahtarı veya kaynak IP bazında hangisine göre sayılıyor? Çok sayıda satıcı adına aynı çıkış IP'sinden istek atılması bir sorun yaratır mı, IP engelleme hangi kritere göre uygulanıyor?
4. Sipariş yanıtındaki `shipmentAddress.phone` ve `invoiceAddress.phone` alanları gerçek müşteri telefonu mu, maskeli mi, yoksa boş mu geliyor?
5. Satıcı Sözleşmesi'nin güncel sürümünde (2022_V37 sonrası) entegratör/üçüncü taraf yazılım, veri saklama ve kişisel veri maddelerinde (EK-6 dahil) bir değişiklik var mı? İhlal bildirim süresi şu an 48 saat mi, 24 saat mi?

Bunların dışında kalan, daha az acil teknik sorularımızı ayrı bir ek listede iletiyoruz (Ek-1). Hepsine aynı yanıtta dönüş yapmanız gerekmiyor; önce yukarıdaki beş soruya yanıt alabilirsek sürece hemen devam edebiliriz.

Yanıtınız için şimdiden teşekkür ederiz. Gerekirse sistemin çalışma biçimini ve veri akışını görüşmede anlatmaya hazırız.

Saygılarımızla,

[AD SOYAD]
[ÜNVAN], [ŞİRKET ADI]
[E-POSTA] | [TELEFON]
[WEB SİTESİ, varsa]

### Ek-1: Diğer sorular (aynı talebe ek olarak)

6. orders/stream servisinin kendi rate limiti nedir? Servis limitleri sayfasında 30 ile 100 istek/dk, getShipmentPackages sayfasında 1000 istek/dk yazıyor; hangisi güncel?
7. Cari hesap ekstresi (settlements ve otherfinancials) için geriye dönük en fazla kaç ay veri çekilebiliyor?
8. settlements içindeki `Sale` satırı sipariş satırının toplamını mı veriyor, yoksa her adet için ayrı satır mı? Aynı barkoddan iki adet olan siparişte kaç satır dönüyor?
9. Reklam bakiyesi alım faturası, reklam harcama mahsubu, influencer bedelleri, operasyonel cezalar ve erken ödeme hizmet bedeli otherfinancials içinde hangi `transactionType` ve açıklama metinleriyle geliyor? Bu satırlar `orderNumber` veya `barcode` taşıyor mu?
10. Ürün veya mağaza reklamlarının ürün bazında harcama verisi için bir API veya planlanan bir servis var mı? Panel Excel raporunun kolon yapısı sabit mi?
11. Platform hizmet bedeli sipariş başına mı hesaplanıyor? Sipariş bazında kırılıma erişim var mı?
12. `packageTyDiscount` ve `lineItemTyDiscount` alanları bireysel (commercial=false) siparişlerde dolu geliyor mu?
13. Satıcı API anahtarını yenilediğinde veya entegratör anahtarını sildiğinde eski anahtar hemen mi geçersiz oluyor? Diğer entegratörlerin anahtarları etkileniyor mu?
14. Satıcıların anonimleştirilmiş ve toplulaştırılmış verisinin kategori ortalaması gibi karşılaştırmalar için kullanılması, Satıcı Sözleşmesi md. 6.1 (Gizli Bilgi) kapsamında kabul edilebilir mi?
15. Stage ortamı dokümanındaki "Statik IP'ler için yetkilendirme sağlanamamaktadır" cümlesi ne anlama geliyor? Bulut (dinamik veya NAT) IP'lerle stage erişimi nasıl sağlanır?
16. Webhook kotası (satıcı başına 15) entegratörler arasında paylaşıldığı için, satıcı başka bir entegratör kullanıyorsa bizim webhook açmamız uygun olur mu, yoksa yalnızca polling mi önerilir?

---

## 3. Ek: Tüm soruların listesi ve önemi

Numaralar araştırma dosyası bölüm 4'e göre. "Talepte" sütunu sorunun ana metinde mi Ek-1'de mi gittiğini gösterir.

| # | Soru (kısa) | Neden önemli | Talepte |
|---|---|---|---|
| S1 | Entegratör kaydı/onayı/sözleşmesi gerekli mi, referans kodu için kayıt şart mı | Üçüncü taraf kullanımın izinli olduğunun yazılı teyidi; yoksa tüm model hesap riski taşır | Ana, soru 1 |
| S2 | Entegratör bazlı anahtar ve salt-okuma rolü | Satıcıya "yalnızca okuyoruz" demenin teknik karşılığı ve güven argümanı | Ana, soru 2 |
| S3 | Anahtar yenilenince/silinince eski anahtarın durumu | Bağlantı kopma davranışını ve diğer entegratörlere etkiyi belirler | Ek-1, soru 13 |
| S4 | Rate limit kapsamı: sellerId, anahtar mı, IP mi | Çok satıcılı SaaS'ın çıkış IP stratejisini ve ölçek sınırını belirler | Ana, soru 3 |
| S5 | orders/stream limiti, 1000/dk ile 30-100/dk çelişkisi | Senkron sıklığı ve istek bütçesi hesabı için doğru limit gerekli | Ek-1, soru 6 |
| S6 | Finans servislerinde geriye dönük azami süre | Onboarding'de kaç aylık geçmiş kârın hesaplanabileceğini belirler | Ek-1, soru 7 |
| S7 | `Sale` satırı adet bazında mı, satır toplamı mı | Komisyonun ürün/adet bazına doğru bölünmesi için gerekli | Ek-1, soru 8 |
| S8 | Reklam, ceza, influencer, erken ödeme satırlarının tip ve açıklamaları, sipariş taşıyıp taşımadığı | Fatura düzeyi kesintilerin otomatik sınıflandırılması ve dağıtımı buna bağlı | Ek-1, soru 9 |
| S9 | Ürün bazında reklam harcaması için API veya plan | Reklam, kâr hesabındaki en büyük veri boşluğu; Excel yüklemeye mecbur muyuz | Ek-1, soru 10 |
| S10 | Platform hizmet bedeli sipariş başına mı, kırılım var mı | Sipariş/ürün bazına doğrudan mı yazılır, dağıtım mı gerekir | Ek-1, soru 11 |
| S11 | Trendyol indirimi alanları bireysel siparişte dolu mu | Net satış ve satıcı gelirinin doğru hesabı için dokümandaki çelişkiyi giderir | Ek-1, soru 12 |
| S12 | `phone` alanları gerçek mi, maskeli mi | KVKK tasarımı ve EK-6 md. 4.1 ile uyum; telefon geliyorsa atma önceliği artar | Ana, soru 4 |
| S13 | Sözleşmenin güncel sürümünde entegratör/veri/ihlal bildirim maddeleri | Okunan sürüm 2022_V37; güncel yükümlülükler (24 mi 48 saat mi) DPA'yı etkiler | Ana, soru 5 |
| S14 | Toplulaştırılmış veriyle benchmark md. 6.1 ile uyumlu mu | Kategori ortalaması gibi bir özelliğin yasal olup olmadığını belirler | Ek-1, soru 14 |
| S15 | Stage ortamında "statik IP" cümlesi, bulut IP ile erişim | Geliştirme ve test ortamı kurulumu için pratik engel | Ek-1, soru 15 |
| S16 | Webhook kotasının paylaşımı | Webhook kullanılacak mı, yalnızca polling mi karar verir; satıcının diğer entegrasyonlarını bozmama | Ek-1, soru 16 |

Soru sıralaması hakkında not: Ana metne hukuki ve erişim izni gerektiren, yanıtı "yapabiliriz/yapamayız" kararını değiştiren beş soru alındı (S1, S2, S4, S12, S13). Veri modeli ile ilgili sorular (S7 ile S11) pilot satıcı hesabında canlı veriyle de test edilebildiği için Ek-1'e bırakıldı. S14 hukuki ağırlıkta olsa da bir özelliğe bağlı olduğu ve ilk görüşmede gereksiz tepki çekebileceği için ek listede.

---

## 4. Yanıt gelince yapılacaklar

Her soru için olası yanıt ve NetKâr mimarisine etkisi. "Yanıt gelmezse" durumu için varsayılan karar da yazıldı.

### S1: Entegratör kaydı/onayı

- **Gerekmiyor, serbest:** Mevcut plan geçerli. Yanıtı (talep numarası, tarih) hukuk klasörüne kaydet; `User-Agent` formatını (`{sellerId} - NetKar`, en fazla 30 karakter, Türkçe karakter yok) sabitle.
- **Kayıt/onay gerekiyor:** Başvuru süreci ürün takvimine girer; pilot satıcılarla canlıya çıkış başvuru sonucuna bağlanır. Onaya kadar yalnızca satıcının kendi `SelfIntegration` benzeri kullanımı ve kapalı pilot düşünülebilir; bu da Trendyol'dan ayrıca teyit edilmeli.
- **Sözleşme/komisyon veya ücret isteniyor:** Birim ekonomisi gözden geçirilir; karar Hasan'a gider.
- **Reddediliyor:** Karar "dar kapsamlı GO"ya döner (araştırma karar bölümü): hesaplama satıcının kendi oturumunda, veri saklamadan yapılır, ya da ürün kapsamı Excel/dosya yüklemesine kayar.
- **Yanıt gelmezse:** 10 iş günü sonra aynı talep üzerinden takip yaz; hâlâ yanıt yoksa pilotu "yazılı teyit yok" notuyla, yalnızca bilinçli kabul eden satıcılarla çalıştır ve riski sözleşmede açıkla.

### S2: Entegratör bazlı anahtar ve rol

- **Ayrı anahtar ve salt-okuma rolü var:** Onboarding akışı satıcıya "NetKâr için yeni anahtar oluştur, entegratör adı NetKar, yalnızca şu rolleri işaretle" adımlarını gösterir. Rol listesini onboarding ekranına ve güvenlik sayfasına yaz. Diğer entegratörler etkilenmez, satıcı NetKâr erişimini tek başına iptal edebilir.
- **Ayrı anahtar var, rol seçimi yok:** Anahtar tam yetkili olur. Kod tarafında yazma endpoint'lerine hiç istemci metodu koyma (allowlist yalnızca GET); kod incelemesi ve test ile "yazma yapmıyoruz" garantisi kendi tarafımızda verilir. Satıcıya bunu açıkça anlat.
- **Ayrı anahtar yok, satıcının tek anahtarı paylaşılıyor:** Anahtar yenilemesi diğer entegratörleri kırar. Onboarding'de bu uyarı gösterilir; anahtar yenileme adımı satıcıya "diğer entegrasyonlarınızı etkileyebilir" uyarısıyla sunulur. Risk büyüdüğü için KMS şifreleme, erişim logu ve sızıntı müdahale planı öne alınır.

### S3: Anahtar yenileme davranışı

- **Eski anahtar hemen geçersiz:** 401 alan bağlantıyı "yeniden bağlan" durumuna al, satıcıya bildirim gönder, o satıcı için tüm zamanlanmış işleri durdur (boşa istek ve IP kara listesi riskini önler).
- **Gecikmeli geçersiz:** 401 geldiğinde birkaç deneme ve bekleme ekle, sonra aynı akışa geç.
- **Diğer entegratör anahtarları etkileniyor:** Onboarding'de uyarı metnine ekle (S2'deki üçüncü durumla aynı).

### S4: Rate limit kapsamı

- **sellerId bazında:** En kolay durum. Satıcı başına istek bütçesi ayrı tutulur (kuyruk anahtarı = sellerId); tek çıkış IP'si sorun olmaz, sıralı worker yeterli.
- **API anahtarı bazında:** Yukarıdakiyle fiilen aynı; her anahtar için ayrı token bucket.
- **IP bazında:** Mimari değişir. (a) Çok satıcılı işleri tek sayaç altında sıraya sokan merkezi, küresel bir rate limiter gerekir (satıcılar arası adil dağıtım dahil); (b) çıkış IP havuzu (birkaç sabit NAT/proxy IP'si) ve satıcıların bu IP'lere atanması; (c) senkron sıklığı, satıcı sayısına göre dinamik olarak seyreltilir; (d) Trendyol tarafında IP'ler için ön bildirim veya whitelist isteği açılır. Maliyet tahmini ve fiyatlama gözden geçirilir.
- **IP engelleme kriteri belirtiliyorsa:** Kriteri izleme kuralına çevir (429 oranı, istek yoğunluğu) ve alarm ekle.
- **Yanıt gelmezse:** IP bazlı varsayımıyla tasarla (en güvenli), merkezi limiter ve ayrı çıkış IP'si kullan; pilotta 429 oranını ölç.

### S5: orders/stream limiti

- **Net limit verilirse:** İstek bütçesi hesabını (satıcı sayısı x dakikada istek) güncelle; worker eşzamanlılığını buna göre ayarla.
- **Eski sayfa yanlış, 30 ile 100/dk geçerli:** Backfill süreleri uzar; onboarding "ilk veri hazırlanıyor" ekranı ve kuyruk önceliği (yeni satıcı önce son 30 gün, sonra geriye doğru) kurgulanır.
- **1000/dk geçerli:** Backfill hızlanır; yine de genel kural olan 10 saniyede 50 istek sınırına uy.

### S6: Finans geriye dönük süre

- **Sınır yok veya uzun (12 ay ve üzeri):** Onboarding'de 12 aylık kâr geçmişi sunulabilir; backfill işi 15 günlük pencerelerle kuyruğa alınır (100/dk limitinde dakikalar).
- **Kısa sınır (örn. 3 ay):** Ürün vaadi "bağlandığın günden öncesi için en fazla N ay" olarak yazılır; sipariş verisi ile aynı pencereye indirgenir. Bağlandıktan sonraki veriyi kaybetmemek için finans senkronunu düzenli yap ve ham finans satırlarını (kişisel veri içermeyen alanlarla) kendi veritabanımızda sakla, çünkü sonradan API'den geri alınamayabilir.

### S7: `Sale` satırı granülerliği

- **Adet başına ayrı satır:** Ürün bazlı komisyon `barcode` + `orderNumber` altında toplanır; adet sayısı sipariş satırından doğrulanır.
- **Satır toplamı (tek satır):** Adet bazlı komisyon, satır komisyonunun `quantity`'ye bölünmesiyle hesaplanır; kısmi iadede orantılama kuralı yazılır.
- **Belirsiz kalıyor:** Mutabakat testi ekle: satır bazlı toplam komisyon, `commissionRate` x net satış ile karşılaştırılır; fark eşiği aşarsa satıcıya "doğrulanamadı" etiketi göster.

### S8: Reklam, ceza, influencer, erken ödeme satırları

- **Net `transactionType`/açıklama metinleri verilirse:** Sınıflandırma tablosu (kural tabanlı) bu metinlerle kurulur; "bilinmeyen kesinti" kovası ayrıca tutulur. Sipariş numarası taşıyan kalemler doğrudan siparişe, taşımayanlar dağıtım kuralına gider.
- **Siparişe/barkoda bağlı geliyorsa:** Ceza ve benzeri kalemler gerçek (allocated değil) ürün maliyetine yazılır; "tahmini" etiketi kaldırılır.
- **Bağlı gelmiyorsa:** Dönem düzeyinde dağıtım (satış cirosuna, adede veya desiye göre) uygulanır; kullanıcı arayüzünde bu kalemler "dağıtılmış" olarak etiketlenir ve kural seçilebilir olur.
- **Yanıt gelmezse:** Pilot satıcı hesabında canlı veriyle test et (araştırma koşul 4); metinleri oradan çıkar.

### S9: Ürün bazlı reklam verisi

- **API var veya planlanıyor:** Reklam bağlayıcısı (connector) ürün planına alınır; Excel yükleme geçici çözüm olarak kalır. Tarih takvimini dikkate alıp özellik bayrağı arkasına koy.
- **API yok, Excel kolonları sabit:** v1'de Excel yükleme (şablon doğrulama, kolon eşleme) ana yol olur; parser sürüm kontrolü ve kolon değişimine karşı uyarı eklenir.
- **API yok, Excel yapısı sabit değil:** Kolon eşleme sihirbazı gerekir; Excel verisi olmadan reklam, ürün kârından ayrı bir kalem olarak sipariş cirosuna oranla dağıtılır ve "tahmini" etiketi taşır.
- **Panel kazıma (scraping) asla yapılmaz** (sözleşme md. 4.10 ve 4.13 riski).

### S10: Platform hizmet bedeli

- **Sipariş başına ve kırılım var:** Doğrudan siparişe yazılır, çok ürünlü siparişte kalemlere adet veya tutar oranıyla dağıtılır.
- **Sabit/dönemsel, kırılım yok:** Dönem toplamı, o dönemde teslim edilen sipariş/paket sayısına bölünerek dağıtılır; etiket "dağıtılmış".
- **Yanıt gelmezse:** Pilot veriyle `PlatformServiceFee` satırlarının sayısı, paket sayısıyla karşılaştırılıp sipariş başına sabit olup olmadığı çıkarılır.

### S11: Trendyol indirim alanları

- **Bireysel siparişte dolu:** Net satış hesabında `lineItemTyDiscount` ayrı gösterilir; satıcının geliri değil Trendyol'un karşıladığı tutar olarak yazılır.
- **Yalnızca commercial=true'da dolu:** Bireysel siparişte satıcı gelirini `sellerRevenue` (settlements) üzerinden al, sipariş satırındaki indirim alanlarını gelir hesabında kullanma; kâr formülü finans satırına dayanır.
- **Yanıt gelmezse:** Tek kaynak olarak settlements'ı esas al, sipariş satırını yalnızca teslim öncesi tahmin için kullan.

### S12: Telefon alanları

- **Gerçek telefon dönüyor:** Ingest katmanında `phone` alanı için ayrı bir "asla yazma" kuralı ve bunu doğrulayan test (alan adı bazlı allowlist dışı her şey atılır) zorunlu; ham gövde logu kapatılır. Trendyol'a bunun EK-6 md. 4.1 ile uyumunu da ayrıca sormak gerekir.
- **Maskeli veya boş:** Risk azalır, ancak mimari değişmez: yine allowlist ile atılır; sadece risk notu güncellenir.
- **Yanıt gelmezse:** Gerçek telefon geliyormuş gibi davran; hiçbir koşulda saklanmaz.

### S13: Sözleşme güncel sürümü

- **Değişiklik yok:** Mevcut DPA taslağı (EK-6 md. 3.2 ile 3.10 ve 4.2) aynen kalır.
- **İhlal bildirimi 24 saat:** Olay müdahale planındaki bildirim süresi 24 saate çekilir; DPA'da satıcıya bildirim süremiz buna göre kısalır (satıcının Trendyol'a bildirim süresine yer bırakacak şekilde, örn. 12 saat).
- **Entegratör veya veri saklama maddeleri yeni getirilmiş:** DPA şablonu ve veri saklama politikası (silme süreleri, denetim raporu formatı) yeniden yazılır; hukukçu gözden geçirir. Yeni sürüm hükümleri karar kaydına eklenir.
- **Yanıt gelmezse:** Satıcının panelinde onayladığı güncel sözleşme sürümünü pilot satıcıdan iste ve metni hukukçuyla oku.

### S14: Benchmark için toplulaştırılmış veri

- **Kabul edilebilir:** Kategori ortalaması gibi özellikler geliştirilebilir; yine de en az N satıcı (örn. 10) şartı ve tekil satıcının geri çıkarılamaması kuralı konur.
- **Kabul edilemez:** Özellik kaldırılır; yalnızca satıcının kendi geçmişiyle karşılaştırma (önceki dönem, kendi ürünleri) yapılır. Veri modelinde satıcılar arası sorgu yolu hiç açılmaz.
- **Yanıt gelmezse:** Özelliği v1 kapsamından çıkar; yazılı izin gelene kadar satıcılar arası toplulaştırma yapma.

### S15: Stage ortamı ve IP

- **Bulut IP ile erişim mümkün:** Test ortamı için sabit çıkış IP'si (veya NAT) tanımlanıp whitelist talebi açılır; CI'dan çağrılar bu IP üzerinden gider.
- **Statik IP şart, dinamik desteklenmiyor:** Geliştirme için sabit IP'li küçük bir proxy/VM kurulur, entegrasyon testleri yalnızca oradan çalışır; CI'da stage'e karşı canlı test yerine kayıtlı yanıtlarla (fixture) test yapılır.
- **Stage erişimi zor kalırsa:** Test için ortak test hesabı yerine pilot satıcı hesabıyla salt-okuma canlı testine ağırlık verilir.

### S16: Webhook kotası

- **Paylaşımlı kota, webhook önerilmiyor veya satıcı başka entegratör kullanıyor:** Webhook varsayılan olarak kapalı; yalnızca `orders/stream` ile 15 ile 30 dakikalık polling yapılır. Webhook, satıcı onayıyla ve kota boşsa açılan opsiyonel bir özellik olur.
- **Webhook serbest:** CREATED, CANCELLED, DELIVERED, RETURNED, UNSUPPLIED, UNPACKED statüleri için abone ol; alıcı idempotent olsun, ham gövdeyi loglamasın (payload tam müşteri verisi taşıyor); yine de periyodik stream eşitlemesi sürsün.
- **Yanıt gelmezse:** Webhook'u v1'e koyma; polling yeterli.

### Genel

- Her yanıtı (metin, tarih, talep numarası) ayrı bir kayıt dosyasında sakla ve 01_trendyol_api.md'deki ilgili "Doğrulanmadı" satırlarını güncelle.
- Sözlü (çağrı merkezi) yanıtlar kayıt altına alınmaz sayılır; yazılı teyit iste.
- Yanıtlar çelişkili veya muğlaksa aynı talep üzerinden tek bir açıklayıcı takip sorusu sor; yeni konu açma.
- S1, S2 veya S13 olumsuz çıkarsa karar yeniden değerlendirilir (araştırma dosyasındaki "dar kapsamlı GO" senaryosu).
