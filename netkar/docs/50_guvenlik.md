# NetKâr · Güvenlik ve Uyum Gereksinimleri (v0.1)

Hedef: OWASP ASVS 5.0.0 (30 Mayıs 2025) Seviye 2. Bölüm numaraları 4.0.3'ten farklıdır; aşağıdaki "ASVS Vx" eşlemeleri S1'de 5.0 numaralarına güncellenecek (research/03 notu). Eşleme: OWASP Top 10 (2021) ve API Security Top 10 (2023), ISO/IEC 27001:2022 Ek A, NIST CSF 2.0, CIS Controls v8 IG1, PCI DSS 4.0 (SAQ-A kapsamında kalmak), KVKK. Sertifika bu aşamada hedef değil; politika ve kanıt klasörü (`docs/security/kanit/`) tutulur.

## 1. MVP öncesi zorunlu kontroller (merge engeli)

| # | Kontrol | Uygulama | Test/kanıt | Eşleme |
|---|---|---|---|---|
| G01 | Kiracı izolasyonu | Her sorguda tenant_id + PostgreSQL RLS | IDOR test paketi: A kiracısı B'nin kaynaklarına 404 almalı | API1 BOLA, ASVS V4 |
| G02 | Kimlik doğrulama | argon2id, en az 12 karakter, sızmış parola kontrolü (k-anonimlik), 2FA TOTP, giriş deneme limiti | Birim + e2e | ASVS V2, API2 |
| G03 | Oturum | HttpOnly, Secure, SameSite=Lax çerez; 12 saat boşta, 30 gün mutlak; oturum yenileme ve çıkışta iptal | e2e | ASVS V3 |
| G04 | CSRF | Çift gönderim token + SameSite | Test | A01 |
| G05 | Pazaryeri anahtarları | AES-256-GCM zarf şifreleme (kayıt başına DEK, KEK ile sarılı, kid'li ve döndürülebilir: ADR-0004); KEK ortam değişkeninde (KMS faz 2); anahtar ekranda bir kez gösterilmez, yalnız son 4 hane | Birim test + kod incelemesi | ASVS V6, A02 |
| G06 | Girdi doğrulama | Pydantic/Zod şemaları, boyut limitleri, Excel içe aktarmada formül enjeksiyonu (CSV injection) engeli | Birim test | A03 |
| G07 | Rate limit | IP + kullanıcı + kiracı bazında; giriş, kayıt, şifre sıfırlama, ihracat uç noktalarında sıkı | Test | API4 |
| G08 | Hata yanıtları | RFC 9457; stack trace ve iç ayrıntı istemciye gitmez | Test | A05 |
| G09 | Log | JSON, kişisel veri ve sır maskeleme filtresi | Birim test (maskeleme) | A09 |
| G10 | Güvenlik başlıkları | CSP (nonce), HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame-ancestors 'none' | Otomatik başlık testi | A05 |
| G11 | Bağımlılıklar | pip-audit, npm audit, Renovate; yüksek/kritik açıkla merge yok | CI | A06 |
| G12 | Statik analiz | Semgrep (OWASP kuralları), Bandit, ESLint security | CI | |
| G13 | Sır tarama | gitleaks (pre-commit + CI) | CI | |
| G14 | Konteyner | Trivy, root olmayan kullanıcı, salt okunur dosya sistemi mümkünse | CI | CIS |
| G15 | Yedek | Günlük şifreli yedek, haftalık geri yükleme testi | Test kaydı | NIST RC, ISO A.8.13 |
| G16 | Kişisel veri | Son müşteri PII'si DB'ye yazılmaz; saklama ve imha politikası | Senkron testi: PII alanları null | KVKK m.4 ve m.12 |
| G17 | Ödeme | Ödeme kuruluşunun barındırdığı form veya tokenizasyon; kart verisi sistemimize hiç gelmez | Mimari inceleme | PCI DSS SAQ-A |
| G18 | Yönetici erişimi | Sunucuya yalnız SSH anahtarı + 2FA'lı Coolify paneli; IP kısıtı; root girişi kapalı | Kontrol listesi | CIS 4, 5, 6 |

## 2. Lansman öncesi
- Bağımsız güvenlik denetimi (opus denetçi + mümkünse dış pentest, bütçe Hasan kararı).
- OWASP ZAP otomatik taraması staging'de, bulgular kapatılmış.
- Olay müdahale planı (KVKK 72 saat bildirim dahil), güvenlik iletişim adresi, `security.txt`.
- Politika seti: erişim kontrolü, şifreleme, yedekleme, değişiklik yönetimi, tedarikçi yönetimi, olay müdahalesi (ISO 27001 Ek A uyumlu kısa dokümanlar).

## 3. Sürekli
- Aylık bağımlılık güncellemesi, üç aylık erişim gözden geçirmesi, yıllık politika gözden geçirmesi.
- Her büyük özellikte tehdit modeli (STRIDE, kısa).
