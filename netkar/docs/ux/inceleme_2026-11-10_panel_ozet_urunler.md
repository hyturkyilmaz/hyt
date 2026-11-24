# UX İncelemesi: Panel Özet, Ürünler ve Ürün Kırılımı (10 Kasım 2026)

- İncelenen commit: `41e23cc` (NetKâr S4: panel özet ve ürün kârlılık ekranları rapor API'sine bağlandı)
- Rol: UX / ürün tasarımcısı (docs/40_ajan_promptlari.md §3.5)
- Hedef kullanıcı: telefondan bakan, muhasebeci olmayan Trendyol satıcısı (research/05 §2.5 Persona A "Elif" birincil, Persona B "Murat" ikincil)
- Kapsam: `apps/web/src/lib/profit/*`, `src/components/profit/*`, `src/app/(app)/panel/page.tsx`, `panel/urunler/page.tsx`, `panel/urunler/[barkod]/page.tsx`, `e2e/profit.spec.ts`, ekran görüntüleri `docs/ux/ekranlar/rapor-*.png` (16 dosya, açık ve koyu, 390 ve 1280 px)
- Ölçüt belgeleri: docs/60_tasarim_sistemi.md (ilkeler, §3-§5), denetim `docs/security/denetim_2026-11-09_kar_ayarlari.md` §7, ADR-0007 §1 ve §5.2, docs/12 §7.4 ve §9 madde 23
- Yöntem: kod okuma (satır numaraları commit `41e23cc` içindir), ekran görüntülerinin görsel incelemesi, token kontrast hesabı. Kullanıcı testi yapılmadı; §9'daki senaryolar bunun için.
- Kod değiştirilmedi. Bu belge yalnız bulgu ve öneridir.

## 0. Kısa sonuç

Kurulumu tamam bir hesapta özet ekranı "kâr ediyor muyum" sorusunu ilk ekranda, 2-3 saniyede cevaplıyor (yeşil ok, renk ve rakam). "Hangi ürün zarar ettiriyor" sorusu ise özet ekranında hiç cevaplanmıyor: kullanıcı mobilde altı kart aşağı inip bir düğmeye basmalı, sonra açılan listede en büyük zarar en sonda geliyor.

Yeni bağlanmış (ayarsız) hesapta durum daha zayıf: ilk ekranda tek bir kâr rakamı yok, yalnız uyarı bandı ve "Hesaplanamadı" var. Bandın düğmesi kargo ve hizmet bedeli formu olmayan bir sayfaya gidiyor. Her yeni kullanıcı bu ekranla başlayacağı için (denetim AO-03), en önemli iki iş şunlar: ADR-0007'nin getirdiği `donem_eksik_giderler_haric_kar` rakamını özetin baş kartına koymak ve bandı çalışan bir ayar akışına bağlamak.

Sunum kurallarının çoğu (asla 0,00 yazmamak, "Kesin" rozetini yalnız kesinlik alanından almak, iade notu, karşılaştırma dökümü, imleç hatasında baştan yükleme) doğru ve testli. Erişilebilirlik temeli (44 px hedefler, kontrast, canlı bölgeler, renk + ikon + metin) iyi.

| Önem | Sayı |
|---|---|
| Kritik | 2 |
| Yüksek | 8 |
| Orta | 14 |
| Düşük | 8 |
| **Toplam** | **32** |

## 1. İlk 5 saniye testi (ekran görüntüleri üzerinden)

| Durum | "Kâr ediyor muyum?" | "Hangi ürün zarar ettiriyor?" | Not |
|---|---|---|---|
| Ayarlı hesap, mobil 390 (`rapor-ozet-mobil-390.png`) | Evet. İlk ekranda "Net kâr ₺3.120,45", yeşil yukarı ok, "Tahmini" rozeti. | Hayır. İlk ekranda ürün adı yok. "Zarar ettiren ürünleri gör" düğmesi 6 kartın altında. | Başlık ve açıklama, dönem seçici ve dönem satırı ilk ekranın yaklaşık üçte birini kaplıyor. |
| Ayarlı hesap, masaüstü 1280 | Evet. | Hayır. Düğme ilk ekranın dışında. | Uyarılar kartında "Zararına satış 3" var ama ürüne gitmiyor. |
| Ayarsız hesap, mobil 390 (`rapor-ozet-ayarsiz-mobil-390.png`) | Hayır. Tek rakam yok; ilk ekranda uyarı bandı ve "Hesaplanamadı". | Hayır. | Kullanıcı yalnız "bir şeyler eksik" mesajı alıyor. |
| Ayarsız hesap, masaüstü 1280 | Hayır. Dört karttan üçü "Hesaplanamadı". | Hayır. | "Hesaplanamadı" duvarı, ürün çalışmıyor izlenimi verir. |
| Ürünler, mobil 390 (`rapor-urunler-mobil-390.png`) | Ürün düzeyinde evet. | Kısmen. İlk ekranda yalnız 1 ürün kartı (en kârlı ürün) görünüyor. Zarar edenler varsayılan sıralamada aşağıda. | Süzgeç, sıralama ve yön denetimleri ilk ekranın yarısını kaplıyor. |

## 2. Bulgular

Biçim: **[No] Önem. Başlık.** Ekran; dosya:satır. Gözlem. Öneri.

### 2.1 Kritik

**[UX-01] Kritik. Ayarsız ve kısmi dönemde özet ekranında hiç kâr rakamı yok; ADR-0007 §5.2 madde 3 uygulanmamış.**
- Ekran: Özet, `rapor-ozet-ayarsiz-*`. Dosya: `src/lib/profit/present.ts:180-229` (`summaryView` `donem_eksik_giderler_haric_kar` okumuyor), `src/lib/api/profit.ts:69-83` (`PeriodTotals` tipinde alan yok; `donem_net_kar` satır 74'te null olamaz diye tanımlı), `src/components/profit/summary-view.tsx:124-154`.
- Gözlem: Kısmi dönemde baş kart yalnız "Hesaplanamadı / Eksik: ürün maliyeti, kargo, hizmet bedeli" gösteriyor. Tam satır sayısı 0 iken (her yeni hesabın ilk günleri) toplam gider ve marj kartları da "Hesaplanamadı". Arka uçta (`services/api/app/api/v1/profit_schemas.py`, çalışma ağacında) `donem_eksik_giderler_haric_kar` her dönemde sayı olarak geliyor ve `donem_net_kar` kısmi dönemde null oluyor. Panel bu alanı göstermediği için satıcı ilk gün hiçbir kâr bilgisi görmüyor; 60_tasarim_sistemi §1 madde 1 (5 saniye kuralı) karşılanmıyor.
- Öneri: §5'teki K39 Revizyon 1 düzeni. Kısaca: baş kartın değeri "Dönem net kârı hesaplanamadı" + eksik kalem satır sayıları + ayar bağlantısı; hemen altında "Eksik giderler hariç dönem kârı (kargo ve hizmet bedeli hariç)" rakamı; tipte `donem_net_kar: Money | null`, `satir_net_kar_toplami: Money | null`, `donem_eksik_giderler_haric_kar: Money` eklenmeli ve `present.test.ts`'e G49 benzeri bir test (tam satırsız dönem + dönem gideri) yazılmalı.

**[UX-02] Kritik. Kurulum bandının tek eylemi çıkmaza gidiyor ve ayar sayfası mağazanın bağlı olmadığını söylüyor.**
- Ekran: Özet (bant) ve Ayarlar. Dosya: `summary-view.tsx:244-248` (düğme `/panel/ayarlar`'a gider), `src/app/(app)/panel/ayarlar/page.tsx:22` (sabit `<Badge>Bağlı değil</Badge>`), `panel-ayarlar-mobil-390.png`.
- Gözlem: "Kargo ve hizmet bedelini gir" düğmesine basan kullanıcı, yalnız "Trendyol bağlantısı: Bağlı değil" kartını görüyor. Kargo tarifesi, hizmet bedeli ya da ürün maliyeti girecek bir form yok. Üstelik özet aynı anda bu mağazanın rakamlarını gösteriyor, yani ayar sayfası yanlış bilgi veriyor. Satıcı ya "uygulama bozuk" diye düşünür ya da mağazayı yeniden bağlamaya çalışır. Uygulamanın ilk 10 dakikalık değeri (research/05 Persona A: "10 dakikada gör") bu adımda kopuyor.
- Öneri: (a) Ayar formu gelene kadar bant düğmesi kaldırılsın ve yerine dürüst bir cümle konsun: "Kargo tarifesi ve hizmet bedeli girişi çok yakında. O zamana kadar bu rakamlar bilinen giderlerle hesaplanıyor." (b) Ayarlar sayfasındaki rozet `useReportAccount` durumuna bağlansın ("Bağlı" / "Bağlı değil"). (c) Ayar formu §8.1'deki düzenle yapılınca bant düğmesi doğrudan ilgili adıma gitsin (`/panel/ayarlar#kargo`).

### 2.2 Yüksek

**[UX-03] Yüksek. Özet ekranı "hangi ürün zarar ettiriyor" sorusunu cevaplamıyor.**
- Ekran: Özet. Dosya: `summary-view.tsx:221-225`.
- Gözlem: Tek bağlantı sayfanın en altında ikincil düğme. Mobilde önünde 4 metrik kartı, "Satır durumları" ve "Uyarılar" kartları var (yaklaşık 4-5 ekran kaydırma). Tasarım ilkesi "hangi ürün zarar ettiriyor sorusunun cevabını ilk ekranda görür" diyor (60 §1 madde 1).
- Öneri: Baş kartın hemen altına "Zarar ettiren ürünler" kartı: `products?filter=loss&limit=3` ile en çok zarar eden 3 ürün (ad, zarar tutarı, neden rozeti) ve "Tümünü gör (N)" bağlantısı. Zarar yoksa kart tek satır: "Bu dönemde zararı kesin olan ürün yok." Kısmi dönemde belirsiz ürün sayısı da yazılsın (UX-15 ile aynı metin). "Satır durumları" kartı aşağı ya da ürün kırılımına taşınabilir (UX-12).

**[UX-04] Yüksek. Zarar listesinin sırası en büyük zararı en sona koyuyor.**
- Ekran: Ürünler, özetten gelinen `filter=loss` görünümü ve `Tümü`. Dosya: `summary-view.tsx:223` (bağlantıda `order` yok), `src/lib/profit/query.ts:5-6` (varsayılan `net_profit` + `desc`), `rapor-urunler-masaustu-1280.png`.
- Gözlem: Özetten gelen kullanıcı zarar edenleri "çoktan aza" net kâr sırasıyla görüyor: -₺30 zarar, -₺500 zarardan önce gelir. Net kârı null ama bilinen giderlerle bile zararda olan ürünler (`known_expenses`, `contribution_before_cost`) her yönde en sona düşüyor (denetim AD-04, arka uçta açık). Ekran görüntüsünde "Bilinen giderlerle bile zarar" ürünü listenin dördüncü sırasında.
- Öneri: (a) Özetteki bağlantı `filter=loss&order=asc` olsun; zarar süzgeci seçilince varsayılan yön "en çok zarar önce" olsun. (b) Arka uçta AD-04 düzeltmesi (`sort=contribution_excl_missing` ya da kesin zararlı null'ların bilinen değerleriyle sıralanması) gelene kadar zarar görünümünde listenin üstüne kısa not: "Kargo ya da maliyeti eksik olup yine de zarar eden ürünler listenin sonunda." (c) AD-04 gelince not kalksın.

**[UX-05] Yüksek. Kurulum bandı başlığı ters anlam veriyor.**
- Ekran: Özet bant. Dosya: `present.ts:165-169`.
- Gözlem: "Kargo tarifesi ve hizmet bedeli girilmedi: net kâr bu kalemler hariç hesaplanamaz." Cümle "bu kalemler hariç tutularak hesaplanamaz" diye okunuyor; kastedilen "bu kalemler olmadan hesaplanamaz". Ayrıca başlık eksikliği değil kullanıcıya olan faydayı söylemeli.
- Öneri: Başlık "Net kârınızı görmek için kargo tarifenizi ve hizmet bedelini girin" (tek kalem eksikse yalnız o kalem). Ayrıntı satırı ADR §5.2 madde 2 sayılarıyla kalsın. Bant, §5'teki düzende baş kartın içine alınırsa ayrı bant gerekmez.

**[UX-06] Yüksek. Yalnız ürün maliyeti eksikken ne bant ne eylem var; maliyet girecek ekran da yok.**
- Ekran: Özet, Ürünler ("Maliyeti eksik" süzgeci). Dosya: `present.ts:161` (`cargo <= 0 && fee <= 0` ise bant null, maliyet satırı da kaybolur), `present.ts:177`, `product-list.tsx:47-50`.
- Gözlem: Ürün maliyeti en büyük gider kalemi ve en sık eksik kalacak bilgi. Kargo ve hizmet bedeli girilmiş, maliyeti eksik bir hesapta özet "Hesaplanamadı / Eksik: ürün maliyeti" diyor ama ne yapılacağını söylemiyor. "Maliyeti eksik" süzgeci ürünleri buluyor ama maliyet girişi yok.
- Öneri: Bant (ya da baş kart) maliyet eksikliğinde de çıksın: "N ürünün maliyeti girilmedi. Maliyetleri girince bu ürünlerin net kârı görünür." + "Maliyetleri gir" (maliyet ekranına ya da `?filter=missing_cost`'a). Maliyet girişi için §8.1.

**[UX-07] Yüksek. Kesin zarardaki ürün "Hesaplanamadı" ile nötr görünüyor; zarar yalnız küçük rozette.**
- Ekran: Ürünler kartı ve tablosu; Ürün kırılımı özet kartı. Dosya: `product-list.tsx:260-268` (`KnownExpensesNote` gri, 12 px, ikon ve renk yok), `shared.tsx:323-337`, `product-detail.tsx:258-262` (kırılımda zarar nedeni rozeti yok).
- Gözlem: `known_expenses` ürününde net kâr hücresi siyah "? Hesaplanamadı", altında gri "Eksik giderler hariç kâr: -₺4,00". Satıcı için en önemli bilgi (bu ürün kesin zararda) renk ve ikon almıyor. Kırılım sayfasında aynı ürün için "Bilinen giderlerle bile zarar" rozeti hiç yok, liste ile kırılım tutarsız.
- Öneri: `loss_reason` doluysa hücrede `ProfitValue` (kırmızı, aşağı ok) ile "En az -₺4,00 zarar" ve altında küçük not "Kargo ve hizmet bedeli eklenince zarar büyür." Eksik kalemler giderdir, bu yüzden bilinen rakam net kârın üst sınırıdır; "en az" ifadesi doğrudur. Kırılım özetinde `eksik_giderler_haric_kar < 0` ise aynı rozet ve aynı kırmızı gösterim. Pozitif değerde yeşil kullanılmasın (UX-21).

**[UX-08] Yüksek. Özetteki "Tüm uyarılar" bağlantısı "Şu an bir uyarı yok" diyen sayfaya gidiyor.**
- Ekran: Özet uyarı kartı, Uyarılar. Dosya: `summary-view.tsx:290-295`, `src/app/(app)/panel/uyarilar/page.tsx:18`, `summary-view.tsx:272` (hata metni de bu sayfaya yönlendiriyor).
- Gözlem: Özet "Zararına satış 3, Ürün maliyeti girilmemiş 2" gösteriyor; bağlantıya basan kullanıcı "Şu an bir uyarı yok ... Mağazanızı bağlayınca uyarılar çalışmaya başlar" ve "Mağazayı bağla" görüyor. İki ekran birbirini yalanlıyor. Persona B'nin itirazı "rakamlar tutar mı" sorusudur; bu tür çelişki güveni en hızlı bozan şeydir.
- Öneri: Uyarılar listesi (§8.3) gelene kadar bağlantı kaldırılsın ya da her uyarı satırı ilgili ürün süzgecine gitsin (ZARAR -> `/panel/urunler?filter=loss&order=asc`, MALIYET_EKSIK -> `?filter=missing_cost`). Hata metni (satır 272) "Biraz sonra tekrar deneyin." olsun.

**[UX-09] Yüksek. Ürün kırılımı özet kartı giderlerin bir kısmını göstermiyor; satırlar toplanınca net kâr tutmayabilir.**
- Ekran: Ürün kırılımı. Dosya: `product-detail.tsx:231-246`.
- Gözlem: Kart net satış, ürün maliyeti, komisyon, kargo (gönderi) ve platform hizmet bedelini listeliyor. `ProductTotals` içinde gelen `kargo_iade`, `ceza`, `degisken_giderler` gösterilmiyor. İadesi ya da cezası olan bir üründe kullanıcı rakamları alt alta toplayınca net kârı bulamaz. Ürün tanıtım sayfası "ekranda topladığınızda net kârı kuruşu kuruşuna bulursunuz" diyor (`src/app/(marketing)/ozellikler/page.tsx:18`).
- Öneri: Sıfır olmayan tüm gider satırları gösterilsin (sıfır olanlar gizlenebilir), sonda çizgi ve "Net kâr" toplam satırı. Reklam ürün toplamında yoksa (tipte alan yok) bu açıkça yazılsın: "Reklam bu üründe satırlara dağıtılmadı" ya da alan eklensin.

**[UX-10] Yüksek. "Eksik" rozeti kırmızı (zarar tonu) ve bir satırda üç kez tekrarlanıyor.**
- Ekran: Özet baş kart, Ürünler. Dosya: `present.ts:75-76` (`eksik` -> `tone: 'loss'`), `product-list.tsx:270-281`, `shared.tsx:330-333`.
- Gözlem: Ayarsız hesabın ilk gördüğü kart "Hesaplanamadı / Eksik: ürün maliyeti, kargo, hizmet bedeli / [Eksik]" (kırmızı). Ürün satırında "Hesaplanamadı", "Eksik: kargo, hizmet bedeli", "Kargo eksik" rozeti ve "Eksik" rozeti aynı bilgiyi dört kez veriyor. Kırmızı bu üründe zarar ve hata için ayrılmış renk (60 §2 `--loss`); eksik veri için kullanılınca kullanıcı "zarar ediyorum" ya da "hata var" diye korkar. Görev tanımındaki "korkutmadan yönlendirme" hedefine ters.
- Öneri: `eksik` kesinliği `warning` ya da `neutral` tonunda ve metni "Bilgi eksik" olsun. "Hesaplanamadı" hücresi eksik kalemleri zaten adıyla söylüyorsa listede "Eksik" kesinlik rozeti ve "Kargo eksik" rozeti gösterilmesin (tek kaynak: "Eksik: kargo, hizmet bedeli" satırı). Kalan rozet sırası: zarar nedeni, kesinlik.

### 2.3 Orta

**[UX-11] Orta. Tam satır yokken üç kart "Hesaplanamadı" diyor.**
- Ekran: Özet ayarsız, masaüstü. Dosya: `summary-view.tsx:169-197`, `present.ts:204-214`.
- Gözlem: Net kâr, toplam gider ve marj kartları üst üste "Hesaplanamadı". Bilgi vermiyor, ürün çalışmıyor izlenimi veriyor.
- Öneri: `tam_satirlar.satir_sayisi = 0` iken toplam gider ve marj kartları hiç çizilmesin (ADR §5.2 madde 4, "kart yoktur" ilkesiyle aynı). Yerlerine "Bilinen giderler" kartı konabilir: komisyon ve dönem düzeyi giderler gibi kesin bilinen tutarlar, "kargo ve hizmet bedeli hariç" etiketiyle.

**[UX-12] Orta. Kesinlik ve satır durumu iki ayrı sayımla, iki farklı adla veriliyor.**
- Ekran: Özet, Ürün kırılımı. Dosya: `summary-view.tsx:29-34` ("Tahmini (ekstresiz)", "Ekstreli"), `summary-view.tsx:148-152` ("Kesin 30, tahmini 20, eksik 0 satır"), `product-detail.tsx:48-53` ("Ekstre bekleniyor"), `product-detail.tsx:351-357` (satır kartında "Kesin" + "Ekstreli" iki rozet).
- Gözlem: Aynı ekranda "Kesin 30" ve "Ekstreli 24, Düzeltilmiş 4, İptal 2" yan yana. Kullanıcı hangisinin doğru olduğunu soracak. Aynı durum özette "Tahmini (ekstresiz)", kırılımda "Ekstre bekleniyor" adını alıyor.
- Öneri: Özette tek cümle yeterli: "50 satıştan 30'unun hakedişi kesinleşti, 20'si Trendyol ekstresini bekliyor." "Satır durumları" kartı kaldırılsın ya da "Ayrıntı" altında katlansın. Terim seti tekleştirilsin: "Kesin" (hakediş geldi), "Tahmini" (ekstre bekleniyor), "Bilgi eksik", "İptal". Satır kartında kesinlik rozeti yeterli; durum rozeti yalnız "Düzeltilmiş" ve "İptal" için gösterilsin.

**[UX-13] Orta. "Tahmini" rozeti ne anlama geldiğini ve ne zaman değişeceğini söylemiyor.**
- Ekran: Özet baş kart, Ürünler. Dosya: `summary-view.tsx:133`, `present.ts:73-74`.
- Gözlem: Kullanıcı "Tahmini ₺3.120,45" görüyor; bu rakama güvenip güvenemeyeceğini, ne zaman kesinleşeceğini bilmiyor.
- Öneri: Baş kartta rozetin altına tek satır: "20 satışın hakedişi henüz gelmedi; ekstre gelince rakam kesinleşir." Rozet bir açıklama penceresi açmasın (mobilde dokunma ile açılan ipuçları kaçırılıyor), metin doğrudan görünsün.

**[UX-14] Orta. Metrik kartlarının başlıkları yalnız rakam; ekran okuyucunun başlık listesinde etiket yok.**
- Ekran: Özet, Ürün kırılımı. Dosya: `summary-view.tsx:126-127, 158-159, 171-172, 189-190` (`CardDescription` etiketi `<p>`, rakam `<h2>`), `product-detail.tsx:251-252`.
- Gözlem: Başlıklar arası gezinen ekran okuyucu kullanıcısı "₺3.120,45 Tahmini", "₺18.450,00", "₺15.329,55", "%16,9" duyuyor; hangisinin net kâr olduğunu bilemiyor (WCAG 2.4.6 Başlıklar ve etiketler, 1.3.1).
- Öneri: Etiket başlık olsun ("Net kâr" `<h2>`), rakam altında `<p>`; ya da metrikler tek bir `<dl>` içinde (`<dt>Net kâr</dt><dd>...</dd>`). Görünüm aynı kalabilir.

**[UX-15] Orta. Ayarsız hesapta "Zarar eden ürün yok" boş durumu yanıltıcı.**
- Ekran: Ürünler, `filter=loss` boş. Dosya: `product-list.tsx:43-46`.
- Gözlem: Ayarsız hesapta çoğu ürün "Belirsiz". Liste boş kalınca "Zarar eden ürün yok. Bu dönemde zararı kesin olan bir ürün bulunmadı." yazıyor; kullanıcı ilk cümleyi okuyup rahatlıyor, "kesin" kelimesinin önemini kaçırıyor.
- Öneri: Belirsiz ürün varsa: başlık "Zararı kesin olan ürün yok", açıklama "N ürünün kârı belirsiz: kargo ve hizmet bedeli girilmeden zarar edip etmedikleri bilinemez." + "Kargo ve hizmet bedelini girin". Belirsiz sayısı için liste yanıtına sayı eklenmesi ya da `filter=all` toplamından türetme gerekir.

**[UX-16] Orta. Ürünler sayfasında ayarsız hesap için kurulum çağrısı yok (§7 madde 5).**
- Ekran: Ürünler. Dosya: `product-list.tsx:61-92`.
- Gözlem: Denetim §7 madde 5: "ayarsız hesapta bu liste yerine kurulum çağrısı". Liste ayarsız hesapta her satırda "Hesaplanamadı" gösteriyor, sayfa düzeyinde ne yapılacağını söyleyen bir şey yok.
- Öneri: Özet bandının kısa hali listenin üstünde: "Kargo tarifesi ve hizmet bedeli girilmediği için N ürünün net kârı hesaplanamıyor. [Girin]". Sayı için özet yanıtı ya da liste yanıtındaki eksik sayımları kullanılabilir.

**[UX-17] Orta. Mobil ürün listesinde denetimler ilk ekranın yarısını kaplıyor; "Sırala" ve "Yön" anlaşılması zor.**
- Ekran: Ürünler mobil. Dosya: `product-list.tsx:63-75, 134-172`, `query.ts:15-20`.
- Gözlem: Başlık + açıklama + dönem + 3 süzgeç (iki satıra kırılıyor) + 2 seçim kutusu + sayım satırından sonra ilk ürün kartı yaklaşık 515 px'te başlıyor; ilk ekranda tek ürün görünüyor. "Net kâr / Azdan çoğa" seçiminin "en çok zarar önce" demek olduğunu satıcı çıkaramaz.
- Öneri: Tek seçim kutusu, anlamlı seçeneklerle: "En çok kâr", "En çok zarar", "En yüksek marj", "En düşük marj", "En çok satış", "En çok adet". Süzgeçler tek satırda yatay kaydırılan çipler. Mobilde sayfa açıklaması gizlensin. Hedef: 390 px'te ilk ekranda en az 2 ürün kartı.

**[UX-18] Orta. "Maliyetsiz bile zarar" metni §7'den sapıyor ve belirsiz.**
- Ekran: Ürünler. Dosya: `present.ts:108`.
- Gözlem: Denetim §7 madde 5 etiketi "maliyet girilmese de zarar". "Maliyetsiz" kelimesi "maliyeti olmayan ürün" diye de okunur.
- Öneri: "Maliyet girilmese de zarar" (rozet için uzunsa: "Maliyet hariç bile zarar"). Test (`present.test.ts`) metne göre güncellensin.

**[UX-19] Orta. Ürün kırılımında her sipariş satırı 9 satırlık tablo; 50 satırlık sayfa mobilde çok uzun.**
- Ekran: Ürün kırılımı mobil. Dosya: `product-detail.tsx:399-433`.
- Gözlem: Sık satan bir üründe kullanıcı sipariş başına tam döküm görüyor (Ceza ₺0,00, Reklam ₺0,00, "Yok" rozetleri dahil). Asıl soru "hangi sipariş zarar etti" ise cevap kaydırma altında kayboluyor.
- Öneri: Satır kartı varsayılan kapalı: sipariş no, net kâr, kesinlik rozeti, uyarı rozetleri. "Kalemleri göster" (`<details>`/`<summary>`, 44 px) ile döküm açılsın. Uyarılı satırlar (BEKLENMEYEN_KESINTI, IADE_KAYDI_BEKLENIYOR) açık başlasın. Sıfır ve kaynağı `yok` olan kalemler gizlensin (UX-30).

**[UX-20] Orta. Kullanıcıya dönük metinlerde iç jargon.**
- Ekran: Özet, Ürünler, Kırılım. Dosya: `summary-view.tsx:204` ("Ekstresi gelen satırlar kesinleşir."), `summary-view.tsx:262` ("Dönemde motorun işaretlediği durumlar."), `present.ts:153` ve `175` ("12 satırda kargo ... tahmini eksik"), `product-detail.tsx:505-507` ("eşik"), `present.ts:95` ("Eşleşen"), `product-detail.tsx:334` ("Değişken giderler"); arka uç uyarı metni (`test-fixtures.ts:109`) "satırın net kârı".
- Gözlem: "Satır", "motor", "eşik", "eşleşen" satıcının dili değil. Satıcı "sipariş", "satış", "hakediş" ile düşünür (research/05 §2.3).
- Öneri: "motorun işaretlediği durumlar" -> "Bu dönemde dikkat etmeniz gerekenler"; "Ekstresi gelen satırlar kesinleşir" -> "Trendyol hakediş ekstresi gelince rakamlar kesinleşir"; "satırda" -> "satışta" (ADR §5.2 madde 2 örnek metni de buna göre güncellenmeli; karar ürün sahibinde); karşılaştırma notu -> "Trendyol beklediğimizden ₺X fazla kesti. ₺Y altındaki farkları göstermiyoruz."; "Eşleşen" -> kaynağın ne olduğunu söyleyen ad ("Kargo faturasından" gibi, arka uç anlamı doğrulanmalı); "Değişken giderler" -> "Diğer giderleriniz" ya da ayar ekranındaki adıyla.

**[UX-21] Orta. Kısmi dönemde pozitif "eksik giderler hariç kâr" yeşil gösterilirse net kâr sanılır (docs/12 §9 madde 23).**
- Ekran: Özet (K39 Revizyon 1 sonrası), Ürünler, İade notu. Dosya: `product-detail.tsx:390-392` (iade notu tahmini `ProfitValue` ile yeşil), öneri UX-01 uygulanırken.
- Gözlem: Bu rakam net kârın üst sınırıdır (eksik kalemler giderdir). Yeşil yukarı ok ve büyük punto "kârdayım" mesajı verir; madde 23'ün sorduğu risk tam budur.
- Öneri: Pozitifken nötr renk (`foreground`) ve ikon yok, yanında "Kargo ve hizmet bedeli düşülünce azalacak."; negatifken kırmızı + "Bilinen giderlerle bile zarar" vurgusu (ADR §5.2 madde 3). İade notundaki tahmin net kâr null iken aynı kurala uysun.

**[UX-22] Orta. Rakamların ne zamana kadar güncel olduğu ve hangi ayarla hesaplandığı görünmüyor (ADR-0007 §5.2 madde 6, §6).**
- Ekran: Özet, Ürünler, Kırılım. Dosya: `summary-view.tsx:115-226` (alt bilgi yok), `src/lib/api/profit.ts:92-97` (`settings_revision` tipte yok).
- Gözlem: ADR "Ayar sürümü {settings_revision}" alt bilgisi ve son senkron zamanını istiyor. Satıcı "bugün gelen siparişler dahil mi" sorusunu da soracaktır.
- Öneri: Sayfa altında küçük metin: "Son güncelleme: bugün 14:32 · Ayar sürümü 7 · Ayar geçmişi". Arka uç alanı gelince tipe eklensin. Senkron 2 saatten eskiyse metin uyarı tonunda.

**[UX-23] Orta. Ürün bulunamadığında "Tekrar dene" sunuluyor.**
- Ekran: Ürün kırılımı 404. Dosya: `product-detail.tsx:129-135`, `src/lib/profit/errors.ts:84-86`.
- Gözlem: 404'te tekrar denemek sonucu değiştirmez. "İstenen kayıt bulunamadı." da genel.
- Öneri: 404'te başlık "Bu ürün bu dönemde bulunamadı", metin "Başka bir dönem seçebilir ya da ürün listesine dönebilirsiniz.", düğme "Ürünlere dön". Tekrar dene yalnız ağ ve 5xx hatalarında.

**[UX-24] Orta. Dönem seçeneklerinde takvim ayı yok.**
- Ekran: Tüm rapor ekranları. Dosya: `query.ts:9-13`.
- Gözlem: "Bugün / 7 gün / 30 gün" günlük karar için iyi. Persona B'nin sorusu "bu ay neden az para kaldı", muhasebeci ay kapanışı ister, en güçlü satın alma anı "Kasım'da gerçekte ne kazandınız" (research/05 §2.4). 30 gün ile takvim ayı farklı rakam verir.
- Öneri: "Bu ay" ve "Geçen ay" seçenekleri (API `range` genişletmesi gerekir). Mobilde 5 seçenek sığmazsa "Bugün / 7 gün / Bu ay / Diğer" + açılır seçim.

### 2.4 Düşük

**[UX-25] Düşük. Sayfa açıklamaları mobilde yer kaplıyor; Özet açıklaması ayarlı kullanıcıya "eksik" diyor.**
- Ekran: Özet, Ürünler. Dosya: `summary-view.tsx:36-39`, `product-list.tsx:63-66`.
- Gözlem: "Seçtiğiniz dönemde ne kazandığınız ve hangi kalemlerin eksik olduğu." her kullanıcıya eksiklik ima ediyor; mobilde 2 satır.
- Öneri: "Seçtiğiniz dönemde ne kazandığınız ve hangi ürünün zarar ettirdiği." Mobilde açıklama gizlenebilir (`hidden sm:block`).

**[UX-26] Düşük. Rozet metni 12 px.**
- Ekran: Tüm rapor ekranları. Dosya: `src/components/ui/badge.tsx:69` (`text-xs`).
- Gözlem: Kontrast yeterli (warning 5,85:1, loss 5,46:1, info 7,71:1; koyu temada daha yüksek) ama 40 yaş üstü kullanıcılar için zarar nedeni gibi karar metinleri küçük.
- Öneri: Rapor ekranlarında anlam taşıyan rozetler (zarar nedeni, kesinlik) `text-sm`.

**[UX-27] Düşük. Kart bağlantısının odak halkası yalnız başlığın çevresinde; tablo satırında `position: relative` doğrulanmalı.**
- Ekran: Ürünler. Dosya: `product-list.tsx:288-295` (kartın tamamı tıklanır, halka başlıkta), `product-list.tsx:362-370` (`<tr className="relative">` ve `after:absolute after:inset-0`).
- Gözlem: Klavye kullanıcısı tıklanır alanın tüm kart olduğunu görmüyor. Bazı tarayıcıların eski sürümleri `tr` üzerinde `relative`'i yok sayar; o durumda örtü tüm tabloyu kaplar ve her tıklama son satıra gider.
- Öneri: Karta `focus-within:ring-2`; masaüstü tabloyu Safari'de ve Firefox'ta elle doğrulayın. Sorun çıkarsa örtüyü ilk hücreyle sınırlayın.

**[UX-28] Düşük. Ekran görüntüleri yalnız ilk ekranı içeriyor; örnek verilerde dönem ve uyarı çelişkisi var.**
- Ekran: `docs/ux/ekranlar/rapor-*`. Dosya: `e2e/profit.spec.ts:93` (`page.screenshot({ path })`, `fullPage` yok), `src/lib/profit/test-fixtures.ts:17` (dönem her istekte 30 gün), `test-fixtures.ts:108-110`.
- Gözlem: Özet görüntülerinde uyarı kartı, zarar düğmesi ve kısmi dönem bloğu görünmüyor; inceleme alt kısmı göremiyor. "7 gün" seçiliyken "Dönem: 12.10.2026 - 10.11.2026" (30 gün) yazıyor. Ayarlı özette net kâr rakamı varken uyarı kartı "Ürün maliyeti girilmemiş; net kâr hesaplanamıyor" diyor. Gerçek veride bunlar olmaz ama görüntüleri paydaşlara gösterirken kafa karıştırır.
- Öneri: `fullPage: true` ile ek görüntü (`-tam` son ekiyle); örnek dönem `range`'e göre üretilsin; ayarlı senaryoda uyarı sayıları özetle tutarlı olsun. Kısmi dönem (tam satır > 0) için ayrı görüntü eklensin.

**[UX-29] Düşük. Aynı eylem için üç farklı düğme metni; aynı kalem için iki ad.**
- Ekran: Özet, Ürünler, Kırılım, Ayarlar. Dosya: `summary-view.tsx:66` ("Bağlantıya başla"), `product-list.tsx:85` ve `product-detail.tsx:88` ("Mağazayı bağla"), ayarlar diyalog düğmesi ("Trendyol mağazasını bağla"); `product-detail.tsx:243` ve `:330` ("Platform hizmet bedeli") ile `present.ts:28` ("hizmet bedeli").
- Öneri: Tek düğme metni "Trendyol mağazanızı bağlayın" ya da kısa hali "Mağazayı bağla"; kalem adı her yerde "Hizmet bedeli" (ilk geçtiği yerde "Trendyol platform hizmet bedeli").

**[UX-30] Düşük. Kaynak sütununda "Yok" rozeti ve dağıtım bilgisinin kaybolması.**
- Ekran: Ürün kırılımı satır tablosu. Dosya: `present.ts:85-101`.
- Gözlem: Gideri olmayan kalem "₺0,00 [Yok]" olarak görünüyor, gürültü. `kesin_dagitim` ve `dagitim_tahmini` (ceza, reklam gibi dağıtılan tutarlar) "Kesin" / "Tahmini" diye gösteriliyor; kullanıcı bu tutarın siparişe değil döneme ait olduğunu bilmiyor.
- Öneri: Kaynağı `yok` ve tutarı sıfır olan satır gizlensin. Dağıtılan tutarlar "Kesin, dağıtıldı" gibi ikinci bir sözcük alsın.

**[UX-31] Düşük. İade notunda "Tahmini" hem metinde hem rozette.**
- Ekran: Ürün kırılımı. Dosya: `product-detail.tsx:385-396`.
- Öneri: Rozet kalsın, metin "Ürün stoğa dönerse net kâr: ₺X" olsun; ya da tersi. §7 madde 6 rozeti şart koştuğu için rozet tutulmalı.

**[UX-32] Düşük. Tarih biçimi okunması yavaş.**
- Ekran: Tüm rapor ekranları. Dosya: `present.ts:319-327`.
- Gözlem: "12.10.2026 - 10.11.2026" hızlı okunmuyor, yıl iki kez tekrarlanıyor.
- Öneri: "12 Ekim - 10 Kasım 2026" (aynı yıl), "Bugün, 10 Kasım" (tek gün). `Intl.DateTimeFormat('tr-TR', { day: 'numeric', month: 'long' })`.

## 3. Etiketlerin anlaşılırlığı ve tutarlılığı

| Etiket | Nerede | Kullanıcının olası okuması | Sorun | Öneri |
|---|---|---|---|---|
| Hesaplanamadı | Özet, liste, kırılım | "Sistem hata verdi" | Neden ve çözüm yanında değil (özette bantta, listede yok) | Kural metni korunur ("Net kâr hesaplanamadı"), yanında her zaman eksik kalem + tek eylem. "Henüz" eklenmesi (madde 23 testine göre) ADR sahibinin onayıyla. |
| Eksik (kesinlik rozeti) | Özet, liste | "Zarar / hata" (kırmızı) | Kırmızı ton, üçlü tekrar (UX-10) | "Bilgi eksik", uyarı tonu, eksik kalem satırı varsa gösterme |
| Eksik: kargo, hizmet bedeli | Hücre alt satırı | Doğru anlaşılır | Yok | Kalsın; tek kaynak bu olsun |
| Kargo eksik | Liste rozeti | Doğru | Tekrar | Kaldır |
| Tahmini | Rozet | "Uydurma mı?" | Ne zaman kesinleşeceği yok (UX-13) | Yanında tek cümle |
| Kesin | Rozet | Doğru | Mavi "bilgi" tonu, güven vurgusu zayıf | Kalsın |
| Belirsiz | Liste rozeti | "Ne belirsiz?" | Öznesiz | "Kâr belirsiz" |
| Zarar | Liste rozeti | Doğru | Yok | Kalsın |
| Maliyetsiz bile zarar | Liste rozeti | "Maliyeti olmayan ürün" | §7 metninden sapma (UX-18) | "Maliyet girilmese de zarar" |
| Bilinen giderlerle bile zarar | Liste rozeti | Doğru, ama hücre nötr | Rakam renk almıyor (UX-07) | Hücrede "En az -₺X zarar", kırmızı |
| Eksik giderler hariç kâr | Liste, kırılım | "Net kâr" sanılabilir | Rakam gri, hangi giderin hariç olduğu etiketin içinde değil | "Bilinen giderlerle kâr (kargo ve hizmet bedeli hariç)" ya da §7'deki "Eksik giderler hariç kâr (kargo ve hizmet bedeli hariç)"; ekranlar arasında aynı metin |
| Tahmini (ekstresiz) / Ekstre bekleniyor / Ekstreli | Özet, kırılım | Karışık | Aynı durum iki ad (UX-12) | "Tahmini (ekstre bekleniyor)", "Kesin (hakediş geldi)" |

Kurulum bandı tonu: uyarı rengi ve üçgen ikon kabul edilebilir, ama başlık suçlayıcı ve ters anlamlı ("girilmedi: ... hesaplanamaz"). Fayda dili ("Net kârınızı görmek için ... girin") ve tek, çalışan bir eylem (UX-02, UX-05) korkutmadan yönlendirir. Bilinen rakamın gösterilmesi (UX-01) kullanıcıya "uygulama çalışıyor, bir adım kaldı" mesajını verir.

## 4. Bilgi hiyerarşisi, mobil yoğunluk, dokunma hedefleri ve durumlar

**İyi olanlar (doğrulandı):**
- Dokunma hedefleri: dönem seçici (`shared.tsx:403`, `min-h-touch min-w-touch`), süzgeç çipleri (`product-list.tsx:115`), seçim kutuları (`product-list.tsx:132`), "Tüm uyarılar" (`summary-view.tsx:292`), "Ürünlere dön" (`product-detail.tsx:64`), ürün kartının tamamı (`product-list.tsx:292`) 44 px ve üstü.
- Yükleniyor: `ReportSkeleton` `role="status"` + gizli "Yükleniyor" (`shared.tsx:440-452`); uyarı kartı kendi yükleniyor metniyle ayrı (`summary-view.tsx:265-269`); "Daha fazla yükle" düğmesi yüklenirken kilitli.
- Hata: ayrıntı sızdırmadan sade cümle ve "Tekrar dene" (`errors.ts:76-95`, `shared.tsx:419-438`); sayfa sonu yükleme hatası listeyi silmiyor (`product-list.tsx:217-221`).
- Boş: dönemde sipariş yok, mağaza bağlı değil, süzgece göre boş liste ayrı metinlerle.
- İmleç geçersizse baştan yükleme ve "Liste güncellendiği için baştan yüklendi." bildirimi (`product-list.tsx:193-200`).
- Dönem, süzgeç ve sıralama URL'de; geri düğmesi ve paylaşım çalışıyor.
- Mobilde kart, masaüstünde tablo; yatay taşma e2e'de denetleniyor (`profit.spec.ts:89-92`).

**Eksikler:**
- Hiyerarşi: özetin sırası (net kâr, net satış, toplam gider, marj, satır durumları, uyarılar, zarar düğmesi) "önce sonuç" ilkesine yarı uyuyor; ikinci soru (zarar ettiren ürün) en sonda (UX-03). Önerilen sıra: 1) dönem net kârı ya da bilinen kâr + kurulum adımı, 2) zarar ettiren ürünler (ilk 3), 3) uyarılar, 4) net satış / gider / marj (ikincil, küçük), 5) kesinlik özeti, 6) alt bilgi (güncellik, ayar sürümü).
- Mobil yoğunluk: Ürünler'de ilk ekranda tek ürün (UX-17); kırılımda satır başına uzun tablo (UX-19).
- Boş durum: ilk senkron sürerken "Bu dönemde sipariş yok" ile "siparişler henüz çekiliyor" ayrılmıyor (`summary-view.tsx:99-110`). Senkron durumu API'de varsa: "Siparişleriniz çekiliyor. İlk rakamlar birkaç dakika içinde burada." + ilerleme.
- Yükleniyor: özet iskeleti 4 eşit gri blok; gerçek düzene benzemiyor (baş kart büyük, diğerleri küçük). Düşük öncelik, bulgu sayılmadı.

## 5. Sunum kurallarına uyum ve K39 Revizyon 1 ile özet ekranında ne değişmeli

### 5.1 Uyum tablosu (denetim §7 + ADR-0007 §5.2)

| Kural | Durum | Kanıt / not |
|---|---|---|
| §7.1 Null net kâr "Hesaplanamadı" + eksik kalem adları, asla 0,00 | Uyuyor | `present.ts:56-64`, `shared.tsx:323-357`; test `profit-screens.test.tsx:97` |
| §7.1 Eksik giderler hariç kâr ayrı ve eksik kalemleri sayan etiketle | Kısmen | Ayrı gösteriliyor; etiket eksik kalemleri saymıyor, adlar bir üst satırda. Rakam renksiz (UX-07) |
| §7.1 Eksik kalem hücresi "eksik" | Uyuyor | `present.ts:256-259`, `product-detail.tsx:421-425` |
| ADR §5.2.1 Tam dönemde `donem_net_kar` ve marj | Uyuyor | `present.ts:188-197` |
| ADR §5.2.2 Kısmi dönemde "Dönem net kârı hesaplanamadı" + satır sayıları + bağlantı | Kısmen | Değer "Hesaplanamadı", etiket "Net kâr" (dönem yok); sayılar ve bağlantı ayrı bantta |
| ADR §5.2.3 "Eksik giderler hariç dönem kârı" | Uymuyor | Alan tipte ve ekranda yok (UX-01) |
| ADR §5.2.4 "Eksiksiz N satır" alt kartı, 0 ise yok | Kısmen | Baş kartın içinde paragraf (`summary-view.tsx:142-147`), marj ayrı kartta; 0 iken çizilmiyor (doğru) |
| ADR §5.2.5 Toplam gider tam satırlardan, dönem düzeyi gider ayrı satır | Uyuyor | `present.ts:208-214`, `summary-view.tsx:178-183`. Şelale yok |
| ADR §5.2.6 Ayar sürümü alt bilgisi | Uymuyor | UX-22 |
| §7.3 Bant `eksik_kalem_satir_sayilari`'na bağlı, `settings_configured` yok | Uyuyor | `present.ts:157-178`. Maliyet eksikliğinde bant yok (UX-06) |
| §7.4 "Kesin" yalnız kesinlikten; `statement_basis` kesinlik değil | Uyuyor | `present.ts:69-82`; `basis` kullanılmıyor |
| §7.5 Zarar nedeni etiketleri | Kısmen | `contribution_before_cost` metni farklı (UX-18) |
| §7.5 Belirsiz "kârlı" değil | Uyuyor | `present.ts:119` |
| §7.5 Ayarsız hesapta "en kârlı" yerine kurulum çağrısı | Uymuyor | Ürünler sayfasında çağrı yok (UX-16) |
| §7.5 "En çok zarar edenler" `filter=loss` ile | Uyuyor | `summary-view.tsx:223`; ama sıra yanlış yönde (UX-04) |
| §7.6 İade kaydı bekleyen satır notu ve "Tahmini" rozeti | Uyuyor | `present.ts:269-278`, `product-detail.tsx:384-397` |
| §7.7 Beklenmeyen kesinti dökümü, varsayılan desi ipucu, kod başına gruplama | Uyuyor | `product-detail.tsx:445-511`, `present.ts:304-315`; özet uyarıları kod başına |
| §7.9 Ürün başlığı metin düğümü | Uyuyor | React metin düğümü, `dangerouslySetInnerHTML` yok |
| §7.10 İptal "İptal", 0,00 yok | Uyuyor | `present.ts:61`, `product-detail.tsx:368-371`. Küçük not: `product-detail.tsx:258` yalnız `iptal`'i dışlıyor, `yok`'u dışlamıyor; ürün düzeyinde `yok` iken "Eksik giderler hariç kâr" satırı görünebilir |
| §7.11 `cursor_invalid` 422'de baştan yükleme | Uyuyor | `errors.ts:67-73`, `use-paged-list.ts` |

### 5.2 K39 Revizyon 1 ile özet ekranı (önerilen düzen)

Arka uç (çalışma ağacında, başka ajanın işi) kısmi dönemde `donem_net_kar` ve `satir_net_kar_toplami` için null, her dönemde `donem_eksik_giderler_haric_kar` döndürüyor. Panel tarafında yapılacaklar:

1. **Tip:** `PeriodTotals.donem_net_kar: Money | null`, `satir_net_kar_toplami: Money | null`, `donem_eksik_giderler_haric_kar: Money`. `summaryView` `net_kar_kismi=false` iken de `donem_net_kar === null` durumunu "hesaplanamadı" saysın (savunma; kural ihlali olursa 0,00 yerine boş).
2. **Baş kart tek kart olsun, bant onun içine girsin.** Ayrı bant + "Hesaplanamadı" kartı aynı mesajı iki kez veriyor.
3. **Pozitif bilinen rakam yeşil değil** (UX-21); negatifte kırmızı + "bilinen giderlerle bile zarar".
4. **Tam satır 0 iken** toplam gider, marj ve "Eksiksiz N satır" yok (UX-11).
5. **Ürün listesi ve kırılım aynı etiketi kullansın**, özetteki "dönem" sözcüğü hariç.

Metin tabanlı tel çerçeve, 390 px, üç durum:

```
A) Tam dönem (net_kar_kismi = false)
------------------------------------------------
Özet                         [Bugün][7 gün][30 gün]
12 Ekim - 10 Kasım 2026

[Kart] Dönem net kârı
  (yukarı ok) ₺3.120,45            [Tahmini]
  20 satışın hakedişi henüz gelmedi; ekstre gelince kesinleşir.
  Marj %16,9

[Kart] Zarar ettiren ürünler
  Silikon Kek Kalıbı Set      -₺30,00   [Zarar]
  ...                                   Tümünü gör (3)

[Kart] Uyarılar (kod başına, her satır ilgili listeye gider)
[Küçük] Net satış ₺18.450,00 · Toplam gider ₺15.329,55
Son güncelleme bugün 14:32 · Ayar sürümü 7
```

```
B) Kısmi dönem, eksiksiz satır var (tam_satirlar.satir_sayisi > 0)
------------------------------------------------
[Kart] Dönem net kârı
  (?) Dönem net kârı hesaplanamadı
  4 satışta kargo tarifesi eksik.
  [Kargo tarifenizi girin]

  Eksik giderler hariç dönem kârı (kargo hariç)
  ₺1.240,00   (nötr renk, ikon yok)
  Kargo düşülünce azalacak.

  [Alt kart] Eksiksiz 20 satış
    Net kâr ₺800,00 · Marj %12,5
    Dönem giderleri hariç.
```

```
C) Kısmi dönem, eksiksiz satır yok (yeni hesap, G49 benzeri)
------------------------------------------------
[Kart] Dönem net kârı
  (?) Dönem net kârı hesaplanamadı
  12 satışta kargo, 12 satışta hizmet bedeli tahmini eksik.
  2 ürünün maliyeti girilmedi.
  [Kargo ve hizmet bedelini girin]

  Eksik giderler hariç dönem kârı
  (ürün maliyeti, kargo ve hizmet bedeli hariç)
  (aşağı ok, kırmızı) -₺17,35   [Bilinen giderlerle bile zarar]

(Toplam gider, marj ve eksiksiz satır kartı yok.)
```

Notlar: "net kâr" sözcüğü bilinen rakamın etiketinde geçmiyor (ADR §5.2 madde 3). "satışta" önerisi ADR örnek metninden ("satırda") sapar; ürün sahibi onaylamazsa "satırda" kalır. "(?) Dönem net kârı hesaplanamadı" ADR metniyle birebir.

## 6. Erişilebilirlik (WCAG 2.2 AA)

- **Kontrast:** Rozet ve bant çiftleri hesaplandı: warning/warning-soft 5,85:1 (koyu 8,11:1), loss/loss-soft 5,46:1 (koyu 7,26:1), info/info-soft 7,71:1, muted/surface 7,08:1. `tokens.test.ts:62-64` warning çiftini koruyor. Sorun yok.
- **Renge tek başına dayanma:** `ProfitValue` renk + ok ikonu + gizli "Kâr:/Zarar:" ile iyi. Marj hücresinde ikon gizli ama eksi işareti ve gizli metin var (yeterli). Sorun: kesin zarardaki null ürünün rakamı renk ve ikon almıyor (UX-07); bu renge dayanma değil, sinyalin hiç verilmemesi.
- **Başlıklar:** metrik başlıkları etiketsiz (UX-14).
- **Ekran okuyucu:** ürün sayısı satırı `aria-live="polite"` ile süzgeç değişince duyuruluyor (iyi); dönem ve süzgeç bağlantıları `aria-current` taşıyor (iyi); tablo `caption` ve `scope` doğru; kırılım satır tablosu `th scope="row"` (iyi).
- **Odak:** tüm etkileşimli öğelerde `focus-visible:ring-2`; kart odağı UX-27.
- **Hedef boyutu (2.5.8):** sorun yok, §4.
- **Otomatik denetim:** e2e axe 0 ihlal (açık/koyu, 390/1280). axe başlık içeriğinin anlamını ve metin anlaşılırlığını ölçmez; UX-14 ve UX-20 elle bulundu.

## 7. Türkçe metin kalitesi

- Em dash yok (`components/profit`, `lib/profit`, `app/(app)/panel` tarandı; U+2014 ve U+2013 karakterleri yok). "Siz" dili tutarlı.
- Anlam hatası: bant başlığı (UX-05).
- Jargon: satır, motor, eşik, eşleşen, ekstreli, değişken giderler (UX-20).
- Tutarsız terimler: "Tahmini (ekstresiz)" / "Ekstre bekleniyor" (UX-12), "Platform hizmet bedeli" / "hizmet bedeli" (UX-29), üç bağlantı düğmesi metni (UX-29), "Maliyetsiz bile zarar" / §7 (UX-18).
- İyi örnekler: "Bağlantı yalnız okuma yapar.", "Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.", "İptal: bu satır kâr hesabına girmez.", "Liste güncellendiği için baştan yüklendi."

## 8. Sonraki ekranlar için öneriler

### 8.1 Ayarlar: kâr ayarları formu (en acil; UX-02, UX-06 buna bağlı)

- **Amaç:** Net kârı hesaplanabilir yapmak. **Birincil eylem:** "Kaydet ve rakamları güncelle".
- **Düzen (mobil):** üç adımlı ilerleme ("3 adımdan 1'i tamam"): 1) Kargo tarifesi, 2) Hizmet bedeli, 3) Ürün maliyetleri. Her adımın sonunda "Bu adımla N satışın net kârı hesaplanacak" geri bildirimi. Özetteki bant bu adımlara derin bağlantı verir.
- **Kargo:** firma adı yalnız `carriers` listesinden ve "Diğer firmalar (*)" seçeneğiyle (§7.8); desi kademeleri satır satır, KDV dahil giriş + yanında KDV hariç karşılığı ("54,00 TL KDV dahil = 45,00 TL KDV hariç"); varsayılan desi açıklaması "Siparişte desi yoksa bu kullanılır".
- **Başlangıç tarihi:** varsayılan hesabın ilk siparişinden önce (AB-01), metin "Bu tarihten sonraki siparişlerde kullanılır".
- **0 girildi:** "0 girildi" rozeti (AB-07).
- **Geçmiş değişikliği:** ADR §5.2 ayar ekranı madde 1'deki pencere metinleri birebir; ikincil düğme "Yalnız bugünden itibaren uygula".
- **409:** "Bu kayıt başka bir değişiklikle güncellendi. Ekranı yeniledik." (`role="alert"`, satır içi; yalnız toast değil).
- **Ürün maliyeti:** iki yol: (a) Ürünler listesinde "Maliyeti eksik" süzgecinde her kartta satır içi "Maliyet gir" alanı (16 px girdi, virgül ve nokta ondalığı), (b) toplu CSV yükleme (Persona B, 1.200 SKU). Maliyet girildikçe kart "Hesaplanamadı"dan rakama döner.
- **Ayar geçmişi:** ADR §5.2 madde 2 biçimi; "geri çekildi" ve "geçmişi etkiledi (onaylı)" rozetleri.
- **Ölçülecek:** ayar tamamlama oranı (bağlantıdan sonraki 24 saatte), bant tıklama -> kayıt dönüşümü, adım başına terk.

### 8.2 Siparişler

- **Amaç:** "Bugünkü siparişlerim kâr bıraktı mı". **Birincil eylem:** siparişe dokunup kalem dökümünü görmek.
- Liste kartı: sipariş no, tarih, ürün adları (ilk 2 + "N ürün daha"), sipariş net kârı ya da "Hesaplanamadı", kesinlik rozeti. İptal siparişte rakam yok, "İptal" (§7.10, B-02: `net_profit "0.00"` gösterilmez).
- Süzgeç: Tümü, Zarar edenler, Hakedişi bekleyenler, Beklenmeyen kesinti. Sipariş no ile arama (satıcı müşteri şikâyetinde numarayla gelir).
- Kalem dökümü ürün kırılımıyla aynı bileşen (UX-19 katlanır kart).
- **Ölçülecek:** arama kullanımı, zarar süzgeci kullanımı.

### 8.3 Uyarılar

- **Amaç:** "Neye bakmam gerekiyor". **Birincil eylem:** uyarıdan ilgili ürün ya da siparişe gitmek.
- Kod başına gruplu kartlar, her kartta sayı, bir cümle açıklama, tek eylem: ZARAR -> zarar edenler (en çok zarar önce); MALIYET_EKSIK -> maliyet girişi; KARGO_TARIFESI_EKSIK ve HIZMET_BEDELI_TAHMINI_EKSIK -> ayar adımı; BEKLENMEYEN_KESINTI -> etkilenen siparişler, kalem dökümü ve varsayılan desi ipucu (§7.7); IADE_KAYDI_BEKLENIYOR -> bilgi tonu, eylem yok.
- Önem sırası: para kaybettirenler (zarar, beklenmeyen kesinti) üstte; kurulum eksikleri ayrı "Kurulum" grubunda, uyarı yorgunluğu yaratmasın.
- "Okundu" ya da "Gizle" (dönem bazında); gizlenen sayı görünür kalsın.
- Özet uyarı kartı bu sayfanın ilk 3 grubunu gösterir (UX-08).
- **Ölçülecek:** uyarı -> eylem tıklama oranı, uyarı sonrası 7 günde ilgili ürünün fiyat/maliyet değişikliği.

## 9. Kullanıcı testi senaryoları (5 senaryo)

**Kurulum:** 5 katılımcı (en az 3'ü Persona A: tek mağaza, ayda 100-1.000 sipariş, muhasebeci değil; en az 1'i Persona B). Kendi telefonlarında, yönlendirmeli, sesli düşünme, 25 dakika. Sahte ama gerçekçi veriyle hazırlanmış hesap (e2e örnek verileri genişletilerek). Her senaryodan sonra tek soru: "Bu görev ne kadar kolaydı?" (1-7, SEQ). docs/12 §9 madde 23 bu testle cevaplanır; sonuç ADR-0007 §7 madde 3'e yazılmalı.

**S1. Yeni hesap, ilk bakış (5 saniye testi; madde 23).**
- Hazırlık: ayarsız hesap, kısmi dönem, bilinen giderlerle kâr pozitif (durum C'nin pozitif hali) ve ayrıca negatif hali (ikinci katılımcı grubuna).
- Görev: Özet ekranı 5 saniye gösterilir, kapatılır. "Son 30 günde kâr ettiniz mi? Ne kadar?" "Ekranda sizden ne istendi?"
- Başarı: katılımcı bilinen rakamı net kâr olarak söylemez; kargo ve hizmet bedeli girmesi gerektiğini söyler.
- Ölçü: rakamı net kâr sanan katılımcı sayısı (hedef 0/5), istenen eylemi doğru söyleyen sayısı (hedef 5/5), "Hesaplanamadı" ifadesine verilen duygu ("bozuk", "eksik", "normal").

**S2. En çok zarar ettiren ürünü bul ve nedenini söyle.**
- Hazırlık: ayarlı hesap, 3 zarar eden ürün (biri kesin net kâr zararı, biri bilinen giderlerle bile zarar, biri maliyet girilmese de zarar) ve 20 kârlı ürün.
- Görev: "Bu ay size en çok para kaybettiren ürün hangisi? Neden zarar ediyor?"
- Başarı: 60 saniye içinde doğru ürüne ulaşır; nedeni kırılımdan doğru okur (örneğin kargo, komisyon).
- Ölçü: görev süresi, yol (özet -> liste -> kırılım), yanlış ürünü seçme, sıralama yönünü değiştirme ihtiyacı (UX-04, UX-17).

**S3. Kurulum bandından kargo tarifesi girme.**
- Hazırlık: ayar formu olan sürüm (yoksa mevcut sürümle beklenti ölçülür).
- Görev: "Ekrandaki uyarıyı giderin ve net kârınızı görün."
- Başarı: bandın düğmesinden forma gider, firma seçer, en az bir desi kademesi girer, özete döner ve net kâr rakamını görür.
- Ölçü: tamamlama, süre, KDV dahil/hariç karışıklığı, geçmişi etkileyen değişiklik penceresindeki seçim ve metnin anlaşılması ("Geçmiş raporlar değişecek" ne demek?). Mevcut sürümle yapılırsa: düğmeden sonra ne beklediği ve "Bağlı değil" rozetine tepkisi (UX-02).

**S4. Trendyol fazla mı kesti? (Beklenmeyen kesinti ve varsayılan desi.)**
- Hazırlık: BEKLENMEYEN_KESINTI uyarılı bir sipariş satırı; kargo farkı baskın, `kargo_tahmini_varsayilan_desi=true` (AD-05 durumu).
- Görev: "Bu siparişte Trendyol beklediğinizden fazla kesmiş. Ne kadar ve neden olabilir? Ne yapardınız?"
- Başarı: farkın tutarını ve kargodan kaynaklandığını söyler; varsayılan desi ipucunu okuyup Trendyol'a itiraz etmeden önce desi bilgisini kontrol etmesi gerektiğini anlar.
- Ölçü: "Trendyol hata yaptı" yanlış sonucuna varanlar (hedef 0), "eşik" kelimesinin anlaşılması (UX-20).

**S5. Rozetleri ve "Tahmini" rakamı anlama.**
- Hazırlık: ürün listesi; Kesin, Tahmini, Bilgi eksik/Eksik, Kâr belirsiz/Belirsiz, Zarar, Bilinen giderlerle bile zarar, Maliyet girilmese de zarar rozetli ürünler; bir de iade kaydı bekleyen satır.
- Görev: Her rozeti gösterip "Bu ne demek? Bu ürün için bir şey yapmanız gerekir mi?" diye sorulur. Sonra: "Bugün gördüğünüz ₺3.120 net kâr yarın değişebilir mi? Neden?"
- Başarı: her rozet için doğru anlam ve eylem; "Tahmini"nin ekstre gelince kesinleşeceğini söyler.
- Ölçü: rozet başına doğru yorum oranı (hedef her rozet için en az 4/5), kırmızı "Eksik" rozetine korku tepkisi (UX-10), mevcut ve önerilen etiketlerin A/B karşılaştırması (yarı katılımcıya mevcut, yarısına önerilen metinler).

## 10. Önceliklendirilmiş yapılacaklar

1. UX-01 (bilinen dönem kârı, K39 Revizyon 1 düzeni) ve UX-05 (bant metni): küçük kod, büyük etki.
2. UX-02 (çıkmaz bant düğmesi ve sabit "Bağlı değil"): ayar formu gelene kadar metin değişikliği, sonra §8.1.
3. UX-03 ve UX-04 (özette zarar eden ürünler, doğru sıra).
4. UX-07, UX-10, UX-18 (zarar ve eksik sinyalleri, rozet tonları, §7 metni).
5. UX-08 (uyarı bağlantısı çelişkisi), UX-09 (kırılım toplamı).
6. Kullanıcı testi S1 ve S5'i UX-01 ve UX-10 uygulanmadan önce ve sonra çalıştırmak (madde 23 cevabı).
