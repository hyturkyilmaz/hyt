# 04 Altyapı Fiyatları (erişim tarihi: 5 Kasım 2026)

## Yöntem ve güven düzeyi

- WebFetch yalnızca Anthropic alan adlarında çalıştı. LLM fiyatları resmi sayfadan okundu (güven: yüksek).
- Diğer kalemler WebSearch özetlerinden alındı, sayfalar açılamadı. Resmi sayfa snippet'i olanlar "orta-yüksek", blog veya agregatör kaynaklılar "orta", "orta-düşük" ya da "düşük" işaretlendi. Hiç sonuç çıkmayanlar "doğrulanmadı".
- Çelişen kaynaklar iki rakamıyla birlikte yazıldı. Hesap yapılmadı. Tüm sayısal kayıtlar CSV'de: `/home/user/hyt/netkar/calisma_dosyalari/fiyatlar_2026-11-05.csv` (74 satır: 22 yüksek, 42 WebSearch tabanlı, 10 doğrulanmadı).
- Bu belgedeki rakamların çoğu üçüncü taraf kaynaktır. Bütçe kararından önce resmi sayfalarla teyit edilmelidir.

## 1. Döviz (TCMB gösterge kuru, 5 Kasım 2026)

| Çift | Alış | Satış | Güven |
|---|---|---|---|
| USD/TRY | 49,9360 | 50,0260 | orta-yüksek |
| EUR/TRY | 56,1576 | 56,2588 | orta-yüksek |

Özet TCMB günlük kur sayfasına atıf yapıyor. EUR değerleri KKTC Merkez Bankası tablosunda aynı; serbest piyasa SPOT satış (50,03 ve 56,26) tutarlı. Kur 15.30 sonrası kesinleşir.

## 2. Barındırma

### Hetzner Cloud (KDV hariç, EUR/ay, güven: orta)

| Plan | Güncel | Zam öncesi | Not |
|---|---|---|---|
| CX23 (2 vCPU, 4 GB) | 5,49 | 3,99 | Çelişki: Better Stack 5,99 (IPv4 dahil). Bir kaynak CX serisi artık sipariş edilemiyor diyor. |
| CX33 (4 vCPU, 8 GB) | 8,49 | 6,49 | Tek kaynak |
| CPX22 (2 vCPU, 4 GB) | 19,49 | 7,99 | 15 Haziran 2026 zammı |
| CPX32 (4 vCPU, 8 GB) | 35,49 | 13,99 | 15 Haziran 2026 zammı |
| CCX13 (2 adanmış vCPU, 8 GB) | 42,99 | 15,99 | 15 Haziran 2026 zammı |
| IPv4 adresi | 0,50 | | ek ücret |

Yedekleme, snapshot ve ek trafik ücreti: doğrulanmadı. Nisan 2026'da ortalama %30-37 zam bildirildi.

### Türkiye VPS (4 vCPU / 8 GB benzeri, KDV hariç, güven: düşük)

| Sağlayıcı | Plan | Fiyat | Not |
|---|---|---|---|
| Natro | XCloud Pro (4 vCPU, 8 GB, 200 GB SSD) | 41,11 USD/ay | Çelişki: aynı sayfa başlığı 29,99 USD. Agregatör (whtop). |
| Turhost | VPS 4 | 17,14 USD/ay | Çelişki: 2 vCPU/4 GB olarak tanımlı, 4/8 eşdeğerliği doğrulanmadı |
| Radore, Veridyen, Netinternet, Turkcell Bulut | | doğrulanmadı | Aramada VPS fiyatı çıkmadı |

### Web ve veri katmanı

| Kalem | Fiyat | Güven | Not |
|---|---|---|---|
| Vercel Pro | 20 USD/koltuk-ay | orta | Kullanım ayrıca |
| Cloudflare Workers Paid | 5 USD/ay | orta-yüksek | 10M istek dahil, ek 0,30 USD/1M |
| Netlify | doğrulanmadı | | |
| Supabase Pro | 25 USD/ay | orta | Compute ayrıca ölçülür. Team 599 USD. |
| Neon | 0,106 USD/CU-saat, 0,35 USD/GB-ay | düşük | Launch/Scale plan fiyatı teyit edilemedi |
| Upstash Redis PAYG | 0,20 USD/100K komut | orta-yüksek | Free: 500K komut/ay. Depolama 0,25 USD/GB. Bant genişliği kaynakları çelişiyor. |
| Cloudflare R2 | 0,015 USD/GB-ay | orta-yüksek | Class A 4,50, Class B 0,36 USD/1M, egress ücretsiz, 10 GB ücretsiz |
| Backblaze B2 | 6,95 USD/TB-ay | orta | Eski sayfalarda 6 USD |
| Hetzner Object Storage | 6,49 EUR/ay (1 TB + 1 TB egress) | düşük | Ek depolama 8,70 EUR/TB (atıf belirsiz), başka sitede 4,09 USD |
| Coolify, Dokploy | doğrulanmadı | | Aranmadı |

## 3. Servisler

| Kalem | Fiyat | Güven | Not |
|---|---|---|---|
| Resend Free | 3.000 e-posta/ay, günde 100 | orta | |
| Resend Pro | 20 USD/ay (50K e-posta) | orta | Aşım 0,90 USD/1000. 100K için 35 USD ve 90 USD çelişkisi. |
| Postmark Basic | 15 USD/ay (10K) | orta | Aşım 1,80 USD/1000 |
| Amazon SES | 0,10 USD/1000 (a la carte) | orta | Çelişki: Temmuz 2026'dan beri yeni hesaplar Essentials, 0,16 USD/1000 |
| Sentry Team | 26 USD/ay (yıllık), 29 USD/ay (aylık) | orta | Developer ücretsiz (5K hata) |
| Expo EAS Starter / Production | 19 / 199 USD/ay | orta | Free 0 USD. Production için eski 99 USD güncel değil. |
| Apple Developer Program | 99 USD/yıl | orta | |
| Google Play Console | 25 USD tek seferlik | orta | |
| .com | yaklaşık 15 USD/yıl kayıt | düşük | Yenileme 420-550 TRY |
| .com.tr (nic.tr) | 450-650 TRY/yıl (.tr uzantıları) | düşük | Cloudean promosyon 6,54 USD. Resmi tarife bulunamadı. |
| Better Stack, UptimeRobot, PostHog, Plausible, Umami, Cloudflare Free | doğrulanmadı | | Aranmadı |

## 4. Ödeme kuruluşları (Türkiye)

| Kuruluş | Bulgu | Güven |
|---|---|---|
| iyzico | Tek çekim %2,79 + 0,25 TL (bir kaynak). Çelişki: başka kaynak %2,49'dan başlayan oran, 0,25 TL işlem ücreti. Oranlar işletmeye özel. Kolay POS sabit aylık ücretli (tutar yok). Abonelik modülü ücreti bulunamadı. | düşük |
| PayTR | Genel aralık %0,99-4,00. Tekrarlayan ödeme için yayımlı oran yok, başvuruya özel. Kart Saklama API'si recurring_payment destekliyor. | düşük |
| Param | doğrulanmadı | |
| Stripe | Çelişki: çoğu kaynak Türkiye'den doğrudan hesap açılamadığını söylüyor (ABD/UK şirketi gerekir). Zunapro 2024'te Türkiye lansmanı iddia ediyor, teyit yok. | düşük |

## 5. e-Arşiv entegratörleri

| Kalem | Fiyat | Güven | Not |
|---|---|---|---|
| Paraşüt ön muhasebe + e-fatura | 752 TRY/ay + KDV, yıllık 9.024 TRY + KDV | orta | Çelişki: başka sayfada 940 TRY/ay, 11.280 TRY/yıl + KDV. 300 kontör hediye. |
| Paraşüt e-kontör | 100 adet 400 TRY + KDV, 200 adet 660 TRY + KDV | orta | 12 ay geçerli |
| BirFatura e-kontör | 0,713 TRY/kontör (2.000 adetlik paket) | orta | Yıllık paket tutarı bulunamadı. Mali mühür 3 yıl 2.500 TRY + KDV. |
| Logo İşbaşı, Uyumsoft | doğrulanmadı | | |

Rakip not: Faturaport yıllık paketleri 1.000 / 5.000 / 6.500 TRY (kaynak bir blog).

## 6. LLM API (doğrulandı, USD, KDV hariç liste fiyatı, 1M token)

| Model | Girdi | Çıktı | Cache okuma | Cache yazma 5 dk | Cache yazma 1 sa | Batch girdi | Batch çıktı |
|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 2 | 10 | 0,10 | 2,50 | 4 | 1 | 5 |
| Claude Haiku 5.5 (istem <= 100K) | 0,10 | 0,50 | 0,01 | 0,125 | 0,20 | 0,05 | 0,25 |
| Claude Haiku 5.5 (istem > 100K) | 0,50 | 2,50 | 0,05 | 0,625 | 1 | 0,25 | 1,25 |

Batch API girdi ve çıktıda %50 indirim verir ve caching ile birleşir. ABD'de sabitlenmiş çıkarım 1,1x çarpandır. Haiku 5.5 eşiği cache tokenlarını da sayar.

## 7. Mali müşavir ve kuruluş (güven: orta-düşük)

| Kalem | Rakam | Not |
|---|---|---|
| Şahıs şirketi aylık | 3.593 TRY'den (serbest meslek 4.492) | Kobitime. 2026 tarifesi Resmi Gazete 33110, 4 il grubu |
| Limited şirket aylık | 7.985 TRY (Kobitime) ve 10.381 TRY, 4. grup (Faturaport) | Çelişki. Orta ölçek 12.776 TRY. Beyanname ve kuruluş ayrıca. |
| Limited kuruluş (sermaye hariç) | 30.000-42.500 TRY (Paraşüt) | Çelişki: Faturaport 24.000-32.000 (tablosunda 33.000-42.000), Vergi Merkezi 29.000-35.000. Asgari sermaye 50.000 TRY. |

## Doğrulanmayan kalemler

Hetzner yedek/snapshot/trafik, Radore, Veridyen, Netinternet, Turkcell Bulut, Netlify, Coolify, Dokploy, Better Stack, UptimeRobot, PostHog, Plausible, Umami, Cloudflare DNS/WAF Free, Param, Logo İşbaşı, Uyumsoft.

## Kaynaklar (APA 7)

Anthropic. (2026, 5 Kasım). *Pricing*. Claude Docs. https://platform.claude.com/docs/en/about-claude/pricing

Better Stack. (2026). *Hetzner Cloud review 2026*. https://betterstack.com/community/guides/web-servers/hetzner-cloud-review/

Bitdoze. (2026, 20 Ekim). *Hetzner Cloud precios 2026*. https://www.bitdoze.com/md/es/hetzner-cloud-precios-2026.md

Cloudflare. (2026). *R2 pricing*. https://developers.cloudflare.com/r2/pricing/

Cloudflare. (2026). *Workers pricing*. https://developers.cloudflare.com/workers/platform/pricing/

Faturaport. (2026). *2026 yılında SM, SMMM, YMM asgari ücret tarifeleri*. https://faturaport.com/blog/on-muhasebe/2026-yilinda-sm-smmm-ymm-asgari-ucret-tarifeleri-kapsamli-rehber

Karekod. (2026). *Domain fiyatları 2026*. https://www.karekod.org/blog/domain-fiyatlari/

Kobitime. (2026). *Aylık muhasebeci ücretleri 2026*. https://kobitime.com/aylik-muhasebeci-ucretleri-2026/

KKTC Merkez Bankası. (2026, 5 Kasım). *Tarih bazında kur sorgulama*. https://www.kktcmerkezbankasi.org/tr/veriler/doviz_kurlari/kur_sorgulama

Paraşüt. (2026). *Limited şirket kuruluş maliyetleri*. https://www.parasut.com/blog/limited-sirket-kurulus-maliyetleri

Paraşüt. (2026). *Elektronik fatura hizmetinin maliyeti*. https://www.parasut.com/kullanim-kilavuzu/elektronik-fatura-hizmetinin-maliyeti

PrivateDevOps. (2026). *Hetzner June 2026 cloud price increase*. https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do

T.C. Merkez Bankası. (2026, 5 Kasım). *Günlük döviz kurları*. https://www.turkiye.gov.tr/doviz-kurlari

Upstash. (2026). *Redis pricing*. https://upstash.com/pricing/redis

Whtop. (2026). *Natro XCloud Pro; Turhost VPS 4*. https://www.whtop.com/tr/plans/natro.com/142483 ; https://www.whtop.com/tr/plans/turhost.com/88337

Diğer ikincil kaynaklar (satır bazında) CSV'deki `kaynak_url` sütununda.

Yedekler: `fiyatlar_2026-11-05_yedek.csv` ve `04_altyapi_fiyatlari_yedek.md` (ilk sürüm, aynı klasörler).
