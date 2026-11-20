# Değişiklik notu: uyarı ve bildirim tabloları (migrasyon 0025, ADR-0009 D2)

- Tarih: 20 Kasım 2026. Kapsam: yalnız şema, tetikleyiciler, RLS, yetkiler, gate işlevleri, ORM; kural, iş, API, gönderim yok.
- Tablolar (hepsi ENABLE + FORCE RLS): `alert_events`, `alert_event_transitions`, `alert_rule_settings`,
  `notification_preferences`, `notification_settings`, `push_subscriptions`, `notification_outbox`, `alert_evaluations`.
- Olay durumu yalnız geçiş defterine INSERT ile değişir. Koruma `pg_trigger_depth() >= 2` ile yapılır (ADR'deki `set_config`
  bayrağı yerine: noktalı GUC her rolde USERSET olduğundan sahtelenebilir, 0013 dersi). Kimlik sütunları ve defter
  `ENABLE ALWAYS` tetikleyicilerle superuser ve replica rolüne karşı da korunur (TRUNCATE tetikleyicileri 0022 gibi hariç).
- Worker yeni yetkiler: olay INSERT/sınırlı UPDATE, geçiş INSERT, outbox ve değerlendirme yazımı, `report_data_revisions`
  SELECT (kiracı politikalı), gate işlevleri. `netkar_app` olay ve outbox'a yazamaz; outbox'a hiç erişemez; push şifreli
  sütunlarını okuyamaz. Bu, ADR-0005 §6 worker kapsamını genişletir; güvenlik incelemesi gerekir.
- `notify_gate.email_for(outbox_id)`: satır `pending`, `email`, `not_before <= now()` ve kiracısı `app.tenant_id` ile eşleşmeli.
  Bu, hata ve programlama yanlışına karşı derinlemesine savunmadır; GUC taklit eden kötü niyetli worker'a karşı tam sınır değildir.
  `alert_gate.purge_resolved` (13 ay), `purge_outbox` ve `purge_push_subscriptions` (30 gün) saklama için eklendi.
- `payload`/`counts`: izin listeli CHECK (her derinlikte anahtar listesi, metin uzunluğu, e-posta benzeri değer reddi).
  Outbox'a `failed_permanent` durumu eklendi; push benzersizliği kısmi (`revoked_at IS NULL`).
- Yeni NOLOGIN rol `netkar_notify_gate`: migrasyondan ÖNCE `provision_roles` / `01-roles.sh` ile kurulmalı; var olan
  ortamda README'deki SQL çalıştırılır. Migrasyon rol yoksa durur.
- Yeni tablolar veri sürüm tetikleyici listesinde DEĞİL (döngü riski); test korur.
- Downgrade: prod'da daima reddedilir; sekiz tabloda kayıt varsa `NETKAR_ALLOW_ALERT_DATA_LOSS=<toplam kayıt>` tam eşleşmeli.
- Testler: `tests/test_alert_schema.py`.
