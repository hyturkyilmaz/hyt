# HYT Görsel Stil Rehberi — Instagram

Sürüm 2.0 · 13 Ekim 2026

## Yönetici özeti

- **Ton:** Teknik, bilgilendirici, yönlendirici danışman. Süs değil kanıt: ekran, tablo, akış şeması, kaynak satırı.
- **Zemin:** Açık kâğıt rengi + ince ızgara çizgisi. CTA slaydı koyu zemin + ızgara.
- **Renk:** hyturkyilmaz.com CTA blok sistemi. Her içerik sütununun kendi rengi var.
- **Hareket:** Her gönderide en az 2 hareketli slayt (MP4). Kapak + bir ekran/akış slaydı.
- **Kural:** Her slaytta tek fikir, altta kaynak veya uygulama satırı.

## 1. Referans

| Kaynak | Alınan |
|---|---|
| @lawrenceaiseo | Kâğıt zemin, küçük harf aralıklı üst etiket, kalın başlık + el çizimi alt çizgi, renkli noktalı zaman çizgisi, alt kaynak satırı, sol çizgili prompt bloğu |
| @badarmunir_official | Numaralı başlık + iş akışı ekranı (renkli düğüm, kesikli bağlantı), son slaytta koyu ızgara zemin üstünde yorum anahtar kelimesi |
| hyturkyilmaz.com | Renk paleti, sol kenarı 4-6 px renkli çizgili blok, "siz" yerine sahadan "ben" dili |

## 2. Renk

| Rol | HEX | Kullanım |
|---|---|---|
| SEO / Arama | `#1a73e8` | SEO, GEO, Search Console içerikleri |
| Reklam | `#34a853` | Google Ads, Meta Ads, onay/başarı işaretleri |
| E-ticaret | `#f29900` | Pazaryeri, CRO, mağaza içerikleri |
| AI | `#7b1fa2` | Claude, GPT, ajanlar, prompt blokları |
| Kâğıt | `#f5f7fa` | Zemin |
| Mürekkep | `#111827` | Başlık, düğüm, kod bloğu zemini |
| Gri metin | `#6b7280` | Üst etiket, kaynak satırı |
| Koyu zemin | `#0f172a` | CTA slaydı |

Gönderinin sütunu ana vurgu rengini belirler (alt çizgi, üst etiket noktası, CTA anahtar kelimesi). Diğer renkler zaman çizgisi ve şemalarda kategori ayırmak için kullanılır.

## 3. Tipografi

- Başlık: Inter Display ExtraBold, 80-112 px, harf aralığı -2/-3 px.
- Gövde: Inter Medium 34-38 px.
- Üst etiket: Inter Bold 24 px, büyük harf, 3 px aralık.
- Kod ve kural blokları: DejaVu Sans Mono 27 px.

## 4. Slayt kalıpları

| Kalıp | Ne zaman | Bileşen |
|---|---|---|
| Kapak | 1. slayt | Üst etiket, başlık + alt çizgi, alt başlık, zaman çizgisi veya 3 madde önizleme, kaynak |
| Ekran | Bir aracı göstermek | Pencere çerçevesi, yazılan istek animasyonu, tablo, onay düğmeleri, "temsili ekran" notu |
| Akış | Süreç anlatmak | Renkli dairesel düğümler, kesikli akan bağlantılar, insan onayı halkalı yeşil düğüm |
| Önce / Sonra | Veri veya düzen farkı | İki tablo ekranı, kırmızı/yeşil etiket |
| Kural + Prompt | Uygulanabilir adım | Koyu kod bloğu + mor çizgili "Claude'a yapıştır" bloğu |
| Matris | Sorumluluk, karşılaştırma | Renk kodlu satır işaretli tablo |
| CTA | Son slayt | Koyu ızgara, anahtar kelime büyük ve titreşimli, Kaydet/Paylaş/Takip çipleri |

## 5. Medya türleri

| Tür | Biçim | Not |
|---|---|---|
| Carousel görsel | PNG 1080×1350 | Statik slaytlar |
| Carousel video | MP4 H.264 1080×1350, 5-8 sn, sessiz | Instagram carousel'de fotoğraf ve video karışık yüklenebilir |
| Reels | MP4 1080×1920, 25-40 sn | Slaytlar ortada, üst-alt boşluk. Ses uygulama içinde lisanslı kütüphaneden eklenir |
| GIF | 540 px, 15 fps | Instagram GIF kabul etmez. Site, LinkedIn, e-posta, WhatsApp için |
| Ekran görüntüsü | Gerçek araç ekranı | Varsa gerçek ekran tercih edilir; kişisel veri, müşteri adı, sipariş numarası bulanıklaştırılır |

## 6. Doğruluk kuralları

- Temsili ekranlarda alt not zorunlu: "Temsili ekran. Gerçek arayüz farklı olabilir."
- Başka bir markanın logosu, arayüz birebir kopyası veya ticari takdimi kullanılmaz. Ürün adı metin olarak geçer.
- Örnek rakamlar "örnek değerler" notuyla verilir.
- Grafiklerde yalnızca doğrulanmış veri. Kaynağı olmayan oran çizilmez.

## 7. Üretim

```
node icerik/araclar/render-media.mjs <slaytlar.html> <cikti-klasoru> 30
```

- `data-duration="6"` taşıyan slayt MP4 olur, diğerleri PNG.
- Animasyonlar CSS ile yazılır; araç kareleri tek tek çeker, sonuç her seferinde aynıdır.
- Reels ve GIF için ffmpeg komutları `icerik/ornek-01/aciklama.md` içinde.
