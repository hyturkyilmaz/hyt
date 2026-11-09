# NetKâr S4 Güvenlik ve Alan Denetimi: Kâr rapor API'si (9 Kasım 2026)

- Denetlenen sürüm: dal `claude/dazzling-clarke-pfvf32`, commit `5623e31` ("NetKâr S4: kâr rapor API uçları"). Satır numaraları bu commit'e göredir.
- İki şapka: (1) uygulama güvenliği (OWASP ASVS 5.0.0 Seviye 2, OWASP API Security Top 10 2023, `docs/50_guvenlik.md` merge engeli kontrolleri G01, G06, G07, G08, G09, G16); (2) kâr motoru alan uzmanlığı (`docs/12_kar_motoru.md` §1-§11; raporun motor çıktısını doğru ve yanıltmadan sunup sunmadığı).
- Kapsamdaki kod: `app/api/v1/profit.py`, `app/api/v1/profit_schemas.py`, `app/services/profit_views.py`, `app/services/profit_report.py`, `app/api/v1/router.py`; testler `tests/test_report_api.py`, `tests/test_report_units.py`, `tests/test_report_golden_api.py`, `tests/test_report_perf.py`, `tests/report_helpers.py`. Bağlam için okunanlar: `app/api/deps.py`, `app/core/ratelimit.py`, `app/db/session.py`, `app/core/middleware.py`, `app/services/profit_feed.py`, `app/services/product_costs.py` (`account_exists`), `app/profit/{aggregate,lines,fees,costs,shipping,settlement,settings,money,enums}.py`.
- Önce okunan belgeler: `docs/50_guvenlik.md`, `docs/12_kar_motoru.md` (§7-§11 ve ilgili K kuralları), `docs/adr/0005-senkron-ve-depolama.md` §7, önceki denetim `docs/security/denetim_2026-11-08_S3_maliyet.md` (biçim).
- Denetçi kodu yazmadı; kod ve test dosyaları değiştirilmedi, commit yapılmadı. Kavram kanıtı (PoC) testleri repo dışında, oturumun geçici dizininde (`test_poc_s4.py`, `test_poc_s4_perf.py`, `s4_defaults.py`) repo `conftest`'i eklenti olarak yüklenerek gerçek PostgreSQL ile çalıştırıldı; özü Ek A'dadır.

## 0. Yöntem ve test sonuçları

| Adım | Sonuç |
|---|---|
| Kod incelemesi (uçlar, şemalar, görünümler, imleç, dönem çözümü, hız sınırı, motor çağrısı, toplulaştırma) | Tamamlandı |
| S4 testleri (`test_report_*.py`), gerçek PostgreSQL | 250 geçti, 3 atlandı (reklam senaryoları G24-G26, bilinçli) |
| Tüm API test paketi (`uv run pytest -q`) | 1471 geçti, 6 atlandı (reklam, bilinçli), 0 kaldı |
| PoC testleri (`test_poc_s4.py`) | 21/21 geçti (birkaç koşuda); `test_poc_*` geçmesi gözlemin varlığını, `test_ok_*` geçmesi bulgu olmadığını gösterir |
| Ölçüm: 30.000 sipariş satırı, 92 gün (`test_poc_s4_perf.py`) | `summary` 10,0 sn; `products` tepe bellek (tracemalloc) yaklaşık 234 MB |
| Varsayılan ayar etkisi: 41 altın senaryo, altın ayarlarla ve `ProfitSettings()` ile (`s4_defaults.py`) | 39 senaryoda dönem net kârı değişiyor, 4 senaryoda zarar/sıfır kâr kâra dönüyor, 21 senaryoda yanlış `BEKLENMEYEN_KESINTI` (Y-02) |

## 1. Özet tablo (ciddiyete göre)

| No | Ciddiyet | Başlık | Konum | Eşleme | Kanıt |
|---|---|---|---|---|---|
| Y-01 | Yüksek | Bağlantı havuzu "tut ve bekle" kilitlenmesi: 20 eşzamanlı rapor isteği oturum bağlantısını tutarken hız sınırı için ikinci bağlantı ister; havuz 30 sn kilitlenir, TÜM kiracılar için API durur, istekler 500 alır ve hız sınırına SAYILMAZ (sınırsız tekrar) | `app/api/v1/profit.py:126-133`; `app/core/ratelimit.py:42-44`; `app/api/deps.py:120-137`; `app/db/session.py:11` | API4:2023; ASVS 15.2.2; G07 | PoC |
| Y-02 | Yüksek (alan) | Kâr ayarları her zaman motor varsayılanı: tahmini satırlarda gönderi kargo 0 (`eksik`) ve platform hizmet bedeli 0 ("tahmini" etiketli, uyarısız); net kâr sistematik şişkin, zarar kâr görünür, ekstreli satırlarda yanlış `BEKLENMEYEN_KESINTI`; özet ve ürün listesinde görünür bayrak yok | `app/api/v1/profit.py:136-141`; `app/profit/settings.py:75-79`; `app/profit/fees.py:103-116`; `app/profit/shipping.py:111-114`; `app/profit/lines.py:54-68` | Alan doğruluğu (K08, K13, K23; docs/12 §11.1) | PoC + ölçüm |
| O-01 | Orta | Motor maliyeti sınırsız eşzamanlılıkla çarpılıyor: önbellek yok, her sayfa ve her uç motoru yeniden çalıştırır; motor süresince bağlantı "idle in transaction"; büyük satıcıda istek başına 10 sn ve yüzlerce MB | `app/services/profit_report.py:59-62`; `app/api/v1/profit.py:144-154, 210-219`; `app/core/config.py:124` | API4:2023; ASVS 15.2.2 | PoC + ölçüm |
| O-02 | Orta (alan) | Kısmi dönemde marj ve gider alanları farklı tabanlarda: `net_kar_marji_yuzde` pay olarak yalnız maliyetli satırları, payda olarak TÜM satırları alır; dönem gider alanları toplanınca net kârı vermez | `app/profit/aggregate.py:131, 150`; `app/api/v1/profit_schemas.py:229-234`; `app/api/v1/profit.py:183-189` | Alan doğruluğu (K25, §7.3-§7.4) | PoC |
| O-03 | Orta (alan) | `basis` yalnız satır durumundan türetiliyor: `settled` etiketli üründe kargo `eksik`, hizmet bedeli `tahmini` olabilir | `app/services/profit_views.py:162-169, 188-207`; `app/api/v1/profit_schemas.py:303-306` | Alan doğruluğu (K22, §5 "kaynaklar") | PoC |
| O-04 | Orta (alan) | İade kaydı (claim) gelmemiş tam iadede ürün maliyeti tamamen gider kalıyor; `adet_iade=0`, `ZARAR` uyarısı; API bu geçici durumu ayırt etmiyor | `app/profit/costs.py:18-32, 48-50`; `app/services/profit_views.py:451-475` | Alan doğruluğu (K10) | PoC |
| D-01 | Düşük | Sipariş ucunda dönem verilmezse siparişin ilk ve son paket günü kullanılıyor; 92 gün sınırı uygulanmıyor (PoC: 274 gün) | `app/api/v1/profit.py:310-314`; `app/services/profit_views.py:377-394` | API4:2023 | PoC |
| D-02 | Düşük (alan) | `filter=loss` maliyeti eksik ama maliyet hariç katkısı negatif (kesin zarar) ürünleri kaçırıyor | `app/services/profit_views.py:210-215` | Alan doğruluğu (K16, §7.4) | Kod |
| D-03 | Düşük | Besleyici tek işlemde birden çok SELECT'i READ COMMITTED ile yapar; eşzamanlı senkron arada commit ederse tutarsız anlık görüntü | `app/services/profit_feed.py:259-382`; `app/api/deps.py:39-45` | ASVS 15.4 | Kod (doğrulanmadı) |
| B-01 | Bilgi | İmleç imzasız, kiracıya/hesaba bağlı değil, sıralama değerini (net kâr) URL'de düz taşıyor; içerik doğrulaması motordan SONRA | `app/services/profit_views.py:105-127, 250-264`; `app/api/v1/profit.py:157-164` | ASVS (veri bütünlüğü), API8 | PoC |
| B-02 | Bilgi (alan) | Yalnız iptal satırı olan ürün listede `net_profit "0.00"` ile, iptal sipariş `net_profit "0.00"` ile görünüyor | `app/profit/aggregate.py:44-48`; `app/services/profit_views.py:365-374` | Alan (K26), UX | PoC |
| B-03 | Bilgi | Hız sınırı yalnız kiracı bazında; bir görüntüleyici kiracının dakikalık bütçesini tüketebilir; tek pano görünümü 3 motor çalıştırması | `app/api/v1/profit.py:132-133` | G07; API4 | Kod |
| B-04 | Bilgi | Katalog başlıkları ve kullanıcı tanımlı gider adları JSON'da yansıyor (panel metin olarak basmalı) | `app/api/v1/profit.py:229`; `app/api/v1/profit_schemas.py:118-122` | ASVS 1.2 (istemci tarafı) | Kod |
| B-05 | Bilgi | Keyset sayfalama her sayfada yeniden hesaplanan sonuç üzerinde; arada senkron veya gece yarısı (`range` önayarı) sayfa atlatır/imleci geçersiz kılar | `app/api/v1/profit.py:211`; `app/services/profit_views.py:130-138` | Tutarlılık, UX | Kod |

Sayım: Kritik 0, Yüksek 2, Orta 4, Düşük 3, Bilgi 5 (toplam 14). Yüksek ve Orta bulguların dördü (Y-02, O-02, O-03, O-04) alan doğruluğu bulgusudur.

## 2. Ayrıntılar

### Y-01 (Yüksek) Bağlantı havuzu "tut ve bekle" kilitlenmesi

**Konum:** `app/api/v1/profit.py:126-133` (`_guard`: önce `costs.account_exists(db, ...)`, sonra `limiter.hit(...)`), `app/core/ratelimit.py:42-44` (`async with self._engine.connect()`: AYNI motor havuzundan ikinci bağlantı), `app/api/deps.py:120-137` (`get_auth_context` oturum işlemini açar, bağlantı istek boyunca tutulur), `app/db/session.py:11` (`pool_size=10, max_overflow=10`, varsayılan `pool_timeout=30`).

**Açıklama:** Her rapor isteği önce oturum (AsyncSession) bağlantısını alır (oturum araması, RLS bağlamı, hesap kontrolü) ve işlem açık kaldığı için bu bağlantıyı bırakmaz. Ardından `RateLimiter.hit` aynı havuzdan AUTOCOMMIT için ikinci bir bağlantı ister. 20 istek aynı anda gelirse 20 oturum bağlantısı havuzu doldurur, her istek ikinci bağlantıyı bekler; hiçbiri ilerleyemez. 30 sn sonra SQLAlchemy `TimeoutError` verir, istekler genel 500 alır. PoC (Ek A.1):

| Eşzamanlı istek (gerçek, hızlı motor; küçük veri) | Süre | Sonuç |
|---|---|---|
| 20 | 30,2 sn | 20 x 500 |
| 30 | 30,3 sn | 30 x 500 |
| 45 | 30,4 sn | 1 x 200, 44 x 500 |

Bu sürede havuz dolu olduğu için başka kiracıların DB'ye dokunan HER isteği (giriş dahil) bekler; `/v1/health/ready` 28,9 sn sürdü. Kilitlenen istekler `hit` içinde düştüğü için sayaç ARTMAZ (PoC: 20 x 500 sonrası `rate_limits` toplamı 0): dakikada 60 sınırı saldırıyı durdurmaz, saldırgan her 30 sn'de bir 20'li dalga gönderip hizmeti sürekli kesebilir. Motor yavaşsa (O-01) daha az eşzamanlı istek yeter. Kalıp sisteme yayılmıştır: aynı PoC maliyet şablonu ucunda (`/product-costs/template.csv`) da 20 x 500 verdi; kodda aynı sıra (oturum sorgusu, sonra `limiter.hit`) maliyet PUT ve içe aktarma (`product_costs.py:140, 261`), pazaryeri bağlama (`marketplace_accounts.py:92-100`) ve TOTP (`auth.py:386`) uçlarında da var (bu uçlar ayrıca test edilmedi; doğrulanmadı).

**İstismar senaryosu:** Bağlı (etkin) Trendyol hesabı olan herhangi bir kiracının herhangi bir kullanıcısı, görüntüleyici rolü dahil, `GET .../profit/summary` isteğini 20 paralel bağlantıyla gönderir (tarayıcı dışı istemci, tek komut). Hesabın verisi olması gerekmez. API tüm kiracılar için 30 sn durur; tekrarlandıkça sürekli hizmet dışı kalır. Önkoşul kimlik doğrulama ve bağlı hesaptır (S3 Y-01 ile aynı önkoşul), etki kiracılar arası tam kesinti ve sınırsız tekrar olduğu için ciddiyet Yüksek'tir. Yoğun bir mağazada birkaç kullanıcının sekmeleri ve sayfalamasıyla kazara da tetiklenebilir.

**Düzeltme önerisi:**
1. Hız sınırı sayacını oturum havuzundan ayırın: `RateLimiter` için ayrı, küçük bir motor (örn. `pool_size=5, max_overflow=0, pool_timeout=2`); zaman aşımında beklemeden 503 + `Retry-After` (kapalı tarafta başarısızlık). Tek düzeltme tüm uçları kapsar.
2. Rapor uçları için süreç başına beklemeyen eşzamanlılık kapısı (S3 `ImportGate` gibi): örn. süreç başına en fazla 4 rapor, kiracı başına en fazla 2; doluysa 429/503. Kapı DB'ye dokunmadan ÖNCE (oturum aramasından hemen sonra) alınmalı.
3. Derinlemesine savunma: `pool_timeout` 5 sn civarına inmeli; Starlette/uvicorn düzeyinde eşzamanlı istek tavanı (`--limit-concurrency`).
4. O-01'deki bağlantı bırakma düzeltmesi (motor süresince bağlantı tutulmasın).

**Test önerisi:** 30 eşzamanlı `summary` isteği (Barrier ile aynı anda): hiçbir yanıt 500 olmamalı (200, 429 veya 503), toplam süre 5 sn altında kalmalı, aynı anda `/v1/health/ready` 1 sn altında yanıt vermeli; `rate_limits` sayacı reddedilen istekleri de saymalı. Aynı test şablon ucu için de.

### Y-02 (Yüksek, alan) Varsayılan ayarlarla kargo ve platform hizmet bedeli kâra girmiyor; sunum bunu gizliyor

**Konum:** `app/api/v1/profit.py:136-141` (`profit_settings_for` her zaman `ProfitSettings()`), `app/profit/settings.py:75-79` (hizmet bedeli tahmini 0, kargo tarifesi boş), `app/profit/fees.py:103-116` (tahmin 0 iken kaynak `Source.ESTIMATED`, uyarı yok), `app/profit/shipping.py:111-114` (tarifesiz satır `eksik` + `KARGO_TARIFESI_EKSIK`, tutar 0), `app/profit/lines.py:54-68` (K23 karşılaştırması tahmini 0'ı gerçek tahmin sayar), `app/api/v1/profit_schemas.py:215-238` (dönem toplamında eksik kalem bayrağı yok).

**Açıklama:** Kiracı ayar tablosu olmadığı için üretimdeki her rapor motor varsayılanlarıyla hesaplanır (ajan bu riski `KARGO_TARIFESI_EKSIK` olarak bildirmiş; bağımsız değerlendirmem daha ağırdır):

1. **Kargo:** Kargo faturası gelmemiş her satırda gönderi kargo 0 ve kaynak `eksik`. Kargo, belgeye göre her siparişte en büyük ikinci Trendyol kesintisidir (docs/12 §9 madde 2).
2. **Platform hizmet bedeli:** Faturası dağıtılmamış her siparişte 0, kaynak "tahmini", HİÇBİR uyarı yok. Bu, docs/12 §11.1 "ayar yoksa kalem `eksik` kaynaklı olur ya da 0 kalır ve uyarı verir" ilkesine aykırıdır.
3. **Yanlış alarm:** K23 karşılaştırması kesin kargo faturası geldiğinde tahmini kargoyu (0) gerçek tahmin sayar; fark (örn. 45,00) eşiği aşar ve `BEKLENMEYEN_KESINTI` üretir. Hizmet bedeli faturası geldiğinde de aynı.
4. **Görünürlük:** `KARGO_TARIFESI_EKSIK` yalnız satır uyarısıdır; `summary.totals.uyarilar` içinde yoktur (PoC: yalnız `MALIYET_EKSIK_SATIRLAR_VAR`), ürün listesinde de bayrak yoktur. Panel özeti ve listeyi gösterdiğinde kullanıcı eksik gideri göremez.

**Ölçüm (Ek A.4):** 41 altın senaryo, altın testlerin ayarlarıyla ve üretimdeki `ProfitSettings()` ile çalıştırıldı:

| Etki | Senaryo sayısı | Örnek |
|---|---|---|
| Dönem net kârı değişiyor | 39 | G01 119,09 -> 174,09 (+%46) |
| Zarar veya sıfır kâr, kâra dönüyor (`ZARAR` uyarısı kayboluyor) | 4 | G32 -35,06 -> +14,94; G33 -19,25 -> +20,75; G19 -7,65 -> +2,35; G31 0,00 -> 50,00 |
| Altın sonuçta olmayan `BEKLENMEYEN_KESINTI` | 21 | G02, G14, G16-G23, G28, G35, G40, G41 ... |

**Senaryo:** Satıcı panelde "en kârlı ürünler" listesine bakar; tahmini satırların kargo ve hizmet bedeli düşülmediği için zararına sattığı ürün kârlı görünür, fiyatı düşürme veya reklam artırma kararı yanlış veriye dayanır. Ekstreler geldikçe her siparişte "beklenmeyen kesinti" uyarısı çıkar; uyarılar gürültüye dönüşür ve gerçek kesinti fark edilmez. Ürünün ana vaadi (doğru net kâr) bozulur.

**Düzeltme önerisi:**
1. Kısa vade (API, yeni iş kuralı gerektirmez): `summary` ve ürün satırlarına veri kalitesi bloğu ekleyin: kaynağı `eksik` olan kalem başına satır sayısı (`kargo_gonderi`, `urun_maliyeti`), kaynağı "tahmini" olup ayarı tanımsız kalemler (hizmet bedeli) ve `kargo_tarifesi_tanimli: false`, `hizmet_bedeli_tahmini_tanimli: false` bayrakları. Dönem uyarılarına satır uyarılarından türetilmiş özet (örn. "N satırda kargo eksik") ekleyin; bunu yeni kural değil, sayım olarak sunun.
2. Motor (önce docs/12, sonra betik ve altın test): hizmet bedeli tahmini tanımsızsa kaynak `eksik` ve uyarı (örn. `HIZMET_BEDELI_TAHMINI_YOK`); K23 karşılaştırmasında tahmini kaynağı `eksik` olan kalem karşılaştırmaya girmesin (yanlış `BEKLENMEYEN_KESINTI` biter).
3. Ürün: kiracı ayar tablosu (kargo tarifesi, hizmet bedeli) gelene kadar panelde net kâr ve marj "kargo ve hizmet bedeli hariç" etiketiyle gösterilmeli veya kurulum sihirbazı tarifeyi zorunlu kılmalı. Bu düzeltme olmadan rapor uçları canlıda kullanıcıya açılmamalı (yayın engeli).

**Test önerisi:** Varsayılan ayarlarla tarifesiz bir tahmini satır ve kargo faturası gelmiş bir ekstreli satır: (a) `summary` veri kalitesi bloğunda kargo eksik sayısı 1, hizmet bedeli ayarı tanımsız bayrağı doğru; (b) ekstreli satırda `BEKLENMEYEN_KESINTI` YOK (motor düzeltmesinden sonra); (c) altın senaryolar `ProfitSettings()` ile çalıştırıldığında hiçbir senaryoda altın sonuçta olmayan `BEKLENMEYEN_KESINTI` çıkmamalı.

### O-01 (Orta) Motor maliyeti sınırsız eşzamanlılıkla çarpılıyor

**Konum:** `app/services/profit_report.py:59-62` (besleyici sorguları ve `run_in_threadpool(calculate_profit, ...)` oturum işlemi açıkken), `app/api/v1/profit.py:144-154` (`_report`), `210-219` (liste: her sayfa yeni motor çalıştırması, ardından başlık sorgusu aynı işlemde), `app/core/config.py:124` (kiracı başına dakikada 60).

**Açıklama ve ölçüm:**
- 30.000 satır, 92 gün: `summary` 10,0 sn; `products` tepe bellek yaklaşık 234 MB (tracemalloc, Ek A.5). Kiracı başına dakikada 60 istek, tek kiracıya dakikada yaklaşık 600 CPU saniyesi ve eşzamanlı 20 istekte birkaç GB bellek izni verir. Önbellek yok: pano açılışı (özet + ürünler + uyarılar) 3 çalıştırma, her sayfa değişimi 1 çalıştırma.
- Motor çalışırken oturum bağlantısı "idle in transaction" kalır (PoC: 1 istekte 1, 45 istekte 20 bağlantı). S3 O-01 ile aynı kalıp; Y-01 ile birleşince havuz daha az istekle tükenir.
- `run_in_threadpool` anyio'nun paylaşılan 40 belirteçli havuzunu kullanır; FastAPI senkron bağımlılıkları (`get_settings_dep`, `get_rate_limiter`, `period_dep` senkron `def`) de aynı havuzda çalışır. 40 uzun motor çalıştırması tüm uçların senkron bağımlılıklarını bekletir. PoC'de Y-01 kilitlenmesi önce devreye girdiği için bu etki ölçülemedi (doğrulanmadı; mekanizma FastAPI'nin bilinen davranışıdır). Motor saf Python ve GIL'i tutar; tek süreçte olay döngüsü yavaşlar.

**Senaryo:** Büyük bir satıcının birkaç kullanıcısı aynı anda 92 günlük raporu sayfalar; ya da kötü niyetli büyük satıcı dakikada 60 isteği paralel gönderir. Süreç CPU ve bellek açısından doyar, diğer kiracıların yanıtları saniyelerce gecikir.

**Düzeltme önerisi:**
1. Y-01 madde 2'deki beklemeyen eşzamanlılık kapısı.
2. Bağlantı bırakma: besleyici sorguları ve başlık sorgusu (başlıklar motor öncesi tüm barkodlar için alınabilir) bittikten sonra `await db.commit()` ile bağlantıyı havuza iade edin, motoru bağlantısız çalıştırın; sonrasında DB gerekiyorsa `set_rls_context`'i yeniden çağırın.
3. Kısa ömürlü önbellek: anahtar (kiracı, hesap, start, end, ayar sürümü, hesabın son senkron zamanı veya veri sürüm sayacı), TTL 60-120 sn, süreç içi LRU (bellek tavanlı). Sayfalama ve pano uçları aynı sonucu paylaşır; senkron sonrası anahtar değişir. Önbellek anahtarında kiracı mutlaka yer almalı (kiracılar arası sızıntı olmasın).
4. Uzun vade: dönem sonuçlarının günlük özetlerle önceden hesaplanması veya motorun ayrı süreç havuzunda (`ProcessPoolExecutor`, bellek ve süre sınırlı) çalışması.
5. Hız sınırını maliyete göre ağırlıklandırmak (satır sayısı x gün) veya kiracı başına eşzamanlı 1-2 rapor.

**Test önerisi:** Motor bir olayla bekletilirken `pg_stat_activity`'de `netkar_app` için `idle in transaction` satırı OLMAMALI; aynı (dönem, sıralama) için ardışık iki sayfa motoru bir kez çalıştırmalı (önbellek), senkron sonrası yeniden çalıştırmalı; kapı doluyken ek istek beklemeden 429/503 almalı.

### O-02 (Orta, alan) Kısmi dönemde marj ve gider alanları farklı tabanlarda

**Konum:** `app/profit/aggregate.py:131` (`urun_maliyeti` yalnız maliyetli satırlar), `132-138` (diğer giderler tüm satırlar), `150` (`percent_of(donem_net_kar, net_satis_TUM_satirlar)`), `app/api/v1/profit_schemas.py:229-234`, `app/api/v1/profit.py:183-189`.

**Açıklama:** Motor belgeye uygun davranıyor (§7.3: dönem net kârı maliyeti olan satırların toplamı); sorun API'nin bunu süzmeden sunmasıdır. PoC (`seed_basic`, Ek A.2): `net_satis_kdv_haric 183,33` (tüm satırlar), `donem_net_kar -10,00` (yalnız B1 satırları), `net_kar_kismi true`, `net_kar_marji_yuzde -5,45`. B1 satırlarının kendi net satışıyla marj -10,00 olurdu; gösterilen marj pay ve paydası farklı satır kümelerinden gelir ve kısmi olmayan bir sayı gibi görünür. Ayrıca panel "toplam gider" çizmek için alanları toplarsa `183,33 - (100,00 + 18,33 + 0 ...) = 65,00` bulur; `donem_net_kar` ise -10,00'dır. Şelale grafik veya "satış - gider = kâr" gösterimi kısmi dönemde tutarsız olur. Ajanın bildirdiği "kısmi marj" riski doğrulandı.

**Düzeltme önerisi:** API: `net_kar_kismi` doğruyken `net_kar_marji_yuzde` null dönsün (veya ayrı `net_kar_marji_kapsami: "kismi"` alanı). Motor (önce docs/12 §7.3-§7.4): `net_satis_maliyetli_satirlar` ve `toplam_gider_maliyetli_satirlar` alanları; kısmi marj bu tabanla ve açıkça "maliyeti girilmiş satırlar" etiketiyle hesaplansın. Panel: kısmi dönemde gider alanlarından türetilmiş toplam gösterilmesin.

**Test önerisi:** Bir maliyetli, bir maliyetsiz satırlı dönemde `net_kar_marji_yuzde` null (veya kapsam alanı "kismi"); motor alanı eklendiğinde marj = `donem_net_kar / net_satis_maliyetli_satirlar`.

### O-03 (Orta, alan) `basis` etiketi kalem kaynaklarını yok sayıyor

**Konum:** `app/services/profit_views.py:162-169` (`_basis`), `188-207`, `app/api/v1/profit_schemas.py:303-306`.

**Açıklama:** `basis=settled` "tüm aktif satırlar ekstreli" demektir; ancak durum `settled` yalnız satış ve komisyonun ekstreden geldiğini gösterir (docs/12 §5: "her kalem kendi kaynağı gelince kesin olur"). PoC: B2 ürünü `basis: settled` iken satırın `kaynaklar`'ı `kargo_gonderi: eksik`, `platform_hizmet_bedeli: tahmini`. Panel `settled`'ı "kesin" rozetiyle gösterirse tahmini ve eksik giderli kâr kesin sanılır. Ajanın "tahmini/kesin etiketlerinin taşınması" işi satır düzeyinde doğrudur (`durum`, `kaynaklar` birebir); ürün ve dönem düzeyinde özet etiket yanıltıcıdır.

**Düzeltme önerisi:** `basis`'i yeniden adlandırın (`statement_basis`: "ekstreli satır oranı") ve ayrı bir `certainty` alanı türetin: tüm satırların tüm kalemleri `kesin`, `kesin_dagitim`, `kullanici` veya `yok` ise `final`; herhangi biri `eksik` ise `incomplete`; aksi halde `estimated`. Kalem başına `eksik`/`tahmini` satır sayıları da verilebilir (Y-02 madde 1 ile aynı blok).

**Test önerisi:** Ekstreli ama kargo faturası gelmemiş satırlı ürün `certainty != final`; tüm kalemleri kesin ürün `final`.

### O-04 (Orta, alan) İade kaydı gelmemiş tam iadede maliyet tamamen gider

**Konum:** `app/profit/costs.py:18-32` (iade adedi yalnız `getClaims` kabul kalemlerinden), `48-50` (`billable = adet - iade_stok`), `app/services/profit_views.py:451-475` (`ZARAR` uyarısı aynen aktarılır).

**Açıklama:** K10'a göre maliyetin düşmesi için iade kalemi (claim) gerekir; ekstrede `Return` gelmiş ama claim henüz senkronlanmamış (veya hiç gelmeyen) satırda gelir sıfırlanır, maliyet tamamen gider kalır. PoC (sipariş 1003): `durum adjusted`, `adet 1`, `adet_iade 0`, `iade_kdv_haric 25,00`, `net_satis 0,00`, `urun_maliyeti 50,00`, `net_kar -50,00`, `ZARAR`. İhtiyat ilkesi olarak savunulabilir; ancak claim gecikmesi boyunca stoğa dönen ürün "zarar" görünür ve kullanıcı bunu ayırt edemez. Dikkat: `ManualRefund` (K11, kısmi iade) satırında ürün müşteride kalır ve maliyetin düşmemesi DOĞRUDUR; ayırım satır çıktısından yapılamıyor. Ajanın "claim'siz iade" riski doğrulandı.

**Düzeltme önerisi:** Motor (önce docs/12 K10): `Return` satırı olup kabul edilmiş claim kalemi olmayan satıra `IADE_KALEMI_BEKLENIYOR` uyarısı (veya `kaynaklar.urun_maliyeti` için ayrı bir değer); API bunu satırda, üründe ve uyarılarda taşır. Panel: "İade kaydı bekleniyor; maliyet geçici olarak tamamen gider sayıldı".

**Test önerisi:** `Return` var, claim yok: uyarı var, `ZARAR` ile birlikte gösterilir; claim (stoğa döndü) gelince uyarı kalkar ve maliyet düşer; `ManualRefund` satırında uyarı yok.

### D-01 (Düşük) Sipariş ucunda dönem tavanı yok

**Konum:** `app/api/v1/profit.py:310-314` (`used = period or Period(*days)`), `app/services/profit_views.py:377-394`.

**Açıklama:** Dönem verilmezse siparişin paketlerinin en erken ve en geç günü kullanılır ve `MAX_PERIOD_DAYS` denetlenmez. PoC: aynı sipariş numaralı iki paket (2026-01-05 ve 2026-10-05) 274 günlük motor çalıştırması üretti. `ordered_at` Trendyol'dan gelir, kullanıcı doğrudan seçemez; gerçekte bölünmüş paketlerin sipariş tarihi aynı olmalıdır (doğrulanmadı). Büyük satıcıda O-01 maliyetini 3 katına çıkarabilir.

**Düzeltme önerisi:** Varsayılan dönemi `[ilk gün, ilk gün + 91]` ile kırpmak veya aralık 92 günü aşarsa 422 (kullanıcı start/end vermeli). **Test önerisi:** 93 gün aralıklı paketli siparişte dönemsiz istek 422 ya da `period.days <= 92`.

### D-02 (Düşük, alan) Zarar süzgeci kesin zararları kaçırıyor

**Konum:** `app/services/profit_views.py:210-215`.

**Açıklama:** `filter=loss` yalnız `net_kar < 0` olan ürünleri döndürür. Maliyeti girilmemiş üründe `maliyet_haric_katki < 0` ise ürün maliyeti negatif olamayacağı için net kâr kesinlikle negatiftir (§7.4). Bu ürünler "zarar" listesinde de `ZARAR` uyarısında da görünmez. **Düzeltme:** süzgeç `net_kar < 0 OR (net_kar is null AND maliyet_haric_katki < 0)`; ayrı işaret `loss_certain_without_cost`. **Test:** maliyetsiz, katkısı negatif ürün `loss` süzgecinde.

### D-03 (Düşük) READ COMMITTED altında çok sorgulu besleme

**Konum:** `app/services/profit_feed.py:259-382` (siparişler, satırlar, ürünler, maliyetler, ekstre, diğer finansallar, kargo, iade ayrı SELECT'ler), `app/api/deps.py:39-45`.

**Açıklama:** Her SELECT kendi anlık görüntüsünü görür; senkron işçisi arada commit ederse sipariş listesi ile ekstre veya kargo sorguları farklı zamanı yansıtır. Motor eşleşmeyen ekstre satırını yok saydığı için (`settlement.py`) 500 beklenmez; sonuç kısa süreli olarak tutarsız (örn. ekstresi gelmiş ama satırı listede olmayan sipariş) olabilir. Ajanın bildirdiği risk; bu denetimde yeniden üretilmedi (doğrulanmadı). **Düzeltme:** rapor işlemi `REPEATABLE READ READ ONLY` ile açılsın (O-01 madde 2'deki commit sonrası yeni işlemin başında `SET TRANSACTION ...`, ardından `set_rls_context`). **Test:** iki sorgu arasına (monkeypatch) senkron yazımı enjekte edip sonucun ilk anlık görüntüyle aynı kaldığını doğrulamak.

### B-01 (Bilgi) İmleç imzasız ve taşınabilir

**Konum:** `app/services/profit_views.py:105-127` (base64 JSON, HMAC yok), `250-264` (değer ayrıştırma motordan sonra), `app/api/v1/profit.py:157-164, 211-213`.

**Açıklama:** PoC: imleç `{"f":"products|net_profit|desc|all|2026-10-01|2026-10-31","k":["0","-10.00","8681000000011"]}`; başka kiracı aynı imleci kabul ediyor (200); uydurulmuş `1E+999999` değeri kabul ediliyor (200). İmleç yalnız konum belirler ve veri her zaman isteği yapan kiracının sonucundan seçilir; bu yüzden IDOR veya veri sızıntısı yok. Kalan etkiler: (1) son öğenin net kârı ve barkodu URL'de düz metin (vekil erişim logları, tarayıcı geçmişi; uygulama logu yalnız yolu yazar, olumlu); (2) parmak izi doğru, içeriği bozuk imleç motoru bir kez çalıştırdıktan sonra 422 alır (sayılır, düşük maliyet). **Öneri:** imleç `HMAC(master_key, "report-cursor", kiracı|hesap|parmak izi|anahtar)` ile imzalansın, içerik motordan önce ayrıştırılsın. **Test:** başka kiracının imleci ve imzası bozulmuş imleç motor çalışmadan 422.

### B-02 (Bilgi, alan) İptal satırlı ürün ve sipariş "0,00 kâr" ile görünüyor

**Konum:** `app/profit/aggregate.py:44-48` (satırı olan her barkod ürün listesine girer), `app/services/profit_views.py:365-374`.

**Açıklama:** PoC: yalnız iptal satırı olan barkod listede `line_count 0`, `net_profit "0.00"`, `cost_missing false` ile; iptal sipariş `totals.net_profit "0.00"`. K26 gereği toplamlara girmez (doğru), ama "0,00 TL kâr" ile "hiç satış yok/iptal" ayırt edilmez ve `total_count` şişer. **Öneri:** listede `line_count == 0` ürünler varsayılan olarak gizlensin veya `basis: none` panelde "Satış yok (iptal)" olarak gösterilsin; sipariş toplamında tüm satırlar iptalse `net_profit: null` ve `cancelled: true`.

### B-03 (Bilgi) Hız sınırı boyutları

**Konum:** `app/api/v1/profit.py:132-133`.

**Açıklama:** G07 "IP + kullanıcı + kiracı" ister; yalnız kiracı sayacı var. Bir görüntüleyici (veya ele geçirilmiş oturum) kiracının dakikalık 60 isteğini tüketip diğer kullanıcılara 429 yaşatabilir. Tek pano açılışı 3 istek, yani dakikada en çok 20 pano görünümü. Dönem doğrulama hatası (422) ve yabancı hesap (404) sayılmıyor; bunlar motor çalıştırmadığı için kabul edilebilir (test `test_rate_limit_is_per_tenant_per_minute_and_shared_across_report_endpoints` bunu belgeliyor). Asıl sayılmayan pahalı yol Y-01'dir. **Öneri:** kullanıcı başına ek sayaç; önbellek (O-01) gelince sınır pano kullanımına göre yeniden ayarlanmalı.

### B-04 (Bilgi) Yansıyan metinler

**Konum:** `app/api/v1/profit.py:229` (Trendyol katalog başlığı), `app/api/v1/profit_schemas.py:118-130` (kullanıcı tanımlı değişken gider adı, reklam kayıt kimliği).

**Açıklama:** Yanıt yalnız JSON ve `Cache-Control: no-store`; sunucu tarafında risk yok. Başlık satıcının Trendyol panelinden, gider adı kullanıcıdan gelir. Panel bu alanları metin olarak (innerHTML değil) basmalı; ileride CSV/XLSX dışa aktarma eklenirse S3 D-02 formül kaçışı uygulanmalı.

### B-05 (Bilgi) Yeniden hesaplanan sonuç üzerinde keyset sayfalama

**Konum:** `app/api/v1/profit.py:211`, `app/services/profit_views.py:130-138`.

**Açıklama:** Her sayfa motoru yeniden çalıştırır; iki sayfa arasında senkron değerleri değiştirirse ürün sıralamada yer değiştirip atlanabilir veya iki kez görünebilir. `range=today|7d|30d` çözülmüş tarihlerle parmak izine girdiği için gece yarısını geçen sayfalama 422 alır. O-01'deki önbellek (aynı anahtar, aynı sonuç) ikisini de büyük ölçüde giderir; panel 422 `cursor_invalid` aldığında listeyi baştan yüklemeli.

## 3. Doğrulanan kontroller (bulgu yok)

| Kontrol | Sonuç ve kanıt |
|---|---|
| IDOR/BOLA (G01, API1) | Her uçta `get_auth_context` RLS bağlamını kurar, ardından `account_exists(tenant_id, account_id)`; yoksa 404 ve hız sınırı sayılmaz. `barcode_known`, `order_days`, `product_titles` ve besleyicinin tüm sorguları açık `tenant_id` + `marketplace_account_id` süzgeci taşır (çift kilit). PoC `test_ok_cross_account_same_tenant_barcode_and_order_404`: aynı kiracının başka hesabında barkod ve sipariş 404. Repo testleri `test_other_tenants_account_is_404_and_leaks_nothing`, `test_each_tenant_sees_only_its_own_data_through_its_own_account` geçti. |
| Görüntüleyici erişimi | Tüm uçlar salt okuma `GET`; `require_role(OWNER, ADMIN, VIEWER)` (ADR-0005 §7 "tüm roller"). Görüntüleyicinin maliyet ve kâr görmesi ürün kararıdır; yazma yolu yok. |
| SQL enjeksiyonu | Tüm sorgular ORM ve bağlı parametre; barkod `[A-Za-z0-9][A-Za-z0-9._-]{0,199}`, sipariş no `[A-Za-z0-9][A-Za-z0-9._-]*` (en çok 64); ham SQL yok. |
| Hata yanıtları (G08) ve girdi yansıması | PoC 6 durum (`code=<script>MARKER</script>`, `sort`, `limit`, `range`, geçersiz takvim günü, bozuk tarih): 422 problem+json, yalnız alan adı ve kural kodu, girdi yansımıyor. `ProfitInputError` 500 problem yanıtı ayrıntısız, loga yalnız hesap kimliği ve hata sınıfı (testli). Havuz zaman aşımı da genel 500 (ayrıntı yalnız logda). |
| Tarih ayrıştırma | Sorgu deseni ve `_ISO_DATE` `[0-9]` (Unicode rakam kabul edilmez; S3 B-01 dersi uygulanmış); `date.fromisoformat`; 2000-2100 aralığı; ters dönem, tek uç, çakışan `range` ve 93 gün 422 (testli); 92 gün kabul. |
| Kişisel veri (G16, G09) | Sipariş yanıtında müşteri alanı yok; `test_order_and_other_responses_never_carry_customer_data_even_after_a_pii_laden_sync` geçti. Uygulama logu sorgu dizesini yazmıyor (yalnız yol). `Cache-Control: no-store` genel. |
| Para biçimi | `fmt` -> `rnd` (ROUND_HALF_UP, `Fraction` ile) -> `format(..., "f")`: negatif sıfır üretmez (`-0` kuruş tamsayı 0), üs gösterimi yok, iki ondalık; zaten iki ondalıklı motor değerlerinde kuruş kaybı yok. Tüm para yapraklarının dizge olduğu ve float olmadığı testli (`test_every_money_field_is_a_two_decimal_string_never_a_float`). |
| Ürün `total_expenses` türetimi | `urun_maliyeti + komisyon + kargo_gonderi + kargo_iade + platform_hizmet_bedeli + ceza + reklam_harcamasi (dağıtılan + satışsız) + degisken_giderler`; motorun ürün net kârı (satır net kârları - satışsız reklam) ile `net_satis - toplam_gider = net_kar` özdeşliği tutar; maliyet eksikse null (motorla tutarlı). Sipariş toplamı satır `toplam_gider`'lerinin toplamı ve aynı özdeşlik. Dönem düzeyinde O-02'ye bakın. |
| İptal ve iade satırları | Ürün, dönem ve sipariş toplamlarına iptal girmez (motor K26 ve `order_totals`); iade satırları (`adjusted`) girer; `status_counts` iptali de sayar (belgelenmiş). |
| Null sıralama | Hesaplanamayan değer (maliyet eksik, net satış 0) her iki yönde sona; eşitlikte barkod artan; imleç anahtarı ile sıralama anahtarı aynı işlev (`_key`); testli ve PoC ile tutarlı. |
| Uyarılar uydurulmuyor | `build_alerts` yalnız motorun `period.warnings` ve satır `warnings` kodlarını aktarır; `ALERT_MESSAGES` anahtarları `WarningCode` ile birebir (testli); motorun üretmediği `REKLAM_KARI_YIYOR`, `IADE_ORANI_ARTISI` yalnız `not_yet_available` içinde. Mesaj metinleri sabit, girdi içermez. |
| Motor kablo adları | 38 altın senaryo API'den motor `render_result` ile birebir (`test_report_golden_api.py`); satır `durum` ve `kaynaklar` birebir taşınıyor. |
| Girdi sınırları | `limit` 1-200, `cursor` 1-400 karakter, imleç parçaları 200 karakter; imleç parmak izi motordan ÖNCE denetleniyor (yabancı sorgunun imleci CPU harcatmaz); bilinmeyen barkod motordan önce 404. |
| Bağımlılıklar (G11) | Bu commit yeni bağımlılık eklemedi (`pyproject.toml`/`uv.lock` değişmedi). |

## 4. Kod kalitesi notları (güvenlik bulgusu değil)

- Sorgu parametresi doğrulama hatalarında `detail` metni "İstek gövdesi geçersiz." (gövde yokken yanıltıcı); "İstek parametreleri geçersiz." daha doğru olur (genel hata işleyicisi).
- `profit_report.product_profit` artık hiçbir uç tarafından kullanılmıyor; ya kaldırılmalı ya da testte kalmalı.
- `ProductProfitListOut.sort/order/filter` `str` tipinde; `Literal` tipleri OpenAPI'de istemciye daha iyi belge verir.
- `alerts` uçlarında `KARGO_TARIFESI_EKSIK` satır başına bir uyarı üretir (perf testinde 5.000'in üzerinde); panel uyarıları kod başına gruplamalı (`counts` bunu sağlıyor).

## 5. 50_guvenlik.md merge engeli kontrolleri (bu kapsamdakiler)

| Kontrol | Durum |
|---|---|
| G01 Kiracı izolasyonu | Karşılanıyor (§3) |
| G06 Girdi doğrulama | Karşılanıyor; imleç bütünlüğü bilgi düzeyinde (B-01) |
| G07 Hız sınırı | KARŞILANMIYOR: Y-01 (kilitlenen istekler sayılmıyor, kiracılar arası kesinti); B-03 (yalnız kiracı boyutu) |
| G08 Hata yanıtları | Karşılanıyor |
| G09 Log | Karşılanıyor (sorgu dizesi ve tutar loglanmıyor) |
| G16 Kişisel veri | Karşılanıyor |

## 6. Merge engeli var mı: EVET

- **Güvenlik:** Y-01 (Yüksek) merge engelidir: herhangi bir rolle, verisiz bir hesapla, tek komutla tüm kiracılar için sınırsız tekrarlanabilir hizmet kesintisi. Kök neden `RateLimiter`'ın oturum havuzunu paylaşmasıdır; düzeltme merkezi yapılırsa S3 uçlarındaki aynı kalıp da kapanır. O-01'deki eşzamanlılık kapısı ve bağlantı bırakma aynı turda yapılmalıdır.
- **Alan doğruluğu:** Y-02 kod merge'ünü engellemek zorunda değildir (API motor çıktısını doğru taşıyor), ancak panelde net kâr gösterilmeden önce YAYIN ENGELİDİR: varsayılan ayarlarla zararına satış kârlı görünür. O-02, O-03, O-04 panel tasarımından önce ele alınmalı (en azından §7'deki sunum kurallarıyla).

## 7. Panel (S4 ekranı) için zorunlu sunum kuralları

1. **Kısmi kâr:** `net_kar_kismi = true` ise dönem marjı GİZLENSİN (O-02); net kâr "Kısmi: N satırın maliyeti girilmedi" rozetiyle ve maliyet girişine bağlantıyla gösterilsin. Kısmi dönemde gider alanlarından şelale/toplam gider çizilmesin.
2. **Eksik giderler:** Tarifesi tanımsız kargo ve tanımsız hizmet bedeli varken net kâr "kargo ve hizmet bedeli hariç" etiketi taşısın (Y-02); kullanıcı tarife girmeden "kârlı" rozeti ve "en kârlı ürünler" sıralaması verilmesin.
3. **Kesinlik:** `basis` "kesin" diye gösterilmesin; kesinlik satır `kaynaklar`'ından türetilsin (O-03). `eksik` kaynaklı kalem "-" veya "eksik" olarak, 0,00 olarak değil gösterilsin.
4. **Null değerler:** `net_kar`, `net_kar_marji_yuzde`, `toplam_gider` null ise "0" değil "Hesaplanamadı" gösterilsin; maliyeti eksik ama `maliyet_haric_katki < 0` olan ürün "maliyet girilmese de zarar" olarak işaretlensin (D-02).
5. **İade:** `iade_kdv_haric > 0` ve `adet_iade = 0` olan `adjusted` satırda "iade kaydı bekleniyor olabilir; maliyet tamamen gider sayıldı" notu (O-04; motor uyarısı gelene dek ipucu olarak).
6. **Uyarılar:** `BEKLENMEYEN_KESINTI` Y-02 düzeltilene kadar tarifesiz hesaplarda gösterilmesin ya da "kargo tarifesi tanımlı değil" notuyla gösterilsin; uyarılar kod başına gruplansın.
7. **Sipariş ekranı:** Sipariş toplamı dönem düzeyi giderleri içermez; dönemsiz açılan sipariş, liste ekranındaki sayıdan farklı olabilir (dağıtım tabanı farklı). Panel sipariş ekranını listedeki `start`/`end` ile açsın.
8. **İptal:** Yalnız iptal satırlı ürün ve sipariş "0,00 kâr" değil "İptal" olarak gösterilsin (B-02).
9. **Sayfalama:** `cursor_invalid` 422'de liste baştan yüklensin; sayfalar arası değer kayması olabileceği belirtilmesin, önbellek (O-01) ile giderilsin.
10. **Metin:** Ürün başlığı ve gider adları metin düğümü olarak basılsın (B-04).

## 8. Ajanın bildirdiği risklerin bağımsız değerlendirmesi

| Ajanın riski | Değerlendirme | Ciddiyet |
|---|---|---|
| Kısmi marj | Doğrulandı; marj pay ve payda farklı satır kümelerinden, gider alanları toplanmaz | Orta (O-02) |
| `KARGO_TARIFESI_EKSIK` | Doğrulandı ve kapsamı daha geniş: hizmet bedeli de 0 (uyarısız), 4 altın senaryoda zarar kâra dönüyor, 21 senaryoda yanlış `BEKLENMEYEN_KESINTI` | Yüksek (Y-02) |
| Önbelleksizlik | Doğrulandı; 92 gün 30.000 satırda 10 sn ve yüzlerce MB; ayrıca motor süresince bağlantı tutuluyor; kilitlenmeyi (Y-01) kolaylaştırıyor | Orta (O-01) |
| READ COMMITTED | Mekanizma doğru; motor eşleşmeyeni yok saydığı için etki geçici tutarsızlık; yeniden üretilmedi | Düşük (D-03, doğrulanmadı) |
| Claim'siz iade | Doğrulandı; K10'a uygun ihtiyatlı sonuç ama sunumda ayırt edilemiyor | Orta (O-04) |

## Ek A. Kavram kanıtı özetleri

Dosyalar oturumun geçici dizinindedir: `/tmp/claude-0/-home-user-hyt/9e0dcdb7-1ce4-5047-97d3-278f704913e7/scratchpad/test_poc_s4.py`, `test_poc_s4_perf.py`, `s4_defaults.py`. Çalıştırma: `cd netkar/services/api && uv run python -m pytest -p tests.conftest -c pytest.ini --rootdir=. -q -s <dosya>`.

### A.1 Havuz kilitlenmesi (Y-01)
- `test_poc_pool_deadlock_without_slow_engine[n]`: `threading.Barrier(n)` ile n eşzamanlı `GET .../profit/summary` (gerçek motor, `seed_basic`). n=20: 30,2 sn, 20 x 500; n=30: 30,3 sn, 30 x 500; n=45: 1 x 200, 44 x 500. Log: `sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 30.00`.
- `test_poc_deadlocked_requests_are_not_counted_and_template_endpoint_same`: 20'li dalga sonrası `SELECT sum(count) FROM rate_limits WHERE key LIKE 'profit-report:%'` = 0; aynı dalga `/product-costs/template.csv` için 20 x 500.
- `test_poc_threadpool_and_pool_starvation_affects_everyone`: motor 4 sn bekletilirken 45 istek; `pg_stat_activity` `netkar_app` "idle in transaction" = 20; kimliksiz `/v1/health/ready` 0,004 sn -> 28,9 sn; `/v1/auth/csrf` etkilenmedi (iş parçacığı havuzu doymadı, istekler havuz bağlantısında bekliyordu).

### A.2 Kısmi marj ve gider alanları (O-02)
- `test_poc_partial_period_margin_mixes_bases`: `net_satis 183.33`, `urun_maliyeti 100.00`, `komisyon 18.33`, `kargo_gonderi 0.00`, `donem_net_kar -10.00`, `net_kar_kismi true`, `net_kar_marji_yuzde -5.45` (= -10,00 / 183,33); alanlardan türetilen net 65,00.

### A.3 Etiket, iade, iptal (O-03, O-04, B-02)
- `test_poc_settled_basis_while_shipping_source_missing`: B2 `basis settled`, `kaynaklar.kargo_gonderi eksik`, `platform_hizmet_bedeli tahmini`.
- `test_poc_claimless_return_keeps_full_cost`: 1003 `adjusted`, `adet_iade 0`, `iade_kdv_haric 25.00`, `urun_maliyeti 50.00`, `net_kar -50.00`, `ZARAR`.
- `test_poc_cancelled_only_product_appears_with_zero_profit`: iptal barkod listede `net_profit "0.00"`, `basis none`; iptal sipariş `totals.net_profit "0.00"`.
- `test_poc_cargo_missing_not_visible_in_summary_or_product_list`: dönem `uyarilar` = `["MALIYET_EKSIK_SATIRLAR_VAR"]`, `kargo_gonderi 0.00`; uyarı sayımında `KARGO_TARIFESI_EKSIK 3`.

### A.4 Varsayılan ayar etkisi (Y-02)
- `s4_defaults.py`: her altın senaryo `parse_input` ile okunur, bir kez kendi ayarlarıyla, bir kez `dataclasses.replace(pi, settings=ProfitSettings())` ile hesaplanır. 40 satırda fark: 39 net kâr değişimi, 21 yeni `BEKLENMEYEN_KESINTI`, 4 zarar/sıfırdan kâra geçiş (G19, G31, G32, G33).

### A.5 Ölçüm (O-01) ve sipariş dönemi (D-01)
- `test_poc_s4_perf.py`: `tests/test_report_perf.seed_large` 30.000 siparişe ve 92 güne yayıldı; `summary` 10,03 sn, `products` tracemalloc tepe 234 MB.
- `test_poc_idle_in_transaction_during_engine`: motor 2 sn bekletilirken 1 "idle in transaction".
- `test_poc_order_default_period_exceeds_92_days`: dönemsiz sipariş isteği `period.days = 274`.

### A.6 İmleç ve olumlu kontroller (B-01, §3)
- `test_poc_cursor_is_unsigned_plain_json_and_portable_across_tenants`: çözülmüş imleç düz JSON; başka kiracıda 200; `1E+999999` değerli uydurma imleç 200.
- `test_poc_forged_cursor_content_runs_engine_before_422`: doğru parmak izli, `NaN` değerli imleç motoru 1 kez çalıştırıp 422.
- `test_ok_errors_do_not_reflect_input` (6 durum) ve `test_ok_cross_account_same_tenant_barcode_and_order_404` geçti.
