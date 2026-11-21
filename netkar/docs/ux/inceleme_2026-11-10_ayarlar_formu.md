# UX ve Güvenlik İncelemesi: /panel/ayarlar kâr ayarları formu (10 Kasım 2026)

- **Kapsam:** commit `1f88b0e` ("NetKâr S4: panelde kâr ayarları formu"), `git diff e320f7d..1f88b0e -- netkar/apps/web`.
- **Denetçi:** bağımsız UX ve güvenlik denetçisi (WCAG 2.2 AA, OWASP ASVS L2). Kodu ben yazmadım; kaynak dosya değiştirilmedi.
- **Ölçütler:** ADR-0007 §5.1 (Revizyon 1) ve §5.2; `docs/ux/inceleme_2026-11-10_panel_ozet_urunler.md` §8.1;
  `docs/security/denetim_2026-11-09_kar_ayarlari.md` §7, AB-01, AB-07; `docs/12_kar_motoru.md` K33-K44; API şeması
  `services/api/app/api/v1/profit_settings.py` ve `profit_settings_schemas.py`.
- **Yöntem:** kod okuma (istemci, API, servis kuralları), `npm test` (vitest), `npx playwright test e2e/settings.spec.ts`,
  üretim derlemesi üzerinde Playwright ile odak ve ayrıştırma yoklaması (geçici betik, depoya yazılmadı), ekran görüntüleri
  `docs/ux/ekranlar/panel-ayarlar-*`.

## 0. Kısa sonuç

**Kritik bulgu yok. Bir yüksek bulgu var (AF-01).** K43 onay akışı doğru kurulmuş: onay yalnız kullanıcının tıklamasıyla ve
sunucunun 409'da döndürdüğü etki tarihiyle gider; kullanıcının görmediği bir geçmiş değişikliğinin istemciden sessizce
yazılmasına giden bir yol bulamadım. Sözleşme alanları şemayla birebir, CSRF ve hata gösterimi güvenli.

En önemli sorunlar:

1. **AF-01 (Yüksek):** tr-TR ondalık ayrıştırma "1,255" ve "12,550" gibi girdileri **binlik** sayıyor (1.255 TL, 12.550 TL).
   Sunucu bu tutarları kabul ediyor (100.000 sınırının altında). KDV hariç girişte ve gider tutarında ekranda yankı da yok.
   Sonuç: sessiz 1000 kat hatalı kargo ya da gider tutarı. Birim test bu davranışı doğru diye sabitlemiş.
2. **AF-02 (Orta):** onay penceresi kapanınca (Esc, Vazgeç, başarılı uygulama) odak `body`'ye düşüyor (Playwright ile
   doğrulandı). WCAG 2.4.3.
3. **AF-03 (Orta):** bugün ya da ileri tarihli sürümün "Geri çek"i tek tıkla, onaysız uygulanıyor. WCAG 3.3.4.
4. **AF-04 (Orta):** "Trendyol anlaşmalı kargo (Trendyol öder)" ipucu alan olarak yanlış: bedel satıcının hakedişinden kargo
   faturasıyla düşülür (K08). Kâr aracında bu cümle "kargo bana bedava" diye okunabilir.

Testler: vitest 30 dosya, **512/512 geçti**; `e2e/settings.spec.ts` **46/46 geçti** (390 ve 1280 px, açık ve koyu, axe 0).

## 1. Bulgular (önem sırasıyla)

### AF-01 (Yüksek) tr-TR ondalık ayrıştırma 3 haneli kesri sessizce binlik sayıyor; 1000 kat hatalı tutar

- **Yer:** `apps/web/src/lib/profit/settings-input.ts:36-49` (tek ayraç + tam 3 hane + `maxFraction < 3` ise binlik);
  `apps/web/src/components/settings/settings-forms.tsx:23-29` (KDV hariç girişte yankı `null`);
  `apps/web/src/components/settings/tariff-section.tsx:575-577` (yardım metni "Ondalık için virgül ya da nokta
  kullanabilirsiniz"); `apps/web/src/lib/profit/settings-input.test.ts:44-46, 71` (`'1,250' -> '1250'`,
  `'1,255' -> '1255'` beklenen sonuç olarak yazılmış).
- **Ne oluyor:**
  - Para alanlarında (`maxFraction = 2`) "1,255" -> 1255, "12,550" -> 12550, "54.500" -> 54500. tr-TR'de virgül her zaman
    ondalıktır; "12,550" yazan satıcı büyük olasılıkla 12,55 TL demek istiyor (muhasebe ve ERP ekranlarından 3 ondalıklı
    birim fiyat kopyalamak olağan).
  - Aynı formda tutarsız: gider formunda tutar alanında "1.250" = 1250, oran alanında (`maxFraction = 4`) "1.250" = 1,25.
  - Yardım metni noktanın ondalık olabileceğini söylüyor; "54.500" yazan kullanıcı metne güvenip 54.500 TL kaydediyor.
  - Sunucu bu değerleri reddetmez (`check_price` 0-100.000, `check_expense_amount` 0-100.000). KDV dahil girişte yankı
    ("12.550,00 TL KDV dahil = 10.458,33 TL KDV hariç") var, ama KDV hariç girişte, hizmet bedelinde hariç modda ve gider
    tutarında hiç yankı yok. Playwright yoklaması: KDV hariç modda "12,550" yazılınca alanın altında hiçbir metin çıkmadı.
  - Etki: tarife kademesi ya da sipariş başı gider 1000 kat; o sürümün etki aralığındaki tüm satırların net kârı yanlış,
    üstelik onaylı ve izli bir "doğru" kayıt gibi görünür.
- **Düzeltme:**
  1. Para alanlarında (`maxFraction <= 2`) "rakam + **virgül** + tam 3 rakam" ve ikinci ayraç yoksa **reddet**:
     "Virgülden sonra en çok 2 hane yazın. Binlik için nokta kullanın: 1.250,00". Virgül tr-TR'de binlik ayracı olarak
     yalnız iki ayracın birlikte geçtiği ("1,250.50") yapıştırma durumunda kabul edilsin.
  2. "Nokta + tam 3 rakam" (tr-TR binlik) kabul edilecekse **her para alanında** ayrıştırılan değeri yankıla
     ("= 1.250,00 TL"), KDV hariç modda ve giderde de. `vatEquivalentText` hariç modda `null` yerine
     "1.250,00 TL KDV hariç" döndürmeli.
  3. Oran alanında da aynı kural (alanlar arası tutarlılık); ya da belirsiz biçimi her yerde reddet.
  4. Yardım metnini kurala göre düzelt ("Ondalık için virgül kullanın: 54,50").
  5. Testi tersine çevir: `parseDecimalInput('1,255', 2)` -> `{ ok: false, reason: 'ambiguous' }`; bileşen testinde
     KDV hariç modda yankının göründüğünü doğrula.

### AF-02 (Orta) Onay penceresi kapanınca odak sayfa gövdesine düşüyor

- **Yer:** `apps/web/src/components/settings/confirm-dialog.tsx:28-35`; `settings-writer.tsx:181-199`
  (`pending` iken tetikleyici düğmeler `disabled`); `tariff-section.tsx:230-237`, `settings-forms.tsx:98-105`.
- **Kanıt (Playwright, 390 px, üretim derlemesi):** "Geri çek" Enter -> 409 -> pencere açılınca odak "Vazgeç" (doğru).
  Esc sonrası `document.activeElement` = `BODY`. "Değişikliği uygula" ile başarı sonrası da `BODY`.
- **Neden:** pencere programatik açılıyor; açıldığı anda odaklı öğe, `pending` yüzünden devre dışı kalmış tetikleyici.
  Radix kapanışta ona dönemiyor. Başarıda form kapanıp (`onDone: onClose`) tetikleyici DOM'dan kalkıyor.
- **Düzeltme:** `WriteJob`'a `returnFocus?: () => HTMLElement | null` ekle; `run` başında `document.activeElement`'i sakla.
  `DialogContent`'e `onCloseAutoFocus={(e) => { e.preventDefault(); target?.focus(); }}` ver. Hedef: Vazgeç/Esc'te
  tetikleyici (formun "Kaydet" düğmesi ya da satırdaki "Geri çek"); başarıda bölümün `SectionNotice`'i (`tabIndex={-1}`)
  ya da bölüm başlığı (`h2`, `tabIndex={-1}`). Aynı hedef pencere açılmadan biten başarılı yazımlar için de geçerli (form
  kapanınca odak yine gövdeye düşüyor). Testi ekle: `expect(trigger).toBeFocused()` (vitest ve e2e).

### AF-03 (Orta) Bugün ya da ileri tarihli sürümün geri çekilmesi onaysız ve geri alınamaz

- **Yer:** `tariff-section.tsx:89-101`, `fee-section.tsx:60-72`, `expenses-section.tsx:71-83`.
- **Ne oluyor:** geri çekme ilk istekte onaysız gider. Sunucu yalnız geçmişi etkileyende (K43) 409 döner; başlangıcı bugün
  ya da ileride olan sürüm tek tıkla geri çekilir. Arayüzde "geri al" yok; değer yalnız ayar geçmişinde okunabilir, yeniden
  elle girilmesi gerekir. Bugün başlayan sürümde bugünkü siparişlerin kâr hesabı da değişir.
- **Ölçüt:** WCAG 3.3.4 (AA): kullanıcı verisini silen/değiştiren işlem geri alınabilir, kontrol edilebilir ya da onaylı
  olmalı.
- **Düzeltme:** geri çekme her durumda istemci tarafı bir onay adımı alsın (409 gelmediği durumda ADR metni yerine
  "{firma} tarifesi ({tarih} başlangıçlı) geri çekilsin mi? Önceki değer ayar geçmişinde kalır." + "Geri çek" / "Vazgeç").
  409 gelirse mevcut ADR penceresi açılır (iki pencere üst üste açılmamalı: istemci onayı alındıktan sonra 409 penceresi
  onun yerine geçer). Alternatif: başarı bildiriminde 10 sn "Geri al" (aynı içerikli satırı yeniden yazar).

### AF-04 (Orta) "Trendyol anlaşmalı kargo (Trendyol öder)" alan olarak yanlış

- **Yer:** `apps/web/src/components/settings/tariff-section.tsx:393`.
- **Neden:** K08: Trendyol anlaşmalı gönderide kargo bedeli Trendyol'un kestiği kargo faturasıyla satıcının hakedişinden
  düşülür; satıcı anlaşmasında (`whoPays=1`) fatura beklenmez. İki durumda da bedeli satıcı öder. "Trendyol öder" bir kâr
  aracında "bu tarifeyi girmeme gerek yok" çıkarımına götürür ve kurulum tamamlanma oranını düşürür.
- **Düzeltme:** "Trendyol'un anlaştığı kargo firmaları. Bedel, kargo faturasıyla hakedişinizden düşülür." Satıcı seçeneği:
  "Kendi anlaşmanızla gönderdiğiniz siparişler. Trendyol kargo faturası kesmez."

### AF-05 (Orta) Başlangıç tarihi önerisi "bugün - 92 gün"; eski hesapta önceki aylar eksik kalır (AB-01 kısmi)

- **Yer:** `tariff-section.tsx:280-281`, `fee-section.tsx:189`, `expenses-section.tsx:207`.
- **Ne oluyor:** öneri `/carriers` tarama penceresine (92 gün) dayanıyor. Backfill 89 gün (`sync/runner.py:59`) olduğu için
  yeni bağlanan hesapta yeterli; ama 6 ay önce bağlanmış ve ayarı şimdi giren hesapta 3 aylık sipariş "eksik" kalır. İlk
  giriş istisnası (onaysız) yalnız ilk yazımda geçerli; sonradan daha erken sürüm eklemek onay penceresi ister.
- **Düzeltme:** bkz. §4 madde 1 (API'ye ilk sipariş günü). O gelene kadar: öneriyi hesabın bağlanma tarihi - 89 gün ile
  bugün - 92 günün küçüğüne çek; tarih alanının altında "Hesabınızdaki en eski sipariş: ..." bilgisi yoksa "Emin değilseniz
  daha eski bir tarih seçin; ilk girişte geçmiş raporlar için onay istenmez" ekle.

### AF-06 (Orta, test) Testler asıl riskin ikisini sabitliyor ya da hiç sınamıyor

- **Yer:** `src/lib/profit/settings-input.test.ts:44-46, 71`; `src/components/settings/profit-settings-panel.test.tsx`;
  `e2e/settings.spec.ts`.
- **Eksikler:**
  1. "Yanlış tutar" riski: test belirsiz biçimi (`'1,255' -> 1255`) doğru diye kilitliyor (AF-01).
  2. Odak: pencere açılışında ilk odak, Esc/Vazgeç/başarı sonrası dönüş hiç sınanmıyor (AF-02 bu yüzden kaçmış).
  3. Pencere içindeki ikinci 409 (etki tarihi değişti): "Etkilenen tarih değişti" notu ve **otomatik yeniden gönderim
     olmaması** sınanmıyor. Onay atlanmasına karşı en değerli test budur: ikinci 409'dan sonra istek sayısı artmamalı,
     ancak yeni tıklamayla yeni tarih gitmeli.
  4. Sözleşme: tüm testler sahte API ile; gövdelerin gerçek pydantic şemasından (`extra="forbid"`) geçtiği doğrulanmıyor.
     Alan adı kayması yalnız TypeScript türleriyle korunuyor (türler de elle yazılmış).
  5. Görüntüleyici: yalnız düğmelerin gizlendiği sınanıyor; `/me` hata verince ne olduğu (AF-10) sınanmıyor.
- **Düzeltme:** yukarıdaki dört test; sözleşme için `services/api` tarafında, panelin ürettiği örnek gövdeleri (fixture
  JSON) `CargoTariffIn.model_validate` ile doğrulayan bir test ya da OpenAPI'den tür üretimi (`openapi-typescript`) ve CI'da
  fark kontrolü.

### AF-07 (Düşük) "Yalnız bugünden itibaren uygula" düzenlemede de sunuluyor; aynı anahtarlı bugünkü sürümü sessizce değiştirebilir

- **Yer:** `tariff-section.tsx:331-339`, `fee-section.tsx:211-219` (gider doğru: `expenses-section.tsx:233-242` yalnız
  eklemede).
- **Ne oluyor:** ADR §5.2 ikincil düğmeyi "tarife, hizmet bedeli ve gider eklemede" tanımlar. Tarife ve hizmet bedeli
  düzenlemesinde de çıkıyor: 1 Ekim sürümünü düzeltmek isteyen kullanıcı bu düğmeyle bugünden başlayan **yeni** sürüm
  ekliyor, 1 Ekim sürümü yanlış kalıyor. Aynı firma ve anlaşmada bugün başlayan bir sürüm zaten varsa, gönderim onu
  "değiştir" olarak ezer (etki tarihi bugün, geçmiş değil, onay yok) ve kullanıcı bunu görmez.
- **Düzeltme:** ya ADR ile hizala (düzenlemede düğme yok) ya da ADR'yi güncelleyip düğme metnini düzenlemede "Bu fiyatları
  bugünden başlayan yeni sürüm olarak ekle" yap; bugün başlayan aynı anahtarlı sürüm varsa düğmeyi gizle ya da metne
  "bugünkü sürümün yerine geçer" ekle.

### AF-08 (Düşük) Bazı 422 alan hataları görünmüyor

- **Yer:** `settings-forms.tsx:50-70`; `tariff-section.tsx:341-348` ve `367-374` (düzenlemede `carrier`, `validFrom`
  alanları çizilmiyor); `fee-section.tsx:221-222`; `fields.tsx:55-110` (`ChoiceGroup` hata çizmez).
- **Ne oluyor:** `applyServerErrors`, `knownFields` içindeki alana `setError` yapar, kök hataya düşürmez. Düzenleme modunda
  `carrier` ya da `validFrom` hatası, her modda `agreement` ya da `vatMode` hatası ekranda hiçbir yerde çıkmaz; kullanıcı
  "Kaydet"e basar ve hiçbir şey olmaz.
- **Düzeltme:** bileşen o an çizilen alanların listesini versin (`renderedFields`); listede olmayan alan hatası kök hataya
  gitsin. `ChoiceGroup`'a `error` özelliği ekle: `fieldset`'e `aria-invalid` ve `aria-describedby` ile bağlı hata satırı.

### AF-09 (Düşük) Bölüm kartları bölge (region) olarak duyurulmuyor

- **Yer:** `tariff-section.tsx:104`, `fee-section.tsx:75`, `defaults-section.tsx:73`, `expenses-section.tsx:86`,
  `history-section.tsx:32`; `components/ui/card.tsx:5-15` (`div`).
- **Ne oluyor:** `aria-labelledby` bir `div` üzerinde; ARIA 1.2'de `generic` rolde adlandırma yasaktır. Yoklamada sayfada
  yalnız 2 `region` var; beş ayar bölümü yer işareti listesinde görünmüyor.
- **Düzeltme:** kartları `<section aria-labelledby=...>` içine al ya da `Card`'a `as="section"` desteği ekle.

### AF-10 (Düşük) Görüntüleyici ve oturum hatalarında yanıltıcı metin

- **Yer:** `use-settings-data.ts:32-38`; `lib/api/client.ts:222-236`.
- **Ne oluyor:** `/me` yüklenirken ya da hata verirse `canEdit = true`; görüntüleyici yazma düğmelerini görür. Basınca sunucu
  403 döner (doğru, esas sunucu) ama metin "İstek doğrulanamadı. Sayfayı yenileyip tekrar deneyin." (CSRF metni). 401'de
  (oturum düştü) metin "Girdiğiniz değerleri kontrol edip tekrar deneyin."; kullanıcı değerlerini boşuna değiştirir.
- **Değerlendirme:** yalnız arayüz gizlemesi kabul edilebilir (sunucu 403 esas, `require_role(OWNER, ADMIN)`).
- **Düzeltme:** `/me` yüklenene kadar yazma düğmelerini gösterme (ya da devre dışı); 403 gövdesinin `type`'ına göre
  "Bu işlem için yetkiniz yok" ile CSRF metnini ayır; 401'de "Oturumunuz sona erdi. Yeniden giriş yapın; girdiğiniz değerler
  bu sekmede duruyor."

### AF-11 (Düşük) Sürüm çakışmasından sonra düzenleme formu eski değerlerle açık kalıyor

- **Yer:** `settings-writer.tsx:162-167`; `tariff-section.tsx:349-351`.
- **Ne oluyor:** başka yönetici aynı tarifeyi değiştirince 409 `settings-revision-conflict` gelir, ekran yenilenir ama form
  kullanıcının eski değerleriyle açık kalır. Tarife PUT'u kimlikle değil anahtarla yapıldığı için `settings-record-ended`
  çıkmaz; kullanıcı bir kez daha kaydedip onaylarsa diğer yöneticinin değişikliğini, farkını hiç görmeden ezer. Bildirim
  metni uyarıyor, bu yüzden düşük.
- **Düzeltme:** düzenleme modunda çakışmada formun altında sunucunun güncel kademelerini göster ("Şu an kayıtlı: ...") ya da
  formu yeni değerlerle yeniden aç.

### AF-12 (Düşük) "Bugün" cihaz saatinden ve sayfa açılışında bir kez alınıyor

- **Yer:** `profit-settings-panel.tsx:85`; `tariff-section.tsx:332-336`, `fee-section.tsx:212-216`,
  `expenses-section.tsx:235-240`.
- **Ne oluyor:** gece yarısını geçen açık sekmede ya da saati yanlış cihazda "Yalnız bugünden itibaren uygula" dünü ya da
  yarını gönderir. Dün: sunucu yeniden 409 verir, pencere "Etkilenen tarih değişti" der; "Değişikliği uygula" asıl gövdeyi
  dünün tarihiyle onaylamaya çalışır ve yine 409 alır (döngü, sessiz yazım yok). Yarın: bugünün siparişleri yeni sürümü almaz.
- **Düzeltme:** sunucu bugünü versin (`SettingsOut.today` ya da 409 gövdesinde `today`); "bugünden" gönderiminde o kullanılsın.

### AF-13 (Düşük) Kurulum ilerlemesi ve adım geri bildirimi UX §8.1'in gerisinde

- **Yer:** `profit-settings-panel.tsx:119-134`; `settings-present.ts:62-81`.
- **Ne oluyor:** iki adım var, adımlar bağlantı değil, "Bu adımla N satışın net kârı hesaplanacak" geri bildirimi yok.
  `done` "bugün geçerli" anlamında (doğru etiketli), ama bugün başlayan tarife girildiğinde "2 adımdan 2'si tamam" yazar
  ve geçmiş dönem hâlâ "eksik"tir (AB-01'in ayar ekranındaki yansıması).
- **Düzeltme:** adımları `#kargo` ve `#hizmet-bedeli` bağlantısı yap; tamamlanmış adımda en eski başlangıç bugünden
  sonraysa "Bugünden önceki siparişler için tarife yok" notu; 3. adım için bkz. §4 madde 5.

### AF-14 (Düşük) Mobil düzen ayrıntıları

- **Yer:** `tariff-section.tsx:495-525` (kademe satırı), `tariff-section.tsx:305` (firma seçeneği), `tariff-section.tsx:443-459`
  (tarih).
- 390 px'te çöp kutusu düğmesi görsel olarak desi alanının **solunda**, DOM'da ise **sonrasında** (sekme sırası desi -> sil ->
  fiyat). WCAG 1.3.2/2.4.3 açısından küçük; düğmeyi sağa al (`col-start-2`).
- Firma seçeneği metni ("Yurtiçi Kargo (son 92 günde 34 satır, tarifesi yok)") 390 px'te kesiliyor; kapalı `select`'te
  "tarifesi yok" bilgisi kayboluyor. Seçili firmanın durumunu `select` altındaki açıklamaya yaz.
- Tarih alanı tarayıcı biçimini kullanıyor; ekran görüntüsünde "08/10/2026" (10 Ağustos). Türkçe okurda 8 Ekim sanılabilir.
  Alanın altına seçilen tarihi uzun biçimde yankıla ("10 Ağustos 2026 ve sonrasındaki siparişlerde kullanılır"); gider
  formunun bitiş alanı bunu zaten yapıyor.

### AF-15 (Düşük) Duyuru ve pencere ayrıntıları

- `fields.tsx:24-46`: `SectionNotice` `role="status"` öğesi içerikle birlikte DOM'a ekleniyor; bazı ekran okuyucular
  sonradan eklenen `status` bölgesini okumaz. Boş canlı bölgeyi kalıcı tut, metni sonradan koy. (`alert` için sorun yok.)
- `confirm-dialog.tsx:28-35`: rol `dialog`; veri değiştiren onay için `alertdialog` (Radix `AlertDialog`) daha doğru,
  dışarı tıklamayla kapanma da olmaz. Kapanma yalnız "Vazgeç" anlamına geldiği için güvenlik açısından sorun yok.
- `confirm-dialog.tsx:47-58` ve `DialogFooter`: 390 px'te görsel sıra (Uygula, Bugünden, Vazgeç) DOM sırasının tersi;
  sekme sırası alttan üste. Yaygın kalıp, kabul edilebilir; not olarak.

### AF-16 (Düşük) 409 gövdesinde etki tarihi yoksa yanlış metin ve döngü

- **Yer:** `lib/api/client.ts:96-101`, `lib/api/profit-settings.ts:263`, `settings-present.ts:99`.
- **Ne oluyor:** tarihli bir yazımın 409'unda `affects_from` eksik ya da biçimsizse `null` sayılır; pencere varsayılan desi
  metnini ("desi bilgisi olmayan tüm geçmiş siparişler") gösterir ve onay `all` gider. Sunucu eşleşmediği için yeniden 409
  döner (sessiz yazım yok). Sunucu bugün hep tarih gönderiyor; savunma amaçlı.
- **Düzeltme:** `topic !== 'defaults'` iken `affectsFrom === null` ise pencere açma; "Değişikliğin etkileyeceği tarih
  alınamadı, sayfayı yenileyin" hata bildirimi göster.

## 2. Kontrol listesi sonuçları

### 2.1 Doğruluk

| Konu | Sonuç |
|---|---|
| İstemci alanları ve şema | Birebir: `agreement`, `carrier`, `valid_from`, `price_includes_vat`, `brackets[].max_desi/price`, `amount`, `amount_includes_vat`, `name`, `kind`, `amount_excl_vat`, `percent`, `vat_rate`, `valid_to`, `default_desi`, `expected_revision`, `confirm_affects_from`. `confirm_past_change` hiç gönderilmiyor (doğru, YT-07). DELETE onayı ve sürümü sorgu parametresi. Yanıt türleri `WriteInfo` alanlarıyla uyumlu. |
| Zod ve sunucu kuralları | Uyumlu: desi `0 < x <= 1000` 2 ondalık; fiyat `0..100.000`; hizmet bedeli `0..10.000`; gider tutarı `0..100.000`; oran `0 < x <= 100` 4 ondalık; KDV 0/1/10/20; ad 1-80, kırpılmış, kontrol karakteri yok (`\p{C}` = Python `C*`); kademe 1-50, kesin artan; başlangıç `2000-01-01..bugün+366`; bitiş >= başlangıç. Ad uzunluğunda JS UTF-16 sayar (astral karakterde istemci daha katı, zararsız). |
| KDV hariç karşılık | `exclusiveOfVat` BigInt ile `round_half_up(dahil x 100 / (100 + oran))`; sunucu `split_inclusive` ile aynı (54,00 -> 45,00; 50,00 -> 41,67). Sabit %20 `settings-forms.tsx:16-17` (bkz. §4 madde 2). Kayıttan sonra liste sunucunun `price_excl_vat` değerini gösteriyor, yanıltma yalnız kayıt öncesi önizlemede olabilir. |
| tr-TR ayrıştırma | **AF-01.** |
| İstanbul günü | `todayIstanbul` `Europe/Istanbul` ile doğru; sınır ve cihaz saati riski AF-12. Tarih karşılaştırmaları YYYY-AA-GG dizgesiyle (doğru). |

### 2.2 K43 akışı

| Konu | Sonuç |
|---|---|
| Onaysız ilk istek | Doğru (`settings-writer.tsx:189`): ilk girişte gönderilmiş onayın bile 409 üreteceği kuralına uygun. |
| 409 sonrası onay | `confirm_affects_from` = 409'daki `affects_from`, `null` ise `all`; `expected_revision` = 409'daki `current_revision` (ADR §5.1 Revizyon 1, AB-03). |
| İkinci 409 | Pencere açık kalır, tarih değiştiyse not çıkar; **otomatik yeniden gönderim yok**, yeni onay yeni tıklama ister (doğru; testi yok, AF-06). |
| "Yalnız bugünden itibaren" | Eklemede ADR'ye uygun, onaysız ve `valid_from = bugün`. Düzenlemede ADR dışı (AF-07). Geri çekme ve varsayılan desi için yok (doğru). |
| Geri çekmede onay | Geçmişi etkileyende 409 ile ADR geri çekme metni (kargo) ya da tarihli genel metin (diğerleri). Geçmiş olmayan geri çekmede hiç onay yok (AF-03). |
| Sessiz geçmiş değişikliği | İstemciden mümkün değil: onay yalnız kullanıcı tıklamasıyla ve sunucunun tarihiyle gider; sunucu tarih eşleşmesini kendisi denetliyor. Onaysız geçmiş yazımı yalnız sunucunun ilk giriş istisnasında oluyor (K43 gereği). |

### 2.3 Güvenlik

| Konu | Sonuç |
|---|---|
| CSRF | Tüm yazımlar `apiFetch` üzerinden: `X-CSRF-Token` başlığı, `credentials: 'same-origin'`, çerez yoksa `GET /auth/csrf`. Uygun. |
| XSS | `dangerouslySetInnerHTML` yok; firma, gider adı, geçmiş fark satırları React metin düğümü (denetim §7 madde 9). `href`'ler sabit. |
| 409/422 gövdesi | `parseDetails` tür ve biçim denetimi yapıyor (`affects_from` regex, `current_revision` güvenli tamsayı, `current_id` <= 64). 422 yalnız `field` ve `code` okunuyor, metin istemcide Türkçe üretiliyor, girdi yansımıyor. Sunucu `detail` metni gösterilmiyor. |
| Görüntüleyici | Yazma düğmeleri yalnız arayüzde gizli; sunucu 403 esas. Kabul. Metin sorunu AF-10. |
| İç bilgi sızıntısı | Hata metinleri genel; 5xx "biz de görüyoruz"; ayrıntı yok. Uygun. |
| Hesap kimliği | `encodeURIComponent` ile yolda; geçmiş imleci `URLSearchParams` ile. Uygun. |

### 2.4 UX ve erişilebilirlik

| Konu | Sonuç |
|---|---|
| 390 px akış | Yatay taşma yok (e2e kontrolü); dokunma hedefleri 44 px (`min-h-touch`); radyolar 16 px ama 44 px'lik etiketin içinde (kabul). Küçük düzen sorunları AF-14. |
| Adım ilerlemesi | Var, iki adım; AF-13 ve §4 madde 5. |
| Etiketler | Her alanda görünür `label` (`FormLabel` + `htmlFor`), radyolarda `fieldset`/`legend`, kademe etiketleri sıra numaralı, ikon düğmelerde `sr-only` ad. |
| Hata mesajları | Alan yanında, `aria-invalid` ve `aria-describedby` ile bağlı (`ui/form.tsx`), "Hata:" öneki ve ikon (renk tek başına değil). Görünmeyen hata durumları AF-08. |
| Onay penceresi odağı | Açılışta "Vazgeç" (güvenli varsayılan), Esc kapatıyor ve istek göndermiyor; **kapanışta dönüş yok** (AF-02). |
| `role="alert"` | Bölüm bildirimi (hata/uyarı), form kök hatası, alan hataları. Gönderimde çok sayıda alan hatası aynı anda `alert` olur (gürültülü ama zararsız; ilk hatalı alana odak RHF ile gidiyor). |
| Renk | Rozetler metinli ("Bugün geçerli tarife yok", "0 girildi"), adım durumları metinli ("eksik", "bugün geçerli"). Uygun. |

## 3. Doğru çalışanlar

- Sözleşme alanları API şemasıyla birebir; `extra="forbid"` gövdelerine fazladan alan gitmiyor; `confirm_past_change` yok.
- K43 onayı yalnız kullanıcı eylemiyle; onay değeri sunucunun etki tarihi, tarihsizde `all`; onaylı yazımda 409'daki sürüm
  `expected_revision` olarak gidiyor; her yazımda `expected_revision` var (AB-03).
- Onay penceresi metinleri ADR-0007 §5.2'den birebir (başlık, tarihli metin, varsayılan desi metni, kargo geri çekme metni);
  birim ve e2e testleriyle korunuyor.
- `settings-record-ended` ve `settings-revision-conflict`: ekran yenileniyor, bölüm içinde `role="alert"` bildirim
  ("Bu kayıt başka bir değişiklikle güncellendi. Ekranı yeniledik.", UX §8.1).
- Firma yalnız `/carriers` listesinden ve "Diğer firmalar" (`*`); boş ad `*`'a eşleniyor (AB-04, AB-06); düzenlenen kaydın
  firması listede yoksa da seçili kalıyor.
- "0 girildi" rozeti listede, formda ve geçmişte (AB-07); hizmet bedeli boş durumu "kesilmiyorsa 0 girebilirsiniz" diyor
  (tanımsız 0 değildir, K33/K35).
- KDV dahil girişte hariç karşılık float'sız ve sunucuyla aynı yuvarlamayla; listede girilen ve hariç değer birlikte
  (denetim §7 madde 8).
- Ayar geçmişi: mühürlü imleç, kişi yerine rol (YT-08), "Geri çekildi" ve "Geçmişi etkiledi (onaylı)" rozetleri, fark satırları
  ADR örneği biçiminde; sürüm değişince liste baştan yükleniyor.
- Özet bandından `#kargo` ve `#hizmet-bedeli` derin bağlantısı, veri gelince kaydırma; mağaza bağlı değilse dürüst boş durum.
- Bölüm başına `pending` kilidi çift gönderimi engelliyor; ağ hatasında pencere kapanıp bölümde hata bildirimi çıkıyor.
- Testler: vitest 512/512, `e2e/settings.spec.ts` 46/46 (390 ve 1280 px, açık ve koyu tema, axe WCAG 2.2 AA etiketleriyle 0
  ihlal, yatay taşma yok).

## 4. Ajanın bildirdiği açıklar: değerlendirme

| # | Açık | Karar | Öneri |
|---|---|---|---|
| 1 | İlk sipariş tarihi ucu yok; öneri bugün - 92 gün | **Geçici olarak kabul**, yeni hesap için yeterli (backfill 89 gün); eski hesapta yetersiz (AF-05) | API: `GET profit-settings` yanıtına `earliest_order_day` (hesabın en eski sipariş günü, İstanbul; sipariş yoksa `null`). Panel öneriyi bu günden 1 gün öncesine çeksin. Tarama penceresini (`lookback_days`) başlangıç önerisi için kullanmayı bırakın: farklı kavram. |
| 2 | KDV oranları uçtan okunmuyor (%20 sabit) | **Kabul** (K33: sistem parametresi, bugün %20; kayıttan sonra liste sunucu değerini gösterir) | `SettingsOut`'a `vat_rates: {shipping, service_fee}` (Decimal dizgesi) ekleyin; istemci sabiti yalnız yedek olsun. Oran değişikliği tek yerden yapılınca önizleme kendiliğinden doğru kalır. `exclusiveOfVat` tamsayı oran istiyor; 0,5 gibi oranlara hazır değil, uçtan okunduğunda kesirli orana genişletin. |
| 3 | Anlaşma değeri `seller`, K34 belgesinde `satici` | **Kabul, istemci doğru** (API, ADR-0006 tablo CHECK'i ve servis `seller` kullanıyor) | `docs/12` K34 "Model" maddesine "API ve veritabanı değeri `seller`; golden şemasında `satici_kargo_tarifesi`" notu. Belge sahibi düzeltmeli. |
| 4 | ADR "panel K43'ü önceden hesaplar" yerine yalnız sunucu 409'u | **Kabul** (daha güvenli: ilk giriş istisnası, gider değiştirmede eski/yeni başlangıcın küçüğü ve geri çekme kuralları istemciye kopyalanmıyor; tek doğruluk kaynağı sunucu, YT-07 bağlaması da sunucuda) | ADR §5.2 madde 1'i güncelleyin ("panel 409'a dayanır"). UX kaybını kapatmak için yalnız bilgi amaçlı satır içi not: başlangıç bugünden önceyse kaydet düğmesinin üstünde "Bu tarih geçmişte; kaydederken geçmiş raporlar için onay isteyebiliriz." Not karar vermez, onay yine 409'la. |
| 5 | İki adımlı ilerleme (UX §8.1 üç adım istiyor) | **Kısmen kabul** (maliyet girişi ekranı henüz yok; olmayan adımı "tamam"lanabilir göstermek yanlış olurdu) | 3. adımı "Ürün maliyetleri: Ürünler ekranında (yakında)" olarak, sayıya katmadan gösterin ya da UX §8.1'i iki adım + ayrı maliyet bandı olarak güncelleyin. Adımları bölüm bağlantısı yapın; "Bu adımla N satışın net kârı hesaplanacak" için `summary.totals.eksik_kalem_satir_sayilari` kullanılabilir (AF-13). |

## 5. Önceliklendirilmiş yapılacaklar

1. AF-01: belirsiz ondalık biçimini reddet, her para alanında yankı, testi tersine çevir. (Birleştirmeden önce.)
2. AF-02: odak dönüşü; AF-06 odak ve ikinci 409 testleri.
3. AF-03: geri çekmeye istemci onayı.
4. AF-04: "Trendyol öder" metni.
5. AF-05 ve §4 madde 1: `earliest_order_day` ucu ve öneri.
6. AF-07, AF-08, AF-09, AF-10: küçük düzeltmeler.
7. ADR §5.2 madde 1 ve docs/12 K34 belge düzeltmeleri (§4 madde 3, 4).
8. AF-11 - AF-16: sonraki tur.
