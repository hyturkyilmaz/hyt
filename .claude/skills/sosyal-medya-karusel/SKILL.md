---
name: sosyal-medya-karusel
description: Hasan Yasin Türkyılmaz adına LinkedIn / Instagram karusel görselleri (1080x1350), dikey video (1080x1920) ve paylaşım metinleri üretir. AI, pazarlama, reklam veya e-ticaret konusunda sosyal medya paylaşımı, karusel, slayt, post görseli, Reels/Shorts videosu istendiğinde kullan.
---

# Sosyal Medya Karusel

## Kalıcı kurallar (kullanıcı talebi, 24.10.2026)

1. **Her paylaşım CTA sayfasıyla biter.** Son slaytta kullanıcının fotoğrafı avatar olarak, altında:
   **"Hasan Yasin Türkyılmaz — AI, pazarlama, reklam ve e-ticaret danışmanlığı için iletişime geçin."**
   Alternatif: içerik çok kısaysa son içerik slaytına küçük tek satır CTA. Ama avatar her zaman var.
2. Avatar dosyası: `pazarlama/sosyal-medya/_assets/avatar.jpg` (veya .png). Dosya yoksa baş harfli yer tutucu (HYT) çizilir ve kullanıcıya fotoğraf yüklemesi hatırlatılır. Fotoğraf uydurulmaz, AI ile üretilmez.
3. Paylaşım metinlerinde de son satır aynı CTA (LinkedIn: tam cümle; Instagram: "Danışmanlık için DM").
4. 3–5 slayt (en fazla 6), son slayt CTA. Her içerik slaytının altında kısa kaynak satırı.
5. Metin dili: doğal, yalın Türkçe; yapay zekâ izi yok (klişe açılışlar, "işte", "hadi gelin", aşırı emoji, uzun tire yığını yok). Sektör terimleri İngilizce kalır (ROAS, CPA, lead, PMax).
6. Rakam ve tarih: kaynağı olmayan iddia slayta girmez. Tek kaynaklı veri "bağımsız teyit yok" notuyla verilir. Hesaplar kodla doğrulanır.

## Üretim hattı

```
pazarlama/sosyal-medya/
  _kaynak/posts.json      ← içerik (imza + postlar + slaytlar)
  _kaynak/render.mjs      ← HTML → PNG (Playwright, yerel Inter fontu, dış ağ yok)
  _assets/avatar.jpg      ← kullanıcı fotoğrafı
  <post-id>/slayt-N.png   ← 1080x1350 çıktı
  <post-id>/dikey/        ← 1080x1920 (video kareleri)
  PAYLASIM-METINLERI.md   ← LinkedIn + Instagram metinleri
```

1. `posts.json`'a yeni post ekle: `id` ASCII ve numaralı (`05-konu-adi`), `etiket`, `slaytlar` (tip: `kapak` | `icerik` | `cta`).
2. Render: `cd pazarlama/sosyal-medya/_kaynak && node render.mjs` (dikey: `node render.mjs --dikey 05`).
3. Video (opsiyonel, dikey kareler hazırken):
   ```bash
   ffmpeg -loop 1 -t 4.5 -i dikey/slayt-1.png ... -filter_complex "xfade=transition=slideleft:duration=0.5:offset=..." \
     -c:v libx264 -crf 20 -pix_fmt yuv420p -movflags +faststart cikti-9x16.mp4
   ```
   Müzik eklenmez (telif). Kullanıcıya platformun telifsiz kütüphanesini önerin.
4. Görsel kontrol: en yoğun slaytı ve CTA'yı oku (taşma, kırpılma, kontrast).
5. Test: repo kökünden `python3 -m unittest discover -s pazarlama/tests -v`. CTA kuralı, boyut, kaynak satırı ve HTML kaçışı test edilir.

## Tasarım sistemi

- Zemin `#0F1B2D`, metin `#F4F1EA`, ikincil `#A9B8CC`, vurgu `#F2B544`. Font Inter (yerel).
- Kapak: sarı şerit + büyük başlık + vurgu satırı + alt metin + "Kaydırın →".
- İçerik: başlık + 3–4 madde (halka ikon) + alt bilgi (kaynak · isim).
- CTA: özet cümle → avatar (300px, sarı çerçeve) → isim → unvan → sarı CTA kutusu.
- Kontrast: vurgu sarısı yalnızca koyu zeminde; sarı kutu içinde lacivert metin.

## Yayın

Paylaşım yapmak dış yayındır: kullanıcı onayı olmadan hiçbir platforma gönderme. Dosyaları teslim et, yayın kararını kullanıcıya bırak.
