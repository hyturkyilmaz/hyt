# Değişiklik notu: e-posta doğrulaması, ön ele geçirme önlemi, e-posta bağlantıları (S1-S2 güvenlik ve hesap, ilk dilim)

- Tarih: 17 Kasım 2026
- Kapsam: Trello P1 "S1-S2 güvenlik ve hesap" kartının madde 1, 5 ve 6'sı. Madde 2 (MFA yeniden doğrulama, kurtarma kodları), 3 (web TOTP kurulum ekranı) ve 4 (kullanım koşulları sürüm kaydı) bu dilimde YOK.
- Dayanak: `docs/security/denetim_2026-11-06_S1.md` bulguları O-06 (kapandı), O-05 (kısmen; aşağıya bakın), D-06 (kanıtla pekiştirildi).
- Durum: commit edilmedi; koordinatör incelemesi bekliyor. OWASP ASVS L2 V2 (kimlik doğrulama), V3 (oturum).

## Hangi bulgu nasıl kapandı

| Bulgu | Karar | Kanıt (test) | Not |
|---|---|---|---|
| O-06 (ön ele geçirme ve sıfırlamaya dayanıklı saldırgan TOTP'si) | Kapandı | `test_prehijack_attacker_cannot_lock_out_the_real_owner`, `test_reset_of_unverified_account_clears_totp_even_if_it_was_somehow_enabled`, `test_unverified_account_is_blocked_on_write_and_totp_endpoints` (`tests/test_email_verification.py`) | PoC'nin tersi: doğrulanmamış hesap TOTP kuramaz (403 `email-not-verified`); gerçek sahibin parola sıfırlaması hesabı devralır (e-posta doğrulanır, olası TOTP temizlenir, saldırganın oturumları ölür). |
| O-05 | Kısmen (yalnız O-06 ile örtüşen kısım) | `test_unverified_account_is_blocked_on_write_and_totp_endpoints` | `/totp/setup` ve `/totp/enable` artık doğrulanmış e-posta ister. Parola ile yeniden doğrulama, kurtarma kodları, MFA değişikliği bildirimi AÇIK (madde 2). |
| D-06 (sıfırlama tüm oturumları kapatmalı; TOTP korunmalı) | Kapandı | `test_password_reset_keeps_totp_and_revokes_all_sessions_for_verified_account`, `test_reset_of_verified_account_does_not_touch_verification_state` | İki açık oturumlu doğrulanmış hesapta sıfırlama sonrası 0 etkin oturum; yeni parola `totp_required` döner, oturum çerezi vermez; TOTP kodu olmadan giriş yok. |
| Madde 5 (e-posta bağlantıları) | Kapandı | `test_reset_email_link_uses_turkish_web_path_with_token`, `test_register_sends_one_email_with_turkish_web_links_and_hash_only_token` | `/login`, `/forgot-password`, `/reset-password?token=` yerine `/giris`, `/sifre-sifirla`, `/sifre-sifirla?token=`, `/e-posta-dogrula?token=`. `next.config.ts` İngilizce yönlendirmeleri, eski e-postalardaki bağlantılar için bırakıldı. |

## Tasarım

- Migrasyon `0017_email_verification.py` (geri alınabilir; `test_migration_0017_email_verification_is_reversible_and_least_privileged`):
  - `email_verification_tokens`: yalnız SHA-256 özeti, tek kullanımlık, süreli, ENABLE + FORCE RLS, `netkar_app` erişemez (parola sıfırlama deseni).
  - `auth_gate.create_email_verification`, `auth_gate.consume_email_verification` (koşullu UPDATE ile atomik tüketim).
  - `auth_gate.consume_password_reset` yeniden tanımlandı (`reset_claimed_unverified` sütunu eklendi). Hesap doğrulanmamışsa sıfırlama `email_verified_at` atar, TOTP sırrı/etkinliği/sayaçlarını temizler ve bekleyen doğrulama bağlantılarını kapatır. Doğrulanmış hesapta TOTP'ye dokunulmaz.
- API: `POST /v1/auth/email/verify` (token, 204, oturum gerekmez), `POST /v1/auth/email/resend` (oturumlu, kullanıcı başına 3/saat, IP başına 10/saat; adres istekten alınmaz), `GET /v1/me` yanıtında `email_verified`. Kayıt 202 davranışı ve numaralandırma koruması aynı: mevcut e-postaya doğrulama bağlantısı gitmez, yalnız "zaten kayıtlı" iletisi gider.
- Doğrulanmamış hesap kısıtı: `require_role(..., verified=True)` ile marketplace bağlama/iptal, maliyet yazma ve içe aktarma, kâr ayarı yazma uçları ile TOTP kurulum uçları 403 problem+json (`email-not-verified`). Okuma uçları, `/me`, yeniden gönderme ve çıkış serbest.
- Web: `/e-posta-dogrula?token=` sayfası (yükleniyor, başarılı, hata), panelde doğrulanmamış hesap uyarı bandı ve "Yeniden gönder" düğmesi.

## Ele geçirme önleminin gerekçesi

Seçenekler: (a) doğrulanmamış hesabın girişini tümden engellemek, (b) kayıtta var olan doğrulanmamış hesabı ezmek, (c) giriş açık, kritik uçlar kapalı, sıfırlama sahipliği devralır. (c) seçildi: en küçük değişiklik, mevcut 202 ve numaralandırma davranışını korur, saldırganın elde ettiği hesabın hiçbir değeri yoktur (mağaza bağlayamaz, veri yazamaz, TOTP kuramaz) ve gerçek sahibin mevcut "şifremi unuttum" yolu hesabı temiz devralır. (b) başkasının kaydını ezmek hesap sahibi hakkında bilgi sızdırır ve yarış yaratır; (a) yeniden gönderme akışını oturumsuz bırakır ve hesap numaralandırması riskini artırır.

## Açık kalanlar ve kalan riskler

- Madde 2, 3, 4 (bu dilim dışı).
- Doğrulama bağlantısına, hesabı OLUŞTURAN saldırgan değil, kurban tıklarsa hesap saldırganın parolasıyla doğrulanmış olur. Önlem: kayıt e-postası "siz oluşturmadıysanız tıklamayın, parolanızı sıfırlayın" der; sıfırlama doğrulanmış hesapta da parolayı ve tüm oturumları devralır, fakat doğrulanmış hesapta TOTP temizlenmez. Doğrulama sırasında parola belirletme (tam çözüm) ayrı karar.
- Mevcut kullanıcılar geriye dönük doğrulanmış sayılmadı (ön ele geçirmeyi meşrulaştırırdı): kullanıcı panelden bağlantıyı yeniden ister. Demo tohumu kullanıcıları doğrulanmış açılır (`seed_demo`).
- Doğrulanmamış hesapların 24-72 saat sonra silinmesi (O-06 önerisi) YAPILMADI: veri silme yasağı; ayrı karar ve ayrı iş gerektirir.
- D-05 (token'ın URL parçasına/POST değişimine taşınması) açık: doğrulama ve sıfırlama bağlantıları hâlâ `?token=` taşır.
- Gerçek e-posta arka ucu yok (dev/test: dosya/bellek); prod başlatma engeli (D-08) sürüyor.
