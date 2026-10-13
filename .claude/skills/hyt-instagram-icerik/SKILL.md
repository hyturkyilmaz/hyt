---
name: hyt-instagram-icerik
description: hyturkyilmaz.com için Instagram/Reels/TikTok/Shorts içeriği üretir — trend araştırması, carousel slaytları (hareketli MP4 + PNG), açıklama metni (tek yazım hatası kuralı), Hasan Yasin'in klon sesiyle seslendirme senaryosu, telifsiz müzikli Reels montajı, yorum anahtar kelimesi → DM → WhatsApp Topluluğu lead akışı ve lead magnet PDF'i. "Instagram gönderisi hazırla", "carousel", "reels", "günlük içerik", "7/14/30 günlük plan", "AJAN gibi anahtar kelime", "lead magnet", "DM akışı" isteklerinde kullan.
---

# HYT Instagram İçerik Sistemi

Hasan Yasin Türkyılmaz (sosyolog, full stack developer, dijital ve performans pazarlama direktörü) için
lead generation ve içerik üreticisi kimliğine hizmet eden günlük içerik hattı.

Bu beceri bir üretim hattıdır: her adımın aracı repoda hazır. Önce `references/` altındaki ilgili dosyayı
oku, sonra araçları çalıştır, en sonda **Kalite kapısı**ndan geçmeyen hiçbir şeyi teslim etme.

## Kullanıcı tercihleri (her yanıtta)

- Yanıt düzeni: **Durum → Yapılanlar → Senin yapacakların → Öneri**. Havacılık dili gibi yalın, kısa.
- Yeni işte önce 3-5 maddelik taslak (özet, hedef, genel çerçeve), sonra detay.
- Kaynakça en sonda, APA stilinde. Metinlerde AI işareti yok, insan gibi yazılır.
- Hanefi mezhebine uygunluk: faiz, kumar, bahis, kaldıraçlı kripto önerisi veya sponsoru yok. Finans örnekleri katılım bankacılığı üzerinden.
- KVKK, GDPR ve Türk mevzuatı izinsiz ihlal edilmez. Ticari ileti için İYS + ayrı onay.
- Hiçbir veri silinmez. Kullanıcının dosyalarının üzerine yazmadan önce yedek veya yeni sürüm.
- Duygusal ve finansal zarar verecek öneri yok. Doğrulanmamış haber yok.

## Hızlı yol (tek komut)

1. `icerik/gonderiler/<tarih>-<slug>/gonderi.json` yaz (örnek: `icerik/gonderiler/2026-10-15-gpt6-model/gonderi.json`).
   İçerik: slaytlar (tipler: kapak, ekran, akis, grafik, oncesonra, kural, matris, cta), açıklama, yazım hatası,
   doğrulama kaynakları, seslendirme senaryosu, lead magnet.
2. `python3 icerik/araclar/gonderi-uret.py icerik/gonderiler/<id>/gonderi.json`
   → slaytlar.html, medya (PNG+MP4), reels-altyazili.mp4, story.mp4, aciklama.md, dm.md, senaryo.json, lead PDF.
3. `python3 .claude/skills/hyt-instagram-icerik/scripts/kontrol.py icerik/gonderiler/<id>`
4. Günde 3 paylaşım: 09:10 carousel · 13:10 story · 20:50 reels. Plan örneği: `icerik/plan/7-gun-2026-10-14.md`.
   Reels açıklaması da tek yazım hatası taşır (plan tablosunda).

Metinde `_kelime_` el çizimi alt çizgi, `**kelime**` kalın. Ekran slaytında `istek` ≤ 45 karakter (tek satır).
Kullanılan anahtar kelimeler: AJAN, MODEL, REKLAM, INDEKS, AKIŞ, SEPET, PROMPT.
Kullanılan yazım hataları: müşterilerimzin, hesapaldım, kampanyalrda, sayfalrın, mesajlşama, politkasını, açıklamlarını,
hazırlk, antlatıyorum, açmdan, müdahle, Kurlumu, hazr, Kopayla. Tekrar etme.

## Hat (her gönderi, ayrıntılı)

| # | Adım | Araç / referans |
|---|---|---|
| 1 | Trend tara, konu puanla (TR yakınlık + bu hafta uygulanabilirlik + lead magnet bağı, 7/9 altı elenir) | `references/arastirma.md` |
| 2 | Haberi en az 2 bağımsız kaynakla doğrula; tek kaynaklı rakam kullanılmaz | WebSearch |
| 3 | Gönderi klasörü aç | `bash .claude/skills/hyt-instagram-icerik/scripts/yeni-gonderi.sh <tarih> <slug> <sutun>` |
| 4 | Slaytları yaz (7 slayt kalıbı) | `sablonlar/carousel-7.html`, `references/gorsel-stil.md` |
| 5 | Medyayı üret: PNG + MP4 | `node icerik/araclar/render-media.mjs <html> <medya> 30` |
| 6 | Açıklama metni + üretim notu (tek yazım hatası) | `references/metin.md` |
| 7 | Seslendirme senaryosu JSON (tts + altyazi alanları) | `references/ses-muzik.md` |
| 8 | Klon ses: Colab defteri (Chatterbox, MIT) | Drive `video-klon/HYT_ses_klon_chatterbox.ipynb` |
| 9 | Reels montajı (ses + %9 müzik + altyazı) | `python3 icerik/araclar/build-reels.py ...` |
| 10 | DM akışı + lead magnet | `references/dm-akisi.md`, `icerik/dm-akisi/` |
| 11 | Kalite kapısı | `python3 .claude/skills/hyt-instagram-icerik/scripts/kontrol.py <gonderi-klasoru>` |
| 12 | Yayın saati ve takvim | `references/takvim.md` |

## Kalite kapısı (teslimden önce hepsi ✔)

**İçerik**
1. Kanca ilk slaytta ≤ 10 kelime, sayı veya isim içeriyor.
2. Her slayt tek fikir; her slaytta kaynak veya uygulama satırı var.
3. Haber 2 kaynakla doğrulandı; temsili ekranlarda "Temsili ekran" notu var.
4. Başka markanın logosu veya arayüz kopyası yok; ürün adı yalnız metin olarak.
5. Örnek rakamlar "örnek değerler" notlu.

**Metin**
6. Açıklama 600-1.200 karakter, 3-5 hashtag.
7. Tam 1 yazım hatası: açıklama gövdesinde, klavye kayması türü; kanca, CTA kelimesi, marka, rakam, hashtag ve görsellerde değil. Yeri üretim notunda.
8. Ben dili, sahadan gözlem, bir cümle sosyolog bakışı. Abartı sıfatı yok (devrim, inanılmaz, oyun değiştirici).
9. CTA tek anahtar kelime, büyük harf; DM akışıyla aynı kelime.

**Görsel / video**
10. PNG 1080×1350; carousel MP4 1080×1350, H.264, 3-60 sn; en az 2 hareketli slayt.
11. Logo işareti her slaytta; renk sütuna göre (`references/marka.md`).
12. Reels 1080×1920, yazılar güvenli alanda (üst 160 px, alt 430 px boş), altyazı her konuşmada.
13. Ses: konuşma -16 LUFS, müzik konuşmanın %8-10'u, final -14 LUFS.

**Lead / hukuk**
14. DM metni, WhatsApp Topluluğu bağlantısı ve kontrol listesi bağlantısı hazır.
15. DM'de kişisel veri istenmiyor; bülten ayrı, onaylı form üzerinden.
16. Müzik telifsiz (yalnız `muzik-uret.py` çıktısı veya lisansı belgelenmiş kaynak). Trend sesler uygulama içinden, lisanslı kütüphaneden eklenir.
17. Ses klonu yalnız Hasan Yasin'in kendi sesi; ticari kullanıma uygun lisanslı model (Chatterbox MIT). XTTS-v2 (CPML) ticari işte kullanılmaz.

## Sabitler

- Site: https://hyturkyilmaz.com · Instagram: @hyturkyilmaz
- WhatsApp Topluluğu: https://chat.whatsapp.com/GKWDdd2jVy3GNCngWVHPhh
- KVKK: https://hyturkyilmaz.com/kvkk-aydinlatma-metni/
- Drive ses hattı: `MyDrive/Claude/Projects/hyt growth/video-klon/` (ref, senaryo, cikti, yuz)
- Mevcut site lead magnet'leri: 25 maddelik e-ticaret CRO listesi, 30 maddelik Google Ads hesap listesi, 20 maddelik teknik SEO listesi, AI görünürlük raporu.

## Bilinen ortam sınırları (bulut oturumu)

- instagram.com, hyturkyilmaz.com, huggingface.co ağ politikasında kapalı olabilir → ekran görüntüsünü kullanıcıdan iste, logoyu dosya olarak iste, ses klonunu Colab'da çalıştır.
- GitHub push 403 verirse kullanıcı claude.ai/connect-github üzerinden bağlantıyı yeniler.
