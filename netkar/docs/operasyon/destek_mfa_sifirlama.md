# Prosedür: kullanıcı MFA'ya erişimini kaybetti (destek)

Kapsam: NetTablo kullanıcısı iki adımlı doğrulama (TOTP) uygulamasına erişemiyor. Dayanak: `docs/50_guvenlik.md` G02 ve G03, `docs/security/degisiklik_2026-11-17_eposta_dogrulama.md` (O-05, "Açık kalanlar": destek süreci belgesi).

Durum tarihi: 18 Kasım 2026. Dal: `claude/dazzling-clarke-pfvf32`. Kod referansları bu dalın çalışma ağacına göredir; testler bu belge için koşulmadı.

## 0. Özet (önce bunu oku)

1. Kurtarma kodu varsa kullanıcı kendi başına çözer (bölüm 2). Destek yalnız yönlendirir.
2. Kurtarma kodu yoksa destek kimlik doğrular, iki kişi onaylar, kayıt tutar (bölüm 3).
3. **EKSİK: ARAÇ YOK.** Kodda yönetici ya da destek için MFA sıfırlama ucu veya aracı bulunmadı (bölüm 4). Bu yüzden bölüm 3 sonunda onaylanan talep bugün teknik olarak uygulanamaz. Talep "bekletilir ve Hasan'a eskale edilir". Doğrudan veritabanı elle düzeltmesi varsayılan yol değildir.
4. Parola sıfırlama MFA sorununu çözmez. Doğrulanmış hesapta TOTP korunur ve girişte istenmeye devam eder (`services/api/app/api/v1/auth.py:790-806`, `docs/security/degisiklik_2026-11-17_eposta_dogrulama.md` D-06). Kullanıcıya "şifremi unuttum" önerme.

## 1. Rol ve ilkeler

- Destek hesabı kendi başına sıfırlayamaz. Hiçbir koşulda tek kişi karar vermez.
- Kullanıcıdan parola, TOTP kodu, kurtarma kodu, API anahtarı ya da sır asla istenmez. Kullanıcı yazarsa kullanma, kayda yazma, silinmesini iste.
- Destek kimlik belgesi (nüfus cüzdanı, ehliyet, pasaport) istemez, almaz, saklamaz.
- Şüphe varsa kullanıcıya erişim verme. Yanlış red geri alınır; yanlış onay geri alınmaz.
- Ürün güvenlik duruşu: saldırgan kurbanın ikinci faktörünü kaldırırsa tüm mağaza verisine ve (Trendyol anahtarı kayıtlıysa) mağaza bağlantısına erişir. Bu yüzden sıfırlama, hesap devri sayılır.

## 2. Önce kullanıcının kendi çözebildiği yollar

### 2.1 Durum tablosu

| Kullanıcı durumu | Yol | Gereken kod sayısı |
|---|---|---|
| Panelde oturumu AÇIK, uygulama yok, kurtarma kodu var | 2.3 | 1 |
| Oturum kapalı, parolayı biliyor, kurtarma kodu var | 2.2 sonra 2.3 | 2 |
| Oturum kapalı, parolayı bilmiyor, kurtarma kodu var | Önce parola sıfırlama (e-posta ile), sonra 2.2 ve 2.3 | 2 |
| Kurtarma kodu yok ya da bitti | Bölüm 3 | - |
| Yalnız 1 kod kaldı ve oturum kapalı | Kod girişte tükenir, kapatmaya kod kalmaz: bölüm 3 (bkz. 2.5) | - |

Gereken kod sayısı koddan çıkarımdır (girişte bir kod tüketilir: `api/v1/auth.py:384-396`; kapatma da bir kod tüketir: `api/v1/auth.py:663-708` ve `:496-554`). Gerçek ortamda uçtan uca doğrulanmadı.

### 2.2 Kurtarma kodu ile giriş

Koddaki uç ve ekranlar:

- Ekran: giriş sayfası (`/giris`), parola sonrası ikinci adım sayfası (`/iki-adim`). Düğme "Kurtarma kodu kullan" (`apps/web/src/components/auth/two-factor-form.tsx:132-134`), form başlığı "Kurtarma kodu ile giriş" (`two-factor-form.tsx:168-169`).
- Uç: `POST /v1/auth/totp/verify` (`services/api/app/api/v1/auth.py:309`). 6 haneli rakam TOTP sayılır, değilse kurtarma kodu olarak işlenir (`auth.py:343-351`, `auth.py:406-407`). Önce parola ile giriş yapılmış olmalı (bekleyen çerez, `auth.py:325-329`).
- Kod biçimi: 12 karakter, yalnız boşluk ve tire ayracı kabul edilir (`services/api/app/core/security.py:169-199`, `docs/security/degisiklik_2026-11-17_eposta_dogrulama.md` "Web" bölümü).
- Kod tek kullanımlıktır, atomik tüketilir (`services/api/app/services/auth.py:342-352`).
- Kullanıcıya otomatik e-posta gider: "girişte bir kurtarma kodu kullanıldı" (`auth.py:397-400`, gövde `auth.py:101-121`). Kullanıcıyı önceden uyar: bu e-posta normaldir.
- Denetim kaydı: `auth.recovery_code_used` ve `auth.login_recovery` (`auth.py:388-396`).

### 2.3 Panelde yeni TOTP ve yeni kurtarma kodları

Ekran: `/panel/guvenlik` (`apps/web/src/app/(app)/panel/guvenlik/page.tsx`, başlık "Güvenlik"). Ayarlar sayfasından bağlantılıdır (`apps/web/src/components/panel/settings-view.tsx:107`). Ekran `security-view.tsx` bileşenidir.

Sıra (kullanıcı kendi yapar):

1. `/panel/guvenlik` içinde "İki adımlı doğrulamayı kapat" (`security-view.tsx:126`). Form parola ve "doğrulama ya da kurtarma kodu" ister; kullanılmamış bir kurtarma kodu yazılır (`components/security/totp-manage-form.tsx:93,109`).
   - Uç: `POST /v1/auth/totp/disable` (`auth.py:663-708`). Kurtarma kodu burada kabul edilir.
   - Etkisi: sır silinir, kalan kurtarma kodları geçersiz olur, bu oturum dışındaki TÜM oturumlar kapanır, kullanıcıya e-posta gider (`auth.py:683-707`). Denetim: `auth.totp_disabled`.
2. "Kurulumu başlat" (`security-view.tsx`, `view.kind === 'setup'`). Parola istenir, QR ve elle anahtar gösterilir, uygulamadaki kod ile doğrulanır.
   - Uçlar: `POST /v1/auth/totp/setup` (`auth.py:557`) ve `POST /v1/auth/totp/enable` (`auth.py:605`).
   - Sonuçta 10 yeni kurtarma kodu BİR KEZ gösterilir. Kullanıcı "kaydettim" demeden "Bitti" kapalıdır (`docs/security/degisiklik_2026-11-17_eposta_dogrulama.md` "Web" bölümü). Kodları yalnız kullanıcı görür; destek hiçbir aşamada görmez.
   - Etkisi: diğer oturumlar yine kapanır, e-posta gider (`auth.py:649-659`). Denetim: `auth.totp_setup`, `auth.totp_enabled`.

Bilgi: "Kurtarma kodlarını yenile" yalnız güncel TOTP kodu kabul eder, kurtarma kodu kabul etmez (`auth.py:711-752`, `security-view.tsx:108-111`). Cihaz kayıpsa bu yol kullanılamaz; 1. ve 2. adımdaki kapat-ve-yeniden-kur yolu kullanılır.

### 2.4 Sınırlar ve kilit (kullanıcıya doğru bilgi vermek için)

- Giriş ve yeniden doğrulamada kullanıcı başına 15 dakikada 10 deneme (`services/api/app/core/config.py:101`).
- Yeniden doğrulamada ek olarak günde 30 deneme (`config.py:105`, `auth.py:527-531`).
- Art arda 5 hatalı ikinci faktörde 15 dakika kilit, yanıt 429 `totp-locked` (`config.py:112-113`, `auth.py:410-422`). Kilitliyken doğru kod da kabul edilmez. Kullanıcıya "15 dakika bekleyin" de.
- Panelde parola hataları kilide yazılmaz, yalnız hız sınırına girer (`auth.py:462-469`).
- E-postası doğrulanmamış hesap TOTP kuramaz (403 `email-not-verified`); kullanıcıya önce panelden doğrulama bağlantısını yeniden istetin (`docs/security/degisiklik_2026-11-17_eposta_dogrulama.md`).
- Kalan kurtarma kodu sayısı panelde görünür ("Kalan kurtarma kodu", 3 ve altında uyarı: `security-view.tsx:40,67-76`; API: `GET /v1/me` içinde `recovery_codes_remaining`, `api/v1/me.py:31`). Destek bu sayıyı göremez (bkz. bölüm 6).

### 2.5 Bilinen boşluk

Oturum kapalıyken yalnız 1 kurtarma kodu kalmış kullanıcı, kodu girişte harcar; kapatmak için ikinci kod gerekir, TOTP uygulaması da yok. Self-servis yol kapanır. Bu durum bölüm 3'e düşer. (Kod incelemesiyle çıkarıldı, doğrulanmadı.)

## 3. Kurtarma kodu da yoksa: destek yolu

### 3.1 Ön koşul ve beklenti yönetimi

Bu yol YAVAŞ ve bilerek sürtünmelidir. Kullanıcıya hemen sıfırlama sözü verilmez. Araç eksikliği nedeniyle (bölüm 4) şu an sonuç "talep kaydedildi ve onaya alındı" demektir.

### 3.2 Kimlik doğrulama adımları (hepsi gerekli)

A. Kanal: Talep yalnız hesaba kayıtlı e-posta adresinden gelirse işleme alınır. Başka adresten gelen, telefon, sosyal medya, canlı sohbet talepleri reddedilmez ama işleme de alınmaz; kullanıcıdan kayıtlı adresten yazması istenir.

B. E-posta sahipliği: Destek, hesap e-postasına yeni bir referans kodu yazar (talep numarası ile karışmayan, tek kullanımlık, 8 karakter). Kullanıcı aynı adresten bu kodu yanıtlar. Yanıt süresi 24 saat. (Yöntem öneridir; bunu otomatikleştiren bir araç yoktur, doğrulanmadı.)

C. Mağaza sahipliği kanıtı (en az biri, destek ipucu vermez, kullanıcı söyler, destek karşılaştırır):
   - Hesaba bağlı Trendyol satıcı numarası. Bağlantı kaydında tutulur (`services/api/app/api/v1/marketplace_accounts.py:84,117-160`).
   - Bağlı anahtarın son 4 hanesi. Kayıtta `api_key_last4` olarak tutulur (`marketplace_accounts.py:160`). Kullanıcının bunu Trendyol panelinden görüp göremeyeceği doğrulanmadı.
   - Hesap kayıt ayı ve kiracı (şirket) adı (`users.created_at`, `tenants.name`).
   Destek bu kayıtlara bugün hangi arayüzle bakar: doğrulanmadı (uygulamada destek rolü yok, bölüm 4). Karşılaştırma yetkisi olmayan ekip için C adımı yapılamaz; bu durumda talep Hasan'a gider.

D. Canlı sınama (şüphe varsa): kullanıcıdan Trendyol satıcı panelinde mağaza adını ve satıcı numarasını görüntülü ekran paylaşımında göstermesi istenir. Kayıt alınmaz, ekran görüntüsü alınmaz. Uygulanabilirliği ve KVKK uygunluğu doğrulanmadı (avukat teyidi).

E. Süre filtresi: B ve C tamamlandıktan sonra bile onaydan önce en az 24 saat beklenir. Bu süre içinde gerçek sahip hesabına e-posta ile ulaşıp itiraz edebilir (bölüm 3.4 kontrol).

### 3.3 Sosyal mühendislik kırmızı bayrakları

Bayraklardan biri varsa işlem durur, Hasan'a eskale edilir.

- Aciliyet baskısı: "bugün fatura keseceğim", "mağazam kapanıyor", "yönetici olarak emrediyorum".
- Talep kayıtlı adresten gelmiyor ya da adres yakın zamanda değişti (uygulamada e-posta değiştirme ucu bulunmadı: yeni bir adres kayıtlı adres sayılmaz).
- Kullanıcı başkası adına yazıyor (muhasebeci, "kardeşim", "çalışanım"). Hesap sahibinin kendisinden yazması istenir. Üçüncü kişi yetkilendirme yolu: doğrulanmadı.
- Kullanıcı mağaza kanıtını verirken eksik, yanlış ya da destekten ipucu bekliyor ("hangi numarayı gördünüz?").
- Kullanıcı parola, TOTP kodu, kurtarma kodu ya da API anahtarı göndermeye çalışıyor ya da "sizin tarafınızdan görülebilir mi" diye soruyor.
- Aynı hesap için kısa sürede birden çok talep, farklı kişi ya da farklı dil.
- Kimlik belgesi göndermeyi öneriyor ya da zorla gönderiyor (bölüm 3.5).
- Talepten önce yaşanan hesap hareketleri: ardışık hatalı giriş, kilit, parola sıfırlama isteği. Bu kayıtları yalnız kiracı sahibi ya da yöneticisi görebilir (`services/api/app/api/v1/tenant.py:57`); destek bu kayda bugün erişemez. Erişim yolu gelirse (bölüm 4) bu kontrol zorunlu olur.
- Sıfırlama sonrası hemen mağaza anahtarı değiştirme ya da dışa aktarım isteği (ikinci talep saldırı belirtisidir).

### 3.4 İki kişi onayı

- Talep sahibi (A): talebi alan destek çalışanı. Bölüm 3.2 adımlarını yürütür, kaydı doldurur.
- Onaylayan (B): A'dan farklı kişi. Başlangıçta Hasan ya da Hasan'ın yazılı olarak yetkilendirdiği kişi. Ekip büyüklüğü ve ikinci kişi belirsiz: doğrulanmadı.
- B, A'nın özetine güvenmez; kaydı ve kanıt karşılaştırmasını bağımsız okur, gerekirse C adımını kendisi tekrarlar.
- Onay kaydı yazılıdır (zaman, B'nin adı, karar, gerekçe). Sözlü onay geçersizdir.
- A ve B aynı kişi olamaz. Bir kişi hem talebi açıp hem onaylayamaz.
- Onay alındıktan sonra sıfırlama uygulanmadan önce son kontrol: gerçek sahibe kayıtlı adrese "talep var, siz değilseniz yanıtlayın" e-postası gitmiş ve 24 saatte itiraz gelmemiş olmalı (şablon T5).

### 3.5 Kişisel veri minimizasyonu (KVKK m.4: ölçülülük)

Destek kimlik belgesi kopyası saklamaz. Kullanıcı kendiliğinden gönderirse: yanıtla "göndermeyin", e-postayı ve eki posta kutusundan kalıcı sil, kayda yalnız "kimlik belgesi gönderildi ve silindi" yaz.

KAYDEDİLİR (talep kaydı, ürün veritabanı dışında, erişimi A, B ve Hasan ile sınırlı):
- Talep numarası.
- Hesap kimliği (kullanıcı UUID'si), e-posta adresi YAZILMAZ (talep numarası ve UUID yeter). Belirli bir kayıt tutma biçimi için doğrulanmadı.
- Talep tarihi, A'nın adı, B'nin adı, onay/red tarihi.
- Hangi doğrulama adımlarının geçildiği (B, C, D: "geçti/kaldı"), kanıt içeriği DEĞİL.
- Kırmızı bayrak var mıydı (evet/hayır, hangi madde numarası).
- Karar ve gerekçe (bir iki cümle).
- Uygulanan işlem ve tarihi (araç gelince araç kayıt numarası).

KAYDEDİLMEZ:
- Kimlik belgesi, kopyası, numarası, fotoğrafı.
- Parola, TOTP sırrı, TOTP kodu, kurtarma kodu, API anahtarı ve son 4 hanesi, satıcı numarası.
- Ekran görüntüsü, ekran kaydı.
- Mağaza, ürün, maliyet ya da kâr verisi.
- Telefon numarası, adres, vergi numarası.
- Kullanıcının IP adresi.

Saklama süresi: doğrulanmadı. Öneri: talep kaydı en çok 1 yıl; Hasan kararı ve avukat teyidi gerekir (bkz. `docs/research/03_hukuk_ve_uyum.md`). Yurt dışı barındırılan araçlara (posta, bilet) bu kaydın aktarımı KVKK m.9 sorusu doğurabilir; doğrulanmadı.

Ürün içi denetim kaydı (`audit_log`) kişisel veri içermez ve eklemelidir (`services/api/app/services/audit.py:1`, `services/api/app/models/tables.py:84-96`); kayda e-posta, belge ya da kanıt yazılmaz. Destek işlemi bu tabloya bugün yazılmaz (araç yok).

## 4. Teknik sıfırlama

### 4.1 Tespit: EKSİK, ARAÇ YOK

İncelenen yerler ve bulgu:

- `services/api/app/api/v1/auth.py` uçları: `register, login, totp/verify, logout, totp/setup, totp/enable, totp/disable, totp/recovery-codes, password-reset/request, password-reset/confirm, email/verify, email/resend`. Hepsi çağıranın KENDİ hesabı içindir; başka kullanıcı adına MFA kaldıran uç yok.
- `services/api/app/api/v1/tenant.py`: yalnız `GET /members`, `GET /sessions`, `GET /audit`. Üye listesi e-posta içermez (`tenant.py:21-29`). Üye yönetimi ya da MFA sıfırlama yok.
- Roller yalnız kiracı içi: `owner`, `admin`, `viewer` (`services/api/app/models/enums.py:8-13`). Platform çapında yönetici, destek ya da operatör rolü yok.
- `services/api/app/tools/`: `common, demo_card, demo_data, legal_documents, migrate_envelope, rewrap_keys, seed_demo`. MFA, oturum ya da kullanıcı araçlarından hiçbiri yok.
- `docs/security/degisiklik_2026-11-17_eposta_dogrulama.md` "Açık kalanlar": "destek MFA sıfırlama süreci belgesi" açık madde olarak duruyor; araç da aynı belgede anılmıyor.
- E-posta değiştirme ucu bulunmadı. Hesabın kayıtlı adresi değişmez; destek talebinde adres sorusu bu yüzden basittir.

Sonuç: Bugün destek, kullanıcının MFA'sını uygulama katmanında sıfırlayamaz. Bölüm 3'ü geçen bir talep teknik olarak bekler.

### 4.2 Gerekli aracın asgari gereksinimleri (öneri)

Araç, uygulamadaki mevcut güvenlik hatlarının yanında çalışmalı, onları atlamamalı.

1. Yetki: yalnız adlandırılmış destek yöneticisi kimliği (ayrı, MFA'lı, IP kısıtlı; `docs/50_guvenlik.md` G18 ile uyumlu). Uygulama kullanıcı rolleriyle (`owner`, `admin`) karıştırılmaz. Kiracı sahibi başka üyeyi sıfırlayacaksa ayrı karar.
2. İki kişi onayı araçta zorunlu: talebi açan kimlik ile onaylayan kimlik farklı olmalı; tek çağrıyla sıfırlama yok.
3. Yeniden doğrulama: araç kullanımı için işlemi yapanın güncel ikinci faktörü (`auth.py:496-554` desenine benzer: kullanıcı başına hız sınırı, günlük üst sınır).
4. Hedef kontrolü: hedef hesap kimliği (UUID) ve talep numarası zorunlu girdi; serbest e-posta ile arama yok. Aynı hesaba 24 saatte ikinci sıfırlama reddedilir.
5. Bekleme penceresi: onaydan sonra en az 24 saat sonra uygulanır (bölüm 3.2 E); bu sürede kullanıcıya bildirim gider ve itiraz hesabı dondurur.
6. İşlem kapsamı (tek işlemde, atomik):
   - TOTP'yi etkisiz hale getirmek ve TOTP sırrını, zaman adımını, hata sayacını, kilidi temizlemek (`auth.py:683-694` ile aynı alan seti).
   - Etkin kurtarma kodlarını geçersiz kılmak (silmeden; `services/api/app/services/auth.py:331-339` deseni).
   - Hedefin TÜM oturumlarını iptal etmek (`revoke_other_sessions` çağıranın bağlamıyla sınırlı olduğundan hedef için ayrı, yetkili bir işlev gerekir; mevcut işlev yetmez: `services/api/app/services/auth.py:370-378`).
   - Parolaya dokunmamak.
7. Sıfırlama sonrası durum: hesap "MFA zorunlu kurulum bekliyor" durumunda olmalı; kullanıcı girişte parola ile girer ve yeni TOTP kurulana kadar yalnız `/panel/guvenlik` açılır. Bu zorunlu kurulum özelliği kodda bugün yok (doğrulanmadı), aracın parçası olarak tasarlanmalı. Aksi halde hesap MFA'sız kalıcı açık kalır.
8. Kullanıcıya e-posta bildirimi: işlem anında kayıtlı adrese, işlem türü ve UTC zamanı ile. Mevcut `_queue_mfa_notice` (`auth.py:101-121`) örneği kullanılabilir. Bildirimde "siz istemediyseniz" yolu bulunmalı (parola sıfırlama bağlantısı yeterli değildir çünkü TOTP korunur; hesabı dondurma ve destek adresi eklenmeli).
9. Denetim kaydı: `audit_log` içine ayrı eylem adı (ör. `support.mfa_reset`); yazan kimlik, onaylayan kimlik, talep numarası, hedef kullanıcı UUID'si. E-posta, belge, kanıt YAZILMAZ. Kayıt ve işlem aynı işlemde commit edilir; kayıt yazılamazsa işlem geri alınır.
10. Geri alınamaz olmamalı (yani işlem tek yönlü bir kapı olmamalı): sıfırlama öncesi durum (TOTP etkin mi, kaç kurtarma kodu vardı) denetim kaydına sayı olarak yazılır; kullanıcı bildirimdeki itirazı ile hesap dondurulabilir; dondurma ve olay incelemesi için yöntem bulunur. Silme (sırrı ya da kodları fiziken silmek) yapılmaz; mevcut desen satır silmez, "iptal edildi" damgası koyar (`degisiklik_2026-11-17_eposta_dogrulama.md` 0019 notu).
11. Hız ve kötüye kullanım sınırı: araç başına günlük sıfırlama üst sınırı, aşımda alarm.
12. Bayrak kapatma: yapılandırmayla araç kapatılabilir (kill-switch).
13. Testler: yetki yok, tek kişi onayı, aynı hesaba tekrar, oturum iptali, bildirim hatası işlemi bozmaz, denetim yazılmazsa işlem olmaz.

### 4.3 Doğrudan veritabanında elle düzeltme

Önerilmez. Varsayılan yol, aracı yazmaktır.

Zorunlu kalırsa (üretimde acil, araç yok, talep bölüm 3'ü tamamen geçti) YALNIZ şu koşullarla:
- Hasan'ın yazılı onayı (bölüm 3.4 onayına ek).
- İşlemden hemen önce alınmış ve geri yüklenebildiği doğrulanmış yedek (G15).
- İşlemin kaydı: kim, ne zaman, hangi hesap kimliği (UUID), hangi alan grubu, neden, yedek tanımı. E-posta kayda girmez.
- Tek kişi yapmaz: ikinci kişi ekranı izler ve kaydı imzalar.

Bu belge SQL vermez. Veritabanında TOTP, kurtarma kodları ve oturumlar ayrı tablolarda, RLS ve değiştirilemezlik tetikleyicileriyle korunur (`degisiklik_2026-11-17_eposta_dogrulama.md`: 0017 doğrulama tetikleyicisi, 0019 RLS, 0020 değiştirilemezlik); elle müdahale hata yapmaya açıktır ve denetim kaydı bırakmaz. Elle işlem sonrası tutarlılığı kontrol etmek ve uygulamayı kullanıcıyla birlikte denemek ayrı bir adım olarak kayda yazılır.

## 5. Kullanıcıya yanıt şablonları

Adresleme: "Merhaba [Ad]," (ad yoksa "Merhaba,"). İmza: "NetTablo Destek". Köşeli parantez içi doldurulur. Destek adresi ve süre değerleri doğrulanmadı.

**T1. İlk yanıt (MFA'ya erişemiyor)**

> Merhaba,
>
> Doğrulama uygulamanıza erişemediğinizi anladım. Önce şunu soralım: Hesabı açarken ya da son yenilemede kaydettiğiniz kurtarma kodlarınız elinizde mi? Yalnız birini kontrol edin, bize yazmayın.
>
> Varsa kendiniz çözebilirsiniz, adımları ayrıca yazıyoruz. Yoksa söyleyin, size başka yolu anlatırız.
>
> NetTablo Destek

**T2. Kurtarma kodu var (kendi çözümü)**

> Merhaba,
>
> Kurtarma kodunuz varsa şöyle ilerleyin:
>
> 1. Giriş sayfasında e-posta ve parolanızı yazın. Kod sorulunca "Kurtarma kodu kullan" düğmesine basın ve kodlarınızdan birini girin. Bu kod bir daha çalışmaz. Girişte size bir bilgilendirme e-postası da gelir, bu normaldir.
> 2. Giriş yaptıktan sonra Ayarlar'dan Güvenlik sayfasına gidin ve "İki adımlı doğrulamayı kapat" düğmesine basın. Parolanızı ve bir kurtarma kodunu yazın.
> 3. Aynı sayfada "Kurulumu başlat" ile yeni telefonunuza doğrulama uygulamasını kurun. Size 10 yeni kurtarma kodu gösterilir. Bunları kaydedip "kaydettim" demeden sayfadan çıkmayın.
>
> Dikkat: Kapatma ve yeniden kurma sırasında diğer cihazlardaki oturumlarınız kapanır. Art arda hatalı kod girerseniz hesap 15 dakika kilitlenir; beklemeniz yeterli. Kodunuz kalmadıysa ya da birden az kaldıysa bize yazın.
>
> NetTablo Destek

**T3. Kurtarma kodu yok (kimlik doğrulama başlatma)**

> Merhaba,
>
> Kurtarma kodunuz yoksa hesabın size ait olduğunu doğrulamamız gerekir. Bu, hesabınızı ve mağaza verilerinizi korumak için zorunlu ve zaman alır. Hemen sıfırlama yapamayız.
>
> Önce bu yazışmayı hesabınıza kayıtlı e-posta adresinden sürdürün. Ardından size bir referans kodu göndereceğiz; aynı adresten yanıtlayın.
>
> Sonra mağaza sahipliğinizi doğrulamamız için bazı bilgiler soracağız. Kimlik belgesi, parola, kurtarma kodu ya da API anahtarı istemiyoruz ve göndermemenizi rica ediyoruz.
>
> NetTablo Destek

**T4. Doğrulama yetmedi / reddedildi**

> Merhaba,
>
> Verdiğiniz bilgilerle hesabın size ait olduğunu doğrulayamadık, bu yüzden bu aşamada iki adımlı doğrulamayı sıfırlayamıyoruz. Bu karar hesabınızı korumak içindir.
>
> Kurtarma kodlarınızı bulursanız ilk e-postamızdaki adımlarla kendiniz giriş yapabilirsiniz. Başka bir doğrulama yolu için bize aynı adresten yeniden yazabilirsiniz.
>
> NetTablo Destek

**T5. Onay bekleme ve itiraz hakkı (gerçek sahibe, kayıtlı adrese)**

> Merhaba,
>
> Hesabınız için iki adımlı doğrulamanın sıfırlanması talep edildi. Talep numarası: [no]. Bu talebi siz yapmadıysanız, bu e-postayı [süre] içinde "bu ben değilim" diye yanıtlayın; işlem durdurulur.
>
> Sorun yoksa bir şey yapmanız gerekmez. Sıfırlama [süre] sonra uygulanır ve ayrıca bildirim alırsınız.
>
> NetTablo Destek

**T6. Araç yokken bekletme (bugünkü durum)**

> Merhaba,
>
> Kimlik doğrulamanız tamamlandı, talebiniz onay aşamasında. İki adımlı doğrulamanın destek tarafından sıfırlanması için gereken araç henüz hazır değil; talebiniz yöneticiye iletildi. Sonuç için [süre] içinde size yazacağız. Bu sürede hesabınıza girmek için kurtarma kodlarınızı aramanızı öneririz.
>
> Anlayışınız için teşekkürler.
>
> NetTablo Destek

**T7. İşlem tamamlandı (araç gelince)**

> Merhaba,
>
> İki adımlı doğrulamanız sıfırlandı. Giriş yaptıktan sonra Ayarlar'daki Güvenlik sayfasından yeni doğrulama uygulamanızı kurun ve size gösterilen 10 kurtarma kodunu güvenli bir yere kaydedin. Hesabınızdaki diğer oturumlar kapatıldı, yeniden giriş yapmanız gerekecek.
>
> Bu işlemi siz istemediyseniz hemen bize yazın.
>
> NetTablo Destek

**T8. Kullanıcı kimlik belgesi gönderdi**

> Merhaba,
>
> Gönderdiğiniz kimlik belgesine ihtiyacımız yok ve saklamıyoruz. E-postayı ve eki sildik. Lütfen bir daha göndermeyin. Doğrulamayı yazdığımız diğer adımlarla yapacağız.
>
> NetTablo Destek

## 6. Doğrulanmadı ve eksikler

- EKSİK: MFA sıfırlama aracı yok (bölüm 4).
- EKSİK: Platform çapında destek/yönetici rolü yok; destek, kullanıcıya ait kayıtlara (kalan kod sayısı, son giriş hataları, bağlı mağaza, `api_key_last4`) uygulama içinden erişemiyor. Erişim yolu doğrulanmadı.
- EKSİK: Sıfırlama sonrası "zorunlu yeni TOTP kurulumu" ve hesap dondurma özelliği yok (4.2/7 ve 10).
- AÇIK: Oturum kapalı ve yalnız 1 kurtarma kodu kalan kullanıcı self-servis çözemez (2.5).
- AÇIK: Parola sıfırlama MFA'yı korur. Hem parola hem MFA kaybedenler iki ayrı çözüm yolu gerektirir (parola sıfırlama sonra bu belge); parola ucu e-posta erişimi ister. Eski hesap (0017 öncesi, doğrulanmamış ve TOTP etkin) davranışı farklıdır, prod denetimi açıktır (`degisiklik_2026-11-17_eposta_dogrulama.md` "O-06 dürüst durum").
- DOĞRULANMADI: Destek iletişim adresi (güvenlik sayfası lansmandan önce eklenecek diyor: `apps/web/src/app/(marketing)/guvenlik-ve-kvkk/page.tsx:65`), destek ekibi yapısı, ikinci onaylayan kişi, yanıt süreleri, bilet aracı.
- DOĞRULANMADI: Kullanıcının `api_key_last4` bilgisine Trendyol panelinden ulaşıp ulaşamayacağı; ekran paylaşımı yönteminin KVKK uygunluğu; üçüncü kişi (muhasebeci) yetkilendirme yolu.
- DOĞRULANMADI: Talep kaydının saklama süresi ve yurt dışı aktarım durumu (avukat teyidi, `docs/research/03_hukuk_ve_uyum.md`).
- Bu belgedeki kod davranışları kod okuyarak çıkarıldı; testler ve gerçek ortam denemesi yapılmadı.
- Kapsam dışı bırakıldı: kod değişikliği, test, e-posta gönderimi.
