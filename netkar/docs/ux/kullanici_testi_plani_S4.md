# S4 Panel UI: 5 kişilik kullanılabilirlik testi planı

- Sürüm: v0.1 taslak, 14 Kasım 2026
- Hazırlayan: UX araştırmacısı (Claude). Moderatör: Hasan (bkz. §1.2 madde 4 ve §8 madde 2)
- Bu plan yol haritasındaki S4 "bitti" ölçütlerinden **"5 kullanıcı testi"** için yazıldı (`docs/30_yol_haritasi.md`, S4 satırı).
- Dayanak: panel kodu (`apps/web/src/app/(app)/panel/*` ve `components/profit`, `components/settings`, `components/panel`), `docs/12_kar_motoru.md` (K37, K39 Revizyon 1, §7.4, §9 madde 23), `docs/ux/inceleme_2026-11-10_panel_ozet_urunler.md` (§9, 5 senaryo) ve `inceleme_2026-11-10_ayarlar_formu.md`, `docs/karar_kaydi.md` (K-N06), `docs/research/03_hukuk_ve_uyum.md`.
- Bu belge koda dokunmaz. Görevlerdeki ekran adları, düğme ve rozet metinleri koddan birebir alındı. Kodda olmayan hiçbir özellik göreve konmadı.

> Üç kırmızı bayrak, ayrıntısı ilgili bölümde: (1) staging yok, demo veri yok (§7.1); (2) KVKK metinlerini avukat onaylamadan kayıt başlamaz (§3); (3) ürün maliyeti girişi arayüzde henüz yok ("yakında"), gerçek satıcılar ilk bunu soracak (G2, G7 ve §8).

---

## 0. Özet

| Başlık | Karar |
|---|---|
| Amaç | S4 panelinin (Özet, Ürünler, Siparişler, Uyarılar, Ayarlar) muhasebeci olmayan bir Trendyol satıcısı tarafından yardımsız kullanılabildiğini ve en riskli iki rakamın (kısmi dönemde "eksik giderler hariç dönem kârı", "Tahmini" kâr) yanlış okunmadığını görmek |
| Kim | 5 katılımcı: Hasan (kendi mağazası), 1 beta satıcı, büyüklük ve kategorisi farklı 3 Trendyol satıcısı |
| Yöntem | Moderatörlü, sesli düşünme, bire bir, uzaktan ekran paylaşımı ya da yüz yüze |
| Süre | Katılımcı başına 35-40 dk (görev süreleri sınırlı, bkz. §4 ve §7) |
| Görev | 8 görev (G1-G8). G8, G4 ve G6'nın 390 px telefon sürümüdür |
| Ölçü | Görev başarısı, süre, hata sayısı, görev sonrası SEQ (1-7), oturum sonu SUS, 3 ürün sorusu |
| Başarı ölçütü | §0.1'de |
| Veri | Yalnız demo hesap (A: ayarsız, B: ayarlı). Gerçek mağaza verisi yalnız sahibinin yazılı onayıyla ve tercihen kayıt dışında |
| Çıktı | Ham gözlem tablosu, bulgu listesi (Nielsen 0-4), S4 sonuç notu; docs/12 §9 madde 23 ve ADR-0007 §7 madde 3'e cevap |
| Bağımlılık | Staging + demo veri tohumu (yok), KVKK metin onayı, Hasan'ın moderatörlük çekincesi |

### 0.1 Başarı ölçütleri (bu tur için)

n=5 ile yüzde ya da istatistiksel anlamlılık iddia edilmez; sayılar "5 kişiden kaçı" diye raporlanır. Aşağıdakiler ekibin kendi eşikleridir, literatürden alınmış hedef değildir.

1. **G1 (kısmi dönem rakamı):** "Eksik giderler hariç dönem kârı"nı net kâr diye okuyan katılımcı sayısı 0/5. Kargo ve hizmet bedelini girmesi gerektiğini söyleyen 5/5.
2. **G2 (kurulum):** Hizmet bedeli ve kargo tarifesini yardımsız kaydeden en az 4/5.
3. **G3 (geçmişi etkileyen onay):** "Geçmiş raporlar değişecek" penceresinin sonucunu doğru anlatan en az 4/5.
4. **G4 ve G8a (zarar eden ürün):** Doğru ürüne 60 sn içinde ulaşan en az 4/5, hem masaüstünde hem telefonda.
5. **G5 ve G6:** Kalem dökümünü doğru okuyan ve "Ekstresi gelmeyen" ile "Beklenmeyen kesinti" süzgeçlerini bulan en az 4/5.
6. **SEQ:** Hiçbir görevde ortalama 5'in altına düşmemesi. 5'in altı bulgu açar.
7. **SUS:** Ortalama en az 68 (Sauro ve Lewis'in sık anılan "ortalama" eşiği; n=5'te yalnız yön gösterir).
8. Önem 4 (felaket) bulgu sayısı 0; önem 3 bulguların hepsi iş kartına dönüşmüş.

**"Bitti" sayılması için:** 5 oturum tamamlandı, notlar §6'daki tabloda dolduruldu, bulgular önem puanlandı, `docs/12` §9 madde 23 ve ADR-0007 §7 madde 3'e kısa cevap yazıldı, önem 3-4 bulgular iş kartı oldu.

---

## 1. Yöntem

### 1.1 Format

- **Moderatörlü, sesli düşünme (think-aloud).** Katılımcı yapmak istediğini ve ne düşündüğünü yüksek sesle söyler. Moderatör yönlendirmez, ekranı anlatmaz.
- **Bire bir**, uzaktan (görüntülü görüşme + ekran paylaşımı) ya da yüz yüze. Telefon görevleri (G8) için gerçek telefon tercih edilir. Uzaktan yapılıyorsa katılımcının telefon ekranını görüşme uygulamasından paylaşması istenir. Bunun kullandığınız uygulamada sorunsuz çalıştığını ilk oturumdan önce deneyin; çalışmazsa 390 px tarayıcı penceresi yedektir ve bu, bulguda not edilir (dokunma hedefi ve kaydırma davranışı gerçek cihazdan farklı olabilir).
- **Süre:** 35-40 dk. Zaman aşımına uğrayan görev sonlandırılır ve "başarısız (süre)" yazılır. Detay §7.2.
- **Dil:** Türkçe. Görev metinleri katılımcıya yüksek sesle okunur ve ekranda yazılı olarak da paylaşılır (sohbet kutusu ya da kâğıt).
- **Veri:** Katılımcı kendi mağazasını değil, demo hesapları kullanır (§7.1). Böylece rakamlar bizim bildiğimiz rakamlardır ve "doğru cevap" tanımlıdır.

### 1.2 Neden 5 kişi

Seçim üç şeye dayanıyor: ekip küçük, ilk turda amaç ölçmekten çok **kullanılabilirlik sorunlarını bulmak**, ve düzelt-tekrar-dene döngüsü bir kez büyük bir test yapmaktan ucuz.

Dayanak Nielsen ve Landauer (1993): bulunan sorun sayısını `N x (1 - (1 - λ)^n)` biçiminde modelliyor; `λ`, tek bir kullanıcının bir sorunu bulma olasılığı, `n` kullanıcı sayısı. Makalenin incelediği projelerde ortalama `λ` yaklaşık %31 çıkıyor (rakamı makalenin kendisinden teyit edin, ben sık anılan değeri aktarıyorum). Bu ortalamayla 5 kullanıcı sorunların kabaca %85'ini yakalıyor. Virzi (1992) benzer bir sonuca ayrı bir veriyle ulaşmıştı.

**Sınırları, dürüstçe:**

1. **`λ` projeye göre değişir.** Ortalama %31 bir ortalamadır. Kullanıcılar birbirinden çok farklıysa ya da sorunlar nadir görevlerde saklıysa `λ` çok daha düşük olur ve 5 kişi sorunların büyük bölümünü kaçırır. Spool ve Schroeder (2001) web sitelerinde 5 kişinin çok az olduğunu gösteren bir karşı örnek yayımladı.
2. **Model sorun bulmayı anlatır, ölçmeyi değil.** "5 kişiden 4'ü başardı" cümlesi tahmin değil gözlemdir; güven aralığı çok geniştir. Bu yüzden yüzde vermiyor, süre ve SUS için ortalamayı "yön" olarak okuyoruz.
3. **Farklı kullanıcı grupları ayrı örneklem ister.** Ajans (Persona C) ve büyük hacimli satıcı bu turun dışında. Sonuçlar yalnız Persona A ve B için geçerlidir (`docs/research/05_pazarlama_gtm.md` §2.5).
4. **Katılımcılardan biri ürünün sahibi.** Hasan ürünü zaten biliyor; "ilk bakış" ve "etiket anlaşılırlığı" görevlerinde saf kullanıcı gibi davranamaz. Bu yüzden bağımsız saf kullanıcı sayısı fiilen 4'tür. Çözüm: Hasan'ın oturumu yapılır ama G1, G6 gibi "anlama" görevlerinde sonuçları ayrı işaretlenir ve başarı sayımında ayrıca belirtilir (§6). Süre ve SUS ortalamaları hesaplanırken Hasan'lı ve Hasan'sız iki rakam raporlanır.
5. **Beta satıcı da ürünü görmüş olabilir** (K-N06). Öğrenme etkisi varsa notta belirtilir.
6. **Tek tur yetmez.** Önem 3-4 bulgular düzeltilince 3-5 kişilik ikinci bir tur planlanmalı (S4 sonrası, kapsam dışı).

### 1.3 Katılımcı kotası

| No | Kim | Not |
|---|---|---|
| P1 | Hasan | Kendi mağazası olduğu için "gerçek veri merakı" yüksek; ayrı notla (§1.2 madde 4) |
| P2 | Beta satıcı | K-N06'daki 1 beta satıcı. Test için ayrı onay gerekir, beta sözleşmesi yerine geçmez |
| P3-P5 | Bağımsız 3 Trendyol satıcısı | Aynı anda en az: 1 küçük (aylık ~300 siparişin altı) ve 1 orta/büyük (~1.000+); en az 2 farklı kategori; en az 1 "kendi kargo anlaşmam" kullanan; en az 1 kârını Excel ile tutan; en az 2 günlük işini çoğunlukla telefondan yapan |

K-N06 "pilot hesap" ve "beta satıcı" sayısını sınırlar. Bu test **mağaza bağlamaz**, demo veriyle çalışır; bu yüzden P3-P5 için K-N06 ihlali yoktur. Yine de P2'nin kendi mağazasını bağlaması gerekirse bu K-N06 kapsamındadır.

---

## 2. Katılımcı alım formu (screener)

Her soru bir kota ya da dışlama kararına bağlıdır.

| # | Soru | Neden / karar |
|---|---|---|
| 1 | Trendyol'da aktif satış yapıyor musunuz? Kaç aydır? | Hayır ise dışla. 3 aydan az ise not al (deneyimsiz grup) |
| 2 | Ayda yaklaşık kaç sipariş alıyorsunuz? (<100, 100-300, 300-1.000, 1.000-5.000, 5.000+) | Büyüklük kotası; 5.000+ dışla (bu tur kapsamı değil) |
| 3 | Hangi ürün kategorisinde satıyorsunuz? | Kategori çeşitliliği |
| 4 | Siparişleri Trendyol anlaşmalı kargoyla mı, kendi kargo anlaşmanızla mı gönderiyorsunuz, ikisi de mi? | "Kendi kargo anlaşmam" kotası; Ayarlar'daki "Kargo anlaşması" seçimi için |
| 5 | Kârınızı şu an nasıl takip ediyorsunuz? (Excel, Trendyol paneli, ön muhasebe programı, takip etmiyorum, diğer) | Mevcut alışkanlık; rekabet ve beklenti |
| 6 | Ürünlerinizin alış maliyetini biliyor musunuz, bir yerde kayıtlı mı? | Maliyet girişinin henüz olmadığı gerçeği için önemli |
| 7 | Günlük satıcı işinizi çoğunlukla hangi cihazdan yapıyorsunuz? (telefon, bilgisayar, ikisi) | Cihaz kotası, G8 sırası |
| 8 | Görüntülü görüşmede ekran (ve mümkünse telefon ekranı) paylaşabilir misiniz? Sessiz bir ortamınız var mı? | Uzaktan uygunluk |
| 9 | Muhasebeci, mali müşavir, e-ticaret ajansı olarak mı çalışıyorsunuz? | Evet ise dışla (Persona C, bu tur kapsamı dışı) |
| 10 | Trendyol çalışanı mısınız ya da NetTablo'a benzer bir ürün geliştiriyor ya da satıyor musunuz? | Evet ise dışla (çıkar çatışması) |
| 11 | NetTablo ekranlarını daha önce gördünüz mü? | Evet ise P2 gibi işaretle |

Alım kanalları (Hasan karar verir): Hasan'ın kendi çevresi, satıcı topluluk grupları (grup kurallarına bakın), bekleme listesi. **Bekleme listesi uyarısı:** listeye yazılanlar büyük olasılıkla yalnız duyuru için iletişim izni verdi (`components/waitlist/waitlist-form.tsx` metnine bakılmadı, kontrol edilmeli); araştırma daveti için ayrı izin gerekebilir. **[Avukat/Hasan teyidi]**

---

## 3. KVKK ve etik

> Bu bölüm hukuki görüş değildir. Aşağıdaki **[A]** işaretli her madde avukat, **[H]** işaretli her madde Hasan teyidi ister. Teyit gelmeden kayıt başlamaz.

### 3.1 Ne kaydedilir

| Veri | Kaydedilir mi | Not |
|---|---|---|
| Ekran paylaşımı görüntüsü | Evet, açık rıza ile | Demo veri gösterildiği sürece mağaza verisi yok |
| Katılımcının sesi | Evet, açık rıza ile | Ses, kişisel veridir (kişi tanınabilir) |
| Katılımcının yüzü (kamera) | Hayır. Kamera kapalı kalır | Gereksiz veri; yüz ifadesi gerekirse moderatör nota yazar |
| Ad, e-posta, telefon | Yalnız iletişim için ayrı listede | Notlarda P1-P5 kodu kullanılır, ad geçmez |
| Satıcı numarası, API anahtarı | Hayır. Katılımcı kendi anahtarını bu testte girmez | Demo hesaplar |
| Son müşteri kişisel verisi (ad, adres, telefon) | **Ekranda hiç görünmemeli** | Panel zaten son müşteri PII'si saklamıyor (`docs/research/03_hukuk_ve_uyum.md` §2.3), ama demo veride sipariş numarası ve ürün adı dışında alan yok. Hasan'ın gerçek mağaza verisi gösterilirse sipariş numaraları da maskelenmeli **[H]** |

### 3.2 Gerçek mağaza kullanımı

- Varsayılan: **demo veri**. Gerçek mağaza yalnız: (a) Hasan'ın kendi mağazası (K-N06; anahtar yalnız staging'e şifreli girer), (b) beta satıcının kendi mağazası, yalnız o satıcının ayrı, yazılı ve geri alınabilir onayıyla.
- Gerçek mağaza oturumları **kaydedilmez ya da ekran kaydı yalnız demo bölümlerde açık kalır**; gerçek veri bölümünde kayıt duraklatılır. Gerçek veriyle yapılacak gezinme en fazla 5 dakikadır, sonunda "benim gerçek rakamlarım mı?" gibi güven sorularını sormak içindir.
- Satıcının satış, kâr ve ürün bilgisi ticari sırdır. Demo veriyle bile ekranda görünen rakamların uydurma olduğu açıkça söylenir. Gerçek mağaza kullanılırsa notlara ve raporlara rakam yazılmaz, yalnız davranış yazılır.

### 3.3 Aydınlatma ve açık rıza (iki ayrı metin)

`docs/research/03_hukuk_ve_uyum.md` §2.6'daki ilkeye uygun olarak aydınlatma ile açık rıza **aynı metinde birleştirilmez**. İkisi de **[A]** onayıyla kesinleşir; aşağıdakiler taslaktır.

**Aydınlatma metni (taslak):**

> Bu çalışmada, [veri sorumlusunun adı/unvanı **[H]**] olarak NetTablo panelinin kullanım kolaylığını incelemek amacıyla görüşme sırasındaki ekran görüntünüzü ve sesinizi kaydediyoruz. Ayrıca iletişim bilginizi (ad, e-posta ya da telefon) görüşmeyi planlamak için tutuyoruz. Kayıtları yalnız ürün ekibi inceler; üçüncü kişilerle ya da yurt dışındaki hizmetlerle paylaşmayız. [Kayıt ve toplantı aracı yurt dışında barındırılıyorsa burada açıkça yazılmalı **[A]**] Verileriniz 6698 sayılı Kişisel Verilerin Korunması Kanunu'nun 11. maddesindeki haklara tabidir: bilgi isteme, düzeltme, silme ve itiraz hakkınız vardır. İletişim: [e-posta **[H]**].

**Açık rıza metni (taslak, ayrı onay kutusuyla):**

> ☐ Bu görüşmede ekran görüntümün ve sesimin kaydedilmesine, kaydın yalnız ürünü geliştirmek için yukarıda belirtilen süre boyunca saklanmasına açık rıza veriyorum.
> ☐ Söylediklerimin adım ve mağazam anılmadan, kısa alıntılar olarak iç raporlarda kullanılmasına izin veriyorum.
> Katılım gönüllüdür. İstediğim an, gerekçe göstermeden görüşmeyi bırakabilirim ve kaydın silinmesini isteyebilirim; bu durumda hiçbir olumsuz sonuç doğmaz.

Katılımcının görüşme başında yüksek sesle "kayda başlıyorum, onaylıyor musunuz?" sorusuna evet demesi de kayıt altına alınır.

### 3.4 Saklama süresi (öneri)

| Veri | Öneri | Not |
|---|---|---|
| Ham ekran ve ses kaydı | Oturumdan en geç **60 gün** sonra silinir (analiz ve bulgu yazımı için yeterli) | Süreyi **[A]** doğrulasın. Silme tarihi iş kartına yazılır |
| Anonim gözlem notları (P1-P5 kodlu) | Ürün geliştirme süresince | Ad ve mağaza adı geçmez |
| İletişim listesi | Görüşme tamamlandıktan sonra en fazla 30 gün | `docs/research/03` §2.8'deki saklama ve imha ilkeleriyle uyumlu olsun **[A]** |
| Rıza formları | Rıza kaydı olduğu için kayıtlar silinse bile ispat amacıyla saklanmalı mı? | **[A]** karar versin |

### 3.5 Yapay zekâ ve yurt dışı aktarım

Kayıtları ya da döküm metinlerini bir yapay zekâ servisine yüklemek yurt dışına aktarım olabilir (K-N08'deki ilkeyle aynı mantık). Bu planda **ham kayıt ve döküm hiçbir yapay zekâ servisine yüklenmez**. Claude'a yalnız anonimleştirilmiş (P1-P5 kodlu, ad ve mağaza adı çıkarılmış, rakamsız) gözlem notları verilir. Bu sınırı genişletmek **[A]** kararı ister.

### 3.6 Katılımcıya söylenecekler (oturum öncesi)

Teşekkür için küçük bir karşılık (ör. kurucu üye indirimi, K-N05) verilecekse Hasan karar verir **[H]**. Karşılık, ödeme beklentisi sorusuna (§5.3) etki edebilir; ürün sorularını teşekkürden önce sorun.

---

## 4. Görevler

### 4.0 Genel kurallar

- Katılımcıya "sizi değil ekranı test ediyoruz" denir. Doğru ya da yanlış yoktur.
- Moderatör görev metnini okur, katılımcı "bitirdim" diyene ya da süre dolana kadar susar. Sorulara "ne yapardınız?" diye karşılık verir.
- **İpucu merdiveni** (sayılır, bkz. §5): (1) "Ne yapmayı düşünüyorsunuz?" (2) tarafsız ipucu ("Menüye bir bakın") (3) ekranı gösterme. 3. basamakta görev "başarısız" sayılır ve devam edilir.
- Görevler G1'den G8'e sırayla yapılır. G4 ve G6'nın telefon sürümü (G8) için sıra P2 ve P4'te değişir (§4.9).
- İki demo hesap kullanılır: **Hesap A** (ayarsız, yeni bağlanmış) G1-G3'te; **Hesap B** (ayarlı, dolu) G4-G8'de. Hesap geçişi G3 sonrasında tek seferdir. Ayrıntı §7.1.

### G1. Özet ekranına ilk bakış (Hesap A, kısmi dönem)

- **Ekran:** `/panel` (Özet), "30 gün" seçili.
- **Senaryo (okunur):** "Trendyol mağazanızı NetTablo'a bağladınız ve paneli ilk kez açıyorsunuz. Ekrana bir bakın ve gördüklerinizi anlatın. Son 30 günde kâr ettiniz mi? Ne kadar?"
- **Hazırlık:** Kargo ve hizmet bedeli girilmemiş, ürün maliyetleri tohumda dolu (§7.1), kısmi dönem. P1-P3'te bilinen kâr pozitif, P4-P5'te negatif ("Bilinen giderlerle bile zarar" rozetli) varyant (isteğe bağlı).
- **Ekranda ne var (koddan):** başlık "Dönem net kârı hesaplanamadı", "Eksik giderler hariç dönem kârı" + "(kargo ve hizmet bedeli hariç)" + "Kargo ve hizmet bedeli düşülünce bu rakam azalır.", uyarı kutusu "Net kârı görmek için kargo tarifesini ve hizmet bedelini girin" ve düğmeler "Kargo tarifesini gir", "Hizmet bedelini gir", "Eksiksiz satırların net kârı", altında "Zarar ettiren ürünler".
- **Başarı:** Katılımcı bilinen rakamı "net kâr" diye söylemez; rakamın eksik giderler hariç olduğunu ve kargo ile hizmet bedeli girilince azalacağını söyler; ekranın kendinden ne istediğini (kargo tarifesi, hizmet bedeli) söyler.
- **Gözlem:**
  - Gözün ilk gittiği yer (rakam mı, uyarı kutusu mu), rakama yeşil-kırmızı anlam yükleyip yüklemediği.
  - "Hesaplanamadı" ifadesine tepkisi: bozuk, eksik, normal?
  - "Eksiksiz satırların net kârı" bloğunu net kâr sanıp sanmadığı.
  - Dönem düğmelerine (Bugün, 7 gün, 30 gün) dokunup dokunmadığı.
- **Sorular:**
  1. "Ekranda bir rakamı bankaya ya da müşavirinize 'net kârım bu' diye söylemeniz gerekse hangisini söylerdiniz?"
  2. "'Dönem net kârı hesaplanamadı' size ne anlatıyor?"
  3. "Alttaki rakam 'eksik giderler hariç'. Bu sözü kendi cümlenizle anlatır mısınız?"
  4. "Bu rakam gerçeğinden büyük mü küçük mü olur sizce?"
- **İlgili açık soru:** `docs/12` §9 madde 23 (satıcı bu rakamı net kâr sanıyor mu, etiket önerisi). Sonuç buraya yazılır.
- **Süre sınırı:** 3 dk.

### G2. İlk kurulum: hizmet bedeli ve kargo tarifesi (Hesap A)

- **Ekran:** Özet'teki uyarı kutusu → `/panel/ayarlar` (bölümler "Kargo tarifesi", "Platform hizmet bedeli tahmini").
- **Senaryo (okunur, "bilgi kartı" paylaşılır):** "Ekranda sizden bir şey isteniyor. Elinizdeki bu karttaki bilgilerle bunu tamamlayın ve net kârınızı görün." (Not: kartta yazanlar uydurma demo değerlerdir.)
  - Bilgi kartı: *Kargo: Trendyol anlaşmalı, Trendyol Express. 0-2 desi: 50 TL; 3-5 desi: 60 TL; 6-10 desi: 80 TL (fiyatlar KDV dahil). Platform hizmet bedeli: sipariş başına 10 TL (KDV dahil).*
- **Ekranda ne var (koddan):** Özet'te "Kargo tarifesini gir" ve "Hizmet bedelini gir" bağlantıları, Ayarlar'da "Kâr ayarları" ilerleme listesi (adımlar "bugün geçerli" ya da "eksik"), "Tarife ekle" ve "Tahmin ekle" düğmeleri; tarife formunda "Kargo anlaşması" (Trendyol anlaşmalı / Kendi kargo anlaşmam), "Kargo firması" listesi, "Başlangıç tarihi", "Fiyatları nasıl giriyorsunuz?" (KDV dahil / KDV hariç), "N. kademe, en çok desi", "Kademe ekle", "Kaydet ve rakamları güncelle"; hizmet bedelinde "Tutarı nasıl giriyorsunuz?" ve "Sipariş başına tutar (KDV dahil, TL)".
- **Başarı:** Hizmet bedeli tahmini **ve** kargo tarifesi (3 kademeyle, doğru desi ve fiyatlar, doğru KDV seçimi) kaydedilir; katılımcı Özet'e döner ve "Dönem net kârı" rakamını görür.
- **Gözlem:**
  - Yol: uyarı kutusu düğmesini mi kullandı, menüden mi gitti? Sayfa kaydı doğru bölüme götürdü mü?
  - "En çok desi" ifadesi: "0-2" kademesini "2" olarak yazdı mı? Ondalık ve binlik (virgül, nokta) hatası.
  - KDV dahil/hariç seçimini kartla eşleştirdi mi, yanında görünen hariç karşılığını okudu mu?
  - Başlangıç tarihi için ne seçti, neden? Öneri notunu okudu mu?
  - Ürün maliyetini sorup sormadığı ("maliyeti nereye gireceğim?").
  - Kaydet sonrası güncellenen rakamı fark etti mi, rakamın değişmesine tepkisi.
  - Hata mesajlarının anlaşılması.
- **Sorular:**
  1. "'En çok desi' size ne anlatıyor?"
  2. "KDV dahil ya da hariç seçimini neye göre yaptınız? Trendyol faturanızda hangisini görüyorsunuz?"
  3. "Başlangıç tarihini neden öyle seçtiniz?"
  4. "Bitirdiğinizde rakamın değişmesini bekliyor muydunuz?"
- **Not:** İlk girişte geçmişi etkileyen onay penceresi çıkmaması beklenir (kodda "ilk giriş istisnası" testi var). Çıkıyorsa bulgu.
- **Süre sınırı:** 6 dk (bu en uzun görev).

### G3. Geçmişi etkileyen bir değişikliği onaylama (Hesap A, G2'nin devamı)

- **Ekran:** `/panel/ayarlar#kargo`, mevcut tarifenin "düzenle" akışı, onay penceresi "Geçmiş raporlar değişecek".
- **Senaryo (okunur):** "Kargo firmasından haber geldi: 3-5 desi fiyatı 60 TL değil 65 TL imiş (KDV dahil). Tarifeyi düzeltin."
- **Hazırlık:** G2'de girilen tarife üzerinde. Geçmişi etkileyen değişiklikte sunucunun 409 ile onay istemesi beklenir; **Hasan/geliştirici staging'de bu adımın gerçekten pencere açtığını önceden doğrulamalı.** Açmıyorsa yedek görev: "Varsayılan desiyi 2'den 3'e değiştirin" (kodda bu konu için ayrı metin var).
- **Ekranda ne var (koddan):** başlık "Geçmiş raporlar değişecek", gövde "Bu değişiklik {tarih} ve sonrasındaki siparişlerin kâr hesabını değiştirir. Daha önce indirdiğiniz ya da paylaştığınız raporlardaki rakamlar artık farklı olabilir. Önceki değer ayar geçmişinde saklanır." Düğmeler "Vazgeç", "Değişikliği uygula" (ekleme akışında ayrıca "Yalnız bugünden itibaren uygula"). Pencere dışına tıklamayla kapanmaz.
- **Başarı:** Katılımcı pencerenin ne dediğini doğru anlatır (geçmiş siparişlerin kâr rakamları değişir, eski rakamlı raporlar farklı olabilir, önceki değer saklanır), bilinçli seçer ve değişikliği uygular; ayar geçmişinin nerede olduğunu gösterir ("Ayar geçmişi" bölümü).
- **Gözlem:**
  - Okuma süresi (3 sn'den kısa tıklama "okumadan geçti" demek).
  - "Raporlar" derken neyi anladığı (müşavire verdiği rapor mu, ekrandaki rakamlar mı).
  - "Vazgeç" ile "Değişikliği uygula" arasında tereddüt; "Yalnız bugünden itibaren" ne anlama geldiği (görünürse).
  - Ayar geçmişini kendiliğinden aradı mı.
- **Sorular:**
  1. "Bu pencere size ne söylüyor, kendi cümlelerinizle?"
  2. "Geçen ay müşavirinize bir rapor verdiyseniz, uygularsanız o rapora ne olur?"
  3. "Yanlış girdiğinizi fark etseniz eski değere nasıl dönerdiniz?"
- **İlgili açık soru:** `docs/12` §9 madde 24-25 (müşavir kilit beklentisi). Katılımcı "kilit" ya da "geri alma" bekliyorsa not edilir.
- **Süre sınırı:** 3 dk.

### G4. En çok zarar ettiren ürünü bul ve nedenini söyle (Hesap B, masaüstü)

- **Ekran:** `/panel` → `/panel/urunler` → `/panel/urunler/{barkod}`.
- **Senaryo (okunur):** "Mağazanız artık kurulu. Son 30 günde size en çok para kaybettiren ürün hangisi? Neden zarar ediyor?"
- **Hazırlık:** Hesap B'de 3 zarar eden ürün: biri kesin net zarar ("Zarar"), biri "Bilinen giderlerle bile zarar", biri "Maliyet girilmese de zarar"; 20+ kârlı ürün. En çok zarar eden ürünün zararının nedeni kalem tablosundan okunabilmeli (ör. kargo ürün fiyatına yakın). Veri seti X (G4) ve Y (G8a) farklı ürünler.
- **Ekranda ne var (koddan):** Özet'te "Zarar ettiren ürünler" kartı (en büyük zarar üstte, "En az ₺X zarar", "Tümünü gör (N)"); Ürünler'de "Zarar edenler" çipi, "Sırala" ve "Yön" listeleri, rozetler; ürün kırılımında "Ürün net kârı", "Satırlar" ve her satırda "Kalem / Tutar (KDV hariç) / Kaynak" tablosu.
- **Başarı:** 60 sn içinde doğru ürüne ulaşır ve nedeni kırılımdan doğru okur (hangi kalem baskın); üç zarar rozetinin farkını söyleyebilir (en az "Zarar" ile "Bilinen giderlerle bile zarar" arasında).
- **Gözlem:**
  - Yol: Özet kartından mı, Ürünler listesinden mi? Sıralama yönünü değiştirmeye ihtiyaç duydu mu?
  - "En az ₺X zarar" ve altındaki "Net kâr hesaplanamadı" satırının anlaşılması.
  - Kırılım ekranında kaç satır karttan sonra neden bulundu; tabloyu okuyabilme.
  - Yanlış ürünü seçme (kârı en düşük yerine marjı en kötü olanı seçme dahil).
- **Sorular:**
  1. "'En az ₺X zarar' derken neyi kastediyor?"
  2. "Bu ürünle ne yapardınız?"
  3. "Bu rakama ne kadar güvenirsiniz? Neden?"
- **Süre sınırı:** 3 dk.

### G5. Siparişi aç, kalem dökümünü oku (Hesap B)

- **Ekran:** `/panel/siparisler`, sipariş no arama, "Kalem dökümünü göster".
- **Senaryo (okunur, sipariş no yazılı verilir):** "{sipariş no} numaralı siparişi bulun. Trendyol bu siparişten komisyon, kargo ve hizmet bedeli olarak ayrı ayrı ne kadar kesmiş? İade olmuş mu?"
- **Hazırlık:** Birden fazla ürünlü bir sipariş, 1 adedi iade edilmiş ve "İade kaydı bekleniyor" notu olan satır. Tutarlar ve kaynaklar bilinen demo değerler.
- **Ekranda ne var (koddan):** "Sipariş no" arama alanı (tam eşleşme; "Numara tam yazılmalıdır; kısmi eşleşme aranmaz."), sipariş kartı, "Kalem dökümünü göster"; satır kartında "Net kâr", "{N} adet, {M} adedi iade", "İade kaydı bekleniyor.", tablo satırları Net satış, Ürün maliyeti, Komisyon, Kargo (gönderi), Kargo (iade), Platform hizmet bedeli, Ceza, Değişken giderler, Reklam; "Kaynak" rozetleri (Kesin, Tahmini, Girdiğiniz, Eşleşen, Eksik).
- **Başarı:** Siparişi bulur (tam numarayla), kalem dökümünü açar, komisyon, kargo, hizmet bedeli rakamlarını doğru okur, iade durumunu doğru söyler ve tutarların **KDV hariç** olduğunu fark eder ya da sorulunca doğru yorumlar.
- **Gözlem:**
  - Kısmi numara yazıp "bulunamadı" mesajına tepki.
  - "Kalem dökümünü göster" düğmesini bulma.
  - "Tutar (KDV hariç)" başlığının okunup okunmadığı; Trendyol ekstresi KDV'li gösteriyorsa "benimkiyle tutmuyor" tepkisi.
  - "Kaynak" sütunu (Kesin, Tahmini) ne anlama geliyor?
  - "Kargo (iade)" ile "adedi iade" ilişkisi; "İade kaydı bekleniyor" notunun anlaşılması.
- **Sorular:**
  1. "Komisyonun KDV'sini bu tabloda nerede ararsınız?" (Dikkat: tabloda **ayrı bir "komisyon KDV'si" satırı yok**; tutarlar KDV hariçtir. Bu, bir ürün sorusudur: satıcı ayrı satır bekliyor mu?)
  2. "'Tahmini' ve 'Kesin' arasındaki fark sizce nedir?"
  3. "Bu rakamlar Trendyol'dan indirdiğiniz ekstreyle aynı mı olur diye düşünürdünüz?"
- **Süre sınırı:** 4 dk.

### G6. "Ekstresi gelmeyen" ve "Beklenmeyen kesinti" siparişlerini bul (Hesap B, masaüstü)

- **Ekran:** `/panel/siparisler`, süzgeç çipleri "Ekstresi gelmeyen" ve "Beklenmeyen kesinti".
- **Senaryo (okunur):** "İki şey öğrenmek istiyorsunuz. Birincisi: Trendyol'un hakedişini henüz hesaplamadığı, parası henüz gelmemiş siparişler hangileri? İkincisi: Trendyol'un beklediğinizden fazla kestiği bir sipariş var mı, varsa ne kadar fazla kesmiş?"
- **Hazırlık:** En az 2 "Ekstresi gelmedi", 1 "Beklenmeyen kesinti" rozetli sipariş (kalem dökümünde karşılaştırma bloğu görünen, kargo farkı baskın, mümkünse varsayılan desi kullanılmış).
- **Not (kasıtlı dil farkı):** Arayüzde etiket **"Ekstresi gelmeyen"**; "hakediş bekleyen" bilerek kullanılmıyor, çünkü ödeme durumu değil ekstre kaydı yok demek (`lib/profit/query.ts` notu). Senaryo cümlesi bilerek satıcının "hakediş" diliyle yazıldı: katılımcı etiketi bulabiliyor mu ve ne anladığı ölçülür.
- **Ekranda ne var (koddan):** çipler "Tümü, Zarar edenler, Ekstresi gelmeyen, Beklenmeyen kesinti"; kart rozetleri "Ekstresi gelmedi", "Beklenmeyen kesinti"; kalem dökümünde "Beklenmeyen kesinti: tahmini ve kesin" tablosu, "Fark" ve "eşik".
- **Başarı:** İki süzgeci bulur, doğru siparişleri seçer; fazla kesintinin tutarını (Fark) ve hangi kalemden geldiğini söyler.
- **Gözlem:**
  - "Ekstresi gelmeyen"in "ödeme gecikti" olarak mı yoksa "ekstre kaydı yok" olarak mı anlaşıldığı.
  - Uyarı sayfasından mı yoksa Siparişler çiplerinden mi gitti.
  - "Eşik" kelimesinin anlaşılması.
  - Karşılaştırma bloğunu okuyabildi mi ("Trendyol hata yaptı" gibi yanlış sonuca varma).
- **Sorular:**
  1. "'Ekstresi gelmedi' size ne söylüyor? Para gecikti mi diye mi anlıyorsunuz?"
  2. "Bu siparişte Trendyol'a itiraz eder miydiniz? Önce neyi kontrol ederdiniz?"
- **Süre sınırı:** 3 dk.

### G7. Bir uyarıya göre harekete geç (Hesap B)

- **Ekran:** `/panel/uyarilar`.
- **Senaryo (okunur):** "Uyarılar ekranını açın. Size göre önce hangisine bakmak gerekir, neden? Sonra o uyarıyla ilgili yapılabilecek bir şeyi yapın."
- **Hazırlık:** Hesap B'de en az şu uyarılar: "Zarar eden satışlar", "Beklenmeyen kesintiler", "Ürün maliyeti eksik", "Varsayılan desi kullanıldı".
- **Ekranda ne var (koddan):** gruplar "Para kaybettirenler", "Kurulum", "Bilgi ve kontrol"; kartlar ve eylem düğmeleri "Zarar eden siparişleri gör", "Etkilenen siparişleri göster", "Maliyeti eksik ürünleri gör", "Varsayılan desiyi gör".
- **Başarı:** Önceliği gerekçesiyle söyler (tercihen "Para kaybettirenler" grubundan, ama gerekçeli başka seçim de geçerli), kartın eylem düğmesini kullanır ve eylemin onu nereye götürdüğünü anlatır.
- **Gözlem:**
  - Gruplama sırasını fark edip kullandı mı?
  - Kartlardaki uzun cümlelerin (ör. Zarar eden satışlar: "Sayı satış satırı sayısıdır; sipariş listesi sipariş toplamına göredir...") okunması, anlaşılması.
  - Rozet sayısı ile açılan liste sayısı uyuşmayınca (satır ve sipariş farkı) tepkisi.
  - **"Maliyeti eksik ürünleri gör" eylemi bir listeye gider; maliyeti girme yeri arayüzde henüz yok** (Ayarlar'da "Ürün maliyetleri: Ürünler ekranında girilecek (yakında)"). Katılımcı "peki maliyeti nereye gireceğim?" diye soruyor mu? Bu bir çıkmaz yol bulgusu adayıdır.
- **Sorular:**
  1. "Bu uyarılardan hangisini görmezden gelirdiniz? Neden?"
  2. "Bu uyarıyı gördükten sonra ne yaparsınız? Ekran size bunu söylüyor mu?"
- **Süre sınırı:** 3 dk.

### G8. Telefonda iki görev (390 px, Hesap B, veri seti Y)

Aynı iki görev farklı veriyle gerçek telefonda tekrarlanır. Süreler ayrı kaydedilir.

- **G8a (G4'ün telefon sürümü).** "Telefonunuzdan bakıyorsunuz. Son 7 günde size en çok para kaybettiren ürün hangisi, neden?" (Dönem 7 gün; veri setinde farklı ürün.)
- **G8b (G6'nın telefon sürümü).** "Telefonunuzdan: Trendyol'un beklediğinizden fazla kestiği siparişi bulun ve hangi kalemin fazla kesildiğini söyleyin." (Farklı bir sipariş.)
- **Ekranda ne var (koddan):** `lg` altında alt gezinme çubuğu (Özet, Ürünler, Siparişler, Uyarılar, Ayarlar), ürün kartları (tablo yok), çiplerin alt satıra sarması, "Sırala" ve "Yön" seçim kutuları, sipariş kartı ve kalem dökümü tablosu (3 sütun, 390 px'te yatay kayabilir).
- **Başarı:** G4 ve G6 ile aynı ölçüt, aynı süre sınırı.
- **Gözlem:**
  - Alt gezinme çubuğunu bulma, dokunma hedeflerine isabet; yanlış dokunuş sayısı.
  - Zarar kartının ilk ekranda görünürlüğü (kaç kaydırma).
  - Kalem dökümü tablosunun sığıp sığmadığı, yatay kaydırma.
  - Klavye açılınca "Sipariş no" alanı ve düğmenin görünürlüğü.
  - Masaüstü süresi ile fark (öğrenme etkisini hesaba kat, §4.9).
- **Sorular:**
  1. "Bu işi telefonda yapmak masaüstüne göre nasıldı? Hangi kısmı zorlaştırdı?"
  2. "Gerçek hayatta bu ekranı telefonda mı bilgisayarda mı açardınız?"
- **Süre sınırı:** G8a 2 dk, G8b 2 dk.

### 4.9 Görev sırası ve cihaz dengesi

- Sıra: giriş (4 dk) → G1 → G2 → G3 → (hesap B'ye geçiş) → G4 → G5 → G6 → G7 → G8 → SUS ve ürün soruları (5 dk).
- **P2 ve P4'te** G4+G6 (veri seti X) **telefonda**, G8 (veri seti Y) **masaüstünde** yapılır. Böylece cihaz sırası iki gruba bölünür. n=5 ile bu dengeleme sağlam bir karşılaştırma vermez, yalnız öğrenme etkisini bir yöne yığmamak içindir; bulgu notunda bu yazılır.
- **Süre taşarsa kesme sırası:** önce G7, sonra G5'in iade sorusu. G1-G4 ve G8 çıkarılmaz.

---

## 5. Metrikler

### 5.1 Her görev için

| Metrik | Nasıl ölçülür |
|---|---|
| **Görev başarısı** | Tam (T): yardımsız, doğru sonuç. Kısmi (K): yardımla (2. basamak ipucu) ya da doğru sonuca yanlış yoldan ulaştı. Başarısız (B): 3. basamak ipucu, yanlış sonuç ya da süre doldu. Sonuç "5 kişiden kaçı T" diye raporlanır |
| **Görev süresi** | Moderatör "başlayın" der demez başlar, katılımcı "bitirdim" der demez biter. Saniye cinsinden. B olan görevler ortalamaya girmez (ayrı yazılır). Süreler sınırlıdır (§4) |
| **Hata sayısı** | (a) yanlış ürün, sipariş, süzgeç seçimi, (b) rakamı yanlış okuma ya da yanlış yorum, (c) çıkmaz yola girme (alakasız ekrana gitme, boş sonuca dönme) |
| **İpucu düzeyi** | 0, 1, 2 ya da 3 (§4.0) |
| **SEQ** | Görev biter bitmez tek soru: "Bu görev ne kadar kolaydı?" 1 (çok zor) ile 7 (çok kolay). Sauro ve Dumas (2009) |

### 5.2 Oturum sonunda: SUS (Sistem Kullanılabilirlik Ölçeği)

Brooke (1996), 10 madde, 5'li ölçek (1: kesinlikle katılmıyorum, 5: kesinlikle katılıyorum). Maddelerdeki "sistem" yerine "NetTablo paneli" denir.

> **Uyarı:** Aşağıdaki Türkçe ifadeler benim çevirimdir. Türkçe uyarlanmış ve geçerlik çalışması yapılmış bir SUS sürümü olduğunu hatırlıyorum ama kaynağını doğrulayamadım, **emin değilim**. Testten önce doğrulanmış çeviriyle karşılaştırılmalı ve gerekirse bu maddeler ona göre değiştirilmeli. Çeviri değişirse puanlar önceki çalışmalarla kıyaslanamaz.

1. NetTablo panelini sık sık kullanmak isteyeceğimi düşünüyorum.
2. Paneli gereksiz yere karmaşık buldum.
3. Panelin kullanımının kolay olduğunu düşündüm.
4. Bu paneli kullanabilmek için teknik bir kişinin desteğine ihtiyacım olacağını düşünüyorum.
5. Paneldeki çeşitli işlevlerin iyi bir bütün oluşturduğunu düşündüm.
6. Panelde çok fazla tutarsızlık olduğunu düşündüm.
7. Çoğu insanın bu paneli çok hızlı öğreneceğini düşünüyorum.
8. Paneli kullanmayı çok zahmetli buldum.
9. Paneli kullanırken kendimden emin hissettim.
10. Bu paneli kullanmaya başlamadan önce çok şey öğrenmem gerekti.

**Puanlama (Brooke, 1996):** Tek numaralı maddelerde (puan - 1), çift numaralı maddelerde (5 - puan); toplam 10 maddenin toplamı 2,5 ile çarpılır (0-100). Eşik olarak Sauro ve Lewis (2016) kitabında geçen ortalama değer 68'dir. n=5 ile ortalama yalnız yön gösterir; güven aralığı geniş olacağı için tek tek puanları da raporlayın.

### 5.3 Ürün soruları (oturum sonunda, teşekkür konuşulmadan önce)

1. **Ödeme niyeti:** "Bu paneli kullanmak için ayda ne kadar ödemeyi makul bulurdunuz? Hiç ödemez miydiniz?" Önce açık uçlu sorun. Fiyat gösterilecekse (K-N05: Başlangıç 499 TL liste, 249 TL kurucu fiyatı önerisi) gösterip göstermeyeceğine Hasan karar versin; öneri henüz karar değil **[H]**. Gösterirseniz açık uçlu cevabı aldıktan sonra gösterin.
2. **En az güvenilen rakam:** "Ekranda gördüğünüz rakamlardan hangisine en az güvenirsiniz? Neden? Onu nasıl kontrol ederdiniz?" Beklenen adaylar: Tahmini kâr, eksik giderler hariç kâr, hizmet bedeli tahmini, komisyon tutarı.
3. **Yerine koyma:** "Şu an bu işi nasıl yapıyorsunuz (Excel, Trendyol paneli)? Bu panel onun yerini alır mı, yanında mı durur?"

---

## 6. Gözlem notu şablonu ve bulgu önem ölçeği

### 6.1 Oturum gözlem tablosu (her katılımcı için bir tane)

Katılımcı kodu: P__ | Tarih | Cihaz / ortam | Moderatör | Not tutan | Veri seti (X/Y, hesap A/B varyantı) | Kayıt rızası: ☐ evet ☐ hayır

| Görev | Başlangıç (dk:sn) | Süre (sn) | Başarı (T/K/B) | Hata | İpucu (0-3) | SEQ (1-7) | Ne yaptı / ne dedi (tırnak içinde) | Olası sorun | Önem (0-4) |
|---|---|---|---|---|---|---|---|---|---|
| G1 | | | | | | | | | |
| G2 | | | | | | | | | |
| G3 | | | | | | | | | |
| G4 | | | | | | | | | |
| G5 | | | | | | | | | |
| G6 | | | | | | | | | |
| G7 | | | | | | | | | |
| G8a | | | | | | | | | |
| G8b | | | | | | | | | |

Oturum sonu: SUS puanı: ____ (10 madde puanı ayrı sayfada) | Ürün soruları (§5.3) kısa cevaplar: ______

### 6.2 Bulgu listesi (5 oturumdan sonra birleştirilir)

| Bulgu no | Başlık | Ekran / bileşen | Kaç katılımcı (x/5) | Hangi görevler | Kanıt (kod, tırnak) | Önem (0-4) | Öneri | İş kartı |
|---|---|---|---|---|---|---|---|---|

Önem, Nielsen'in (1994) üç etkenini birlikte tartar: **sıklık** (kaç kişi yaşadı), **etki** (kullanıcı için ne kadar kolay aşılır) ve **ısrar** (bir kez öğrenince geçiyor mu, hep mi takılıyor). Hasan'ın (P1) ve beta satıcının (P2) yaşadığı sorunlar "ürünü bilen kullanıcı bile takıldı" diye ağırlık kazanır, ama sıklığa "saf kullanıcı" olarak sayılmaz.

| Puan | Anlam | Ne yapılır |
|---|---|---|
| 0 | Kullanılabilirlik sorunu değil | Kaydet, kapat |
| 1 | Kozmetik sorun | Zaman kalırsa düzelt |
| 2 | Küçük sorun | Düşük öncelik |
| 3 | Büyük sorun | Yüksek öncelik, S4 kapanmadan düzelt |
| 4 | Felaket | Yayından önce mutlaka düzelt; ilgili rakam yanlış okunuyor ya da kullanıcı yanlış karar veriyorsa her zaman 4 |

**Ek kural (bu ürüne özgü):** Satıcının yanlış parasal karar vermesine yol açabilecek her yanlış okuma (ör. eksik giderler hariç kârı net kâr sanmak) sıklığı ne olursa olsun en az 3'tür.

---

## 7. Lojistik

### 7.1 Test ortamı ve bağımlılıklar

| Bağımlılık | Durum | Not |
|---|---|---|
| **Staging ortamı** | **Yok** | `docs/10_mimari.md` §8 staging'i tanımlıyor (`main` → staging otomatik, Trendyol stage API, test verisi) ama ayağa kalktığını gösteren bir şey görmedim. Test staging'e bağlı |
| **Demo hesap verisi** | **Yok** | Aşağıda şartname. Kodda test verisi yardımcıları var (`services/api/tests/report_helpers.py` gibi), ama demo hesabı tohumlayan ayrı bir betik görmedim. Kontrolüm yüzeyseldi, **emin değilim** |
| Sahte API (`apps/web/e2e/fake-api.mjs`) | Yetmez | Yalnız oturum ve boş durum döndürüyor. Rapor verisi testlerde Playwright route ile taklit ediliyor, ayrı bir demo ortamı değil |
| Geçici çözüm | Yerel | `npm run dev` + `services/api` + geçici PostgreSQL ile yerel gerçek API (README'deki `e2e:gercek-api` düzeni) ve tohum verisi. Katılımcı kendi bilgisayarından bağlanamaz; yüz yüze ya da Hasan'ın ekranını paylaşması gerekir. **Uzaktan test için staging şart** |
| Veri güncelliği | Gerekli | Demo siparişleri "bugün", "7 gün", "30 gün" pencerelerine göre tarihlendirilmeli; test günü rakamları tazelemek için tohum betiği yeniden çalıştırılabilir olmalı |

**Demo veri şartnamesi:**

*Hesap A (ayarsız, yeni bağlanmış):* kargo tarifesi ve hizmet bedeli yok; ürün maliyetleri tohumda dolu (arayüzde giriş olmadığı için); kısmi dönem. En az 8 ürün, 40 sipariş. Bilgi kartındaki tarife girilince "Dönem net kârı" görünmeli. Pozitif ve negatif bilinen kâr varyantı (isteğe bağlı).

*Hesap B (ayarlı, dolu):* kargo ve hizmet bedeli girilmiş; 25 ürün; 3 zarar eden ürün (üç ayrı zarar rozeti); 2 ürünün maliyeti eksik; 1 çok ürünlü sipariş; 1 iade ("İade kaydı bekleniyor") ; en az 2 "Ekstresi gelmedi" sipariş; en az 1 "Beklenmeyen kesinti" siparişi (karşılaştırma bloğu, varsayılan desi); uyarılar sayfasında dört kart (§4 G7). Veri seti X ve Y: G4/G6 ile G8 için farklı ürün, sipariş ve en çok zarar eden. Ürün adları ve sipariş numaraları uydurma; hiçbir gerçek kişi ya da mağaza adı geçmez.

**Moderatör için bilinen doğru cevap kartı:** Her görev için "doğru ürün, doğru sipariş, doğru rakam" kartı hazırlanır (tohumla birlikte üretilir; elle yazılmaz).

**Doğrulanacak iki teknik varsayım (G2, G3):** (1) ilk girişte onay penceresi açılmıyor; (2) mevcut tarifeyi düzenlemek geçmişi etkileyen onayı tetikliyor. Staging'de bir kez deneyin. İkincisi tetiklemiyorsa G3'ün yedeği "Varsayılan desi" değişikliğidir.

### 7.2 Süre planı (katılımcı başına, ~38 dk)

| Bölüm | Dk |
|---|---|
| Karşılama, kayıt rızası, ısınma ("Trendyol'da en son neyin kârını merak ettiniz?") | 4 |
| G1 | 3 |
| G2 | 6 |
| G3 | 3 |
| G4 | 3 |
| G5 | 4 |
| G6 | 3 |
| G7 | 3 |
| G8 (a+b) | 4 |
| SUS + ürün soruları + kapanış | 5 |
| **Toplam** | **38** |

### 7.3 Her oturumdan önce kontrol listesi

- [ ] Katılımcı kodu verildi (P1-P5), ad notlara yazılmadı.
- [ ] Aydınlatma metni gönderildi, açık rıza kutuları işaretli ve saklandı; kayıt yalnız rıza sonrası başladı.
- [ ] Kamera kapalı; kayıt aracında bulut aktarımı ve paylaşım ayarları kontrol edildi.
- [ ] Demo veri tazelendi (tarihler bugüne göre); ekranda son müşteri verisi yok.
- [ ] Hesap A ve B ayrı tarayıcı profillerinde oturumu açık; geçiş süresi 30 sn'in altında.
- [ ] Doğru cevap kartı ve veri seti (X/Y) bu katılımcı için seçildi, cihaz sırası (§4.9) belli.
- [ ] Görev metinleri, bilgi kartı (G2), sipariş numarası (G5) paylaşıma hazır.
- [ ] Telefon ekranı paylaşımı denendi (G8) ya da 390 px yedeği hazır.
- [ ] Zamanlayıcı ve not tablosu (§6.1) hazır.
- [ ] SUS formu ve ürün soruları (§5.3) hazır.
- [ ] Oturum sonrası: kaydın yeri, silme tarihi (en geç +60 gün) iş kartına yazıldı.

### 7.4 Kim ne yapar

| İş | Sorumlu |
|---|---|
| Katılımcı bulma, davet, rıza formunu gönderme | Hasan |
| Aydınlatma ve rıza metinlerinin hukuki onayı, saklama süresi, yurt dışı aktarım | Avukat (Hasan aracılığıyla) |
| Staging ve demo veri tohumu | Geliştirme (Sonnet ajanı ya da Hasan; §7.1 bağımlılığı) |
| Görev kartları, bilgi kartı, doğru cevap kartı, not şablonu, SUS formu | Claude hazırlar |
| Oturumu yürütme (moderatörlük) | Hasan. Kendi oturumu (P1) için başka biri gerekir |
| Not tutma | İkinci bir kişi varsa o; yoksa kayıttan sonradan, aynı gün |
| Bulgu birleştirme, önem puanı taslağı, S4 sonuç notu | Claude, yalnız anonim notlardan (§3.5); önem puanını Hasan onaylar |
| Önem 3-4 bulguların iş kartına çevrilmesi | Hasan onaylar, geliştirme alır |

---

## 8. Açık noktalar ve riskler

1. **Staging ve demo veri yok.** Uzaktan test bunlara bağlı; yüz yüze yerel ortamla başlanabilir. Tohum betiği henüz yok.
2. **Hasan moderatör ve katılımcı.** Kendi oturumunu yönetemez; "uzman gözden geçirme" olarak yürütmek ve saf kullanıcı sayımından ayrı işaretlemek dürüst olan. Başka bir moderatör bulunması iyi olur.
3. **Ürün maliyeti girişi arayüzde yok** ("Ürün maliyetleri: Ürünler ekranında girilecek (yakında)"). Gerçek satıcılar bunu hemen soracak, "Maliyeti eksik ürünleri gör" eylemi de çıkmaza gider. Plan bunu bulgu olarak yakalar (G2, G7), ama test sonucunun SUS ve SEQ'ini düşürebilir; sonuç raporunda ayrıca belirtin.
4. **Komisyon KDV'si ayrı satır değil.** Kalem tablosundaki tutarların hepsi KDV hariç. Satıcı Trendyol ekstresindeki KDV'li rakamla karşılaştırmak isteyecek. G5 bunu ölçer; sonuç ürün kararıdır **[H]**.
5. **"Ekstresi gelmeyen" etiketi bilerek "hakediş bekleyen" değil.** Satıcı diliyle uyuşmazlık olabilir; G6 bunu ölçer.
6. **KVKK metinleri taslak.** Veri sorumlusunun kim olduğu (şirket mi, Hasan mı), yurt dışında barındırılan toplantı aracı, saklama süreleri avukat onayı bekliyor.
7. **Bekleme listesinden davet** için izin kapsamı belirsiz (§2).
8. **Tutarsız belge:** `docs/00_yonetici_ozeti.md` "1 pilot ve 5 beta satıcı" diyor, `docs/karar_kaydi.md` K-N06 beta sayısını 1'e indirmiş. Bu plan K-N06'yı esas aldı.
9. **Test bitince** ikinci tur planlanmadı; önem 3-4 bulgular düzelince 3-5 kişiyle tekrar bakılması önerilir.

---

## 9. Kaynaklar

Brooke, J. (1996). SUS: A "quick and dirty" usability scale. In P. W. Jordan, B. Thomas, B. A. Weerdmeester, & A. L. McClelland (Eds.), *Usability evaluation in industry* (pp. 189-194). Taylor & Francis.

Nielsen, J. (1994). Heuristic evaluation. In J. Nielsen & R. L. Mack (Eds.), *Usability inspection methods* (pp. 25-62). John Wiley & Sons. (0-4 önem ölçeği bu bölümde anlatılır. Sayfa aralığından emin değilim.)

Nielsen, J., & Landauer, T. K. (1993). A mathematical model of the finding of usability problems. In *Proceedings of the INTERCHI '93 Conference on Human Factors in Computing Systems* (pp. 206-213). ACM. https://doi.org/10.1145/169059.169166 (Makalenin yayımlandığı kongre adını ve sayfa aralığını teyit edin, emin değilim.)

Sauro, J., & Dumas, J. S. (2009). Comparison of three one-question, post-task usability questionnaires. In *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '09)* (pp. 1599-1608). ACM. https://doi.org/10.1145/1518701.1518946

Sauro, J., & Lewis, J. R. (2016). *Quantifying the user experience: Practical statistics for user research* (2nd ed.). Morgan Kaufmann. (SUS için ortalama 68 eşiği.)

Spool, J., & Schroeder, W. (2001). Testing web sites: Five users is nowhere near enough. In *CHI '01 Extended Abstracts on Human Factors in Computing Systems* (pp. 285-286). ACM. (Sayfa aralığından emin değilim.)

Virzi, R. A. (1992). Refining the test phase of usability evaluation: How many subjects is enough? *Human Factors, 34*(4), 457-468.

6698 sayılı Kişisel Verilerin Korunması Kanunu. (2016, 7 Nisan). *Resmî Gazete* (Sayı: 29677). Aydınlatma yükümlülüğü için: Aydınlatma Yükümlülüğünün Yerine Getirilmesinde Uyulacak Usul ve Esaslar Hakkında Tebliğ (*Resmî Gazete*, 10 Mart 2018), `docs/research/03_hukuk_ve_uyum.md` §2.6'da listeli.

**Türkçe SUS uyarlaması:** Geçerlik çalışması yapılmış bir Türkçe sürüm olduğunu hatırlıyorum, ama yazar, yıl ve dergiyi güvenle veremiyorum; **emin değilim**. Kaynak olarak yazmadım, testten önce bulunup doğrulanmalı.
