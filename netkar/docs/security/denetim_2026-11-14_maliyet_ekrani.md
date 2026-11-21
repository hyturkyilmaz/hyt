# Denetim: Ürün maliyeti giriş ekranı (web) 2026-11-14

Kapsam: `netkar/apps/web` altındaki commit edilmemiş değişiklikler (yeni: `src/app/(app)/panel/maliyetler/page.tsx`,
`src/components/costs/*`, `src/lib/api/product-costs.ts`, `src/lib/validation/product-costs.ts`,
`src/lib/profit/cost-*.ts`, `e2e/fake-costs.mjs`; değişen: `src/lib/api/client.ts`, `alerts.ts`, ürün ve ayar ekranlarındaki
bağlantılar). Gerçek sözleşme (salt okunur): `services/api/app/api/v1/product_costs.py`, `product_cost_schemas.py`,
`app/services/cost_import.py`, `app/services/product_costs.py`, `app/services/import_gate.py`.

Yöntem: statik okuma, `git diff`, grep. Playwright ve backend çalıştırılmadı. Ölçüt: OWASP ASVS L2, para doğruluğu,
WCAG 2.2 AA.

## Özet

- Kritik veya yüksek bulgu yok. Güvenlik denetimleri (CSRF, kimlik bilgisi kipi, metin olarak basma, URL kodlama) doğru.
- Sözleşme büyük ölçüde birebir: alan adları (`unit_cost_excl_vat`, `vat_rate`, `valid_from`), KDV hariç tutar, oranlar
  {0, 1, 10, 20}, geçerlilik aralığı (2000-01-01 ile bugün + 366 gün), 422 alan yolu (`loc[1:]`), `dry_run` varsayılanı
  ve `allow_partial` yalnız açık düğmeyle, `import-validation-failed` gövdesindeki `report`.
- Para: tutarlar dizge olarak taşınıyor, `parseDecimalInput` ve `describeParseFailure` ayar formuyla aynı kural,
  `toMoneyString` ile kuruş biçimi, gösterim `formatTRY` (dizge tabanlı yuvarlama). Float aritmetiği yok.
- "Bugün geçerli maliyet" (`applySavedCost`): `valid_from <= bugün` olan en yeni kayıt; eşit tarih upsert. Sunucunun
  `list_products` LATERAL sorgusuyla aynı kural.
- Orta düzey 3 bulgu: istemci tarafı "maliyeti eksik" süzgecinin 20 sayfaya kadar kendiliğinden yükleme yapması (ME-01),
  şablonun düz `<a download>` ile indirilmesi (ME-02) ve desen dışı barkodlu ürünlerin düzenlenememesi (ME-03).
- Sahte API (`fake-costs.mjs`) CSRF, multipart, 422 rapor ve dosya hatalarını doğru taklit ediyor; ancak
  `import-in-progress` (429), `import-busy` (503), `import-unavailable` (503) ve `X-Template-Truncated` yollarını
  taklit etmiyor, ME-02 ve ME-04 bu yüzden testlerde görünmüyor.

## Doğrulanan noktalar (bulgu yok)

| Konu | Kanıt |
| --- | --- |
| PUT ve multipart POST'ta CSRF başlığı | `client.ts:210-212` güvenli olmayan her yöntemde `X-CSRF-Token`; `formData` dalı aynı `send()` yolundan geçiyor |
| Multipart Content-Type | `client.ts:207-209` FormData varken JSON başlığı konmuyor, sınır değerini tarayıcı koyuyor |
| Kimlik bilgisi kipi | `credentials: 'same-origin'` (`client.ts:224`) |
| Sunucu metni yalnız metin olarak | Bileşenlerde `dangerouslySetInnerHTML` yok; `detail` 300 karakterle kesiliyor ve yalnız `import-file-invalid` için basılıyor (sabit sunucu metni); satır `value` ve `ignored_columns` JSX metni olarak basılıyor; hiçbirinden URL üretilmiyor |
| URL kodlama | `accountId` ve `barcode` için `encodeURIComponent` (`product-costs.ts:83,107,112`); `q`, `after`, `filtre` için `URLSearchParams` (`product-costs.ts:97-100`, `cost-query.ts:17-23`) |
| İstemci dosya denetimi yalnız UX | `checkImportFile` uzantı ve boyut; sunucu imza, zip ve içerik denetimini yine yapıyor (`cost_import.py:222-240`) |
| Konsola kişisel veri | Yeni dosyalarda `console.*` yok |
| Görüntüleyici rolü | Arayüz gizliyor, sunucu `AdminDep` ile 403 veriyor; 403 metni Türkçe ve açıklayıcı |
| Para ayrıştırma | `validation/product-costs.ts:33` ayar formuyla aynı `parseDecimalInput(text, 2)`; sunucu `_PLAIN_DECIMAL` ve 2 ondalık kuralıyla uyumlu |
| 422 eşleme | Sunucu `field = loc[1:]` (`errors.py:138`), istemci `unit_cost_excl_vat`/`vat_rate`/`valid_from` anahtarları; kodlar `cost_*`, `vat_rate_invalid`, `valid_from_out_of_range`, `decimal_invalid` birebir |
| İçe aktarma akışı | Önce `dry_run=true&allow_partial=false`; kayıt `dry_run=false`, hatalı satır varsa yalnız "Yalnız geçerli N satırı kaydet" düğmesi `allow_partial=true` gönderiyor |
| Diyalog | Radix Dialog (odak tuzağı, Esc), etiketli alanlar, `ChoiceGroup` ile `legend`; tarih kısayol düğmeleri varsayılan `type="button"` (form göndermez) |

## Bulgular

| ID | Önem | Dosya:satır | Senaryo | Düzeltme |
| --- | --- | --- | --- | --- |
| ME-01 | Orta | `src/components/costs/costs-screen.tsx:37-39`, `211-234`; `src/lib/profit/cost-query.ts:25-31` | API'de "maliyeti eksik" süzgeci yok; süzgeç açıkken görünen satır 10'un altındaysa 20 sayfaya kadar (1.000 ürün, 21 istek) art arda yükleniyor. Sayaç anahtarı `missingOnly` içerdiği için "Tüm ürünler" ile "Maliyeti eksik" arasında her geçişte sıfırlanıyor, liste ise korunuyor: birkaç tıklamayla tüm katalog belleğe çekilebilir, her istek LATERAL alt sorgulu bir DB sorgusu. Uyarılardaki "Maliyeti eksik ürünleri gör" bağlantısı artık bu ekrana geliyor (`alerts.ts`), yani en sık yol bu. `GET /products` üzerinde kiracı ya da IP sınırı yok (429 riski yok, ama DB yükü ve gereksiz trafik var). Sonuç yine eksik kalabiliyor ("devamı var"). | Kalıcı: sunucuya `missing=true` sorgu parametresi (`current_cost IS NULL` koşulu, keyset aynı) ve istemci süzgecini kaldırma. Geçici: sayaç anahtarından `missingOnly`'yi çıkarın (oturum başına toplam sınır), sınırı 5 sayfaya indirin, kullanıcıya "N ürün tarandı" bilgisini gösterin. |
| ME-02 | Orta | `src/components/costs/cost-import-panel.tsx:138-145`; `src/lib/api/product-costs.ts:86-89` | Şablon düz `<a href download>` ile iniyor. Oturum düşmüşse (401), hesap yoksa (404) ya da saatlik 60 şablon sınırı dolmuşsa (429, `rate_limit_cost_template_tenant`) arayüz hiçbir şey söylemiyor; tarayıcıya göre indirme "başarısız" görünür ya da problem+json gövdesi `maliyet_sablonu.csv` adıyla kaydedilir ve kullanıcı bunu doldurmaya çalışır. 10.000'den fazla üründe sunucunun `X-Template-Truncated: true` başlığı okunamıyor, kullanıcı şablonun eksik olduğunu bilmiyor. Güvenlik açısından sorun yok (GET, aynı köken, formül kaçışı sunucuda). | `fetch` (aynı köken, `credentials: 'same-origin'`) ile indirin; `response.ok` değilse `describeImportError` benzeri Türkçe ileti ve `Retry-After`; başarıda `X-Template-Truncated` başlığını okuyup uyarı gösterin, gövdeyi `Blob` ve `URL.createObjectURL` ile indirin, ardından `revokeObjectURL`. Sahte API'ye 429 ve kesilme senaryosu ekleyin. |
| ME-03 | Orta | `src/components/costs/cost-form-dialog.tsx:85-87`, `93`; `src/lib/api/product-costs.ts:106-115`; sunucu `product_costs.py:30`, `product_costs.py (router) BarcodePath` | Sunucu yol parametresinde barkodu `^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$` ile sınırlıyor; Trendyol modelinde `barcode: str` serbest (`integrations/trendyol/models.py:96`). Senkron boşluk, Türkçe harf, `/` ya da `+` içeren bir barkodu yazarsa ürün listede "Maliyet gir" düğmesiyle görünür, ama geçmiş isteği 422 ile "Geçmiş yüklenemedi", kayıt 422 `barcode` alanı ile genel "Bu değeri kontrol edin." iletisi verir. Toplu içe aktarma da aynı barkodu reddeder. Kullanıcı bu ürünün net kârını hiçbir yoldan hesaplatamaz ve nedenini öğrenemez. | İstemcide aynı deseni (`BARCODE_PATTERN`) dışa aktarın; desene uymayan satırda düzenleme düğmesi yerine "Bu barkod biçimi desteklenmiyor" açıklaması gösterin ve 422 `field=barcode` için özel ileti ekleyin. Backend tarafında senkronun bu barkodları nasıl sakladığı ve desenin genişletilmesi ayrıca karara bağlanmalı. |
| ME-04 | Düşük | `src/lib/profit/cost-present.ts:139-161` | Kod yerine yalnız durum koduna bakılan dallar: `import-unavailable` (503, "XLSX geçici olarak kapalı, CSV kullanın") kullanıcıya "çok fazla içe aktarma var" diye gösteriliyor, kullanıcı CSV'ye geçmesi gerektiğini öğrenemiyor; `import-in-progress` (429, aynı mağazada süren içe aktarma) da aynı genel iletiye düşüyor. Kiracı sınırı (`rate-limited`, saatlik pencere) `Retry-After` değerini saniye olarak basıyor ("3412 saniye sonra"). Sahte API bu kodları üretmediği için testler yakalamıyor. | `switch (error.code)` içine `import-unavailable`, `import-in-progress`, `import-busy`, `rate-limited` dallarını ekleyin; 120 saniyeden uzun bekleme süresini dakika olarak yazın. `fake-costs.mjs` içine bu üç yanıtı tetikleyen dosya adları ekleyin. |
| ME-05 | Düşük | `src/components/costs/cost-import-panel.tsx:227-240`, `251-265` | Klavye yolu: "Dosyayı kontrol et" düğmesi kontrol bitince DOM'dan kalkıyor, "N satırı kaydet" düğmesi de kayıt bitince kalkıyor; odak `body`'ye düşüyor (WCAG 2.4.3). Ekran okuyucu kullanıcısı rapora ve sonraki eyleme yeniden gezinmek zorunda. | Rapor bölümüne `tabIndex={-1}` ve başlık verin, faz değişince `ref.focus()`; "done" fazında odağı "Başka dosya yükle" düğmesine taşıyın. |
| ME-06 | Düşük | `src/components/costs/costs-screen.tsx:262-269`; `src/components/costs/cost-import-panel.tsx:329-350` | Canlı bölgeler: kayıt iletisinin `role="status"` kabı `hidden` (display:none) sınıfıyla gizli ve içerikle aynı anda görünür oluyor; rapor özeti `role="status"` içeriğiyle birlikte ilk kez DOM'a ekleniyor. Her iki durumda da NVDA/VoiceOver duyuruyu atlayabiliyor; aynı ürüne art arda aynı ileti yazılırsa ikinci duyuru hiç yapılmıyor. | Canlı bölgeyi her zaman DOM'da ve görünür (boş) tutun, yalnız metnini değiştirin; tekrar duyuru için iletiyi önce boşaltıp sonraki karede yazın ya da bir sayaç ekleyin. |
| ME-07 | Düşük | `src/lib/profit/use-viewer.ts:10-12`; `src/components/costs/costs-screen.tsx:84`, `111-127` | `useIsViewer` rol yüklenirken ya da `/auth/me` hata verirse `false` dönüyor: görüntüleyiciye toplu yükleme paneli ve "Maliyet gir" düğmeleri kısa süre (hata durumunda kalıcı) gösteriliyor. Sunucu 403 ile koruyor, veri riski yok; yanıltıcı arayüz. | Üç durumlu sonuç (`loading` / `viewer` / `editor`); rol bilinene kadar yazma denetimlerini gösterme. |
| ME-08 | Düşük | `src/components/costs/cost-import-panel.tsx:80-105` | Kuru deneme ve kayıt aynı `File` nesnesini iki kez okuyor. Kullanıcı dosyayı diskte kontrol ile onay arasında değiştirirse kaydedilen içerik onaylanan rapordan farklı olur; "Yalnız geçerli satırları kaydet" yolunda yeni hatalı satırlar sessizce atlanır. Bazı tarayıcılarda değişen dosya okunamaz ve hata "Sunucuya ulaşılamadı" diye görünür. Sunucu yeniden doğruladığı için bütünlük ihlali yok. | Kontrolde dosyayı bir kez belleğe alın (`new File([await file.arrayBuffer()], file.name)`, en çok 2 MB) ve kayıtta bu anlık görüntüyü gönderin; kayıt raporunun sayıları önizlemeden farklıysa uyarın. |
| ME-09 | Düşük | `src/lib/profit/cost-present.ts:138`; `src/lib/api/client.ts` (fetch hata eşlemesi) | Yukarıdaki okuma hatası ve CORS dışı istemci hataları `NetworkError` olarak "İnternet bağlantınızı kontrol edin" iletisine düşüyor; dosya kaynaklı sorun bağlantı sorunu gibi görünüyor. | `importFile` çağrısından önce dosyayı okuyun (ME-08) ve okuma hatasını "Dosya okunamadı, yeniden seçin" olarak ayrı bildirin. |
| ME-10 | Bilgi | `src/components/costs/cost-import-panel.tsx:85-89` | 200 yanıtındaki rapor `parseImportReport` ile doğrulanmıyor (yalnız 422 yolunda doğrulanıyor). Şekil sapmasında arayüz `undefined` sayı gösterebilir. Güvenlik etkisi yok (metin olarak basılıyor). | İki yolda da `parseImportReport` kullanın; `null` ise genel hata iletisi. |
| ME-11 | Bilgi | `src/components/costs/costs-screen.tsx:182`; `src/lib/profit/settings-input.ts:128-137` | `today` bileşen açılışında bir kez ve istemci saatiyle hesaplanıyor. Gece yarısını geçen oturumda ya da yanlış saatli cihazda istemci doğrulaması (bugün + 366) ve `applySavedCost` sunucudan bir gün sapabilir. Sunucu belirleyici olduğu için yalnız yanlış ileti ya da geçici yanlış satır gösterimi olur. | Diyalog açılırken `todayIstanbul()` yeniden hesaplanabilir; kayıt sonrası satırı yerel tahmin yerine `GET /products?q=<barkod>` ile tazelemek de seçenek. |
| ME-12 | Bilgi | `src/components/costs/cost-form-dialog.tsx:75-80` | Mevcut maliyeti düzenlerken varsayılan tarih "bugün". Yanlış girilmiş bir maliyeti düzelten kullanıcı farkında olmadan yeni sürüm ekler, geçmiş siparişler eski (hatalı) maliyetle kalır. Açıklama metni ve "Mevcut kaydın tarihi" düğmesi var; risk düşük ama para sonucu etkileniyor. | İki açık seçenek sunun: "Mevcut kaydı düzelt" (tarih = mevcut `valid_from`) ve "Yeni fiyattan itibaren" (tarih = bugün). |

Not: Her içe aktarma kiracı başına saatlik 30 sınırından iki hak harcıyor (kuru deneme + kayıt, `rate_limit_cost_import_tenant`);
saatte en çok 15 tam içe aktarma. Bilerek seçilmiş bir tasarım; ME-04 iletisi düzeltildiğinde kullanıcı bunu anlayabilir.

## Sonuç

Kritik: 0, Yüksek: 0, Orta: 3, Düşük: 6, Bilgi: 3.

Karar: **Koşullu kabul.** Güvenlik açısından (CSRF, kimlik bilgisi kipi, XSS, URL kodlama, yetki) birleştirmeye engel bulgu
yok. Birleştirmeden önce ME-01 (en azından sayaç sıfırlamasının kaldırılması ve sınırın düşürülmesi) ve ME-02 (fetch ile
indirme, hata ve kesilme uyarısı) giderilmeli; ME-03 için en azından istemcide desen denetimi ve açıklayıcı ileti eklenmeli,
backend kararı ayrı iş olarak açılmalı. Düşük bulgular (özellikle ME-04, ME-05, ME-06) aynı turda kapatılması kolay ve
önerilir.
