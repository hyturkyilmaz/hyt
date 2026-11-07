# ADR-0001: RLS, kimlik doğrulama öncesi yol ve rate limit tasarımı

- Durum: Kabul edildi (S1)
- Tarih: 6 Kasım 2026
- İlgili: `docs/10_mimari.md` §5-6, `docs/50_guvenlik.md` G01-G04, G07

## 1. Bağlam

Kiracı izolasyonu uygulama katmanındaki `WHERE tenant_id = ...` süzgecine bırakılamaz; tek bir unutulmuş sorgu IDOR üretir. Bu yüzden PostgreSQL satır düzeyi güvenlik (RLS) ikinci kilit olarak devrede olmalı. Ancak kimlik doğrulama sırasında kiracı henüz bilinmez:

1. Girişte kullanıcı e-postayla aranır (`users` tablosu kiracıya bağlı değildir; bir kullanıcı ileride birden çok kiracıya üye olabilir).
2. Oturum çerezi geldiğinde token özetinden oturum bulunur; kiracı bu kaydın içindedir.
3. Kayıtta kiracı, kullanıcı ve üyelik birlikte oluşur.
4. Parola sıfırlama token'ı kiracısız bir kullanıcı eylemidir.

Bu adımlar için RLS'yi aşan bir yol gerekir. Yol açık, dar ve denetlenebilir olmalı; uygulama rolüne genel bir "RLS'yi atla" yetkisi verilemez.

## 2. Karar

### 2.1 Üç rol

| Rol | Giriş | Amaç | Not |
|---|---|---|---|
| `netkar_owner` | evet | Migrasyon, tablo sahibi | Superuser değil. Çalışma zamanında kullanılmaz. |
| `netkar_app` | evet | API ve worker | Superuser ve `BYPASSRLS` değil. Yalnız gerekli tablo ve sütunlara yetki. |
| `netkar_auth` | hayır | `auth_gate` işlevlerinin sahibi | Kimse bu rolle bağlanamaz. |

Roller migrasyon öncesi kurulur (`infra/postgres/init/01-roles.sh`, testlerde `app.db.provision`). `netkar_owner`, `netkar_auth`'a `INHERIT FALSE, SET TRUE` ile bağlıdır: migrasyonda `SET LOCAL ROLE netkar_auth` yapabilir, ama politikaları devralmaz. (İlk denemede varsayılan `INHERIT` ile owner de `netkar_auth` politikasından yararlanıyor ve `FORCE ROW LEVEL SECURITY` owner için boşa düşüyordu; `test_forced_rls_applies_even_to_table_owner` bunu yakaladı.)

### 2.2 Kiracı politikaları

Kiracı verisi taşıyan tablolarda (`memberships`, `sessions`, `audit_log`; `tenants` için `id` ile) `ENABLE` + `FORCE ROW LEVEL SECURITY` ve şu politika vardır:

```sql
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
```

`NULLIF(..., '')` bilinçlidir: `SET LOCAL` ile ayarlanmış bir GUC, işlem bittikten sonra aynı bağlantıda `NULL` değil boş dize döndürür; çıplak `''::uuid` dönüşümü hata verirdi. Bağlam yoksa ya da boşsa hiçbir satır görünmez (güvenli varsayılan).

`users` tablosunda politika kiracıya değil kullanıcıya bağlıdır: `id = app.user_id`. Böylece bir kiracının oturumu başka kullanıcıların satırlarını (e-posta, TOTP sırrı) görmez. `password_hash` sütununa uygulama rolünün `SELECT` yetkisi yoktur; yalnız `auth_gate` işlevleri okur.

Bağlam, istek başında `set_config('app.tenant_id', ..., true)` ile (işlem yerel; `SET LOCAL` eşdeğeri, parametre bağlamayı destekler) yazılır. Değer istemciden değil, sunucunun doğruladığı oturum kaydından gelir. İşlem biterken sıfırlandığı için havuzdaki bağlantı yeniden kullanıldığında sızıntı olmaz.

Gelecekteki her `tenant_id` sütunlu tablo aynı kalıbı taşımak zorundadır; `test_every_tenant_table_has_forced_rls` bunu otomatik doğrular (yeni tablo RLS'siz eklenirse test kırılır).

### 2.3 Kimlik doğrulama öncesi yol: `auth_gate` işlevleri

RLS dışı yol, `auth_gate` şemasındaki beş `SECURITY DEFINER` işlevidir. Sahipleri `netkar_auth`'tur, `search_path` sabittir (`pg_catalog, public`), `PUBLIC`'ten `EXECUTE` alınmış, yalnız `netkar_app`'e verilmiştir.

| İşlev | Ne yapar | Neden RLS dışı |
|---|---|---|
| `find_user_for_login(email)` | E-postayla kullanıcı, parola özeti, TOTP durumu ve ilk üyelik kiracısı | Kiracı henüz bilinmiyor |
| `get_session(token_hash)` | Token özetinden oturum ve rol | Kiracı oturum kaydının içinde |
| `register_account(...)` | Kullanıcı + kiracı + owner üyeliği (e-posta varsa hiçbir şey yapmaz) | `users`/`tenants` için uygulama rolünde INSERT yok |
| `create_password_reset(...)` | Kullanıcı varsa token özeti yazar, eski bekleyen token'ları kapatır | Kiracısız eylem |
| `consume_password_reset(...)` | Token'ı atomik tüketir, parolayı değiştirir, kullanıcının tüm oturumlarını iptal eder | Oturumlar birden çok kiracıda olabilir |

`FORCE ROW LEVEL SECURITY` açık olduğundan `netkar_auth` için de RLS geçerlidir; bu rol için tablolarda açıkça adlandırılmış `auth_path` politikaları (`TO netkar_auth USING (true)`) vardır. Yani aşma `BYPASSRLS` gibi örtük ve geniş değil, tablo ve komut düzeyinde yazılı ve `pg_policy` ile denetlenebilirdir. `netkar_auth`'un tablo yetkileri de en azdır (örn. `sessions` için yalnız `SELECT, UPDATE`).

Her işlev tek amaçlıdır ve dönüş kümesi dardır: genel "kullanıcıları listele" yolu yoktur. Bir SQL enjeksiyonu uygulama rolüyle bile olsa saldırgan, geçerli bir token özeti ya da e-posta bilmeden hiçbir şey okuyamaz.

### 2.4 Reddedilen alternatifler

- **Uygulama rolüne `BYPASSRLS`:** Her sorgu RLS'yi aşabilir hale gelir; çift kilit anlamını yitirir.
- **Giriş için ayrı bir "yönetici" bağlantısı (superuser/owner):** Süreçte yüksek yetkili kimlik bilgisi tutmak gerekir; sızarsa tüm veri açılır.
- **`users` tablosuna `tenant_id` koymak:** Bir kullanıcının birden çok kiracıya üyeliği modeli ve e-posta benzersizliği bozulur.
- **Yalnız uygulama katmanı süzgeci:** G01'in "çift kilit" gereksinimini karşılamaz.

## 3. Oturum ve CSRF notları

- Oturum token'ı 256 bit rastgeledir (`secrets.token_urlsafe(32)`); DB'de yalnız SHA-256 özeti tutulur. Token yüksek entropili olduğu için yavaş özet gerekmez.
- Çerez: `__Host-` önekli, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, `Domain` yok. Boşta 12 saat (`last_seen_at`, istek başına en fazla dakikada bir güncellenir), mutlak 30 gün, çıkışta ve parola sıfırlamada iptal.
- CSRF: çift gönderim. `__Host-nk_csrf` çerezi (JS okuyabilsin diye `HttpOnly` değil) ile `X-CSRF-Token` başlığı eşleşmeli. `__Host-` öneki alt alan çerez enjeksiyonunu engeller. Oturum başında token yenilenir. İstemci, ilk durum değiştiren istekten önce `GET /v1/auth/csrf` çağırır.
- TOTP girişi: parola doğruysa kısa ömürlü (5 dk) HMAC imzalı `__Host-nk_pending` çerezi verilir; tam oturum yalnız doğru TOTP koduyla açılır.

## 4. Rate limit tasarımı

Seçenekler: (a) süreç içi sabit pencere, (b) PostgreSQL tablosu, (c) Redis. Redis mimari ilkesi gereği yok. Süreç içi sayaç, API'nin birden çok kopyası ve yeniden başlatmalar altında sınırı çarpar/sıfırlar. Bu yüzden MVP için (b) seçildi: `rate_limits(key, window_start, count)` tablosu, tek atomik `INSERT ... ON CONFLICT DO UPDATE ... RETURNING count`.

- Sabit pencere (giriş ve TOTP 15 dk, kayıt ve sıfırlama 1 saat). Pencere sınırında en fazla 2x ani artış kabul edilen bir ödünleşimdir; kaba kuvvet için yeterlidir.
- Anahtarlar: `login:ip:<hmac>`, `login:email:<hmac>`, `register:ip`, `reset:ip`, `reset:email`, `reset-confirm:ip`, `totp:user`. Anahtarlar HMAC özetidir; tabloda ham IP veya e-posta bulunmaz.
- Sayaç kendi bağlantısında ve autocommit ile yazılır; isteğin işlemi geri alınsa bile deneme sayılır.
- Eşikler ayarlanabilirdir (`RATE_LIMIT_*`). Aşımda 429 + `Retry-After` (RFC 9457 gövdesiyle).
- Eski pencereler `netkar.prune_rate_limits` periyodik görevi ile 24 saat sonra silinir (operasyonel sayaç, kullanıcı verisi değil).
- İstemci IP'si: güvenilir vekil yapılandırması yoksa bağlantının eş adresi; vardır ise `X-Forwarded-For` sağdan sola güvenilir vekiller atlanarak okunur. (İlk sürümün `TRUST_PROXY_HEADERS` varsayımı BFF topolojisinde yanlış çıktı; bkz. ADR-0002, denetim Y-01.) IP sınırları gövde ayrıştırılmadan önce ASGI ara katmanında uygulanır.
- Her istek bir yazma demektir; MVP ölçeğinde (yüzlerce satıcı) kabul edilebilir. Ölçek tetiği: giriş uç noktalarında DB yazma gecikmesi veya Cloudflare/WAF önünde hız sınırlama devreye alınır (mimari §2 Cloudflare).

## 5. Hesap varlığını sızdırmama

- Kayıt ve sıfırlama isteği her durumda aynı 202 gövdesini döndürür. Mevcut e-postaya "zaten kayıtlı" bildirimi, yeni hesaba "hesap oluşturuldu" iletisi gider. E-posta gönderimi `BackgroundTasks` ile yanıttan sonra yapılır (zamanlama farkı olmasın).
- Kayıtta parola özeti, e-posta var olsa da hesaplanır (zamanlama eşitleme). Girişte kullanıcı yoksa sahte özetle doğrulama yapılır.
- Başarısız giriş yanıtı kullanıcı yokken ve parola yanlışken birebir aynıdır.

## 6. Sonuçlar ve açık riskler

- Yeni kiracı tablosu eklerken migrasyon, RLS + politika + yetki üçlüsünü içermek zorundadır; koruyucu test vardır.
- `auth_gate` işlevleri güvenlik açısından kritik koddur; değişiklikleri güvenlik denetçisi incelemelidir.
- E-posta doğrulaması S1'de yoktur (`email_verified_at` boş kalır). Başkasının e-postasıyla önceden hesap açma (pre-hijack) riski vardır; doğrulama akışı S2 işi olarak önerilir.
- TOTP kod tekrar kullanımı: `users.totp_last_step` (migrasyon 0003) son başarılı zaman adımını saklar; aynı veya eski adım atomik `UPDATE ... WHERE totp_last_step < :step` ile reddedilir. Kaba kuvvet: ardışık 5 hatada hesap 15 dk TOTP girişine kapanır (`totp_failed_count`, `totp_locked_until`), her başarısızlık/kilit `audit_log`'a yazılır (denetim O-01, O-02).
- RLS (GUC bağlamı) SQL enjeksiyonuna karşı değil, uygulama mantığı hatalarına (unutulmuş `WHERE`) karşı ikinci kilittir; SQLi altında bağlam taklit edilebilir (denetim B-01). SQLi bulunmadı; tüm sorgular parametrelidir.
- Parola özeti parametreleri kütüphane varsayılanıdır; üretimde barındırma donanımına göre ayarlanıp yük testiyle doğrulanmalıdır.
- Kullanıcı birden çok kiracıya üye olursa giriş en eski üyeliği seçer; kiracı değiştirme (yeni oturum) ayrı bir özelliktir.
