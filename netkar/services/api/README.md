# NetKâr API

FastAPI (Python >= 3.12), SQLAlchemy 2 (async), Alembic, PostgreSQL 16 (RLS), procrastinate (PostgreSQL tabanlı kuyruk). Ürün adı tek ayardan okunur: `PRODUCT_NAME`. Mimari karar kaydı: [`docs/adr/0001-rls-ve-kimlik-dogrulama.md`](../../docs/adr/0001-rls-ve-kimlik-dogrulama.md).

## Kurulum

Gereksinimler: [uv](https://docs.astral.sh/uv/), Docker (yalnız yerel çalıştırma için PostgreSQL), `openssl`.

```sh
cd netkar
make setup      # uv sync
make env        # infra/.env üretir (rastgele parolalar ve DATA_ENCRYPTION_KEY)
make db-up      # PostgreSQL 16 (roller 01-roles.sh ile kurulur)
make migrate    # alembic upgrade head (netkar_owner rolüyle)
make dev        # http://127.0.0.1:8000  (OpenAPI: /v1/openapi.json, prod'da kapalı)
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

Önemli test dosyaları: `tests/test_rls_idor.py` (kiracı izolasyonu: uç noktalar ve doğrudan SQL), `tests/test_auth_flow.py`, `tests/test_totp.py`, `tests/test_password_reset.py`, `tests/test_rate_limit.py`, `tests/test_logging.py` (maskeleme), `tests/test_http_hardening.py` (güvenlik başlıkları, RFC 9457), `tests/test_migrations.py` (geri alınabilirlik).

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
| `TRUST_PROXY_HEADERS` | hayır | `false` | `true` ise `X-Forwarded-For`'un en sağdaki değeri istemci IP'si sayılır. Yalnız güvenilir vekil arkasında açın. |
| `EMAIL_BACKEND` | hayır | `file` | `file` (JSONL) veya `memory` (test). Gerçek servis yok. |
| `EMAIL_DEV_OUTBOX_PATH` | hayır | `var/outbox.jsonl` | `file` arka ucunun yazdığı dosya. |
| `WEB_BASE_URL` | hayır | `http://localhost:3000` | Sıfırlama bağlantılarındaki web adresi. |
| `RATE_LIMIT_LOGIN_IP` / `_LOGIN_EMAIL` | hayır | 30 / 10 | 15 dakikalık pencerede giriş denemesi sınırı. |
| `RATE_LIMIT_REGISTER_IP` | hayır | 10 | 1 saatte kayıt sınırı (IP). |
| `RATE_LIMIT_RESET_IP` / `_RESET_EMAIL` | hayır | 10 / 3 | 1 saatte sıfırlama isteği sınırı. |
| `RATE_LIMIT_TOTP_USER` | hayır | 10 | 15 dakikada TOTP doğrulama denemesi (kullanıcı başına). |

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

Durum değiştiren her istek `X-CSRF-Token` başlığı ve `__Host-nk_csrf` çerezini birlikte ister (önce `GET /v1/auth/csrf`). Hatalar `application/problem+json` (RFC 9457) biçimindedir.

## Dizin yapısı

```
app/main.py            create_app fabrikası
app/core/              config, security, crypto, logging, errors, middleware, ratelimit, email, pwned
app/db/                session, base, rls (bağlam), provision (rol kurulumu)
app/models/            ORM modelleri
app/api/v1/            auth, me, tenant, health
app/services/          auth (auth_gate çağrıları, oturum), audit
app/worker/            procrastinate App ve görevler (heartbeat, rate limit temizliği)
migrations/            Alembic (0001 şema + RLS + auth_gate, 0002 procrastinate)
```

## Kiracı bağlamı kuralı

Kiracı verisine dokunan her kod `app.db.rls.set_rls_context` ile bağlam kurulmuş bir işlemde çalışır ve sorguda yine de açık `tenant_id` süzgeci kullanır (çift kilit). Yeni kiracı tablosu: `tenant_id` sütunu + `ENABLE`/`FORCE ROW LEVEL SECURITY` + politika + `netkar_app` için en az yetki. `test_every_tenant_table_has_forced_rls` kuralı otomatik doğrular.
