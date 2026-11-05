# NetKâr: Pazara Giriş (GTM) Planı, Reklamsız veya Düşük Bütçeli

- Belge no: 05
- Sürüm: 1.0
- Hazırlanma ve erişim tarihi: 5 Kasım 2026
- Kapsam: Trendyol satıcılarına satılacak B2B SaaS + mobil uygulama (çalışma adı NetKâr). Sonra Hepsiburada, n11, Amazon TR; ileride global.
- Bütçe kısıtı: Varsayılan reklam bütçesi 0 TL. Bölüm 7'deki koşullar sağlanırsa ayda en fazla 5.000 TL test.
- İnsan zamanı: Hasan için haftada en fazla 4-5 saat pazarlama. Geri kalan iş Claude ajanlarıyla otomasyon.

## Yöntem notu

- Pazar ve kanal verileri WebSearch ile toplandı. Arama hacmi ve SERP verisi, hyturkyilmaz.com projesindeki OpenSEO aracıyla (DataForSEO altyapısı, Türkiye, Türkçe, Google) 5 Kasım 2026'da çekildi. Hacimler 12 aylık ortalama tahmindir, Google Ads yakın varyantları gruplar ("kar" ve "kâr" aynı hacmi gösteriyor).
- Bazı rakip sitelere (trendhesap.net, selleriq.co, melontik.com) ve cnbce.com'a bu oturumun ağ kısıtı nedeniyle doğrudan erişilemedi. Bu sitelere ait bilgiler arama motoru özetlerinden alındı ve öyle işaretlendi. Kayıt öncesi sayfadan teyit edilmeli.
- Doğrulanamayan her sayı ve hedef metinde **(varsayım)** olarak işaretlendi. Hedef rakamları tahmin değil, planlama hedefidir.
- Kaynaklar sonda APA 7 biçimindedir. Tüm web kaynaklarına erişim tarihi 5 Kasım 2026'dır.

---

## 1) Yönetici özeti

### Durum

- Türkiye'de e-ticaret hacmi 2025'te bir önceki yıla göre %52,2 artarak 4,57 trilyon TL'yi aştı. En büyük pay 428,7 milyar TL ile giyim, ayakkabı ve aksesuarda (Ticaret Bakanlığı, 2026).
- Trendyol'un 2025 Sosyoekonomik Etki Raporu'na göre platform 250 binden fazla iş ortağıyla çalışıyor. Satıcıların %50'si Marmara'da, %15'i İç Anadolu'da, %13'ü Ege'de (Anadolu Ajansı, t.y.). "İş ortağı" sayısı satıcı sayısıyla birebir aynı olmayabilir.
- Hepsiburada'nın aktif satıcı sayısı 30 Haziran 2025 itibarıyla 100,3 bin (Hepsiburada, 2025). İkinci pazar için ciddi bir havuz.
- Talep ölçülebilir ve yüksek: "trendyol komisyon hesaplama" ayda 18.100, "desi hesaplama" 14.800, "trendyol kar hesaplama" 6.600, "trendyol komisyon oranları" 2.900 arama alıyor. Anahtar kelime zorluğu (KD) 0 ile 15 arasında (OpenSEO/DataForSEO, 2026).
- Ancak SERP kalabalık. "trendyol komisyon hesaplama" sorgusunda ilk sayfada 15'ten fazla ücretsiz hesaplayıcı var (rexven.com, malidigital.com.tr, faturaport.com, beekod.com, melontik.com, sentos.com.tr, parasut.com, zunapro.com vb.) ve SERP'te AI Overview kutusu çıkıyor (OpenSEO/DataForSEO, 2026). Sadece "bir hesaplayıcı daha" yapmak fark yaratmaz.
- Doğrudan rakipler var: Melontik (Trendyol ve Hepsiburada net kâr, hakediş kontrolü, fiyat motoru), TrendHesap (7 gün deneme, arama özetine göre 399 TL/ay KDV dahil), SellerIQ (30 gün deneme, salt okuma API), Entegrify Profit (reklam maliyeti dahil, 7 gün kartsız deneme), KarPanel (Product Hunt'ta listelenmiş), Zunapro (negatif marj uyarısı ve repricer) ve Rexven'in ücretsiz kâr hesaplama eklentisi. Aramada ROAS düşünce bildirim gönderen bir ürüne rastlanmadı.
- Fırsat alanı: Gerçek hakediş ekstresiyle mutabakat, reklamın ürün bazında kârı yediğini gösteren uyarılar ve mobil bildirim. Trendyol'un resmi finans servisleri satış, iade, indirim, kupon, komisyon ve hakediş kalemlerini ayrı servislerden veriyor (Trendyol Developers, t.y.-a). Bu veri, hesaplayıcıların veremediği "gerçekleşen" rakamı sağlar.

### Hedef (planlama hedefleri, varsayım)

| Zaman | Bekleme listesi | Kurucu üye | Ödeyen satıcı | MRR (KDV hariç) |
|---|---|---|---|---|
| 90. gün (7 Şubat 2027) | 400-800 | 50 | 60-120 | 35-80 bin TL |
| 6. ay (Mayıs 2027) | - | 50 | 150-220 | 100-150 bin TL |
| 12. ay (Kasım 2027) | - | 50 | 250-350 (başabaş bandı) | 160-230 bin TL |

Varsayım: Ortalama hesap başı gelir (ARPA) indirimler ve yıllık planlar sonrası yaklaşık 650 TL/ay.

### Strateji: dört büyüme motoru

1. **Ücretsiz araç + SEO:** Komisyon, net kâr, desi-kargo, iade maliyeti ve başabaş ROAS hesaplayıcıları. Farkı "sonucu kaydet, gerçek verinle karşılaştır" adımı yaratır: hesaplayıcı tahmin verir, NetKâr gerçekleşeni gösterir.
2. **Kurucu liderliğinde güven:** Hasan'ın LinkedIn ağı, sektör tanınırlığı ve hyturkyilmaz.com blogu. İçerik ajanlar tarafından taslaklanır, Hasan onaylar ve kendi sesiyle yayınlar.
3. **Ortaklık kanalı:** Mali müşavirler, e-ticaret eğitmenleri ve akademiler, entegratörler, kargo ve fulfillment firmaları. Tekrarlayan komisyon (öneri: ilk 12 ay %20-25).
4. **Ürün içi viral döngüler:** Paylaşılabilir "Aylık Kâr Karnesi" görseli, muhasebeciye giden "NetKâr ile hazırlandı" rozetli PDF rapor, iki taraflı davet ödülü, ekip ve muhasebeci koltuğu daveti.

### KPI özeti (haftalık izlenir)

- Kuzey yıldızı metriği: **Haftalık aktif "kâr görüntüleyen" mağaza sayısı** (son 7 günde first_profit_view veya kâr ekranı açan, API'si bağlı mağaza).
- Edinim: hesaplayıcı kullanımı, bekleme listesi kaydı, kayıt (signup), kanal bazında kayıt payı.
- Aktivasyon: kayıttan sonra 24 saat içinde api_connected oranı (hedef %50+), 48 saat içinde first_profit_view (hedef %40+).
- Gelir: deneme→ücretli dönüşüm (hedef %12-20, kartsız deneme için iddialı bir hedef, Bölüm 4.3'e bakın), MRR, ARPA.
- Elde tutma: aylık logo churn (hedef %5 altı), net gelir tutma.
- Verimlilik: kanal bazında CAC, geri ödeme süresi (hedef 6 ay altı), harcama varsa CPA ve ROAS.

---

## 2) ICP ve segmentler

### 2.1 Segment tablosu

Sipariş hacmi sınırları ve oranlar varsayımdır. Trendyol satıcı büyüklük dağılımına dair kamuya açık resmi veri bulunamadı.

| Segment | Aylık sipariş (varsayım) | Tipik yapı | Acı noktası | Satın alma tetikleyicisi | Öncelik |
|---|---|---|---|---|---|
| Mikro / yeni başlayan | 0-100 | Tek kişi, yan iş | Komisyonu ve kargoyu bilmeden fiyat koyuyor | İlk zararlı satış, ilk hakediş şaşkınlığı | Ücretsiz araçlarla besle, satış hedefi değil |
| Küçük, büyüyen | 100-1.000 | 1-3 kişi, Excel ile takip | Ciro artıyor ama banka hesabına yansımıyor | Reklama başlamak, Kasım gibi kampanya dönemi, kargo zammı | **Birincil ICP** |
| Orta | 1.000-10.000 | 3-15 kişi, entegratör kullanıyor, muhasebeci var | Yüzlerce üründe hangisinin zarar ettiği belli değil, reklam bütçesi büyük | Komisyon değişikliği, hakediş farkı, ortak veya yatırımcı raporu | **Birincil ICP** |
| Büyük | 10.000+ | ERP ve iç ekip | Özel raporlama, çok pazar | Yeni pazar, denetim | İkincil, ilk yıl satış hedefi değil |
| Ajans / danışman / muhasebeci | 5-30 mağaza yönetiyor | Müşteri adına mağaza ve reklam yönetimi | Her müşteriye ayrı Excel, müşteriye kârlılık gösterememe | Yeni müşteri kazanımı, raporlama yükü | **İkincil ICP, çarpan etkisi** |

### 2.2 Kategori önceliği

- **Giyim, ayakkabı, aksesuar:** e-ticaretin en büyük sektörü (Ticaret Bakanlığı, 2026). İade oranının yüksek olduğu bir kategori olduğu yaygın kabul görüyor ancak Trendyol'a özel iade oranı verisi bulunamadı (varsayım). İade maliyeti mesajı en güçlü burada.
- **Ev ve yaşam, kozmetik, anne-bebek:** Düşük birim fiyat ve desi etkisi nedeniyle kargo payı yüksek (varsayım).
- **Elektronik aksesuar:** Buybox rekabeti ve düşük marj (varsayım). Buybox ve fiyat uyarıları burada değerli.

### 2.3 Ortak acı noktaları (kanıt)

- Satıcı kâr formülü çok kalemli: komisyon, komisyon KDV'si, kargo (desi bazlı), platform hizmet bedeli, %1 stopaj, reklam, iade (ecomcalctools, t.y.; Webrazzi, 2024). Kaynaklar arasında bile komisyonun KDV dahil mi hariç mi hesaplandığı konusunda çelişki var: bir rehber KDV hariç fiyat üzerinden bölerek, diğeri KDV dahil fiyat üzerinden hesaplıyor (OpenSEO/DataForSEO, 2026 SERP özetleri). Bu karışıklık, "gerçek ekstreden doğrulanmış rakam" vaadinin değerini artırıyor.
- Şikayetvar'da satıcılar iade ve iptal nedeniyle zarara girdiklerini, reklam bakiyesinin hem karttan hem hakedişten kesildiğini anlatıyor (Şikayetvar, t.y.-a; Şikayetvar, t.y.-b). Bunlar anekdottur, istatistik değildir.
- Bağımsız bir "reklam kârı yiyor" anketi bulunamadı. Bu nedenle mesajda yüzde vermiyoruz. Beta verisinden anonim ve toplu bir endeks çıkarmak (kullanıcı onayıyla) içerik planının parçasıdır.

### 2.4 Satın alma tetikleyicileri (zamanlama)

1. **Kampanya dönemi sonrası hakediş:** Trendyol Kasım 2026 için 1,5 milyar ziyaret ve 120 milyon ürün hedefi açıkladı (Dünya, 2026). Kasım satışlarının hakedişi Aralık'ta gelir. "Kasım'da gerçekte ne kazandınız?" sorusu Aralık ayında en güçlü kancadır.
2. **Komisyon veya kargo tarifesi değişikliği.**
3. **Reklam bütçesini artırma kararı.**
4. **Yıl sonu kapanışı ve muhasebeci talepleri** (Aralık-Ocak).
5. **Stopaj gibi mevzuat değişiklikleri:** 1 Ocak 2025'ten beri e-ticaret aracı hizmet sağlayıcılarının satıcıya ödemelerinden %1 stopaj kesiliyor (Webrazzi, 2024).

### 2.5 Üç persona

**Persona A: Elif, büyüyen tek mağaza sahibi (birincil)**

- 31 yaşında, İstanbul. Kadın giyim, kendi tedarikçisinden alıyor. Trendyol'da 2 yıldır, ayda 600-900 sipariş, 180 ürün.
- Ekibi: kendisi ve yarı zamanlı bir paketleme çalışanı. Takip Excel ile.
- Acısı: "Ciro 400 bin TL görünüyor, hesabıma o kadar yatmıyor. Reklamı açınca satış artıyor ama kâr artıyor mu bilmiyorum."
- Mevcut çözüm: Ücretsiz hesaplayıcı, ayda bir Excel'de hakediş kontrolü.
- İtirazı: "API anahtarımı vermekten çekinirim. Bir uygulamaya daha para vermek istemem."
- Nerede: Instagram ve YouTube'da e-ticaret eğitmenleri, WhatsApp satıcı grupları (varsayım), Trendyol Akademi.
- Ona söylenecek: "Hangi ürünün sana para kaybettirdiğini 10 dakikada gör. Bağlantı salt okuma, istediğin an kesersin."

**Persona B: Murat, aile şirketinde e-ticaret sorumlusu (birincil)**

- 44 yaşında, Bursa. Ev tekstili üreticisi, Trendyol ve Hepsiburada'da. Ayda 3.000-5.000 sipariş, 1.200 SKU, entegratör kullanıyor.
- Acısı: Ürün bazında kârlılık yok. Patron "bu ay neden az para kaldı" diye soruyor. Muhasebeci ay sonu rakamları geç veriyor.
- Mevcut çözüm: Entegratör raporları + muhasebecinin Excel'i.
- İtirazı: "Entegratörümüzde zaten rapor var. Rakamlar muhasebeyle tutar mı?"
- Nerede: LinkedIn, sektör etkinlikleri, ticaret odası ve ihracatçı birliği duyuruları, mali müşaviri.
- Ona söylenecek: "Hakediş ekstresini satır satır siparişle eşleştiriyoruz. Muhasebecinize aylık PDF gider."

**Persona C: Burak, e-ticaret ajansı veya danışman (ikincil, çarpan)**

- 36 yaşında, İzmir. 12 müşterinin Trendyol mağazasını ve reklamını yönetiyor.
- Acısı: Müşteriye ciro ve ROAS raporu veriyor ama net kârı gösteremiyor. Her müşteri için ayrı Excel. Müşteri kaybı riski.
- İtirazı: "Fiyat mağaza başına katlanırsa bana pahalı olur. Müşterim verisini görmeli mi?"
- Nerede: LinkedIn, ajans toplulukları, eğitim verdiği platformlar.
- Ona söylenecek: "Tek panelde tüm müşteri mağazaları. Müşterine kendi logonla aylık kâr raporu. Getirdiğin her mağaza için komisyon."

---

## 3) Konumlandırma ve mesaj evi

### 3.1 Konumlandırma cümlesi (iç kullanım)

Trendyol'da satış yapan ve reklam harcayan küçük ve orta ölçekli satıcılar için NetKâr, gerçek hakediş ekstresini ürün ve sipariş bazında çözümleyerek her ürünün komisyon, KDV, kargo, iade ve reklam sonrasında ne bıraktığını gösteren ve zarar başladığında haber veren kârlılık uygulamasıdır. Hesaplayıcılardan farkı tahmin değil gerçekleşen rakamı vermesi, entegratör raporlarından farkı reklam ve iadeyi ürün kârına bağlaması ve mobil uyarı göndermesidir.

### 3.2 Tek cümle vaat (dış kullanım)

> **Cironuzu değil, cebinize kalanı gösterir.**
> Alt satır: Trendyol hesabınızı bağlayın, her ürünün komisyon, kargo, iade ve reklam sonrası net kârını hakediş ekstrenizle eşleşmiş olarak görün.

Not: "Kesin", "garanti", "%100 doğru" gibi ifadeler kullanılmaz. Rakamların kaynağı (Trendyol finans servisleri) ve kullanıcının girdiği maliyet varsayımları her ekranda açıkça yazılır.

### 3.3 Mesaj evi

| Katman | İçerik |
|---|---|
| Çatı (vaat) | Cironuzu değil, cebinize kalanı gösterir. |
| Sütun 1: Gerçek veri | Hesaplama tahmine değil, Trendyol'un hakediş ve cari hesap ekstresi servislerine dayanır (Trendyol Developers, t.y.-a). Sipariş, iade, kupon ve komisyon satırları siparişle eşleşir. |
| Sütun 2: Reklam dahil ürün kârı | Her ürün için başabaş ROAS ve reklam sonrası net kâr. "Bu üründe reklam kârı yiyor" uyarısı. |
| Sütun 3: Zamanında uyarı | "Zararına satıyorsun", "hakediş beklenenden düşük", "komisyon değişti" bildirimleri telefona gelir. |
| Temel (güven) | Salt okuma bağlantı, istediğiniz an bağlantıyı kesme, KVKK uyumlu aydınlatma, veriler Türkiye'de veya sözleşmeli veri aktarımıyla (karar verilecek, Bölüm 9), kurucu adı ve yüzü görünür. |
| Ek değer | AI ile müşteri sorusuna yanıt taslağı (gönderilmeden önce satıcı onaylar). |

### 3.4 Üç kanıt (beta sonunda doldurulacak)

Kanıtlar henüz yoktur, beta sürecinde üretilecektir. Uydurma vaka kullanılmaz.

1. **Kanıt 1, mutabakat doğruluğu:** "Beta mağazalarında hakediş ekstresiyle hesaplanan net tutar arasındaki fark ortalama X TL / %Y" (iç ölçüm, Hafta 7'de yayımlanır).
2. **Kanıt 2, bulunan zararlı ürünler:** "Kurucu 50 programındaki mağazaların %X'inde en az bir ürünün reklam sonrası zararda olduğu görüldü" (anonim, toplu, kullanıcı onaylı).
3. **Kanıt 3, isimli vaka:** En az 3 satıcının adıyla ve izniyle yayımlanan önce/sonra hikayesi (ör. "zararlı 14 ürünün reklamını durdurdu, aylık net kâr şu kadar değişti").

### 3.5 İtiraz ve cevap tablosu

| İtiraz | Cevap (doğal dil, abartısız) | Kanıt veya destek |
|---|---|---|
| "Excel'de zaten yapıyorum." | Excel tahmini iyi yapar. Zorlaşan kısım iade, kupon ve reklam kesintilerinin hangi siparişe ait olduğunu bulmak. NetKâr bunu ekstreden otomatik eşleştirir. İlk ay Excel'inizle yan yana kullanın, farkı kendiniz görün. | Ücretsiz "Excel ile karşılaştır" şablonu |
| "API anahtarımı vermek riskli." | Bağlantı yalnızca okuma için kullanılır, ürün veya fiyat değiştirmez. Anahtarı Trendyol panelinden istediğiniz an yenileyebilir, bağlantıyı tek tıkla kesebilirsiniz. Anahtarlar şifreli saklanır. | /guvenlik sayfası, Trendyol'un entegrasyon bilgilerinin panelde yönetildiğine dair resmi doküman (Trendyol Developers, t.y.-a) |
| "Entegratörümde rapor var." | Entegratörler sipariş, stok ve fatura akışında güçlü. NetKâr onların yerine geçmez, yanına eklenir: reklam ve iadeyi ürün kârına bağlar, hakedişle karşılaştırır. | Entegrasyonlar sayfası |
| "Ücretsiz hesaplayıcılar var." | Biz de ücretsiz hesaplayıcı sunuyoruz. Hesaplayıcı bir ürünün olması gereken kârını söyler, NetKâr geçen ay gerçekten ne kaldığını. | /araclar |
| "Pahalı." | Başlangıç planı 499 TL/ay (varsayım fiyat). Ayda bir zararlı ürünü yakalamak çoğu mağazada bu tutarı karşılar (her mağazada geçerli olmayabilir, deneme süresinde kendi verinizle görün). 14 gün ücretsiz, kart gerekmez. | Deneme sonunda "NetKâr'ın bulduğu" özeti |
| "Trendyol paneli zaten gösteriyor." | Panel finans ekranları kalemleri ayrı ayrı gösterir. Ürün bazında reklam ve iade sonrası kârı tek ekranda ve uyarıyla vermez (Hasan'ın panel incelemesiyle teyit edilmeli, varsayım). | Ekran karşılaştırması |
| "Muhasebecim hallediyor." | Muhasebeci ay sonunda toplamı görür. Siz ürün kararını gün içinde verirsiniz. Muhasebeciniz için ayrıca aylık PDF rapor hazırlanır. | Muhasebeci koltuğu, PDF rapor |
| "Rakamlar doğru mu?" | Her rakamın yanında kaynağı yazar: Trendyol ekstresi mi, sizin girdiğiniz maliyet mi. Fark çıkan siparişler ayrı listelenir. | Mutabakat ekranı |
| "Hepsiburada'da da satıyorum." | İlk sürüm Trendyol. Hepsiburada entegrasyonu yol haritasında (hedef 4.-5. ay, varsayım). Bekleme listesine ekleyelim. | Yol haritası sayfası |
| "AI cevap yazarsa yanlış bir şey söyler." | AI yalnızca taslak hazırlar. Siz okumadan ve onaylamadan hiçbir cevap gönderilmez. | Ürün içi onay adımı |

---

## 4) Kanal planı

### 4.1 Haftalık insan saati bütçesi (en fazla 5 saat)

| Blok | Saat/hafta | Ne yapılır |
|---|---|---|
| LinkedIn kurucu içeriği | 1,5 | 2-3 gönderi onayı ve yayın, yorumlara cevap, 10 DM |
| Satıcı görüşmeleri ve onboarding | 1,5 | Haftada 3-4 adet 20 dakikalık görüşme (ilk 8 hafta keşif, sonra kurucu üye onboarding) |
| Ortaklık | 1,0 | Haftada 2 ortak adayıyla görüşme veya takip |
| Topluluk + içerik onayı | 1,0 | Topluluk sorularına cevap, ajan taslaklarının onayı, SEO sayfa onayı |
| **Toplam** | **5,0** | |

Kural: Ajan taslak üretir, Hasan onaylamadan hiçbir şey kurucu adıyla yayımlanmaz. Topluluklarda otomatik paylaşım yapılmaz (spam ve hesap kapanma riski).

### 4.2 Kanal tablosu

Beklenen sonuç aralıkları, benzer çalışmalara dair Türkiye'ye özel veri bulunamadığı için **varsayımdır** ve ilk 4 haftanın verisiyle güncellenir.

| # | Kanal | Taktik | İnsan saat/hafta | Ajan otomasyonu | Beklenen sonuç, 90 gün (varsayım) | Maliyet | Ölçüm |
|---|---|---|---|---|---|---|---|
| A | Ücretsiz araçlar + SEO | 5 hesaplayıcı (komisyon, net kâr, desi-kargo, iade maliyeti, başabaş ROAS), "Trendyol komisyon oranları" güncel tablo sayfası. Her araçta "sonucu e-postana gönder" ve "gerçek verinle karşılaştır" adımı. | 0,25 (onay) | Sayfa taslakları, oran tablosu güncelleme ajanı (haftalık kontrol, değişiklik varsa Hasan'a bildirim), SERP izleme | Arama hacmi: komisyon 18.100, desi 14.800, kâr 6.600, komisyon oranları 2.900/ay. 90. günde ilk 10'a girmek iddialı, kalabalık SERP. Hedef: ayda 1.500-4.000 organik ziyaret, araçtan e-posta bırakma %3-6, kayıt %1-2 | Geliştirme zamanı, 0 TL medya | GSC gösterim/tık/sıra, calculator_used, waitlist_joined, signup (utm_source=google, medium=organic) |
| B | Rehber kümesi (blog) | NetKâr sitesinde 4 küme: komisyon ve kesintiler, kargo-desi-iade, reklam ve ROAS, hakediş ve muhasebe. hyturkyilmaz.com'da kurucu bakışlı yorum yazıları ve NetKâr araçlarına bağlam içi bağlantı. | 0,25 | Taslak, iç bağlantı, şema, güncelleme. hyturkyilmaz.com mevcut günlük içerik otomasyonuna "e-ticaret kârlılığı" teması eklenir | Ayda 8 rehber (Hasan onaylı). Uzun vadeli, 90 günde sınırlı trafik | 0 TL | Organik oturum, rehber→araç tıklaması, rehber kaynaklı signup |
| C | LinkedIn kurucu içeriği | Haftada 3 gönderi: (1) gerçek hesap örneği "600 TL'lik ürün sana ne bırakıyor", (2) beta'dan anonim bulgu, (3) kurucu günlüğü. Ayda 1 karusel. Mevcut ağdaki marka, ajans ve ekosistem kişilerine kişisel DM. | 1,5 | Gönderi taslağı Hasan'ın sesinde, görsel/karusel üretimi, yorum özetleri, DM listesi hazırlama | 20-60 bekleme listesi/ay, 5-15 ortak adayı, 1-3 basın/podcast daveti | 0 TL | Gösterim, profil ziyareti, link tıklaması (utm_source=linkedin), DM→görüşme oranı |
| D | Topluluklar | Facebook satıcı grupları, Telegram/WhatsApp satıcı toplulukları, r10.net e-ticaret başlıkları (Trendyol komisyon başlıkları mevcut: R10.net, t.y.). Kural: önce soruya cevap, link yalnız izin verilirse. Ayda 1 "canlı kâr kliniği" (grup yöneticisi izniyle). | 0,75 | Hangi grupta hangi sorunun sorulduğunun izlenmesi (manuel dışa aktarılan içerikten), cevap taslakları | 30-80 bekleme listesi, 10-20 beta adayı | 0 TL | utm_source=facebook_grup / telegram / whatsapp / r10, grup bazında kayıt |
| E | Ortaklık (mali müşavir, eğitmen, entegratör, kargo/fulfillment) | Bölüm 4.4 | 1,0 | Aday listesi, kişiselleştirilmiş e-posta taslağı, ortak paneli raporları, ortak içerik kiti | 5-10 aktif ortak, ortak kaynaklı 15-30 kayıt | Komisyon (gelirden), 0 TL peşin | partner_id, ref kodu, ortak bazında MRR |
| F | Ürün içi viral döngüler | Kâr Karnesi görseli, rozetli PDF, iki taraflı davet ödülü, muhasebeci/ekip koltuğu (Bölüm 4.5) | 0 | Tamamen ürün içi | Kayıtların %10-20'si davet veya paylaşım kaynaklı | Davet ödülü maliyeti (1 ay ücretsiz) | report_shared, referral_invite_sent, referral_signup, viral katsayı |
| G | Bekleme listesi + Kurucu 50 | Hafta 1'de bekleme listesi, Hafta 4-9 kurucu üye programı (Bölüm 5) | (görüşmeler A satırında değil, 4.1'de) | Bekleme listesi skorlaması (sipariş hacmi, reklam kullanımı), e-posta dizisi | 50 kurucu üye, 30+ geri bildirim görüşmesi | Kurucu indirimi (gelir kaybı) | waitlist_joined, founder_applied, founder_activated |
| H | PR ve girişim platformları | Webrazzi girişim formu (yeni girişim incelemesi için form, haber için bulten@webrazzi.com) (Webrazzi, t.y.-a); Startups.watch profili; Product Hunt (yerel rakip KarPanel orada listelenmiş: Product Hunt, t.y.); e-ticaret podcast ve bültenleri | 0,25 (lansman haftası 1 saat) | Basın bülteni, Product Hunt metinleri, gazeteci listesi | 1-3 haber, Product Hunt'tan küçük ama nitelikli trafik (Türk satıcı kitlesi orada sınırlı, varsayım) | 0 TL | utm_source=webrazzi / producthunt, referans alan adları (backlink) |
| I | Etkinlikler | Ziyaretçi olarak katılım ve önceden ayarlanmış görüşmeler. Stand yok (bütçe). Takvim Bölüm 4.6 | Etkinlik haftası +2-3 saat (o hafta LinkedIn azaltılır) | Katılımcı ve konuşmacı listesi, takip e-postaları | Etkinlik başına 5-15 nitelikli temas | Ulaşım ve bilet (pazarlama bütçesinden değil, kurucu gideri) | Etkinlik kodu ile kayıt (utm_campaign) |
| J | E-posta ve yaşam döngüsü | Bekleme listesi dizisi, deneme onboarding (gün 0, 1, 3, 7, 12, 14), aylık "Kâr Bülteni" | 0 | Tamamen otomatik, metinleri Hasan bir kez onaylar | Deneme→ücretli dönüşümüne +2-5 puan katkı (varsayım) | E-posta aracı ücreti | Açılma, tıklama, aktivasyon adımı tamamlama |
| K | Kısa video (YouTube Shorts, Instagram Reels) | Ekran kaydı: "Bu ürün aslında zararda, şöyle anladım". Hasan'ın yüzü yalnız ayda 1-2 videoda. | 0 (ilk 90 gün düşük öncelik) | Senaryo, ekran kaydı kurgusu, altyazı | Belirsiz. SERP'te video sonuçları var (OpenSEO/DataForSEO, 2026), rakip Rexven video ile sıralanıyor | 0 TL | utm_source=youtube / instagram |
| L | Chrome eklentisi (6.-9. ay) | Satıcı panelinde ürün sayfasında net kâr gösteren eklenti. Rakipler: Rexven ücretsiz eklentisi, TPro360, Trendyol Profit Calculator. Helium 10'un ücretsiz eklentisi büyüme kapısı olarak kullanılıyor (Helium 10, t.y.-a). | 0 | Geliştirme | 90 gün kapsamı dışında | Geliştirme zamanı | Kurulum, aktif kullanıcı, eklentiden kayıt |

### 4.3 KPI tanımları ve hedefler

| KPI | Tanım | 90 gün hedefi (varsayım) | Not |
|---|---|---|---|
| Harcama | Kanal bazında TL (medya + sponsorluk + ödül maliyeti) | 0 TL medya | Ortak komisyonu ayrı satırda |
| CPA | Harcama / ödeyen müşteri (kayıt başı değil) | Ücretli test açılırsa 1.500 TL altı | Bölüm 7 |
| ROAS (NetKâr'ın kendi pazarlaması için) | İlk 3 ayın tahsil edilen geliri / harcama | Ücretli testte 1,0 üstü (3 ayda kendini çıkarma) | Kısa vadeli ölçüt, LTV ile birlikte okunur |
| CVR | Sayfa bazında: ziyaret→e-posta, ziyaret→kayıt | Araç sayfası e-posta %3-6, ana sayfa kayıt %2-4 | |
| Lead kalitesi | Skor: Trendyol satıcısı mı (+), aylık sipariş 100+ (+), reklam kullanıyor (+), API bağladı (++) | Kayıtların %50'si 2+ puan | Bekleme listesi formunda 3 soru |
| Aktivasyon | Kayıttan 48 saat içinde first_profit_view | %40+ | En kritik metrik |
| Deneme→ücretli | 14 gün içinde paid / trial_started | %12-20 | Kıyas: kartsız denemede medyan yaklaşık %4-6, üst çeyrek %10-15; kart istenen denemede "iyi" bant %25-35 (Userpilot, t.y.). Hedefimiz kartsız deneme için üst çeyreğin üstünde, çünkü API bağlama adımı zaten niyet filtresi gibi çalışıyor (varsayım) |
| Churn | Aylık iptal eden ödeyen mağaza / ay başı ödeyen | %5 altı | KOBİ SaaS için yaygın bant aylık %3-7 (UserJot, 2025); kaynaklar metodolojik olarak zayıf, yön göstericidir |
| MRR | Aylık tekrarlayan gelir, KDV hariç | 35-80 bin TL | |
| LTV / CAC | Brüt marj × ARPA / churn ÷ CAC | 3 üstü | Örnek: 650 TL × %80 brüt marj / %4 churn = 13.000 TL LTV (varsayımlar) |
| Geri ödeme süresi | CAC / (ARPA × brüt marj) | 6 ay altı | 6 ay için CAC tavanı yaklaşık 3.100 TL |

### 4.4 Ortaklık programı

**Neden:** Yurt dışı benzerler ortaklığı reklamın yerine kullanıyor. Sellerboard kendi blogunda ortaklarına %20 tekrarlayan komisyon ve ücretsiz katılım duyuruyor (Sellerboard, 2025). TrueProfit'in ortaklık sayfaları ilk ay için %50 veya %100 ve sonrasında %20 tekrarlayan komisyon ilan ediyor, sayfalar arasında koşullar çelişkili (TrueProfit, t.y.-a; TrueProfit, 2025). TrueProfit ayrıca mevcut müşterilere davet edilen arkadaşın ilk aboneliğinin %20'si kadar kredi, arkadaşa %20 indirim veriyor (TrueProfit, t.y.-b).

**NetKâr önerisi (varsayım, ilk 6 ay sonunda gözden geçirilir):**

| Ortak tipi | Havuz | Teklif | İlk adım |
|---|---|---|---|
| Mali müşavirler | TÜRMOB'a kayıtlı 136.685 meslek mensubu, bunların 59.958'i bağımsız çalışan SM/SMMM (Alomaliye, 2026). E-ticaret müşterisi olan oran bilinmiyor (varsayım). | Müşterilerine ücretsiz "muhasebeci koltuğu" (salt okuma), aylık PDF raporlar, getirdiği her ödeyen mağazadan 12 ay %25 komisyon veya kendi müşterilerine %10 indirim. Kendi ofisi için ücretsiz panel. | Hasan'ın ağındaki 10 e-ticaret odaklı müşavirle görüşme, 1 webinar ("Pazaryeri satıcısının hakedişini 15 dakikada kontrol etmek") |
| E-ticaret eğitmenleri ve akademiler | YouTube'da Trendyol eğitimi veren çok sayıda kanal var (ör. "A'dan Z'ye Trendyol Eğitimi" videoları) (YouTube, t.y.). Kanal listesinin büyüklüğü doğrulanmadı. | Öğrencilerine 30 gün deneme + %15 indirim kodu, eğitmene 12 ay %25 komisyon, derslerinde kullanacakları demo mağaza verisi | 15 eğitmen listesi, 5 görüşme, 2 ortak |
| Entegratörler | Pazaryeri entegrasyon firmaları (BirFatura, Sentos, Tam Entegre, Sopyo vb.) (KOBİTime, t.y.) | Rakip değil tamamlayıcı konumlama, karşılıklı listeleme, ortak webinar, gelir paylaşımı. Uzun vadede API ile veri alışverişi | 3 entegratörle görüşme, 1 ortak içerik |
| Kargo ve fulfillment | Kargo ve depo firmaları | Desi-kargo hesaplayıcısında "fulfillment teklifi al" bağlantısı karşılığında karşılıklı tanıtım | 6. aydan sonra |
| Ajanslar | Persona C | Ajans paketi, müşteri başına indirim, beyaz etiket rapor | Ajans paketi ile birlikte |

Kurallar: Ortaklara reklamda NetKâr marka kelimesine teklif vermek yasak. Ortak içeriklerinde "garanti kâr" gibi ifadeler yasak. Komisyon, müşteri ilk ödemeyi yapıp 14 gün iade süresi dolduktan sonra hak edilir.

### 4.5 Ürün içi viral döngüler

| Döngü | Nasıl çalışır | Gizlilik önlemi | Ölçüm |
|---|---|---|---|
| Aylık Kâr Karnesi | Her ayın 3'ünde (önceki ayın hakedişleri oturduktan sonra, varsayım) 1080×1350 görsel: net kâr marjı, en kârlı 3 ürün kategorisi, reklam verimliliği notu. Alt köşede "NetKâr ile hazırlandı" ve davet bağlantısı. Tek dokunuşla Instagram hikayesi, WhatsApp, LinkedIn. | Varsayılan olarak TL tutarı değil yüzde gösterilir. TL göstermek ayrı onay ister. Ürün adları gizlenebilir. | report_shared, paylaşım başına ziyaret, ref ile kayıt |
| Muhasebeci PDF raporu | Aylık PDF: hakediş mutabakatı, kesintiler, iade dökümü. Altbilgide "NetKâr ile hazırlandı" rozeti ve "Mali müşavirler için ücretsiz panel" bağlantısı. | Satıcı onayıyla gönderilir. | pdf_exported, muhasebeci daveti, müşavir kayıtları |
| Davet et, iki taraf kazansın | Davet edene 1 ay ücretsiz, gelene ilk ayda %20 indirim (TrueProfit modeline benzer). | Ödül ilk ödemeden sonra verilir. | referral_invite_sent, referral_signup, referral_paid |
| Ekip ve muhasebeci koltuğu | Salt okuma koltuk. Davet edilen kişi kendi mağazası için de NetKâr'ı görür. | Rol bazlı yetki. | seat_invited, seat_activated |
| Hesaplayıcı sonuç linki | Hesaplayıcı sonucu paylaşılabilir bağlantı olur (girdiler URL'de değil, kısa kod ile). | Kişisel veri yok. | calculator_result_shared |

### 4.6 Kanal ve etkinlik takvimi (2026-2027)

| Etkinlik | Tarih | Durum | NetKâr için anlamı |
|---|---|---|---|
| Türkiye E-Ticaret Haftası | 2025'te 21-22 Kasım, Lütfi Kırdar (Alomaliye, 2025). **2026 tarihi doğrulanamadı.** | Ticaret Bakanlığı, ETİD ve TOBB Türkiye E-Ticaret Meclisi katkısıyla | Kasım 2026'da yapılırsa ziyaretçi olarak katıl. Hafta 1'de tarih teyit edilmeli. |
| Oniki E-Ticaret ve E-İhracat Konferansı (ETİD) | 19 Ocak, Bursa. **Yıl doğrulanamadı** (Haberler.com, t.y.) | Hibrit, çevrimiçi katılım mümkün | 2027 ise Hafta 11'e denk gelir. Bursa ev tekstili ve üretici satıcılar Persona B ile örtüşüyor. |
| İstanbul Perakende Fuarı 2027 | 2-3 Haziran 2027, Haliç Kongre Merkezi (ExpoAssist, t.y.). Üçüncü taraf listesi, organizatörden teyit edilmeli. | E-ticaret yazılımı ve lojistik ürün grupları listelenmiş | 7. ayda ziyaretçi, entegratör ve kargo ortaklıkları için |
| İstanbul Küresel E-İhracat Zirvesi (IGEXX) | 2026'da 3-5 Eylül, Haliç Kongre Merkezi. TİM organizasyonu, ETİD iş birliği (Alomaliye, 2026b). 2027 tarihi yok. | 2026 edisyonu geçti | 2027'de global açılım hazırlığı için (10.-12. ay) |
| Webrazzi etkinlikleri | Webrazzi Fintech 2026: 9 Aralık 2026, İstanbul. Webrazzi'nin ayrı bir e-ticaret konferansı en son 2021'de görünüyor (Webrazzi, t.y.-b). | | Basın ilişkisi kurmak için opsiyonel |
| Trendyol İş Ortağı Buluşmaları ve Akademi | Trendyol iş ortağı buluşmaları ve canlı yayınlar düzenliyor, bir yılda 44 buluşmada 40 bin satıcıya ulaşıldığı belirtiliyor (Yeni Akit, t.y.). Akademi'de 300'e yakın ücretsiz eğitim (Habertürk, t.y.). 2026 takvimi bulunamadı. | Resmi kanal, üçüncü taraf ürün tanıtımına açık olduğu doğrulanmadı | İçerik konuları için izlenir. Trendyol'a "çözüm ortağı" başvuru yolu araştırılmalı (açık görev). |
| TOBB Türkiye E-Ticaret Meclisi | 2026 toplantı tarihi bulunamadı. Meclis 2016'da kuruldu, üyeleri e-ticaret firmaları, kamu kurumları ve dernekler (Alomaliye, 2016). | | Kamuoyu ve mevzuat takibi, doğrudan satış kanalı değil |

### 4.7 Topluluk kanallarına dair doğrulama notu

Facebook satıcı grupları, Telegram ve WhatsApp toplulukları için arama motorundan doğrulanabilir bir liste çıkmadı. Bu gruplar çoğunlukla kapalı olduğu için web aramasında görünmüyor. **Hafta 1 görevi:** Hasan, kendi hesabıyla "Trendyol satıcıları", "pazaryeri satıcıları", "e-ticaret girişimcileri" aramalarıyla 10 grup bulur, üye sayısını ve paylaşım kurallarını tabloya yazar. Ajan bu tabloyu takip listesine çevirir. Doğrulanmış açık alanlar: r10.net'te Trendyol komisyon ve mağaza açma başlıkları (R10.net, t.y.), Ekşi Sözlük'te "buybox" başlığı, Şikayetvar'da satıcı şikayetleri (OpenSEO/DataForSEO, 2026 SERP).

### 4.8 Yurt dışı benzerlerden reklamsız büyüme dersleri

| Şirket | Gözlenen taktik | Kaynak | NetKâr uyarlaması |
|---|---|---|---|
| Sellerboard | %20 tekrarlayan ömür boyu ortaklık komisyonu, ücretsiz katılım. Latka tahminine göre dış yatırım almadan büyümüş, küçük ekip (tahmini veri). | Sellerboard (2025); Latka (t.y.) | Ortaklık programı ilk günden. Küçük ekip modelinin mümkün olduğuna işaret (Latka verisi şirket beyanı değil). |
| Helium 10 | Ücretsiz Chrome eklentisi ve ücretsiz hesapla giriş, profitability calculator ücretsiz katmanda. Haftalık "Serious Sellers Podcast" ile içerik. Freedom Ticket eğitimi üyeliğe dahil. | Helium 10 (t.y.-a); Helium 10 (t.y.-b) | Hesaplayıcılar ve ileride eklenti. Eğitim içeriğini ürüne bağlamak: "Trendyol Kâr Okulu" mini e-posta kursu. |
| TrueProfit | Kalıcı ücretsiz plan yok, 14 gün deneme. Ücretsiz web hesaplayıcı. Shopify mağazasında yüksek puan ve çok sayıda yorum. Ortaklık ve müşteri davet programı ayrı. | Shopify App Store (t.y.-a); TrueProfit (t.y.-a, t.y.-b) | Deneme + ücretsiz araç + iki ayrı program (ortak ve müşteri daveti). Yorum toplama: Trendyol'da uygulama mağazası olmadığı için Google İşletme ve kendi vaka sayfası. |
| BeProfit | 2024'te ücretsiz planı kaldırdı, giriş planını 49 USD'ye çekti. Bu değişiklik olumsuz yorumlara yansıdı. | Shopify App Store (t.y.-b) | Sonra geri alınacak kalıcı ücretsiz plan açma. Ücretsiz değer araçlarda ve tek seferlik raporda kalsın. |
| HubSpot Website Grader | Ücretsiz analiz aracı, potansiyel müşteriyi niyetini göstererek getirir. HubSpot aracın yüz binlerce şirket tarafından kullanıldığını duyurdu. | HubSpot (t.y.) | "Kâr Röntgeni": API bağlamadan, Trendyol'dan indirilen Excel ile tek seferlik 30 günlük kâr analizi (ürün kapsamı kararına bağlı, varsayım). |
| KarPanel (Türkiye) | Product Hunt'ta listelenmiş Trendyol kâr analizi paneli | Product Hunt (t.y.) | Product Hunt yerel rakip tarafından da kullanılıyor, lansmanda düşük maliyetli bir adım. |

---

## 5) 90 günlük lansman takvimi

Varsayım: Trendyol bağlantısı, sipariş ve hakediş çekme, ürün bazında kâr ekranı Hafta 4'te kapalı betaya hazır. Hazır değilse Hafta 4-13 bloğu aynı sırayla kayar, ön lansman işleri değişmez.

| Hafta | Tarih | Aşama | İnsan işleri (≤5 saat) | Ajan işleri | Çıkış ölçütü |
|---|---|---|---|---|---|
| 1 | 9-15 Kas 2026 | Ön lansman | Bekleme listesi sayfası metnini onayla. 10 satıcı grubunu bul (4.7). LinkedIn'de "neden NetKâr" duyurusu. Türkiye E-Ticaret Haftası 2026 tarihini teyit et. | Bekleme listesi LP, 3 soruluk form, skorlama, UTM ve event kurulumu, komisyon hesaplayıcı v1 | LP canlı, ölçüm çalışıyor |
| 2 | 16-22 Kas | Ön lansman | 4 keşif görüşmesi (Excel nasıl tutuluyor, hakedişi nasıl kontrol ediyor). 2 LinkedIn gönderisi. | Net kâr hesaplayıcısı, "Trendyol komisyon oranları" sayfası, 4 rehber taslağı | 100 bekleme listesi |
| 3 | 23-29 Kas | Ön lansman (Kasım kampanya dönemi) | 4 görüşme. "Kasım'da gerçekte ne kazandınız? Aralık'ta birlikte bakalım" çağrısı. 5 mali müşavire mesaj. | Desi-kargo ve iade maliyeti hesaplayıcıları, e-posta dizisi | 200 bekleme listesi, 20 kurucu üye başvurusu |
| 4 | 30 Kas-6 Ara | Kurucu 50, dalga 1 | İlk 15 kurucu üye ile 20 dakikalık kurulum görüşmesi | Onboarding e-postaları, kurulum kontrol listesi, hata raporu toplama | 15 mağaza API bağlı |
| 5 | 7-13 Ara | Kurucu 50, dalga 2 | 15 kurucu üye daha. İlk "Kasım Kâr Karnesi" örneklerini (izinle, anonim) LinkedIn'de paylaş. | Kâr Karnesi v1, haftalık bulgu özeti | 30 mağaza bağlı, ilk anonim bulgular |
| 6 | 14-20 Ara | Kurucu 50, dalga 3 | Son 20 kurucu üye. 2 eğitmenle ortaklık görüşmesi. | Ortak kiti (tanıtım metni, ekran görüntüleri, kod), ortak takip paneli | 50 kurucu üye, 2 ortak sözlü onay |
| 7 | 21-27 Ara | Beta | 3 kurucu üyeyle derin geri bildirim. Mutabakat doğruluğu ölçümünü yayımla (Kanıt 1). | Başabaş ROAS hesaplayıcısı, mutabakat raporu, reklam uyarısı v1 | Aktivasyon oranı ölçülmüş |
| 8 | 28 Ara-3 Oca 2027 | Beta (yıl sonu) | Muhasebeci PDF raporunu 3 mali müşavirle test et. Daha az LinkedIn (tatil). | PDF rapor, muhasebeci koltuğu, yıl sonu rehberi ("2026 pazaryeri gelirini muhasebeciye hazırlamak") | 2 müşavir ortak adayı |
| 9 | 4-10 Oca | Beta, lansman hazırlığı | 2 isimli vaka çalışması (Kanıt 3) için görüşme. Basın listesini onayla. | Vaka sayfaları, basın bülteni, Product Hunt metinleri, fiyat sayfası, ödeme akışı testi | 2 vaka onaylı, fiyat sayfası canlı |
| 10 | 11-17 Oca | **Halka açık lansman** | Lansman günü LinkedIn gönderisi, ağdaki 30 kişiye kişisel mesaj, Webrazzi'ye bülten ve girişim formu, Product Hunt. 1 saat ek zaman. | Bekleme listesine dalgalı davet (her gün 100 kişi), lansman e-postaları, sosyal kanıt güncellemesi | 150 kayıt, 60 deneme başlatmış |
| 11 | 18-24 Oca | Ölçek | Oniki konferansı 2027'de ise katıl veya çevrimiçi izle. 2 ortak görüşmesi. | Deneme onboarding optimizasyonu, ilk A/B testi (LP başlığı) | Deneme→ücretli ilk kohort okuması |
| 12 | 25-31 Oca | Ölçek | İlk "canlı kâr kliniği" (bir satıcı grubunda, yöneticinin izniyle). 3 churn veya iptal görüşmesi. | Klinik kaydından kısa videolar, SSS güncellemesi | 1. kohort dönüşüm ve aktivasyon raporu |
| 13 | 1-7 Şub | Ölçek, değerlendirme | 90 gün değerlendirmesi: hangi kanal kayıt ve ödeyen getirdi. Bölüm 7 tetikleyicilerini kontrol et. | Kanal raporu, sonraki 90 günün içerik planı | Karar: ücretli test açılsın mı |

### Kurucu 50 programı

- **Kimler:** Aktif Trendyol satıcısı, aylık 200+ sipariş, tercihen reklam kullanan. Kategori çeşitliliği hedeflenir (en az 15 giyim, 10 ev-yaşam, 10 kozmetik ve kişisel bakım, 15 diğer, varsayım).
- **Ne alırlar:** İlk ay ücretsiz. Sonrasında abonelik kesintisiz sürdükçe Pro planda kurucu fiyatı (öneri 479 TL/ay, Pro'nun %40 altı). "Kurucu Üye" rozeti. Yol haritasına oy hakkı. Kurucu üye grubu (WhatsApp veya Telegram, Hasan ve destek ajanı).
- **Ne verirler:** 20 dakikalık kurulum görüşmesi, 2 geri bildirim görüşmesi, anonim veri kullanım izni (toplu istatistik için, ayrı açık rıza), en az 10'undan isimli vaka veya alıntı.
- **Neden 50:** Hasan'ın haftalık 1,5 saatlik görüşme bütçesiyle 3 haftada yönetilebilir sayı.

### 6-12 ay planı

| Ay | Odak | Ana işler | Hedef (varsayım) |
|---|---|---|---|
| 4 (Şubat-Mart 2027) | Elde tutma | Uyarıların isabetini artır, aylık Kâr Karnesi otomasyonu, churn görüşmeleri | Churn %5 altı |
| 4-5 | Hepsiburada | Hepsiburada entegrasyonu, "Hepsiburada komisyon hesaplama" sayfası (1.000 arama/ay) | Mevcut kullanıcıların %20'si ikinci mağaza bağlar |
| 5-6 | Ajans paketi | Çok mağazalı panel, beyaz etiket PDF, ajans ortaklık programı | 10 ajans |
| 6 | Ücretli test (koşullara bağlı) | Bölüm 7 | CPA 1.500 TL altı |
| 6-9 | Chrome eklentisi + mobil | Panel içi net kâr gösterimi, mobil push uyarılarını öne çıkarma | Eklentiden aylık 50+ kayıt |
| 7 | Etkinlik | İstanbul Perakende Fuarı 2027 ziyareti (tarih teyit edilecek) | 10 ortak teması |
| 7-9 | n11 ve Amazon TR | Entegrasyonlar, ilgili hesaplayıcılar ("n11 komisyon hesaplama" 140, "amazon komisyon hesaplama" 90 arama/ay) | Yeni pazar kayıtları |
| 9 | İçerik varlığı | "Türkiye Pazaryeri Satıcı Kârlılık Endeksi" (anonim, toplu, kullanıcı onaylı) ilk sayı, basına dağıtım | 3+ haber, 20+ referans alan adı |
| 10-12 | Global hazırlık | /en sayfaları, hreflang, IGEXX 2027 takibi, Türk satıcıların yurt dışı pazaryerleri için kâr ihtiyacının araştırılması | EN bekleme listesi |
| 12 (Kasım 2027) | Kampanya dönemi | Kasım 2027 için "kampanya öncesi zarar taraması" özelliği ve kampanyası | 250-350 ödeyen |

---

## 6) Fiyatlandırma ve paketleme önerisi

### 6.1 Rakip fiyat sinyalleri

| Ürün | Fiyat / deneme | Kaynak ve güvenilirlik |
|---|---|---|
| TrendHesap | 7 gün deneme, 399 TL/ay KDV dahil | Arama motoru özeti, sayfa doğrudan açılamadı |
| SellerIQ | 30 gün deneme, fiyat bulunamadı | Arama motoru özeti |
| Entegrify Profit | 7 gün kartsız deneme, fiyat bulunamadı, sayfa eski olabilir | Arama motoru özeti |
| Pazaryeri Komisyon | 3 gün deneme | Arama motoru özeti |
| Melontik | Fiyat bulunamadı | SERP açıklaması |
| TrueProfit (global) | Kalıcı ücretsiz plan yok, 14 gün deneme, planlar yaklaşık 35 USD'den 200 USD'ye | Shopify App Store (t.y.-a) ve üçüncü taraf listeleri |
| BeProfit (global) | 49 USD/ay'dan başlıyor, ücretsiz plan 2024'te kaldırıldı | Shopify App Store (t.y.-b) |

Yorum: Yerel fiyat çıpası 399 TL civarında görünüyor. Başlangıç 499 TL, en yakın rakibin üstünde. Bu fark ancak hakediş mutabakatı ve reklam uyarısı gibi görünür bir ek değerle savunulabilir. Fiyat testi önerisi aşağıda.

### 6.2 Paket önerisi (fiyatlar KDV hariç gösterilir, sayfada "KDV hariç" açıkça yazılır)

| Plan | Aylık | Yıllık (2 ay bedava, yaklaşık %17 indirim) | Kimin için | Limitler ve özellikler (varsayım) |
|---|---|---|---|---|
| Başlangıç | 499 TL | 4.990 TL | Persona A | 1 Trendyol mağazası, aylık 1.500 siparişe kadar, ürün bazında net kâr, hakediş mutabakatı, temel uyarılar, aylık Kâr Karnesi |
| Pro | 799 TL | 7.990 TL | Persona B | 2 mağaza, aylık 10.000 sipariş, reklam ve ROAS analizi, tüm uyarılar ve mobil push, AI müşteri sorusu taslakları (aylık kota), muhasebeci koltuğu ve PDF rapor, öncelikli destek |
| Ajans | 1.499 TL | 14.990 TL | Persona C | 5 mağaza dahil, ek mağaza 199 TL/ay, beyaz etiket PDF, müşteri bazlı erişim, ortaklık komisyonu |
| Ücretsiz araçlar | 0 TL | - | Herkes | Hesaplayıcılar, sonuç kaydetme, komisyon değişikliği e-posta uyarısı |

### 6.3 Deneme, kurucu fiyatı, indirimler

- **Deneme:** 14 gün, kart gerekmeden. Gerekçe: Başlangıçta hacim ve öğrenme önemli. Kartlı deneme daha yüksek dönüşüm oranı verir ama daha az kayıt getirir (Userpilot, t.y.). 6. ayda bir kohortla kartlı deneme A/B testi yapılabilir.
- **"İlk ay ücretsiz" seçeneği:** Yalnızca kurucu üyelere ve ortak kanalından gelenlere. Genel kullanıcıya 14 gün yeterli: Kasım hakedişi gibi bir aylık döngüyü görmek için 14 gün kısa kalırsa, API'den geçmiş 3 ay verisi çekilerek ilk günden geriye dönük rapor gösterilmelidir (ürün gereksinimi).
- **Kurucu fiyatı:** İlk 50 üye için Pro 479 TL/ay, abonelik sürdükçe sabit (enflasyon ayarlamasından muaf değil, sözleşmede yazılır).
- **Yıllık plan:** 2 ay bedava. Türkiye'de nakit akışı hassas KOBİ'ler için yıllık peşin ödeme zor olabilir (varsayım), bu nedenle 3 taksit seçeneği ödeme sağlayıcısıyla değerlendirilmeli.
- **Fiyat güncelleme:** Enflasyon ortamında yılda 1-2 kez fiyat güncellemesi gerekebilir (varsayım). Mevcut müşteriye en az 30 gün önceden bildirim. Fiyat sayfasında "son güncelleme tarihi".
- **Fiyat testi:** Lansmanda iki fiyat hücresi denenebilir (Başlangıç 449 / 499 TL) ancak az trafik nedeniyle istatistiksel olarak anlamlı sonuç 90 günde beklenmez (varsayım). Bunun yerine Van Westendorp tipi 4 soruluk fiyat anketi kurucu üyeler ve bekleme listesiyle yapılır.

### 6.4 Satışa engel olabilecek riskler

| Risk | Etki | Önlem |
|---|---|---|
| Güven: API anahtarı paylaşma kaygısı | Aktivasyon düşer | Salt okuma vurgusu, güvenlik sayfası, kurucu yüzü ve iletişim bilgisi, "bağlantıyı nasıl keserim" videosu, ilk kullanımda Excel ile dene seçeneği |
| Fiyat: 399 TL'lik rakip | Başlangıç planında kayıp | Değer farkını gösteren karşılaştırma, deneme sonunda "NetKâr bu mağazada şunları buldu" özeti |
| Veri doğruluğu: maliyet girdisi eksik | Yanlış kâr, güven kaybı | Ürün maliyeti toplu yükleme, eksik maliyet uyarısı, her rakamda kaynak etiketi |
| Trendyol API ve kural değişiklikleri | Özellik bozulur | Değişiklik izleme ajanı, durum sayfası. Finans servisinde tarih aralığı 15 gün ile sınırlı (Trendyol Developers, t.y.-a), toplu geçmiş veri çekimi buna göre tasarlanmalı |
| Trendyol'un kendi panelinde benzer özellik sunması | Değer önerisi zayıflar | Çok pazar yeri, muhasebeci ve ajans katmanı, uyarı ve mobil deneyim |
| Ödeme ve faturalama | Tahsilat kaybı | Tekrarlayan ödeme destekleyen yerli ödeme sağlayıcısı, e-fatura/e-arşiv entegrasyonu, başarısız ödeme e-posta dizisi |
| KVKK ve yurt dışı veri aktarımı | Hukuki risk, güven | Bölüm 9 |
| AI yanıt özelliğinin hatalı içerik üretmesi | Satıcının mağaza puanı zarar görür | Yalnız taslak, onaysız gönderim yok, yasaklı ifade filtresi |

---

## 7) Reklam tetikleyicileri

Ücretli test, aşağıdaki **tüm** koşullar art arda 2 haftalık ölçümde sağlanırsa açılır. Tavan ayda 5.000 TL'dir (ajans ücreti yok, kreatifler ajanlarla üretilir).

### 7.1 Açma koşulları

1. Aktivasyon (kayıttan 48 saat içinde first_profit_view) %40 veya üstü.
2. Son 2 deneme kohortunda deneme→ücretli %10 veya üstü.
3. Aylık logo churn %5 veya altı (en az 2 aylık veri).
4. Fiyat sayfasında en az 3 isimli vaka ve 10 alıntı.
5. Organik ve ortak kanallardan gelen ödeyen müşteri sayısı 50 veya üstü (böylece kayıt→ödeyen oranı güvenilir okunur).
6. Ücretli trafiğin ineceği sayfa (araç veya LP) ziyaret→e-posta veya kayıt dönüşümünde %3 veya üstü.
7. Çerez onayı ve dönüşüm ölçümü KVKK'ya uygun kurulu (onaysız piksel yok).

### 7.2 Hangi kanal, hangi sırayla

| Sıra | Kanal | Neden | Bütçe | Hedefleme |
|---|---|---|---|---|
| 1 | Google Arama | Niyet en yüksek. Tahmini TBM (CPC) düşük: "trendyol kar hesaplama" 0,35 USD, "trendyol komisyon hesaplama" 0,45 USD, "trendyol fiyat hesaplama" 0,73 USD, "roas hesaplama" 2,76 USD (OpenSEO/DataForSEO, 2026) | 3.000 TL/ay | Kâr ve kârlılık niyetli kelimeler, "program", "uygulama", "takip" ekleri. Rakip marka kelimelerine teklif yok (ilk testte). |
| 2 | Meta yeniden pazarlama | Hesaplayıcı kullanmış ama kayıt olmamış kişiler | 1.500 TL/ay | Yalnız çerez onayı vermiş ziyaretçiler, ekran kaydı kreatifleri |
| 3 | Eğitmen sponsorluğu | Sabit ücretli tek video veya bülten | 500-1.500 TL (tek seferlik, ay bütçesi içinde) | Ortaklık programına geçiş için test |
| Yok | LinkedIn reklamları | KOBİ satıcıyı hedeflemek için pahalı ve isabetsiz (varsayım) | 0 | Organik LinkedIn yeterli |

Kaba hesap (varsayım): 1 USD = 43 TL kabulüyle 0,45 USD TBM yaklaşık 19 TL eder, 3.000 TL yaklaşık 155 tık getirir. %5 kayıt ve %15 ödeyen dönüşümüyle ayda 1-2 ödeyen müşteri beklenir. Bu nedenle ücretli test bir büyüme motoru değil, hangi mesajın tıklandığını öğrenme aracıdır.

### 7.3 Durdurma kuralları

- 3.000 TL harcamadan sonra ödeyen müşteri başı CPA 1.500 TL'yi aşıyorsa kanal durdurulur.
- Kampanyadan gelen kayıtların aktivasyon oranı organik ortalamanın yarısının altındaysa durdurulur (yanlış kitle).
- Toplam aylık harcama hiçbir koşulda 5.000 TL'yi geçmez. Bütçe günlük limitle sınırlanır.

---

## 8) Ölçüm planı

### 8.1 İlkeler

- Event adları İngilizce, snake_case. Özellik değerleri küçük harf, Türkçe karakter yok.
- Analitik sistemine ad, e-posta, telefon, vergi numarası, API anahtarı gönderilmez. Kullanıcı ve mağaza kimlikleri iç kimlikle (UUID) gönderilir.
- Pazarlama çerezleri yalnız onay sonrası. Ürün içi zorunlu ölçüm, aydınlatma metninde açıklanır.
- Sunucu tarafı event'ler (paid, churn, api_connected) ödeme ve backend kaynaklıdır, istemci event'iyle çift sayılmaz.
- Araç önerisi (varsayım): PostHog AB bölgesi veya GA4 + sunucu tarafı event. Karar, veri yerleşimi kararına bağlıdır.

### 8.2 Event sözlüğü

Zorunlu altı event kalın yazılmıştır.

| Event | Tetiklendiği an | Kaynak | Zorunlu özellikler | Hangi KPI |
|---|---|---|---|---|
| page_view | Sayfa görüntüleme | İstemci | path, referrer, utm_* | Trafik |
| calculator_used | Hesaplayıcıda "hesapla" | İstemci | tool (komisyon, kar, desi, iade, roas), category | Araç kullanımı |
| calculator_result_saved | Sonucu e-postayla kaydetme | İstemci + sunucu | tool | Lead |
| calculator_result_shared | Sonuç linki paylaşımı | İstemci | tool, channel | Viral |
| waitlist_joined | Bekleme listesi formu | Sunucu | monthly_orders_band, uses_ads, marketplaces, lead_score, utm_* | Lead kalitesi |
| founder_applied | Kurucu üye başvurusu | Sunucu | lead_score | Program |
| **signup** | Hesap oluşturuldu | Sunucu | user_id, signup_method, utm_* (ilk dokunuş ve son dokunuş), referral_code, partner_id | Kayıt |
| email_verified | E-posta doğrulandı | Sunucu | user_id | Huni |
| api_connect_started | Bağlantı ekranı açıldı | İstemci | marketplace | Huni |
| **api_connected** | API bilgileri doğrulandı | Sunucu | store_id, marketplace, time_from_signup_min | Aktivasyon |
| api_connect_failed | Doğrulama hatası | Sunucu | marketplace, error_code | Hata |
| data_sync_completed | İlk veri çekimi bitti | Sunucu | store_id, orders_count, days_backfilled | Huni |
| cost_data_completed | Ürün maliyetlerinin en az %80'i girildi | Sunucu | store_id, coverage_pct | Doğruluk |
| **first_profit_view** | Kullanıcı ilk kez ürün bazında net kâr ekranını gördü | İstemci + sunucu doğrulama | store_id, time_from_signup_min, loss_products_count | Aktivasyon (kuzey yıldızı girdisi) |
| loss_alert_sent | "Zararına satış" veya "reklam kârı yiyor" uyarısı gönderildi | Sunucu | store_id, alert_type, channel (push, email) | Değer |
| alert_opened | Uyarı açıldı | İstemci | alert_type | Değer |
| settlement_reconciled | Hakediş dönemi mutabakatı tamamlandı | Sunucu | store_id, diff_pct_band | Kanıt 1 |
| ai_reply_drafted | AI yanıt taslağı oluşturuldu | Sunucu | store_id | Ek özellik |
| ai_reply_approved | Taslak onaylanıp gönderildi | Sunucu | edited (true/false) | Ek özellik kalitesi |
| report_shared | Kâr Karnesi paylaşıldı | İstemci | channel, shows_tl (true/false) | Viral |
| pdf_exported | Muhasebeci PDF'i oluşturuldu | Sunucu | recipient_type | Viral, ortak |
| seat_invited / seat_activated | Koltuk daveti | Sunucu | role | Genişleme |
| referral_invite_sent / referral_signup / referral_paid | Davet döngüsü | Sunucu | referral_code | Viral katsayı |
| **trial_started** | Deneme başladı (kayıtla aynı anda veya API bağlandığında, ürün kararına göre tek tanım seçilir) | Sunucu | plan, trial_length_days, card_required | Gelir hunisi |
| trial_ending_notice | Deneme bitimine 3 gün | Sunucu | plan | Huni |
| checkout_started | Ödeme sayfası | İstemci | plan, billing_period | Huni |
| **paid** | İlk başarılı ödeme | Sunucu (ödeme sağlayıcı webhook) | plan, billing_period, amount_try_ex_vat, discount_code, partner_id, founder (true/false) | Dönüşüm, MRR |
| plan_changed | Yükseltme / düşürme | Sunucu | from_plan, to_plan | Genişleme |
| payment_failed | Başarısız tahsilat | Sunucu | attempt | İstemsiz churn |
| **churn** | Abonelik dönemi sonunda yenilenmedi veya iptal edildi | Sunucu | plan, tenure_months, reason (çıkış anketi), voluntary (true/false) | Churn |
| reactivated | Geri dönüş | Sunucu | months_away | Geri kazanım |

Türetilmiş metrikler: Aktivasyon oranı = first_profit_view (48 saat) / signup. Deneme→ücretli = paid / trial_started (aynı kohort). Viral katsayı = referral_signup / aktif kullanıcı.

### 8.3 UTM sözlüğü

Kurallar: Hepsi küçük harf, Türkçe karakter yok, boşluk yerine alt çizgi. Kampanya adı `yyyymm_amac_konu` biçiminde.

| Parametre | İzin verilen değerler | Örnek |
|---|---|---|
| utm_source | google, bing, linkedin, youtube, instagram, facebook_grup, telegram, whatsapp, r10, newsletter, hyturkyilmaz, webrazzi, producthunt, startupswatch, partner_{kisa_ad}, event_{kisa_ad}, meta (ücretli), in_app | partner_ahmetsmmm |
| utm_medium | organic, organic_social, community, referral, partner, email, pr, event, in_product, cpc, paid_social, sponsorship | community |
| utm_campaign | yyyymm_amac_konu. Amaç: waitlist, founder50, launch, trial, karne, klinik, webinar, retarget | 202612_karne_kasim |
| utm_content | Kreatif veya varyant: post_{tarih}, video_{konu}, cta_{konum}, varyant_a/b | post_20261208 |
| utm_term | Yalnız ücretli arama kelimesi veya topluluk adı | trendyol_kar_hesaplama |
| ref | Ortak veya müşteri davet kodu (UTM'den bağımsız, 90 gün çerez, varsayım) | ref=MRT25 |

Örnek bağlantılar:

- LinkedIn gönderisi: `?utm_source=linkedin&utm_medium=organic_social&utm_campaign=202611_waitlist_kasim&utm_content=post_20261118`
- Mali müşavir ortak: `?utm_source=partner_ahmetsmmm&utm_medium=partner&utm_campaign=202612_founder50_muhasebe&ref=AHMET25`
- Ürün içi Kâr Karnesi: `?utm_source=in_app&utm_medium=in_product&utm_campaign=202612_karne_kasim&ref={kullanici_kodu}`

---

## 9) Riskler ve varsayımlar

### 9.1 Riskler

| Risk | Olasılık | Etki | Önlem | Sahip |
|---|---|---|---|---|
| SERP doygunluğu: hesaplayıcı sayfaları ilk sayfaya giremez | Yüksek | Orta | Farklılaşan araç (gerçek veriyle karşılaştırma, kategori bazlı oran tablosu, güncellik tarihi), kurucu otoritesi, ortak siteler ve basından bağlantı | Ajan + Hasan |
| AI Overview tıklamaları azaltır | Orta | Orta | Cevabı net veren, kaynaklı, güncel sayfalar ve marka bilinirliği (bkz. 06 belgesi GEO bölümü) | Ajan |
| Topluluklarda spam algısı | Orta | Yüksek | Önce cevap, link yalnız izinle, otomatik paylaşım yok | Hasan |
| Hasan'ın 5 saatinin aşılması | Orta | Yüksek | Etkinlik haftalarında LinkedIn azaltılır. Görüşmeler 20 dakika ile sınırlı | Hasan |
| Kurucu 50'nin 3 haftada dolmaması | Orta | Orta | Ortak kanalından ve LinkedIn DM'den doğrudan davet, programı 5 haftaya yayma | Hasan |
| Ürün hazır olmaması (Hafta 4) | Orta | Yüksek | Takvimin kaydırılması, bekleme listesine şeffaf tarih | Ürün |
| Trendyol API veya kural değişikliği, erişim kısıtı | Düşük-Orta | Yüksek | Resmi dokümantasyon izleme, entegrasyon referans kodunun gizli tutulması (Trendyol Developers, t.y.-a) | Ürün |
| KVKK: yurt dışında barındırma | Orta | Yüksek | 2024 değişikliğiyle yurt dışı aktarım yeterlilik kararı, uygun güvenceler (standart sözleşme vb.) veya istisnalara dayanıyor. Standart sözleşme imzadan sonra 5 iş günü içinde Kurum'a bildirilmeli (Erdem & Erdem, t.y.; KVKK, t.y.). Hukuk danışmanıyla barındırma kararı. | Hasan + hukuk |
| Karşılaştırma sayfalarında rakip markası kullanımı | Düşük | Orta | Yalnız doğrulanabilir, tarihli bilgiler, hukuki ön kontrol | Hasan + hukuk |
| Fiyat savaşı | Orta | Orta | Değer farkı, ajans ve muhasebeci katmanı | Hasan |
| Enflasyon ve kur | Yüksek | Orta | Fiyat güncelleme politikası, yıllık plan | Hasan |

### 9.2 Varsayımlar listesi (doğrulanmadı)

1. Hedef rakamlar (bekleme listesi, ödeyen, MRR) planlama hedefidir, sektör verisine dayanmaz.
2. ARPA yaklaşık 650 TL, brüt marj %80, aylık churn %4.
3. Segmentlerin sipariş hacmi sınırları ve kategori öncelikleri.
4. Giyimde iade oranının yüksek olduğu (Trendyol'a özel veri bulunamadı).
5. Trendyol panelinin ürün bazında reklam ve iade sonrası kârı tek ekranda göstermediği (Hasan'ın panelde teyidi gerekir).
6. Kanal bazında beklenen sonuç aralıkları.
7. 1 USD = 43 TL kur kabulü (yalnız Bölüm 7 kaba hesabı için).
8. Facebook, Telegram, WhatsApp satıcı topluluklarının varlığı ve büyüklüğü (web aramasıyla doğrulanamadı).
9. Türkiye E-Ticaret Haftası 2026 ve Oniki 2027 tarihleri.
10. Kâr Karnesi için hakedişlerin ayın 3'ünde oturduğu (hakediş takvimi teyit edilmeli).
11. Ödeme sağlayıcısının tekrarlayan ödeme ve taksit desteği.
12. AI müşteri sorusu özelliği için Trendyol soru-cevap servislerinin kullanılabilirliği (ürün dokümanında teyit edilmeli).

### 9.3 Açık görevler (Hafta 1-2)

- Türkiye E-Ticaret Haftası 2026 tarihini resmi kaynaktan teyit.
- 10 satıcı topluluğunun listesi (4.7).
- Rakiplerin (TrendHesap, Melontik, SellerIQ, Entegrify, KarPanel) fiyat ve özelliklerinin doğrudan siteden teyidi ve ekran görüntüsüyle arşivlenmesi.
- Trendyol'un üçüncü taraf uygulama veya çözüm ortağı programının olup olmadığının araştırılması.
- Barındırma ve KVKK kararı.

---

## Kaynaklar (APA 7)

Tüm web kaynaklarına erişim tarihi: 5 Kasım 2026. "t.y." tarih yok anlamındadır. Arama motoru özetinden alınan ve sayfası doğrudan açılamayan kaynaklar köşeli parantezle işaretlenmiştir.

Alomaliye. (2016, 25 Ekim). *e-Ticarette henüz yolun başındayız*. https://www.alomaliye.com/2016/10/25/e-ticarette-henuz-yolun-basindayiz/

Alomaliye. (2025, 21 Kasım). *Ticaret Bakanı Ömer Bolat'ın "Türkiye E-Ticaret Haftası" açılış konuşması*. https://www.alomaliye.com/2025/11/21/ticaret-bakani-omer-bolatin-turkiye-e-ticaret-haftasi-acilis-konusmasi/amp/

Alomaliye. (2026a, 29 Ocak). *SMMM ve YMM sayıları ve sorunları*. https://www.alomaliye.com/2026/01/29/smmm-ve-ymm-sayilari-ve-sorunlari/amp/

Alomaliye. (2026b, 7 Temmuz). *Küresel e-ihracat zirvesi için geri sayım*. https://www.alomaliye.com/2026/07/07/kuresel-e-ihracat-zirvesi-icin-geri-sayim/

Anadolu Ajansı. (t.y.). *Trendyol 2025 Sosyoekonomik Etki Raporu yayımlandı*. https://www.aa.com.tr/tr/isdunyasi/e-ticaret/trendyol-2025-sosyoekonomik-etki-raporu-yayimlandi/703357

Dünya. (2026). *Trendyol'dan Kasım ayı için rekor hedef: 1,5 milyar ziyaret, 120 milyon ürün*. https://www.dunya.com/sirketler/trendyoldan-kasim-ayi-icin-rekor-hedef-15-milyar-ziyaret-120-milyon-urun-haberi-845404

ecomcalctools. (t.y.). *Trendyol kâr hesaplama rehberi*. https://ecomcalctools.com/tr/blog/trendyol-kar-hesaplama/

[Entegrify. (t.y.). *Trendyol'da kâr zarar hesaplama*. https://entegrify.com/trendyolda-kar-zarar-hesaplama]

Erdem & Erdem. (t.y.). *Standart sözleşme bildirim modülü hakkında kamuoyu duyurusu*. https://www.erdem-erdem.av.tr/bilgi-bankasi/standart-sozlesme-bildirim-modulu-hakkinda-kamuoyu-duyurusu

ExpoAssist. (t.y.). *İstanbul Perakende Fuarı 2027*. https://expoassist.net/etkinlik/istanbul-perakende-fuari

Haberler.com. (t.y.). *ETİD'in yapay zeka destekli e-ticaret konferansı 19 Ocak'ta Bursa'da yapılacak*. https://www.haberler.com/etid-in-yapay-zeka-destekli-e-ticaret-konferansi-15550616-haberi/

Habertürk. (t.y.). *Dijital alışverişte yeni çözümlerin Türkiye ekonomisine katkısı*. https://www.haberturk.com/dijital-alisveriste-yeni-cozumlerin-turkiye-ekonomisine-katkisi-2983702-ekonomi

Helium 10. (t.y.-a). *How do I install and navigate the Chrome Extension? An introduction and overview*. https://kb.helium10.com/hc/en-us/articles/360049023813

Helium 10. (t.y.-b). *Serious Sellers Podcast: Learn how to sell on Amazon FBA & Walmart* [Podcast]. Apple Podcasts. https://podcasts.apple.com/podcast/id1453455876

Hepsiburada. (2025, 31 Temmuz). *Hepsiburada announces second quarter 2025 financial results* [Basın bülteni]. https://quantisnow.com/insight/hepsiburada-announces-second-quarter-2025-financial-results-6140354

HubSpot. (t.y.). *250,000 companies test their internet marketing acumen with Website Grader*. https://www.hubspot.com/blog/bid/4056/250-000-companies-test-their-internet-marketing-acumen-with-website-grader

KOBİTime. (t.y.). *Pazaryeri entegrasyon firmaları karşılaştırması 2026*. https://kobitime.com/pazaryeri-entegrasyon-firmalari-karsilastirmasi-2026/

KVKK. (t.y.). *Yurt dışına kişisel veri aktarımında kullanılacak standart sözleşmelerde dikkat edilmesi gereken hususlara ilişkin kamuoyu duyurusu*. Kişisel Verileri Koruma Kurumu. https://www.kvkk.gov.tr/Icerik/8170/Yurt-Disina-Kisisel-Veri-Aktariminda-Kullanilacak-Standart-Sozlesmelerde-Dikkat-Edilmesi-Gereken-Hususlara-Iliskin-Kamuoyu-Duyurusu

Latka. (t.y.). *SellerBoard revenue and company data*. https://getlatka.com/companies/sellerboard.com

[Melontik. (t.y.). *Trendyol ve Hepsiburada net kâr analizi*. https://melontik.com/]

OpenSEO / DataForSEO. (2026, 5 Kasım). *Anahtar kelime metrikleri (35 kelime) ve Google SERP okumaları (5 sorgu), Türkiye, Türkçe, masaüstü* [Yayımlanmamış veri seti, hyturkyilmaz.com projesi]. https://app.openseo.so/p/d90cd6a0-e282-4737-8d23-f23016fd6e8e/keywords

[Pazaryeri Komisyon. (t.y.). *Trendyol komisyon hesaplama*. https://pazaryerikomisyon.com/]

Product Hunt. (t.y.). *KarPanel*. https://www.producthunt.com/products/karpanel

R10.net. (t.y.). *Trendyol komisyon hesaplama* [Forum başlığı]. https://www.r10.net/off-topic/3939432-trendyol-komisyon-hesaplama.html

Rekabet Kurumu. (2024, 28 Kasım). *Investigation concerning DSM Grup Danışmanlık İletişim ve Satış Ticaret AŞ (Trendyol) concluded*. https://www.rekabet.gov.tr/en/Guncel/investigation-concerning-dsm-grup-danism-cfebfc2175adef1193d70050568585c9

[SellerIQ. (t.y.). *Trendyol satıcı kâr analiz paneli*. https://selleriq.co/]

Sellerboard. (2025, 16 Temmuz). *Why the sellerboard affiliate program is a smart move for passive income*. https://blog.sellerboard.com/2025/07/16/why-the-sellerboard-affiliate-program-is-a-smart-move-for-passive-income/

Shopify App Store. (t.y.-a). *TP: True Profit Analytics*. https://apps.shopify.com/trueprofit

Shopify App Store. (t.y.-b). *BeProfit: Profit Analytics, reviews*. https://apps.shopify.com/beprofit-profit-tracker/reviews

Şikayetvar. (t.y.-a). *Trendyol'da satıcı olmak pişmanlıktır, zararına satmaktır ve batmaktır*. https://www.sikayetvar.com/trendyol/trendyolda-satici-olmak-pismanliktir-zararina-satmaktir-ve-batmaktir

Şikayetvar. (t.y.-b). *Trendyol satıcı paneli reklam bakiye iadesi yapmıyorlar*. https://www.sikayetvar.com/trendyol/trendyol-satici-paneli-reklam-bakiye-iadesi-yapmiyorlar

Ticaret Bakanlığı. (2026). *Türkiye'de e-ticaret hacmi 2025'te 4,6 trilyon liraya ulaştı*. https://ticaret.gov.tr/haberler/turkiyede-e-ticaret-hacmi-2025te-4-6-trilyon-liraya-ulasti

Ticaret Bakanlığı. (2026, 12 Mayıs). *Türkiye'de e-ticaretin görünümü raporu yayınlandı*. https://ticaret.gov.tr/duyurular/turkiyede-e-ticaretin-gorunumu-raporu-yayinlandi-12-05-2026

[TrendHesap. (t.y.). *E-ticaret kâr ve finans analiz platformu*. https://trendhesap.net/]

Trendyol Developers. (t.y.-a). *Cari hesap ekstresi entegrasyonu*. https://developers.trendyol.com/docs/cari-hesap-ekstresi-entegrasyonu.md

Trendyol Developers. (t.y.-b). *Product buybox check*. https://developers.trendyol.com/tr/v3.0/docs/12-product-buybox-check

TrueProfit. (t.y.-a). *Affiliate program*. https://trueprofit.io/partner/affiliate-program

TrueProfit. (t.y.-b). *TrueProfit's referral program*. https://help.trueprofit.io/en/article/trueprofits-referral-program-o75ai2

TrueProfit. (2025). *New TrueProfit's affiliate program: Earn 20% recurring commission*. https://trueprofit.io/product-updates/new-trueprofits-affiliate-program-earn-20-recurring-commission

UserJot. (2025). *SaaS churn rate benchmarks: What's actually normal in 2025*. https://userjot.com/blog/saas-churn-rate-benchmarks

Userpilot. (t.y.). *What is a good free trial conversion rate in SaaS?* https://userpilot.com/blog/free-trial-conversion-rate/

Webrazzi. (2024, 23 Aralık). *E-ticarette stopaj oranı yüzde 1 olarak belirlendi*. https://webrazzi.com/2024/12/23/e-ticarette-stopaj-orani-yuzde-1-olarak-belirlendi/

Webrazzi. (t.y.-a). *Girişim formu*. https://webrazzi.com/girisim-formu/

Webrazzi. (t.y.-b). *Etkinlikler*. https://webrazzi.com/etkinlik

Yeni Akit. (t.y.). *Trendyol satıcılarını tüm gücüyle destekliyor*. https://www.yeniakit.com.tr/haber/trendyol-saticilarini-tum-gucuyle-destekliyor-1523165.html

YouTube. (t.y.). *Trendyol'da satışı adım adım anlattım! A'dan Z'ye Trendyol eğitimi (2 saat)* [Video]. https://www.youtube.com/watch?v=DFXhSGOWz4k
