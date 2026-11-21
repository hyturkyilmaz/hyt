# ADR-0008: Destek için MFA sıfırlama aracı (iki kişi onayı, bekleme süresi, zorunlu yeniden kurulum)

- Durum: Önerildi (yalnız tasarım; kod, migrasyon dosyası ve test bu ADR'nin kapsamı dışında)
- Tarih: 18 Kasım 2026
- İlgili: `docs/operasyon/destek_mfa_sifirlama.md` (bölüm 3, 4.1 "araç yok", 4.2 asgari 13 gereksinim, 2.5 self-servis
  boşluğu); `docs/50_guvenlik.md` G02, G03, G18; ADR-0001 (RLS, `auth_gate` deseni, roller); ADR-0004 §2 "Araçların
  veritabanı erişimi"; `docs/security/degisiklik_2026-11-17_eposta_dogrulama.md`; Trello kartı "[NetKâr] (P1) Destek
  MFA sıfırlama aracı" (https://trello.com/c/ZPmoHXuM).
- Kod referansları `claude/dazzling-clarke-pfvf32` dalının çalışma ağacına göredir. Testler bu ADR için koşulmadı.

## 1. Bağlam

Bugün kurtarma kodu da olmayan kullanıcının MFA'sını sıfırlayan bir yol yoktur. Prosedür belgesi bölüm 3'ü geçen
talep "bekletilir" (`destek_mfa_sifirlama.md` bölüm 0 madde 3, 4.1). Koddan tespitler:

1. Tüm MFA uçları çağıranın KENDİ hesabı içindir: TOTP kapatma `services/api/app/api/v1/auth.py:663-708`, kurtarma
   kodu yenileme `auth.py:711-752`, yeniden doğrulama `auth.py:496-554`.
2. Roller yalnız kiracı içidir (`owner`, `admin`, `viewer`: `services/api/app/models/enums.py:8-13`). Platform
   çapında destek rolü yok.
3. Oturum iptal işlevi yalnız çağıranın kendi bağlamında çalışır: `auth_gate.revoke_other_sessions`
   (`services/api/migrations/versions/0019_mfa_recovery_codes.py:83-104`, kontrol `:91-94`). Başka kullanıcının
   oturumlarını iptal edemez.
4. Mevcut araçlar (`services/api/app/tools/`) `DATABASE_ADMIN_URL` ile superuser ya da BYPASSRLS rolle çalışır
   (`app/tools/common.py:76-94`, ADR-0004 §2). `netkar_owner` NOBYPASSRLS'tir
   (`infra/postgres/init/01-roles.sh:16`, `app/db/provision.py:35`); bu yüzden "owner rolüyle CLI" bugünkü
   `ensure_rls_bypass` denetiminden geçmez (`common.py:86-94`) ve ADR-0001 §2.1'e göre owner çalışma zamanında
   kullanılmaz.
5. Kurtarma kodu satırları silinmez; `used_at` ve `revoked_at` bir kez dolunca değişmez
   (`0020_recovery_code_immutability.py:171-186`).
6. Sıfırlama sonrası "zorunlu yeni TOTP kurulumu" durumu yok. TOTP kapalı hesapta giriş parola ile doğrudan tam
   oturum açar (`auth.py:296-306`).
7. Üretimde gerçek e-posta arka ucu yok: `EMAIL_BACKEND=file/memory` iken prod açılmaz (`app/core/config.py:286-288`).
   Bildirim ve itiraz penceresi bu arka uca bağlıdır.

## 2. Karar özeti

1. Araç **sunucuda çalışan CLI**'dır (`python -m app.tools.support_mfa_reset`), ama `DATABASE_ADMIN_URL` ya da
   `netkar_owner` ile DEĞİL: yeni, dar bir `support_gate` şeması ve işlevleri üzerinden, operatör başına ayrı
   PostgreSQL giriş rolüyle çalışır (bölüm 4). Platform yönetici API ucu reddedildi (bölüm 3).
2. Akış bir durum makinesidir: `opened -> notice_sent -> approved -> executed`; her aşamada `cancelled`, `objected`,
   `expired` ile biter. Durum, değişmez olay tablosundan türetilir (bölüm 5, 6).
3. Kimlik kanıtı kişisel veri saklamaz: e-posta kutusu sahipliği aracın (işçinin) gönderdiği tek kullanımlık kodla,
   mağaza sahipliği veritabanında karşılaştırmayla kanıtlanır; yalnız geçti/kaldı yazılır (bölüm 5.2).
4. İki kişi onayı veritabanında zorunludur (`session_user` farklı olmalı). Tek operatör varken "tek kişi modu":
   daha uzun bekleme, açılış ile onay arasında asgari süre, kullanıcıya itiraz bağlantılı e-posta ve harici
   alarm (bölüm 5.3, 5.4).
5. Sıfırlama tek işlemdir: TOTP kapanır, etkin kurtarma kodları `revoked_at` alır (silinmez), tüm oturumlar iptal
   edilir, hesap "yeniden kurulum zorunlu" durumuna geçer; parola değişmez (bölüm 5.5).
6. Yeniden kurulum, e-postaya giden tek kullanımlık kurulum bağlantısı olmadan tamamlanamaz; o zamana kadar API
   yalnız güvenlik sayfasının uçlarına izin verir (bölüm 5.7).
7. Self-servis boşluğu: son kurtarma kodunu girişte harcayan kullanıcı, bu oturum taze iken (öneri 10 dk) TOTP'yi
   yalnız parolayla kapatabilir (bölüm 8).

## 3. Seçenek karşılaştırması

| Ölçüt | (1) Sunucuda CLI (`app/tools` deseni) | (2) Platform yönetici API ucu + ayrı rol |
|---|---|---|
| Saldırı yüzeyi | İnternete açık uç yok. Erişim SSH anahtarı + 2FA'lı panel + IP kısıtı ile sınırlı (G18). | Yeni internete açık uçlar, yeni kimlik doğrulama türü (platform yöneticisi), yeni oturum ve CSRF yüzeyi. API süreci başka kullanıcının MFA'sını değiştirme yetkisi taşır: API ele geçirilirse bu yetki de geçer. |
| Kimlik ve iki kişi kuralı | Operatör başına PostgreSQL giriş rolü; `support_gate` işlevleri `session_user` ile kimliği DB'de okur, açan ile onaylayan farkını DB zorlar. | Uygulama katmanı kimliği; DB yalnız `netkar_app`'i görür. Kuralı uygulama kodu zorlar, DB düzeyinde ikinci kilit yok (ADR-0001 "çift kilit" ilkesine aykırı yön). |
| Denetlenebilirlik | Olaylar değişmez tabloda, kiracı `audit_log`'una da yansır. CLI çıktısı sır içermez (mevcut araç ilkesi `common.py:8-9`). | Aynı denetim yazılabilir; ek olarak HTTP istek günlükleri. Fark yok denecek kadar az. |
| RLS / `auth_gate` uyumu | Yeni `support_gate` şeması, `auth_gate` ile aynı desen: SECURITY DEFINER, sabit `search_path`, adlandırılmış politika (ADR-0001 §2.3). `netkar_app` bu işlevleri çalıştıramaz. | `netkar_app`'e başka kullanıcının satırlarını değiştiren işlevlerin EXECUTE yetkisi gerekir. SQLi ya da mantık hatası bu yolu açar. |
| Solo kurucu operasyonu | Uygun. Sıfırlama seyrek (öngörü: ayda 0-2). Tek komut seti, ek UI yok. Bekleme süreleri DB saatine bağlı, operatör atlayamaz. | Fazla: yönetici paneli, ayrı MFA, IP listesi, testler. Destek ekibi yokken bakım yükü. |
| Teknik olmayan destek personeli | Zor (SSH ve terminal). | Kolay. |
| Geliştirme maliyeti | Orta (migrasyon, işlevler, CLI, worker görevi, API kapısı). | Yüksek (aynısı + yönetici kimlik doğrulama + web arayüzü). |

**Öneri: (1) CLI, `support_gate` ile.** Gerekçe: aynı güvenceyi daha küçük yüzeyle verir; iki kişi kuralı ve
bekleme süresi veritabanında zorlanır; API sürecine başka kullanıcının MFA'sına dokunan yetki verilmez.
**Yeniden değerlendirme tetiği:** teknik olmayan destek personeli işe alınırsa ya da sıfırlama ayda 10'u geçerse
(2) yeni bir ADR ile ele alınır.

Reddedilen alt seçenekler:

- **CLI + `DATABASE_ADMIN_URL` (superuser/BYPASSRLS), mevcut araçlar gibi:** her komut tüm tablolara açık olur;
  iki kişi kuralını ve bekleme süresini yalnız CLI kodu zorlar, aynı kimlik bilgisiyle `psql` açan biri hepsini
  atlar. Bakım penceresi araçları (anahtar döndürme) için kabul edilebilir, rutin destek işi için değil.
- **CLI + `netkar_owner`:** owner NOBYPASSRLS'tir (1. bölüm madde 4), tablo sahibi olduğu için şema değiştirebilir;
  ADR-0001 §2.1 owner'ı çalışma zamanından dışlar.
- **Doğrudan elle SQL:** `destek_mfa_sifirlama.md` 4.3 zaten reddeder; denetim kaydı bırakmaz, 0020 tetikleyicisine
  takılmaya açıktır (bölüm 7).

## 4. Roller ve yetki yolu

| Rol | Giriş | Amaç |
|---|---|---|
| `netkar_support_gate` | hayır | `support_gate` şemasının ve işlevlerinin sahibi. Tablolarda yalnız gerekli sütun yetkileri ve adlandırılmış `support_path` politikaları. |
| `netkar_support` | hayır (grup) | `support_gate` işlevlerinde EXECUTE. Hiçbir tabloda doğrudan yetki yok. |
| `nk_op_01`, `nk_op_02`, ... | evet | Operatör başına giriş rolü, `netkar_support` üyesi. Ad kişisel veri içermez; ad-kişi eşlemesi ürün veritabanı dışında, Hasan'da. Parola operatörün parola yöneticisinde; sunucu ortamına yazılmaz. |

- Rol kurulumu migrasyonda değil, mevcut rol kurulum yolundadır (`app/db/provision.py:26-46`,
  `infra/postgres/init/01-roles.sh:16-23`); operatör rolleri tek seferlik yönetici runbook'uyla eklenir.
  `GRANT netkar_support_gate TO netkar_owner WITH INHERIT FALSE, SET TRUE` deseni `netkar_auth` ile aynıdır
  (`provision.py:42-46`).
- İşlevler `SECURITY DEFINER`, `SET search_path = pg_catalog, public, pg_temp` (0020'deki sertleştirme), `PUBLIC`'ten
  EXECUTE alınmış, yalnız `netkar_support`'a verilmiş olur. Operatör kimliği `session_user`'dır (SECURITY DEFINER
  `current_user`'ı değiştirir, `session_user`'ı değiştirmez). İşlev, `session_user`'ı `support_operators.db_role` ile
  eşler; eşleşme yoksa ya da operatör pasifse 42501.
- `netkar_app`'in `support_gate` şemasında USAGE yetkisi yoktur. Kullanıcı tarafı adımlar (itiraz bağlantısı,
  kurulum bağlantısı, oturum kapısı) `auth_gate` içinde ayrı, dar işlevlerdir (bölüm 6.4).
- E-posta gönderimi ve tek kullanımlık kodların üretimi işçidedir (bölüm 5.4); işçi rolü yalnız bir okuma işlevinde
  ve bir "gönderildi" işlevinde EXECUTE alır. Operatör hiçbir aşamada düz metin kod, token ya da hedefin e-postasını
  görmez.
- Sınır: sunucuda root ya da PostgreSQL superuser yetkisi olan biri bu kontrollerin hepsini atlar. Araç bu kişiye
  karşı değil; hataya, tek operatörün kötüye kullanımına ve sosyal mühendisliğe karşıdır. Root seviyesine karşı
  kontrol: G18, kullanıcıya bildirim ve harici alarm (bölüm 9.3).

## 5. Akış

### 5.1 Talep kaydı (`open`)

```
python -m app.tools.support_mfa_reset open --ticket NK-2026-0042 --email <kayıtlı adres>
```

- Girdi: talep numarası (deseni `^[A-Z0-9-]{4,32}$`, serbest metin yok) ve kullanıcının yazdığı adres.
- `support_gate.open_request(ticket, email)` adresi `lower(email)` ile arar (`find_user_for_login` gibi,
  `0001_initial.py:156-167`). Tabloya YALNIZ kullanıcı UUID'si yazılır; e-posta yazılmaz.
- **Numaralandırma yok:** hesap olsun olmasın aynı çıktı döner ("talep açıldı, kullanıcıya doğrulama kodu
  gönderilecek"). Hesap yoksa hedef NULL kalır, e-posta gitmez, talep 72 saatte `expired` olur. Operatör hesabın
  varlığını ancak kullanıcı doğru kodu geri getirince öğrenir.
- Aynı hedef için açık talep varsa yeni talep açılmaz (danışma kilidi `pg_advisory_xact_lock` + açık durum
  denetimi); çıktı yine aynıdır.
- Hedefte `support_hold_at` doluysa (bölüm 5.9) talep açılır ama onaylanamaz; Hasan'a eskale edilir.

### 5.2 Kimlik doğrulama kanıtı (kişisel veri saklamadan)

| Adım | Yöntem | Saklanan |
|---|---|---|
| B. E-posta sahipliği | İşçi, kayıtlı adrese 8 karakterlik tek kullanımlık kod ve T5 bildirimini gönderir. Kullanıcı kodu destek yazışmasında söyler; operatör `verify-challenge` ile girer. Kod özeti (HMAC, `recovery_code_hash` deseni `app/core/security.py:193`) karşılaştırılır. En çok 5 deneme, 72 saat geçerli. | `challenge_passed` / `challenge_failed` olayı, deneme sayısı |
| C. Mağaza sahipliği | Operatör, kullanıcının SÖYLEDİĞİ değeri `store-check --seller-id ... --last4 ...` ile girer. `support_gate.check_store_claim` hedefin üye olduğu kiracıların `marketplace_accounts` satırlarıyla (`seller_id`, `api_key_last4`: `app/models/tables.py:122,126`) karşılaştırır ve yalnız eşleşti/eşleşmedi döner. Kayıtlı değer hiçbir zaman gösterilmez (ipucu sızıntısı yok, operatör veriyi görmez). En çok 3 deneme. | Alan başına `true/false`, deneme sayısı. Girilen değer yazılmaz. |
| D. Canlı sınama | Operatör beyanı (`--live-check passed`). | `true/false` |
| Kırmızı bayrak | Operatör, prosedür 3.3 madde numaralarını girer. Bayrak varsa onay işlevi reddeder; yalnız `--escalated` ile Hasan'ın operatör rolü onaylayabilir (tek kişi modunda Hasan zaten tek operatördür; bayrak varsa bekleme ikiye katlanır). | Madde numaraları (tam sayı dizisi) |

Onay ön koşulu (DB'de): B geçti VE C'de en az bir alan eşleşti. D isteğe bağlı. Saklanmayanlar prosedür 3.5
"KAYDEDİLMEZ" listesiyle aynıdır.

Not: Trendyol satıcı numarası mağaza sayfası adresinde görünüyor olabilir; bu durumda zayıf kanıttır. Doğrulanmadı
(Hasan kararı K8).

### 5.3 İki kişi onayı ve tek kişilik ekip

**Çift mod (en az iki etkin operatör):**

- `approve` işlevi: onaylayanın `session_user`'ı açanınkinden farklı olmalı (42501).
- Onaylayan kanıt olaylarını kendisi okur (`show` komutu yalnız olay listesini ve geçti/kaldı değerlerini gösterir);
  gerekirse C adımını kendisi tekrarlar (aynı deneme sınırı içinde).

**Tek kişi modu (etkin operatör sayısı 1):**

Yazılımla iki kişi kuralı tek kişide anlamsızdır; yerine şu üç denetim konur, hepsi DB'de zorlanır:

1. **Zaman kilidi:** onay, açılıştan en az `solo_min_review` (öneri 24 saat) sonra ve ayrı bir CLI oturumunda
   yapılabilir. Amaç: aciliyet baskısı altındaki kararı soğutmak, "ikinci göz" yerine "ikinci zaman".
2. **İtiraz penceresi:** uygulama, `notice_sent` olayından en az `objection_window_solo` (öneri 72 saat; çift modda 24)
   sonra yapılabilir. Pencere e-posta gönderimi BAŞARILI olunca başlar.
3. **Harici alarm:** her `opened`, `approved`, `executed`, `objected` olayında işçi, ürün sunucusundan bağımsız bir
   adrese (Hasan'ın ayrı posta kutusu) yalnız talep numarası ve olay türünü içeren uyarı gönderir. Sunucuya erişen
   ama bu kutuya erişemeyen biri fark edilmeden sıfırlama yapamaz.

Mod, onay anındaki etkin operatör sayısından türetilir; ikinci operatör eklendiği anda çift mod zorunlu olur.
İkinci operatör kimin olacağı ve tek kişi modunun hiç izinli olup olmayacağı Hasan kararıdır (K1).

### 5.4 Kullanıcıya bildirim ve itiraz penceresi (yürütme öncesi)

- İşçi görevi `netkar.support_notices` her dakika çalışır (mevcut dakikalık periyodik görev deseni:
  `app/worker/tasks.py:87`). `support_gate.pending_notices()` ile bekleyen bildirimleri alır, kodu ve tokenı burada
  üretir, yalnız özetlerini `support_mfa_reset_tokens`'a yazar, e-postayı gönderir, başarıda `notice_sent` olayını
  yazar. Gönderim başarısızsa olay yazılmaz; pencere başlamaz; görev sonraki dakikada yeniden dener.
- E-posta (T5 şablonunun araç sürümü): talep numarası, doğrulama kodu, "siz değilseniz" bağlantısı
  (`/destek/itiraz?token=...`), uygulamanın en erken UTC zamanı. Kod, IP ve başka kişisel veri yazılmaz
  (`_queue_mfa_notice` ilkesi, `auth.py:101-121`).
- İtiraz bağlantısı: GET sayfası yalnız bir onay düğmesi gösterir (bağlantı önizleyicileri tetiklemesin); POST
  `auth_gate.object_support_reset(token_hash)` çağırır: token tek kullanımlık, talep terminal değilse `objected`
  olayı yazılır, harici alarm gider. Yanıt her durumda aynıdır (numaralandırma yok). IP hız sınırı uygulanır.

### 5.5 Sıfırlama (`execute`)

`support_gate.execute_reset(request_id)` tek işlemde, şu sırayla:

1. Ön koşullar (hepsi DB'de): talep `approved`; terminal olay yok; `now() >= not_before`
   (`notice_sent + pencere`); hedef var; hedefte `support_hold_at` yok; aynı hedefte son 30 günde `executed` yok;
   son 24 saatte toplam `executed` sayısı üst sınırın altında; çağıran etkin operatör. Onaydan sonra 7 gün geçtiyse
   `expired` yazılır ve reddedilir.
2. Hedef kullanıcı satırı `FOR UPDATE` kilitlenir.
3. Önceki durum sayıları okunur: TOTP etkin miydi, etkin kurtarma kodu sayısı, etkin oturum sayısı, e-posta doğrulanmış
   mı.
4. `users`: `totp_enabled = false`, `totp_secret_encrypted = NULL`, `totp_last_step = NULL`, `totp_failed_count = 0`,
   `totp_locked_until = NULL` (TOTP kapatmadaki alan seti, `auth.py:685-695`), ayrıca
   `mfa_enrollment_required_at = now()`, `mfa_enrollment_deadline = now() + 7 gün`. Parolaya dokunulmaz.
5. `mfa_recovery_codes`: `UPDATE ... SET revoked_at = now() WHERE user_id = :u AND used_at IS NULL AND revoked_at IS NULL`
   (bölüm 7'deki koşul zorunlu).
6. `sessions`: hedefin TÜM kiracılardaki tüm etkin oturumları `revoked_at = now()` (istisna yok; operatörün oturumu
   ürün oturumu değildir).
7. `support_mfa_reset_events`'e `executed` olayı (meta: 3. adımdaki sayılar).
8. Hedefin üye olduğu her kiracının `audit_log`'una `support.mfa_reset_executed` satırı (bölüm 5.8).
9. Kurulum tokenı ve T7 bildirimi için bekleyen bildirim kaydı (işçi gönderir).

Bir adım hata verirse (ör. 0020 tetikleyicisi 23514) işlemin tamamı geri alınır; yarım sıfırlama olmaz. Denetim
kaydı yazılamazsa işlem olmaz (4.2 madde 9).

Yan etki kontrolü: sıfırlamadan önce verilmiş `__Host-nk_pending` çerezi işe yaramaz; `totp/verify`
`user.totp_enabled` false iken başarısız olur (`auth.py:345`, `:356`).

### 5.6 Kullanıcıya bildirim (yürütme sonrası)

- İşçi, kayıtlı adrese T7'nin araç sürümünü gönderir: işlem türü, UTC zamanı, kurulum bağlantısı
  (`/panel/guvenlik?kurulum=<token>`, 72 saat), "siz istemediyseniz" bağlantısı (itiraz tokenı, işlemden sonra 30
  gün geçerli). Parola sıfırlama bağlantısı tek başına önerilmez; TOTP'yi korumaz, burada TOTP zaten yok
  (`destek_mfa_sifirlama.md` 4.2 madde 8).
- Gönderim hatası sıfırlamayı geri almaz (işlem bitmiştir). Hata `notify_failed` olayı olarak yazılır, harici alarm
  gider, işçi yeniden dener. Kullanıcı panelden kurulum bağlantısını yeniden isteyebilir (5.7).

### 5.7 Sonraki girişte zorunlu yeni TOTP kurulumu

- `auth_gate.get_session` dönüşüne `mfa_enrollment_required` ve `support_hold` eklenir (`0001_initial.py:168-178`
  gövdesi, dönüş tipi değiştiği için DROP + CREATE). `lookup_session` (`app/services/auth.py:104-129`) bu alanları
  `AuthContext`'e taşır.
- `get_auth_context` (`app/api/deps.py:141-158`) varsayılan olarak REDDEDER: `mfa_enrollment_required` iken
  403 `mfa-enrollment-required` döner. Yalnız yeni `EnrollmentAuthDep` kullanan uçlar açıktır: `GET /v1/me`,
  `POST /v1/auth/totp/setup`, `POST /v1/auth/totp/enable`, `POST /v1/auth/logout`, `GET /v1/auth/csrf`,
  `POST /v1/auth/email/resend`, `POST /v1/auth/email/verify`, yeni `POST /v1/auth/totp/enroll-link`. Kapı varsayılan
  kapalıdır: yeni uç eklendiğinde unutulursa kapalı kalır.
- `totp/setup` (`auth.py:557-590`) ve `totp/enable` (`auth.py:605-660`) bu durumda ek olarak kurulum tokenı ister.
  `enable`, TOTP'yi açtıktan sonra aynı işlemde `auth_gate.complete_mfa_enrollment(token_hash, user_id)` çağırır:
  token o kullanıcıya ait ve geçerli değilse hata, işlem geri alınır; geçerliyse token tüketilir, bayrak temizlenir,
  `enrolled` olayı yazılır. `netkar_app`'e bayrak sütununda UPDATE yetkisi VERİLMEZ.
- Neden kurulum tokenı: sıfırlama ile kurulum arasında hesap yalnız parolalıdır. Sızmış parolası olan biri bu
  aralıkta kendi TOTP'sini kurup hesabı devralabilirdi. Token e-posta kutusu sahipliğini ikinci kez ister.
- `totp/enroll-link`: oturumdaki kullanıcıya (adres istekten alınmaz) yeni kurulum bağlantısı; kullanıcı başına
  saatlik sınır (`email/resend` deseni, `auth.py:874-920`). Eski token geçersiz olur.
- Süre: `mfa_enrollment_deadline` geçerse giriş yine çalışır ama yalnız güvenlik uçları açıktır; ek olarak harici
  alarm gider (kullanıcı kurulumu tamamlamadı).
- E-postası doğrulanmamış eski hesap (0017 öncesi): TOTP etkinleştirme tetikleyicisi doğrulama ister
  (`0019_mfa_recovery_codes.py:60-81`); izinli listede `email/resend` ve `email/verify` bu yüzden vardır. Bu hesaplar
  için aracın açılıp açılmayacağı Hasan kararıdır (K9).
- Web: panel layout'u zaten `GET /v1/me` ile oturumu doğrular (`apps/web/src/middleware.ts:10-11` notu);
  `MeResponse`'a `mfa_enrollment_required` eklenir ve layout `/panel/guvenlik`'e yönlendirir. Asıl kapı API'dedir;
  web yönlendirmesi yalnız kullanıcı deneyimidir.

### 5.8 Denetim kaydı alanları (kişisel veri yok)

`support_mfa_reset_events.meta` ve kiracı `audit_log.meta` yalnız şu anahtarları taşıyabilir; DB'de
`CHECK (meta - ARRAY[...izinli anahtarlar...] = '{}'::jsonb)` ile zorlanır:

| Anahtar | Tür | Not |
|---|---|---|
| `request_id` | uuid | |
| `ticket` | metin | Desenli talep numarası |
| `mode` | `dual` / `solo` | |
| `operator` | uuid | `support_operators.id`, takma ad; kişi adı değil |
| `challenge_passed`, `store_seller_match`, `store_last4_match`, `live_check` | boolean | |
| `attempts` | tam sayı | |
| `red_flags` | tam sayı dizisi | Prosedür 3.3 madde numaraları |
| `wait_hours` | tam sayı | Uygulanan bekleme |
| `totp_was_enabled`, `email_verified` | boolean | Önceki durum |
| `recovery_codes_revoked`, `sessions_revoked` | tam sayı | |

Yazılmayanlar: e-posta, ad, IP ya da IP özeti (CLI'da istemci IP yok), girilen satıcı numarası ve son 4 hane, kod,
token, serbest metin gerekçe. Serbest metin gerekçe prosedürdeki ürün dışı talep kaydında kalır
(`destek_mfa_sifirlama.md` 3.5).

Kiracı tarafı: `audit_log.action` değerleri `support.mfa_reset_requested`, `support.mfa_reset_executed`,
`support.mfa_reset_objected`, `support.mfa_enrolled`. `user_id` hedef kullanıcıdır; operatör `meta.operator`'dadır
(`audit_log.user_id` `users`'a referanstır: `0001_initial.py:88-98`). Kiracı sahibi bu kayıtları mevcut
`GET /v1/tenant/audit` ile görür (`app/api/v1/tenant.py:57-80`).

### 5.9 Geri alma ve itiraz

- **Yürütmeden önce:** kullanıcı itiraz bağlantısı (5.4) ya da operatör `cancel` ile talep `objected`/`cancelled`
  olur. Terminal olay tekildir (bölüm 6.2), sonra yürütülemez.
- **Yürütmeden sonra:** eski TOTP sırrı geri getirilmez (sır NULL; saklamak, sırrı ikinci kez riske atar). Geri alma
  "hesabı güvenli duruma almak" demektir: itiraz bağlantısı (30 gün) ya da operatör `hold` komutu
  `support_hold_at = now()` yazar, tüm oturumları yeniden iptal eder, `objected` ya da `hold_set` olayı ve harici
  alarm üretir. `support_hold_at` doluyken `find_user_for_login` ve `get_session` hesap için oturum açtırmaz
  (doğru parolada bile 403 `account-on-hold`, yanlış parolada mevcut 401). Kaldırma yalnız `release-hold` ile ve yeni
  bir destek talebiyle (yeniden kimlik kanıtı) yapılır.
- Kötüye kullanım değerlendirmesi: itiraz bağlantısı yalnız kayıtlı posta kutusuna gider; kutuya erişen biri zaten
  parola sıfırlayabilir. Bekletme yalnız hesabı kilitler, veri silmez. Bekletme girişi tamamen kapatsın mı, yoksa
  yalnız güvenlik sayfasını mı açsın: Hasan kararı (K5).

## 6. Şema değişikliği taslağı (migrasyon 0023, geri alınabilir)

Yalnız taslaktır; dosya yazılmadı. Desenler: değişmezlik 0021 (`0021_legal_documents_acceptance.py:72-85`),
TRUNCATE engeli ve sunucu alanları 0022 (`0022_legal_acceptance_hardening.py:39-62`), downgrade koruması 0021/0022
(`0021_legal_documents_acceptance.py:111-141`).

### 6.1 `users` sütunları

```sql
ALTER TABLE users
  ADD COLUMN mfa_enrollment_required_at timestamptz,
  ADD COLUMN mfa_enrollment_deadline timestamptz,
  ADD COLUMN support_hold_at timestamptz;
GRANT SELECT (mfa_enrollment_required_at, mfa_enrollment_deadline, support_hold_at) ON users TO netkar_app;
-- netkar_app UPDATE ALMAZ. Yazan: netkar_support_gate (execute, hold) ve netkar_auth (complete_mfa_enrollment).
```

### 6.2 Yeni tablolar

```sql
CREATE TABLE support_operators (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  db_role text NOT NULL UNIQUE CHECK (db_role ~ '^nk_op_[0-9]{2}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  disabled_at timestamptz            -- NULL -> değer bir kez; geri açılmaz (tetikleyici)
);

CREATE TABLE support_mfa_resets (    -- başlık: DEĞİŞMEZ
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket text NOT NULL UNIQUE CHECK (ticket ~ '^[A-Z0-9-]{4,32}$'),
  target_user_id uuid REFERENCES users (id),   -- hesap yoksa NULL (numaralandırma yok)
  opened_by uuid NOT NULL REFERENCES support_operators (id),
  opened_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE support_mfa_reset_events (   -- eklemeli: DEĞİŞMEZ
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES support_mfa_resets (id),
  kind text NOT NULL CHECK (kind IN ('opened','notice_sent','challenge_passed','challenge_failed',
        'store_check','live_check','approved','cancelled','objected','expired','executed',
        'user_notified','notify_failed','enrolled','hold_set','hold_released')),
  operator_id uuid REFERENCES support_operators (id),
  created_at timestamptz NOT NULL DEFAULT now(),   -- BEFORE INSERT tetikleyicisi now() yazar (0022 deseni)
  meta jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (meta - ARRAY[...5.8 listesi...] = '{}'::jsonb)
);
CREATE UNIQUE INDEX uq_reset_terminal ON support_mfa_reset_events (request_id)
  WHERE kind IN ('executed','cancelled','objected','expired');
CREATE UNIQUE INDEX uq_reset_approved ON support_mfa_reset_events (request_id) WHERE kind = 'approved';
CREATE UNIQUE INDEX uq_reset_notice ON support_mfa_reset_events (request_id) WHERE kind = 'notice_sent';

CREATE TABLE support_mfa_reset_tokens (
  token_hash text PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES support_mfa_resets (id),
  purpose text NOT NULL CHECK (purpose IN ('challenge','objection','enroll')),
  expires_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
  created_at timestamptz NOT NULL DEFAULT now(),
  used_at timestamptz                -- NULL -> değer bir kez (0020 deseni)
);
```

Notlar:

- Terminal, onay ve bildirim olaylarının tekilliği kısmi benzersiz indekslerle DB'de zorlanır; yarışta ikinci
  `executed` 23505 alır. Satır kilidine (`FOR UPDATE`) gerek kalmaz; hedef başına "tek açık talep" kuralı için işlev
  içinde `pg_advisory_xact_lock(hashtextextended(target_user_id::text, 0))` kullanılır.
- `support_mfa_resets` ve `support_mfa_reset_events`: BEFORE UPDATE OR DELETE ve BEFORE TRUNCATE tetikleyicileri
  (23514). `support_mfa_reset_tokens`: yalnız `used_at` NULL -> değer ve `attempts` artışı serbest; başka her UPDATE,
  DELETE ve TRUNCATE 23514. `support_operators`: yalnız `disabled_at` NULL -> değer serbest.
- Bu tablolarda `tenant_id` yoktur (platform verisi; kullanıcı birden çok kiracıya üye olabilir: ADR-0001 §1).
  `test_every_tenant_table_has_forced_rls` (`services/api/tests/test_rls_idor.py:214`) bu yüzden onları otomatik
  kapsamaz; ayrı bir koruyucu test eklenir (bölüm 11).

### 6.3 RLS ve yetkiler

```sql
-- Dört tabloda: ENABLE + FORCE ROW LEVEL SECURITY. netkar_app için politika ve yetki YOK.
CREATE POLICY support_path ON support_mfa_resets       TO netkar_support_gate USING (true) WITH CHECK (true);
CREATE POLICY support_path ON support_mfa_reset_events TO netkar_support_gate USING (true) WITH CHECK (true);
CREATE POLICY support_path ON support_mfa_reset_tokens TO netkar_support_gate USING (true) WITH CHECK (true);
CREATE POLICY support_path ON support_operators        TO netkar_support_gate USING (true);
-- Kullanıcı tarafı (itiraz, kurulum tamamlama) netkar_auth üzerinden:
CREATE POLICY auth_path ON support_mfa_reset_tokens TO netkar_auth USING (true) WITH CHECK (true);
CREATE POLICY auth_path_insert ON support_mfa_reset_events FOR INSERT TO netkar_auth WITH CHECK (true);
CREATE POLICY auth_path_read ON support_mfa_resets FOR SELECT TO netkar_auth USING (true);

-- Mevcut tablolarda yeni, adlandırılmış ve dar politikalar:
CREATE POLICY support_path ON users              TO netkar_support_gate USING (true) WITH CHECK (true);
CREATE POLICY support_path ON mfa_recovery_codes TO netkar_support_gate USING (true) WITH CHECK (true);
CREATE POLICY support_path ON sessions           TO netkar_support_gate USING (true) WITH CHECK (true);
CREATE POLICY support_path ON memberships        FOR SELECT TO netkar_support_gate USING (true);
CREATE POLICY support_path ON marketplace_accounts FOR SELECT TO netkar_support_gate USING (true);
CREATE POLICY support_path_insert ON audit_log   FOR INSERT TO netkar_support_gate WITH CHECK (true);

GRANT SELECT (id, email, totp_enabled, email_verified_at, support_hold_at) ON users TO netkar_support_gate;
GRANT UPDATE (totp_enabled, totp_secret_encrypted, totp_last_step, totp_failed_count, totp_locked_until,
              mfa_enrollment_required_at, mfa_enrollment_deadline, support_hold_at) ON users TO netkar_support_gate;
GRANT SELECT (user_id, used_at, revoked_at) ON mfa_recovery_codes TO netkar_support_gate;
GRANT UPDATE (revoked_at) ON mfa_recovery_codes TO netkar_support_gate;
GRANT SELECT (user_id, revoked_at) ON sessions TO netkar_support_gate;
GRANT UPDATE (revoked_at) ON sessions TO netkar_support_gate;
GRANT SELECT (user_id, tenant_id) ON memberships TO netkar_support_gate;
GRANT SELECT (tenant_id, seller_id, api_key_last4, status) ON marketplace_accounts TO netkar_support_gate;
GRANT INSERT (tenant_id, user_id, action, target, meta) ON audit_log TO netkar_support_gate;
```

`users` için sütun SELECT'inde `email` yalnız `open_request` içindeki eşleştirme ve işçinin `pending_notices`
okuması içindir; hiçbir `support_gate` işlevi e-postayı operatöre döndürmez. `password_hash` ve
`totp_secret_encrypted` için SELECT verilmez. `marketplace_accounts` şifreli sütunları kapsam dışıdır.

### 6.4 İşlevler

`support_gate` (sahip `netkar_support_gate`, EXECUTE `netkar_support`):
`open_request(ticket, email)`, `verify_challenge(request_id, code_hash)`,
`check_store_claim(request_id, seller_id, last4)`, `record_live_check(request_id, passed)`,
`record_red_flags(request_id, int[])`, `approve(request_id, escalated boolean)`, `cancel(request_id)`,
`execute_reset(request_id)`, `set_hold(user_id)`, `release_hold(request_id)`, `show(request_id)` (olay listesi,
sayılar, en erken uygulama zamanı; kişisel veri yok).

`support_gate` (EXECUTE yalnız `netkar_worker`): `pending_notices()` (request_id, amaç, hedef e-posta; gönderilmesi
gerekenler), `mark_notice_sent(request_id, purpose, token_hash, expires_at)`.

`auth_gate` (sahip `netkar_auth`, EXECUTE `netkar_app`): `object_support_reset(token_hash)`,
`complete_mfa_enrollment(token_hash, user_id)`; `get_session` ve `find_user_for_login` dönüşleri genişler
(DROP + CREATE; geri almada 0001 gövdeleri). `test_auth_gate_functions_are_security_definer_with_fixed_search_path`
(`test_rls_idor.py:232`) beklenen işlev kümesini sabit tutar; bu test güncellenmek zorundadır.

Bekleme süreleri, üst sınırlar ve pencere değerleri işlev sabitleri değil `support_gate_settings` tek satırlık
tablodan okunur; satır yalnız migrasyonla (owner) değişir, uygulama ya da operatör değiştiremez.

### 6.5 Geri alma (downgrade)

- `ENVIRONMENT=prod` iken destek tablolarında satır varsa reddedilir (0021 deseni). Prod dışında
  `NETKAR_ALLOW_SUPPORT_DATA_LOSS=requests=N,events=M` tam sayılarla istenir.
- `mfa_enrollment_required_at` ya da `support_hold_at` dolu kullanıcı varsa downgrade DURUR: sütunları düşürmek bu
  hesapları kapısız, TOTP'siz tam oturuma açardı.
- Sırası: `auth_gate` işlevleri 0001/0019 gövdelerine döner, `support_gate` şeması düşer, politikalar ve yetkiler
  geri alınır, tablolar düşer, `users` sütunları düşer. `mfa_recovery_codes` ve `sessions` satırlarına dokunulmaz.

## 7. 0019/0020 tetikleyicileriyle çakışma analizi

| Tetikleyici | Sıfırlamadaki yazım | Sonuç |
|---|---|---|
| `mfa_recovery_codes_immutable_marks` (`0020_recovery_code_immutability.py:173-182`): `used_at` ya da `revoked_at` doluyken farklı değere çekilemez. | Etkin kodlara `revoked_at = now()`. | **İptal, "değiştirme" sayılmaz:** NULL -> değer ilk doldurmadır ve tetikleyici izin verir. |
| Aynı tetikleyici | Koşulsuz `UPDATE ... SET revoked_at = now() WHERE user_id = :u` | **Hata:** daha önce iptal edilmiş kodda `revoked_at` dolu ve farklı değere çekilir: 23514, tüm sıfırlama geri alınır. Kullanılmış ama iptal edilmemiş kodda ise tetikleyici izin verir ama "kullanıldı" bilgisinin yanına anlamsız bir iptal damgası ekler. |
| Doğru biçim | `WHERE user_id = :u AND used_at IS NULL AND revoked_at IS NULL` | Mevcut `revoke_recovery_codes` ile aynı (`app/services/auth.py:331-339`). Tetikleyiciye takılmaz, kullanılmış kod "kullanıldı" olarak kalır. Satır silinmez (DELETE yetkisi yok: `0019_mfa_recovery_codes.py:56-57`). |
| `users_totp_requires_verified_email` (`0019_mfa_recovery_codes.py:60-81`) | `totp_enabled = false` | Çakışma yok: tetikleyici yalnız `NEW.totp_enabled` true iken karar verir. Sonraki yeniden kurulumda doğrulanmamış hesap TOTP açamaz (bkz. 5.7, K9). |
| `user_self` politikası (`0019_mfa_recovery_codes.py:54-55`) | Başka kullanıcının kod satırı | `netkar_support_gate` için `app.user_id` taklidi YAPILMAZ (işlev içinde `set_config` ile hedef kullanıcıya bürünmek örtük ve denetlenmesi zor). Yerine adlandırılmış `support_path` politikası (6.3), ADR-0001 `auth_path` deseni. |
| `revoke_other_sessions` (`0019_mfa_recovery_codes.py:91-94`) | Hedefin oturumları | Kullanılamaz (çağıran = hedef şartı). Ayrı işlev, `support_path` + `UPDATE (revoked_at)` ile. |

## 8. Self-servis boşluğu (tek kurtarma kodu, oturum kapalı)

Sorun: girişte kurtarma kodu bir kod tüketir (`auth.py:383-396`); TOTP kapatma ikinci bir kod ister
(`auth.py:680-682`, `_reauthenticate` `:537-553`). Son kodu girişte harcayan ve cihazı olmayan kullanıcı panelde
mahsur kalır (`destek_mfa_sifirlama.md` 2.5).

Karar (önerilen):

1. `sessions`'a `second_factor text CHECK (second_factor IN ('none','totp','recovery'))` eklenir; `_start_session`
   (`auth.py:233-258`) eylem adından doldurur (`auth.login_recovery` -> `recovery`). Eski satırlar NULL kalır ve
   hiçbir ayrıcalık taşımaz. Geri alma: sütun düşer.
2. `totp/disable`, kod verilmediğinde şu ÜÇ koşul birlikte sağlanırsa yalnız parola ile kabul eder:
   oturum `second_factor = 'recovery'`; oturum `created_at` en çok `recovery_fresh_seconds` önce (öneri 600 sn);
   kullanıcının etkin kurtarma kodu sayısı 0 (`count_recovery_codes`, `app/services/auth.py:355-367`).
   Denetim kaydında `meta.factor = "fresh_recovery_session"`.
3. Gerekçe: bu oturum dakikalar önce parola + kurtarma kodu ile açıldı; kapatma için ikinci kod istemek aynı kanıtı
   ikinci kez istemektir. Kod kalan kullanıcı bu yolu kullanamaz (normal yol ondadır), dar tutulur.
4. Risk ve azaltım: çalınmış oturum çerezi 10 dakika içinde parola ile birlikte kullanılırsa TOTP kapanır. Saldırganın
   zaten parola + kurtarma kodu kanıtı vardır; ek kazancı küçüktür. Kapatma mevcut haliyle diğer oturumları kapatır ve
   e-posta gönderir (`auth.py:696-707`).
5. Önleyici: girişte kurtarma kodu kullanıldı e-postasına (`auth.py:397-400`) kalan kod sayısı eklenir (sayı kişisel
   veri değildir); panel uyarısı zaten 3 ve altında çıkar (`apps/web/src/components/security/security-view.tsx:40`).
   Web: kalan kod 0 iken girişten sonra güvenlik sayfası "şimdi yeniden kur" yönlendirmesi gösterir.

Reddedilen: her kurtarma girişinde zorunlu yeniden kurulum (cihazı olan kullanıcıyı gereksiz kurulum döngüsüne sokar;
kod yenileme TOTP ile zaten mümkün: `auth.py:711-752`); kapatmada kurtarma kodunu hiç istememek (normal yolu
zayıflatır).

## 9. Tehdit modeli

### 9.1 STRIDE

| Tehdit | Senaryo | Kontrol |
|---|---|---|
| S (kimlik sahtekârlığı) | Saldırgan kullanıcı gibi destek ister. | Yalnız kayıtlı adres; işçinin gönderdiği kod (operatör görmez); DB'de mağaza karşılaştırması, ipucu yok; itiraz penceresi; kurulum için ikinci e-posta kanıtı (5.7). |
| S | Operatör başka operatör gibi davranır. | Kimlik `session_user`; operatör başına ayrı DB parolası; açan ve onaylayan farkı DB'de. |
| T (kurcalama) | Olay ya da başlık satırı değiştirilir, silinir, TRUNCATE edilir. | BEFORE UPDATE/DELETE/TRUNCATE tetikleyicileri; `netkar_app`'te yetki yok; `created_at` sunucu yazar. |
| T | Bekleme süresi kısaltılır. | Süreler `support_gate_settings`'te, yalnız migrasyonla değişir; karşılaştırma DB `now()` ile. |
| R (inkâr) | "Ben onaylamadım." | Her olayda operatör kimliği; harici alarm kutusunda bağımsız iz. |
| I (bilgi sızıntısı) | Operatör hesap varlığını, e-postayı, satıcı numarasını, son 4 haneyi öğrenir. | `open` aynı yanıt; işlevler değer döndürmez, yalnız eşleşme; denetimde kişisel veri yok (DB `CHECK`). |
| I | Kiracı denetiminde operatör kimliği. | Takma ad UUID; ad-kişi eşlemesi ürün dışında. |
| D (hizmet engelleme) | Saldırgan sürekli talep açtırır ya da itiraz eder. | Hedef başına tek açık talep; operatör başına günlük açılış sınırı; itiraz yalnız posta kutusu sahibinde. |
| D | Toplu sıfırlama. | 24 saatte genel üst sınır (öneri 3), aşımda işlev reddeder ve alarm. Kill-switch (9.4). |
| E (yetki yükseltme) | `netkar_app` ele geçirilip sıfırlama yapılır. | `netkar_app`'te `support_gate` USAGE yok; bayrak sütunlarında UPDATE yok. |
| E | Sıfırlama sonrası parolalı saldırgan kendi TOTP'sini kurar. | Kurulum tokenı (5.7); kapı, kurulum bitene dek yalnız güvenlik uçlarını açar. |

### 9.2 Sosyal mühendislik

- Aciliyet: tek kişi modunda asgari 24 saat inceleme + 72 saat pencere yazılımla zorlanır; "bugün lazım" talebi
  teknik olarak hızlandırılamaz. Operatörün "hayır" demesi gerekmez.
- Üçüncü kişi adına talep (muhasebeci, çalışan): yalnız hesap sahibinin kayıtlı adresi; kod o adrese gider.
- Sıfırlamadan hemen sonra mağaza anahtarı değiştirme ya da dışa aktarma (prosedür 3.3 son madde): öneri, sıfırlamadan
  sonra 24 saat `marketplace_accounts` anahtar değişikliği ve dışa aktarma uçları 403 döner (K10). Bu ADR'de yalnız
  öneridir.
- Kimlik belgesi teklifi: araçta belge alanı yoktur; yükleme yolu yoktur.

### 9.3 İçeriden tehdit

- Tek kötü niyetli operatör (çift mod): onay için ikinci DB kimliği gerekir; kodu kendisi göremez, sahte
  `challenge_passed` üretemez.
- Tek operatör = Hasan (solo): yazılım Hasan'a karşı koruma iddia etmez. Kazanım: soğuma süresi, kullanıcının itiraz
  hakkı, harici alarm ve değişmez iz.
- Sunucu root ya da DB superuser: tüm DB kontrollerini atlar. Azaltım: G18; superuser parolasının uygulama ortamında
  bulunmaması (ADR-0004 §5 son madde ile aynı ilke); harici alarm sunucu dışındadır; üç aylık erişim gözden geçirmesi
  (`docs/50_guvenlik.md` bölüm 3).
- Not: `netkar_app` `sessions` tablosunda tablo düzeyi UPDATE taşır (`0001_initial.py:136`); ele geçirilmiş uygulama
  iptal edilmiş oturumu geri açabilir. Bu ADR'nin konusu değil; ayrı bulgu olarak denetime önerilir.

### 9.4 Hız sınırları ve kesme anahtarı

| Sınır | Öneri | Yer |
|---|---|---|
| Operatör başına günlük `open` | 10 | `open_request`, olay sayımı |
| Doğrulama kodu denemesi | 5 / talep | `support_mfa_reset_tokens.attempts` |
| Mağaza karşılaştırma denemesi | 3 / talep | olay sayımı |
| Aynı hedefe yürütme arası | 30 gün (prosedür 4.2/4'teki 24 saatten sıkı) | `execute_reset` |
| Genel yürütme | 3 / 24 saat | `execute_reset` |
| Onay sonrası yürütme süresi | 7 gün, sonra `expired` | `execute_reset` |
| İtiraz ucu | IP başına saatlik (mevcut `IpRateLimitMiddleware` deseni) | API |
| Kurulum bağlantısı yeniden isteme | Kullanıcı başına saatte 3 (`rate_limit_verify_resend_user` ile aynı, `config.py:98`) | API |
| Kesme anahtarı | (a) CLI `SUPPORT_MFA_RESET_ENABLED=false` iken komut çalışmaz; (b) sert kesme: `REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA support_gate FROM netkar_support` (runbook) | CLI + DB |

## 10. Uygulama için iş kırılımı (Sonnet dilimleri)

Her dilim ayrı PR, kendi testleriyle; sıra bağımlılık sırasıdır. Her dilimden sonra Opus güvenlik incelemesi
(kart "bitti kriteri").

| # | Dilim | Dosyalar (mevcut ya da yeni) | Bağımlılık |
|---|---|---|---|
| D1 | Roller: `netkar_support_gate`, `netkar_support`; owner'a `INHERIT FALSE, SET TRUE`; operatör rolü ekleme runbook'u | `app/db/provision.py`, `infra/postgres/init/01-roles.sh`, `services/api/README.md` | yok |
| D2 | Migrasyon 0023 şema: tablolar, değişmezlik tetikleyicileri, RLS, yetkiler, `users` ve `sessions` sütunları, `support_gate_settings`, downgrade korumaları | `migrations/versions/0023_*.py` (yeni) | D1 |
| D3 | `support_gate` işlevleri (open, verify_challenge, check_store_claim, live/red flags, approve, cancel, show) | 0023 içinde | D2 |
| D4 | `execute_reset`, `set_hold`, `release_hold` | 0023 içinde | D3 |
| D5 | `auth_gate` değişiklikleri: `get_session` ve `find_user_for_login` genişlemesi, `object_support_reset`, `complete_mfa_enrollment`; `app/services/auth.py` eşlemeleri | 0023 içinde, `app/services/auth.py` | D2 |
| D6 | API kapısı: `AuthContext` alanları, `get_auth_context` varsayılan ret, `EnrollmentAuthDep`, `MeResponse.mfa_enrollment_required`, setup/enable kurulum tokenı, `totp/enroll-link`, hold yanıtı | `app/api/deps.py`, `app/api/v1/auth.py`, `app/api/v1/me.py`, `app/api/v1/schemas.py` | D5 |
| D7 | İtiraz ucu (GET sayfa verisi + POST), IP sınırı | `app/api/v1/auth.py` ya da yeni `app/api/v1/support.py` | D5 |
| D8 | İşçi görevi `netkar.support_notices` + harici alarm; e-posta şablonları (T5, T7 araç sürümleri) | `app/worker/tasks.py`, yeni servis modülü | D3, D4; prod için gerçek e-posta arka ucu (K12) |
| D9 | CLI `app/tools/support_mfa_reset.py`: alt komutlar `open`, `verify-challenge`, `store-check`, `live-check`, `red-flags`, `approve`, `cancel`, `execute`, `show`, `hold`, `release-hold`; `DATABASE_SUPPORT_URL` (parola istemde `getpass`), kuru çalıştırma varsayılanı olan komutlarda `--apply`, yazılı onay istemi (`app/tools/legal_documents.py:409-413` deseni), çıkış kodları `common.py:24-26` | yeni dosya, `app/tools/common.py` (gerekirse) | D3, D4 |
| D10 | Self-servis boşluğu: `sessions.second_factor`, `_start_session`, `_reauthenticate` taze kurtarma oturumu kuralı, bildirimde kalan kod sayısı | `app/api/v1/auth.py`, `app/services/auth.py`, 0023 | D2 |
| D11 | Web: zorunlu kurulum yönlendirmesi ve kurulum tokenlı akış, itiraz sayfası, kod 0 iken yönlendirme, `account-on-hold` iletisi | `apps/web/src/app/(app)/panel/guvenlik/page.tsx`, `apps/web/src/components/security/security-view.tsx`, panel layout, yeni itiraz sayfası | D6, D7, D10 |
| D12 | Belgeler: `destek_mfa_sifirlama.md` bölüm 3-4 ve şablonlar araca göre; `docs/50_guvenlik.md`'ye kontrol satırı | belgeler | D9, D11 |

## 11. Test listesi

Veritabanı ve migrasyon:

1. 0023 upgrade -> downgrade -> upgrade gidiş dönüşü (`tests/test_migrations.py` deseni); downgrade prod'da satır
   varken reddedilir; kapı bayraklı kullanıcı varken durur; sayı bayrağı yanlışsa durur.
2. Dört yeni tabloda ENABLE + FORCE RLS ve en az bir politika (yeni koruyucu test; `tenant_id` olmadığı için
   `test_rls_idor.py:214` kapsamaz).
3. `netkar_app` ile: `support_gate` işlevlerini çalıştıramaz; destek tablolarını okuyamaz/yazamaz; `users` bayrak
   sütunlarını UPDATE edemez (`test_app_role_is_least_privileged` listesine ek, `test_rls_idor.py:184`).
4. `netkar_support` grubu tablo okuyamaz; yalnız işlev çağırır.
5. Olay ve başlıkta UPDATE, DELETE, TRUNCATE 23514; token tablosunda `used_at` ikinci kez yazılamaz; `created_at`
   istemciden verilemez.
6. `meta`'ya izinsiz anahtar (ör. `email`) yazılamaz (CHECK).
7. İkinci terminal olay, ikinci `approved`, ikinci `notice_sent` 23505.
8. `auth_gate` işlev kümesi testi güncel (`test_rls_idor.py:232`); yeni `support_gate` işlevleri SECURITY DEFINER,
   sabit `search_path`, `PUBLIC` EXECUTE yok.

İşlev davranışı:

9. `open`: hesap var/yok aynı dönüş; yok iken hedef NULL, bildirim kuyruğa girmez; aynı hedefe ikinci açık talep yok.
10. Doğrulama kodu: doğru kod geçer; 5 yanlış denemeden sonra kilit; süresi dolmuş kod reddedilir.
11. Mağaza karşılaştırması: eşleşme/eşleşmeme yalnız boolean; 3 denemeden sonra ret; başka kiracının satıcısıyla
    eşleşmez.
12. Çift mod: aynı `session_user` onaylayamaz (42501); farklı operatör onaylar.
13. Tek kişi modu: `solo_min_review` dolmadan onay reddedilir; dolduktan sonra kabul.
14. `notice_sent` yoksa yürütme reddedilir; pencere dolmadan reddedilir; itirazdan sonra reddedilir; onaydan 7 gün
    sonra `expired`.
15. Yürütme: TOTP alanları temiz, etkin kodlar `revoked_at` aldı, kullanılmış kod `revoked_at` ALMADI, önceden iptal
    edilmiş kod içeren hesapta işlem 23514 vermeden biter, tüm kiracılardaki oturumlar iptal, parola özeti değişmedi,
    olay meta sayıları doğru, her üyelik kiracısına bir `audit_log` satırı.
16. Yürütme içinde denetim yazımı başarısız olursa (ör. kiracı yok) hiçbir alan değişmez (atomiklik).
17. Aynı hedefe 30 gün içinde ikinci yürütme reddedilir; genel günlük üst sınır aşımında ret.
18. Pasif operatör hiçbir işlevi çağıramaz.

API ve akış:

19. Kapı: bayraklı oturumla `/v1/tenant/audit` ve bir veri ucu 403 `mfa-enrollment-required`; izinli listedeki uçlar
    çalışır; yeni bir uç `AuthDep` ile eklendiğinde varsayılan ret (kapalı başarısızlık testi).
20. Kurulum: token olmadan `enable` reddedilir; başka kullanıcının tokenıyla reddedilir; doğru tokenla TOTP açılır,
    bayrak temizlenir, token ikinci kez kullanılamaz.
21. Sıfırlama öncesi verilmiş bekleyen çerezle `totp/verify` başarısız.
22. Hold: doğru parolada 403 `account-on-hold`, yanlış parolada mevcut 401 (ayrım yalnız doğru parolada);
    mevcut oturum geçersiz.
23. İtiraz ucu: geçerli/geçersiz/kullanılmış token aynı yanıt; terminal talepte etkisiz; IP sınırı.
24. Bildirim hatası: yürütme geri alınmaz, `notify_failed` olayı yazılır, görev yeniden dener; T5 gönderilemezse
    pencere başlamaz.
25. E-posta gövdesinde kod dışında kişisel veri ve IP yok (`_queue_mfa_notice` testine benzer).

Self-servis boşluğu:

26. Son kodla giriş + 10 dk içinde yalnız parola ile `totp/disable` kabul; 10 dk sonra ret; kod kalan kullanıcıda ret;
    TOTP ile açılmış oturumda ret; `second_factor` NULL eski oturumda ret.

CLI:

27. Kesme anahtarı kapalıyken çıkış kodu 3, DB'ye bağlanmaz; çıktıda e-posta, kod, token, satıcı numarası yok;
    kuru çalıştırma hiçbir şey yazmaz; yazılı onay eşleşmezse iptal.

## 12. Hasan kararı gereken noktalar

| # | Karar | Öneri |
|---|---|---|
| K1 | İkinci onaylayan kim? Tek kişi modu izinli mi? | Lansmanda tek kişi modu açık; ilk destek personeli ya da güvenilen ikinci kişi operatör olunca çift mod. |
| K2 | Bekleme süreleri | Çift mod: itiraz penceresi 24 saat. Tek kişi: asgari inceleme 24 saat, pencere 72 saat. Onay sonrası geçerlilik 7 gün. |
| K3 | Aynı hesaba yeniden sıfırlama arası | 30 gün |
| K4 | Genel günlük üst sınır | 3 |
| K5 | Hold girişi tamamen kapatsın mı? | Evet (kapatsın); kaldırma yeni talep ve yeniden kanıtla. |
| K6 | Harici alarm adresi | Ürün sunucusunda barınmayan ayrı posta kutusu. |
| K7 | Taze kurtarma oturumu süresi (bölüm 8) | 10 dakika |
| K8 | Mağaza kanıtı olarak hangi alan(lar) yeterli? | `api_key_last4` zorunlu; satıcı numarası tek başına yetmez (kamusal olabilir, doğrulanmadı). |
| K9 | E-postası doğrulanmamış eski hesaplara araç açık mı? | Hayır; önce e-posta doğrulaması (oturumla) istenir; prod'da bu durumda hesap sayısı denetlenir. |
| K10 | Sıfırlama sonrası 24 saat mağaza anahtarı değişikliği ve dışa aktarma engeli | Evet (ayrı kart). |
| K11 | Destek tablolarının saklama süresi | En çok 1 yıl; avukat teyidi (prosedür 3.5). |
| K12 | Gerçek e-posta arka ucu ve sağlayıcı (prod açılış engeli, `config.py:286-288`) | Araçtan önce gelmeli; araç bildirimsiz çalışmaz. |
| K13 | Kurulum süresi (`mfa_enrollment_deadline`) ve kurulum bağlantısı TTL | 7 gün / 72 saat |

## 13. Sonuçlar ve kalan riskler

- Prosedürün asgari 13 gereksinimiyle eşleme (`destek_mfa_sifirlama.md` 4.2): 1 ayrı kimlik (bölüm 4), 2 iki kişi
  (5.3), 3 yeniden doğrulama (operatör DB parolası + G18; ürün tarafında TOTP benzeri ikinci faktör yok, bkz. aşağı),
  4 hedef ve talep numarası zorunlu, serbest arama yok (5.1; e-posta yalnız eşleştirme girdisi, sonuç sızdırmaz),
  5 bekleme (5.3, 5.4), 6 atomik kapsam (5.5), 7 zorunlu kurulum (5.7), 8 bildirim (5.4, 5.6), 9 denetim (5.8),
  10 geri alma (5.9), 11 hız sınırı (9.4), 12 kesme anahtarı (9.4), 13 testler (11).
- Madde 3'ten sapma: operatör için ayrı TOTP istenmedi. DB işlevi TOTP'yi doğrulayamaz (sır DB dışı anahtarla
  şifreli); CLI içinde doğrulamak, aynı DB kimliğiyle `psql` açan için atlanabilir bir kontrol olurdu. Operatörün
  ikinci faktörü sunucuya erişimdeki SSH anahtarı + 2FA'lı paneldir (G18). Bu kabul Hasan onayı ister (K1 ile
  birlikte).
- Gerçek e-posta arka ucu yokken (K12) araç prod'da işlevsizdir; staging'de `file` arka ucuyla denenir.
- Tek kişi modunda yazılım kurucuya karşı koruma sağlamaz; sağladığı şey zaman, kullanıcı itirazı ve iz.
- Doğrulanmadı: Trendyol satıcı numarasının kamusal olup olmadığı; kullanıcının `api_key_last4`'e Trendyol panelinden
  ulaşıp ulaşamadığı; worker rolünün `users.email` okumasının KVKK kaydına etkisi (mevcut bildirimlerle aynı amaç,
  yeni kategori yok varsayımı).
- Bu ADR kodu okuyarak yazıldı; satır numaraları belirtilen dal içindir, değişebilir.
