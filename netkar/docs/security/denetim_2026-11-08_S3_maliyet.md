# NetKâr S3 Güvenlik Denetimi: Ürün maliyeti API'si ve CSV/XLSX toplu içe aktarma (8 Kasım 2026)

- Denetlenen sürüm: dal `claude/dazzling-clarke-pfvf32`, commit edilmemiş çalışma ağacı (`git status` ve `git diff`, izlenmeyen yeni dosyalar dahil). Denetim sürerken aynı değişiklikler başka bir oturumda `382b345` olarak commit edildi (sonraki `b5099c7` yalnız S2 regresyon testini değiştirir); satır numaraları `382b345` ile birebir aynıdır.
- Hedef ve ölçüt: OWASP ASVS 5.0.0 Seviye 2, OWASP API Security Top 10 (2023), `docs/50_guvenlik.md` merge engeli kontrolleri (özellikle G01, G06, G07, G08, G09, G11).
- Kapsamdaki kod: `app/api/v1/product_costs.py`, `app/api/v1/product_cost_schemas.py`, `app/api/v1/router.py`, `app/services/product_costs.py`, `app/services/cost_import.py`, `app/core/limits.py` (`pattern_limits`), `app/core/config.py`, `app/core/clock.py`, `app/main.py`, `pyproject.toml` / `uv.lock` (openpyxl 3.1.5, defusedxml 0.7.1, python-multipart 0.0.33), testler `tests/test_product_costs_*.py`, `tests/test_cost_import_units.py`, `tests/product_cost_helpers.py`, `tests/conftest.py` (yeni `put`).
- Önce okunan belgeler: `docs/50_guvenlik.md`, `docs/adr/0005-senkron-ve-depolama.md`, önceki denetim `docs/security/denetim_2026-11-07_S2.md` (biçim). Bağlam için `app/api/deps.py`, `app/core/middleware.py`, `app/core/errors.py`, `app/core/ratelimit.py`, `app/db/session.py`, `app/db/rls.py`, migrasyon `0006_trendyol_data_and_sync.py` okundu.
- Denetçi kodu yazmadı; kod ve test dosyaları değiştirilmedi, commit yapılmadı. Kavram kanıtı (PoC) testleri repo dışında, oturumun geçici dizininde çalıştırıldı; özü Ek A'dadır.

## 0. Yöntem ve test sonuçları

| Adım | Sonuç |
|---|---|
| Kod incelemesi (uçlar, şemalar, servis, içe aktarma, gövde sınırı, bağımlılıklar, testler) | Tamamlandı |
| Yeni testler (`test_cost_import_units.py`, `test_product_costs_import.py`, `test_product_costs_api.py`), gerçek PostgreSQL | 162 geçti, 0 kaldı |
| Tüm API test paketi (`uv run pytest -q`) | 1017 geçti, 3 atlandı (reklam, bilinçli), 0 kaldı |
| PoC testleri (repo dışı `test_poc_s3.py`, repo `conftest`'i eklenti olarak yüklenerek) | 12/12 geçti; her biri ilgili gözlemi kanıtlar (Ek A) |
| Bellek/CPU ölçümü: `parse_import` sınırların hemen altındaki hazırlanmış XLSX'lerle, ayrı süreçte `ru_maxrss` | Y-01'in kanıtı (Ek A.1) |
| `pip-audit` (kilit dosyasından üretilen üretim bağımlılıkları) | Bilinen açık yok |
| openpyxl XML arka ucu (`openpyxl/xml/functions.py`): lxml kurulu değil, `DEFUSEDXML=True`; `fromstring` ve `iterparse` defusedxml'den | Doğrulandı |

## 1. Özet tablo (ciddiyete göre)

| No | Ciddiyet | Başlık | Konum | Eşleme | Kanıt |
|---|---|---|---|---|---|
| Y-01 | Yüksek | XLSX ayrıştırmada bellek ve CPU amplifikasyonu, eşzamanlılık sınırı yok: 0,9 MB dosya 1,3 GB bellek ve 22 sn CPU tüketiyor; tek yönetici API sürecini bellek tükenmesiyle düşürebilir | `app/services/cost_import.py:41-44, 144-176, 201-221`; `app/api/v1/product_costs.py:196-208`; `app/core/config.py:120` | API4:2023; ASVS 5.2.1, 5.2.3, 15.2.2; G06, G07 | PoC + ölçüm |
| O-01 | Orta | İçe aktarmada veritabanı bağlantısı dosya ayrıştırılırken "idle in transaction" tutuluyor; eşzamanlı yavaş içe aktarmalar 20 bağlantılık havuzu tüketir, tüm kiracıların istekleri zaman aşımına düşer | `app/api/v1/product_costs.py:195-208`; `app/api/deps.py:113-130`; `app/db/session.py:11` | API4:2023; ASVS 15.2.2 | PoC |
| D-01 | Düşük | Multipart gövde (2 MiB + 64 KiB) kimlik doğrulamadan ÖNCE ayrıştırılıyor; kalıp UUID olmayan 36 karakterlik yolu da kabul ediyor | `app/main.py:113`; `app/api/v1/product_costs.py:41, 178-189`; FastAPI gövde çözümü | API4:2023; ASVS 15.2.2 | PoC |
| D-02 | Düşük | Şablon CSV'sinde formül kaçışı yalnız hücrenin ilk karakterine bakıyor; ',' liste ayırıcılı Excel'de `;` ayraçlı satır virgülden bölünür ve `=...` hücresi oluşur | `app/services/cost_import.py:483-496` | ASVS 1.2.10 (CSV/formül enjeksiyonu); G06 | PoC (Excel'de açılış doğrulanmadı) |
| B-01 | Bilgi | Sayı ve tarih desenlerinde `\d` Unicode rakamları kabul ediyor ("١٢.٥٠" 12.50 olarak kaydediliyor) | `app/api/v1/product_cost_schemas.py:27`; `app/services/cost_import.py:248, 252, 313-314` | ASVS 1.3 (girdi normalizasyonu) | PoC |
| B-02 | Bilgi | defusedxml kullanımı çalışma zamanında zorlanmıyor (`OPENPYXL_DEFUSEDXML=False` ile kapanır; yalnız testte doğrulanıyor) | `app/services/cost_import.py:7-8, 202`; `tests/test_product_costs_import.py:362` | ASVS 1.5.1; API8 | Kod |
| B-03 | Bilgi | `pyproject.toml` alt sınırı `python-multipart>=0.0.20`; kilit 0.0.33 ama alt sınır eski sürümlere izin veriyor | `pyproject.toml:21` | ASVS 15.2.1; G11 | Kod |
| B-04 | Bilgi | Maliyet üzerine yazılınca eski değer hiçbir yerde kalmıyor (denetim kaydında tutar yok, geçmiş tablosu yok); finansal veri değişikliği sonradan yeniden kurulamaz | `app/api/v1/product_costs.py:130-139, 226-243`; `app/services/product_costs.py:267-275` | ASVS V16.2, 16.3 | Kod |
| B-05 | Bilgi | İçe aktarma raporu hücre değerinden 20 karakter ve başlık adlarını yansıtıyor (temizlenmiş, JSON) | `app/services/cost_import.py:236-241, 364-365` | ASVS 1.2 (çıktı kodlama, istemci tarafı) | Kod |
| B-06 | Bilgi | Hız sınırı yalnız kiracı bazında; kullanıcı ve IP boyutu yok; okuma uçlarında (liste/arama, geçmiş) sınır yok | `app/api/v1/product_costs.py:67-70, 73-110` | G07; API4 | Kod |
| B-07 | Bilgi | Toplu upsert satırları dosya sırasıyla kilitliyor; eşzamanlı çakışan içe aktarmalarda kilitlenme (deadlock) ve 500 olası (bütünlük korunur) | `app/services/product_costs.py:243-279` | ASVS 15.4 (eşzamanlılık) | Kod (doğrulanmadı) |
| B-08 | Bilgi | Gövde sınırı kalıbında gevşetme yok; kanonik olmayan yol biçimleri (sonda `/`, tiresiz/`urn:` UUID) 8 KiB'ye düşüyor (güvenli tarafta başarısızlık) | `app/core/limits.py:61-68`; `app/api/v1/product_costs.py:41` | ASVS 5.2.1 | PoC |

Sayım: Kritik 0, Yüksek 1, Orta 1, Düşük 2, Bilgi 8 (toplam 12).

## 2. Ayrıntılar

### Y-01 (Yüksek) XLSX ayrıştırmada bellek ve CPU amplifikasyonu, eşzamanlılık sınırı yok

**Konum:** `app/services/cost_import.py:41-44` (`MAX_ZIP_UNCOMPRESSED = 50 MB`, `MAX_ZIP_RATIO = 100`, `_BIG_ENTRY = 1 MB`), `144-176` (`check_zip`: yalnız toplam boyut ve oran), `201-221` (`load_workbook(read_only=True, data_only=True)`), `app/api/v1/product_costs.py:196-208` (hız sınırı sonra `run_in_threadpool(parse_import, ...)`), `app/core/config.py:120` (`rate_limit_cost_import_tenant = 30` / saat).

**Açıklama:** Zip denetimi açılmış toplam boyutu 50 MB ve oranı 100 ile sınırlıyor; bu, zip bombasına karşı doğru ama yetersiz. openpyxl `read_only` kipinde bile:

- `xl/styles.xml` defusedxml `fromstring` ile TAM ağaç olarak yüklenir ve her `<xf>` için Python nesnesi üretilir;
- `xl/sharedStrings.xml` tamamen belleğe, her girdi ayrı `str` nesnesi olarak okunur.

XML'in Python nesnesine dönüşümü bayt başına onlarca kat bellek tüketir. Ölçümler (Ek A.1, ayrı süreç, `ru_maxrss`):

| Dosya (tüm denetimleri geçer) | Boyut | Açılmış | Süre | Tepe bellek artışı |
|---|---|---|---|---|
| `styles.xml` içinde 2,5 milyon `<xf numFmtId=".." fontId="0"/>` | 0,92 MB (oran 56) | 51,4 MB | 21,8 sn | yaklaşık 1,33 GB |
| `sharedStrings.xml` içinde 2,7 milyon 3 harfli dize | 1,87 MB (oran 27,5) | 51,4 MB | 17,7 sn | yaklaşık 380 MB |
| Aynı sharedStrings dosyası, 4 eşzamanlı iş parçacığı | 4 x 1,87 MB | | 78 sn toplam | yaklaşık 1,45 GB |

Bellek eşzamanlı isteklerle doğrusal büyür; CPU ise GIL altında sıralanır ve olay döngüsünü yavaşlatır. Eşzamanlılığı sınırlayan hiçbir şey yok: kiracı başına saatlik 30 deneme sınırı istek BAŞINDA sayılır, 30 isteğin hepsi aynı anda başlayabilir; `run_in_threadpool` anyio'nun varsayılan 40 belirteçli havuzunu kullanır (diğer iş parçacığı işleriyle paylaşılır; örn. diske taşmış `UploadFile.read`). Satır sınırı (10.000) ve fiziksel satır tavanı (50.000) yalnız sayfa satırlarını sayar; stil ve paylaşılan dize bölümleri bu sınırların dışındadır.

**İstismar senaryosu:** Etkin pazaryeri hesabı olan herhangi bir kiracının owner/admin kullanıcısı (veya ele geçirilmiş bir yönetici oturumu) 0,9 MB'lık hazırlanmış XLSX'i `dry_run=true` ile 10-30 kez paralel gönderir. 10 istek yaklaşık 13 GB, 30 istek yaklaşık 40 GB bellek ister; API süreci veya konteyner OOM ile öldürülür ve TÜM kiracılar için hizmet kesilir. Saatte 30 deneme sınırı saldırıyı saatte bir kez tekrarlamaya yeter; birden çok kiracıyla çarpılır. Önkoşul kimlik doğrulama ve bağlı Trendyol hesabıdır (her müşteri bu önkoşulu sağlar), bu yüzden ciddiyet Yüksek'tir.

**Düzeltme önerisi:**
1. Bölüm bazlı sınır ve izin listesi: yalnız gereken bölümler kabul edilsin (`[Content_Types].xml`, `_rels/.rels`, `xl/workbook.xml`, `xl/_rels/workbook.xml.rels`, ilk çalışma sayfası, `xl/sharedStrings.xml`, `xl/styles.xml`, `xl/theme/*`, `docProps/*`); diğerleri reddedilsin. Bölüm başına açılmış üst sınır: örn. `styles.xml` <= 1 MB, `sharedStrings.xml` <= 8 MB, sayfa <= 16 MB, diğerleri <= 256 KB; toplam <= 20 MB (10.000 satırlık gerçekçi bir maliyet dosyası birkaç MB açılır).
2. Öğe sayısı ön taraması: `styles.xml` ve `sharedStrings.xml` defusedxml `iterparse` ile akışla sayılsın (`cellXfs` <= 10.000, `si` <= 200.000) ve aşımda openpyxl hiç çağrılmasın. Alternatif: openpyxl yerine ilk sayfa XML'ini doğrudan akışla okuyan dar bir okuyucu (stil yalnız tarih biçimi için gerekir).
3. Eşzamanlılık: süreç başına küresel `anyio.CapacityLimiter(2)` (veya semafor) ve kiracı başına aynı anda tek içe aktarma; dolu ise beklemeden 429/503 problem yanıtı.
4. Derinlemesine savunma: ayrıştırmayı ayrı bir süreçte (`ProcessPoolExecutor`, `max_tasks_per_child`) `RLIMIT_AS` (örn. 512 MB) ve süre sınırıyla (örn. 10 sn) çalıştırmak; aşım 422 "dosya çok karmaşık".

**Test önerisi:** Ek A.1'deki iki üreticiyle (stil ve paylaşılan dize) dosya üreten regresyon testi: yanıt 422, süre < 2 sn, `tracemalloc` tepe artışı < 100 MB. Eşzamanlılık testi: ayrıştırma bir olayla bekletilirken aynı kiracıdan ikinci içe aktarma 429 almalı.

### O-01 (Orta) Dosya ayrıştırılırken veritabanı bağlantısı "idle in transaction" tutuluyor

**Konum:** `app/api/v1/product_costs.py:195` (`_require_account` sorgusu işlemi başlatır), `197` (hız sınırı ayrı bağlantı ister), `198-208` (dosya okuma ve `run_in_threadpool(parse_import, ...)`), `app/api/deps.py:113-130` (`set_rls_context` işlemi zaten açmıştır), `app/db/session.py:11` (`pool_size=10, max_overflow=10`).

**Açıklama:** `get_auth_context` RLS bağlamını işlem yerel GUC ile kurar; `_require_account` sorgusu da aynı işlemdedir. Ardından ayrıştırma (normal dosyada saniyenin altında, Y-01 dosyalarında 20 sn ve üstü) boyunca işlem açık ve bağlantı havuzdan alınmış kalır. PoC (Ek A.2) ayrıştırma sırasında `pg_stat_activity`'de `netkar_app` için `idle in transaction` satırını gösterdi. `RateLimiter.hit` de aynı motor havuzundan bağlantı ister.

**İstismar senaryosu:** Bir yönetici 20 yavaş (Y-01) dosyayı aynı anda gönderir. 20 bağlantı ayrıştırma bitene kadar boşta işlemde kalır; diğer kiracıların istekleri ve hız sınırı sayacı havuzdan bağlantı bekler, SQLAlchemy `pool_timeout` (30 sn) sonrası 500 döner. Uzun açık işlem ayrıca VACUUM'u geciktirir. Y-01 düzeltilse bile, 2 MiB'lik meşru dosyalar ve küresel eşzamanlılık sınırı olmadan havuz baskısı sürer.

**Düzeltme önerisi:** Hesap kontrolü ve hız sınırından sonra `await db.commit()` (veya `rollback()`) ile bağlantıyı havuza iade edin; ayrıştırmayı bağlantısız yapın; yazma aşamasından önce `set_rls_context(db, ctx.tenant_id, ctx.user_id)`'yi yeniden çağırın (commit GUC'leri sıfırlar). Derinlemesine savunma: `ALTER ROLE netkar_app SET idle_in_transaction_session_timeout = '15s'`.

**Test önerisi:** Ek A.2'deki PoC'nin tersi: `parse_import` bir olayla bekletilirken `pg_stat_activity`'de `netkar_app` için `idle in transaction` satırı OLMAMALI; ardından yazma yine kiracı bağlamıyla başarılı olmalı (RLS testi ile birlikte).

### D-01 (Düşük) Multipart gövde kimlik doğrulamadan önce ayrıştırılıyor

**Konum:** `app/main.py:113` (`pattern_limits`), `app/api/v1/product_costs.py:41` (`[0-9A-Fa-f-]{36}`), `178-189` (`file: UploadFile = File()` ve `AdminDep`). FastAPI istek işleyicisi form gövdesini bağımlılıklardan (oturum, rol) ÖNCE `request.form()` ile çözer.

**Açıklama:** PoC (Ek A.3) oturumsuz bir istemcinin, kendi seçtiği `__Host-nk_csrf` çerezi ve aynı `X-CSRF-Token` başlığıyla (çift gönderim CSRF tarayıcı dışı istemciyi durdurmaz) 2 MiB multipart gövdeyi `/v1/marketplace-accounts/<rastgele uuid>/product-costs/import` ve hatta `/v1/marketplace-accounts/------------------------------------/product-costs/import` yoluna gönderebildiğini; `MultiPartParser.parse`'ın 2 kez çalıştığını ve yanıtın ancak sonra 401 olduğunu gösterdi. Starlette 1 MB üstü dosya parçasını diske (geçici dosya) taşır. Diğer uçlarda kimliksiz gövde zaten 1 MiB'ye (varsayılan) kadar okunabildiği için artış sınırlıdır; python-multipart 0.0.33 için bilinen açık yok (`pip-audit`).

**İstismar senaryosu:** Kimliksiz saldırgan çok sayıda paralel 2,1 MiB istekle bant genişliği, CPU ve geçici disk G/Ç'si tüketir. Etki saldırganın kendi bant genişliğiyle orantılıdır.

**Düzeltme önerisi:** İçe aktarma yolu için saf ASGI ön denetimi: oturum çerezi yoksa gövde okunmadan 401 (ucuz), mümkünse oturum doğrulaması da gövdeden önce. `IpRateLimitMiddleware` tam yol eşlemesi yerine kalıp desteklesin ve içe aktarma yoluna IP sınırı eklensin. Kalıp kanonik UUID'ye daraltılsın: `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}` (büyük harf için `(?i)`).

**Test önerisi:** Oturumsuz ve sahte CSRF çiftli 2 MiB istek 401 almalı ve `MultiPartParser.parse` sayacı 0 kalmalı; 36 tireli yol 8 KiB sınırına düşmeli.

### D-02 (Düşük) Şablon CSV'sinde formül kaçışı ayraç uyumsuzluğunu kapsamıyor

**Konum:** `app/services/cost_import.py:483-486` (`csv_safe_cell`: yalnız `startswith(FORMULA_PREFIXES)`), `489-496` (`;` ayraç, `QUOTE_MINIMAL`).

**Açıklama:** Şablon `;` ile yazılır ve yalnız `;`, `"` veya satır sonu içeren alan tırnaklanır. Liste ayırıcısı `,` olan bir Excel (Türkçe dışı yerel ayar) dosyayı virgülden böler. PoC (Ek A.4): başlığı `x,=1+1,y` olan ürün şablonda `A1;x,=1+1,y;;;` satırını üretir; virgülden bölünce ikinci hücre `=1+1` olur. `"` içermeyen formüller (örn. aritmetik veya DDE biçimi `=cmd|' /C calc'!A0`) bu yolla taşınabilir. Barkod da `products` tablosundan gelir ve orada allowlist yoktur (yalnız 1-200 karakter CHECK). Excel'in bu dosyayı gerçekten bu şekilde açıp hücreyi formül olarak değerlendirdiği bu denetimde Excel üzerinde DOĞRULANMADI. Başta boşluk (`" =1+1"`) ve tam genişlik `＝` varyantlarının Excel'de formül sayılması da doğrulanmadı (beklenen: sayılmaz); sağlamlaştırma olarak ele alınmalı.

**İstismar senaryosu:** Satıcının Trendyol panelinde ürün başlığını düzenleyebilen ama NetKâr'da yetkisi olmayan biri (çalışan, ajans) başlığa `x,=...,y` yazar; senkron sonrası NetKâr kullanıcısı şablonu İngilizce yerel ayarlı Excel'de açar ve formül çalışır veya uyarı ekranı çıkar. Veri kiracının kendi kataloğu olduğundan etki sınırlıdır.

**Düzeltme önerisi:** Tercihen şablonu XLSX olarak üretin (openpyxl ile hücre tipi metin; formül yorumlanmaz). CSV kalacaksa: bilgi amaçlı `baslik` sütununda `, ; \t \r \n "` karakterlerini boşlukla değiştirin; her hücrede baştaki boşluklar atıldıktan sonra ilk karakter `= + - @` (ve tam genişlik `＝ ＋ － ＠`) ise başa `'` ekleyin; barkod hücresine de aynı kural.

**Test önerisi:** Başlıklar `x,=1+1,y`, `x;=1`, `" =1"`, `" =1"`, `"＝1"`, `x\t=1` için: satır `[,;\t]` ile bölündüğünde hiçbir parça (soldan boşluk atılmış) `'` olmadan formül karakteriyle başlamamalı.

### B-01 (Bilgi) `\d` Unicode rakamları kabul ediyor

**Konum:** `app/api/v1/product_cost_schemas.py:27` (`_PLAIN_DECIMAL`), `app/services/cost_import.py:248` (`_NUMBER_CHARS`), `252` (`_group_pattern`), `313-314` (tarih desenleri).

**Açıklama:** Python `re` `\d` ile Arapça-Hint ve tam genişlik rakamları eşler; `Decimal` bunları dönüştürür. PoC: PUT gövdesinde `"١٢.٥٠"` ve `"１２.５０"` 200 döndü ve 12.50 kaydedildi. Değer normalize edildiği için istismar yolu bulunamadı; ancak doğrulama ile belgelenen biçim ("yalnız rakam") uyuşmaz ve gelecekte dizgenin olduğu gibi saklandığı bir alanda karışıklığa yol açabilir.

**Düzeltme önerisi:** `[0-9]` veya `re.ASCII` bayrağı. **Test önerisi:** Unicode rakamlı değerler 422 almalı.

### B-02 (Bilgi) defusedxml kullanımı çalışma zamanında zorlanmıyor

**Konum:** `app/services/cost_import.py:7-8, 202`; test `tests/test_product_costs_import.py:362`.

**Açıklama:** openpyxl, defusedxml'i yalnız kuruluysa ve `OPENPYXL_DEFUSEDXML` ortam değişkeni `True` (varsayılan) ise kullanır; lxml kurulursa `fromstring` için lxml (`resolve_entities=False`) devreye girer. Bugün durum doğru (lxml yok, `DEFUSEDXML=True`; XXE ve billion laughs testleri 422 veriyor). Ancak doğrulama yalnız testte; üretimde ortam değişkeni veya bağımlılık değişikliği korumayı sessizce kapatabilir (CPython'un expat 2.4+ amplifikasyon koruması ve harici varlık çözümlememesi ikinci katman olarak kalır).

**Düzeltme önerisi:** `_read_xlsx` veya uygulama başlangıcında `if not openpyxl.DEFUSEDXML: raise RuntimeError(...)` (fail-closed). **Test önerisi:** `monkeypatch.setattr(openpyxl, "DEFUSEDXML", False)` ile içe aktarma 500/503 değil, açık bir başlangıç hatası vermeli (veya içe aktarma reddedilmeli).

### B-03 (Bilgi) python-multipart alt sınırı kilitten geride

**Konum:** `pyproject.toml:21` (`python-multipart>=0.0.20`), kilit `uv.lock`: 0.0.33.

**Açıklama:** Kilit dosyası güncel ve `pip-audit` temiz; ancak alt sınır, kilit yeniden üretilirken veya kilitsiz kurulumda eski sürümlere izin verir. 0.0.20 ile 0.0.33 arasındaki yayımlanmış tavsiyelerin (örn. Starlette'in varsayılan kullanımında etkisiz olduğu bildirilen dosya yazma tavsiyesi) kapsamı bu denetimde ayrıntılı DOĞRULANMADI.

**Düzeltme önerisi:** `python-multipart>=0.0.33` (güvenlik açısından hassas diğer bağımlılıklarda da alt sınırı kilitle hizalamak).

### B-04 (Bilgi) Üzerine yazılan maliyetin izi kalmıyor

**Konum:** `app/api/v1/product_costs.py:130-139` (denetimde yalnız barkod ve tarih), `226-243` (içe aktarmada yalnız sayaçlar), `app/services/product_costs.py:267-275` (`ON CONFLICT DO UPDATE`, satırda yalnız son `entered_by`).

**Açıklama:** Denetim kaydında kişisel veri ve tutar yok (olumlu, G09). Ancak aynı (barkod, tarih) üzerine yazılınca önceki tutar, KDV oranı ve önceki yazan kaybolur; içe aktarma kaydı hangi barkodların değiştiğini de tutmaz. Kâr raporunu etkileyen finansal girdinin kim tarafından ne zaman ne olarak değiştirildiği yeniden kurulamaz (iç tehdit, hatalı toplu yükleme sonrası geri dönüş). Docstring'de bilinçli tasarım olarak yazılmış.

**Düzeltme önerisi:** Ekleme yalnız (append-only) `product_cost_revisions` tablosu veya denetim `meta`'sında önceki ve yeni değerin kiracı anahtarlı özeti; içe aktarmada değişen satır listesinin (barkod, tarih) ayrı tabloda tutulması. Koordinatör kararı gerektirir.

### B-05 (Bilgi) İçe aktarma raporunda hücre yansıması

**Konum:** `app/services/cost_import.py:236-241` (`excerpt`: kontrol karakterleri silinmiş ilk 20 karakter), `364-365` (en çok 20 yok sayılan başlık).

**Açıklama:** Yanıt yalnız JSON; değerler loga yazılmıyor; 422 rapor da aynı kısaltmayı kullanıyor. Yansıyan değer `=HYPERLINK(` gibi bir parça içerebilir. Ön yüz bu alanı metin olarak (innerHTML değil) göstermeli; ileride "hata raporunu CSV indir" eklenirse D-02'deki kaçış uygulanmalı.

### B-06 (Bilgi) Hız sınırı boyutları

**Konum:** `app/api/v1/product_costs.py:67-70` (yalnız `...:tenant:` anahtarı), `73-110` (liste, arama ve geçmişte sınır yok).

**Açıklama:** G07 "IP + kullanıcı + kiracı" ister. Kiracı bazlı sınır, bir yöneticinin (veya ele geçirilmiş oturumun) tüm kiracının içe aktarma bütçesini tüketmesine izin verir (kiracı içi hizmet engelleme). Okuma uçlarında sınır yok; `q` araması başlıkta `ILIKE '%..%'` ile hesap içinde sıralı tarama yapar (hesap başına ürün sayısıyla sınırlı, düşük maliyet). Hız sınırı eşzamanlılık denetimi değildir (Y-01).

**Düzeltme önerisi:** İçe aktarma ve tekil yazımda kullanıcı bazlı ek sayaç; okuma uçlarında cömert kullanıcı bazlı sınır (örn. 600/dk).

### B-07 (Bilgi) Toplu upsert kilit sırası belirsiz

**Konum:** `app/services/product_costs.py:243-279` (satırlar dosya sırasıyla, 1000'lik parçalarla tek işlemde).

**Açıklama:** İşlem bütünlüğü doğru: tüm parçalar tek işlemde, commit denetim kaydından sonra; hatalı satırlarda `allow_partial=false` iken hiçbir şey yazılmıyor (testli). Ancak aynı hesaba çakışan iki içe aktarma (veya içe aktarma ile PUT) satırları farklı sırada kilitlerse PostgreSQL kilitlenme tespiti birini iptal eder; kullanıcı genel 500 görür, ayrıntı loga gider. Kısmi yazma oluşmaz. Bu davranış PostgreSQL'in bilinen özelliğidir; bu kod için PoC yazılmadı (DOĞRULANMADI).

**Düzeltme önerisi:** Yazmadan önce satırları `(barcode, valid_from)` ile sıralamak; `DeadlockDetected`/`SerializationFailure`'ı 409 veya 503 problem yanıtına (yeniden dene) çevirmek.

### B-08 (Bilgi) Gövde sınırı kalıbı: gevşetme yok, kanonik olmayan biçimler güvenli tarafta

**Konum:** `app/core/limits.py:61-68`, `app/api/v1/product_costs.py:41`.

**Açıklama:** PoC (Ek A.5): kanonik yol ve büyük harfli UUID 2 MiB sınırını alıyor (200); `%2F` kodlu eğik çizgi Starlette tarafından çözüldüğü için yönlendirme ile tutarlı (200); sonda `/`, tiresiz UUID ve `urn:uuid:` biçimi 8 KiB önek sınırına düşüyor (413, yönlendirmeden önce). Yol büyük/küçük harfi ve sorgu dizesi kalıbı etkilemiyor (`scope["path"]` sorgu içermez; yönlendirme büyük/küçük harfe duyarlı). Kalıp `[^/]` içermediği için başka bir uç noktanın 8 KiB veya 1 MiB sınırını gevşetmiyor; PUT maliyet ucu 8 KiB'de kalıyor (testli). Not: uygulama `root_path` ile bir önek altında yayımlanırsa `scope["path"]` öneki içerir ve kalıp eşleşmez (mevcut önek kuralları için de geçerli; güvenli tarafta başarısızlık).

## 3. Doğrulanan kontroller (bulgu yok)

| Kontrol | Sonuç ve kanıt |
|---|---|
| IDOR/BOLA (G01, API1) | Her uçta önce `account_exists(tenant_id, account_id)`; yoksa 404 (varlık sızdırılmaz). Tüm sorgularda `tenant_id` ve `marketplace_account_id` süzgeci; `product_costs` FORCE RLS, `(marketplace_account_id, tenant_id)` bileşik yabancı anahtarı; benzersiz anahtarda kiracı olmaması bu FK ile güvenli. `test_other_tenant_gets_404_on_every_endpoint_and_nothing_leaks`, `test_rls_hides_cost_rows_from_other_tenant_at_database_level` geçti. `list_products` LATERAL alt sorgusu da kiracıya bağlı. |
| Rol kontrolü | PUT ve içe aktarma `require_role(OWNER, ADMIN)`; viewer 403 (`test_viewer_can_read_but_not_write`). Okuma ve şablon tüm rollere açık (beklenen). |
| CSRF (G04) | PUT ve POST için çift gönderim ara katmanı; `test_put_requires_csrf_token`. |
| SQL enjeksiyonu | Tüm sorgular ORM ve bağlı parametre; `icontains(..., autoescape=True)` `%` ve `_` için testli; `after` imleci bağlı parametre. |
| ReDoS | Tüm desenler doğrusal (iç içe niceleyici yok); sayı metni 40 karakterle sınırlı; yol deseni pydantic-core (Rust regex) ile. Sondaki `\n`, `\r`, boşluk, tam genişlik harf ve 201 karakterlik barkod yolda 422 (PoC). |
| Decimal ayrıştırma | Dizge deseninde üs yok (`"1e5"` 422); JSON `NaN`, `Infinity`, `1e999` 422; 4001 haneli tamsayı 422; 5001 haneli tamsayı 400 (Python tamsayı dizgesi sınırı, 500 değil). XLSX'te `inf`/`nan` float reddediliyor; `quantize` yalnız üst sınır denetiminden sonra çalışıyor. |
| XXE ve billion laughs | openpyxl `iterparse` ve `fromstring` defusedxml'den (lxml yok); `test_xlsx_xxe_and_entity_expansion_are_rejected` geçti; hata ayrıntısı sızmıyor. |
| Zip bombası | Bildirilen toplam, gerçek akış sayımı (yalan başlık), oran, girdi sayısı denetimleri testli. Kalan risk bellek amplifikasyonudur (Y-01). |
| İçe aktarmada formül enjeksiyonu | Barkod allowlist'i (`[A-Za-z0-9][A-Za-z0-9._-]{0,199}`) formül karakteriyle başlayan değeri her biçimde reddediyor; diğer alanlar sayı ve tarihe dönüştürülüyor; saklanan veride formül metni kalmıyor. `data_only=True` ile formül değerlendirilmiyor. |
| Dosya türü | Uzantı ve imza birlikte (XLSX `PK\x03\x04`, CSV'de `PK` ve NUL yok, UTF-8 zorunlu); işleyicide 2 MiB dosya sınırı (413). |
| Hata yanıtları (G08) | RFC 9457; `ImportFileError` ayrıntıları sabit Türkçe metin; okuma hataları ayrıntısız yakalanıyor; doğrulama hatası girdi değerini yansıtmıyor; yakalanmamış hata genel 500. |
| Denetim izinde kişisel veri (G09, G16) | Yalnız barkod, tarih, sayaçlar, kullanıcı kimliği ve HMAC'li IP özeti; tutar ve kişisel veri yok (`test_put_audit_trail_has_barcode_and_date_but_no_amounts`). |
| İşlem bütünlüğü | Tek işlem, parça hatasında hiçbir şey yazılmıyor (`test_import_is_atomic_when_the_database_rejects_a_chunk`); kuru deneme hiçbir şey yazmıyor. |
| Hız sınırı (kuru deneme, tekil yazım) | İçe aktarma her denemede (kuru deneme ve dosya hatası dahil) sayılıyor (`test_import_is_rate_limited_per_tenant_including_dry_runs`); tekil yazım ve şablon ayrı sayaçlı. Sayaç ayrı otomatik commit'li bağlantıda. |
| Bağımlılıklar (G11) | `pip-audit`: openpyxl 3.1.5, defusedxml 0.7.1, python-multipart 0.0.33, et-xmlfile 2.0.0, starlette 1.10.0, fastapi 0.162.0 için bilinen açık yok. |

## 4. Kod kalitesi notları (güvenlik bulgusu değil)

- Barkod allowlist'i Trendyol barkod biçimine göre doğrulanmamış (kodda da belirtilmiş). `products` tablosu 1-200 karakterlik her barkodu kabul ettiği için (testlerde `X%_9`) allowlist dışı barkodlu ürünlere PUT veya içe aktarma ile maliyet girilemez; şablonda bu barkodlar `'` önekiyle çıkar ve geri yüklenemez. İşlevsel risk; canlı pilotla doğrulanmalı.
- `known_barcodes` 10.000 öğeye kadar `IN` listesi kullanıyor (asyncpg 32.767 parametre sınırının altında); `= ANY(:array)` daha az ayrıştırma maliyetlidir.

## 5. 50_guvenlik.md merge engeli kontrolleri (bu kapsamdakiler)

| # | Durum | Not |
|---|---|---|
| G01 Kiracı izolasyonu | Karşılanıyor | §3 |
| G04 CSRF | Karşılanıyor | §3 |
| G06 Girdi doğrulama, boyut limitleri, formül enjeksiyonu | Kısmen | Boyut limitleri dosya bazında var ama bölüm ve eşzamanlılık bazında yok (Y-01); şablon kaçışı ayraç uyumsuzluğunu kapsamıyor (D-02) |
| G07 Rate limit | Kısmen | Kiracı bazında var; kullanıcı ve IP boyutu yok (B-06); eşzamanlılık sınırı yok (Y-01) |
| G08 Hata yanıtları | Karşılanıyor | §3 |
| G09 Log maskeleme | Karşılanıyor | Hücre değeri loga yazılmıyor |
| G11 Bağımlılıklar | Karşılanıyor | `pip-audit` temiz; alt sınır notu B-03 |

## 6. Merge engeli var mı: EVET

Y-01 (Yüksek) merge engelidir: tek bir kimliği doğrulanmış yönetici, sınırların altında kalan 1 MB'tan küçük dosyalarla API sürecini bellek tükenmesiyle düşürebilir ve tüm kiracıları etkiler. Kapanış için asgari: bölüm izin listesi ve bölüm başına açılmış boyut sınırı (özellikle `styles.xml` ve `sharedStrings.xml`), öğe sayısı ön taraması, süreç başına küresel ve kiracı başına eşzamanlılık sınırı, Ek A.1 dosyalarıyla regresyon testi. O-01'in aynı turda kapatılması önerilir (ayrıştırmadan önce bağlantıyı iade etmek küçük bir değişikliktir). D-01, D-02 ve Bilgi maddeleri merge engeli değildir.

## Ek A. Kavram kanıtı özetleri

PoC dosyaları repo dışında tutuldu (talimat gereği yalnız bu rapor yazıldı). Çalıştırma: `cd services/api && uv run pytest -q -s -p tests.conftest --rootdir=. <poc_dosyası>`; ölçüm betikleri `uv run python <betik> <dosya>`.

### A.1 Bellek/CPU amplifikasyonu (Y-01)

Üretici (özet): openpyxl ile 2 satırlık meşru bir çalışma kitabı kaydedilir, sonra zip yeniden yazılır.

```python
# styles.xml: </cellXfs> öncesine ~49 MB rastgele küçük xf öğesi (oran ~56, tüm check_zip denetimlerini geçer)
body.write(b'<xf numFmtId="%d" fontId="0"/>' % rnd.randrange(4))
# sharedStrings.xml: 2 harfli alfabeden 3 harfli 2,7 milyon <si><t>..</t></si> (oran ~27,5);
# [Content_Types].xml'e sharedStrings Override eklenir.
```

Ölçüm: `parse_import(ad, veri, date(2026, 11, 8))` ayrı süreçte, öncesi ve sonrası `resource.getrusage(RUSAGE_SELF).ru_maxrss`.

```
styles4.xlsx  ok total=1 invalid=1 | size=922503  | time=21.81s | maxrss before=50MB peak=1385MB
bomb2.xlsx    ok total=1 invalid=1 | size=1866264 | time=17.66s | maxrss before=51MB peak=431MB
bomb2.xlsx x4 iş parçacığı          n=4 time=78.1s peak=1495MB
CSV 2 MiB (tek satır çok sütun)      time=0.06s peak=104MB   (CSV yolu sorunsuz)
CSV 2 MiB (50 sütun, 6070 satır)     time=0.11s peak=78MB
```

### A.2 Ayrıştırma sırasında boşta işlem (O-01)

`app.api.v1.product_costs.parse_import` bir `threading.Event` ile bekletilir, içe aktarma ayrı iş parçacığında gönderilir, yönetici bağlantısıyla sorgulanır:

```
SELECT usename, state FROM pg_stat_activity
 WHERE usename = 'netkar_app' AND state LIKE 'idle in transaction%'
-> [('netkar_app', 'idle in transaction')]   (olay bırakılınca yanıt 200)
```

### A.3 Kimliksiz multipart ayrıştırma (D-01)

`starlette.formparsers.MultiPartParser.parse` sayaçla sarılır; oturumsuz istemci `__Host-nk_csrf=AAAA...` çerezini ve aynı `X-CSRF-Token` başlığını kendisi koyar, 2 MiB dosya gönderir:

```
.../c667c73c-ecd7-4de1-aa94-c5247a61e8ad/product-costs/import 401 urn:netkar:problem:unauthorized
.../------------------------------------/product-costs/import 401 urn:netkar:problem:unauthorized
multipart parse calls (kimliksiz): 2
```

### A.4 Şablonda ayraç uyumsuzluğu (D-02)

```
'A1;x,=1+1,y;;;' | virgülle bölünce: ['A1;x', '=1+1', 'y;;;']
'A2; =1+1;;;'    | virgülle bölünce: ['A2; =1+1;;;']
'A3;＝1+1;;;'     | virgülle bölünce: ['A3;＝1+1;;;']
```

### A.5 Yol varyasyonları ve sayı girdileri (B-01, B-08, §3)

```
kanonik        -> 200    BÜYÜK uuid -> 200    %2F -> 200
sonda /        -> 413    tiresiz uuid -> 413  urn uuid -> 413
PUT unit_cost: '1e5' 422, 'NaN' 422, 'Infinity' 422, '12.50\n' 422, '١٢.٥٠' 200 (12.50), '１２.５０' 200 (12.50)
JSON ham: NaN 422, Infinity 422, 1e999 422, 4001 hane 422, 5001 hane 400
Barkod yolu: ABC%0A 422, ABC%0D 422, ABC%20 422, %EF%BC%A1BC 422, 201 x 'A' 422
```
