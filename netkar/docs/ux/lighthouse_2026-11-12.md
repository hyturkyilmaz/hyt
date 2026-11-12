# Lighthouse mobil ölçümü: açılış ve panel ekranları

Tarih: 2026-11-12
Kapsam: `/` (açılış) ve `/panel`, `/panel/urunler`, `/panel/siparisler`, `/panel/uyarilar`, `/panel/ayarlar`
Kaynak: `netkar/apps/web` (Next.js 15), derleme ve ölçüm kaynak kodu değiştirilmeden yapıldı.

## Ölçüm koşulları ve sınırlar

- **Yerel üretim derlemesi ve sahte API.** `npm run build` çıktısı `next start` ile çalıştırıldı, API yerine `e2e/fake-api.mjs` kullanıldı. Gerçek backend ve gerçek ağ koşulları ölçülmedi.
- **Simüle edilmiş kısıtlama.** Lighthouse varsayılan `simulate` yöntemini kullandı: 4x CPU yavaşlatma, 150 ms RTT, yaklaşık 1,6 Mbps indirme. Skorlar gerçek cihaz ve ağ ölçümü değil, Lighthouse'un tahminidir.
- **Panel verisi.** Sahte API `GET /v1/marketplace-accounts` için boş dizi döner (bağlı mağaza yok). Panel sayfaları bu varsayılan yanıtla, yani boş durum ile ölçüldü. Ürün, sipariş ve uyarı verisi dolu iken ölçülmedi.
- **Oturum.** Panel sayfaları için `Cookie: __Host-nk_session=e2e-oturum` başlığı (`e2e/helpers.ts` içindeki `signIn` değeri) gönderildi. Her sayfanın h1'i ölçümle uyumlu: Özet, Ürünler, Siparişler, Uyarılar, Ayarlar.
- **Araç.** Lighthouse 12.8.2, Chrome for Testing 153 (`/opt/pw-browsers/chromium-1243/chrome-linux64/chrome`), `--headless=new --no-sandbox`, `--form-factor=mobile`, kategoriler: performance, accessibility, best-practices, seo.
- **Tekrar.** Her sayfa 3 kez ölçüldü. Tabloda medyan değer verildi.
- JSON çıktıları repoya yazılmadı: `/tmp/claude-0/-home-user-hyt/9e0dcdb7-1ce4-5047-97d3-278f704913e7/scratchpad/lighthouse/`

## Sonuçlar (mobil, medyan)

| Sayfa | Performans | Erişilebilirlik | En iyi uygulamalar | SEO | LCP | TBT | CLS | FCP |
|---|---|---|---|---|---|---|---|---|
| `/` (açılış) | 95 | 100 | 100 | 91 | 2,7 s | 140 ms | 0 | 0,9 s |
| `/panel` | 92 | 100 | 100 | 63 | 3,2 s | 120 ms | 0 | 0,8 s |
| `/panel/urunler` | 93 | 100 | 100 | 63 | 3,2 s | 90 ms | 0 | 0,8 s |
| `/panel/siparisler` | 92 | 100 | 100 | 63 | 3,3 s | 90 ms | 0 | 0,8 s |
| `/panel/uyarilar` | 96 | 100 | 100 | 63 | 2,7 s | 50 ms | 0 | 0,8 s |
| `/panel/ayarlar` | **89** | 100 | 96 | 63 | 3,6 s | 100 ms | 0 | 0,8 s |

Tekrar değerleri (performans): `/` 95, 95, 95 · `/panel` 92, 91, 92 · `/panel/urunler` 93, 93, 92 · `/panel/siparisler` 92, 90, 92 · `/panel/uyarilar` 94, 96, 99 · `/panel/ayarlar` 89, 89, 90.

## Bitti kriteri değerlendirmesi (performans ve erişilebilirlik en az 90)

- Erişilebilirlik: 6 sayfanın 6'sı 100.
- Performans: 6 sayfanın 5'i 90 üstünde (92 ile 96 arası). **`/panel/ayarlar` medyan 89 ile kriteri karşılamıyor.** Üç ölçümün ikisi 89, üçüncüsü 90. Sınır değerde olduğu için kriter bu sayfada kesin olarak karşılanmış sayılmaz.

## 90 altı kalanlar: ilk 3 öneri

### `/panel/ayarlar`, performans 89

1. `largest-contentful-paint` (puan 0,6, LCP 3,6 s). LCP öğesi `section#kargo` içindeki bir metin paragrafı. Lighthouse LCP dökümü yalnızca TTFB (30 ms) ve öğe render gecikmesi (283 ms) gösteriyor. Toplam 3,6 s'nin büyük kısmı bu dökümde açıklanmıyor. Ölçülen LCP sayfanın diğer panel sayfalarından (3,2 s ve 3,3 s) da yüksek. Kök neden bu raporla belirlenemedi.
2. `total-blocking-time` (puan 0,98, 100 ms). Küçük bir kayıp, öncelik düşük.
3. `unused-javascript` (tahmini kazanç 36 KiB). En büyük sorun `992-2c32cfb5e0e19292.js` dosyası: yaklaşık 42 KB, bunun %88'i kullanılmıyor. Ayarlar sayfası diğer panel sayfalarından daha büyük bir istemci paketi yüklüyor (ilk yükleme JS 44 kB, diğer panel sayfaları 3 ile 5 kB).

Ek bilgi: `legacy-javascript` denetimi 0,5 puan aldı (tahmini kazanç 11 KiB). Ayrıca `bf-cache` denetimi başarısız (sayfa `Cache-Control: no-store` ile geliyor). Bu denetim performans puanına dahil değil.

### Panel sayfaları, SEO 63 (tüm `/panel/*` sayfaları)

1. `is-crawlable` (puan 0). Sayfada `<meta name="robots" content="noindex, nofollow" />` var. Bu, `src/app/(app)/layout.tsx` içindeki kasıtlı bir ayardır: kimlik doğrulamalı alan arama motorlarına açılmamalı. Beklenen bir sonuçtur, hata değildir.
2. Bu sayfalarda ağırlıklı başka başarısız SEO denetimi yok.

SEO puanı bu ekranlar için bir kalite ölçütü değil. Bitti kriteri SEO'yu kapsamıyor.

### `/` (açılış)

Performans, erişilebilirlik ve en iyi uygulamalar 90 üstünde. SEO 91 olup eşik üstünde. Yine de öneri listesi: LCP (puan 0,88, 2,7 s) ve TBT (puan 0,93, 140 ms).

## Özet

- Açılış sayfası ve dört panel sayfası performans ve erişilebilirlikte 90 üstünde.
- `/panel/ayarlar` performansta 89 (medyan). Tek başarısız ölçüt bu sayfa. Düzeltmek için önce LCP öğesinin neden geç çizildiğini incelemek gerekiyor.
- Ölçümler simüle edilmiş mobil kısıtlama ile yerel üretim derlemesinde ve sahte API ile yapıldı. Gerçek ağ ve gerçek veriyle sonuçlar farklılaşabilir.
