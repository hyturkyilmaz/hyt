# NetKâr · Yol Haritası ve Sprint Planı (v0.1, 5 Kasım 2026)

Hafta numarası: N01 = 9 Kasım 2026 haftası (Pazartesi). Koordinatör hafta numarasını Python ile hesaplar.

## Özet
- **Kapı (N00, bu hafta):** Trendyol API erişimi, hukuk ve maliyet doğrulaması. Engel çıkarsa iş durur, Hasan'a karar sorulur.
- **MVP (N01-N06):** Trendyol bağlantısı, senkron, kâr motoru, panel, maliyet girişi, uyarılar. 5 beta satıcıyla gerçek veri.
- **Beta (N07-N09):** Abonelik, ödeme, fatura, onboarding, PWA bildirim, web sitesi ve ücretsiz araçlar canlı.
- **Lansman (N10-N12):** Kurucu 50 satıcı programı, vaka çalışmaları, başabaş yolunda ilk 100 ödeyen.
- **Sonrası:** AI soru yanıt taslağı, Hepsiburada/n11, Expo mobil uygulama, global (EN, Amazon/Shopify).

## Fazlar ve sprintler

| Sprint | Hafta | Kapsam | Bitti kriteri | Sorumlu (model) |
|---|---|---|---|---|
| S0 Kapı | N00 (5-8 Kas) | 01-06 araştırma dosyaları, maliyet modeli, karar kartı, repo iskeleti | 6 araştırma dosyası + maliyet Excel + GO/NO-GO kararı | Opus (sentez), Sonnet (araştırma) |
| S1 Temel | N01 | Monorepo, Docker Compose, CI (lint/test/güvenlik), DB şeması v1 + migrasyon, auth + kiracı + RLS, tasarım sistemi (tokenlar, bileşenler) | CI yeşil; kayıt/giriş/2FA e2e testi; RLS IDOR testi geçiyor | Sonnet (kod), Opus (mimari + güvenlik incelemesi) |
| S2 Trendyol | N02 | Trendyol istemcisi (rate limit, retry, stage), bağlantı ekranı, anahtar şifreleme, backfill + artımlı senkron (sipariş, iade, ürün) | Stage hesabında 90 günlük veri senkron; kişisel veri DB'ye yazılmıyor (test) | Sonnet, Opus inceleme |
| S3 Kâr motoru | N02-N03 | Kâr motoru (estimated/settled), finans ekstresi senkronu, mutabakat, maliyet girişi (form + Excel içe aktarma) | %100 satır kapsamı; 30+ altın test senaryosu (elle hesaplanmış); gerçek beta verisinde elle doğrulama | Opus (alan modeli), Sonnet (kod) |
| S4 Panel UI | N03-N04 | Özet (bugün/7/30 gün), ürün kârlılık tablosu, sipariş detayı ve kalem kırılımı, uyarılar, ayarlar; mobil öncelikli | Lighthouse mobil ≥ 90 (performans, erişilebilirlik); WCAG 2.2 AA otomatik testler; 5 kullanıcı testi | Sonnet (UI), Opus (UX incelemesi) |
| S5 Web sitesi | N02-N04 (paralel) | LP, fiyatlar, ücretsiz hesaplayıcılar (komisyon, kâr, desi), KVKK/güvenlik sayfaları, bekleme listesi, blog iskeleti | Canlıda; CWV yeşil; şema doğrulandı; bekleme listesi formu İYS/KVKK uyumlu | Sonnet (metin + kod), Haiku (doğrulama) |
| S6 Uyarı + bildirim | N05 | Zararına satış, reklam kârı yiyor, beklenmeyen kesinti, iade oranı artışı uyarıları; e-posta + web push | Uyarı kuralları testli; bildirim tercihleri | Sonnet |
| S7 Beta | N05-N06 | 5 beta satıcı onboarding, geri bildirim döngüsü, hata düzeltme, güvenlik denetimi (iç) | 5 satıcı haftalık aktif; kritik/yüksek açık yok | Opus (güvenlik), Sonnet |
| S8 Ödeme | N07 | Abonelik (ödeme kuruluşu), deneme süresi, plan limitleri, e-Arşiv fatura | Test kartıyla uçtan uca; iptal akışı | Sonnet, Opus inceleme |
| S9 Onboarding + analitik | N08 | Kayıt → bağlantı → ilk kâr görünümü < 10 dk; PostHog event'leri; e-posta dizisi | Aktivasyon hunisi ölçülüyor | Sonnet |
| S10 Lansman hazırlığı | N09 | Yük testi, yedek geri yükleme testi, durum sayfası, destek kanalı, yasal metinler son hali | Kontrol listesi tam | Opus, Haiku |
| S11-S12 Lansman | N10-N12 | Kurucu programı, vaka çalışmaları, topluluk lansmanı | 50 kurucu satıcı, ilk ödeyenler | Pazarlama planı |
| Sonra | N13+ | AI soru yanıt taslağı, Hepsiburada, Expo uygulama, EN | Ayrı plan | |

## Kritik yol
Trendyol API doğrulaması → S2 senkron → S3 kâr motoru (finans ekstresi eşlemesi) → beta verisiyle doğrulama. Kâr motoru yanlışsa ürün değersiz: en çok test burada.

## Hasan'ın zamanı (hedef: haftada en fazla 4 saat)
- Karar kartı yanıtları (haftada 30 dk)
- Beta satıcı bulma ve görüşme (N04-N06, haftada 2 saat)
- Prod deploy onayı ve hesap açılışları (ödeme kuruluşu, alan adı, mağaza hesapları)
