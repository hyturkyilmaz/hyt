# ADR-0006: Kâr ayarları (kargo tarifesi, hizmet bedeli, değişken gider) ve eksik kalem davranışı

- Durum: Önerildi (alan tasarımı; uygulama P0 kartında, adım 2)
- Tarih: 9 Kasım 2026
- İlgili: `docs/12_kar_motoru.md` §8, §9 (madde 16-22), §12 (K33-K41); `docs/security/denetim_2026-11-09_S4_rapor.md`
  (Y-02, O-02, O-03, O-04, §7 panel sunum kuralları); ADR-0001 (RLS), ADR-0005 §7 (motor bağlantısı, `profit_settings_for`)
  ve §10 madde 8 (kiracı ayar tablosu sonraki tur); Trello kartı "[NetKâr] (P0) Kiracı kâr ayarları"; altın testler
  G42-G48 ve doğrulama betiği `calisma_dosyalari/altin_test_hesap_ayarlar.py`.

## 1. Bağlam

S4 rapor API'si her hesap için motor varsayılanı `ProfitSettings()` kullanıyor (`profit_settings_for`). Varsayılanda
kargo tarifesi boş, hizmet bedeli tahmini 0. Sonuç (denetim Y-02): faturası gelmemiş her satırda kargo 0 (`eksik`
ama net kâra 0 olarak karışıyor), hizmet bedeli 0 ("tahmini" etiketli, uyarısız); net kâr sistematik şişkin, dört
altın senaryoda zarar kâr görünüyor, ekstreli satırlarda K23 karşılaştırması 0 tahmini gerçek tahmin sayıp yanlış
`BEKLENMEYEN_KESINTI` üretiyor. Aynı kartta üç alan bulgusu daha var: kısmi dönem marjının karışık tabanı (O-02),
`basis` etiketinin kalem kaynaklarını yok sayması (O-03), claim'siz iadede maliyetin ayırt edilemeyen geçici durumu
(O-04).

İki ayrı soru vardır: (1) kullanıcının ayarlarını nerede, hangi biçimde tutacağız; (2) ayar (ya da maliyet) yokken
motor ne üretmeli. İkincisi birincisinden bağımsız olarak çözülmelidir: ayar tablosu gelse de yeni bağlanan her
hesap bir süre ayarsızdır.

## 2. Karar: motor davranışı (özet; kurallar docs/12 §12)

1. **Tanımsız 0 değildir (K33, K35).** Kullanıcı ayarlarının varsayılanı "tanımsız"dır. Motor `ProfitSettings()`
   ile hizmet bedeli tahmini `None`, tarife boş, varsayılan desi `None` alır. NetKâr Trendyol tarifesi ya da hizmet
   bedeli rakamı önermez (research/01'de kaynak yok).
2. **Eksik kalem (K37).** Kaynağı `eksik` olan kalem (ürün maliyeti, gönderi kargo, platform hizmet bedeli)
   `eksik_kalemler` listesine girer; satırın `net_kar`, `toplam_gider`, marjı null olur; bilinen giderlerle kâr ayrı
   alanda (`eksik_giderler_haric_kar`) verilir. Bilinen giderlerle zarar kesin zarardır (`ZARAR`).
3. **Uyarı kodları.** Mevcut `KARGO_TARIFESI_EKSIK` kalır; yeni satır kodları `HIZMET_BEDELI_TAHMINI_EKSIK`,
   `KARGO_DESI_VARSAYILAN` (bilgi), `IADE_KAYDI_BEKLENIYOR`; yeni dönem özet kodları `KARGO_EKSIK_SATIRLAR_VAR`,
   `HIZMET_BEDELI_EKSIK_SATIRLAR_VAR`, `IADE_KAYDI_BEKLENEN_SATIRLAR_VAR` (mevcut `MALIYET_EKSIK_SATIRLAR_VAR` kalıbı).
4. **K23 sıfır tahminle tetiklenmez (K38).** Tahmini tanımsız kalem karşılaştırmaya girmez; karşılaştırma bloğunda
   null'dır.
5. **Kısmi dönem (K39).** Dönem net kârı tam satırlardan; kısmi dönemde dönem marjı null; `tam_satirlar` bloğu
   kendi içinde tutarlı kırılım ve marj verir.
6. **Kesinlik (K40).** Motor satır, ürün ve dönem için `kesinlik` (`kesin`, `tahmini`, `eksik`, `iptal`/`yok`) üretir;
   API `basis`'i bu anlamda kullanmaz.
7. **Claim'siz iade (K41).** Maliyet ihtiyatla tam gider kalır, kaynak `tahmini`, uyarı ve askıdaki maliyet bilgisi.

### 2.1 Reddedilen alternatifler (motor)

| Alternatif | Neden reddedildi |
|---|---|
| Eksik kalemi 0 sayıp `net_kar`'ı `kismi=true` bayrağıyla döndürmek | Bayrağı okumayan her tüketicide (sıralama, zarar süzgeci, CSV, e-posta özeti, ileride uyarı motoru) sayı gerçek net kâr olur; Y-02'nin kendisi budur. Null hatayı görünür kılar, etiketli değer ayrı alanda kalır. K16 (maliyet) ile tutarlı |
| NetKâr'ın "ortalama" tarife ve hizmet bedeli tablosu sunması | Kaynak yok (research/01); uydurma rakam ürünün vaadini bozar; yanlış tahmin K23 uyarılarını da bozar |
| Ayarsız hesapta rapor uçlarını kapatmak (422) | Ayarsız hesapta da kesin kayıtlı satırlar (G48 satır 1) ve maliyet hariç katkı anlamlıdır; panel kurulum sihirbazıyla yönlendirir, veri saklanmaz |
| Claim'siz iadede "stoğa döndü" varsayımı | Kanıtsız maliyet düşürür, kusurlu iadede kârı şişirir (K41) |
| Kısmi dönemde marjı tüm satırların net satışına bölmek (v0.1) | Pay ve payda farklı satır kümelerinden (O-02) |

## 3. Karar: ayar verisi

### 3.1 Düzey ve kapsam
- **Hesap düzeyi** (`marketplace_account_id`), her satırda `tenant_id` (RLS). Gerekçe K33: kargo anlaşması ve hizmet
  bedeli Satıcı ID'ye bağlıdır; iki düzeyli birleştirme belirsizlik üretir.
- **Kullanıcı ayarları:** kargo tarifeleri (Trendyol anlaşmalı, satıcı anlaşmalı), varsayılan desi, hizmet bedeli
  tahmini, değişken giderler. **Sistem parametreleri** (KDV oranları, komisyon KDV varsayımı, stopaj, eşikler, KDV
  tespit toleransı) tabloda yoktur; kod sabitidir (`ProfitSettings` alan varsayılanları).
- **Geçerlilik tarihli:** tarife sürümü, hizmet bedeli sürümü, değişken gider (başlangıç + isteğe bağlı bitiş).
  Seçim sipariş gününe göre motorda yapılır (K33); API dönem için TÜM sürümleri yükler (dönem başından önceki son
  sürüm de gerekir; hacim küçüktür, süzme gerekmez).
- **KDV girişi:** tarife ve hizmet bedeli girildiği biçimde (`*_includes_vat` bayrağıyla) saklanır; motora verilirken
  K02 ile KDV hariçe çevrilir (sistem kargo/hizmet KDV oranıyla, tutar başına bir yuvarlama). Değişken gider KDV hariç
  + oran (K17).

### 3.2 Migrasyon taslağı (`0007_profit_settings.py`, revises `0006`)

Kalıp `0006` ile aynı: `_common(table)` (uuid PK, `tenant_id` FK `tenants`, `marketplace_account_id`, bileşik FK
`(marketplace_account_id, tenant_id) -> marketplace_accounts (id, tenant_id)`), `ENABLE` + `FORCE ROW LEVEL SECURITY`,
`tenant_isolation` politikası (`USING` ve `WITH CHECK`, `TENANT_EXPR`), para `numeric(18,6)`, oran `numeric(9,4)`.

```sql
-- Hesap başına tek satır: varsayılan desi ve ayar sürüm sayacı.
CREATE TABLE profit_settings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants (id),
    marketplace_account_id uuid NOT NULL,
    CONSTRAINT fk_profit_settings_account FOREIGN KEY (marketplace_account_id, tenant_id)
        REFERENCES marketplace_accounts (id, tenant_id),
    default_desi numeric(9,2) NULL CHECK (default_desi IS NULL OR (default_desi > 0 AND default_desi <= 1000)),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),   -- her ayar yazımında +1 (aynı işlemde)
    updated_by uuid NOT NULL REFERENCES users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_profit_settings_account UNIQUE (marketplace_account_id)
);

CREATE TABLE cargo_tariffs (
    <_common>,
    agreement text NOT NULL CHECK (agreement IN ('trendyol', 'seller')),
    carrier text NOT NULL CHECK (char_length(carrier) BETWEEN 1 AND 100 AND carrier = btrim(carrier)),
    valid_from date NOT NULL,
    price_includes_vat boolean NOT NULL,
    -- [{"max_desi": "2", "price": "54.00"}, ...] artan max_desi; tutarlar METİN (ADR-0005 order_lines.items kalıbı).
    brackets jsonb NOT NULL CHECK (jsonb_typeof(brackets) = 'array'
                                   AND jsonb_array_length(brackets) BETWEEN 1 AND 50),
    entered_by uuid NOT NULL REFERENCES users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_cargo_tariffs_version UNIQUE (marketplace_account_id, agreement, carrier, valid_from)
);

CREATE TABLE service_fee_estimates (
    <_common>,
    valid_from date NOT NULL,
    amount numeric(18,6) NOT NULL CHECK (amount >= 0 AND amount <= 10000),
    amount_includes_vat boolean NOT NULL,
    entered_by uuid NOT NULL REFERENCES users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_service_fee_estimates_version UNIQUE (marketplace_account_id, valid_from)
);

CREATE TABLE variable_expenses (
    <_common>,
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    kind text NOT NULL CHECK (kind IN ('siparis_basi', 'adet_basi', 'satis_yuzdesi')),
    amount_excl_vat numeric(18,6) NULL,
    percent numeric(9,4) NULL,
    vat_rate numeric(9,4) NOT NULL CHECK (vat_rate IN (0, 1, 10, 20)),
    valid_from date NOT NULL,
    valid_to date NULL CHECK (valid_to IS NULL OR valid_to >= valid_from),
    entered_by uuid NOT NULL REFERENCES users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_variable_expenses_kind_amount CHECK (
        (kind = 'satis_yuzdesi' AND percent IS NOT NULL AND percent > 0 AND percent <= 100
             AND amount_excl_vat IS NULL)
     OR (kind IN ('siparis_basi', 'adet_basi') AND amount_excl_vat IS NOT NULL
             AND amount_excl_vat >= 0 AND amount_excl_vat <= 100000 AND percent IS NULL))
);
```

- İndeksler: her tabloda `(tenant_id, marketplace_account_id)`.
- RLS: dört tabloda `ENABLE` + `FORCE` + `tenant_isolation` (0006 ile birebir).
- Yetkiler: `netkar_app` dört tabloda `SELECT, INSERT, UPDATE`; `cargo_tariffs`, `service_fee_estimates`,
  `variable_expenses` için ayrıca `DELETE` (yanlış sürümün silinmesi; `audit_log` kaydıyla). `profit_settings`'te
  `DELETE` yok. `netkar_worker` dördünde yalnız `SELECT` (ileride senkron sonrası uyarı üretimi için; yazamaz).
  `netkar_sync_gate` erişmez.
- Kod tarafı kontroller (CHECK ile ifade edilmeyenler, API'de 422): kademelerde kesin artan `max_desi`, `0 < max_desi
  <= 1000`, `0 <= price <= 100000`, en çok 2 ondalık; `carrier` kontrol karakteri içermez; `*` yalnız "diğer firmalar"
  anlamında; `valid_from` `2000-01-01`..bugün+366 gün (`product_costs.check_valid_from` yeniden kullanılır); hesap
  başına en çok 50 değişken gider, en çok 200 tarife sürümü, en çok 200 hizmet bedeli sürümü
  (`too_many_service_fee_versions`; denetim AO-01). Çok büyük JSON sayıları (`1e30`, 31 haneli tamsayı) 422
  `*_out_of_range` döner (AD-01).
- Geri alma (`downgrade`): yetkileri geri alır, dört tabloyu düşürür (yalnız bu migrasyonun verisi kaybolur; `CASCADE`
  yok). Tablolar kullanıcı beyanı veri (tarife, hizmet bedeli, gider) taşır ve Trendyol'dan yeniden çekilemez: tek
  satır bile varsa downgrade Türkçe bir hatayla DURUR; veri kaybı `NETKAR_ALLOW_SETTINGS_DATA_LOSS=1` ortam
  değişkeniyle bilerek kabul edilir (AD-03). Runbook: 0007 downgrade öncesi `pg_dump -t profit_settings -t cargo_tariffs
  -t service_fee_estimates -t variable_expenses` ya da tablo başına `\copy ... TO` yedeği.
- Migrasyon testi: `test_migrations.py` kalıbında upgrade/downgrade/upgrade; `test_rls_idor.py` kalıbında kiracılar
  arası okuma/yazma reddi (FORCE RLS ile sahip rolü dahil).

### 3.3 API (`/v1/marketplace-accounts/{account_id}/profit-settings`)

| Uç | Rol | Gövde / yanıt |
|---|---|---|
| `GET /profit-settings` | owner, admin, viewer | `revision`, `default_desi`, `cargo_tariffs[]` (girilen fiyat, `price_includes_vat`, hesaplanan KDV hariç fiyat), `service_fee_estimates[]` (girilen ve KDV hariç), `variable_expenses[]`, `completeness` (aşağıda) |
| `GET /profit-settings/carriers` | owner, admin, viewer | Son 92 günün siparişlerinde görülen `cargoProviderName` x anlaşma (`whoPays`) çiftleri, satır sayısı, bugün geçerli tarifeyle kapsanıyor mu |
| `PUT /profit-settings/cargo-tariffs` | owner, admin | `{agreement, carrier, valid_from, price_includes_vat, brackets: [{max_desi, price}]}`; (anlaşma, firma, başlangıç) ile upsert |
| `DELETE /profit-settings/cargo-tariffs/{id}` | owner, admin | sürümü siler |
| `PUT /profit-settings/service-fee-estimates` | owner, admin | `{valid_from, amount, amount_includes_vat}`; başlangıçla upsert |
| `DELETE /profit-settings/service-fee-estimates/{id}` | owner, admin | sürümü siler |
| `POST /profit-settings/variable-expenses`, `PUT .../{id}`, `DELETE .../{id}` | owner, admin | `{name, kind, amount_excl_vat \| percent, vat_rate, valid_from, valid_to}` |
| `PUT /profit-settings/defaults` | owner, admin | `{default_desi: string \| null}` |

- Yazma uçları: isteğe bağlı `expected_revision`; uyuşmazsa 409 `settings-revision-conflict` (iki yönetici aynı anda
  düzenlerse sessiz ezme yok). Her yazım aynı işlemde `profit_settings.revision`'ı artırır (satır yoksa oluşturur).
- Hız sınırı: maliyet yazma uçlarıyla aynı kiracı başına sınırlayıcı (ayrı sayaç havuzu, Y-01 düzeltmesi). Okuma
  uçları (`GET profit-settings`, `GET .../carriers`) kiracı başına dakikada `rate_limit_profit_settings_read_tenant`
  (varsayılan 120) isteğe sınırlıdır; iki uç aynı sayacı paylaşır, sayaç anahtarı yazma sayacından ayrıdır
  (`profit-settings-read:tenant:`); hesap yoksa 404 sayaca girmez (AD-02).
- Denetim izi: `record_audit(action="profit_settings.<kalem>.<upsert|delete>", target=<kayıt id>)`; tutarlar
  denetim kaydına yazılmaz (ticari bilgi, gereksiz). Log'a tutar yazılmaz.
- Hata kodları (422, alan adıyla): `brackets_not_increasing`, `desi_out_of_range`, `price_out_of_range`,
  `too_many_brackets`, `carrier_invalid`, `valid_from_out_of_range`, `valid_to_before_valid_from`,
  `amount_out_of_range`, `percent_out_of_range`, `vat_rate_invalid`, `kind_amount_mismatch`, `too_many_expenses`,
  `too_many_tariff_versions`, `too_many_service_fee_versions`.
  Gövde girdiyi yansıtmaz (S4 kalıbı). viewer yazarsa 403, başka kiracının hesabı 404.
- `completeness` (rapor `summary` yanıtına da eklenir):
  `{cargo_tariff_defined, seller_cargo_tariff_defined, service_fee_estimate_defined, variable_expenses_defined,
  default_desi_defined}`; "bugün geçerli bir sürüm var mı" anlamında. Eski `settings_configured` alanı bir sürüm
  boyunca `cargo_tariff_defined AND service_fee_estimate_defined` olarak korunur, sonra kaldırılır.

### 3.4 Motor bağlantısı
- `profit_settings_for(db, tenant_id, account_id) -> ProfitSettings`: dört tabloyu okuyup sürümlü `ProfitSettings`
  kurar; KDV dahil girişleri K02 ile çevirir (`split_inclusive` ile aynı yuvarlama). Hesap için hiç satır yoksa
  `ProfitSettings()` (tanımsız). Tek değişiklik noktası olarak kalır (ADR-0005 §7).
- Motor girdi modeli (öneri, adlar uygulayıcının): `CargoTariff.steps: Mapping[str, tuple[TariffVersion, ...]]`
  (`TariffVersion(valid_from: date | None, brackets)`) ve `lookup(carrier, desi, day)` (K34 sırası, `*` yedeği);
  `service_fee_estimates: tuple[DatedAmount, ...]` (boş = tanımsız; `estimated_service_fee_per_order_excl_vat`
  alanı kaldırılır ya da `None` varsayılanlı olur); `default_desi: Decimal | None = None`;
  `VariableExpense.valid_from/valid_to: date | None`. `schema_v1.parse_settings` golden README "Ayarlar bloğu"ndaki
  iki biçimi de okur (eski liste biçimi = başlangıçsız tek sürüm; `null` hizmet bedeli = tanımsız).
- Rapor önbelleği (denetim O-01 açık maddesi) gelince anahtar `profit_settings.revision`'ı içermelidir.

## 4. Sonuçlar
- Ayarsız hesapta panel hiçbir zaman şişkin net kâr göstermez; "eksik giderler hariç kâr" etiketiyle bilinen
  kısmı ve hangi kalemlerin eksik olduğunu gösterir. Y-02 yayın engeli motor tarafında kalkar.
- Ölçüm (`altin_test_hesap_ayarlar.py`): G01-G41 ayarsız çalıştırıldığında 57 aktif satırın 53'ü eksik kalemli
  olur ve net kârı null'dır (v0.1'de hepsi sayı veriyordu); yanlış `BEKLENMEYEN_KESINTI` 28 satırdan 0'a iner. 4 satır
  (G23) ayarsız hesapta da tamdır, çünkü tüm kalemleri kesin kayıttan gelir.
- G01-G41'in eski çıktısındaki tek değer değişikliği G29 dönem marjıdır (19,60 -> null); diğer tüm eski alanlar
  aynıdır, yeni alanlar eklenmiştir.
- Kullanıcı ilk raporda bir kurulum adımı görür (tarife ve hizmet bedeli). Bu bilinçli bir sürtünmedir.
- Kesinlik etiketi motor çıktısıdır; panel ve API aynı tanımı kullanır, `basis` yanıltıcı anlamını yitirir.

## 5. Panel ve rapor API'si (denetim §7 kurallarının yeni alanlarla karşılığı)
- `summary`: `completeness`, dönem `eksik_kalem_satir_sayilari`, `kesinlik`, `kesinlik_satir_sayilari`,
  `tam_satirlar`; `tariff_missing_line_count` = `eksik_kalem_satir_sayilari.kargo_gonderi` (sayım motordan).
- Ürün listesi: `certainty` (motor `kesinlik`), `statement_basis` (eski `basis`, bir sürüm boyunca `basis` adıyla da),
  `missing_items` (ürün `eksik_kalem_satir_sayilari` > 0 olan kalemler), `contribution_excl_missing`
  (`eksik_giderler_haric_kar`); `loss_reason` için ek değer `known_expenses` (net kâr null, eksik giderler hariç kâr
  < 0). `net_profit` sıralamasında null değerler sona;
  istisna (AD-04): net kârı null ama zararı kesin ürün (`loss_reason` dolu) eksik giderler hariç kâr değeriyle
  sıralanır, yani `asc`'de belirsiz null'lardan (eksik giderler hariç kâr >= 0) önce gelir; imleç anahtarı bu
  değerden türer. Ayrı bir `sort=contribution_excl_missing` alanı eklenmedi.
- Sipariş ve ürün kırılımı: satır `kesinlik`, `eksik_kalemler`, `iade_kaydi_bekleyen_adet`, `askidaki_urun_maliyeti`
  kablo adıyla aynen.
- Panel: kısmi dönemde dönem marjı gösterilmez, `tam_satirlar.net_kar_marji_yuzde` etiketiyle gösterilebilir;
  eksik kalem "eksik" yazılır, 0,00 yazılmaz; `IADE_KAYDI_BEKLENIYOR` satırında "stoğa dönerse" notu
  (`net_kar + askidaki_urun_maliyeti`).

## 6. Uygulama sırası ve kabul ölçütleri (kodu yazacak ajan)

Sıra docs/12 kuralı gereği: belge (bitti) -> betik (bitti) -> altın test (bitti) -> motor -> migrasyon -> API.

1. **Motor ayar modeli ve şema** (`settings.py`, `schema_v1.py`): sürümlü tarife ve hizmet bedeli, `default_desi`,
   değişken gider geçerliliği; `ProfitSettings()` = tanımsız. Golden README "Ayarlar bloğu"nun iki biçimi.
2. **Kargo ve hizmet bedeli** (`shipping.py`, `fees.py`): K34 seçimi (`*` yedeği, kademe aşımı eksik, varsayılan
   desi + `KARGO_DESI_VARSAYILAN`, `KARGO_DESI_FARKI` yalnız sipariş desisiyle); K35 tanımsız -> `eksik` +
   `HIZMET_BEDELI_TAHMINI_EKSIK`; tahmini değerler tanımsızken `None` (0 değil).
3. **Maliyet ve değişken gider** (`costs.py`): K36 geçerlilik; K41 koşulu, `tahmini` kaynak, bekleyen adet ve askıdaki
   maliyet.
4. **Satır** (`lines.py`, `results.py`, `enums.py`): `eksik_kalemler`, null kuralı, `eksik_giderler_haric_kar`,
   kesin zarar, K38 karşılaştırması (`LineComparison` tahmini alanları `Decimal | None`), `kesinlik` (teyit bekleyen
   satır `tahmini`), yeni uyarı kodları.
5. **Toplulaştırma** (`aggregate.py`, `results.py`): ürün ve dönem yeni alanları, `tam_satirlar`, kısmi marj null,
   dönem özet uyarıları.
6. **Testler:** `test_profit_golden.py` sayısı 41 -> 48; `test_profit_properties.py`'ye K39 özdeşlikleri (I1-I4) ve
   "eksik kalem varken net_kar null" özelliği; `test_profit_engine.py`'ye `teyit_bekliyor` satırında kesinlik
   `tahmini`, açıkça 0 hizmet bedeli tahmininin eksik sayılmaması ve K38'e girmesi, `*` yedeğinin firma sürümü
   gelecekteyken kullanılması; `make test-profit` satır ve dal kapsamı %100.
7. **Migrasyon 0007** ve RLS/IDOR testleri (§3.2).
8. **Ayar API'si** (§3.3) ve `profit_settings_for`'un DB'den okunması; KDV dahil giriş dönüşüm testi (54,00 -> 45,00;
   50,00 -> 41,67; hizmet bedeli 12,00 -> 10,00).
9. **Rapor API'si** (§5) ve `test_report_golden_api.py` / `test_feed_golden_database.py`'nin 48 senaryoyla geçmesi
   (`profit_settings_for` imzası değişirse testlerdeki `monkeypatch` güncellenir; G45'te `cargoDeci: null` senkron
   eşleyiciden geçmeli).

**Kabul ölçütleri (P0 kartının "bitti" tanımı ile):**
- `python3 netkar/calisma_dosyalari/altin_test_hesap_ayarlar.py` "TAMAM" verir ve `--yaz` sonrası `git diff`
  `tests/golden/` altında boş kalır (motor değil betik kaynaklıdır, el ile düzenleme yok).
- 48 altın senaryo motorda ve API üzerinden kuruşu kuruşuna yeşil; `make test-profit` %100 satır ve dal.
- G01-G41 her senaryo `ProfitSettings()` ile çalıştırıldığında: altın sonuçta olmayan `BEKLENMEYEN_KESINTI` yok;
  `eksik_kalemler` boş olmayan hiçbir satırda `net_kar` sayı değil; dönem `net_kar_kismi` doğruysa dönem marjı null
  (betiğin 5. adımının motor karşılığı, `tests/test_profit_properties.py`'ye eklenir).
- Ayar API'si: viewer yazamaz (403), başka kiracı 404, sınır dışı değerler 422 ve gövde girdiyi yansıtmaz, her yazım
  `revision`'ı artırır ve `audit_log`'a düşer; ayar yazımından sonraki `summary` yeni ayarla hesaplanır.
- Panel ayar eksikken net kârı "kargo ve hizmet bedeli hariç" etiketiyle gösterebilir: `summary.completeness` ve satır,
  ürün, dönem `eksik_kalemler` / `eksik_kalem_satir_sayilari` bunun için yeterlidir.

## 7. Açık sorular
docs/12 §9 madde 16-22 (tarife modeli ve desi aşımı, firma adı yazımı, hizmet bedeli yapısı, Return/claim sırası,
kısmi dönemde dönem düzeyi giderler, eksik kalemli nakit akışı sunumu, değişken giderde KDV dahil giriş). Hiçbiri
uygulamayı bloklamaz; cevap modeli değiştirirse önce docs/12, sonra betik, sonra altın test, en son kod.
