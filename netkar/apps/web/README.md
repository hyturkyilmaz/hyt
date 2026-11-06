# NetKâr web (Next.js 15)

Pazarlama sayfası, kimlik doğrulama ekranları ve panel kabuğu. Tasarım sistemi: `../../docs/60_tasarim_sistemi.md`. Ürün adı: `src/config/brand.ts` (`NEXT_PUBLIC_PRODUCT_NAME` ile ezilir).

## Kurulum

Node 22, npm.

```
cp .env.example .env.local
npm ci
npm run dev        # http://localhost:3000
```

Ortam değişkenleri `src/config/env.ts` içinde Zod ile doğrulanır: `API_BASE_URL` (sunucu), `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_PRODUCT_NAME`.

## Betikler

| Komut                             | Ne yapar                                                                                                                           |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `npm run dev` / `build` / `start` | Next.js                                                                                                                            |
| `npm run lint`                    | ESLint (next, jsx-a11y, security), uyarı da hata sayılır                                                                           |
| `npm run typecheck`               | `tsc --noEmit` (strict)                                                                                                            |
| `npm test`                        | vitest + Testing Library                                                                                                           |
| `npm run e2e`                     | Playwright: üretim derlemesini başlatır, 390x844 ve 1280x800, axe-core, ekran görüntüleri `../../docs/ux/ekranlar/` altına yazılır |

Playwright bu makinede `/opt/pw-browsers/chromium` kullanır (`PW_CHROMIUM_PATH` ile değişir); `playwright install` gerekmez.

## Yapı

```
src/app/(marketing)   ana sayfa
src/app/(auth)        giris, kayit, iki-adim, sifre-sifirla
src/app/(app)/panel   Özet, Ürünler, Siparişler, Uyarılar, Ayarlar (boş durum + iskelet)
src/components/ui     shadcn/ui tabanlı bileşenler
src/lib/api           fetch sarmalayıcı (CSRF), uç nokta tanımları
src/lib/format.ts     formatTRY, formatPercent
src/middleware.ts     nonce tabanlı CSP
```

## API sözleşmesi

Tarayıcı `/api/v1/...` çağırır; `next.config.ts` rewrites bunu `API_BASE_URL`'e yönlendirir (aynı köken, çerezler aynı yerde). Yazan istekler `csrf_token` çerezini `X-CSRF-Token` başlığına koyar. `src/lib/api/endpoints.ts` içindeki yollar (`/auth/login`, `/auth/register`, `/auth/2fa/verify`, `/auth/password-reset/request|confirm`) ve `two_factor_required` alanı **API ile henüz doğrulanmadı**; değişirse yalnız o dosya güncellenir.

## Bilinen sınırlar

- Panelde oturum koruması yok (API hazır olunca middleware veya sunucu bileşeninde eklenecek).
- Kayıt formundaki `/kullanim-kosullari` ve `/kvkk-aydinlatma-metni` sayfaları henüz yok.
- Servis çalışanı bilinçli olarak yok (bkz. tasarım dokümanı, bölüm 7).
- Open Graph görseli yok.
