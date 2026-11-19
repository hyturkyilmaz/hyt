# Değişiklik notu: sessions tablosunda UPDATE yetkisinin daraltılması (migrasyon 0023)

- Tarih: 19 Kasım 2026. Durum: commit edilmedi; koordinatör incelemesi bekliyor. Dayanak: OWASP ASVS L2 V3 (oturum yönetimi), en az yetki ilkesi.

## Sorun

`0001_initial.py`, `netkar_app` rolüne `sessions` üzerinde tablo düzeyi `UPDATE` vermişti. Uygulama yalnız iki sütunu günceller: `last_seen_at` (`touch_session`) ve `revoked_at` (`revoke_session`). Tablo düzeyi yetki, ele geçirilmiş bir uygulama bağlantısının (ör. SQL enjeksiyonu) iptal edilmiş oturumu geri açmasına (`revoked_at = NULL`), `expires_at` uzatmasına, oturumu başka kullanıcıya ya da kiracıya bağlamasına izin verirdi.

## Değişiklik (geri alınabilir, veri silinmez)

- `netkar_app`: tablo düzeyi `UPDATE` kalktı, yalnız `UPDATE (last_seen_at, revoked_at)`. `netkar_auth` (auth_gate işlevlerinin sahibi; işlevler yalnız `revoked_at` yazar): tablo düzeyi `UPDATE` kalktı, yalnız `UPDATE (revoked_at)`. SELECT ve INSERT aynı.
- BEFORE UPDATE tetikleyicisi `sessions_immutable_guard` (23514, superuser dahil, `ENABLE ALWAYS`: `session_replication_role = replica` ile atlanamaz):
  - `revoked_at` dolduktan sonra değiştirilemez; ilk doldurma `now() +- 5 dk` içinde olmalı.
  - `last_seen_at` yalnız ileri gider ve `now() + 5 dk` sınırını aşamaz. Uygulama tarafında `touch_session` bu yüzden `GREATEST(last_seen_at, now())` yazar, `revoke_session` `now()` yazar (veritabanı saati: uygulama saati kayıksa tetikleyicinin 5 dk penceresine takılmaz; eşzamanlı isteklerde eski değer geri çekip 23514 üretmez). Uygulama saati yalnız karşılaştırmalarda kullanılır.
  - `expires_at` yalnız kısaltılabilir.
  - `id`, `token_hash`, `user_id`, `tenant_id`, `created_at` hiçbir rolle değiştirilemez (sütun yetkisi yalnız uygulama ve auth rolünü durdurur; tetikleyici sahip ve superuser yolunu da kapatır).
- **Sınır:** tablo sahibi ya da superuser `ALTER TABLE sessions DISABLE TRIGGER sessions_immutable_guard` ile tetikleyiciyi kapatabilir (DDL yetkisi). Testlerin zaman kaydırması (`tests/session_helpers.py`) bu yolu kullanır. `ip_hash` ve `user_agent` tetikleyici kapsamı dışında (sütun yetkisi yok, uygulama yazmaz).
- `auth_gate` işlevleri değişmedi.
- Downgrade: tetikleyici ve işlev kaldırılır, iki role tablo düzeyi `UPDATE` geri verilir; sütun düzeyi ACL kalıntısı kalmaz (testle doğrulanır).

## Kanıt

`tests/test_session_privileges.py` (22 test): yetki matrisi (her sütun, iki rol), 42501 ve 23514 ayrımı, iptal geri açma reddi (uygulama, `netkar_auth`, superuser), gerçek ikinci kullanıcı/kiracıya taşıma reddi, `last_seen_at` geri/ileri sınırı, iptal zamanı penceresi, `expires_at` yalnız kısalır, replica modunda da tetik, aynı değerle yeniden yazma serbest, 0023 upgrade/downgrade/upgrade döngüsü (`attacl` kalıntısı yok). `test_auth_flow.py` zaman kaydırmayı `session_guard_disabled` ile yapar (tetikleyici geçici kapanır, `ENABLE ALWAYS` ile geri açılır).

## Açık riskler (kapsam dışı, ayrı iş)

- **`netkar_app` INSERT yetkisi:** uygulama rolü `sessions`'a INSERT ile istediği kiracı ve kullanıcı adına, istediği `expires_at` ile uzun süreli oturum yaratabilir (RLS yalnız kiracıyı sınırlar). Öneri: `auth_gate.create_session` SECURITY DEFINER işlevi (süre ve kimlik sunucuda üretilir, kullanıcı-kiracı üyeliği doğrulanır) ve `netkar_app`'ten `sessions` INSERT yetkisinin kaldırılması.
- **`memberships`:** `netkar_app` tablo düzeyi `SELECT, INSERT, UPDATE` sahibi; `role` sütunu güncellenerek rol yükseltilebilir. Sütun düzeyine daraltma ve rol değişikliği için ayrı korumalı yol gerekir.
- **`tenants`:** `netkar_app` tablo düzeyi `UPDATE` sahibi; yalnız gereken sütunlara (ör. `name`) daraltılmalı.
