# NetKâr: Hukuk ve Uyum Çerçevesi (Kontrol Listesi)

Erişim tarihi (tüm kaynaklar): 5 Kasım 2026. Sürüm: v0.1. İlgili dokümanlar: `docs/10_mimari.md`, `docs/50_guvenlik.md`, `docs/research/04_altyapi_fiyatlari.md`.

> **ÖNEMLİ UYARI: Bu doküman hukuki, mali veya vergi tavsiyesi değildir.** Kurucunun avukat (KVKK ve bilişim hukuku), mali müşavir (vergi ve şirket türü) ve marka vekiliyle teyit etmesi gereken bir **kontrol listesidir**. Her satırdaki "Güven" sütunu bilginin ne kadar sağlam olduğunu gösterir. "Doğrulanmadı" yazan hiçbir bilgi karar dayanağı yapılmamalıdır.

## 0. Yöntem notu ve güvenilirlik sınırı (önce okuyun)

- Bu araştırma ortamında doğrudan sayfa açma (WebFetch) mevzuat.gov.tr, kvkk.gov.tr ve developers.trendyol.com için engelliydi (alan adı çözümlenemedi). Resmî metinleri **satır satır okuyamadım**. Bilgiler arama motoru özetlerinden ve ikincil kaynaklardan (hukuk bürosu bültenleri, meslek siteleri) derlendi. Resmî kaynak bağlantıları yine de verildi; avukat bu bağlantılardan metni teyit etmelidir.
- mevzuat.gov.tr bağlantıları sitenin standart kalıbıyla (`MevzuatNo`, `MevzuatTur`, `MevzuatTertip`) oluşturuldu; bu oturumda açılıp kontrol edilmedi. Yönetmelikler için Resmî Gazete günlük dizin sayfası verildi.
- Fıkra ve bent numaraları ikincil kaynaklardan geldiği yerlerde "(fıkra no. teyit edilmeli)" notu var.
- Hiçbir madde, tutar veya tarih uydurulmadı. Çelişkili bulgu varsa iki değer de yazıldı.

**Güven ölçeği**

| Düzey | Anlamı |
|---|---|
| Yüksek | Birden çok bağımsız kaynakta tutarlı, kuralın varlığı tartışmasız; yalnız resmî metin bu oturumda açılamadı |
| Orta | İkincil kaynaklarla teyit edildi, ayrıntı (fıkra, tutar, süre) resmî metinden kontrol edilmeli |
| Düşük | Tek kaynak veya kaynaklar çelişkili |
| Doğrulanmadı | Kaynak bulunamadı; genel bilgi veya çıkarım |

---

## 1. Yönetici özeti

**Kırmızı bayraklar (MVP öncesi çözülmeli)**

- **[KIRMIZI BAYRAK 1] Yurt dışında barındırma = KVKK m.9 aktarımı.** Hetzner (Almanya/Finlandiya), AWS, GCP, Vercel, Supabase, Cloudflare, Sentry, PostHog, Resend gibi Türkiye dışındaki her hizmete kişisel veri giderse bu "yurt dışına aktarım"dır. Kurul'un yayımlanmış bir yeterlilik kararı bulamadım (doğrulanmadı). Pratik yol Kurul'un **değiştirilemeyen** standart sözleşmesidir; imzadan sonra **5 iş günü içinde Kurum'a bildirim** gerekir. Büyük bulut sağlayıcıların bu metni değiştirmeden imzalayıp imzalamadığını doğrulayamadım. Bu, `10_mimari.md` içindeki K-N02 kararının hukuki tarafıdır.
- **[KIRMIZI BAYRAK 2] AI özelliği (ABD'deki LLM API) ayrı bir yurt dışı aktarımdır.** Müşteri sorusunda ad, sipariş no, adres, telefon olabilir. Maskeleme yapılmadan ve m.9 mekanizması kurulmadan bu özellik açılmamalı. Arızi aktarım istisnası düzenli akışlar için kullanılamaz (Kurum rehberi, ikincil kaynak).
- **[KIRMIZI BAYRAK 3] "NetKâr" adı tanımlayıcı olabilir.** Net kâr hesaplayan bir hizmet için "NetKâr", SMK m.5 kapsamında tanımlayıcı marka itirazına veya reddine açık görünüyor (doğrulanmadı, marka vekili değerlendirmeli). Ayrıca araştırma 02'de App Store'da aynı adlı bir uygulama bulundu.
- **[KIRMIZI BAYRAK 4] Trendyol satıcı sözleşmesinin üçüncü taraf yazılım ve veri paylaşımı hükümlerini bulamadım.** Resmî geliştirici dokümanı entegratör kullanımını öngörüyor (User-Agent'ta entegratör adı), ancak sözleşme metni görülmeden "izinli" denemez. Bir satıcı hesabından sözleşmenin güncel metni alınmalı.
- **[KIRMIZI BAYRAK 5] Sorumluluk sınırlaması tek başına korumaz.** Kâr hesabı hatasından doğan zararlar için ağır kusur sorumluluğu önceden kaldırılamaz (TBK m.115). Genel işlem koşullarındaki tek taraflı değişiklik yetkisi yazılmamış sayılabilir (TBK m.24). Fiyat artışı ve koşul değişikliği için yeniden onay akışı kurulmalı.

**Diğer ana bulgular**

- **Roller:** Satıcı, son müşteri (alıcı) verileri için veri sorumlusu; NetKâr bu verilerde **veri işleyen**. Satıcının kendi kullanıcı hesabı, fatura ve pazarlama verilerinde NetKâr **veri sorumlusu**. Şahıs işletmesi satıcıların finans verisi de gerçek kişiye ait olduğundan kişisel veri sayılabilir (orta güven).
- **Minimizasyon en güçlü kalkan:** Son müşteri adı, adresi, telefonu veritabanına yazılmazsa (mimaride zaten planlandı) ihlal riski, aktarım kapsamı ve imha yükü ciddi biçimde azalır.
- **VERBİS:** Kuruluş aşamasında büyük olasılıkla muafiyet var (çalışan 50'den az ve yıllık mali bilanço 100 milyon TL'den az; 2025/1572 sayılı kararla özel nitelikli veri işleyenler için ayrı eşik getirildi). Muafiyet aydınlatma, güvenlik, ihlal bildirimi yükümlülüklerini kaldırmaz.
- **Veri ihlali:** Kurul'a öğrenmeden itibaren 72 saat içinde bildirim (Kurul kararı 2019/10). Veri işleyen olarak satıcıya daha kısa sürede (öneri: 24 saat) haber verme taahhüdü DPA'ya yazılmalı. 7545 sayılı Siber Güvenlik Kanunu kapsamında ayrı bir bildirim rejimi olabilir (orta güven).
- **Ticari elektronik ileti:** Tacir veya esnafa e-posta/SMS için önceden onay gerekmez, ama alıcı adresleri ileti gönderilmeden **İYS'ye kaydedilmeli** ve ret durumu kontrol edilmelidir (2020 değişikliği, orta güven). NetKâr İYS'ye hizmet sağlayıcı olarak kaydolmalı.
- **Abonelik:** Müşteriler ticari amaçla hareket ettiğinden 6502 ve Mesafeli Sözleşmeler Yönetmeliği büyük olasılıkla uygulanmaz; TBK ve TTK uygulanır (orta güven). Yine de kolay iptal ve yenileme öncesi bildirim iyi uygulamadır.
- **Vergi:** SaaS aboneliği hizmet; genel KDV oranı %20 (CBK 7346, 10.07.2023'ten beri). Yurt dışından alınan bulut ve LLM hizmetleri için sorumlu sıfatıyla KDV beyanı gündeme gelir (mali müşavire sorulacak). Yurt dışı müşteriye satışta hizmet ihracatı istisnası (KDVK m.11/1-a, m.12/2) iki koşula bağlıdır.
- **Ödeme:** Para bizim hesabımızda başkası adına tutulmadıkça NetKâr ödeme hizmeti sağlayıcı değildir; lisanslı ödeme kuruluşunun barındırdığı form ve kart saklama (token) ile PCI DSS SAQ A kapsamında kalınabilir.
- **Güvenlik:** `50_guvenlik.md` ASVS 4.0.3'ü hedefliyor; güncel sürüm **ASVS 5.0.0 (30 Mayıs 2025)**. Hedef "ASVS 5.0 L2" olarak güncellenmeli.

---

## 2. KVKK (6698 sayılı Kanun)

Dayanak bağlantısı: 6698 sayılı Kişisel Verilerin Korunması Kanunu, https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6698&MevzuatTur=1&MevzuatTertip=5

### 2.1 Roller: kim veri sorumlusu, kim veri işleyen?

| Veri | Kimin verisi | Rol (NetKâr) | Gerekçe |
|---|---|---|---|
| Son müşteri (alıcı) adı, adresi, telefonu, sipariş içeriği | Trendyol alıcısı | Veri işleyen (satıcı adına) | Amaç ve aracı satıcı belirler; biz satıcının talimatıyla hesaplama yaparız |
| Müşteri sorusu metni (AI taslak) | Alıcı | Veri işleyen | Aynı gerekçe |
| Satıcının finans ekstresi, hakediş | Satıcı (tüzel kişi ise kişisel veri değil; şahıs işletmesi ise kişisel veri olabilir) | Veri işleyen | Satıcının kendi işletme verisi |
| Kullanıcı hesabı (ad, e-posta, telefon), oturum ve log kayıtları | Satıcı çalışanı / sahibi | **Veri sorumlusu** | Abonelik ilişkisi için kendi amacımızla işleriz |
| Fatura, ödeme kaydı | Satıcı | **Veri sorumlusu** | VUK ve TTK yükümlülükleri bizim |
| Pazarlama, web sitesi çerezleri, analitik | Ziyaretçi, satıcı | **Veri sorumlusu** | Kendi amacımız |

**Kritik çizgi:** Satıcı verisini kendi amacımız için (ör. satıcılar arası kıyas, model eğitimi, reklam) kullanırsak o işlemde veri sorumlusu oluruz ve ayrı hukuki sebep gerekir. Rol sözleşme başlığına göre değil fiilî duruma göre belirlenir (ikincil kaynak, Kurul 2020/71 kararına atıf; orta güven). Ürün geliştirme için yalnız anonim ve toplulaştırılmış veri kullanılmalı ve bu DPA'da açıkça yazmalı.

| Yükümlülük | Dayanak (madde, link) | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Veri sorumlusu ve veri işleyen tanımları | KVKK m.3 (6698, link yukarıda) | Yukarıdaki rol tablosunu Gizlilik Politikası ve DPA'ya aynen koy | MVP öncesi | Yüksek |
| Veri sorumlusu ile veri işleyen veri güvenliğinden müştereken sorumlu | KVKK m.12/2 | DPA'da güvenlik tedbirleri eki; satıcıya denetim/bilgi hakkı | MVP öncesi | Yüksek |
| İşleme ilkeleri: amaçla bağlantılı, sınırlı ve ölçülü; gerekli süre kadar saklama | KVKK m.4/2 | Son müşteri PII'si DB'ye yazılmaz (bkz. 2.3) | MVP öncesi | Yüksek |
| Kendi kullanıcılarımız için hukuki sebep | KVKK m.5/2 (c) sözleşmenin ifası, (ç) hukuki yükümlülük, (f) meşru menfaat | Hesap ve fatura verisi için açık rıza **istenmez**; yanlış yere açık rıza koymak sorun çıkarır | MVP öncesi | Yüksek |

### 2.2 Veri İşleme Sözleşmesi (DPA) şablonunda olması gerekenler

KVKK DPA için hazır metin şart koşmaz; m.12/2 müşterek sorumluluk ve ispat yükü nedeniyle yazılı sözleşme uygulamada gereklidir (ikincil kaynak; orta güven). Abonelik kabulünde tıklama ile onaylanan bir "Veri İşleme Eki" olarak kurgulanabilir.

| # | Madde | İçerik önerisi |
|---|---|---|
| 1 | Taraflar ve roller | Satıcı veri sorumlusu, NetKâr veri işleyen; NetKâr'ın veri sorumlusu olduğu işlemler ayrıca listelenir |
| 2 | Konu, amaç, süre | Net kâr hesaplama, iade ve finans mutabakatı, (faz 2) soru yanıt taslağı; süre abonelik süresi |
| 3 | Veri ve ilgili kişi kategorileri | Sipariş, iade, ürün, finans; alıcı için yalnız il ve tuzlu hash anahtar (PII saklanmaz); soru metni (maskelenmiş) |
| 4 | Talimatla işleme | NetKâr yalnız satıcının talimatıyla işler; kendi amaçları için kullanmaz; anonim ve toplulaştırılmış istatistik istisnası açıkça tanımlanır |
| 5 | Gizlilik | Personel ve yükleniciler gizlilik taahhüdü altındadır |
| 6 | Güvenlik tedbirleri | Ek: şifreleme, erişim kontrolü, loglama, yedekleme, kiracı izolasyonu (bkz. Bölüm 10) |
| 7 | Alt işleyenler | Güncel liste (barındırma, e-posta, hata izleme, LLM, ödeme), ülke bilgisi, değişiklikten en az 15 gün önce bildirim, itiraz hakkı, aynı yükümlülüklerin aktarılması |
| 8 | Yurt dışı aktarım | Hangi alt işleyen hangi ülkede, KVKK m.9 mekanizması (standart sözleşme), Kurum'a bildirimi kimin yapacağı |
| 9 | İlgili kişi başvuruları | NetKâr satıcıya başvurunun cevaplanmasında yardım eder (KVKK m.11, m.13: başvuru en geç 30 günde sonuçlandırılır) |
| 10 | İhlal bildirimi | NetKâr ihlali öğrendiği andan itibaren en geç 24 saat içinde satıcıya bildirir (öneri); içerik: ne oldu, hangi veri, kaç kişi, alınan önlem |
| 11 | Denetim ve bilgi | Yılda bir soru listesi veya özet güvenlik raporu; yerinde denetim makul bildirimle |
| 12 | Saklama ve sona erme | Abonelik bitince veriler X gün (öneri 30) içinde dışa aktarım imkânı, sonra silme ve imha kaydı; yasal saklama gerektiren fatura verisi hariç |
| 13 | API anahtarı yetkisi | Satıcı anahtarı NetKâr'a yalnız okuma amacıyla verir; satıcı istediği an Trendyol panelinden iptal edebilir; NetKâr anahtarı şifreli saklar |
| 14 | Yapay zekâ | LLM'e giden verinin maskelendiği, sağlayıcının veriyi model eğitiminde kullanmadığı (sözleşme dayanağıyla), saklama süresi |
| 15 | Sorumluluk ve rücu | Taraflar kendi kusurları oranında; m.12/2 müşterek sorumluluk saklı |
| 16 | Uygulanacak hukuk ve yetki | Türk hukuku; yetkili mahkeme (ör. İstanbul) |

### 2.3 Son müşteri verisinin minimizasyonu

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Veri ölçülü ve sınırlı olmalı | KVKK m.4/2 (ç) | Trendyol sipariş yanıtındaki ad, soyad, adres, telefon, e-posta alanları ingest sırasında **atılır**, DB'ye ve log'a yazılmaz. Yalnız il ve tuzlu hash müşteri anahtarı (tekrar eden müşteri analizi için) tutulur | MVP öncesi | Yüksek |
| Hash da kişisel veri olabilir | KVKK m.3 (kişisel veri tanımı: kimliği belirlenebilir) | Tuzlu hash takma addır, anonim değildir; tuz kiracı başına ve gizli tutulur; DPA'da "takma adlı veri" olarak belirtilir | MVP öncesi | Orta (genel ilke, Kurul kararı aranmadı) |
| Test ve geliştirme ortamı | KVKK m.12/1 | Gerçek satıcı verisi geliştirme makinesine indirilmez; sentetik veri kullanılır | MVP öncesi | Doğrulanmadı (iyi uygulama) |

### 2.4 Yurt dışına aktarım (2024 değişikliği)

**Ne değişti:** 7499 sayılı Kanun (Resmî Gazete 12.03.2024) KVKK m.9'u yeniden düzenledi; yeni hükümler 01.06.2024'te yürürlüğe girdi, eski açık rıza temelli düzen 01.09.2024'e kadar birlikte uygulandı. Uygulama esasları "Kişisel Verilerin Yurt Dışına Aktarılmasına İlişkin Usul ve Esaslar Hakkında Yönetmelik" ile (RG 10.07.2024, sayı 32598) belirlendi. Kurul 2024/959 sayılı kararıyla dört standart sözleşme seti kabul etti (veri sorumlusundan veri sorumlusuna, veri sorumlusundan veri işleyene, veri işleyenden veri işleyene, veri işleyenden veri sorumlusuna). Kurum Ocak 2025'te Yurt Dışına Aktarım Rehberi yayımladı.

**Kademeli sistem:**

1. **Yeterlilik kararı** (Kurul ülke, sektör veya uluslararası kuruluş için verir, en geç 4 yılda bir değerlendirir). Bu oturumda yayımlanmış bir yeterlilik kararı bulamadım: **doğrulanmadı**.
2. **Uygun güvenceler** (yeterlilik kararı yoksa): standart sözleşme, bağlayıcı şirket kuralları (Kurul onayı gerekir; grup şirketleri için, NetKâr için uygun değil), yazılı taahhütname (Kurul izni gerekir), kamu kurumları arası anlaşma.
3. **Arızi aktarım istisnaları** (ör. riskler hakkında bilgilendirilmiş açık rıza, sözleşmenin ifası): Rehber'e göre olağan faaliyet akışı içindeki tekrarlı aktarımlar arızi sayılmaz (ikincil kaynak). Bir SaaS'ın sürekli barındırma veya LLM akışı arızi değildir.

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Yurt dışına aktarım ancak yeterlilik kararı veya uygun güvenceyle | KVKK m.9 (7499 ile değişik), Yönetmelik RG 10.07.2024/32598: https://www.resmigazete.gov.tr/eskiler/2024/07/20240710.htm | Tüm alt işleyenleri ülke bazında listele (barındırma, CDN/WAF, e-posta, hata izleme, analitik, LLM, ödeme). Her biri için mekanizma seç | MVP öncesi | Yüksek |
| Standart sözleşme metni değiştirilemez; yalnız seçimlik ve alternatif maddeler seçilebilir | Kurum duyurusu (5 Şubat 2025): https://www.kvkk.gov.tr/Icerik/8170/Yurt-Disina-Kisisel-Veri-Aktariminda-Kullanilacak-Standart-Sozlesmelerde-Dikkat-Edilmesi-Gereken-Hususlara-Iliskin-Kamuoyu-Duyurusu ; sözleşme setleri: https://www.kvkk.gov.tr/Icerik/7938/Standart-Sozlesmeler-ve-Baglayici-Sirket-Kurallarina-Iliskin-Dokumanlar-Hakkinda-Kamuoyu-Duyurusu | Sağlayıcıya Kurul'un "veri işleyenden veri işleyene" setini değiştirilmeden imzalatabiliyor musun? Sağlayıcının kendi DPA'sı veya AB SCC'si **yerine geçmez** | MVP öncesi | Orta |
| Standart sözleşme imzadan itibaren **5 iş günü** içinde Kurum'a bildirilir (fiziki, KEP veya Standart Sözleşme Bildirim Modülü) | KVKK m.9 (fıkra no. teyit edilmeli); Kurum duyurusu 5.2.2025; bildirim modülü duyurusu Ekim 2024 | İmza tarihlerini sözleşmeye yaz; bildirim takvimi ve KEP adresi hazırla; değişiklik ve sona ermede de bildirim | Her imzada | Orta |
| Bildirim yapmamanın yaptırımı | KVKK m.18 (2024 değişikliğiyle eklendi); 2026 için yeniden değerlenmiş tutar ikincil kaynakta 90.308 TL ile 1.806.377 TL | Takvim hatası maliyetli; bildirim sorumlusu ata | Sürekli | Düşük (tutar resmî metinden teyit edilmeli) |
| m.9 veri işleyen için de uygulanır | KVKK m.9 son fıkrası (teyit edilmeli); ikincil kaynak: veri işleyenin aktarımı veri sorumlusunun sorumluluğunu kaldırmaz | NetKâr hem kendi verisi için (sorumlu) hem satıcı verisi için (işleyen) aktarımı yapan taraftır; iki ayrı set gerekebilir: "veri sorumlusundan veri işleyene" (kendi kullanıcı verimiz) ve "veri işleyenden veri işleyene" (satıcının alıcı verisi) | MVP öncesi | Orta |

**Bulut sağlayıcı seçeneklerinin KVKK sonucu**

| Seçenek | KVKK sonucu | Artı | Eksi | Güven |
|---|---|---|---|---|
| A. Türkiye'de barındırma (yerel veri merkezi, VPS veya yerel bulut; ör. Turkcell Bulut, Radore, Veridyen; ürünler `04_altyapi_fiyatlari.md`'de, düşük güven) | DB ve uygulama sunucusu için m.9 yok. Ama Cloudflare, Sentry, PostHog, e-posta ve LLM yine yurt dışıysa aktarım devam eder | En temiz anlatı ("verileriniz Türkiye'de"); satıcıya satış argümanı | Fiyat ve kalite belirsiz; yönetilen servis az | Orta |
| B. AB bulutu (Hetzner Almanya/Finlandiya, AWS Frankfurt) + Kurul standart sözleşmesi + 5 iş günü bildirim | AB için yeterlilik kararı bulunamadı; AB de "yurt dışı"dır | Ucuz, kaliteli (Hetzner) | Sağlayıcının Kurul metnini değiştirmeden imzalaması belirsiz; imzalamazsa yasal yol kalmaz | Orta / sağlayıcı tutumu doğrulanmadı |
| C. ABD platformları (Vercel, Supabase, AWS us-east) | B ile aynı rejim; ek olarak ABD erişim riskleri hakkında aydınlatma | Hız | Aynı sözleşme sorunu, daha fazla alt işleyen | Orta |
| D. Hibrit: kişisel veri işleyen her şey Türkiye'de; yurt dışına yalnız kişisel veri içermeyen trafik (statik LP, anonim metrik) | Aktarım yüzeyi en küçük | Esnek | Cloudflare TLS sonlandırırsa oturum çerezi, e-posta, IP adresi yurt dışından geçer; bu da aktarımdır | Orta |

Not: Google Cloud ve Turkcell'in Türkiye bölgesi için 2028-2029 hedefi bildirildi (ikincil kaynak, DatacenterDynamics); MVP için seçenek değildir. Google Cloud'un gizlilik bildirimine KVKK bölümü eklediği üçüncü taraf bir değişiklik takip sitesinde geçiyor; standart sözleşmeyle ilgisi doğrulanmadı.

**Öneri (hipotez, avukatla teyit):** MVP'de seçenek A veya D. Cloudflare yalnız DNS ve statik içerik için kullanılsın ya da Cloudflare ile standart sözleşme yoluna gidilsin. B seçilecekse önce sağlayıcıdan Kurul setini değiştirilmeden imzalayıp imzalamayacağı yazılı olarak sorulmalı.

### 2.5 VERBİS kaydı

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Veri sorumluları sicile kayıt olur; Kurul istisna getirebilir | KVKK m.16; Veri Sorumluları Sicili Hakkında Yönetmelik (RG 30.12.2017): https://www.resmigazete.gov.tr/eskiler/2017/12/20171230.htm | Veri işleyen sıfatıyla kayıt yok; veri sorumlusu sıfatıyla muafiyet kontrolü | Kuruluşta ve her yıl beyanname sonrası | Yüksek |
| İstisna: yıllık çalışan sayısı 50'den az **ve** yıllık mali bilanço toplamı 100 milyon TL'den az, ana faaliyeti özel nitelikli veri işleme olmayan | Kurul 2018/87 kararı, 2023/1154 ile eşik 25 milyon TL'den 100 milyon TL'ye çıktı (RG 25.07.2023) | NetKâr MVP'de büyük olasılıkla muaf | Kuruluşta | Orta |
| 2025 değişikliği: ana faaliyeti özel nitelikli veri olanlar için ayrı ölçüt (çalışan 10'dan az ve bilanço 10 milyon TL'den az) | Kurul 04.09.2025 tarih ve 2025/1572 sayılı kararı; uygulama esasları 2025/2393 (ikincil kaynak) | NetKâr özel nitelikli veri işlemiyor; etkisi yok. Bilanço usulünde defter tutmayanlarda yalnız çalışan sayısı esas alınır (ikincil kaynak) | Bilgi | Orta |
| İstisna diğer yükümlülükleri kaldırmaz | Aynı kararlar | Aydınlatma, güvenlik, ihlal bildirimi, saklama yine geçerli | Sürekli | Yüksek |

### 2.6 Aydınlatma metni ve açık rıza

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Veri toplarken aydınlatma (kimlik, amaç, aktarılan taraflar, toplama yöntemi ve hukuki sebep, m.11 hakları) | KVKK m.10; Aydınlatma Yükümlülüğünün Yerine Getirilmesinde Uyulacak Usul ve Esaslar Hakkında Tebliğ (RG 10.03.2018): https://www.resmigazete.gov.tr/eskiler/2018/03/20180310.htm | Kayıt ekranında ve mobil uygulamada aydınlatma bağlantısı; yurt dışı alt işleyenler ülkeleriyle yazılır. Aydınlatma ile açık rıza aynı metinde birleştirilmez | MVP öncesi | Yüksek (Tebliğ var), ayrıntı Orta |
| Son müşteriyi aydınlatmak satıcının işi | KVKK m.10 (veri sorumlusu yükümlülüğü) | NetKâr satıcıya örnek ifade sunabilir ("sipariş verileriniz kârlılık analizi için hizmet sağlayıcımıza aktarılır"); bu yardım DPA'da yer alır | Lansman | Orta |
| Açık rıza gerekir mi? | KVKK m.5/1, m.5/2 | Hesap, abonelik, fatura: **hayır** (sözleşme ve hukuki yükümlülük). Zorunlu olmayan çerez ve analitik (PostHog): **evet**, ayrı onay. Yurt dışı aktarım için açık rıza ana yol **değildir** (yalnız arızi) | MVP öncesi | Orta |
| Çerezler | KVKK Çerez Uygulamaları Hakkında Rehber (kvkk.gov.tr, 2022; bu oturumda açılamadı) | Zorunlu olmayan çerezler varsayılan kapalı; kabul ve red eşit kolaylıkta | MVP öncesi | Düşük (rehber metni okunmadı) |

### 2.7 Veri ihlali bildirimi

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| İhlal "en kısa sürede" ilgili kişiye ve Kurul'a bildirilir | KVKK m.12/5 | Olay müdahale planı | MVP öncesi | Yüksek |
| "En kısa süre" = öğrenmeden itibaren **72 saat**; gecikmede gerekçe; ilgili kişiye tespitten sonra makul en kısa sürede; Kişisel Veri İhlal Bildirim Formu, bilgiler aşamalı verilebilir | Kurul 24.01.2019 tarih ve 2019/10 sayılı kararı: https://www.kvkk.gov.tr/Icerik/5362/Veri-Ihlali-Bildirimi | Bildirimi **veri sorumlusu** yapar. Alıcı verisinde bu satıcıdır; NetKâr satıcıya 24 saat içinde bilgi verir. Kendi kullanıcı verimizde bildirimi NetKâr yapar | MVP öncesi | Yüksek |
| İhlal bildirimlerinin Kurum sitesinde ilan süresi | Kurul 25.12.2025 tarih ve 2025/2451 sayılı kararı, duyuru 20.01.2026: https://www.kvkk.gov.tr/Icerik/8595/kamuoyu-duyurusu | İtibar riski: ilan edilebilir | Bilgi | Orta |
| Siber olay bildirimi (ayrı rejim) | 7545 sayılı Siber Güvenlik Kanunu (RG 19.03.2025, sayı 32846): https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=7545&MevzuatTur=1&MevzuatTertip=5 | Kapsam siber uzayda hizmet sunan gerçek ve tüzel kişileri içeriyor (ikincil kaynak); NetKâr için bildirim yükümlülüğünün kapsamı ve süresi avukata sorulmalı | Lansman | Düşük |

### 2.8 Saklama ve imha politikası

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Amaç ortadan kalkınca silme, yok etme veya anonimleştirme | KVKK m.7; Kişisel Verilerin Silinmesi, Yok Edilmesi veya Anonim Hale Getirilmesi Hakkında Yönetmelik (RG 28.10.2017): https://www.resmigazete.gov.tr/eskiler/2017/10/20171028.htm | Veri türü bazında saklama tablosu | MVP öncesi | Yüksek |
| Periyodik imha en fazla 6 ay aralıkla; imha kayıtları en az 3 yıl | Aynı Yönetmelik (ikincil kaynak) | Otomatik imha işi (cron) ve imha kaydı tablosu | Lansman | Orta |
| Saklama ve imha politikası yazılı belge | Aynı Yönetmelik m.5 (ikincil kaynak): VERBİS'e kayıtlı olanlar için zorunlu; muaf olanlar için zorunlu değil ama m.4 ilkesi geçerli | Muaf olsak da kısa bir politika yaz; satıcılar ve yatırımcılar ister | Lansman | Orta |
| Fatura ve defter saklama | VUK m.253 (5 yıl, izleyen takvim yılından başlar); TTK m.82 (10 yıl) | Fatura ve ödeme kaydı 10 yıl; bu veri imhadan hariç tutulur | MVP öncesi | Yüksek |

**Saklama tablosu taslağı (öneri)**

| Veri | Süre (öneri) | Gerekçe |
|---|---|---|
| Son müşteri PII | Saklanmaz | Minimizasyon |
| Sipariş, iade, finans satırları (PII'siz) | Abonelik süresi + 30 gün | Hizmet; sonra dışa aktarım ve silme |
| Trendyol API anahtarı | Bağlantı kaldırılınca hemen | Gereksiz risk |
| Kullanıcı hesabı | Hesap kapanınca + 30 gün; sonra silme | Sözleşme |
| Güvenlik ve erişim logları | 1 yıl (öneri) | Olay incelemesi; 5651 sayılı Kanun kapsamı ayrıca avukata sorulmalı (doğrulanmadı) |
| Fatura, ödeme kaydı | 10 yıl | TTK m.82, VUK m.253 |
| LLM istem ve yanıtları | Saklanmaz veya 30 gün (hata ayıklama) | Minimizasyon |

### 2.9 İdari para cezaları (2026, bilgi amaçlı)

Kaynak: Yeniden değerleme oranı %25,49 (RG 27.11.2025, sayı 33090) ile güncellenmiş tutarlar; yalnız ikincil kaynak (Cott Group, Kazım Ceylan Hukuk). **Güven: Düşük, resmî metinden teyit edilmeli.**

| İhlal (KVKK m.18) | 2026 aralığı (TL) |
|---|---|
| Aydınlatma yükümlülüğü | 85.437 ile 1.709.200 |
| Veri güvenliği yükümlülüğü | 256.357 ile 17.092.242 |
| VERBİS kayıt ve bildirim | 341.809 ile 17.092.242 |
| Standart sözleşme bildirimi | 90.308 ile 1.806.377 |

---

## 3. Yapay zekâ kullanımı (müşteri sorusunu ABD'deki LLM API'sine göndermek)

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| LLM sağlayıcısı alt işleyendir; ABD'ye gönderim yurt dışı aktarımdır | KVKK m.9; m.12/2 | Sağlayıcı alt işleyen listesine eklenir; satıcı DPA ile önceden bilgilendirilir | Faz 2 öncesi | Yüksek |
| Aktarım mekanizması | KVKK m.9 (standart sözleşme, 5 iş günü bildirim) | LLM sağlayıcısının Kurul'un "veri işleyenden veri işleyene" setini değiştirmeden imzalayıp imzalamayacağı **doğrulanmadı**. İmzalamazsa kişisel veri gönderilmemeli | Faz 2 öncesi | Orta |
| Anonim veri KVKK kapsamı dışındadır; takma adlı veri değildir | KVKK m.3, m.28/1 (anonim hale getirilmiş veri; teyit edilmeli) | **Maskeleme katmanı:** isim, telefon, e-posta, adres, sipariş no, kargo takip no, TCKN, IBAN düzenli ifade ve NER ile `[AD]`, `[TELEFON]` gibi yer tutuculara çevrilir; eşleme tablosu Türkiye'de kalır; taslak dönünce yer tutucular geri doldurulur. Maskeleme testleri (kırmızı takım örnekleri) CI'da | Faz 2 öncesi | Orta |
| Üretken YZ ve kişisel veriler | Kurum, "Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi (15 Soruda)", 24.11.2025: https://www.kvkk.gov.tr/Icerik/8547/uretken-yapay-zeka-ve-kisisel-verilerin-korunmasi-rehberi-15-soruda ; ayrıca 24.02.2025 duyurusu | Rehber hukuki sebep, yurt dışı aktarım, şeffaflık, ilgili kişi hakları ve güvenlik başlıklarını içeriyor (ikincil kaynak). Avukat rehberi NetKâr akışına göre okumalı | Faz 2 öncesi | Orta (rehber metni bu oturumda okunmadı) |
| Sözleşme önlemleri | Genel ilke | Sağlayıcının API verisini model eğitiminde kullanmadığı, saklama süresi (sıfır veya kısa saklama seçeneği), alt işleyenleri ve güvenlik belgeleri yazılı olarak dosyalanır | Faz 2 öncesi | Doğrulanmadı (sağlayıcı koşulları bu raporda incelenmedi) |
| İnsan kontrolü | Genel ilke; 6563 ve tüketici mevzuatı bakımından cevabı satıcı gönderir | Taslak otomatik gönderilmez; satıcı onaylar. Arayüzde "AI taslağı, kontrol edin" uyarısı. Bu, hatalı veya yanıltıcı cevapta sorumluluğun satıcıda kalmasına da yardım eder | Faz 2 öncesi | Doğrulanmadı (iyi uygulama) |
| Alternatif | Mimari | Türkiye'de barındırılan açık ağırlıklı model veya Türkiye'de hizmet veren LLM sağlayıcısı; maliyet ve kalite ayrıca ölçülmeli | Ölçek | Doğrulanmadı |

**Not:** AB bölgesindeki LLM uç noktası (ör. AB veri yerleşimi) KVKK sorununu çözmez; AB için de yeterlilik kararı bulunamadı.

---

## 4. Ticari elektronik ileti (6563 sayılı Kanun ve İYS)

Dayanak bağlantıları: 6563 sayılı Elektronik Ticaretin Düzenlenmesi Hakkında Kanun, https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6563&MevzuatTur=1&MevzuatTertip=5 ; Ticari İletişim ve Ticari Elektronik İletiler Hakkında Yönetmelik (RG 15.07.2015), https://www.resmigazete.gov.tr/eskiler/2015/07/20150715.htm ; 2020 değişikliği (RG 04.01.2020, sayı 30998), https://www.resmigazete.gov.tr/eskiler/2020/01/20200104.htm

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Ticari elektronik ileti için önceden onay | 6563 m.6 | Bireysel (tüketici) alıcılara pazarlama için onay al ve İYS'ye kaydet | Lansman | Yüksek |
| **Tacir istisnası:** tacir veya esnaf alıcılara önceden onay gerekmez; ret hakkını kullanmışlarsa gönderilemez | Yönetmelik m.6 (fıkra no. teyit edilmeli) | Trendyol satıcıları tacir veya esnaftır; satış e-postası onaysız gönderilebilir, **ama** her iletide kolay ret bağlantısı | Lansman | Orta |
| Tacir ve esnaf adresleri ileti gönderilmeden **İYS'ye kaydedilir** ve ret durumu İYS'den kontrol edilir | Yönetmelik, 2020 değişikliği | Kayıtlı alıcı listesi İYS ile senkron; "tacir" türünde kayıt | Lansman | Orta |
| Hizmet sağlayıcının İYS'ye kaydı; ret bildirimlerinin 3 iş günü içinde İYS'ye iletilmesi | Yönetmelik (ikincil kaynak) | NetKâr İYS'ye kaydolur; e-posta sağlayıcısının ret webhook'u İYS'ye aktarılır | Lansman | Orta |
| Bilgilendirme iletileri (abonelik, fatura, şifre sıfırlama, kâr uyarısı) ticari ileti değildir | Yönetmelik (bilgilendirme amaçlı ileti hükmü; teyit edilmeli) | Ürün bildirimleri ile pazarlama iletilerini teknik olarak ayır; bildirimlere reklam koyma | MVP öncesi | Orta |
| KVKK hukuki sebebi | KVKK m.5/2 (f) meşru menfaat | 6563 tacir istisnası KVKK'yı kaldırmaz; aydınlatma metninde pazarlama amacı ve itiraz hakkı | Lansman | Orta |
| Trendyol alıcılarına NetKâr veya satıcı adına pazarlama | 6563 m.6; Trendyol kuralları (doğrulanmadı) | NetKâr alıcıya hiçbir ileti göndermez; ürün bu özelliği içermez | Sürekli | Orta |

---

## 5. Abonelik satışı, kullanım koşulları ve SLA

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Tüketici: ticari veya mesleki olmayan amaçlarla hareket eden kişi | 6502 sayılı TKHK m.3: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6502&MevzuatTur=1&MevzuatTertip=5 | Satıcı işletmesi için abonelik alan tacir tüketici değildir; Mesafeli Sözleşmeler Yönetmeliği (RG 27.11.2014): https://www.resmigazete.gov.tr/eskiler/2014/11/20141127.htm büyük olasılıkla uygulanmaz. Kayıtta "ticari amaçla kullanıyorum" beyanı ve vergi no alanı | MVP öncesi | Orta (tacir ve karma amaç konusunda açık hüküm yok, ikincil kaynak) |
| B2B'de geçerli rejim | 6098 sayılı TBK: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6098&MevzuatTur=1&MevzuatTertip=5 ; 6102 sayılı TTK: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6102&MevzuatTur=1&MevzuatTertip=5 | Kullanım koşulları TBK ve TTK'ya göre yazılır | MVP öncesi | Yüksek |
| Genel işlem koşulları: karşı tarafa açıkça bildirilmeli ve öğrenme imkânı verilmeli, aksi hâlde yazılmamış sayılır | TBK m.20-21 | Kayıtta koşullar kaydırmalı metin + onay kutusu; onaylanan sürüm ve tarih DB'de saklanır | MVP öncesi | Orta (madde içeriği genel bilgi; ikincil kaynak bulunamadı) |
| Tek taraflı aleyhe değişiklik yetkisi veren kayıtlar yazılmamış sayılır | TBK m.24 | Fiyat artışı ve koşul değişikliği: en az 30 gün önce e-posta + panel bildirimi, yeni dönemde yeniden onay, kabul etmeyene cezasız iptal | MVP öncesi | Orta |
| Abonelik iptali ve otomatik yenileme | B2B için özel kanun hükmü bulunamadı (doğrulanmadı); tüketiciye satış olursa 6502 ve abonelik yönetmeliği devreye girebilir | Panelden tek tıkla iptal, dönem sonuna kadar erişim; yıllık planda yenilemeden 7 gün önce bildirim; aylıkta her tahsilatta e-posta makbuz | MVP öncesi | Doğrulanmadı (iyi uygulama) |
| Sorumluluk sınırlaması | TBK m.115: ağır kusurdan sorumsuzluk önceden kararlaştırılamaz (kesin hükümsüz); hafif kusur için sınırlama mümkün, GİK içinde dürüstlük kuralına aykırı olmamalı (ikincil kaynak, CMS ve Erdem & Erdem) | Bkz. aşağıdaki madde listesi | MVP öncesi | Orta |
| Elektronik ticarette genel bilgi verme | 6563 m.3 | Site künyesi: ticaret unvanı, MERSİS/vergi no, adres, iletişim, meslek odası | Lansman | Orta |
| ETBİS kaydı | Elektronik Ticarette Hizmet Sağlayıcı ve Aracı Hizmet Sağlayıcılar Hakkında Yönetmelik (RG 26.08.2015, sayı 29457) m.16'ya dayanan ETBİS Tebliği m.5 (ikincil kaynak) | Kendi sitesinden hizmet satan hizmet sağlayıcı olarak ETBİS kaydı gerekip gerekmediği avukata sorulmalı; gerekiyorsa faaliyet öncesi kayıt, 30 gün içinde bildirim | Lansman öncesi | Düşük (B2B SaaS'a uygulanma kapsamı net değil) |

**Kullanım koşullarında olması gerekenler (kontrol listesi)**

1. Hizmet tanımı: hesaplamalar Trendyol API'sinden gelen veriye ve satıcının girdiği maliyetlere dayanır; "tahmini" ve "kesinleşmiş" kâr ayrımı açıkça tanımlanır.
2. **Hesaplama sorumluluk reddi:** Sonuçlar karar destek bilgisidir, muhasebe, vergi veya hukuki tavsiye değildir; satıcı kendi muhasebe kayıtlarıyla doğrulamalıdır.
3. Üçüncü taraf bağımlılığı: Trendyol API değişikliği, kesintisi, rate limit veya erişim iptali NetKâr'ın kontrolü dışındadır.
4. Sorumluluk tavanı: hafif kusurda toplam sorumluluk son 12 ayda ödenen abonelik bedeliyle sınırlı (öneri). Kâr kaybı ve dolaylı zarar hafif kusurda hariç. Kast ve ağır kusur saklı tutulur (TBK m.115 gereği yazılmazsa da geçersiz olur).
5. Satıcının yükümlülükleri: doğru maliyet girişi, API anahtarını yetkisiz kişilerle paylaşmama, alıcıları aydınlatma (veri sorumlusu olarak).
6. Ücret, faturalama, KDV dahil/hariç gösterimi, başarısız tahsilatta deneme ve askıya alma süreci.
7. Fiyat ve koşul değişikliği süreci (TBK m.24 uyumlu, yukarıda).
8. Fesih: satıcı her an; NetKâr ağır ihlalde. Fesihte veri dışa aktarımı (CSV) ve silme süresi.
9. Fikrî mülkiyet: yazılım NetKâr'ın; satıcı verisi satıcının; anonim istatistik kullanım hakkı açıkça.
10. Gizlilik Politikası ve Veri İşleme Eki'ne atıf.
11. Uygulanacak hukuk ve yetkili mahkeme; tacirler arası olduğu için yetki sözleşmesi mümkündür (HMK m.17, teyit edilmeli).
12. Mücbir sebep.

**SLA'da olması gerekenler (öneri, doğrulanmadı: iyi uygulama)**

| Konu | Öneri (MVP) |
|---|---|
| Erişilebilirlik hedefi | Aylık %99,5 (planlı bakım hariç); taahhüt değil hedef olarak başlanabilir |
| Planlı bakım | En az 24 saat önce duyuru, düşük trafik saatinde |
| Veri tazeliği | Siparişler 15 dakika, finans ekstresi günde 2 (Trendyol erişilebilir olduğu sürece) |
| Destek | E-posta ve panel içi; iş günlerinde ilk yanıt 1 iş günü |
| Hizmet kredisi | Hedefin altında kalan ayda bir sonraki faturadan indirim; tek çözüm yolu olarak tanımlanır |
| Hariç tutulanlar | Trendyol, ödeme kuruluşu, internet altyapısı kaynaklı kesintiler |
| Yedek ve geri yükleme | RPO 24 saat, RTO 8 saat (iç hedef) |
| Durum sayfası | Herkese açık durum sayfası |

---

## 6. Vergi ve fatura

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| SaaS aboneliği KDV'ye tabi hizmettir; genel oran **%20** | 3065 sayılı KDVK: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=3065&MevzuatTur=1&MevzuatTertip=5 ; CBK 7346 (RG 07.07.2023, sayı 32241; yürürlük 10.07.2023): https://www.resmigazete.gov.tr/eskiler/2023/07/20230707.htm | Fiyat sayfasında "KDV hariç" ve KDV dahil tutar; yazılım hizmetine indirimli oran bulunamadı | MVP öncesi | Yüksek (oranın Kasım 2026'da değişmediği resmî kaynaktan teyit edilmeli) |
| e-Fatura zorunluluğu: brüt satış hasılatı 3 milyon TL ve üzeri (genel); internet üzerinden mal ve hizmet satanlarda 500 bin TL (ikincil kaynak) | VUK 509 Sıra No.lu Genel Tebliğ: https://www.gib.gov.tr | Eşik beklenmeden ilk günden özel entegratör üzerinden e-Fatura + e-Arşiv: müşterilerin çoğu e-Fatura mükellefi olduğundan alıcı tarafında da kolaylık | MVP öncesi | Orta |
| e-Arşiv: 589 Sıra No.lu Tebliğ (RG 31.12.2025) ile 2026'dan itibaren e-Arşiv kapsamında olmayanların faturalarını tutara bakılmaksızın e-Arşiv'den düzenlemesi (ikincil kaynak, Andersen); bir başka kaynak ertelemeden söz ediyor | 509 ve 589 Sıra No.lu Tebliğler | Zaten e-Arşiv kullanılacaksa etkisi yok | MVP öncesi | Düşük (kaynaklar çelişkili) |
| Yurt dışından alınan hizmetler (Hetzner, AWS, LLM API, Vercel vb.) için **sorumlu sıfatıyla KDV** | KDVK m.9 (genel bilgi; teyit edilmeli) | Mali müşavirle 2 No.lu KDV beyannamesi süreci; yurt dışı faturaları aylık topla | İlk yurt dışı ödemede | Orta |
| Yurt dışı yazılım lisansı ödemelerinde vergi kesintisi olasılığı | KVK m.30 / GVK m.94 (genel bilgi) | Bulut ve API hizmetlerinin niteliği mali müşavire sorulmalı | İlk yurt dışı ödemede | Doğrulanmadı |
| Hizmet ihracatı KDV istisnası: hizmet yurt dışındaki müşteri için yapılmalı **ve** hizmetten yurt dışında faydalanılmalı | KDVK m.11/1-a ve m.12/2; KDV Genel Uygulama Tebliği; GİB özelgeleri | Global faz için: müşteri yurt dışı mukimi, fatura yurt dışı müşteri adına, kullanım yurt dışında. Türkiye'de kullanılan kısım KDV'ye tabi olabilir (ikincil kaynak). Bedelin döviz olarak getirilmesi şartı eski tebliğe dayanıyor, güncelliği teyit edilmeli | Ölçek | Orta |
| Defter ve belge saklama | VUK m.253, TTK m.82 | Bkz. 2.8 | Sürekli | Yüksek |

### 6.1 Şahıs işletmesi ve limited şirket (kısa karşılaştırma)

| Kriter | Şahıs işletmesi | Limited şirket | Güven |
|---|---|---|---|
| Vergi | Gelir vergisi artan oranlı tarife (193 sayılı GVK: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=193&MevzuatTur=1&MevzuatTertip=4 ) | Kurumlar vergisi %25 (5520 sayılı KVK m.32: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=5520&MevzuatTur=1&MevzuatTertip=5 ); kâr dağıtımında ayrıca stopaj | Orta (oranlar bu araştırmada ayrıca teyit edilmedi) |
| Genç girişimci istisnası | GVK mük. m.20: 29 yaşını doldurmamış, ilk kez faaliyete başlayan; 3 vergilendirme dönemi; 2026 tutarı ikincil kaynakta 400.000 TL; Bağ-Kur prim desteğinin 2026'da kaldırıldığı iddiası var | Uygulanmaz (gerçek kişi istisnası) | Düşük (tutar ve süre çelişkili) |
| Sorumluluk | Sınırsız, kişisel mal varlığıyla | Ortak sermaye taahhüdüyle sınırlı (TTK); ancak kamu alacaklarında ortaklar ve müdürler için 6183 sayılı Kanun m.35 ve mük. m.35 sorumluluğu (genel bilgi, teyit edilmeli) | Orta |
| Asgari sermaye | Yok | 50.000 TL (CBK 7887, 01.01.2024'ten beri); bir kaynakta 2026'da 100.000 TL iddiası var | Orta (100.000 TL iddiası doğrulanmadı) |
| Kuruluş ve işletme maliyeti | Düşük; basit defter imkânı | Ticaret sicili, bilanço usulü, daha yüksek muhasebe ücreti | Orta |
| Yatırım alma, hisse devri | Uygun değil | Mümkün; ileride A.Ş.'ye tür değiştirme | Orta |
| B2B güven algısı | Daha düşük | Daha yüksek | Doğrulanmadı |

**Not (avukat ve mali müşavire):** Kısa vadede yatırım ve büyük kurumsal müşteri beklenmiyorsa şahıs + genç girişimci istisnası (uygunsa) ucuz başlangıçtır; sorumluluk riski (kâr hesabı hatasında tazminat) limited lehine argümandır.

### 6.2 Teknoloji geliştirme bölgesi (teknokent) kısaca

| Avantaj | Dayanak | Not | Güven |
|---|---|---|---|
| Bölgede yürütülen yazılım, Ar-Ge ve tasarım faaliyetinden elde edilen kazanç gelir ve kurumlar vergisinden istisna, **31.12.2028**'e kadar | 4691 sayılı Kanun geçici m.2: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=4691&MevzuatTur=1&MevzuatTertip=5 (7263 ile uzatıldı, ikincil kaynak) | Yalnız bölgede yapılan faaliyet; bölge dışı iş kapsam dışı | Orta |
| Bölgede üretilen yazılımların teslimi ve kiralanması KDV'den istisna, 31.12.2028'e kadar | KDVK geçici m.20 (ikincil kaynak; özelgede yazılım kiralaması istisna sayılmış) | SaaS'ın "yazılım kiralaması" sayılıp sayılmadığı mali müşavire sorulmalı; bakım ve destek kapsam dışı olabilir. Yüklenilen KDV indirilir ama iade edilmez | Düşük |
| Ar-Ge ve destek personeli ücretlerine gelir vergisi istisnası ve SGK desteği | 4691 (genel bilgi) | Bu araştırmada kaynakla doğrulanamadı | Doğrulanmadı |
| Bedel | Teknokent kira ve başvuru süreci, proje onayı | Ofis maliyeti ve proje raporlama yükü | Doğrulanmadı |

---

## 7. Ödeme altyapısı

| Yükümlülük | Dayanak | NetKâr için ne yapılmalı | Ne zaman | Güven |
|---|---|---|---|---|
| Ödeme hizmeti yalnız bankalar ve TCMB'den izinli ödeme ve elektronik para kuruluşlarınca verilebilir; izinsiz faaliyet suçtur | 6493 sayılı Kanun m.12, m.14, m.28: https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6493&MevzuatTur=1&MevzuatTertip=5 ; TCMB ödeme kuruluşları listesi: https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Temel+Faaliyetler/Odeme+Hizmetleri/Odeme+Kuruluslari | NetKâr yalnız kendi aboneliğinin bedelini tahsil eden **üye işyeridir**; başkası adına para toplamaz, tutmaz, aktarmaz. Seçilen sağlayıcının (iyzico, PayTR, Param) güncel TCMB listesinde olduğu kontrol edilir | MVP öncesi | Orta |
| Model değişirse lisans riski | 6493 | İleride satıcılar adına tahsilat, cüzdan, ödeme dağıtma gibi özellikler eklenirse önce avukat görüşü | Ölçek | Orta |
| Kart verisi sistemlerimize hiç girmemeli | PCI DSS v4.0.1 (PCI SSC): https://www.pcisecuritystandards.org | Ödeme kuruluşunun barındırdığı ödeme sayfası (yönlendirme) en temiz yol; iframe kullanılırsa SAQ A'nın yeni uygunluk ölçütü (ödeme sayfasının betik saldırılarına karşı korunması) devreye girer (ikincil kaynak, SecurityMetrics) | MVP öncesi | Orta |
| Tekrarlayan ödeme ve kart saklama | Ödeme kuruluşunun kart saklama veya abonelik ürünü; banka ve ödeme kuruluşu belgeleri token tabanlı saklamayı tarif ediyor | Kart numarası yerine sağlayıcının kart/kullanıcı token'ı saklanır; PAN, CVV, son kullanma tarihi hiçbir log'da olmaz. Üye işyerinin kart verisini saklamasını yasaklayan özel mevzuat maddesini bulamadım (doğrulanmadı); sağlayıcı sözleşmesi bunu zaten kısıtlar | MVP öncesi | Orta |
| Mobil uygulamada abonelik satışı | App Store ve Google Play politikaları (hukuk değil, platform kuralı) | Faz 1 PWA, ödeme web'de (mimari kararı). Native uygulamada uygulama içi satın alma zorunluluğu ve "çok platformlu hizmet" istisnası ayrıca incelenmeli | Faz 2 | Doğrulanmadı |
| Ödeme kuruluşu KVKK rolü | KVKK m.3 | Ödeme kuruluşu kart verisi için genelde kendisi veri sorumlusudur; aydınlatma metninde aktarılan taraf olarak yazılır | MVP öncesi | Orta |

---

## 8. Marka (TÜRKPATENT)

Dayanak: 6769 sayılı Sınai Mülkiyet Kanunu (SMK): https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6769&MevzuatTur=1&MevzuatTertip=5 ; Türk Patent ve Marka Kurumunca 2026 Yılında Uygulanacak Ücret Tarifesine İlişkin Tebliğ (BİK/TÜRKPATENT: 2026/1, RG 31.12.2025, sayı 33124, 5. mükerrer): https://www.resmigazete.gov.tr/eskiler/2025/12/20251231.htm ; değişiklik 2026/2 (RG 31.10.2026, sayı 33416; yarışma muafiyeti ve bazı KOBİ/YZ patent ücretleri, marka ücretini değiştirdiği görülmedi).

| Konu | Bilgi | Güven |
|---|---|---|
| Sınıf 9 | İndirilebilir yazılım, mobil uygulama | Yüksek (Nice sınıflandırması) |
| Sınıf 35 | İş yönetimi, ticari bilgi ve analiz, e-ticaret danışmanlığı | Yüksek |
| Sınıf 42 | SaaS, yazılım hizmeti, bulut yazılım | Yüksek |
| Sınıf 36 (değerlendir) | Mali analiz ve finansal bilgi hizmetleri kâr hesabına yakın düşebilir | Doğrulanmadı (vekil görüşü) |
| 2026 başvuru ücreti | 1. sınıf 2.820 TL, 2. sınıf 2.820 TL, 3. ve sonraki her sınıf 3.150 TL (ikincil kaynak; başka bir sitede 2.027,17 TL geçiyor) | Düşük |
| Tescil ücreti | 7.010 TL (ikincil kaynak) | Düşük |
| 3 sınıf yaklaşık toplam (resmî ücret) | 2.820 + 2.820 + 3.150 + 7.010 = **15.800 TL** civarı; vekil ücreti hariç | Düşük |
| Süre | Başvuru, inceleme, Bültende ilan, **2 ay itiraz süresi** (SMK m.18), itiraz yoksa tescil; toplamda yaklaşık 6 ile 12 ay (genel bilgi) | Orta (itiraz süresi yüksek, toplam süre doğrulanmadı) |
| Tanımlayıcılık riski | Yalnız malın veya hizmetin cinsini, niteliğini, amacını gösteren işaretler tescil edilmez (SMK m.5/1-c, genel bilgi). "NetKâr" bu riske açık; ayırt edici logo veya farklı bir ad önerilir | Orta (somut değerlendirme vekilde) |

---

## 9. Trendyol tarafı

| Konu | Bulgu | Kaynak | NetKâr için ne yapılmalı | Güven |
|---|---|---|---|---|
| Entegratör kullanımı öngörülüyor | Aracı firma ile çalışılıyorsa User-Agent "Satıcı Id - {Entegrasyon Firması İsmi}", kendi yazılımıysa "Satıcı Id - SelfIntegration"; entegratör adı en fazla 30 alfanümerik karakter | Trendyol Developers, "2. Authorization": https://developers.trendyol.com/docs/2-authorization (arama özetinden) | Her istekte doğru User-Agent; entegratör adı sabit ve marka adıyla uyumlu | Orta |
| Anahtar nerede, kim görür | Satıcı Paneli > Hesap Bilgilerim > Entegrasyon Bilgileri; Satıcı ID, API Key, API Secret yalnız master user (admin rolü) ile görünür. Basic auth (API Key kullanıcı adı, API Secret şifre) | Aynı sayfa | Onboarding'de adım adım görsel rehber; "admin olmayan kullanıcı göremez" uyarısı | Orta |
| Anahtar gizliliği | API bilgilerinin açık platformlarda (GitHub, GitLab) paylaşılmaması gerektiği belirtiliyor | Aynı sayfa | Zarf şifreleme, log maskeleme, sır tarama (Bölüm 10) | Orta |
| Rate limit | Aynı uç nokta için 10 saniyede en fazla 50 istek, aşımda 429 | Aynı sayfa (arama özeti); ticari blogların farklı rakamları güvenilmez | Token bucket + geri çekilme (mimaride var) | Orta |
| Satıcı sözleşmesinde üçüncü taraf yazılıma anahtar verme ve veri paylaşımı kısıtı | **Bulunamadı.** Kamuya açık sözleşme metnine ulaşamadım; arama sonuçları başvuru ve entegrasyon rehberleri | Yok | Bir satıcı hesabından güncel "Pazaryeri Satıcı Sözleşmesi" ve KVKK eklerini indir; avukata şu soruları sor: (1) entegratöre erişim verme, (2) alıcı verisinin amaç sınırı, (3) verinin Trendyol dışında saklanması, (4) toplulaştırılmış kıyas yasağı, (5) Trendyol markasının kullanımı | **Doğrulanmadı** |
| Resmî entegratör veya partner programı | Resmî bir yetkili entegratör listesi veya onay süreci bulunamadı; ticari blogların iddiaları doğrulanmadı | Yok | Trendyol Partner destek kanalına yazılı soru; varsa başvuru | Doğrulanmadı |
| Marka kullanımı | "Trendyol" adı ve logosu Trendyol'un markasıdır (genel bilgi) | Yok | Pazarlamada "Trendyol satıcıları için" gibi tanımlayıcı kullanım; ortaklık ima eden ifade ve logo yok | Doğrulanmadı |
| Pratik gösterge | Paraşüt, İdeasoft, Sentos gibi çok sayıda firma satıcıdan API anahtarı alarak entegrasyon sunuyor | Rehber sayfaları (ikincil) | Sektör pratiği izin olduğunu düşündürür ama sözleşme yerine geçmez | Düşük |

---

## 10. Güvenlik standartları: minimum kontrol listesi

**Çerçeveler (sertifika değil, hizalama):**

| Çerçeve | Güncel sürüm | Kullanım | Güven |
|---|---|---|---|
| OWASP ASVS | **5.0.0**, 30 Mayıs 2025 (Global AppSec EU, Barselona): https://owasp.org/www-project-application-security-verification-standard/ | Seviye 2 = iş uygulamalarının çoğu için hedef. `50_guvenlik.md` 4.0.3'e göre yazılmış; bölüm numaraları 5.0'da değişti, eşleme güncellenmeli | Yüksek (sürüm), Orta (bölüm adları) |
| ISO/IEC 27001 | 2022 sürümü, Ek A 93 kontrol (genel bilgi): https://www.iso.org/standard/27001 | Politika seti ve risk yaklaşımı; sertifika yok | Orta |
| NIST CSF | 2.0, 26 Şubat 2024; yeni "Govern (GV)" fonksiyonu: https://www.nist.gov/cyberframework | Altı fonksiyon: GV, ID, PR, DE, RS, RC | Yüksek |
| CIS Controls | v8.1; 18 kontrol, 153 güvenlik önlemi; IG1 küçük kuruluşlar için temel set (IG1 sayısı 56 olarak bilinir, doğrulanmadı). CIS'in CSF 2.0 eşlemesi: https://www.cisecurity.org/insights/white-papers/cis-controls-v8-1-mapping-to-nist-csf-2-0 | Ekip ve cihaz hijyeni | Orta |
| PCI DSS | v4.0.1 | SAQ A kapsamında kalmak (Bölüm 7) | Orta |

**ISO/IEC 27001 uyumlu politika seti (kısa dokümanlar, her biri 1 ile 2 sayfa):** Bilgi güvenliği politikası; risk değerlendirme yöntemi ve risk kaydı; uygulanabilirlik bildirgesi (SoA) taslağı; varlık ve veri envanteri ile veri sınıflandırma; erişim kontrolü; kriptografi ve anahtar yönetimi; kabul edilebilir kullanım ve uç cihaz; güvenli geliştirme ve değişiklik yönetimi; loglama ve izleme; yedekleme ve iş sürekliliği; tedarikçi ve alt işleyen yönetimi; olay müdahalesi (KVKK 72 saat dahil); saklama ve imha (KVKK).

**MVP için somut 15 madde**

ASVS 5.0 bölüm adları ve ISO Ek A numaraları genel bilgiye dayanır; eşleme bir kez resmî dokümandan kontrol edilmeli.

| # | Kontrol | Somut uygulama | ASVS 5.0 | ISO 27001:2022 Ek A | NIST CSF 2.0 | CIS v8.1 |
|---|---|---|---|---|---|---|
| 1 | Pazaryeri anahtarlarının korunması | AES-256-GCM zarf şifreleme, KEK ayrı yerde (faz 2 KMS), yalnız worker çözer, ekranda gösterilmez, log'a yazılmaz, bağlantı silinince anahtar silinir | V11 Cryptography, V13 Configuration | 8.24 | PR.DS | 3 |
| 2 | Kiracı izolasyonu | Her sorguda tenant_id + PostgreSQL RLS; IDOR test paketi CI'da | V8 Authorization | 8.3 | PR.AA | 6 |
| 3 | Güçlü kimlik doğrulama | argon2id, sızmış parola kontrolü, giriş deneme limiti, hesap sahibine TOTP 2FA, oturum çerezleri HttpOnly/Secure/SameSite | V6 Authentication, V7 Session Management | 8.5 | PR.AA | 5, 6 |
| 4 | Yönetici ve altyapı erişimi | Bulut paneli ve Git için 2FA zorunlu; SSH yalnız anahtar; en az yetki; ayrılan kişinin erişimi 24 saatte kapanır; üç ayda bir erişim gözden geçirme | V13 Configuration | 5.15-5.18, 8.2 | PR.AA, GV.RR | 5, 6 |
| 5 | Veri minimizasyonu ve maskeleme | Son müşteri PII'si ingest'te atılır; log maskeleme filtresi; LLM'e giden metinde PII redaksiyonu | V14 Data Protection | 5.34, 8.11 | PR.DS | 3 |
| 6 | Aktarım ve depolama şifrelemesi | TLS 1.2+, HSTS; disk ve yedek şifreleme | V12 Secure Communication, V11 | 8.24 | PR.DS | 3 |
| 7 | Girdi doğrulama ve çıktı kodlama | Pydantic/Zod şemaları, boyut limitleri, CSV formül enjeksiyonu engeli, ORM parametreli sorgu | V1 Encoding and Sanitization, V2 Validation and Business Logic | 8.28 | PR.PS | 16 (IG2) |
| 8 | Web ön yüz ve API sertleştirme | CSP nonce, güvenlik başlıkları, CSRF koruması, rate limit (IP, kullanıcı, kiracı) | V3 Web Frontend Security, V4 API and Web Service | 8.26, 8.28 | PR.PS | 16 (IG2) |
| 9 | Sır yönetimi | Repo'da sır yok; gitleaks pre-commit + CI; sırların yıllık ve olay sonrası rotasyonu | V13 Configuration | 8.24, 8.4 | PR.DS | 3, 4 |
| 10 | Bağımlılık ve açık yönetimi | Renovate, pip-audit, npm audit, Trivy; kritik açık 7 gün, yüksek 30 gün içinde kapatılır | V15 Secure Coding and Architecture | 8.8 | ID.RA, PR.PS | 7 |
| 11 | Güvenli geliştirme hattı | Branch koruması, zorunlu kod incelemesi, Semgrep, PR şablonunda ASVS L2 kontrol kutuları, büyük özellikte kısa STRIDE tehdit modeli | V15 | 8.25, 8.28, 8.32 | PR.PS, GV.SC | 16 (IG2) |
| 12 | Loglama ve izleme | Giriş, yetki değişikliği, anahtar erişimi, dışa aktarım olayları merkezi log'da; PII'siz; uyarı kuralları; 1 yıl saklama | V16 Security Logging and Error Handling | 8.15, 8.16 | DE.CM, DE.AE | 8 |
| 13 | Yedekleme ve geri dönüş | Günlük şifreli yedek, farklı konumda kopya, ayda bir geri yükleme testi kaydı; RPO 24 saat, RTO 8 saat | V14 | 8.13, 5.30 | PR.DS, RC.RP | 11 |
| 14 | Olay müdahalesi | 1 sayfalık runbook: tespit, sınırlama, kanıt, satıcıya 24 saat, Kurul'a 72 saat (veri sorumlusu olduğumuz veride), iletişim şablonları; yılda bir masa başı tatbikat; `security.txt` | V16 | 5.24-5.28 | RS.MA, RS.CO, RC.RP | 17 |
| 15 | Varlık, alt işleyen ve uç cihaz envanteri | Sunucu, servis, alt işleyen (ülke, sözleşme, standart sözleşme bildirim tarihi) listesi; ekip cihazlarında disk şifreleme, ekran kilidi, otomatik güncelleme | V15 | 5.9, 5.19-5.22, 8.1 | ID.AM, GV.SC | 1, 2, 4, 10, 15 |

---

## 11. Hasan'a sorulacak kararlar

| Kod | Karar | Seçenekler | Etkilediği bölüm | Önerim (hipotez) |
|---|---|---|---|---|
| K-H01 (K-N02) | Barındırma yeri | A Türkiye; B AB + Kurul standart sözleşmesi; D hibrit | 2.4, 10 | A veya D; B ise önce sağlayıcıdan yazılı teyit |
| K-H02 | Cloudflare, Sentry, PostHog, e-posta sağlayıcısının rolü | Yurt dışı alt işleyen olarak sözleşme ve bildirim; yerli veya self-host alternatif; kapsamı daraltma | 2.4 | Kişisel veri geçmeyecek şekilde daralt; geçiyorsa sözleşme yolu |
| K-H03 | Son müşteri PII'si saklanacak mı | Hiç; yalnız il + hash; tam | 2.3 | Hiç saklanmaz (il + tuzlu hash) |
| K-H04 | AI özelliği zamanlaması ve sağlayıcı | ABD API + maskeleme + standart sözleşme; Türkiye'de model; ertele | 3 | Sözleşme yolu netleşene kadar ertele |
| K-H05 | Şirket türü | Şahıs (genç girişimci uygunluğu: yaş ve ilk mükellefiyet); limited; A.Ş. | 6.1 | Mali müşavirle; sorumluluk riski limited lehine |
| K-H06 | Teknokent başvurusu | Şimdi; ilk gelirden sonra; hiç | 6.2 | İlk müşteri doğrulamasından sonra değerlendir |
| K-H07 | Ödeme kuruluşu | iyzico, PayTR, Param | 7 | Barındırılan ödeme sayfası + abonelik/kart saklama ürünü olan, TCMB listesinde teyit edilen |
| K-H08 | Marka adı | NetKâr (tanımlayıcılık riski) veya ayırt edici yeni ad + logo | 8 | Vekil görüşü gelene kadar ad yatırımı yapma |
| K-H09 | Sorumluluk tavanı ve SLA hedefi | 12 aylık ücret; 3 aylık; sabit tutar. %99 / %99,5 | 5 | 12 aylık ücret, %99,5 hedef (taahhüt değil) |
| K-H10 | Fiyat değişikliği ve yenileme politikası | Aylık, yıllık, ikisi | 5 | 30 gün önceden bildirim + yeniden onay |
| K-H11 | Pazarlama kanalları | E-posta, SMS, WhatsApp | 4 | Başta e-posta; İYS kaydı lansmandan önce |
| K-H12 | Trendyol sözleşme incelemesi | Bir satıcı hesabından metni al, avukata ver | 9 | MVP öncesi zorunlu |
| K-H13 | Danışman bütçesi | KVKK avukatı, mali müşavir, marka vekili | Tümü | Lansman öncesi tek seferlik paket teklif al |
| K-H14 | Global zamanlama | Hizmet ihracatı ve GDPR ne zaman | 6 | Türkiye'de ürün-pazar uyumu sonrası |

**Avukata götürülecek ilk 5 soru:** (1) Barındırma ve alt işleyen seçimimizde m.9 için hangi standart sözleşme setleri gerekir, bildirimi kim yapar? (2) Trendyol satıcı sözleşmesi entegratöre erişime ve verinin dışarıda saklanmasına izin veriyor mu? (3) Kullanım koşullarımızdaki sorumluluk sınırı ve fiyat değişikliği hükmü TBK m.20-25 ve m.115 karşısında geçerli mi? (4) ETBİS ve 7545 sayılı Kanun kapsamında yükümlülüğümüz var mı? (5) "NetKâr" tescil edilebilir mi?

---

## 12. Kaynaklar (APA 7)

Erişim tarihi tüm kaynaklar için 5 Kasım 2026'dır. Resmî kaynaklarda bağlantı verilmiş, ancak bu oturumda mevzuat.gov.tr, kvkk.gov.tr ve developers.trendyol.com doğrudan açılamamıştır (bkz. Bölüm 0).

### Resmî kaynaklar

Cumhurbaşkanlığı. (2023, 7 Temmuz). *Katma değer vergisi oranlarının belirlenmesine ilişkin karar (Karar Sayısı: 7346)*. Resmî Gazete, 32241. https://www.resmigazete.gov.tr/eskiler/2023/07/20230707.htm

Elektronik Ticaretin Düzenlenmesi Hakkında Kanun, 6563 sayılı Kanun. (2014). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6563&MevzuatTur=1&MevzuatTertip=5

Gelir İdaresi Başkanlığı. (t.y.). *e-Fatura ve e-Arşiv mevzuatı (VUK 509 Sıra No.lu Genel Tebliğ)*. https://www.gib.gov.tr

Gelir Vergisi Kanunu, 193 sayılı Kanun. (1960). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=193&MevzuatTur=1&MevzuatTertip=4

Katma Değer Vergisi Kanunu, 3065 sayılı Kanun. (1984). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=3065&MevzuatTur=1&MevzuatTertip=5

Kişisel Verileri Koruma Kurumu. (2019). *Veri ihlali bildirimi* [Kurul'un 24.01.2019 tarihli ve 2019/10 sayılı kararı]. https://www.kvkk.gov.tr/Icerik/5362/Veri-Ihlali-Bildirimi

Kişisel Verileri Koruma Kurumu. (2024). *Standart sözleşmeler ve bağlayıcı şirket kurallarına ilişkin dokümanlar hakkında kamuoyu duyurusu*. https://www.kvkk.gov.tr/Icerik/7938/Standart-Sozlesmeler-ve-Baglayici-Sirket-Kurallarina-Iliskin-Dokumanlar-Hakkinda-Kamuoyu-Duyurusu

Kişisel Verileri Koruma Kurumu. (2025, 5 Şubat). *Yurt dışına kişisel veri aktarımında kullanılacak standart sözleşmelerde dikkat edilmesi gereken hususlara ilişkin kamuoyu duyurusu*. https://www.kvkk.gov.tr/Icerik/8170/Yurt-Disina-Kisisel-Veri-Aktariminda-Kullanilacak-Standart-Sozlesmelerde-Dikkat-Edilmesi-Gereken-Hususlara-Iliskin-Kamuoyu-Duyurusu

Kişisel Verileri Koruma Kurumu. (2025, 24 Kasım). *Üretken yapay zekâ ve kişisel verilerin korunması rehberi (15 soruda)*. https://www.kvkk.gov.tr/Icerik/8547/uretken-yapay-zeka-ve-kisisel-verilerin-korunmasi-rehberi-15-soruda

Kişisel Verileri Koruma Kurumu. (2026, 20 Ocak). *Kamuoyu duyurusu* [Kurul'un 2025/2451 sayılı kararı, ihlal bildirimlerinin ilan süresi]. https://www.kvkk.gov.tr/Icerik/8595/kamuoyu-duyurusu

Kişisel Verilerin Korunması Kanunu, 6698 sayılı Kanun. (2016; 7499 sayılı Kanunla değişik, 2024). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6698&MevzuatTur=1&MevzuatTertip=5

Kişisel Verilerin Yurt Dışına Aktarılmasına İlişkin Usul ve Esaslar Hakkında Yönetmelik. (2024, 10 Temmuz). Resmî Gazete, 32598. https://www.resmigazete.gov.tr/eskiler/2024/07/20240710.htm

Kişisel Verilerin Silinmesi, Yok Edilmesi veya Anonim Hale Getirilmesi Hakkında Yönetmelik. (2017, 28 Ekim). Resmî Gazete. https://www.resmigazete.gov.tr/eskiler/2017/10/20171028.htm

Aydınlatma Yükümlülüğünün Yerine Getirilmesinde Uyulacak Usul ve Esaslar Hakkında Tebliğ. (2018, 10 Mart). Resmî Gazete. https://www.resmigazete.gov.tr/eskiler/2018/03/20180310.htm

Kurumlar Vergisi Kanunu, 5520 sayılı Kanun. (2006). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=5520&MevzuatTur=1&MevzuatTertip=5

Mesafeli Sözleşmeler Yönetmeliği. (2014, 27 Kasım). Resmî Gazete. https://www.resmigazete.gov.tr/eskiler/2014/11/20141127.htm

Ödeme ve Menkul Kıymet Mutabakat Sistemleri, Ödeme Hizmetleri ve Elektronik Para Kuruluşları Hakkında Kanun, 6493 sayılı Kanun. (2013). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6493&MevzuatTur=1&MevzuatTertip=5

Sınai Mülkiyet Kanunu, 6769 sayılı Kanun. (2016). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6769&MevzuatTur=1&MevzuatTertip=5

Siber Güvenlik Kanunu, 7545 sayılı Kanun. (2025). Resmî Gazete, 32846. https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=7545&MevzuatTur=1&MevzuatTertip=5

Teknoloji Geliştirme Bölgeleri Kanunu, 4691 sayılı Kanun. (2001). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=4691&MevzuatTur=1&MevzuatTertip=5

Ticari İletişim ve Ticari Elektronik İletiler Hakkında Yönetmelik. (2015, 15 Temmuz). Resmî Gazete. https://www.resmigazete.gov.tr/eskiler/2015/07/20150715.htm

Ticari İletişim ve Ticari Elektronik İletiler Hakkında Yönetmelikte Değişiklik Yapılmasına Dair Yönetmelik. (2020, 4 Ocak). Resmî Gazete, 30998. https://www.resmigazete.gov.tr/eskiler/2020/01/20200104.htm

Tüketicinin Korunması Hakkında Kanun, 6502 sayılı Kanun. (2013). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6502&MevzuatTur=1&MevzuatTertip=5

Türk Borçlar Kanunu, 6098 sayılı Kanun. (2011). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6098&MevzuatTur=1&MevzuatTertip=5

Türk Patent ve Marka Kurumu. (2025, 31 Aralık). *Türk Patent ve Marka Kurumunca 2026 yılında uygulanacak ücret tarifesine ilişkin tebliğ (BİK/TÜRKPATENT: 2026/1)*. Resmî Gazete, 33124 (5. mükerrer). https://www.resmigazete.gov.tr/eskiler/2025/12/20251231.htm

Türk Ticaret Kanunu, 6102 sayılı Kanun. (2011). https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6102&MevzuatTur=1&MevzuatTertip=5

Türkiye Cumhuriyet Merkez Bankası. (t.y.). *Ödeme kuruluşları*. https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Temel+Faaliyetler/Odeme+Hizmetleri/Odeme+Kuruluslari

Veri Sorumluları Sicili Hakkında Yönetmelik. (2017, 30 Aralık). Resmî Gazete. https://www.resmigazete.gov.tr/eskiler/2017/12/20171230.htm

### Standartlar ve platform dokümanları

Center for Internet Security. (2024). *CIS Controls v8.1 mapping to NIST CSF 2.0*. https://www.cisecurity.org/insights/white-papers/cis-controls-v8-1-mapping-to-nist-csf-2-0

International Organization for Standardization. (2022). *ISO/IEC 27001:2022 Information security, cybersecurity and privacy protection: Information security management systems: Requirements*. https://www.iso.org/standard/27001

National Institute of Standards and Technology. (2024, 26 Şubat). *The NIST Cybersecurity Framework (CSF) 2.0*. https://www.nist.gov/cyberframework

OWASP Foundation. (2025, 30 Mayıs). *Application Security Verification Standard 5.0.0*. https://owasp.org/www-project-application-security-verification-standard/

PCI Security Standards Council. (2024). *PCI DSS v4.0.1*. https://www.pcisecuritystandards.org

Trendyol. (t.y.). *2. Authorization*. Trendyol Developers. https://developers.trendyol.com/docs/2-authorization

### İkincil kaynaklar

Alomaliye. (2025, 31 Aralık). *Türk Patent ve Marka Kurumunca 2026 yılında uygulanacak ücret tarifesi*. https://www.alomaliye.com/2025/12/31/turk-patent-ve-marka-kurumunca-2026-yilinda-uygulanacak-ucret-tarifesi/

Alomaliye. (2026, 31 Ekim). *TÜRKPATENT 2026 ücret tarifesinde değişiklik (BİK/TÜRKPATENT: 2026/2)*. https://www.alomaliye.com/2026/10/31/turkpatent-2026-ucret-tarifesinde-degisiklik-bik-turkpatent-2026-2/

Andersen Türkiye. (2026). *e-Belgelerle ilgili değişiklikler* [Sirküler 62]. https://tr.andersen.com/tr/images/pdf/and_62-ebelgelerle-ilgili-degisiklikler.pdf

CMS. (t.y.). *Limitations and exclusions of liability in business to business contracts in Türkiye*. https://cms.law/en/int/expert-guides/limitations-and-exclusions-of-liability-in-b2b-contracts/turkiye

Cott Group. (2026). *Yeniden değerleme oranına göre 2026 yılı KVKK idari para cezaları*. https://cottgroup.com/tr/mevzuat/item/yeniden-degerleme-oranina-gore-2026-yili-kvkk-idari-para-cezalari

Cott Group. (t.y.). *Standart sözleşme bildirim yükümlülüğü ve yaptırımları*. https://cottgroup.com/tr/blog/kvkk-gdpr/item/standart-sozlesme-bildirim-yukumlulugu-ve-yaptirimlari

DatacenterDynamics. (2026). *Google and Turkcell team up for cloud region and data center in Türkiye*. https://www.datacenterdynamics.com/en/news/google-and-turkcell-team-up-for-cloud-region-and-data-center-in-türkiye/

Erdem & Erdem. (t.y.). *Kişisel verilerin yurt dışına aktarılmasında yaşanan son gelişmeler*. https://www.erdem-erdem.av.tr/bilgi-bankasi/kisisel-verilerin-yurt-disina-aktarilmasinda-yasanan-son-gelismeler

Erdem & Erdem. (t.y.). *VERBİS kayıt yükümlülüğüne ilişkin yeni istisnaların uygulama esasları açıklandı*. https://www.erdem-erdem.av.tr/bilgi-bankasi/verbis-kayit-yukumlulugune-iliskin-yeni-istisnalarin-uygulama-esaslari-aciklandi

Erdem & Erdem. (t.y.). *Siber Güvenlik Kanunu 101*. https://www.erdem-erdem.av.tr/bilgi-bankasi/siber-guvenlik-kanunu-101

Erdem & Erdem. (t.y.). *Borçlar Kanunu hükümleri uyarınca sorumsuzluk anlaşmaları*. https://www.erdem-erdem.av.tr/bilgi-bankasi/borclar-kanunu-hukumleri-uyarinca-sorumsuzluk-anlasmalari

Kobitime. (2026). *Marka tescili nasıl yapılır 2026*. https://kobitime.com/marka-tescili-nasil-yapilir-2026/

KPMG Türkiye. (t.y.). *Anonim ve limited şirketlerde asgari sermaye tutarına uyum süresi 31 Aralık 2026'da sona eriyor*. https://kpmgvergi.com/yayinlar/mali-bultenler/vergi/anonim-ve-limited-sirketlerde-asgari-sermaye-tutarina-uyum-suresi-31-aralik-2026da-sona-eriyor/4518

Paraşüt. (t.y.). *e-Fatura ve e-Arşiv zorunluluğu*. https://www.parasut.com/blog/e-fatura-ve-e-arsiv-zorunlulugu

SecurityMetrics. (t.y.). *SAQ A unpacked: What merchants actually need to know*. https://www.securitymetrics.com/learn/saq-a-unpacked-what-merchants-actually-need-to-know

İdeaSoft. (2026). *E-ticarette e-fatura zorunluluğu 2026: Güncel limitler ve cezalar*. https://www.ideasoft.com.tr/e-ticaret-icin-e-fatura-zorunlulugu/
