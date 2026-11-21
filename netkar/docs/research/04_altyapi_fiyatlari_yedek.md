# 04 Altyapı Fiyatları (erişim tarihi: 5 Kasım 2026)

## Durum özeti

Bu çalışmada yalnızca LLM API fiyatları resmi kaynaktan doğrulanabildi. Oturumun ağ politikası yalnızca Anthropic alan adlarına (claude.com, platform.claude.com) izin verdi. Diğer tüm resmi fiyat sayfaları (TCMB, Hetzner, Vercel, Supabase, Neon, Cloudflare, Resend, Sentry, iyzico, Paraşüt vb.) `getaddrinfo ENOTFOUND` veya proxy 403 hatası verdi. Kurala uygun olarak bu kalemlerin fiyatı uydurulmadı, "doğrulanmadı" işaretlendi ve CSV'de fiyat hücresi boş bırakıldı. Hesaplama yapılmadı.

Tamamlamak için gerekli: oturumun izinli alan listesine aşağıdaki "Erişim gereken alan adları" bölümündeki hostlar eklenmeli, ardından toplama yeniden çalıştırılmalı.

## 6. LLM API (doğrulandı, USD, KDV hariç liste fiyatı)

| Model | Girdi /1M tok | Çıktı /1M tok | Cache okuma | Cache yazma 5 dk | Cache yazma 1 sa | Batch girdi | Batch çıktı |
|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 2 | 10 | 0,10 | 2,50 | 4 | 1 | 5 |
| Claude Haiku 5.5 (istem <= 100K token) | 0,10 | 0,50 | 0,01 | 0,125 | 0,20 | 0,05 | 0,25 |
| Claude Haiku 5.5 (istem > 100K token) | 0,50 | 2,50 | 0,05 | 0,625 | 1 | 0,25 | 1,25 |

Notlar:
- Batch API hem girdi hem çıktıda %50 indirim verir; prompt caching ile birleştirilebilir.
- Haiku 5.5 fiyatı istem uzunluğuna göre iki kademelidir; eşik cache okuma/yazma tokenlarını da sayar, her istem ayrı fiyatlanır.
- ABD'de sabitlenmiş çıkarım (`inference_geo`) tüm kalemlere 1,1x çarpan uygular.
- Sonnet 5.5 için cache okuma, taban girdinin 0,05 katıdır (Sonnet 5'te 0,10 kat).
- Kaynak: Anthropic (2026) ve claude.com fiyat sayfası. Erişim: 5 Kasım 2026.

## Diğer kalemler (hepsi doğrulanmadı)

| Grup | Kalem | Durum |
|---|---|---|
| Döviz | USD/TRY, EUR/TRY (TCMB) | doğrulanmadı, TCMB erişilemedi |
| Barındırma | Hetzner CX/CPX/CCX, yedek, snapshot, trafik | doğrulanmadı |
| Barındırma TR | Natro, Turhost, Radore, Veridyen, Netinternet, Turkcell Bulut | doğrulanmadı |
| Web | Vercel, Cloudflare Pages/Workers, Netlify | doğrulanmadı |
| Veritabanı | Supabase, Neon | doğrulanmadı |
| Redis | Upstash | doğrulanmadı |
| Depolama | R2, Hetzner Object Storage, Backblaze B2 | doğrulanmadı |
| Self-host PaaS | Coolify, Dokploy (açık kaynak, ücretsiz olduğu doğrulanmadı) | doğrulanmadı |
| E-posta | Resend, Postmark, Amazon SES | doğrulanmadı |
| İzleme | Sentry, Better Stack, UptimeRobot, PostHog, Plausible, Umami | doğrulanmadı |
| Alan adı | .com, .com.tr (nic.tr) | doğrulanmadı |
| Mağaza/mobil | Apple Developer, Google Play, Expo EAS | doğrulanmadı |
| Ödeme | iyzico, PayTR, Param, Stripe (TR kullanılabilirliği) | doğrulanmadı |
| e-Arşiv | Paraşüt, BirFatura, Logo İşbaşı, Uyumsoft | doğrulanmadı |
| Muhasebe | Mali müşavir (şahıs, limited), limited kuruluş maliyeti | doğrulanmadı |

Hetzner için tek ikincil ipucu: üçüncü taraf bloglar 2026 Nisan ve Haziran'da fiyat artışı ve CX22/CPX21 yerine CX23/CPX22 geçişi bildiriyor. Rakamlar birbiriyle çelişiyor, resmi sayfayla teyit edilmediği için kullanılmamalı.

## Erişim gereken alan adları

www.tcmb.gov.tr, www.hetzner.com, vercel.com, developers.cloudflare.com, www.cloudflare.com, www.netlify.com, supabase.com, neon.com, upstash.com, www.backblaze.com, coolify.io, dokploy.com, resend.com, postmarkapp.com, aws.amazon.com, sentry.io, betterstack.com, uptimerobot.com, posthog.com, plausible.io, umami.is, www.nic.tr, developer.apple.com, support.google.com, expo.dev, www.iyzico.com, www.paytr.com, www.param.com.tr, stripe.com, www.parasut.com, www.birfatura.com, www.logo.com.tr, www.uyumsoft.com, www.turmob.org.tr, www.natro.com, www.turhost.com, www.radore.com, www.veridyen.com, www.netinternet.com.tr, bulut.turkcell.com.tr.

## Kaynaklar (APA 7)

Anthropic. (2026, 5 Kasım). *Pricing*. Claude Docs. https://platform.claude.com/docs/en/about-claude/pricing

Anthropic. (2026, 5 Kasım). *Pricing*. Claude. https://claude.com/pricing

Not: Çıktı CSV: `/home/user/hyt/netkar/calisma_dosyalari/fiyatlar_2026-11-05.csv` (71 satır; 23 doğrulanmış LLM kalemi, kalanı doğrulanmadı).
