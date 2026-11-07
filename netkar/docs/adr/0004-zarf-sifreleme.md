# ADR-0004: Pazaryeri anahtarları için zarf şifreleme (DEK/KEK), anahtar kimliği ve döndürme

- Durum: Kabul edildi (S2 denetim düzeltme turu, O-01 ve D-04)
- Tarih: 7 Kasım 2026
- İlgili: `docs/50_guvenlik.md` G05, `docs/10_mimari.md` §3.1, `docs/adr/0003-trendyol-istemcisi.md` §7, `docs/security/denetim_2026-11-07_S2.md` (O-01, D-04, D-05, B-01), `services/api/app/core/envelope.py`, `services/api/app/tools/`

## 1. Bağlam

ADR-0003'ün ilk turu satıcı API anahtarını ve sırrını `DATA_ENCRYPTION_KEY`'den HKDF ile türetilen tek bir alt anahtarla doğrudan AES-256-GCM ile saklıyordu ve zarf şifrelemeyi "faz 2" diye erteliyordu. S2 denetimi bunu O-01 olarak işaretledi: G05 (merge engeli) "AES-256-GCM zarf şifreleme; KEK ortam değişkeninde" ister ve `docs/10_mimari.md` §3.1 yalnız KMS'i faz 2'ye bırakır. Eksikler: şifreli değerde anahtar kimliği yok, iki anahtarla çözme yok, yeniden şifreleme aracı yok, kayıt başına veri anahtarı yok; ayrıca AAD kiracıyı ve satıcıyı bağlamıyordu (D-04).

## 2. Karar

**Zarf şifreleme.** Her şifrelemede (her kayıt, her alan) rastgele 256 bit veri anahtarı (DEK) üretilir; değer DEK ile AES-256-GCM şifrelenir; DEK, etkin anahtar şifreleme anahtarı (KEK) ile AES-256-GCM sarılır. KEK'ler ortam değişkenindedir (G05); KMS faz 2'dedir.

**Biçim (sürümlü, kid'li):**

```
v2:<kid>:<sarılı_dek_b64>:<veri_b64>

kid            = [A-Za-z0-9_-]{1,32}   (KEK kimliği; ':' içermez)
sarılı_dek_b64 = base64( nonce12 || AES-256-GCM(KEK[kid], DEK, AAD = "netkar:dek-wrap:v2:<kid>") )
veri_b64       = base64( nonce12 || AES-256-GCM(DEK, düz metin, AAD = bağlam) )
```

Nonce'lar `os.urandom(12)`. Uygulama: `app/core/envelope.py` (`KeyRing`, `EnvelopeCipher`).

**AAD (D-04 dahil).** `marketplace_accounts:v2:{tenant_id}:{platform}:{seller_id}:{account_id}:{field}` (`field`: `api_key` | `api_secret`). Şifreli değer başka kiracıya, platforma, satıcıya, satıra veya alana taşınırsa çözülemez. Eski v1 AAD (`marketplace_accounts:{id}:{field}`) yalnız geçiş ve okuma için tutulur (`legacy_aad`).

**KEK halkası.** `DATA_KEKS` = virgülle ayrılmış `kid:base64(32 bayt)` listesi; `DATA_KEK_ACTIVE` = yeni şifrelemede kullanılan kid. Çözmede kid ile anahtar seçilir; halkada olmayan kid `DecryptionError`. Bu KEK'ler `DATA_ENCRYPTION_KEY`'den bağımsızdır: TOTP sırları, IP/e-posta HMAC özetleri ve rate limit anahtarları ayrı köktedir, birini döndürmek diğerini etkilemez. `prod`'da `DATA_KEKS` ve `DATA_KEK_ACTIVE` zorunludur (açılış hatası); diğer ortamlarda verilmezse `DATA_ENCRYPTION_KEY`'den HKDF ile türetilen `dev-derived` geliştirme KEK'i kullanılır (yalnız kolaylık).

**Döndürme (`python -m app.tools.rewrap_keys`).** Etkin olmayan kid ile sarılı DEK'leri etkin KEK'e taşır. Yalnız sarılı DEK yeniden sarılır; veri gövdesi aynı kalır ve düz metin tool tarafında yalnız doğrulama için bellekte açılır. Varsayılan kuru çalıştırma (`--apply` ile yazar), idempotent (etkin kid'e dokunmaz), yazmadan önce eski ve yeni değerin aynı düz metni verdiğini doğrular, satır bazında karşılaştır-ve-yaz (eşzamanlı değişen satıra dokunmaz), her taşıma için `audit_log` kaydı (`marketplace_account.keys_rewrapped`, yalnız kid'ler), bozuk satırda devam eder ve çıkış kodu 2 verir.

**Biçim geçişi (`python -m app.tools.migrate_envelope`).** Eski `v1:` (FieldCipher) değerleri v2'ye çevirir; `--revert` v2'yi v1'e geri çevirir (düz metin değişmez, veri silinmez). Aynı güvenceler: kuru çalıştırma varsayılan, idempotent, doğrulama, CAS, denetim kaydı. Uygulama kodu geçiş süresince `decrypt_credentials(..., legacy=FieldCipher)` ile v1'i de okuyabilir; geçiş bitince bu yol kaldırılır.

**Araçların veritabanı erişimi.** İkisi de `DATABASE_ADMIN_URL` ile RLS'yi aşabilen bir rolle (superuser veya BYPASSRLS) çalışır; uygulama rolü kiracı bağlamı olmadan satır göremez. Rol RLS'yi aşamıyorsa araç "0 kayıt" demek yerine hata verip durur (çıkış kodu 3). Çıktıya şifreli değer, düz metin, anahtar veya parola yazılmaz.

**Yetki daraltma (D-05, migrasyon 0005).** `netkar_app` artık `marketplace_accounts` üzerinde yalnız şu sütunlarda UPDATE yapabilir: `api_key_encrypted`, `api_secret_encrypted`, `api_key_last4`, `status`, `last_validated_at`, `updated_at`, `revoked_at`. `tenant_id`, `platform`, `seller_id`, `created_by`, `created_at` değişmez. Geri alma tablo düzeyi UPDATE'i geri verir. `find_live_account` artık şifreli sütunları yüklemez (çözme yalnız gerektiğinde, senkron işçisinde).

## 3. Operasyon

**İlk kurulum.**
1. KEK üret: `echo "kek-202611:$(openssl rand -base64 32)"`. Çıktıyı `DATA_KEKS`'e, kid'i `DATA_KEK_ACTIVE`'e yazın. Halka yedeğini (kid + anahtar) veritabanı yedeğinden AYRI, güvenli bir yerde tutun; kaybedilirse pazaryeri anahtarları çözülemez (satıcılar yeniden bağlanır, veri kaybı yok).
2. Migrasyonları çalıştırın (`make migrate`, 0005 dahil).
3. Canlıda zaten v1 satır varsa: `python -m app.tools.migrate_envelope` (kuru), sonra `--apply`; ikinci çalıştırma "0 kayıt dönüştürüldü" demeli. Gerekli ortam: `DATABASE_ADMIN_URL`, `DATA_KEKS`, `DATA_KEK_ACTIVE`, `DATA_ENCRYPTION_KEY`.

**Anahtar döndürme (planlı, örn. 90 günde bir, veya olay sonrası hemen).**
1. Yeni KEK üretin (yeni kid). `DATA_KEKS`'e ekleyin (eskisi kalsın), `DATA_KEK_ACTIVE`'i yeni kid yapın; API ve işçileri yeniden başlatın. Yeni yazmalar artık yeni kid ile sarılır; eski kayıtlar eski kid ile çözülmeye devam eder (kesinti yok).
2. `python -m app.tools.rewrap_keys` (kuru) ile kapsamı görün, sonra `--apply`. Çıktıda "0 kayıt başarısız" olmalı.
3. Tekrar çalıştırın: "0 kayıt taşındı" beklenir (idempotent kanıtı).
4. Eski KEK'i halkadan çıkarmadan önce şunları göz önünde bulundurun: döndürmeden önce alınmış veritabanı yedekleri ESKİ kid ile sarılı DEK taşır; bu yedekleri geri yükleme ihtimali sürdüğü sürece eski KEK arşivde saklanmalıdır. Eski KEK'in imhası, o yedeklerdeki pazaryeri sırlarını kalıcı olarak okunamaz kılar (kasıtlı kriptografik silme).
5. KEK sızıntısı şüphesinde: yukarıdaki adımları hemen uygulayın ve ek olarak etkilenen satıcılardan Trendyol panelinde API anahtarını yenilemelerini isteyin (sızan KEK + yedek erişimi çözmeye yeter).

**Geri alma.** Kodu önceki sürüme almadan önce: `python -m app.tools.migrate_envelope --apply --revert` (v2 -> v1), sonra eski sürümü dağıtın; gerekirse `alembic downgrade 0004`. Veri kaybı yoktur.

## 4. Reddedilen alternatifler

- **Tek anahtarla doğrudan şifreleme (önceki hal):** döndürme, çift anahtarla çözme ve kid yok; kök sızıntısında müdahale kesintiyle ve tek seferlik betikle olur.
- **Tenant başına DEK:** iptalde ve döndürmede ayrıntı kaybı; kayıt (ve alan) başına DEK, kiracıya özel imha ve rewrap'i basit tutar. Maliyet ihmal edilebilir (iki küçük değer).
- **AES-KW (RFC 3394) ile sarma:** standart ama ek bağımlılık/API; AES-GCM ile sarma mevcut kütüphaneyle aynı ilkelleri kullanır ve AAD ile `kid`'e bağlar.
- **Şifreli değeri iptalde yeniden yazmak veya `VACUUM FULL`:** B-01'i kökten çözmez (WAL ve yedekler); KEK imhası daha tutarlı bir kontroldür.
- **KMS (AWS KMS, Cloud KMS, Vault):** faz 2. Biçim (`v2:<kid>:...`) buna hazırdır: KMS'e geçişte KEK kimlikleri KMS anahtar sürümlerine eşlenir, `rewrap` aracı KMS `Decrypt/Encrypt` çağırır.

## 5. Sonuçlar ve kalan riskler

- KEK hâlâ ortam değişkeninde: ortam dökümü + veritabanı yedeği birlikte sızarsa sırlar çözülür. Kazanım gizlilik değil, **döndürme, kid ile kesintisiz geçiş, kayıt başına anahtar ve KMS'e geçiş kolaylığıdır.**
- **B-01 (iptal sonrası ölü satır sürümü) tam kapanmadı.** İptalde iki sütun NULL olur; eski satır sürümü `VACUUM`'a kadar diskte, WAL'da ve yedeklerde sarılı DEK ile birlikte kalır. DEK aynı satırda saklandığı için "DEK silme" gerçek kriptografik silme sağlamaz; koruma, ilgili KEK'in döndürülüp eskisinin imhası (yukarıda) ve yedek saklama süresiyle sınırlıdır. Gerçek kriptografik silme DEK'in satır dışında (KMS) tutulmasını gerektirir (faz 2). Satıcı yine Trendyol panelinden anahtarı yenilemelidir.
- (Güncelleme, ADR-0005 §6) `netkar_app`'in şifreli sütunlarda SELECT yetkisi kaldırıldı: ayrı `netkar_worker` rolü şifreli sütunları okuyabilen tek roldür (migrasyon 0006). D-05 tamamen kapandı. Yukarıdaki ertelenen madde artık geçerli değildir.
- Python bellekte düz metni ve anahtar baytlarını sıfırlayamaz; pencere kısa tutulur (istemci kullanım başına kurulur).
- `rewrap_keys` ve `migrate_envelope` bakım pencerelerinde, yönetici DB kimlik bilgisiyle çalışır; bu kimlik bilgisi uygulama ortamında bulundurulmaz.
