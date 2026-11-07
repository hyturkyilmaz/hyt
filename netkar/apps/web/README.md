# NetKâr web (Next.js 15)

Pazarlama sayfası, kimlik doğrulama ekranları ve panel kabuğu. Tasarım sistemi: `../../docs/60_tasarim_sistemi.md`. Ürün adı: `src/config/brand.ts` (`NEXT_PUBLIC_PRODUCT_NAME` ile ezilir).

## Kurulum

Node 22, npm.

```
cp .env.example .env.local
npm ci
npm run dev        # http://localhost:3000
```

Ortam değişkenleri `src/config/env.ts` içinde Zod ile doğrulanır: `API_BASE_URL` (sunucu), `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_PRODUCT_NAME`, `CLIENT_IP_SOURCE` (`none` | `cf-connecting-ip` | `x-forwarded-for`, varsayılan `none`), `CLIENT_IP_TRUSTED_HOPS` (yalnız `x-forwarded-for` için, varsayılan 1). İstemci IP kaynağı seçimi ve güven koşulları: `../../docs/adr/0002-istemci-ip-ve-vekil-guveni.md`.

## Betikler

| Komut                             | Ne yapar                                                                                                                                           |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run dev` / `build` / `start` | Next.js                                                                                                                                            |
| `npm run lint`                    | ESLint (next, jsx-a11y, security), uyarı da hata sayılır                                                                                           |
| `npm run typecheck`               | `tsc --noEmit` (strict)                                                                                                                            |
| `npm test`                        | vitest + Testing Library                                                                                                                           |
| `npm run e2e`                     | Playwright (sahte API ile): üretim derlemesini başlatır, 390x844 ve 1280x800, axe-core, ekran görüntüleri `../../docs/ux/ekranlar/` altına yazılır |
| `npm run e2e:gercek-api`          | Playwright, **gerçek API** ile: geçici PostgreSQL + `services/api` + web; kayıt, giriş, panel, çıkış, TOTP ikinci adım (aşağıya bakın)             |

Playwright bu makinede `/opt/pw-browsers/chromium` kullanır (`PW_CHROMIUM_PATH` ile değişir); `playwright install` gerekmez.

## Yapı

```
src/app/(marketing)   ana sayfa, /ozellikler, /fiyatlar, /guvenlik-ve-kvkk, /sss, /araclar (+ 3 hesaplayıcı)
src/app/(auth)        giris, kayit, iki-adim, sifre-sifirla
src/app/(app)/panel   Özet, Ürünler, Siparişler, Uyarılar, Ayarlar (boş durum + iskelet); oturum korumalı
src/app/(marketing)   ayrıca /kullanim-kosullari ve /kvkk-aydinlatma-metni (taslak iskelet, hukuki inceleme bekliyor)
src/components/ui     shadcn/ui tabanlı bileşenler
src/lib/api           fetch sarmalayıcı (CSRF), uç nokta tanımları, server.ts (GET /v1/me ile oturum doğrulama)
src/lib/auth          çerez adları, güvenli yönlendirme (safeNextPath)
src/lib/format.ts     formatTRY, formatPercent
src/middleware.ts     nonce tabanlı CSP + /panel için oturum çerezi kapısı + /api için istemci IP başlıklarının temizlenmesi
src/lib/client-ip.ts  IP kaynağı seçimi, doğrulama, başlık temizleme (ADR-0002)
```

## API sözleşmesi

Kaynak: `services/api/app/api/v1/{auth,me,schemas}.py` ve `app/core/{cookies,middleware,errors}.py`. Tarayıcı aynı kökende `/api/v1/...` çağırır; `next.config.ts` rewrites bunu backend'in `API_BASE_URL/v1/...` yoluna iletir (backend'de `/api` öneki yoktur; adres derleme sırasında rewrites içine gömülür). Yollar ve alanlar yalnız `src/lib/api/endpoints.ts` içindedir.

| Akış        | Yol                                                | Gövde (backend şeması)              | Yanıt                                                                                 |
| ----------- | -------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------- |
| CSRF        | `GET /v1/auth/csrf`                                |                                     | `{csrf_token}` + `__Host-nk_csrf` çerezi                                              |
| Kayıt       | `POST /v1/auth/register`                           | `{email, password, tenant_name}`    | 202 `{status:"accepted"}`; oturum AÇMAZ, kullanıcı giriş yapar                        |
| Giriş       | `POST /v1/auth/login`                              | `{email, password}`                 | `{status:"ok"}` (oturum çerezi) veya `{status:"totp_required"}` (`__Host-nk_pending`) |
| İkinci adım | `POST /v1/auth/totp/verify`                        | `{code}` (6 hane)                   | `{status:"ok"}`                                                                       |
| Çıkış       | `POST /v1/auth/logout`                             |                                     | 204 (idempotent)                                                                      |
| Oturum      | `GET /v1/me`                                       |                                     | `MeResponse` (`user_id, email, role, totp_enabled, tenant{...}`)                      |
| Sıfırlama   | `POST /v1/auth/password-reset/request` / `confirm` | `{email}` / `{token, new_password}` | 202 / 204                                                                             |

- **CSRF:** durum değiştiren istekte `X-CSRF-Token` başlığı, `__Host-nk_csrf` çerezindeki değerle aynı olmalıdır. `apiFetch` çerezi okur; okunamıyorsa önce `GET /v1/auth/csrf` çağırır. Oturum çerezi `__Host-nk_session` HttpOnly'dir. `__Host-` öneki Secure ister: tarayıcılar bunu yalnız https'te ve `localhost`/`127.0.0.1` üzerinde kabul eder (LAN IP'si ile http'de çerez kurulmaz).
- **Hatalar:** `application/problem+json`; makine kodu `type` alanındaki `urn:netkar:problem:<slug>` sonekidir (`invalid-credentials`, `weak-password`, `invalid-code`, `invalid-reset-token`, `rate-limited`, `validation-error` ...). 422'de `errors: [{field, code}]` gelir. Arayüz sunucu `detail` metnini göstermez.
- **Backend e-postaları** `WEB_BASE_URL` + `/login`, `/forgot-password`, `/reset-password?token=` bağlantıları üretir; web bunları `/giris` ve `/sifre-sifirla` adreslerine yönlendirir (`next.config.ts` redirects).

## İstemci IP'si (rate limit)

`/api/v1/*` istekleri rewrites ile API'ye vekillenir ve Next.js istemcinin yazdığı `X-Forwarded-For`/`X-Real-IP` başlıklarını olduğu gibi geçirir. Bu yüzden `src/middleware.ts` `/api/*` isteklerinde (eşleyici prefetch başlığıyla atlatılamaz) tüm IP başlıklarını siler ve `CLIENT_IP_SOURCE` ile seçilen tek kaynaktan doğrulanan IP'yi tek bir `X-Forwarded-For` olarak yazar. Canlı (Cloudflare arkasında): `CLIENT_IP_SOURCE=cf-connecting-ip`, köken yalnız Cloudflare aralıklarına açık, API'de `TRUSTED_PROXY_CIDRS` = web ağı. Varsayılan `none`: API'ye IP iletilmez (tek kova, güvenli).

## Oturum koruması

1. `src/middleware.ts`: `/panel` ve altında `__Host-nk_session` çerezi yoksa `/giris?sonra=<yol>` adresine yönlendirir (kaba kapı).
2. `src/app/(app)/layout.tsx`: `getSession()` (`src/lib/api/server.ts`) yalnız oturum çerezini API'ye `GET /v1/me` ile iletir; 401 ise girişe yönlendirir (asıl kapı). API'ye ulaşılamazsa oturum düşürülmez, "tekrar dene" ekranı gösterilir.
3. `?sonra=` değeri `safeNextPath` ile doğrulanır: yalnız `/` ile başlayan, `//`, `\`, denetim karakteri veya dış adres içermeyen, giriş sayfaları dışındaki uygulama içi yollar kabul edilir; aksi halde `/panel`.
4. Çıkış: kenar çubuğu (masaüstü) ve üst çubuk (mobil) `LogoutButton` bileşeni `POST /v1/auth/logout` çağırır.

## Gerçek API ile uçtan uca test

`npm run e2e:gercek-api`: `e2e/real-api/serve_api.py` geçici bir PostgreSQL 16 kümesi kurar (`services/api/tests/conftest.py` mantığı: initdb, yalnız unix socket, tmp dizin), roller ve migrasyonlar çalışır, `services/api` uvicorn ile `127.0.0.1:8100` üzerinde başlar; web `127.0.0.1:3101` üzerinde ona bağlanır. Gereksinim: `uv` (`services/api` ortamı kurulu), `/usr/lib/postgresql/16/bin` (`PG_BIN`), Chromium. Süreç bitince küme ve tmp dizin silinir. Senaryo: kayıt, yanlış parola, giriş, panel, çerez bayrakları, çıkış, `sonra` yönlendirmesi (dış adres reddi), TOTP etkinleştirme (arayüzde kurulum ekranı henüz yok, API sayfa bağlamından çağrılır), ikinci adımla giriş ve aynı kodun yeniden kullanımının reddi. `rate-limit.spec.ts` (web `CLIENT_IP_SOURCE=cf-connecting-ip`, API `TRUSTED_PROXY_CIDRS=127.0.0.0/8`): sahte `X-Forwarded-For`/`X-Real-IP` ile IP sınırı aşılamaz, farklı gerçek istemciler birbirinin sınırını tüketmez. Varsayılan `npm run e2e` sahte API (`e2e/fake-api.mjs`, yalnız `/v1/me` ve `/v1/auth/csrf`) kullanır.

## Pazarlama sitesi (S5)

- **Hesaplayıcılar** (`src/lib/calc`, tamsayı BigInt kuruş, float yok; kurallar docs/12 K01, K02, K06, K07, K10, K18, K20, K25): `/araclar/trendyol-komisyon-hesaplama`, `/araclar/trendyol-kar-hesaplama`, `/araclar/desi-hesaplama`. İstemcide çalışır, sunucuya veri gitmez. Komisyon KDV'si (K07) varsayımı arayüzde işaretli ve seçilebilir. Birim testleri golden tahminleriyle karşılaştırır (G01, G03, G09, G10, G12, G24, G31, G32).
- **Bekleme listesi:** `POST /api/bekleme-listesi` -> `WaitlistSink` (`src/lib/waitlist/sink.ts`: bellek veya dosya; üretimde hedef yoksa 503). Origin denetimi, bot tuzağı, hız sınırı, ayrı ve işaretsiz ticari ileti onayı. Turnstile yeri hazır, kapalı. E-posta gönderilmez. İstemci paketine zod girmemesi için seçenekler `options.ts` içindedir.
- **SEO:** sayfa bilgisi `src/lib/seo/pages.ts` (başlık, açıklama, site haritası), JSON-LD `src/lib/seo/jsonld.ts` (FAQPage yalnız /sss).
- **CWV:** `e2e/cwv.spec.ts` Playwright ile LCP, CLS, etkileşim gecikmesi ve JS boyutunu ölçer (Lighthouse CI yok, bağımlılık eklenmedi).

## Bilinen sınırlar

- `/kullanim-kosullari` ve `/kvkk-aydinlatma-metni` yalnız taslak bölüm iskeletidir (noindex); metinler hukuki incelemeden sonra yazılacak.
- Kullanım koşulları onayı yalnız arayüzde zorunludur; API onay sürümünü/tarihini kaydetmiyor.
- TOTP kurulum ekranı yok (API hazır: `/v1/auth/totp/setup`, `/enable`).
- Panel verisi hâlâ boş durum iskeleti; yalnız `GET /v1/me` kullanılıyor.
- Servis çalışanı bilinçli olarak yok (bkz. tasarım dokümanı, bölüm 7).
- Open Graph görseli yok.
