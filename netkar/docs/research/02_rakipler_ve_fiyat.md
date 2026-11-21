# NetKâr: Rakipler, Fiyat ve İsim Kontrolü

Erişim tarihi (tüm kaynaklar): 5 Kasım 2026. Çalışma dosyası: `calisma_dosyalari/rakipler.csv` (42 satır).

## 0. Yöntem notu ve güvenilirlik sınırı (önce okuyun)

- Bu araştırma ortamında doğrudan web sayfası açma (WebFetch) engelliydi (alan adları çözümlenemedi). Bu yüzden hiçbir rakip sitesinin kendi fiyat veya özellik sayfasını doğrudan okuyamadım. Tüm bilgiler arama motoru sonuç özetlerinden gelir. Satıcının kendi pazarlama metni, rakip blogları ve toplayıcı siteler bağımsız doğrulanmış sayılmamalıdır.
- Türkiye entegratör fiyatlarının çoğu tek bir rakip kaynaktan (Zunapro blogları, Ekim 2026) geliyor. Bu kaynak taraflıdır. Bu rakamlar "doğrulanmadı (rakip kaynağı)" kabul edilmelidir.
- TÜRKPATENT, alan adı kayıt sorgusu (WHOIS), App Store ve Google Play sayfaları doğrudan sorgulanamadı. İsim ve alan adı sonuçları "arama izi" niteliğindedir, hukuki güvence değildir.
- Hiçbir rakam uydurulmadı. Bulunamayan her hücre "doğrulanmadı" olarak işaretlendi. Kur dönüşümü yapılmadı (Kasım 2026 kuru doğrulanamadı).

## 1. Yönetici özeti

1. **Pazar kalabalık ama kalite belirsiz.** Ürün bazlı net kâr vaat eden en az 6 Türk girişimi var (EZV, Melontik, Biliyo, OZZMOO, Cirometre, Pazarus) ve en az 8 ücretsiz hesaplayıcı veya eklenti (ecomcalctools, IdeaSoft, Ticimax, ikas, tetsi, analyzertr, SellerIQ, Trendyol Profit Calculator). Hiçbirinin fiyatını doğrulayamadım.
2. **Çoğu araç tahmin yapıyor.** Hesaplayıcılar ve eklentiler (TPro360, Vitrin, Pazarus, ecomcalctools) komisyon, KDV, kargo girdilerinden tahmin üretiyor. Ekstre kullanımını kendi sayfalarında açıkça iddia edenler EZV ve Melontik (hakediş ve ödeme mutabakatı). Bunlar da bağımsız doğrulanmadı.
3. **Entegratörler kâr analizini yan özellik olarak sunuyor.** Sentos (hakedişte net kalan), Entegra (hakediş takibi, eksik ödeme kontrolü) en yakın olanlar. Dopigo, BirFatura, Stockmount, Paraşüt için ürün bazlı net kâr raporu bulunamadı.
4. **Entegratör fiyatı yıllık ve yüksek.** Rakip kaynağa göre Sentos Basic 9.500 TL/yıl (aylık eşdeğeri yaklaşık 792 TL), Dopigo Pazaryeri 24.999 TL/yıl (yaklaşık 2.083 TL/ay), Entegra 10.500 ile 125.000 TL/yıl. Aylık ödeme seçeneği bulunamadı.
5. **Mobil boşluk gerçek görünüyor.** Doğrulanabilen mobil ürünler: Trendyol Satıcı Paneli uygulaması (Pusula içeriyor, 2021 haberi), Dopigo iOS (satış, stok, sipariş; yeterli puan yok) ve manuel hesaplayıcı uygulamaları. Pazaryeri ekstresinden beslenen, mobil öncelikli bir net kâr uygulaması bulamadım (bu bir yokluk kanıtı değil, arama sınırlıdır).
6. **Trendyol kendi ekstre verisini API ile açıyor.** Cari Hesap Ekstresi (`settlements`) uç noktası komisyon oranı, komisyon tutarı, satıcı hakedişi, sipariş no, ödeme emri no alanlarını veriyor. Sınırlar: tarih aralığı en fazla 15 gün, kayıtlar teslimattan sonra oluşuyor, işlem tipi zorunlu. Bu, "gerçek ekstre" farklılaşmasının teknik temelidir.
7. **Satıcı tabanı büyük.** Trendyol: 250 binden fazla satıcı/iş ortağı (CEO Erdem İnan, 2025, AA haberleri), 125 binden fazlası yurt dışına satıyor. Hepsiburada: 31 Aralık 2025'te 102,0 bin aktif satıcı (Q4 2025 sonuçları). Segment kırılımı (mikro/KOBİ/büyük) bulunamadı.
8. **İsim çakışması var.** App Store'da "NetKar" adlı, gelir-gider ve otomatik net kâr/zarar vaat eden bir iOS uygulaması listelenmiş (kimlik 6757768044, geliştirici doğrulanmadı). Aynı işlev alanında olduğu için çakışma riski yüksek. Bölüm 7'de 5 alternatif var.
9. **Yurt dışı fiyat çıpaları.** Sellerboard yaklaşık 15 ile 79 USD/ay, Sellerise 19,99 USD'den, TrueProfit 35 USD'den (300 sipariş), BeProfit 49 USD'den. Hepsi sipariş hacmi kademeli. Bu model NetKâr için uygun.
10. **Fiyat bandı önerisi (hipotez, test edilmeli).** Ücretsiz katman + Başlangıç 349 TL/ay + Pro 799 TL/ay + Büyüme 1.799 TL/ay (KDV hariç, sipariş hacmine göre). Gerekçe Bölüm 4'te.

## 2. Türkiye rakipleri

Kısaltmalar: GE = gerçek ekstre kullanımı; İ = iade dahil; R = reklam dahil; M = mobil. "D" = doğrulanmadı. Her satırın kaynak URL'si ve tarihi CSV'dedir.

### 2.1 Doğrudan: net kâr ve kârlılık analizi

| Ürün | Kategori | GE | İ | R | M | Aylık fiyat | Segment | Güçlü / zayıf |
|---|---|---|---|---|---|---|---|---|
| EZV (ezv.com.tr) | analiz | İddia: hakediş ve ödeme mutabakatı | İddia: iade kontrolü | D | D | D | Trendyol ve Hepsiburada satıcıları | Güçlü: hakediş, desi/kargo kontrolü, nakit akış takvimi iddiası. Zayıf: fiyat ve bağımsız doğrulama yok |
| Melontik | analiz | İddia: hakediş kontrolü | D | D | D | D | Trendyol satıcıları | Güçlü: sipariş, ürün, kampanya bazında net kâr, fiyat motoru iddiası. Zayıf: fiyat yok |
| Biliyo | analiz | İddia: API ile sipariş anında net kâr | D | D | D | D | Trendyol, Hepsiburada | Yeni pazaryerleri beta. Tek kaynak kendi sayfası |
| OZZMOO | analiz | D | İddia: iade maliyeti | D | D | D | Pazaryeri satıcıları | Komisyon, kargo, iade maliyeti tek panelde iddiası |
| Pazarus | eklenti / analiz | Tahmin (flaş indirim ekranında net kâr/zarar) | D | D | Hayır (eklenti) | Capterra'da 19,99 USD geçiyor, plan belirsiz | Trendyol satıcıları | Kampanya kararı anında net kâr. İki farklı tanım çıktı, aynı ürün mü D |
| Cirometre | hesaplayıcı / analiz | Tahmin | D | D | D | D | Trendyol, Hepsiburada, n11 | Sipariş bazlı kâr iddiası |

### 2.2 Eklentiler ve hesaplayıcılar (tahmin tabanlı)

| Ürün | Kategori | GE | İ | R | M | Aylık fiyat | Not |
|---|---|---|---|---|---|---|---|
| TPro360 | eklenti | Tahmin (ürün sayfası hesabı) | D | D | Hayır | D | Chrome sürüm 1.9.3, yaklaşık 42 kullanıcı. Komisyon, kargo, kâr, rakip tahmini stok, fiyat geçmişi, tahmini aylık satış. Mağaza puanı D |
| Trendyol Profit Calculator | eklenti | Tahmin | Hayır | Hayır | Hayır | Ücretsiz görünüyor (D) | Yaklaşık 61 kullanıcı |
| Vitrin Trendyol Satıcı Analiz | eklenti | Tahmin | Kısmen (kargo, KDV; iade D) | Hayır | Hayır | D | 7 kullanıcı; rakip fiyat değişim bildirimi |
| SellerIQ Kar Hesaplayıcı | eklenti | Tahmin | D | D | Hayır | D | Üçüncü taraf tarayıcı sayfasında listeli |
| ecomcalctools | hesaplayıcı | Tahmin | Hayır | Hayır | Hayır (web) | Ücretsiz | Net kâr, net marj, başabaş fiyat. Sabit komisyon tablosu yok |
| IdeaSoft, Ticimax, ikas, Zunapro hesaplayıcıları | hesaplayıcı (lead aracı) | Tahmin | Hayır | Hayır | Hayır | Ücretsiz | Altyapı satıcılarının edinim aracı |
| tetsi, analyzertr, Fikri | hesaplayıcı | Tahmin | D | D | Hayır | Ücretsiz görünüyor (D) | Detay okunamadı |
| E-Ticaret Kar Hesaplayıcı (iOS) | mobil hesaplayıcı | Tahmin (manuel giriş) | Hayır | Hayır | Evet | 49,99 EGP (Mısır mağazası) | Türkiye mağazası sayfası bulunamadı; puan D |
| Cuspart: Kâr/Zarar (iOS) | mobil kayıt | Manuel | Manuel | Manuel | Evet | D | Veriler yalnızca telefonda |

### 2.3 Dolaylı: entegratör, muhasebe, altyapı ve pazaryerinin kendisi

| Ürün | Kategori | Kâr hesabı | Mobil | Fiyat | Segment ve not |
|---|---|---|---|---|---|
| Sentos | entegratör | Hakedişte komisyon/kargo sonrası net kalan (arama özeti) | Bağımsız uygulama bulunamadı | Basic 9.500, Pro 24.900, Plus 39.000, Premium 59.000, Platinum 89.000 TL/yıl, Prestige teklif (rakip kaynağı, Ekim 2026). Aylık seçenek bulunamadı | Orta ve büyük satıcı. Şikayetvar'da tek kullanıcı: Platinum 62.100 TL, 3 taksit (doğrulanmadı) |
| Dopigo | entegratör | Kâr raporu bulunamadı | iOS var; yeterli değerlendirme yok | Pazaryeri 24.999, E-Ticaret 39.999, Muhasebe 74.999 TL/yıl (rakip kaynağı) | Ürün limitleri 500 / 5.000 / 10.000 / 20.000 |
| Entegra | entegratör | Pazaryeri muhasebe ve hakediş takibi, eksik ödeme kontrolü | Bulunamadı | 10.500 ile 125.000 TL/yıl (rakip kaynağı) | En yüksek fiyatlılardan biri (bir kaynağa göre) |
| Zunapro | entegratör | Fiyat motoru (komisyon, KDV, marj); ekstre kullanımı kanıtı yok | D | Süresiz ücretsiz başlangıç, ürün limitli (kendi blog iddiası); ücretli liste D | Kendi sayfasında kategori komisyonu %12 ile 23 diyor (doğrulanmadı) |
| Entagl | analiz / yapay zeka (D) | D | D | D | Yalnızca blog sayfası görüldü (Trendyol yapay zeka asistanı) |
| Stockmount | entegratör | Listeleme kurallarında kâr-zarar tanımı | D | D | 2018'de 500 bin USD yatırım haberi. Güncel fiyat bulunamadı |
| BirFatura | entegratör, e-fatura | Hayır (sipariş, fatura, kargo, mutabakat) | D | Ücretsiz plan: aylık 20 fatura kontörü; ücretli D | Mağaza başına ücret yok |
| Paraşüt e-Ticaret | muhasebe | Muhasebe odaklı | D | e-Ticaret PRO 14.100 TL + KDV (dönem belirsiz); ayrı Paraşüt aboneliği gerekir | 7 gün deneme. Bir blogdaki 79/199/499 TL rakamları resmi sayfayla tutarsız |
| ikas, IdeaSoft, Ticimax | altyapı modülü | Kâr raporu doğrulanmadı | D | ikas modülü ücretli, tutar yok | Sepet altyapısı müşterisine pazaryeri senkronu |
| Kolay Entegre | D | D | D | D | Bu adla ürün bulunamadı. Benzer: Akakçe "Kolay Sipariş" (satış altyapısı) |
| Trendyol Satıcı Paneli, Canlı Performansım, Pusula | pazaryeri paneli | Canlı ciro, ziyaret, sipariş, en çok satan 5 ürün (2021 haberi); net kâr raporu bulunamadı | Evet (Satıcı Paneli uygulaması) | Satıcıya dahil | Google Play'de 3,9 puan, 0 oy (zayıf kaynak) |
| Seller Assistant (sellerassistant.app) | eklenti, global | Amazon odaklı | Hayır | 14 gün deneme, fiyat D | Trendyol ürünü değil. Trendyol'un "Seller Assistant" adlı aracı bulunamadı |

## 3. Yurt dışı karşılıklar

Fiyatlar çoğunlukla üçüncü taraf özetlerden. Resmi fiyat sayfaları okunamadı.

| Ürün | Fiyat | Temel özellik | Kullanıcı / gelir | Övülen 3 | Şikayet 3 |
|---|---|---|---|---|---|
| Sellerboard | Yıllık faturalamada ~15/23/31/63 USD, aylık ~19/29/39/79 (kaynaklar çelişkili); sipariş limiti 3.000 / 6.000 / 15.000 / 50.000 | Amazon kâr panosu, PPC, iade | D | Fiyat/değer, hızlı destek, kolay kurulum (Capterra, G2) | Fiyat yüksek bulanlar var; bazen karmaşık; yorum sayısı az |
| Helium 10 Profits | Platinum 99 (yıllık) / 129 (aylık), Diamond 279 / 359 USD (rakip blog, D) | Geniş Amazon suite | D | Özellik genişliği, eğitim videoları, veri doğruluğu | Faturalama ve iptal, destek (Capterra destek 3,9/5), ücretsiz plan çok sınırlı |
| Jungle Scout | Starter 49 aylık / 29 yıllık; Growth ~79 USD | Ürün araştırma ağırlıklı | D | D | D |
| SellerApp | 39 ile 99 USD (çelişkili) | Amazon analiz | D | D | D |
| Shopkeeper | D | Amazon kâr takibi | D | "En ucuz, 250 sipariş altı" etiketi | D |
| Sellerise | 19,99 USD'den (1 hesap, 1.000 sipariş) | Kâr, marj, sipariş; Chrome Profit Analyzer | G2 4,8 (16 yorum) | Doğru net kâr, düşük giriş fiyatı | Örneklem küçük; "ürün canlıyken en iyi" (RevenueGeeks) |
| Profit Peek | D (arama sonucu yok) | Shopify | D | D | D |
| TrueProfit | 35 / 60 / 100 / 200 USD (300 / 600 / 1.500 / 3.500 sipariş) | Shopify kâr analizi | Shopify 4,9 (391 ile 802 yorum, çelişkili) | Yüksek puan, net arayüz | Destek, zor kurulum, sipariş aşımı ücreti |
| BeProfit | 49 / 99 / 149 / 249 USD | Shopify, Amazon, Woo | Shopify 4,3 (188) ile 4,5 (345) | Çok kanal | Veri doğruluğu, yavaş destek, pahalı, ücretsiz plan değişti |
| Triple Whale | 0 ile 549+ USD (çelişkili); medyan sözleşme ~14.500 USD/yıl (üçüncü taraf) | Atıf + kâr | G2 4,5 (481 yorum) | D | Ek hizmet maliyeti (+%30 ile 60, üçüncü taraf iddiası) |
| 生意参谋 | D | Taobao/Tmall veri aracı | D | D | D |

Not: "En çok övülen/şikayet edilen 3 şey" yalnızca Sellerboard, Helium 10, TrueProfit, BeProfit için kısmen doldurulabildi. Diğerleri için kullanıcı yorumu verisine ulaşılamadı. Pinduoduo araçları araştırılamadı.

## 4. Fiyat bandı önerisi ve gerekçesi

Bu bir hipotezdir, doğrulanmış talep verisi yoktur. Lansman öncesi 15 ile 20 satıcıyla Van Westendorp fiyat duyarlılığı görüşmesi önerilir.

| Plan | Aylık (KDV hariç) | Sınır | Hedef |
|---|---|---|---|
| Ücretsiz | 0 TL | 1 pazaryeri, 50 sipariş/ay, son 30 gün, uyarı yok | Hesaplayıcı kullanan mikro satıcı, edinim |
| Başlangıç | 349 TL | 1 pazaryeri, 500 sipariş/ay, ekstre tabanlı net kâr, günlük özet | Yeni, tek mağazalı satıcı |
| Pro | 799 TL | 2 pazaryeri, 3.000 sipariş/ay, reklam/ROAS, iade/ceza, kârlılık uyarıları, mobil bildirim | Çekirdek segment |
| Büyüme | 1.799 TL | Tüm pazaryerleri, 15.000 sipariş/ay, çoklu mağaza, dışa aktarım, ekip kullanıcıları | Büyük satıcı, ajans |

Yıllık ödemede iki ay bedava (yıllık = aylık x 10) önerilir. Fiyatlar enflasyon nedeniyle 6 aylık gözden geçirilmeli.

Gerekçe:
- **Entegratör çıpası.** Sentos Basic yaklaşık 792 TL/ay, Dopigo Pazaryeri yaklaşık 2.083 TL/ay eşdeğeri (rakip kaynağı). NetKâr bir entegratörün yerine değil, yanına konumlanır. Pro planın Sentos Basic eşdeğeriyle yaklaşık aynı bantta olması, "bir entegratörün yarısı kadar ek bütçe" mesajını destekler. Bu mesaj doğrulanmadı.
- **Aylık ödeme farkı.** Bulunan entegratörler yıllık lisansla satıyor, aylık seçenek bulunamadı. Aylık, iptali kolay bir plan düşük risk algısı yaratır (hipotez).
- **Hacim kademesi.** Sellerboard, TrueProfit, Sellerise, BeProfit sipariş limitine göre kademeli. Maliyet (API çağrısı, depolama) siparişle ölçeklenir.
- **Ücretsiz hesaplayıcılar fiyat tavanı koyar.** En az 8 ücretsiz araç var, bu yüzden ücretsiz katman edinim için şart, ücretli değer "ekstre doğruluğu + uyarı + mobil" olmalı.
- **Aşağı yönlü risk.** Başlangıç 349 TL altına inmek EZV, Melontik vb. fiyatları bilinmediği için körlemesine olur. Önce rakip fiyat sayfalarını doğrudan okuyun (Bölüm 8).

## 5. Farklılaşma fırsatları

1. **Ekstre tabanlı gerçek net kâr.** Trendyol `settlements` verisiyle komisyon oranı ve tutarı gerçek değerden alınır, tahmin yerine mutabakat gösterilir. Teknik not: 15 gün pencere, kayıt teslimattan sonra oluşur, işaret kuralları test verisiyle doğrulanmalı (dokümanlar arasında tutarsızlık notu var).
2. **Tahmin ve gerçek farkı.** Her ürün için "tahmini kâr" ile "ekstreye göre gerçekleşen kâr" yan yana. Hesaplayıcıların güvenilirlik zayıflığına doğrudan yanıt.
3. **İade, ceza, kargo faturası (DeductionInvoices) dahil.** Birçok eklenti iadeyi dışarıda bırakıyor (doğrulanmadı) veya belirtmiyor.
4. **Reklam ve ROAS'ın ürün bazında net kâra bağlanması.** Reklam harcamasını ürün kârından düşüp "reklam sonrası gerçek ROAS" göstermek. Trendyol reklam API'sinin kapsamı doğrulanmadı, teknik keşif şart.
5. **Kârlılık uyarıları.** "Bu ürün son 7 günde zarara döndü", "komisyon oranı değişti", "kampanya fiyatı marjı bitiriyor". Bulunan araçların hiçbirinin uyarı özelliğini doğrulayamadım.
6. **Mobil öncelikli, push bildirimli günlük kâr özeti.** Bulunan mobil ürünler manuel veya paneldir.
7. **Kampanya anı kararı.** Pazarus flaş indirimde net kâr gösteriyor. NetKâr bunu ekstre tabanlı gerçek maliyet ve iade oranıyla yapabilir.
8. **Çoklu pazaryeri tek kâr tablosu.** Trendyol, sonra Hepsiburada, n11, Amazon TR. Hepsiburada tarafında 102 bin aktif satıcı hedef havuzu.
9. **Nakit akışı ve vade.** EZV iddia ediyor. Ödeme vadesi (paymentOrderId) takibi mobilde "ne zaman ne yatacak" olarak sunulabilir.
10. **Entegratörle ortaklık.** Rakip değil, eklenti olarak (Sentos, Dopigo, BirFatura müşterileri). Ortaklık potansiyeli doğrulanmadı.

Risk: EZV, Melontik, Biliyo, OZZMOO benzer vaatte. Bağımsız kullanıcı yorumu bulunamadı, bu yüzden gerçek kalite farkı bilinmiyor. Rakiplerin demolarını denemek şart.

## 6. Satıcı sayısı ve segment

| Veri | Değer | Kaynak ve güvenilirlik |
|---|---|---|
| Trendyol satıcı/iş ortağı | 250 binden fazla (2025) | AA, Erdem İnan açıklamaları. Orta-yüksek güvenilirlik (haber ajansı, şirket beyanı); "satıcı" ve "iş ortağı" ifadeleri karışık kullanılıyor |
| Trendyol yurt dışına satan | 125 binden fazla satıcı | Aynı AA haberleri (şirket beyanı) |
| Trendyol e-ihracat | 2022'den beri 51 binden fazla satıcı ihracat yaptı, 42 bini ilk kez | Habertürk (tarihi haberde açık değil, D) |
| Diğer sayılar | 230 bin+, 300 bin+ | Blog ve ilan metinleri. Düşük güvenilirlik, birbiriyle çelişiyor |
| Trendyol satıcı bölgesel dağılım | Marmara %50, İç Anadolu %15, Ege %13 | Trendyol 2025 Sosyoekonomik Etki Raporu (haber aktarımı) |
| Trendyol segment (mikro, KOBİ, büyük) | Bulunamadı | D. Tam raporun okunması gerekir |
| Hepsiburada aktif satıcı | 102,0 bin (31 Aralık 2025), bir yıl önce 100,2 bin (+%1,8) | Hepsiburada Q4 ve 2025 sonuçları (6-K). Yüksek güvenilirlik (resmi); 2026 Q1'den itibaren metrik tanımları Kaspi'ye göre değişecek |
| Hepsiburada pazaryeri GMV | 176,2 milyar TL (2025), toplam GMV'nin %68,4'ü | Aynı sonuç bildirimi (TMS 29 enflasyon muhasebesine göre) |

Hepsiburada FY2025 Form 20-F SEC'te yayımlanmış (bağlantı Kaynaklar'da); içeriğini okuyamadım, satıcı sayısı yukarıdaki sonuç bildiriminden alındı. Sonuç: yaklaşık 350 bin ile 400 bin satıcılık adreslenebilir havuz olabilir, ancak iki platformda çakışan satıcılar çıkarılmadan toplanamaz (çakışma oranı D).

## 7. İsim kontrolü

| Arama | Sonuç |
|---|---|
| App Store "NetKar" | **Çakışma bulundu.** mwm.ai üçüncü taraf listeleme sitesinde "NetKar" (App Store kimliği 6757768044): günlük/haftalık/aylık gelir-gider takibi, otomatik net kâr/zarar, kategori bazlı harcama analizi; küçük işletme, serbest çalışan ve bireysel hedefli. Geliştirici, ülke, puan, yorum sayısı doğrulanmadı |
| Google Play | Bulunamadı (D) |
| Web ("netkar", netkar.com.tr, netkar.app) | Arama motorunda bu adla şirket veya site çıkmadı; benzer: Netmak, Netmera, Netcad, Netaş, TurkNet |
| TÜRKPATENT | Sorgulanamadı (D). Marka Sorgulama'dan 9, 35, 36, 42. sınıflar manuel kontrol edilmeli |
| Alan adı müsaitliği | Doğrulanamadı (D). WHOIS/registrar'dan netkar.com.tr, netkar.app, netkar.com kontrol edilmeli |
| Ek risk | Trendyol "Pusula" (satıcı paneli) adı ve Cirometre ("-metre") ile yakın isimlerden kaçınıldı |

**Sonuç:** App Store'daki "NetKar", aynı işlev alanında ve neredeyse aynı yazımda olduğu için çakışma riskini yüksek sayıyorum. Hukuki değerlendirme için marka vekili gerekir. "Netkar" ve "NetKâr" yazımları aynı ses ve ASCII hâlinde karışır.

**5 alternatif isim** (hiçbirinin alan adı veya marka müsaitliği doğrulanmadı; önerilen alan adları tahmindir):

| İsim | Anlam | Olası alan adı (D) |
|---|---|---|
| SafiKâr | "Safi" Türkçe muhasebede net demek; kısa, ciddi | safikar.com.tr, safikar.app |
| KârBak | Emir kipi, mobilde "bak" çağrışımı | karbak.com.tr, karbak.app |
| KârİZ | "Kâr izi", ürün bazlı iz sürme | kariz.com.tr (ortak kelime, dolu olma riski yüksek) |
| NetKasa | Net + kasa, nakit akışı çağrışımı | netkasa.com.tr, netkasa.app |
| Marjik | Marj + küçük ek; marka olarak üretilebilir | marjik.com.tr, marjik.app |

## 8. Doğrulanması gereken sonraki adımlar

1. Alan adı izni açık bir ağdan EZV, Melontik, Biliyo, OZZMOO, Cirometre, Pazarus, TPro360, Entagl, Zunapro, Dopigo, Sentos, Entegra fiyat sayfalarını doğrudan okuyun.
2. Chrome Web Store, App Store TR, Google Play TR'den puan ve yorum sayılarını toplayın (bu çalışmada neredeyse tamamı boş).
3. Trendyol 2025 Sosyoekonomik Etki Raporu tam metninden segment dağılımını alın.
4. TÜRKPATENT ve WHOIS sorgularını yapın; "NetKar" iOS uygulamasının geliştiricisini App Store'dan öğrenin.
5. Trendyol reklam API'si ve Hepsiburada finans uç noktalarının kapsamını dokümandan doğrulayın.

## Kaynaklar (APA 7)

Not: Erişim tarihi hepsi için 5 Kasım 2026. Çoğu kaynak arama sonucu özeti olarak okundu; sayfa gövdesi doğrudan okunamadı. Yazarı olmayan kaynaklarda başlık başa alındı.

Anadolu Ajansı. (2025). *Trendyol, Perakende Günleri 2025'te teknoloji odaklı e-ihracat yol haritasını paylaştı*. 5 Kasım 2026 tarihinde https://www.aa.com.tr/tr/isdunyasi/e-ticaret/trendyol-perakende-gunleri-2025te-teknoloji-odakli-e-ihracat-yol-haritasini-paylasti/695439 adresinden alındı

Anadolu Ajansı. (2025). *Trendyol'un "Kasım Kampanyaları" bu yıl 15 ülkede birden gerçekleştirilecek*. 5 Kasım 2026 tarihinde https://www.aa.com.tr/tr/isdunyasi/e-ticaret/trendyolun-kasim-kampanyalari-bu-yil-15-ulkede-birden-gerceklestirilecek/698270 adresinden alındı

Capterra. (t.y.). *Pazarus*. 5 Kasım 2026 tarihinde https://www.capterra.co.za/software/1222090/Pazarus adresinden alındı

Capterra. (t.y.). *Helium 10 reviews 2026*. 5 Kasım 2026 tarihinde https://www.capterra.com/p/193503/Helium10/reviews/ adresinden alındı

Capterra. (t.y.). *Sellerboard reviews 2026*. 5 Kasım 2026 tarihinde https://www.capterra.com/p/238895/sellerboard/reviews/ adresinden alındı

Chromeboard. (t.y.). *Tpro360 Trendyol Satıcı A*. 5 Kasım 2026 tarihinde https://chromeboard.com/extension/tpro360-trendyol-satıcı-a-cgjaahlokendogeedjdphhoimdigkllb adresinden alındı

Chromeboard. (t.y.). *Trendyol Profit Calculato*. 5 Kasım 2026 tarihinde https://chromeboard.com/extension/trendyol-profit-calculato-mffdekjlcmfajgmonidofllojhjjklfo adresinden alındı

Chromeboard. (t.y.). *Vitrin Trendyol Satıcı An*. 5 Kasım 2026 tarihinde https://www.chromeboard.com/extension/vitrin-trendyol-satıcı-an-gngemcnlckjbkdancoeibchcmmoiegol adresinden alındı

Chrome Web Store. (t.y.). *Pazarus*. 5 Kasım 2026 tarihinde https://chromewebstore.google.com/detail/pazarus/agoiefdamjbiiklngbdpkhddkbiojmdd adresinden alındı

CostBench. (t.y.). *All Triple Whale plans and pricing*. 5 Kasım 2026 tarihinde https://costbench.com/software/marketing-attribution/triple-whale/ adresinden alındı

D-Market Electronic Services & Trading. (2026). *Form 20-F, fiscal year ended December 31, 2025*. U.S. Securities and Exchange Commission. 5 Kasım 2026 tarihinde https://www.sec.gov/Archives/edgar/data/0001850235/000110465926053195/heps-20251231x20f.htm adresinden alındı (içerik okunamadı)

Ecomcalctools. (t.y.). *Trendyol komisyon hesaplama 2026*. 5 Kasım 2026 tarihinde https://ecomcalctools.com/tr/trendyol/komisyon-hesaplama/ adresinden alındı

Ecomcalctools. (t.y.). *Trendyol kâr hesaplama rehberi*. 5 Kasım 2026 tarihinde https://ecomcalctools.com/tr/blog/trendyol-kar-hesaplama/ adresinden alındı

EcomCrew. (t.y.). *Helium 10 vs Jungle Scout, what is better in 2026?* 5 Kasım 2026 tarihinde https://www.ecomcrew.com/helium10-vs-junglescout/ adresinden alındı

Entagl. (t.y.). *Trendyol yapay zeka asistanı soru cevaplama*. 5 Kasım 2026 tarihinde https://www.entagl.com/blog/trendyol-yapay-zeka-asistani-soru-cevaplama adresinden alındı

EZV. (t.y.). *Trendyol ve Hepsiburada kâr analizi programı*. 5 Kasım 2026 tarihinde https://ezv.com.tr/ adresinden alındı

Hepsiburada. (2026, 26 Şubat). *Hepsiburada announces fourth quarter and full year 2025 financial results*. 5 Kasım 2026 tarihinde https://finviz.com/news/324386/hepsiburada-announces-fourth-quarter-and-full-year-2025-financial-results adresinden alındı

Helium 10. (t.y.). *Helium 10 pricing plan vs Jungle Scout pricing plan*. 5 Kasım 2026 tarihinde https://www.helium10.com/blog/helium10-pricing-plan-vs-jungle-scout-pricing-plan/ adresinden alındı

IdeaSoft. (t.y.). *Trendyol ücretsiz komisyon ve kâr hesaplama aracı*. 5 Kasım 2026 tarihinde https://www.ideasoft.com.tr/sayfa/trendyol-komisyon-hesaplama/ adresinden alındı

Melontik. (t.y.). *Melontik*. 5 Kasım 2026 tarihinde https://melontik.com/ adresinden alındı

mwm.ai. (t.y.). *NetKar*. 5 Kasım 2026 tarihinde https://mwm.ai/apps/netkar/6757768044 adresinden alındı

Nefes. (t.y.). *Trendyol 2025 sosyoekonomik etki raporunu yayımladı*. 5 Kasım 2026 tarihinde https://www.nefes.com.tr/trendyol-2025-sosyoekonomik-etki-raporunu-yayimladi-137400 adresinden alındı

Paraşüt. (t.y.). *e-Ticaret entegrasyonları*. 5 Kasım 2026 tarihinde https://www.parasut.com/e-ticaret-entegrasyonlari adresinden alındı

Pazarus. (t.y.). *Pazaryeri kâr hesaplama*. 5 Kasım 2026 tarihinde https://pazarus.io/pazarus-ozellikleri/pazaryeri-kar-hesaplama adresinden alındı

Ringly. (t.y.). *The best TrueProfit alternatives (tested and compared)*. 5 Kasım 2026 tarihinde https://www.ringly.io/blog/trueprofit-alternatives adresinden alındı

RevenueGeeks. (t.y.). *How much does Sellerise cost? Updated pricing guide (2026)*. 5 Kasım 2026 tarihinde https://revenuegeeks.com/?p=7890 adresinden alındı

RevenueGeeks. (t.y.). *Profit trackers*. 5 Kasım 2026 tarihinde https://revenuegeeks.com/amazon/profit-trackers adresinden alındı

Sentos. (t.y.). *Trendyol entegrasyonu*. 5 Kasım 2026 tarihinde https://www.sentos.com.tr/trendyol-entegrasyon/ adresinden alındı

SpotSaaS. (t.y.). *Sellerboard pricing*. 5 Kasım 2026 tarihinde https://www.spotsaas.com/product/sellerboard/pricing adresinden alındı

Trendyol. (t.y.). *Cari hesap ekstresi entegrasyonu*. Trendyol Developers. 5 Kasım 2026 tarihinde https://developers.trendyol.com/docs/cari-hesap-ekstresi-entegrasyonu adresinden alındı

Webrazzi. (2021, 16 Ağustos). *Trendyol'dan satıcılara özel veri kontrol merkezi: Canlı Performansım*. 5 Kasım 2026 tarihinde https://webrazzi.com/2021/08/16/trendyoldan-saticilara-ozel-veri-kontrol-merkezi-canli-performansim/ adresinden alındı

Webrazzi. (2018, 20 Mart). *Sanal mağaza yönetimi için yerli alternatif: StockMount*. 5 Kasım 2026 tarihinde https://webrazzi.com/2018/03/20/sanal-magaza-yonetimi-icin-yerli-alternatif-stockmount/ adresinden alındı

Zunapro. (2026, Ekim). *Sentos alternatifi*. 5 Kasım 2026 tarihinde https://www.zunapro.com/turkey/tr/blog/sentos-alternatifi adresinden alındı (rakip kaynağı)

Zunapro. (2026, Ekim). *Dopigo alternatifi*. 5 Kasım 2026 tarihinde https://www.zunapro.com/turkey/tr/blog/dopigo-alternatifi adresinden alındı (rakip kaynağı)

Zunapro. (2026, Ekim). *Entegra alternatifi*. 5 Kasım 2026 tarihinde https://www.zunapro.com/turkey/tr/blog/entegra-alternatifi adresinden alındı (rakip kaynağı)
