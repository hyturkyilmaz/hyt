# Denetim: dönem sonucu önbelleği ve siparişler ekranı (a6312ff, 1002d5a)

Tarih: 12 Kasım 2026. Denetçi: bağımsız güvenlik ve doğruluk denetimi (kodu yazan değil). Kaynak kod değiştirilmedi.

Kapsam:

- a6312ff (backend): `app/services/report_cache.py` ve kullanımları (`app/api/v1/profit.py` `_report`, `deps.py`, `main.py`, `config.py`), `report_gate.py` adalet kuralı (YO-01), `profit_views.py` (`order_dates`, `order_in_period`, `alert_breakdown`), `profit_schemas.py`, `tests/conftest.py`, `tests/test_report_cache.py`.
- 1002d5a (web): `/panel/siparisler` (`components/profit/order-list.tsx`, `lib/profit/orders.ts`, `lib/profit/query.ts`, `lib/api/profit.ts`) ve uyarılar düzeltmeleri (`lib/profit/alerts.ts`, `components/profit/alerts-view.tsx`, `lib/profit/use-viewer.ts`).
- Önceki denetimler: `denetim_2026-11-11_siparis_uyari.md` (SU-01..SU-05, §7 backend kapanışı), `denetim_2026-11-09_S4_rapor.md` (YO-01, O-01).

## Sonuç önce

- Kritik 0, Yüksek 0. Orta 3 (OS-01, OS-02, OS-03), Düşük 6 (OS-04..OS-09), Bilgi 1 (OS-10).
- Kiracılar arası sızıntı YOK: anahtar kiracı ve hesabı içerir, her uçta `_guard` (hesap sahipliği, 404) önbellek okumasından ÖNCE çalışır; önbellek isabeti yetkiyi atlamaz (kod ve test ile doğrulandı).
- Bayatlık işareti bugünkü bütün yazım yollarını kapsıyor (senkron upsert, `removed_at`, maliyet içe aktarma ve PUT, senkron imleci); `updated_at` yazmayan yazım yolu bulunmadı. Kalan pencere TTL (90 sn) ile sınırlı (OS-04).
- Orta bulgular performans ve adalet tasarımıyla ilgili, veri gizliliğiyle değil: tavanı aşan (saklanmayan) sonuçta tek uçuş bekleyenleri SIRAYLA yeniden hesaplatıyor (OS-01, PoC: 3 istek, 3 motor çalışması, 3 kat süre); kiracı başına tavan yalnız girdi sayısını sınırlıyor, satır ağırlığını değil (OS-02, PoC: tek kiracı 5 kurbanın 5'ini de düşürdü); veri sürümü sorgusu her istekte (isabet dahil) hesabın tüm geçmiş satırlarını tarıyor (OS-03).
- SU-02, SU-04, SU-05 backend düzeltmeleri doğru. Web tarafında alanlar şemayla birebir; iptal ve null net kâr gösterimi, `known_expenses_profit` etiketi, kalem dökümünün listedeki dönemle açılması doğru.

## 0. Yöntem ve test sonuçları

| Adım | Sonuç |
| --- | --- |
| `uv run pytest -q --no-cov tests/test_report_cache.py tests/test_report_orders_api.py` | 71 geçti, 0 düştü (34,6 sn) |
| PoC 1 (OS-01): `ReportCache(max_lines=100)`, 500 satırlık sonuç, aynı anahtarla 3 eşzamanlı `get_or_compute` | Motor 3 kez çalıştı, toplam 0,6 sn (tek çalışma 0,2 sn): bekleyenler sırayla yeniden hesapladı |
| PoC 2 (OS-02): varsayılan ayarlar (16 girdi, 40.000 satır, kiracı başına 4); 5 kiracı 1.000'er satır, sonra tek kiracı tek hesapta 4 dönem x 9.998 satır | Kurbanların 5'i de düştü; toplam satır 39.996 |
| Web | `apps/web/node_modules` yok; vitest ve Playwright koşturulmadı. Web bulguları kod okumasına dayanır. |

PoC betiği: `ReportCache` doğrudan, sahte `PeriodReport` (yalnız `result.lines` uzunluğu) ile; veritabanı gerekmez.

## 1. Özet tablo

| No | Önem | Başlık | Yer |
| --- | --- | --- | --- |
| OS-01 | Orta | Saklanmayan (tavanı aşan) sonuçta tek uçuş paylaşmıyor; bekleyenler motoru sırayla yeniden çalıştırır | `services/api/app/services/report_cache.py:150-153, 186-207` |
| OS-02 | Orta | Kiracı başına tavan satır ağırlığını sınırlamıyor; tek kiracı tüm önbelleği boşaltabilir | `report_cache.py:8-9, 156-163` |
| OS-03 | Orta | Veri sürümü sorgusu her istekte (isabet dahil) hesabın 8 tablodaki tüm satırlarını tarar; `updated_at` dizini yok | `report_cache.py:61-85`; `api/v1/profit.py:176`; `migrations/versions/0006_trendyol_data_and_sync.py:110-308` |
| OS-04 | Düşük | `now()` işlem başı zamanı: eşzamanlı iki yazarda güncelleme sürümü değiştirmeyebilir; tutarsız anlık görüntü 90 sn tüm uçlarda paylaşılır | `report_cache.py:61-70`; `services/sync/store.py:76, 120` |
| OS-05 | Düşük | Bellek tavanı süreç başına yaklaşık 160 MB (ölçülen 4 KB/satır x 40.000), işçi sayısıyla çarpılır; süresi dolan girdi temizlenmez | `core/config.py:135-141`; `report_cache.py:140-163` |
| OS-06 | Düşük | YO-01 adalet kuralı başka kiracı beklemiyorken de 429 verir; `process_slots <= tenant_slots` ayarında kiracı ikinci yuvasını hiç kullanamaz | `services/report_gate.py:62-70` |
| OS-07 | Düşük | Önbellekli yolun test boşlukları (conftest kapatıyor; `removed_at`, bekleme sonrası isabet + DB kullanan uç, OS-01, OS-02, YO-01 uçtan uca) | `tests/conftest.py:188-190`; `tests/test_report_cache.py` |
| OS-08 | Düşük | Başlıksız üründe barkod gösterilmiyor (yorum "barkod gösterilir" diyor) | `apps/web/src/lib/profit/orders.ts:45-48`; `components/profit/order-list.tsx:346` |
| OS-09 | Düşük | URL'deki geçersiz `q` sessizce düşüyor; yorum "ekran bunu söyler" diyor ama söylemiyor | `apps/web/src/lib/profit/query.ts:113-125`; `order-list.tsx` `OrderSearch` |
| OS-10 | Bilgi | Bekleme süresiz (`pending.wait()`), eski yorum (`PAGE_SIZE`), iptalde iş parçacığı kapıdan bağımsız sürer | `report_cache.py:197`; `order-list.tsx:55-56`; `services/profit_report.py:70` |

## 2. Ayrıntılar: a6312ff (backend)

### OS-01 (Orta) Saklanmayan sonuçta tek uçuş paylaşmıyor

**Açıklama:** `get_or_compute` bekleyenlere sonucu doğrudan vermez; olay (`asyncio.Event`) set edilince bekleyen yeniden `get` dener. `put`, ağırlığı `max_lines`'ı (40.000) aşan sonucu saklamaz (`report_cache.py:152`). Bu durumda bekleyenlerin `get`'i boş döner, `_inflight` boştur, ilk bekleyen kendi hesabını başlatır, diğerleri onu bekler, ve bu sırayla sürer. Panel açılışında özet, ürünler ve uyarılar aynı anda gelir: önbellek öncesinde bunlar (kiracı başına 2 yuva ile) paralel ya da 429 ile dönüyordu; şimdi büyük satıcıda motor 3 kez ARKA ARKAYA çalışır. O-01'deki "büyük satıcıda istek başına 10 sn" ölçüsüyle üçüncü yanıt yaklaşık 30 sn gelir. Önbellekten en çok yararlanması gereken en büyük satıcılar hem isabet alamaz hem de gecikme katlanır. Aynı desen kapı 429/503 reddinde de çalışır (hata paylaşılmaz, her bekleyen ayrı dener); bu bilinçli bir tercih ve kabul edilebilir.

**PoC:** §0 PoC 1 (3 istek, 3 çalışma, 0,6 sn).

**Düzeltme:** Bekleyenlere sonucu `asyncio.Future` ile verin; saklanıp saklanmaması paylaşımı etkilemesin:

```python
fut = loop.create_future(); self._inflight[key] = fut
try:
    report = await compute(); self.put(key, report); fut.set_result(report); return report, False
except BaseException as exc:
    fut.set_exception(exc) if not paylasilir(exc) else ...  # 429/503 ve iptal paylaşılmaz, bekleyen yeniden dener
    raise
finally:
    del self._inflight[key]
```

Bekleyen tarafta `await asyncio.shield(fut)`; başarıda sonucu alır, paylaşılmayan hatada döngüye döner. Ayrıca 40.000 satırı aşan dönemler için tavanı ölçülen bayta göre yeniden değerlendirin (OS-05).

**Test:** `max_lines` küçük önbellekte aynı anahtarla 3 eşzamanlı istek: motor 1 kez çalışır, 3 yanıt aynı.

### OS-02 (Orta) Kiracı başına tavan satır ağırlığını sınırlamıyor

**Açıklama:** `put` kiracı başına GİRDİ sayısını (4) sınırlar, ama genel satır tavanı (40.000) için en eski girdileri kime ait olduğuna bakmadan atar (`report_cache.py:162-163`). Tek kiracı (tek hesapta 4 farklı dönem, her biri yaklaşık 10.000 satır) tavanın tamamını doldurur ve diğer tüm kiracıların girdisini düşürür. Modül docstring'i (`report_cache.py:8-9`) ve satır 156 yorumu "tek kiracı başkalarının girdisini dışarı itemez" der; bu yalnız girdi sayısı için doğrudur. Test (`test_per_tenant_cap_stops_one_tenant_from_evicting_the_others`) ağırlığı 1 olan sahte raporla yazıldığından durumu yakalamaz. Etki gizlilik değil, adalet ve kapasite: diğer kiracılar ıskaya düşer, motor ve kapı yükü artar (O-01, YO-01'in asıl çözümü zayıflar). Meşru büyük satıcı dönem değiştirerek bunu kendiliğinden yapar; dakikalık 60 istek sınırı engellemez (90 sn'de 4 istek yeter).

**PoC:** §0 PoC 2 (5 kurbandan 0'ı kaldı).

**Düzeltme:** Kiracı başına satır tavanı ekleyin (örn. `tenant_lines = max_lines // 4`); kiracı kendi tavanını aşıyorsa yalnız KENDİ en eski girdilerini düşürsün, tek girdisi `tenant_lines`'ı aşıyorsa saklanmasın (OS-01 düzeltmesiyle tek uçuş yine paylaşır). Docstring ve yorum düzeltilsin.

**Test:** 5 kiracı küçük girdi, tek kiracı 4 büyük girdi: kurbanların hepsi kalır, gürültülü kiracının toplamı `tenant_lines` altında.

### OS-03 (Orta) Veri sürümü sorgusu her istekte hesabın tüm geçmişini tarar

**Açıklama:** `_report` önbellek açıkken her istekte (isabet dahil) `report_data_version` çalıştırır (`profit.py:176`). Sorgu 8 tabloda `max(updated_at)` ve `count(*)` alır; süzgeç yalnız kiracı ve hesaptır, dönem sınırı yoktur (`report_cache.py:71-81`). `updated_at` üzerinde dizin yoktur (0006'daki dizinler `(tenant_id, marketplace_account_id)` ve benzerleri); `max(updated_at)` için hesabın bütün geçmiş satırları yığından okunur. Commit ölçümü (5.000 satırlık tohum, isabet 0,06 sn) üretim geçmişini temsil etmez: birkaç yıllık satıcıda `financial_transactions` ve `order_lines` yüz binlerce satırdır. Bu iş kapının DIŞINDA ve bağlantı tutularak yapılır, yani isabet "ucuz" değildir ve sınırsız eşzamanlılıkla çoğalır (kiracı başına dakikada 60 istek ile sınırlı). Üretim hacminde ölçülmedi (doğrulanmadı).

**Düzeltme (önerilen):** Hesap başına tek sayaç: `marketplace_accounts.report_data_revision bigint`; her motor girdisi yazım işleminde (senkron `upsert_rows`, `upsert_orders`, `removed_at`, imleç, `upsert_costs`) aynı işlem içinde `UPDATE marketplace_accounts SET report_data_revision = report_data_revision + 1 WHERE id = :account`. Okuma tek satırdır; satır kilidi commit sırasını da düzene sokar ve OS-04'ü kapatır. Daha küçük adım: her tabloda `(tenant_id, marketplace_account_id, updated_at)` dizini (`max` için yeterli; `count(*)` yine tarar, bu yüzden sayaç tercih edilmeli).

**Test:** Sürüm okuma sorgusunun planında tam tarama olmadığını (EXPLAIN) ya da sayaç artışını tüm yazım yolları için doğrulayan test.

### OS-04 (Düşük) `now()` işlem başı zamanı ve anlık görüntü tutarsızlığı

**Açıklama:** PostgreSQL `now()` işlemin BAŞLANGIÇ zamanıdır. Aynı hesap ve aynı tabloya eşzamanlı iki yazar varsa (örn. `financial_transactions`'a `settlements` ve `other_financials` senkronları; maliyet içe aktarma ile PUT), geç commit eden ama erken başlamış işlemin GÜNCELLEDİĞİ satırlar (sayı değişmez) en büyük zamanı değiştirmez; önbellek TTL dolana dek (90 sn) eski sonucu verir. Docstring bunu kabul ediyor (`report_cache.py:66-68`); iki senkron kaynağının aynı hesapta paralel koşup koşmadığı doğrulanmadı. Ek olarak S4 denetimindeki READ COMMITTED anlık görüntü notu (besleyici sorgular arasında commit) artık tek isteği değil, 90 sn boyunca özet, ürün, sipariş, uyarı ve detay uçlarının hepsini etkiler.

**Düzeltme:** OS-03'teki hesap sayacı (commit sırasını satır kilidiyle sıralar). Besleyici okumaları `REPEATABLE READ READ ONLY` işlemde yapın (S4 önerisi); sürümü de aynı işlemde okuyun.

### OS-05 (Düşük) Bellek tavanı ve süresi dolan girdiler

**Açıklama:** Kapanış notu saklanan sonucu yaklaşık 4 KB/satır ölçtü; 40.000 satır tavanı süreç başına yaklaşık 160 MB eder ve çok işçili dağıtımda işçi sayısıyla çarpılır (motorun hesaplama tepe belleğine ek). `config.py:135-137` yorumu "yüzlerce MB'a varmaz" diyor; 160 MB çoğu küçük kapsayıcı için büyük bir pay. Süresi dolan girdiler yalnız aynı anahtar okununca ya da LRU baskısında düşer (`report_cache.py:144-146, 162`); veri sürümü değişen eski anahtarlar da tavan dolana dek yer tutar (sınırlı, sızıntı değil).

**Düzeltme:** Tavanı ölçülen bayta göre ve kapsayıcı belleğine oranla belirleyin (örn. 10.000 satır ya da işçi başına bayt tavanı), yorumu düzeltin; `put` başında süresi dolanları süpürün.

### OS-06 (Düşük) YO-01 adalet kuralının yan etkisi

**Açıklama:** Kural (`report_gate.py:62`) "yuvası olan kiracı süreçteki son boş yuvayı alamaz" der ve başka kiracının gerçekten bekleyip beklemediğine bakmaz. Varsayılanlarda (süreç 4, kiracı 2): A ve B birer rapor çalıştırırken A ikinci yuvayı alır, B'nin ikinci isteği hiçbir üçüncü kiracı yokken 429 "Diğer mağazalara da yer bırakmak için" alır. İki mağazalı ya da çok kullanıcılı kiracıda meşru panel açılışları 429 görür (web tek yeniden deneme yapar). `profit_report_process_concurrency=2` ve `tenant_concurrency=2` gibi bir ayarda kiracı tek başınayken bile ikinci yuvasını hiç kullanamaz (`1 + 1 >= 2`). Önbellek isabeti kapıya girmediği için etki ıskalarla sınırlı.

**Düzeltme:** Kuralı yalnız son `Retry-After` penceresinde yuvasız bir kiracı 503 aldıysa uygulayın (son ret zamanı tutulur), ya da ayar doğrulamasında `process_slots >= tenant_slots + 1` şartı koyun. Ret yanıtında tür adı `report-in-progress` yerine ayrı bir tür (örn. `report-fair-share`) istemcinin ayırt etmesini kolaylaştırır.

**Test:** Tek kiracı, süreç 2 / kiracı 2 ayarı: ikinci eşzamanlı rapor 200 (ya da ayar reddi).

### OS-07 (Düşük) Önbellekli yolun test boşlukları

**Açıklama:** `conftest.py` önbelleği bütün testlerde kapatır (`profit_report_cache_ttl_seconds=0`); kapalıyken tek uçuş da yoktur (`report_cache.py:183-184`). Önbellekli yol yalnız `test_report_cache.py` (ve bir perf testi) ile çalışıyor. Bu dosya kiracı ayrımı, 404 önceliği, ayar, maliyet ve senkron geçersizleştirmesi, TTL, kapı atlama ve eşzamanlı tek uçuşu iyi kapsıyor; eksikler:

- `removed_at` işareti ile geçersizleşme (yalnız ekleme ve `UPDATE ... updated_at = now()` test edilmiş).
- Bekleyen istek sonra isabet alıp veritabanına dokunan bir uca (orders, products, product detail) dönüyor: `release()` işlemi kapatır, uç `_restore_context` ile RLS'yi yeniden kurmalı. Kod bunu yapıyor (`profit.py` orders ve products yolları), ama eşzamanlı test yalnız `summary` ve `alerts` ile (DB'ye sonradan dokunmayan uçlar).
- OS-01 (saklanmayan sonuç), OS-02 (ağırlık), YO-01 kuralının HTTP düzeyinde testi.

**Düzeltme:** Yukarıdaki testler; ek olarak rapor API test dosyalarından birinin (örn. `test_report_orders_api.py`) önbellek açık parametresiyle de koşması.

### SU-02, SU-04, SU-05 doğruluğu

- SU-02: `order_dates` artık `ordered_at` için `[lower, upper)` süzgeci kullanıyor; motorun paket seçimi (`profit_feed._orders_in_period`) ile aynı koşul, aynı İstanbul gün sınırları (`period_bounds`). Doğru.
- SU-04: `order_in_period` motorla aynı koşulda (tam eşleşme `order_number`, aynı dönem) çalışır; motor `filter_orders` tam eşleşme yaptığından erken boş yanıt motorun vereceği sonuçla aynıdır. Erken yolda `_guard` (404, hız sınırı) yine önce çalışır. Net kâr sıralamasında tarih sorgusu yalnız sayfadaki siparişler için. Doğru.
- SU-05: `alert_breakdown` motorun `LineComparison` alanlarından türetiliyor; `compared` koşulu motorun fark toplamına alma koşuluyla birebir (`profit/lines.py:65-70`: kargo ve hizmet bedeli yalnız tahmini ve kesin ikisi de varsa); komisyon her zaman dahil. Girenlerin `difference` toplamı motorun `fark`ına eşit (aynı yuvarlanmamış Decimal'ler). `default_desi_used` motorun bilgi alanı. Alanlar isteğe bağlı ve eklemeli (eski istemci kırılmaz). Doğru.

## 3. Ayrıntılar: 1002d5a (web)

### OS-08 (Düşük) Başlıksız üründe barkod gösterilmiyor

**Açıklama:** `orderProductTitle` başlık yoksa "Başlıksız ürün" döner; JSDoc "katalogda yoksa barkod gösterilir" diyor (`orders.ts:45-48`). Kartta barkod hiç basılmıyor (`order-list.tsx:346`); iki başlıksız ürünlü siparişte satırlar ayırt edilemez.

**Düzeltme:** Başlık yoksa "Başlıksız ürün (barkod X)" ya da barkodu ikinci satırda düz metin olarak basın; yorumu kodla eşleyin. Test: başlıksız ürün kartında barkod görünür.

### OS-09 (Düşük) URL'deki geçersiz arama sessizce düşüyor

**Açıklama:** `parseOrderQuery` geçersiz `q`'yu boşaltır; yorum "ekran bunu girdi alanında ayrıca söyler" der (`query.ts:123`), ama `OrderSearch` yalnız `value=''` alır ve uyarı göstermez. Paylaşılan bir bağlantıda (örn. `q=ab cd`) kullanıcı aramanın neden yapılmadığını görmez; tüm siparişleri arama sonucu sanabilir. Güvenlik etkisi yok (istek atılmaz, değer yansıtılmaz).

**Düzeltme:** `parseOrderQuery` geçersizlik bayrağı da döndürsün; `OrderSearch` ilk çizimde ham değeri ve satır içi hatayı göstersin. Ya da yorumu kaldırın.

### Kontrol listesi (web)

| Konu | Sonuç |
| --- | --- |
| API alanları ile şema | `OrderListItem` 17 alanı `OrderListItemOut` ile ad ve null olabilirlik açısından birebir; `OrderTotals`, `OrderDetail`, `AlertBreakdownItem` de eşleşiyor. `breakdown` ve `default_desi_used` isteğe bağlı tanımlı (eski API uyumu). |
| İptal ve null net kâr | İptalde rakam yok, "İptal" (`orderNetView` ilk dal), rozet basılmaz, "tüm satırları iptal" notu. Null net kârda "Hesaplanamadı" ve eksik kalem adları; kesin zararda "En az ₺X zarar" ve "Net kâr hesaplanamadı" etiketi. |
| `known_expenses_profit` | Yalnız net kâr null iken ve "Eksik giderler hariç kâr:" etiketiyle (`order-list.tsx:305`) ya da zarar dalında "En az" biçiminde; etiketsiz gösterim yok. |
| Kalem dökümü dönemi | `OrderLines` listedeki yanıtın `period.start/end` değerleriyle çağrılır (`order-list.tsx:419-433`); dönem yoksa istek atılmaz. Sunucu tarafında cursor parmak izi dönemi içerdiği için gün dönümünde sayfa karışmaz. |
| Arama doğrulaması | İstemci deseni API deseniyle aynı (`^[A-Za-z0-9][A-Za-z0-9._-]*$`, 64); `maxLength`, `trim`, geçersizde istek atılmaz, `role="alert"` ile neden söylenir. Sunucu da aynı deseni ayrıca uygular. |
| XSS | Sipariş no, ürün adı, arama metni JSX metin düğümü olarak basılıyor; `dangerouslySetInnerHTML` yok. |
| Erişilebilirlik | `role="search"` formu, etiketli girdi, `aria-invalid` ve `aria-describedby`, liste rolleri, `aria-expanded`/`aria-controls`, ekran okuyucu için sipariş no eki, `aria-live` sayaç, yükleniyor için `role="status"`. |
| Görüntüleyici rolü | Siparişler ekranında yazma eylemi yok. Uyarılarda `useIsViewer` yalnız etiket seçer, yetki sunucuda; rol alınamazsa düzenleyici etiketi görünür ama sunucu yazmayı reddeder (kabul edilebilir). |
| SU-05 (web) | Desi ipucu yalnız `default_desi_used === true` ve kargo farkı karşılaştırılan kalemler içinde en büyükse; eski API'de koşullu metin. Doğru. |

## 4. Doğru çalışanlar

| Konu | Gözlem |
| --- | --- |
| Kiracılar arası ayrım | `ReportKey` kiracı ve hesap kimliğini içerir (`report_cache.py:88-96`); önbellek yalnız anahtar eşitliğiyle okunur. |
| Yetki önce | Altı rapor ucunun hepsinde `_guard` (hesap kiracıya ait değilse 404, sonra hız sınırı) `_report`'tan önce. Test: B oturumuyla A'nın hesabı, A'nın sonucu önbellekteyken 404 ve motor çalışmadı. |
| Yazım yolları ve `updated_at` | Modellerde `onupdate` yok, ama motor girdisi tablolarına yazan her yol `updated_at = now()` koyuyor: `upsert_rows` ve `upsert_orders` (`store.py:76, 120`), `removed_at` (`store.py:143`), imleç (`store.py:221-224`), maliyet upsert (`product_costs.py:269-276`). Sert silme yok. `products.unit_desi` ve `returns.returned_to_stock` için henüz yazan uç yok (eklenirse `updated_at` yazmalı). |
| Kapsanan tablolar | `profit_feed` okuduğu 7 tablo (orders, order_lines, returns, financial_transactions, cargo_invoice_items, products, product_costs) ve `sync_cursors` sürümde; hepsi kiracı ve hesapla süzülüyor. Ayarlar `settings_revision` ile anahtarda. |
| Sürüm sırası | Sürüm, besleyici okumalardan önce okunuyor; veri arada değişirse sonuç eski anahtarla saklanır ve sonraki istek yeni sürümle ıskalar (güvenli yön). |
| Tek uçuş, hata ve iptal | Lider `finally` içinde `_inflight`'ı siler ve olayı set eder: hata ya da `CancelledError` bekleyenleri kilitlemez; hata paylaşılmaz. Bekleyen beklemeden önce `release()` ile işlemi commit eder (bağlantı havuza döner, "idle in transaction" yok), kapı yuvası tutmaz; sonra hesaplarsa ya da DB'ye dokunursa RLS yeniden kurulur (`_restore_context`). |
| Paylaşılan nesne | `ProfitResult` ve alt sınıflar `frozen=True`; görünümler yeni listeler üretir, önbellekteki sonuç istekler arasında değiştirilmiyor. |
| İsabet ve kapı | İsabet kapıya girmez ve motoru çalıştırmaz; ıska kapıya girer (test). Hız sınırı isabette de sayılır. |
| Kapatılabilirlik | TTL 0 önbelleği ve tek uçuşu tümüyle kapatır (`ge=0`). |
| Son müşteri verisi | Önbellekte yalnız motor sonucu var; müşteri alanı motor girdisinde yok. |

## 5. Öncelikli yapılacaklar

1. OS-01 ve OS-02: tek uçuşu `Future` ile sonucu paylaşacak şekilde değiştirmek ve kiracı başına satır tavanı (küçük kod, büyük satıcı gecikmesi ve diğer kiracıların isabet oranı).
2. OS-03 ve OS-04: hesap başına veri sürümü sayacı (isabet maliyetini sabitler, commit sırası penceresini kapatır); besleyiciyi `REPEATABLE READ READ ONLY` yapmak.
3. OS-05, OS-06: tavanı ölçülen bayta göre ayarlamak, adalet kuralını gerçek bekleyene bağlamak.
4. OS-07: eksik testler. OS-08, OS-09, OS-10: küçük web ve yorum düzeltmeleri.

## 6. OS-10 (Bilgi) notları

- `pending.wait()` süresizdir (`report_cache.py:197`); lider bir DB kilidinde ya da iş parçacığı havuzunda takılırsa bekleyenler de takılır (bağlantı tutmazlar, hız sınırıyla sınırlı). Kodda `statement_timeout` bulunamadı (veritabanı ya da rol düzeyinde olabilir, doğrulanmadı). Öneri: `asyncio.wait_for(..., timeout)` ve süre aşımında 503 + `Retry-After`.
- İstemci bağlantıyı kesip lider iptal edilirse `run_in_threadpool` içindeki motor iş parçacığı sürmeye devam eder, kapı yuvası ise `async with` çıkışında bırakılır (önceden var olan davranış; kapı CPU işini tam sınırlamaz).
- `order-list.tsx:55-56` yorumu "Önbellek gelene dek" diyor; önbellek geldi, sayfa boyutu gerekçesi güncellenmeli.

## 7. Backend kapanışı (OS-01, OS-02, OS-03, OS-04, OS-05, OS-06, OS-07, OS-10)

| No | Durum | Kapanış |
| --- | --- | --- |
| OS-01 | Kapandı | Tek uçuş sonucu `asyncio.Future` ile bekleyenlere doğrudan verir; sonuç saklanmasa da motor 1 kez çalışır. Hata paylaşılmaz (kural değişmedi): hesaplayan 429/503/500/iptal ile biterse bekleyen döngüye girip kendi denemesini yapar (kendi kapı yuvasını ister, kendi hatasını alır). |
| OS-02 | Kapandı | Kiracı başına satır tavanı (`profit_report_cache_tenant_lines`, varsayılan 10.000); kiracı önce kendi en eski girdilerini düşürür; genel tavan dolarsa en çok satır tutan kiracının en eski girdisi düşer (az yer kaplayan korunur); kiracı tavanını aşan tek sonuç saklanmaz. Docstring düzeltildi. |
| OS-03 | Kapandı | Migrasyon 0012: `report_data_revisions` hesap başına sayaç; sekiz motor girdisi tablosunda ERTELENMİŞ kısıt tetikleyicisi commit anında işlem başına bir kez `revision + 1` (`ON CONFLICT DO UPDATE`). Yazım yolu unutulamaz (uygulama, betik, elle SQL). Uygulama rolleri sayacı yazamaz (yalnız `netkar_app` SELECT, FORCE RLS); okuma tek satırdır. |
| OS-04 | Kapandı (OS-03 ile) | Artış ve veri aynı işlemde, commit anında ve satır kilidi altında görünür: `now()` işlem başlangıcı penceresi yok. Besleyicinin `REPEATABLE READ` önerisi bu turda yapılmadı (S4 anlık görüntü notu açık). |
| OS-05 | Kapandı | Yorum bellek gerçeğine göre düzeltildi (yaklaşık 4 KB/satır, süreç başına, işçi sayısıyla çarpılır); süresi dolanlar her `put`'ta süpürülür. Varsayılan tavan değiştirilmedi. |
| OS-06 | Kapandı | Son yuva yalnız GERÇEKTEN bekleyen yuvasız kiracı için ayrılır (süreç doluluğundan 503 alan, `2 x Retry-After` penceresinde, hâlâ yuvasız). Kimse beklemiyorsa kural işlemez; `process_slots <= tenant_slots` ayarı da çalışır. |
| OS-07 | Kapandı | `removed_at`, bekleme sonrası isabet + veritabanına dokunan uçlar, OS-01, OS-02, YO-01 HTTP testleri; `test_report_orders_api.py` önbellek AÇIK koşar. |
| OS-10 | Kapandı | Bekleme `profit_report_cache_wait_seconds` (25 sn) ile sınırlı; aşımda 503 `report-wait-timeout` + `Retry-After`. Gerekçe: bekleyenin kendi hesabını başlatması takılmış hesaplayanın pahalı işini çoğaltır ve kapının CPU korumasını zorlar. |
