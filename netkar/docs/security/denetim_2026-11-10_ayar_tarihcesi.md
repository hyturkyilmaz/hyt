# NetKâr Güvenlik ve Alan Denetimi: Ayar tarihçesi ve dönem rakamı (10 Kasım 2026)

**Sonuç önce:** Kritik ve Yüksek bulgu YOK. Merge'ü engelleyen güvenlik bulgusu yok. 10 bulgu var, hepsi Düşük.
Bunlardan ikisi (YT-01 damga yarışı, YT-03 taşımanın savunma dalı) rapor önbelleği ya da canlı veri taşıması
gelmeden kapatılmalı.

- Denetlenen sürüm: commit `2b34c1a` ("NetKâr: ayar tarihçesi ve dönem rakamı uygulandı (K39 Rev.1, K42-K44,
  migrasyon 0008)"), taban `9cd1a4e`. Satır numaraları `2b34c1a`'ya göredir.
- Kapsam: K39 Revizyon 1 (motor, rapor şeması), K42-K44 (servis, API, rapor damgası), migrasyon
  `0008_profit_settings_history.py`; `git diff 9cd1a4e..2b34c1a -- netkar/services/api netkar/calisma_dosyalari`.
  `netkar/apps/web` kapsam dışı (başka ajan çalışıyor; yalnız okundu, dokunulmadı).
- Spesifikasyon: `docs/adr/0007-ayar-tarihcesi-ve-donem-rakami.md` (§4, §5.1, §7, §8), `docs/12_kar_motoru.md`
  (K39 Revizyon 1, K42-K44, I1-I6), `docs/adr/0006-kar-ayarlari.md`, önceki denetim
  `docs/security/denetim_2026-11-09_kar_ayarlari.md` (AO-02, AO-03).
- İki şapka: (1) uygulama güvenliği (OWASP ASVS 5.0 Seviye 2, OWASP API Top 10 2023, `docs/50_guvenlik.md` G01,
  G06-G09); (2) kâr motoru ve ayar alanı doğruluğu.
- Denetçi kodu yazmadı; kaynak ve test dosyaları değiştirilmedi, commit yapılmadı. Kavram kanıtı (PoC) testleri
  repo dışında, oturumun geçici dizininde repo `conftest`'i eklenti olarak yüklenerek gerçek PostgreSQL ile
  çalıştırıldı (Ek A).

## 0. Yöntem ve test sonuçları

| Adım | Sonuç |
|---|---|
| Kod incelemesi: migrasyon 0008, model, servis (`app/services/profit_settings.py`), API (`profit_settings.py`, şemalar), rapor uçları (`profit.py`, `profit_schemas.py`), motor (`aggregate.py`, `results.py`), referans betik, değişen 20 test dosyası | Tamamlandı |
| `uv run pytest tests/test_profit_settings_history_api.py tests/test_profit_settings_history_schema.py -q` | 46 geçti (21,7 sn) |
| `make test-profit` | 656 geçti, `app/profit` satır ve dal kapsamı %100 (149 sn) |
| `uv run pytest tests/test_report_api.py tests/test_report_golden_api.py tests/test_feed_golden_database.py tests/test_golden_script_guard.py -q` | 215 geçti, 6 atlandı (reklam, bilinçli) (Ek B) |
| Referans betik (`uv run python ../../calisma_dosyalari/altin_test_hesap_ayarlar.py`, yalnız doğrulama; `--yaz` çalıştırılmadı, dosya yazmamak için) | "TAMAM: tüm kontroller geçti", 49 senaryo, 170 elle kontrol edilen değer |
| PoC (`test_poc_tarihce.py`, 9 test) | 9/9 geçti (`test_poc_*` gözlemin varlığını, `test_ok_*` bulgu olmadığını gösterir) |
| Tam `make test` | Koşulmadı (gerekli görülmedi; uygulayıcı 1983 geçti bildiriyor) |

## 1. Özet tablo

| No | Önem | Başlık | Konum |
|---|---|---|---|
| YT-01 | Düşük | Rapor damgası (`settings_revision`) ile motorun kullandığı satırlar ayrı anlık görüntülerden okunuyor: eşzamanlı yazımda damga R, satırlar R+1 (K44 iddiası o yanıt için yanlış); `summary` tamlığı üçüncü bir okumadan | `app/services/profit_settings.py:298-354`; `app/api/v1/profit.py:165, 233` |
| YT-02 | Düşük | `settings-record-ended` halef zinciri halka başına bir sorguyla yürüyor, `replaces_id` indekssiz; uzun zincirde istek saniyelerce bağlantı ve hesap ayar kilidini tutuyor | `app/services/profit_settings.py:716-732`; `migrations/versions/0008_profit_settings_history.py:55` |
| YT-03 | Düşük | Taşımanın savunma dalı (ayar satırı olmayan hesap) tutarsız durum bırakıyor: etkin satır var ama damga 0, `tasima` kaydı yok; ilk değiştirme/geri çekme 500 | `0008_profit_settings_history.py:64, 159-164`; `app/services/profit_settings.py:531-533, 683-687` |
| YT-04 | Düşük | Derinlemesine savunma: `netkar_app` INSERT ile tarihçeyi DB düzeyinde sahteleyebiliyor (geçmiş `revision_from`, baştan kapalı satır, sahte `tasima`, başka kiracının kullanıcısı `changed_by`, sayaçtan kopuk `revision_to`) | `0008:172-175` (yetki), `0008:98-111` (tetikleyici yalnız UPDATE) |
| YT-05 | Düşük | Değişmezlik tetikleyicisi ADR §3/§7'deki `ON DELETE SET NULL` seçeneğini ve gelecekteki veri doldurma migrasyonlarını engeller; belgelenmemiş | `0008:98-111`; ADR-0007 §3, §7 madde 1 |
| YT-06 | Düşük | `GET /history` imleci mühürsüz düz tamsayı (projedeki AES-GCM imleç deseninden sapma); güvenlik etkisi yok | `app/api/v1/profit_settings.py:75, 745`; `app/services/profit_settings.py:1115-1116` |
| YT-07 | Düşük | Onay (`confirm_past_change`) gösterilen etki tarihine bağlı olmayan çıplak bool; önceki onaylı gövde başka bir tarihle yeniden kullanılabilir | `app/services/profit_settings.py:626-636`; şemalar `ConfirmPastChange` |
| YT-08 | Düşük | Belge kayması: docs/12 K43 hata türünü `past-change-confirmation-required` diyor; ADR §4 `ck_..._replace` ve §5.1 `changed_by` görünen ad maddeleri koda göre güncellenmedi | `docs/12_kar_motoru.md:1147`; ADR-0007 §4 (satır 188), §5.1 (satır 235) |
| YT-09 | Düşük | Günlük kısıtları gevşek: `defaults` kaydında `record_id`/`replaced_record_id` ve desi önce/sonra tutarlılığı DB'de denetlenmiyor | `0008:148-151` |
| YT-10 | Düşük | Test anlamsızlaşması: `test_other_financials_classification` dalı sabitlemiyor (bir dal ölü); damga yarışı ve zincir maliyeti için test yok | `tests/test_profit_shipping_fees.py:276-282` |

Sayım: Kritik 0, Yüksek 0, Orta 0, Düşük 10.

## 2. Ayrıntılar

### YT-01 (Düşük) Rapor damgası ile ayar satırları ayrı anlık görüntülerden okunuyor

**Kanıt:** `load_bundle` önce başlığı okur (`app/services/profit_settings.py:298-301`, `current = head.revision`),
sonra tarife, hizmet bedeli ve gideri ayrı `SELECT`'lerle yalnız `revision_to IS NULL` süzgeciyle okur
(`315-350`, `_in_force(..., None)` = `259-261`). Oturum READ COMMITTED'dır; her ifade kendi anlık görüntüsünü alır.
Arada commit edilen bir yazım, damgası R olan ama R+1 satırlarıyla kurulmuş bir `SettingsBundle` üretir.
`profit.py:165` bu demeti hem motora hem `settings_revision`'a verir. Ayrıca `summary` tamlığı motor sonrası
yeniden okunur (`profit.py:233`, önceki denetimin AB-02'si açık kaldı): tek yanıtta üç ayrı ayar okuması.

PoC (Ek A.1): sürüm 1'de hizmet bedeli 12,00; başlık okunduktan sonra eşzamanlı yönetici aynı anahtarı 99,00 ile
değiştirip commit eder. Sonuç: `bundle.revision == 1`, `fees == [99.00]`, `revision_from == 2`.

**Etki:** K44'ün "aynı sürüm aynı sonucu verir" ve "damga, rakam neden değişti sorusunun ilk adımıdır" vaadi o
yanıt için yanlıştır; panel "Ayar sürümü 1" yazar ama rakamlar sürüm 2'dendir. ADR-0006 §3.4'teki rapor önbelleği
anahtarı `settings_revision` içerdiğinde, R anahtarlı önbellek girdisine R+1 sonucu yazılır ve sonraki R
istekleri yanlış sonucu alır (önbellek geldiğinde Orta'ya çıkar). `GET /profit-settings` için aynı yarış
gereksiz bir 409'a yol açar (güvenli yön).

**Düzeltme:** Satırlar değişmez olduğu için çözüm ucuzdur: güncel okumada da satırları başlıkta okunan sürümle
süz (`_in_force(model, current)`, yani `revision_from <= current AND (revision_to IS NULL OR revision_to >
current)`); desi zaten başlıkla aynı satırdan gelir. Böylece başlıktan sonra commit edilen yazım hiçbir okumaya
sızmaz (PoC `test_ok_as_of_filter_at_the_read_revision_would_close_the_race` dayanağı). `summary` tamlığı
(`profit.py:233`) aynı demetten `completeness_of(bundle, today)` ile hesaplansın; `LoadedSettings` demeti de
taşısın. Alternatif: `load_bundle`'ı `REPEATABLE READ` işlemde çalıştırmak.

**Test:** başlık okunduktan sonra eşzamanlı yazım commit edilir; demetin satırları ve desisi damgayla aynı
sürümden (PoC A.1'in tersi).

### YT-02 (Düşük) Halef zinciri halka başına sorgu, indekssiz `replaces_id`

**Kanıt:** `_current_id` (`app/services/profit_settings.py:716-732`) kapanmış satırdan etkin halefe kadar
`while` döngüsünde her halka için `SELECT ... WHERE replaces_id = :id` yapar; döngü sınırsızdır ve
`replaces_id` üzerinde indeks yoktur (`0008:55`; yalnız `(tenant_id, marketplace_account_id)` ve
`revision_from` indeksleri var). Çağrı `begin_write`'tan SONRA olduğu için (`profit_settings.py:336-337`) bu süre
boyunca hesabın `profit_settings` satırı `FOR UPDATE` kilitli ve bir havuz bağlantısı tutulur.

PoC (Ek A.4): tek gider tanımının 200 ve 2000 kez değiştirilmiş zinciri; en eski kimliğe `PUT` (409
`settings-record-ended`, doğru `current_id`): 0,19 sn ve 2,29 sn (10 katta 12 kat, doğrusalın üstü).

**Senaryo:** owner/admin yazma sınırı (saatte 600) içinde bir gideri sürekli değiştirir (2000 halka yaklaşık 3,5
saat); sonra en eski kimliğe paralel istekler gönderir. Her istek saniyelerce bağlantı tutar; zincir büyüdükçe
süre artar. Etki önce kendi hesabının yazımlarını kilitler, sonra paylaşılan bağlantı havuzunu (kiracılar arası)
zorlar. Önkoşul yönetici rolü ve uzun hazırlık olduğundan Düşük. İmha işinde (hesap silme) self-FK'nin
indekssiz olması silinen her satır için ayrıca tarama demektir.

**Düzeltme:** (1) `CREATE INDEX ix_<tablo>_replaces ON <tablo> (replaces_id) WHERE replaces_id IS NOT NULL`
(üç tablo; 0009 ya da 0008 yayınlanmadıysa 0008); (2) zinciri tek sorguda yürü (`WITH RECURSIVE`), ya da
satıra bir `lineage_id` (ilk satırın kimliği) yazıp `WHERE lineage_id = :x AND revision_to IS NULL` ile tek
okuma; (3) savunma olarak döngüye üst sınır (örn. 10.000) ve aşımda `current_id: null`.

**Test:** 5.000 halkalı zincirde `settings-record-ended` yanıtı sabit sayıda sorgu (sayaçla) ya da 200
halkalının en çok 2 katı süre.

### YT-03 (Düşük) Taşımanın savunma dalı tutarsız durum bırakıyor; ilk değiştirme 500

**Kanıt:** `0008:64` ayar satırı (`profit_settings`) olmayan hesabın satırlarına `revision_from = 1` yazar; `tasima`
kaydı yalnız `profit_settings` satırı olan hesaplar için düşer (`0008:159-164`). Bu durumda: `load_bundle`
başlık yok diye `current = 0` döner ama etkin satırları okur (damga 0, satırlar var: K44 "hiç ayar yazılmamışsa
0" ile çelişir). İlk yazımda `begin_write` başlığı `revision = 1` ile oluşturur ve `ticket.next == 1`
(`profit_settings.py:531-533`); değiştirme/geri çekme eski satırı `revision_to = 1` ile kapatmaya çalışır ve
`ck_<tablo>_ended` (`revision_to > revision_from`) ihlali 500 olur.

PoC (Ek A.7): başlıksız `revision_from = 1` hizmet bedeli; `GET` `revision: 0` ve 1 satır; aynı anahtarlı `PUT`
500 (`CheckViolation ck_service_fee_estimates_ended`).

**Etki:** 0007 akışında her yazım başlığı oluşturduğu için bu durum normalde oluşmaz; ama migrasyon bu dalı
"savunma" diye açıkça kodluyor ve bu dal hesabı kalıcı olarak yazılamaz bırakır (her değiştirme/geri çekme 500;
log'da yığın izi, tutar yok). Test tohumları da (`tests/test_feed_golden_database.py` `add_user_settings`,
desi yoksa) bu durumu üretiyor; yalnız okuma yaptıkları için görünmüyor.

**Düzeltme:** Taşımada başlığı olmayan hesaplar için önce başlık oluştur:
`INSERT INTO profit_settings (tenant_id, marketplace_account_id, revision, updated_by) SELECT DISTINCT
tenant_id, marketplace_account_id, 1, entered_by FROM (üç tablo UNION ALL) ... WHERE NOT EXISTS (...)`; sonra
`revision_from` doldurma ve `tasima` kaydı herkes için çalışır. Servis tarafında savunma: `begin_write`
oluşturma dalında hesapta etkin satır varsa `RuntimeError` yerine açık bir 409/500 nedeni loglansın. Test
tohumları başlık satırını her zaman eklesin.

**Test:** 0007 şemasında başlıksız satır, upgrade sonrası başlık `revision = 1`, `tasima` kaydı var; aynı anahtarlı
`PUT` 200 ve sürüm 2.

### YT-04 (Düşük) Uygulama rolü tarihçeyi INSERT ile sahteleyebiliyor (derinlemesine savunma)

**Kanıt:** Değişmezlik iki katmanı (yetki, `0008:172-173`; tetikleyici, `0008:98-111`) yalnız UPDATE ve DELETE'i
kapsar. INSERT'te sürüm ile başlık ve günlük arasında DB bağı yoktur: `revision_from` herhangi bir değer, satır
baştan kapalı eklenebilir, günlüğe `changed_by NULL` ile `tasima` eklenebilir (kısıt yalnız `item = 'tasima'`
ister), `changed_by` yalnız `users(id)`'ye FK olduğundan başka kiracının kullanıcısı yazılabilir; etkin satırın
`revision_to`'su başlık sayacından bağımsız (örn. 1.000.000) yazılabilir.

PoC (Ek A.3): `netkar_app` rolüyle beş sahte yazımın beşi kabul edildi.

**Etki:** Önkoşul uygulama rolünün ele geçirilmesi ya da hatalı kod (SQL enjeksiyonu yok; ORM ve bağlı
parametre). Sonuç: sürümle yükleme (K44) eski bir sürümde sahte satırı görür, sahte `tasima` eski sürümleri
"yeniden kurulamaz" yapar, geçmiş ekranı yanlış kişi gösterir. ADR §2.1'in "veritabanı düzeyinde güvence"
ölçütü UPDATE/DELETE için sağlanıyor, INSERT için sağlanmıyor.

**Düzeltme (önem sırasıyla):** (1) `BEFORE INSERT` tetikleyicisi: `revision_to IS NULL`, `ended_* IS NULL` ve
`revision_from = (SELECT revision FROM profit_settings WHERE marketplace_account_id = NEW.marketplace_account_id)`
şartı (başlık aynı işlemde artırıldığı için yazım akışıyla uyumlu); (2) `BEFORE UPDATE` tetikleyicisine
`NEW.revision_to = başlık.revision` şartı; (3) günlükte `item = 'tasima'` INSERT'ini `netkar_app` için
reddeden tetikleyici (`current_user = 'netkar_app'` ise) ve `changed_by`'ın kiracı üyesi olduğunu denetleyen
`(tenant_id, changed_by) -> memberships (tenant_id, user_id)` bileşik FK'si (üyelik silinince sorun yaratırsa
tetikleyiciyle).

**Test:** `netkar_app` ile geçmiş `revision_from`, baştan kapalı satır ve `tasima` INSERT'i hata; normal yazım
akışı geçer.

### YT-05 (Düşük) Tetikleyici `ON DELETE SET NULL` seçeneğini ve veri doldurma migrasyonlarını engeller

**Kanıt:** `profit_settings_version_guard` (`0008:98-111`) kapanmış satırda HER güncellemeyi ve etkin satırda
kapanış sütunları dışındaki her değişikliği reddeder; `entered_by` ve `ended_by` istisna değildir. PostgreSQL'de
referans eylemi (`ON DELETE SET NULL`) referans veren tabloda UPDATE yapar ve kullanıcı tetikleyicileri tetiklenir.
ADR-0007 §3 ve §7 madde 1 kullanıcı silmede `ON DELETE SET NULL`'u seçeneklerden biri olarak sunuyor; bu
tetikleyiciyle o seçenek uygulanırsa kullanıcı silme "kapanmis kar ayari surumu degistirilemez" hatasıyla
durur. Aynı şekilde gelecekte bir migrasyonda yeni sütunu `UPDATE` ile doldurmak her satırda reddedilir.

**Etki:** Bugün kullanıcı silme yok; tuzak, avukat cevabı geldiğinde ya da bir sonraki şema değişikliğinde ortaya
çıkar.

**Düzeltme:** ADR §3/§7'ye not: "Değişmezlik tetikleyicisi nedeniyle kimliksizleştirme (kullanıcı satırında ad ve
e-postayı silmek) tercih edilir; `SET NULL` seçilirse tetikleyici `entered_by`, `ended_by` için yalnız
NULL'a çekmeye izin vermeli". Migrasyon rehberine: "sürümlü tablolarda veri doldurma `ALTER TABLE ... DISABLE
TRIGGER trg_<tablo>_version_guard` ile, aynı işlemde yeniden `ENABLE`".

### YT-06 (Düşük) `GET /history` imleci mühürsüz

**Kanıt:** `HistoryCursor = int` (`app/api/v1/profit_settings.py:75`), yanıtta `str(page.next_cursor)` (`745`),
sorguda `revision < cursor` (`app/services/profit_settings.py:1115-1116`). Rapor uçları imleci AES-GCM ile
mühürleyip sorgu parmak iziyle bağlar (`profit.py` `_codec`, `_check_cursor`).

**Değerlendirme:** Güvenlik etkisi yok: sorgu kiracı ve hesapla süzülür, RLS altındadır; `revision` zaten
`GET /profit-settings`'te açık. PoC (Ek A.5): A kiracısı `cursor = 2^62` ile yalnız kendi kaydını görür. Sapma
tutarlılık ve ileride sıralama anahtarı değişirse kırılganlık açısından.

**Düzeltme:** Ya mevcut `cursor_codec` ile `("history", account_id, revision)` mühürlensin ve `cursor_invalid`
422 aynı biçimde dönsün, ya da ADR §5.1'e "geçmiş imleci düz sürüm numarasıdır, gizli değildir" notu eklensin.
Yanıtta `next_cursor` dizge, girdi tamsayı: belgede belirtilmeli.

### YT-07 (Düşük) Onay gösterilen etki tarihine bağlı değil

**Kanıt:** `_confirm` yalnız `confirmed: bool` görür (`app/services/profit_settings.py:626-636`). Panel 409'daki
`affects_from`'u gösterip aynı gövdeyi `confirm_past_change=true` ile yeniden gönderir (ADR §5.2); sunucu
onayın hangi tarih için alındığını bilmez. PoC (Ek A.6): onaylı gövde 2000-01-01 başlangıçla kabul edildi.

**Değerlendirme:** Aynı yetkili kullanıcı; bir güvenlik sınırı aşılmıyor. Risk istemci hatası ya da formun 409
ile yeniden gönderim arasında değişmesi: kullanıcı "1 Ekim" için onay verir, 2000'den itibaren değişir.
`expected_revision` gönderilmezse araya giren başka yöneticinin değişikliği de onayın dışında kalır (AB-03).

**Düzeltme:** İsteğe bağlı, sertleştirme: `confirm_past_change` yerine (ya da yanında) `confirm_affects_from:
date | "all"`; sunucu hesapladığı etki tarihi bununla eşleşmiyorsa yeniden 409. Panel her onaylı yazımda
`expected_revision` göndermeli (409 gövdesindeki `current_revision`).

### YT-08 (Düşük) Belge kayması

**Kanıt ve düzeltme:**
- `docs/12_kar_motoru.md:1147`: `past-change-confirmation-required`; kod, ADR-0007 §5.1 ve §8, ADR-0006 satır 281
  `settings-past-change-unconfirmed`. docs/12 düzeltilmeli (panel ajanı docs/12'yi de okuyabilir).
- ADR-0007 §4 satır 188 `ck_profit_settings_changes_replace` taslağı kodla (`0008:150-151`) uyumlu hale
  getirilmeli; migrasyon belgesi sapmayı açıklıyor (`0008:17-19`), ADR açıklamıyor.
- ADR-0007 §5.1 satır 235 `changed_by` "görünen adı" diyor; kod `{user_id, role}`. ADR güncellenmeli (sapma 3).
- K42 "Değişken gider değiştirmede yeni satır eskinin `created_at`'ini taşır" kuralı belgede yok (sapma 4).

### YT-09 (Düşük) Günlük kısıtları `defaults` için gevşek

**Kanıt:** `ck_profit_settings_changes_replace` `item = 'defaults' OR (...)` (`0008:150-151`): `defaults` kaydı
`record_id` ve `replaced_record_id` taşıyabilir; `ekle` için `default_desi_before IS NULL`, `geri_cek` için
`default_desi_after IS NULL` denetlenmiyor. Servis doğru yazıyor (`profit_settings.py:1062-1079`, test
`test_first_entry_exception_for_default_desi_only_from_null_to_a_value`); kısıt derinlemesine savunmadır.

**Düzeltme:**
`CHECK ((item = 'defaults' AND record_id IS NULL AND replaced_record_id IS NULL AND (action <> 'ekle' OR
default_desi_before IS NULL) AND (action <> 'geri_cek' OR default_desi_after IS NULL)) OR (item <> 'defaults' AND
(action = 'degistir') = (replaced_record_id IS NOT NULL)))`.

### YT-10 (Düşük) Test anlamsızlaşması ve eksik testler

**Kanıt:** `tests/test_profit_shipping_fees.py:276-282` eski kesin eşitliği (`period_net_profit ==
line_net_profit_total - 105 - 57 - 18`) dal koşuluna çevirdi: `if period.net_profit_partial: ... else: ...`.
Senaryo deterministiktir (`ProfitSettings()`, ayarsız): her zaman kısmi; `else` dalı ölü ve test hangi dalın
beklendiğini söylemiyor. Başka bir test eşiği gevşetilmedi (aşağıda §3.3).

Eksik testler: YT-01 (eşzamanlı okuma-yazım damgası), YT-02 (zincir maliyeti), YT-03 (başlıksız satırların
taşıması); `eşzamanlılık` başlıklı bölümde (`test_profit_settings_history_api.py:730`) yalnız bağımsız hesap
testi var, aynı anahtara eşzamanlı yazım testi yok (PoC A.2 bunun doğru çalıştığını gösterdi).

**Düzeltme:** `assert period.net_profit_partial is True` ve `assert period.period_net_profit is None` ile
sabitle; PoC A.1, A.2, A.4, A.7'nin `test_ok_*` biçimleri repo testine alınsın.

## 3. Doğru çalışanlar

### 3.1 Güvenlik

| Kontrol | Sonuç ve kanıt |
|---|---|
| RLS yeni tabloda | `profit_settings_changes` ENABLE + FORCE, `tenant_isolation` USING ve WITH CHECK (`0008:165-170`); test `test_journal_table_has_forced_rls_policy_index_and_least_privilege`, `test_journal_is_tenant_isolated_for_read_and_write` (bağlamsız 0 satır, sahip rol de FORCE altında, başka kiracı adına INSERT reddi). Bileşik FK `(marketplace_account_id, tenant_id)`. Taşıma INSERT'i RLS açılmadan önce; FORCE işlem sonunda geri (`0008:93-94, 177-178`). |
| IDOR/BOLA | Her uçta `_require_account`; servis sorgularında açık `tenant_id` + `marketplace_account_id` (`_scope`); `get_record` başka hesabın kimliğine None -> 404, 409 değil (test `test_other_tenants_record_ids_are_404_not_409`; PoC A.5: başka kiracının tarifesine DELETE 404, gövdede `affects_from` yok). Geçmişte kayıt ve üyelik sorguları da kiracı süzgeçli. |
| En az yetki | `netkar_app`: üç tabloda DELETE yok, tablo düzeyi UPDATE yok, yalnız dört kapanış sütununda UPDATE (`0008:172-173`); günlükte SELECT, INSERT (UPDATE, DELETE, TRUNCATE yok); `netkar_worker` günlükte yalnız SELECT; `netkar_sync_gate` ve PUBLIC erişimsiz (testli). INSERT boşluğu YT-04. |
| Tetikleyici ve SECURITY DEFINER | `profit_settings_version_guard` SECURITY INVOKER (varsayılan), yalnız `pg_catalog` işlevleri; arama yolu ele geçirme ya da yetki yükseltme yolu yok. Sahip rolü de bağlıyor (test `test_owner_role_is_bound_by_the_version_guard_trigger`): kapanmış satır ve iş alanları güncellenemez; `jsonb - text[]` karşılaştırması gelecekte eklenen sütunları da kapsar. |
| Yarış ve sürüm | Tüm yazımlar `begin_write` (`INSERT ON CONFLICT DO NOTHING` + `SELECT FOR UPDATE`) ile hesap başına sıralı; etkin anahtar kısmi tekil indeksle (`uq_*_active_version`), günlük `UNIQUE (marketplace_account_id, revision)` ile korunur. PoC A.2: ayarsız hesapta aynı anahtara iki eşzamanlı yazım (beklenen sürüm yok) sürüm 1 ve 2, tek etkin satır, ikincisi birincinin yerini alıyor, günlükte `ekle` + `degistir`. Sınır sayımları kilit altında (TOCTOU yok). |
| Onay atlatılamıyor | Kontrol sırası ADR §5.1 ile aynı (`profit_settings.py:334-367`): hız sınırı -> kilit/beklenen sürüm -> işlem türü -> değişmedi -> onay -> yazım -> günlük -> denetim -> commit. İlk giriş istisnası dar: tarifede yalnız `ekle` ve aynı anlaşmada etkin tarife 0; hizmet bedelinde etkin 0; desi yalnız `null` -> değer; giderde yok; değiştirme ve geri çekmede yok. İki adımlı kaçış (geri çek + yeniden ekle) geri çekme adımında onay ister. Değişmedi yanıtı onaysız 200 ama hiçbir şey yazmaz. Eşzamanlı iki "ilk giriş" kilit altında sıralanır; ikincisi onay ister. |
| 409 gövdeleri | `settings-past-change-unconfirmed`: yalnız `affects_from`, `affects_past`, `current_revision`; `settings-record-ended`: yalnız `current_id` (aynı hesabın); tutar ya da başka kiracı bilgisi yok (PoC A.5). |
| Denetim izi | Eylem adları `<kalem>.create/replace/retract`, `defaults.update`; meta kimlikler, etki tarihi, onay, sürüm; tutar anahtarı yok (`_identity`, `profit_settings.py:298-313`; test `test_audit_trail_carries_identities_only_never_amounts`). Değişmeyen ve reddedilen yazım denetlenmez. Not: gider adı (serbest metin) ADR gereği meta'da; KVKK açısından ad bilgisi değişmez satırda zaten durduğundan ileride yalnız `record_id` yeterli olabilir (bulgu değil, öneri). |
| Hız sınırı | Yazım uçları kiracı başına saatlik sayaç (409 ve değişmedi dahil sayılır; sayaç ayrı AUTOCOMMIT bağlantıda, geri alma onu silmez). `GET /history` okuma sayacını paylaşır (test `test_history_shares_the_read_rate_limit_counter`); `limit` 1-100, `cursor >= 1` (422 testli). |
| Kişisel veri | `changed_by` yalnız `{user_id, role}`; ad, e-posta yok (üyeler listesiyle aynı). Görüntüleyici geçmişte tutarları görür; zaten `GET /profit-settings`'te görüyor. |
| Migrasyon geri alınabilirliği | Downgrade tarihçe varsa (`revision_to IS NOT NULL` ya da `tasima` dışı günlük) bayraksız DURUR; işlem geri alınır, FORCE yerinde kalır (test `test_downgrade_is_refused_while_history_exists_and_the_database_is_left_untouched`); bayrak yalnız tam `"1"` (testli); bayrakla etkin satırlar ve değerleri korunur, eski tekil kısıtlar ve 0007 yetkileri geri gelir; upgrade/downgrade/upgrade boş ve dolu tabloda testli. Hata metni yedek komutunu veriyor. Kilit: ayar tabloları küçük; FK eklemeleri `users`, `tenants`, `marketplace_accounts` üzerinde işlem boyunca SHARE ROW EXCLUSIVE alır (kısa; canlıda `SET lock_timeout` önerilir). |
| Önceki bulgular | AO-02 KAPANDI (değişmez satır, geri çekme, günlük, kimlikli denetim, onay; ADR §8 PoC A.2'nin tersi testli). AO-03 KAPANDI (aşağıda). AD-02 okuma sınırı geçmişe de uygulanmış. AB-02 açık (YT-01'e katıldı). |

### 3.2 Alan doğruluğu

| Kural | Uygulama | Sonuç |
|---|---|---|
| K39 Rev.1 null kuralı | `aggregate.py`: `partial` ise `line_net_profit_total`, `period_net_profit`, marj None; `full_lines` bloğu her zaman | Uygun |
| I5 | `period_known_expenses_profit = Σ aktif satır known_expenses_profit - dönem düzeyi giderler`; tam dönemde `= donem_net_kar` | Uygun (özellik testi `assert_period_identities`, ayarlı ve ayarsız; betik `degismezler`) |
| I6 | Ürün toplamı - (dönem gideri - satışsız reklam) = dönem alanı | Uygun (aynı testler) |
| Motor ve API tutarlılığı | `PeriodTotalsOut`: iki alan `Amount | None`, yeni alan `Amount`; `test_report_golden_api.py` 46 reklamsız senaryoda API = motor kablo çıktısı birebir; `profit_views`'te bu alanları kullanan başka yer yok | Uygun |
| Altın senaryolar | 49 senaryo; betik bağımsız (`app` içe aktarmıyor), 170 elle değer, TAMAM; IZINLI_FARKLAR yalnız G29'un üç alanı; G49 elle doğrulandı (174,09 - 17,35 = 156,74) | Uygun |
| K44 damga | `settings_revision` beş rapor ucunda; ayarsızda 0 (başlık yoksa); değişmedi ve reddedilen yazım artırmaz (rollback, testli); her gerçek yazımda +1 | Uygun (eşzamanlı okuma YT-01; başlıksız taşıma YT-03) |
| K44 sürümle yükleme | `_in_force` `revision_from <= R < revision_to`; desi günlükten; `tasima` öncesi ve geleceği `RevisionUnavailable`; test 0-5 sürümün her birinde `summary` kuruşu kuruşuna aynı | Uygun |
| K42 işlemler | ekle / değiştir (eski `degistirildi`, yeni `replaces_id`) / geri çek / değişmedi; sınırlar etkin satırları sayar (200 etkin tarifede değiştirme 200, ekleme 422 testli) | Uygun |
| K43 etki tarihi | tarife ve hizmet bedeli başlangıç; gider değiştirmede min(eski, yeni); desi `null`; `is_past` İstanbul günü, bugün geçmiş değil | Uygun (ihtiyatlı alt sınır belgeyle aynı) |

### 3.3 Testlerin değiştirilmesi

Eski davranışa bağlı testler incelendi: `test_profit_settings_api.py` yardımcıları varsayılan olarak
`confirm_past_change: true` gönderiyor, onay kuralı ayrı `raw_*` yardımcılarıyla sınanıyor (makul);
`== {"revision": N}` tam eşitlikleri yeni alanlar nedeniyle `["revision"] == N`'e döndü ve yanına `action`,
`replaced_id`, `current_id` denetimleri eklendi (güçlendi); kiracılar arası DELETE denetimi kiracılar arası
kapanış UPDATE'ine döndü ve DELETE yetkisinin hiç olmadığı ayrı testte (eşdeğer ya da güçlü). Süre eşiği
(`test_summary_time_stays_linear_with_many_service_fee_versions`) ve kapsam eşiği (%100) değişmedi. Tek
anlamsızlaşma YT-10.

## 4. Uygulayıcının bildirdiği sapmalar

| No | Sapma | Karar | Gerekçe |
|---|---|---|---|
| 1 | Hata türü `settings-past-change-unconfirmed` (ADR), docs/12 `past-change-confirmation-required` | **Kabul** | ADR-0007 daha yeni ve API sözleşmesinin sahibi; diğer ayar hatalarıyla (`settings-revision-conflict`, `settings-record-ended`) aynı önek. docs/12 satır 1147 düzeltilmeli (YT-08). |
| 2 | `ck_profit_settings_changes_replace`'e `item = 'defaults'` istisnası | **Kabul** | ADR taslağı kendi içinde çelişkiliydi: K42 desi değişikliğini günlüğe `degistir` olarak yazdırıyor ama taslak kısıt `degistir` için `replaced_record_id` şart koşuyor; desinin satır kimliği yok. İstisna doğru ama fazla geniş: YT-09'daki daha sıkı kısıt önerilir; ADR §4 güncellenmeli. |
| 3 | `changed_by` yalnız `{user_id, role}` | **Kabul** | ADR "üyeler listesindeki gibi" diyor; üyeler listesi (`/v1/tenant/members`, `MemberOut`) de ad ya da e-posta döndürmüyor, kullanıcı satırları RLS ile yalnız kendine açık. Ad eklemek görüntüleyiciye yeni kişisel veri açardı (KVKK en aza indirme). Not: `role` bugünkü roldür, değişiklik anındaki değil; ADR'de bu da yazılmalı. |
| 4 | Değişken gider değiştirmede yeni satır eskinin `created_at`'ini taşıyor | **Kabul (koşullu)** | Amaç doğru ve gerekli: `load_bundle` giderleri `created_at, id` ile sıralıyor; bu olmasa değiştirilen gider listenin sonuna gider ve sürümle yükleme R'de ve R+1'de farklı sıra verirdi (test `test_expense_replace_keeps_definition_order_and_extends_the_end_date`). Bedeli: `created_at` artık "satırın eklendiği an" değil "tanımın ilk oluşturulduğu an"; adli incelemede yanıltıcı (gerçek an günlükte `changed_at` ve eski satırda `ended_at`). Koşul: K42 ve model belgesine yazılsın; uzun vadede ayrı `defined_at` ya da YT-02'deki `lineage_id` ile sıralama ve `created_at`'in gerçek ekleme anı olarak bırakılması önerilir. |
| 5 | İlk giriş istisnasında istemci onay gönderirse `past_change_confirmed = true` | **Kabul** | Alanın anlamı "kullanıcı geçmişi etkileyen bu yazımı açıkça onayladı"; istisnada da kullanıcı onayladıysa doğru kayıttır ve panel K43'ü önceden hesaplayıp pencere gösterebilir (ADR §5.2 madde 1). Onaysız ilk girişte `false` (testli). İsteğe bağlı: "onay gerekiyor muydu" ayrımı için günlüğe `confirmation_required` eklenebilir; panelin "geçmişi etkiledi (onaylı)" rozeti `affects_past AND past_change_confirmed` ile doğru çalışır. |

## 5. Merge engeli var mı: HAYIR

- Kritik, Yüksek ya da Orta bulgu yok. AO-02 ve AO-03 kapandı; ADR-0007 §8 kabul ölçütlerinin hepsi testle
  karşılanıyor.
- Rapor önbelleği (ADR-0006 §3.4) eklenmeden önce **YT-01** kapatılmalı (aksi halde Orta: yanlış anahtarlı
  önbellek girdisi).
- Hazırlık ya da canlı ortamda 0008 çalıştırılmadan önce **YT-03** taşıma düzeltmesi yapılmalı.
- YT-02 ve YT-04 birden çok kiracı canlıya alınmadan önce; diğerleri belge ve sertleştirme.

## Ek A. Kavram kanıtı özetleri

Dosya: `/tmp/claude-0/-home-user-hyt/9e0dcdb7-1ce4-5047-97d3-278f704913e7/scratchpad/test_poc_tarihce.py`.
Çalıştırma: `cd netkar/services/api && uv run python -m pytest -p tests.conftest -c pytest.ini --rootdir=. -q -s
<dosya>`. Sonuç: 9 geçti (10,1 sn + 3,1 sn).

- **A.1** `test_poc_stamp_and_rows_come_from_different_snapshots`: `db.execute` sarmalanır, başlık okunduktan sonra
  ikinci oturum hizmet bedelini 99,00 ile değiştirip commit eder. Çıktı `POC stamp: 1 [(Decimal('99.000000'),
  2)]`. `test_ok_as_of_filter_at_the_read_revision_would_close_the_race`: aynı veride `at_revision=1` 12,00 verir.
- **A.2** `test_ok_concurrent_same_key_writes_without_expectation_serialise`: iki eşzamanlı ilk yazım; çıktı
  `[(10, 1, 2, False), (20, 2, None, True)]`, günlük `[(1, 'ekle'), (2, 'degistir')]`.
- **A.3** `test_poc_app_role_can_insert_forged_history_rows`: `netkar_app` ile geçmiş `revision_from`, baştan
  kapalı satır, `tasima`, başka kiracı kullanıcısı `changed_by`, `revision_to = 1000000`: beşi kabul.
- **A.4** `test_poc_record_ended_successor_walk_is_one_query_per_link`: 200 halka 0,191 sn, 2000 halka 2,292 sn;
  yanıt doğru (`current_id` zincirin sonu).
- **A.5** `test_ok_history_cursor_is_plain_but_only_scopes_own_account`, `test_ok_conflict_bodies_do_not_leak_other_tenants_or_amounts`:
  sahte imleç yalnız kendi kaydı; 409 gövde anahtarları `affects_from, affects_past, current_revision` + problem
  alanları; başka kiracı kimliği 404.
- **A.6** `test_poc_confirmation_is_a_bare_boolean_not_bound_to_the_shown_date`: onaylı gövde 2000-01-01 ile 200.
- **A.7** `test_poc_rows_without_head_get_stamp_0_and_first_replace_fails`: `revision 0`, 1 etkin satır; `PUT`
  500, log `CheckViolation ck_service_fee_estimates_ended` (tutar yok, parametreler gizli).

## Ek B. Rapor ve altın API testleri

`uv run pytest tests/test_report_api.py tests/test_report_golden_api.py tests/test_feed_golden_database.py
tests/test_golden_script_guard.py -q`: 215 geçti, 6 atlandı (reklam senaryoları, bilinçli), 0 kaldı; 146,7 sn.
