# NetKâr · Tasarım Sistemi (v0.1)

Kaynak dosyalar: `apps/web/src/styles/tokens.css` (tokenlar), `apps/web/tailwind.config.ts` (tokenları Tailwind'e bağlar), `apps/web/src/components/ui/` (shadcn/ui tabanlı bileşenler). Ürün adı yalnız `apps/web/src/config/brand.ts` içinde okunur (`NEXT_PUBLIC_PRODUCT_NAME` ile ezilebilir). Ekran görüntüleri: `docs/ux/ekranlar/`.

## 1. İlkeler
1. **5 saniye kuralı.** Telefondan bakan satıcı "bugün ne kazandım, hangi ürün zarar ettiriyor" sorusunun cevabını ilk ekranda görür. Önce sonuç, sonra ayrıntı.
2. **Güven veren, sade, soğuk değil.** Sıcak kâğıt tonlu zemin, koyu mürekkep metin, tek bir marka rengi (ultramarin). Gradient, parıltı, blob, dekoratif illüstrasyon yok. Gölgeler düz ve hafif.
3. **Mobil öncelikli.** Tasarım 390px genişlikten başlar. Başparmakla ulaşılan alt gezinme, tek sütun, büyük dokunma hedefleri.
4. **Renge tek başına güvenme.** Kâr/zarar her zaman renk + ikon + metin ile verilir.
5. **Dürüst metin.** Jargon yok, abartı ve garanti yok. "Siz" dili (research/06 kararı). Tahmin ile kesin rakam ayrı etiketlenir. Örnek veri "Örnek veri" rozetiyle işaretlenir.
6. **Her ekranda dört durum:** yükleniyor (iskelet), boş (ne olduğu + sonraki adım), hata (ayrıntı sızdırmadan, tekrar dene), başarı.

## 2. Tokenlar
Renkler hex olarak tutulur ve `src/styles/tokens.test.ts` her çifti WCAG 2.2 AA'ya karşı otomatik doğrular (açık ve koyu tema).

| Token | Açık | Koyu | Kullanım |
|---|---|---|---|
| `--background` | #faf8f4 | #12120f | Sayfa zemini |
| `--surface` | #ffffff | #1b1a17 | Kart, form, gezinme |
| `--surface-muted` | #f2eee7 | #25241f | İskelet, hover, ikincil alan |
| `--foreground` | #1b1a17 | #f2efe8 | Ana metin |
| `--muted-foreground` | #5c5850 | #b0aa9d | İkincil metin (4.5:1 sağlar) |
| `--border` | #ddd7cb | #3a382f | Süs çizgisi (kart kenarı) |
| `--input-border` | #857e70 | #8a8474 | Girdi kenarlığı (3:1, WCAG 1.4.11) |
| `--primary` | #23409a | #9bb0ff | Marka, birincil eylem, bağlantı |
| `--ring` | #23409a | #9bb0ff | Odak halkası |
| `--profit` / `--profit-soft` | #0a6b36 / #e1f2e6 | #4cc884 / #12301f | Kâr |
| `--loss` / `--loss-soft` | #b3261e / #fbe6e3 | #ff8f86 / #3a1714 | Zarar, hata |
| `--warning` / `--warning-soft` | #85500a / #fcefd2 | #f2b84b / #35270b | Uyarı, örnek veri |
| `--info` / `--info-soft` | #23409a / #e6eafa | #9bb0ff / #1a2248 | Bilgi, seçili menü |

Tema: varsayılan sistem tercihi; `<html data-theme="light|dark">` ile zorlanır.

- **Tipografi:** Inter (değişken ağırlık), `next/font/local` ile yerelden; harici CDN yok. Türkçe karakterler için latin ve latin-ext alt kümeleri. Ölçek: xs 12, sm 14, base 16, lg 18, xl 20, 2xl 24, 3xl 30, 4xl 36, 5xl 48 px. Girdilerde en az 16px (iOS yakınlaştırması olmasın). Rakamlar için `.num` (tabular-nums).
- **Boşluk:** 4px adım (`--space-1..16`), sayfa yan boşluğu `--gutter` 16px.
- **Yarıçap:** sm 6, md 10, lg 14, full.
- **Gölge:** `--shadow-sm`, `--shadow-md`; renkli parıltı yok.
- **Boyut:** `--touch-target` 44px, `--bottom-nav-height` 68px, `--sidebar-width` 256px, `--content-max` 72rem.

## 3. Bileşen kuralları
- **Button:** en az 44px yükseklik. Varsayılan `type="button"` (formda kazara gönderim olmaz). Yükleniyorsa dönen ikon + fiil ("Giriş yapılıyor") ve kilitli.
- **Input/Label/Form:** etiket her zaman görünür ve `htmlFor` ile bağlı; placeholder etiket yerine geçmez. Hata mesajı alanın altında, `role="alert"`, "!" simgesi + gizli "Hata:" ön eki; alan `aria-invalid` ve `aria-describedby` alır. Hata kenarlığı kalın (2px) olur, yalnız renk değil.
- **PasswordInput:** göster/gizle düğmesi 44px, `aria-pressed`, değişken `aria-label`.
- **Card:** sayfa başlığı h1, kart başlıkları h2 (`CardTitle as="h1"` ile auth kartında h1).
- **Badge:** renk + her zaman metin.
- **Dialog (Radix):** odak tuzağı, Esc ile kapanma, başlık ve açıklama zorunlu; kapat düğmesi 44px.
- **Sonner (toast):** kısa başarı mesajları için; hata mesajı yalnız toast'a bırakılmaz, satır içi de gösterilir.
- **Skeleton:** `aria-hidden`; kapsayıcı `role="status"` + gizli "Yükleniyor" metni. `prefers-reduced-motion` altında animasyon durur.
- **EmptyState:** başlık (ne yok), açıklama (neden/ne olacak), tek birincil eylem.
- **Gezinme:** Özet, Ürünler, Siparişler, Uyarılar, Ayarlar. Mobil (<1024px) alt çubuk, masaüstü kenar çubuğu. `aria-current="page"`. Kaynak: `components/panel/nav-items.ts`.

## 4. Sayı ve para biçimi (tr-TR)
`apps/web/src/lib/format.ts`, birim testli.
- `formatTRY("1234.5")` → `₺1.234,50`. Girdi string (Decimal) önerilir; float kullanılmaz, kuruşa **sıfırdan uzağa yarım yukarı** yuvarlanır (`1.005` → `₺1,01`). Negatifte `-₺212,40`. Sıfıra yuvarlanan negatif eksi göstermez. `style: 'code'` → `1.234,50 TL` (metin ve sözleşme dili), `signed` → `+` işareti.
- `formatPercent("12.5")` → `%12,5` (yüzde puanı; oran değil). `fractionDigits` ile hane sayısı.
- Geçersiz girdide **hata fırlatır**; sessizce yanlış para yazmaz.
- Para ve yüzdeler her zaman `.num` ile hizalanır. Girdi alanları ileride hem virgül hem nokta ondalığı kabul etmelidir (research/06 §2).
- `ProfitValue`: pozitif = yeşil + yukarı ok + "Kâr:" (ekran okuyucu), negatif = kırmızı + aşağı ok + "Zarar:" + eksi işareti, sıfır = nötr + çizgi.

## 5. Erişilebilirlik kuralları (WCAG 2.2 AA)
- **Kontrast:** metin 4.5:1, metin dışı bileşen ve odak halkası 3:1; açık ve koyu temada otomatik testle korunur. Yeni token eklenince `tokens.test.ts` çiftlere eklenir.
- **Odak halkası:** `:focus-visible` 2px halka + 2px boşluk, her etkileşimli öğede. Sabit alt çubuk odaklı öğeyi örtmesin diye `scroll-padding-bottom` ayarlıdır (WCAG 2.4.11).
- **Dokunma hedefi:** en az 44x44px (kural 24px'tir, biz daha sıkıyız). Satır içi bağlantılar metin akışında istisnadır.
- **Renge tek başına güvenme:** kâr/zarar, hata, uyarı, seçili menü: ikon, metin veya şekil eşlik eder.
- **Klavye:** "İçeriğe geç" bağlantısı, mantıklı sekme sırası, diyalog odak tuzağı.
- **Hareket:** `prefers-reduced-motion` ile animasyonlar kapanır.
- **Otomatik denetim:** Playwright + axe-core (wcag2a, 2aa, 21aa, 22aa) tüm sayfalarda, 390 ve 1280px, açık ve koyu temada 0 ihlal bekler.

## 6. Güvenlik başlıkları
Nonce tabanlı CSP `src/middleware.ts` içinde her istekte üretilir (`script-src 'self' 'nonce-…' 'strict-dynamic'`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`). Bu yüzden sayfalar dinamik (istek anında) üretilir. `style-src` için `'unsafe-inline'` bilinçli bir ödündür: Sonner ve Radix çalışma anında satır içi stil yazar. Betikler nonce ile korunur. HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options` `next.config.ts` içindedir; `poweredByHeader: false`.

## 7. PWA ve servis çalışanı (service worker)
`app/manifest.ts` ve SVG ikonlar (`/icon.svg`, `/maskable-icon.svg`, marka adının baş harfi) vardır. **Bu aşamada servis çalışanı eklenmedi.** Nedenleri:
1. Panel sayfaları ve API yanıtları satıcıya ait finansal veri içerir. Hatalı bir SW önbelleği oturum kapandıktan sonra veya başka bir hesapla girişte eski kullanıcının verisini gösterebilir (KVKK ve kiracı izolasyonu riski, G01).
2. Çevrimdışı kullanım bu fazda bir gereksinim değil; ana ekrana ekleme manifest ile sağlanır.
3. CSP nonce ve dinamik render ile SW önbelleği birlikte tasarlanmalı.

Eklenirse kurallar: yalnız statik varlıklar (`/_next/static`, ikonlar, yazı tipi) önbelleğe alınır; HTML, `/api/*` ve kimlikli hiçbir yanıt önbelleğe alınmaz (`Cache-Control: private/no-store` yanıtları dahil); çıkışta önbellek temizlenir. Not: Chrome kurulabilirlik denetimi PNG 192/512 ikon isteyebilir; PNG ikonlar gerçek logoyla birlikte üretilecek.
