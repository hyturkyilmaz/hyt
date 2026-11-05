# NetKâr: Web Sitesi ve Landing Page Planı

- Belge no: 06
- Sürüm: 1.0
- Hazırlanma ve erişim tarihi: 5 Kasım 2026
- Bağlı belge: 05_pazarlama_gtm.md (konumlandırma, persona, event ve UTM sözlüğü oradadır)
- Kapsam: Site haritası, sayfa bazında amaç, anahtar kelime kümesi, bölüm bölüm wireframe metni, dönüşüm hunisi, teknik SEO (Next.js), GEO, hız ve erişilebilirlik hedefleri.

## Okuma notu

- Arama hacimleri OpenSEO aracıyla (DataForSEO altyapısı, Türkiye, Türkçe, Google, 12 aylık ortalama tahmin) 5 Kasım 2026'da çekildi. Sayı yanında "/ay" yazanlar bu veridir. Veri dönmeyen kelimeler için **"hacim doğrulanmadı"** yazılmıştır.
- KD: anahtar kelime zorluğu (0-100). TBM: tıklama başı maliyet tahmini, USD.
- Site metinlerindeki rakamlar (fiyat, sayaç, vaka) örnektir. Canlıya çıkmadan önce gerçek veriyle değiştirilir. Uydurma sosyal kanıt kullanılmaz: gerçek sayı yoksa ilgili alan gizlenir.
- Alan adı henüz seçilmedi. Metinde yalnız yol (path) kullanıldı.

---

## 1) Site haritası

```
/                                   Ana sayfa
/fiyatlar                           Fiyatlar
/ozellikler                         Özellikler (hub)
  /ozellikler/urun-bazinda-net-kar
  /ozellikler/hakedis-mutabakati
  /ozellikler/reklam-ve-roas
  /ozellikler/uyarilar
  /ozellikler/ai-musteri-sorulari
  /ozellikler/mobil-uygulama
/araclar                            Ücretsiz araçlar (hub)
  /araclar/trendyol-komisyon-hesaplama
  /araclar/trendyol-kar-hesaplama
  /araclar/desi-kargo-hesaplama
  /araclar/iade-maliyeti-hesaplama
  /araclar/basabas-roas-hesaplama
  /araclar/hepsiburada-komisyon-hesaplama   (4.-5. ay)
  /araclar/n11-komisyon-hesaplama           (7.-9. ay)
  /araclar/amazon-komisyon-hesaplama        (7.-9. ay)
/trendyol-komisyon-oranlari         Güncel oran tablosu (veri sayfası)
/rehber                             Rehber (hub)
  /rehber/komisyon-ve-kesintiler/...
  /rehber/kargo-desi-iade/...
  /rehber/reklam-ve-roas/...
  /rehber/hakedis-ve-muhasebe/...
  /rehber/baslangic/...
/karsilastirma                      Karşılaştırmalar (hub)
  /karsilastirma/netkar-ve-excel
  /karsilastirma/netkar-ve-entegrator-raporlari
  /karsilastirma/netkar-ve-ucretsiz-hesaplayicilar
  /karsilastirma/{rakip}            (hukuki kontrol sonrası, 6. aydan itibaren)
/entegrasyonlar
  /entegrasyonlar/trendyol
  /entegrasyonlar/hepsiburada       (yakında, bekleme listesi)
/guvenlik                           Güvenlik ve veri
/kvkk-aydinlatma-metni
/gizlilik-politikasi
/cerez-politikasi
/kullanim-kosullari
/abonelik-sozlesmesi                (mesafeli sözleşme ve iptal koşulları)
/sss
/kurucu-uyelik                      Bekleme listesi + Kurucu 50
/ortaklik                           Ortaklık programı (hub)
  /ortaklik/mali-musavirler
  /ortaklik/ajanslar
  /ortaklik/egitmenler
/vaka-calismalari
/hakkimizda                         Kurucu ve şirket
/kayit
/giris
/durum                              Servis ve entegrasyon durumu
/en/...                             İngilizce (10.-12. ay, şimdiden yapı hazır)
```

Gezinme (üst menü): Özellikler, Ücretsiz araçlar, Fiyatlar, Rehber, Güvenlik. Sağda: Giriş, "14 gün ücretsiz dene" düğmesi.
Alt bilgi: tüm yasal sayfalar, ortaklık, durum sayfası, iletişim, kurucunun LinkedIn bağlantısı.

---

## 2) Metin ilkeleri

- Ses: Bir e-ticaret danışmanının satıcıyla masada konuşması gibi. Kısa cümle, somut rakam, sen dili (kurumsal sayfalarda siz dili; seçim tek bir kez yapılır ve tüm sitede tutarlı uygulanır. Öneri: **siz**, çünkü Persona B ve muhasebeciler de okuyor).
- Kullanılmayacaklar: "garanti", "kesin", "%100 doğru", "devrim", "sihirli", "bir sonraki seviyeye taşıyın", "hızla değişen dünyada", "sadece bir araç değil", "keşfedin" ile başlayan başlıklar, art arda üçlü sıfat dizileri.
- Her rakamın kaynağı yazılır: "Trendyol ekstresinden" veya "sizin girdiğiniz maliyetten".
- Her sayfanın üstünde değil altında "Son güncelleme: gg.aa.yyyy" yer alır (oran ve mevzuat sayfalarında üstte).
- Türkçe sayı biçimi: 1.234,56 TL. Girdi alanları hem virgül hem nokta ondalığı kabul eder.

---

## 3) Sayfa bazında plan

Her sayfa için: amaç, hedef anahtar kelime kümesi, bölüm bölüm wireframe (başlık, alt başlık, CTA, sosyal kanıt yeri) ve notlar.

### 3.1 Ana sayfa `/`

**Amaç:** Trendyol satıcısına 5 saniyede ne yaptığımızı anlatmak, deneme başlatmak veya ücretsiz araca yönlendirmek.
**Birincil dönüşüm:** signup (deneme). İkincil: calculator_used, waitlist_joined (lansman öncesi).
**Anahtar kelimeler:** Marka aramaları. "trendyol kâr analizi programı", "trendyol kâr takip uygulaması", "pazaryeri kârlılık analizi" (hacim doğrulanmadı). "e-ticaret kar hesaplama" 90/ay, KD 0.

| Bölüm | İçerik |
|---|---|
| 1. Hero | **H1:** Cironuzu değil, cebinize kalanı görün. **Alt başlık:** Trendyol mağazanızı salt okuma bağlantısıyla bağlayın. Her ürünün komisyon, KDV, kargo, iade ve reklam sonrası net kârını, hakediş ekstrenizle eşleşmiş olarak görün. **CTA 1:** 14 gün ücretsiz deneyin (kart gerekmez). **CTA 2 (metin bağlantı):** Önce ücretsiz kâr hesaplayıcısını deneyin. **Güven satırı:** Salt okuma bağlantı. Bağlantıyı istediğiniz an kesersiniz. KVKK aydınlatma metni. **Görsel:** Ürün listesi ekranı, kırmızı işaretli 2 zararlı ürün, köşede "örnek veri" etiketi. |
| 2. Sorun | **H2:** Satış artıyor ama hesaba yatan tutar aynı kalıyor mu? Üç kart: (1) "Komisyonun KDV'si, hizmet bedeli ve stopaj ayrı ayrı kesiliyor." (2) "İade gelen siparişin kargosu iki kez ödeniyor." (3) "Reklam satış getiriyor, ama hangi ürünün kârını yediği görünmüyor." |
| 3. Nasıl çalışır | **H2:** Üç adımda ilk raporunuz. (1) Trendyol panelinden API bilgilerinizi kopyalayın, (2) ürün maliyetlerinizi Excel ile yükleyin veya tek tek girin, (3) geçmiş 3 ayın ürün bazında net kârını görün. Alt satır: Kurulum çoğu mağazada 10-15 dakika sürer (beta ortalamasıyla güncellenecek, şimdilik varsayım). |
| 4. Özellikler | 4 blok, her biri bir alt sayfaya bağlı: Ürün bazında net kâr / Hakediş mutabakatı / Reklam ve ROAS / Uyarılar ve mobil bildirim. Ek satır: Müşteri sorularına AI yanıt taslağı (siz onaylamadan gönderilmez). |
| 5. Sosyal kanıt | **Yer tutucu:** 3 kurucu üye alıntısı (ad, mağaza kategorisi, fotoğraf, izinli). Sayaç "Bağlı mağaza: X" yalnız X ≥ 100 olduğunda gösterilir. Vaka bağlantısı: "Bir ev tekstili satıcısı 14 ürünün reklamını neden durdurdu?" (gerçek vaka gelince). Lansman öncesi bu bölüm yerine "Kurucu 50 programı" kutusu. |
| 6. Ücretsiz araçlar şeridi | **H2:** Hesap yapmak için kayıt gerekmez. 5 araç kartı. |
| 7. Güvenlik özeti | **H2:** Verileriniz nasıl korunuyor? 4 madde: salt okuma, şifreli saklama, bağlantıyı kesme, KVKK. **CTA:** Güvenlik sayfası. |
| 8. Fiyat özeti | 3 plan, "14 gün ücretsiz, kart gerekmez". **CTA:** Fiyatları inceleyin. |
| 9. Kurucu notu | Hasan'ın fotoğrafı ve 3-4 cümle: kim olduğu, neden yaptığı, iletişim (LinkedIn). Bu bölüm güven için önemli: ürünün arkasında görünür bir insan var. |
| 10. Kısa SSS | 5 soru: Bağlantı güvenli mi? Entegratörümle çalışır mı? Rakamlar muhasebemle tutar mı? Hepsiburada var mı? İptal nasıl? |
| 11. Son CTA | **H2:** Geçen ay gerçekte ne kazandığınızı görün. **CTA:** 14 gün ücretsiz deneyin. |

### 3.2 Fiyatlar `/fiyatlar`

**Amaç:** Plan seçtirmek, itirazları kapatmak.
**Anahtar kelimeler:** "trendyol kâr analizi fiyat", "netkar fiyat" (hacim doğrulanmadı, marka sonrası).

| Bölüm | İçerik |
|---|---|
| Başlık | **H1:** Mağazanızın büyüklüğüne göre plan seçin. **Alt:** Tüm planlar 14 gün ücretsiz. Kart gerekmez. Fiyatlar KDV hariçtir. |
| Dönem anahtarı | Aylık / Yıllık (2 ay bedava) |
| Plan kartları | Başlangıç 499 TL, Pro 799 TL (önerilen etiketi), Ajans 1.499 TL. Her kartta: kimin için (tek cümle), sipariş ve mağaza limiti, 5-6 özellik, CTA "Ücretsiz deneyin". (Fiyatlar 05 belgesindeki öneridir, araştırma sonrası değişebilir.) |
| Kurucu fiyatı kutusu | Lansman öncesi: "İlk 50 kurucu üyeye Pro planı 479 TL/ay. Kalan yer: X" (gerçek sayı). |
| Karşılaştırma tablosu | Tüm özellikler satır satır. |
| Sosyal kanıt yeri | Plan kartlarının hemen altında 2 alıntı (biri Başlangıç, biri Pro kullanıcısı). |
| Fiyat SSS | Deneme bitince ne olur? Sipariş limitini aşarsam? Fatura (e-fatura/e-arşiv)? İptal ve iade? Fiyat artışı politikası (30 gün önceden bildirim)? Muhasebecim ücretsiz erişebilir mi? |
| Son CTA | 14 gün ücretsiz deneyin. Alt satır: "Ajans mısınız? Ortaklık programına bakın." |

### 3.3 Özellikler hub `/ozellikler` ve alt sayfalar

**Amaç:** Her özellik için ayrı niyet ve ayrı ekran görüntüsü. Alt sayfalar uzun kuyruk ve karşılaştırma aramalarını karşılar.

| Alt sayfa | H1 önerisi | Alt başlık | Anahtar kelimeler | Sosyal kanıt yeri | CTA |
|---|---|---|---|---|---|
| urun-bazinda-net-kar | Her ürünün size ne bıraktığını görün | Komisyon, komisyon KDV'si, hizmet bedeli, stopaj, kargo, iade ve reklam düşüldükten sonra kalan tutar, ürün ve sipariş bazında. | "trendyol kar marjı hesaplama" (hacim doğrulanmadı), "kar marjı hesaplama" 1.000/ay KD 0 | Ekranın altında 1 alıntı | Ücretsiz deneyin |
| hakedis-mutabakati | Hakedişinizi siparişlerinizle satır satır eşleştirin | Trendyol'un cari hesap ekstresi ve finans servislerinden gelen satış, iade, kupon ve komisyon kalemlerini siparişe bağlıyoruz. Tutmayanları ayrı listeliyoruz. | "trendyol hakediş" (hacim doğrulanmadı), "trendyol hakediş hesaplama" (hacim doğrulanmadı) | Mutabakat doğruluğu ölçümü (Kanıt 1, beta sonrası) | Ücretsiz deneyin |
| reklam-ve-roas | Reklam hangi üründe kâr getiriyor, hangisinde yiyor? | Her ürün için başabaş ROAS'ı hesaplıyor, reklam sonrası net kârı gösteriyoruz. | "trendyol reklam" 720/ay KD 9, "roas hesaplama" 170/ay | Vaka bağlantısı | Ücretsiz deneyin + Başabaş ROAS aracı |
| uyarilar | Zarar başladığında haber alın | Zararına satış, beklenenden düşük hakediş, komisyon değişikliği ve reklam uyarıları telefonunuza ve e-postanıza gelir. | Hacim doğrulanmadı | Uyarı ekran görüntüsü | Ücretsiz deneyin |
| ai-musteri-sorulari | Müşteri sorularına yanıt taslağı, onay sizde | Ürün bilgilerinize göre taslak hazırlanır. Siz okuyup onaylamadan hiçbir cevap gönderilmez. | "trendyol müşteri soruları" (hacim doğrulanmadı) | Yok (beta sonrası) | Pro planı inceleyin |
| mobil-uygulama | Kârınız cebinizde | Günlük net kâr özeti ve uyarılar iOS ve Android uygulamasında. | Marka + "uygulama" | Mağaza puanı (gerçek olduğunda) | Uygulamayı indirin |

### 3.4 Ücretsiz araçlar

Ortak ilkeler:
- Araç sayfa yüklenir yüklenmez çalışır, kayıt istemez. Sonuç alanının yüksekliği baştan ayrılır (CLS).
- Sayfa sunucuda örnek değerlerle hazır gelir (ör. 600 TL satış, %21 komisyon, 3 desi). Böylece sayfa içeriği ve örnek sonuç arama motoruna görünür.
- Sonuçtan sonra iki adım: (1) "Bu hesabı e-postama gönder" (calculator_result_saved, e-posta toplar, ileride oran değişikliğinde haber verilir), (2) "Gerçek rakamlarınız bu tahmine ne kadar yakın? Mağazanızı bağlayın, geçen ayı görün" (signup).
- Her araçta formül açıkça yazılır, örnek hesap adım adım gösterilir, kaynaklar ve "son güncelleme" tarihi verilir.
- Kaynaklar arasında komisyonun KDV dahil mi hariç fiyata uygulandığı konusunda çelişki var (SERP'teki rehberler farklı formül veriyor). Araç, Trendyol'un resmi kesinti dokümanı ve gerçek ekstre satırlarıyla doğrulanmadan yayımlanmamalı. Doğrulanana kadar "nasıl hesapladık" kutusunda varsayım açıkça yazılır.

#### 3.4.1 `/araclar/trendyol-komisyon-hesaplama`

- **Amaç:** En yüksek hacimli ticari bilgi araması, giriş kapısı.
- **Anahtar kelime kümesi:** "trendyol komisyon hesaplama" 18.100/ay, KD 0, TBM 0,45. "trendyol fiyat hesaplama" 720/ay. "pazaryeri komisyon hesaplama" 170/ay. "trendyol hizmet bedeli" 110/ay. "trendyol komisyon kdv" (hacim doğrulanmadı).
- **SERP durumu (5 Kasım 2026):** İlk sırada rexven.com (ücretsiz eklenti), sonra malidigital.com.tr, faturaport.com, gelirebak.com, beekod.com, melontik.com, sentos.com.tr, a2adijital.com, parasut.com. AI Overview ve video sonuçları var. Rekabet içerik kalitesinde değil, güncellik ve güvenilirlikte kazanılır.

| Bölüm | İçerik |
|---|---|
| Başlık | **H1:** Trendyol komisyon hesaplama (2026). **Alt:** Kategori ve satış fiyatını girin. Komisyonu, komisyon KDV'sini, hizmet bedelini ve stopajı ayrı ayrı görün. |
| Araç | Alanlar: kategori (açılır liste, oranlar /trendyol-komisyon-oranlari sayfasından), KDV dahil satış fiyatı, ürün KDV oranı, kargo (opsiyonel, desi aracına bağlantı). Sonuç: kesinti kalemleri tablosu ve "hesabınıza geçecek tutar". |
| Kısa cevap (GEO) | 2-3 cümle: "Trendyol komisyonu kategoriye göre değişen bir oranla hesaplanır. Komisyona ayrıca KDV eklenir. Bunlara platform hizmet bedeli ve %1 e-ticaret stopajı eklenince satıcının eline geçen tutar bulunur." (Stopaj kaynağı: 1 Ocak 2025'ten beri %1, Webrazzi, 2024.) |
| Formül ve örnek | Adım adım örnek hesap, her satırda kaynak. |
| Sonraki adım CTA | "Bu bir tahmin. Gerçek kesintileriniz hakediş ekstrenizde. Mağazanızı bağlayın, geçen ayın gerçek komisyonunu ürün bazında görün." **CTA:** 14 gün ücretsiz deneyin. |
| Sosyal kanıt yeri | CTA kutusunun içinde 1 kısa alıntı. |
| İlgili araçlar ve rehberler | Kâr hesaplama, desi, komisyon oranları tablosu, "komisyon KDV'si nasıl hesaplanır" rehberi. |
| SSS (görünür) | 4-5 soru. Ör. "Kampanya indirimi komisyonu nasıl etkiler?", "İade olunca komisyon geri gelir mi?" (bir rehber iade onaylanınca komisyonun satıcıya otomatik döndüğünü yazıyor, Trendyol kaynağıyla teyit edilmeli: BirFatura, t.y.). |

#### 3.4.2 `/araclar/trendyol-kar-hesaplama`

- **Amaç:** Tam net kâr hesabı (reklam ve iade dahil). Ürünün ana vaadine en yakın araç.
- **Anahtar kelime kümesi:** "trendyol kar hesaplama" / "trendyol kâr hesaplama" 6.600/ay (aynı küme), KD 0, TBM 0,35. "kar marjı hesaplama" 1.000/ay. "e-ticaret kar hesaplama" 90/ay. "başabaş noktası hesaplama" 70/ay.
- **Komisyon aracından ayrışma:** Komisyon aracı "kesinti" niyetini, bu araç "net kâr ve başabaş fiyatı" niyetini karşılar. İki sayfa birbirine bağlanır, başlık ve içerik ayrışır (yamyamlaşmayı önlemek için).
- **SERP durumu:** jetstok.com, hoays.com, clickzone.io, birfatura.com, balpdijital.com, faturaport.com, melontik.com, zunapro.com. Rexven'in YouTube videosu da sıralanıyor.

| Bölüm | İçerik |
|---|---|
| Başlık | **H1:** Trendyol kâr hesaplama: reklam ve iade dahil net kâr. **Alt:** Ürün maliyeti, komisyon, kargo, iade payı ve reklam harcamasını girin, ürün başına net kârı ve başabaş fiyatını görün. |
| Araç | Alanlar: satış fiyatı, alış maliyeti, kategori, desi veya kargo tutarı, iade oranı (%), reklam: "sipariş başı reklam maliyeti" veya "ROAS". Sonuç: net kâr (TL ve %), başabaş satış fiyatı, başabaş ROAS. |
| Kısa cevap | "Net kâr = satış fiyatı − (alış maliyeti + komisyon + komisyon KDV'si + hizmet bedeli + kargo + iade payı + reklam + stopaj). İade payı için geçmiş iade zararınızı sipariş sayısına bölmek pratik bir yöntemdir." (ecomcalctools, t.y.) |
| CTA | "Tek ürün için hesap kolay. 300 ürün için her ay? Mağazanızı bağlayın, hepsini otomatik görün." |
| Sosyal kanıt yeri | CTA kutusu içinde |
| İndirilebilir | "Excel şablonu" (e-posta karşılığı). Şablonun son sekmesinde NetKâr tanıtımı. |

#### 3.4.3 `/araclar/desi-kargo-hesaplama`

- **Amaç:** Çok yüksek hacimli ama genel (kargo herkes için) bir arama. Satıcı olmayan trafik de gelir. Lead kalitesi düşük olabilir, marka bilinirliği ve bağlantı kazanımı için.
- **Anahtar kelime kümesi:** "desi hesaplama" 14.800/ay, KD 0. "trendyol kargo ücretleri" 720/ay. "trendyol kargo hesaplama" 170/ay. "trendyol desi hesaplama" 110/ay. "hepsiburada kargo hesaplama" 10/ay.
- **SERP durumu:** kargopek.com, satisortagim.koctas.com.tr, tsoft.com.tr, worgoo.com, lonca.com, bilirhesap.com, desi.hesaplama.net vb. Hesaplama siteleri ve kargo firmaları baskın.

| Bölüm | İçerik |
|---|---|
| Başlık | **H1:** Desi hesaplama ve Trendyol kargo maliyeti. **Alt:** Koli ölçülerini girin, desiyi ve yaklaşık kargo maliyetini görün. Ağırlık desiden fazlaysa hangisinin geçerli olduğunu gösteririz. |
| Araç | En, boy, yükseklik (cm), ağırlık (kg), yurt içi/yurt dışı bölen seçimi. Sonuç: desi, ücretlendirmeye esas değer. "Trendyol anlaşmalı kargo tarifesiyle yaklaşık maliyet" alanı yalnız güncel tarife doğrulandıysa gösterilir. |
| Kısa cevap | "Yurt içi kargoda desi = en × boy × yükseklik (cm) ÷ 3.000. Yurt dışında bölen genellikle 5.000'dir. Kargo firması desi ile gerçek ağırlıktan büyük olanı esas alır." (Faturaport, t.y.; Paraşüt, t.y.) |
| İpucu bloğu | "Koliniz 1 cm küçülürse ne değişir?" küçük hesap tablosu (özgün içerik). |
| CTA | Satıcıya yönelik: "Kargo kâr marjınızın ne kadarını yiyor? Ürün bazında görün." Satıcı olmayan ziyaretçi için ikincil bir şey önerilmez. |
| Sosyal kanıt yeri | Yok (sade araç sayfası) |

#### 3.4.4 `/araclar/iade-maliyeti-hesaplama`

- **Amaç:** Rakip araçlarda nadir olan bir hesap. Giyim satıcısına doğrudan dokunur.
- **Anahtar kelime kümesi:** "trendyol iade kargo ücreti" 50/ay. "iade maliyeti hesaplama" (hacim doğrulanmadı). Not: "trendyol iade" 2.400/ay ama ağırlıkla tüketici niyetli (navigasyonel), hedeflenmez.
- **SERP durumu:** Aramada özel bir Trendyol iade maliyeti hesaplayıcısı bulunamadı. Fırsat.

| Bölüm | İçerik |
|---|---|
| Başlık | **H1:** İade maliyeti hesaplama: bir iade size gerçekte kaça mal oluyor? **Alt:** Gidiş ve dönüş kargosu, paketleme, satılamaz hale gelen ürün payı ve iade oranınızla sipariş başı gizli maliyeti görün. |
| Araç | Alanlar: aylık sipariş, iade oranı, gidiş kargo, dönüş kargo, paketleme, hasarlı/satılamaz oranı, ürün maliyeti. Sonuç: aylık iade maliyeti, sipariş başı iade payı, bu payın net kâra etkisi. |
| Kısa cevap | Formül ve 1 örnek. Komisyonun iade sonrası geri dönüp dönmediği ayrı bir notta, kaynakla. |
| CTA | "Hangi ürününüz en çok iade alıyor ve bu ona kaça mal oluyor? Mağazanızı bağlayın." |

#### 3.4.5 `/araclar/basabas-roas-hesaplama`

- **Amaç:** "Reklam kârı yiyor" mesajını araçla somutlaştırmak.
- **Anahtar kelime kümesi:** "roas hesaplama" 170/ay, KD 0, TBM 2,76 (reklam verenler için değerli). "trendyol reklam" 720/ay. "başabaş roas" (hacim doğrulanmadı).
- **Rakip:** magazadanismani.com.tr ücretsiz başabaş ROAS hesaplayıcısı sunuyor (arama özeti).

| Bölüm | İçerik |
|---|---|
| Başlık | **H1:** Başabaş ROAS hesaplama: reklamınız hangi noktadan sonra kâr ettiriyor? **Alt:** Ürünün reklam öncesi kâr marjını girin, zarar etmemek için gereken en düşük ROAS'ı görün. |
| Araç | Satış fiyatı, reklam öncesi net kâr (veya kâr aracından aktar), mevcut ROAS. Sonuç: başabaş ROAS, mevcut ROAS ile fark, "her 100 TL reklamda kalan/kaybedilen". |
| Kısa cevap | "Başabaş ROAS = 1 ÷ reklam öncesi kâr marjı. Marjınız %20 ise reklamdan en az 5 kat ciro gelmeli." |
| CTA | "Bu hesabı her ürün için her gün yapıyoruz ve eşik aşılınca haber veriyoruz." |

### 3.5 Trendyol komisyon oranları sayfası `/trendyol-komisyon-oranlari`

- **Amaç:** Sürekli güncellenen veri sayfası. Bağlantı mıknatısı ve araçların veri kaynağı.
- **Anahtar kelime kümesi:** "trendyol komisyon oranları" 2.900/ay, KD 0, TBM 0,43. Kategori uzun kuyrukları ("trendyol giyim komisyon oranı" vb., hacim doğrulanmadı).
- **SERP durumu:** faturaport.com, hesapbilir.com, sopyo.com, qukasoft.com, pixasoftware.com, stockmount.com, tsoft.com.tr. SERP'teki sayfalar aynı kategori için farklı oranlar veriyor (ör. giyim için %15-20, %17-20, %21,50). Güvenilir ve kaynaklı tek tablo farklılaştırır.
- **Wireframe:** H1 "Trendyol komisyon oranları (güncelleme: gg.aa.yyyy)". Alt: "Kategori bazında oranlar, kaynak ve son değişiklik tarihleriyle." Tablo (filtrelenebilir). "Değişiklik geçmişi" bölümü. "Oran değişince e-posta alın" (e-posta toplama). CTA: komisyon aracı.
- **Not:** Oranların kaynağı Trendyol satıcı paneli veya resmi duyurudur. Kaynak gösterilemeyen oran yayımlanmaz. Kategori alt sayfaları ancak her biri özgün bilgi (oran geçmişi, kategoriye özel kargo ve iade notları) taşıyorsa açılır. Aksi halde Google'ın ölçekli içerik kötüye kullanımı politikası riski doğar (Google Search Central, t.y.-b).

### 3.6 Rehber kümesi `/rehber`

**Amaç:** Konu otoritesi, araçlara iç bağlantı, AI aramalarında kaynak gösterilme.
Yayın ritmi: ayda 8 rehber (05 belgesi). Her rehber ajan taslağıdır, Hasan uzman notu ekler ve onaylar. Yazar kutusu Hasan.

| Küme (pillar) | Pillar sayfa | Küme yazıları (örnek) | Hacim verisi |
|---|---|---|---|
| Komisyon ve kesintiler | Trendyol'da bir satıştan hangi kesintiler yapılır? | Komisyon KDV'si nasıl hesaplanır; Hizmet bedeli nedir; E-ticaret stopajı %1 satıcıyı nasıl etkiler; Kampanya indirimi komisyonu nasıl değiştirir | "trendyol komisyon oranları" 2.900, "trendyol hizmet bedeli" 110, "trendyol stopaj" ve "trendyol komisyon kdv" hacim doğrulanmadı |
| Kargo, desi, iade | Kargo ve iade kârınızı nasıl etkiler? | Koli boyutu küçültme; İade oranı yüksek kategoriler; İade kargo ücreti kimde | "desi hesaplama" 14.800, "trendyol kargo ücretleri" 720, "trendyol iade kargo ücreti" 50 |
| Reklam ve ROAS | Trendyol reklamı kârlı mı? Ürün bazında nasıl anlaşılır | Başabaş ROAS; Reklam bütçesini ürünlere dağıtmak; Kasım kampanyasında reklam | "trendyol reklam" 720, "roas hesaplama" 170, "trendyol reklam nasıl verilir" 10 (KD 51) |
| Hakediş ve muhasebe | Trendyol hakedişi nasıl kontrol edilir? | Cari hesap ekstresi okuma; Muhasebeciye ay sonu dosyası; Yıl sonu pazaryeri geliri | "trendyol hakediş" hacim doğrulanmadı, "trendyol api" 1.300, "trendyol entegrasyon" 480 |
| Buybox ve fiyat | Buybox ve kârlılık: en ucuz olmak zorunda mısınız? | Buybox'ı etkileyen faktörler; Rekabet Kurumu kararı ve "Buybox fiyatına eşitle" seçeneğinin kalkması (Rekabet Kurumu, 2024); Fiyat düşürmeden önce kâr kontrolü | "trendyol buybox" 110 (SERP: sellbox.tr, sikayetvar.com, akademi.trendyol.com, melontik.com) |
| Başlangıç | Trendyol'da satışa başlamadan önce kâr hesabı | Mağaza açma maliyetleri; İlk 30 günde fiyatlandırma | "trendyol mağaza açma" 2.900 (KD 15), "trendyol satıcı olmak" 2.400 (KD 15). Mikro segment, düşük satın alma niyeti |

Not: "trendyol satıcı paneli" 110.000/ay ama navigasyonel (satıcı panele girmek istiyor). Hedeflenmez, ancak "satıcı panelinde kâr nasıl görülür" gibi bir rehber dolaylı trafik alabilir.

hyturkyilmaz.com ile ilişki: Kişisel blogda kurucu bakışlı yorum yazıları (ör. "Pazaryeri satıcısı neden kârını göremiyor: bir sosyoloğun ve performans pazarlamacısının notları"). NetKâr rehberleriyle aynı yazının kopyası yayımlanmaz. Günlük içerik otomasyonu e-ticaret konusuna kaydırılırsa, insan onayı ve özgün katkı olmadan seri üretim yapılmaz (Google Search Central, t.y.-b).

### 3.7 Karşılaştırma sayfaları `/karsilastirma`

**Amaç:** Karar aşamasındaki ziyaretçiyi ikna etmek. Rakip adı içeren sayfalar en son ve hukuki kontrolle.

| Sayfa | H1 | İçerik | Anahtar kelimeler |
|---|---|---|---|
| netkar-ve-excel | Excel ile kâr takibi mi, NetKâr mı? | Excel'in güçlü yanlarını kabul eden dürüst tablo. Ücretsiz Excel şablonu. "İlk ay ikisini yan yana kullanın" önerisi. | "trendyol kar hesaplama excel" (hacim doğrulanmadı) |
| netkar-ve-entegrator-raporlari | Entegratörünüz varken NetKâr'a neden ihtiyaç duyabilirsiniz? | Rakip değil tamamlayıcı. Entegratör: sipariş, stok, fatura. NetKâr: kâr, mutabakat, reklam. | "trendyol entegrasyon" 480 |
| netkar-ve-ucretsiz-hesaplayicilar | Hesaplayıcı tahmin eder, NetKâr ölçer | Tahmin ile gerçekleşen arasındaki fark kaynakları (kupon, iade, kampanya). | "trendyol komisyon hesaplama" kümesine destek |
| {rakip} (6. ay sonrası) | NetKâr ve {Rakip}: farklar | Yalnız kamuya açık, tarihli, ekran görüntüsüyle arşivlenmiş bilgi. Rakibin güçlü yanları da yazılır. Karşılaştırmalı reklam kuralları için hukuki ön kontrol (varsayım: yönetmelik koşullarına uygunluk gerekir). | "{rakip} alternatif" (hacim doğrulanmadı) |

Sosyal kanıt yeri: Her karşılaştırma sayfasında "{X}'ten geçen satıcı" alıntısı (gerçek olduğunda).

### 3.8 Güvenlik ve KVKK `/guvenlik`

**Amaç:** En büyük itirazı (API anahtarı) kapatmak. Sade ve teknik olarak doğru.
**Anahtar kelimeler:** "trendyol api anahtarı güvenli mi" (hacim doğrulanmadı), "trendyol api" 1.300/ay (navigasyonel ağırlıklı).

| Bölüm | İçerik |
|---|---|
| Başlık | **H1:** Verileriniz nasıl korunuyor? **Alt:** Hangi veriye eriştiğimizi, ne için kullandığımızı ve bağlantıyı nasıl keseceğinizi açıkça yazdık. |
| Hangi veriye erişiyoruz | Sipariş, ürün, iade, finans (hakediş ve cari hesap) verileri. Ürün, fiyat veya stok değiştirmiyoruz (ürünün gerçekten yazma çağrısı yapmadığı kodla doğrulanmalı). |
| API bilgileri | Trendyol panelinde Hesap Bilgilerim > Entegrasyon Bilgileri altında bulunur (Trendyol Developers, t.y.-a). Bilgileri şifreli saklıyoruz. Panelden anahtarı yenilediğinizde eski bağlantı çalışmaz. "Entegrasyon referans kodu"nu hiçbir zaman istemiyoruz (Trendyol bu kodu gizli tutulması gereken bir bilgi olarak tanımlıyor). |
| Bağlantıyı kesme | Adım adım 3 ekran görüntüsü. |
| Veri nerede tutuluyor | Barındırma bölgesi ve alt işleyenler listesi. Yurt dışı aktarım varsa dayanağı (KVKK m.9, 2024 değişikliği sonrası standart sözleşme ve bildirim yükümlülüğü) (KVKK, t.y.). |
| Silme | Hesabı kapatınca verinin kaç gün içinde silineceği. |
| Kişi | Veri sorumlusu bilgisi ve başvuru yolu. |
| Sosyal kanıt yeri | Yok. Güven bu sayfada belge ve açıklıkla sağlanır, alıntıyla değil. |
| CTA | "Sorunuz mu var? Kurucuya doğrudan yazın" (e-posta). |

### 3.9 Entegrasyonlar `/entegrasyonlar`

- **H1:** Bağlanabildiğiniz pazaryerleri. **Alt:** Trendyol bugün, Hepsiburada yakında. Hangi pazaryeri sırada, sizin oylarınızla belirleniyor.
- Kartlar: Trendyol (aktif), Hepsiburada (bekleme listesi), n11, Amazon TR (planlı). Entegratör uyumu notu: "Entegratörünüzle aynı API bilgileri kullanılabilir mi?" sorusunun teknik cevabı (Trendyol tarafındaki kurala göre doğrulanmalı).
- `/entegrasyonlar/trendyol`: Kurulum rehberi, ekran görüntüleri, hangi veriler, sık hatalar (api_connect_failed hata kodlarına göre). Anahtar kelime: "trendyol api" 1.300/ay, "trendyol api entegrasyonu" (hacim doğrulanmadı).
- Sosyal kanıt yeri: "Bağlı Trendyol mağazası" sayacı (eşik 100).

### 3.10 SSS `/sss`

- Kategoriler: Kurulum, Veri ve güvenlik, Hesaplama yöntemi, Fiyat ve fatura, Muhasebeci ve ajans, Mobil uygulama.
- Her cevap ilk cümlede doğrudan yanıt verir (GEO).
- FAQPage şeması eklenebilir ancak zengin sonuç beklenmez: Google Ağustos 2023'te FAQ zengin sonuçlarını iyi bilinen resmi kurum ve sağlık sitelerine sınırladı (Google Search Central, 2023). Üçüncü taraf haberler 2026'da tamamen kaldırıldığını bildiriyor, Google dokümanından teyit edilmeli.

### 3.11 Kayıt `/kayit` ve Kurucu üyelik `/kurucu-uyelik`

**Kayıt sayfası:**
- **H1:** 14 günlük ücretsiz denemenizi başlatın. **Alt:** Kart gerekmez. İlk raporunuz için Trendyol API bilgileriniz ve 10-15 dakikanız yeterli.
- Alanlar: ad, e-posta, şifre (veya Google ile giriş), "Aylık sipariş sayınız" (aralık seçimi), "Reklam kullanıyor musunuz?". Telefon zorunlu değil.
- Erişilebilir kimlik doğrulama: şifre yapıştırma ve şifre yöneticisi engellenmez, bilişsel test içeren CAPTCHA kullanılmaz (WCAG 2.2, 3.3.8).
- Sağ sütun: 3 madde (ne olacak), 1 alıntı, güvenlik bağlantısı.
- Kayıttan sonra doğrudan "Trendyol'u bağla" ekranı (huni Bölüm 4).

**Kurucu üyelik (lansman öncesi ana LP):**
- **H1:** NetKâr'ın ilk 50 satıcısından biri olun. **Alt:** İlk ay ücretsiz, sonrasında abonelik sürdükçe kurucu fiyatı. Karşılığında iki kısa geri bildirim görüşmesi istiyoruz.
- Form: e-posta, mağaza adı (opsiyonel), aylık sipariş aralığı, reklam kullanımı, kategoriler, "Şu an kârınızı nasıl takip ediyorsunuz?" (açık uçlu).
- Şeffaflık: "Kalan yer: X" (gerçek), "Ürün şu an kapalı beta aşamasında, ilk davetler {tarih}".
- Sosyal kanıt yeri: Hasan'ın kısa videosu (60 sn) ve LinkedIn bağlantısı.
- CTA: "Başvurumu gönder". Teşekkür sayfasında: arkadaşını davet et bağlantısı (sırada öne geçme), ücretsiz araçlar.

### 3.12 Ortaklık sayfaları `/ortaklik`

| Sayfa | H1 | Teklif özeti | CTA | Sosyal kanıt yeri |
|---|---|---|---|---|
| /ortaklik | Satıcılara faydalı bir araç önerin, gelirinizden pay alın | Getirdiğiniz her ödeyen mağazadan 12 ay boyunca tekrarlayan komisyon (oran 05 belgesinde öneri) | Ortak olun | Ortak sayısı (eşik 10) |
| /ortaklik/mali-musavirler | E-ticaret müşterilerinizin hakedişini dakikalar içinde kontrol edin | Ücretsiz müşavir paneli, müşteri başına salt okuma erişim, aylık PDF, komisyon veya müşteriye indirim seçeneği | Ücretsiz müşavir hesabı açın | 1 müşavir alıntısı |
| /ortaklik/ajanslar | Müşterilerinize ciro değil net kâr raporu verin | Ajans paketi, beyaz etiket PDF, çok mağaza paneli | Demo isteyin | Ajans vakası |
| /ortaklik/egitmenler | Öğrencileriniz kârını gerçek veriyle görsün | Öğrenci indirimi, demo mağaza verisi, ders içi kullanım | Ortak olun | Eğitmen alıntısı |

### 3.13 Vaka çalışmaları `/vaka-calismalari`

- Şablon: Satıcı profili (kategori, sipariş aralığı, şehir) / Sorun / NetKâr'da ne gördü / Ne yaptı / Sonuç (rakamlar, ölçüm dönemi ve yöntem notuyla) / Satıcının kendi cümlesi.
- Kural: Sonuçlar "NetKâr sayesinde" değil "NetKâr'da gördükten sonra şunu yaptı ve şu değişti" diliyle yazılır. Mevsimsellik gibi başka etkenler varsa belirtilir.
- Lansman öncesi sayfa yayımlanmaz.

### 3.14 Hakkımızda `/hakkimizda`

- **H1:** NetKâr'ı kim, neden yapıyor? Hasan'ın kısa biyografisi (sosyolog, full stack geliştirici, dijital ve performans pazarlama direktörü, e-ticaret pazarlama uzmanı), fotoğraf, LinkedIn ve hyturkyilmaz.com bağlantısı. Şirket bilgileri (unvan, adres, MERSİS/vergi no, iletişim). Person ve Organization şemaları bu sayfadan beslenir.

---

## 4) Dönüşüm hunisi

```
Arama / sosyal / ortak / topluluk
        |
        v
[1] Ziyaret (araç, rehber, ana sayfa)
        |  araç sayfasında: calculator_used
        v
[2] Mikro dönüşüm: sonucu e-postayla kaydet, Excel şablonu, oran değişikliği uyarısı, bekleme listesi
        |  e-posta dizisi (5 e-posta / 14 gün)
        v
[3] Kayıt (signup) + trial_started
        v
[4] API bağlantısı (api_connected)            <- en büyük kayıp noktası
        v
[5] Veri çekimi + maliyet girişi (data_sync_completed, cost_data_completed)
        v
[6] İlk kâr görünümü (first_profit_view)      <- "aha" anı: zararlı ürünü görmek
        v
[7] Değer tekrarı: uyarı alındı, mutabakat raporu, Kâr Karnesi
        v
[8] Ücretli (paid)
        v
[9] Elde tutma ve yayılma: aylık karne paylaşımı, muhasebeci daveti, ortak/davet
```

| Adım | Hedef oran (varsayım, ilk 90 günün verisiyle güncellenir) | Kayıp nedeni (beklenen) | Önlem |
|---|---|---|---|
| Ziyaret → mikro dönüşüm (araç sayfası) | %3-6 | Sadece hesap yapıp çıkmak | Sonucu kaydetme değerini açık yazmak, oran uyarısı |
| Ziyaret → kayıt (ana sayfa, fiyat) | %2-4 | Güven, fiyat | Güvenlik özeti, kurucu notu, kart istememek |
| Mikro dönüşüm → kayıt (30 gün) | %8-15 | Zamanlama | Kasım hakedişi gibi tetikleyicide e-posta |
| Kayıt → API bağlantısı (24 saat) | %50+ | API bilgisini bulamamak, kaygı | Ekran görüntülü rehber, 2 dakikalık video, "Kurulumda yardım isteyin" (WhatsApp veya görüntülü 10 dk) |
| API → ilk kâr görünümü (48 saat) | %80+ | Maliyet girmemek | Maliyet olmadan da "komisyon ve kargo sonrası" görünümü göstermek, maliyet için Excel yükleme |
| Deneme → ücretli | %12-20 | Değeri görmemek | Gün 10'da "NetKâr'ın bulduğu" kişisel özet |
| Aylık churn | %5 altı | Kampanya dışı aylarda kullanmamak | Haftalık özet bildirimi, aylık karne |

Sayfa içi CTA hiyerarşisi: Birincil CTA her zaman "14 gün ücretsiz deneyin" (lansman öncesi "Kurucu üyeliğe başvurun"). Araç sayfalarında birincil eylem aracı kullanmaktır, CTA sonuçtan sonra gelir. Bir sayfada en fazla iki CTA tipi.

---

## 5) SEO teknik gereksinimleri (Next.js)

### 5.1 Mimari ve render

- Next.js App Router. Pazarlama sitesi ve uygulama ayrı: pazarlama `/` altında, uygulama ayrı alt alan adında (ör. `app.`) ve `noindex`. Böylece uygulama JS'i pazarlama sayfalarına yüklenmez.
- Sayfa türüne göre render: Ana sayfa, özellikler, fiyatlar, araçlar: statik üretim (SSG). Komisyon oranları ve rehberler: ISR (ör. 1 saatlik yeniden doğrulama, oran değişince manuel tetikleme). Hesaplayıcı mantığı istemci bileşeni, ama sayfa sunucuda örnek değerler ve örnek sonuçla birlikte HTML olarak gelir.
- İçerik kaynağı: Rehberler MDX veya başlıksız CMS. Komisyon oranları tek bir JSON/veritabanı tablosundan hem araçlara hem tabloya beslenir (tek doğruluk kaynağı).

### 5.2 URL, meta, kanonik

- Küçük harf, Türkçe karakter yok, kelimeler tire ile (`/araclar/trendyol-kar-hesaplama`). Sonda eğik çizgi kullanılmaz, tutarlı 301 yönlendirmesi.
- Metadata API ile her sayfada benzersiz `title` (≤60 karakter) ve `description` (≤155 karakter). `generateMetadata` ile dinamik sayfalar.
- `alternates.canonical` her sayfada. Hesaplayıcı parametreli URL'leri (paylaşılan sonuç linkleri) ana araç sayfasına kanonikleşir.
- `sitemap.ts` ile otomatik site haritası, `lastModified` gerçek güncelleme tarihi. `robots.ts` ile uygulama, giriş, kayıt adımları ve parametreli URL'ler hariç.
- Açık Grafik (Open Graph) görselleri her araç ve rehber için dinamik üretilir (kişisel veri içermez).

### 5.3 hreflang hazırlığı (TR / EN)

- Türkçe kök dizinde, İngilizce `/en` altında. Yerel ayar klasörü yapısı şimdiden kurulur, İngilizce sayfalar çevrilene kadar yayımlanmaz ve hreflang'e eklenmez (boş veya otomatik çeviri sayfa yayımlanmaz).
- Metadata API'de `alternates.languages`: `tr` (veya `tr-TR`), `en`, `x-default` (Türkçe sürüm). Site haritasında her giriş için dil alternatifleri (General Translation, t.y.; Next.js resmi dokümanından teyit edilmeli).
- Sayfa çiftleri birbirine karşılıklı işaret eder. Para birimi ve pazaryeri farkı nedeniyle EN sayfalar birebir çeviri değil, yerelleştirilmiş içerik olur (global pazar kararıyla birlikte).
- `<html lang="tr">` ve `<html lang="en">` doğru atanır.

### 5.4 Yapılandırılmış veri (JSON-LD)

| Şema | Nerede | Not |
|---|---|---|
| Organization | Tüm sayfalar (layout) | ad, logo, url, sameAs (LinkedIn, YouTube, Instagram), iletişim |
| WebSite | Ana sayfa | Site adı "NetKâr" (marka varlığının tutarlılığı için) |
| SoftwareApplication | Ana sayfa, fiyatlar, mobil sayfa | applicationCategory BusinessApplication, operatingSystem (Web, iOS, Android), offers (3 plan, TRY, KDV notu açıklamada). AggregateRating yalnız gerçek ve doğrulanabilir mağaza puanı olduğunda |
| WebApplication | Her hesaplayıcı | isAccessibleForFree true, offers fiyat 0 |
| BreadcrumbList | Tüm iç sayfalar | |
| Article / BlogPosting | Rehberler | author: Person (Hasan, sameAs hyturkyilmaz.com ve LinkedIn), datePublished, dateModified |
| Person | Hakkımızda, yazar kutuları | jobTitle, sameAs |
| FAQPage | SSS, araç sayfalarındaki görünür SSS | Zengin sonuç beklenmez (Google Search Central, 2023), makine okunurluğu için düşük öncelikli |
| VideoObject | Video içeren sayfalar | Kurulum videosu |
| HowTo | Kullanılmaz | Google HowTo zengin sonuçlarını 2023'te kaldırdı (Google Search Central, 2023) |

Doğrulama: Rich Results Test ve Schema.org doğrulayıcı CI adımında.

### 5.5 İçerik ve iç bağlantı

- Her araç sayfası ilgili rehbere ve komisyon oranları tablosuna, her rehber en az bir araca bağlanır. Hub sayfaları kümeyi listeler.
- Programatik sayfalar (kategori bazlı oranlar) ancak özgün veri ve açıklama içerdiğinde. Aksi halde tek tabloda filtre.
- Güncellik: Oran ve mevzuat içeren sayfalarda "son kontrol tarihi" ve aylık kontrol ajanı. Değişiklik geçmişi görünür.
- Görsel optimizasyonu: `next/image`, AVIF/WebP, anlamlı alt metin. Ürün ekran görüntülerinde örnek veri etiketi.

---

## 6) GEO: AI arama görünürlüğü

Hedef: ChatGPT, Gemini, Google AI Overviews ve AI Mode, Perplexity ve Claude gibi sistemlerde "Trendyol kâr hesaplama", "Trendyol'da hangi ürünüm zararda" gibi sorulara verilen cevaplarda NetKâr'ın kaynak veya öneri olarak geçmesi. SERP'teki beş hedef sorgunun hepsinde AI Overview görüldü (OpenSEO/DataForSEO, 2026).

### 6.1 Temel (Google'ın kendi rehberine göre)

- Google, AI özellikleri için özel bir dosya veya özel bir işaretleme gerekmediğini, temel SEO gereksinimlerinin (taranabilirlik, iç bağlantı, iyi sayfa deneyimi, yararlı ve özgün içerik) geçerli olduğunu söylüyor. llms.txt Google için gerekli değil (Google Search Central, t.y.-a; Search Engine Roundtable, t.y.).
- robots.txt ve CDN/WAF katmanında arama tarayıcıları engellenmez.

### 6.2 İçerik biçimi

1. **Önce cevap:** Her araç ve rehber, ilk 40-60 kelimede soruyu doğrudan cevaplar, ardından formül ve rakamlı örnek gelir.
2. **Formül ve tanım blokları:** "Net kâr = ..." gibi tek satırlık, alıntılanabilir tanımlar. Birim ve tarih ile.
3. **Birincil kaynak gösterimi:** Resmî Gazete (stopaj), Trendyol geliştirici dokümanları, Rekabet Kurumu kararı gibi. AI sistemleri kaynağı belli içeriği tercih ediyor (varsayım, genel gözlem).
4. **Özgün veri:** 9. ayda "Türkiye Pazaryeri Satıcı Kârlılık Endeksi" (anonim, toplu, kullanıcının açık rızasıyla). Başka sitelerin ve AI cevaplarının alıntılayacağı türden bir veri.
5. **Tutarlı varlık adı:** Her yerde "NetKâr" (logo, şema, sosyal profiller, basın). Organization ve Person şemalarında sameAs bağlantıları.
6. **Yazar ve deneyim:** Rehberlerde Hasan'ın gerçek deneyimine dayanan notlar ve görünür yazar kutusu.

### 6.3 Site dışı sinyaller

- AI cevapları üçüncü taraf kaynaklardan da besleniyor (varsayım, genel gözlem). Bu nedenle: ortak sitelerde (mali müşavir, eğitmen) tanıtım sayfaları, Webrazzi ve sektör yayınlarında haber, YouTube'da kurulum ve vaka videoları, r10.net gibi forumlarda kurucunun kendi adıyla verdiği yardımcı cevaplar (reklam değil).
- Ürün karşılaştırma ve "alternatif" listelerinde yer alma: liste yazan bloglara doğrulanabilir bilgi kiti.

### 6.4 Tarayıcı politikası (karar önerisi)

| Bot | Öneri | Gerekçe |
|---|---|---|
| Googlebot, Bingbot | İzin | Arama ve AI Overviews |
| OAI-SearchBot, PerplexityBot, Claude'un arama botları | Pazarlama sayfalarında izin, uygulamada engel | AI aramada kaynak gösterilmek |
| Model eğitimi amaçlı botlar (Google-Extended, GPTBot vb.) | Hasan'ın kararına bırakılır | Eğitime izin vermek görünürlüğü doğrudan artırmaz (varsayım), içerik sahipliği tercihi |
| llms.txt | Opsiyonel, düşük maliyetli | Google için gerekli değil, diğer sistemlere etkisi kanıtlanmamış |

### 6.5 Ölçüm

- Aylık 20 soruluk sabit soru seti (ör. "Trendyol satıcıları için kâr analizi uygulaması öner", "Trendyol komisyonu nasıl hesaplanır", "Trendyol hakedişimi nasıl kontrol ederim") ChatGPT, Gemini, Perplexity ve Google AI Mode'da elle veya ajanla kontrol edilir. Kayıt: marka geçti mi, kaynak olarak sitemiz gösterildi mi, hangi rakipler geçti.
- OpenSEO'da AI görünürlük takibi araçları var ancak kredi harcar, açılmadan önce maliyet tahmini alınmalı.
- Search Console'da AI Overview kaynaklı tıklamalar ayrı raporlanmadığı için marka aramalarının trendi dolaylı gösterge olarak izlenir (varsayım).

---

## 7) Hız ve erişilebilirlik hedefleri

### 7.1 Core Web Vitals

Ölçüm, gerçek kullanıcı verisinin 75. yüzdeliğinde, mobil ve masaüstü ayrı (web.dev, t.y.).

| Metrik | Google "iyi" eşiği | NetKâr iç hedefi (pazarlama sayfaları) |
|---|---|---|
| LCP | ≤ 2,5 sn | ≤ 1,8 sn (mobil, 4G) |
| INP | ≤ 200 ms | ≤ 150 ms (hesaplayıcılarda her tuşa basışta hesaplama yapılır, bu nedenle hesaplama hafif ve debounce'lu) |
| CLS | ≤ 0,1 | ≤ 0,05 (sonuç alanı yüksekliği önceden ayrılır, font yüklemesinde kayma yok) |

Ek iç hedefler (varsayım, ölçülerek ayarlanır): Araç sayfasında ilk yüklemede istemci JS'i 150 KB (sıkıştırılmış) altında. Yazı tipi en fazla 2 dosya, kendi sunucumuzda, Türkçe karakterleri kapsayan alt küme, `font-display: swap` ve boyut eşlemesi. Üçüncü taraf script'ler (analitik, sohbet) onaydan sonra ve etkileşim sonrası yüklenir. Lighthouse CI ile her PR'da performans bütçesi kontrolü, gerçek kullanıcı verisi için web-vitals kütüphanesiyle RUM.

### 7.2 WCAG 2.2 AA

WCAG 2.2, Ekim 2023'te W3C tavsiyesi olarak yayımlandı ve 2.1'e 9 yeni başarı ölçütü ekledi, 4.1.1 Ayrıştırma ölçütünü kaldırdı (W3C, 2023).

| Ölçüt | Sitede ne anlama geliyor |
|---|---|
| 1.4.3 Kontrast (en az 4,5:1) ve 1.4.11 Metin dışı kontrast (3:1) | Kırmızı/yeşil kâr-zarar renkleri tek başına bilgi taşımaz, yanında işaret ve metin olur (1.4.1). Grafik ve odak halkası 3:1 |
| 1.4.10 Yeniden akış | 320 CSS piksel genişlikte yatay kaydırma yok. Karşılaştırma tabloları mobilde kart görünümüne döner |
| 1.3.5 Girdi amacının belirlenmesi | Kayıt formunda `autocomplete` (name, email) |
| 2.4.7 Odak görünür, 2.4.11 Odak gizlenmemiş (en az) | Yapışkan üst menü ve çerez bandı odaklanan öğeyi örtmez |
| 2.5.7 Sürükleme hareketleri | Fiyat dönem anahtarı veya kaydırıcı varsa tıklama alternatifi |
| 2.5.8 Hedef boyutu (en az) | Tıklanabilir hedefler en az 24×24 CSS piksel (mobilde iç hedef 44×44) |
| 3.2.6 Tutarlı yardım | "Kurulumda yardım" bağlantısı her sayfada aynı yerde |
| 3.3.1 / 3.3.3 Hata tanımlama ve öneri | Hesaplayıcıda "Satış fiyatı alış maliyetinden düşük olamaz mı? Kontrol edin" gibi açık mesaj, alanla ilişkili (`aria-describedby`) |
| 3.3.7 Gereksiz tekrar | Araçtan kayda geçerken girilen bilgiler (e-posta, sipariş aralığı) tekrar sorulmaz |
| 3.3.8 Erişilebilir kimlik doğrulama (en az) | Şifre alanına yapıştırma serbest, şifre yöneticisi destekli, bilişsel test içeren CAPTCHA yok, e-posta ile sihirli bağlantı alternatifi |
| 4.1.3 Durum mesajları | Hesaplayıcı sonucu `aria-live="polite"` ile ekran okuyucuya bildirilir |
| Dil | `lang="tr"`, İngilizce terimler (ROAS, Buybox) için ilk geçişte açıklama |

Test: Otomatik (axe-core, CI'da), elle klavye testi, NVDA ve VoiceOver ile kayıt ve hesaplayıcı akışı, ayda bir erişilebilirlik kontrol listesi. Erişilebilirlik beyanı sayfası (alt bilgide).

### 7.3 Ölçüm ve gizlilik

- Event sözlüğü ve UTM kuralları 05 belgesi Bölüm 8'dedir.
- Çerez bandı: Zorunlu dışındaki çerezler onaydan önce yüklenmez. Reddetme seçeneği kabul etme kadar kolay erişilir.
- Araç girdileri (satış fiyatı, maliyet) analitiğe ham olarak gönderilmez, yalnız aralık (band) olarak.

---

## 8) Yayın sırası (05 belgesindeki takvimle uyumlu)

| Hafta | Yayına çıkacak |
|---|---|
| 1 | /kurucu-uyelik, /araclar/trendyol-komisyon-hesaplama (v1), /hakkimizda, yasal sayfalar, ölçüm |
| 2 | /araclar/trendyol-kar-hesaplama, /trendyol-komisyon-oranlari, ilk 4 rehber |
| 3 | /araclar/desi-kargo-hesaplama, /araclar/iade-maliyeti-hesaplama, /guvenlik |
| 7 | /araclar/basabas-roas-hesaplama, /ozellikler alt sayfaları |
| 9 | /fiyatlar, /sss, /entegrasyonlar, /karsilastirma (3 sayfa), /vaka-calismalari |
| 10 | Ana sayfa lansman sürümü, /kayit, /ortaklik sayfaları |
| 4.-5. ay | Hepsiburada araç ve entegrasyon sayfaları |
| 10.-12. ay | /en sayfaları ve hreflang |

---

## Kaynaklar (APA 7)

Tüm web kaynaklarına erişim tarihi: 5 Kasım 2026. "t.y." tarih yok anlamındadır. Arama motoru özetinden alınan ve sayfası doğrudan açılamayan kaynaklar köşeli parantezle işaretlenmiştir.

BirFatura. (t.y.). *Trendyol iade faturası, Trendyol kurumsal iade*. https://birfatura.com/trendyol-iade-faturasi-trendyol-kurumsal-iade/

ecomcalctools. (t.y.). *Trendyol kâr hesaplama rehberi*. https://ecomcalctools.com/tr/blog/trendyol-kar-hesaplama/

Faturaport. (t.y.). *Trendyol kargo ücretleri 2026: Güncel fiyat rehberi*. https://www.faturaport.com/blog/on-muhasebe/trendyol-kargo-ucretleri-2026-guncel-fiyat-rehberi

General Translation. (t.y.). *Multilingual Next.js SEO*. https://generaltranslation.com/en-US/blog/multilingual-nextjs-seo

Google Search Central. (2023, 8 Ağustos). *Changes to HowTo and FAQ rich results*. https://developers.google.com/search/blog/2023/08/howto-faq-changes

Google Search Central. (t.y.-a). *AI features and your website*. https://developers.google.com/search/docs/appearance/ai-features

Google Search Central. (t.y.-b). *Spam policies for Google web search*. https://developers.google.com/search/docs/essentials/spam-policies

KVKK. (t.y.). *Yurt dışına kişisel veri aktarımında kullanılacak standart sözleşmelerde dikkat edilmesi gereken hususlara ilişkin kamuoyu duyurusu*. Kişisel Verileri Koruma Kurumu. https://www.kvkk.gov.tr/Icerik/8170/Yurt-Disina-Kisisel-Veri-Aktariminda-Kullanilacak-Standart-Sozlesmelerde-Dikkat-Edilmesi-Gereken-Hususlara-Iliskin-Kamuoyu-Duyurusu

[Mağaza Danışmanı. (t.y.). *Trendyol mağaza yönetimi ve danışmanlık, başabaş ROAS hesaplayıcı*. https://magazadanismani.com.tr/]

OpenSEO / DataForSEO. (2026, 5 Kasım). *Anahtar kelime metrikleri (35 kelime) ve Google SERP okumaları (5 sorgu), Türkiye, Türkçe, masaüstü* [Yayımlanmamış veri seti, hyturkyilmaz.com projesi]. https://app.openseo.so/p/d90cd6a0-e282-4737-8d23-f23016fd6e8e/keywords

Paraşüt. (t.y.). *Trendyol kargo ücretleri*. https://www.parasut.com/blog/trendyol-kargo-ucretleri

Rekabet Kurumu. (2024, 28 Kasım). *Investigation concerning DSM Grup Danışmanlık İletişim ve Satış Ticaret AŞ (Trendyol) concluded*. https://www.rekabet.gov.tr/en/Guncel/investigation-concerning-dsm-grup-danism-cfebfc2175adef1193d70050568585c9

Search Engine Roundtable. (t.y.). *New Google docs on using AI generative content & AI search features*. https://www.seroundtable.com/google-docs-ai-content-ai-search-features-39456.html

Trendyol Developers. (t.y.-a). *Cari hesap ekstresi entegrasyonu*. https://developers.trendyol.com/docs/cari-hesap-ekstresi-entegrasyonu.md

Trendyol Developers. (t.y.-b). *Product buybox check*. https://developers.trendyol.com/tr/v3.0/docs/12-product-buybox-check

W3C. (2023). *Web Content Accessibility Guidelines (WCAG) 2.2*. https://www.w3.org/TR/WCAG22/

web.dev. (t.y.). *How the Core Web Vitals metrics thresholds were defined*. https://web.dev/articles/defining-core-web-vitals-thresholds

Webrazzi. (2024, 23 Aralık). *E-ticarette stopaj oranı yüzde 1 olarak belirlendi*. https://webrazzi.com/2024/12/23/e-ticarette-stopaj-orani-yuzde-1-olarak-belirlendi/
