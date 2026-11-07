# NetKâr · Sistem Mimarisi (v0.1, 5 Kasım 2026)

> Çalışma adı NetKâr. Marka kontrolü bitmeden kalıcı isim değildir.
> Bu doküman canlıdır. Değişiklikler `calisma_dosyalari/degisiklik_kaydi.tsv` dosyasına işlenir.

## 1. Özet

- **Ürün:** Trendyol satıcısının API anahtarıyla bağlanan, ürün ve sipariş bazında **gerçek net kâr**, ROAS ve kârlılık uyarıları veren B2B SaaS. Mobil öncelikli PWA, ikinci fazda native mobil (Expo).
- **Fark:** Sipariş anında "tahmini kâr", Trendyol hakediş ekstresi gelince "kesinleşmiş kâr". İkisi arasındaki farkı (kaçak kesinti) gösterir.
- **Mimari ilke:** Tek geliştirici + ajan ekibiyle yönetilebilir, ucuz, güvenli, ölçeklenebilir. "Sıkıcı teknoloji": PostgreSQL her şeyin merkezi; ayrı Redis/kuyruk servisi yok.
- **Ölçek yolu:** Pazaryeri adaptör katmanı (Trendyol → Hepsiburada → n11 → Amazon SP-API → Shopify), çok para birimi, TR/EN arayüz.

## 2. Bileşenler

```
                 ┌──────────────── Cloudflare (DNS, TLS, WAF, CDN, Turnstile) ───────────────┐
                 │                                                                            │
   Kullanıcı ──► │  apps/web  (Next.js 15, App Router, TS)                                    │
   (mobil/PWA)   │   ├─ (marketing)  LP, fiyatlar, ücretsiz hesaplayıcılar, blog (SSG/ISR)    │
                 │   └─ (app)        Panel: kâr, ürünler, siparişler, uyarılar, ayarlar        │
                 │            │  HttpOnly çerez oturumu, BFF üzerinden API çağrısı              │
                 │            ▼                                                               │
                 │  services/api  (Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2)           │
                 │   ├─ auth, kiracı (tenant) yönetimi, abonelik                              │
                 │   ├─ bağlantılar: pazaryeri hesabı ekleme, anahtar şifreleme               │
                 │   ├─ kâr motoru (saf Python, deterministik, %100 test)                     │
                 │   └─ rapor/uyarı API'leri                                                  │
                 │            │                                                               │
                 │  services/worker (aynı kod tabanı, ayrı süreç)                             │
                 │   ├─ procrastinate (PostgreSQL tabanlı iş kuyruğu, periyodik görevler)     │
                 │   ├─ Trendyol senkron: siparişler, iadeler, finans, ürünler, sorular        │
                 │   ├─ mutabakat: tahmini ↔ kesinleşmiş kâr                                  │
                 │   └─ bildirim: e-posta (Resend/SES), web push, (faz 2) mobil push           │
                 │            │                                                               │
                 │  PostgreSQL 16 (tek veritabanı, kiracı izolasyonu: tenant_id + RLS)        │
                 │  Nesne depolama (şifreli yedekler, rapor PDF'leri)                         │
                 └────────────────────────────────────────────────────────────────────────────┘
   Dış: Trendyol API · Ödeme kuruluşu (iyzico/PayTR, tokenize abonelik) · e-Arşiv entegratörü
        · LLM API (faz 2, maskelenmiş veri) · Sentry · uptime izleme · PostHog (çerez onaylı)
```

### 2.1 Neden bu yığın?
| Karar | Seçim | Gerekçe | Alternatif (reddedildi) |
|---|---|---|---|
| Web/LP | Next.js 15 + Tailwind + shadcn/ui | SEO için SSG/ISR, panel ve LP tek kod tabanı, PWA desteği | Ayrı WordPress LP (iki sistem, iki güvenlik yüzeyi) |
| Backend | Python FastAPI | Kâr motoru ve veri işleme Python'da test edilmesi en kolay; kullanıcı tercihi | Next.js API routes (uzun senkron işler için uygun değil) |
| Kuyruk | procrastinate (Postgres) | Redis yok, bir servis eksik, işlemsel tutarlılık | Celery + Redis (ek maliyet ve bakım) |
| DB | PostgreSQL 16 + RLS | Kiracı izolasyonu veritabanı seviyesinde | Kiracı başına DB (erken aşamada gereksiz) |
| Mobil | Faz 1 PWA, Faz 2 Expo | Mağaza onayı ve %15-30 komisyon olmadan hızlı çıkış; ödeme web'de | İlk günden native (2x iş) |
| Deploy | Docker Compose + Coolify/Dokploy, tek VM | Aylık maliyet düşük, tek komutla geri dönüş | Kubernetes (erken) |
| Barındırma yeri | **Öneri: Türkiye'de VPS** (karar K-N02). AB seçilirse KVKK m.9 standart sözleşme + 5 iş günü içinde Kurum'a bildirim | KVKK ve Trendyol EK-6 riski; maliyet farkı ayda ~1.550 TL | Yurt dışı yönetilen bulut (aktarım yükü, ölçekte pahalı) |

## 3. Veri akışı ve senkron stratejisi

1. **Bağlantı:** Satıcı panelde Satıcı ID, API Key, API Secret girer. API bir test çağrısıyla doğrular. Anahtar AES-256-GCM ile zarf şifreleme yapılarak saklanır (veri anahtarı başına KEK; KEK ortam değişkeninde, faz 2'de KMS). Düz metin anahtar hiçbir log'a yazılmaz.
2. **İlk yükleme (backfill):** (ayrıntı ve kararlar: ADR-0005) Siparişler `orders/stream` (cursor, son 3 ay, 14 günlük pencereler); ekstre `settlements` ve `otherfinancials` (15 günlük pencereler, kayıt teslimattan sonra oluşur); kargo faturası kalemleri `cargo-invoice/{seri}/items`. İlerleme çubuğu kullanıcıya gösterilir. İlk "aha anı": ilk 10 dakikada en çok satan 20 ürünün tahmini kârı.
3. **Artımlı senkron:** Sipariş paketi statüleri webhook ile (satıcı başına en fazla 15 webhook, en az bir kez teslim → işlem idempotent olmalı), yedek olarak 15 dakikada bir `v2/orders` polling; iadeler (`claims`) 15 dakikada bir; ekstre günde 2 kez; ürün kataloğu ve komisyon oranları günde 1 kez; sorular (faz 2) 10 dakikada bir.
4. **Trendyol istemci kuralları (research/01):** Taban URL `https://apigw.trendyol.com` (eski `api.trendyol.com/sapigw` kapandı); stage `stageapigw.trendyol.com` (IP whitelist ister). Basic Auth (API Key:Secret). Zorunlu `User-Agent: "{sellerId} - <ÜrünAdı>"` (en fazla 30 alfanümerik, aksi 403). Rate limit: aynı uç noktaya 10 sn'de 50 istek; finans 100/dk, iade 1000/dk, sipariş 30-100/dk (listeleme seviyesine göre). Satıcı + uç nokta başına token bucket; 429'da üstel geri çekilme + jitter; tüm çağrılar `api_call_log` tablosuna (gövdesiz, yalnız meta).
5. **Veri minimizasyonu (KVKK + Trendyol sözleşmesi EK-6):** Sipariş yanıtındaki son müşteri adı, soyadı, açık adresi, telefonu, TCKN'si ve relay e-postası **ilk alım anında atılır, hiçbir yere yazılmaz** (log dahil). EK-6 müşteri verisiyle veri tabanı oluşturmayı yasaklıyor. Yalnız il ve takma adlı müşteri anahtarı (tuzlu HMAC; anonim değil, takma adlı veri sayılır) tutulur.
5a. **Reklam ve fatura düzeyi kesintiler:** API'de reklam harcaması yok. Satıcı panelden indirdiği reklam raporunu (Excel) yükler; ürün bazında eşlenir, eşlenemeyen kısım satış oranıyla dağıtılır ve "tahmini" etiketiyle gösterilir. Panel kazıma (scraping) yapılmaz.
6. **Mutabakat:** Her sipariş satırı `estimated` durumda başlar; finans ekstresinde eşleşen kayıtlar gelince `settled` olur. Fark > eşik ise uyarı üretilir ("Bu siparişte 37 TL beklenmeyen kesinti").

## 4. Kâr motoru (özet; ayrıntı `12_kar_motoru.md`)

Sipariş satırı başına:
```
Net kâr = Net satış (KDV hariç)
        − Ürün maliyeti (KDV hariç, kullanıcı girer veya toplu Excel)
        − Komisyon (KDV hariç)            [settled: ekstreden, estimated: kategori oranı]
        − Platform hizmet bedeli
        − Kargo (desi/anlaşma, settled: kargo faturasından)
        − Paketleme ve diğer değişken gider (kullanıcı tanımlı)
        − İade maliyeti payı (iade kargo + geri alınamayan bedeller, iade olasılığıyla dağıtılmış)
        − Reklam payı (Trendyol reklam + harici reklam, ürün bazında ya da satışa oranla dağıtılmış)
KDV etkisi ayrı satırda: satış KDV'si − (komisyon KDV'si + kargo KDV'si + maliyet KDV'si) = ödenecek KDV etkisi
Stopaj (%1 e-ticaret stopajı, doğrulanacak) gider değil, peşin vergi olarak nakit akışında ayrı gösterilir.
```
Tüm para işlemleri `Decimal` ile, kuruş hassasiyetinde; yuvarlama kuralı tek yerde.

## 5. Veri modeli (çekirdek tablolar)

| Tablo | Amaç | Kritik alanlar |
|---|---|---|
| `tenants` | Satıcı firma (hesap) | plan, durum, deneme bitişi, para birimi, dil |
| `users` | Kullanıcı | e-posta, argon2id parola özeti, rol (owner/admin/viewer), 2FA |
| `marketplace_accounts` | Pazaryeri bağlantısı | platform, seller_id, şifreli anahtar, son senkron, durum |
| `products` | Ürün | barkod, SKU, kategori, komisyon oranı, maliyet (geçmişli) |
| `product_costs` | Maliyet geçmişi | geçerlilik tarihi, birim maliyet, KDV oranı |
| `orders`, `order_lines` | Sipariş | sipariş no, tarih, fiyat, indirimler, durum, il, müşteri hash |
| `returns` | İade (kalem başına satır) | neden kodu, durum, iade kalemi stoğa döndü mü (kullanıcı işareti) |
| `financial_transactions` | Ekstre satırları | istek tipi, tutar, sipariş no eşlemesi, belge no |
| `cargo_invoice_items` | Kargo faturası kalemleri | fatura seri no, sipariş no, tutar, desi |
| `sync_runs`, `sync_cursors` | Senkron ilerlemesi ve imleç | kaynak, pencere, durum, sayaçlar, hata sınıfı; kaynak başına son başarılı pencere |
| `ad_spend` | Reklam harcaması | kaynak, tarih, ürün (varsa), tutar |
| `profit_snapshots` | Hesaplanmış kâr | satır bazında durum (estimated/settled), kalem kırılımı |
| `alerts` | Uyarılar | tür, önem, ürün/sipariş, okunma |
| `subscriptions`, `invoices` | Abonelik | ödeme kuruluşu token referansı (kart bilgisi yok) |
| `audit_log` | Denetim izi | kim, ne, ne zaman, IP (anonimleştirilmiş) |

Her kiracı tablosunda `tenant_id` + PostgreSQL Row Level Security politikası. Uygulama, veritabanına kiracı bağlamını `SET app.tenant_id` ile verir; yönetici işleri ayrı rol.

## 6. Güvenlik (özet; ayrıntı `50_guvenlik.md`)

- OWASP ASVS L2 hedefi; OWASP Top 10 ve API Security Top 10 kontrol listesi CI'da.
- Kimlik: argon2id, oturum HttpOnly + Secure + SameSite=Lax çerez, CSRF token, 2FA (TOTP), başarısız giriş limiti, Cloudflare Turnstile.
- Yetkilendirme: her uç noktada kiracı kontrolü + RLS (çift kilit). IDOR testleri zorunlu.
- Sırlar: API anahtarları zarf şifreleme; sırlar repo'ya girmez (gitleaks CI).
- Tedarik zinciri: Dependabot/Renovate, `pip-audit`, `npm audit`, Semgrep, Trivy imaj taraması, SBOM.
- Ödeme: kart verisi bize hiç gelmez (ödeme kuruluşu barındırmalı form/tokenizasyon), PCI DSS kapsamı SAQ-A seviyesinde kalır.
- Yedek: günlük şifreli `pg_dump` (restic) + haftalık geri yükleme testi; RPO 24 saat, RTO 4 saat (MVP).
- Standart eşlemesi: ISO/IEC 27001 Ek A politika seti, NIST CSF 2.0 (Govern/Identify/Protect/Detect/Respond/Recover), CIS Controls IG1. Sertifika değil, uyumlu politika ve kanıt klasörü.

## 7. Gözlemlenebilirlik

- Sentry (hata + performans), yapılandırılmış JSON log (kişisel veri maskeli), uptime izleme, senkron sağlık paneli (satıcı başına son başarılı senkron, hata oranı).
- Ürün analitiği: PostHog (çerez onayı ile), event sözlüğü pazarlama planında.

## 8. Ortamlar ve teslim

- `dev` (yerel Docker Compose), `staging` (Trendyol stage API, test verisi), `prod`.
- CI (GitHub Actions): lint (ruff, eslint), tip (mypy, tsc), test (pytest, vitest, Playwright e2e), güvenlik (Semgrep, gitleaks, pip-audit, npm audit, Trivy), kapsam eşiği: kâr motoru %100 satır, genel %80.
- CD: `main` → staging otomatik; prod manuel onay (Hasan) + geri dönüş komutu.

## 9. Ölçek planı (global)

| Aşama | Tetik | Değişiklik |
|---|---|---|
| 0-300 satıcı | MVP | Tek VM, tek DB |
| 300-2.000 | CPU > %60 veya senkron gecikmesi > 30 dk | Worker'ları ayrı VM'e, yönetilen PostgreSQL, okuma replikası |
| 2.000+ / global | Yeni pazar | Pazaryeri adaptörleri (Amazon SP-API, Shopify, Etsy), bölgesel veri yerleşimi (AB/ABD), çok para birimi, EN arayüz |

## 10. Açık kararlar (Trello karar kartında)

- **K-N01:** Kalıcı ürün adı ve alan adı (marka araştırması sonrası).
- **K-N02:** Barındırma yeri: Türkiye VPS vs AB (Hetzner) + KVKK standart sözleşme.
- **K-N03:** Şirket türü (şahıs vs limited) ve fatura kesme altyapısı.
- **K-N04:** Ödeme kuruluşu (iyzico / PayTR / Param).
- **K-N05:** Fiyatlandırma (rakip araştırmasına göre).
