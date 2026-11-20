# ADR-0009: Uyarı kuralları, uyarı olayları ve bildirim teslimatı (S6)

- Durum: Önerildi (yalnız tasarım; kod, migrasyon dosyası, test ve gerçek gönderim bu ADR'nin kapsamı dışında)
- Tarih: 20 Kasım 2026
- İlgili: `docs/30_yol_haritasi.md` S6 satırı; `docs/10_mimari.md` §2 (bildirim bileşeni), §3 madde 5a ve 6, §5
  (`ad_spend`, `alerts` tabloları); `docs/12_kar_motoru.md` K10, K15, K23 (§6), K25 (§7), K37, K44;
  `docs/50_guvenlik.md` G01, G06, G07, G09, G16; `docs/60_tasarim_sistemi.md` §7 (servis çalışanı kuralları);
  `docs/research/01_trendyol_api.md` §2.4e (reklam), §2.5 (webhook); `docs/research/03_hukuk_ve_uyum.md` §4 (6563 ve
  İYS); `docs/research/05_pazarlama_gtm.md` (uyarı vaadi, satır 143-144, 342); ADR-0001 (RLS, `auth_gate` deseni),
  ADR-0004 (zarf şifreleme), ADR-0005 (senkron, worker rolü), ADR-0006/0007 (ayar sürümü K44), ADR-0008 §12 K12
  (gerçek e-posta arka ucu).
- Kod referansları `claude/dazzling-clarke-pfvf32` dalının çalışma ağacına göredir. Satır numaraları değişebilir.
  Testler bu ADR için koşulmadı. Doküman metni veri olarak okundu.

## 1. Bağlam ve mevcut durum envanteri

### 1.1 Motorun bugün ürettiği uyarı kodları

Kodlar `services/api/app/profit/enums.py:33-54` (`WarningCode`). Hepsi tek dönem (sipariş günü aralığı) içindir;
kalıcı kayıt yoktur, bildirim yoktur.

| Kod | Düzey | Üretildiği yer | S6 ile ilişkisi |
|---|---|---|---|
| `ZARAR` | satır | `app/profit/lines.py:146-149` (K37: `net_kar < 0` ya da null iken bilinen giderlerle zarar) | "Zararına satış" kuralının ham girdisi. İade zararını da kapsar (bkz. 3.1). |
| `BEKLENMEYEN_KESINTI` | satır | `app/profit/lines.py:50-91`, karar `:71-77` | "Beklenmeyen kesinti" kuralının ham girdisi. |
| `MALIYET_EKSIK` | satır | `app/profit/costs.py:69` | Panel uyarısı; bildirim kapsamı dışı. |
| `IADE_KAYDI_BEKLENIYOR` | satır | `app/profit/costs.py:62` | Aynı. |
| `KARGO_TARIFESI_EKSIK`, `KARGO_DESI_VARSAYILAN` | satır | `app/profit/shipping.py:120`, `:128` | Aynı. `KARGO_DESI_VARSAYILAN` beklenmeyen kesintide yanlış pozitif kaynağıdır. |
| `KARGO_DESI_FARKI`, `KARGO_FATURASI_KDV_BELIRSIZ` | satır | `app/profit/shipping.py:161`, `:164` | Aynı. |
| `HIZMET_BEDELI_TAHMINI_EKSIK` | satır | `app/profit/fees.py:114` | Aynı. |
| `SINIFLANDIRILMAMIS_KESINTI` | dönem | `app/profit/fees.py:47-48` | Aynı. |
| `ESLESMEMIS_HAKEDIS_DUZELTMESI`, `EKSTRE_IC_TUTARSIZLIK`, `KOMISYON_ORANI_FARKLI` | satır | `app/profit/settlement.py:130`, `:132`, `:140` | Aynı. |
| `MALIYET_EKSIK_SATIRLAR_VAR`, `KARGO_EKSIK_SATIRLAR_VAR`, `HIZMET_BEDELI_EKSIK_SATIRLAR_VAR`, `IADE_KAYDI_BEKLENEN_SATIRLAR_VAR`, `STOPAJ_EKSTRE_FARKI` | dönem | `app/profit/aggregate.py:181`, `:183`, `:185`, `:187`, `:191` | Aynı. |

Eşikler: `WarningThresholds` (`app/profit/settings.py:66-77`): mutlak 5,00 TL, oransal %5, yuvarlama toleransı
0,05 TL. Bu eşikler hesap ayarı olarak SAKLANMIYOR: `to_profit_settings` `thresholds` vermez
(`app/services/profit_settings.py:385-400`), motor varsayılanı geçerlidir.

### 1.2 `/alerts` ucu bugün

- Uç: `GET /v1/marketplace-accounts/{account_id}/profit/alerts` (`app/api/v1/profit.py:609-647`). Rapor
  önbelleğinden dönem sonucunu alır, `build_alerts` ile listeler (`app/services/profit_views.py:818-851`, iptal
  satırlar hariç `:822-823`). Yeni kural yoktur; kalıcı durum (okundu, susturuldu) yoktur.
- `not_yet_available` (`app/services/profit_views.py:731-738`): `REKLAM_KARI_YIYOR` ("ad_spend henüz yok") ve
  `IADE_ORANI_ARTISI` ("motor çıktısı henüz yok (S6)"). Web bu listeyi ad olarak gösterir
  (`apps/web/src/lib/profit/alerts.ts:387-399`, `apps/web/src/components/profit/alerts-view.tsx:137`).

### 1.3 Eksik olanlar

| Eksik | Kanıt | Sonuç |
|---|---|---|
| Reklam harcaması verisi | Trendyol API dizininde reklam ucu yok (research/01 §2.4e satır 137, güven Yüksek). Ekstredeki "Satıcı Reklamı Satın Alma" bakiye yükleme tutarıdır, harcama değildir (satır 138, 141, güven Orta). `otherfinancials` içindeki satır tipi Doğrulanmadı (satır 139). Ürün bazında harcama yalnız panel "Oluşturulan Reklamlar" Excel'inden gelir (satır 140, güven Orta); kolon adları Doğrulanmadı (satır 238; docs/12 K15 ve §9 madde 13, satır 575). | Kaynak: kullanıcı Excel/CSV yüklemesi. API yok, kazıma yok (10_mimari §3 madde 5a). |
| `ad_spend` tablosu ve besleyici | Motor girdi tipi var (`AdRecord`, `app/profit/inputs.py:153-163`; dağıtım `app/profit/advertising.py:30`; ürün ROAS ve başabaş ROAS `app/profit/aggregate.py:83-87`). Besleyici `ad_records` vermez (`app/services/profit_feed.py:370-381`). Tablo ve migrasyon yok (`migrations/versions/` 0001-0024). | REKLAM_KARI_YIYOR için önce veri dilimi gerekir (D9). |
| İade oranı kuralı | `returns` tablosu var (`app/models/trendyol_data.py:132-152`: `barcode`, `status`, `claim_date`, `order_line_id`); iadeler 15 dakikada bir çekilir (`app/worker/tasks.py:43`). Kural yok. | Motor dışında, tarihe bağlı kohort kuralı (bkz. 3.4). |
| Kalıcı uyarı olayı | Tablo yok. `10_mimari.md` §5 `alerts` tablosunu planlar (satır 96). | Bu ADR tanımlar (bölüm 4). |
| Bildirim teslimatı | E-posta yalnız `file` ve `memory` arka uçları (`app/core/email.py:36-47`, `:61-98`); `EmailMessage` yalnız `to`, `subject`, `body` (`:21-27`). Gönderim istek içi `BackgroundTasks` ile yapılır (`app/api/v1/auth.py:101-122`); DB outbox yok. Prod gerçek arka uç olmadan açılmaz (`app/core/config.py:294-296`). Web push yok; servis çalışanı yok (`apps/web/src/app/manifest.ts:5-6`, `docs/60_tasarim_sistemi.md` §7). | Outbox tablosu, dağıtıcı iş ve push bu ADR'de. |
| Worker'ın alıcı adresi okuması | `netkar_worker` `users` ve `memberships` üzerinde yetkisiz (0001'de `users` yalnız `netkar_app` ve `netkar_auth`: `migrations/versions/0001_initial.py:133-142`; 0006 worker yetkileri `:326-338`). | Dar SECURITY DEFINER işlev gerekir (bölüm 4.4). |
| Worker'ın veri sürümü okuması | `report_data_revisions` worker'a kapalı (`migrations/versions/0012_report_data_revision.py:10`). | 0025'te worker'a SELECT (bölüm 5). |
| Gerçek e-posta sağlayıcısı kararı | Karar kaydında K-N11 YOK (`docs/karar_kaydi.md` K-N01..K-N09). Açık karar ADR-0008 §12 K12 ve staging planı C13 (`docs/operasyon/staging_ve_dagitim_plani.md:249`). | Bu ADR sağlayıcı seçmez; arayüze bağlar (bölüm 7.1). |

## 2. Karar özeti

1. Dört bildirim kuralı (`ZARARINA_SATIS`, `REKLAM_KARI_YIYOR`, `BEKLENMEYEN_KESINTI`, `IADE_ORANI_ARTISI`) yeni,
   saf bir modülde yazılır (`app/alerts/rules.py`, yeni). Kâr motoru ve altın testler değişmez. İlk üçü motor
   sonucunu okur; iade oranı tarihli kohort sayımı okur.
2. Değerlendirme worker'da procrastinate işidir (`alerts.evaluate`): senkron sonrası, ayar/maliyet yazımı sonrası ve
   günde bir kez. Değerlendirme anahtarı (hesap, İstanbul günü, veri sürümü, ayar sürümü, kural sürümü) tekildir; aynı
   anahtar ikinci kez çalışmaz (idempotent).
3. Sonuç `alert_events` tablosuna yazılır: kimlik alanları değişmez, durum geçişleri yalnız ekleme yapılan
   `alert_event_transitions` üzerinden. RLS zorunlu.
4. Bildirimler aynı işlemde `notification_outbox`'a yazılır (transactional outbox). Ayrı dağıtıcı iş gönderir.
   Gerçek gönderim iki bayrakla varsayılan KAPALI: `ALERT_NOTIFICATIONS_ENABLED=false` ve
   `WEB_PUSH_ENABLED=false`. Kapalıyken e-posta mevcut `file`/`memory` arka ucuna yazılır, push yalnız log meta.
5. Kanal x kural tercih matrisi kullanıcı başınadır; eşikler hesap başınadır. Sessiz saatler ve günlük özet
   Europe/Istanbul saatidir.
6. Bildirim içeriğinde son müşteri verisi YOKTUR (zaten motor girdisinde yok); sipariş numarası e-posta ve push'a
   girmez. Tutar gösterimi kullanıcı tercihidir; push için varsayılan kapalı.
7. Uyarı e-postaları işlemsel (bilgilendirme) iletidir, İYS kaydı gerektirmediği kanaatindeyiz; avukat teyidi
   gerekir (bölüm 9). Bu e-postalara tanıtım içeriği konmaz.

## 3. Kurallar

Ortak kurallar:

- **Para:** tüm tutarlar `Decimal`, KDV hariç, kuruş. Satır tutarları motorda `rnd` (ROUND_HALF_UP,
  `app/profit/money.py:33`) ile yuvarlanmış gelir; kural yalnız toplar ve karşılaştırır, yeniden yuvarlamaz.
  Eşikler `numeric(14,2)`. Kural kodunda `float` yasak (test: AST taraması, `app/alerts/` altında `float(` ve
  `math.` yok). Olay yükünde (`payload`) tutarlar API'deki gibi metin olarak saklanır.
- **Oranlar:** `Decimal` kesir; yüzde yalnız gösterimde 1 ondalığa yuvarlanır. İstatistik karşılaştırmaları
  `decimal.localcontext(prec=28)` içinde, karekök almadan (z² ile) yapılır.
- **Null kuralı (K37, docs/12 satır 891-900):** `net_kar` null olan satır veya ürün hiçbir kuralda 0 sayılmaz.
  Kural ya bilinen giderlerle kesin sonucu kullanır ya da o konu için uyarı üretmez.
- **Kesinlik:** her olay yükü motorun kesinlik etiketini (`kesin`, `tahmini`) taşır (K40). Bildirim metni
  "tahmini" sözcüğünü gösterir.
- **Damga (K44, docs/12 satır 1215-1218):** her olay `data_revision` ve `settings_revision` taşır; e-posta özeti
  ayar sürümünü yazar.
- **Pencereler:** İstanbul günü, bugün dahil, panelin `range` tanımıyla aynı (`app/services/profit_views.py:44`,
  `:78-90`). Bildirimdeki bağlantı aynı `start`/`end` ile paneli açar; kullanıcı aynı sayıyı görür.

### 3.1 ZARARINA_SATIS

| Alan | Tasarım |
|---|---|
| Tanım | Ürünün son 7 günde en az bir satış satırı, iade etkisi olmadan zararda. |
| Girdi | Motor sonucu, 7 günlük dönem (`range=7d`). Satır `ZARAR` uyarısı (`lines.py:149`), `refunded_quantity == 0` ve `pending_refund_quantity == 0` (`app/profit/results.py:136-138`), durum `cancelled` değil. |
| Neden iade süzgeci | `ZARAR` tam iade edilen satırda da çıkar (G16: -100,00, docs/12 K10). Bu "iade zararı"dır, "zararına satış" değildir. İade zararı iade oranı kuralına aittir. |
| Kapsam ve tekilleştirme | Ürün (barkod). Anahtar `ZARARINA_SATIS|<hesap>|<barkod>`. Pencere anahtara girmez: ürün zararda kaldıkça tek olay açık kalır, `last_seen_at` ilerler. |
| Yük | zarar satır sayısı; toplam zarar = Σ satır `net_kar` (null ise `eksik_giderler_haric_kar`); en kötü satır zararı; kesinlik; eksik kalem var mı. |
| Eşik | Hesap ayarı `loss_min_amount` (varsayılan 5,00 TL): toplam zarar bu tutarın altındaysa olay açılmaz. 0,00 izinli. |
| Gürültü | Aynı olay için yeniden bildirim yok. İstisna: toplam zarar son bildirilen değerin 2 katına çıkarsa YALNIZ BİR KEZ daha (4 kat, 8 kat için ek bildirim yok; D1 kodu: `loss_notification_due(total, notified_amount, renotified=...)`). Yük `notified_amount` ve D2'de `renotified` bayrağı saklanır. |
| Kapanma | Değerlendirmede koşul yoksa `resolved`. 7 gün içinde yeniden açılırsa bildirim gitmez, yalnız panelde açılır. |
| Yanlış pozitif | (a) Tahmini kargo (tarife, varsayılan desi) gerçekten yüksek çıkabilir; (b) maliyet yanlış girilmiş; (c) kampanya indirimi bilerek zarar; (d) D9 gelince mağaza reklamının `dagitim_tahmini` payı satır zararına neden olabilir (tahmini mağaza reklamıyla zarar bildirimi) ve aynı üründe ZARARINA_SATIS ile REKLAM_KARI_YIYOR birlikte çalışabilir (çift bildirim). D9'a kadar reklam verisi olmadığı için ikisi de görünmez; D9'da bildirim birleştirme yeniden değerlendirilecek. Azaltım: kesinlik etiketi metinde; "Bu ürünü 30 gün sustur" eylemi. |

### 3.2 REKLAM_KARI_YIYOR

Ön koşul: reklam verisi (D9). Veri yokken kural çalışmaz ve `not_yet_available` kalır.

| Alan | Tasarım |
|---|---|
| Tanım | Ürün reklamdan önce kârda, reklam payı bu kârın eşik yüzdesini yiyor. |
| Girdi | Motor sonucu, 30 günlük dönem. Ürün toplamı (`aggregate_products`, `app/profit/aggregate.py:55-121`): `advertising_spend` (`:81`, `:114`), `net_profit` (`:80`). Satır `ad_details` (`app/profit/results.py:148`, `AdDetail.kind` kaynak: `eslesen` ya da `dagitim_tahmini`, `results.py:99-102`). |
| Formül | `spend = reklam_harcamasi`; `before = net_kar + spend`. Koşul: `net_kar` null değil, `spend >= ad_min_spend`, `before > 0`, `spend * 100 >= ad_share_percent * before`. |
| ROAS neden kullanılmıyor | Ürün ROAS'ı KDV dahil ciro ile, başabaş ROAS KDV hariç ciro ile hesaplanır (docs/12 satır 530-531); doğrudan karşılaştırma hatalıdır. Kâr tabanlı tanım birim karışıklığı taşımaz. Panel kartında başabaş ROAS bilgi olarak gösterilir. |
| Eşikler | Hesap ayarı `ad_share_percent` (varsayılan 100: reklam sonrası kâr <= 0; izinli aralık 50-100) ve `ad_min_spend` (varsayılan 50,00 TL). |
| Tahmini dağıtım | Mağaza reklamı, eşlenmeyen barkod: `dagitim_tahmini` (docs/12 K15). Koşul yalnız eşlenen harcamayla (`kind == eslesen` toplamı) da sağlanıyorsa bildirim gider. Yalnız tahmini dağıtımla sağlanıyorsa olay panelde "tahmini" rozetiyle açılır, bildirim gitmez. |
| Satışsız reklam | `reklam_satissiz` (`aggregate.py:74`) olan ve satışı olmayan ürün bu kurala girmez (`before` hesaplanamaz). Ayrı uyarı bu ADR'de yok. |
| Çakışma | `before <= 0` ise ürün zaten zararda; bu kural açılmaz, `ZARARINA_SATIS` kapsar. |
| Kapsam, anahtar | Ürün. `REKLAM_KARI_YIYOR|<hesap>|<barkod>`. |
| Gürültü | Yeniden bildirim 14 gün sonra ve yalnız koşul hâlâ sağlanıyorsa (haftalık değil, iki haftalık hatırlatma). |
| Yanlış pozitif | Excel atıf penceresi 7 gün (research/01 satır 140): harcama ile satış aynı pencereye düşmeyebilir. 30 günlük pencere bu kaymayı azaltır, kaldırmaz. Excel KDV durumu Doğrulanmadı (docs/12 §9 madde 13): yanlış işaret harcamayı %20 şişirir. |

### 3.3 BEKLENMEYEN_KESINTI

| Alan | Tasarım |
|---|---|
| Tanım | Motorun `BEKLENMEYEN_KESINTI` ürettiği satır (K23, docs/12 §6). Yeni hesap yok. |
| Girdi | Motor sonucu, 92 günlük dönem (`MAX_PERIOD_DAYS`, `profit_views.py:41`). Gerekçe: ekstre teslimattan sonra gelir (research/01 satır 23; docs/12 §5); 30 günlük pencere geç gelen ekstreyi kaçırır. Satır `comparison.difference`, `threshold`, `shipping_estimate_default_desi`. |
| Eşik | Motor eşiği SABİT (5,00 TL / %5 / 0,05; `settings.py:66-77`). Kiracı ayarı değildir: motor eşiğini değiştirmek rapor sayısını ve K44 damgasını etkiler, ayar tarihçesine (ADR-0007) girmesi gerekir. Bunun yerine bildirim eşiği hesap ayarıdır: `deduction_notify_min` (varsayılan 10,00 TL; olay her zaman açılır, yalnız bu tutarın altındaki fark anlık bildirim üretmez, özete girer). |
| Kapsam, anahtar | Sipariş satırı. `BEKLENMEYEN_KESINTI|<hesap>|<sipariş no>|<paket>|<satır>`. Sipariş numarası olay tablosunda kalır (panel bağlantısı için), bildirim içeriğine girmez. |
| Gürültü | Ekstre senkronu günde 2 kez (`tasks.py:44`). Bir değerlendirmede açılan yeni olaylar tek bildirimde toplanır: "12 satırda beklenmeyen kesinti, toplam 184,20 TL". Aynı satır bir kez bildirilir. |
| Yanlış pozitif | (a) Kargo tahmini varsayılan desiyle yapılmış (`KARGO_DESI_VARSAYILAN`, `default_desi_used` `profit_views.py:805`, `:846`): öneri bildirimden dışla, panelde göster (Hasan kararı H10). Bastırma YALNIZ fark kargodan geliyorsa uygulanır: kesin gönderi kargosu karşılaştırmaya girmediyse ya da kargo dışı fark (`fark - (kargo_kesin - kargo_tahmini)`) tek başına motor eşiğini (`esik`) aşıyorsa (ör. komisyon farkı) bastırma yoktur. (b) Kampanya komisyonu: `KOMISYON_ORANI_FARKLI` ile birlikte gelir; yükte işaretlenir. (c) Tarife eski: ayar güncellenince sonraki değerlendirmede olay kapanır (`resolved`). |

### 3.4 IADE_ORANI_ARTISI

Motor dönemlik çalışır; iade oranı ise iki dönemin kıyasıdır ve iadeler gecikmeyle gelir. Kural motor dışındadır,
`returns` ve `order_lines` üzerinden kohort sayar.

**Birim:** sipariş satırı (ürün başına). Adet değil: aynı siparişteki adetler birbirinden bağımsız değildir (tek
müşteri 5 adedi birlikte iade eder). `x` = en az bir iade kalemi olan satır sayısı, `n` = satır sayısı.

**Sayılan iade:** `returns.status = "Accepted"` (motorun kullandığı tek değer, `app/profit/costs.py:16`). Diğer
statü adları kodda yok; "reddedilen hariç tüm talepler" kümesi pilot veriyle tanımlanır (Doğrulanmadı). Bu seçim
iade sayısını eksik sayar: yanlış pozitifi azaltır, gecikmeyi artırır.

**Sabit ufuk kohortu:** her iki dönemde de yalnız sipariş gününden sonraki `H` gün içinde açılmış iade sayılır
(`claim_date <= ordered_at + H`). Böylece yeni kohort "henüz iade edecek vakti olmadı" diye düşük görünmez.

- `T` = değerlendirme günü (İstanbul). `H = 21` gün (Trendyol iade süresi + kargo; süre Doğrulanmadı, pilot veriyle
  ayarlanır).
- Güncel kohort `C`: sipariş günü `[T-H-28, T-H)` (28 gün).
- Taban kohort `B`: sipariş günü `[T-H-28-84, T-H-28)` (84 gün).
- İptal satırlar (K26) ve `removed_at` dolu satırlar sayılmaz.

**Test (tek yönlü iki oran z testi, havuzlu):**

```
pC = xC / nC        pB = xB / nB        p = (xC + xB) / (nC + nB)
fark = pC - pB
z2   = fark^2 / ( p * (1 - p) * (1/nC + 1/nB) )
Alarm: fark > 0  VE  z2 >= z_kritik^2  VE  fark >= min_fark  VE  pC >= 1,5 * pB
```

Tüm işlemler `Decimal` bölme ve çarpmadır; karekök yoktur. `z_kritik^2` sabit tablodan gelir.

**Küçük örneklemde alarm yok (hepsi sağlanmalı):**

1. `nC >= 30` ve `nB >= 60`.
2. `xC >= 5`.
3. Normal yaklaşım koşulu her iki kohortta: `n * p >= 5` ve `n * (1 - p) >= 5` (havuzlu `p` ile).
4. `p = 0` ya da `p = 1` ise test yapılmaz (payda sıfır).

**Çoklu karşılaştırma:** bir hesapta onlarca ürün aynı gün test edilir. Bonferroni ile ürün başına anlamlılık
`0,01 / k` olur (`k` = 1-3 koşulunu geçen ürün sayısı). Kritik değer kova tablosundan, kovanın üst ucuyla (ihtiyatlı):

| `k` | α (tek yönlü) | `z_kritik` | `z_kritik^2` |
|---|---|---|---|
| 1 | 0,01 | 2,326 | 5,412 |
| 2-5 | 0,002 | 2,878 | 8,284 |
| 6-20 | 0,0005 | 3,291 | 10,828 |
| 21-100 | 0,0001 | 3,719 | 13,832 |
| 101-500 | 0,00002 | 4,107 | 16,872 |
| 501 ve üstü | bkz. aşağıdaki not | | 18,190 ... 30,150 |

Hesap düzeyinde aynı test tüm ürünlerin toplamına `k = 1` ile ayrıca uygulanır (kapsam `account`).

Kova tablosu D1 kodunda `app/alerts/stats.py`'dedir. Kritik değer `inv_cdf(1 - alfa)^2` olarak `statistics.NormalDist` ile hesaplanıp 3 ondalığa YUKARI yuvarlanmıştır (testle doğrulanır). `k > 100` için kovalar genişletildi (alfa her kova üst ucu için 0,01/k'ya eşit ya da daha sıkı): 101-500: 0,00002 (16,872); 501-1000: 0,00001 (18,190); 1001-5000: 0,000002 (21,265); 5001-50000: 0,0000002 (25,695); üstü 0,00000002 (30,150). Karar `z^2` ile kritik değer arasında tamsayı çapraz çarpımla verilir. Ürün sayısı pratikte 50000'i geçmez.

| Alan | Tasarım |
|---|---|
| Eşik | `min_fark` hesap ayarı `return_min_diff_points` (varsayılan 5 yüzde puanı). α, `H`, pencere uzunlukları ve küçük örneklem sınırları SABİT (yanlış ayarla istatistiği bozmamak için). |
| Kesinlik | Olay `tahmini` etiketlidir (istatistiksel çıkarım; yalnız `Accepted` talepler sayılır). Motor etiketi yoktur. |
| Kapsam, anahtar | Ürün: `IADE_ORANI_ARTISI|<hesap>|<barkod>`; hesap: `IADE_ORANI_ARTISI|<hesap>|*`. |
| Yük | `nC`, `xC`, `nB`, `xB`, `pC`, `pB` (metin, 4 ondalık), kohort tarihleri, `k`, iade neden kodlarının ilk 3'ü (`reason_code`, yalnız kod, serbest metin yok). |
| Gürültü | Günlük pencere kaydığı için ardışık günler yüksek korelasyonludur; yeniden bildirim 14 gün içinde yok. Kanal varsayılanı günlük özet. |
| Gecikme | Sinyal sipariş gününden en erken `H` gün sonra görünür. Bilinçli ödün: erken ama gürültülü sinyal yerine geç ama savunulabilir sinyal. |
| Yanlış pozitif | Sezon ve kampanya (Kasım indirimleri iadeyi artırır), kategori değişikliği, tek bir kusurlu parti (gerçek sinyal). Azaltım: tabanın 84 gün olması; susturma. |
| Reddedilen yöntemler | Fisher kesin testi (küçük örneklemde doğru ama Decimal ile faktöriyel ve kuyruk toplamı pahalı, açıklaması zor). Wilson aralıklarının örtüşmesi (çok ihtiyatlı, anlamlılık düzeyi belirsiz). Basit "oran 2 katına çıktı" (küçük örneklemde 1/10'dan 2/10'a alarm). |

## 4. Veri modeli

### 4.1 `alert_events`

| Sütun | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id`, `marketplace_account_id` | uuid | Kiracı ve hesap. FK `tenants`, hesap FK `marketplace_accounts`. |
| `rule` | text | CHECK: 4 kural adı. |
| `scope` | text | CHECK: `product`, `order_line`, `account`. |
| `subject` | text | Kapsam önekli: `urun:<barkod>` (barkodun baş/son boşluğu atılır), `satir:<sipariş no>|<paket>|<satır>`, `hesap:*`. |
| `dedupe_key` | text | `sha256(rule|hesap|subject)` hex; hesap kimliği kanonik küçük harfli UUID metnine çevrilir. UNIQUE (`tenant_id`, `marketplace_account_id`, `dedupe_key`). |
| `first_seen_at`, `last_seen_at` | timestamptz | `first_seen_at` değişmez. |
| `occurrence_count` | int | Görüldüğü değerlendirme sayısı. |
| `severity` | text | CHECK: `high` (zararına satış, beklenmeyen kesinti), `medium` (reklam, iade). |
| `status` | text | CHECK: `open`, `read`, `muted`, `resolved`. Yalnız geçiş tetikleyicisi yazar. |
| `muted_until` | timestamptz null | `muted` iken zorunlu; en çok `now() + 90 gün`. |
| `resolved_at` | timestamptz null | Koşul kalkınca worker yazar. |
| `payload` | jsonb | Kural yükü (bölüm 3). Anahtar izin listesi CHECK ile (ör. `email`, `name`, `address` anahtarı yasak). Boyut <= 4 KB. |
| `payload_version` | smallint | Kural sürümü. |
| `data_revision`, `settings_revision` | bigint | Son değerlendirmenin damgası (0012 sayacı, K44). |
| `last_notified_at`, `notified_amount` | timestamptz null, numeric(14,2) null | Bastırma kuralları için. |
| `created_at` | timestamptz | `now()`, istemciden verilemez. |

Durum anlamı kiracı düzeyidir (bir üye okundu yaparsa hesap için okunmuş olur). Kullanıcı başına okundu bilgisi
Hasan kararıdır (H1).

### 4.2 `alert_event_transitions` (yalnız ekleme)

`id`, `tenant_id`, `alert_event_id` (FK), `from_status`, `to_status`, `actor` (`user` | `system`), `actor_user_id`
(null: sistem), `muted_until`, `created_at`. UPDATE, DELETE, TRUNCATE 23514 (0020 deseni:
`migrations/versions/0020_recovery_code_immutability.py:3-4`, `:52-53`).

AFTER INSERT tetikleyicisi (SECURITY DEFINER, sabit `search_path`) `alert_events.status`, `muted_until`,
`resolved_at` alanlarını günceller. İzinli geçişler:

| Kim | Geçiş |
|---|---|
| Kullanıcı (`netkar_app`, `actor_user_id = app.user_id`) | `open -> read`, `read -> open`, `open/read -> muted` (owner/admin; `muted_until` zorunlu), `muted -> open` (owner/admin) |
| Sistem (`netkar_worker`) | `open/read -> resolved`, `resolved -> open` (yeniden görülme), `muted -> open` (`muted_until` geçti), `muted -> resolved` |

Diğer her geçiş 23514. Rol denetimi tetikleyicide `memberships` üzerinden yapılır (uygulama katmanı ayrıca
`require_role` ile, çift kilit).

### 4.3 Değişmezlik

- `alert_events` BEFORE UPDATE tetikleyicisi: `id`, `tenant_id`, `marketplace_account_id`, `rule`, `scope`, `subject`,
  `dedupe_key`, `first_seen_at`, `created_at` değişirse 23514 (0024 `memberships_immutable_guard` deseni,
  `migrations/versions/0024_privilege_narrowing_2.py:85`).
- `status`, `muted_until`, `resolved_at` yalnız geçiş tetikleyicisinin oturum işaretiyle (`set_config` işlem yerel
  bayrağı, 0012 deseni) değişebilir; doğrudan UPDATE 23514.
- `netkar_app`: `alert_events` üzerinde yalnız SELECT; `alert_event_transitions` üzerinde SELECT, INSERT.
- `netkar_worker`: `alert_events` SELECT, INSERT, UPDATE (sistem sütunları: `last_seen_at`, `occurrence_count`,
  `severity`, `payload`, `payload_version`, `data_revision`, `settings_revision`, `last_notified_at`,
  `notified_amount`); geçiş tablosuna INSERT. DELETE hiçbir uygulama rolünde yok.
- Saklama: `resolved` olaylar 13 ay sonra silinir (H13). Silme sahibi `netkar_owner` olan dar işlevle
  (`alert_gate.purge_resolved(cutoff)`), worker periyodik işiyle çağrılır.

### 4.4 Bildirim tabloları

| Tablo | Sütunlar (özet) | Yazan | RLS |
|---|---|---|---|
| `alert_rule_settings` | `tenant_id`, `marketplace_account_id` (PK), `loss_min_amount`, `ad_share_percent`, `ad_min_spend`, `deduction_notify_min`, `return_min_diff_points`, `rules_enabled` (text[]), `updated_by`, `updated_at` | `netkar_app` (owner/admin) | tenant |
| `notification_preferences` | PK (`tenant_id`, `user_id`, `rule`, `channel`); `mode` CHECK `off`, `instant`, `digest` | `netkar_app` (yalnız kendi satırı) | tenant VE `user_id = app.user_id` (yazma); worker tenant (okuma) |
| `notification_settings` | PK (`tenant_id`, `user_id`); `quiet_start`, `quiet_end` (time), `digest_hour` (0-23), `show_amounts_email`, `show_amounts_push` (bool) | `netkar_app` (kendi) | aynı |
| `push_subscriptions` | `id`, `tenant_id`, `user_id`, `endpoint_host` (düz, izin listesi için), `endpoint_digest` (HMAC, UNIQUE), `endpoint_enc`, `p256dh_enc`, `auth_enc` (ADR-0004 zarf), `vapid_key_id`, `created_session_id`, `created_at`, `last_success_at`, `failure_count`, `revoked_at` | `netkar_app` (INSERT, kendi satırında `revoked_at`); worker (`last_success_at`, `failure_count`, `revoked_at`) | tenant VE kullanıcı |
| `notification_outbox` | `id`, `tenant_id`, `user_id`, `channel`, `kind` (`instant`, `digest`, `test`), `dedupe_key` UNIQUE, `alert_event_ids` uuid[], `payload` jsonb (izin listesi), `status` (`pending`, `held`, `sent`, `failed`, `suppressed`, `skipped`), `not_before`, `attempts`, `last_error_class`, `created_at`, `sent_at` | yalnız `netkar_worker` | tenant |
| `alert_evaluations` | `id`, `tenant_id`, `marketplace_account_id`, `as_of_date`, `data_revision`, `settings_revision`, `rules_version`, `started_at`, `finished_at`, `status`, `counts` jsonb; UNIQUE (hesap, `as_of_date`, `data_revision`, `settings_revision`, `rules_version`) | yalnız worker; yalnız ekleme + `finished_at`/`status` bir kez | tenant |

Alıcı adresi outbox'ta saklanmaz: gönderim anında `notify_gate.email_for(user_id, tenant_id)` ile okunur. İşlev
SECURITY DEFINER, sahibi yeni NOLOGIN `netkar_notify_gate` rolü (`users(id, email, email_verified_at)` ve
`memberships` üzerinde SELECT, adlandırılmış politika), sabit `search_path`, PUBLIC EXECUTE yok, yalnız
`netkar_worker` çalıştırır. Kullanıcı artık üye değilse ya da e-postası doğrulanmamışsa NULL döner ve satır
`skipped` olur. Kiracılar arası iş listesi `notify_gate.due_outbox(limit)` ile alınır (yalnız `id`, `tenant_id`;
`sync_gate.syncable_accounts` deseni, `app/services/sync/runner.py:201-211`).

### 4.5 Reklam verisi tablosu (D9, ayrı migrasyon)

`ad_spend_records`: `id`, `tenant_id`, `marketplace_account_id`, `import_id`, `record_key` (Excel satırından
türetilmiş, UNIQUE hesapla), `barcode` null, `start_date`, `end_date`, `spend` numeric(14,2), `spend_includes_vat`,
`ad_revenue` numeric(14,2) null, `created_at`. Alanlar `AdRecord` ile birebir (`app/profit/inputs.py:153-163`);
Excel kolon eşlemesi Doğrulanmadı, içe aktarma ekranında kolon eşleme adımı olur (docs/12 K15). İçe aktarma
güvenliği `app/services/cost_import.py:1-17` desenidir (imza, zip sınırları, akışlı okuyucu, formül enjeksiyonu).
Bu tablo `report_data_revisions` tetikleyici listesine EKLENMELİ (`0012_report_data_revision.py:46-55`); aksi
halde rapor önbelleği eski sonuç döndürür ve değerlendirme atlanır. Elle giriş (tek kayıt formu) aynı tabloya yazar.

## 5. Migrasyon taslağı (0025, geri alınabilir)

Numara: son migrasyon `0024_privilege_narrowing_2.py`. ADR-0008 0023'ü önermişti, o numara
`0023_session_update_privileges.py` ile kullanıldı; numara uygulama anında son dosyaya göre verilir.

Upgrade sırası:

1. Rol denetimi: `netkar_worker`, `netkar_app` yoksa hata (0007 deseni `:69-70`). Yeni NOLOGIN rol
   `netkar_notify_gate` `app/db/provision.py` ve `infra/postgres/init/01-roles.sh` ile önceden yaratılır.
2. Tablolar (4.1, 4.2, 4.4). CHECK kısıtları, UNIQUE'ler, `(tenant_id)` ve `(tenant_id, status, last_seen_at)`
   indeksleri, outbox için `(status, not_before)` kısmi indeksi.
3. Her tabloda `ENABLE` + `FORCE ROW LEVEL SECURITY`; politikalar `TENANT_EXPR` ve `USER_EXPR`
   (`migrations/versions/0001_initial.py:19-20`); rol başına adlandırılmış politika.
4. Tetikleyiciler: değişmezlik, geçiş doğrulama ve baş satır güncelleme, `alert_evaluations` tek kez kapanma,
   outbox durum makinesi (`pending/held -> sent/failed/suppressed/skipped`, `failed -> pending` yalnız
   `attempts < 6`).
5. `notify_gate` ve `alert_gate` şemaları ve işlevleri; `REVOKE ALL ... FROM PUBLIC`; EXECUTE yalnız worker.
6. Yetkiler (4.3, 4.4). Ek: `GRANT SELECT ON report_data_revisions TO netkar_worker` ve worker için
   `tenant_isolation_worker` SELECT politikası.
7. Yeni tablolar `report_data_revisions` tetikleyici listesine GİRMEZ. Girerse değerlendirmenin kendi yazımı veri
   sürümünü artırır ve bir sonraki değerlendirmeyi tetikler (sonsuz döngü). Test bunu korur.

Downgrade:

- Prod'da `alert_events` ya da `notification_outbox` satırı varsa `NETKAR_ALLOW_ALERT_DATA_LOSS=<satır sayısı>`
  olmadan durur (0021 deseni: `migrations/versions/0021_legal_documents_acceptance.py:41`, `:138`).
- Ters sıra: yetkiler, işlevler, şemalar, tetikleyiciler, tablolar; worker'ın `report_data_revisions` yetkisi geri
  alınır. Rol `netkar_notify_gate` silinmez (provision sahibi).

## 6. Değerlendirme zamanlaması

### 6.1 Tetikler

| Tetik | Nasıl | Not |
|---|---|---|
| Senkron sonrası | `sync.backfill` ve `sync.incremental` görevleri (`app/worker/tasks.py:97-109`) sonuçta `upserted > 0` olan kaynak varsa `alerts.evaluate(account_id)` erteler. `SourceOutcome.upserted` (`app/services/sync/runner.py:63-75`). | Durum `invalid` ya da `credentials_error` ise ertelenmez. |
| Ayar ve maliyet yazımı | API `JobQueue`'ya `enqueue_alert_evaluation` eklenir (bugün yalnız `enqueue_backfill`, `app/worker/queue.py:58-61`). Kâr ayarı PUT ve maliyet içe aktarma sonrasında çağrılır. | Hata olursa yanıt etkilenmez; günlük iş telafi eder. |
| Günlük | Periyodik `alerts.plan_daily`, cron `47 3 * * *` UTC (06:47 İstanbul). Pencere günü kaydığı için veri değişmese de değerlendirme gerekir (iade kohortu `T`'ye bağlı). | Dakika 0/30 değil (`tasks.py:42` ilkesi). |

Kuyruk `alerts`, `queueing_lock=f"alerts-eval:{account_id}"` (bekleyen tek iş), `lock=f"alerts:{account_id}"`
(aynı hesabın değerlendirmeleri sırayla). Senkron kilidinden (`queue.py:26-28`) ayrıdır: değerlendirme senkronu
bekletmez.

### 6.2 İş adımları (idempotent)

1. Hesabın kiracısı `sync_gate` ile çözülür. `tenant_transaction` (`app/db/rls.py:29`) ile RLS kurulur.
2. Ayar sürümü (`load_profit_settings`) ve veri sürümü (`report_data_version`, `app/services/report_cache.py:68-91`)
   motor girdisi okunmadan ÖNCE okunur (aynı dosyadaki gerekçe).
3. `alert_evaluations`'a anahtar ile `INSERT ... ON CONFLICT DO NOTHING`. Satır eklenmediyse iş biter.
4. Motor üç dönemle çalışır: 7 gün, 30 gün (reklam verisi varsa), 92 gün (`period_profit`,
   `app/services/profit_report.py:56-118`, `release_connection=True`). İade kohort sorguları ayrı.
5. Kurallar (bölüm 3) saf fonksiyonla aday olay listesi üretir.
6. Tek işlemde: aday olaylar `dedupe_key` ile UPSERT; artık görülmeyen açık olaylar için `resolved` geçişi;
   `muted_until` geçmiş olanlar için `open` geçişi; bildirim gerekenler için outbox satırları
   (`dedupe_key = sha256(user|channel|event|notify_generation)`, `ON CONFLICT DO NOTHING`); `alert_evaluations`
   kapatılır. Hata olursa hiçbiri yazılmaz; procrastinate yeniden dener ve 3. adım satırı da geri alındığı için iş
   baştan güvenle çalışır.
7. Log: yalnız hesap kimliği, sayaçlar, süre. Barkod, tutar, e-posta yok (G09).

### 6.3 Rapor önbelleği ve veri sürümü ile ilişki

- API'nin `ReportCache`'i süreç içidir (`report_cache.py:15-17`); worker onu paylaşmaz ve kendi hesabını yapar.
  Panel ile worker aynı (veri sürümü, ayar sürümü, dönem) için aynı motor sonucunu üretir (motor deterministik).
- Olay, `data_revision` ve `settings_revision` taşır. Panel kartı güncel sürümden eskiyse "veriler güncellendi,
  yeniden değerlendiriliyor" yazar ve tıklamada `/alerts` dönem görünümüne gider.
- `ad_spend_records` 0012 listesine girer (4.5); alarm tabloları girmez (5. bölüm madde 7).
- CPU: motor hesap başına günde birkaç kez üç dönemle. 300 satıcıda kabul edilebilir tahmin; ölçüm D4'te
  (`alert_evaluations.started_at/finished_at`). Gerekirse `alerts` kuyruğu ayrı işçi süreciyle sınırlanır
  (procrastinate `--queues`, Makefile `:81` bugün `--concurrency 4`).

## 7. Bildirim teslimatı

### 7.1 E-posta (outbox deseni)

- Dağıtıcı periyodik iş `notify.dispatch`, her dakika (`* * * * *` uygun; heartbeat deseni `tasks.py:87-90`).
  `notify_gate.due_outbox` ile `pending` ve `not_before <= now()` satırları alır, her biri için kiracı işlemi açar,
  satırı `FOR UPDATE SKIP LOCKED` ile kilitler, alıcıyı çözer, gönderir, durumu yazar.
- Gönderici mevcut `EmailSender` arayüzüdür (`app/core/email.py:30-33`). Bugün `file`/`memory`. Gerçek arka uç
  (Resend ya da SES) ADR-0008 K12 ve staging planı C13 kararına bağlıdır; bu ADR seçmez. `EmailMessage`'a
  `headers` (ör. `List-Unsubscribe`) alanı eklenmesi D5'tedir.
- Gönderim kapısı: `ALERT_NOTIFICATIONS_ENABLED` (varsayılan `false`). `false` iken dağıtıcı e-postayı yalnız
  `file`/`memory` arka ucuna verir; gerçek arka uç tanımlı olsa bile uyarı e-postası gitmez, satır `suppressed`
  olur ve sayaç artar. `true` yapmak Hasan onayıdır (README "e-posta gönderimi Hasan onayıyla").
- Hata: geçici hata `failed`, üstel bekleme (en çok 6 deneme, `SYNC_RETRY` ile aynı aralıklar, `tasks.py:34`);
  kalıcı hata (adres geçersiz) `failed` ve yeniden deneme yok. Gövde ve adres loglanmaz (`auth.py:96-98` deseni).
- Biçim: düz metin (bugünkü `EmailMessage.body`). Ürün başlıkları Trendyol katalogundan gelir, güvenilmez veridir:
  kontrol karakterleri temizlenir, 80 karaktere kesilir. HTML eklenirse kaçışlı şablon zorunlu.

### 7.2 Web push

- Standartlar: Push API, VAPID (RFC 8292), yük şifreleme `aes128gcm` (RFC 8291), `TTL`, `Urgency`, `Topic`
  başlıkları (RFC 8030). `Topic` = kural adı: teslim edilmemiş eski bildirim yenisiyle değişir (gürültü azaltma).
- Servis çalışanı: yok (`docs/60_tasarim_sistemi.md` §7). Eklenecek SW yalnız `push`, `notificationclick` ve
  `pushsubscriptionchange` dinler; `fetch` dinleyicisi YOKTUR, hiçbir yanıt önbelleğe alınmaz (§7 kuralları).
  CSP `worker-src 'self'` zaten var (`apps/web/src/lib/csp.ts:26`). `notificationclick` yalnız aynı kökenli ve izin
  listesindeki yollara (`/panel/uyarilar...`) gider; yükteki tam URL kullanılmaz.
- iOS/iPadOS: web push yalnız ana ekrana eklenmiş PWA'da çalışır (iOS 16.4+). Ayar ekranı bunu yazar.
- Abonelik saklama: `push_subscriptions` (4.4). Uç nokta, `p256dh`, `auth` ADR-0004 zarf şifrelemesiyle saklanır
  (cihaz tanımlayıcısıdır, kişisel veri). Uç nokta ana bilgisayarı izin listesine karşı denetlenir (SSRF,
  API7:2023): öneri listesi `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `*.push.apple.com`,
  `*.notify.windows.com` (liste Doğrulanmadı; tarayıcı belgelerinden teyit edilecek). Yalnız `https`, port 443.
- 404 ve 410 yanıtında abonelik `revoked_at` alır. 180 gün başarısız abonelik iptal.
- Anahtar yönetimi: VAPID özel anahtarı (P-256) sırdır: `WEB_PUSH_VAPID_PRIVATE_KEY` ortam değişkeni, `.env` ve
  parola yöneticisinde (staging planı `:200`), repoda yok (gitleaks, G13), DB'de yok, log'da yok. Genel anahtar
  `GET /v1/push/vapid-public-key` ile verilir. Her aboneliğe `vapid_key_id` yazılır. Döndürme: yeni anahtar
  yayınlanır, panel açılışında istemci kayıtlı `vapid_key_id` farklıysa yeniden abone olur; eski abonelikler 30 gün
  sonra iptal. VAPID `sub` iletişim adresi `mailto:` ya da site URL'si (Hasan kararı H5 ile).
- Kapı: `WEB_PUSH_ENABLED` (varsayılan `false`). Kapalıyken abonelik kaydı çalışır, gönderim yapılmaz, satır
  `suppressed`.
- Kütüphane: Python tarafında web push imzalama ve şifreleme için bir bağımlılık gerekir (ör. `pywebpush`); seçim
  D8'de `pip-audit` ve bakım durumu denetimiyle yapılır.

### 7.3 Sıklık sınırı, sessiz saatler, günlük özet

| Kural | Varsayılan | Yer |
|---|---|---|
| Kullanıcı ve kanal başına anlık bildirim | E-posta 4/gün, push 6/gün; aynı kanalda iki anlık arası en az 30 dk | Dağıtıcı, outbox sayımı |
| Fazla bildirim | Silinmez; `held` olur ve sonraki özete katlanır | Dağıtıcı |
| Aynı olay | Bölüm 3'teki bastırma (zarar 2 kat, reklam ve iade 14 gün, kesinti bir kez) | Değerlendirme |
| Tek değerlendirmede birden çok olay | Kanal başına tek ileti (kural başına sayı ve toplam) | Değerlendirme |
| Sessiz saatler | 22:00-08:00 Europe/Istanbul; bu aralıktaki anlık bildirimler `not_before = bitiş` ile `held` ve bitişte tek iletide birleşir | Değerlendirme + dağıtıcı |
| Günlük özet | Varsayılan saat 08 (İstanbul); periyodik `notify.build_digests`, cron `13 * * * *` UTC: saati gelen kullanıcılar için açık ve son 24 saatte yeni olayların özeti. Yeni olay yoksa ileti yok | Worker |
| Genel kesme | `ALERT_NOTIFICATIONS_ENABLED=false` tüm uyarı e-postalarını, `WEB_PUSH_ENABLED=false` tüm push'ları durdurur | Config |

Saat dilimi `zoneinfo("Europe/Istanbul")` ile hesaplanır (motor sipariş gününü UTC+3 sabit alır, docs/12 K16;
bildirim tarafı da aynı sonucu verir, sabit ofset kodu yazılmaz).

### 7.4 İçerik

| Öğe | E-posta | Push |
|---|---|---|
| Kural adı ve sayı | Evet ("3 üründe zararına satış") | Evet |
| Ürün adı/barkod | En çok 3, kısaltılmış | Hayır |
| Tutar | Tercih `show_amounts_email` (varsayılan açık, H3) | Tercih `show_amounts_push` (varsayılan kapalı: kilit ekranı) |
| Sipariş numarası | Hayır | Hayır |
| Son müşteri verisi (ad, adres, il, müşteri anahtarı) | Hayır (motor girdisinde de yok, `report_cache.py:12-13`) | Hayır |
| Bağlantı | Yalnız `web_base_url` + sabit yol + olay kimliği (`_web_link` deseni, `auth.py:82-85`); token yok | Aynı; SW izin listesi |
| Ayar sürümü damgası | Evet (K44) | Hayır |
| Tercih bağlantısı | Ayarlar sayfası + tek tık kapatma bağlantısı (7.5) | Yok |
| Tanıtım içeriği | Yok (bölüm 9) | Yok |

### 7.5 Tek tık kapatma

`POST /v1/notifications/unsubscribe` (RFC 8058 `List-Unsubscribe-Post` uyumlu) ve onay sayfası. Token:
`HMAC(master_key, "notify-unsub", user|tenant|rule|channel|exp)`, 90 gün geçerli, yalnız ilgili tercihi `off`
yapar, oturum gerektirmez, IP başına hız sınırı. Token başka hiçbir işlem yapamaz.

## 8. Tercihler, API ve panel

### 8.1 Varsayılan matris (kullanıcı başına, kiracı içinde)

| Kural | Uygulama içi | E-posta | Push |
|---|---|---|---|
| ZARARINA_SATIS | her zaman | günlük özet | anında |
| BEKLENMEYEN_KESINTI | her zaman | günlük özet | anında |
| REKLAM_KARI_YIYOR | her zaman | günlük özet | kapalı |
| IADE_ORANI_ARTISI | her zaman | günlük özet | kapalı |

- Push yalnız kullanıcı bir cihazda abone olunca etkilidir (tarayıcı izni).
- `viewer` rolü için e-posta varsayılanı `off` (H2). Owner ve admin için tablo geçerlidir.
- Uygulama içi kapatılamaz (panel kaynağıdır); kural hesap düzeyinde `rules_enabled` ile kapatılabilir (owner/admin).

### 8.2 API uçları (taslak)

| Uç | Rol | Not |
|---|---|---|
| `GET /v1/marketplace-accounts/{account_id}/alert-events?status=&rule=&limit=&cursor=` | tümü | Mühürlü imleç (`profit.py` `_codec` deseni). Yanıt `data_revision`, `settings_revision`. |
| `POST /v1/marketplace-accounts/{account_id}/alert-events/{event_id}/transitions` gövde `{to: read|open|muted, muted_days?}` | read/open: tümü; muted ve muted->open: owner/admin | Geçiş tablosuna INSERT; RLS + tetikleyici. Başka hesabın olayı 404 (G01). |
| `POST /v1/marketplace-accounts/{account_id}/alert-events/read-all` | tümü | Açık olayların hepsine `read` geçişi, en çok 500. |
| `GET`, `PUT /v1/marketplace-accounts/{account_id}/alert-settings` | GET tümü, PUT owner/admin (doğrulanmış e-posta) | Pydantic sınırları (bölüm 3); `audit_log` kaydı. |
| `GET`, `PUT /v1/me/notification-preferences` | oturumdaki kullanıcı | Matris + sessiz saat + özet saati + tutar tercihleri. |
| `GET /v1/push/vapid-public-key` | oturum | Genel anahtar ve `key_id`. |
| `POST /v1/me/push-subscriptions` | oturum | Gövde: `endpoint`, `keys.p256dh`, `keys.auth`. Boyut sınırı, ana bilgisayar izin listesi, kullanıcı başına en çok 10 etkin abonelik. |
| `GET /v1/me/push-subscriptions` | oturum | Maskeli: ana bilgisayar, oluşturma, son başarı. |
| `DELETE /v1/me/push-subscriptions/{id}` | oturum | `revoked_at`. |
| `POST /v1/me/notifications/test` | oturum | Kanal başına saatte 3; bayrak kapalıyken `suppressed` döner. |
| `POST /v1/notifications/unsubscribe` | oturumsuz, token | 7.5. |

Mevcut `/alerts` ucu kalır (dönem dökümü). `not_yet_available` yalnız gerçekten veri yokken döner: reklam kaydı
olan hesapta `REKLAM_KARI_YIYOR` listeden çıkar; `IADE_ORANI_ARTISI` dönemlik değil, olay listesinde görünür ve
`not_yet_available` metni "Uyarılar > Yeni sekmesinde" olarak güncellenir (D10).

### 8.3 Panel ekranı (mobil öncelikli, 390 px)

**Uyarılar (`apps/web/src/app/(app)/panel/uyarilar/page.tsx`)**

```
[ Yeni (3) | Tümü | Dönem dökümü ]          <- sekmeler, 44 px
-------------------------------------------
(!) Zararına satış            2 saat önce
    3 ürün son 7 günde zararda. Toplam 412,30 TL.
    Tahmini kargo içeriyor.
    [ Ürünleri gör ]              [ ... ]    <- menü: Okundu, 7/30 gün sustur
-------------------------------------------
(!) Beklenmeyen kesinti        dün 18:07
    12 satırda fark, toplam 184,20 TL.
    [ Siparişleri gör ]           [ ... ]
-------------------------------------------
(i) İade oranı artışı          3 gün önce
    Ürün X: %4,1 -> %11,3 (son 28 gün, 21 günlük iade penceresi).
    [ Ürünü gör ]                 [ ... ]
```

- "Dönem dökümü" bugünkü `alerts-view.tsx` içeriğidir (değişmez).
- Renk tek başına anlam taşımaz: ikon + metin (docs/60 §5). Tutarlar `num` sınıfı.
- Görüntüleyici rolünde susturma eylemi gizli, yerine "Hesap yöneticiniz susturabilir." (`VIEWER_NOTE` deseni,
  `alerts.ts:32`).
- Boş durum: "Yeni uyarı yok. Son değerlendirme: bugün 06:47."

**Ayarlar > Bildirimler (yeni: `apps/web/src/app/(app)/panel/ayarlar/bildirimler/page.tsx`)**

```
Kanallar
  E-posta   h***@ornek.com  (doğrulandı)
  Bu cihaz  [ Bildirimleri aç ]   (iOS: önce ana ekrana ekleyin)
Kurallar                       E-posta        Push
  Zararına satış          [Özet v]       [Anında v]
  Beklenmeyen kesinti     [Özet v]       [Anında v]
  Reklam kârı yiyor       [Özet v]       [Kapalı v]
  İade oranı artışı       [Özet v]       [Kapalı v]
Zamanlama
  Sessiz saatler  22:00 - 08:00 (İstanbul)
  Günlük özet     08:00
Gizlilik
  [x] E-postada tutar göster
  [ ] Bildirimde tutar göster (kilit ekranında görünür)
Eşikler (hesap, yalnız sahip/yönetici)
  Zarar bildirimi alt sınırı      5,00 TL
  Reklam payı eşiği               %100
  Reklam en az harcama            50,00 TL
  Kesinti bildirimi alt sınırı    10,00 TL
  İade oranı en az fark           5 puan
[ Test bildirimi gönder ]
```

390 px'te kural satırı iki satıra kırılır (kanal seçicileri alt satırda). Seçiciler yerel `<select>`; 44 px hedef.

## 9. KVKK ve İYS

| Konu | Değerlendirme | Güven |
|---|---|---|
| Uyarı e-postası ticari ileti mi | Hayır kanaati: satıcının kendi verisi hakkında, hizmetin parçası olan bilgilendirme. research/03 §4 satır 222 aynı yönde ("kâr uyarısı ticari ileti değildir"), güveni Orta, "teyit edilmeli". | Orta, **avukat teyidi** |
| İYS kaydı | İşlemsel iletide gerekmez kanaati. Koşul: iletide tanıtım, plan yükseltme çağrısı, kampanya yok. Pazarlama iletileri ayrı akış ve ayrı gönderen adresinden, İYS kontrolüyle (research/03 satır 220-221). | Orta, **avukat teyidi** |
| Ayırma | `notification_outbox.kind` yalnız `instant`, `digest`, `test`. Pazarlama bu tabloya giremez (CHECK). Gönderen adı ve adresi işlemsel (ör. `bildirim@`), pazarlama adresinden ayrı (H5). | Tasarım |
| Hukuki sebep | Alıcı e-postası ve push aboneliği: sözleşmenin ifası (KVKK m.5/2-c) kanaati; aydınlatma metnine "uyarı bildirimleri" amacı ve push aboneliği (cihaz tanımlayıcısı) eklenir. | Orta, avukat teyidi |
| Son müşteri verisi | Bildirim içeriğinde yok; olay yükü izin listeli (4.1). Sipariş numarası da iletiye girmez. | Yüksek (tasarım) |
| Satıcının finansal verisi | Şahıs şirketi sahibinde ticari bilgi gerçek kişiye ilişkin veri sayılabilir. E-posta sağlayıcısı yurt dışındaysa KVKK m.9 aktarımı (research/03 satır 29; staging planı satır 223, 227). Tutar tercihi bu yüzden kullanıcıdadır. | Orta |
| Push yükü | RFC 8291 ile uçtan uca şifreli; push servisi içeriği okuyamaz, meta veriyi (zaman, boyut, uç nokta) görür. Risk kilit ekranıdır: push tutar varsayılanı kapalı. | Yüksek (standart) |
| Saklama | Outbox 30 gün, olay 13 ay (çözülmüş), push aboneliği iptal anında silinir (DELETE değil: şifreli alanlar NULL'lanır, satır 30 gün sonra temizlenir). Süreler avukat teyidine bağlı (H13). | Öneri |

## 10. Güvenlik

### 10.1 Tehdit modeli (kısa)

| Tehdit | Senaryo | Etki | Azaltım |
|---|---|---|---|
| Push aboneliği ele geçirme | DB sızıntısı ya da log ile uç nokta ve anahtarlar çalınır | Saldırgan, VAPID özel anahtarı yoksa abonelik bizim genel anahtarımıza bağlı olduğu için ileti gönderemez (servislerin VAPID zorlaması tarayıcıya göre Doğrulanmadı) | Alanlar zarf şifreli (ADR-0004); VAPID özel anahtarı DB dışında sır; log'da uç nokta yok |
| VAPID özel anahtarı sızıntısı | `.env` ele geçirilir | Tüm abonelere sahte bildirim (oltalama) | Sır yönetimi, döndürme prosedürü (7.2), SW yalnız izinli yolu açar |
| Paylaşılan cihaz | Kullanıcı çıkış yapar, push gelmeye devam eder | Sonraki kişi uyarı başlığını görür | Çıkışta istemci aboneliği siler; sunucu `created_session_id` ile açık çıkış ve "diğer oturumları kapat" ile aboneliği iptal eder (oturum süresinin dolması iptal etmez, H11); tutar varsayılan kapalı |
| E-posta içerik sızıntısı | Yanlış alıcı, eski üye, yönlendirme, sağlayıcı | Ticari bilgi ifşası | Alıcı gönderim anında çözülür, üyelik ve doğrulanmış e-posta şartı; asgari içerik; sipariş no yok; TLS |
| Bildirim yoluyla oltalama | Saldırgan "NetTablo uyarısı" taklidi gönderir | Kimlik bilgisi çalma | SPF, DKIM, DMARC `p=reject` (alan adı kurulumu, Hasan); uyarı e-postasında giriş bağlantısı ve token yok; sabit metin "Bu e-posta parola istemez"; bağlantılar tek kökene |
| SSRF | Kötü niyetli abonelik uç noktası iç ağa işaret eder | Worker'dan iç ağa istek | Ana bilgisayar izin listesi, yalnız https/443, yönlendirme izlenmez, DNS sonrası özel IP reddi |
| IDOR / BOLA | Başka kiracının olayını okuma ya da susturma | Veri sızıntısı | RLS + `tenant_id` süzgeci + `require_role` (G01); IDOR testleri |
| Toplu atama | Geçiş gövdesinde `status=resolved` | Sistem durumunu taklit | Şema yalnız izinli değerler; tetikleyici kullanıcı için `resolved` yasak (API3:2023) |
| Bildirim taşkını | Hatalı kural binlerce olay açar | Maliyet, kullanıcı kaybı | Sıklık sınırı, değerlendirme başına tek ileti, genel kesme bayrakları, hesap başına günlük olay tavanı (500) |
| Şablon enjeksiyonu | Ürün başlığında kontrol karakteri ya da HTML | E-posta bozulması, sahte bağlantı | Düz metin, temizleme, kısaltma |
| Kapatma tokenı sahteciliği | Başkasının tercihini kapatma | Bildirim kaybı | Amaca özel HMAC, kapsam ve süre, yalnız `off` yönü |

### 10.2 ASVS 5.0 L2 eşlemesi

`docs/50_guvenlik.md` hedefi ASVS 5.0.0 L2'dir; bölüm adları aşağıdadır, madde numaraları S1 eşleme çalışmasıyla
teyit edilecektir (aynı dosyanın başındaki not). Madde numarası bu ADR'de verilmedi (Doğrulanmadı).

| ASVS 5.0 bölümü | Bu ADR'deki karşılığı |
|---|---|
| V2 Doğrulama ve iş mantığı | Eşik ve tercih sınırları (Pydantic), sıklık sınırı, geçiş durum makinesi |
| V4 API ve web servisi | Mühürlü imleç, RFC 9457 hata biçimi, yalnız izinli alanlar |
| V8 Yetkilendirme | RLS + rol denetimi, olay ve abonelikte nesne düzeyi denetim |
| V11 Kriptografi | VAPID P-256, RFC 8291 şifreleme, zarf şifreleme, HMAC tokenlar |
| V13 Yapılandırma | VAPID özel anahtarı ve bayraklar ortam değişkeninde; prod açılış denetimi |
| V14 Veri koruma | Asgari bildirim içeriği, tutar tercihi, saklama süreleri, SW önbelleği yok |
| V16 Güvenlik günlüğü ve hata yönetimi | Kişisel veri ve sır içermeyen log; geçiş ve ayar değişikliği `audit_log`'da |
| V3 Web ön yüz | SW kapsamı, `notificationclick` köken denetimi, CSP `worker-src 'self'` |

OWASP API Top 10 (2023): API1 (BOLA), API3 (nesne özelliği düzeyi yetki), API4 (kaynak tüketimi), API7 (SSRF).

## 11. Uygulama dilimleri (Sonnet)

Her dilim ayrı PR, kendi testleriyle. Her dilimden sonra Opus güvenlik incelemesi.

| # | Dilim | Dosyalar | Bağımlılık |
|---|---|---|---|
| D1 | Saf kurallar: 4 kural, bastırma kararları, z² kova tablosu, sabitler | `app/alerts/__init__.py`, `app/alerts/rules.py`, `app/alerts/stats.py` (yeni) | yok |
| D2 | Migrasyon 0025: tablolar, RLS, değişmezlik ve geçiş tetikleyicileri, `notify_gate`/`alert_gate`, yetkiler, downgrade koruması; rol provizyonu | `migrations/versions/0025_*.py` (yeni), `app/models/`, `app/db/provision.py`, `infra/postgres/init/01-roles.sh` | yok |
| D3 | İade kohort sorgusu ve besleyici (İstanbul günü, sabit ufuk, iptal hariç) | `app/services/alert_inputs.py` (yeni) | D2 |
| D4 | `alerts.evaluate` işi, senkron sonrası erteleme, `plan_daily`, `JobQueue.enqueue_alert_evaluation`, değerlendirme anahtarı, outbox yazımı | `app/worker/tasks.py`, `app/worker/queue.py`, `app/services/alert_evaluation.py` (yeni), kâr ayarı ve maliyet uçları | D1, D2, D3 |
| D5 | Dağıtıcı: `notify.dispatch`, `notify.build_digests`, sıklık sınırı, sessiz saat, `ALERT_NOTIFICATIONS_ENABLED`, `EmailMessage.headers`, şablonlar, tek tık kapatma ucu | `app/services/notify.py` (yeni), `app/core/email.py`, `app/core/config.py`, `app/worker/tasks.py` | D2, D4 |
| D6 | API: olay listesi, geçişler, toplu okundu, hesap eşikleri, kullanıcı tercihleri | `app/api/v1/alerts.py` (yeni), `app/api/v1/router.py`, şemalar | D2 |
| D7 | Web: Uyarılar sekmeleri ve kartlar; Ayarlar > Bildirimler | `apps/web/src/app/(app)/panel/uyarilar/page.tsx`, `apps/web/src/components/profit/alerts-view.tsx`, yeni `ayarlar/bildirimler` sayfası ve bileşenleri | D6 |
| D8 | Web push: VAPID ayarları, abonelik uçları, izin listesi, gönderici, SW (`push`, `notificationclick`, `pushsubscriptionchange`), `WEB_PUSH_ENABLED` | `app/api/v1/push.py` (yeni), `app/services/push.py` (yeni), `apps/web/public/sw.js` (yeni), kayıt bileşeni | D2, D5, D7 |
| D9 | Reklam verisi: `ad_spend_records` migrasyonu (0012 listesine ekleme dahil), Excel/CSV içe aktarma ve kolon eşleme, elle giriş, besleyicide `ad_records` | yeni migrasyon, `app/services/ad_import.py` (yeni), `app/services/profit_feed.py`, uçlar, web ekranı | Hasan'dan örnek Excel (H8) |
| D10 | `/alerts` `not_yet_available` güncellemesi ve web adları | `app/services/profit_views.py:731-738`, `apps/web/src/lib/profit/alerts.ts:387-390` | D4, D9 |
| D11 | Belgeler: `docs/50_guvenlik.md` kontrol satırı, runbook (VAPID döndürme, kesme bayrakları), aydınlatma metni notu | belgeler | D5, D8 |

## 12. Test listesi

Kurallar (D1):

1. ZARARINA_SATIS: tam iadeli zarar satırı (G16 benzeri) olay açmaz; iadesiz zarar satırı açar; eşik altı toplam
   açmaz; null `net_kar` satırında `eksik_giderler_haric_kar` kullanılır; iptal satır sayılmaz.
2. Zarar 2 katına çıkınca bir kez yeniden bildirim; 1,9 katta yok.
3. REKLAM: `before <= 0` açmaz; `net_kar` null açmaz; `spend < ad_min_spend` açmaz; %100 eşikte `net_kar = 0,00`
   sınırda açar; yalnız `dagitim_tahmini` ile sağlanan koşul olay açar ama bildirim üretmez.
4. BEKLENMEYEN_KESINTI: motor uyarısı olmayan satır açmaz; `default_desi_used` satırı (H10 evet ise) bildirime girmez;
   `deduction_notify_min` altı fark özete girer, anlık değil.
5. İade z testi: elle hesaplanmış 6 vaka (sınırın iki yanı); `nC=29` alarm yok; `xC=4` alarm yok; `p=0` test yok;
   kova sınırları (k=1, 2, 5, 6, 20, 21, 100, 101); `pC >= 1,5 pB` koşulu; sonuçlar `float` ile aynı yönde
   (referans test, kod yolu Decimal).
6. `app/alerts/` altında `float` ve `math` kullanımı yok (AST testi).

Veritabanı ve migrasyon (D2):

7. 0025 upgrade -> downgrade -> upgrade; prod'da satır varken ve bayraksız downgrade durur.
8. Tüm yeni tablolarda ENABLE + FORCE RLS; `test_rls_idor.py` kapsamına eklenir: A kiracısı B'nin olayını,
   tercihini, aboneliğini göremez ve geçiş ekleyemez.
9. Kimlik alanı UPDATE 23514; doğrudan `status` UPDATE 23514; geçiş tablosunda UPDATE/DELETE/TRUNCATE 23514.
10. Geçiş matrisi: kullanıcı `resolved` yapamaz; viewer `muted` yapamaz; `muted_until` > 90 gün reddedilir.
11. `netkar_app` outbox'a erişemez; `notify_gate` işlevlerini çalıştıramaz; `users.email`'i yalnız kendi satırında görür.
12. `notify_gate.email_for`: üye olmayan, doğrulanmamış kullanıcıda NULL; SECURITY DEFINER, sabit `search_path`,
    PUBLIC EXECUTE yok.
13. Alarm tabloları `report_data_revisions` tetikleyicisini tetiklemez (değerlendirme yazımı sürümü artırmaz).
14. `payload`'a yasak anahtar (`email`, `name`, `address`) yazılamaz; 4 KB üstü reddedilir.

Değerlendirme (D3, D4):

15. Aynı anahtarla ikinci çalıştırma hiçbir şey yazmaz; işlem ortasında hata olursa hiçbir olay ve outbox satırı
    kalmaz, yeniden deneme aynı sonucu verir.
16. Senkron `upserted=0` iken iş ertelenmez; `invalid` hesapta ertelenmez; bekleyen iş varken ikinci erteleme
    `AlreadyEnqueued`.
17. Kohort: İstanbul gün sınırı (23:50 / 00:30, G30 deseni); `claim_date > ordered_at + H` sayılmaz; iptal satır
    sayılmaz.
18. Koşul kalkınca `resolved`; yeniden görülünce `open` ve bastırma kuralı.
19. Log çıktısında barkod, tutar, e-posta yok.

Teslimat (D5, D8):

20. Bayrak kapalıyken gerçek arka uç çağrılmaz, satır `suppressed`; `file` arka ucuna yazılır.
21. Sıklık sınırı aşımında `held` ve sonraki özete katlanma; sessiz saatte `not_before` = 08:00 İstanbul.
22. Özet: yeni olay yoksa ileti yok; saat eşleşmesi İstanbul'a göre.
23. E-posta gövdesinde sipariş numarası, müşteri verisi yok; tutar tercihi kapalıyken tutar yok; ürün başlığındaki
    kontrol karakteri temizlenir.
24. Üyelikten çıkarılan kullanıcıya bekleyen ileti gitmez (`skipped`).
25. Push: izin listesi dışı ana bilgisayar 422; http reddi; 410 yanıtında `revoked_at`; açık çıkışta abonelik iptal.
26. Kapatma tokenı: başka kullanıcı ve kural için geçersiz; süresi dolmuş geçersiz; yalnız `off` yapar.

API ve web (D6, D7):

27. IDOR: başka hesabın olay kimliğiyle geçiş 404.
28. Eşik PUT: aralık dışı değer 422; viewer 403; `audit_log` satırı.
29. Web: sekmeler, kart eylemleri, viewer notu; axe-core 390 ve 1280 px, açık ve koyu tema 0 ihlal (docs/60 §5).
30. SW: `notificationclick` dış URL'yi açmaz; `fetch` dinleyicisi yok (statik test).

## 13. Hasan kararı gereken noktalar

| # | Karar | Öneri |
|---|---|---|
| H1 | Okundu durumu kiracı düzeyinde mi kullanıcı düzeyinde mi? | Kiracı düzeyi (küçük ekipler); ajans planında kullanıcı düzeyi yeniden değerlendirilir. |
| H2 | Varsayılan kanal matrisi ve viewer e-postası | 8.1 tablosu; viewer için e-posta kapalı. |
| H3 | Tutar gösterimi varsayılanları | E-posta açık, push kapalı. |
| H4 | Sessiz saatler ve özet saati | 22:00-08:00, özet 08:00 İstanbul. |
| H5 | Gerçek e-posta sağlayıcısı ve gönderen adresi (ADR-0008 K12, staging C13); VAPID `sub` adresi | Resend (maliyet modeli varsayımı) + işlemsel alt alan adı; KVKK m.9 sözleşme yolu avukatla. |
| H6 | `ALERT_NOTIFICATIONS_ENABLED` ve `WEB_PUSH_ENABLED` ne zaman açılır | Staging'de `file` ile; prod'da beta satıcının yazılı onayı ve H5 sonrası. |
| H7 | İYS ve işlemsel ileti ayrımı | Avukat teyidi alınana dek yalnız beta satıcıya ve Hasan'a gönderim. |
| H8 | Reklam Excel örneği (docs/12 §9 madde 13) | Hasan panelden bir örnek indirir; D9 buna göre kolon eşlemesi yapar. |
| H9 | Eşik varsayılanları | Zarar 5,00 TL; reklam %100 ve 50,00 TL; kesinti bildirimi 10,00 TL; iade 5 puan; α 0,01 Bonferroni; `H` 21 gün. İlk 4 hafta pilot verisiyle gözden geçirme. |
| H10 | Varsayılan desiyle tahmin edilen kargodan doğan kesinti bildirime girsin mi? | Hayır; panelde görünür. |
| H11 | Push aboneliği oturum bitince silinsin mi? | Yalnız açık çıkış, "diğer oturumları kapat" ve parola sıfırlamada; süre dolumunda değil. |
| H12 | Push ve uyarılar plan özelliği mi? (research/05 satır 342: push Pro'da) | Beta'da herkese açık; plan kuralı S8'de. |
| H13 | Saklama süreleri | Çözülmüş olay 13 ay, outbox 30 gün, iptal edilmiş abonelik 30 gün; avukat teyidi. |

## 14. Sonuçlar ve kalan riskler

- Kâr motoru değişmez; altın testler ve %100 kapsam korunur. Kurallar ayrı modülde test edilir.
- REKLAM_KARI_YIYOR veri dilimi (D9) gelmeden çalışmaz. Reklam Excel'inin yapısı, KDV durumu ve atıf penceresi
  Doğrulanmadı; ilk sürümde reklam uyarısı "tahmini" kabul edilmelidir.
- İade kuralı "Accepted" dışındaki statüleri saymaz; iade süresi `H` ve statü kümesi pilot veriyle ayarlanır
  (Doğrulanmadı). Sinyal en erken sipariş gününden 21 gün sonra gelir.
- Gerçek e-posta sağlayıcısı (K12) olmadan prod'da uyarı e-postası yoktur; panel olayları çalışır.
- Push teslimi tarayıcı ve işletim sistemi politikalarına bağlıdır (iOS yalnız PWA); push servis ana bilgisayar
  listesi ve servislerin VAPID zorlaması Doğrulanmadı.
- İYS ve ticari ileti değerlendirmesi kanaattir; avukat teyidi olmadan pazarlama içeriği uyarı iletisine
  eklenmez.
- Worker'a `report_data_revisions` okuma ve `notify_gate` üzerinden e-posta okuma yetkisi verilir; bu, ADR-0005 §6
  worker rolünün kapsamını genişletir ve S6 güvenlik incelemesinde ayrıca bakılmalıdır.
- Bu ADR kodu okuyarak yazıldı; satır numaraları belirtilen dal içindir.
