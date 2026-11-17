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
