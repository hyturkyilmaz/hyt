# ADR-0002: İstemci IP'si ve vekil güveni

- Durum: Kabul edildi (S1, güvenlik denetimi düzeltmesi)
- Tarih: 6 Kasım 2026
- İlgili: `docs/security/denetim_2026-11-06_S1.md` Y-01, `docs/10_mimari.md` §2, `docs/50_guvenlik.md` G07, ADR-0001 §4

## 1. Bağlam

Rate limit (giriş, kayıt, parola sıfırlama, TOTP) IP başına kova kullanır; denetim izi ve oturum kaydı da IP'nin anahtarlı özetini saklar. Hepsi tek bir soruya bağlıdır: isteği gerçekte kim gönderdi?

Mimari: tarayıcı, Next.js (BFF; `next.config.ts` rewrites ile `/api/v1/*` isteklerini API'ye vekiller), API. Canlıda önlerinde Cloudflare ve Traefik (Coolify) olması beklenir. Denetim (Y-01) iki kusur gösterdi:

1. Next.js rewrites vekili (`http-proxy`, `xfwd` kapalı) kendi X-Forwarded-For (XFF) girdisini eklemez, istemcinin yazdığı XFF ve X-Real-IP başlıklarını API'ye olduğu gibi geçirir. Deneysel doğrulama: istemci `X-Forwarded-For: 6.6.6.6` gönderince API `6.6.6.6` gördü.
2. Eski `client_ip` iki seçenek sunuyordu: `TRUST_PROXY_HEADERS=false` (API'nin gördüğü eş adres herkes için web konteyneri, yani platform genelinde tek kova: bir anonim saldırgan herkesin girişini 429'a düşürür) veya `true` (XFF'nin en sağdaki değeri; vekil eklemiyorsa istemci seçer, sınır sıfırlanır).

Ek tuzak: uvicorn varsayılan olarak `--proxy-headers` açıktır ve `127.0.0.1` eşinden gelen XFF'ye kendisi güvenir (`request.client` değişir). Web ve API aynı makinede çalışırsa uygulamanın kuralı devre dışı kalır.

## 2. Karar

Güven zinciri iki katmanlıdır ve her katman tek bir sorumluluk taşır.

### 2.1 API: güvenilir vekil yapılandırması (`app/core/clientip.py`)

- İki ayar (ortam değişkeni): `TRUSTED_PROXY_CIDRS` (virgülle ayrılmış CIDR listesi, örn. web konteyner ağı) ve `TRUSTED_PROXY_HOPS` (sağdan sayılan güvenilir vekil sayısı, bağlantının eş adresi dahil). İkisi de boşsa hiçbir vekile güvenilmez: XFF yok sayılır, bağlantının eş adresi kullanılır (güvenli varsayılan).
- Algoritma: zincir = XFF girdileri (soldan sağa) + eş adres. Eş adres CIDR listesinde değilse (liste verilmişse) başlık okunmaz. Aksi halde sağdan sola yürünür: önce `TRUSTED_PROXY_HOPS` kadar girdi atlanır, sonra CIDR listesindeki adresler atlanır; ilk güvenilmeyen adres istemcidir. Sol taraftaki değerleri istemci yazabildiği için esas alınmaz. Geçersiz bir girdi (IP olmayan metin) görülürse onun solundakilere güvenilmez.
- IPv6 istemciler `/64` önekine indirgenir (bir ev/ofis bağlantısına `/64` verilir; adres başına kova saldırgana sınırsız kova verirdi). `::ffff:a.b.c.d` IPv4'e çevrilir. Port ve köşeli parantez ayıklanır.
- uvicorn `--no-proxy-headers` ile başlatılır (Dockerfile, `make dev`, e2e başlatıcısı): IP kararı yalnız uygulamada verilir.
- `TRUST_PROXY_HEADERS` kaldırıldı. Eski ortamda tanımlı kalırsa yok sayılır (güvenli yön: başlığa güvenilmez).
- Aynı çözümleyici rate limit, `sessions.ip_hash` ve `audit_log.ip_hash` için kullanılır.

### 2.2 Web: istemci başlıklarını temizleme ve tek kaynaktan iletme (`src/middleware.ts`, `src/lib/client-ip.ts`)

Middleware `/api/*` isteklerinde (eşleyici koşulsuzdur: istemci `purpose: prefetch` yazarak atlatamaz) şunu yapar:

1. İstemciden gelen `X-Forwarded-For`, `X-Real-IP`, `CF-Connecting-IP`, `True-Client-IP`, `X-Client-IP`, `X-Cluster-Client-IP`, `Fastly-Client-IP`, `Forwarded` başlıklarını siler.
2. `CLIENT_IP_SOURCE` ile seçilen TEK kaynaktan istemci IP'sini çıkarır, doğrular (yalın IPv4/IPv6; port, ad, ek içerik reddedilir).
3. Doğrulanan değeri tek bir `X-Forwarded-For` değeri olarak yazar. Belirlenemezse hiçbir IP başlığı iletilmez.

Seçenekler (dağıtım değişkeni, yalnız biri):

| `CLIENT_IP_SOURCE` | Ne zaman | Güven koşulu |
|---|---|---|
| `none` (varsayılan) | Yerel geliştirme, vekilsiz | Hiçbir başlığa güvenilmez; API vekilin (web) adresini görür, tek kova. Güvenli ama hassas değil. |
| `cf-connecting-ip` | Cloudflare arkasında (öngörülen canlı topoloji) | Köken (Traefik/Coolify) yalnız Cloudflare IP aralıklarına açık olmalı; aksi halde başlığı herkes yazabilir. |
| `x-forwarded-for` | XFF ekleyen bir vekil (örn. yalnız Traefik) arkasında | Sağdan `CLIENT_IP_TRUSTED_HOPS` (varsayılan 1) girdi alınır. Vekil gelen XFF'yi güvenilmeyen kaynaklardan atmalı/üzerine yazmalı (Traefik `forwardedHeaders.trustedIPs`). |

Geçersiz `CLIENT_IP_SOURCE`/`CLIENT_IP_TRUSTED_HOPS` middleware'de istisna fırlatır (500): sahte başlığa güvenmektense kapalı başarısız olunur.

### 2.3 Güven zinciri (canlı topoloji)

```
istemci -> Cloudflare -> Traefik -> Next.js (middleware) -> API
           CF-Connecting-IP        tek XFF = doğrulanmış IP    TRUSTED_PROXY_CIDRS = web ağı
```

- API yalnız web konteyner ağından erişilebilir olmalı (compose ağı; portlar yalnız `127.0.0.1`). `TRUSTED_PROXY_CIDRS` bu ağı gösterir. Web dışından API'ye doğrudan bağlanabilen biri eş adresi güvenilir değilse kendi adresiyle sınırlanır; güvenilir ağdaysa XFF'yi yazabilir, bu yüzden ağ yalıtımı zorunludur.
- Köken IP'si yalnız Cloudflare aralıklarına açılmalı (Coolify/Traefik IP izin listesi). Bu bir dağıtım yapılandırmasıdır, kodla zorlanamaz.

### 2.4 Rate limit sırası

IP sınırları, FastAPI gövdeyi ayrıştırmadan ÖNCE çalışsın diye saf ASGI ara katmanına taşındı (`IpRateLimitMiddleware`); sıra: güvenlik başlıkları, istek bağlamı, gövde boyut sınırı (`BodyLimitMiddleware`, denetim O-04), IP sınırı, CSRF, uygulama. 429 alacak istek gövdesi okunmaz. E-posta ve kullanıcı bazlı sayaçlar gövdedeki alanlara bağlı olduğundan işleyicide kalır. Anahtar adları ve eşikler değişmedi.

## 3. Reddedilen alternatifler

- **Yalnız uvicorn `--forwarded-allow-ips`:** CIDR/hop modeli yok, `request.client` değişir (kayıt/log tutarsızlığı), 127.0.0.1 varsayılanı tuzağı sürer. Karar tek yerde (uygulama) verilsin diye reddedildi.
- **`TRUST_PROXY_HEADERS` boolean'ını korumak:** "en sağdaki değer" varsayımı Next.js rewrites ile yanlıştı; hop/CIDR olmadan doğru yapılandırılamaz.
- **Middleware'de socket adresini okumak:** Next.js 15'te `NextRequest.ip` yok; middleware'e eş adres verilmez. Next'in `x-forwarded-for ??= socket` ataması yalnız başlık yokken çalışır ve rewrites yolunda hiç çalışmaz; istemcinin yazdığından ayırt edilemez. Bu yüzden "socket" kaynağı sunulmadı.
- **Rewrites yerine Route Handler ile BFF vekili:** Daha fazla kod (çerez, akış, hata aktarımı), kapsam büyür; middleware başlık geçersiz kılması aynı sonucu daha küçük yüzeyle verir. Gerekirse sonraki adım.
- **Başlığa yalnız CIDR listesiyle güvenmek (hop yok):** Tek vekilli kurulumlarda (Next arkasında) CIDR yazmak yerine "1 hop" yeterli; ikisi birlikte de kullanılabilir.

## 4. Sonuçlar ve açık riskler

- Yanlış yapılandırma (örn. `none` ile canlıya çıkmak) güvenli ama keskin değildir: tüm kullanıcılar vekilin kovasını paylaşır ve tek saldırgan 429 ile herkesi engelleyebilir. Canlı kontrol listesi: `CLIENT_IP_SOURCE=cf-connecting-ip`, köken Cloudflare'e kilitli, `TRUSTED_PROXY_CIDRS` web ağı.
- `TRUSTED_PROXY_HOPS` gerçek vekil sayısından büyük girilirse zincirin sol (istemci yazılı) tarafına sızar; küçük girilirse vekil adresi kova olur. Dağıtım değişikliğinde yeniden doğrulanmalı.
- Köken Cloudflare dışına açık kalırsa `cf-connecting-ip` sahte olabilir (denetimin "köken kilidi" önerisi hâlâ geçerli).
- IP sınırı tek başına yeterli değildir (başarılı istekler de sayılır, bkz. denetim D-03). Turnstile S2'dedir.
- Next.js vekili ve Traefik/Cloudflare için gövde boyut sınırı bu işte yapılmadı; API sınırı (auth 64 KiB, genel 1 MiB) son savunmadır. Dış katmanlara da konmalı.

## 5. Doğrulama

- API birim: `tests/test_client_ip.py` (zincir senaryoları, sahte sol değerler, güvenilmeyen eş, çoklu vekil, IPv6, geçersiz girdi).
- API entegrasyon: `tests/test_denetim_s1_regression.py::test_y01_*` (sahte XFF ile limit aşılamaz, farklı gerçek istemciler birbirinin limitini tüketmez, IPv6 /64, denetim izi IP özeti).
- Web birim: `src/lib/client-ip.test.ts`, `src/middleware.test.ts` (başlık temizleme, kaynak seçimi, eşleyici).
- Uçtan uca (gerçek PostgreSQL + API + Next.js): `e2e/real-api/rate-limit.spec.ts`. Web `CLIENT_IP_SOURCE=cf-connecting-ip` ile çalışır; istemci Cloudflare rolünde. Middleware'in `/api` dalı devre dışı bırakıldığında üç senaryo da kırıldı, açıkken geçti (kanıt, bu işte elle denendi).
