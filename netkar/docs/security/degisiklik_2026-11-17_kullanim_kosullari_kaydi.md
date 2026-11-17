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
4. **Kayıtta kabul edilen sürüm:** istemci sürüm göndermez, sunucu kayıt anındaki güncel sürümü yazar. Kullanıcının GÖRDÜĞÜ metin ile kaydedilen sürümün aynı olması, web sayfası ve `legal_documents` satırının birlikte yayınlanmasına bağlıdır (araç yayın sırası: önce sayfa canlıya, sonra `publish`). Kayıt formunun gerçek sürüm kodunu göstermesi ve istemcinin sürümü göndermesi istenirse ayrı iş.
5. **İçerik özeti:** gerçek sürümlerde hangi biçim özetlenecek (Markdown kaynağı mı, render edilen HTML mi)? Araç dosyanın ham baytını özetler.
6. **Yer tutucu sürüm:** `taslak-2026-11` ile kabul edilen kayıtlar gerçek koşulları kapsamaz; gerçek metin yayınlanınca tüm mevcut kullanıcılar yeniden kabul etmelidir (kapı bu yüzden açılmalı).
7. **Pazarlama izni:** ticari elektronik ileti onayı ayrı, varsayılan kapalı ve ayrı kayıtla (İYS yükümlülüğü dahil) tasarlanacak; bu dilimde yok.

## Dürüst durum ve açık kalanlar

- Downgrade kabul kaydı varken durur (ispat verisi); veri kaybı bilinçli onayla (`NETKAR_ALLOW_LEGAL_DATA_LOSS=1`) ve önce `pg_dump -t user_legal_acceptances -t legal_documents` ile yedekle. Tablolar TRUNCATE'e karşı tetikleyiciyle korunmaz (yalnız superuser/sahip yapabilir; kullanıcı silme yok, `TRUNCATE users CASCADE` yalnız test içindir).
- Demo tohumu (`seed_demo`) kullanıcıları güncel sürümleri "kabul etmiş" işaretler (e-posta doğrulamasıyla aynı gerekçe: üretim dışı, korumalı betik); gerçek kabul değildir.
- 0021 öncesi mevcut kullanıcıların kabul kaydı yoktur (geriye dönük kabul sayılmadı); kapı kapalıyken yalnız panel bandı görürler.
- Rol bazlı kabul (üye/admin kullanıcıların her biri kendi adına kabul eder; kiracı sahibi adına toplu kabul yok): TBK m.20-21 açısından avukata sorulacak.
- Web e2e (Playwright) çalıştırılmadı: `e2e/real-api/auth-flow.spec.ts` iki kutuya güncellendi ama bu ortamda koşulmadı; yeniden kabul bandı için e2e yazılmadı (vitest var).
- Günlük yeniden doğrulama sayacı sabit pencerelidir (kayan değil); yönetim arayüzünde sayaç sıfırlama aracı yok.
