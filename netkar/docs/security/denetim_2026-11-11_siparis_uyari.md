# NetTablo S4 Güvenlik ve UX Denetimi: Sipariş kârlılık listesi ve Uyarılar ekranı (11 Kasım 2026)

**Kapsam:**
1. `7a661bf` `GET /v1/marketplace-accounts/{id}/profit/orders` (sipariş kârlılık listesi).
2. `32fe9cc` `/panel/uyarilar` ekranı (`apps/web/src/lib/profit/alerts.ts`, `components/profit/alerts-view.tsx`, özet bağlantısı).

**Ölçütler:** ADR-0005 §7, `docs/security/denetim_2026-11-09_S4_rapor.md` (önceki rapor denetimi ve kapanışı), `docs/50_guvenlik.md` (G01, G06, G07, G08, G16), `docs/ux/inceleme_2026-11-10_panel_ozet_urunler.md` §8.3, `docs/security/denetim_2026-11-09_kar_ayarlari.md` §7, `docs/12_kar_motoru.md` (uyarı kodlarının anlamı).

**Denetçi notu:** Kod bağımsız olarak incelendi; kaynak kod değiştirilmedi, commit yapılmadı. PoC için geçici bir test dosyası oluşturuldu, çalıştırıldı ve silindi (çalışma ağacı temiz).

## Sonuç önce

- **Kritik ya da Yüksek bulgu YOK.** Merge engeli yok.
- Orta 4 (SU-01, SU-05, SU-06, SU-07), Düşük 5 (SU-02, SU-03, SU-04, SU-08, SU-09), Bilgi 1 (SU-10).
- Güvenlik çekirdeği (IDOR/BOLA, RLS, imleç mühürü ve parmak izi ayrımı, `q` doğrulaması, ReportGate ve oran sınırı paylaşımı, kişisel veri yokluğu, XSS'e kapalı gösterim) doğru.
- Orta bulgular alan ve UX doğruluğudur: uyarı kartlarının üç tanesinde metin ya da eylem bağlantısı motorun gerçek anlamıyla tam örtüşmüyor (SU-05, SU-06, SU-07); sipariş listesi önbelleksiz motor maliyetini (açık O-01, YO-01) büyütüyor (SU-01). Siparişler ekranı yazılmadan ve uyarılar ekranı yayına alınmadan önce ele alınmalı.

## 0. Yöntem ve test sonuçları

| Adım | Sonuç |
|---|---|
| `git checkout --detach 7a661bf` | Tamam (HEAD `7a661bf`, üstünde `32fe9cc`) |
| `uv run pytest -q --no-cov tests/test_report_orders_api.py` | **50 geçti** (34,7 sn) |
| `npm test` (apps/web) | **Koşulmadı:** `apps/web/node_modules` yok. Ön yüz kod okumayla incelendi; commit mesajındaki vitest 618/618 ve Playwright sonuçları doğrulanmadı. |
| PoC 1 (SU-02) | Dönem sınırına yayılan iki paketli sipariş: listede `ordered_on` dönem dışı, kart tutarı ile dönemsiz detay farklı (aşağıda) |
| PoC 2 (SU-04) | Var olmayan sipariş no ile `q` araması: `total_count 0`, motor 1 kez çalıştı |

PoC çıktısı (dönem 2026-10-01..2026-10-31; sipariş 3001: paket 31 2026-09-20, paket 32 2026-10-14):

```
POC ordered_on 2026-09-20 period_start 2026-10-01 line_count 1 net_sales 50.00
POC detail_no_period 200 {'period': {'start': '2026-09-20', 'end': '2026-10-14', ...}, 'totals': {'line_count': 2, 'net_sales_excl_vat': '133.33', ...
POC q_nonexistent 200 0 engine_runs 1
```

## 1. Özet tablo

| No | Önem | Başlık | Konum |
|---|---|---|---|
| SU-01 | Orta | Sipariş listesi her sayfada tüm dönem motorunu çalıştırıyor; uzun sipariş listelerinde açık O-01/YO-01 etkisi büyüyor | `services/api/app/api/v1/profit.py:400` |
| SU-05 | Orta | `BEKLENMEYEN_KESINTI`: varsayılan desi ipucu koşulsuz, kalem dökümü yok (K38, §7.7, §8.3) | `apps/web/src/lib/profit/alerts.ts:67-74`, `components/profit/alerts-view.tsx:340-351`, `services/api/app/api/v1/profit_schemas.py:535-548` |
| SU-06 | Orta | `ZARAR` kartı satır sayar, eylemi ürün düzeyi zarar süzgecine gider: sayı ile açılan liste tutmayabilir | `apps/web/src/lib/profit/alerts.ts:25-31, 59-66` |
| SU-07 | Orta | `KARGO_TARIFESI_EKSIK` metni yanlış neden söylüyor (tarife varken de üretilir) ve net kârın hesaplanamadığını söylemiyor | `apps/web/src/lib/profit/alerts.ts:82-88` |
| SU-02 | Düşük | `ordered_on` ve tarih sıralaması dönem dışı ilk paketin anını kullanıyor; kart tutarı yalnız dönem içi paketler (PoC) | `services/api/app/services/profit_views.py:653-667`, `profit.py:403` |
| SU-03 | Düşük | `awaiting_payout` adı "hakediş ödenmedi" diye okunuyor, tanım "ekstre kaydı yok" | `profit_views.py:591`, `profit_schemas.py:514` |
| SU-04 | Düşük | Var olmayan sipariş no araması 92 günlük motoru çalıştırıyor; tarih sorgusu net kâr sıralamasında da tüm satırlar için | `profit.py:397-403` |
| SU-08 | Düşük | "Tüm uyarılar (N)" aynı sorunu iki kez sayıyor ve binlerle şişiyor; kurulum grubunda aynı eylemli yinelenen kartlar; sayılarda binlik ayırıcı yok | `alerts.ts:97-120, 321-326`, `alerts-view.tsx:202-210`, `summary-view.tsx:473` |
| SU-09 | Düşük | Erişilebilirlik ve rol: `list-none` liste anlamı, ton ayrımı ekran okuyucuda yok, yinelenen "Tanınmayan uyarı" başlıkları, görüntüleyiciye "gir" eylemleri | `alerts-view.tsx:48-60, 171, 198-201, 223-225`, `alerts.ts:290-299` |
| SU-10 | Bilgi | §8.3 "Gizle/Okundu" yok; etkilenen siparişler sipariş ekranına bağlanmıyor; Siparişler sayfası hâlâ "Henüz sipariş yok" diyor | `alerts-view.tsx:320-338`, `app/(app)/panel/siparisler/page.tsx` |

## 2. Ayrıntılar: 7a661bf (`GET /profit/orders`)

### SU-01 (Orta) Sipariş listesi her sayfada tüm dönem motorunu çalıştırıyor

**Konum:** `services/api/app/api/v1/profit.py:400` (`_report`), ADR-0005 §7 ("önbellek yok").

**Açıklama:** Uç, ürün listesinin desenini doğru izliyor: istek başına motor bir kez (`test_one_request_runs_the_engine_exactly_once_and_a_second_page_is_a_new_run`), kapı ve oran sınırı paylaşılıyor. Ancak sipariş listesi ürün listesinden çok daha uzundur: ayda 1.000 sipariş veren bir satıcı için 92 günde yaklaşık 3.000 sipariş, varsayılan `limit=50` ile 60 sayfa, yani 60 tam motor çalışması. Önceki ölçümde 30.000 satır, 92 gün `summary` 10 sn ve yüzlerce MB idi (S4 O-01; bu denetimde yeniden ölçülmedi). Kapanış denetimindeki açık YO-01 (iki büyük kiracı süreçteki 4 yuvayı doldurunca diğerleri 503) ile birleşince, Siparişler ekranında "Daha fazla yükle" ile gezinen tek bir büyük satıcı kapı yuvasını dakikalarca dolu tutar. Ek motor sonrası iş (satır gruplama, sıralama, `ANY(array)` tarih sorgusu) motorun yanında küçüktür: `ix_orders_account_order_number (marketplace_account_id, order_number)` dizini var, sorgu tek gidiş ve dizi parametresiyle bağlayıcı sınırına takılmıyor.

**Somut düzeltme:**
1. Siparişler ekranı yayına girmeden önce O-01 madde 3'teki kısa ömürlü dönem sonucu önbelleği: anahtar (kiracı, hesap, start, end, `settings_revision`, hesabın veri sürümü ya da son senkron zamanı), TTL 60-120 sn, bellek tavanlı LRU. Ürün, sipariş, uyarı ve özet uçları aynı girdiyi paylaşır.
2. Önbellek gelene dek panel Siparişler ekranında `limit=200` kullansın ve önceden sayfa getirmesin (prefetch yok); `range` varsayılanı 30 gün kalsın.
3. Önbellek anahtarında kiracı ve hesap mutlaka bulunsun; imleç parmak izi değişmeden kalabilir.

**Test önerisi:** Aynı dönem için `products` ve `orders` ardışık istekleri motoru bir kez çalıştırmalı; senkron sonrası yeniden çalıştırmalı.

### SU-02 (Düşük) `ordered_on` ve tarih sıralaması dönem dışı ilk paketin anını kullanıyor

**Konum:** `services/api/app/services/profit_views.py:653-667` (`order_dates`: `min(Order.ordered_at)` dönem sınırı olmadan), `services/api/app/api/v1/profit.py:403`; besleyici dönem seçimi `app/services/profit_feed.py:8, 124-125` (paket `ordered_at` dönem içinde).

**Açıklama:** Motor dönemi PAKET düzeyinde seçer; sipariş listesi kartı yalnız dönem içi paketlerin satırlarını toplar. `ordered_on` ise siparişin TÜM paketlerinin en erkeni olduğu için dönem dışı olabilir ve `sort=date` bu dönem dışı anla sıralar. PoC: 2026-10 döneminde sipariş 3001 kartı `ordered_on 2026-09-20`, `line_count 1`, `net_sales 50.00`; aynı siparişin dönemsiz detayı `line_count 2`, `net_sales 133.33`. Kullanıcı Ekim listesinde Eylül tarihli bir sipariş görür ve detaya geçince farklı tutar okur. Güvenlik etkisi yok.

**Somut düzeltme:**
1. `order_dates` sorgusuna besleyiciyle aynı dönem sınırlarını ekleyin (`Order.ordered_at >= lower, < upper`, İstanbul günü), ya da tarihi motorun girdisindeki satır sipariş gününden alın (besleyici `order_day` üretiyor; DB sorgusu tamamen kalkar).
2. Kartta `package_count_outside_period` ya da `partial_period: true` bayrağı; panel "Siparişin bir kısmı bu dönemin dışında" notu göstersin.
3. Panel sipariş detayını listedeki `start`/`end` ile açsın (S4 denetimi §7 madde 7, hâlâ geçerli). ADR-0005 §7'ye "kart yalnız dönem içi paketlerdir" cümlesi eklensin.

**Test önerisi:** İki paketi dönem sınırının iki yanında olan sipariş: `ordered_on` dönem içinde, tarih sıralaması dönem içi pakete göre.

### SU-03 (Düşük) `awaiting_payout` adı ile tanımı ayrışıyor

**Konum:** `profit_views.py:591` (`any(line.status is Status.ESTIMATED ...)`), `profit_schemas.py:514`, ADR-0005 §7.

**Açıklama:** Tanım docs/12 §5 ile tutarlı ve doğru uygulanmış: `estimated` = "eşleşen Sale kaydı yok"; iptal satırlar hariç; "en az bir aktif satır". Ancak "hakediş bekleyen" satıcı dilinde "parası henüz hesabıma geçmedi" demektir. Trendyol'da Sale kaydı teslimde oluşur, ödeme vadesi sonradır; ekstresi gelmiş (`settled`) ama parası ödenmemiş sipariş bu süzgece girmez, teslim edilmemiş sipariş ise girer. Süzgeç adıyla nakit beklentisi kurulursa yanlış okunur. (Motorda ödeme tarihi alanı olup olmadığı bu denetimde doğrulanmadı.)

**Somut düzeltme:** API alanı geriye uyumluluk için kalabilir ama açıklaması "ekstre kaydı (hakediş kaydı) henüz gelmemiş; ödeme durumu değildir" olsun; panel etiketi "Ekstresi gelmeyen (tahmini)" olsun. Nakit anlamı istenirse ayrı alan (`payout_pending`, vade tarihi bazlı) docs/12'de tanımlandıktan sonra eklensin.

### SU-04 (Düşük) Var olmayan sipariş no araması tam dönem motorunu çalıştırıyor

**Konum:** `profit.py:397-403`.

**Açıklama:** `q` doğrulaması sağlam (desen, 64 karakter, yalnız bellekte tam eşleşme, SQL'e gitmiyor). Ancak sonuç boş olacak bir arama da 92 günlük motoru çalıştırıyor (PoC: `total_count 0`, `engine_runs 1`). Sipariş detay ucu bilinmeyen siparişi motordan önce 404 ile keser; liste araması kesmiyor. Ayrıca `order_dates` her istekte süzülmüş TÜM siparişler için çalışıyor; `sort=net_profit` iken yalnız sayfadaki siparişlerin tarihi gerekir. Oran sınırı ve kapı bunu sınırlar, bu yüzden Düşük.

**Somut düzeltme:**
1. `q` verildiğinde motordan önce siparişin dönem içinde paketi var mı tek sorguyla bakın (`order_days` benzeri, dönem sınırlı); yoksa motor çalıştırmadan boş liste dönün (istek yine sayılır).
2. `sort=net_profit` iken `order_dates`'i sayfalamadan SONRA yalnız sayfadaki sipariş numaraları için çağırın; `sort=date` iken mevcut tek sorgu kalsın.

**Test önerisi:** Var olmayan `q` ile motor çalışmamalı; `sort=net_profit` sayfasında tarih sorgusunun dizi uzunluğu `limit`'i aşmamalı.

## 3. Ayrıntılar: 32fe9cc (`/panel/uyarilar`)

### SU-05 (Orta) `BEKLENMEYEN_KESINTI`: koşulsuz desi ipucu, kalem dökümü yok

**Konum:** `apps/web/src/lib/profit/alerts.ts:67-74` (kart cümlesi), `apps/web/src/components/profit/alerts-view.tsx:340-351` (etkilenen sipariş satırı yalnız fark ve eşik), `services/api/app/api/v1/profit_schemas.py:535-548` (`AlertOut` karşılaştırma alanı taşımıyor).

**Açıklama:**
- Kart cümlesi "Siparişte desi yoksa fark varsayılan desiden kaynaklanabilir" ipucunu HER durumda veriyor. docs/12 K38 (AD-05) ipucunu yalnız `karsilastirma.kargo_tahmini_varsayilan_desi = true` olduğunda ister; kâr ayarları denetimi §7.7 "kargo farkı baskınsa" der. Fark komisyondan ya da hizmet bedelinden doğduğunda ipucu satıcıyı yanlış yöne iter.
- UX §8.3 ve kâr ayarları denetimi §7.7 "etkilenen siparişler, **kalem dökümü** (tahmini ve kesin kargo, hizmet bedeli, komisyon)" ister. Liste yalnız toplam farkı ve eşiği gösteriyor; hangi kalemin fazla kesildiği görünmüyor. UX §9 S4 senaryosunun başarı ölçütü ("farkın kargodan kaynaklandığını söyler", "Trendyol hata yaptı yanlış sonucuna varan 0") bu ekranla karşılanamaz.
- "Trendyol ekstrede ... fazla kesinti yaptı": karşılaştırılan kargo ve hizmet bedeli kesin değerleri kargo ve hizmet faturalarından gelir (docs/12 §6), yalnız ekstreden değil.
- API tarafında `AlertOut` bu bilgiyi taşımadığı için panel doğru davranışı tek başına kuramaz.

**Somut düzeltme:**
1. API: `BEKLENMEYEN_KESINTI` öğelerine motorun `karsilastirma` bloğundan kalem dökümünü ekleyin (`breakdown: [{item: commission|outbound_shipping|platform_service_fee, estimated, actual}]`) ve `default_desi_used: bool` (`kargo_tahmini_varsayilan_desi`). Para alanları iki ondalıklı dizge, yeni kural yok.
2. Panel: kart cümlesinden desi ipucunu kaldırın: "Trendyol bu satışlarda beklediğimizden fazla kesti (komisyon, kargo ya da hizmet bedeli)." Etkilenen sipariş satırında kalem dökümü; ipucu yalnız `default_desi_used` true ve kargo farkı en büyük kalem ise.
3. API değişikliği gelene dek ipucu "Fark kargodaysa ve siparişte desi yoksa varsayılan desi farkı olabilir" biçiminde koşullu dille yazılsın.

**Test önerisi:** Komisyon kaynaklı farkta ipucu görünmemeli; varsayılan desili kargo farkında görünmeli; döküm kalemlerinin farkları toplam farka eşit olmalı.

### SU-06 (Orta) `ZARAR` kartının sayısı ile eylem listesi farklı düzeyde

**Konum:** `apps/web/src/lib/profit/alerts.ts:25-31` (`lossProductsHref`), `59-66`.

**Açıklama:** `ZARAR` satır uyarısıdır (docs/12 K37: satırın net kârı < 0 ya da null ve bilinen giderlerle kâr < 0); kart "Zarar eden satışlar (N)" der. Eylem `/panel/urunler?filter=loss` ise ÜRÜN toplamına bakar (`loss_reason(ProductTotals)`). Bir ürünün iki satırından biri zararda ama toplamı kârdaysa ürün listede çıkmaz: kart "3 zarar eden satış" der, tıklanan liste boş ya da daha kısa olabilir. Sıra doğru (`sort=net_profit&order=asc`, AD-04), sorun düzey uyumsuzluğu. UX §8.3 birincil eylemi "uyarıdan ilgili ürün ya da siparişe gitmek".

**Somut düzeltme:**
1. Kısa vadede (Siparişler ekranı yokken): eylem etiketi "Zararda olan ürünleri gör" ve kart cümlesine "Liste ürün toplamına göredir; tek satırı zararda olan ürün kârlı görünebilir." Ya da kart açıldığında `alerts?code=ZARAR` listesini (`BEKLENMEYEN_KESINTI` ile aynı `DeductionDetails` deseni: sipariş, barkod, net kâr ya da bilinen giderlerle kâr) gösterin; bu veri API'de zaten var (`AlertOut.net_profit`, `known_expenses_profit`).
2. Siparişler ekranı gelince eylem `/panel/siparisler?filter=loss&sort=net_profit&order=asc&range=...` olsun (sipariş düzeyi yeni uçla tutarlı).

**Test önerisi:** Toplamı kârlı ürünün tek zarar satırında kart eylemi boş liste göstermemeli.

### SU-07 (Orta) `KARGO_TARIFESI_EKSIK` metni yanlış neden söylüyor

**Konum:** `apps/web/src/lib/profit/alerts.ts:82-88`.

**Açıklama:** Metin: "Kargo tarifesi tanımlı olmadığı için tahmini kargo bedeli hesaplanamadı." docs/12 K34'e göre kargo, firmanın o gün geçerli tarifesi VARKEN de eksik olur: desi en yüksek kademeyi aşıyorsa ya da desi bilinmiyorsa (`*` yedeğine düşülmez) ve aynı `KARGO_TARIFESI_EKSIK` uyarısı üretilir. Tarifesini girmiş satıcıya "tarife tanımlı değil" denir, "Kargo tarifesini gir" eylemi döngüye sokar. Ayrıca metin, bu satırlarda NET KÂRIN hesaplanamadığını söylemiyor (K37; hizmet bedeli kartı söylüyor, kargo kartı söylemiyor).

**Somut düzeltme:** Metin: "Bu satışlar için tarifede uygun fiyat bulunamadı (tarife yok, desi tarifedeki en yüksek kademeyi aşıyor ya da desi bilinmiyor); net kâr hesaplanamıyor." Eylem etiketi "Kargo tarifesini kontrol et". İleride API ayrım verirse (`reason: no_tariff|desi_over_max|desi_unknown`) kart nedene göre ayrılsın.

**Test önerisi:** Kart metni "tanımlı olmadığı için" ifadesini içermemeli; net kârın hesaplanamadığını söylemeli.

### SU-08 (Düşük) Uyarı sayısı şişiyor, kurulum kartları yineleniyor

**Konum:** `apps/web/src/lib/profit/alerts.ts:97-120` (dönem özeti kartları), `321-326` (`totalAlertCount`), `apps/web/src/components/profit/alerts-view.tsx:202-210` (sayı biçimi), `apps/web/src/components/profit/summary-view.tsx:473`.

**Açıklama:**
- `totalAlertCount` satır uyarılarının sayısı ile dönem özet uyarılarını toplar. `MALIYET_EKSIK` (satır) ile `MALIYET_EKSIK_SATIRLAR_VAR` (dönem, 1) aynı sorundur ve iki kez sayılır; kargo ve hizmet bedeli için de aynı. Ayarsız bir hesapta `KARGO_TARIFESI_EKSIK` ve `HIZMET_BEDELI_TAHMINI_EKSIK` her aktif satırda üretilir (önceki denetim: 5.000'in üzerinde), özetteki "Tüm uyarılar (10.4xx)" uyarı yorgunluğu yaratır (UX §8.3 "uyarı yorgunluğu yaratmasın").
- Kurulum grubunda aynı eyleme giden iki kart görünür ("Kargo tarifesi eksik" ve "Dönem kârı kısmi: kargo eksik"), toplam 6 kart, 3 sorun.
- `card.count` ham sayı olarak basılıyor ("5231"); Türkçe biçim "5.231" olmalı.

**Somut düzeltme:** Dönem özet kodunu ilgili satır kartına birleştirin (satır kartında "Dönem net kârı bu yüzden kısmi" cümlesi; ayrı kart yalnız satır kodu hiç yoksa). Özet bağlantısı toplam satır sayısı yerine kart (sorun türü) sayısını göstersin: "Tüm uyarılar (5 tür)" ya da önce para kaybettiren grubun sayısı. Sayılar `Intl.NumberFormat('tr-TR')` ile biçimlensin.

### SU-09 (Düşük) Erişilebilirlik ve rol ayrıntıları

**Konum:** `alerts-view.tsx:48-60, 171, 198-201, 223-225, 320`, `alerts.ts:290-299`.

**Açıklama ve düzeltme:**
- `<ul className="list-none ...">`: Safari ve VoiceOver `list-style: none` olan listede liste anlamını düşürür. `role="list"` ekleyin (171, 320, 384. satırlardaki üç liste).
- Renk tek başına anlam taşımıyor (simge şekli ve grup başlığı var; görsel olarak WCAG 1.4.1 karşılanıyor). Ancak simge `aria-hidden` olduğundan "Bilgi ve kontrol" grubundaki `info` ve `warning` tonlu kartların farkı ekran okuyucuda yok. Başlığa `sr-only` "Uyarı:" / "Bilgi:" öneki ekleyin.
- Birden çok bilinmeyen kod aynı `h3` "Tanınmayan uyarı" başlığıyla gelir; başlıklar ayırt edilemez. Başlığa kodu ekleyin ("Tanınmayan uyarı: KOD").
- Görüntüleyici rolü ayar formunu salt okunur görür (`useEditAccess`), ama kart eylemleri "Kargo tarifesini gir", "Hizmet bedelini gir" der. Görüntüleyicide etiket "Kargo tarifesini gör" olsun ve cümleye "Hesap yöneticiniz girebilir." eklensin.

### SU-10 (Bilgi) Açık kalan UX maddeleri

- UX §8.3 "Okundu" ya da "Gizle (dönem bazında)" yok; commit mesajı backend karşılığı olmadığını belirtiyor. Kabul edilebilir; S4 kapsamında açık madde olarak izlenmeli.
- Etkilenen siparişler listesinde sipariş numarası bağlantı değil (`alerts-view.tsx:323-331`). Siparişler ekranı yazılınca `/panel/siparisler?q=<no>&start=..&end=..` bağlantısı verilmeli (SU-02 madde 3).
- `app/(app)/panel/siparisler/page.tsx` hâlâ "Henüz sipariş yok" boş durumunu gösteriyor; bağlı ve siparişli hesapta yanıltıcı. `/orders` ucu artık var; ekran yazılana dek metin "Siparişler ekranı yakında" olmalı (bu iki commit'in dışında, önceden var olan durum).
- Kapanış denetimindeki YB-02 (kanonik olmayan imleç base64'ü) bu uç için de geçerli; etiket doğrulaması aynı baytlar üzerinde olduğundan bütünlük etkisi yok.

## 4. Doğru çalışanlar

### 7a661bf (`GET /profit/orders`)

| Kontrol | Sonuç ve kanıt |
|---|---|
| IDOR/BOLA (G01, API1) | `_guard` önce `account_exists(tenant_id, account_id)`; yabancı hesap 404 ve sızıntı yok (`test_other_tenants_account_is_404_and_leaks_nothing`, `test_each_tenant_sees_only_its_own_orders`). Motor sonucu yalnız isteyen hesabın verisinden. |
| RLS ve çift kilit | Motor bağlantıyı iade ettikten sonra `_restore_context` ile RLS bağlamı yeniden kuruluyor (`profit.py:402`); `order_dates` ve `product_titles` ayrıca açık `tenant_id` + `marketplace_account_id` süzgeci taşıyor. |
| İmleç AAD ve parmak izi | AES-256-GCM, `derive_key(master, "report-cursor")`, AAD = `tenant|account|` + parmak izi. Parmak izi `orders|sort|order|filter|q|start|end`; ürün (`products|`), satır (`lines|`) ve uyarı (`alerts|`, 5 parça) imleçleriyle önekten ayrışıyor. `q` deseni `|` içeremediği için parmak izi alanları kayamaz. Testli: ürün imleci, başka sorgu, başka kiracı ya da hesap, kurcalanmış ve doğru parmak izli sahte içerik 422 ve motor çalışmadan reddediliyor (`_check_cursor` motordan önce). |
| `q` enjeksiyonu (G06) | `^[A-Za-z0-9][A-Za-z0-9._-]*$`, 1-64 karakter; yalnız bellekte tam eşleşme, SQL'e girmiyor; geçersiz değer 422 ve yansıtılmıyor (`test_search_value_is_validated`). `ANY(array)` sorgusu bağlı dizi parametresi (`bindparam(..., ARRAY(Text))`), ham SQL yok. |
| ReportGate ve oran sınırı (G07) | `_report` kapı yuvasını kullanıyor (429/503 testli); oran sınırı anahtarı diğer rapor uçlarıyla aynı kova (`test_rate_limit_is_per_tenant_per_minute_and_shared_with_the_other_report_endpoints`). |
| Motor istek başına bir kez | `_report` tek çağrı; ikinci sayfa yeni çalıştırma (testli; ADR ile uyumlu). |
| Büyük dönem sorgusu | Tarih sorgusu tek gidiş, dizi parametresi (bağlayıcı sınırı yok), `ix_orders_account_order_number` dizini kullanılabilir; 92 gün tavanı korunuyor (`test_period_rules_match_the_other_report_endpoints`). Maliyet notu SU-01, SU-04. |
| Kişisel veri (G16, KVKK) | Yanıtta yalnız sipariş no, barkod ve katalog başlığı. `customer_key`, il, ad, adres, telefon yok; PII yüklü senkron sonrası anahtar taraması testli (`test_response_never_carries_customer_data_even_with_a_pii_laden_sync`, `test_item_keys_are_exactly_the_documented_contract`). Katalog başlığı satıcının ürün kartıdır (sipariş kişiselleştirmesi değil), kişisel veri değil. |
| İptal null kuralı (B-02) | Tümüyle iptal siparişte `cancelled=true`, `net_profit`, `net_sales_excl_vat`, `known_expenses_profit` null, `certainty=cancelled`; kısmi iptalde toplamlar yalnız aktif satırlardan (`order_totals`). Testli (`test_list_shape_defaults_and_cancelled_order_has_null_amounts_not_zero`). |
| `awaiting_payout` uygulaması | docs/12 §5 `estimated` tanımıyla birebir, iptal satırlar hariç (adlandırma notu SU-03). `unexpected_deduction` yalnız motorun ürettiği kod. |
| Zarar kuralı | `order_loss_reason` ürün `loss_reason` ile aynı K37 kuralı; null net kârlı kesin zarar `asc` sıralamada bilinen değeriyle öne geliyor (AD-04 deseni), belirsiz ve iptal her yönde sonda. |
| Sıralama ve sayfalama | Ortak `value_page`: (boş mu, yöne göre değer, sipariş no artan) anahtarı; imleç anahtarı sıralama anahtarıyla aynı işlevden; değer `is_finite` denetimli. Tüm listeyi bir kez ve aynı sırayla gezme testli. Sayfalar arası kayma B-05 (açık, önbellekle gider). |
| Hata yanıtları (G08) | Girdi tutarsızlığı ayrıntısız 500 problem yanıtı, log yalnız hesap kimliği ve hata sınıfı (testli). |
| Liste toplamı ile özet | Altın senaryolarda Σ net satış, Σ bilinen giderlerle kâr - dönem düzeyi giderler ve tam dönemde Σ net kâr özet ile eşit (testli). |

### 32fe9cc (`/panel/uyarilar`)

| Kontrol | Sonuç ve kanıt |
|---|---|
| XSS'e kapalı gösterim | Tüm API metinleri React metin düğümü; `dangerouslySetInnerHTML` yok (yalnız ilgisiz `json-ld.tsx`). Bilinmeyen kodun mesajı 280 karakterle kırpılıp düz metin; kod `<code>` içinde metin. Test `<b>kalın</b>` metninin işlenmeden göründüğünü doğruluyor. |
| Bilinmeyen kod | `Object.hasOwn` ile katalog araması (`__proto__`, `constructor` testli); çökmeden "Diğer uyarılar" grubunda, eylemsiz, nötr tonla. Sayısı sıfır ya da geçersiz giriş atılıyor. |
| Bağlantı güvenliği | `range` `parseRange` ile beyaz listeden; barkod `encodeURIComponent` ile ve backend deseni `.` ile başlamaya izin vermediği için yol kaçışı yok; ürün bağlantıları sorgu dizesini `productQueryString` ile kuruyor. |
| Eylem bağlantıları | `#kargo`, `#hizmet-bedeli`, `#desi` ayar bölümlerinde gerçek kimlikler (`tariff-section.tsx:115`, `fee-section.tsx:88`, `defaults-section.tsx:82`); maliyet eksik süzgeci ve zarar süzgecinin sırası (`asc`, AD-04) doğru. Düzey uyumsuzluğu SU-06. |
| Uyarı kodu kapsamı | Katalog motorun `WarningCode` kümesinin tamamını içeriyor (18 kod, birebir); motorun üretmediği `REKLAM_KARI_YIYOR`, `IADE_ORANI_ARTISI` sayısız "Henüz hesaplanmayan uyarılar" bölümünde, gerekçe metni basılmadan. |
| Metin doğruluğu (SU-05, SU-06, SU-07 dışındakiler) | `ZARAR` cümlesi K37 ile, `HIZMET_BEDELI_TAHMINI_EKSIK` K35 ile, `KARGO_DESI_VARSAYILAN` K34 ile, `KARGO_FATURASI_KDV_BELIRSIZ` ("KDV hariç kabul edildi") docs/12 K08 (bilinmeyen KDV hariç kabul) ile, `SINIFLANDIRILMAMIS_KESINTI` ("ihtiyatla kâra yansıtıldı", dönem geneli) ile, `IADE_KAYDI_BEKLENIYOR` K41 ile (bilgi tonu, eylemsiz; UX §8.3) uyumlu. Grup sırası UX §8.3 (para kaybettirenler üstte, kurulum ayrı). |
| Başlık yapısı | `h1` (PageHeader) -> `h2` grup ve "Henüz hesaplanmayan uyarılar" -> `h3` kart; bölümler `aria-labelledby` ile adlandırılmış. |
| Renk tek başına anlam taşımıyor | Her tonun ayrı simgesi, görünür başlığı ve grup başlığı var; sayı rozetinde `sr-only` "uyarı". (Ekran okuyucu ton ayrımı SU-09.) |
| Durumlar | Yükleniyor (iskelet, `role="status"`), boş ("Bu dönemde uyarı yok"), hata ("Tekrar dene"), mağaza yok; açılır ayrıntı `aria-expanded`/`aria-controls`; sayfalama hatası `role="alert"`; `cursor_invalid` sonrası "baştan yüklendi" bildirimi (S4 §7.11). |
| 429 davranışı | `Retry-After` bir kez, en çok 30 sn beklenir, `AbortSignal` ile iptal edilir; ikinci 429 kullanıcıya düğmeyle bırakılır. |
| İstek maliyeti | Sayımlar için `limit=1` tek istek; ayrıntı listesi yalnız kart açılınca istenir. |

## 5. 50_guvenlik.md merge engeli kontrolleri (bu kapsamdakiler)

| Kontrol | Durum |
|---|---|
| G01 Kiracı izolasyonu | Karşılanıyor |
| G06 Girdi doğrulama | Karşılanıyor (`q`, `sort`, `order`, `filter`, `limit`, `cursor`) |
| G07 Hız sınırı | Karşılanıyor (paylaşılan kova + kapı); maliyet notu SU-01 |
| G08 Hata yanıtları | Karşılanıyor |
| G09 Log | Karşılanıyor (sorgu dizesi ve tutar loglanmıyor) |
| G16 Kişisel veri | Karşılanıyor |

## 6. Öncelikli yapılacaklar

1. SU-05, SU-06, SU-07: uyarılar ekranı kullanıcıya açılmadan önce metin ve eylem düzeltmeleri (SU-05 için API'ye kalem dökümü ve `default_desi_used`).
2. SU-01: Siparişler ekranı yazılmadan önce dönem sonucu önbelleği (O-01 madde 3, YO-01 ile birlikte).
3. SU-02, SU-04: tarih sorgusunu dönemle sınırlamak, boş aramada motoru atlamak (küçük kod).
4. SU-03, SU-08, SU-09: etiket, sayı ve erişilebilirlik iyileştirmeleri.

## 7. Backend kapanışı (12 Kasım 2026)

| No | Durum | Karşılık |
|---|---|---|
| SU-01 | Kapandı | Süreç içi dönem sonucu önbelleği: `app/services/report_cache.py`; anahtar (kiracı, hesap, dönem, `settings_revision`, hesap veri sürümü), TTL 90 sn, LRU (16 girdi, 40.000 satır, kiracı başına 4). Tüm rapor uçları aynı girdiyi paylaşır; isabet kapıya girmez ve motoru çalıştırmaz (test: ikinci istekte motor 0). Ayar yazımı, maliyet içe aktarma ve PUT, senkron yazımı sonrası eski sonuç dönmez (test). Kiracılar arası sızıntı testle çürütüldü. Ölçüm (5.000 satır): ilk istek yaklaşık 1,5 sn, isabet 0,06 sn; saklanan sonuç yaklaşık 4 KB/satır. Şema değişikliği yok. |
| SU-02 | Kapandı | `order_dates` dönem sınırlı (`ordered_at` İstanbul günü [start, end]); PoC testi: `ordered_on` dönem içi paketten, tarih sıralaması aynı anla. ADR-0005 §7'ye "kart yalnız dönem içi paketlerdir" yazıldı. `partial_period` bayrağı eklenmedi (isteğe bağlıydı). |
| SU-03 | Kapandı (belge) | ADR-0005 §7: `awaiting_payout` = "ekstresi gelmeyen", ödeme durumu değil. Alan adı geriye uyum için korundu. |
| SU-04 | Kapandı | `q` verildiğinde dönemde böyle bir paket yoksa motor çalıştırılmadan boş liste; `sort=net_profit` iken tarih sorgusu yalnız sayfadaki siparişler için (testli). |
| SU-05 (API) | Kapandı | `AlertOut.breakdown` ve `AlertOut.default_desi_used` (yalnız `BEKLENMEYEN_KESINTI`, isteğe bağlı); motorun `karsilastirma` bloğundan türer, motor değişmedi. Panel kısmı (metin, koşullu ipucu) web ajanındadır. |
| YO-01 | Kısmen kapandı | Önbellek isabeti yuva tutmaz ve eşzamanlı aynı anahtar tek motor çalıştırması paylaşır; kapıda adalet kuralı: son boş süreç yuvası yuvası olmayan kiracıya ayrılır (iki ağır kiracı üçüncüyü sürekli 503'te bırakamaz). Dört ve üzeri farklı ağır kiracı yine tüm yuvaları doldurabilir; ağır rapor havuzu (öneri 3) yapılmadı. |
| O-01 madde 3 | Kapandı | SU-01 ile. Çok süreçli dağıtımda önbellek süreç başınadır. |
