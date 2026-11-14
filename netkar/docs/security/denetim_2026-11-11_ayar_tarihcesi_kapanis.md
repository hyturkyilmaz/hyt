# NetKâr Güvenlik Denetimi: Ayar tarihçesi kapanış denetimi (11 Kasım 2026)

Bağımsız denetçi; kodu ben yazmadım, kaynak kodu değiştirmedim. Ölçüt: OWASP ASVS L2 (V4 erişim denetimi, V8 veri
bütünlüğü, V5 girdi doğrulama), PostgreSQL RLS ve rol en az yetkisi.

**Kritik ya da yüksek bulgu yok.** Merge engeli yok. YT-01..YT-10'dan dokuzu kapandı, YT-04 kısmen kapandı (YK-01).
Yeni bulguların tamamı Düşük ya da Bilgi düzeyindedir.

- Denetlenen sürüm: `ebaf5d4` (dal `claude/dazzling-clarke-pfvf32`); inceleme kapsamı
  `git diff 0f12884..e320f7d -- netkar/services/api netkar/docs`. `e320f7d..ebaf5d4` arasında ayar tarihçesi koduna
  dokunan değişiklik yok (yalnız yapılandırma adları ve bir test yorum/biçim değişikliği).
- Commit'ler: `b5ee8e7` (YT düzeltmeleri, migrasyon 0009, 0008 yerinde düzeltme), `e320f7d` (halef zinciri
  LATERAL adımı, `ix_*_replaces (replaces_id, tenant_id, marketplace_account_id)`).
- Spesifikasyon: `docs/adr/0007-ayar-tarihcesi-ve-donem-rakami.md` §4, §4.1, §5.1 Revizyon 1;
  `docs/12_kar_motoru.md` K42-K44. Önceki denetim: `docs/security/denetim_2026-11-10_ayar_tarihcesi.md`.

## 0. Yöntem ve test sonuçları

- Kod okuma: `migrations/versions/0008_*.py`, `0009_*.py`, `app/services/profit_settings.py`,
  `app/api/v1/profit_settings.py`, `profit_settings_schemas.py`, `profit.py`, `app/services/profit_views.py`
  (`CursorCodec`), yetki migrasyonları 0001, 0006, 0007, `app/db/provision.py`.
- Testler (PostgreSQL 16, conftest yapılandırması çalıştı):
  `uv run pytest -q --no-cov tests/test_profit_settings_history_api.py tests/test_profit_settings_history_schema.py`
  sonucu **71 passed** (38,5 sn). `skip`, `xfail` ya da gevşek eşik yok (bkz. §5).
- Kavram kanıtı: geçici bir test dosyasıyla (çalıştırıldı ve silindi; repoda iz yok) dört deneme yapıldı, sonuçlar
  Ek A'da. Ayrıca `pg_auth_members`, `has_table_privilege` ve `pg_proc` sorgularıyla roller ve işlevler doğrulandı.

## 1. Özet tablo: önceki bulguların durumu

| No | Durum | Kanıt |
|---|---|---|
| YT-01 damga yarışı | **Kapandı** | `app/services/profit_settings.py:321` (`at = current if as_of is None else as_of`), `:260-268` (`_in_force` her zaman sürümle), `:364` (`revision=at`); desi başlıkla aynı satırdan (`:361`). `summary` tamlığı aynı demetten: `app/api/v1/profit.py:229` (`completeness_of(loaded.bundle, ...)`). Test: `test_bundle_rows_and_stamp_come_from_one_revision_despite_a_concurrent_commit` (üç yarış türü, parametreli), `test_summary_completeness_and_figures_come_from_the_same_settings_read`. |
| YT-02 halef zinciri | **Kapandı** | `profit_settings.py:748-781` tek özyinelemeli CTE, adım `LATERAL ... LIMIT 1` (`:766-772`), kapsam her adımda (`:769`), üst sınır `MAX_SUCCESSOR_CHAIN = 10_000` (`:77`, `:776`); indeks `0009:152-156`. Test: tek sorgu sayacı ve sınır (`test_successor_walk_uses_a_constant_number_of_queries_and_is_capped`), 2000 halka süresi. |
| YT-03 başlıksız taşıma | **Kapandı** | `0008:104-114` başlık önce `revision = 1` ile; savunma dalı kaldırıldı. Test: şema ve API (`test_upgrade_creates_the_head_...`, `test_moved_headless_account_has_a_stamp_and_the_first_replace_is_200_not_500`). |
| YT-04 INSERT ile sahteleme | **Kısmen** | Beş PoC denemesi kapandı (`0009:90-131`, test `test_app_role_cannot_forge_history_rows_the_five_audit_attempts`). Ancak sayaç bağı "eşit" olarak uygulandı, "bu işlemde artırılmış" olarak değil; sayaç da `netkar_app` tarafından serbestçe yazılabilir. İki yol hâlâ açık: **YK-01**. Bileşik FK uygulama rolü üyelik ekleyerek aşılabilir: **YK-02**. |
| YT-05 tetikleyici ve `SET NULL` | **Kapandı** (belge) | ADR-0007 §3 Revizyon 1 notu ve docs/12 K42 Revizyon 1: kimliksizleştirme tercihi, `DISABLE TRIGGER` deseni. |
| YT-06 imleç | **Kapandı** | `app/api/v1/profit_settings.py:98, 759-777, 792, 817`; AAD `tenant|account|settings-history` (`profit_views.py:139, 145, 153`). Test: `test_history_cursor_is_sealed_and_bound_to_tenant_account_and_query`. |
| YT-07 onay | **Kapandı** | `profit_settings.py:648-668` (`confirm != expected` ise 409), API sorgu deseni `profit_settings.py:83-90`, `confirm_dep` `:109-129`, gövde `profit_settings_schemas.py:91-101`. Panel `confirm_affects_from` ve `expected_revision` gönderiyor (`apps/web/src/components/settings/*-section.tsx`). Yan not: YK-04. |
| YT-08 belge kayması | **Kapandı** | docs/12 hata adı düzeltildi (`docs/12_kar_motoru.md:1184` yalnız revizyon notunda eski ad); ADR §4 `ck_..._replace`, §5.1 `changed_by {user_id, role}` (ADR satır 293), K42 `created_at` devralma kuralı. Küçük yeni kayma: YK-05. |
| YT-09 günlük kısıtı | **Kapandı** | `0009:139-145`; test `test_journal_defaults_rows_are_tight_ck_replace`. |
| YT-10 test anlamsızlaşması | **Kapandı** | `tests/test_profit_shipping_fees.py` dal sabitlendi (`assert period.net_profit_partial is True`); PoC A.1, A.2 (`test_concurrent_writes_to_the_same_key_serialise_per_account`), A.4, A.7 repo testi oldu. |

## 2. Yeni bulgular

| No | Önem | Başlık | Konum |
|---|---|---|---|
| YK-01 | Düşük | Sıra tetikleyicileri sayacın bu işlemde artırıldığını denetlemiyor; `netkar_app` sayacı geri sarıp geçmiş sürüme ya da artırmadan yayımlanmış sürüme satır ekleyebiliyor | `0009:77-84, 101-106, 123-128`; `0007:80, 149` |
| YK-02 | Bilgi | Bileşik FK (`changed_by`, `tenant_id`) uygulama rolü üyelik ekleyerek aşılabilir | `0009:161-164`; `0001:135` |
| YK-03 | Bilgi | Üyelik silme artık FK'ye takılıyor (her rol için); ADR §5.1 "üyelik silindiyse `null`" ifadesiyle çelişiyor; ileride üye çıkarma ve imha akışı için tuzak | `0009:161-164`; ADR-0007 satır 293 |
| YK-04 | Bilgi | Gövdedeki `confirm_affects_from` sorgudakinden gevşek ayrıştırılıyor (saat dilimli tarih-saat, Unix zaman damgası dizgesi) | `app/api/v1/profit_settings_schemas.py:91-101` |
| YK-05 | Bilgi | Belge ve sertleştirme: ADR §4.1 indeks tanımı eski, "aynı işlemde artırılmış" iddiası koda yansımıyor; tetikleyici işlevlerinde `search_path` sabit değil | ADR-0007 §4.1 (satır ~262-269); `0009:64-132` |

### YK-01 (Düşük) Sayaç bağı "eşit", "bu işlemde artırılmış" değil

**Kanıt:** `profit_settings_insert_guard` yalnız `NEW.revision_from = profit_settings.revision` şartını arar
(`0009:101-106`); kapanış kuralı (`0009:77-84`) ve günlük kuralı (`0009:123-128`) da aynı eşitliği kullanır. ADR §4.1
ve migrasyon belgesi (`0009:10-12`) "aynı işlemde artırılmış ayar sayacına eşit" der, ama işlem bağı yoktur.
Üstelik `netkar_app` `profit_settings` üzerinde tablo düzeyi `UPDATE` yetkisine sahiptir (`0007:149`) ve sayaç
üzerinde tekdüzelik denetimi yoktur (yalnız `CHECK (revision >= 1)`, `0007:80`; tabloda tetikleyici yok).

PoC (Ek A, `netkar_app`, sayaç 5, ikisi de **kabul edildi**):
- A: sayaç artırılmadan `revision_from = 5` tarife satırı ve günlük kaydı eklendi. Yayımlanmış sürüm 5'in
  içeriği geriye dönük değişir; K44 "aynı sürüm aynı sonucu verir" ve rapor damgası o sürüm için yanlışlanır.
- B: `UPDATE profit_settings SET revision = 2`, `revision_from = 2` sahte satır ve günlük, sonra `revision = 5`.
  Sonuç: sayaç 5, sahte satır sürüm 2'den beri "etkin". Bu, YT-04'ün birinci denemesinin (geçmiş
  `revision_from`) iki ek ifadeyle aynen yapılabilmesidir.

Gerçek veride günlük tekilliği (`uq_profit_settings_changes_revision`) sahte günlük kaydını engeller; ama saldırgan
günlüğü atlayıp yalnız satırı ekleyebilir, sürümle yükleme (`load_bundle(as_of)`) satırı yine görür.

**Etki ve önem:** Önkoşul uygulama rolünün ele geçirilmesi ya da hatalı kod (YT-04 ile aynı tehdit modeli);
bu yüzden Düşük. Ancak YT-04'ün düzeltme hedefi tam olarak bu sınıftı ve testler bu iki yolu denemiyor; belge
olmayan bir güvence iddia ediyor.

**Düzeltme:** sayaca işlem bağı ve tekdüzelik eklenmeli (0010, geri alınabilir):
1. `profit_settings`'e `revision_xact xid8` sütunu ve `BEFORE INSERT OR UPDATE` tetikleyicisi. `netkar_app` için:
   INSERT'te `NEW.revision = 1`; UPDATE'te `NEW.revision IN (OLD.revision, OLD.revision + 1)`. Her rol için
   tetikleyici `revision_xact`'i kendisi atar: sürüm arttıysa (ya da INSERT) `pg_current_xact_id()`, değilse
   `OLD.revision_xact` (istemci değeri yok sayılır; böylece sütun sahtelenemez).
2. Üç sıra kuralında `head` ile birlikte `revision_xact` okunsun ve `revision_xact = pg_current_xact_id()` şartı
   eklensin (uygulama `SAVEPOINT` kullanmıyor, `begin_nested` yok; PostgreSQL 16 `xid8` destekler). Varsayılan desi
   yazımının aynı işlemdeki ikinci başlık UPDATE'i (`profit_settings.py:1117` civarı) sürümü değiştirmediği için
   `revision_xact` korunur ve akış bozulmaz.
3. Test: Ek A'daki A ve B denemeleri `CheckViolation` vermeli; dürüst yazım dizisi testi
   (`test_app_role_honest_write_sequence_still_passes_the_guards`) başlığı önce artıracak biçimde güncellenmeli
   (bugün sayacı artırmadan kapanış ve ekleme yaptığı için yeni kuralla düşer; bu, testin de "işlemde artırılmış"
   şartını sınamadığını gösterir).
4. Bu yapılmayacaksa ADR §4.1 ve `0009:10-12` "aynı işlemde artırılmış" ifadesini "sayaca eşit" olarak düzeltip
   kalan riski açıkça kabul etmeli.

### YK-02 (Bilgi) Bileşik FK uygulama rolü üyelik ekleyerek aşılabilir

**Kanıt:** `fk_profit_settings_changes_member` (`0009:161-164`) başka kiracının kullanıcısını engelliyor (test
`test_journal_changed_by_must_be_a_member_of_the_row_tenant_for_every_role`). Ama `netkar_app` `memberships`
üzerinde `INSERT` yetkisine sahiptir (`0001:135`; davet akışı için gerekli). PoC C: `netkar_app`, A kiracısı
bağlamında B kiracısının kullanıcısına A'da `viewer` üyeliği ekleyip aynı işlemde `changed_by = B kullanıcısı`
günlük kaydı yazdı: kabul edildi (RLS `WITH CHECK` yalnız `tenant_id`'yi denetler).

**Değerlendirme:** FK kod hatasına karşı (yanlış kullanıcı kimliği) etkili; ele geçirilmiş uygulama rolüne karşı
değil. Ek bir iz bırakır (üyelik satırı), bu yüzden Bilgi.

**Düzeltme:** ADR §4.1'e "FK hatalı koda karşı güvencedir; ele geçirilmiş uygulama rolüne karşı değil (rol üyelik
ekleyebilir)" notu. İstenirse günlük tetikleyicisi `changed_by` üyeliğinin `created_at < now()` (aynı işlemde
oluşturulmamış) olmasını da arayabilir.

### YK-03 (Bilgi) Üyelik silme FK'ye takılıyor; ADR'de çelişki

**Kanıt:** PoC D: günlükte kaydı olan kullanıcının üyeliğini yönetici bağlantısıyla silmek
`ForeignKeyViolation` verdi (FK `NO ACTION`, `0009:161-164`). Bugün üyelik silen kod yolu yok (`netkar_app` ve
`netkar_auth` için `DELETE` yok; `app/` içinde `DELETE FROM memberships` yok). ADR-0007 satır 293 ise
`changed_by.role` için "üyelik silindiyse `null`" diyor: FK varken bu durum oluşamaz.

**K42 ile çakışma:** Yok. Günlük tablosunda UPDATE tetikleyicisi yok ve FK referans eylemi `NO ACTION` olduğu için
silme referans veren tabloda UPDATE üretmez; YT-05'teki `SET NULL` tuzağı burada doğmaz. `ON DELETE SET NULL`
seçilirse `ck_profit_settings_changes_actor` (`0008:167`) `tasima` dışı kayıtta yine reddeder.

**Düzeltme:** ADR satır 293'teki "üyelik silindiyse `null`" ibaresi "üyelik silinemez (0009 FK); üye çıkarma
özelliği üyeliği pasifleştirerek yapılmalı" olarak düzeltilmeli. İleride kiracı imhası (KVKK) iş akışı
`profit_settings_changes`'i üyeliklerden ÖNCE silmeli; imha runbook'una eklenmeli.

### YK-04 (Bilgi) Gövde onayı sorgudakinden gevşek ayrıştırılıyor

**Kanıt:** Sorgu parametresi katı desenle (`^(all|[0-9]{4}-[0-9]{2}-[0-9]{2})$`, `profit_settings.py:86`)
doğrulanıyor; gövde alanı `date | Literal["all"] | None` ve yalnız "dizge olsun" ön denetimi
(`profit_settings_schemas.py:91-101`, `_require_text` `:53-56`). Pydantic esnek modda şunları kabul ediyor
(denendi): `"2026-01-01T00:00:00"`, `"2026-01-01T00:00:00+03:00"` (saat dilimi yok sayılır, 2026-01-01),
`"2026-01-01T00:00:00Z"`, `"1735689600"` (Unix zaman damgası, 2025-01-01). Reddedilenler: `"2026-01-01T05:00:00"`,
`"20260101"`, `"ALL"`, baştaki boşluk.

**Değerlendirme:** Onay atlatılamaz: her biçim sunucunun hesapladığı tarihle (`profit_settings.py:665-666`)
karşılaştırılır; `"all"` tarihli kayıtta, tarih de varsayılan desi kaydında reddedilir (testli). Eksik onay 409,
ilk giriş istisnasında eşleşmeyen onay da 409. Sorun yalnız sözleşme tutarlılığı (ADR "YYYY-AA-GG" diyor).

**Düzeltme:** Gövde ön doğrulayıcısı sorgudakiyle aynı düzenli ifadeyi uygulasın (`all` ya da tam
`YYYY-MM-DD`), aksi halde `date_invalid`; test `test_confirmation_must_match_the_affects_from_the_server_computed`
çöp listesine `"2026-01-01T00:00:00+03:00"` ve `"1735689600"` eklensin.

### YK-05 (Bilgi) Belge kayması ve küçük sertleştirme

- ADR-0007 §4.1 YT-02 maddesi indeksi `(replaces_id) WHERE replaces_id IS NOT NULL` diye yazıyor; `e320f7d` sonrası
  gerçek tanım `(replaces_id, tenant_id, marketplace_account_id) WHERE replaces_id IS NOT NULL` (`0009:152-156`,
  test `test_replaces_indexes_exist_and_are_partial`). ADR güncellenmeli.
- ADR §4.1 YT-04 maddesi "aynı işlemde artırılmış" diyor: bkz. YK-01.
- Tetikleyici işlevleri `SECURITY INVOKER` (doğru; `prosecdef = false`) ve tabloyu `public.profit_settings` diye
  nitelikli adlandırıyor; `SET search_path` yok. Çağıran rolün kendi `search_path`'i yetki yükseltmesi sağlamaz
  (işlev çağıranın haklarıyla çalışır), risk pratikte yok. Tutarlılık için 0006'daki `sync_gate` işlevi gibi
  `SET search_path = pg_catalog, public` eklenmesi önerilir.

## 3. Kontrol listesi yanıtları

**2. `current_user = 'netkar_app'` sapması.**
- Yetki taraması (`has_table_privilege`; `profit_settings`, üç sürümlü tablo, günlük): INSERT/UPDATE/DELETE/TRUNCATE
  yalnız `netkar_app`'te (profit_settings INSERT+UPDATE, üç tabloda INSERT, günlükte INSERT; sürümlü tablolarda
  UPDATE yalnız dört kapanış sütununda, `0008:192-193`). `netkar_worker` (`0007:151`, `0008:195`), `netkar_sync_gate`,
  `netkar_auth` ve PUBLIC'te yazma yetkisi **yok**. Bu yüzden kurallar başka çalışma zamanı rolüyle atlatılamaz.
- Rol üyeliği: `netkar_app` hiçbir rolün üyesi değil (`pg_auth_members` yalnız `netkar_owner -> netkar_auth,
  netkar_sync_gate`, `INHERIT FALSE`); `SET ROLE` ile `current_user`'ı değiştirerek kaçamaz. Roller `NOBYPASSRLS`
  (`provision.py:35`).
- İşlevler `SECURITY INVOKER`, sahibi `netkar_owner`, `proconfig` boş. Başlık okuması RLS altında yapılır;
  `app.tenant_id` kurulmamışsa ya da başka kiracıysa `head IS NULL` ve kural **reddeder** (kapalı başarısızlık;
  testte `add_change(conn, b, 5)` denemesi).
- Sahip rol ve süper kullanıcı muafiyeti bilinçli ve kabul edilebilir (tetikleyiciyi zaten kapatabilirler);
  ADR §4.1'de gerekçeli. Değişmezlik tetikleyicisi herkesi bağlıyor (testli). Kalan açık: YK-01.

**3. Bileşik FK.** `memberships` üzerinde `uq_memberships_user_tenant UNIQUE (user_id, tenant_id)` var
(`0001:56`), FK geçerli. Üyelik silinince: `ForeignKeyViolation` (YK-03). K42 değişmezlik tetikleyicisiyle çakışma
yok (gerekçe YK-03). MATCH SIMPLE ile `changed_by IS NULL` yalnız `tasima`'da (`ck_..._actor`), `tasima`'yı da
uygulama rolü yazamıyor. Atlatma yolu: YK-02.

**4. YT-07 `confirm_affects_from`.** Eksik: geçmiş etkili, istisnasız yazımda 409 (`profit_settings.py:662-665`). Yanlış biçim: sorguda
422 `date_invalid`, gövdede 422 (YK-04'teki gevşek biçimler hariç; onları da sunucu tarihiyle karşılaştırır). Saat
dilimi: etki tarihi takvim günü (`date`), karşılaştırma gün eşitliği; `+03:00` ekli dizge yine aynı güne iner,
atlatma sağlamaz. `"all"` tarihli kayıtta: reddedilir (`expected` tarih, `"all" != date`; testli, gövde ve
DELETE sorgusu). Çıplak `confirm_past_change=true`: etkisiz (testli). Gelecek tarihte başıboş onay yok sayılır
(testli). Sonuç: onay atlatılamıyor. Not: 409 gövdesi `affects_from`'u döndürdüğü için istemci onayı otomatik
yansıtabilir; bu tasarım gereği panelin sorumluluğudur (panel kullanıcıya gösteriyor ve `expected_revision`
gönderiyor). Sunucu `expected_revision`'ı onaylı yazımda zorunlu kılmıyor (önceki AB-03); öneri olarak kalır.

**5. YT-06 imleç.** AAD `"{tenant_id}|{account_id}|" + "settings-history"` (`profit_views.py:139, 145, 153`),
anahtar `derive_key(master, "report-cursor")` (`:138`); şifreli yük tam olarak 1 dizge ve sürüm `1..2^62` ASCII
tamsayı (`profit_settings.py:765-768`). Rapor imleçleri `products|`, `lines|`, `alerts|` önekli parmak izleri
kullandığı için `settings-history` ile çakışamaz; kiracı ve hesap UUID'leri sabit uzunlukta, bağlama dizgesi
belirsiz değil. Test: başka kiracının imleci, başka sorgunun (`products|...`) doğru mühürlü imleci, kurcalanmış,
kısaltılmış, düz sayı ve geçersiz içerikli imleçler 422 `cursor_invalid`. Anahtarın rapor imleçleriyle paylaşılması
parmak izi ayrımıyla güvenli; ayrı amaç etiketi gerekmez.

**6. `e320f7d`.** Çapa (`:760-763`) ve LATERAL adım (`:769`) `_scope(model, tenant_id, account_id)` ile süzülüyor
(`:722-723`, kiracı ve hesap eşitliği); üstüne RLS. `replaces_id` FK'si tek sütunlu olduğu için başka kiracının
satırı bir A satırını "yerini aldığı" diye gösterebilir; kapsam süzgeci bunu zincirden dışlar, sızıntı yok.
`MAX_SUCCESSOR_CHAIN` çağrı anında modül değişkeninden okunuyor; çapa derinliği 1 ve `depth < MAX` ile en çok MAX
satır; test sınırı 5'e indirip tam sınırı ve aşımı doğruluyor. Döngü olamaz (`replaces_id` ekleme anında var olan
satırı gösterir ve sonradan güncellenemez; sınır yine de korur). 0009 downgrade indeksi adıyla düşürüyor
(`0009:187`), sütun değişikliği etkilemiyor; `test_0009_downgrade_removes_only_its_objects_and_roundtrips` geçti.

**7. Testler.** Yeni testler eski kodda başarısız olacak biçimde yazılmış: çıplak bool 409 bekliyor, imleç
`isdigit()` olmamalı, zincir tek sorgu sayacı, yarış testi başlıktan sonra commit ediyor ve satırın `revision_from`
değerini doğruluyor, beş sahte yazım `CheckViolation`/`ForeignKeyViolation` bekliyor. `skip`/`xfail` yok. Değişen
eski testler mekanik (`confirm_past_change` yerine `confirmed(...)` yardımcısı). İki küçük gevşeme, ikisi de
gerekçeli: (a) `test_profit_settings_schema.py`'de B kiracısı adına uygulama rolü eklemesi artık
`InsufficientPrivilege` ya da `CheckViolation` kabul ediyor (0009 tetikleyicisi RLS `WITH CHECK`'ten önce
çalışıyor); RLS politikası sahip rolle ayrı bir `InsufficientPrivilege` testiyle hâlâ sınanıyor. (b)
`test_profit_settings_api_denetim.py`'de yansıma taraması rastgele `request_id`'yi dışlıyor (yanlış pozitif
düzeltmesi; gövdenin geri kalanı taranıyor). Eksik: YK-01'in iki yolu ve YK-04 biçimleri test edilmiyor.

## 4. Doğru çalışanlar

| Alan | Gözlem |
|---|---|
| Tek sürüm okuma (K44) | Satırlar başlıkta okunan sürümle süzülüyor; değişmez satırlar sayesinde READ COMMITTED altında tutarlı görünüm. Damga, rakamlar ve tamlık tek demetten. |
| Yazım sırası | `finish_write` başlığı satır, kapanış ve günlükten önce `flush` ediyor (`profit_settings.py:589-602`); yeni başlıkta INSERT doğrudan yürütülüyor (`:558-572`). Tetikleyicilerle uyumlu, 71 test geçti. |
| Değişmezlik | Kapanmış satır ve iş alanları sahip rol dahil herkese kapalı; 0009 bu gövdeyi koruyup yalnız uygulama rolüne kapanış sürümü kuralı ekliyor. |
| Günlük sertleştirmesi | `tasima` uygulama rolüne kapalı, günlük sürümü sayaca bağlı, `defaults` kısıtı sıkı (YT-09 önerisiyle birebir). |
| En az yetki | Yazma yetkisi yalnız `netkar_app`'te; worker ve sync_gate salt okur ya da erişimsiz; rol üyeliği kaçışı yok; işlevler invoker haklı. |
| Halef zinciri | Sabit tek sorgu, kapsamlı LATERAL adım, bileşik kısmi indeks, üst sınır; 409 yanıtı `current_id` dışında iç ayrıntı sızdırmıyor. |
| İmleç | AES-GCM mühür, kiracı/hesap/sorgu bağlı AAD, içerik doğrulanmadan ayrıştırılmıyor, girdi yansıtılmıyor. |
| Onay | Sunucunun hesapladığı etki tarihine bağlı; `all` ve tarih karşılıklı reddediliyor; eksik ve eşleşmeyen onayda hiçbir şey yazılmıyor ve denetim kaydı düşmüyor (testli). |
| Migrasyon | 0009 geri alınabilir, veri kaybı yok, roundtrip testli; 0008 yerinde düzeltmesi hiçbir ortamda çalışmamış sürüme yapıldı (belgeli). |
| Belge | ADR-0007 ve docs/12 Revizyon 1 notları eski içeriği silmeden eklenmiş; sapma (`current_user` kuralı) gerekçeli. |

## 5. Merge engeli var mı: HAYIR

- YK-01, birden çok kiracı canlıya alınmadan ve rapor önbelleği (ADR-0006 §3.4) eklenmeden önce kapatılmalı;
  önbellek anahtarı `settings_revision` içerdiğinde geriye dönük değiştirilmiş bir sürüm yanlış önbellek girdisi
  bırakır. Kapatılmayacaksa ADR §4.1 ifadesi düzeltilmeli.
- YK-02..YK-05 belge ve sertleştirme; uygun bir sonraki işte.

## Ek A. Kavram kanıtı özetleri (geçici test, `netkar_app` bağlantısı `role_tx` ile, işlem sonunda geri alındı)

Ortak tohum: `seed_forgery_target` (A kiracısı sayaç 5, B kiracısı ayrı). Sonuçlar aynı işlem içinde okundu.

| Deneme | Adımlar | Sonuç |
|---|---|---|
| A | `forged_tariff(conn, a, 5, None)`; `add_change(conn, a, 5)` (sayaç artırılmadı) | Kabul: `revision_from = 5` sahte satır, sayaç 5 |
| B | `UPDATE profit_settings SET revision = 2`; `forged_tariff(conn, a, 2, None)`; `add_change(conn, a, 2)`; `UPDATE ... SET revision = 5` | Kabul: `revision_from = 2` sahte satır, sayaç 5 |
| C | `INSERT INTO memberships (user_id, tenant_id, role) VALUES (B kullanıcısı, A kiracısı, 'viewer')`; `add_change(conn, a, 5, changed_by=B kullanıcısı)` | Kabul: 1 kayıt |
| D | Yönetici: günlükte kaydı olan kullanıcının üyeliğini `DELETE` | `ForeignKeyViolation` |
| Yetki | `has_table_privilege` beş rol x beş tablo x dört yetki | Yazma yalnız `netkar_app` |
| Rol | `pg_auth_members` | `netkar_app` hiçbir rolün üyesi değil |
| İşlev | `pg_proc` | Üç guard işlevi `prosecdef = false`, sahip `netkar_owner`, `proconfig` boş |
