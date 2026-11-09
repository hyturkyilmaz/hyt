# ADR-0005: Trendyol verisinin depolanması, senkron işleri ve ayrı worker rolü

- Durum: Kabul edildi (S2/S3 köprü turu: depolama + senkron + motor bağlantısı; API uçları ve maliyet içe aktarma sonraki tur)
- Tarih: 7 Kasım 2026
- İlgili: `docs/10_mimari.md` §3 (veri akışı) ve §5 (veri modeli), `docs/12_kar_motoru.md` §11, ADR-0001 (RLS), ADR-0003 (istemci, PII atma noktası), ADR-0004 (zarf şifreleme, D-05 ertelemesi), `docs/security/denetim_2026-11-07_S2.md` (D-05), migrasyon `0006_trendyol_data_and_sync.py`, `services/api/app/services/sync/`, `app/services/profit_feed.py`, `app/worker/`

## 1. Bağlam

İstemci (ADR-0003) ve motor (docs/12) hazırdı ama aralarında kalıcı katman yoktu: Trendyol verisi yalnız bellekte okunuyor, motor yalnız altın test JSON'uyla besleniyordu. Bu ADR dört şeyi birlikte karara bağlar: (1) hangi veri hangi tabloda nasıl saklanır, (2) senkron işleri nasıl çakışmadan, yeniden denemeye dayanıklı ve idempotent çalışır, (3) şifreli pazaryeri anahtarlarını okuyabilen rol API'den ayrılır (S2 D-05'in ertelenen kısmı), (4) kayıtlar motor girdisine nasıl çevrilir.

## 2. Karar: depolama

**Tablolar** (migrasyon 0006; hepsinde `tenant_id` + `marketplace_account_id`, `ENABLE` + `FORCE` RLS, politika `tenant_isolation`; `(marketplace_account_id, tenant_id)` bileşik yabancı anahtarı hesabın başka kiracıya ait bir satıra bağlanmasını engeller):

| Tablo | Satır birimi | Doğal anahtar (idempotent upsert) |
|---|---|---|
| `products` | katalog varyantı | `(hesap, barcode)` |
| `product_costs` | geçerlilik tarihli maliyet (boş başlar, kullanıcı girer) | `(hesap, barcode, valid_from)` |
| `orders` | sipariş PAKETİ (Trendyol `shipmentPackageId`) | `(hesap, shipment_package_id)` |
| `order_lines` | sipariş satırı | `(order_id, line_id)` |
| `returns` | iade KALEMİ (`claimItems[]`) | `(hesap, claim_id, claim_item_id)` |
| `financial_transactions` | ekstre satırı (settlements ve otherfinancials) | `(hesap, source, request_type, request_sub_type, transaction_id)` |
| `cargo_invoice_items` | kargo faturası kalemi | `(hesap, invoice_serial_number, item_key)` |
| `sync_runs` | bir kaynağın bir senkron adımı | (kimlik; upsert değil) |
| `sync_cursors` | kaynak başına son başarılı pencere | `(hesap, source)` birincil anahtar |

**Para tipi: `NUMERIC(18,6)`, oranlar `NUMERIC(9,4)`.** Kuruş tamsayı (bigint) seçilmedi çünkü motorun girdisi kuruşa yuvarlanmış değildir: Trendyol kuruş altı hassasiyetli tutar gönderir (komisyon 74,985; hakediş 424,915; altın testlerde 25 satır, maliyet 3,335) ve motor ara adımlarda yuvarlamaz, `Fraction` ile tam hassasiyetle çalışıp çıkışta tek yuvarlama (`money.rnd`, ROUND_HALF_UP) yapar (K01). `NUMERIC(18,2)` veya kuruş tamsayı girdiyi kayıt anında yuvarlardı ve 74,985 gibi yarım kuruş sınırlarında motor çıkışını değiştirirdi (G33, G41 bu sınırı sınar). Altı ondalık, Trendyol'un double'larından gelen makul uzunluktaki değerleri kayıpsız tutar; `Decimal` ile gidiş dönüş birebirdir. Yuvarlama yalnız motor çıkışında olur. Bunun kanıtı: 38 altın senaryo veritabanından geçirilince aynı çıktıyı verir (§7).

**Kullanıcı verisi sütunları senkron tarafından ASLA ezilmez** (`ON CONFLICT DO UPDATE` kümesinde yoktur): `returns.returned_to_stock` (K10 "satılamaz" işareti), `products.unit_desi` (Trendyol desi vermez, K09), `orders.customer_key`. `netkar_app` yalnız `returned_to_stock` ve maliyet tablosunu yazabilir.

**Silme yok.** Siparişin payload'ında artık olmayan satır (paket bölündü, satır kalktı) silinmez, `order_lines.removed_at` ile işaretlenir; sonraki payload'da geri gelirse işaret kalkar. Besleyici işaretli satırı motora vermez. Hiçbir rolün veri tablolarında `DELETE` yetkisi yoktur.

**`order_lines.items` JSONB'dir** (adet başına `{id, seller_discount, ty_discount}`, tutarlar metin). Ayrı tablo yerine seçildi çünkü kalem kırılımı satırla birlikte atomik yazılır ve değişirse bütünüyle yenilenir (kalem bazında silme/işaretleme mantığı gerekmez); SQL'de toplanan indirim değerleri satır sütunlarındadır. Kalem sayısı adetle uyuşmazsa ve satırda indirim varsa besleyici satırı motora vermez ve `FeedNotes.lines_bad_items` ile sayar.

**Kargo faturası kalem kimliği (`item_key`).** `parcelUniqueId` boş gelebilir ve aynı sipariş için özdeş kalemler olabilir. Anahtar `sha256(tip | koli | sipariş | tutar | desi | sıra)`'dır; `sıra` aynı özetin fatura içindeki n. tekrarıdır. Böylece özdeş kalemler tekilleşip kaybolmaz, kalem sırası değişse anahtar değişmez, fatura yeniden çekilince aynı satırlar güncellenir.

**Ekstre doğal anahtarında `request_type` ve `request_sub_type` vardır.** Motor sınıflandırmayı yanıttaki Türkçe metne değil, çekilen istek tipine göre yapar (K05); `DeductionInvoices` alt tipsiz istek `PlatformServiceFee` satırlarını da döndürebilir (K13). Aynı kimlik iki istek altında iki satır olur; besleyici alt tipli olanı tutar (alt tipsiz kopya bedeli iki kez gider yazardı).

## 3. Karar: senkron stratejisi

Kaynaklar sabit sırayla işlenir: `orders`, `claims`, `products`, `settlements`, `other_financials`, `cargo_invoices` (sonuncusu, ekstredeki "Kargo Faturası" satırlarının seri numaralarına bağlıdır).

| Kaynak | Uç nokta | Pencere | Artımlı örtüşme | Not |
|---|---|---|---|---|
| orders | `orders/stream` (`lastModified`) | 14 gün - 1 ms, her pencere yeni akış | 1 saat | v2/orders kullanılmaz (10.000 kayıt tavanı, sessiz kırpma yok) |
| claims | `claims` | 14 gün (üst sınır dokümante değil, tutucu seçim) | 2 saat | |
| products | `products/approved` | pencere yok, tam yenileme | n/a | günde 1; `unit_desi` ezilmez |
| settlements | `settlements`, her pencerede 23 tip | 15 gün - 1 ms (istemci kuralı) | 7 gün | `[CHE]`: 1 istekte 1 tip |
| other_financials | `otherfinancials`: DeductionInvoices, DeductionInvoices+PlatformServiceFee, Stoppage, CashAdvance, FinancialItem | 15 gün - 1 ms | 7 gün | nakit hareketleri (`PaymentOrder`, `WireTransfer`, `IncomingTransfer`) gider olmadığı için çekilmez |
| cargo_invoices | `cargo-invoice/{seri}/items` | seri numarası başına | n/a | kalemi olmayan seri çekilir; bir çalıştırmada en çok 200 seri |

- **Geriye bakma:** 89 gün (`SyncPolicy.lookback_days`). Trendyol "son 3 ay" der; sınır gününün yorumu belirsiz olduğundan 1 gün pay bırakıldı. Artımlı çekim imleç bundan eskiyse başlangıcı 89 güne kırpar.
- **Pencereler komşuyla sınır anını paylaşır** (istemci kuralı): sınırda yinelenen kayıt gelebilir, doğal anahtarla upsert bunu zararsız yapar; aynı INSERT içinde yinelenen anahtar yazımdan önce tekilleştirilir (`ON CONFLICT ... cannot affect row a second time` hatası olmaz).
- **Örtüşme gerekçesi:** ekstre satırları teslimattan sonra, geriye dönük işlem tarihiyle oluşur; sipariş ve iade değişiklikleri `lastModified`'e göre gelir ama saat kayması ve geç yazım için pay bırakılır.
- **Pencere atomikliği.** Bir pencere önce ağdan çekilip bellekte eşlenir (veritabanı işlemi AÇIK DEĞİL), sonra TEK işlemde yazılır; aynı işlemde `sync_runs` sayaçları ve `sync_cursors.watermark` ilerler. Pencere ya tam yazılır ya hiç. Çökme sonrası yeniden deneme imleçten devam eder ve ilk pencereleri tekrar çekmez (`test_backfill_resumes_from_the_cursor_after_a_transient_failure`).
- **Backfill** `sync_cursors.backfill_completed_at`'i kaynak bazında işaretler; tamamlanmış kaynak tekrar backfill edilmez (`force=True` ile edilir). **Artımlı çekim backfill'i tamamlanmamış kaynağı atlar** (`needs_backfill`); o kaynağı backfill üstlenir.
- **`sync_runs` yalnız sayaç ve sınıf tutar:** kaynak, pencere, durum (`running|succeeded|failed|skipped`), pencere ilerlemesi (`windows_done/windows_total`), çekilen/yazılan/atlanan sayısı, `error_class` (kısa belirteç). Yanıt gövdesi, hata iletisi ve izleme yoktur (veritabanı hata iletileri satır değeri taşıyabilir).
- **Planlayıcılar (procrastinate periyodik, UTC):** `sync.plan_orders_claims` her 15 dk (`*/15 * * * *`), `sync.plan_finance` günde 2 (`7 3,15 * * *`), `sync.plan_products` günde 1 (`23 1 * * *`). Planlayıcı etkin hesapları `sync_gate.syncable_accounts()` ile listeler: backfill'i eksik hesaba `sync.backfill`, backfill'i tamamlanmış kaynaklara `sync.incremental` ekler (ikisi aynı hesapta sırayla çalışır). Planlayıcı aynı zamanda bağlantı eklenirken kuyruğa girememiş backfill için güvenlik ağıdır.
- **Bağlantı eklenince** `POST /v1/marketplace-accounts` (ekleme ve yeniden bağlama), kayıt kalıcı olduktan SONRA `sync.backfill` işini kuyruğa ekler (API `netkar_app` rolüyle yalnız `procrastinate_jobs`'a iş ekler). Kuyruk hatası bağlantıyı bozmaz (uyarı loglanır).

## 4. Karar: kilit ve eşzamanlılık

Aynı hesabın işleri üç katmanla çakışmaz:

1. **procrastinate `lock` = `sync:{hesap}`:** aynı kilitli işler sırayla çalışır.
2. **`queueing_lock`:** bekleyen yinelenen iş eklenmez (`sync-backfill:{hesap}`, `sync-incr:{hesap}:{kaynaklar}`); planlayıcı 15 dakikada bir çalışsa da kuyrukta kaynak kümesi başına tek iş bekler.
3. **PostgreSQL danışma kilidi (`pg_try_advisory_lock(hashtextextended('netkar:sync:{hesap}', 0))`)**, yürütücüde, ayrı bir bağlantıda. Kuyruk dışından doğrudan çağrılan yürütücüyü de kapsar (planlayıcı, bakım betiği, test). Kilit alınamazsa iş çakışmadan `locked` sonucuyla çıkar ve Trendyol'a istek atmaz. Süreç çökerse bağlantı kopar ve kilit kendiliğinden düşer (zaman aşımı veya kalp atışı mantığı gerekmez). Kilit açılamazsa bağlantı havuza geri verilmez.

Sınır: kovalar (rate limit) hâlâ süreç içidir (ADR-0003 §3). Birden çok worker süreci aynı satıcıya istek atarsa toplam hız çarpılır; 429 geri çekilmesi bunu tolere eder.

## 5. Karar: hata sınıflandırması

Sınıf yalnız kısa belirteçtir; `sync_runs.error_class` ve loga yalnız bu yazılır.

| İstisna | Sınıf | Davranış |
|---|---|---|
| `TrendyolAuthError` (401) | `unauthorized` | hesap `invalid`, denetim kaydı `marketplace_account.sync_invalidated` (neden + kaynak), senkron DURUR, iş yeniden denenmez |
| `TrendyolForbiddenError` (403) | `forbidden` | aynısı |
| `TrendyolRateLimitedError` (+ `WaitBudget`) | `rate_limited` | GEÇİCİ: kaynak `failed`, diğer kaynaklar sürer, iş `SyncTransientError` ile geri çekilmeyle yeniden denenir |
| `TrendyolServerError` (5xx) | `server_error` | geçici |
| `TrendyolNetworkError` | `network` | geçici |
| `TrendyolProtocolError` | `protocol` | kalıcı: kaynak `failed`, iş yeniden denenmez (aynı sonucu verir); sonraki planlama turu aynı pencereyi imleçten tekrar dener |
| `TrendyolWindowTooLargeError` | `window_too_large` | kalıcı |
| `TrendyolRequestError` (diğer 4xx) | `request_rejected` | kalıcı |
| `TrendyolValidationError` | `validation` | kalıcı (istemci tarafı parametre hatası) |
| diğer `TrendyolError` | `trendyol` | kalıcı |
| beklenmeyen istisna (veritabanı dahil) | `internal` | kalıcı, yalnız sınıf adı loglanır |

Yeniden deneme: `RetryStrategy(max_attempts=6, exponential_wait=4, retry_exceptions=[SyncTransientError])` (4, 16, 64, 256, 1024 sn). Kimlik bilgisi çözülemezse (`DecryptionError`, KEK eksik) hiçbir istek atılmaz ve sonuç `credentials_error` olur (hesap geçersiz sayılmaz: sorun satıcıda değil, yapılandırmadadır). 401/403'ten sonra hesap `invalid` olduğu için sonraki çalıştırmalar `inactive` döner; satıcı yeniden bağlanınca (`POST` aynı satıcı) hesap `active` olur ve yeni backfill kuyruğa girer.

`403` geçici de olabilir (IP/User-Agent/rol); talimat gereği `invalid` yapılır. Yanlış alarm riski §10'dadır.

## 6. Karar: ayrı worker rolü (S2 D-05)

ADR-0004 §5, `netkar_app`'in şifreli sütunlarda SELECT yetkisini senkron işçisi yazılırken ele almayı erteledi. Karar: **`netkar_worker` şifreli sütunları SELECT edebilen TEK roldür; `netkar_app` artık edemez** (migrasyon 0006).

| Rol | Giriş | Yetki özeti |
|---|---|---|
| `netkar_app` (API) | evet | `marketplace_accounts`: şifreli sütunlar HARİÇ sütun düzeyi SELECT; INSERT; UPDATE yalnız gerekli sütunlar (şifreli sütunları YAZABİLİR: bağlantı ekleme, yeniden bağlama, iptal çalışır). Yeni veri tablolarında yalnız SELECT; `product_costs` INSERT/UPDATE; `returns.returned_to_stock` UPDATE. `procrastinate_jobs` iş ekler |
| `netkar_worker` | evet | `marketplace_accounts`: tüm sütunlar SELECT, UPDATE yalnız `status`, `updated_at` (geçersizleştirme). Yeni veri tablolarında SELECT, INSERT, UPDATE (`product_costs` yalnız SELECT). `audit_log` SELECT/INSERT. `rate_limits` SELECT/DELETE (temizlik görevi). procrastinate tabloları |
| `netkar_sync_gate` | hayır | `sync_gate.syncable_accounts` işlevinin sahibi; `marketplace_accounts(id, tenant_id, status, created_at)` ve `sync_cursors(hesap, source, backfill_completed_at)` sütunlarını okur, yalnız bu rol için açık adlandırılmış `FOR SELECT` politikalarıyla |

- **RLS worker için de geçerlidir.** Politika `tenant_isolation` rol ayrımı yapmaz: worker kiracı bağlamı olmadan hiçbir satır göremez, başka kiracıya yazamaz (`WITH CHECK`). Her iş adımı kendi işlemini ve bağlamını kurar (`app.db.rls.tenant_transaction`, `set_config(..., true)` işlem yereldir, havuzdaki bağlantıya sızmaz).
- **Kiracı bağlamsız tek yol `sync_gate.syncable_accounts(account_id DEFAULT NULL)`'dir** (`SECURITY DEFINER`, sabit `search_path`, `PUBLIC`'ten kapalı, `EXECUTE` yalnız `netkar_worker`'a, `netkar_app` kullanamaz). Döndürdüğü: kiracı, hesap kimliği, backfill'i tamamlanmış kaynak listesi. Sır ve durum dışı veri YOKTUR; yalnız `active` hesapları görür. Planlayıcı hesapları buradan listeler, görev `account_id` argümanından kiracıyı yine buradan çözer (`sync.backfill(account_id)` imzası korunur; sahte `account_id` kiracı bulamazsa iş `inactive` döner).
- **Worker uygulama rolüne geri düşmez.** `WORKER_DATABASE_URL` yoksa worker başlamaz (`Settings.worker_libpq_url` hata verir). Sessiz geri düşme, senkronu çalışır gösterip kimlik bilgisi okurken patlatırdı.
- **API'nin kuyruğa iş eklemesi** `netkar_app` ile yapılır: procrastinate'in `defer` işlevleri tablo yetkisiyle çalışır, `netkar_app` 0002'de bu yetkiyi almıştı.
- **Operasyon.** Roller migrasyondan ÖNCE superuser tarafından kurulur (`netkar_owner` `CREATEROLE` değildir; migrasyon rol yoksa açık iletiyle durur). Yeni kurulum: `infra/postgres/init/01-roles.sh` (`NETKAR_WORKER_PASSWORD` gerekir). Mevcut veri dizini: `app.db.provision.provision_roles` (idempotent) veya elle:

  ```sql
  CREATE ROLE netkar_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD '<parola>';
  CREATE ROLE netkar_sync_gate NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  GRANT netkar_sync_gate TO netkar_owner WITH INHERIT FALSE, SET TRUE;
  GRANT CONNECT ON DATABASE netkar TO netkar_worker;
  ```

  Sonra `make migrate`, sonra `WORKER_DATABASE_URL`'u worker'a verin (API'ye VERMEYİN). Geri alma: `alembic downgrade 0005` grantleri geri alır (`netkar_app` tablo düzeyi SELECT'e döner), işlevi ve tabloları düşürür (YALNIZ bu migrasyonun eklediği veri kaybolur); roller kümeye aittir, bırakılır.

## 7. Karar: motor bağlantısı

`app/services/profit_feed.py::build_profit_input(db, tenant_id, account_id, start, end, settings)` motorun tek girdisini (`ProfitInput`) kurar; `app/services/profit_report.py` dönem (`period_profit`) ve ürün (`product_profit`) özetini hesaplar. API uçları `app/api/v1/profit.py` (aşağıda).

- **Dönem:** sipariş paketi `ordered_at` İstanbul takvim günü [start, end] içindeyse. Ekstre, iade ve kargo kalemleri bu siparişlerin numarasıyla eşlenir. Siparişe bağlanamayan `otherfinancials` iki kuralla seçilir: (a) `paymentOrderId` dönemdeki hakedişlerden biriyle aynı (hizmet bedeli, K13), (b) siparişe bağlı değil ve işlem tarihi (yoksa ödeme tarihi) dönemde (stopaj, bağsız ceza, erken ödeme). Kargo faturasında dönemdeki bir siparişe dokunan faturanın TÜM kalemleri verilir (KDV tespiti fatura toplamını kalem toplamıyla karşılaştırır, K08).
- **Eşleme `schema_v1.parse_input` ile aynı kuralları izler** (örn. `unit_gross = lineGrossAmount`), bu yüzden `tests/test_feed_golden_database.py` 41 altın senaryonun 38'ini sahte Trendyol -> gerçek senkron -> PostgreSQL (worker rolü) -> besleyici (API rolü) -> motor yolundan geçirir ve sonucun doğrudan motor çıktısıyla BİREBİR (tüm alanlar) ve altın `beklenen` ile kuruşu kuruşuna aynı olduğunu doğrular. G24-G26 (reklam) hariçtir: reklam kayıtları (`ad_spend`) sonraki turdadır.
- **Tahmin uydurulmaz.** Oranı (KDV veya komisyon) ne satırda ne ürün kartında olan satır, kalem kırılımı tutarsız satır, sipariş numarası/barkodu eksik ekstre satırı motora verilmez ve `FeedNotes` sayaçlarında görünür.
- **Ceza ve erken ödeme sınıflandırması okuma anında yapılır** (`financial_classes.DEFAULT_CLASS_RULES`: `DeductionInvoices` + metinde "ceza" ve "erken ödeme hizmet"). Metinler KURGUSALDIR ve canlıda doğrulanmamıştır (docs/12 §9 madde 7); eşleşmeyen satır `siniflandirilmamis_kesinti` olarak ihtiyatla kâra yansır. Okuma anında olduğu için tablo düzeltilince eski satırlara da uygulanır.
- **Rapor API'si (S4 paneli için, salt okuma, tüm roller):** `/v1/marketplace-accounts/{id}/profit/` altında `summary`, `products` (sıralı, süzgeçli, imleç sayfalı liste), `products/{barcode}`, `orders/{order_number}` ve `alerts`. Dönem `start`+`end` (İstanbul günü, uçlar dahil) ya da `range=today|7d|30d`; verilmezse 30 gün; en fazla 92 gün (aşımda 422). Bir istek motoru dönem için EN FAZLA BİR KEZ çalıştırır (CPU işi iş parçacığında) ve ürün, sipariş, uyarı görünümlerini dönem sonucundan seçer; sayfa değişimi yeni istektir ve motoru yeniden çalıştırır (önbellek yok, kiracı başına dakikada 60 rapor isteği sınırı `rate_limit_profit_report_tenant`). Motor blokları motorun KABLO adlarıyla (`schema_v1.render_result` ile birebir, `tests/test_report_golden_api.py` 38 altın senaryoyu API'den doğrular), zarf alanları İngilizce snake_case'tir; para JSON'da iki ondalıklı dizgedir. Uyarılar yalnız motorun ürettiği kodlardır; motorun üretmediği (`REKLAM_KARI_YIYOR`, `IADE_ORANI_ARTISI`) yanıtta `not_yet_available` olarak bildirilir. Kâr ayarları için tek değişiklik noktası `profit_settings_for` (kiracı ayar tablosu gelene dek motor varsayılanları: tarifesiz satır `KARGO_TARIFESI_EKSIK` uyarısı alır).
- İşlem ayarları (`ProfitSettings`: kargo tarifesi, hizmet bedeli tahmini, KDV oranları) çağıranın verdiği nesnedir; kiracı ayar tablosu sonraki turdadır.

## 8. Karar: PII

- Hiçbir tabloda ad, soyad, adres, telefon, TCKN, e-posta, koordinat, vergi bilgisi veya müşteri notu sütunu yoktur (`test_no_table_has_a_customer_pii_column`). `orders.province` ve `province_code` yalnız il adı ve kodudur.
- **Kanıt:** `tests/test_sync_pii.py` tüm Trendyol uç noktalarını (sipariş stream'i, iade, ekstre, kargo, ürün) sahte sentinel kişisel verili fixture'larla sürer; sonra `public` şemadaki HER tablonun HER satırı (JSON) ve yakalanan TÜM loglar taranır, hiçbir sentinel yoktur. Hata yolları (sunucu hatası, yetki hatası, bozuk gövde) için aynı tarama yapılır. Atma noktası değişmedi: PII, istemcide pydantic ayrıştırması sırasında düşer (ADR-0003 §5); bu katman yalnız modeller üzerinde çalışır.
- **`orders.customer_key` (takma adlı müşteri anahtarı) BOŞ kalır.** `customerId` modellenmez (ADR-0003 §5) ve hukuk onayı (K-N07 madde 16: takma adlı veri EK-6 md. 4.2 "kayıt yaratma yasağı" karşısında kabul edilebilir mi) yoktur. Sütun ve HMAC çekirdeği (`app.core.pseudonym.customer_key`: kiracı + hesap bağlı, ana anahtardan türetilmiş anahtarla HMAC-SHA256) hazırdır ve testlidir; onay gelirse HMAC ham değer model katmanına girmeden istemci içinde hesaplanmalıdır. Senkron sütuna dokunmaz.
- **Serbest metin:** ekstre `description` (satıcının kendi hesap hareketi, 1000 karakterle sınırlı) ve `type_text` tutulur; müşteri sorusu metni senkronlanmaz.

## 9. Reddedilen alternatifler

- **Para alanları `NUMERIC(18,2)` veya kuruş tamsayı:** girdiyi yuvarlar, §2.
- **Ham yanıtı JSON olarak saklamak:** PII diske girer (ADR-0003 §8).
- **İlerlemeyi `sync_runs` yerine yalnız imleçte tutmak:** kullanıcıya ilerleme çubuğu ve hata sınıfı gösterilemez.
- **Her pencere için ayrı `sync_runs` satırı:** satır sayısı patlar; kaynak başına bir satır ve `windows_done` sayacı yeter.
- **Worker için `BYPASSRLS` rolü:** RLS'nin ikinci kilit olma amacını bozar. Kiracı bağlamlı rol + dar kapı işlevi seçildi.
- **`sync_gate` yerine worker'a `marketplace_accounts` üzerinde bağlamsız SELECT politikası:** worker her zaman tüm kiracıların hesap satırlarını (şifreli sütunlar dahil) görürdü; işlev yalnız kimlik, kiracı ve backfill durumu verir.
- **Kilidi yalnız procrastinate `lock`'ına bırakmak:** kuyruk dışı çağrıları ve yinelenen worker kayıtlarını kapsamaz.
- **Kilit için işlem düzeyi advisory lock (`xact`):** senkron uzun sürer, işlemi dakikalarca açık tutmak gerekirdi.
- **Çekimi veritabanı işlemi içinde yapmak:** ağ beklemesi sırasında bağlantı ve kilit tutulurdu (ADR-0003 §4 ile aynı ilke).
- **`order_lines` için ayrı `order_line_items` tablosu:** §2.

## 10. Açık sorular, riskler ve sonraki tur

1. **`sync_runs` büyümesi.** Artımlı çekim her 15 dakikada hesap başına iki satır ekler (yaklaşık 70 bin satır/yıl/hesap); saklama süresi veya özetleme yok. `DELETE` yetkisi bilinçli olarak verilmedi. Öneri: ay bölümleme + eski bölümü bırakma (operatör işlemi) veya bir saklama kararı.
2. **403 geçici olabilir** (IP, User-Agent, rol). Talimat gereği 401 ve 403 hesabı `invalid` yapar; yanlış alarm olursa satıcı "yeniden bağlan" görür. Canlı pilotta 403 nedenlerinin ayrışması (K-N07 madde 3, 14) gerekir.
3. **Kovalar süreç içi** (ADR-0003 §3); worker sayısı 1'i aşarsa kova durumu PostgreSQL'e taşınmalı. Worker eşzamanlılığı `procrastinate worker --concurrency 4` ile verilir; tek uzun backfill diğer hesapların 15 dakikalık çekimini bloklamaz.
4. **Ekstre örtüşmesi 7 gün ve geriye bakma 89 gün tahminidir.** Ekstre satırlarının gerçek gecikme dağılımı canlı pilotla ölçülmeli; `transactionDate` ile ekranda görünme arasındaki fark bilinmiyor (K-N07 madde 5).
5. **Ekstre tip adları canlıda doğrulanmadı** (K-N07 madde 6, docs/12 §9 madde 4). Tipler tek tek (liste uzunluğu 1) istenir. Trendyol bir tip adını reddederse (400) yalnız o istek atlanır; `sync_runs.skipped_count` artar ve uyarı loglanır (tip adı), diğer tipler ve pencereler sürer. Atlanan tipin verisi eksik kalır (örn. yanlış yazılmış `DeliveryFee` K29 satırlarını getirmez): pilotta `skipped_count > 0` bir uyarı olarak izlenmeli, düzeltme `sources.SETTLEMENT_TYPES` ve `OTHER_FINANCIAL_REQUESTS` listelerindedir.
6. **Planlayıcı kalıcı hatalı kaynağı her 15 dakikada yeniden dener** (protokol hatası, doğrulanmamış tip). Trendyol'a gereksiz yük ve sürekli `failed` satırı üretir; öneri: kaynak başına hata sayacı ve bekleme (sonraki tur).
7. **Ürün kataloğunda silinen/arşivlenen ürünler** `products`'ta kalır (silme yok); `archived`/`onSale` bayrağı modellenmedi.
8. **Reklam kayıtları (`ad_spend`) ve maliyet Excel içe aktarma** sonraki tur; kiracı ayar tablosu (kargo tarifesi, hizmet bedeli) da.
9. **KMS** hâlâ faz 2 (ADR-0004). Worker ortamı KEK'leri taşır; worker kimlik bilgisi sızıntısında anahtarlar çözülebilir (rol ayrımı API'nin ele geçirilmesinden korur, worker'ın ele geçirilmesinden korumaz).
10. Zaman damgası: `orderDate` "GMT+3" etiketi belirsiz (K-N07 madde 8). `ordered_at` ham epoch'a göre saklanır; dönüşüm gerekirse tek migrasyonla düzeltilir.

## 11. Sonuçlar

- Trendyol verisi artık kalıcı ve motorla uçtan uca doğrulanmış; senkron idempotent, kaldığı yerden devam eden ve hesap başına çakışmasız.
- S2 D-05 tamamen kapandı: API, pazaryeri sırlarını veritabanından okuyamaz; yalnız worker okur ve RLS ikisi için de geçerlidir.
- Sonraki tur: (`/v1` rapor uçları ve maliyet Excel içe aktarma tamamlandı),  `ad_spend`, kiracı ayar tablosu, `sync_runs` saklama, planlayıcı geri çekilmesi, canlı pilotla fixture/tip adı/ceza metni doğrulaması.
- Sonraki tur (S3 YB-01): çok süreçte kiracı kilidi ve ayrıştırma yuvaları `pg_try_advisory_lock`'a taşınmalı (maliyet içe aktarma kapısı `import_gate.py` bugün süreç içidir; `--workers N` veya çok kopya öncesinde yapılmalı, yuva sayısı süreç sayısına bölünmeli). Yalnız not; uygulama yok.
