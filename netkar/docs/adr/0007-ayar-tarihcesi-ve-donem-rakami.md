# ADR-0007: Ayar tarihçesi (geçmiş dönem raporunun izsiz yeniden yazılmaması) ve kısmi dönemde dönem rakamı

- Durum: Önerildi (alan tasarımı; uygulama P0 kartında, ADR-0006'nın devamı)
- Tarih: 10 Kasım 2026
- İlgili: denetim `docs/security/denetim_2026-11-09_kar_ayarlari.md` (AO-02, AO-03, §6, §7, §8, Ek A.2, A.3);
  `docs/12_kar_motoru.md` v0.3 (K39 Revizyon 1, K42-K44, §9 madde 20 ve 23-26); ADR-0006 (Revizyon 1 bölümü bu
  karara bağlanır); ADR-0001 (RLS); `docs/research/03_hukuk_ve_uyum.md` §2.1 (veri rolleri), §2.8 (saklama);
  altın test G49 ve betik `calisma_dosyalari/altin_test_hesap_ayarlar.py`.
- **Revizyon 1 (10 Kasım 2026):** bağımsız denetim `docs/security/denetim_2026-11-10_ayar_tarihcesi.md` (YT-01..YT-10)
  sonrası uygulama ve belge güncellemesi. Eski içerik silinmedi; değişen yerlerde "Revizyon 1" notu vardır: §3
  (kullanıcı kimlikleri, tetikleyici ve `SET NULL`), §4 (`ck_..._replace` taslağı, başlıksız hesap taşıması, yeni
  migrasyon 0009), §5.1 (`confirm_affects_from`, `changed_by`, mühürlü `GET /history` imleci), §7 madde 1.
- **Revizyon 3 (11 Kasım 2026):** kapanış denetimi `docs/security/denetim_2026-11-11_ayar_tarihcesi_kapanis.md`
  (YK-01..YK-05) sonrası: §4.1 yeni migrasyon 0010 (sayaç işlem bağı), bileşik FK'nin koruma sınırı, üyelik silme ve
  kiracı imha sırası, indeks tanımının hizalanması, `search_path`; §5.1 (`confirm_affects_from` gövde ayrıştırması,
  üyelik silindiyse ifadesi). Eski içerik silinmedi.
- **Revizyon 4 (11 Kasım 2026):** kapanış denetimi `docs/security/denetim_2026-11-11_0010_kapanis.md` (ZK-01..ZK-05)
  sonrası: §4.2 yeni migrasyon 0011 (başlık kilidi: sütun düzeyi UPDATE, hesap anahtarı değişmezliği, işlem başına tek
  artış, olumlu muafiyet listesi). Eski içerik silinmedi.
- **Revizyon 2 (11 Kasım 2026):** yalnız belge düzeltmesi; kod kuralı değişmedi: §5.2 "Ayar ekranı" madde 1 (panel K43
  etki tarihini önceden hesaplamaz, sunucunun 409'una dayanır; geri çekmede istemci önce kendi onayını ister).

## 1. Karar: kısmi dönemde dönem rakamı (AO-03, docs/12 K39 Revizyon 1)

**Karar:** kısmi dönemde (`net_kar_kismi = true`) `donem_net_kar` ve `satir_net_kar_toplami` **null**; dönem için
yeni, her zaman sayı olan `donem_eksik_giderler_haric_kar` = Σ aktif satır `eksik_giderler_haric_kar` -
`donem_duzeyi_giderler_toplami`. Tam satır sayısı 0 iken `tam_satirlar` bloğu boş toplamdır (0,00, marj null) ve
panelde gösterilmez; dönemin tek kâr rakamı `donem_eksik_giderler_haric_kar`'dır. Özdeşlikler I1-I6 docs/12'de.

**Gerekçe (tek cümle):** ADR-0006 §2.1 satırda "eksik kalemi 0 sayıp bayrakla döndürmeyi" reddetti; aynı ilke
dönemde de geçerlidir: "net kâr" adını taşıyan alan ya gerçek değeri taşır ya null'dır, bilinen kısım adı ne
olduğunu söyleyen ayrı alandadır.

**Etkiler:** G01-G48'de değişen eski değerler: G29, G42, G43, G45, G46, G48 `donem_net_kar` (ve kısmi olanlarda
`satir_net_kar_toplami`) null; 49 senaryonun hepsine `donem_eksik_giderler_haric_kar` eklendi; yeni G49 (tam
satırsız dönem + dönem gideri). Reddedilen alternatifler (tam satırların dönem giderleri dahil kârı, yalnız tam satır
0 iken null, dönem giderlerini tam satırlara dağıtmak, yeni alan için marj) gerekçeleriyle docs/12 K39 Revizyon 1
tablosundadır.

## 2. Karar: ayar tarihçesi (AO-02, docs/12 K42-K44)

### 2.1 Değerlendirilen seçenekler

| Ölçüt | (a) Değişmez kayıt (append-only): PUT yeni satır + eski "yerini aldı"; DELETE yerine "geri çekme" | (b) Kapanmış dönem kilidi: ekstresi kesinleşmiş aylar için geriye tarihli değişiklik reddedilir ya da onay ister | (c) Yalnız denetim izini zenginleştirmek (eski/yeni değer özeti audit_log'a) |
|---|---|---|---|
| "Bu ay neden değişti" cevaplanır mı | Evet: önceki değer, kim, ne zaman, hangi kayıt | Hayır (kilitli ayda değişiklik olmaz; kilitsiz ayda iz yok) | Evet ama değer audit_log'da |
| Yanlış girişin düzeltilmesi | Serbest, izli | Engellenir ya da onaya bağlanır; yanlış değer kapanmış ayda kalır | Serbest |
| Kurulum akışı (geriye tarihli ilk giriş, denetim AB-01) | Etkilenmez (ilk giriş istisnası, K43) | Kilit sürümü kurulumu bozar: yeni hesap geçmiş aylara tarife giremez | Etkilenmez |
| "Kapanmış dönem" tanımı | Gerekmez | Gerekir; NetKâr'da yetkili kapanış yok: ekstre, iade, kargo faturası ve düzeltmeler haftalarca gelir, `settled` kapanış değildir (K22) | Gerekmez |
| Tutar yazmama kuralı (ADR-0006 §3.3) | Korunur: tutar değişmez satırda, denetimde kimlik | Etkilenmez | **Çatışır**: tutar güvenlik kaydına girer |
| KVKK (aşağıda §3) | Aynı amaç, aynı saklama, aynı RLS; ek veri kategorisi yok | Etkisiz | Ticari değerler ikinci bir depoya (farklı saklama süresi, şemasız jsonb) yayılır: veri en aza indirme ilkesine aykırı yön |
| Veritabanı düzeyinde güvence | Var: `netkar_app`'ten DELETE ve iş alanı UPDATE yetkisi kalkar, tetikleyici kapanmış satırı korur | Uygulama kuralı | Yok: yerinde ezme sürer, iz yalnız uygulama yazarsa var |
| Rapor yeniden üretimi (K44) | Sürümle yüklenebilir | Yalnız kilitli aylar için | Değerler serbest metin; yeniden kurmak kırılgan |
| Uygulama maliyeti | Orta (migrasyon 0008, servis, günlük, geçmiş ucu) | Orta (dönem kavramı, kural, istisnalar) | Düşük |

### 2.2 Seçilen: (a) + (b)'nin yumuşak biçimi (onay) + (c)'nin kimlik kısmı

1. **(a) Değişmez ayar satırları ve ayar günlüğü** (K42). Satırın iş alanları değişmez, uygulama silmez;
   değiştirme eski satırı `revision_to` ile kapatıp yeni satır ekler (`replaces_id`), geri çekme yalnız kapatır.
   Varsayılan desinin önceki ve yeni değeri günlükte.
2. **(b) yerine onay** (K43). Geçmişi etkileyen yazım (`affects_from` bugünden önce ya da tarihsiz) açık onay
   olmadan uygulanmaz (409); yalnız "eksik"i dolduran ilk giriş istisnadır. Sert kilit **reddedildi** (kurulumu
   bozar, yetkili kapanış yok, yanlış değeri korur). Kullanıcının bilerek bir ayı "kapatması" ve kapatılmış ayın
   raporunun dondurulması ayrı bir özelliktir; müşavirin beklentisi (docs/12 §9 madde 24) gelince değerlendirilir.
3. **(c)'den yalnız kimlikler.** `audit_log` meta'sı kalem, işlem, satır ve yerini aldığı satır kimliği, anlaşma,
   firma, başlangıç, gider adı ve tipi, etki tarihi, onay ve sürümü taşır; **tutar taşımaz**. Önceki değer
   değişmez satırdan okunur. Böylece denetimin istediği "ne silindi, ne değişti" kimlikle cevaplanır, tutar
   yazmama kuralı ve güvenlik kaydının amacı korunur.

**Gerekçe (tek cümle):** sürümlemenin vaadi ("ayar değişikliği geçmiş raporu sessizce değiştirmez") ancak eski
değerler veritabanı düzeyinde silinemez ve geçmişi etkileyen değişiklik kullanıcının bilgisiyle yapılırsa
tutar; kilit ise meşru düzeltmeyi ve kurulumu engellediği için yanlış araçtır.

## 3. KVKK ve mali kayıt düzeni değerlendirmesi

> Bu bölüm hukuki ya da mali görüş değildir; research/03 ile aynı ilke: "Doğrulanmadı" ve "varsayım" yazan
> maddeler karar dayanağı yapılmadan avukat ve müşavirle teyit edilir.

**Verinin niteliği ve rol.** Kargo tarifesi, hizmet bedeli tahmini ve değişken gider satıcının ticari verisidir.
Satıcı tüzel kişiyse kişisel veri değildir; şahıs işletmesiyse kişisel veri olabilir (research/03 §2.1). NetKâr
satıcının finans verisinde veri işleyendir (aynı tablo). `entered_by`, `ended_by`, `changed_by` NetKâr kullanıcı
kimlikleridir; bunlarda NetKâr veri sorumlusudur (aynı tablo, "Kullanıcı hesabı ... log kayıtları"). Bu kimlikler
bugün de `audit_log`'da ve 0007 tablolarında (`entered_by`) tutuluyor; seçenek (a) yeni bir veri kategorisi
eklemez.

**Amaç ve ölçülülük (KVKK m.4/2, research/03 §2.1 tablosu).** Eski sürümler aynı amaç için (satıcının kendi kâr
raporunun açıklanabilirliği) ve aynı kiracı içinde, aynı RLS altında saklanır. Tarihçeyi kiracıdan gizlemek yerine
"ayar geçmişi" ekranıyla göstermek şeffaflığı artırır. Saklanan ek hacim, yazma hız sınırıyla sınırlıdır.

**Saklama ve imha (research/03 §2.8).** Ayar satırları ve günlük, hesabın diğer verileriyle aynı sürede saklanır
(öneri tablosu: "Sipariş, iade, finans satırları: abonelik süresi + 30 gün") ve hesapla birlikte silinir.
Değişmezlik yalnız uygulama rolü (`netkar_app`) içindir: hesap silme ve periyodik imha işi ayrı, yetkili rolle
çalışır, imha kaydı tutar (research/03 §2.8: periyodik imha ve imha kayıtları). Bu iş bugün yoktur; ayar tarihçesi
için engel oluşturmaması kabul ölçütüdür (§8). Satıcının bir ayar kaydını "silmesi" iş düzeltmesidir, KVKK
anlamında silme talebi değildir; ilgili kişinin silme talebi hesap düzeyinde işlenir.

**Kullanıcı kimlikleri.** `entered_by`, `ended_by`, `changed_by` `users (id)`'ye yabancı anahtardır; değişmez
satırlar bir kullanıcı kaydının silinmesini engeller. Kullanıcı hesabı kapatma akışı (research/03 öneri tablosu:
"hesap kapanınca + 30 gün; sonra silme") kullanıcı satırını silmek yerine kimliksizleştirmeli (ad ve e-posta
silinir, kimlik kalır) ya da bu sütunlar `ON DELETE SET NULL` olmalıdır. Hangisinin yeterli olduğu avukata sorulur
(§7 madde 1). `audit_log.user_id` aynı durumdadır; yeni bir sorun değildir.

> **Revizyon 1 (YT-05):** `ON DELETE SET NULL` bu tasarımda uygulandığı hâliyle işlemez: PostgreSQL referans eylemi
> referans veren tabloda UPDATE yapar ve `profit_settings_version_guard` kapanmış satırdaki her güncellemeyi (ve
> `entered_by`/`ended_by` dahil iş alanı değişikliğini) reddeder; kullanıcı silme hatayla durur. Bu yüzden
> kimliksizleştirme (kullanıcı satırında ad ve e-postayı silip kimliği tutmak) tercih edilir. `SET NULL` seçilirse
> tetikleyici ayrı bir migrasyonla `entered_by` ve `ended_by` için yalnız `NOT NULL -> NULL` geçişine izin vermelidir.
> Sürümlü tablolarda veri doldurma migrasyonu önce doldurur sonra tetikleyiciyi kurar ya da aynı işlemde `ALTER TABLE
> ... DISABLE TRIGGER trg_<tablo>_version_guard` / `ENABLE TRIGGER` kullanır (docs/12 K42 Revizyon 1). 0009'dan
> itibaren `changed_by` ayrıca `(changed_by, tenant_id) -> memberships (user_id, tenant_id)` bileşik yabancı
> anahtarıyla kiracı üyesine bağlıdır; üyelik silme özelliği yoktur (`netkar_app` memberships'te DELETE'e sahip
> değil), eklenirse bu FK'ye takılır ve kimliksizleştirme (üyeliği tutmak) gerekir.

**Mali kayıt düzeni.** NetKâr raporu bir yönetim raporudur; yasal defter ya da belge sayılmadığı **varsayımdır**
(docs/12 §9 madde 25'te müşavire sorulur). Yasal defter ve belge saklama yükümlülükleri (research/03 §2.8: VUK
m.253, TTK m.82) NetKâr'ın kendi faturaları ve ödeme kayıtları içindir; satıcının ayar tarihçesine uygulanmaz.
Buna rağmen rapor müşavire ya da muhasebeye veriliyorsa "verilen rakam neden değişti" sorusu doğar. Muhasebedeki
"kayıt silinmez, düzeltme ayrı kayıtla yapılır" uygulaması seçenek (a)'nın tasarım benzetmesidir; NetKâr için
yasal dayanak iddia edilmez (benzetmenin yerindeliği §9 madde 25).

## 4. Migrasyon taslağı (`0008_profit_settings_history.py`, revises `0007`)

Kalıp 0007 ile aynı: rollerin varlık kontrolü, ENABLE + FORCE RLS, `tenant_isolation` politikası (`USING` ve
`WITH CHECK`), açık sıra, `CASCADE` yok, Türkçe ama ASCII hata metinleri.

```sql
-- 1. Sürüm aralığı ve kapanış sütunları (üç sürümlü tablo: cargo_tariffs, service_fee_estimates, variable_expenses)
ALTER TABLE cargo_tariffs
    ADD COLUMN revision_from bigint,                              -- satırın eklendiği ayar sürümü
    ADD COLUMN revision_to bigint,                                -- kapandığı sürüm; NULL = etkin
    ADD COLUMN ended_at timestamptz,
    ADD COLUMN ended_by uuid REFERENCES users (id),
    ADD COLUMN end_reason text,                                   -- 'degistirildi' | 'geri_cekildi'
    ADD COLUMN replaces_id uuid REFERENCES cargo_tariffs (id);    -- değiştirmede yerini aldığı satır
-- (service_fee_estimates ve variable_expenses için aynı; replaces_id kendi tablosuna)

-- 2. Doldurma: FORCE RLS altında sahip rol satır göremez (0007 _guard_user_data ile aynı yöntem);
--    bu işlemde geçici olarak NO FORCE, işlem sonunda yeniden FORCE.
ALTER TABLE profit_settings NO FORCE ROW LEVEL SECURITY;
ALTER TABLE cargo_tariffs NO FORCE ROW LEVEL SECURITY;
UPDATE cargo_tariffs t SET revision_from = p.revision
  FROM profit_settings p
 WHERE p.marketplace_account_id = t.marketplace_account_id AND p.tenant_id = t.tenant_id;
UPDATE cargo_tariffs SET revision_from = 1 WHERE revision_from IS NULL;   -- savunma: ayar satırı olmayan hesap
-- Revizyon 1 (YT-03): yukarıdaki savunma satırı UYGULANMADI ve taslaktan çıkarıldı sayılır. Ayar satırı olmayan
-- hesap `revision_from = 1` alıp `tasima` kaydı almıyor, damga 0 iken etkin satırı olan tutarsız bir durum bırakıyor ve
-- ilk değiştirmede `ck_..._ended` ihlaliyle 500 veriyordu. Uygulanan 0008 doldurmadan ÖNCE başlığı olmayan hesaplar için
-- `INSERT INTO profit_settings (tenant_id, marketplace_account_id, revision, updated_by) SELECT DISTINCT ON
-- (marketplace_account_id) tenant_id, marketplace_account_id, 1, entered_by FROM (üç tablonun satırları UNION ALL) ...
-- WHERE NOT EXISTS (başlık) ORDER BY marketplace_account_id, created_at` çalıştırır; sonra doldurma ve `tasima` kaydı
-- herkes için aynı yoldan işler (0008 hiçbir ortamda çalışmadan yerinde düzeltildi).
ALTER TABLE cargo_tariffs ALTER COLUMN revision_from SET NOT NULL;
ALTER TABLE cargo_tariffs ADD CONSTRAINT ck_cargo_tariffs_revision CHECK (revision_from >= 1);
ALTER TABLE cargo_tariffs ADD CONSTRAINT ck_cargo_tariffs_ended CHECK (
      (revision_to IS NULL AND ended_at IS NULL AND ended_by IS NULL AND end_reason IS NULL)
   OR (revision_to IS NOT NULL AND revision_to > revision_from AND ended_at IS NOT NULL
       AND ended_by IS NOT NULL AND end_reason IN ('degistirildi', 'geri_cekildi')));
ALTER TABLE cargo_tariffs ADD CONSTRAINT ck_cargo_tariffs_replaces CHECK (replaces_id IS NULL OR replaces_id <> id);
-- (üç tablo için aynı; sonra her birinde FORCE ROW LEVEL SECURITY geri açılır)

-- 3. Tekillik yalnız etkin satırlarda
ALTER TABLE cargo_tariffs DROP CONSTRAINT uq_cargo_tariffs_version;
CREATE UNIQUE INDEX uq_cargo_tariffs_active_version
    ON cargo_tariffs (marketplace_account_id, agreement, carrier, valid_from) WHERE revision_to IS NULL;
ALTER TABLE service_fee_estimates DROP CONSTRAINT uq_service_fee_estimates_version;
CREATE UNIQUE INDEX uq_service_fee_estimates_active_version
    ON service_fee_estimates (marketplace_account_id, valid_from) WHERE revision_to IS NULL;
-- Etkin satır okuma ve sürümle (as-of) okuma için:
CREATE INDEX ix_cargo_tariffs_active ON cargo_tariffs (tenant_id, marketplace_account_id) WHERE revision_to IS NULL;
CREATE INDEX ix_cargo_tariffs_revision ON cargo_tariffs (tenant_id, marketplace_account_id, revision_from);
-- (üç tablo için aynı)

-- 4. Değişmezlik: tetikleyici (sahip rol dahil) + yetki (uygulama rolü)
CREATE FUNCTION profit_settings_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kapanmis kar ayari surumu degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason']) THEN
        RAISE EXCEPTION 'kar ayari surumunun is alanlari degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER trg_cargo_tariffs_version_guard BEFORE UPDATE ON cargo_tariffs
    FOR EACH ROW EXECUTE FUNCTION profit_settings_version_guard();
-- (üç tablo için aynı)
REVOKE UPDATE, DELETE ON cargo_tariffs, service_fee_estimates, variable_expenses FROM netkar_app;
GRANT UPDATE (revision_to, ended_at, ended_by, end_reason)
    ON cargo_tariffs, service_fee_estimates, variable_expenses TO netkar_app;
-- profit_settings: yetki değişmez (revision, default_desi, updated_by, updated_at güncellenir; DELETE zaten yok).

-- 5. Ayar günlüğü: ayar sürümü başına tek kayıt
CREATE TABLE profit_settings_changes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants (id),
    marketplace_account_id uuid NOT NULL,
    CONSTRAINT fk_profit_settings_changes_account FOREIGN KEY (marketplace_account_id, tenant_id)
        REFERENCES marketplace_accounts (id, tenant_id),
    revision bigint NOT NULL CHECK (revision >= 1),
    changed_by uuid REFERENCES users (id),                 -- NULL yalnız 'tasima'
    changed_at timestamptz NOT NULL DEFAULT now(),
    item text NOT NULL CHECK (item IN ('cargo_tariff', 'service_fee_estimate', 'variable_expense',
                                       'defaults', 'tasima')),
    action text NOT NULL CHECK (action IN ('ekle', 'degistir', 'geri_cek', 'tasima')),
    record_id uuid,                                        -- eklenen ya da geri çekilen satır (tablo item'dan)
    replaced_record_id uuid,                               -- değiştirmede kapanan satır
    affects_from date,                                     -- NULL: tarihsiz (varsayılan desi) ya da tasima
    affects_past boolean NOT NULL,
    past_change_confirmed boolean NOT NULL DEFAULT false,
    default_desi_before numeric(9,2),                      -- yalnız defaults ve tasima
    default_desi_after numeric(9,2),
    CONSTRAINT uq_profit_settings_changes_revision UNIQUE (marketplace_account_id, revision),
    CONSTRAINT ck_profit_settings_changes_tasima CHECK ((item = 'tasima') = (action = 'tasima')),
    CONSTRAINT ck_profit_settings_changes_actor CHECK (item = 'tasima' OR changed_by IS NOT NULL),
    CONSTRAINT ck_profit_settings_changes_desi CHECK (
        item IN ('defaults', 'tasima') OR (default_desi_before IS NULL AND default_desi_after IS NULL)),
    CONSTRAINT ck_profit_settings_changes_replace CHECK ((action = 'degistir') = (replaced_record_id IS NOT NULL))
    -- Revizyon 1 (YT-08, YT-09): bu taslak kendi içinde çelişkiliydi. K42 varsayılan desi değişikliğini günlüğe
    -- `degistir` olarak yazdırır ama desinin satır kimliği yoktur; taslak `defaults` + `degistir` kaydını imkansız
    -- kılardı. 0008 şu kısıtla uygulandı (`defaults` istisnası):
    --   CHECK (item = 'defaults' OR (action = 'degistir') = (replaced_record_id IS NOT NULL))
    -- İstisna fazla genişti (`defaults` kaydı `record_id`/`replaced_record_id` taşıyabiliyordu); 0009 şu daha sıkı
    -- kısıtla değiştirdi:
    --   CHECK ((item = 'defaults' AND record_id IS NULL AND replaced_record_id IS NULL
    --           AND (action <> 'ekle' OR default_desi_before IS NULL)
    --           AND (action <> 'geri_cek' OR default_desi_after IS NULL))
    --       OR (item <> 'defaults' AND (action = 'degistir') = (replaced_record_id IS NOT NULL)))
);
CREATE INDEX ix_profit_settings_changes_tenant_account
    ON profit_settings_changes (tenant_id, marketplace_account_id, revision DESC);
ALTER TABLE profit_settings_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE profit_settings_changes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON profit_settings_changes
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT ON profit_settings_changes TO netkar_app;   -- UPDATE ve DELETE yok
GRANT SELECT ON profit_settings_changes TO netkar_worker;

-- 6. Taşıma kaydı: her hesap için mevcut durumun sınırı (K44). NO FORCE altında, sonra FORCE geri.
INSERT INTO profit_settings_changes (tenant_id, marketplace_account_id, revision, changed_at, item, action,
                                     affects_past, default_desi_after)
SELECT tenant_id, marketplace_account_id, revision, now(), 'tasima', 'tasima', false, default_desi
  FROM profit_settings;
```

- **Taşıma notu:** 0008 öncesi yazımların sürüm başına kaydı yoktur; mevcut satırlar o anki sürümle işaretlenir
  ve `tasima` kaydı bu sınırı belirtir. Daha eski bir sürümle yükleme "yeniden kurulamaz" hatasıdır (K44). Bugün
  canlı veri yoktur (P0 yayınlanmadı); taşıma test ve hazırlık ortamları içindir.
  **Revizyon 1 (YT-03):** satırı olup `profit_settings` başlığı olmayan hesap için taşıma başlığı `revision = 1`
  ile önce oluşturur (yukarıdaki SQL notu); böylece etkin satırı olan her hesapta damga en az 1'dir ve `tasima`
  kaydı herkes için düşer. Test: 0007 şemasında başlıksız satır, upgrade sonrası başlık `revision = 1`, `tasima`
  kaydı var, aynı anahtarlı `PUT` 200 ve sürüm 2.
- **Geri alma (`downgrade`):** kapanmış satır (`revision_to IS NOT NULL`) ya da `tasima` dışı günlük kaydı varsa,
  bunlar eski şemaya sığmaz (aynı anahtarlı kapanmış satırlar eski tekillik kısıtını bozar) ve silinmeleri
  gerekir: downgrade Türkçe bir hatayla DURUR, veri kaybı `NETKAR_ALLOW_SETTINGS_HISTORY_LOSS=1` ile bilerek kabul
  edilir (0007 AD-03 kalıbı; hata metni `\copy profit_settings_changes TO ...` ve kapanmış satırlar için
  `\copy (SELECT * FROM cargo_tariffs WHERE revision_to IS NOT NULL) TO ...` yedeğini önerir). Sonra sırayla: NO
  FORCE; kapanmış satırları sil; günlüğü düşür; tetikleyicileri ve işlevi düşür; etkin indeksleri düşür; eski
  `uq_*_version` kısıtlarını geri ekle; sütunları düşür; sütun düzeyi UPDATE yetkisini geri al, tablo düzeyi
  `UPDATE, DELETE` yetkisini `netkar_app`'e geri ver; FORCE. Etkin satırlar ve değerleri korunur.
- **Migrasyon testleri:** `test_migrations.py` kalıbında upgrade/downgrade/upgrade (boş ve dolu, bayraklı ve
  bayraksız); `test_rls_idor.py` kalıbında günlükte kiracılar arası okuma/yazma reddi; `netkar_app` ile `DELETE
  FROM cargo_tariffs` ve `UPDATE cargo_tariffs SET brackets = ...` yetki hatası; sahip rolle kapanmış satırın
  güncellenmesi tetikleyici hatası; etkin satırın yalnız kapanış sütunlarının güncellenmesi başarılı.

### 4.1 Revizyon 1: migrasyon `0009_profit_settings_history_hardening.py` (revises `0008`; YT-02, YT-04, YT-09)

Geri alınabilir ek migrasyon (0008'e eklenmedi; yalnız YT-03 0008'de düzeltildi). İçerik:

- **YT-02:** `CREATE INDEX ix_<tablo>_replaces ON <tablo> (replaces_id) WHERE replaces_id IS NOT NULL` (üç sürümlü
  tablo). **Revizyon 3 (YK-05):** uygulanan tanım `e320f7d` sonrası `(replaces_id, tenant_id, marketplace_account_id)
  WHERE replaces_id IS NOT NULL`'dir (kapsam sütunları indekste; istatistiği olmayan tabloda planlayıcı her adımda
  hesabın bütün satırlarını taramasın); yukarıdaki tek sütunlu tanım ilk taslaktır. `settings-record-ended` halef zinciri tek özyinelemeli sorguyla yürünür (üst sınır 10.000; aşılırsa
  `current_id` null).
- **YT-04 (derinlemesine savunma):** `netkar_app` INSERT ile tarihçeyi sahteleyebiliyordu. Eklenenler:
  `BEFORE INSERT` tetikleyicisi (üç sürümlü tablo): satır baştan kapalı olamaz, `revision_from` aynı işlemde
  artırılmış `profit_settings.revision`'a eşit olmalı (yazım akışı başlığı satırdan önce flush eder);
  `profit_settings_version_guard` genişletildi: uygulama rolü satırı yalnız sayaçtaki sürümle kapatır
  (`revision_to = sayaç`); `BEFORE INSERT` günlük tetikleyicisi: `revision` sayaca eşit, `tasima` kaydını uygulama
  rolü yazamaz; `changed_by` için bileşik FK `(changed_by, tenant_id) -> memberships (user_id, tenant_id)`
  (`changed_by` boşsa denetlenmez). **Sapma ve gerekçe:** sıra kuralları yalnız `current_user = 'netkar_app'` için
  uygulanır; tablo sahibi zaten tetikleyiciyi kapatabilir ve sahip rolle çalışan veri doldurma migrasyonları
  (YT-05) sıra kuralına takılmamalıdır. Değişmezlik tetikleyicisi (kapanmış satır, iş alanları) ve bileşik FK
  herkesi bağlar. Denetimin beş sahte yazımının (geçmiş `revision_from`, baştan kapalı satır, sahte `tasima`, başka
  kiracı kullanıcısı `changed_by`, sayaçtan kopuk `revision_to`) her biri testle reddedilir.
  **Revizyon 3 (YK-01, YK-02):** "aynı işlemde artırılmış" ifadesi 0009'da koda yansımamıştı (kural yalnız sayaca
  EŞİTLİK arıyordu ve `netkar_app` sayacı serbestçe yazabiliyordu); 0010 bunu kapatır (aşağıda §4.2). Bileşik FK
  (`changed_by`, `tenant_id`) HATALI KODA karşı güvencedir (yanlış ya da başka kiracının kullanıcı kimliği
  yazılamaz); ELE GEÇİRİLMİŞ uygulama rolüne karşı değildir: `netkar_app` `memberships`'e satır ekleyebildiği için
  (davet akışı) başka kiracının kullanıcısına kendi kiracısında üyelik açıp `changed_by` olarak yazabilir (denetim
  PoC C). Bu risk bilinçli kabul edilmiştir: ek bir iz (üyelik satırı) bırakır ve rol ele geçirildiğinde tarihçe
  zaten yazılabilir bir alandır. İstenirse günlük tetikleyicisi `changed_by` üyeliğinin bu işlemde oluşturulmamış
  olmasını da arayabilir (yapılmadı).
  **Revizyon 3 (YK-03):** FK referans eylemi `NO ACTION` olduğundan günlükte kaydı olan kullanıcının üyeliği
  SİLİNEMEZ (her rol için `ForeignKeyViolation`; denetim PoC D). Bugün üyelik silen bir kod yolu yoktur. İleride üye
  çıkarma özelliği üyeliği silmemeli, pasifleştirmelidir (kimliksizleştirme ilkesi, §3). Kiracı imha (KVKK) akışı
  sırası: önce `profit_settings_changes` (ve gerekirse sürümlü tablolar, `DISABLE TRIGGER` deseniyle), SONRA
  `memberships`; ters sıra FK'ye takılır. Bu sıra imha runbook'una eklenmelidir.
- **YT-09:** `ck_profit_settings_changes_replace` yukarıdaki sıkı tanımla değiştirilir.
- **Geri alma:** tetikleyiciler, işlevler, FK ve indeksler düşer; kapanış işlevi 0008 gövdesine, kısıt 0008
  tanımına döner. Veri kaybı yoktur; test: downgrade, nesnelerin yokluğu, veri korunumu, upgrade.

### 4.2 Revizyon 3: migrasyon `0010_profit_settings_revision_xact.py` (revises `0009`; YK-01, YK-05)

Geri alınabilir ek migrasyon. Sorun: 0009 sıra kuralları satır sürümünün sayaca eşitliğine bakıyordu, sayacın bu
işlemde artırıldığına bakmıyordu; `netkar_app` sayacı geri sarıp geçmiş sürüme ya da sayaç artırılmadan yayımlanmış
sürüme satır ekleyebiliyordu (denetim PoC A ve B). Eklenenler:

- `profit_settings.revision_xact xid8`: sayacın son artırıldığı işlem. Sütunu istemci yazamaz; `BEFORE INSERT OR
  UPDATE` tetikleyicisi (`profit_settings_head_guard`) her rol için atar: satır yeniyse ya da sayaç değiştiyse
  `pg_current_xact_id()`, değilse eski değer (istemcinin gönderdiği değer yok sayılır).
- Tekdüzelik (yalnız `netkar_app`): INSERT'te sayaç 1; UPDATE'te sayaç ya aynı kalır ya +1 artar; azalma ve atlama
  `check_violation`. Sahip rol ve yönetici muaftır (veri doldurma ve düzeltme; tetikleyiciyi zaten kapatabilirler).
- 0009'un üç sıra kuralı (sürümlü tablolara ekleme, kapanış sürümü, günlük kaydı) ek olarak
  `revision_xact = pg_current_xact_id()` ister. Satır ancak sayacı BU işlemde artıran akışla yazılabilir.
- **Gerekçe (`xid8`):** `pg_current_xact_id()` en üst düzey işlem kimliğini döndürür; SAVEPOINT bunu değiştirmez, bu
  yüzden alt işlem kullanımı kuralı bozmaz (uygulama zaten SAVEPOINT/`begin_nested` kullanmaz). 64 bit olduğundan
  sarmalama sorunu yoktur. `now()` tabanlı bir bağ aynı işlemde ve eşzamanlı işlemlerde ayrım yapamazdı.
- Dürüst akış değişmez: `begin_write` kilitler, `finish_write` sayacı +1 yapıp flush eder, sonra satır, kapanış ve
  günlük gelir; aynı işlemde varsayılan desi için ikinci başlık UPDATE'i sürümü değiştirmediğinden bağ korunur.
- **YK-05 sertleştirmesi:** dört tetikleyici işlevine `SET search_path = pg_catalog, public` eklendi. İşlevler
  `SECURITY INVOKER` olduğundan çağıranın haklarıyla çalışır ve `search_path` ile yetki yükseltme riski yoktur
  (düşük risk); ek önlem 0006'daki `sync_gate` işlevleriyle tutarlılık ve ileriye dönük güvence içindir.
- **Geri alma:** tetikleyici, işlev ve sütun düşer; üç kural işlevi 0009 gövdesine döner; veri kaybı yoktur.
  Test: PoC A ve B reddi, dürüst akış geçişi, upgrade, downgrade, upgrade.
- **Kalan risk (kabul):** ele geçirilmiş `netkar_app` sayacı +1 artırıp aynı işlemde gerçek yazım akışını taklit
  edebilir; bu zaten meşru yazımdır (günlük ve sürüm sayacı tutarlı kalır). Sahip rol ve yönetici muafiyeti §4.1'deki
  gibidir.

**Revizyon 4 (11 Kasım 2026): migrasyon `0011_profit_settings_head_lockdown.py` (revises `0010`; ZK-01..ZK-04).**
Kapanış denetimi (`denetim_2026-11-11_0010_kapanis.md`) yukarıdaki "sayaç geri sarılamaz" iddiasının üç açığını
buldu; hepsi geri alınabilir yeni migrasyonla kapatıldı (0010 yayımlanmış sayıldığı için değiştirilmedi).

- **ZK-01 (düşük):** `netkar_app` `profit_settings` tablosunun tüm sütunlarını güncelleyebiliyordu; başlığın
  `marketplace_account_id` değerini aynı kiracıdaki başka hesaba çevirip hesaba yeni başlık (`revision = 1`) ekleyerek
  sayacı dolaylı olarak 1'e indirebiliyordu (yayımlanmış sürüm 1'e sahte satır ve günlük). Düzeltme: tablo düzeyi
  UPDATE geri alındı; yalnız uygulamanın gerçekten yazdığı `default_desi`, `revision`, `updated_by`, `updated_at`
  sütunlarına sütun düzeyi UPDATE verildi (kod doğrulaması: `begin_write` yalnız ekler ve `FOR UPDATE` ile kilitler,
  `finish_write` ve `write_default_desi` yalnız bu dört sütunu yazar; `SELECT ... FOR UPDATE` için tek sütunda UPDATE
  yetkisi yeterlidir). Derinlemesine savunma: `profit_settings_head_guard` `id`, `tenant_id`,
  `marketplace_account_id` değişimini HER rol için (sahip rol ve süper kullanıcı dahil) `check_violation` ile
  reddeder. Denetim PoC'u testle (InsufficientPrivilege) reddedilir; dürüst akış testleri geçer.
- **ZK-02 (bilgi):** "atlama reddedilir" yalnız deyim başınaydı; aynı işlemde sayaç istenen kadar artırılabiliyordu.
  Düzeltme: sayaç bu işlemde zaten artırılmışsa (`OLD.revision_xact = pg_current_xact_id()`) yeni artış reddedilir;
  yani uygulama rolü için işlem başına en fazla bir artış. Dürüst akış uyumludur: `finish_write` işlem başına bir kez
  artırır, başlığın yeni oluşturulduğu işlemde (`ticket.created`) hiç artırmaz.
- **ZK-03 (bilgi):** muafiyet "netkar_app dışındaki her rol" biçimindeydi. **Seçilen yön: olumlu liste.** Yalnız
  açıkça adlandırılmış bakım rolleri muaftır: `netkar_owner` ve süper kullanıcı (`profit_settings_maintenance_role()`
  yardımcı işlevi, dört kural işlevinde tek kaynak). Gerekçe: (1) varsayılan ret ("fail closed"): yazma yetkisi
  alan yeni bir rol (destek paneli, yönetim API'si, ayrı içe aktarma işçisi) hiçbir bakım yapılmadan kurallara tabi
  olur; ters yön ("kural netkar_app ve gelecekteki tüm uygulama rollerine") bir rol listesini sürekli güncel tutmayı
  ve unutulduğunda sessiz muafiyeti gerektirirdi; (2) muaf kümesi küçük, adlı ve denetlenebilir (sahip rol ve
  süper kullanıcı tetikleyiciyi zaten kapatabilir, bu yüzden bağlanmaları ek güvenlik katmaz); (3) `netkar_worker`
  bugün yalnız SELECT sahibidir, tabloya yazsaydı kurallar onu da bağlardı. Test: yazma yetkili rol kümesi tam
  olarak `{netkar_app, netkar_owner}` (yeni rol yetki alırsa kırılır), muaf küme `{netkar_owner} + süper kullanıcılar`,
  ve yazma yetkisi verilen varsayımsal bir rolün sıra kurallarına takıldığı.
- **ZK-04 (bilgi):** 0010 downgrade'i 0009 gövdelerini `importlib` ile dosyadan yüklüyordu (dosya adına ve sabit
  adlarına bağımlı). 0010 değiştirilmedi; 0011 downgrade'i 0010 gövdelerini kendi içinde METİN olarak taşır ve
  başka migrasyon dosyasına dayanmaz. Test `pg_get_functiondef` ile 0011, 0010 ve 0009 durumlarında dört işlevin
  tanımının beklenen sabitlerle eşit olduğunu doğrular.
- **ZK-05 (bilgi):** `earliest_order_day` için aynı kiracıda ikinci hesap senaryosu testi eklendi (kod değişmedi).
- **Geri alma:** dört işlev 0010 gövdelerine döner, yardımcı işlev düşer, sütun düzeyi UPDATE geri alınıp tablo
  düzeyi UPDATE verilir; veri kaybı yoktur. Test: upgrade, downgrade, upgrade gidiş-dönüşü.
- **Kalan risk (kabul):** ele geçirilmiş `netkar_app` hâlâ kendi hesabında işlem başına bir artış yapıp gerçek yazım
  akışını taklit edebilir (meşru yazımla aynıdır; sürüm ve günlük tutarlı kalır). Denetimin isteğe bağlı üçüncü
  önerisi (INSERT'te sürümlü tablo ya da günlükte satırı olan hesaba başlık eklemeyi reddetme) uygulanmadı: hesap
  anahtarı artık değiştirilemediği ve başlık silinemediği için geri sarma yolu kapalıdır.

## 5. API davranış değişikliği ve panel

### 5.1 Ayar API'si (`/v1/marketplace-accounts/{account_id}/profit-settings`)

| Uç | Önce (0007) | Sonra (0008) |
|---|---|---|
| `PUT /cargo-tariffs` | (anlaşma, firma, başlangıç) varsa yerinde günceller | Etkin aynı anahtarlı satır varsa onu kapatır (`degistirildi`) ve yeni satır ekler; yoksa ekler; birebir aynıysa hiçbir şey yazmaz |
| `PUT /service-fee-estimates` | başlangıç varsa yerinde günceller | Aynı (anahtar: başlangıç) |
| `PUT /variable-expenses/{id}` | yerinde günceller | Etkin satırı kapatır, yeni kimlikle yeni satır ekler (`replaces_id = id`) |
| `DELETE .../{id}` (üç kalem) | satırı kalıcı siler | Satırı `geri_cekildi` ile kapatır; satır tabloda kalır |
| `PUT /defaults` | yerinde günceller, iz yok | Yerinde günceller, önceki ve yeni değer günlüğe |
| `GET /profit-settings` | tüm satırlar | Yalnız etkin satırlar (biçim aynı) |
| `GET /profit-settings/history` | yok | Yeni: günlük, yeniden eskiye, imleçli (`cursor`, `limit` en çok 100); her kayıtta `revision`, `changed_at`, `changed_by` (kullanıcı kimliği ve görünen adı, üyeler listesindeki gibi; **Revizyon 1 (YT-08): uygulandığı biçim `{user_id, role}`, görünen ad yoktur.** Üyeler listesi (`/v1/tenant/members`) de ad ya da e-posta döndürmez ve kullanıcı satırları RLS ile yalnız kendine açıktır; ad eklemek görüntüleyiciye yeni kişisel veri açardı (KVKK en aza indirme). `role` bugünkü roldür, değişiklik anındaki rol değildir; **Revizyon 3 (YK-03): günlükte kaydı olan kullanıcının üyeliği silinemez (0009 bileşik FK, §4.1), bu yüzden `role` bugün `null` olamaz; üye çıkarma üyeliği pasifleştirerek yapılmalıdır. Eski ifade "üyelik silindiyse `null`" idi**), `item`, `action`, `affects_from`, `affects_past`, `past_change_confirmed`, `record` ve `replaced_record` (satırın tam içeriği: girilen ve KDV hariç değerler); varsayılan desi için önceki ve yeni değer. owner, admin, viewer; okuma sınırlayıcısını paylaşır (AD-02 sayacı) |

- **Onay alanı:** PUT ve POST gövdelerinde `confirm_past_change: bool = false`; DELETE'te aynı adlı sorgu
  parametresi (`expected_revision` kalıbı). K43'e göre geçmişi etkileyen ve ilk giriş istisnasına girmeyen yazım
  onaysızsa **409** `settings-past-change-unconfirmed`, gövde `{affects_from, affects_past: true,
  current_revision}`; işlem geri alınır (sürüm artmaz, günlük ve denetim kaydı yok). Kontrol sırası: rol ve hesap
  -> hız sınırı -> `begin_write` (kilit, `expected_revision`) -> işlem türü ve etki tarihi -> onay -> yazım ->
  günlük -> denetim -> commit.
  - **Revizyon 1 (YT-07, API değişikliği): onay etki tarihine bağlanır.** Çıplak `confirm_past_change` artık onay
    SAYILMAZ (alan geriye uyum için kabul edilir, karara etkisi yoktur; web istemcisi henüz bu uca bağlı değildir).
    İstemci 409 gövdesindeki `affects_from` değerini PUT/POST gövdesinde `confirm_affects_from` (YYYY-AA-GG) olarak
    geri gönderir; `affects_from` null ise (varsayılan desi) `all`. DELETE'te aynı adlı sorgu parametresi
    (`confirm_affects_from=2026-01-01` ya da `all`; geçersiz biçim 422; **Revizyon 3 (YK-04):** gövde alanı sorgu parametresiyle aynı katı desenle (`all` ya da tam `YYYY-AA-GG`) ayrıştırılır, saat dilimli tarih-saat ve sayısal zaman damgası dizgesi 422 `date_invalid` verir). Sunucunun hesapladığı etki tarihiyle
    eşleşmeyen ya da eksik onay (ilk giriş istisnası hariç) yeniden 409 `settings-past-change-unconfirmed` olur ve
    hiçbir şey yazılmaz; gövde sunucunun `affects_from` değerini taşır. İlk giriş istisnasında onay gerekmez ama
    gönderilmiş ve eşleşmeyen onay yine 409'dur; etki tarihi geçmiş değilse onay değerlendirilmez. Değişken gider
    değiştirmede beklenen değer eski ve yeni başlangıcın küçüğüdür. Panel her onaylı yazımda 409 gövdesindeki
    `current_revision`'ı `expected_revision` olarak da göndermelidir (araya giren başka yönetici değişikliği onayın
    dışında kalmasın, denetim AB-03).
  - **Revizyon 1 (YT-06): `GET /history` imleci mühürlüdür.** `next_cursor` opak bir dizgedir (AES-256-GCM,
    rapor uçlarının `CursorCodec` deseni; kiracı, hesap ve sorgu parmak izi `settings-history` AAD). İstek imleci
    bozuk, başka kiracı/hesap/sorguya ait ya da sürüm numarası geçersizse 422 `cursor_invalid` (`errors: [{field:
    "cursor", code: "cursor_invalid"}]`). Önceki düz tamsayı imleci kabul edilmez.
- **Kapanmış satıra yazım:** `PUT /variable-expenses/{id}` ya da `DELETE .../{id}` kapanmış satıra gelirse **409**
  `settings-record-ended`, gövde `{current_id}` (yerini alan etkin satır; geri çekilmişse `null`). Başka kiracının
  ya da hesabın kimliği yine 404.
  **Revizyon 1 (YT-02):** `current_id` halef zinciri tek özyinelemeli sorguyla bulunur ve `replaces_id` indekslidir;
  zincir 10.000 halkayı aşarsa `current_id` null döner.
- **Yazım yanıtları** (`TariffWriteOut`, `ServiceFeeWriteOut`, `ExpenseWriteOut`, `DeleteOut`, `DefaultsOut`) ek
  alanlar: `changed` (bool), `action` (`created` | `replaced` | `retracted` | `unchanged`), `replaced_id`,
  `affects_from`, `affects_past`. `created` bir sürüm boyunca korunur (`action == "created"` ile aynı).
- **Sürüm sınırları:** etkin satırları sayar (K42); değiştirme sınırı aşmaz.
- **Denetim izi:** eylem adları `<kalem>.create`, `<kalem>.replace`, `<kalem>.retract` (`upsert` ve `delete`
  yerine; mevcut önek aynı kalır), varsayılan desi `defaults.update`; değişmeyen yazım denetlenmez. Meta:
  `account_id`, `revision`, `record_id`, `replaced_id`, kaleme göre `agreement`, `carrier`, `valid_from` ya da
  `name`, `kind`, `valid_from`, `valid_to`; `affects_from`, `affects_past`, `past_change_confirmed`. `brackets`,
  `price`, `amount`, `amount_excl_vat`, `percent`, `default_desi` anahtarları **yoktur**.
- **Rapor API'si:** `summary`, ürün listesi, ürün ve sipariş kırılımı ile uyarılar yanıtlarına `settings_revision`
  (K44). `summary.totals`'ta `donem_net_kar` ve `satir_net_kar_toplami` `null` olabilir, `donem_eksik_giderler_haric_kar`
  eklenir (K39 Revizyon 1). `settings_revision` sorgu parametresiyle eski ayarla yeniden hesap P1.

### 5.2 Panel (denetim §7 kurallarına ekler; madde 2 ve 8'in yerine geçer)

**Rapor ekranı, dönem rakamı (denetim §7 madde 2 yerine):**
1. `net_kar_kismi = false`: başlık rakamı `donem_net_kar`, marj `net_kar_marji_yuzde`.
2. `net_kar_kismi = true`: başlıkta "Dönem net kârı hesaplanamadı" ve eksik kalem satır sayıları ("12 satırda
   kargo, 12 satırda hizmet bedeli tahmini eksik") + ayar sayfasına bağlantı. 0,00 asla yazılmaz.
3. Hemen altında "Eksik giderler hariç dönem kârı" = `donem_eksik_giderler_haric_kar`; etiket eksik kalemleri adıyla
   sayar ("kargo ve hizmet bedeli hariç"); "net kâr" kelimesi bu rakamın etiketinde geçmez. Değer < 0 ise "bilinen
   giderlerle bile zarar" vurgusu.
4. `tam_satirlar.satir_sayisi > 0` ise "Eksiksiz N satır" alt kartı: `tam_satirlar.net_kar` ve
   `tam_satirlar.net_kar_marji_yuzde`, "dönem giderleri hariç" etiketiyle. `satir_sayisi = 0` ise kart yoktur.
5. Şelale ve toplam gider: tam dönemde üst düzey alanlardan; kısmi dönemde `tam_satirlar` bloğundan, dönem düzeyi
   giderler (`donem_duzeyi_giderler`) ayrı satır.
6. Rapor alt bilgisi: "Ayar sürümü {settings_revision}"; ayar geçmişine bağlantı.

**Ayar ekranı (denetim §7 madde 8'e ek):**
1. Geçmişi etkileyecek yazımda (panel, `GET profit-settings` verisiyle K43'ü önceden hesaplar; sunucu 409 dönerse
   aynı pencere açılır) onay penceresi:
   - Başlık: "Geçmiş raporlar değişecek".
   - Metin (tarihli): "Bu değişiklik {affects_from, örn. 1 Ekim 2026} ve sonrasındaki siparişlerin kâr hesabını
     değiştirir. Daha önce indirdiğiniz ya da paylaştığınız raporlardaki rakamlar artık farklı olabilir. Önceki
     değer ayar geçmişinde saklanır."
   - Metin (varsayılan desi): "Siparişinde desi bilgisi olmayan tüm geçmiş siparişlerin kargo tahmini değişir."
   - Metin (geri çekme): "Bu sürüm geri çekilirse {tarih} sonrası siparişlerde kargo önceki sürümden ya da
     'diğer firmalar' tarifesinden hesaplanır; hiçbiri yoksa kargo 'eksik' görünür ve net kâr hesaplanamaz."
   - Düğmeler: birincil "Değişikliği uygula" (`confirm_past_change=true` ile yeniden gönderir); tarife, hizmet
     bedeli ve gider eklemede ikincil "Yalnız bugünden itibaren uygula" (başlangıcı bugün olan yeni sürüm olarak
     gönderir, onay gerekmez); "Vazgeç".
     **Revizyon 1 (YT-07):** "Değişikliği uygula" artık yalnız `confirm_past_change=true` göndermez; 409'daki
     `affects_from` değerini `confirm_affects_from` olarak (tarihsizde `all`), 409'daki `current_revision`'ı
     `expected_revision` olarak geri gönderir (§5.1 Revizyon 1).
     **Revizyon 2 (11 Kasım 2026, belge kayması düzeltmesi):** yukarıdaki "panel `GET profit-settings` verisiyle K43'ü
     önceden hesaplar" cümlesi uygulanmadı ve geçersizdir. Panel K43 etki tarihini (`affects_from`) önceden
     HESAPLAMAZ; karar sunucudadır: panel yazımı gönderir, geçmişi etkiliyorsa sunucunun 409
     `settings-past-change-unconfirmed` yanıtındaki `affects_from` (tarihsizde `all`) ile onay penceresini açar ve
     onaylanırsa aynı değeri `confirm_affects_from` olarak geri gönderir (istemci tarafı tarih hesabı sunucudaki
     kuralla ayrışabilirdi). İstisna geri çekmedir: DELETE'te istemci, sunucuyu beklemeden önce KENDİ onayını ister
     ("geri çekme" metni; önceki değer ayar geçmişinde kalır); ardından gönderilen DELETE de geçmişi etkiliyorsa
     sunucunun 409'u yine aynı akışla ikinci onayı ister.
2. "Ayar geçmişi" sekmesi: `GET /history`; her kayıt "{tarih saat}, {kişi}: Trendyol Express tarifesi
   (başlangıç 1 Ekim 2026) değiştirildi: 2 desi 54,00 -> 60,00 (KDV dahil)" biçiminde; fark `record` ve
   `replaced_record`'dan panelde hesaplanır; "geri çekildi" ve "geçmişi etkiledi (onaylı)" rozetleri.
3. 409 `settings-record-ended`: ekran yeniden yüklenir, "Bu kayıt başka bir değişiklikle güncellendi" bildirimi.

## 6. Rapor yeniden üretilebilirliği (K44)

Gerekli mi: **evet, damga olarak**. Her rapor yanıtı ve dışa aktarım `settings_revision` taşır; önbellek anahtarı
bunu zaten içermek zorundaydı (ADR-0006 §3.4). Maliyeti bir tamsayıdır, "rakam neden değişti" sorusunun ilk
adımıdır (iki raporun sürümleri farklıysa ayar geçmişinin o aralığına bakılır). Sürümle yeniden hesap (as-of)
yükleyicide P0 (değişmez satırlarla bedava gelir ve test edilir), API'de P1. **Sınır:** veri (sipariş, ekstre,
fatura, iade, maliyet) tasarım gereği değişir; tam yeniden üretim veri anlık görüntüsü ister, v1 kapsamı dışıdır.
Panel ayar sürümünü ve son senkron zamanını birlikte gösterir.

## 7. Açık sorular

1. **Avukat (KVKK):** değişmez satırlardaki ve günlükteki kullanıcı kimlikleri için hesap kapatmada kullanıcı
   satırının kimliksizleştirilmesi yeterli mi, yoksa `ON DELETE SET NULL` mı gerekir (§3)? Ayar tarihçesinin
   saklama süresi hesabın diğer verileriyle aynı olmalı mı?
   **Revizyon 1 (YT-05):** değişmezlik tetikleyicisi `ON DELETE SET NULL`'u engeller (§3 Revizyon notu); kimliksizleştirme
   bu yüzden öntanımlı yöntemdir ve sorunun cevabı `SET NULL` ise tetikleyici ayrıca değiştirilir.
2. **Ürün maliyeti (`product_costs`, K16):** maliyet kayıtları da yerinde güncelleniyor ve aynı AO-02 sorusu
   orada da var (maliyet en büyük gider kalemidir). K42'nin maliyete genişletilmesi ayrı karar; bu ADR kapsamı
   dışında, P0 kartına not.
3. **Müşavir ve Hasan:** docs/12 §9 madde 23 (kısmi dönem ekranının anlaşılırlığı), 24 (kilit beklentisi, geçmiş
   raporun aynen yeniden üretimi), 25 (düzeltme kaydı benzetmesi ve saklama), 26 (varsayılan desi tarihli mi).
   Madde 24'ün cevabı "kilit gerekir" ise seçenek (b) kullanıcı başlatmalı "dönem kapatma" olarak eklenir; bu ADR'nin
   veri modeli (sürüm aralıkları) bunu destekler.

## 8. Uygulama sırası ve kabul ölçütleri (kodu yazacak ajan)

Sıra docs/12 kuralı gereği: belge (bitti) -> betik (bitti) -> altın test (bitti) -> motor -> migrasyon -> servis
-> API -> panel.

1. **Motor, K39 Revizyon 1** (`results.py`, `aggregate.py`): `PeriodTotals.line_net_profit_total` ve
   `period_net_profit` `Decimal | None` (kısmi dönemde None); yeni `period_known_expenses_profit` (`wire
   ("donem_eksik_giderler_haric_kar")`) = Σ aktif satır `known_expenses_profit` - dönem düzeyi giderler; marj
   kuralı aynı. `tests/test_profit_golden.py` sayısı ve ad listesi 48 -> 49; `tests/test_golden_script_guard.py`
   sayısı 48 -> 49; `tests/test_profit_properties.py` I1-I6 (ayarlı ve ayarsız) ve "kısmi dönemde
   `donem_net_kar` null". `make test-profit` satır ve dal kapsamı %100.
2. **Rapor API'si, K39 Revizyon 1** (`profit_schemas.PeriodTotalsOut`): `period_net_profit` ve
   `line_net_profit_total` `Amount | None`, yeni alan; `profit_views`'te bu alanları kullanan yerler;
   `test_report_golden_api.py`, `test_feed_golden_database.py` 49 senaryoyla.
3. **Migrasyon 0008** (§4) ve model değişiklikleri (`updated_at` artık yazılmaz; `revision_from`, `revision_to`,
   `ended_*`, `end_reason`, `replaces_id`; `ProfitSettingsChange` modeli) ve migrasyon/RLS testleri.
4. **Servis** (`app/services/profit_settings.py`): `load_bundle` yalnız etkin satırlar (isteğe bağlı `at_revision`:
   sürümde etkin satırlar + günlükten varsayılan desi; `tasima` öncesi sürüm hata); `upsert_*` -> ekle / değiştir /
   değişmedi; `update_expense` -> değiştir; `delete_version` -> geri çek; sürüm sınırı sayımı etkin satırlar; K43
   etki tarihi, ilk giriş istisnası ve onay; günlük kaydı her yazımda aynı işlemde.
5. **API** (`app/api/v1/profit_settings.py`, şemalar): §5.1; denetim meta'sı; `GET /history`; rapor uçlarında
   `settings_revision`.
6. **Panel** (ayrı ajan, `apps/web`): §5.2.

**Kabul ölçütleri:**
- `cd netkar/services/api && uv run python ../../calisma_dosyalari/altin_test_hesap_ayarlar.py` "TAMAM" verir ve
  `--yaz` sonrası `git diff` `tests/golden/` altında boş kalır.
- 49 altın senaryo motorda ve API üzerinden kuruşu kuruşuna yeşil; `make test-profit` %100 satır ve dal.
- G01-G41 her senaryo `ProfitSettings()` ile çalıştırıldığında kısmi dönemde `donem_net_kar` ve
  `satir_net_kar_toplami` null, `donem_eksik_giderler_haric_kar` I5 ve I6'yı sağlar (özellik testi).
- Denetim PoC A.2'nin tersi: aynı anahtarlı PUT sonrası eski kademeler `GET /history`'de `replaced_record` olarak
  okunur ve eski satır tabloda `revision_to` doluyla durur; DELETE sonrası satır `end_reason = geri_cekildi` ile
  tabloda kalır ve motor onu kullanmaz; geriye tarihli yeni sürüm onaysız 409 alır.
- `netkar_app` rolüyle `DELETE FROM cargo_tariffs` ve iş alanı `UPDATE`'i yetki hatası; sahip rolle kapanmış satırın
  güncellenmesi tetikleyici hatası.
- Onaysız geçmişi etkileyen yazım: 409 `settings-past-change-unconfirmed`, `profit_settings.revision` değişmez,
  günlük ve `audit_log`'a kayıt düşmez. Onaylı: 200, günlükte `past_change_confirmed = true`.
- İlk giriş istisnası: ayarsız hesapta başlangıcı 2026-01-01 olan ilk Trendyol tarifesi ve ilk hizmet bedeli
  onaysız 200; ikinci Trendyol tarifesi (farklı firma, geçmiş başlangıç) onay ister; ilk değişken gider (geçmiş
  başlangıç) onay ister.
- Denetim meta'sı: silmede `agreement`, `carrier`, `valid_from`, `record_id` var; hiçbir yazımda tutar anahtarı yok.
- Aynı içerikli PUT: `changed = false`, `revision` değişmez, günlük ve denetim kaydı yok.
- Sürüm sınırı: 200 etkin tarife sürümü varken değiştirme 200, yeni ekleme 422.
- K44: `summary.settings_revision` = `profit_settings.revision` (ayarsız hesapta 0); bir ayar yazımından sonra
  artar. Yükleyici R sürümüyle çağrıldığında, R'den sonraki değişikliklere rağmen R anındaki summary ile kuruşu
  kuruşuna aynı sonucu verir (aynı sipariş verisiyle).
- 0008 upgrade/downgrade/upgrade: boş tabloda bayraksız geçer; tarihçe varken bayraksız durur, bayrakla etkin
  satırları koruyarak geri alır.
