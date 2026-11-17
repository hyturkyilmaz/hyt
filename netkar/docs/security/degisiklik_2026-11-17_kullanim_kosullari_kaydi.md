# Değişiklik notu: kullanım koşulları ve aydınlatma metni sürüm kaydı, yeniden doğrulama günlük sınırı (S1-S2 güvenlik ve hesap, dilim 3)

- Tarih: 17 Kasım 2026. Kapsam: Trello P1 "S1-S2 güvenlik ve hesap" kartı madde 4 ve önceki dilim bilgi notu (R). Durum: commit edilmedi; koordinatör incelemesi bekliyor.
- Dayanak: `docs/research/03_hukuk_ve_uyum.md` §5 (TBK m.20-21: "onaylanan sürüm ve tarih DB'de saklanır"), §2.6 (aydınlatma ile açık rıza aynı metinde birleştirilmez), TBK m.24 (tek taraflı değişiklik için yeniden onay). OWASP ASVS L2 V2.2 ve V2.5.
- **Hukuki METİN yazılmadı.** Yalnız sürüm kaydı altyapısı. Web sayfaları (`/kullanim-kosullari`, `/kvkk-aydinlatma-metni`) taslak iskeletidir ve değişmedi.

## Ne eklendi

- **Migrasyon 0021** (geri alınabilir): `legal_documents` (tür {terms, privacy_notice}, sürüm kodu, yayın zamanı, içerik SHA-256 özeti; UNIQUE tür+sürüm) ve `user_legal_acceptances` (yalnız kullanıcı, belge satırı, kabul zamanı; UNIQUE kullanıcı+belge). IP, IP özeti, kullanıcı aracısı SAKLANMAZ (KVKK veri en aza indirme). İkisi de ENABLE + FORCE RLS. Satırlar DEĞİŞMEZ: UPDATE/DELETE tetikleyicisi (23514, superuser dahil) ve `netkar_app` için yalnız SELECT (+ kabul tablosunda INSERT). Belge tablosu herkese okunur, yazma politikası yalnız `netkar_owner`; kabul tablosu `user_id = app.user_id`; worker erişemez. Yer tutucu sürüm `taslak-2026-11` her iki tür için eklenir; özeti belge metninin DEĞİL `netkar-legal-placeholder:<tür>:<sürüm>` dizgisinin SHA-256'sıdır.
- **Yayın aracı:** `python -m app.tools.legal_documents publish --type terms|privacy_notice --version V --file belge.md` (`DATABASE_ADMIN_URL`; dosyanın SHA-256'sı yeni satır olur, metin yazılmaz). "Güncel sürüm" = türün `published_at <= now()` olan en yeni satırı.
- **Kayıt:** `POST /v1/auth/register` gövdesine `accept_terms` ve `acknowledge_privacy_notice` eklendi; yalnız JSON `true` kabul edilir (eksik, `false`, `1`, `"true"` 422; hesap oluşmaz). Kayıt anındaki güncel sürümler hesapla AYNI işlemde kabul tablosuna yazılır. 202 yanıtı ve numaralandırma davranışı aynı: var olan e-postada kabul kaydı eklenmez, onay eksikse yine aynı 422. Pazarlama izni eklenmedi (ayrı ve varsayılan kapalı olacak; şimdilik yok).
- **Yeniden kabul:** `GET /v1/me` içine `legal: {pending[], enforced}`; `POST /v1/legal/accept` (oturumlu, CSRF'li; gövde `documents:[{doc_type, version}]`; yalnız GÜNCEL sürüm kabul edilir, değilse 409 `legal-version-stale`; idempotent; tek geçersiz kalem tüm isteği düşürür; denetim kaydı `legal.accepted`, IP özeti yazılmaz).
- **(R) Yeniden doğrulama günlük sınırı:** `_reauthenticate` mevcut `reauth:user` (15 dk) sınırına EK olarak `reauth:day` (varsayılan 30 / 24 saat, `rate_limit_reauth_daily_user`) uygular; aşımda 429. Giriş kilidinden (`totp_failed_count`) bağımsızdır, başarılı ve başarısız her deneme sayılır, tüm yeniden doğrulama uçları (setup, enable, disable, recovery-codes) ortak sayaç kullanır. Fail-closed: sayaç yazılamazsa (havuz dolu) 503 ve parola doğrulanmaz. Sınır: sabit pencere (UTC günü); gün sınırında kısa sürede en çok iki pencere kullanılabilir (kayan pencere değil).
- **Web:** kayıt formunda iki ayrı, zorunlu, `aria-required` onay kutusu (koşullar: "okudum, kabul ediyorum"; aydınlatma: yalnız "okudum" ve "açık rıza yerine geçmez" açıklaması); bağlantılar yeni sekmede açılır ve bu GÖRÜNÜR metinle söylenir (form verisi kaybolmasın). Panelde `LegalReacceptanceBanner`: bekleyen belge/sürüm, sürümle kabul, 409'da sıfırlama.

## Karar: yeniden kabul kapısı (403) mı, yalnız panel uyarısı mı

Seçenekler: (a) kabule kadar yazma uçları 403 `terms-acceptance-required`; (b) yalnız panel uyarısı.
Seçilen: **ikisi de kodlandı, kapı bir ayarla yönetilir ve VARSAYILAN KAPALI** (`legal_reacceptance_enforced=false`): varsayılanda (b) çalışır, açılırsa (a).

Gerekçe:
- Şu anki sürüm yer tutucudur (avukat onaysız metin). Açılışta 0021 öncesi tüm kullanıcılar "kabulsüz" görünür; kapı varsayılan açık olsaydı onaylanmamış taslak metin yüzünden herkesin yazması kilitlenirdi. Bu, hukuken de savunması zor (kullanıcı henüz var olmayan koşulu kabul etmeye zorlanır) ve ürün için riskli.
- (b) tek başına, yeni sürümün bağlayıcılığı için ispat üretmez (TBK m.24: tek taraflı değişiklik yazılmamış sayılabilir); panel uyarısını görmezden gelen kullanıcıda kabul kaydı oluşmaz. Bu yüzden gerçek sürüm yayınlanınca (a) açılabilmelidir.
- (a) açıkken kapsam bilerek dar: yalnız tenant verisi YAZAN uçlar (`require_role(..., verified=True)`: mağaza bağlama/iptal, maliyet, kâr ayarı). Okuma, dışa aktarma, `/me`, çıkış, hesap güvenliği (TOTP/kurtarma) ve kabul ucu açık kalır: veri erişimi (KVKK m.11) ve güvenlik işlemleri rehin tutulmaz. Sıra: rol, e-posta doğrulaması, kabul.
- Kapıyı açmak koda dokunmadan ortam değişkeniyle (`LEGAL_REACCEPTANCE_ENFORCED=true`) yapılır.

## Kanıt (testler)

`tests/test_legal_acceptance.py` (41 test): yer tutucu satırları ve özetleri, kabul tablosunda yalnız `id,user_id,document_id,accepted_at` sütunları, 8 onay varyantında 422 ve hesap oluşmaması, kayıtta en yeni sürümün yazılması, ileri tarihli sürümün güncel sayılmaması, var olan e-posta için aynı 202, UPDATE/DELETE'in her rolde reddi, FORCE RLS ve yetkiler, kullanıcı yalıtımı ve başkası adına INSERT reddi, `/me` bekleyen listesi, kabul (idempotent, denetimli, IP'siz), 409 bayat sürüm, CSRF ve oturum zorunluluğu, kapı varsayılan kapalı, kapı açıkken 12 tenant yazma ucunun tamamı 403 (parametrik), okuma/TOTP/çıkış açık ve kabulden sonra kapı açılır, eski kullanıcı, "doğrulanmamış" hatasının önceliği, yayın aracı, 0021 geri alma (kanıt varken downgrade DURUR, `NETKAR_ALLOW_LEGAL_DATA_LOSS=1` ile geri alınır). `tests/test_mfa_recovery.py`: 3 yeni test (günlük sınır 15 dk penceresinden ve giriş kilidinden bağımsız, başarılı denemeler de sayılır, sayaç yoksa 503 fail-closed). Web: `legal-reacceptance-banner.test.tsx` (6), kayıt formu ve şema testleri.

## Hasan / avukat kararı (karar_kaydi.md'ye YAZILMADI)

1. **Yeniden kabul kapısı:** `legal_reacceptance_enforced` ne zaman açılacak? Açıkken yazma kilidi ve okuma/dışa aktarma açık kalması hukuken yeterli mi; kabul etmeyen kullanıcıya cezasız iptal (TBK m.24 önerisi) nasıl sunulacak, hesap sahibi olmayan üyeler (admin/üye rolleri) için kabul kimin adına geçerli?
2. **Saklama süresi:** kabul kayıtları ve belge özetleri ne kadar saklanır? Hesap kapanınca da (ispat, zamanaşımı) tutulacak mı? Şu an silme yok ve kayıtlar değişmez; "silme talebi" (KVKK m.7/11) ile ispat verisi çelişkisi için avukat görüşü gerekir. Kabul tablosu kişisel veri (kullanıcı kimliği + zaman) içerir; aydınlatmada saklama süresi yazılmalı.
3. **Aydınlatma onay kutusu:** zorunlu "okudum" kutusu doğru yöntem mi, yoksa aydınlatma yalnız bağlantı olarak mı kalmalı (Tebliğ yalnız bilgilendirme ister, kabul istemez)? Kutu şimdi kayıt için zorunlu; arayüz metni ("açık rıza yerine geçmez") avukat onayına bağlı.
4. **Kayıtta kabul edilen sürüm:** (tur 1'de kapandı) istemci gördüğü sürümü gönderir, güncel değilse 409. Kalan koşul: web sayfasındaki METİN ile `legal_documents` satırının birlikte yayınlanması (önce sayfa canlıya, sonra `publish`).
5. **İçerik özeti:** gerçek sürümlerde hangi biçim özetlenecek (Markdown kaynağı mı, render edilen HTML mi)? Araç dosyanın ham baytını özetler.
6. **Yer tutucu sürüm:** `taslak-2026-11` ile kabul edilen kayıtlar gerçek koşulları kapsamaz; gerçek metin yayınlanınca tüm mevcut kullanıcılar yeniden kabul etmelidir (kapı bu yüzden açılmalı).
7. **Pazarlama izni:** ticari elektronik ileti onayı ayrı, varsayılan kapalı ve ayrı kayıtla (İYS yükümlülüğü dahil) tasarlanacak; bu dilimde yok.

## Dürüst durum ve açık kalanlar

- Downgrade kabul kaydı varken durur (ispat verisi); bkz. tur 1 (bayrak artık tam sayılarla eşleşmeli, prod'da reddedilir); önce `pg_dump -t user_legal_acceptances -t legal_documents` ile yedekle. Tablolar TRUNCATE'e karşı tetikleyiciyle korunmaz (yalnız superuser/sahip yapabilir; kullanıcı silme yok, `TRUNCATE users CASCADE` yalnız test içindir).
- Demo tohumu (`seed_demo`) kullanıcıları güncel sürümleri "kabul etmiş" işaretler (e-posta doğrulamasıyla aynı gerekçe: üretim dışı, korumalı betik); gerçek kabul değildir.
- 0021 öncesi mevcut kullanıcıların kabul kaydı yoktur (geriye dönük kabul sayılmadı); kapı kapalıyken yalnız panel bandı görürler.
- Rol bazlı kabul (üye/admin kullanıcıların her biri kendi adına kabul eder; kiracı sahibi adına toplu kabul yok): TBK m.20-21 açısından avukata sorulacak.
- Web e2e (Playwright) çalıştırılmadı: `e2e/real-api/auth-flow.spec.ts` iki kutuya güncellendi ama bu ortamda koşulmadı; yeniden kabul bandı için e2e yazılmadı (vitest var).
- Günlük yeniden doğrulama sayacı sabit pencerelidir (kayan değil); yönetim arayüzünde sayaç sıfırlama aracı yok.


## Bağımsız inceleme, düzeltme turu 1 (0022; 0021'e dokunulmadı)

| # | Bulgu | Çözüm | Kanıt |
|---|---|---|---|
| 1 (orta) | Kayıtta sürüm yarışı | Herkese açık `GET /v1/legal/current` (tür, sürüm, yayın zamanı). Register gövdesi `terms_version` ve `privacy_notice_version` ister; güncel değilse 409 `legal-version-stale`, hesap var olsun olmasın aynı yanıt (numaralandırma korunur, hesap/kabul oluşmaz). Web formu sürümü sunucudan alır, gösterir, gönderir; 409'da kutuları sıfırlar ve sürümü yeniler; sürüm alınamazsa istek gitmez. | `test_register_with_stale_or_missing_version...`, `test_legal_current_is_public...`, `auth-forms.test.tsx` (+2) |
| 2 (orta) | `accepted_at`/`id` istemciden verilebiliyordu | `netkar_app` INSERT yalnız `(user_id, document_id)` sütunlarına; BEFORE INSERT tetikleyicisi `id` ve `accepted_at`'i sunucu üretir (superuser dahil geçersiz kılar). | `test_app_role_cannot_supply_id_or_accepted_at...`, `test_privileges_and_force_rls`, `test_migration_0022_is_reversible...` |
| 3 (orta) | Kapı açıkken veri işlemeyi durdurma hakkı rehin | `POST .../revoke` ayrı bağımlılıkla (`require_role(..., legal_gate=False)`) kapıdan muaf; e-posta doğrulaması yine şart. Başka "durdurma/silme talebi" ucu YOK (hesap silme ucu henüz yok; eklenirse `legal_gate=False` kullanmalı). | `test_enforced_gate_keeps_marketplace_revoke_open`, `test_unverified_user_still_cannot_revoke...` |
| 4 (düşük) | TRUNCATE ile kanıt silinebilirdi | İki tabloya BEFORE TRUNCATE FOR EACH STATEMENT tetikleyicisi (CASCADE dahil). Test/bakım için yalnız superuser'ın `session_replication_role = replica` ayarı atlar; test temizliği buna uyarlandı. | `test_records_are_immutable_for_every_role` |
| 5 (düşük) | Gerçek sürüm + kapalı kapı sessizdi | Açılışta (`lifespan`) taslak olmayan güncel sürüm varsa ve bayrak kapalıysa uyarı günlüğü (açılışı engellemez); yayın aracı gerçek sürümde hatırlatma basar. | `test_startup_warns_when_real_version...`, araç testi |
| 6 (düşük) | Downgrade bayrağı "1" | 0022 downgrade'i (0021'den önce çalışır): `ENVIRONMENT=prod` iken HER durumda reddeder; kayıt varsa `NETKAR_ALLOW_LEGAL_DATA_LOSS=accepted=N,published=M` tam eşleşmeli (ileti beklenen değeri söyler; "1" artık yetmez). 0021 değişmediği için doğrulama sonrası ortam değişkeni yalnız o alembic sürecinde "1"e çekilir. Not: koruma 0022'den 0021'e tek adımlık geri almada da çalışır (kayıp olmasa da). | `test_migration_downgrade_protects_evidence_with_exact_counts_and_refuses_prod`, `..._without_evidence_needs_no_flag_but_prod_always_refuses` |
| 7 (düşük) | Yayın aracı | `--published-at` (ISO 8601; geçmiş reddedilir, ileri tarih güncel sayılmaz), `--dry-run` (doğrular, ekler, özeti yazar), onay adımı (`<tür> <sürüm>` yazılmadan eklemez; otomasyon için `--yes`). | `test_publish_tool_dry_run_confirmation_and_published_at` |
| Bilgi | Denetim hedefi | `legal.accepted` hedefi yalnız bu istekte YENİ eklenen satırları listeler. | `test_accept_audit_target_lists_only_newly_inserted_rows` |

Dürüst notlar: ileri tarihli yayın ve `--yes` yalnız bakım penceresinde kullanılmalıdır; `session_replication_role` atlaması yalnız superuser'a açıktır (uygulama rolü yapamaz). Saklama süresi ve KVKK m.7/m.11 silme talebi ile ispat verisi çelişkisi Hasan/avukat kararı olarak yukarıda (madde 2) açıktır.
