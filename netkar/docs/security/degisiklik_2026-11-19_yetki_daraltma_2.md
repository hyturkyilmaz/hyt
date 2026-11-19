# Değişiklik notu: sessions INSERT, memberships ve tenants yazma yetkilerinin daraltılması (migrasyon 0024)

- Tarih: 19 Kasım 2026. Durum: commit edilmedi; koordinatör incelemesi bekliyor. Dayanak: OWASP ASVS L2 V3 (oturum yönetimi), V4 (erişim denetimi), en az yetki ilkesi. Önceki adım: `degisiklik_2026-11-19_oturum_yetkisi.md` (0023) ve oradaki "açık riskler".

## Sorun

`netkar_app` (ele geçirilmiş bir bağlantı, ör. SQL enjeksiyonu) 0001'den kalan tablo düzeyi yetkilerle şunları yapabilirdi: `sessions`'a istediği kiracı/kullanıcı adına, istediği `expires_at` ile oturum eklemek; `memberships.role` değerini `owner` yapmak ya da üyeliği başka kullanıcıya bağlamak; `tenants.plan/status/trial_ends_at` (faturalama durumu) değiştirmek.

## Kod incelemesi (uygulama rolünün gerçek yazmaları)

- `sessions`: tek INSERT `app/services/auth.py::create_session` (çağıran: `_start_session`, giriş/TOTP/kayıt sonrası). UPDATE zaten 0023'te daraldı.
- `memberships`, `tenants`: uygulama kodu yalnız SELECT yapar (`/v1/me`, `/v1/tenant/members`, kâr ayarı geçmişi üye sorgusu). Yazan tek yol `auth_gate.register_account` (sahibi `netkar_auth`). `seed_demo` de bu işlevi kullanır. Rol değiştirme, üye davet etme ya da kiracı güncelleme akışı yoktur.

## Değişiklik (geri alınabilir, veri silinmez)

1. **`auth_gate.create_session(user_id, tenant_id, token_hash, ip_hash, user_agent, absolute_seconds)`**: SECURITY DEFINER, sahibi `netkar_auth`, `search_path = pg_catalog, public, pg_temp` (pg_temp en sonda), PUBLIC'ten EXECUTE alınmış, yalnız `netkar_app` çalıştırır. Yalnız sunucu üretimli alanlar yazılır: `created_at = last_seen_at = now()`, `revoked_at = NULL`, `expires_at = now() + LEAST(absolute_seconds, 2592000)`. **Bağlam denetimi:** `p_tenant_id` ve `p_user_id`, isteğin RLS bağlamıyla (`app.tenant_id`, `app.user_id`) eşleşmiyorsa (bağlamsız çağrı dahil) 42501; `_start_session` iki bağlamı da işlevden önce kurar (`set_rls_context`). Kullanıcının kiracıda üyeliği yoksa 42501. Token özeti 64 haneli küçük harf hex değilse, IP özeti (`ip_hash_for`: 32 haneli hex, zorunlu) geçersizse, user_agent 200 karakterden uzunsa ya da süre < 1 ise 22023. `netkar_auth`'a yalnız gereken 8 sütunda INSERT verildi (`id`, `revoked_at` dışarıda). `netkar_app`'ten `sessions` INSERT kalktı. `create_session` Python işlevi artık bu işlevi çağırır (`now` parametresi kaldırıldı; hiçbir çağıran kullanmıyordu).
   - **Süre tek kaynağı:** `app.core.config.SESSION_ABSOLUTE_MAX_SECONDS` (30 gün). `Settings.session_absolute_seconds` varsayılanı bu sabittir ve artık `60..30 gün` ile sınırlıdır; işlev aynı değeri üst sınır olarak taşır. Ayar kısaltabilir, uzatamaz. Testle eşitlik doğrulanır (işlev tanımı sabiti içerir).
   - **BEFORE INSERT tetikleyici alternatifi gerekmedi:** işlev yaklaşımı mevcut akışı bozmadı (RLS bağlamı işlevden önce zaten kuruluyor, aynı işlemde çalışıyor).
2. **`memberships`**: `netkar_app`'ten INSERT ve UPDATE tamamen kalktı (yalnız SELECT). Kodda yazma akışı olmadığı için "gereken sütun" kümesi boştur; sütun düzeyi GRANT eklemek kullanılmayan yetki olurdu. Ek olarak BEFORE UPDATE tetikleyicisi `memberships_immutable_guard` (`ENABLE ALWAYS`, replica modunda da çalışır): `id`, `user_id`, `tenant_id`, `created_at` hiçbir rolle (superuser dahil) değişmez (23514); rol yükseltme (viewer < admin < owner) yalnız superuser ya da `netkar_owner` ile yapılabilir, diğer roller 42501 alır (yetki yanlışlıkla geri verilse bile kendi rolünü yükseltemez).
3. **`tenants`**: `netkar_app`'ten UPDATE tamamen kalktı (yalnız SELECT); aynı gerekçe. Tetikleyici `tenants_immutable_guard` (`ENABLE ALWAYS`): `id` ve `created_at` değişmez (23514).
- **Sınır (0023 ile aynı):** tablo sahibi ya da superuser `ALTER TABLE ... DISABLE TRIGGER` ile tetikleyicileri kapatabilir (DDL yetkisi). `tests/session_helpers.py::tenant_guard_disabled` bunu `created_at` kaydırması için kullanır (`test_email_verification.py`).
- Downgrade: tetikleyiciler ve işlevler kaldırılır, `netkar_auth`'tan `sessions` INSERT alınır, `netkar_app`'e 0001'deki tablo düzeyi INSERT/UPDATE geri verilir. Sütun düzeyi ACL kalıntısı kalmaz (iki downgrade'de ham `relacl`/`attacl` aynı, testle doğrulanır).

## Kanıt

`tests/test_privilege_narrowing_2.py` (18 test): yetki matrisi (iki rol, her sütun), sahte oturum INSERT'i 42501, `create_session` sunucu alanları, süre üst sınırı, üyelik dışı kullanıcı/kiracı ve RLS bağlamı uyuşmazlığı/bağlamsız çağrı reddi (42501), hatalı argüman (22023, 23505), worker rolünün çalıştıramaması, işlevin SECURITY DEFINER/sahip/search_path/EXECUTE nitelikleri, memberships ve tenants yazma reddi, rol yükseltme ve kimlik tetikleyicileri (geçici GRANT ile yetkiden bağımsız), superuser ve `netkar_owner` yükseltme yolunun sürmesi, replica modunda tetikleyici, mevcut giriş/çıkış/üye/oturum akışı, 0024 upgrade/downgrade/upgrade döngüsü (veri silinmez). Güncellenen mevcut testler: `test_rls_idor.py` (tenants UPDATE artık 42501; auth_gate işlev listesine `create_session`), `test_session_privileges.py` (sessions INSERT artık False), `test_email_verification.py` (created_at kaydırma tetikleyici kapalıyken).

## Açık riskler

- **`create_session` giriş kanıtı istemez, ama bağlama bağlıdır:** işlev yalnız çağıranın RLS bağlamındaki (`app.tenant_id`, `app.user_id`) üyelik için oturum açar. SQL enjeksiyonu altındaki saldırgan GUC değerlerini kendisi ayarlayabildiğinden bu, başka kullanıcı/kiracı için oturum açılmasını tek başına engellemez; kanıtsız oturum yalnız kendi bağlamındaki üyelik için değil, bağlamı taklit edebildiği her üyelik için mümkün kalır (RLS'in kendisiyle aynı sınır, ADR-0001 §6, denetim B-01). Keyfi süre ve keyfi (üye olmayan) çift kapandı. Öneri: giriş kanıtını (parola/TOTP sonucu) işleve imzalı bağlamak ya da oturum açmayı doğrulamayla tek `auth_gate` işlevinde birleştirmek (ayrı iş).
- **Oturum zamanları superuser/owner yolunda denetimsiz:** `sessions` için BEFORE INSERT tetikleyicisi eklenmedi (işlev yeterli görüldü); tablo sahibi ya da superuser hâlâ doğrudan INSERT edebilir (DDL/yönetici yetkisi kapsamı).
- **Rol yükseltme yalnız ayrıcalıklı rollerle:** uygulama içinde üye davet/rol değiştirme özelliği eklenirse ayrı bir SECURITY DEFINER işlevi (çağıran rolü ve kendi rolünü yükseltememe, son owner düşürülememe kuralları) ve sütun düzeyi GRANT gerekir. "Son owner düşürülemez" kuralı şimdi uygulanmadı: mevcut testler tek owner'ı yönetici bağlantısıyla düşürüyor ve uygulama yolu kapalı.
- **Rol kontrolü `current_user` tabanlı:** `SET ROLE netkar_owner` yapabilen bir bağlantı tetikleyiciyi aşar; `netkar_owner` çalışma zamanında kullanılmaz (ADR-0001 §2.1), parolası uygulamada yok.
- `tenants` ve `memberships` için `netkar_app` UPDATE'i tamamen kapalı olduğundan ileride "mağaza adını değiştir" gibi bir özellik gelirse `UPDATE (name)` sütun yetkisi ve test eklenmelidir.
- ADR-0001 §2.3'teki "`netkar_auth` tablo yetkileri en azdır (örn. `sessions` için yalnız `SELECT, UPDATE`)" cümlesi eskidi (artık `UPDATE (revoked_at)` ve sütun düzeyi INSERT); ADR metnine dokunulmadı.
- **Gelecekteki SECURITY DEFINER işlev ve rol yükseltme kontrolü:** `memberships_immutable_guard` rol yükseltme izni için `current_user` bakar. `netkar_owner` sahipli ve `memberships` güncelleyen bir SECURITY DEFINER işlev, tetikleyicide `current_user = netkar_owner` göründüğünden bu kontrolü atlar. Böyle bir işlev eklenirse sahibi `netkar_auth` olmalı ve kendi rol kuralları (kendi rolünü yükseltememe, son owner) işlevin içinde uygulanmalıdır.

## Sürüm notu

Migrasyon ve uygulama birlikte dağıtılır. 0024 uygulandıktan sonra eski uygulama sürümü doğrudan `sessions` INSERT'i yapamaz (giriş 500 verir); yeni uygulama sürümü ise 0024 öncesi veritabanında `auth_gate.create_session` bulamaz. Bu yüzden dağıtım kısa bir kesintiyle (migrasyon, hemen ardından yeni uygulama) yapılır; geri alırken önce uygulama, sonra migrasyon geri alınır.

- **Bozuk bağlam değeri:** `app.tenant_id` ya da `app.user_id` UUID olmayan dolu bir değer taşırsa `create_session` 42501 yerine 22P02 ile düşer; oturum açılmaz (RLS politikalarıyla aynı davranış). Uygulama bağlamı her zaman `str(UUID)` ile kurar.
