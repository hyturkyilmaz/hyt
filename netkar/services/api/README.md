# NetKâr API

FastAPI (Python >= 3.12), SQLAlchemy 2 (async), Alembic, PostgreSQL 16 (RLS), procrastinate (PostgreSQL tabanlı kuyruk). Ürün adı tek ayardan okunur: `PRODUCT_NAME`. Mimari karar kayıtları: [`0001` RLS ve kimlik doğrulama](../../docs/adr/0001-rls-ve-kimlik-dogrulama.md), [`0002` istemci IP'si](../../docs/adr/0002-istemci-ip-ve-vekil-guveni.md), [`0003` Trendyol istemcisi](../../docs/adr/0003-trendyol-istemcisi.md), [`0004` zarf şifreleme](../../docs/adr/0004-zarf-sifreleme.md), [`0005` Trendyol verisi, senkron ve worker rolü](../../docs/adr/0005-senkron-ve-depolama.md).

## Kurulum

Gereksinimler: [uv](https://docs.astral.sh/uv/), Docker (yalnız yerel çalıştırma için PostgreSQL), `openssl`.

```sh
cd netkar
make setup      # uv sync
make env        # infra/.env üretir (rastgele parolalar ve DATA_ENCRYPTION_KEY)
make db-up      # PostgreSQL 16 (roller 01-roles.sh ile kurulur)
make migrate    # alembic upgrade head (netkar_owner rolüyle)
make dev        # http://127.0.0.1:8000  (OpenAPI: /v1/openapi.json, prod'da kapalı; uvicorn --no-proxy-headers)
make worker     # procrastinate worker (`sync` ve `default` kuyrukları: senkron işleri, planlayıcılar, rate limit temizliği; `alerts` kuyruğunu ALMAZ); WORKER_DATABASE_URL ister
make worker-alerts  # AYRI procrastinate süreci, yalnız `alerts` kuyruğu (uyarı değerlendirmesi, ADR-0009 D4)
```

Uyarı değerlendirmesi kâr motorunu çalıştırır (CPU işi); senkronu bekletmesin diye ayrı süreçte (`worker-alerts`, eşzamanlılık 1) koşar. İki worker da çalışmazsa değerlendirme ya da senkron durur: `docker compose` her ikisini de başlatır, yerelde iki terminal (`make worker`, `make worker-alerts`) gerekir.

Tüm yığın (api, worker, worker-alerts, migrate, postgres) için: `docker compose -f infra/docker-compose.yml up --build`. Web servisi `--profile web` ile eklenir (apps/web hazır olunca).

`make dev` e-postaları `var/outbox.jsonl` dosyasına yazar (gövdede sıfırlama bağlantısı olur, log'a token yazılmaz).

## Test ve lint

```sh
make lint       # ruff check, ruff format --check, mypy (strict)
make test       # pytest + kapsam (eşik %90)
```

Testler gerçek PostgreSQL 16 kullanır:

- `TEST_DATABASE_URL` yoksa `/usr/lib/postgresql/16/bin` (`PG_BIN` ile değişir) altındaki `initdb`/`pg_ctl` ile oturum boyunca geçici bir küme başlatılır (tmp dizin, rastgele port, yalnız unix socket). Root olarak çalışılıyorsa komutlar `postgres` OS kullanıcısına geçirilerek çalıştırılır.
- `TEST_DATABASE_URL` verilirse (CI) bu bir **yönetici (superuser)** bağlantısı olmalıdır, örn. `postgresql://postgres:...@localhost:5432/postgres`. Testler rastgele adlı bir veritabanı ve `netkar_*` rolleri kurar, migrasyonları çalıştırır, bitince veritabanını düşürür.
- Uygulama testlerde de `netkar_app` rolüyle (superuser olmayan, RLS'ye tabi) bağlanır; tablo temizliği ve doğrulama için ayrı yönetici bağlantısı kullanılır.

Senkron ve depolama testleri: `tests/test_sync_schema.py` (migrasyon 0006, RLS, rol yetkileri, sync_gate), `tests/test_sync_mappers.py`, `tests/test_sync_runner.py` ve `tests/test_sync_edge.py` (backfill, artımlı çekim, idempotentlik, yeniden başlama, kilit, 401/403, hata sınıfları), `tests/test_sync_worker.py` (görevler, planlayıcı, kuyruk, bağlantı eklenince backfill), `tests/test_sync_pii.py` (hiçbir tabloda ve logda müşteri verisi yok), `tests/test_feed_database.py` ve `tests/test_feed_golden_database.py` (38 altın senaryo veritabanı yolundan, motor çıktısıyla birebir). Ortak fixture'lar `tests/sync_fixtures.py` (conftest `pytest_plugins`) ve `tests/sync_helpers.py` (sahte Trendyol API'si).

Önemli test dosyaları: `tests/test_rls_idor.py` (kiracı izolasyonu: uç noktalar ve doğrudan SQL), `tests/test_auth_flow.py`, `tests/test_totp.py`, `tests/test_password_reset.py`, `tests/test_rate_limit.py`, `tests/test_logging.py` (maskeleme), `tests/test_http_hardening.py` (güvenlik başlıkları, RFC 9457), `tests/test_migrations.py` (geri alınabilirlik), `tests/test_client_ip.py` ve `tests/test_limits.py` (istemci IP çözümleyici, gövde sınırı), `tests/test_denetim_s1_regression.py` (S1 güvenlik denetimi PoC'lerinin tersine çevrilmiş regresyon testleri).

## Ortam değişkenleri

Örnek değerler: [`infra/.env.example`](../../infra/.env.example). Sır repoya girmez.

| Değişken | Zorunlu | Varsayılan | Açıklama |
|---|---|---|---|
| `DATABASE_URL` | evet | | Uygulama rolü (`netkar_app`, superuser DEĞİL). |
| `DATABASE_MIGRATION_URL` | migrasyonda | | Tablo sahibi rol (`netkar_owner`); yalnız Alembic okur. |
| `WORKER_DATABASE_URL` | worker'da | | Senkron işçisi rolü (`netkar_worker`, superuser DEĞİL, RLS'ye tabi): pazaryeri şifreli sütunlarını okuyabilen TEK rol. Yalnız worker süreci okur, API'ye VERİLMEZ; yoksa worker başlamaz, uygulama rolüne geri düşmez (ADR-0005 §6). |
| `DATA_ENCRYPTION_KEY` | evet | | AES-256-GCM ana anahtarı, 32 bayt base64 (`openssl rand -base64 32`). Alt anahtarlar (IP özeti, imzalı token) HKDF ile türetilir. |
| `PRODUCT_NAME` | hayır | `NetKâr` | Ürün adı (TOTP yayıncı adı, e-posta metinleri, API başlığı). |
| `ENVIRONMENT` | hayır | `dev` | `dev`, `test`, `staging`, `prod`. `staging` ve `prod`'da OpenAPI belgesi kapalı, `DEBUG` yasak, `DATA_KEKS`/`DATA_KEK_ACTIVE` zorunludur (çerezler her ortamda `Secure`, yani ikisi de yalnız HTTPS). Farklar: `prod` `EMAIL_BACKEND=file/memory` ile açılmaz (gerçek arka uç gerekir); `staging` `file` ile açılır (dışarıya e-posta gitmez, bilinçli), `memory` ile ve `TRENDYOL_ENVIRONMENT=live` ile açılmaz. Açılış kilidi iki yönlüdür: `prod` işaretli veritabanıyla AÇILMAZ, `staging` işaretsiz veritabanıyla AÇILMAZ (DT-21; `mark-non-prod` bir kez çalıştırılmalı); `dev`/`test`'te sorgu atılmaz. `staging`'de `EMAIL_DEV_OUTBOX_PATH` mutlak yol olmalıdır (DT-20). |
| `LOG_LEVEL` | hayır | `INFO` | JSON log seviyesi. |
| `PWNED_CHECK_ENABLED` | hayır | `false` | HIBP k-anonimlik kontrolü (dış ağ çağrısı yapar). |
| `TRUSTED_PROXY_CIDRS` | hayır | boş | Güvenilir vekil ağları (virgülle ayrılmış CIDR, örn. web konteyner ağı). Eş adres bu listedeyse `X-Forwarded-For` sağdan sola okunur, listedeki adresler atlanır. Boşsa başlık yok sayılır ([ADR-0002](../../docs/adr/0002-istemci-ip-ve-vekil-guveni.md)). |
| `TRUSTED_PROXY_HOPS` | hayır | `0` | Sağdan sayılan güvenilir vekil sayısı (eş adres dahil). BFF arkasında tek vekil için `1`. CIDR ile birlikte de kullanılabilir. |
| `DEBUG` | hayır | `false` | Yalnız geliştirme. `ENVIRONMENT=prod` ya da `staging` iken açıksa (veya `prod` iken `EMAIL_BACKEND=file/memory` ise) uygulama başlamaz. |
| `RATE_LIMIT_TOTP_IP` | hayır | 30 | 15 dakikada TOTP doğrulama denemesi (IP başına). |
| `TOTP_MAX_FAILURES` / `TOTP_LOCK_SECONDS` | hayır | 5 / 900 | Ardışık hatalı TOTP kodunda hesabın geçici kilit eşiği ve süresi (429 `totp-locked`). |
| `MAX_REQUEST_BODY_BYTES` / `MAX_AUTH_BODY_BYTES` | hayır | 1 MiB / 64 KiB | İstek gövdesi üst sınırı (genel / `/v1/auth/*`). Aşımda 413 problem+json, işleyici çağrılmaz. |
| `PASSWORD_HASH_CONCURRENCY` | hayır | min(4, CPU) | Aynı anda çalışan argon2 özet sayısı (her biri ~64 MiB). Özetler iş parçacığı havuzunda çalışır, olay döngüsünü bloklamaz. |
| `EMAIL_BACKEND` | hayır | `file` | `file` (JSONL) veya `memory` (test). Gerçek servis yok. |
| `EMAIL_DEV_OUTBOX_PATH` | hayır | `var/outbox.jsonl` | `file` arka ucunun yazdığı dosya. `staging`'de mutlak yol (`..` içermeyen) ZORUNLU, aksi halde uygulama başlamaz. **Outbox gizli veridir** (alıcı adresi ve ham sıfırlama bağlantısı içerir, DT-20): dosya 0600 ile açılır (simgesel bağ izlenmez; düz, bu sürecin sahipliğinde ve tek bağlı olmalı), eksik dizinlerin her biri 0700 ile oluşturulur (var olan dizinlerin izni değişmez); `staging`/`prod`'da üst dizin grup/diğer yazılabilir ise uygulama başlamaz; yedeğe, günlük toplayıcıya ya da paylaşılan birime koymayın. |
| `EMAIL_OUTBOX_MAX_BYTES` | hayır | `262144` | Etkin outbox bu boyutu aşınca döndürülür (`<ad>.<UTC damga>-<sıra>`, 0600). En az 1024. |
| `EMAIL_OUTBOX_MAX_FILES` | hayır | `5` | 1-50. Tutulan döndürülmüş dosya sayısı; fazlası en eskiden başlayarak silinir. |
| `EMAIL_OUTBOX_RETENTION_DAYS` | hayır | `7` | 1-30 gün. Döndürülmüş dosyalar bundan eskiyse silinir (açılışta ve her gönderimde). Silme yalnız yapılandırılan dizinde ve adı bu kalıba uyan düz dosyalara dokunur. |
| `WEB_BASE_URL` | hayır | `http://localhost:3000` | Sıfırlama bağlantılarındaki web adresi. |
| `ALERT_NOTIFICATIONS_ENABLED` | hayır | `false` | Uyarı e-postalarının GERÇEK gönderimi (ADR-0009 D5). Kapalıyken gerçek arka uç asla çağrılmaz, outbox satırı `suppressed` olur; ileti yalnız yerel arka uca (`file`/`memory`) yazılır. Açmak Hasan onayıdır (H6; gerçek sağlayıcı kararı H5/K12). Aşağıdaki "Bildirim dağıtıcısı" bölümüne bakın. |
| `NOTIFY_UNSUBSCRIBE_TTL_DAYS` | hayır | `90` | 1-365. Tek tık kapatma bağlantısının ömrü. İmza anahtarı ayrı sır değildir: `DATA_ENCRYPTION_KEY`'den `notify-unsub` amacıyla türetilir. |
| `RATE_LIMIT_NOTIFY_UNSUBSCRIBE_IP` | hayır | 30 | `POST /v1/notifications/unsubscribe` için IP başına saatlik sınır; yalnız doğrulaması BAŞARISIZ denemelere işler. |
| `RATE_LIMIT_NOTIFY_UNSUBSCRIBE_TOKEN` | hayır | 10 | Aynı (geçerli) token için saatlik sınır (token özeti başına). |
| `RATE_LIMIT_LOGIN_IP` / `_LOGIN_EMAIL` | hayır | 30 / 10 | 15 dakikalık pencerede giriş denemesi sınırı. |
| `RATE_LIMIT_REGISTER_IP` | hayır | 10 | 1 saatte kayıt sınırı (IP). |
| `RATE_LIMIT_RESET_IP` / `_RESET_EMAIL` | hayır | 10 / 3 | 1 saatte sıfırlama isteği sınırı. |
| `RATE_LIMIT_TOTP_USER` | hayır | 10 | 15 dakikada TOTP doğrulama denemesi (kullanıcı başına). |
| `TRENDYOL_ENVIRONMENT` | hayır | `stage` | `stage` veya `live`. Canlıya yalnız açıkça geçilir. |
| `TRENDYOL_INTEGRATOR_NAME` | hayır | `NetKar` | User-Agent'taki entegratör adı (`"{sellerId} - {ad}"`): yalnız ASCII harf/rakam, en fazla 30 karakter. Geçersizse uygulama açılmaz. |
| `TRENDYOL_CONNECT_TIMEOUT_SECONDS` / `TRENDYOL_READ_TIMEOUT_SECONDS` | hayır | 5 / 20 | Bağlantı ve okuma zaman aşımı. |
| `TRENDYOL_MAX_RETRIES` | hayır | 4 | 429, 5xx ve ağ hatasında yeniden deneme sayısı (üst sınır 10). |
| `TRENDYOL_BACKOFF_BASE_SECONDS` / `TRENDYOL_BACKOFF_CAP_SECONDS` | hayır | 1 / 30 | Üstel geri çekilme tabanı ve üst sınırı (saniye). |
| `DATA_KEKS` / `DATA_KEK_ACTIVE` | prod'da evet | | Pazaryeri anahtarları için zarf şifreleme KEK halkası: `kid:base64,kid2:base64` ve etkin kid (ADR-0004). Boşsa yalnız prod dışında `DATA_ENCRYPTION_KEY`'den türetilen geliştirme KEK'i kullanılır. |
| `RATE_LIMIT_MARKETPLACE_IP` / `_TENANT` | hayır | 20 / 10 | 1 saatte bağlantı ekleme denemesi (IP / kiracı); her deneme Trendyol'a doğrulama çağrısı yapar. |
| `RATE_LIMIT_MARKETPLACE_GLOBAL_PER_MINUTE` | hayır | 60 | Tüm kiracılar için dakikalık platform tavanı; aşılınca Trendyol'a gidilmez, 503 `marketplace-busy`. |
| `TRENDYOL_VALIDATION_MAX_WAIT_SECONDS` / `_DEADLINE_SECONDS` | hayır | 5 / 15 | Bağlantı doğrulama isteği içinde toplam bekleme bütçesi (Retry-After, kova, geri çekilme) ve toplam son tarih. Senkron işleri bu sınırlara tabi değildir. |
| `MAX_MARKETPLACE_BODY_BYTES` | hayır | 8192 | `/v1/marketplace-accounts` gövde üst sınırı. |

Oturum süreleri (boşta 12 saat, mutlak 30 gün), sıfırlama token ömrü (30 dk) ve deneme süresi (14 gün) `app/core/config.py` içinde ayarlanabilir alanlardır.

## Uç noktalar (v1)

| Yöntem | Yol | Açıklama |
|---|---|---|
| GET | `/v1/health`, `/v1/health/ready` | Canlılık (DB'siz), hazırlık (`SELECT 1`) |
| GET | `/v1/auth/csrf` | CSRF çerezi üretir, değeri döndürür |
| POST | `/v1/auth/register` | Hesap oluşturur (her durumda 202, varlık sızdırmaz) |
| POST | `/v1/auth/login` | `ok` veya `totp_required` |
| POST | `/v1/auth/totp/verify` | Girişte ikinci adım |
| POST | `/v1/auth/logout` | Oturumu iptal eder (idempotent) |
| GET | `/v1/me` (`/v1/auth/me`) | Kullanıcı, rol, kiracı |
| POST | `/v1/auth/totp/setup`, `/v1/auth/totp/enable` | TOTP kurulumu ve etkinleştirme |
| POST | `/v1/auth/password-reset/request`, `/confirm` | Parola sıfırlama (tek kullanımlık, 30 dk) |
| GET | `/v1/tenant/members`, `/sessions`, `/audit` | Kiracı kapsamlı okuma (sessions ve audit: owner/admin) |
| POST | `/v1/marketplace-accounts` | Trendyol bağlantısı ekler (owner/admin). Gövde: `seller_id`, `api_key`, `api_secret`. Anahtarlar önce Trendyol'da doğrulanır; başarısızsa kaydedilmez. 201 maskeli özet, 409 etkin bağlantı var, 422 anahtar reddedildi, 502/503 Trendyol ulaşılamaz |
| GET | `/v1/marketplace-accounts` | Bağlantılar (maskeli: yalnız anahtarın son 4 hanesi) |
| POST | `/v1/marketplace-accounts/{id}/revoke` | Bağlantıyı iptal eder (owner/admin): durum `revoked`, şifreli anahtarlar boşaltılır, satır silinmez, denetim kaydı yazılır |

Durum değiştiren her istek `X-CSRF-Token` başlığı ve `__Host-nk_csrf` çerezini birlikte ister (önce `GET /v1/auth/csrf`). Hatalar `application/problem+json` (RFC 9457) biçimindedir.

## Ürün listesi: maliyeti eksik süzgeci (`GET /v1/marketplace-accounts/{id}/products`)

Sorgu parametreleri: `limit` (1-200, varsayılan 50), `after` (önceki sayfanın `next_cursor`'ı; keyset, barkoda göre artan), `q` (barkod ya da başlıkta arama) ve **`missing`** (bool, varsayılan `false`). Sözleşme değişikliği (geriye uyumlu, yalnız ekleme):

- `missing=true`: yalnız **bugün geçerli maliyet kaydı olmayan** ürünler. "Bugün", sunucunun maliyeti seçerken kullandığı İstanbul günüdür; kural motor ve `current_cost` ile aynıdır: `valid_from <= bugün` olan en az bir kayıt varsa maliyet vardır (eski kayıt, yeni kayıt gelene kadar geçerlidir; bitiş tarihi yoktur), yalnız gelecek tarihli kayıt varsa maliyet YOKTUR. Süzgeç sayfalamadan önce uygulanır: sayfalar (son hariç) `limit` kadar dolu gelir, `next_cursor` aynı barkod sırasıdır ve `q` ile birlikte kullanılabilir. Geçersiz değer (`missing=belki`) 422 verir. Kiracı kapsamı ve RLS değişmez (başka kiracının hesabı 404).
- Yanıta **`total_missing`** (int, her zaman var) eklendi: hesabın TÜM ürünleri içinde bugün geçerli maliyeti olmayanların sayısı; `q`, `after`, `limit` ve `missing` değerinden bağımsızdır (sayfa içeriğinden değil hesaptan sayılır, ekrandaki "N ürünün maliyeti eksik" rozeti için). Eski istemciler yeni alanı yok sayar; `items[].cost_missing` ve `next_cursor` anlamı aynıdır. **DT-19 kararı:** değer her sayfada ve her yanıtta dolu kalır (`after` olsa da `null` dönmez; web her sayfada okuyor, sözleşme değişmedi). Maliyet bilinçli kabul edildi: sayım tek anti-join'dir ve yukarıdaki indekslerle çalışır (plan testi Seq Scan olmadığını doğrular). Katalog çok büyürse sonraki adım, sayımı yalnız `after` yokken hesaplamak ya da ayrı önbellekli uca taşımaktır; o zaman istemciler ilk sayfadaki değeri saklamalıdır (şu an gerekmez).
- Sorgu planı: sayfa mevcut `uq_products_account_barcode` (sıralı tarama, keyset koşulu indeks koşulunda) ve `uq_product_costs_account_barcode_from` (anti-join) indekslerini kullanır; sayaç aynı indekslerle tek anti-join'dir. Yeni indeks ya da migrasyon gerekmedi; plan testi (`tests/test_product_costs_missing.py`) Seq Scan olmadığını ve LIMIT'te erken durduğunu satır sayısıyla doğrular (duvar saati eşiği yok).

## Demo veri tohumu

Kullanılabilirlik testi ve yerel demo için uydurma satıcı verisi ve moderatör "doğru cevap kartı" (kaynak: `docs/ux/kullanici_testi_plani_S4.md` §7.1). Üç demo kiracısı kurar: **Hesap A** (ayarsız, kısmi dönem; kargo tarifesi, hizmet bedeli ve varsayılan desi yok), **Hesap B veri seti X** ve **Y** (ayarlı; üç zarar rozeti, maliyeti eksik ürünler, çok ürünlü ve iadeli sipariş, ekstresi gelmeyen ve beklenmeyen kesintili siparişler, uyarı kartları).

```bash
# netkar/ dizininden (migrasyon yapılmış, infra/.env hazır)
NETKAR_ENV=local make seed-demo
NETKAR_ENV=local make seed-demo SEED_ARGS="--instance 2 --dataset x --as-of 2026-11-14"
# ya da services/api içinde
NETKAR_ENV=local uv run python -m app.tools.seed_demo --demo
```

Seçenekler: `--instance N` (1-99, her katılımcı için temiz Hesap A; G2 ve G3 ayarı değiştirir ve ayarlar silinemez), `--dataset x|y|all`, `--as-of YYYY-AA-GG` (verinin "bugünü"; varsayılan bugün, veri bundan en çok 27 gün geriye uzanır), `--a-variant positive|negative` (Hesap A bilinen kâr işareti), `--reset-passwords`, `--write-card` (kartı varsayılan yola, `docs/ux/demo_cevap_karti.md`, yazar) ve `--card-path` (kartı o dosyaya yazar). **Kart yalnız `--write-card` ya da `--card-path` verilince yazılır**; verilmezse hiçbir dosya yazılmaz. Çıktı: giriş tablosu (parolalar yalnız ekrana, bir kez; kart yazımı başarısız olsa bile önce gösterilir). **Tohum "üretim değil" işaretini YAZMAZ**; işaret ayrı bir provisioning adımıdır (`mark-non-prod` alt komutu, aşağıda).

**Koruma (üretimde çalışmaz).** Betik şu koşulların HEPSİ sağlanmazsa hiçbir şey yazmadan çıkış kodu 3 ile reddeder. Bir bölümü yapılandırmadır, bir bölümü bağlandıktan sonra sunucuya sorularak denetlenir; hepsi ilk yazımdan ÖNCE yapılır.

- Yapılandırma: `--demo` bayrağı; `NETKAR_ENV` açıkça `local`, `test` ya da `staging` (Makefile varsayılan atamaz); `ENVIRONMENT` `prod` değil; `TRENDYOL_ENVIRONMENT` `live` değil. Bağlantı dizeleri sürücünün (psycopg) yorumladığı gibi çözülür: sorguda `hostaddr`, `dbname`, `service`, `servicefile` varsa reddedilir; `host` URL'de sunucu yokken yalnız sorguda (unix soket dizini) verilebilir; boş sunucu (PGHOST'a düşer) ve çoklu sunucu reddedilir; `port` URL'de varken sorguda da verilirse reddedilir (psycopg sorgudaki değeri URL'dekinin üstüne yazar; belirsiz hedef); `local` iken sunucu açıkça `localhost`, `127.0.0.1`, `::1` ya da bilinen yerel soket dizini (`/tmp`, `/var/run/postgresql`, `/run/postgresql`) olmalı; `postgres` ve `db` gibi Docker ağı adları ve `/cloudsql/...` gibi uzak soketler yerel sayılmaz (Docker ağı için `NETKAR_ENV=test` ya da `staging`). Veritabanı adında `prod`, `canli` ya da `live` geçmez; `DATABASE_URL`, `WORKER_DATABASE_URL` (ve verilmişse `DATABASE_ADMIN_URL`) aynı sunucu, port ve veritabanına işaret eder.
- Bağlandıktan sonra: sunucunun kendi bildirdiği `current_database()`, `inet_server_addr()` ve `inet_server_port()` aynı denetimlerden geçer (`local` iken adres YALNIZ loopback olmalı; `test` ve `staging` iken loopback ya da özel ağ; unix soketinde adres yoktur). Sunucu kimliği de karşılaştırılır: migrasyon 0016 `deployment_marks.instance_id` (sunucuya özgü rastgele UUID) yazar; uygulama, işçi ve yönetici bağlantılarında bu değer aynı olmalıdır. Unix soketinde `inet_server_addr()` ve `inet_server_port()` NULL döner; aynı soket dizininde başka sunucuya yönlendirilmiş (ör. SSH ile) aynı adlı bir veritabanını ayıran değer budur. Roller doğrulanır: app bağlantısı `netkar_app`, worker bağlantısı `netkar_worker` olmalı ve ikisi de süper kullanıcı ya da BYPASSRLS olamaz.
- Veritabanında saklanan "üretim değil" işareti: `deployment_marks` tablosunda `non_production = 'true'` satırı (migrasyon 0015). **İşaret yoksa betik durur.** İşareti yalnız süper kullanıcı ya da `netkar_owner` yazabilir (uygulama ve işçi rolleri yalnız okur) ve bu **kurulum (provisioning) adımıdır, tohum komutunun parçası değildir**: ayrı alt komut, yalnız üretim dışı olduğundan emin olunan sunucuda, bir kez:

  ```bash
  # 1) Kimliği görmek için (yazmaz; sunucunun bildirdiği veritabanı, adres, port ve instance_id'yi basar)
  DATABASE_ADMIN_URL=... NETKAR_ENV=staging make mark-non-prod
  # 2) Ekrandaki kimliği doğrulayıp açık onayla (veritabani@instance_id birebir eşleşmeli)
  DATABASE_ADMIN_URL=... NETKAR_ENV=staging make mark-non-prod MARK_ARGS="--confirm netkar_staging@<instance_id>"
  ```

  Onay olmadan ya da yanlış onayla hiçbir şey yazılmaz (çıkış kodu 3). Alt komut tohumla aynı yapılandırma ve sunucu denetimlerini yapar; `DATABASE_ADMIN_URL` uygulamanın bağlandığı sunucuya (aynı `instance_id`) gitmelidir. Gerekçe (en basit güvenli tasarım): bağlantı dizesi ve ortam değişkenleri yanlış yönlendirilebilir, veritabanının kendisinde duran işaret yönlendirilemez; üretim veritabanına bu satırı yazan olmadığı sürece betik orada çalışmaz. **Ters yön de denetlenir:** `ENVIRONMENT=prod` iken API ve işçi açılışta bu satırı okur, varsa BAŞLAMAZ (`NonProductionMarkError`; staging dökümü üretime geri yüklendiyse ya da işaret yanlış sunucuya yazıldıysa sessiz kalmaz). **Staging için tersi (DT-21):** `ENVIRONMENT=staging` iken satır YOKSA (ya da tablo yoksa, değer `true` değilse, okunamıyorsa) API ve işçi BAŞLAMAZ; staging'e yanlışlıkla üretim veritabanı bağlanırsa sıfırlama bağlantıları düz metin outbox'a yazılmaz. Yeni staging veritabanında önce `mark-non-prod` çalıştırılmalıdır (hata iletisi komutu söyler); aynı 10 sn zaman aşımı ve açılmama ilkesi geçerlidir. **Kimlik yenileme (DT-17):** `instance_id` veritabanı içeriğidir, yani `pg_dump`/geri yükleme ya da fiziksel kopya onu da taşır. Bu yüzden `mark-non-prod` işareti YENİ yazarken aynı işlemde `instance_id`'yi de yeniler (`gen_random_uuid()`), yeni değeri ekrana basar; üretimden kopyalanmış bir staging, işaretlendiği anda üretimden ayrışır. İşaret zaten varsa (tekrar çalıştırma) kimlik değişmez. Yenileme sonrası `--confirm` için yeni kimlik gerekir. **Açılış denetimi (DT-18):** sorgu şema niteliklidir (`public.deployment_marks`; rolün `search_path`'i değişse de atlanmaz) ve API tarafında bağlantı ile sorgu birlikte 10 sn ile sınırlıdır (işçideki `connect_timeout=10` ile aynı); süre dolarsa doğrulanamayan `prod` açılmaz. Çalışma notu: `ENVIRONMENT=prod` ve `staging` açılışı veritabanı erişimi ister; veritabanı yokken api yeniden başlatma döngüsüne girer (bilinçli, açılmama ilkesi). Satırı kaldırmak bilinçli bir veritabanı işlemidir (süper kullanıcı: `DELETE FROM deployment_marks WHERE key = 'non_production'`). `COMMENT ON DATABASE` yerine tablo seçildi çünkü uygulama rolü okuyabilir ve yetki ayrımı (okuma serbest, yazma yönetici) sütun ve tablo yetkileriyle zorlanır. İşaret, ayrıca demo bayrağının da kapısıdır (aşağıda).
- Bu bir savunma katmanıdır; asıl sınır roller ve RLS'tir.

**Demo hesabı senkron dışı.** Betik pazaryeri hesaplarını `marketplace_accounts.is_demo = true` ile işaretler. `sync_gate.syncable_accounts` ve sync_gate politikası `NOT is_demo` ister, bu yüzden senkron zamanlayıcı ve çalıştırıcı demo hesabı hiç görmez: staging'de worker açık olsa da sahte anahtarla Trendyol'a istek atılmaz ve hesap `invalid` olmaz. `netkar_app` bu sütunu doğrudan yazamaz (INSERT ve UPDATE sütun düzeyinde, `is_demo` hariç); bayrağı yalnız `public.mark_demo_account(uuid)` açar: SECURITY DEFINER, kiracı RLS'i altında yalnız çağıranın kendi hesabına dokunur ve `non_production` işareti yoksa ve hiçbir satır güncellenmezse (kiracı bağlamı yok, hesap yok ya da başka kiracıda) hata verir (migrasyon 0016, `IF NOT FOUND`, SQLSTATE 42704); tohum çağrıdan sonra `is_demo`'nun gerçekten açıldığını da doğrular.

**Yetki yolları.** Süper kullanıcı kullanılmaz, RLS aşılmaz (yalnız `mark-non-prod` alt komutu işaret için `DATABASE_ADMIN_URL` kullanır, bir kez). Kiracı ve kullanıcı `auth_gate.register_account` ile (API kayıt yolu), pazaryeri hesabı, ürün maliyeti ve kâr ayarları `netkar_app` ile (API servisleri, kiracı bağlamı kurulu), ürün, sipariş, ekstre ve kargo faturası `netkar_worker` ile (senkron işçisinin yazma yolu, kiracı bağlamı kurulu) yazılır. Bu yüzden `DATABASE_URL` ve `WORKER_DATABASE_URL` birlikte gerekir.

**Ön denetim.** Tüm hesaplar için salt okuma ön denetim yazımdan önce yapılır: demo e-postası kayıtlıysa kiracısının tohumla oluşturulduğu (seed denetim işareti) doğrulanır, değilse betik durur ve o kullanıcının parolasına ve verisine dokunmaz (`--reset-passwords` dahil); tohum sürümü uyuşmazlığı da burada reddedilir (parola sıfırlanıp hesap kilitli kalmaz).

**Bakım notu (sütun yetkileri).** `netkar_app` INSERT yetkisi `marketplace_accounts` üzerinde sütun düzeyindedir (`is_demo` hariç). Modele yeni sütun eklerken migrasyona `GRANT INSERT (yeni_sutun) ON marketplace_accounts TO netkar_app` eklemek gerekir; unutulursa `tests/test_marketplace_accounts.py::test_app_role_column_insert_grants_match_the_orm_model` CI'da düşer (aksi halde hesap ekleme üretimde `permission denied` verirdi).

**KVKK ve sırlar.** Son müşteriye ait hiçbir alan yoktur (il bile yok); ürün, mağaza ve sipariş adları uydurmadır, e-postalar `example.com`. Pazaryeri anahtarları sahte yer tutucudur ve zarf şifreli saklanır (Trendyol'a doğrulama çağrısı YAPILMAZ). Parolalar depoda yoktur: yeni kullanıcı için çalışma anında rastgele üretilir ve bir kez yazılır; istenirse `NETKAR_DEMO_PASSWORD` kullanılır ve API'nin parola politikasından geçer (12-128 karakter, `PWNED_CHECK_ENABLED` açıksa sızmış parola denetimi; ekrana yazılmaz). Var olan kullanıcının parolası sorulmaz ve değişmez (`--reset-passwords` API'nin parola sıfırlama yoluyla yenisini üretir). Parolaları CI günlüklerinde saklanacak ortamda (staging dağıtım hattı) rastgele üretimle çalıştırmayın; `NETKAR_DEMO_PASSWORD` kullanın.

**Idempotency.** Doğal anahtarlar sabittir (sipariş no, paket no, barkod, işlem no); yeniden çalıştırma kayıt çoğaltmaz, `--as-of` ile tarihleri kaydırır. Kâr ayarları yalnız yoksa yazılır (katılımcının düzenlemesi ezilmez). Betik silmez: tohum sürümü (`SEED_VERSION`, `app/tools/demo_data.py`) değişirse aynı veritabanında yeniden tohumlama reddedilir (temiz veritabanı ya da başka `--instance`). Tohum tablosu ve cevap kartı kodu: `app/tools/demo_data.py`, `app/tools/demo_card.py`; testler: `tests/test_seed_demo.py`.

**Doğru cevap kartı.** Kartın hiçbir rakamı elle yazılmaz: tohumdan sonra gerçek kâr motoru ve rapor servisleri (`period_profit`, `profit_views`, kayıtlı ayarlar) çalıştırılır; testler kart değerlerini `/profit/summary`, `/products`, `/orders` ve `/alerts` yanıtlarıyla karşılaştırır. Kart tohum sürümünü, veri tarihini ve dönem aralığını yazar.

## Dizin yapısı

```
app/main.py            create_app fabrikası
app/core/              config, security, crypto, logging, errors, middleware, limits (gövde sınırı, IP rate limit), clientip, clock, ratelimit, email, pwned
app/db/                session, base, rls (bağlam), provision (rol kurulumu)
app/models/            ORM modelleri
app/api/v1/            auth, me, tenant, health, marketplace_accounts
app/integrations/trendyol/  TrendyolClient (tek HTTP noktası), modeller (PII yok), hız sınırı, pencere yardımcıları, hatalar
app/services/          auth (auth_gate çağrıları, oturum), audit, marketplace_accounts (şifreleme, istemci fabrikası), sync/ (senkron yürütücü, kaynaklar, eşlemeler, upsert), profit_feed (DB -> ProfitInput), profit_report (dönem ve ürün kâr özeti), financial_classes (ceza/erken ödeme metin eşlemesi)
app/worker/            procrastinate App, görevler (sync.backfill, sync.incremental, planlayıcılar, heartbeat, rate limit temizliği), çalışma zamanı (worker rolü), kuyruk (iş ekleme)
migrations/            Alembic (0001 şema + RLS + auth_gate, 0002 procrastinate, 0003 TOTP tekrar kullanım + kilit, 0004 marketplace_accounts, 0005 dar UPDATE yetkisi, 0006 Trendyol verisi + senkron durumu + worker rolü + sync_gate)
tests/fixtures/trendyol/  Resmi doküman örneklerinden türetilmiş, sahte kişisel veri içeren yanıt fixture'ları
```

## Senkron ve depolama (ADR-0005)

Trendyol verisi (ürün, sipariş paketi ve satırı, iade kalemi, ekstre, kargo faturası) hesap ve kiracı bağlı tablolarda saklanır (migrasyon 0006, hepsi `FORCE` RLS). Son müşteri adı, adresi, telefonu, TCKN'si ve e-postası hiçbir tabloda ve logda yoktur; yalnız il adı tutulur. Para alanları `NUMERIC(18,6)` (kuruş altı hassasiyet kayıpsız; yuvarlama yalnız motor çıkışında), oranlar `NUMERIC(9,4)`.

**Roller.** Üç ayrı kimlik: `netkar_owner` (migrasyon), `netkar_app` (API; şifreli anahtar sütunlarını okuyamaz), `netkar_worker` (senkron işçisi; okuyabilen tek rol). Roller migrasyondan ÖNCE superuser ile kurulur: yeni kurulumda `infra/postgres/init/01-roles.sh` (`NETKAR_WORKER_PASSWORD` gerekir). Var olan bir veri dizininde (betik yeniden çalışmaz) superuser ile:

```sql
CREATE ROLE netkar_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD '<parola>';
CREATE ROLE netkar_sync_gate NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT netkar_sync_gate TO netkar_owner WITH INHERIT FALSE, SET TRUE;
-- 0025 (uyarı ve bildirim tabloları, ADR-0009) için:
CREATE ROLE netkar_notify_gate NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT netkar_notify_gate TO netkar_owner WITH INHERIT FALSE, SET TRUE;
GRANT CONNECT ON DATABASE netkar TO netkar_worker;
```

(ya da Python'dan `app.db.provision.provision_roles`, idempotent). Sonra `make migrate` ve worker'a `WORKER_DATABASE_URL`. Migrasyon rol yoksa açık iletiyle durur. Geri alma: `alembic downgrade 0005` (yalnız 0006'nın eklediği veri kaybolur).

**İşler (procrastinate, kuyruk `sync`).** `sync.backfill(account_id)`: siparişler (son 89 gün, `orders/stream`, 14 günlük pencereler), iadeler, ürünler, ekstre (15 günlük pencereler, tip başına ayrı istek), kargo faturası kalemleri; ilerleme `sync_runs`'a, imleç `sync_cursors`'a yazılır, çökme sonrası kaldığı yerden devam eder. `sync.incremental(account_id, sources=None)`: imleçten (örtüşmeyle) devam eder. Periyodik planlayıcılar: sipariş ve iade 15 dakikada bir, ekstre günde 2 (03:07 ve 15:07 UTC), ürünler günde 1. Hesap başına çakışma yoktur (procrastinate `lock`, `queueing_lock` ve PostgreSQL danışma kilidi). 401/403 gelirse hesap `invalid` olur, denetim kaydı yazılır ve senkron durur; geçici hata (429, 5xx, ağ) üstel geri çekilmeyle yeniden denenir. Bağlantı eklenince (`POST /v1/marketplace-accounts`) backfill kuyruğa girer. Sağlık için: `SELECT source, status, windows_done, windows_total, error_class FROM sync_runs ORDER BY started_at DESC` (gövde ve ileti yok, yalnız sınıf).

**Motor bağlantısı.** `app.services.profit_feed.build_profit_input(db, tenant_id, account_id, start, end, settings)` veritabanı kayıtlarından `ProfitInput` kurar; `app.services.profit_report.period_profit` ve `product_profit` motoru çalıştırır (API ucu sonraki tur). RLS bağlamı çağıran tarafından kurulur (`app.db.rls.tenant_transaction`).

```python
async with tenant_transaction(sessionmaker, tenant_id) as session:
    report = await period_profit(
        session, tenant_id, account_id, date(2026, 10, 1), date(2026, 10, 31), settings
    )
    (
        report.totals.period_net_profit,
        report.notes.total,
    )  # notes: motora verilmeyen kayıt sayısı (eksik oran vb.)
```

## Trendyol entegrasyonu

Karar kaydı ve açık sorular: [ADR-0003](../../docs/adr/0003-trendyol-istemcisi.md). Yerel kaynak: `docs/research/01_trendyol_api.md` ve resmi doküman kopyası (`docs/research/trendyol_docs_ham/`, repoya alınmaz).

**Tek istemci kuralı.** Trendyol'a her HTTP çağrısı `app/integrations/trendyol/client.py` içindeki `TrendyolClient` üzerinden yapılır (httpx.AsyncClient). Başka bir yerde Trendyol'a doğrudan httpx çağrısı yasaktır; `tests/test_trendyol_client.py::test_only_the_client_module_imports_httpx_for_trendyol` bunu denetler.

```python
from pydantic import SecretStr
from app.integrations.trendyol import TrendyolClient, TrendyolConfig, TrendyolCredentials

credentials = TrendyolCredentials(seller_id="2738", api_key=SecretStr("..."), api_secret=SecretStr("..."))
async with TrendyolClient(credentials, TrendyolConfig()) as client:  # varsayılan ortam: stage
    check = await client.verify_connection()  # en hafif çağrı, ürün sayısı döner
    async for row in client.iter_settlements(["Sale"], start, end):  # 15 günlük pencereler otomatik
        ...
```

Salt okuma uç noktaları: sipariş paketleri (`get_shipment_packages` v2 ve cursor tabanlı `iter_shipment_packages_stream`), iadeler (`get_claims`, `iter_claims`), cari hesap ekstresi (`get_settlements`, `get_other_financials`, `iter_*` ile 15 günlük otomatik bölme, `get_payment_orders`), kargo faturası kalemleri (`iter_cargo_invoice_items`), onaylı ürünler v2 (`iter_approved_products`, 10.000 sonrası `nextPageToken`), müşteri soruları (`iter_questions`, yalnız çekme).

Kurallar:

- **Ortam.** `TRENDYOL_ENVIRONMENT=stage|live`, varsayılan `stage` (stage ortamı IP yetkilendirmesi ister; yetki yoksa 503 döner).
- **Kimlik.** Basic Auth (API anahtarı : sır) ve zorunlu `User-Agent: "{sellerId} - {TRENDYOL_INTEGRATOR_NAME}"`. Entegratör adı geçersizse (ASCII harf/rakam dışı, 30 karakterden uzun) ayar doğrulaması uygulamayı başlatmaz; istemci de kurulmaz.
- **Hız sınırı.** (satıcı, uç nokta grubu) başına token bucket: genel 10 sn'de 50, finans 100/dk, iade 1000/dk, sipariş 30/dk (seviyeye göre 30-100 arasından en tutucusu), stream en az 5 sn aralık. Süreç içi kova; birden çok worker süreci varsa toplam hız çarpılır (ADR-0003).
- **Yeniden deneme.** 429, 500/502/503/504 ve ağ hatalarında "eşit jitter" üstel geri çekilme (taban 1 sn, üst sınır 30 sn, en fazla `TRENDYOL_MAX_RETRIES`); `Retry-After` kırpılarak uygulanır. 401 ve 403'te yeniden deneme yok: `TrendyolAuthError` / `TrendyolForbiddenError`.
- **PII.** Müşteri adı, soyadı, adres, telefon, TCKN, e-posta, müşteri kimliği, kullanıcı adı, vergi no ve fatura bağlantısı hiçbir modelde tanımlı değildir (`extra="ignore"`); ham yanıt hiçbir yere loglanmaz. Teslimat adresinden yalnız il adı ve il kodu alınır. Çağrı meta logu yalnız yöntem, uç nokta grubu, durum, süre ve deneme sırasını içerir (gövde, sorgu dizesi ve kimlik bilgisi yok; httpx'in kendi URL logu kapatılmıştır).
- **Bağlantı doğrulama.** `verify_connection`: stok ve fiyat odaklı onaylı ürün v2, `size=1` (gerekçe ADR-0003 §4).
- **Anahtar saklama.** `marketplace_accounts.api_key_encrypted` ve `api_secret_encrypted`: zarf şifreleme (`EnvelopeCipher`, ADR-0004): kayıt başına rastgele DEK (AES-256-GCM), DEK KEK ile sarılı; biçim `v2:<kid>:<sarılı_dek>:<veri>`; AAD kiracı + platform + satıcı + hesap + alan adıdır (başka kiracıya/satıcıya/satıra taşınan değer çözülemez). Eski `v1:` değerler `python -m app.tools.migrate_envelope` ile dönüştürülür; KEK döndürme `python -m app.tools.rewrap_keys` ile (ikisi de varsayılan kuru çalıştırma, idempotent; ortam: `DATABASE_ADMIN_URL`). Listelemede ve `find_live_account`'ta şifreli sütunlar okunmaz (`deferred`). `netkar_app` yalnız gerekli sütunlarda UPDATE yapabilir (migrasyon 0005) ve şifreli sütunları SELECT EDEMEZ (migrasyon 0006, ADR-0005 §6): bunları yalnız `netkar_worker` okur. İptalde (`revoke`) iki alan da NULL olur, satır silinmez. Satıcı, anahtarı Trendyol panelinden de silmelidir.
- **Yeni zorunlu testler** (hepsi sahte taşımayla): `tests/test_trendyol_basics.py` (User-Agent, token bucket, pencere bölme), `tests/test_trendyol_client.py` (429 geri çekilme ve deneme sayısı, 401/403'te yeniden deneme yok, uç nokta sözleşmeleri), `tests/test_trendyol_models_pii.py` (PII hiçbir nesnede ve log'da yok), `tests/test_marketplace_accounts.py` (anahtarlar DB'de şifreli, RLS izolasyonu, iptal sonrası alanlar boş).

## Bildirim dağıtıcısı (ADR-0009 D5)

AYRI `notify` kuyruğunda ve ayrı süreçte (`make worker-notify`, compose `worker-notify`, eşzamanlılık 1; CPU ağır uyarı
değerlendirmesi dakikalık dağıtımı geciktirmesin) iki görev çalışır: `notify.dispatch` (her dakika) outbox
satırlarını işler, `notify.build_digests` (saat başı, dakika 13) İstanbul saatine göre özet saati gelen kullanıcılar için
günlük özet satırı yazar (saat, periyodik görevin ZAMANLANMIŞ tik `timestamp`ından hesaplanır: geç uyanan worker o
saatin kullanıcılarını kaçırmaz). Özet alıcıları kiracının doğrulanmış ÜYELERİdir (rol `memberships`'ten,
`notify_gate.tenant_recipients`; varsayılan matris D6'nın `default_matrix(role)` işlevidir: viewer e-posta off,
owner/admin günlük özet). Gerçek gönderim `ALERT_NOTIFICATIONS_ENABLED=false` ile KAPALIDIR: kapalıyken satır `suppressed`
olur ve ileti yalnız yerel `file`/`memory` arka ucuna yazılır (ağa çıkmaz). Gerçek e-posta sağlayıcısı entegrasyonu yoktur
(karar H5/K12 Hasan'da); yalnız `EmailSender` arayüzü vardır. Yapısal güvence: geliştirme kopyası
`build_local_email_sender` ile (file/memory) kurulur, kurucu yerel olmayan `dev_sender`'ı ve gerçek arka uçsuz açık
bayrağı (ya da yerel göndericiyle açık bayrağı: staging'de sahte `sent` olmasın) reddeder. Gönderim işlem DIŞINDADIR:
satır önce 10 dk kiralanır ve commit edilir, sonra gönderilir (`idempotency_key` = outbox kimliği, 30 sn zaman aşımı,
çalıştırma başına 50 sn toplam süre sınırı), sonra sonuç yazılır. Beklenmeyen hata ayrı işlemde `attempts + 1` ve
`failed` yazar. **H5 öncesi açık:** gerçek sağlayıcı seçilince `idempotency_key`'in sağlayıcıda gerçekten tekilleştirdiği
doğrulanmalı.

- Alıcı adresi yalnız gönderim anında `notify_gate.email_for(outbox_id)` ile okunur; outbox'a, loga ve hata metnine
  yazılmaz. Üyelikten çıkmış ya da e-postası doğrulanmamış kullanıcıya ileti gitmez (`skipped`).
- Sıklık sınırı (kullanıcı ve kanal başına günde 4 anlık e-posta, iki anlık arası 30 dk) aşılırsa satır `held` olur ve
  sonraki günlük özete katlanır; sessiz saatte (22:00-08:00 İstanbul) `not_before` 08:00 olur ve bitişte tek iletide
  birleşir. Geçici hata `failed` + üstel bekleme (4, 16, 64, 256, 1024 sn), kalıcı hata ya da 6. hata `failed_permanent`.
- Bastırma (O-a): bir kuralın bildirimi yalnız KENDİ veri kaynağı başarısız ya da yedeklemesi eksikse bastırılır
  (`app/services/alert_evaluation.py` `RULE_SOURCES`); olay yine açılır.
- Tek tık kapatma: `POST /v1/notifications/unsubscribe?token=...` (imzalı, süreli, kullanıcı ve kural bağlı, yalnız `off`,
  üyelik denetimli). `CsrfMiddleware` bu TAM yolu (`CSRF_EXEMPT`: yöntem + `scope["path"]`, önek ve eğik çizgi
  yok) muaf tutar; uç çerez/oturum okumaz ve yazmaz; gövde varsa yalnız `application/x-www-form-urlencoded` ve
  `List-Unsubscribe=One-Click`. Hız sınırı: IP yalnız başarısız doğrulamalara, geçerli token için token başına
  (`RATE_LIMIT_NOTIFY_UNSUBSCRIBE_TOKEN`). Anlık iletinin `List-Unsubscribe` başlığı yalnız o kuralı kapatır (çok
  kurallı anlık iletide başlık yoktur); `*` yalnız özette.
- Token iptali yalnız ANAHTAR DÖNDÜRMEYLE (`DATA_ENCRYPTION_KEY`) olur (tüm bekleyen bağlantılar geçersizleşir). Sorgu
  dizesi token taşır: ters vekil/CDN erişim loglarında `/v1/notifications/unsubscribe` ve `/bildirim-kapat` sorgu
  dizesi MASKELENMELİDİR (uygulama logu zaten yalnız yolu yazar).
- `text()` içinde f-string yoktur: `semgrep/sql-text-literal.yml` (yerel kural) ve `tests/test_notify_sql_rules.py` korur.

## Kiracı bağlamı kuralı

Kiracı verisine dokunan her kod `app.db.rls.set_rls_context` ile bağlam kurulmuş bir işlemde çalışır ve sorguda yine de açık `tenant_id` süzgeci kullanır (çift kilit). Yeni kiracı tablosu: `tenant_id` sütunu + `ENABLE`/`FORCE ROW LEVEL SECURITY` + politika + `netkar_app` için en az yetki. `test_every_tenant_table_has_forced_rls` kuralı otomatik doğrular.

## İstemci IP'si, vekil güveni ve istek sınırları

- Varsayılan: hiçbir vekile güvenilmez; `X-Forwarded-For` yok sayılır, bağlantının eş adresi kullanılır. BFF (Next.js) arkasında `TRUSTED_PROXY_CIDRS` (web konteyner ağı) ve/veya `TRUSTED_PROXY_HOPS=1` verin; web tarafı `CLIENT_IP_SOURCE` ile istemci başlıklarını temizler ve tek bir doğrulanmış XFF iletir. API yalnız web ağından erişilebilir olmalıdır. Ayrıntı ve güven zinciri: ADR-0002.
- uvicorn her zaman `--no-proxy-headers` ile çalıştırılır (Dockerfile, `make dev`); IP kararını yalnız uygulama verir.
- Sıra (dıştan içe): güvenlik başlıkları, istek bağlamı, gövde boyut sınırı, IP rate limit, CSRF, uygulama. IP sınırı ve gövde sınırı gövde ayrıştırılmadan önce çalışır.
- TOTP: son başarılı zaman adımı saklanır (`users.totp_last_step`); aynı veya eski adım reddedilir. Ardışık hatada hesap geçici kilitlenir ve `audit_log`'a (`auth.totp_failed`, `auth.totp_replay`, `auth.totp_locked`) yazılır.
- Hata metninde bağlı SQL parametreleri yazılmaz (`hide_parameters`); log maskeleme argon2 özeti, 64 haneli hex özet ve Unicode e-postayı da kapsar.
