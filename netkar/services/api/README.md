# NetKâr API

FastAPI (Python >= 3.12), SQLAlchemy 2 (async), Alembic, PostgreSQL 16 (RLS), procrastinate (PostgreSQL tabanlı kuyruk). Ürün adı tek ayardan okunur: `PRODUCT_NAME`. Mimari karar kayıtları: [`0001` RLS ve kimlik doğrulama](../../docs/adr/0001-rls-ve-kimlik-dogrulama.md), [`0002` istemci IP'si](../../docs/adr/0002-istemci-ip-ve-vekil-guveni.md), [`0003` Trendyol istemcisi](../../docs/adr/0003-trendyol-istemcisi.md).

## Kurulum

Gereksinimler: [uv](https://docs.astral.sh/uv/), Docker (yalnız yerel çalıştırma için PostgreSQL), `openssl`.

```sh
cd netkar
make setup      # uv sync
make env        # infra/.env üretir (rastgele parolalar ve DATA_ENCRYPTION_KEY)
make db-up      # PostgreSQL 16 (roller 01-roles.sh ile kurulur)
make migrate    # alembic upgrade head (netkar_owner rolüyle)
make dev        # http://127.0.0.1:8000  (OpenAPI: /v1/openapi.json, prod'da kapalı; uvicorn --no-proxy-headers)
make worker     # procrastinate worker (heartbeat ve rate limit temizliği)
```

Tüm yığın (api, worker, migrate, postgres) için: `docker compose -f infra/docker-compose.yml up --build`. Web servisi `--profile web` ile eklenir (apps/web hazır olunca).

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

Önemli test dosyaları: `tests/test_rls_idor.py` (kiracı izolasyonu: uç noktalar ve doğrudan SQL), `tests/test_auth_flow.py`, `tests/test_totp.py`, `tests/test_password_reset.py`, `tests/test_rate_limit.py`, `tests/test_logging.py` (maskeleme), `tests/test_http_hardening.py` (güvenlik başlıkları, RFC 9457), `tests/test_migrations.py` (geri alınabilirlik), `tests/test_client_ip.py` ve `tests/test_limits.py` (istemci IP çözümleyici, gövde sınırı), `tests/test_denetim_s1_regression.py` (S1 güvenlik denetimi PoC'lerinin tersine çevrilmiş regresyon testleri).

## Ortam değişkenleri

Örnek değerler: [`infra/.env.example`](../../infra/.env.example). Sır repoya girmez.

| Değişken | Zorunlu | Varsayılan | Açıklama |
|---|---|---|---|
| `DATABASE_URL` | evet | | Uygulama rolü (`netkar_app`, superuser DEĞİL). |
| `DATABASE_MIGRATION_URL` | migrasyonda | | Tablo sahibi rol (`netkar_owner`); yalnız Alembic okur. |
| `DATA_ENCRYPTION_KEY` | evet | | AES-256-GCM ana anahtarı, 32 bayt base64 (`openssl rand -base64 32`). Alt anahtarlar (IP özeti, imzalı token) HKDF ile türetilir. |
| `PRODUCT_NAME` | hayır | `NetKâr` | Ürün adı (TOTP yayıncı adı, e-posta metinleri, API başlığı). |
| `ENVIRONMENT` | hayır | `dev` | `dev`, `test`, `prod`. `prod`'da OpenAPI belgesi kapalıdır. |
| `LOG_LEVEL` | hayır | `INFO` | JSON log seviyesi. |
| `PWNED_CHECK_ENABLED` | hayır | `false` | HIBP k-anonimlik kontrolü (dış ağ çağrısı yapar). |
| `TRUSTED_PROXY_CIDRS` | hayır | boş | Güvenilir vekil ağları (virgülle ayrılmış CIDR, örn. web konteyner ağı). Eş adres bu listedeyse `X-Forwarded-For` sağdan sola okunur, listedeki adresler atlanır. Boşsa başlık yok sayılır ([ADR-0002](../../docs/adr/0002-istemci-ip-ve-vekil-guveni.md)). |
| `TRUSTED_PROXY_HOPS` | hayır | `0` | Sağdan sayılan güvenilir vekil sayısı (eş adres dahil). BFF arkasında tek vekil için `1`. CIDR ile birlikte de kullanılabilir. |
| `DEBUG` | hayır | `false` | Yalnız geliştirme. `ENVIRONMENT=prod` iken açıksa (veya `EMAIL_BACKEND=file/memory` ise) uygulama başlamaz. |
| `RATE_LIMIT_TOTP_IP` | hayır | 30 | 15 dakikada TOTP doğrulama denemesi (IP başına). |
| `TOTP_MAX_FAILURES` / `TOTP_LOCK_SECONDS` | hayır | 5 / 900 | Ardışık hatalı TOTP kodunda hesabın geçici kilit eşiği ve süresi (429 `totp-locked`). |
| `MAX_REQUEST_BODY_BYTES` / `MAX_AUTH_BODY_BYTES` | hayır | 1 MiB / 64 KiB | İstek gövdesi üst sınırı (genel / `/v1/auth/*`). Aşımda 413 problem+json, işleyici çağrılmaz. |
| `PASSWORD_HASH_CONCURRENCY` | hayır | min(4, CPU) | Aynı anda çalışan argon2 özet sayısı (her biri ~64 MiB). Özetler iş parçacığı havuzunda çalışır, olay döngüsünü bloklamaz. |
| `EMAIL_BACKEND` | hayır | `file` | `file` (JSONL) veya `memory` (test). Gerçek servis yok. |
| `EMAIL_DEV_OUTBOX_PATH` | hayır | `var/outbox.jsonl` | `file` arka ucunun yazdığı dosya. |
| `WEB_BASE_URL` | hayır | `http://localhost:3000` | Sıfırlama bağlantılarındaki web adresi. |
| `RATE_LIMIT_LOGIN_IP` / `_LOGIN_EMAIL` | hayır | 30 / 10 | 15 dakikalık pencerede giriş denemesi sınırı. |
| `RATE_LIMIT_REGISTER_IP` | hayır | 10 | 1 saatte kayıt sınırı (IP). |
| `RATE_LIMIT_RESET_IP` / `_RESET_EMAIL` | hayır | 10 / 3 | 1 saatte sıfırlama isteği sınırı. |
| `RATE_LIMIT_TOTP_USER` | hayır | 10 | 15 dakikada TOTP doğrulama denemesi (kullanıcı başına). |
| `TRENDYOL_ENVIRONMENT` | hayır | `stage` | `stage` veya `live`. Canlıya yalnız açıkça geçilir. |
| `TRENDYOL_INTEGRATOR_NAME` | hayır | `NetKar` | User-Agent'taki entegratör adı (`"{sellerId} - {ad}"`): yalnız ASCII harf/rakam, en fazla 30 karakter. Geçersizse uygulama açılmaz. |
| `TRENDYOL_CONNECT_TIMEOUT_SECONDS` / `TRENDYOL_READ_TIMEOUT_SECONDS` | hayır | 5 / 20 | Bağlantı ve okuma zaman aşımı. |
| `TRENDYOL_MAX_RETRIES` | hayır | 4 | 429, 5xx ve ağ hatasında yeniden deneme sayısı (üst sınır 10). |
| `TRENDYOL_BACKOFF_BASE_SECONDS` / `TRENDYOL_BACKOFF_CAP_SECONDS` | hayır | 1 / 30 | Üstel geri çekilme tabanı ve üst sınırı (saniye). |
| `RATE_LIMIT_MARKETPLACE_IP` / `_TENANT` | hayır | 20 / 10 | 1 saatte bağlantı ekleme denemesi (IP / kiracı); her deneme Trendyol'a doğrulama çağrısı yapar. |
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

## Dizin yapısı

```
app/main.py            create_app fabrikası
app/core/              config, security, crypto, logging, errors, middleware, limits (gövde sınırı, IP rate limit), clientip, clock, ratelimit, email, pwned
app/db/                session, base, rls (bağlam), provision (rol kurulumu)
app/models/            ORM modelleri
app/api/v1/            auth, me, tenant, health, marketplace_accounts
app/integrations/trendyol/  TrendyolClient (tek HTTP noktası), modeller (PII yok), hız sınırı, pencere yardımcıları, hatalar
app/services/          auth (auth_gate çağrıları, oturum), audit, marketplace_accounts (şifreleme, istemci fabrikası)
app/worker/            procrastinate App ve görevler (heartbeat, rate limit temizliği)
migrations/            Alembic (0001 şema + RLS + auth_gate, 0002 procrastinate, 0003 TOTP tekrar kullanım + kilit, 0004 marketplace_accounts)
tests/fixtures/trendyol/  Resmi doküman örneklerinden türetilmiş, sahte kişisel veri içeren yanıt fixture'ları
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
- **Anahtar saklama.** `marketplace_accounts.api_key_encrypted` ve `api_secret_encrypted`: AES-256-GCM (`FieldCipher`), AAD satır kimliği + alan adıdır (şifreli değer başka satıra taşınamaz). Listelemede şifreli sütunlar hiç okunmaz (`deferred`). İptalde (`revoke`) iki alan da NULL olur, satır silinmez. Satıcı, anahtarı Trendyol panelinden de silmelidir.
- **Yeni zorunlu testler** (hepsi sahte taşımayla): `tests/test_trendyol_basics.py` (User-Agent, token bucket, pencere bölme), `tests/test_trendyol_client.py` (429 geri çekilme ve deneme sayısı, 401/403'te yeniden deneme yok, uç nokta sözleşmeleri), `tests/test_trendyol_models_pii.py` (PII hiçbir nesnede ve log'da yok), `tests/test_marketplace_accounts.py` (anahtarlar DB'de şifreli, RLS izolasyonu, iptal sonrası alanlar boş).

## Kiracı bağlamı kuralı

Kiracı verisine dokunan her kod `app.db.rls.set_rls_context` ile bağlam kurulmuş bir işlemde çalışır ve sorguda yine de açık `tenant_id` süzgeci kullanır (çift kilit). Yeni kiracı tablosu: `tenant_id` sütunu + `ENABLE`/`FORCE ROW LEVEL SECURITY` + politika + `netkar_app` için en az yetki. `test_every_tenant_table_has_forced_rls` kuralı otomatik doğrular.

## İstemci IP'si, vekil güveni ve istek sınırları

- Varsayılan: hiçbir vekile güvenilmez; `X-Forwarded-For` yok sayılır, bağlantının eş adresi kullanılır. BFF (Next.js) arkasında `TRUSTED_PROXY_CIDRS` (web konteyner ağı) ve/veya `TRUSTED_PROXY_HOPS=1` verin; web tarafı `CLIENT_IP_SOURCE` ile istemci başlıklarını temizler ve tek bir doğrulanmış XFF iletir. API yalnız web ağından erişilebilir olmalıdır. Ayrıntı ve güven zinciri: ADR-0002.
- uvicorn her zaman `--no-proxy-headers` ile çalıştırılır (Dockerfile, `make dev`); IP kararını yalnız uygulama verir.
- Sıra (dıştan içe): güvenlik başlıkları, istek bağlamı, gövde boyut sınırı, IP rate limit, CSRF, uygulama. IP sınırı ve gövde sınırı gövde ayrıştırılmadan önce çalışır.
- TOTP: son başarılı zaman adımı saklanır (`users.totp_last_step`); aynı veya eski adım reddedilir. Ardışık hatada hesap geçici kilitlenir ve `audit_log`'a (`auth.totp_failed`, `auth.totp_replay`, `auth.totp_locked`) yazılır.
- Hata metninde bağlı SQL parametreleri yazılmaz (`hide_parameters`); log maskeleme argon2 özeti, 64 haneli hex özet ve Unicode e-postayı da kapsar.
