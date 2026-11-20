# NetTablo · Staging ve üretim dağıtım planı (v0.1, 15 Kasım 2026)

> Bu belge yalnız plandır. Hesap açılmadı, sunucu kurulmadı, alan adı alınmadı, para harcanmadı.
> KVKK ile ilgili cümleler hukuki görüş değildir; canlıya geçmeden önce avukat teyidi gerekir.
> Dayanaklar: `docs/10_mimari.md` §6-8, `docs/20_maliyet.md`, `calisma_dosyalari/maliyet_modeli.py`,
> `calisma_dosyalari/karar_hesap_2026-11-07.py`, `docs/50_guvenlik.md`, `docs/karar_kaydi.md` (K-N02, K-N06),
> `docs/hukuk/hetzner_kvkk_kontrol.md`, `docs/adr/0002` ve `0004`, `infra/docker-compose.yml`,
> `infra/postgres/init/01-roles.sh`, `services/api/Dockerfile`, `services/api/migrations/versions/0001-0015`,
> `services/api/README.md` ("Demo veri tohumu"), `docs/operasyon/runbook_rapor_motoru.md`,
> `.github/workflows/netkar-ci.yml`, `docs/ux/kullanici_testi_plani_S4.md` §7.1.

## 0. Özet

- **Amaç.** Önce bir **staging** ortamı açmak (uzaktan kullanılabilirlik testinin ön koşulu, S4 planı §7.1), sonra aynı kalıpla **prod**'u açmak. Tek küçük VM, Docker Compose, önde Cloudflare, VM'de TLS sonlandıran ters vekil (Caddy). Kubernetes yok, yönetilen veritabanı yok.
- **İki yol (K-N02'ye bağlı).**
  - **A · Hetzner (AB).** Toplam 4.974 TL/ay (altyapı 521 TL, gerisi işletme gideri). Hetzner'in KVKK m.9 standart sözleşmesini imzalaması ve imzadan sonra 5 iş günü içinde Kurum'a bildirim şart. İmza yoksa bu yol kapanır.
  - **B · Güzel Hosting (yurt içi).** Toplam 5.818 TL/ay. Yurt dışı aktarım sunucu tarafında kalkar, ama yedek deposu, e-posta, hata izleme ve Cloudflare yine yurt dışında (aşağıda §2.9).
  - Kod iki yolda aynıdır. Yalnız sunucu adresi, yedek hedefi ve birkaç ortam değişkeni değişir.
- **Hasan'a bağlı olanlar** (ayrıntı §3.2): Hetzner'e KVKK sorusunu göndermek, K-N02 son kararı, alan adı alımı ve DNS, Cloudflare/GitHub/sağlayıcı hesapları ve ödeme, Resend alan adı doğrulaması (SPF/DKIM), avukat teyidi, KEK ve yedek parolalarının ayrı saklanması, Trendyol stage IP izni (gerekirse), prod dağıtım onayı.
- **Repoda prod'u bugün engelleyen dört şey** (hepsi [Claude] işi, §3.1):
  1. `apps/web` için Dockerfile yok; compose dosyası `../apps/web` dizinini derlemeye çalışıyor.
  2. Next.js rewrite vekilinin varsayılan zaman aşımı **30 sn** (kurulu `next@15.5.29`, `dist/server/lib/router-utils/proxy-request.js`: `proxyTimeout || 30000`). Rapor hesap sınırı 45 sn olduğu için takılan rapor, API'nin `503 report-compute-timeout` yanıtı gelmeden web katmanında kesilir.
  3. `ENVIRONMENT` yalnız `dev | test | prod` alıyor. Demo tohumu `prod`'da çalışmıyor, `dev/test` ise OpenAPI'yi açık bırakıyor. Staging için ayrı bir değer gerekiyor.
  4. `EMAIL_BACKEND` yalnız `file | memory`; `ENVIRONMENT=prod` bu ikisiyle açılmıyor (bilinçli koruma). Gerçek e-posta arka ucu yazılmadan prod başlamaz.
- **Kaba takvim** (hafta numarası `docs/30_yol_haritasi.md` düzeninde, N01 = 9 Kasım):
  - N02 (16-22 Kas): repo hazırlığı [Claude]; Hetzner sorusu, alan adı, hesaplar [Hasan].
  - N03 (23-29 Kas): staging ayakta, demo tohumu yüklü, bir pilot oturum.
  - N04 (30 Kas-6 Ara): uzaktan kullanılabilirlik oturumları staging'de.
  - 1 Aralık: Hetzner'den yanıt yoksa B yoluna geçiş kararı.
  - N05-N06 (7-20 Ara): prod (beta için). Gerçek satıcı verisi ancak KVKK yolu netleşince girer. Gerçekçi tahmin N06.
  - N09 (4-10 Oca): ikinci geri yükleme testi, lansman kontrol listesi (S10).

## 1. Kapsam

Bu plan iki ortamı kapsar: `staging` ve `prod`. `dev` yerel Docker Compose olarak kalır (`infra/docker-compose.yml`). Mimari belgesindeki tanım geçerli: `main` dalı staging'e otomatik gider, prod'a manuel onayla (Hasan) ve tek komutlu geri dönüşle çıkılır (`docs/10_mimari.md` §8).

Kapsam dışı: ölçek aşaması (ayrı DB sunucusu, replika; `docs/10_mimari.md` §9), KMS (ADR-0004'te faz 2), mobil.

## 2. Hedef topoloji

### 2.1 Ortak yapı (iki yolda da aynı)

```
 Tarayıcı / telefon
        │ HTTPS
        ▼
 Cloudflare (DNS, TLS, WAF, Turnstile)     köken zaman aşımı ~100 sn (emin değilim, §9)
        │ HTTPS, yalnız Cloudflare IP aralıklarından
        ▼
 ┌──────────────────────────── VM (tek sunucu) ────────────────────────────────┐
 │  caddy        :443   TLS (Cloudflare Origin CA sertifikası), yanıt sınırı 60 sn │
 │    │  ağ: edge                                                               │
 │    ▼                                                                         │
 │  web (Next.js 15)  :3000   /api/v1/* -> api:8000/v1/*  (proxyTimeout 55 sn)   │
 │    │  ağ: app                                                                │
 │    ▼                                                                         │
 │  api (FastAPI, uvicorn --no-proxy-headers)  :8000   dışarıya hiç açık değil   │
 │  worker (procrastinate, aynı imaj)                                           │
 │  migrate (tek seferlik, netkar_owner)                                        │
 │    │  ağ: db                                                                 │
 │    ▼                                                                         │
 │  postgres:16   veri birimi pgdata, port yayını yok                           │
 │                                                                              │
 │  cron: gece yedeği (pg_dump + restic), log uyarı betiği, disk ve yedek yaşı   │
 └──────────────────────────────────────────────────────────────────────────────┘
        │ restic (şifreli)
        ▼
 Uzak yedek deposu (A: Cloudflare R2; B: tercihen yurt içi, §2.7)
```

Notlar:

- API'ye yalnız web konteyneri erişir (ADR-0002: "API yalnız web ağından erişilebilir olmalıdır"). Caddy yalnız `web`'e yönlendirir. Bugünkü compose dosyasındaki `127.0.0.1:8000` ve `127.0.0.1:5432` yayınları prod dosyasında kaldırılır.
- İstemci IP'si: web `CLIENT_IP_SOURCE=cf-connecting-ip`, API `TRUSTED_PROXY_CIDRS=<app ağı CIDR>` ve `TRUSTED_PROXY_HOPS=1` (apps/web/README ve ADR-0002). Köken güvenlik duvarında 443 yalnız Cloudflare aralıklarına açılır; aksi halde `CF-Connecting-IP` taklit edilebilir.
- Konteyner sertleştirmesi bugünkü compose dosyasındaki gibi kalır: `read_only`, `tmpfs: /tmp`, `cap_drop: ALL`, `no-new-privileges`, root olmayan kullanıcı (G14).

### 2.2 İstek yolu ve zaman aşımı zinciri

Kural: her dış katman, içindekinden uzun bekler. Böylece API'nin kendi problem+json yanıtı (503 + `Retry-After`) kullanıcıya ulaşır, bağlantı ortada kopmaz.

| Katman | Sınır | Nereden | Durum |
|---|---|---|---|
| PostgreSQL `statement_timeout` (rapor işlemi) | 40 sn (kalan bütçe - 5 sn, en az 1 sn) | `app/core/config.py` yorumu (DK-05) | Var |
| Tek uçuşta bekleyen (`PROFIT_REPORT_CACHE_WAIT_SECONDS`) | 25 sn (toplam bütçenin parçası) | `config.py` | Var |
| Rapor hesabı (`PROFIT_REPORT_COMPUTE_TIMEOUT_SECONDS`) | 45 sn, bekleme + hesap TOPLAM bütçesi (bekleme sonrası hesap kalan süreyle sınırlı, 6 sn altı 503) | `config.py`, `report_cache.py` | Var |
| Next.js rewrite vekili (`experimental.proxyTimeout`) | **55 sn** | `apps/web/next.config.ts` | **Yok**, bugün varsayılan 30 sn (C3) |
| Caddy `reverse_proxy` yanıt sınırı | **60 sn** | `infra/prod/Caddyfile` | **Yok** (C2) |
| Cloudflare köken yanıt sınırı | yaklaşık 100 sn | Cloudflare belgeleri (emin değilim) | Değiştirilmez |

Caddy taslağı (yalnız fikir vermek için, C2'de yazılacak):

```caddy
app.<alan-adi> {
    tls /etc/caddy/origin.pem /etc/caddy/origin-key.pem
    encode zstd gzip
    reverse_proxy web:3000 {
        transport http {
            dial_timeout 3s
            response_header_timeout 60s
            read_timeout 60s
        }
    }
    log {
        output file /var/log/caddy/access.log {
            roll_size 50MiB
            roll_keep_for 336h
        }
        format filter {
            request>remote_ip ip_mask 16 32
            request>client_ip ip_mask 16 32
            request>headers>Cookie delete
            request>headers>Authorization delete
        }
    }
}
```

Staging bloğunda ek olarak `basic_auth` (katılımcı ve ekip için ortak, sık değişen parola) ve `header X-Robots-Tag "noindex, nofollow"` bulunur.

### 2.3 Servisler, ağlar ve kaynak payı

| Servis | İmaj | Ağlar | Dışa açık | Not |
|---|---|---|---|---|
| caddy | `caddy:2` (sürüm ve özet sabitlenir) | edge | 443 (yalnız Cloudflare aralıkları) | TLS, erişim günlüğü IP maskeli |
| web | `ghcr.io/<hesap>/netkar-web:<sha>` | edge, app | hayır | `API_BASE_URL=http://api:8000` derleme anında rewrites içine gömülür; iki ortamda aynı değer olduğu için tek imaj yeter |
| api | `ghcr.io/<hesap>/netkar-api:<sha>` | app, db | hayır | `DATABASE_URL` = `netkar_app`; Dockerfile sağlık kontrolü `/v1/health` |
| worker | api ile aynı imaj | db | hayır | `WORKER_DATABASE_URL` = `netkar_worker`; dış ağa çıkış gerekir (Trendyol) |
| migrate | api ile aynı imaj | db | hayır | `DATABASE_MIGRATION_URL` = `netkar_owner`; dağıtımda tek sefer |
| postgres | `postgres:16.x` (küçük sürüm ve özet sabit) | db | hayır | `pgdata` birimi; ilk açılışta `01-roles.sh` |

Bellek kabaca (CX33, 4 vCPU / 8 GB varsayımıyla): rapor önbelleği süreç başına en çok yaklaşık 160 MB (`PROFIT_REPORT_CACHE_MAX_LINES=40000`, `config.py` yorumu), motor tepe belleği buna ek, argon2 özeti başına ~64 MiB (en çok 4). Staging daha küçük bir VM'de çalışırsa `PROFIT_REPORT_CACHE_MAX_LINES=10000` ve `PROFIT_REPORT_PROCESS_CONCURRENCY=2` önerilir. Compose dosyasında her servise `mem_limit` yazılır ki bir servis ötekini OOM ile düşürmesin.

### 2.4 PostgreSQL rolleri (migrasyonların tanımladığı gibi, yeni rol yok)

| Rol | Giriş | Özellik | Kim kullanır | Kaynak |
|---|---|---|---|---|
| `postgres` | evet (yalnız konteyner içi soket) | süper kullanıcı | Yalnız ilk kurulum (`01-roles.sh`), gece yedeği, `--mark-non-prod` ve ADR-0004 araçları (bakım penceresinde) | compose, ADR-0004 |
| `netkar_owner` | evet | NOSUPERUSER, NOBYPASSRLS; veritabanının ve `public` nesnelerinin sahibi; `netkar_auth`, `netkar_sync_gate` ve `netkar_notify_gate` rollerine `INHERIT FALSE, SET TRUE` ile üye | Yalnız `migrate` servisi | `01-roles.sh`, 0013/0014 |
| `netkar_app` | evet | NOSUPERUSER, NOBYPASSRLS; şifreli anahtar sütunlarını okuyamaz; `is_demo` yazamaz; `deployment_marks` yalnız okur | api | 0005, 0006, 0015 |
| `netkar_worker` | evet | NOSUPERUSER, NOBYPASSRLS; şifreli sütunları okuyabilen tek rol; `deployment_marks` yalnız okur; 0025 ile uyarı/bildirim tablolarına dar yazma, `report_data_revisions` SELECT, `notify_gate`/`alert_gate` işlevleri | worker | 0006, 0025, ADR-0005 §6 |
| `netkar_auth` | hayır | `auth_gate` şeması ve işlevlerinin sahibi | (SECURITY DEFINER işlevler) | 0001 |
| `netkar_sync_gate` | hayır | `sync_gate` şeması ve işlevlerinin sahibi; politikası `status = 'active' AND NOT is_demo` | (SECURITY DEFINER işlevler) | 0006, 0015 |
| `netkar_notify_gate` | hayır | `notify_gate` şeması ve işlevlerinin sahibi; `users(id, email, email_verified_at)`, `memberships(user_id, tenant_id)` ve `notification_outbox` (6 sütun) için yalnız `FOR SELECT` politikaları | (SECURITY DEFINER işlevler) | 0025, ADR-0009 §4.4 |

Önemli ayrıntılar:

- Tüm kiracı tabloları `ENABLE` + `FORCE ROW LEVEL SECURITY`. Tablo sahibi bile RLS'ye tabidir. Bu yüzden yedek `netkar_owner` ile alınamaz (RLS satırları süzer); yedek süper kullanıcıyla, konteyner içi soketten alınır. Yeni bir BYPASSRLS yedek rolü **kurulmaz** (rol kümesi migrasyonlardaki gibi kalsın).
- `GRANT ... WITH INHERIT FALSE, SET TRUE` sözdizimi PostgreSQL 16 gerektirir. Sağlayıcı bir "yönetilen PostgreSQL" önerse bile bu plan kendi `postgres:16` konteynerimizi kullanır.
- Var olan bir veri dizininde `01-roles.sh` yeniden çalışmaz; roller o durumda `app.db.provision.provision_roles` ile kurulur (services/api README).
- Üç giriş rolünün parolası ayrı, rastgele, hex (URL'de sorun çıkmasın diye; `infra/.env.example` notu).
- Veritabanı adı: staging `netkar_staging`, prod `netkar_prod`. Demo tohumu adında `prod`, `canli` ya da `live` geçen veritabanını zaten reddeder (README), bu da prod'a ikinci bir isim kilidi ekler.

### 2.5 Yol A: Hetzner (AB)

| Konu | Plan |
|---|---|
| Sunucu | Hetzner Cloud CX33 (4 vCPU, 8 GB), Almanya ya da Finlandiya. Fiyat 8,49 EUR/ay (fiyatlar CSV, orta güven). CSV'de "bir kaynak CX serisinin artık sipariş edilemediğini söylüyor" notu var: hesap açılmadan resmi sayfadan teyit. |
| Staging | Aşama 1: staging kendi VM'inde (önerilen CX23, 2 vCPU / 4 GB, 5,49 EUR/ay, aynı CSV). Prod henüz yokken tek VM yalnız staging'dir. |
| Ağ | Hetzner Cloud Firewall: 443 yalnız Cloudflare IP aralıkları, 22 yalnız SSH anahtarıyla (mümkünse Hasan'ın sabit IP'si ya da Tailscale benzeri bir tünel; karar §8). Root girişi kapalı (G18). |
| Uzak yedek | Cloudflare R2 (~20 GB, 0,30 USD/ay, maliyet modeli). R2'de AB yargı alanı kısıtı seçeneği var (emin değilim, teyit). |
| KVKK | Satıcı hesap verisi yurt dışında işlenir. Hetzner standart sözleşmeyi imzalamadan **gerçek kişisel veri** girmez (K-N02 "Koşullu"). |

**Hetzner'de staging, KVKK yanıtından önce açılabilir mi?** Staging yalnız demo veriyle çalışırsa (e-postalar `example.com`, ürün ve sipariş adları uydurma, son müşteri alanı yok; README "KVKK ve sırlar") kişisel veri neredeyse yoktur. Kalan iki kalem: erişim günlüğündeki IP (maskelenir, §2.2) ve Hasan ile ekibin kendi giriş bilgileri. Bu "pratikte sıfıra yakın" durumun hukuken yeterli olup olmadığından **emin değilim**; avukata ayrıca sorulmalı. Hasan'ın gerçek mağaza anahtarı bu VM'e KVKK yolu netleşmeden girmez.

### 2.6 Yol B: Güzel Hosting (yurt içi)

| Konu | Plan |
|---|---|
| Sunucu | Private Cloud 3, 16.198,90 TL/yıl (karar_hesap_2026-11-07.py). Fiyat üçüncü taraf listeden (karekod.org, Mart 2026), resmi sayfadan doğrulanmadı. Paket özellikleri (vCPU, RAM, disk) repoda yazılı değil: **doğrulanmadı**. Root erişimi ve Docker kurulumuna izin verilip verilmediği de doğrulanmadı; bu plan bunu varsayar. |
| Staging | Aynı sağlayıcıda ikinci küçük sunucu. Fiyat repoda yok: **doğrulanmadı**. Geçici çözüm: staging prod'dan önce aynı sunucuda tek başına çalışır, prod açılınca ayrı sunucuya taşınır. |
| Ağ | Sağlayıcı güvenlik duvarı varsa A'daki kurallar; yoksa VM üzerinde `nftables` ile aynı kurallar. |
| Uzak yedek | Yurt içi bir depo tercih edilir (sağlayıcının yedek hizmeti ya da ikinci bir yurt içi sağlayıcı); fiyat **doğrulanmadı**. R2 kullanılırsa yedek yurt dışına çıkar (maliyet modeli ve karar hesabı R2'yi B'ye de koyuyor). Restic yedeği istemci tarafında şifreler; şifreli verinin yurt dışına çıkmasının KVKK açısından aktarım sayılıp sayılmadığından **emin değilim**, avukata sorulacak. |
| KVKK | Ana veritabanı yurt içinde kalır. Cloudflare, Resend ve Sentry yine yurt dışı hizmetlerdir (§2.9). |

### 2.7 Yedekleme

**Başlangıç (staging ve prod): gece mantıksal yedek + uzak kopya.**

1. Her gece (prod 02:30, staging 03:30 İstanbul) konteyner içinden süper kullanıcıyla `pg_dump -Fc` (özel biçim, `pg_restore` ile seçici geri yükleme). FORCE RLS nedeniyle süper kullanıcı zorunlu (§2.4).
2. Aynı anda `pg_dumpall --globals-only` (rol tanımları). `pg_dump` rolleri içermez; geri yüklemeden önce roller kurulmalıdır (PostgreSQL belgeleri, §9). Rol parolaları bu dökümden ayıklanır ya da geri yüklemede yeniden üretilir.
3. `restic backup` ile uzak depoya. Restic veriyi istemci tarafında şifreler; depo parolası sunucudaki `.env` dosyasında değil, ayrı bir dosyada (`/srv/netkar/<ortam>/secrets/restic.pass`, 600) ve Hasan'ın parola yöneticisinde durur.
4. Saklama: prod `--keep-daily 7 --keep-weekly 4 --keep-monthly 6`; staging `--keep-daily 7` (demo veri yeniden tohumlanabilir).
5. Her prod dağıtımında migrasyondan hemen önce ek bir `pg_dump` (dağıtım betiğinin ilk adımı, §4.3).

**Geri yükleme testi (G15: haftalık).** Pazar gecesi betik son yedeği geçici bir `postgres:16` konteynerine açar: önce `01-roles.sh` ile roller, sonra `pg_restore`, ardından `alembic current` (beklenen: head), tablo sayısı ve birkaç temel tabloda satır sayısı karşılaştırması, `SELECT count(*) FROM deployment_marks WHERE key='non_production'` (prod yedeğinde 0 olmalı). Sonuç `ops/restore_log.tsv` dosyasına yazılır, başarısızlık uyarı üretir (§6). Lansmandan önce bu test elle iki kez izlenir (S10, N09).

**Hedefler.** Mimari belgesindeki MVP hedefi: RPO 24 saat, RTO 4 saat (`docs/10_mimari.md` §6).

**PITR (sürekli WAL arşivi) ne zaman?** Trendyol verisi yeniden çekilebilir, ama satıcının girdiği ürün maliyetleri, kâr ayarları ve ayar geçmişi çekilemez. Bu yüzden **ilk ödeyen satıcıdan önce** (S8, N07) pgBackRest ya da WAL-G ile WAL arşivine geçilmesi önerilir; RPO dakikalara iner. Karar §8'de.

**Anahtarlar yedekle birlikte durmaz.** ADR-0004: KEK halkası (`DATA_KEKS`) ve `DATA_ENCRYPTION_KEY` veritabanı yedeğinden **ayrı** saklanır. KEK kaybolursa pazaryeri anahtarları çözülemez (satıcılar yeniden bağlanır); `DATA_ENCRYPTION_KEY` kaybolursa TOTP sırları çözülemez. KEK döndürüldükten sonra, eski yedeklerin geri yüklenme ihtimali sürdükçe eski KEK arşivde tutulur.

### 2.8 Sırlar

- **Repoda sır yok.** Bugünkü düzen korunur: `infra/.env.example` yalnız yer tutucu içerir, `make env` rastgele değer üretir, gitleaks CI'da çalışır (G13).
- **Sunucuda.** Her ortamın kendi dosyası: `/srv/netkar/staging/.env` ve `/srv/netkar/prod/.env`, sahibi `deploy` kullanıcısı, izin 600. İlk kurulumda sunucuda `infra/prod/gen_env.sh` (C8) ile üretilir; içerik hiçbir zaman sohbete, CI günlüğüne ya da e-postaya yapıştırılmaz.
- **Ortamlar arasında paylaşım yok.** Staging ve prod ayrı `DATA_ENCRYPTION_KEY`, ayrı KEK halkası (`kek-202611` gibi farklı kid), ayrı rol parolaları kullanır.
- **Zarf şifreleme (ADR-0004).** Prod'da `DATA_KEKS` ve `DATA_KEK_ACTIVE` zorunlu (uygulama aksi halde açılmaz). KEK üretimi: `echo "kek-202611:$(openssl rand -base64 32)"`. Döndürme 90 günde bir ya da olay sonrası hemen: yeni kid ekle, etkin yap, api ve worker'ı yeniden başlat, `python -m app.tools.rewrap_keys` (kuru), sonra `--apply`, ikinci çalıştırma "0 kayıt taşındı" demeli.
- **Yönetici bağlantısı.** `DATABASE_ADMIN_URL` uygulama `.env` dosyasında durmaz; yalnız bakım penceresinde (rewrap, `--mark-non-prod`) tek komutluk ortam değişkeni olarak verilir (ADR-0004 §5 son madde).
- **CI tarafında.** GitHub Actions'ta yalnız iki sır: staging ve prod için ayrı SSH dağıtım anahtarları. Sunucuda bu anahtarlar `authorized_keys` içinde `command="/srv/netkar/bin/deploy-gate"`, `no-port-forwarding,no-pty` ile kısıtlanır; anahtar yalnız dağıtım betiğini çalıştırabilir. İmaj itme için `GITHUB_TOKEN` (`packages: write`) yeterli. Uygulama sırları GitHub'a girmez.
- **İnsan tarafında.** Hasan'ın parola yöneticisinde: iki ortamın `.env` yedeği, KEK halkası, restic parolası, Cloudflare ve sağlayıcı hesapları (2FA açık). Parola yöneticisi seçimi ve maliyeti açık (§7).

### 2.9 Log saklama, KVKK ve veri yerleşimi

**Ne loglanır.** Uygulama JSON log yazar, kişisel veri ve sır maskeleme filtresi var (G09, `tests/test_logging.py`). Son müşteri adı, adresi, telefonu, TCKN'si ve e-postası hiçbir tabloya ve loga yazılmaz (G16, `tests/test_sync_pii.py`, `tests/test_trendyol_models_pii.py`). Trendyol çağrı meta logu gövde, sorgu dizesi ve kimlik bilgisi içermez (services/api README). `audit_log` IP'yi anonimleştirilmiş tutar.

**Saklama önerisi.**

| Kaynak | Nerede | Süre | Not |
|---|---|---|---|
| api, worker, web konteyner logu | VM, Docker `local` ya da `json-file` sürücüsü, `max-size: 50m`, `max-file: 10` | Boyutla sınırlı, kabaca 30 gün | Günlük `docker compose logs` arşivi tutulmaz |
| Caddy erişim günlüğü | VM | 14 gün (`roll_keep_for 336h`) | IP son iki baytı maskeli, çerez ve `Authorization` silinir |
| `audit_log` (DB) | PostgreSQL | Karar bekliyor (saklama ve imha politikası, G16) | §8 açık karar |
| Yedekler | Uzak depo | Prod 6 aya kadar (aylık), staging 7 gün | İptal edilen anahtarın eski satır sürümü yedekte kalır (ADR-0004 B-01) |
| Sentry (eklenince) | Sentry | Sağlayıcı varsayılanı | `app/core/privacy.py` süzgeci hazır; Sentry henüz eklenmedi |

**Veri yerleşimi (hangi veri nerede işlenir).** Aşağıdaki tablo hukuki değerlendirme değil, avukata götürülecek envanterdir.

| Hizmet | İşlediği veri | Yol A | Yol B | Not |
|---|---|---|---|---|
| Uygulama + PostgreSQL | Satıcı hesabı (ad, e-posta), Trendyol sipariş verisi (son müşteriden yalnız il ve takma adlı anahtar) | AB (Hetzner) | TR | A için Hetzner standart sözleşmesi şart (K-N02) |
| Uzak yedek | Yukarıdakinin şifreli kopyası | AB/ABD şirketi (R2) | Tercihen TR; R2 seçilirse yurt dışı | Şifreli yedeğin durumu belirsiz (emin değilim) |
| Cloudflare | Tüm HTTP trafiği TLS sonrası (giriş e-postası, parola dahil), IP | Yurt dışı | Yurt dışı | Mimari Cloudflare'i varsayıyor; B'de "yurt içi" iddiası buna takılır |
| Resend (e-posta) | Satıcı e-posta adresi, sıfırlama bağlantısı | Yurt dışı | Yurt dışı | Prod için gerekli |
| Sentry (eklenince) | Hata bağlamı (süzülmüş) | Yurt dışı | Yurt dışı | Veri bölgesi seçeneği teyit edilmeli |
| HIBP (`PWNED_CHECK_ENABLED`) | Parola özetinin ilk 5 karakteri (k-anonimlik) | Yurt dışı | Yurt dışı | Kişisel veri sayılmayabilir, emin değilim |

Sonuç: `docs/hukuk/hetzner_kvkk_kontrol.md` yalnız Hetzner'i ele alıyor. Yol hangisi olursa olsun Cloudflare, Resend, R2 ve Sentry için de m.9 durumu avukata sorulmalı. Bu, B yolunu da tamamen "yurt içi" yapmaz; fark yalnız ana veritabanının yeridir.

## 3. Kurulum kontrol listesi

İşaretler: **[Claude]** repoda hazırlanabilir, PR olarak gelir, Hasan inceler. **[Hasan]** hesap açma, ödeme, DNS, hukuk ya da sunucuda komut çalıştırma gerektirir (sunucu komutlarını Claude hazırlar, çalıştırmak Hasan'a ya da Hasan'ın erişim verdiği oturuma düşer).

### 3.1 [Claude] Repo hazırlığı (sunucu gerektirmez)

| # | İş | Çıktı | Neden |
|---|---|---|---|
| C1 | Web için çok aşamalı Dockerfile (Next.js `output: 'standalone'`, root olmayan kullanıcı, `HEALTHCHECK`) | `apps/web/Dockerfile`, `next.config.ts` | Compose `../apps/web` dizinini derliyor ama Dockerfile yok |
| C2 | Prod compose dosyası: imajlar özetle sabit, port yayını yok (yalnız caddy 443), üç ağ (edge/app/db), `mem_limit`, log sürücüsü sınırları, `restart: unless-stopped`; Caddyfile (60 sn sınır, IP maskeli log, staging'de `basic_auth` ve `noindex`) | `infra/prod/compose.yml`, `infra/prod/Caddyfile`, `infra/prod/.env.example` | Bugünkü dosya yerel geliştirme için |
| C3 | Next.js rewrite zaman aşımını 55 sn yapmak (`experimental.proxyTimeout: 55000`) ve bunu doğrulayan küçük test | `apps/web/next.config.ts` | Varsayılan 30 sn, rapor hesap sınırı 45 sn |
| C4 | `ENVIRONMENT=staging` değeri: prod gibi sertleşir (OpenAPI kapalı, `DEBUG` yasak, `DATA_KEKS` zorunlu) ama `EMAIL_BACKEND=file` ve demo tohumuna izin verir (DT-20: `EMAIL_DEV_OUTBOX_PATH` mutlak yol zorunlu, outbox 0600/dizin 0700, boyuta göre döndürme ve 7 gün/5 dosya saklama); `TRENDYOL_ENVIRONMENT=live` ile birlikte açılmaz | `app/core/config.py`, testler | Bugün staging ya `dev/test` (gevşek) ya `prod` (tohum çalışmaz) olmak zorunda |
| C5 | **Açılış kilidi (iki yönlü, DT-21):** staging'de `non_production` işareti YOKSA da api ve worker açılmaz (hata iletisi `mark-non-prod` komutunu söyler); aşağıdaki prod kuralı değişmedi. **Prod açılış kilidi:** `ENVIRONMENT=prod` iken api ve worker açılışta `deployment_marks` tablosunda `non_production` satırı görürse açılmayı reddeder (net hata iletisi, çıkış kodu ≠ 0). `netkar_app` ve `netkar_worker` bu tabloyu zaten okuyabiliyor (0015) | `app/main.py` yaşam döngüsü, `app/worker/runtime`, testler | Üretim değil işaretli bir veritabanına prod kodunun bağlanmasını engeller |
| C6 | Migrasyon ön kontrol betiği (`netkar_owner` ile çalışır, §4.4): bağlanan rol, roller ve öznitelikleri, nesne ve şema sahiplikleri (0013/0014 denetiminin genellemesi), tek head, prod'da işaret yokluğu | `app/tools/migrate_preflight.py`, `tests/test_migrate_preflight.py` | Yanlış rolle migrasyon 0012'de yaşandı (0014 açıklaması) |
| C7 | Migrasyon ortamına `lock_timeout` (ör. 5 sn) ve makul `statement_timeout`; uzun kilit beklerse migrasyon temiz düşsün | `migrations/env.py` | Tek VM'de canlı trafik altında DDL kilidi kuyruğu bütün istekleri bekletebilir |
| C8 | Sunucuda `.env` üreten betik (`make env` mantığı, ortam adını alır, KEK'i kid ile üretir, mevcut dosyaya dokunmaz) | `infra/prod/gen_env.sh` | Sırlar sunucuda doğar, kimseye gösterilmez |
| C9 | Dağıtım betiği: `deploy.sh <staging|prod> <imaj-etiketi>` ve `deploy.sh <ortam> rollback` (§4.3); `RELEASES` dosyasına yazar | `infra/prod/deploy.sh`, `infra/prod/deploy-gate` | Tek komutla dağıtım ve geri dönüş |
| C10 | **İşaretleme adımı ayrı betik:** yalnız staging'de, bir kez, elle çalışır; `deployment_marks.non_production='true'` yazar (README'deki `--mark-non-prod` yolu). Hedef veritabanı adı `netkar_staging` değilse ya da `ENVIRONMENT` staging değilse reddeder. Dağıtım betiği bu işi **hiç** yapmaz | `infra/prod/mark_staging.sh` | İşaretin otomatik akışa karışmaması |
| C11 | Yedek, geri yükleme testi ve uyarı betikleri (cron): `backup.sh`, `restore_test.sh`, `log_alerts.sh` (`profit_engine_abandoned`), `disk_and_backup_age.sh`, `worker_heartbeat.sh` | `infra/ops/` | §2.7 ve §6 |
| C12 | CD iş akışı: imaj derleme ve GHCR'a itme (etiket `sha-<kısa>`), Trivy imaj taraması (G14 bugün yalnız dosya sistemi taraması yapıyor), staging'e otomatik dağıtım, prod için elle tetiklenen iş | `.github/workflows/netkar-cd.yml` | §4 |
| C13 | Gerçek e-posta arka ucu (Resend ya da SES; maliyet modeli Resend Free'yi varsayıyor) ve `EMAIL_BACKEND` değeri | `app/core/email.py`, config, testler | Prod bu olmadan açılmaz (D-08 koruması) |
| C14 | Sentry'yi `app/core/privacy.py` süzgeciyle eklemek (DSN yoksa kapalı) | api, worker, web | Hata izleme (G09 ile uyumlu) |
| C15 | Bu planın operasyon kısmını runbook'a çevirmek: ilk kurulum, dağıtım, geri dönüş, geri yükleme, KEK döndürme | `docs/operasyon/runbook_dagitim.md` | Hasan'ın tek başına uygulayabilmesi |

Not (15 Kasım durumu): Çalışma ağacında başka bir iş akışının henüz commit edilmemiş değişiklikleri var: `0016_instance_id_and_mark_demo_strict.py` migrasyonu ve `app/db/deployment_guard.py` (DT-14: `ENVIRONMENT=prod` iken işaret varsa ya da doğrulanamıyorsa API ve işçi açılmaz; tohum betiğinde `mark-non-prod` alt komutu). Bu C5'in kendisi; birleşirse C5 kapanır, C10 da yeni alt komutu sarmalar. Bu plan 0001-0015'e dayanır; 0016 birleşirse C6 ve C10 `deployment_marks.instance_id` kontrolünü de kullanabilir. README'deki `--mark-non-prod` bayrağının adı bu değişiklikle değişebilir; §3.3 ve §5'teki komutlar birleşmeden sonra güncellenecek.

### 3.2 [Hasan] Hesap, ödeme, DNS ve hukuk

| # | İş | Ne zaman | Bağımlılık |
|---|---|---|---|
| H1 | Hetzner'e KVKK standart sözleşme sorusunu göndermek (İngilizce metin hazır: `docs/hukuk/hetzner_kvkk_kontrol.md`, hesap açmadan iletişim formundan) | 18 Kas | yok |
| H2 | K-N02 son kararı: Hetzner yanıtına göre A ya da B | yanıt gelince, en geç 1 Ara | H1 |
| H3 | Staging'in KVKK yanıtından önce nerede açılacağı: Hetzner'de yalnız demo veriyle mi, Güzel'de mi (§2.5) | 20 Kas | yok |
| H4 | Alan adı alımı (`nettablo.com` ve/veya `.com.tr`; uygunluk doğrulanmadı, K-N01 notu) ve ad sunucularını Cloudflare'e yönlendirmek | 20 Kas | yok |
| H5 | Cloudflare hesabı (2FA), alan adının eklenmesi, SSL modu "Full (strict)", Origin CA sertifikası üretimi (anahtar dosyası doğrudan sunucuya, sohbete değil) | 22 Kas | H4 |
| H6 | Sağlayıcı hesabı ve ödeme (A: Hetzner Cloud; B: Güzel Hosting); staging sunucusunun açılması; SSH anahtarı ekleme | 24 Kas | H3 |
| H7 | DNS kayıtları: `staging.<alan>` ve (prod'da) `app.<alan>` A/AAAA, Cloudflare vekilli (turuncu bulut) | 24 Kas | H5, H6 |
| H8 | Uzak yedek deposu hesabı (A: Cloudflare R2 kovası; B: yurt içi seçenek) ve erişim anahtarının sunucuya girilmesi | 24 Kas | H2/H3 |
| H9 | GitHub tarafı: GHCR paket görünürlüğü özel, iki dağıtım anahtarının Actions sırlarına eklenmesi; repo planının ortam onayı (required reviewers) destekleyip desteklemediğine bakmak (§4.2) | 24 Kas | C12 |
| H10 | Sunucuda ilk kurulum komutlarını çalıştırmak (§3.3) ya da bunun için Claude oturumuna erişim vermek | 25-27 Kas | C1-C11, H6 |
| H11 | Parola yöneticisinde KEK halkası, `DATA_ENCRYPTION_KEY`, restic parolası ve `.env` yedeklerini ayrı kayıtlar olarak saklamak | ilk kurulumla aynı gün | H10 |
| H12 | Uyarı kanalı seçimi (e-posta ya da Telegram botu) ve harici uptime izleme hesabı | 27 Kas | yok |
| H13 | Trendyol stage ortamı için IP izni ve stage satıcı hesabı (yalnız staging'de entegrasyon denemesi istenirse; ilk aşamada gerekmez, §5) | isteğe bağlı | H6 |
| H14 | Resend hesabı ve alan adı doğrulaması (SPF, DKIM, DMARC kayıtları) | prod'dan önce, 4 Ara | H5, C13 |
| H15 | Avukat: Hetzner (A) ve tüm yurt dışı işleyenler (Cloudflare, Resend, R2, Sentry) için m.9 değerlendirmesi, aydınlatma metni, VERBİS kontrolü; A seçilirse standart sözleşme imzası ve 5 iş günü içinde Kurum'a bildirim | prod'dan önce, 4 Ara | H2 |
| H16 | Prod sunucusunun açılması ve prod dağıtımını onaylamak (her prod dağıtımı Hasan'ın elinden geçer) | N05-N06 | H2, H14, H15, C13 |

### 3.3 Sunucuda ilk kurulum sırası (staging, sonra aynısı prod için)

1. **[Hasan]** VM açılır (Ubuntu LTS), SSH anahtarı eklenir, sağlayıcı güvenlik duvarı: 22 kısıtlı, 443 yalnız Cloudflare aralıkları, 80 kapalı.
2. **[Hasan]** Claude'un hazırladığı temel sertleştirme komutları: `deploy` kullanıcısı, root ve parola ile SSH girişi kapalı, otomatik güvenlik güncellemeleri, Docker Engine ve Compose eklentisi, saat dilimi UTC.
3. **[Hasan]** `/srv/netkar/staging/` dizini, `infra/prod/` dosyalarının kopyası, `gen_env.sh staging` ile `.env` üretimi; Origin CA sertifikası `/srv/netkar/staging/caddy/`.
4. **[Hasan]** `docker compose up -d postgres` (ilk açılışta `01-roles.sh` beş rolü kurar), ardından `deploy.sh staging sha-<ilk>`: ön kontrol, `migrate` (`netkar_owner`), api, worker, web, caddy.
5. **[Hasan]** **Ayrı işaretleme adımı** (yalnız staging, bir kez): `mark_staging.sh`. Bu betik `DATABASE_ADMIN_URL` ile `NETKAR_ENV=staging ... seed_demo --demo --mark-non-prod` çalıştırır ve `deployment_marks.non_production='true'` yazar. Prod'da bu adım **yoktur**; prod'da yapılırsa C5 kilidi api ve worker'ı açtırmaz.
6. **[Hasan]** Demo tohumu (§5), cron işleri (yedek, geri yükleme testi, uyarılar), harici uptime izlemesi.
7. **[Claude]** Duman testi listesi: `https://staging.<alan>/` basic auth sonrası 200, `/api/v1/health/ready` 200, demo hesabıyla giriş, Özet ekranı, 45 sn'den uzun süren bir rapor isteğinin 503 problem+json ile döndüğünün görülmesi (test kancasıyla), worker heartbeat'in son 5 dakikada yazılmış olması.
8. **[Hasan]** İlk gece yedeği ve ilk geri yükleme testinin sonucunu görmek.

## 4. CD akışı

### 4.1 `main` → staging (otomatik)

```
push main
  └─ netkar-ci (var): ruff, mypy, pytest (kapsam %90), web lint/typecheck/test, gitleaks, semgrep, pip-audit, npm audit, trivy fs
       └─ başarılıysa netkar-cd (yeni, workflow_run):
            1. api ve web imajını derle, etiket sha-<kısa>, GHCR'a it, Trivy imaj taraması (HIGH/CRITICAL'da dur)
            2. staging'e SSH (kısıtlı anahtar): deploy.sh staging sha-<kısa>
            3. duman testi (health/ready, giriş sayfası 200); başarısızsa deploy.sh otomatik geri döner ve iş kırmızı olur
```

- Dağıtımlar `concurrency: netkar-deploy-<ortam>` ile sıraya girer, iki dağıtım üst üste binmez.
- Staging dağıtımı demo tohumuna dokunmaz. Tohum ayrı, elle çalışan bir adımdır (§5).
- Tek VM'de `docker compose up -d` konteynerleri yeniden yaratır; birkaç saniyelik kesinti olur. MVP için kabul edilebilir, sıfır kesinti hedefi yok.

### 4.2 Prod (manuel onay)

- Prod'a yalnız **staging'de duman testinden geçmiş** bir etiket gider. İş akışı `workflow_dispatch` ile, girdi olarak etiket (`sha-<kısa>`) alır ve etiketin staging `RELEASES` dosyasında başarılı olarak yer aldığını kontrol eder.
- Onay: GitHub Environments'ta `production` ortamı ve "required reviewers" kuralı (Hasan). **Dikkat:** GitHub belgelerine göre özel repolarda bu koruma kuralı her planda yok; benim bildiğim kadarıyla özel repoda required reviewers için Enterprise gerekiyor (emin değilim, §9). Destek yoksa yedek düzen: prod işini yalnız Hasan tetikler (repo yazma yetkisi tek kişide), iş girdi olarak `ONAY=<etiket>` metnini ister ve prod SSH anahtarı yalnız bu işin ortam sırrındadır. Bundan da basit yol: Hasan kendi terminalinden `ssh deploy@prod deploy.sh prod sha-<kısa>`.
- Prod dağıtım betiği (§4.3) şu durumlarda **başlamaz**: veritabanında `non_production` işareti var; son başarılı yedek 26 saatten eski; diskte %20'den az yer var; ön kontrol (§4.4) başarısız.

### 4.3 Dağıtım betiği adımları ve geri dönüş komutu

`deploy.sh prod sha-abc123`:

1. Kilitler (aynı anda tek dağıtım), `RELEASES` dosyasından şu anki etiketi okur.
2. Koruma kontrolleri: işaret yokluğu (prod), yedek yaşı, disk, `.env` izinleri 600.
3. **Migrasyon öncesi yedek:** `pg_dump -Fc` yerel diske ve restic ile uzak depoya (prod'da zorunlu, staging'de atlanabilir).
4. `docker compose pull` (imaj özetleri kaydedilir).
5. `docker compose run --rm migrate python -m app.tools.migrate_preflight && alembic upgrade head` (`netkar_owner`).
6. `docker compose up -d --no-deps api worker web`.
7. Sağlık bekleme: api `/v1/health/ready` 200, web 200, worker heartbeat; en çok 120 sn.
8. Başarısızsa kodu bir önceki etikete döndürür (şema olduğu yerde kalır) ve hata kodu verir; başarılıysa `RELEASES` dosyasına `<zaman> <etiket> <alembic head> ok` yazar.

**Geri dönüş komutu:**

```sh
/srv/netkar/bin/deploy.sh prod rollback          # RELEASES'teki bir önceki başarılı etikete döner
/srv/netkar/bin/deploy.sh prod rollback sha-9f1e2d  # belirli etikete döner
```

Geri dönüş yalnız **kodu** döndürür. Bunun güvenli olması için migrasyon kuralı: her şema değişikliği bir önceki kod sürümüyle de çalışmalı (genişlet, sonra daralt: sütun silme ya da ad değiştirme iki ayrı sürümde yapılır). Şemanın da geri alınması gerekirse:

```sh
docker compose run --rm migrate alembic downgrade <hedef_revizyon>   # netkar_owner ile
```

Bunu yalnız o migrasyonun geri alınması `tests/test_migrations.py` ile denenmişse yapın. Bazı geri almalar kullanıcı verisi varken kasıtlı olarak durur (ör. 0007 ve 0008'deki `_guard_user_data`, `_guard_history`). O durumda seçenek, 3. adımdaki migrasyon öncesi yedeğe dönmektir; bu, yedekten sonra yazılan veriyi kaybettirir ve Hasan'ın kararıdır.

### 4.4 Migrasyon güvenliği

Kurallar:

- **Her migrasyon geri alınabilir.** Repodaki desen zaten böyle (`downgrade()` her dosyada var; 0014 gibi yalnız doğrulayan migrasyonlarda güvenli no-op). `tests/test_migrations.py` aşağı-yukarı gidiş dönüşü ve 0003, 0015 için yetki ayrıntısını sınıyor.
- **Her zaman `netkar_owner` ile.** Süper kullanıcıyla migrasyon nesne sahipliğini bozar; 0014 tam olarak bu yüzden yazıldı (0012 süper kullanıcıyla çalıştırılınca `report_data_revisions` tablosunun sahibi yanlış kalmış, ertelenmiş tetikleyici COMMIT anında bütün motor girdisi yazımlarını düşürürdü). 0014 sessizce düzeltmez, durur; bu plan da aynı ilkeyi izler.
- **Migrasyon başına işlem** (`env.py`: `transaction_per_migration=True`); hata o migrasyonu geri sarar.
- **Kilit süresi sınırı** (C7): canlı trafikte uzun kilit beklenirse migrasyon düşer, tekrar denenir.

Ön kontrol (C6) taslağı, `netkar_owner` bağlantısıyla:

```sql
-- 1) Doğru rol, yetkisiz özellik yok
SELECT current_user = 'netkar_owner' AS rol_dogru, NOT r.rolsuper AND NOT r.rolbypassrls AS ozellik_dogru
FROM pg_catalog.pg_roles r WHERE r.rolname = current_user;

-- 2) Altı rol var ve hiçbiri süper kullanıcı ya da BYPASSRLS değil
SELECT rolname, rolcanlogin, rolsuper, rolbypassrls FROM pg_catalog.pg_roles
WHERE rolname IN ('netkar_owner','netkar_app','netkar_worker','netkar_auth','netkar_sync_gate','netkar_notify_gate');

-- 3) public şemasında sahibi netkar_owner olmayan tablo (0013 denetiminin genellemesi)
SELECT c.relname, pg_catalog.pg_get_userbyid(c.relowner) AS sahip
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
  AND pg_catalog.pg_get_userbyid(c.relowner) <> 'netkar_owner';

-- 4) 0014'ün denetlediği iki nesne (tablo ve işlev) netkar_owner'da
-- 5) Şema sahipleri: auth_gate -> netkar_auth, sync_gate -> netkar_sync_gate,
--    notify_gate -> netkar_notify_gate, alert_gate -> netkar_owner
SELECT nspname, pg_catalog.pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace
WHERE nspname IN ('auth_gate','sync_gate','notify_gate','alert_gate');

-- 6) Yalnız prod: üretim değil işareti OLMAMALI (tablo henüz yoksa, yani 0015 öncesi, geçer)
SELECT count(*) FROM public.deployment_marks WHERE key = 'non_production';
```

Beklenen sonuçtan sapma varsa betik hiçbir migrasyonu çalıştırmadan, 0014'teki gibi Türkçe ve ne yapılacağını söyleyen bir iletiyle durur. 3. sorgunun bugünkü şemada boş döndüğü test veritabanında doğrulanacak (C6 testinin ilk işi); istisna çıkarsa (ör. procrastinate tabloları) beklenen sahip listesi migrasyonlardan çıkarılıp betiğe yazılır.

## 5. Staging verisi

**Demo tohumu (services/api README, "Demo veri tohumu").** Staging'de veri yalnız demo tohumundan gelir. Sunucuda api imajının içinden çalışır (uv yerelde değil):

```sh
cd /srv/netkar/staging
docker compose run --rm -e NETKAR_ENV=staging -e NETKAR_DEMO_PASSWORD \
  api python -m app.tools.seed_demo --demo --instance 2 --dataset all --as-of 2026-11-27 \
  --card-path /tmp/demo_cevap_karti.md
```

- Betiğin korumaları staging'e uygun: `NETKAR_ENV=staging`, `ENVIRONMENT` prod değil (C4 ile `staging`), `TRENDYOL_ENVIRONMENT` live değil, veritabanı adında `prod/canli/live` yok, app ve worker bağlantıları aynı sunucuda, roller `netkar_app` ve `netkar_worker`, ikisi de süper kullanıcı ya da BYPASSRLS değil, **`deployment_marks.non_production` işareti var** (yoksa betik durur; işaret §3.3 adım 5'te ayrıca konur).
- Parola: README, CI günlüğü tutulan ortamda rastgele üretim yerine `NETKAR_DEMO_PASSWORD` kullanılmasını istiyor. Tohum CD hattında değil, sunucuda elle çalıştığı için iki yol da olur; yine de parolayı parola yöneticisinden ortam değişkeniyle vermek ekranda iz bırakmaz.
- Kart: konteyner salt okunur, yalnız `/tmp` yazılabilir; kart `--card-path /tmp/...` ile yazılır ve `docker compose cp` ile alınır. Kartın rakamları gerçek motordan üretilir (README), bu yüzden staging'de üretilen kart staging verisiyle birebir tutar.
- Tazeleme: test gününden önce aynı komut `--as-of <bugün>` ile yeniden çalışır; idempotent, tarihleri kaydırır, katılımcının ayarlarını ezmez. Tohum sürümü değişirse aynı veritabanında yeniden tohumlama reddedilir: temiz `--instance` ya da staging veritabanını sıfırlama (staging'de kabul edilebilir).

**Trendyol stage API ve senkron.** Demo hesapları `is_demo = true` ile işaretlenir; `sync_gate.syncable_accounts` ve sync_gate politikası `NOT is_demo` ister (0015). Worker staging'de açık kalsa bile demo hesapları görmez, Trendyol'a istek atmaz, hesaplar `invalid` olmaz. Bu yüzden ilk aşamada staging'de **senkron yoktur** ve Trendyol stage erişimi gerekmez; worker yalnız heartbeat ve hız sınırı temizliği çalıştırır (altyapının çalıştığının kanıtı). Stage entegrasyonu ileride istenirse: `TRENDYOL_ENVIRONMENT=stage`, stage satıcı hesabı ve staging VM'in IP'sinin Trendyol tarafından yetkilendirilmesi gerekir (`docs/10_mimari.md` §3.4: stage IP izni ister; yetki yoksa 503) [Hasan, H13].

**Gerçek mağaza (K-N06) ile çelişki.** K-N06 "pilot anahtarı yalnız staging'e, şifreli" diyor. Ancak Hasan'ın gerçek mağazası `TRENDYOL_ENVIRONMENT=live` ister, demo tohumu ise live ortamda çalışmaz; ayrıca "üretim değil" işaretli bir veritabanına gerçek anahtar koymak işaretin anlamını bulandırır. Önerim: pilot mağaza **prod'a ilk kiracı olarak** bağlansın, KVKK yolu netleşince. Karar Hasan'da (§8).

**Kullanılabilirlik testi katılımcıları nasıl hesap alır.**

1. Katılımcı kayıt olmaz. Her katılımcı için ayrı bir tohum örneği: `--instance N` (1-99). Kod, hesap e-postalarını `demo-<anahtar>-<N>@<demo alanı>` biçiminde örnek başına ayrı üretiyor; README'ye göre her örnek temiz bir Hesap A verir (G2 ve G3 ayarları değiştirir ve ayarlar silinemez). Hesap B'nin (X, Y) örnekler arasında ayrı olup olmadığını ilk pilot oturumdan önce deneyeceğim.
2. Oturum başında moderatör, katılımcıya görüntülü görüşmenin sohbet kutusundan iki şey verir: staging basic auth bilgisi ve o örneğin demo hesap girişi. Telefon görevi (G8) için aynı adres telefondan açılır.
3. Oturumdan sonra `--reset-passwords` ile o örneğin parolaları yenilenir; basic auth parolası haftalık değişir.
4. Katılımcının kendi Trendyol anahtarı istenmez (S4 planı §3.1). Ekranda son müşteri verisi yoktur.
5. Erişim günlüğündeki IP maskelidir (§2.2); oturum kaydı ve saklama süresi S4 planı §3.4'e göre ayrıca yönetilir.

## 6. İzleme ve uyarı (en az)

Metrik altyapısı (Prometheus vb.) yok (runbook_rapor_motoru.md notu). Başlangıç düzeni: Docker sağlık kontrolleri, VM'de cron ile çalışan küçük betikler, harici uptime izleme ve (eklenince) Sentry.

| # | Ne | Nasıl | Eşik | Önem | Kanal |
|---|---|---|---|---|---|
| M1 | Dış erişim | Harici uptime izleme: `https://app.<alan>/api/v1/health/ready` (web üzerinden API ve DB) ve ana sayfa; staging için de ayrı, daha seyrek | 2 ardışık hata | kritik (prod), uyarı (staging) | Hasan (H12) |
| M2 | API canlılığı | Dockerfile'daki `HEALTHCHECK` (`/v1/health`, 30 sn); `restart: unless-stopped` | 3 hata | uyarı | log |
| M3 | Web ve postgres | Web için yeni `HEALTHCHECK` (C1); postgres `pg_isready` (compose'da var) | 3 hata | uyarı | log |
| M4 | Worker | `worker_heartbeat.sh`: son başarılı `netkar.heartbeat` işi (dakikada bir planlı, `app/worker/tasks.py`) 5 dakikadan eski mi | > 5 dk | kritik | Hasan |
| M5 | **Takılan rapor motoru** | `log_alerts.sh` her 5 dk: api logunda `profit_engine_abandoned` satırları; `abandoned >= process_slots` ise bütün raporlar bloktur. Aynı `pid` için `profit_engine_abandoned_finished` 10 dk içinde gelmezse motor takılı | `abandoned >= process_slots`: kritik; eşleşmeyen terk: uyarı | kritik/uyarı | Hasan; çözüm `runbook_rapor_motoru.md` (ilgili süreci yeniden başlat) |
| M6 | DB süre aşımı | Aynı betik: `profit_statement_timeout`, `db_statement_timeout` sayısı | 15 dk'da > 5 | uyarı | Hasan |
| M7 | Disk | `disk_and_backup_age.sh`: kök disk ve Docker birimleri | %80 uyarı, %90 kritik | uyarı/kritik | Hasan |
| M8 | Yedek yaşı | Son başarılı restic anlık görüntüsü | > 26 saat | kritik | Hasan |
| M9 | Geri yükleme testi | Haftalık `restore_test.sh` sonucu | başarısız | kritik | Hasan |
| M10 | Senkron sağlığı (prod) | `sync_runs` son 24 saatte `error_class` dağılımı, `invalid` olan hesap sayısı (README'deki sorgu) | yeni `invalid` hesap ya da hata oranı > %20 | uyarı | Hasan |
| M11 | Uygulama hataları | Sentry (C14), kişisel veri süzgeçli | yeni hata türü | uyarı | Hasan |
| M12 | TLS | Uptime izlemesinin sertifika bitiş kontrolü (Origin CA uzun ömürlü; kenar sertifikası Cloudflare'de) | < 14 gün | uyarı | Hasan |

Uyarı betikleri log satırının yalnız anahtar alanlarını (`pid`, `account`, sayaçlar) iletir; log gövdesi bildirime kopyalanmaz.

## 7. Maliyet (TL/ay, KDV hariç)

Kur ve fiyat kaynağı: `calisma_dosyalari/maliyet_modeli.py` (1 EUR = 56,2588 TL, 1 USD = 50,0260 TL; TCMB gösterge, 5 Kasım 2026) ve `calisma_dosyalari/fiyatlar_2026-11-05.csv`. Güzel Hosting rakamı `calisma_dosyalari/karar_hesap_2026-11-07.py` içinden. Aşağıdaki TL değerleri bu sabitlerle aynı yuvarlama kuralıyla hesaplandı. Repoda karşılığı olmayan kalem **doğrulanmadı** olarak işaretlidir; uydurma fiyat yoktur.

| Kalem | A · Hetzner | B · Güzel Hosting | Kaynak ve güven |
|---|---|---|---|
| Prod sunucusu | 477,64 (CX33, 8,49 EUR) | 1.349,91 (Private Cloud 3, 16.198,90 TL/yıl ÷ 12) | A: fiyatlar CSV, orta; B: karar_hesap, üçüncü taraf liste, resmi değil |
| IPv4 | 28,13 (0,50 EUR) | pakete dahil mi: doğrulanmadı | A: fiyatlar CSV, orta |
| Uzak yedek (~20 GB) | 15,01 (R2, 0,30 USD) | 15,01 (R2 varsayımı) | maliyet_modeli.py; B'de yurt içi seçenek doğrulanmadı |
| E-posta (Resend Free, 3.000/ay) | 0 | 0 | maliyet_modeli.py, fiyatlar CSV orta |
| Hata izleme (Sentry Developer) | 0 | 0 | maliyet_modeli.py |
| Cloudflare Free (DNS, WAF, TLS) | 0 | 0 | maliyet_modeli.py sıfır alıyor; CSV'de "doğrulanmadı" |
| **Altyapı ara toplamı (modeldeki)** | **520,78** | **1.364,92** | |
| İşletme gideri (mali müşavir 3.593 + Paraşüt 752 + alan adları 108,37) | 4.453,37 | 4.453,37 | maliyet_modeli.py `ISLETME["sahis"]` |
| **Toplam (karar kaydındaki rakam)** | **4.974,15** | **5.818,29** | `docs/karar_kaydi.md` K-N02: 4.974 ve 5.818 |
| *Bu planın eklediği kalemler* | | | |
| Ayrı staging sunucusu | 336,99 (CX23 5,49 EUR = 308,86 + IPv4 28,13) | doğrulanmadı | A: fiyatlar CSV, orta; CX satılabilirliği çelişkili |
| Yedek alanı büyümesi | 0,75 TL/GB-ay (R2 0,015 USD) | aynı ya da doğrulanmadı | fiyatlar CSV, orta-yüksek |
| Sağlayıcı sunucu yedeği / anlık görüntü | doğrulanmadı | doğrulanmadı | CSV: "teyitli rakam yok" |
| Harici uptime izleme | doğrulanmadı | doğrulanmadı | CSV: "aranmadı" |
| GHCR özel imaj depolama | doğrulanmadı | doğrulanmadı | repoda yok |
| Parola yöneticisi | doğrulanmadı | doğrulanmadı | repoda yok |
| Avukat (KVKK değerlendirmesi) | doğrulanmadı | doğrulanmadı | repoda yok |
| **Toplam, ayrı staging ile (doğrulanmamışlar hariç)** | **5.311,14** | **5.818,29 + staging (doğrulanmadı)** | |

Notlar:

- Toplamın büyük kısmı barındırma değil işletme gideri (4.453,37 TL). Barındırma farkı A ile B arasında aylık 844 TL (karar kaydı).
- Güzel Hosting'in staging için ikinci sunucu fiyatı bilinmediği için B'de ayrı staging maliyeti hesaplanamadı. Teklif alınmadan iki yol "staging dahil" karşılaştırılamaz.
- Fiyatlar 5 Kasım kuruyla; Hetzner fiyatları EUR olduğu için kur oynadıkça TL tutarı değişir. Haziran 2026 Hetzner zammı CSV'ye işlenmiş (CPX ve CCX için).

## 8. Riskler ve açık kararlar

### 8.1 Hasan için tarihli karar listesi

| Tarih | Karar | Önerim | Ne olmazsa ne olur |
|---|---|---|---|
| 18 Kas 2026 | Hetzner'e KVKK sorusunu göndermek (H1) | Gönder, metin hazır | 1 Aralık kararı ertelenir |
| 20 Kas 2026 | Staging nerede (Hetzner demo-only mi, Güzel mi) (H3) | Hetzner'de yalnız demo veriyle, IP maskeli log, basic auth; avukata ayrıca sor | N03'te staging açılmaz, uzaktan test kayar (S4 planı) |
| 20 Kas 2026 | Alan adı alımı ve DNS'in Cloudflare'e taşınması (H4) | `nettablo.com` ve `.com.tr` uygunluğunu kontrol edip al | Staging adresi olmaz |
| 20 Kas 2026 | Coolify/Dokploy mu, düz Compose + betik mi | Düz Compose + `deploy.sh`: daha az hareketli parça, panel ve onun güvenliği (G18'deki 2FA'lı panel) gerekmez. Sonradan Coolify'a geçmek mümkün | Mimari belgesiyle küçük sapma; G18 metni güncellenir |
| 27 Kas 2026 | K-N06 pilot mağaza: staging mi, prod mu | Prod'a ilk kiracı olarak, KVKK yolu netleşince | Staging'de gerçek anahtar ile "üretim değil" işareti yan yana durur |
| 27 Kas 2026 | Uyarı kanalı ve uptime izleme hesabı (H12) | E-posta + bir anlık bildirim kanalı (Telegram botu gibi) | Uyarılar yalnız log'da kalır |
| 27 Kas 2026 | GitHub ortam onayı desteklenmiyorsa prod onay düzeni (§4.2) | Hasan'ın elle tetiklediği iş ya da Hasan'ın terminalinden SSH | Onay adımı yazılı ama zorlanmamış olur |
| 1 Ara 2026 | **K-N02 son kararı** (H2) | Hetzner yanıtı "imzalarız" ise A, değilse ya da yanıt yoksa B | Prod sunucusu açılamaz, beta (N05) kayar |
| 4 Ara 2026 | Avukat görüşü: tüm yurt dışı işleyenler, aydınlatma metni, VERBİS (H15) | Beta öncesi şart | Gerçek satıcı verisi alınamaz |
| 4 Ara 2026 | Resend alan adı doğrulaması (H14) | Prod öncesi | Parola sıfırlama e-postası gitmez, prod açılmaz |
| 21 Ara 2026 (S8 öncesi) | PITR (WAL arşivi) geçişi | İlk ödeyen satıcıdan önce geç | RPO 24 saat kalır; satıcının girdiği maliyetlerde bir günlük kayıp riski |
| 21 Ara 2026 | `audit_log` ve log saklama/imha süreleri (G16 politikası) | Avukatla birlikte, §2.9 tablosundan başla | Saklama süresi belirsiz kalır |

### 8.2 Riskler

| Risk | Olasılık | Etki | Azaltma |
|---|---|---|---|
| Hetzner standart sözleşmeyi imzalamaz | orta (güven orta, hetzner_kvkk_kontrol.md) | A kapanır | Kod sağlayıcıdan bağımsız; B'ye geçiş birkaç saatlik iş (`docs/20_maliyet.md`) |
| Standart sözleşme imzalanıp bildirim 5 iş günü içinde yapılmaz | düşük | idari para cezası (repo kaynağı: 2026 için 90.308-1.806.377 TL; resmi kaynaktan teyit edilmedi) | Bildirim tarihi takvime, imza günü yazılır |
| Diğer yurt dışı işleyenler (Cloudflare, Resend, R2, Sentry) gözden kaçar | orta | B yolunda bile KVKK açığı | H15 kapsamına alındı (§2.9 envanteri) |
| Tek VM tek hata noktası | orta | RTO 4 saat hedefi | Haftalık geri yükleme testi, yazılı runbook (C15), `.env` ve anahtar yedeği ayrı |
| KEK ya da `DATA_ENCRYPTION_KEY` kaybı | düşük | Pazaryeri anahtarları ya da TOTP sırları çözülemez | H11: parola yöneticisinde ayrı kayıt; ADR-0004 prosedürü |
| Prod veritabanına yanlışlıkla `non_production` işareti yazılır | düşük | Demo bayrağı açılabilir hale gelir | C5 kilidi api ve worker'ı açtırmaz; C10 betiği yalnız `netkar_staging` adına yazar; dağıtım betiği kontrol eder |
| Migrasyon yanlış rolle çalışır | düşük (bir kez yaşandı) | Ertelenmiş tetikleyicide yazımlar düşer (0014) | C6 ön kontrolü, compose'da yalnız `netkar_owner` URL'i |
| Zaman aşımı zinciri yanlış (web 30 sn) | yüksek (bugün böyle) | Takılan raporda kullanıcı problem+json yerine kopuk bağlantı görür | C3, C2; duman testinde 45 sn senaryosu |
| CX33/CX23 sipariş edilemiyor | orta (CSV notu) | Fiyat ve model değişir | Hesap açmadan resmi sayfa; eşdeğer model seçilir, maliyet tablosu güncellenir |
| Güzel Hosting Docker/root vermiyor ya da paket özellikleri yetersiz | bilinmiyor | B yolu bu plana uymaz | Teklif öncesi yazılı soru: root, Docker, vCPU/RAM/disk, yedek, güvenlik duvarı |
| Staging herkese açık kalır, rastgele kişiler kayıt olur | orta | Staging'e gerçek kişisel veri girer | Caddy `basic_auth`, `noindex`; demo dışı kayıt beklenmez |
| Tek VM'de canlı trafik altında migrasyon kilidi | düşük-orta | Kısa süre tüm istekler bekler | C7 `lock_timeout`, genişlet-sonra-daralt kuralı |
| Trendyol stage IP izni gecikir | orta | Staging'de entegrasyon denemesi yapılamaz | İlk aşamada gerekmiyor (demo hesapları senkron dışı) |

## 9. Kaynaklar

Repo içi belgeler başta listelendi; burada yalnız dış kaynaklar var. Emin olmadığım adres ya da ayrıntılar işaretli.

Cloudflare. (t.y.). *Error 524: A timeout occurred*. Cloudflare Docs. https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/ (100 saniyelik köken sınırı bildiğim değer; adres yolu emin değilim)

Caddy. (t.y.). *reverse_proxy (Caddyfile directive)*. Caddy Documentation. https://caddyserver.com/docs/caddyfile/directives/reverse_proxy

Caddy. (t.y.). *log (Caddyfile directive)*. Caddy Documentation. https://caddyserver.com/docs/caddyfile/directives/log (`ip_mask` süzgecinin tam sözdizimi kurulumda teyit edilecek; emin değilim)

Docker. (t.y.). *JSON File logging driver*. Docker Docs. https://docs.docker.com/engine/logging/drivers/json-file/

Docker. (t.y.). *Services top-level elements (Compose file reference)*. Docker Docs. https://docs.docker.com/reference/compose-file/services/

GitHub. (t.y.). *Managing environments for deployment*. GitHub Docs. https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-deployments/managing-environments-for-deployment (adres yolu ve plan koşulları değişmiş olabilir; emin değilim)

Hetzner Online GmbH. (t.y.). *Data protection at Hetzner*. https://docs.hetzner.com/general/company-and-policy/data-protection-at-hetzner

Kişisel Verileri Koruma Kanunu, 6698 sayılı Kanun. (2016, 7 Nisan). *Resmî Gazete* (Sayı: 29677). https://www.mevzuat.gov.tr/mevzuatmetin/1.5.6698.pdf

Kişisel Verileri Koruma Kurumu. (2024). *Standart sözleşmeler*. https://www.kvkk.gov.tr/Icerik/7929/Standart-Sozlesmeler

Kişisel Verileri Koruma Kurumu. (2025, 5 Şubat). *Yurt dışına kişisel veri aktarımında kullanılacak standart sözleşmelerde dikkat edilmesi gereken hususlara ilişkin kamuoyu duyurusu*. https://www.kvkk.gov.tr/Icerik/8170/Yurt-Disina-Kisisel-Veri-Aktariminda-Kullanilacak-Standart-Sozlesmelerde-Dikkat-Edilmesi-Gereken-Hususlara-Iliskin-Kamuoyu-Duyurusu

Ceza Muhakemesi Kanunu ile Bazı Kanunlarda Değişiklik Yapılmasına Dair Kanun, 7499 sayılı Kanun. (2024, 12 Mart). *Resmî Gazete* (Sayı: 32487). (KVKK m.9 değişikliği; kanun ve sayı numarası emin değilim, resmi kaynaktan teyit edilecek)

PostgreSQL Global Development Group. (t.y.). *pg_dump*. PostgreSQL 16 Documentation. https://www.postgresql.org/docs/16/app-pgdump.html

PostgreSQL Global Development Group. (t.y.). *pg_dumpall*. PostgreSQL 16 Documentation. https://www.postgresql.org/docs/16/app-pg-dumpall.html

PostgreSQL Global Development Group. (t.y.). *Continuous archiving and point-in-time recovery (PITR)*. PostgreSQL 16 Documentation. https://www.postgresql.org/docs/16/continuous-archiving.html

PostgreSQL Global Development Group. (t.y.). *Row security policies*. PostgreSQL 16 Documentation. https://www.postgresql.org/docs/16/ddl-rowsecurity.html

PostgreSQL Global Development Group. (t.y.). *Client connection defaults* (`lock_timeout`, `statement_timeout`). PostgreSQL 16 Documentation. https://www.postgresql.org/docs/16/runtime-config-client.html

restic authors. (t.y.). *restic documentation*. https://restic.readthedocs.io/

Vercel. (2026). *next* (Sürüm 15.5.29) [Yazılım]. `node_modules/next/dist/server/lib/router-utils/proxy-request.js` dosyası, `proxyTimeout || 30000` satırı; bu oturumda kurulu paketten okundu. Next.js belgelerinde `experimental.proxyTimeout` sayfasının adresinden emin değilim.
