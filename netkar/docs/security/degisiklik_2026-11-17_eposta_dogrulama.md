# Değişiklik notu: e-posta doğrulaması, ön ele geçirme önlemi, e-posta bağlantıları (S1-S2 güvenlik ve hesap, ilk dilim)

- Tarih: 17 Kasım 2026
- Kapsam: Trello P1 "S1-S2 güvenlik ve hesap" kartının madde 1, 5 ve 6'sı. Madde 2 (MFA yeniden doğrulama, kurtarma kodları), 3 (web TOTP kurulum ekranı) ve 4 (kullanım koşulları sürüm kaydı) bu dilimde YOK.
- Dayanak: `docs/security/denetim_2026-11-06_S1.md` bulguları O-06 (kapandı), O-05 (kısmen; aşağıya bakın), D-06 (kanıtla pekiştirildi).
- Durum: commit edilmedi; koordinatör incelemesi bekliyor. OWASP ASVS L2 V2 (kimlik doğrulama), V3 (oturum).

## Hangi bulgu nasıl kapandı

| Bulgu | Karar | Kanıt (test) | Not |
|---|---|---|---|
| O-06 (ön ele geçirme ve sıfırlamaya dayanıklı saldırgan TOTP'si) | Yeni kayıtlar için kapandı; 0017 öncesi hesaplar için kısmen (aşağıdaki "Dürüst durum") | `test_prehijack_attacker_cannot_lock_out_the_real_owner`, `test_reset_of_legacy_unverified_account_with_enabled_totp_keeps_totp`, `test_reset_of_unverified_account_clears_staged_but_not_enabled_totp_secret`, `test_unverified_account_is_blocked_on_every_write_and_totp_endpoint` (`tests/test_email_verification.py`) | PoC'nin tersi: doğrulanmamış hesap TOTP kuramaz (403 `email-not-verified`); gerçek sahibin parola sıfırlaması hesabı devralır (e-posta doğrulanır, saldırganın oturumları ölür; saldırgan TOTP kuramadığı için temizlenecek bir şey yoktur). |
| O-05 | Kısmen (yalnız O-06 ile örtüşen kısım) | `test_unverified_account_is_blocked_on_every_write_and_totp_endpoint` | `/totp/setup` ve `/totp/enable` artık doğrulanmış e-posta ister. Parola ile yeniden doğrulama, kurtarma kodları, MFA değişikliği bildirimi AÇIK (madde 2). |
| D-06 (sıfırlama tüm oturumları kapatmalı; TOTP korunmalı) | Kapandı | `test_password_reset_keeps_totp_and_revokes_all_sessions_for_verified_account`, `test_reset_of_verified_account_does_not_touch_verification_state` | İki açık oturumlu doğrulanmış hesapta sıfırlama sonrası 0 etkin oturum; yeni parola `totp_required` döner, oturum çerezi vermez; TOTP kodu olmadan giriş yok. |
| Madde 5 (e-posta bağlantıları) | Kapandı | `test_reset_email_link_uses_turkish_web_path_with_token`, `test_register_sends_one_email_with_turkish_web_links_and_hash_only_token` | `/login`, `/forgot-password`, `/reset-password?token=` yerine `/giris`, `/sifre-sifirla`, `/sifre-sifirla?token=`, `/e-posta-dogrula?token=`. `next.config.ts` İngilizce yönlendirmeleri, eski e-postalardaki bağlantılar için bırakıldı. |

## Tasarım

- Migrasyon `0017_email_verification.py` (geri alınabilir; `test_migration_0017_email_verification_is_reversible_and_least_privileged`):
  - `email_verification_tokens`: yalnız SHA-256 özeti, tek kullanımlık, süreli, ENABLE + FORCE RLS, `netkar_app` erişemez (parola sıfırlama deseni).
  - `auth_gate.create_email_verification`, `auth_gate.consume_email_verification` (koşullu UPDATE ile atomik tüketim).
  - `auth_gate.consume_password_reset` yeniden tanımlandı (`reset_claimed_unverified` sütunu eklendi). Hesap doğrulanmamışsa sıfırlama `email_verified_at` atar, bekleyen doğrulama bağlantılarını kapatır ve etkin OLMAYAN TOTP sırrını temizler (etkin TOTP, eski hesap kuralı gereği korunur; aşağıya bakın). Doğrulanmış hesapta TOTP'ye dokunulmaz.
- API: `POST /v1/auth/email/verify` (token, 204, OTURUM ZORUNLU ve token yalnız oturumdaki kullanıcıya aitse kabul; başka kullanıcının ya da geçersiz token'ı aynı 400), `POST /v1/auth/email/resend` (oturumlu, kullanıcı başına 3/saat, IP başına 10/saat; adres istekten alınmaz), `GET /v1/me` yanıtında `email_verified`. Kayıt 202 davranışı ve numaralandırma koruması aynı: mevcut e-postaya doğrulama bağlantısı gitmez, yalnız "zaten kayıtlı" iletisi gider.
- Doğrulanmamış hesap kısıtı: `require_role(..., verified=True)` ile marketplace bağlama/iptal, maliyet yazma ve içe aktarma, kâr ayarı yazma uçları ile TOTP kurulum uçları 403 problem+json (`email-not-verified`). Okuma uçları, `/me`, yeniden gönderme ve çıkış serbest.
- Web: `/e-posta-dogrula?token=` sayfası: otomatik istek yok, açık "E-postamı doğrula" düğmesi; oturum yoksa `/giris?sonra=...` ile girişe, girişten sonra aynı bağlantıya döner (mevcut `safeNextPath` yardımcıları); token okununca `history.replaceState` ile adres çubuğundan silinir; yola `Referrer-Policy: no-referrer` ve `Cache-Control: no-store` (derlenmiş sunucuda doğrulandı). Panelde doğrulanmamış hesap uyarı bandı ve "Yeniden gönder" düğmesi.

## Ele geçirme önleminin gerekçesi

Seçenekler: (a) doğrulanmamış hesabın girişini tümden engellemek, (b) kayıtta var olan doğrulanmamış hesabı ezmek, (c) giriş açık, kritik uçlar kapalı, sıfırlama sahipliği devralır. (c) seçildi: en küçük değişiklik, mevcut 202 ve numaralandırma davranışını korur, saldırganın elde ettiği hesabın hiçbir değeri yoktur (mağaza bağlayamaz, veri yazamaz, TOTP kuramaz) ve gerçek sahibin mevcut "şifremi unuttum" yolu hesabı temiz devralır. (b) başkasının kaydını ezmek hesap sahibi hakkında bilgi sızdırır ve yarış yaratır; (a) yeniden gönderme akışını oturumsuz bırakır ve hesap numaralandırması riskini artırır.

## Bağımsız inceleme turu 1 (0018) ve dürüst durum

- Bulunan zincir: saldırgan kurbanın adresiyle kayıt olup oturumunu açık tutar; kurban ya da e-posta tarayıcısı bağlantıyı açar (sayfa otomatik POST atıyordu), hesap doğrulanır; saldırgan TOTP kurar; kurbanın sıfırlaması TOTP'yi korur (doğrulanmış hesap) ve kurban kilitlenir. Düzeltme: doğrulama oturumlu ve token sahibine bağlı (migrasyon 0018), web otomatik istek atmaz. Kanıt: `test_verify_chain_prehijack_with_open_session_is_closed`, `test_verify_requires_a_session`, `test_verify_with_another_users_session_fails_with_the_same_400`, `test_concurrent_verifications_of_the_same_token_let_only_one_win`.
- Kalan koşul: bağlantıyı kurbanın KENDİ hesabıyla değil, saldırganın açık oturumuyla (ör. kurban saldırganın tarayıcısında) açmaya ikna edilmesi. Bu sosyal mühendisliktir; kayıt e-postası ve sayfa metni "bağlantıyı bu hesapla giriş yaptığınız tarayıcıda açın" der.
- Düşük bulgular: `create_email_verification` kullanıcı satırını `FOR UPDATE` kilitler ve TTL'yi 1-4320 dakikayla sınırlar; doğrulanmamış hesap sıfırlamayla devralınınca deneme süresi baştan başlar (`trial_ends_at = now() + (trial_ends_at - created_at)`; kiracı adı ve veriler SİLİNMEZ, yalnız `trial_ends_at` sütununda `netkar_auth` için dar UPDATE yetkisi); engelleme testi 14 ucun tamamını kapsar ve openapi'deki yazma yolları listeyle karşılaştırılır (yeni yazma ucu kapıya konmazsa test düşer).
- Eski kullanıcı kuralı: doğrulanmamış ve TOTP'si ETKİN hesapta sıfırlama TOTP'yi temizlemez, yalnız e-postayı doğrular. Gerekçe: 0017'den sonra doğrulanmamış hesapta TOTP etkinleştirilemez (403), dolayısıyla "doğrulanmamış + TOTP etkin" yalnız 0017 öncesinde oluşmuş hesaplarda bulunur; bunların gerçek kullanıcı olma olasılığı yüksektir ve ikinci faktörü silinmemelidir. Tarih sütunu karşılaştırması yerine bu değişmez kullanıldı (migrasyon zamanına bağlı sabit gerekmez, geri alınabilir). Etkinleştirilmemiş (yarım kurulum) sır yine temizlenir.
- **O-06 dürüst durum:** 0017 sonrası oluşan hesaplar için kapandı. 0017 ÖNCESİ oluşmuş, doğrulanmamış ve TOTP'si etkin bir hesap gerçekten bir saldırganınsa, sıfırlama onu temizlemez ve gerçek sahip kilitli kalır. Bu açık bilinçli kabul edildi (gerçek kullanıcıyı kilitlemeyi önlemek için) ve prod'a gitmeden önce ELLE denetlenmelidir: `SELECT id, email, created_at FROM users WHERE email_verified_at IS NULL AND totp_enabled` sorgusunun sonucu gözden geçirilmeli (prod verisi bu turda incelenmedi).

## Açık kalanlar ve kalan riskler

- Madde 2, 3, 4 (bu dilim dışı).
- Doğrulama bağlantısı artık yalnız kaydeden oturumla çalışır; kurban/tarayıcı tıklaması hesabı doğrulamaz. Kalan: kurban saldırganın oturumunda bağlantıyı açarsa (sosyal mühendislik). Doğrulama sırasında parola belirletme (tam çözüm) ayrı karar.
- Mevcut kullanıcılar geriye dönük doğrulanmış sayılmadı (ön ele geçirmeyi meşrulaştırırdı): kullanıcı panelden bağlantıyı yeniden ister. Demo tohumu kullanıcıları doğrulanmış açılır (`seed_demo`).
- Doğrulanmamış hesapların 24-72 saat sonra silinmesi (O-06 önerisi) YAPILMADI: veri silme yasağı; ayrı karar ve ayrı iş gerektirir.
- D-05 (token'ın URL parçasına/POST değişimine taşınması) açık: doğrulama ve sıfırlama bağlantıları hâlâ `?token=` taşır.
- Gerçek e-posta arka ucu yok (dev/test: dosya/bellek); prod başlatma engeli (D-08) sürüyor.


---

# Dilim 2: MFA yeniden doğrulama, kurtarma kodları, web TOTP ekranı (0019)

- Tarih: 17 Kasım 2026. Kapsam: Trello P1 "S1-S2 güvenlik ve hesap" kartı madde 2 ve 3, önceki dilim düşük bulgusu (D) ve bilgi bulgusu (B). Madde 4 (kullanım koşulları sürüm kaydı) bu dilimde YOK. Durum: commit edilmedi; koordinatör incelemesi bekliyor. OWASP ASVS L2 V2.5 (kurtarma), V2.8 (OTP), V3 (oturum).

## O-05 durumu (dürüst)

| Konu | Durum | Kanıt (test) |
|---|---|---|
| `/totp/setup` ve `/totp/enable` yeniden doğrulama | Kapandı: güncel parola zorunlu (yoksa 422, yanlışsa 403 `reauth-failed`, işlem yapılmaz) | `test_setup_and_enable_require_the_current_password` |
| TOTP etkinken değişiklik (kapatma, kod yenileme) | Kapandı: parola + güncel TOTP ya da kurtarma kodu | `test_disable_requires_password_and_current_code_and_revokes_other_sessions`, `test_regenerate_replaces_codes_revokes_other_sessions_and_needs_reauth` |
| Başarısız yeniden doğrulama | Mevcut altyapıya bağlı: kullanıcı başına hız sınırı (`reauth:user`), `totp_failed_count` ve `totp_locked_until` kilidi (TOTP girişiyle paylaşılır), denetim kaydı `auth.reauth_failed` | `test_failed_reauth_is_rate_limited_and_locks_through_existing_machinery` |
| Kurtarma kodları | Kapandı: etkinleştirmede 10 kod, düz metin yalnız o yanıtta | `test_enable_returns_ten_codes_once_and_stores_only_keyed_hashes` |
| TOTP kapatma yolu | Kapandı: `POST /v1/auth/totp/disable` | aynı test |
| Diğer oturumların iptali | Kapandı: kapatma ve kod yenilemede çağıran oturum hariç tümü (`auth_gate.revoke_other_sessions`) | aynı testler |
| MFA değişikliğinde e-posta bildirimi | AÇIK: yapılmadı (gerçek e-posta arka ucu yok, D-08). Denetim kaydı var (`auth.totp_enabled`, `auth.totp_disabled`, `auth.recovery_codes_regenerated`) | |
| Destek üzerinden kimlik doğrulamalı MFA sıfırlama süreci belgesi | AÇIK | |

O-05 "kapandı (e-posta bildirimi ve destek süreci hariç)" olarak değerlendirilmelidir.

## Tasarım kararları

- **Özet yöntemi:** HMAC-SHA256, anahtar `derive_key(master, "recovery-code")` (pepper), girdi `user_id:kod`. Kodlar 60 bit (12 karakter, 32'lik alfabe, `secrets`) olduğundan yavaş parola özeti gerekmez; çevrimiçi tahmin hız sınırı ve 5 hatada 15 dakikalık kilitle sınırlıdır (TOTP ile aynı sayaç). DB sızsa bile anahtar olmadan kod türetilemez.
- **Yarış önlemi:** `UPDATE mfa_recovery_codes SET used_at = now() WHERE user_id = ? AND code_hash = ? AND used_at IS NULL AND revoked_at IS NULL RETURNING id` (tek ifade, atomik). Kanıt: `test_concurrent_use_of_the_same_recovery_code_lets_only_one_win` (8 eşzamanlı deneme, 1 kazanan).
- **Şema (0019):** `mfa_recovery_codes` ENABLE + FORCE RLS (`user_id = app.user_id`), `netkar_app` yalnız SELECT, INSERT ve `used_at/revoked_at` UPDATE; DELETE yok (kullanılan `used_at`, yenilenen/kapatılan `revoked_at` alır, satır silinmez); worker erişemez. `auth_gate.revoke_other_sessions(user, keep)` SECURITY DEFINER, yalnız çağıranın kendi `app.user_id` bağlamı için çalışır (başkası için 42501).
- **Giriş:** `/totp/verify` 6 haneli TOTP ya da kurtarma kodu kabul eder (aynı uç, aynı IP/kullanıcı sınırı ve kilit). Kullanım `auth.recovery_code_used` (kalan sayı) ve `auth.login_recovery` olarak denetlenir; hatalar `auth.recovery_failed`. Kalan kod sayısı `GET /v1/me` içinde `recovery_codes_remaining`.
- **Hata durumu:** yeniden doğrulama başarısızlığı 401 değil 403 döner (web istemcisi 401'i "oturum bitti" sayar).
- **Sözleşme değişikliği:** `/totp/setup` gövde `{password}`, `/totp/enable` gövde `{code, password}` ve 204 yerine 200 `{recovery_codes}` döner (geriye dönük uyumsuz; web ve testler güncellendi). Yeni: `/totp/disable`, `/totp/recovery-codes`; ikisi de doğrulanmış e-posta kapısı arkasında (kapı testi 16 uca çıktı).

## (D) Doğrulanmamış hesapta TOTP: veritabanı tetikleyicisi

`users_totp_requires_verified_email` (BEFORE INSERT OR UPDATE): `email_verified_at IS NULL` iken `totp_enabled = true` yazılamaz (23514). Karar yalnız yeni INSERT'te ve `totp_enabled`/`email_verified_at` değerinin değiştiği UPDATE'te verilir; 0017 öncesi (doğrulanmamış + TOTP etkin) satır olduğu gibi kalır ve diğer sütunları (zaman adımı, sayaç) güncellenebilir. 0018 kuralının (sıfırlama etkin TOTP'yi korur) yalnız eski hesaplara özgü olduğu kanıtı: `test_trigger_blocks_totp_on_unverified_accounts_for_new_writes`, `test_legacy_unverified_totp_rows_are_untouched_by_the_trigger_and_rule_stays_legacy_only` (eski durum yalnız tetikleyici kapatılarak taklit edilir; API yeni duruma ulaşamaz). O-06 prod denetimi notu (elle `SELECT ... WHERE email_verified_at IS NULL AND totp_enabled`) geçerliliğini korur.

## (B) Giriş sayfasında token

`/giris?sonra=/e-posta-dogrula?token=...` ve `/iki-adim?sonra=...`: sayfa açılınca `history.replaceState` ile token taşıyan `sonra` adresten silinir (hedef bileşen durumunda korunur). Kanıt: `auth-forms.test.tsx` "Giriş akışı: adres çubuğundaki token", `redact-url.test.ts`.

## Web (madde 3)

`/panel/guvenlik` (Ayarlar sayfasından bağlantılı): parola ile yeniden doğrulama, QR (istemcide `qrcode-generator@2.0.4`, MIT, sıfır bağımlılık, `npm audit` 0 bulgu; çıktı React SVG yolu, innerHTML ve dış servis yok), elle anahtar ve kopyala, kod doğrulama, kurtarma kodlarını bir kez gösterme (kopyala, `.txt` indir, "kaydettim" onayı olmadan "Bitti" kapalı, sayfadan ayrılırken uyarı), TOTP kapatma ve kod yenileme. Girişte "Kurtarma kodu kullan". Parola yalnız bileşen belleğinde tutulur; kodlar storage, toast ya da günlüğe yazılmaz.

## Açık kalanlar

- MFA değişikliği e-posta bildirimi, destek MFA sıfırlama süreci belgesi (yukarıda).
- Kurtarma kodu kalmayınca ya da TOTP cihazı kaybolunca self-servis yol: yalnız parola sıfırlama TOTP'yi korur; kurtarma kodları bittiyse kullanıcı oturum açıkken yenileyebilir, açık oturum yoksa destek süreci gerekir (belgelenmedi).
- Madde 4 (kullanım koşulları sürüm kaydı), D-05 (token URL parçası), D-08 (e-posta arka ucu) bu dilimde yok.
- e2e (Playwright) `/panel/guvenlik` için yazılmadı; gerçek API e2e'sinin TOTP adımı yeni sözleşmeye güncellendi ama bu ortamda koşulmadı.
- Migrasyon downgrade'i `mfa_recovery_codes` tablosunu düşürür (özetler kaybolur; kullanıcılar kodları yeniden üretir).


## Dilim 2, bağımsız inceleme turu 1 (0020)

- **MFA bildirimi (ASVS V2.2.3), kapandı:** TOTP etkinleştirme, kapatma, kurtarma kodu yenileme ve kurtarma koduyla giriş sonrası kullanıcıya e-posta gider (`EmailSender` + `BackgroundTasks`, yanıttan sonra; gönderim hatası yutulur ve yalnız adressiz uyarı günlüğe yazılır). Gövde: işlem türü, UTC zamanı, `/sifre-sifirla` bağlantısı; kod ve IP yok. Testler: `test_mfa_changes_and_recovery_login_send_a_notice_without_secrets`, `test_recovery_code_login_sends_a_notice`, `test_notice_failure_does_not_break_the_operation`. Bu, önceki "e-posta bildirimi AÇIK" maddesini kapatır (gerçek e-posta arka ucu hâlâ yok, D-08).
- **Düşük 1:** yeniden doğrulamada PAROLA hataları `totp_failed_count` ve giriş kilidine yazılmaz (çalınmış çerezle kurbanın girişini kilitleme DoS'u); yalnız `reauth:user` hız sınırı ve denetim kaydı işler. İkinci faktör hataları kilidi besler (parola gerektirdiği için çerezle tek başına tetiklenemez). Testler: `test_password_failures_rate_limited_but_never_touch_the_login_lock`, `test_second_factor_failures_in_reauth_feed_the_login_lock`.
- **Düşük 2:** `replace_recovery_codes` kullanıcı satırını `FOR UPDATE` ile kilitler; `test_concurrent_regenerations_leave_exactly_ten_active_codes`.
- **Düşük 3:** etkinleştirme de diğer oturumları iptal eder; `test_enable_revokes_other_sessions`.
- **Düşük 4:** `/totp/recovery-codes` yalnız TOTP kabul eder (kurtarma kodu 422); kapatma kurtarma kodunu kabul etmeye devam eder. Web formu buna uyar.
- **Düşük 5 (0020, 0019'a dokunulmadı):** `mfa_recovery_codes` BEFORE UPDATE tetikleyicisi, dolmuş `used_at`/`revoked_at` değiştirilemez (23514); `auth_gate.revoke_other_sessions` `search_path` sonuna `pg_temp`. Geri alınabilir; `test_migration_0020_is_reversible_and_hardens_search_path`, `test_recovery_code_marks_are_immutable`.
- **Web:** `downloadTextFile` `revokeObjectURL`'i 1 sn erteler; kurtarma kodu doğrulaması yalnız boşluk ve tire ayracı kabul eder (backend ile aynı).
