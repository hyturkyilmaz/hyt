# Denetim 2026-11-13: Önbellek düşük bulguları kapanış incelemesi (OK-01, OK-03, OK-05, OK-09, OK-11)

Kapsam: `ok_diff.patch` (kod kökü `netkar/services/api`): `migrations/versions/0013_report_data_revision_xact.py`,
`app/api/v1/profit.py`, `app/core/config.py`, `app/main.py`, `app/services/profit_report.py`,
`app/services/report_cache.py`, `app/services/report_gate.py`, `tests/test_report_cache.py`,
`tests/test_report_data_revision.py`. Referans: `denetim_2026-11-12_onbellek_kapanis.md`, migrasyonlar 0010, 0011, 0012.

Yöntem: salt okuma. Kod, migrasyonlar ve kurulu kütüphane kaynakları (anyio 4.15.1, psycopg 3.3.8,
SQLAlchemy 2.1.8, Starlette 1.10.0, Python 3.13) okundu. pytest çalıştırılmadı (paylaşılan test veritabanı
kullanımdaydı); test iddiaları kod üzerinden değerlendirildi.

## Özet

- Kritik 0, Yüksek 0, Orta 1 (DK-01), Düşük 2 (DK-02, DK-03), Bilgi 5 (DK-04..DK-08).
- 0013 tetikleyicisi doğru: işlem başına hesap başına tam bir artış; yeni hesap satırının ilk INSERT'ünde,
  eşzamanlı yazarlarda (ON CONFLICT yarışı), SAVEPOINT geri almasında ve `SET CONSTRAINTS ALL IMMEDIATE`
  kipinde de geçerli. Uygulama rolleri artışı ne bastırabilir ne de sahte işaret yazabilir. `search_path`
  bu kurulumda güvenli.
- Geri alma 0012 durumunu ve sayaç verisini koruyor, ancak 0012'nin `TO CURRENT_USER` politikasını (OK-09'un
  kendisi) geri getiriyor (DK-02). İşlev sahibi doğrulanmıyor (DK-03).
- OK-05: üst süre, yuva ve uçuş kaydı bırakımı, istemci iptalinin yayılması doğru. Yan etki: terk edilen motor
  iş parçacığı kapı yuvasını bırakıyor, böylece kapının bellek ve CPU sınırı zaman aşımı senaryosunda artık
  geçerli değil; takılan motorda iş parçacığı ve bellek sınırsız birikebilir (DK-01).
- OK-03 ve OK-11 tam kapandı. Var olan testlerdeki değişiklikler meşru; atlanan ya da gevşetilen test yok.

## Bulgular

| ID | Önem | Dosya:satır | Senaryo | Düzeltme |
|----|------|-------------|---------|----------|
| DK-01 | Orta | `app/services/profit_report.py:73`; `app/services/report_cache.py:214-236`; `tests/test_report_cache.py:1099` | `anyio.to_thread.run_sync(..., abandon_on_cancel=True)` iptalde `CapacityLimiter` jetonunu hemen bırakır (anyio `_backends/_asyncio.py:2670-2671`: `async with limiter` + `CancelScope(shield=False)`), iş parçacığı ise çalışmaya devam eder. `asyncio.timeout` aşımında `compute` iptal edilir, `gate.slot` çıkışı kapı yuvasını bırakır; ama motor iş parçacığı `feed.profit_input` ve motorun tepe belleğiyle (config notuna göre yüzlerce MB) yaşamayı sürdürür. Sonuç: (a) varsayılan 40 jetonluk anyio sınırlayıcısı tükenmez, fakat OS iş parçacığı sayısı hiçbir şeyle sınırlı değildir (anyio boşta işçi yoksa yeni `WorkerThread` açar); (b) kapının amacı olan "süreçte en çok N motor" (S4 Y-01/O-01) zaman aşımı yaşandığı anda bozulur. Motor süresi T > 45 sn olan büyük bir hesapta her yeniden deneme (dakikada 60 istek sınırı içinde) yeni bir motor başlatır, eşzamanlı motor sayısı yaklaşık `yuva x T/45` olur; motor takılırsa (OK-05'in hedeflediği senaryo) her 45 sn'de süreç yuvası kadar kalıcı iş parçacığı birikir ve süreç bellek tükenmesiyle düşebilir (bütün kiracılar etkilenir). Eskiden takılan hesap yalnız o anahtarı 503 döngüsüne sokuyordu. Herhangi bir dış iptal (istemci kopması vb.) da artık iş parçacığını terk eder. HTTP testi `gate.active == 0` iddiasını motor hâlâ bloklu iken yaparak bu davranışı sabitliyor. Veritabanı aşamasındaki zaman aşımı iş parçacığı bırakmaz (psycopg sorguyu sunucuda iptal eder), risk yalnız motor aşamasındadır. | Yanıt 503 dönebilir ama kaynak sayımı iş parçacığı GERÇEKTEN bitene dek sürmeli. Örnek: süreç düzeyi `threading.BoundedSemaphore` (ya da kapıda "terk edilmiş motor" sayacı) motor sarmalayıcısının İÇİNDE `try/finally` ile bırakılsın; yeni hesap başlatılmadan önce bloklamadan alınsın, doluysa 503 `report-busy`. Alternatif: kapı yuvasını zaman aşımında bırakmayıp iş parçacığının bitiş geri çağrısına devretmek. Terk edilen iş parçacığı sayısı için log ya da metrik ekleyin; testte iş parçacığı bitmeden yeni hesabın reddedildiğini ve bitince yuvanın döndüğünü doğrulayın. |
| DK-02 | Düşük | `migrations/versions/0013_report_data_revision_xact.py:96` | Geri alma `owner_counter` politikasını `TO CURRENT_USER` ile yeniden kuruyor (0012 gövdesi aynen). Geri alma `netkar_owner` dışındaki bir rolle (ör. süper kullanıcı, OK-09'un tarif ettiği işletim biçimi) çalıştırılırsa politika o role bağlanır; işlev sahibi `netkar_owner` FORCE RLS altında hiçbir INSERT/UPDATE politikası bulamaz ve sekiz motor girdisi tablosundaki HER yazım COMMIT anında RLS ihlaliyle düşer (senkron, maliyet içe aktarma, PUT). Test geri almayı `netkar_owner` ile çalıştırdığı için bunu görmez. | Geri almada da `TO netkar_owner` kullanın (sahip rolle çalıştırıldığında 0012 durumuyla birebir aynıdır, yanlış rolde güvenli kalır). Test bunu zaten `roles == ["netkar_owner"]` ile doğruluyor, değişmesi gerekmez. |
| DK-03 | Düşük | `migrations/versions/0013_report_data_revision_xact.py:83-87` | OK-09 önerisinin yalnız politika kısmı uygulandı. İşlev sahibi ne değiştiriliyor ne doğrulanıyor (`CREATE OR REPLACE` sahibi korur). 0012 süper kullanıcıyla çalıştırıldıysa SECURITY DEFINER işlev süper kullanıcı yetkisiyle çalışmaya devam eder (en az yetki ihlali sürer); migrasyon `netkar_owner` olmayan süper kullanıcı olmayan bir rolle çalıştırılırsa işlev sahibi o rol olur ve yeni `TO netkar_owner` politikası yazımları DK-02'deki gibi kırar. Docstring "işlev sahibi değişmez" diyor ama bunu kontrol eden kod yok. | Yükseltme başında `SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid = 'public.bump_report_data_revision()'::regprocedure` sonucu `netkar_owner` değilse ya da `current_user <> 'netkar_owner'` ise `RAISE EXCEPTION` ile durun (0011'deki açık rol adı deseni), ya da yetki varsa `ALTER FUNCTION ... OWNER TO netkar_owner`. Bir testte işlev sahibinin `netkar_owner` olduğunu doğrulayın. |
| DK-04 | Bilgi | `app/api/v1/profit.py:180-184, 196, 208-219` | `statement_timeout` rapor işleminin başında kuruluyor, ama 57014 yalnız `period_profit` çevresinde 503'e çevriliyor. `load_profit_settings`, `report_data_version`, `compute` içindeki `_restore_context`/`_bound_statements` ve önbellek isabetinde aynı işlemde sonradan çalışan uç sorguları 57014 alırsa yakalanmaz: Starlette düz metin "Internal Server Error" (500) döner. İstemciye ayrıntı sızmaz (`debug` kapalı), ancak problem+json değildir ve log'a SQL ile parametreler (kiracı/hesap kimliği) yazılır. Ayrıca bu sorgular `compute` dışında olduğundan `asyncio.timeout` onları sınırlamaz; tek sınır veritabanı tarafıdır. | 57014 için uygulama düzeyinde bir `DBAPIError` işleyicisi (sqlstate 57014 ise 503 + `Retry-After`, diğerleri yeniden yükseltilir) ya da `_report` tamamını saran tek yakalama. |
| DK-05 | Bilgi | `app/api/v1/profit.py:234-245`; `report_cache.py:225` | `statement_timeout` hesap üst süresine eşit (45 sn). Bir deyim hesap başladıktan sonra başladığı için `asyncio.timeout` hep önce dolar; veritabanı sınırı pratikte yalnız yedek olur. Zaman aşımı veritabanı aşamasında dolarsa psycopg 3.3 `CancelledError` üzerine sorguyu sunucuda iptal eder (`connection_async.py:535-542`: `cancel_safe` 5 sn + bekleme 5 sn), SQLAlchemy de `CancelledError`'ı çıkış istisnası sayıp yalnız o bağlantıyı geçersiz kılar (`engine/base.py:2231-2244`). Sızıntı yok, ama yanıt en kötü durumda üst süreden yaklaşık 10 sn sonra gelir ve bağlantı yeniden kurulur. Depoda ters vekil zaman aşımı yapılandırması bulunamadı; config notundaki "ters vekilden kısa" şartı doğrulanamıyor. | `statement_timeout` değerini hesap üst süresinden birkaç saniye kısa kurun (ör. `compute - 5 sn`); tipik veritabanı aşımı 57014 yolundan temiz döner ve bağlantı geçersiz kılınmaz. Dağıtım belgesine "ters vekil zaman aşımı >= compute_timeout + 10 sn" notu ekleyin. |
| DK-06 | Bilgi | `0013_report_data_revision_xact.py:46-70` | 0012'deki GUC erken dönüşü kalktı: N satırlık bir işlemde commit anında N ertelenmiş olayın HER biri artık tam bir `INSERT ... ON CONFLICT` yürütür (PK dizin yoklaması, kendi kilidinin kontrolü, WHERE değerlendirmesi). Doğruluk sorunu değil (SPI her deyimden önce komut sayacını artırdığı için "cannot affect row a second time" oluşmaz), ama OK-08'deki commit kuyruğu maliyeti büyür ve sayaç satır kilidi kuyruk işlenirken tutulur. | Büyük senkron işleminde (binlerce satır) commit süresini 0012 ile karşılaştırarak ölçün. OK-08'deki `WHERE ... IS DISTINCT FROM EXCLUDED` önerisi olay sayısını da azaltır. |
| DK-07 | Bilgi | `tests/test_report_data_revision.py:242-383`; `tests/test_report_cache.py:1083-1105` | Test boşlukları: SAVEPOINT + `ROLLBACK TO` ve `SET CONSTRAINTS ALL IMMEDIATE` kipinde tek artış sınanmıyor; OK-01 testi GUC'yi `admin_dsn` oturumunda kuruyor, `netkar_app`/`netkar_worker` oturumunda değil (sonuç aynı olmalı ama tehdit modeli uygulama rolleri); terk edilen iş parçacığının kaynak sınırı sınanmıyor (DK-01) ve HTTP testi yuvanın motor bitmeden boşalmasını doğru kabul ediyor. Var olan testlerdeki değişiklikler meşru: eski kurulumlar `tenant_lines == max_lines` kullanıyordu, yeni kural (`<= max_lines // 4`) bunu imkânsız kılıyor; aynı davranışlar (toplam tavanda tahliye, en ağır kiracının düşmesi, süresi dolanın süpürülmesi) dört ya da beş kiracıyla korunarak sınanıyor. `0012` geri alma testindeki `0013` sürüm beklentisi de doğru. Atlanan, `xfail` yapılan ya da eşiği gevşetilen test yok. | Eksik üç testi ekleyin (savepoint, IMMEDIATE, uygulama rolü oturumunda GUC); DK-01 düzeltmesiyle HTTP testini "motor bitene dek yuva dolu, sonra boş" biçimine çevirin. |
| DK-08 | Bilgi | `0013_report_data_revision_xact.py:48`; `app/db/provision.py:48-51`; `infra/postgres/init/01-roles.sh:24` | `search_path = pg_catalog, public` bu kurulumda güvenli: veritabanı sahibi `netkar_owner`, PG16'da `public` şemasının sahibi `pg_database_owner` (yani `netkar_owner`) ve PUBLIC'in CREATE hakkı yok; `REVOKE ALL ON DATABASE ... FROM PUBLIC` TEMP hakkını da kaldırıyor (pg_temp gölgelemesi yok). Gövdedeki tablo ve işlev adları nitelikli; `uuid`, `xid8`, `xid8 = xid8` ve `bigint + integer` pg_catalog'da tam eşleşmeyle önce çözülür. Ancak depoda açık bir `REVOKE CREATE ON SCHEMA public FROM PUBLIC` yok; PG14 ve öncesinden `pg_upgrade` ile gelen bir kümede eski ACL (PUBLIC CREATE) korunur. | Derinlemesine savunma: bir migrasyonda `REVOKE CREATE ON SCHEMA public FROM PUBLIC`; SECURITY DEFINER işlevlerde `search_path = pg_catalog, public, pg_temp` (pg_temp açıkça sonda). |

## Ayrıntılı değerlendirme

### 0013 tetikleyicisi

- Tetikleyici 0012'den kalan `DEFERRABLE INITIALLY DEFERRED` satır düzeyi kısıt tetikleyicisi; işlev COMMIT
  anında olay başına bir kez çağrılır. İlk çağrı satırı ekler ya da `last_xact` farklıysa artırır; aynı
  işlemin sonraki çağrıları `WHERE r.last_xact IS DISTINCT FROM pg_current_xact_id()` koşulunu sağlamaz.
  PL/pgSQL her deyimden önce komut sayacını artırdığından aynı işlemin önceki ekleme/güncellemesi görünürdür,
  "ON CONFLICT DO UPDATE command cannot affect row a second time" hatası oluşmaz. Koşul sağlanmasa da satır
  kilitlenir (zaten ilk çağrıda kilitli).
- Yeni hesap satırı: ilk olay `revision = 1, last_xact = T` ekler. Eşzamanlı iki işlemde ikincisi
  spekülatif eklemede birincinin bitişini bekler; birinci commit ederse çakışma yoluna girer ve satırda
  `last_xact = T1 <> T2` olduğu için artırır, birinci geri alınırsa kendisi ekler. Kayıp ya da çift artış
  yok (`test_first_writers_racing_on_a_new_account...` ve `test_concurrent_writers_never_lose_an_increment`
  baş sürümde, yani 0013 ile çalışır).
- SAVEPOINT: geri alınan alt işlemde kuyruğa alınan ertelenmiş olaylar atılır. `SET CONSTRAINTS ALL
  IMMEDIATE` ile olay alt işlem içinde çalışırsa satır sürümü alt işlemle birlikte geri alınır ve sonraki
  yazım yeniden artırır. `pg_current_xact_id()` en üst düzey kimliktir; 64 bit olduğu için sarmalama yok.
  İlk değer NULL, `IS DISTINCT FROM` bunu doğru ele alır.
- `REPEATABLE READ`/`SERIALIZABLE` yazarlarda eşzamanlı artış serileştirme hatası verir; 0012 ile aynı (OK-07).
- Sahtecilik/bastırma: `netkar_app` yalnız SELECT (test `InsufficientPrivilege` doğruluyor), `netkar_worker`
  yetkisiz. İşlevde `REVOKE ALL ... FROM PUBLIC` 0012'den gelir ve `CREATE OR REPLACE` ACL'yi korur; tetikleyici
  işlevleri zaten doğrudan çağrılamaz. Yeni tetikleyici eklemek TRIGGER yetkisi/sahiplik, devre dışı bırakmak
  sahiplik, `session_replication_role` süper kullanıcı ister. `SET CONSTRAINTS` yalnız zamanlamayı değiştirir.
  Uygulama rolü sayacı yalnız meşru veri yazımıyla artırabilir.

### Geri alma

Sıra doğru (önce 0012 işlevi, sonra politika, en son sütun); `revision` ve satırlar korunur; ACL korunur;
test gidiş-dönüşü ve işlev gövdesinin birebir geri geldiğini doğruluyor. Tek sorun DK-02.

### OK-05 çalışma zamanı

- `asyncio.timeout` yalnız kendi aşımını çevirir (`scope.expired()`); hesabın içinden gelen `TimeoutError`
  aynen yayılır (test var). Dış `CancelledError` (istemci iptali) zaman aşımına çevrilmez, `get_or_compute`
  `finally` bloğu uçuş kaydını siler ve bekleyenlere `None` verir (hata paylaşılmaz).
- Motor iş parçacığı veritabanı oturumu ya da bağlantısı tutmaz: `release_connection=True` ile besleyici
  okumalarından sonra commit yapılır, motor yalnız saf `profit_input` alır. Terk edilen iş parçacığının sonucu
  iptal edilmiş `Future`'a yazılmaz (anyio iptal edilmiş geleceği atlar); önbelleğe ya da paylaşılan duruma
  yazma yolu yok. Kaynak sınırı sorunu DK-01.
- `set_config('statement_timeout', ..., true)` işlem yereldir; ilk işlemde ve `release()` sonrası
  `compute` içinde `_restore_context` ile birlikte yeniden kurulur, yani besleyicinin gerçekten kullandığı
  işlemde geçerlidir (test `SHOW statement_timeout == '7s'` ile doğruluyor; yalnız bırakılmamış yol test
  ediliyor, bırakılmış yol kod incelemesiyle doğru). RLS bağlamıyla sıra bağımsız. 57014 dalı yuvayı bırakır
  ve ayrıntısız 503 döner; kapsam dışı 57014 için DK-04.
- Anyio varsayılan sınırlayıcısı (40) terk edilen iş parçacıklarıyla tükenmez, çünkü jeton iptalde bırakılır;
  asıl sınırsızlık OS iş parçacığı ve bellek tarafındadır (DK-01). Kapı yalnız etkin (terk edilmemiş) hesapları
  sınırlar.

## OK maddeleri için hüküm

| OK | Hüküm | Gerekçe |
|----|-------|---------|
| OK-01 | Kapandı | GUC tamamen kalktı; tekilleştirme istemcinin yazamadığı `last_xact xid8` işaretine bağlı; ilk ekleme, yarış, savepoint ve IMMEDIATE kipinde doğru. Test GUC'nin artışı bastıramadığını ve uygulama rollerinin sütunu yazamadığını gösteriyor (eksik test notları DK-07). |
| OK-03 | Kapandı | Etkin tavan `min(tenant_lines, max(1, max_lines // 4))`; `max_lines=8000` PoC senaryosu testte, varsayılan 10.000 korunuyor. |
| OK-05 | Büyük ölçüde kapandı | Hesaplayan üst süreli, yuva ve uçuş kaydı bırakılıyor, 503 + ayarlı `Retry-After`, veritabanı tarafında `statement_timeout`, ayar doğrulaması (> bekleme süresi). Kalan: terk edilen iş parçacığı kapı sınırının dışına çıkıyor (DK-01, Orta); kapsam dışı 57014 500 olur (DK-04). |
| OK-09 | Kısmen | Yükseltmede politika `TO netkar_owner`; işlev sahibi doğrulanmıyor (DK-03) ve geri alma `TO CURRENT_USER`'ı geri getiriyor (DK-02). |
| OK-11 | Kapandı | `report-wait-timeout` ve yeni `report-compute-timeout` `Retry-After` değerini ayardan alıyor; `_starved` temizliği 503 dalında da çalışıyor; iki testle doğrulanmış. |

## Düzeltme turu 1 yeniden denetim

Kapsam: `ok_diff2.patch` içinde yalnız DK-01..DK-05 değişiklikleri (`report_gate.py` `SlotHandle`,
`profit_report.py` `period_profit(slot=)`, `profit.py` `_report`/`_report_inner`/`_bound_statements`,
`0013` sahip ve politika satırları, ilgili testler). Salt okuma, pytest çalıştırılmadı.

### DK maddeleri için hüküm

| DK | Hüküm | Gerekçe |
|----|-------|---------|
| DK-01 | Kapandı | `abandon_on_cancel` kalktı; motor ayrı görevde `asyncio.shield` ile bekleniyor, yuva `SlotHandle.defer()` ile iş parçacığı görevinin bitiş geri çağrısına devrediliyor. Yuva sızıntısı yolu bulunamadı: `build_profit_input`/commit/`ensure_future` hatası `defer()` öncesinde olur ve `slot()` `finally` bloğu bırakır; `ensure_future` ile `defer()` arasında `await` yok, iptal penceresi yok; görev anyio'nun kalkanlı `CancelScope`'u içinde çalıştığı için dışarıdan iptal edilse de iş parçacığı bitince tamamlanır ve geri çağrı çalışır. Çift bırakma yok (tutamak idempotent, ertelenmişse `slot()` çıkışı bırakmaz); yanlış kiracı yok (kiracı kimliği tutamağa bağlı, `_release` yalnız tutamaktan çağrılır). `_finished` `shield`'den önce kaydedildiği için normal yolda yuva çağıran devam etmeden bırakılır. Motor hatası terk edilmişse hem `_finished` hem `shield` iç geri çağrısı `exception()` okur: "never retrieved" uyarısı yok. Motor iş parçacığı veritabanına dokunmaz (besleyiciden sonra commit; `app/profit` paketinde SQLAlchemy yok, girdi donmuş dataclass), istek bitince oturum/bağlantı açık kalmaz. Görev, çalışan iş parçacığının yerel `future` referansı üzerinden güçlü tutulur (asyncio'nun zayıf görev kümesi sorun olmaz). anyio jetonu iş parçacığı boyunca tutulur ama kapı (en çok `process_slots`) bunu 40'ın çok altında sınırlar. HTTP testi artık "motor bloklu iken yuva dolu, bitince boş" iddiasını yapıyor. Kalan bedel DK-10. |
| DK-02 | Kapandı | Geri alma da `TO netkar_owner`. |
| DK-03 | Kısmen (yeni DK-09) | `ALTER FUNCTION ... OWNER TO netkar_owner` eklendi: yanlış rolle (üye olmayan, süper olmayan) çalıştırmada migrasyon güvenle durur, süper kullanıcıyla çalıştırmada sahiplik düzelir. Ancak tablo sahipliği/yetkisi ele alınmadı (DK-09). |
| DK-04 | Kapandı | `_report` sarmalayıcısı `_report_inner` içindeki her 57014'ü (ayar ve sürüm okuması, bağlam kurulumu, besleyici) 503 `report-compute-timeout` yapıyor; log yalnız hesap kimliği; `from None` ile zincir kesik; diğer `DBAPIError`'lar aynen yayılır. Test ayar okumasında 57014'ü sınıyor. Kalan çok küçük boşluk DK-11'de. |
| DK-05 | Kapandı | `statement_timeout = ceil(max(1, compute - 5) * 1000)` ms (varsayılan 40 sn); ayar doğrulaması `compute > wait (25)` olduğundan pratikte en az 20 sn. Veritabanı sınırı artık `asyncio.timeout`tan önce dolar, tipik veritabanı aşımı bağlantıyı geçersiz kılmadan 57014 yolundan döner. Test `SHOW statement_timeout == '2s'` (7 - 5). |

### Yeni bulgular

| ID | Önem | Dosya:satır | Senaryo | Düzeltme |
|----|------|-------------|---------|----------|
| DK-09 | Düşük | `migrations/versions/0013_report_data_revision_xact.py` `upgrade()` (`ALTER FUNCTION ... OWNER TO netkar_owner`) | DK-03'ün hedeflediği durumda (0012 süper kullanıcıyla çalıştırılmış) `report_data_revisions` tablosunun sahibi de süper kullanıcıdır ve `netkar_owner`'ın bu tabloda INSERT/UPDATE/SELECT yetkisi yoktur (0012 yalnız `netkar_app`'e SELECT verir). İşlev sahibi `netkar_owner`'a geçince SECURITY DEFINER gövdesindeki `INSERT ... ON CONFLICT` "permission denied" alır; ertelenmiş tetikleyici COMMIT anında çalıştığından sekiz motor girdisi tablosundaki bütün yazımlar (senkron, maliyet içe aktarma, PUT) düşer. Beklenen dağıtımda (migrasyonlar `netkar_owner` ile) tablo zaten `netkar_owner`'ındır ve sorun yoktur. | Aynı migrasyonda `ALTER TABLE report_data_revisions OWNER TO netkar_owner` (sahip FORCE RLS altında, `owner_counter` politikası onu kapsar) ya da yükseltme başında tablo ve işlev sahibinin `netkar_owner` olduğunu doğrulayıp değilse `RAISE EXCEPTION`. Bir testte `pg_tables.tableowner` ve `pg_proc.proowner` değerlerinin `netkar_owner` olduğunu doğrulayın. |
| DK-10 | Bilgi | `app/services/profit_report.py:79-98`; `app/services/report_gate.py` | Bilinçli ödünleşim: takılan motor yuvasını süreç yeniden başlayana dek tutar. `tenant_slots` (2) takılı motor o kiracıyı kalıcı 429'a, `process_slots` (4) takılı motor bütün raporları kalıcı 503'e sokar; zarif kapanış (asyncio görevleri iptal edilip beklenirken) kalkanlı iş parçacığı bitene dek bekler. Bellek ve iş parçacığı artık sınırlı, ama sorun sessizce kalıcı hale gelebilir. | `profit_engine_abandoned` logu için uyarı/metrik; kapıda etkin ve terk edilmiş yuva sayısını sağlık ya da metrik ucunda yayımlayın; runbook: terk edilmiş yuva sayısı `process_slots`'a ulaşırsa süreci yeniden başlatın. |
| DK-11 | Bilgi | `app/services/report_cache.py` `_run` docstring ve modül notu; `app/core/config.py` `profit_report_compute_timeout_seconds` yorumu; `0013` docstring; `app/api/v1/profit.py:358, 430, 499` | Bayat belgeler: `_run` hâlâ "iş parçacığı `abandon_on_cancel` ile bırakılır" ve "yuva bırakılır" diyor; config yorumu "aynı değer `statement_timeout` olarak kurulur" diyor (artık `compute - 5`); 0013 docstring'i hem "işlev sahibi değişmez" hem "`OWNER TO` ile sabitlenir" diyor. Ayrıca önbellek isabeti yolunda (bırakılmamış işlem) `_report` sonrasında aynı işlemde çalışan `product_titles` vb. sorgular 40 sn `statement_timeout` altında ama sarmalayıcının dışında; aşılırsa düz 500 (ayrıntı sızmaz, olasılık çok düşük). | Belgeleri güncelleyin; isterseniz `_report` dönüşünden önce `SET LOCAL statement_timeout` değerini sıfırlayın ya da 57014 için uygulama düzeyi işleyici ekleyin. Görev için `asyncio` belgesinin önerdiği güçlü referans kümesi (ör. modül düzeyi `set` + `discard` geri çağrısı) savunma amaçlı eklenebilir. |

### Açık bulgu sayıları (bu tur sonrası)

- Kritik 0, Yüksek 0, Orta 0, Düşük 1 (DK-09), Bilgi 5 (DK-06, DK-07, DK-08 bu turda kapsam dışı ve değişmedi; yeni DK-10, DK-11).
- DK-01, DK-02, DK-04, DK-05 kapandı; DK-03 kısmen (DK-09 ile izleniyor).
