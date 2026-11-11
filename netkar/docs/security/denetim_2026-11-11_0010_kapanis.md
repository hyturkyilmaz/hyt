# NetTablo Güvenlik Denetimi: 0010 sayaç bağı ve ayar formu sunucu bilgileri (11 Kasım 2026)

Kapsam: `48e9755` (migrasyon 0010, YK-01..YK-05) ve `689a14f` (GET profit-settings: `earliest_order_day`,
`today_istanbul`, `vat_rates`; web formu). İnceleme `git checkout --detach 48e9755` üzerinde yapıldı.
Önceki denetim: `docs/security/denetim_2026-11-11_ayar_tarihcesi_kapanis.md`.

Denetçi bağımsızdır; kaynak kod değiştirilmedi, commit yapılmadı. Kavram kanıtı geçici bir test dosyasıyla
(`netkar_app` bağlantısı, `role_tx`, işlem sonunda geri alındı) koşturuldu ve sonra silindi.

## Kritik ya da yüksek bulgu: YOK

Kritik ya da yüksek önemde bulgu yoktur. En önemli bulgu ZK-01'dir (Düşük, YK-01 ile aynı tehdit modeli:
uygulama rolünün ele geçirilmesi ya da hatalı kod): YK-01'in "geri sarma" yolu sayaç sütunu üzerinden kapandı,
ama başlık satırının hesap anahtarı değiştirilerek sayaç yine 1'e indirilebiliyor.

## 0. Yöntem ve test sonuçları

- `git show 48e9755`, `git show 689a14f` (backend ve web dosyaları), 0007, 0008, 0009 migrasyonları, rol
  kurulumu (`app/db/provision.py`), yazım akışı (`app/services/profit_settings.py:575-628`).
- İstenen üç test dosyası: `uv run pytest -q --no-cov tests/test_profit_settings_history_schema.py
  tests/test_profit_settings_history_api.py tests/test_profit_settings_api.py` sonucu **161 geçti** (74,7 sn).
- Geçici PoC (Ek A): ZK-01 yolu `netkar_app` ile hatasız yürüdü; ZK-02 (aynı işlemde 50 kez +1) geçti.

## 1. Önceki bulguların durumu

| No | Önceki önem | Durum | Not |
|----|-------------|-------|-----|
| YK-01 PoC A (sayaç artırılmadan yayımlanmış sürüme ekleme) | Düşük | Kapandı | Üç kural `revision_xact = pg_current_xact_id()` istiyor; test `test_app_role_cannot_add_rows_to_a_published_revision_without_bumping_the_counter` |
| YK-01 PoC B (sayacı geri sarma) | Düşük | Kısmen kapandı | `revision` sütunu üzerinden geri sarma reddediliyor; başlık satırını başka hesaba taşıyıp yeniden 1 ile ekleme yolu açık (ZK-01) |
| YK-02 | Bilgi | Belgelendi | ADR-0007 Revizyon 3 |
| YK-03 | Bilgi | Belgelendi | ADR-0007 Revizyon 3 |
| YK-04 | Bilgi | Kapandı | `_STRICT_DATE` yalnız ASCII `[0-9]{4}-[0-9]{2}-[0-9]{2}`, sonra `date` ayrıştırması; `all` ayrı |
| YK-05 | Bilgi | Kapandı | Dört işlevde `SET search_path = pg_catalog, public`; tablo başvuruları `public.` ile nitelenmiş |

## 2. Yeni bulgular

| No | Önem | Başlık | Konum |
|----|------|--------|-------|
| ZK-01 | Düşük | Başlık satırının `marketplace_account_id` alanı değiştirilip hesaba yeni başlık (`revision = 1`) eklenerek sayaç geri sarılabiliyor; yayımlanmış sürüm 1'e satır ve günlük eklenebiliyor | `0010:59-80` (UPDATE dalı 67-75); `0007:149`; `0004:57` |
| ZK-02 | Bilgi | "Atlama reddedilir" yalnız deyim başına geçerli; aynı işlemde sayaç istenen kadar artırılabiliyor | `0010:68-70`; `0010:12-13` (belge) |
| ZK-03 | Bilgi | Muafiyet "netkar_app dışındaki her rol" biçiminde; ileride yazma yetkisi alacak her yeni rol sıra kurallarından sessizce muaf olur | `0010:63, 68, 97, 120, 147` |
| ZK-04 | Bilgi | Downgrade 0009 gövdelerini dosyadan `importlib` ile yüklüyor; dosya adı ve sabit adlarına bağlı | `0010:169-176, 190-194` |
| ZK-05 | Bilgi | `earliest_order_day` IDOR testi yalnız kiracılar arası; aynı kiracıda ikinci hesap senaryosu test edilmiyor (kod doğru) | `tests/test_profit_settings_api.py:722-731` |

### ZK-01 (Düşük) Başlık satırı başka hesaba taşınarak sayaç 1'e indirilebiliyor

**Bulgu.** `profit_settings_head_guard` UPDATE dalında yalnız `revision` alanına bakar (`0010:67-75`);
`marketplace_account_id`, `tenant_id`, `id` değişimini denetlemez. `netkar_app` tabloda tüm sütunlar için UPDATE
yetkisine sahiptir (`0007:149`: `GRANT SELECT, INSERT, UPDATE ON profit_settings`) ve kendi kiracısında yeni
pazaryeri hesabı satırı ekleyebilir (`0004:57`: `GRANT SELECT, INSERT, UPDATE ON marketplace_accounts`;
benzersizlik yalnız canlı satıcıda, `0004:51`). Bileşik FK yalnız aynı kiracıdaki hesabı şart koşar, RLS de
kiracı değişimini engeller; aynı kiracı içinde taşıma serbesttir.

**Kavram kanıtı (doğrulandı, Ek A).** A hesabının sayacı 5, sürüm 1 satırları etkin:

1. Aynı kiracıda ikinci hesap satırı A2 (iptal durumlu da olur; uygulama rolü kendisi ekleyebilir).
2. `UPDATE profit_settings SET marketplace_account_id = A2 WHERE marketplace_account_id = A` (sürüm aynı:
   tetikleyici geçirir).
3. `INSERT INTO profit_settings (..., marketplace_account_id, revision) VALUES (..., A, 1)` (INSERT kuralı
   yalnız `revision = 1` ister; `revision_xact` bu işleme atanır).
4. `INSERT INTO cargo_tariffs (revision_from = 1, ...)` ve `INSERT INTO profit_settings_changes (revision = 1)`:
   ikisi de geçti. Sonuç: A için yayımlanmış sürüm 1'e sahte satır ve günlük kaydı, A'nın sayacı 5'ten 1'e.

Bu, YK-01 PoC B'nin (geri sar, geçmiş sürüme satır ekle) başka bir anahtar üzerinden aynısıdır. Ek yan etki:
A2'nin başlığı A'nın sayacını (5) devralır; A2 için sürüm 5'ten başlayan, A'nın geçmişiyle karışan bir tarihçe
yazılabilir. Dürüst uygulama kodunda bu alanı değiştiren yol yoktur (`begin_write` yalnız ekler ve kilitler,
`finish_write` yalnız `revision`, `updated_by`, `updated_at` yazar); risk yalnız ele geçirilmiş rol ya da hatalı
kod içindir. Bu yüzden önem YK-01 ile aynı tutuldu: **Düşük**. Ancak kapanış iddiası ("sayaç geri sarılamaz",
`0010:17`) bu yol açıkken doğru değildir.

**Düzeltme (0011, geri alınabilir):**

1. Sütun düzeyinde yetki (asıl önlem):
   ```sql
   REVOKE UPDATE ON profit_settings FROM netkar_app;
   GRANT UPDATE (default_desi, revision, updated_by, updated_at) ON profit_settings TO netkar_app;
   ```
   `SELECT ... FOR UPDATE` için en az bir sütunda UPDATE yetkisi yeterlidir; ORM yalnız değişen sütunları
   yazdığı için dürüst akış etkilenmez (`default_desi` yazımı ve `finish_write`).
2. Tetikleyicide her rol için anahtar değişmezliği (derinlemesine savunma; sahip rol de bağlanır):
   ```sql
   IF NEW.id <> OLD.id OR NEW.tenant_id <> OLD.tenant_id
      OR NEW.marketplace_account_id <> OLD.marketplace_account_id THEN
       RAISE EXCEPTION 'ayar basliginin hesap anahtari degistirilemez (K42)' USING ERRCODE = 'check_violation';
   END IF;
   ```
3. İsteğe bağlı: `netkar_app` INSERT'inde, hesap için sürümlü tablolarda ya da günlükte satır varsa reddet
   (başlıksız geçmiş olmamalı; 0009 göçü başlığı zaten oluşturur).
4. Test: yukarıdaki dört adımlı yol `netkar_app` ile `InsufficientPrivilege` ya da `CheckViolation` vermeli.

### ZK-02 (Bilgi) Aynı işlemde sayaç birden çok kez artırılabiliyor

**Bulgu.** Kural `NEW.revision IN (OLD.revision, OLD.revision + 1)` deyim başına değerlendirilir. Aynı işlemde
50 ayrı `UPDATE ... SET revision = revision + 1` geçti (5'ten 55'e). Belge (`0010:12-13`, commit mesajı)
"atlama reddedilir" diyor. Etki: geçmiş sürüme satır eklenemez (her satır en yeni sayaçla yazılır), yalnız
günlüğü ve satırı olmayan boş sürümler oluşur; istemcinin 409 karşılaştırması bozulmaz.

**Düzeltme:** Uygulama rolü için işlem başına en fazla bir artış:
```sql
IF current_user = 'netkar_app' AND NEW.revision <> OLD.revision
   AND OLD.revision_xact = pg_current_xact_id() THEN
    RAISE EXCEPTION 'ayar sayaci bir islemde yalniz bir kez artar (K42)' USING ERRCODE = 'check_violation';
END IF;
```
Dürüst akış uyumludur: `finish_write` işlem başına bir kez artırır, yeni başlık oluşturulan işlemde artırma
yapılmaz (`ticket.created`). Bu eklenmeyecekse belgedeki "atlama" ifadesi "deyim başına" olarak düzeltilmeli.

### ZK-03 (Bilgi) Muafiyet olumsuz liste biçiminde

**Bulgu.** Sıra kuralları `current_user = 'netkar_app'` iken uygulanır; diğer her rol muaftır. Bugün bu güvenli:
`netkar_worker` bu tablolarda yalnız SELECT yetkisine sahip, `netkar_owner` migrasyon rolü ve tetikleyiciyi zaten
kapatabilir, `netkar_app` başka role üye değil (`provision.py:35, 44-46`). Ancak ileride yazma yetkisi verilecek
bir rol (destek paneli, yönetim API'si, ayrı içe aktarma işçisi) hiçbir uyarı olmadan muaf olur.

**Düzeltme:** Kuralı tersine çevirin: yalnız açıkça adlandırılmış bakım rolleri muaf olsun
(`current_user <> 'netkar_owner'` ya da `NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)` ile
birlikte), ya da yeni rol eklerken bu işlevleri güncellemeyi ADR-0005 §6 rol listesine madde olarak ekleyin.
Test: `pg_class` üzerinde bu dört tabloya yazma yetkisi olan rollerin kümesinin `{netkar_app, netkar_owner}`
olduğunu doğrulayan bir şema testi.

### ZK-04 (Bilgi) Downgrade 0009 dosyasını `importlib` ile yüklüyor

**Bulgu.** `_migration_0009()` 0009 dosyasını ada göre bulup modül olarak çalıştırır ve `VERSION_GUARD_0009`,
`INSERT_GUARD_SQL`, `JOURNAL_GUARD_SQL` sabitlerini kullanır (`0010:169-176, 190-194`). Doğru çalışıyor:
gövdeler 0009'un son hâlidir, `CREATE FUNCTION` yalnız ilk geçişte `CREATE OR REPLACE` olur, işlevler sütun
düşmeden önce değiştirilir (plpgsql sütun bağımlılığı izlemediği için sıra önemli ve doğru), modülün yan etkisi
yoktur. Gidiş-dönüş testi gövdeleri karşılaştırıyor. Kırılganlık: 0009 dosyasının adı ya da sabit adları
değişirse (yeniden adlandırma, squash) 0010 downgrade'i çalışma anında kırılır; 0009 içeriği sonradan
değiştirilirse 0010 downgrade'i sessizce farklı gövdeye döner.

**Düzeltme:** 0009 gövdelerini 0010 içine metin olarak kopyalayın (migrasyonlar dondurulmuş belgedir) ya da
mevcut gidiş-dönüş testine "0010 downgrade sonrası işlev metni, 0009 upgrade sonrası işlev metnine eşit"
denetimi ekleyin (`pg_get_functiondef` karşılaştırması). Zorunlu değil.

### ZK-05 (Bilgi) `earliest_order_day` aynı kiracı içi hesap ayrımı testi yok

**Bulgu.** Sorgu açıkça `Order.tenant_id == tenant_id AND Order.marketplace_account_id == account_id` ile
süzülüyor (`app/services/profit_settings.py:502-516`), uç nokta önce `_require_account` (404) çalıştırıyor
(`app/api/v1/profit_settings.py:182-196, 293`) ve `orders` RLS altında. Kod doğru. Test
(`tests/test_profit_settings_api.py:722-731`) yalnız iki ayrı kiracıyı karşılaştırıyor; aynı kiracıda iki hesap
olduğunda diğer hesabın daha eski siparişinin görünmediği denetlenmiyor.

**Düzeltme:** Aynı kiracıda ikinci hesap ve ona daha eski bir sipariş ekleyen, birinci hesabın
`earliest_order_day` değerinin değişmediğini doğrulayan bir test.

## 3. Kontrol listesi yanıtları

1. **YK-01 PoC A kapandı mı:** Evet. Ekleme, kapanış ve günlük kuralları `head_xact IS DISTINCT FROM
   pg_current_xact_id()` ile reddediyor; `IS DISTINCT FROM` 0010 öncesi satırlardaki `NULL` değeri de reddeder.
   Aynı değerle başlık UPDATE'i bağ kurmuyor (test var).
2. **YK-01 PoC B kapandı mı:** `revision` sütunu üzerinden evet (azaltma, sıfır, uçurum reddediliyor). Hesap
   anahtarı üzerinden hayır (ZK-01).
3. **`revision_xact` istemciden sahtelenebiliyor mu:** Hayır. BEFORE INSERT OR UPDATE tetikleyicisi her rol ve
   her yazımda değeri kendisi atar (INSERT: geçerli işlem; UPDATE: sürüm değiştiyse geçerli işlem, değilse eski
   değer). `netkar_app` tetikleyiciyi kapatamaz (tablo sahibi değil), `session_replication_role` süper kullanıcı
   ister. `pg_current_xact_id()` en üst işlem kimliğidir; SAVEPOINT ya da plpgsql EXCEPTION bloğu sonucu
   değiştirmez. `xid8` 64 bit, sarmalama yok. Profit_settings üzerinde başka BEFORE tetikleyici yok; sıralama
   riski yok.
4. **Sahip rol muafiyetinin sınırı:** Muafiyet yalnız sıra kurallarını kapsar; `revision_xact` ataması ve
   sürümlü tablolardaki değişmezlik (kapalı satır, iş alanları) her rolü bağlar (test:
   `test_owner_role_is_bound_by_the_version_guard_trigger`, `test_revision_xact_is_assigned_by_the_trigger...`).
   Bugün muaf olan roller fiilen yalnız `netkar_owner` ve süper kullanıcıdır; biçim olumsuz liste (ZK-03).
5. **Downgrade 0009 gövdelerine doğru dönüyor mu:** Evet; sıra doğru (önce işlevler, sonra tetikleyici, işlev
   ve sütun). `importlib` yüklemesi çalışıyor, kırılganlığı ZK-04.
6. **`SET search_path` doğru mu:** Evet. `pg_catalog, public`; `pg_temp` açıkça listelenmediği için yalnız
   ilişki adlarında örtük aranır, ama tüm tablo başvuruları `public.profit_settings` olarak nitelenmiş; işlev ve
   işleçler `pg_catalog`'tan çözülür. İşlevler SECURITY INVOKER; yetki yükseltme yüzeyi yok.
7. **Dürüst yazım akışı bozuldu mu:** Hayır. `begin_write` başlığı `ON CONFLICT DO NOTHING` ile ekler (yeni ise
   `revision = 1`, `revision_xact` bu işlem) ve `FOR UPDATE` ile kilitler; `finish_write` mevcut başlıkta +1 yapıp
   flush eder; aynı işlemdeki ikinci başlık UPDATE'i (varsayılan desi) sürümü değiştirmediğinden bağ korunur.
   Eşzamanlı ilk yazımda ikinci işlem `ON CONFLICT` sonrası kilit bekler ve `created = False` ile +1 yapar.
   ORM modeli `revision_xact` sütununu `deferred=True` eşliyor; uygulama okumuyor ve yazmıyor. 161 test geçti.
8. **YK-04 katı biçim:** Doğru. `None` ve `all` dışında yalnız metin kabul edilir (`_require_text`), ASCII
   `[0-9]` deseni `fullmatch` ile, ardından pydantic `date` ayrıştırması (ör. `2026-02-30` reddedilir). Unicode
   rakam, saat dilimli tarih-saat ve Unix zaman damgası artık geçmez.
9. **`earliest_order_day` kiracı ve hesap süzgeçli mi, RLS altında mı:** Evet (ZK-05'te ayrıntı). `_read_guard`
   başka kiracının hesabına 404 döner, sorgu iki süzgeçli ve RLS altındaki uygulama oturumunda çalışır.
10. **İstanbul gün çevirisi:** Doğru. `ordered_at` `timestamptz` (`DateTime(timezone=True)`), sürücü UTC'li
    farkında değer döndürür, `astimezone(UTC+3).date()` motorla aynı sabit kural (K16). UTC 20:59 / 21:00 sınırı
    testli. `today_istanbul` aynı `ISTANBUL` sabitini kullanır.
11. **Yanıt yeni bilgi sızdırıyor mu:** Anlamlı bir sızıntı yok. `earliest_order_day` aynı hesabın sipariş
    listesini/raporlarını görebilen roller için türetilmiş bir bilgidir; `today_istanbul` ve `vat_rates`
    (`Decimal` dizgesi, motor sabiti) gizli değil. Başka hesabın ya da kiracının verisi yanıtlanmıyor.
12. **Web, sunucu değeri bozuk gelirse güvenli yedeğe düşüyor mu:** Evet.
    - `resolveVatRates`: dize değilse ya da `^\d{1,3}(\.\d{1,4})?$` dışında ise `"20"` (`u` bayrağı olmadan `\d`
      yalnız ASCII). `exclusiveOfVat` oranı BigInt ile işler, float yok, negatifte hata fırlatır.
    - `resolveToday` ve `suggestStartDay`: `isDateText` takvim doğrulaması yapar (`2026-02-30`, `0050-01-01`
      reddedilir); bozuk değerde cihaz günü ya da yaklaşık öneri kullanılır; öneri `MIN_VALID_FROM` altına inmez.
    - `advanceServerDay`: cihaz saati geri giderse ilerleme 0 (geri gitmez). İstemcinin "bugün" değeri yalnız
      görüntü ve öneri içindir; K43 geçmiş değişiklik kararı sunucuda verilir.
    - Not edilecek küçük nokta (bulgu değil): oran üst sınırı istemcide 999,9999; sunucu güvenilir kaynak olduğu
      için kabul edilebilir.

## 4. Doğru çalışanlar

- `revision_xact` yalnız tetikleyici tarafından atanıyor; istemci değeri INSERT ve UPDATE'te yok sayılıyor.
- Üç sıra kuralı (sürümlü ekleme, kapanış, günlük) sayacın bu işlemde artırılmasını istiyor; YK-01 PoC A testle
  reddediliyor.
- `netkar_app` için sayaç azaltma, sıfırlama, deyim içinde atlama ve 1 dışında başlangıç reddediliyor.
- `netkar_app` `profit_settings` satırını silemiyor (bu tabloya DELETE hiç verilmedi: `0007:42, 150` yalnız
  sürümlü tablolara verdi, 0008 onları da geri aldı); başlık silinip yeniden eklenerek geri sarma yolu yok.
- Değişmezlik kuralları (kapalı satır, iş alanları) sahip rolü de bağlıyor.
- `SET search_path` dört işlevde de var; tablo başvuruları nitelenmiş.
- Downgrade sırası doğru, veri kaybı yok; gidiş-dönüş testi var.
- Dürüst yazım akışı (`begin_write` / `finish_write`) yeni kurallarla uyumlu; eşzamanlı ilk yazım güvenli.
- YK-04 katı tarih doğrulaması sorgu parametresiyle aynı sözleşmede.
- `earliest_order_day` IDOR korumalı (404 + iki süzgeç + RLS), indeksli `MIN`, İstanbul günü doğru.
- Web tarafı sunucu alanları yoksa ya da bozuksa güvenli yedeklere düşüyor; tarih ve oran doğrulaması katı.
- İstenen üç test dosyası: 161/161 geçti.

## 5. Merge engeli var mı: HAYIR

Kritik ya da yüksek bulgu yok. ZK-01 (Düşük) YK-01 kapanış iddiasını eksik bırakıyor; bir sonraki migrasyonda
(0011) sütun düzeyinde UPDATE yetkisi ve anahtar değişmezliği ile kapatılması önerilir. ZK-02..ZK-05 bilgi
düzeyindedir.

## Ek A. Kavram kanıtı özeti (geçici test, sonra silindi)

```python
a, _ = seed_forgery_target(admin_conn)        # A: sayaç 5, sürüm 1 satırları etkin
a2 = uuid4()                                  # aynı kiracıda ikinci hesap (revoked)
admin_conn.execute("INSERT INTO marketplace_accounts (id, tenant_id, platform, seller_id, status, "
                   "created_by, api_key_last4, revoked_at) VALUES (%s, %s, 'trendyol', '7777', "
                   "'revoked', %s, 'abcd', now())", (a2, a.tenant_id, a.user_id))
with role_tx(database.app_dsn(), a.tenant_id) as conn:   # netkar_app
    conn.execute("UPDATE profit_settings SET marketplace_account_id = %s "
                 "WHERE marketplace_account_id = %s", (a2, a.account_id))       # geçti
    conn.execute("INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, revision) "
                 "VALUES (%s, %s, %s, 1)", (a.tenant_id, a.account_id, a.user_id))  # geçti
    forged_tariff(conn, a, 1, None)           # revision_from = 1: geçti
    add_change(conn, a, 1)                    # günlük revision = 1: geçti
# işlem içi gözlem: A için revision_from = 1 satır sayısı 1 -> 2; başlıklar [(A, 1), (A2, 5)]

# ZK-02
with role_tx(database.app_dsn(), a.tenant_id) as conn:
    for _ in range(50):
        conn.execute("UPDATE profit_settings SET revision = revision + 1")   # hepsi geçti, 5 -> 55
```
