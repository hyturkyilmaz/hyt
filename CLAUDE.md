# hyt — proje hafızası

Hasan Yasin Türkyılmaz (hyturkyilmaz.com) için içerik ve otomasyon deposu.

## Kullanıcı
- Sosyolog, full stack developer, dijital ve performans pazarlama direktörü, e-ticaret pazarlama uzmanı.
- Yanıt düzeni: Durum → Yapılanlar → Senin yapacakların → Öneri. Yalın, havacılık dili gibi.
- Yeni işte önce 3-5 maddelik taslak. Kaynakça en sonda APA. Metinlerde AI işareti yok.
- Hanefi; finans önerileri faizsiz/katılım. KVKK, GDPR, TR mevzuatı izinsiz ihlal edilmez.
- Hiçbir veri silinmez; dosyanın üzerine yazmadan önce yeni sürüm.

## Instagram içerik sistemi (Ekim 2026)
- Beceri: `.claude/skills/hyt-instagram-icerik/` — günlük gönderi hattı, kalite kapısı, şablon.
- Rehberler: `icerik/rehber/instagram-icerik-rehberi.md`, `icerik/rehber/gorsel-stil-rehberi.md`.
- Araçlar: `icerik/araclar/` — render-media.mjs (PNG+MP4), build-reels.py (ses+müzik+altyazı), muzik-uret.py (telifsiz), render-altyazi.mjs.
- Örnek 01 (Amazon × Claude, AJAN): `icerik/ornek-01/` — v2 onaylandı ("bu stil güzel, koruyalım").
- Stil: kâğıt zemin + ızgara, el çizimi alt çizgi, renkli zaman çizgisi, iş akışı şemaları, koyu CTA slaydı. Her gönderide ≥ 2 hareketli slayt.
- Renk: logo yeşili #2e9447; sütunlar SEO #1a73e8, Reklam #34a853, E-ticaret #f29900, AI #7b1fa2.
- Tek yazım hatası kuralı: yalnız açıklama gövdesinde, klavye kayması, yeri üretim notunda.
- Ses: klon yalnız Hasan Yasin'in kendi sesi. Chatterbox Multilingual (MIT) Colab'da; XTTS-v2 (CPML) ticari işte kullanılmaz. Müzik konuşmanın %8-10'u.
- Lead: yorum anahtar kelimesi → DM → kontrol listesi + WhatsApp Topluluğu (https://chat.whatsapp.com/GKWDdd2jVy3GNCngWVHPhh).
- Takvim aşamaları: örnek → 7 gün → 14 gün → 30 gün → günlük 1. 7 günlük plan hazır (`icerik/plan/7-gun-2026-10-14.md`, 14-20 Ekim). 14 günlük plan hazır (`icerik/plan/14-gun-2026-10-28.md`, 28 Ekim - 10 Kasım, 42 paylaşım). 30 günlük plan hazır (`icerik/plan/30-gun-2026-11-11.md`, 11 Kasım - 10 Aralık, 90 paylaşım). Sıradaki: 11 Aralık'tan itibaren günde 1 gönderi.
- Proje yönetimi: Trello "HYT Proje Yönetimi" panosu (https://trello.com/b/sCt5VDnm). Kart adı `[HYT Marka] (P1) İş (S/M/L)`, açıklamada "Bitti kriteri". Akış: Yapılacaklar → Devam Eden → İncelemede → Tamamlandı. `/trello-proje-yonetimi` becerisi bu ortamda yüklü değil; panonun kendi kuralları uygulanıyor.
- Günde 3 paylaşım: 09:10 carousel · 13:10 story · 20:50 reels (kullanıcı isteği, 13 Ekim).
- Reels günde 1, en yüksek etkileşim saatinde (kullanıcı isteği, 28 Ekim): hafta içi ve pazar 20:50, perşembe 08:50, cuma-cumartesi 21:20 TRT. Kaynak Buffer 2026 + Türkiye akşam verisi; ilk 7 günden sonra Instagram İstatistikleri ile doğrulanır. Takvimler: `icerik/plan/reels-gunluk-2026-10-28.md` (28 Ekim - 10 Kasım), `icerik/plan/reels-gunluk-2026-11-11.md` (11 Kasım - 10 Aralık). Resmi anma saatlerinde (10 Kasım sabahı) ticari paylaşım yok.
- Çok platformlu yayın (kullanıcı isteği, 5 Kasım): her video 6 platformda (Instagram, Facebook, YouTube Shorts, TikTok, X, LinkedIn). Paket `icerik/gonderiler/<id>/yayin_paketi.md`, kuyruk `icerik/yayin/yayin_kuyrugu-2026-11-11.json`, plan `icerik/plan/coklu-platform-2026-11-11.md`. Saat TRT: LinkedIn 08:40 (hafta sonu 10:40), X 09:40 (11:40), YouTube 18:40, Instagram+Facebook Reels kuralı, TikTok 22:10 (hafta sonu 11:10). DM otomasyonu yalnız Instagram; diğerlerinde WhatsApp Topluluğu bağlantısı, LinkedIn'de bağlantı ilk yorumda. HubSpot sosyal izni yok; yayın Cowork/Chrome veya platform zamanlayıcısıyla. WhatsApp sabit mesajları ve profil metinleri: `icerik/yayin/whatsapp-sabit-mesajlar-2026-11-11.md` (her gün 08:30, sütun grubuna). Kontrol hatırlatmaları kurulu: 10 Kasım 19:10, 18 Kasım 09:10 (7 gün saat karşılaştırması), 26 Kasım 10:10 (izlenme süresi).
- Eski videolar 17:50 kuşağı (kullanıcı onayı, 10 Kasım): Ekim ve Kasım başında üretilip paylaşılmayan 15 video 11-25 Kasım her gün 17:50 Instagram Reels, altyazısız ve telifsiz müzikli (`medya/reels-muzikli-altyazisiz.mp4`, `build-reels.py --altyazisiz`). Plan `icerik/plan/eski-videolar-1750-2026-11-11.md`. Paylaşılmayacak: 28 Ekim META, 1 Kasım özet, 2 Kasım 11.11, 9 Kasım 11.11 operasyon (eskidi). Yayınlananlar: Örnek 01 AJAN (7 Kasım), GPT-6 MODEL (10 Kasım).
- Akşam gönderimi (kullanıcı isteği, 11 Kasım): her gün 21:40 TRT zamanlanmış görev ertesi günün 30 günlük plan videosunu (`medya/reels-muzikli-altyazisiz.mp4`) ve metnini (`yayin-reels-<tarih>.md`, carousel açıklamasından, "Videoda") kullanıcıya gönderir; 10 Aralık'tan sonra kendini kapatır. Kullanıcı yalnız video paylaşıyor, altyazısız tercih ediyor.
- Düzeltme kuralı: değişen bilgi silinmez; eski gönderiye sabit yorum + haftalık özette açık düzeltme (örnek: 28 Ekim META, Meta şartları ertelendi).
- Tek komut: `python3 icerik/araclar/gonderi-uret.py icerik/gonderiler/<id>/gonderi.json`.
- Instagram'a doğrudan erişim yok (bulut oturumu kullanıcının Chrome'una bağlanamaz); yayın Meta Business Suite Planlayıcı ile kullanıcıda.

## Ortam notları
- Bulut oturumunda instagram.com, hyturkyilmaz.com, huggingface.co kapalı olabilir.
- GitHub push 403 → kullanıcı claude.ai/connect-github ile bağlantıyı yeniler.
- Drive ses hattı: `MyDrive/Claude/Projects/hyt growth/video-klon/` (ref, senaryo, cikti, yuz).
