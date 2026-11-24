# NetKâr Güvenlik ve Alan Denetimi: Kâr ayarları ve motor K33-K41 (9 Kasım 2026)

- Denetlenen sürüm: dal `claude/dazzling-clarke-pfvf32`, commit `58aabb2` ("NetKâr: kâr ayarları ve motor K33-K41 (ADR-0006, S4 Y-02)"). Satır numaraları bu commit'e göredir.
- İki şapka: (1) uygulama güvenliği (OWASP ASVS 5.0.0 Seviye 2, OWASP API Security Top 10 2023, `docs/50_guvenlik.md` merge engeli kontrolleri G01, G06, G07, G08, G09); (2) kâr motoru alan uzmanlığı (`docs/12_kar_motoru.md` §7, §8, §11, §12 K33-K41; `docs/adr/0006-kar-ayarlari.md`).
- Kapsamdaki kod: `app/profit/{settings,shipping,fees,costs,settlement,lines,aggregate,results,enums,work,schema_v1}.py`, `migrations/versions/0007_profit_settings.py`, `app/models/profit_settings.py`, `app/services/profit_settings.py`, `app/api/v1/profit_settings.py`, `app/api/v1/profit_settings_schemas.py`, `app/api/v1/profit.py`, `app/api/v1/profit_schemas.py`, `app/services/profit_views.py`, `app/core/config.py`; testler `tests/test_profit_settings*.py`, `tests/test_profit_properties.py`, `tests/test_report_*.py`, `tests/test_feed_golden_database.py`, `tests/test_golden_script_guard.py`, `tests/test_denetim_s4_kapanis.py`, `tests/golden/G01-G48`; referans betik `calisma_dosyalari/altin_test_hesap_ayarlar.py`. Bağlam için okunanlar: `app/main.py` (gövde ve IP sınırları), `app/core/limits.py`, `app/api/deps.py`, `app/services/product_costs.py` (`account_exists`, `check_valid_from`), `app/services/audit.py`, `app/profit/money.py`.
- Önce okunan belgeler: `docs/adr/0006-kar-ayarlari.md`, `docs/12_kar_motoru.md` (§7, §8, §11, §12), `docs/50_guvenlik.md`, önceki denetim `docs/security/denetim_2026-11-09_S4_rapor.md` (biçim ve açık bulgular).
- Denetçi kodu yazmadı; kod ve test dosyaları değiştirilmedi, commit yapılmadı. Kavram kanıtı (PoC) testleri repo dışında, oturumun geçici dizininde repo `conftest`'i eklenti olarak yüklenerek gerçek PostgreSQL ile çalıştırıldı; özü Ek A'dadır.

## 0. Yöntem ve test sonuçları

| Adım | Sonuç |
|---|---|
| Kod incelemesi (migrasyon, RLS, model, servis, 10 ayar ucu, şemalar, rapor değişiklikleri, motor K33-K41) | Tamamlandı |
| Ayar ve rapor testleri (`test_profit_settings_api.py`, `test_profit_settings_schema.py`, `test_profit_settings.py`, `test_report_api.py`), gerçek PostgreSQL | 274 geçti |
| Tüm API test paketi (`uv run pytest -q`) | 1780 geçti, 6 atlandı (reklam, bilinçli), 0 kaldı (Ek B) |
| Referans betik (`python3 calisma_dosyalari/altin_test_hesap_ayarlar.py`) | "TAMAM: tüm kontroller geçti", 48 senaryo, 139 elle kontrol edilen değer |
| PoC (`test_poc_ayarlar.py`, 16 test) | 16/16 geçti (`test_poc_*` geçmesi gözlemin varlığını, `test_ok_*` geçmesi bulgu olmadığını gösterir) |
| PoC: hizmet bedeli sürüm sayısı (`test_poc_ayarlar_fee.py`) | 5.000 sipariş, 30 gün: `summary` 1,62 sn (210 sürüm) -> 76,17 sn (10.173 sürüm) |
| Ölçüm: `carriers` ucu, 30.000 satır, 92 gün (`test_poc_ayarlar_perf.py`) | Tek istek 33-83 ms; 20 eşzamanlı istek 0,29 sn; plan indeksli |
| S4 Y-02 ölçümünün tekrarı: G01-G41 `ProfitSettings()` ile (`ayar_defaults.py`) | 57 aktif satırın 53'ü eksik kalemli; eksik kalemli satırda sayı net kâr 0; yanlış `BEKLENMEYEN_KESINTI` 0 (S4'te 21 senaryo); kısmi dönemde marj 0 |
| Motor seçim kuralları noktasal denetimi (`k34_check.py`, `default_desi_k23.py`, `lookup_bench.py`, `fee_bench.py`) | K34/K35 seçim sırası belgeyle aynı; AD-05 ve AO-01 gözlemleri |
| S4 ilk turunun alan PoC'leri (`test_poc_s4.py`) yeniden | O-02 PoC'si artık başarısız (kapandı); diğerlerinin iddiası yeni alanlarla anlamını yitirdi (bkz. §4) |

## 1. Özet tablo (ciddiyete göre)

| No | Ciddiyet | Başlık | Konum | Eşleme | Kanıt |
|---|---|---|---|---|---|
| AO-01 | Orta | Hizmet bedeli tahmini sürüm sayısı sınırsız ve motor her siparişte tüm sürümleri baştan sıralıyor: yönetici rolüyle kalıcı rapor maliyeti çarpanı (47 kat), süreç rapor yuvalarını tutar (S4 YO-01'i büyütür) | `app/services/profit_settings.py:525-562`; `app/profit/settings.py:30-37, 145-147`; `app/profit/fees.py:109` | API4:2023; ASVS 15.2.2; G07 | PoC + ölçüm |
| AO-02 | Orta (alan, bütünlük) | Geçmiş dönem raporu iz bırakmadan yeniden yazılabiliyor: aynı anahtarlı PUT yerinde günceller, DELETE kalıcı siler, geriye tarihli yeni sürüm kapanmış dönemi değiştirir; denetim izinde önceki değer ve silinen sürümün kimliği yok | `app/services/profit_settings.py:486-492, 544-550, 610-626, 643-656`; `app/api/v1/profit_settings.py:499-528` | ASVS 16.2.1 (denetim kaydında "ne değişti"); K33 gerekçesi | PoC |
| AO-03 | Orta (alan, belge) | Kısmi dönemde `donem_net_kar` sayı olarak kalıyor (tam satır alt kümesi eksi TÜM dönem giderleri); ayarsız hesapta 0,00; dönem düzeyinde "eksik giderler hariç kâr" yok. ADR §2.1'in satır için reddettiği "bayraklı kısmi sayı" kalıbı dönem düzeyinde sürüyor | `app/profit/aggregate.py:165, 175, 213`; `app/api/v1/profit_schemas.py` (`PeriodTotalsOut`); docs/12 K39 | Alan doğruluğu (K37 gerekçesi, K39) | PoC |
| AD-01 | Düşük | Çok büyük JSON sayısı (`1e30`, 31 haneli tamsayı) `decimal.InvalidOperation` ile 500 veriyor; 5 alanda; hız sınırına sayılmıyor | `app/api/v1/profit_settings_schemas.py:38-50`; `app/services/profit_settings.py:109-110, 155-165` | G06, G08; ASVS 1.4/2.2 | PoC |
| AD-02 | Düşük | Okuma uçlarında (`GET /profit-settings`, `GET /profit-settings/carriers`) hiç hız sınırı yok; görüntüleyici dahil sınırsız; `carriers` her istekte 92 günlük birleştirme sorgusu | `app/api/v1/profit_settings.py:186-219` | API4:2023; G07 | PoC + ölçüm |
| AD-03 | Düşük | Migrasyon 0007 geri alınırken kullanıcı beyanı veri (tarife, hizmet bedeli, gider) korumasız düşürülüyor; 0006'dan farkı: bu veri Trendyol'dan yeniden çekilemez | `migrations/versions/0007_profit_settings.py:151-165` | ISO 27001 A.8.13; değişiklik yönetimi | Kod |
| AD-04 | Düşük (alan) | Ürün listesinde `sort=net_profit` ayarsız hesapta anlamsız: tüm değerler null, sıra barkoda düşer; kesin zararlı ürünler (`loss_reason=known_expenses`) `asc` sıralamada sona gider; eksik giderler hariç kâra göre sıralama yok | `app/services/profit_views.py:300-316` | Alan (K37), UX | PoC |
| AD-05 | Düşük (alan) | Varsayılan desiyle hesaplanan kargo tahmini K23 karşılaştırmasına giriyor; fatura gelince `KARGO_DESI_VARSAYILAN` uyarısı kalkıyor, satır yalnız `BEKLENMEYEN_KESINTI` gösteriyor (fark varsayımdan doğuyor) | `app/profit/shipping.py:100-127`; `app/profit/lines.py:65-67` | Alan (K23, K34, K38) | PoC (motor) |
| AB-01 | Bilgi (alan) | `completeness` ve `settings_configured` "bugün" bayrağıdır, raporlanan dönemi anlatmaz: bugün başlayan tarife ile `settings_configured=true` iken dönemin 3 satırında kargo hâlâ eksik | `app/services/profit_settings.py:339-350`; `app/api/v1/profit.py:222-232` | Alan, UX | PoC |
| AB-02 | Bilgi | `summary`'de motorun kullandığı ayar ile yanıttaki `completeness` ayrı okumalarla alınıyor; arada yazım olursa tutarsız | `app/api/v1/profit.py:164, 222-225` | Tutarlılık | Kod (doğrulanmadı) |
| AB-03 | Bilgi | `expected_revision` isteğe bağlı: gönderilmezse son yazan kazanır (ADR'ye uygun) | `app/services/profit_settings.py:451-453` | Eşzamanlılık | Kod |
| AB-04 | Bilgi | `carriers` ucu siparişte firma yoksa `carrier: ""` döndürüyor; bu adla tarife yazılamaz (422) | `app/services/profit_settings.py:410` | UX | Kod |
| AB-05 | Bilgi | Tarife sürüm seçimi her pakette baştan sıralanıyor: 200 sürüm x 30.000 paket +0,8 sn | `app/profit/settings.py:101-117` | API4 (küçük) | Ölçüm |
| AB-06 | Bilgi (alan) | Firma adı eşleşmesi birebir; Unicode normalizasyonu yok, iç NBSP kabul ediliyor (sıfır genişlik ve bidi reddediliyor: olumlu) | `app/services/profit_settings.py:89-106` | Alan (K34) | PoC |
| AB-07 | Bilgi (alan) | Tüm kullanıcı ayarları 0 girilerek (tarife `*` 0, hizmet bedeli 0) eksik kalem uyarıları susturulabilir; net kâr sayı olur, kesinlik `tahmini` kalır | K33 "bilerek 0" kuralı | Alan, UX | Kod (repo testi bu yolu kullanıyor) |
| AB-08 | Bilgi (test) | Altın senaryolar API yolunda ayarları KDV HARİÇ yazıyor; KDV dahil girişin DB -> motor dönüşümü yalnız birim testte | `tests/test_feed_golden_database.py` (`add_user_settings`) | Test kapsamı | Kod |

Sayım: Kritik 0, Yüksek 0, Orta 3, Düşük 5, Bilgi 8 (toplam 16). Orta bulguların ikisi (AO-02, AO-03) alan doğruluğu/bütünlük bulgusudur; AO-01 güvenlik (kaynak tüketimi) bulgusudur.

## 2. Ayrıntılar

### AO-01 (Orta) Hizmet bedeli sürüm sayısı sınırsız; motor maliyeti sürüm sayısıyla çarpılıyor

**Konum:** `app/services/profit_settings.py:525-562` (`upsert_service_fee`: tarifedeki `MAX_TARIFF_VERSIONS` (63, 493-508) benzeri sayım YOK), `app/profit/settings.py:30-37` (`pick_version` her çağrıda uygun sürümlerin listesini kurup SIRALAR), `145-147` (`service_fee_estimate_on`), `app/profit/fees.py:109` (her sipariş için bir çağrı), `app/services/profit_settings.py:226-277` (`load_bundle` tüm sürümleri her raporda okur).

**Açıklama:** ADR-0006 §3.2 hesap başına 200 tarife sürümü ve 50 değişken gider sınırı koyar, hizmet bedeli sürümü için sınır koymaz; kod da koymaz. `valid_from` 2000-01-01 ile bugün+366 arasında ve hesap başına tekil olduğundan bir hesap yaklaşık 10.200 sürüm tutabilir. Motor her siparişte tüm sürümleri süzüp sıraladığı için maliyet `sipariş x sürüm x log(sürüm)` olur. Ölçüm (Ek A.1):

| Durum | Sonuç |
|---|---|
| API ile 210 sürüm yazımı (200 sınırının üstü) | 210 x 200, ret yok |
| `seed_large` (5.000 sipariş, 30 gün), 210 sürüm | `summary` 1,62 sn |
| Aynı veri, 10.173 sürüm | `summary` 76,17 sn (47 kat) |
| Mikro ölçüm, yalnız `service_fee_estimate_on` | 10.175 sürüm: 1.000 siparişte 3,24 sn, 5.000 siparişte 16,89 sn |

**Senaryo:** Kötü niyetli (ya da ele geçirilmiş) bir owner/admin, yazma sınırı (kiracı başına saatte 600) içinde yaklaşık 17 saatte her güne bir hizmet bedeli sürümü yazar. Bundan sonra o hesabın HER rapor isteği (görüntüleyici dahil) dakikalar sürer. Motor iş parçacığında GIL'i tutar ve S4 rapor kapısının yuvasını (kiracı başına 2, süreç başına 4) bu süre boyunca tutar: iki böyle kiracı süreçteki tüm rapor yuvalarını sürekli doldurur, diğer kiracılar 503 `report-busy` alır (S4 YO-01'in büyük veri gerektirmeyen biçimi). Kazara da olabilir: içe aktarma veya betikle günlük tahmin yazan bir entegrasyon.

**Düzeltme önerisi:**
1. `upsert_service_fee`'ye yeni sürüm eklerken hesap başına sayım (örn. `MAX_SERVICE_FEE_VERSIONS = 200`) ve `LimitError("valid_from", "too_many_fee_versions", ...)`; `begin_write` kilidi altında olduğu için yarış yok. ADR-0006 §3.2 ve docs/12 K33 tablosuna satır eklenmeli.
2. Motor: `ProfitSettings` kurulurken sürümler bir kez sıralansın (`to_profit_settings` zaten `valid_from` sırasıyla okuyor) ve `pick_version` `bisect` ile O(log n) seçsin; ya da gün başına önbellek (siparişler aynı günde yoğunlaşır). Aynı düzeltme tarifeyi de kapsar (AB-05).
3. `GET /profit-settings` yanıtı da sürüm sayısıyla büyür; sınır bunu da kapatır.

**Test önerisi:** 201. hizmet bedeli sürümü 422 `too_many_fee_versions`; motor birim testi: 10.000 sürüm ve 5.000 siparişte `calculate_profit` süresi 1 sürümlü durumun en çok 1,5 katı (ya da `pick_version` çağrı başına sıralama yapmıyor, sayaçla).

### AO-02 (Orta, alan ve bütünlük) Geçmiş dönem raporu iz bırakmadan değiştirilebiliyor

**Konum:** `app/services/profit_settings.py:486-492` (aynı (anlaşma, firma, başlangıç) anahtarlı PUT kademeleri yerinde ezer), `544-550` (hizmet bedeli aynı), `610-626` (değişken gider yerinde güncelleme), `643-656` (`delete_version`: kalıcı DELETE), `app/api/v1/profit_settings.py:254-268` ve `499-528` (denetim kaydı).

**Açıklama:** K33'ün sürümleme gerekçesi "ayar değişikliği geçmiş dönem raporunu değiştirmemeli"dir. Uygulama bunu yalnız "yeni başlangıç tarihli sürüm eklenirse" sağlar. Üç yol geçmişi yeniden yazar ve hiçbiri geri izlenemez:

1. Aynı anahtarla PUT: PoC (Ek A.2) 1001 siparişinin Ekim kargosu 45,00 -> 100,00 oldu; önceki kademeler hiçbir yerde kalmadı (kayıt kimliği aynı, `created=false`).
2. DELETE: aynı satır kargo "eksik"e döndü, net kâr null oldu; tabloda satır yok.
3. Geriye tarihli yeni sürüm (`valid_from=2000-01-01`): kapanmış Ekim döneminin eksik kargo satır sayısı 3 -> 0.

Denetim izi tutar yazmaz (ADR kararı, doğru); ancak silmede (`cargo_tariff.delete`) meta yalnız `{revision, account_id}`'dir: hangi anlaşma, firma ve başlangıcın silindiği bile yok. Güncellemede önceki değer yok. Sonuç: bir ay önce müşteriye/muhasebeciye verilmiş bir dönem raporu (ileride CSV ve e-posta özeti) neden değişti sorusuna sistem cevap veremez; yetkili bir iç kullanıcı geçmiş kârlılığı iz bırakmadan değiştirebilir. Uygulayıcının "önceki sürümler korunur / geçmiş silinmez" notu yalnız farklı başlangıçlı sürümler için doğrudur; DELETE ucu ve yerinde güncelleme bu iddiayla gerilim halindedir.

Yanlış girilmiş sürümü düzeltmek meşru bir ihtiyaçtır (ADR §3.2 DELETE gerekçesi); sorun düzeltmenin değil, izsizliğin ve kullanıcıya etkisinin gösterilmemesinin.

**Düzeltme önerisi:**
1. Yumuşak silme: üç tabloya `deleted_at`, `deleted_by` (motor ve `load_bundle` silinmişleri okumaz); `netkar_app`'ten `DELETE` yetkisi geri alınır. Yerinde güncelleme yerine eski satır `superseded_at` ile kapatılıp yeni satır eklenir (aynı anahtar için kısmi tekil indeks `WHERE deleted_at IS NULL AND superseded_at IS NULL`).
2. Denetim izi: silme ve güncellemede tanımlayıcılar (anlaşma, firma, başlangıç; gider adı ve tipi) meta'ya yazılsın; tutar yine yazılmasın (tarihçe tablosunda RLS altında durur).
3. Geçmişi etkileyen yazımda (başlangıç < bugün, aynı anahtar güncellemesi, silme) yanıt `affects_from` tarihini döndürsün; panel onay penceresi göstersin ("Ekim 2026 ve sonrası raporlar değişecek").
4. Rapor önbelleği (S4 O-01 açık maddesi) gelince anahtar `profit_settings.revision`'ı içermeli (ADR §3.4 zaten söylüyor).

**Test önerisi:** Silinen tarife sürümü tabloda `deleted_at` ile kalır ve motor onu kullanmaz; denetim meta'sında anlaşma, firma ve başlangıç var, tutar yok; aynı anahtarlı PUT sonrası eski kademeler tarihçede okunabilir; `netkar_app` rolüyle `DELETE FROM cargo_tariffs` yetki hatası.

### AO-03 (Orta, alan, belge düzeyi) Kısmi dönemde dönem net kârı sayı olarak kalıyor

**Konum:** `app/profit/aggregate.py:165` (`line_profit` yalnız tam satırlar), `175` (`partial`), `213` (`period_net_profit=line_profit - period_expenses`, kısmi dönemde de sayı), `217` (marj kısmi dönemde null: doğru); `app/api/v1/profit_schemas.py` `PeriodTotalsOut` (dönem düzeyinde `eksik_giderler_haric_kar` yok); docs/12 K39.

**Açıklama:** Motor K39'u belgeye harfiyen uyguluyor; bulgu belgenin kendisinedir. ADR-0006 §2.1 satır düzeyinde "eksik kalemi 0 sayıp sayıyı bayrakla döndürmeyi" reddeder: "bayrağı okumayan her tüketicide (sıralama, CSV, e-posta özeti, uyarı motoru) sayı gerçek net kâr olur". Dönem düzeyinde aynı kalıp sürüyor: `donem_net_kar` = tam satırların net kârı eksi dönemin TÜM dönem düzeyi giderleri, yanında `net_kar_kismi=true`. PoC (Ek A.3, `seed_basic`, ayar yok): 3 aktif satırın 3'ü eksik, `tam_satirlar.satir_sayisi=0`, `donem_net_kar "0.00"`, `net_satis_kdv_haric 183.33`. Dönemde sınıflandırılmamış kesinti olsaydı (G46'daki 17,35 gibi) dönem net kârı -17,35 görünürdü. Yeni bağlanan her hesap ilk günlerde bu durumdadır: panelin ana rakamı "Dönem net kârı 0,00 TL" olur. Ayrıca dönem için "eksik giderler hariç kâr" alanı yoktur; panel "kargo ve hizmet bedeli hariç dönem kârı"nı ancak üst düzey alanları kendisi toplayarak (K39'un kısmi dönemde yasakladığı türetme) çıkarabilir.

**Düzeltme önerisi (önce docs/12 K39, sonra betik, altın test, kod):**
1. Kısmi dönemde `donem_net_kar` null olsun; tam satırlar için dönem giderleri dahil değer ayrı ve adı ne olduğunu söyleyen alanda dursun (örn. `tam_satirlar_donem_giderleri_dahil_net_kar`), ya da en azından `tam_satirlar.satir_sayisi = 0` iken null.
2. Dönem düzeyinde `eksik_giderler_haric_kar` = Σ aktif satır `eksik_giderler_haric_kar` - `donem_duzeyi_giderler_toplami` (ürün düzeyindeki alanın dönem karşılığı) ve rapor `summary`'de aynı adla.
3. Bu karar verilene kadar panel kuralı §7 madde 2 uygulanmalı.

**Test önerisi:** Ayarsız hesap `summary`: `donem_net_kar` null (ya da karara göre etiketli alan), dönem `eksik_giderler_haric_kar` = satır toplamı - dönem gideri; G46 ve G29 betik değerleri yeni alanlarla.

### AD-01 (Düşük) Çok büyük JSON sayısı 500

**Konum:** `app/api/v1/profit_settings_schemas.py:38-50` (`_coerce_decimal`: dizge `_PLAIN_DECIMAL` ile 15 tam haneyle sınırlanır, ama JSON tamsayısı DEĞİŞMEDEN geçer, float `Decimal(repr(...))` olur), `app/services/profit_settings.py:109-110` (`_two_decimals`: `value.quantize(_CENT)`), `155-165` (`check_percent`: `quantize(_BASIS_POINT)`).

**Açıklama:** `Decimal.quantize` sonuç 28 haneyi aşınca `InvalidOperation` fırlatır; bu `ValueError` olmadığı için pydantic onu doğrulama hatasına çevirmez, istek genel 500 olur. PoC: `amount: 1000000000000000000000000000000`, `amount: 1e30`, `max_desi: <31 haneli>`, `default_desi: 1e40`, `percent: 1e30`: beşi de 500 `internal-error` (gövde genel, iç ayrıntı yok; G08 açısından olumlu). Log'a tam yığın izi yazılıyor (girdi değeri yok). Gövde doğrulaması işleyiciden önce olduğundan istek yazma sayacına girmez. Önkoşul owner/admin oturumu ve CSRF; etki log gürültüsü ve 5xx alarmları.

**Düzeltme önerisi:** `_coerce_decimal` tamsayı ve float için de `_PLAIN_DECIMAL` biçimine çevirip denetlesin (`format(Decimal(value), "f")` sonra desen) ya da `_two_decimals`/`check_percent` önce büyüklük denetlesin (`abs(value) < 10**15`) ve `InvalidOperation`'ı `RuleError`'a çevirsin. Genel bir güvence olarak pydantic doğrulayıcılarında `ArithmeticError` -> `PydanticCustomError` sarmalayıcı.

**Test önerisi:** Yukarıdaki beş gövde 422 ve ilgili alan kodu (`amount_out_of_range`, `desi_out_of_range`, `percent_out_of_range`); yanıt girdiyi yansıtmaz.

### AD-02 (Düşük) Okuma uçlarında hız sınırı yok

**Konum:** `app/api/v1/profit_settings.py:186-198` (`read_settings`), `201-219` (`carriers`): yalnız `_require_account`; `limiter.hit` yok. IP kuralı (`app/main.py:35-47`) yalnız POST ve tam yol.

**Açıklama:** PoC: görüntüleyici rolüyle 300 `carriers` + 300 `GET /profit-settings` isteği, 600 x 200; `rate_limits` tablosunda bu uçlar için sayaç 0. Ölçüm: 30.000 satır, 92 günde `carriers` 33-83 ms (indeksli plan, 29 ms yürütme), 20 eşzamanlı istek 0,29 sn. Tek başına etki düşüktür; ancak `docs/50_guvenlik.md` G07 "IP + kullanıcı + kiracı bazında" sınır ister ve bu uçlar bağlantı havuzunu sınırsız kullanabilir; AO-01 düzeltilmezse `GET /profit-settings` yanıtı da büyür.

**Düzeltme önerisi:** İki uca kiracı başına dakikalık sayaç (örn. `profit-settings-read`, 120/dk, ayrı sayaç havuzu); `carriers` sonucu (hesap, gün) anahtarıyla kısa ömürlü önbellek.

**Test önerisi:** Sınır + 1. istek 429 `Retry-After` ile; sayaç anahtarı yazma sayacından ayrı.

### AD-03 (Düşük) Downgrade kullanıcı beyanı veriyi korumasız siler

**Konum:** `migrations/versions/0007_profit_settings.py:151-165` (`REVOKE` ardından `DROP TABLE IF EXISTS ... CASCADE`); uyarı yalnız modül belgesinde (20-21).

**Açıklama:** Kalıp 0004 ve 0006 ile aynıdır ve geri alınabilirlik testi vardır (`test_migration_0007_is_reversible_and_leaves_earlier_tables_intact`, `test_downgrade_below_0007_revokes_privileges_before_dropping`). Fark: 0006 tabloları Trendyol'dan yeniden senkronlanabilir; 0007 tabloları kullanıcının elle girdiği tarife, hizmet bedeli ve giderlerdir, yedek dışında geri getirilemez. Yanlış ortamda ya da sorun giderme sırasında çalıştırılan `alembic downgrade 0006` tüm kiracıların ayarlarını sessizce siler; raporlar "eksik"e döner. `CASCADE` ileride bu tablolara bağlanan görünümleri de sessizce düşürür.

**Düzeltme önerisi:** Downgrade başında tablolar boş değilse `RAISE EXCEPTION` (ya da `alembic -x allow_settings_data_loss=1` gibi açık bayrak olmadan reddet) ve hata metninde yedek alma komutu; `CASCADE` yerine açık sıra. Operasyon runbook'una "0007 downgrade öncesi `COPY ... TO` yedeği" maddesi.

**Test önerisi:** Ayar satırı varken downgrade reddedilir; bayrakla ya da boş tablolarla geçer.

### AD-04 (Düşük, alan) Net kâr sıralaması ayarsız hesapta anlamsız; kesin zararlar sona gidiyor

**Konum:** `app/services/profit_views.py:300-316` (`sort_value`, `_key`: null her yönde sona, eşitlikte barkod).

**Açıklama:** ADR §5'e uygun ("null değerler sona"). Ancak ayarsız ya da yarı ayarlı hesapta neredeyse tüm ürünlerin `net_profit`'i null'dır; PoC: iki ürünün ikisi de null, `asc` ve `desc` aynı barkod sırası. `B1` kesin zararlı (`loss_reason=known_expenses`, `contribution_excl_missing -10.00`) ama "en çok zarar eden" (`asc`) görünümünde sonda. `filter=loss` kesin zararı doğru buluyor (olumlu). Eksik giderler hariç kâra göre sıralama seçeneği yok.

**Düzeltme önerisi:** `sort=contribution_excl_missing` (ya da `known_expenses_profit`) eklenmeli; ya da `net_profit asc`'de kesin zararlı null'lar (`loss_reason` dolu) bilinen negatif değerleriyle sıralanıp belirsiz null'lardan önce gelmeli (imleç anahtarı buna göre). Panel kuralı §7 madde 5.

**Test önerisi:** Biri net kârlı, biri kesin zararlı (null), biri belirsiz (null, pozitif) üç ürün: `asc` sıralamada kesin zararlı belirsizden önce.

### AD-05 (Düşük, alan) Varsayılan desi ile tahmin K23'e giriyor, iz kayboluyor

**Konum:** `app/profit/shipping.py:100-127` (varsayılan desiyle fiyatlanan tahmin `ship_out_estimated_excl`'e yazılır; fatura varsa 113. satırdaki `continue` nedeniyle `KARGO_DESI_VARSAYILAN` eklenmez), `app/profit/lines.py:65-67` (tanımlı tahmin karşılaştırmaya girer).

**Açıklama:** PoC (motor, Ek A.4): siparişte desi yok, varsayılan desi 3, `*` kademesi <=3 -> 50,00. Faturasız: uyarı `KARGO_DESI_VARSAYILAN`, fark 0. Fatura (150,00 KDV dahil = 125,00 hariç) gelince: uyarılar `BEKLENMEYEN_KESINTI` (fark 75,00), `KARGO_DESI_VARSAYILAN` YOK, `KARGO_DESI_FARKI` çıkamaz (siparişte desi yok, K34 gereği doğru). Kullanıcı "Trendyol fazla kesti" sanır; fark aslında hesabın varsayılan desisinin paketten küçük olmasından doğar. K38'in amacı ("uyarı yalnız kullanıcının ya da siparişin beklentisiyle gerçek kesinti arasındaki farkı ölçer") teknik olarak karşılanıyor ama varsayılan desi bir beklenti değil, bilinmeyen için konmuş bir yer tutucudur. Belge (K34, K38) bu durumu açıkça ele almıyor.

**Düzeltme önerisi (önce docs/12 K34/K38):** Varsayılan desiyle fiyatlanan tahmin K23'e girmesin (kargo kalemi karşılaştırma dışı, `kargo_gonderi_tahmini` null ya da ayrı `kargo_tahmini_varsayilan_desi: true`), ya da girerse satırda `KARGO_DESI_VARSAYILAN` korunsun ve uyarı metni "fark varsayılan desiden kaynaklanabilir" desin.

**Test önerisi:** Yukarıdaki iki girdi: faturalı satırda ya `BEKLENMEYEN_KESINTI` yok ya da `KARGO_DESI_VARSAYILAN` ile birlikte.

### AB-01 - AB-08 (Bilgi)

- **AB-01 Tamlık bugünü anlatır:** PoC: tarife ve hizmet bedeli 2026-11-08 (bugün) başlangıçlı yazıldı; Ekim `summary`'si `settings_configured=true`, `completeness` iki bayrak doğru, ama `eksik_kalem_satir_sayilari.kargo_gonderi=3`. `carriers.covered` de bugüne göredir. Panel kurulum bandını `completeness`'e değil dönemin eksik satır sayılarına bağlamalı (§7 madde 3); ayar ekranı başlangıç tarihini varsayılan olarak hesabın ilk siparişinden önceye önermeli.
- **AB-02 Ayrı okumalar:** Motor ayarı `_report` içinde (`profit.py:164`), `completeness` motor sonrası yeniden bağlam kurularak (`222-225`) okunur. Arada bir yönetici yazarsa yanıt "tanımlı" derken satırlar eski ayarla hesaplanmış olur. Kod incelemesi; yeniden üretilmedi. Öneri: `load_bundle` bir kez okunup hem `to_profit_settings` hem `completeness_of` aynı demetten beslensin (zaten mümkün).
- **AB-03 Son yazan kazanır:** `expected_revision` verilmezse 409 yok. Eşzamanlılık testi (`test_concurrent_writers_are_serialised_and_exactly_one_wins_with_same_expectation`) beklenen sürümle doğru; panel her yazımda göndermeli (§7 madde 8). Okuma ucu dört tabloyu ayrı SELECT'lerle okur; araya yazım girerse istemci eski `revision` ile yeni veri görebilir, bu yalnız gereksiz bir 409 üretir (güvenli yön).
- **AB-04 Boş firma adı:** Siparişte `cargoProviderName` null ise `carriers` `""` döndürür; arayüz bu adla tarife yazamaz (1-100 karakter). Öneri: boş adı `*` önerisine eşlemek.
- **AB-05 Tarife seçimi maliyeti:** 200 sürüm (tek firmada) ve 30.000 pakette `lookup` 0,85 sn (1 sürümde 0,07 sn). AO-01 madde 2 ile kapanır.
- **AB-06 Firma adı normalizasyonu:** `check_carrier` kontrol karakterlerini (Cc, Cf: sıfır genişlik, bidi) reddeder (PoC: 422, olumlu); içteki NBSP kabul edilir (200). Eşleşme birebir olduğu için NBSP'li ya da NFD yazılmış ad sessizce eşleşmez ve kargo "eksik" kalır (güvenli yön). Firma adı yalnız `carriers` listesinden seçtirilirse sorun doğmaz.
- **AB-07 Sıfırla susturma:** `*` firması 1000 desiye 0 TL ve hizmet bedeli 0 girildiğinde tüm eksik kalem uyarıları kalkar (repo testi `test_d02_loss_filter_includes_costless_product_with_negative_contribution` bu yolu kullanıyor). K33'e uygundur; panel 0 tutarlı tarife ve tahmini görünür biçimde işaretlemeli.
- **AB-08 KDV dahil giriş altın yolda yok:** `add_user_settings` tüm ayarları `price_includes_vat=false` / `amount_includes_vat=false` yazar; K02 dönüşümü (54,00 -> 45,00; 50,00 -> 41,67; 12,00 -> 10,00) `test_profit_settings_for_reads_the_database_and_converts_vat` birim testinde doğrulanıyor. Öneri: bir altın senaryoyu (örn. G44) KDV dahil girişle de API yolundan çalıştırmak.

## 3. Doğrulanan kontroller (bulgu yok)

### 3.1 Güvenlik

| Kontrol | Sonuç ve kanıt |
|---|---|
| RLS (G01) | Dört tabloda `ENABLE` + `FORCE ROW LEVEL SECURITY`, `tenant_isolation` hem `USING` hem `WITH CHECK` (`0007:133-143`). Repo testleri: kiracılar arası okuma/yazma reddi, tablo sahibi de RLS'ye bağlı (`test_table_owner_is_also_bound_by_row_level_security`). |
| Bileşik FK | `(marketplace_account_id, tenant_id) -> marketplace_accounts (id, tenant_id)`; başka kiracının hesabına satır bağlanamaz (`test_natural_keys_are_unique_and_account_tenant_pair_is_enforced`). `uq_profit_settings_account` hesap kimliği üzerinden; hesap kimliği kiracıya bağlı olduğundan çapraz kiracı tekillik yan kanalı yok. |
| Yetki (en az ayrıcalık) | `netkar_app`: SELECT, INSERT, UPDATE; DELETE yalnız üç sürüm tablosunda, `profit_settings`'te yok (testli). `netkar_worker` yalnız SELECT (`test_worker_can_read_but_not_write`). |
| IDOR/BOLA (API1) | Her uçta `_require_account` (kiracı + hesap) ve tüm servis sorgularında açık `tenant_id` + `marketplace_account_id` süzgeci (çift kilit). PoC `test_ok_same_tenant_other_account_item_is_404_and_revision_unchanged`: aynı kiracının başka hesabındaki tarife ve gider için DELETE ve PUT 404, sürüm artmadı, diğer hesabın kaydı yerinde. Repo testi: başka kiracı her uçta 404. |
| Rol kontrolü | Yazma `require_role(OWNER, ADMIN)`, okuma üç rol; rol bağımlılığı gövde ayrıştırmasından önce çözülür. Görüntüleyici yazamaz (403, testli). |
| Revision ve 409 | `begin_write`: `INSERT ... ON CONFLICT DO NOTHING` + `SELECT ... FOR UPDATE`; ilk yazım yarışında ikinci istek benzersiz indeks üzerinde bekler, sonra güncel satırı kilitler (kilitlenme yok). Sayı sınırları (200 tarife, 50 gider) aynı kilit altında sayıldığı için TOCTOU yok. 404 ve 409'da commit yok: sürüm artışı ve ilk satır geri alınır (testli). |
| Denetim izi | Her başarılı yazım `audit_log`'a; meta'da tutar yok (PoC çıktısı: `carrier`, `agreement`, `valid_from`, `revision`, `account_id`); reddedilen yazım denetlenmez (testli). Eksik olan "ne silindi" bilgisi AO-02'de. |
| Girdi doğrulama (G06) | Dizge sayılar yalnız ASCII rakam, en çok 15 tam + 10 ondalık; `bool` ve `Infinity` 422; aralık ve ondalık kuralları docs/12 K33 tablosuyla aynı; `extra="forbid"`; `brackets` kesin artan, 1-50; `*` yalnız tek başına; kontrol ve biçim karakterleri reddi; `valid_from` 2000-01-01..bugün+366 (`check_valid_from` yeniden kullanımı); `valid_to >= valid_from`. DB CHECK kısıtları derinlemesine savunma (testli). JSONB kademeler yalnız API'den, metin tutarlarla yazılır. İstisna: AD-01. |
| Gövde boyutu (DoS) | `/v1/marketplace-accounts` öneki 8 KiB sınırı bu uçlara da uygulanır; 50 kademe sığar, büyük gövde 413 (testli). |
| Hata yanıtında yansıma (G08) | PoC `test_ok_error_bodies_do_not_reflect_input`: `<script>MARKER</script>` firma, tarih, desi, tutar, gider adı, tip ve KDV alanlarında; hepsi 422 ve yanıtta işaret yok. 409 gövdesi yalnız `current_revision`. |
| Log (G09) | Yeni kodda log çağrısı yok; tutar loglanmıyor. |
| SQL enjeksiyonu | ORM ve bağlı parametre; ham SQL yok. |
| Geri alınabilir migrasyon | upgrade/downgrade/upgrade testli; downgrade önce yetkileri geri alır. Veri kaybı koruması AD-03. |
| Ayar yazımından sonra rapor | Önbellek yok; her rapor `profit_settings_for` ile DB'den okur. Repo testi `test_summary_is_recomputed_with_the_new_settings` ve PoC (1001 kargo 45,00 -> 100,00 -> eksik) yeni ayarın bir sonraki istekte uygulandığını gösteriyor. |
| Bağımlılıklar (G11) | Bu commit yeni bağımlılık eklemedi. |

### 3.2 Alan doğruluğu (K33-K41 uygunluk tablosu)

| Kural | Uygulama | Sonuç |
|---|---|---|
| K33 tanımsız varsayılan | `ProfitSettings()`: tahmin `()`, tarife boş, varsayılan desi None; kayıt yoksa `to_profit_settings` aynı sonucu verir | Uygun |
| K33 sürüm seçimi | `pick_version`: `başlangıç <= gün` en son; başlangıçsız en eski (noktasal denetim: 2025 günü başlangıçsızı, 2026-01-01 tarihliyi seçti) | Uygun (maliyet AO-01) |
| K33 KDV dahil -> hariç | `split_inclusive`: `rnd(dahil x 100 / 120)`, kademe ve tutar başına bir kez; 54,00 -> 45,00, 50,00 -> 41,67, 12,00 -> 10,00 (testli) | Uygun |
| K34 seçim sırası | Firma o gün geçerli sürümü varsa yalnız o; aşım ve desi yok -> None, yedeğe düşmez; firmanın sürümü gelecekteyse `*` (noktasal: TEX 2026-12 sürümlü, 5 Ekim siparişi `*` 50) | Uygun |
| K34 desi sırası ve uyarılar | `cargoDeci` -> `ceil(deci)` -> varsayılan desi; `KARGO_DESI_VARSAYILAN` yalnız tahmin fiyatlandığında; `KARGO_DESI_FARKI` yalnız sipariş desisiyle (`_order_desi`) | Uygun; K23 etkileşimi AD-05 |
| K35 tanımsız != 0 | Tahmin None ise kaynak `eksik` + `HIZMET_BEDELI_TAHMINI_EKSIK`, kesin dağıtılmış siparişte uyarı yok; açık 0 tanımlı (noktasal: `service_fee_estimate_on` 0 döndü) | Uygun |
| K36 değişken gider geçerliliği | `applies_on` uçlar dahil; sipariş başı tipte sipariş günü | Uygun |
| K37 eksik kalem ve null kuralı | `missing_items_of` kanonik sıra; eksikse `net_kar`, `toplam_gider`, marj null; `eksik_giderler_haric_kar` her aktif satırda; ZARAR = `net_kar < 0` ya da (null ve bilinen giderlerle kâr < 0); ürün null; dönem sayıları ve üç özet uyarısı | Uygun (dönem düzeyi AO-03) |
| K38 | Kargo ve hizmet bedeli yalnız tahmini tanımlı VE kesin gelmişse iki toplama girer; tanımsız tahmin karşılaştırma bloğunda null | Uygun; Y-02 ölçümünde yanlış `BEKLENMEYEN_KESINTI` 0 |
| K39 | Tam satır = aktif ve eksiksiz; kısmi dönemde marj null; `tam_satirlar` bloğu; I1-I4 hipotez testleri (60 örnek, ayarlı ve ayarsız) ve 48 altın senaryoda | Uygun (belge düzeyi itiraz AO-03) |
| K40 | Kesin kaynak kümesi {kesin, kesin_dagitim, kullanici, eslesen, yok} ve `teyit_bekliyor` boş; ürün ve dönem özeti `yok/eksik/kesin/tahmini` sırası | Uygun |
| K41 | Koşul: yalnız `Return` satırlarından iade > 0 ve kabul edilmiş claim kalemi 0 (`ManualRefund` dışarıda); bekleyen adet `floor(x + 1/2)` (pozitif sayıda ROUND_HALF_UP), `[1, adet]` aralığında, satış 0 ise adet; maliyet tam gider, kaynak `tahmini`, askıdaki maliyet `rnd(birim x bekleyen)`, maliyet yoksa null | Uygun |
| Rapor API sıralama ve süzgeç | Null her yönde sona (ADR §5); `filter=loss` `known_expenses` dahil üç nedeni kapsar; `_total_expenses` eksik kalemde null; sipariş toplamı eksik kalemde null ve `known_expenses_profit` taşır | Uygun (AD-04 UX) |

### 3.3 Altın senaryolar ve referans betiğin bağımsızlığı

- `altin_test_hesap_ayarlar.py` motoru çağırmıyor: `app` paketinden hiçbir şey içe aktarmıyor (yalnız `altin_test_hesap.py` yardımcıları, standart kütüphane ve `Decimal`); K33-K41'i `hesapla2` içinde bağımsız olarak yeniden yazıyor. Betik motor commit'inden ÖNCE (`6ab98f9`, alan tasarımı) yazılmış; G42-G48 için 139 elle hesaplanmış sabit (`ELLE`) ve G01-G41 için v0.1 kurallarıyla gerileme karşılaştırması (izinli fark listesiyle) yapıyor. Denetimde "TAMAM" verdi; `test_golden_script_guard.py` betiği argümansız çalıştırıp dosyaların değişmediğini denetliyor. Test zayıflığı bulunmadı (bu bağımsızlık olumlu kontroldür).
- API altın yolu (`test_report_golden_api.py`) ayarları gerçekten DB tablolarına yazıp `profit_settings_for` ile okuyor (monkeypatch yalnız tabloda olmayan sistem parametrelerini bindiriyor); kalan boşluk AB-08.
- Eski betik doğrudan çalıştırılınca yeni betiğe yönleniyor; G42-G48'i silme riski kapandı.

## 4. S4 bulgularının durumu

| Bulgu | Durum | Kanıt |
|---|---|---|
| Y-02 varsayılan ayarla şişkin net kâr | KAPANDI (motor + API) | G01-G41 `ProfitSettings()` ile: eksik kalemli 53 satırın hiçbirinde net kâr sayı değil; yanlış `BEKLENMEYEN_KESINTI` 0 (S4'te 21 senaryo); S4'te zarardan kâra dönen G19, G32, G33 artık null + pozitif eksik giderler hariç kâr ("belirsiz"), kâr olarak görünmüyor. `summary` özet uyarıları `KARGO_EKSIK_SATIRLAR_VAR`, `HIZMET_BEDELI_EKSIK_SATIRLAR_VAR` içeriyor. Panelde sunum kuralları (§7) uygulanmadan yayın yapılmamalı. |
| O-02 kısmi dönem marjı | KAPANDI | İlk turun PoC'si başarısız oluyor (marj artık null); `tam_satirlar` bloğu. Belge düzeyi kalan itiraz AO-03. |
| O-03 `basis` etiketi | KAPANDI | `certainty` (motor `kesinlik`), `statement_basis`; PoC: B2 `statement_basis=settled`, `certainty=eksik`, `missing_items` üç kalem. `basis` bir sürüm boyunca aynı değerle duruyor (açıklaması "kesinlik anlamı taşımaz"). |
| O-04 claim'siz iade | KAPANDI | PoC 1003: `IADE_KAYDI_BEKLENIYOR`, bekleyen adet 1, askıdaki maliyet 50,00; dönem `IADE_KAYDI_BEKLENEN_SATIRLAR_VAR`. |
| B-02 iptal "0,00 kâr" | AÇIK (kısmen) | Satır `kesinlik=iptal`, ürün `certainty=yok` panelin ayırt etmesine yetiyor; sipariş toplamı hâlâ `net_profit "0.00"`. |
| YO-01 rapor kapısı adaleti | AÇIK | AO-01 bu bulguyu büyük veri gerektirmeden tetiklenebilir kılıyor. |
| D-03, B-03, B-04, B-05, YD-01, YB-01, YB-02 | AÇIK (kapsam dışı) | Değişiklik yok. B-04'e firma adı ve gider adı eklendi (yansıyan kullanıcı metni). |

## 5. 50_guvenlik.md merge engeli kontrolleri (bu kapsamdakiler)

| Kontrol | Durum |
|---|---|
| G01 Kiracı izolasyonu | Karşılanıyor (§3.1) |
| G06 Girdi doğrulama | Karşılanıyor; AD-01 (büyük sayı 500) ve AO-01 (sürüm sayısı sınırı eksik) düzeltilmeli |
| G07 Hız sınırı | Kısmen: yazma uçları kiracı başına sınırlı; okuma uçları sınırsız (AD-02); AO-01 sınırı sayaçla değil sayı kuralıyla kapanmalı |
| G08 Hata yanıtları | Karşılanıyor (500'ler genel gövdeli, yansıma yok) |
| G09 Log | Karşılanıyor |

## 6. Merge engeli var mı: HAYIR (koşullu)

- Kritik veya Yüksek bulgu yok. Kod merge'ünü engelleyen güvenlik bulgusu yok.
- **AO-01** (Orta, güvenlik) birden çok kiracı canlıya alınmadan önce kapatılmalı: düzeltme küçük (sayı sınırı + `bisect`), etkisi kiracılar arası rapor kesintisi.
- **AO-02** ve **AO-03** (Orta, alan) panelde dönem raporu ve ayar ekranı yayınlanmadan önce karar gerektirir: AO-03 docs/12 K39 değişikliğidir (önce belge, sonra betik, altın test, kod); karar gelene dek §7 madde 2 zorunludur. AO-02 için en azından denetim meta'sına tanımlayıcılar ve geçmişi etkileyen yazımda panel onayı.
- S4 Y-02 yayın engeli motor tarafında KALKTI; panel §7 kurallarına uymadan net kâr gösterirse engel fiilen geri gelir.

## 7. Panel (rapor ve ayar ekranları) için güncellenen sunum kuralları

S4 raporu §7'nin yerine geçer.

1. **Null net kâr:** `net_kar` / `net_profit` null ise "Net kâr hesaplanamadı" ve eksik kalemler adlarıyla (`eksik_kalemler` / `missing_items`: "ürün maliyeti", "kargo", "hizmet bedeli") gösterilir; asla 0,00 yazılmaz. `eksik_giderler_haric_kar` / `contribution_excl_missing` yalnız "Eksik giderler hariç kâr (kargo ve hizmet bedeli hariç)" gibi eksik kalemleri sayan etiketle ve net kâr başlığından ayrı gösterilir. Eksik kalem hücresi "eksik" yazar, 0,00 değil.
2. **Dönem rakamı (AO-03):** `net_kar_kismi=true` ise `donem_net_kar` başlık rakamı olarak gösterilmez; `tam_satirlar.satir_sayisi = 0` ise hiç gösterilmez. Kısmi dönemde gösterilebilecek marj yalnız `tam_satirlar.net_kar_marji_yuzde` ("eksiksiz satırların marjı, dönem giderleri hariç" etiketiyle). Şelale ve toplam gider yalnız `tam_satirlar` bloğundan çizilir; dönem düzeyi giderler (`donem_duzeyi_giderler`) ayrı satır.
3. **Kurulum bandı (AB-01):** Bant `completeness`'e değil dönemin `totals.eksik_kalem_satir_sayilari`'na bağlanır: "Bu dönemde N satırda kargo, M satırda hizmet bedeli tahmini eksik" + ayar sayfasına bağlantı. `completeness` yalnız ayar ekranında "bugün geçerli" anlamıyla kullanılır. `settings_configured` yeni ekranlarda kullanılmaz (eski alan).
4. **Kesinlik:** "Kesin" rozeti yalnız `certainty` / `kesinlik = kesin`'den; `tahmini` ve `eksik` ayrı rozet. `statement_basis` "ekstre durumu" olarak gösterilebilir, kesinlik olarak değil; `basis` yeni kodda kullanılmaz.
5. **Zarar ve sıralama (AD-04):** `loss_reason`: `net_profit` "zarar", `contribution_before_cost` "maliyet girilmese de zarar", `known_expenses` "bilinen giderlerle bile zarar". Net kârı null ve eksik giderler hariç kârı pozitif ürün "belirsiz"dir, "kârlı" değildir. "En kârlı ürünler" yalnız `net_profit` null olmayan ürünlerden; ayarsız hesapta bu liste yerine kurulum çağrısı. "En çok zarar edenler" `filter=loss` ile, `sort=net_profit&order=asc` ile değil.
6. **İade kaydı bekleyen satır:** `IADE_KAYDI_BEKLENIYOR` satırında "İade kaydı bekleniyor; ürün stoğa dönerse tahmini net kâr: `net_kar + askidaki_urun_maliyeti`" (net kâr null ise eksik giderler hariç kâr üzerinden ve aynı etiketle); kesinlik `tahmini` rozeti.
7. **Uyarılar:** `BEKLENMEYEN_KESINTI` artık ayarsız hesapta da gösterilebilir (K38). AD-05 düzeltilene kadar uyarının yanında `karsilastirma` kalem dökümü (tahmini ve kesin kargo, hizmet bedeli, komisyon) gösterilsin; kargo farkı baskınsa "siparişte desi yoksa varsayılan desi farkı olabilir" ipucu. Uyarılar kod başına gruplanır.
8. **Ayar ekranı:** Firma adı yalnız `carriers` listesinden ve `*` ("diğer firmalar") seçeneğiyle; serbest yazım yok; boş ad (`""`) `*` önerisine eşlenir (AB-04). Her yazımda `expected_revision` gönderilir; 409'da ekran yeniden yüklenir ve kullanıcıya bildirilir (AB-03). Başlangıç tarihi bugünden önceyse, aynı anahtarlı güncelleme ya da silmede "geçmiş dönem raporları değişecek" onay penceresi (AO-02). Girilen ve KDV hariç fiyat birlikte gösterilir. 0 tutarlı tarife ve hizmet bedeli "0 girildi" rozetiyle (AB-07). Başlangıç tarihi önerisi hesabın ilk siparişinden önce (AB-01).
9. **Metin:** Ürün başlığı, firma adı, gider adı ve `carriers` öğeleri metin düğümü olarak basılır (B-04).
10. **İptal:** `kesinlik=iptal` satır ve `certainty=yok` ürün "İptal" olarak; sipariş toplamındaki `net_profit "0.00"` iptal siparişte gösterilmez (B-02).
11. **Sayfalama:** `cursor_invalid` 422'de liste baştan yüklenir (S4 kuralı sürer).

## 8. Uygulayıcının notunun değerlendirmesi ("geçmiş silinmez" ile DELETE ucu)

| Not | Değerlendirme | Ciddiyet |
|---|---|---|
| "Sürümlü kayıtlarda önceki sürümler korunur; DELETE yalnız istenen tek kaydı siler" | Doğru ama dar: farklı başlangıçlı sürümler korunur; aynı anahtarlı PUT, DELETE ve geriye tarihli yeni sürüm kapanmış dönemi yeniden yazar ve önceki durum hiçbir yerden okunamaz (PoC). Yanlış girişi düzeltme ihtiyacı meşru; çözüm yumuşak silme, tarihçe ve denetim meta'sında tanımlayıcı | Orta (AO-02) |
| "Migrasyon geri alınabilir" | Doğru (testli); kullanıcı beyanı veri için koruma yok | Düşük (AD-03) |
| "Hız sınırı" | Yazma uçları için doğru; okuma uçları sınırsız; sürüm sayısı sınırı hizmet bedelinde eksik | Orta (AO-01), Düşük (AD-02) |

## Ek A. Kavram kanıtı özetleri

Dosyalar oturumun geçici dizinindedir: `/tmp/claude-0/-home-user-hyt/9e0dcdb7-1ce4-5047-97d3-278f704913e7/scratchpad/` altında `test_poc_ayarlar.py`, `test_poc_ayarlar_fee.py`, `test_poc_ayarlar_perf.py`, `ayar_defaults.py`, `k34_check.py`, `default_desi_k23.py`, `lookup_bench.py`, `fee_bench.py`. Çalıştırma: `cd netkar/services/api && uv run python -m pytest -p tests.conftest -c pytest.ini --rootdir=. -q -s <dosya>` (betikler `uv run python <dosya>`).

### A.1 Hizmet bedeli sürümleri (AO-01)
- `test_poc_unbounded_service_fee_versions`: API ile 2000-01-01'den başlayan 210 ardışık günlük sürüm, hepsi 200. `tests.test_report_perf.seed_large` (5.000 sipariş, 30 gün): `summary` 1,62 sn. Kalan günler `admin_conn` ile eklendi (10.173 sürüm; API ile kiracı başına saatte 600 yazımla yaklaşık 17 saat): `summary` 76,17 sn.
- `fee_bench.py`: 10.175 sürümde `service_fee_estimate_on`, 1.000 çağrı 3,24 sn, 5.000 çağrı 16,89 sn. `lookup_bench.py`: 200 tarife sürümü x 50 kademe, 30.000 `lookup` 0,85 sn (1 sürüm 0,07 sn).

### A.2 Geçmişin yeniden yazılması (AO-02)
- `test_poc_delete_and_inplace_update_rewrite_past_report_and_audit_has_no_before_values`: `seed_basic`, tarife 2026-01-01 (54,00 dahil) + hizmet bedeli. 1001 satırı kargo: 45.00 -> (aynı anahtar PUT 120,00 dahil) 100.00 -> (DELETE) 0.00 ve `eksik_kalemler ['kargo_gonderi']`, net kâr null. Denetim meta'ları: upsert `{carrier, agreement, valid_from, revision, account_id}`, delete `{revision, account_id}`. Tabloda tarife satırı 0.
- `test_poc_backdated_new_version_rewrites_closed_period`: `valid_from=2000-01-01` tarife yazımı Ekim `eksik_kalem_satir_sayilari.kargo_gonderi` 3 -> 0.

### A.3 Dönem rakamı ve sıralama (AO-03, AD-04, AB-01)
- `test_poc_unconfigured_period_net_profit_is_a_number_from_subset`: `donem_net_kar 0.00`, `net_kar_kismi true`, `tam_satirlar.satir_sayisi 0`, `kesinlik_satir_sayilari {kesin 0, tahmini 0, eksik 3}`, `net_satis_kdv_haric 183.33`; dönemde `eksik_giderler_haric_kar` alanı yok.
- `test_poc_net_profit_asc_puts_certain_losses_last`: `asc` sıralama `[(B1, null, -10.00, known_expenses), (B2, null, 75.00, null)]` (barkod sırası); `filter=loss` yalnız B1 (`known_expenses`): doğru.
- `test_poc_completeness_true_while_period_lines_still_missing`: bugün başlangıçlı tarife ve hizmet bedeli; `settings_configured true`, `completeness` iki bayrak doğru, Ekim `eksik_kalem_satir_sayilari {urun_maliyeti 1, kargo_gonderi 3, platform_hizmet_bedeli 3}`.

### A.4 Varsayılan desi ve K23 (AD-05)
- `default_desi_k23.py`: sipariş "Ornek Kargo", desi yok; ayar: varsayılan desi 3, `*` [<=3: 50, <=30: 200], hizmet bedeli 10. Faturasız: `['MALIYET_EKSIK', 'KARGO_DESI_VARSAYILAN']`, tahmini kargo 50.00, fark 0.00. Faturalı (150,00 dahil): `['MALIYET_EKSIK', 'BEKLENMEYEN_KESINTI']`, tahmini kargo 50.00, fark 75.00.
- `k34_check.py`: firmanın gelecekteki sürümü varken `*` 50; firma sürümünde aşım None; desi yok None; bilinmeyen firma `*` 50, `*` aşımı None; açık 0 tahmin 0; hizmet bedeli 5 Ekim 8, 15 Ekim 10, ilk sürümden önce None.

### A.5 Girdi ve okuma uçları (AD-01, AD-02, olumlu kontroller)
- `test_poc_huge_json_number_gives_500` (4 durum) ve `test_poc_huge_percent_gives_500`: 500 `internal-error`; log: `decimal.InvalidOperation` (`_two_decimals` 4, `check_desi` 2, `check_service_fee_amount` 2, `check_percent` 1 çerçeve). 422 doğrulama hataları yazma sayacına girmiyor (sayaç 0).
- `test_poc_read_endpoints_have_no_rate_limit`: görüntüleyici, 600 x 200; sayaç 0. `test_poc_ayarlar_perf.py`: 30.000 satır, 92 gün, `carriers` 33-83 ms, 20 eşzamanlı 0,29 sn, `EXPLAIN ANALYZE` yürütme 29 ms.
- Olumlu: `test_ok_same_tenant_other_account_item_is_404_and_revision_unchanged`, `test_ok_error_bodies_do_not_reflect_input`, `test_ok_carrier_bidi_and_zero_width_rejected_nbsp_inside_accepted` (iç NBSP 200), `test_ok_s4_domain_findings_now_visible` (dönem uyarıları dört özet kodu, marj null, kesinlik `eksik`; B2 `eksik`/`settled`; 1003 `IADE_KAYDI_BEKLENIYOR` 1 adet 50,00; 1004 `iptal`).

### A.6 Y-02 ölçümünün tekrarı
- `ayar_defaults.py`: G01-G41, her senaryo kendi ayarıyla ve `ProfitSettings()` ile. Aktif satır 57, eksik kalemli 53, eksikken sayı net kâr 0, altın sonuçta olmayan `BEKLENMEYEN_KESINTI` 0, kısmi dönemde sayı marj 0. Ayarsızken `ZARAR` uyarısı kalkan satırlar G19, G32, G33 (2): bilinen giderlerle kâr pozitif, net kâr null ("belirsiz"); doğru davranış.

## Ek B. Tüm test paketi

`cd netkar/services/api && uv run pytest -q` (58aabb2, gerçek PostgreSQL): 1780 geçti, 6 atlandı (reklam senaryoları, bilinçli), 0 kaldı; 310,9 sn. Uygulayıcının bildirdiği sayıyla aynı.
