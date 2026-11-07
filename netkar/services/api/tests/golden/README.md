# Kâr motoru altın testleri

Bu klasördeki `G*.json` dosyaları NetKâr kâr motorunun (bkz. `netkar/docs/12_kar_motoru.md`) kuruşu kuruşuna
uyması gereken beklenen çıktılardır. Dosyaları elle düzenlemeyin; üreten betik:

```
python3 netkar/calisma_dosyalari/altin_test_hesap.py
```

Betik tüm `G*.json` dosyalarını silip yeniden yazar. Bir kural değişirse önce `12_kar_motoru.md`, sonra betik,
sonra bu dosyalar güncellenir; üçü aynı commit'te olmalı.

Tüm tutarlar kurgusaldır. Kargo tarifesi, platform hizmet bedeli tahmini ve ceza metinleri gerçek Trendyol
değerleri değildir; yalnız kuralı sınamak içindir.

## Motorun testte yapması gereken

1. `girdi` bloğunu (ayarlar dahil) motora ver.
2. Motor çıktısını `beklenen` ile karşılaştır: para alanları string, iki ondalık, birebir eşit olmalı
   (tolerans yok). Yüzde ve oranlar da iki ondalıklı string. `null` alanlar `null` olmalı.
3. `uyarilar` listeleri sıra önemsiz küme olarak karşılaştırılabilir; kodlar birebir aynı olmalı.
4. Motorun ürettiği ek alanlar karşılaştırmayı bozmaz; eksik alan hatadır.

## Dosya şeması (sema_surumu 1)

```
{
  "senaryo_id": "G01",
  "ad": "basit_satis_tahmini",
  "aciklama": "...",
  "kurallar": ["K02", ...],          // 12_kar_motoru.md kural kimlikleri
  "etiketler": [...],
  "sema_surumu": "1",
  "girdi": {
    "ayarlar": {...},                // varsayılanlarla birleştirilmiş tam ayar seti
    "donem": {"baslangic": "2026-10-01", "bitis": "2026-10-31"},
    "siparisler": [ShipmentPackage], // getShipmentPackages alt kümesi
    "urun_maliyetleri": [...],       // NetKâr kullanıcı verisi
    "urunler": [...],                // isteğe bağlı katalog (satışı olmayan ürünler)
    "settlements": [...],            // Cari Hesap Ekstresi settlements satırları
    "otherfinancials": [...],        // Cari Hesap Ekstresi otherfinancials satırları
    "kargo_faturalari": [...],       // cargo-invoice/{invoiceSerialNumber}/items
    "iadeler": [...],                // getClaims alt kümesi
    "reklam_kayitlari": [...]        // panel Excel'inden NetKâr iç şemasına aktarılmış satırlar
  },
  "beklenen": {
    "siparis_satirlari": [...],      // satır (lineId) bazında kâr kırılımı
    "urun_toplamlari": [...],        // barkod bazında
    "donem_toplami": {...},
    "kargo_faturasi_kdv_durumu": {"<invoiceSerialNumber>": "dahil" | "haric" | "bilinmiyor"}
  }
}
```

### Girdi alanlarının kaynağı

Trendyol alan adları resmi doküman kopyalarından alınmıştır (`netkar/docs/research/trendyol_docs_ham/pages/`):

| Blok | Trendyol alanları | Kaynak dosya |
|---|---|---|
| `siparisler[]` | `orderNumber`, `shipmentPackageId`, `orderDate` (ms), `status`, `cargoProviderName`, `cargoTrackingNumber`, `cargoDeci`, `whoPays`, `commercial`, `packageGrossAmount`, `packageSellerDiscount`, `packageTyDiscount`, `packageTotalDiscount`, `packageTotalPrice` | `docs__sipariş-paketlerini-çekme-getshipmentpackages.md`, `docs__sipariş-paketlerini-çekme-servisindeki-i̇ndirim-gösterimleri.md` |
| `siparisler[].lines[]` | `lineId`, `barcode`, `quantity`, `lineGrossAmount`, `lineSellerDiscount`, `lineTyDiscount`, `lineTotalDiscount`, `lineUnitPrice`, `vatRate`, `commission`, `discountDetails[]` (`lineItemId`, `lineItemPrice`, `lineItemSellerDiscount`, `lineItemTyDiscount`) | aynı iki dosya |
| `settlements[]` | `id`, `transactionDate`, `barcode`, `transactionType` (Türkçe metin), `receiptId`, `description`, `debt`, `credit`, `paymentPeriod`, `commissionRate`, `commissionAmount`, `commissionInvoiceSerialNumber`, `sellerRevenue`, `orderNumber`, `paymentOrderId`, `paymentDate`, `sellerId`, `orderDate`, `affiliate`, `shipmentPackageId` | `docs__cari-hesap-ekstresi-entegrasyonu.md`, `reference__getsettlements.md` |
| `otherfinancials[]` | aynı `FinancialTransaction` alanları; istek parametreleri `transactionType`, `transactionSubType=PlatformServiceFee` | `docs__cari-hesap-ekstresi-entegrasyonu.md`, `reference__getotherfinancials.md` |
| `kargo_faturalari[]` | `invoiceSerialNumber` (path), `items[]`: `shipmentPackageType`, `parcelUniqueId`, `orderNumber`, `amount`, `desi` | `docs__kargo-faturası-detayları.md`, `reference__getcargoinvoiceitems.md` |
| `iadeler[]` | `claimId`, `orderNumber`, `orderShipmentPackageId`, `items[].orderLine` (`barcode`, `price`, `vatRate`), `items[].claimItems[]` (`id`, `orderLineItemId`, `customerClaimItemReason.code`, `claimItemStatus.name`, `autoAccepted`, `acceptedBySeller`) | `docs__i̇adesi-oluşturulan-siparişleri-çekme-getclaims.md` |

Fixture'da Trendyol'un JSON number alanları string olarak yazılmıştır (ör. `"debt": "449.99"`); motor bunları
`Decimal(str)` ile okumalıdır, `float` asla.

### `netkar_` önekli alanlar (Trendyol alanı DEĞİL)

| Alan | Anlamı |
|---|---|
| `netkar_istek_tipi` | Satırın hangi `transactionType` isteğiyle çekildiği (ör. `Sale`). Yanıttaki `transactionType` Türkçe metindir ("Satış"); motor sınıflandırmayı istek tipine göre yapar (K05). |
| `netkar_istek_alt_tipi` | `transactionSubType` istek parametresi (`PlatformServiceFee`). |
| `netkar_sinif`, `netkar_kdv_orani` | NetKâr eşleme tablosunun `otherfinancials` satırına verdiği sınıf (`ceza`, `erken_odeme_bedeli`) ve KDV oranı (K14). Gerçek metinler pilot hesapla doğrulanacak. |
| `netkar_urun_desi` | Ürün kartındaki birim desi (kargo dağıtım ağırlığı, K09). |
| `netkar_urun_durumu` | Kullanıcının iade gelen kalem için işareti: `stoga_dondu` (varsayılan) veya `satilamaz` (K10). |
| `netkar_not_orderDate_iso` | Okunabilirlik için `orderDate`'in ISO karşılığı. |

### Beklenen: `siparis_satirlari[]`

| Alan | Açıklama |
|---|---|
| `durum` | `estimated`, `settled`, `adjusted`, `cancelled` (K22) |
| `adet`, `adet_iade` | Satır adedi ve kabul edilmiş iade kalemi sayısı |
| `kalemler` | Kâr kırılımı; satış alanları dışında hepsi KDV hariç gider: `brut_satis_kdv_dahil`, `satici_indirimi_kdv_dahil`, `trendyol_indirimi_kdv_dahil` (bilgi), `satis_kdv_dahil`, `satis_kdv_haric`, `iade_kdv_dahil`, `iade_kdv_haric`, `net_satis_kdv_haric`, `urun_maliyeti`, `komisyon`, `kargo_gonderi`, `kargo_iade`, `platform_hizmet_bedeli`, `ceza`, `reklam`, `degisken_giderler`, `toplam_gider`, `maliyet_haric_katki`, `net_kar`, `net_kar_marji_yuzde` |
| `kdv` | `satis_kdv`, `iade_kdv`, `komisyon_kdv`, `kargo_kdv`, `platform_hizmet_bedeli_kdv`, `ceza_kdv`, `urun_maliyeti_kdv`, `degisken_giderler_kdv`, `reklam_kdv`, `kdv_etkisi` (K20) |
| `nakit_akisi` | `trendyol_hakedis`, `fatura_kesintileri_kdv_dahil`, `stopaj`, `beklenen_net_tahsilat` (K21) |
| `kaynaklar` | Her kalemin kaynağı: `kesin`, `kesin_dagitim`, `tahmini`, `kullanici`, `eslesen`, `dagitim_tahmini`, `eksik`, `yok` |
| `degisken_gider_detayi`, `reklam_detayi` | Dağıtılan kalemlerin kayıt bazında dökümü |
| `karsilastirma` | Yalnız ekstre gelmiş satırlarda: tahmini ve kesin komisyon, gönderi kargo, hizmet bedeli; fark ve eşik (K23) |
| `uyarilar` | `MALIYET_EKSIK`, `ZARAR`, `KARGO_DESI_FARKI`, `BEKLENMEYEN_KESINTI`, `KOMISYON_ORANI_FARKLI`, `EKSTRE_IC_TUTARSIZLIK`, `ESLESMEMIS_HAKEDIS_DUZELTMESI`, `KARGO_FATURASI_KDV_BELIRSIZ`, `KARGO_TARIFESI_EKSIK` |

`urun_maliyeti` yoksa `urun_maliyeti`, `toplam_gider`, `net_kar`, `net_kar_marji_yuzde` `null` olur;
`maliyet_haric_katki` yine hesaplanır.

### Beklenen: `urun_toplamlari[]` ve `donem_toplami`

Ürün toplamları satırların yuvarlanmış değerlerinin toplamıdır (yeniden hesaplanmaz). Ek alanlar:
`reklam_satissiz`, `reklam_harcamasi`, `reklam_cirosu`, `roas`, `basabas_roas`, `maliyet_eksik`, `stopaj`.
Dönem toplamı ayrıca `donem_duzeyi_giderler` (satışsız ürün reklamı, dağıtılamayan reklam, sipariş bağsız ceza,
erken ödeme bedeli, sınıflandırılmamış kesinti), `donem_net_kar`, `net_kar_kismi`, `kdv_etkisi`, `nakit_akisi`
(`stopaj_hesaplanan`, `stopaj_ekstre`, `erken_odeme_nakit_girisi`) ve dönem uyarılarını (`SINIFLANDIRILMAMIS_KESINTI`,
`MALIYET_EKSIK_SATIRLAR_VAR`, `STOPAJ_EKSTRE_FARKI`) taşır. İptal satırları ürün ve dönem toplamlarına girmez.

## Senaryo listesi (41)

| Kimlik | Dosya | Kurallar | Etiketler | Beklenen durum ve satır net kârı |
|---|---|---|---|---|
| G01 | `G01_basit_satis_tahmini.json` | K02, K04, K06, K07, K08, K13, K16, K22 | basit_satis, estimated | estimated 119.09 |
| G02 | `G02_basit_satis_kesin.json` | K04, K05, K06, K07, K08, K22, K23, K27, K28 | basit_satis, settled, komisyon_kdv | settled 119.09 |
| G03 | `G03_satici_indirimi_tahmini.json` | K03, K04, K06 | satici_indirimi, estimated | estimated 28.29 |
| G04 | `G04_satici_indirimi_kesin_net_sale.json` | K03, K04, K05, K06 | satici_indirimi, settled | settled 28.29 |
| G05 | `G05_satici_indirimi_kesin_brut_sale_discount.json` | K04, K05, K06, K28 | satici_indirimi, settled, isaret_kurali | settled 28.29 |
| G06 | `G06_trendyol_karsilamali_indirim.json` | K03, K04, K06 | trendyol_indirimi, settled | settled 51.67 |
| G07 | `G07_birlesik_indirim_tahmini.json` | K03, K04, K06 | satici_indirimi, trendyol_indirimi, estimated | estimated 81.00 |
| G08 | `G08_cok_adetli_satir.json` | K03, K04, K16, K27 | cok_adet, settled | settled 48.12 |
| G09 | `G09_kdv_yuzde_10.json` | K02, K07, K20 | kdv_orani, estimated | estimated 28.33 |
| G10 | `G10_kdv_yuzde_1.json` | K02, K20 | kdv_orani, estimated | estimated 13.22 |
| G11 | `G11_cok_satirli_karma_kdv_komisyon.json` | K06, K07, K09, K24 | komisyon_kdv, kdv_orani, settled | settled 139.58 / 62.62 / 53.45 |
| G12 | `G12_komisyon_kdv_haric_varsayimi.json` | K07 | komisyon_kdv, settled, ayar | settled 106.59 |
| G13 | `G13_kargo_desi_farki.json` | K08, K23 | kargo_desi, beklenmeyen_kesinti, settled | settled 104.09 |
| G14 | `G14_kargo_faturasi_kdv_haric_tespiti.json` | K08 | kargo_kdv, settled | settled 119.09 |
| G15 | `G15_kargo_desi_agirlikli_dagitim.json` | K08, K09, K24 | kargo_dagitim, estimated | estimated 103.86 / 63.50 |
| G16 | `G16_tam_iade_stoga_donen.json` | K05, K10, K12, K22 | tam_iade, iade_kargo, adjusted, negatif_kar | adjusted -100.00 |
| G17 | `G17_tam_iade_urun_satilamaz.json` | K10, K16 | tam_iade, adjusted, negatif_kar | adjusted -280.00 |
| G18 | `G18_kismi_iade_manualrefund.json` | K05, K11 | kismi_iade, adjusted | adjusted 48.26 |
| G19 | `G19_cok_adetten_bir_iade.json` | K10, K12, K16 | kismi_iade, cok_adet, iade_kargo, adjusted | adjusted -7.65 |
| G20 | `G20_kismi_iade_sonra_tam_iade.json` | K05, K10, K11 | kismi_iade, tam_iade, adjusted, isaret_kurali | adjusted -100.00 |
| G21 | `G21_ceza_siparise_bagli.json` | K14, K22, K24 | ceza, adjusted | adjusted 109.39 / 73.87 |
| G22 | `G22_ceza_bagsiz_ve_siniflandirilmamis.json` | K14, K25 | ceza, donem, siniflandirilmamis | settled 119.09 (dönem -98.26) |
| G23 | `G23_platform_hizmet_bedeli_dagitimi.json` | K13, K24 | hizmet_bedeli, dagitim, settled | settled 117.98 / 94.01 / 70.72 / 27.22 |
| G24 | `G24_reklam_eslenen.json` | K15, K25 | reklam_eslenen, estimated, roas | estimated 79.09 / 208.19 |
| G25 | `G25_reklam_eslenmeyen_dagitim.json` | K15, K24 | reklam_eslenmeyen, estimated | estimated 86.49 / 41.34 / 8.76 |
| G26 | `G26_reklam_satissiz_urun.json` | K15, K25 | reklam_eslenen, reklam_eslenmeyen, donem | estimated 106.59 (dönem 26.59) |
| G27 | `G27_beklenmeyen_kesinti_komisyon_orani.json` | K22, K23 | estimated_settled_fark, beklenmeyen_kesinti | settled 106.59 |
| G28 | `G28_fark_esik_alti.json` | K23 | estimated_settled_fark, settled | settled 119.05 |
| G29 | `G29_maliyet_girilmemis.json` | K16, K25 | maliyet_eksik, estimated | estimated 138.80 / null |
| G30 | `G30_maliyet_gecerlilik_tarihi.json` | K16 | maliyet_tarihli, estimated | estimated 129.09 / 109.09 |
| G31 | `G31_sifir_kar.json` | K25 | sifir_kar, estimated | estimated 0.00 |
| G32 | `G32_negatif_kar_ucuz_urun.json` | K25 | negatif_kar, estimated | estimated -35.06 |
| G33 | `G33_yuvarlama_sinir_yarim_kurus.json` | K01, K02, K24 | yuvarlama, estimated | estimated -4.81 / -14.44 |
| G34 | `G34_yuvarlama_dagitim_en_buyuk_kalan.json` | K01, K24 | yuvarlama, dagitim, estimated | estimated 24.15 / 24.17 / 24.17 |
| G35 | `G35_stopaj_nakit_akisi.json` | K18, K21 | stopaj, settled | settled 119.09 / 64.17 |
| G36 | `G36_degisken_giderler.json` | K17, K24 | degisken_gider, estimated | estimated 105.33 / 86.40 |
| G37 | `G37_erken_odeme.json` | K19, K25 | erken_odeme, donem, settled | settled 119.09 (dönem 19.09) |
| G38 | `G38_iptal_siparis.json` | K26 | iptal | cancelled 0.00 |
| G39 | `G39_satici_anlasmali_kargo.json` | K08, K21 | kargo_satici_anlasmasi, settled | settled 126.09 |
| G40 | `G40_komisyon_duzeltme_kaydi.json` | K05, K22, K23 | isaret_kurali, adjusted | adjusted 114.93 |
| G41 | `G41_eslesmemis_hakedis_duzeltmesi.json` | K05, K22 | isaret_kurali, adjusted | adjusted 135.76 |

### İstenen kapsamın eşlemesi

| Konu | Senaryolar |
|---|---|
| Basit satış | G01, G02 |
| Satıcı indirimi | G03, G04, G05, G07 |
| Trendyol karşılamalı indirim | G06, G07 |
| Çok adetli satır | G08, G19, G24 |
| KDV %1 / %10 / %20 | G10 / G09 / G01; karma G11 |
| Komisyon KDV'si | G02, G11, G12 |
| Kargo desi farkı | G13 (ayrıca KDV tespiti G14, dağıtım G15, satıcı anlaşması G39) |
| Tam iade / kısmi iade | G16, G17 / G18, G19, G20 |
| İade kargo bedeli | G16, G17, G19, G20 |
| Ceza kesintisi | G21, G22 |
| Platform hizmet bedeli dağıtımı | G23 (tahmini her estimated senaryoda) |
| Reklam eşlenen / eşlenmeyen | G24, G26 / G25, G26 |
| estimated -> settled farkı, beklenmeyen kesinti | G13, G27 (uyarı), G28, G40 (eşik altı) |
| Maliyeti girilmemiş ürün | G29 |
| Sıfır / negatif kâr | G31 / G16, G17, G19, G32, G33 |
| Yuvarlama sınır vakaları | G33, G34 |
| Stopajın nakit akışına yansıması | G35 (her senaryoda `nakit_akisi.stopaj`) |
| Ek | Maliyet geçerlilik tarihi G30, değişken giderler G36, erken ödeme G37, iptal G38, ekstre düzeltmeleri G40, G41 |
