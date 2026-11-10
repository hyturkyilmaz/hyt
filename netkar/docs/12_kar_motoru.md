# NetKâr · Kâr Motoru Kuralları (v0.3, 10 Kasım 2026)

Sahibi: kâr motoru alan modelcisi (docs/40_ajan_promptlari.md §3.2).
Özet: docs/10_mimari.md §4. Altın testler: `services/api/tests/golden/` (49 senaryo), üreten ve doğrulayan
betik: `calisma_dosyalari/altin_test_hesap_ayarlar.py` (K01-K41, K39 Revizyon 1; K01-K32 hesap yardımcılarını ve G01-G41
tanımlarını `calisma_dosyalari/altin_test_hesap.py`'den alır; o betik artık tek başına çalıştırılmaz, çünkü
tüm `G*.json` dosyalarını silip yalnız G01-G41'i eski kurallarla yazar).

v0.2 değişikliği: kâr ayarları ve eksik kalem kuralları (§12, K33-K41; denetim S4 Y-02, O-02, O-03, O-04,
karar kaydı `docs/adr/0006-kar-ayarlari.md`). Mevcut kural numaraları değişmedi.

v0.3 değişikliği (10 Kasım 2026, denetim `docs/security/denetim_2026-11-09_kar_ayarlari.md` AO-02, AO-03; karar
kaydı `docs/adr/0007-ayar-tarihcesi-ve-donem-rakami.md`): **K39 Revizyon 1** (kısmi dönemde `donem_net_kar` ve
`satir_net_kar_toplami` null, yeni `donem_eksik_giderler_haric_kar`, özdeşlikler I1-I6) ve yeni kurallar **K42**
(ayar kayıtlarının değişmezliği ve tarihçesi), **K43** (geçmişi etkileyen ayar değişikliği), **K44** (rapor ayar
damgası). Altın test G49 eklendi; G01-G48'de değişen eski değerler K39 Revizyon 1'de listelidir. Mevcut kural
numaraları değişmedi.

> **Uyarı:** Bu belge mali müşavirlik görüşü değildir. "Güven" sütunu Düşük ya da Doğrulanmadı olan her kural
> §9'daki teyit listesine bağlıdır. Teyit sonucu değişirse önce bu belge, sonra betik, sonra altın testler
> güncellenir; motor kodu en son değişir.

Güven ölçeği (01_trendyol_api.md ile aynı): **Yüksek** resmi doküman ya da mevzuat metninde birebir; **Orta**
resmi kaynaktan çıkarım veya tutarlı ikincil kaynaklar; **Düşük** tek kaynak ya da yorum; **Doğrulanmadı**
kaynak yok, pilot hesap ya da müşavir gerekir.

Kaynak kısaltmaları (hepsi `docs/research/trendyol_docs_ham/pages/` altında):
- **[CHE]** `docs__cari-hesap-ekstresi-entegrasyonu.md` (settlements, otherfinancials, payment-order, işaret tabloları)
- **[SET]** `reference__getsettlements.md`, **[OTH]** `reference__getotherfinancials.md`
- **[IND]** `docs__sipariş-paketlerini-çekme-servisindeki-i̇ndirim-gösterimleri.md`
- **[PKG]** `docs__sipariş-paketlerini-çekme-getshipmentpackages.md`, **[PKGR]** `reference__getshipmentpackages.md`
- **[KRG]** `docs__kargo-faturası-detayları.md`, **[KRGR]** `reference__getcargoinvoiceitems.md`
- **[CLM]** `docs__i̇adesi-oluşturulan-siparişleri-çekme-getclaims.md`
- **[TAZ]** `docs__tazmin-entegrasyonu.md`, **[CHG]** `changelog__changelog.md`
- **[API]** `docs/research/01_trendyol_api.md`, **[HUK]** `docs/research/03_hukuk_ve_uyum.md`, **[GTM]** `docs/research/05_pazarlama_gtm.md`

---

## 1. Özet: tek satırlık formül

Sipariş satırı (`lineId`) başına, tüm giderler KDV hariç:

```
net_satis_kdv_haric = satis_kdv_haric - iade_kdv_haric
net_kar = net_satis_kdv_haric
        - urun_maliyeti - komisyon - kargo_gonderi - kargo_iade
        - platform_hizmet_bedeli - ceza - reklam - degisken_giderler
maliyet_haric_katki = net_kar + urun_maliyeti        (maliyet yoksa da hesaplanır)
```

KDV ve %1 stopaj kâra girmez; ayrı `kdv` ve `nakit_akisi` bloklarında gösterilir (K18, K20, K21).

Sayısal referans (altın test G01, tahmini): 499,90 TL KDV dahil, %20 KDV, %15 komisyon, maliyet 180,00:

| Kalem | Tutar |
|---|---|
| Satış KDV hariç | 416,58 |
| Ürün maliyeti | -180,00 |
| Komisyon (74,985 KDV dahil) | -62,49 |
| Gönderi kargo (desi 2 tarifesi) | -45,00 |
| Platform hizmet bedeli (ayar) | -10,00 |
| **Net kâr** | **119,09** (marj %28,59) |
| KDV etkisi (83,32 - 12,50 - 9,00 - 2,00 - 36,00) | 23,82 (bilgi) |
| Stopaj (416,58 x %1) | 4,17 (nakit) |

---

## 2. Kavramlar

| Kavram | Tanım | Trendyol alanı (kaynak) |
|---|---|---|
| Brüt satış | İndirimsiz birim fiyat x adet, KDV dahil. Satır alanları (`lineSellerDiscount`, `lineTyDiscount`) birim **ortalamasıdır**; kalem bazında gerçek değer `discountDetails[]` içindedir. Motor tutarları daima `discountDetails` toplamından alır. | `lines[].lineGrossAmount`, `quantity`, `discountDetails[]` ([IND], [PKG]) |
| Satıcı indirimi | Satıcının karşıladığı indirim; satıcı gelirini ve komisyon matrahını düşürür. | `lineItemSellerDiscount`; ekstrede `Discount`, `Coupon` ([IND], [CHE]) |
| Trendyol karşılamalı indirim | Trendyol'un karşıladığı kupon/kampanya. Kılavuz: "satıcıya yansıtılmaz". Müşterinin ödediğini düşürür, satıcı gelirini düşürmez. NetKâr'da yalnız bilgi kalemi. | `lineItemTyDiscount`, `packageTyDiscount` ([IND]) |
| Müşterinin ödediği | `lineItemPrice = lineGrossAmount - lineItemSellerDiscount - lineItemTyDiscount` | [IND] "Temel Kural" |
| Satış (gelir tabanı) | `brüt - satıcı indirimi`, KDV dahil. Kesinleşince ekstre satırlarının `credit - debt` toplamı. | K04 |
| KDV dahil / hariç | Türkiye'de pazaryeri fiyatları KDV dahildir. Kâr hesabı KDV hariç yapılır; dönüşüm K02. | `lines[].vatRate` ([PKG]) |
| Komisyon matrahı | Satıcının satış tutarı (KDV dahil, satıcı indirimi düşülmüş). | `commission` (oran, sipariş), `commissionRate`, `commissionAmount` (ekstre) |
| Komisyon KDV'si | Trendyol'un komisyon faturasındaki %20 KDV; satıcı için indirilecek KDV, gider değil. | K07 |
| Platform hizmet bedeli | Trendyol'un hizmet faturası; fatura düzeyinde gelir, sipariş kırılımı belgelenmemiş. | `otherfinancials`, `DeductionInvoices` + `transactionSubType=PlatformServiceFee` ([CHE]) |
| Gönderi / iade kargo bedeli | Trendyol anlaşmalı kargoda kargo faturası kalemleri, sipariş numarası ve desi ile. | `cargo-invoice/{invoiceSerialNumber}/items`: `shipmentPackageType`, `orderNumber`, `amount`, `desi` ([KRG]) |
| Desi | Tahminde siparişteki `cargoDeci` ("Bu bilgi sonradan değişebilmektedir"), kesinde faturadaki `desi`. | [PKG], [KRG] |
| İade | `Return` (tam), `ManualRefund` (kısmi), `ManualRefundCancel` (kısmi iadenin iptali). Komisyon iade satırında geri yazılır. | [CHE] |
| Geri alınamayan bedeller | İadede gönderi kargo, iade kargo, platform hizmet bedeli (teyit), paketleme. | K10 |
| Reklam | API yok; panel Excel'i yüklenir, barkodla eşlenir; eşlenemeyen satışa oranla dağıtılır ve "tahmini" etiketlenir. | [API] §2.4e |
| Ceza / tazmin | Ceza için ayrı tip yok; `DeductionInvoices` veya `FinancialItem` altında olası. Tazmin (TEX) gelir. | [CHE], [TAZ] |
| Erken ödeme | `CashAdvance` nakit girişidir; bedeli ayrı satırda (doğrulanmadı). | [CHE] |
| E-ticaret stopajı | %1 gelir/kurumlar vergisi tevkifatı; peşin ödenen vergi, gider değil. | `otherfinancials` `Stoppage` ([CHE], [CHG] 27.12.2024) |
| Ürün maliyeti | Kullanıcı girer; KDV hariç birim maliyet, alış KDV oranı, geçerlilik başlangıç tarihi. | NetKâr verisi |
| Değişken gider | Kullanıcı tanımlı: sipariş başı, adet başı, satış yüzdesi. | NetKâr verisi |

---

## 3. Para kuralları (K01, K02, K24)

### K01 · Sayı türü ve yuvarlama
- **Formül:** Tüm para `Decimal`; girdi `Decimal(str(x))` ile okunur, `float` yasak (JSON number da önce stringe).
  Kuruşa yuvarlama `quantize(Decimal("0.01"), ROUND_HALF_UP)`; Python'da HALF_UP negatiflerde sıfırdan uzağa
  yuvarlar (-0,005 -> -0,01). Yüzde ve oranlar da iki ondalık, HALF_UP.
- **Ne zaman yuvarlanır:** Her **kalem, satır sonunda bir kez** yuvarlanır. Ara adımlar tam hassasiyette kalır
  (ör. ekstredeki `commissionAmount` 4 ondalıklı gelir: 67,4985). Satırın `net_kar`ı yuvarlanmış kalemlerin
  farkıdır; ürün ve dönem toplamları yuvarlanmış satır değerlerinin toplamıdır, yeniden hesaplanmaz.
- **Gerekçe:** (1) Kullanıcı ekranda kalemleri topladığında net kârı kuruşu kuruşuna bulmalı; toplamda yeniden
  hesaplamak "kayıp kuruş" üretir. (2) Kalem (adet) bazında yuvarlamak çok adetli satırda hatayı büyütür:
  3 x 12,03 satırında birim bazında 3 x 10,03 = 30,09, satır sonunda 36,09 / 1,20 = 30,075 -> 30,08 (G33).
  (3) Trendyol ekstresi satır (barkod) düzeyinde ve 4 ondalık taşıdığı için satır sonu yuvarlama ekstreyle
  mutabakatı en az farkla verir. (4) HALF_UP, Türkiye'de fatura ve muhasebe yazılımlarında yaygın kuraldır;
  banker yuvarlaması (HALF_EVEN) 10,025'i 10,02 yapar, kullanıcıya "hatalı" görünür.
- **Örnek:** 12,03 / 1,20 = 10,025 -> 10,03 (G33 satır 1). Maliyet 3,335 x 3 = 10,005 -> 10,01 (G33 satır 2).
- **Kaynak:** Tasarım kararı; KDV tutarlarının kuruş yuvarlaması için genel muhasebe uygulaması.
- **Güven:** Yüksek (iç kural). Ekstrenin kendi yuvarlama yöntemi Doğrulanmadı (§9 madde 9).

### K02 · KDV dahil / hariç dönüşümü
- **Formül (dahilden):** `haric = rnd(dahil_exact / (1 + r/100))`, `kdv = rnd(dahil_exact) - haric`.
  Böylece `rnd(dahil) = haric + kdv` her zaman tutar.
- **Formül (hariçten):** `haric = rnd(haric_exact)`, `kdv = rnd(haric_exact x r/100)`.
- **Hangi oran:** Satış ve iade için satırın `vatRate`'i; komisyon, kargo, platform hizmet bedeli, reklam için
  ayarlardaki oran (varsayılan %20, genel oran); ürün maliyeti için maliyet kaydındaki alış KDV oranı.
  Geçerli oranlar %1, %10, %20 (Trendyol 10.07.2023 duyurusu: "KDV oranları %10 ve %20 olarak güncellenmiştir").
- **Örnek:** 499,90 -> 416,58 + 83,32 (G01); 275,00 %10 -> 250,00 + 25,00 (G09); 180,00 %1 -> 178,22 + 1,78 (G10).
- **Kaynak:** [CHG] "KDV Oranları Hakkında" (10.07.2023); CBK 7346 (RG 07.07.2023, sayı 32241)
  https://www.resmigazete.gov.tr/eskiler/2023/07/20230707.htm ; %1 oranının değişmediği ikincil kaynaklarla
  (PwC, KPMG bültenleri) teyit edildi, 2026 için yeni oran kararı bulunamadı.
- **Güven:** Yüksek (formül), Orta (2026 oranlarının değişmediği; RG'den teyit edilmeli).

### K24 · Dağıtım algoritması (en büyük kalan)
- **Formül:** Kuruşa yuvarlanmış toplam T, ağırlıklar w_i. `ham_i = T_kurus x w_i / Σw`, `taban_i = floor(ham_i)`,
  kalan kuruşlar `ham_i - taban_i` en büyük olandan başlayarak birer kuruş verilir; eşitlikte listedeki ilk
  satır önce alır. Ağırlıkların hepsi 0 ise eşit ağırlık. Negatif ağırlık 0 sayılır. KDV hariç tutar ve KDV
  tutarı **ayrı ayrı** dağıtılır (her ikisinin toplamı korunur).
- **Örnek:** 40,00 kargo üç eşit satıra 13,34 / 13,33 / 13,33; KDV 8,00 -> 2,67 / 2,67 / 2,66 (G34).
  Platform hizmet bedeli 33,33 üç siparişe 11,11 / 11,11 / 11,11; KDV 6,67 -> 2,23 / 2,22 / 2,22 (G23).
- **Kaynak:** Tasarım kararı (Hamilton yöntemi). **Güven:** Yüksek (iç kural).

---

## 4. Kurallar (kalem kalem)

Kâr ayarları ve eksik kalem kuralları (K33-K41) §12'dedir; K08, K13, K16, K17 ve K23'ü tamamlarlar.

### K03 · Brüt satış ve indirim ayrımı
- **Formül:** `brut = Σ lineGrossAmount` (her kalem için), `satici_ind = Σ lineItemSellerDiscount`,
  `ty_ind = Σ lineItemTyDiscount`. `satis_dahil (tahmini) = brut - satici_ind`. `ty_ind` gelirden düşülmez.
- **Örnek:** 350,00 brüt, %15 satıcı indirimi 52,50 -> satış 297,50 KDV dahil, 247,92 hariç (G03).
  500,00 brüt, 75,00 TY kuponu -> satış 500,00 (müşteri 425,00 öder) (G06). 600 - 60 satıcı - 50 TY -> 540,00 (G07).
- **Kaynak:** [IND] ("İkisi birbirinden tamamen bağımsızdır", "Trendyol kuponu ... satıcıya yansıtılmaz";
  `lineSellerDiscount` açıklaması [PKG]: "Birim satıcı indirimi (item'ların ortalaması)").
- **Güven:** Yüksek (alanlar), Orta (TY indiriminin satıcı gelirini hiç düşürmediği; `packageTyDiscount` yalnız
  `commercial=true` siparişte dolu gelebilir notuyla çelişki, §9 madde 3).

### K04 · Satış geliri (tahmini ve kesin)
- **Tahmini:** `satis_dahil = brut - satici_ind` (K03).
- **Kesin:** Satıra eşleşen ekstre satırlarından `satis_dahil = Σ (credit - debt)` (tipler: Sale, PayByLink,
  Discount, DiscountCancel, Coupon, CouponCancel, ProvisionPositive, ProvisionNegative);
  `iade_dahil = Σ (debt - credit)` (Return, ManualRefund, ManualRefundCancel). Motor ekstrenin hangi biçimde
  geldiğine bakmaz: Sale net (indirim düşülmüş) da gelse, Sale brüt + ayrı Discount satırı da gelse sonuç aynıdır.
- **Örnek:** G04 (Sale 297,50) ve G05 (Sale 350,00 + Discount 52,50) ikisi de net satış 247,92, net kâr 28,29.
- **Kaynak:** [CHE] işlem türü tablosu ve örnek Sale yanıtı (`debt`, `credit`).
- **Güven:** Yüksek (alanlar), Orta (Sale `credit`'in brüt mü net mi geldiği; formül iki durumda da doğru).

### K05 · Ekstre işlem tipleri ve işaret kuralı
- **Kural:** Sınıflandırma, yanıttaki Türkçe `transactionType` metnine ("Satış") değil, motorun çektiği istek
  tipine (`netkar_istek_tipi`) göre yapılır; her istek tek tipte atılır ([CHE]: "transactionType için 1 istekte
  yalnızca 1 type"). Tutarlar `abs()` ile okunur, işaret tablodan gelir.
- **Gelir:** `credit - debt` (K04).
- **Komisyon maliyet işareti** (+1 satıcıya komisyon yazıldı, -1 geri verildi):

| +1 | -1 | 0 |
|---|---|---|
| Sale, PayByLink, DiscountCancel, CouponCancel, ProvisionPositive, ManualRefundCancel, CommissionPositive, CommissionNegativeCancel, DeliveryFee | Return, Discount, Coupon, ProvisionNegative, ManualRefund, CommissionNegative, CommissionPositiveCancel, DeliveryFeeCancel | SellerRevenue* (dört tip) |

  Satış, iade, indirim, kupon ve provizyon satırları [CHE] "comissionAmount" sütunundan (- = satıcıdan kesildi)
  alındı. `Commission*` satırları için o sütun ters okunuyor (CommissionPositive "+"), bu yüzden işaret
  [CHE]'deki eşleşme kuralından türetildi: "SellerRevenueNegative ve CommissionPositive birlikte
  değerlendirilmelidir" ve ÖdemeTipi "Komisyon Pozitif Düzeltme: Borç (-)". Yani CommissionPositive = ek komisyon.
- **Hakediş düzeltmeleri:** `SellerRevenue*` satırları eşi olan `Commission*` satırının hakediş yansımasıdır;
  geliri ayrıca düşürmez. Satır bazında `artik = Σ(SellerRevenue* credit - debt) + Σ(işaretli Commission*)`;
  `artik ≠ 0` ise kalan tutar gelir düzeltmesi olarak satışa eklenir ve `ESLESMEMIS_HAKEDIS_DUZELTMESI` uyarısı
  verilir.
- **Örnek:** G40: CommissionPositive 5,00 + SellerRevenueNegative 5,00 -> komisyon 74,985 + 5 = 79,985 (66,65
  hariç), gelir değişmez. G41: eşsiz SellerRevenuePositive 20,00 -> satış 519,90, uyarı.
- **Kaynak:** [CHE] iki işaret tablosu ve "birlikte değerlendirilmelidir" listesi.
- **Güven:** Orta. Tabloda iç çelişkiler var (Coupon ÖdemeTipi "Alacak (+)" ama sellerRevenue "-"; TyDiscount
  "Borç (-)"); `Return` satırlarının tutarları pozitif mi negatif mi döndüğü Doğrulanmadı. §9 madde 4.

### K06 · Komisyon matrahı ve tutarı
- **Tahmini:** `komisyon_dahil_exact = satis_dahil x commission / 100` (satırın `commission` oranı, %).
- **Kesin:** `komisyon_dahil_exact = Σ işaret x |commissionAmount|` (K05), tam hassasiyet.
- **Matrah:** Satıcının satış tutarı, KDV dahil, satıcı indirimi düşülmüş; TY indirimi düşülmez.
- **Örnek:** [CHE] örneği: credit 449,99 x %15 = 67,4985 = `commissionAmount`; `sellerRevenue` 382,4915 =
  449,99 - 67,4985. Yani matrah KDV dahil satış tutarı. G05'te Sale 350 x %18 = 63,00, Discount 52,50 x %18 =
  9,45 geri, net 53,55 = 297,50 x %18.
- **Kaynak:** [CHE] örnek yanıt; [PKG] `"commission": 13, // Komisyon oranı`.
- **Güven:** Yüksek (matrahın KDV dahil satış olduğu, örnek aritmetiği birebir tutuyor), Orta (Discount
  satırının komisyonu geri verdiği; işaret tablosundan).

### K07 · Komisyon tutarının KDV'si
- **Varsayılan (ayar `komisyon_tutari_kdv_dahil=true`):** `commissionAmount` KDV dahildir.
  `komisyon = rnd(dahil_exact / 1,20)`, `komisyon_kdv = rnd(dahil_exact) - komisyon`.
- **Alternatif (`false`):** `komisyon = rnd(exact)`, `komisyon_kdv = rnd(exact x 0,20)` (KDV üstüne eklenir).
- **Örnek:** 499,90 x %15 = 74,985 -> 62,49 + 12,50 (G02). Alternatifte 74,99 + 15,00 ve net kâr 106,59 (G12):
  satır başına 12,50 TL fark, 1.000 sipariş/ayda 12.500 TL.
- **Gerekçe:** (1) Sözleşme ekindeki komisyon tablosu oranları "KDV Dahil" diye tanımlıyor ([API] §2.4f).
  (2) Ekstre örneğinde hakediş = satış - commissionAmount; komisyon KDV hariç olsaydı KDV'nin ayrıca bir yerden
  düşülmesi gerekirdi, örnekte böyle bir satır yok.
- **Kaynak:** [API] §2.4f (sözleşme 2022_V37), [CHE] örnek; çelişki notu [GTM] satır 81.
- **Güven:** Orta. Projenin en önemli belirsizliği (§9 madde 1). Pilotta bir komisyon faturası
  (`commissionInvoiceSerialNumber`) ile ekstre toplamı karşılaştırılarak doğrulanmalı.

### K08 · Gönderi kargo bedeli
- **Tahmini (Trendyol anlaşması, `whoPays` yok):** Tarife tablosu (kargo firması `cargoProviderName` + desi)
  KDV hariç tutar verir. Desi: `cargoDeci`, yoksa `ceil(deci)`. Tarife NetKâr ayarıdır (gerçek tarife
  satıcının panelinden girilir; testlerdeki tarife kurgusal).
- **Satıcı anlaşması (`whoPays=1`):** Kullanıcının kendi kargo tarifesi; Trendyol kargo faturası beklenmez,
  kaynak `kullanici`, hakedişten düşülmez (G39). [PKG]: "Eğer satıcı anlaşması ise 1 gelir".
- **Kesin:** `otherfinancials?transactionType=DeductionInvoices` içinde `transactionType` metni "Kargo Faturası"
  ya da "Kargo Fatura" olan satırın `id`'si = `invoiceSerialNumber`; kalemler
  `shipmentPackageType="Gönderi Kargo Bedeli"` ve `orderNumber` ile eşlenir. Bu ekstre satırı ayrıca gider
  sayılmaz (çift sayım yok).
- **Fatura KDV durumu tespiti:** Kalemlerin `amount`'unun KDV dahil mi hariç mi olduğu dokümanda yok. Motor fatura
  başına karar verir: `|Σ amount - ekstre debt| ≤ tol` ise **dahil**; `|Σ amount x 1,20 - debt| ≤ tol` ise
  **hariç**; ikisi de değilse **bilinmiyor** (hariç kabul edilir, `KARGO_FATURASI_KDV_BELIRSIZ`).
  `tol = max(0,05; 0,01 x kalem sayısı)`.
- **Örnek:** 54,00 dahil kalem -> 45,00 + 9,00 (G02). Kalemler 45,00 + 40,00, borç 102,00 -> hariç (G14).
  Desi 2 tahmin 45,00, faturada desi 5, 72,00 dahil -> 60,00; fark 15,00 (G13).
- **Kaynak:** [KRG] (seri numarası bulma, alanlar), [PKG] (`cargoDeci` "sonradan değişebilmektedir", `whoPays`).
- **Güven:** Yüksek (alanlar ve akış), Doğrulanmadı (`amount`'un KDV durumu; tespit kuralı bunu veriyle çözer),
  Doğrulanmadı (`parcelUniqueId` = `cargoTrackingNumber`; şimdilik eşleme `orderNumber` ile).

### K09 · Kargonun satırlara dağıtımı
- **Formül:** Paket (sipariş) düzeyindeki kargo, aktif satırlara K24 ile dağıtılır. Ağırlık: tüm satırlarda ürün
  kartı desisi (`netkar_urun_desi`) varsa `desi x adet`, yoksa satırın `satis_kdv_haric`'i (iade öncesi;
  gönderi kargosu gönderilen mala aittir).
- **Örnek:** 85,00 iki satıra desi x adet 2:3 -> 34,00 / 51,00 (G15). Satış oranıyla 50,00 -> 26,66 / 23,34 (G36).
- **Kaynak:** Tasarım kararı; fatura sipariş bazında, ürün bazına inmez ([API] §2.4d).
- **Güven:** Orta (dağıtım anahtarı bir yorumdur, kullanıcıya "dağıtım" etiketiyle gösterilir).

### K10 · Tam iade
- **Gelir:** `Return` satırı `debt` = iade tutarı (KDV dahil) -> `iade_kdv_haric` (K02, satırın KDV oranı).
- **Komisyon:** `Return` satırının `commissionAmount`'u geri yazılır (işaret -1).
- **Ürün maliyeti:** İade kalemleri `getClaims` ile sayılır: `claimItems[].orderLineItemId` satırın
  `discountDetails[].lineItemId` kümesinde ve `claimItemStatus.name = "Accepted"`. Kullanıcı kalemi
  `stoga_dondu` (varsayılan) işaretlerse maliyet `(adet - iade_stok) x birim`; `satilamaz` işaretlerse maliyet
  gider kalır.
- **Geri alınamayanlar:** gönderi kargo bedeli, iade kargo bedeli (K12), platform hizmet bedeli (iadede iade
  edildiği belgelenmediği için geri alınmaz kabul edildi, §9 madde 6), paketleme gideri.
- **Örnek:** G16: satış 416,58 - iade 416,58 = 0; komisyon 0; gönderi 45 + iade 45 + hizmet 10 -> net kâr -100,00.
  G17 (`satilamaz`): -280,00. G19: 3 adetten 1 iade -> net satış 249,83, maliyet 2 x 55, net kâr -7,65.
- **Kaynak:** [CHE] (`Return`: "Siparişlere ait iade kayıtlarını verir"; işaret tablosu), [CLM] (alanlar,
  statüler).
- **Güven:** Yüksek (gelir ve komisyon ters kaydı), Orta (stok kararı kullanıcıda), Doğrulanmadı (hizmet bedeli).

### K11 · Kısmi iade
- **Formül:** `ManualRefund` debt -> iade (ürün müşteride kalır, maliyet düşmez); komisyonu geri gelir.
  `ManualRefundCancel` önceki kısmi iadeyi sıfırlar (tam iade geldiğinde): `credit` gelir artışı, komisyon +1.
- **Örnek:** 100,00 kısmi iade -> net satış 333,25, komisyon 49,99, net kâr 48,26 (G18). Kısmi iade + iptal +
  tam iade -> net satış 0, komisyon 0, net kâr -100,00 (G20).
- **Kaynak:** [CHE] (`ManualRefund`: "Bir ürün için ürün tutarından daha az olacak şekilde iade kaydı";
  `ManualRefundCancel`: "kısmi iadenin iptali amacıyla").
- **Güven:** Yüksek (anlam), Orta (komisyon işareti, K05).

### K12 · İade kargo bedeli
- **Formül:** Kargo faturasında `shipmentPackageType="İade Kargo Bedeli"`, `orderNumber` eşleşmesi; KDV durumu
  K08 tespitiyle. İade kalemi olan satırlara iade tutarı oranında, iade bilgisi yoksa tüm satırlara satış
  oranında dağıtılır. `getClaims` yanıtında iade kargo bedeli yoktur.
- **Örnek:** 54,00 dahil -> 45,00 (G16); 48,00 dahil 1 desi -> 40,00 (G19).
- **Kaynak:** [KRG] örnek yanıt; [API] §2.4b.
- **Güven:** Yüksek.

### K13 · Platform hizmet bedeli
- **Tahmini:** Ayar `platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric` (kullanıcı ya da NetKâr'ın güncel
  tarife tablosu; testlerde kurgusal 10,00). Sipariş başına, satırlara satış oranıyla.
- **Kesin:** `otherfinancials?transactionType=DeductionInvoices&transactionSubType=PlatformServiceFee`.
  Satır `orderNumber` taşıyorsa o siparişe; taşımıyorsa aynı `paymentOrderId`'ye düşen Sale satırı olan
  siparişlere **eşit** (sipariş başı bedel varsayımı), sipariş içinde satış oranıyla. Fatura tutarı (`debt`)
  KDV dahil kabul edilir; KDV ayrımı fatura düzeyinde yapılıp hariç ve KDV ayrı dağıtılır (K24).
  Faturası henüz gelmemiş kesin siparişte tahmini kalır, kaynak `tahmini`.
- **Örnek:** 40,00 dahil -> 33,33 + 6,67; üç siparişe 11,11 ve 2,23/2,22/2,22; iki satırlı siparişte 4,57 / 6,54 (G23).
- **Kaynak:** [CHE] ("Yalnızca Platform Hizmet Bedeli kayıtlarını filtrelemek için önerilen endpoint"), [OTH].
- **Güven:** Yüksek (endpoint), Doğrulanmadı (sipariş başı mı, `orderNumber` taşır mı, kapsadığı dönem,
  `debt`'in KDV dahil olduğu; §9 madde 5).

### K14 · Ceza ve sınıflandırılmış kesintiler
- **Kural:** `otherfinancials` satırları NetKâr eşleme tablosuyla (istek tipi + `transactionType`/`description`
  metni -> `sinif`, `kdv_orani`) sınıflanır. Bilinen sınıflar: `kargo_faturasi` (K08), `platform_hizmet_bedeli`
  (K13), `ceza`, `erken_odeme_bedeli` (K19), `stopaj` (K18), nakit hareketleri (`PaymentOrder`, `CashAdvance`,
  `WireTransfer`, `IncomingTransfer`) gider değildir.
- **Ceza:** `orderNumber` varsa siparişin satırlarına satış oranıyla (durum `adjusted`); yoksa dönem düzeyi
  `dagitilmamis_ceza` (ürüne dağıtılmaz; bir siparişin cezası diğer ürünlerin kârını bozmamalı).
  `kdv_orani > 0` ise tutar KDV dahil kabul edilir.
- **Sınıflandırılamayan satır:** Tutarı (`debt - credit`) dönem gideri `siniflandirilmamis_kesinti` olarak
  ihtiyatla kâra yansır ve `SINIFLANDIRILMAMIS_KESINTI` uyarısı verilir.
- **Örnek:** 60,00 dahil sipariş cezası -> 50,00 + 10,00; satırlara 29,41 / 20,59 (G21). Bağsız 240,00 -> dönem
  200,00; bilinmeyen FinancialItem 17,35 (G22).
- **Kaynak:** [CHE] (`DeductionInvoices`: "Trendyol tarafından sağlanan hizmetler için tedarikçiye kesilen
  faturadır"; `FinancialItem`: "düzeltme kayıtları"), [API] §2.4c ("ceza adında bir transactionType yok").
- **Güven:** Doğrulanmadı (ceza metinleri, sipariş taşıyıp taşımadığı, KDV'si). Eşleme tablosu pilot hesapla
  doldurulmalı (§9 madde 7).

### K15 · Reklam
- **Veri:** Satıcı panelindeki "Oluşturulan Reklamlar" Excel raporu kullanıcı tarafından yüklenir ve NetKâr iç
  şemasına aktarılır: `kayit_id`, `barkod` (yoksa null), `baslangic`, `bitis`, `harcama`, `harcama_kdv_dahil`,
  `reklam_cirosu`. Excel kolon adları Doğrulanmadı; yükleme ekranında kolon eşleme adımı olmalı.
- **Formül:** Harcama KDV dahil işaretliyse K02 ile hariçleştirilir. Kayıt dönemine (sipariş tarihi
  `orderDate`, İstanbul günü) düşen, net satışı > 0 olan satırlar adaydır.
  - **Eşlenen** (barkod katalogda): o barkodun satırlarına net satış oranıyla (K24), etiket `eslesen`.
    Dönemde o ürünün satışı yoksa harcama başka ürüne kaydırılmaz: ürün toplamında `reklam_satissiz`, dönemde
    gider.
  - **Eşlenmeyen** (mağaza reklamı, barkodsuz, katalogda olmayan barkod): dönemdeki tüm satırlara net satış
    oranıyla, etiket `dagitim_tahmini`; ekranda "tahmini" rozeti. Aday satır yoksa dönem gideri
    `reklam_dagitilamayan`.
- **Ürün kârlılığı harcanan tutarı kullanır; ekstredeki "Satıcı Reklamı Satın Alma" bakiye yükleme tutarı yalnız
  nakit akışına aittir** ([API] §2.4e).
- **Örnek:** 120,00 iki satıra 40,00 / 80,00 (G24); 90,00 dahil -> 75,00, üç satıra 32,60 / 22,83 / 19,57 (G25);
  satışsız ürün 80,00 ve katalog dışı barkod 12,50 (G26).
- **Kaynak:** [API] §2.4e (API yok, Excel ve ekstre davranışı, Orta güven).
- **Güven:** Orta (yaklaşım), Doğrulanmadı (Excel kolonları, harcamanın KDV dahil olup olmadığı, ciro tanımı).

### K16 · Ürün maliyeti
- **Formül:** Barkod için `gecerlilik_baslangic ≤ sipariş günü` olan en son kayıt. Sipariş günü `orderDate`
  (ms, UTC) Europe/Istanbul'a çevrilerek bulunur (UTC+3 sabit). `maliyet = birim_maliyet_kdv_haric x
  (adet - stoğa dönen iade)`, `maliyet_kdv = rnd(... x alış KDV oranı)`.
- **Maliyet yoksa:** `urun_maliyeti`, `net_kar`, `toplam_gider`, marj `null`; `maliyet_haric_katki` hesaplanır;
  uyarı `MALIYET_EKSIK`; ürün toplamında `maliyet_eksik=true`; dönem net kârı `net_kar_kismi=true`
  (yalnız maliyeti olan satırları toplar). Sıfır maliyet varsayılmaz.
- **Örnek:** 9 Ekim 23:50 siparişi 170,00, 10 Ekim 00:30 siparişi 190,00 (G30); B maliyetsiz (G29).
- **Kaynak:** Tasarım kararı ([API] §3: COGS Trendyol'da yok).
- **Güven:** Yüksek (iç kural). Maliyet yöntemi (son alış, FIFO, ortalama) kullanıcının girdiği birim maliyettir;
  NetKâr stok değerlemesi yapmaz.

### K17 · Değişken giderler (kullanıcı tanımlı)
- **Tipler:** `siparis_basi` (sipariş düzeyi, satırlara satış oranıyla), `adet_basi` (tutar x adet), `satis_yuzdesi`
  (net satış KDV hariç x oran). Her biri KDV hariç tutar + KDV oranı.
- **Örnek:** paketleme 6,00 sipariş başı, etiket 0,50 adet başı, e-fatura entegratörü %0,5 -> satır 1: 3,20 + 1,00 +
  1,67 = 5,87 (G36).
- **Kaynak:** Tasarım kararı. **Güven:** Yüksek (iç kural).

### K18 · E-ticaret stopajı (%1)
- **Kural:** Gider değildir. Satıcı adına Trendyol'un kestiği peşin gelir/kurumlar vergisidir; satıcı yıllık ya da
  geçici vergi beyanında mahsup eder. Kâr hesabına girmez; satırın `nakit_akisi.stopaj` alanında ve dönemde
  gösterilir.
- **Formül:** `stopaj = rnd(net_satis_kdv_haric x %1)`. Matrah KDV hariç satış bedeli; komisyon ve kargo
  düşülmez. İade edilen tutar matrahtan çıkar (net satış üzerinden).
- **Mutabakat:** `otherfinancials?transactionType=Stoppage` dönem toplamı ("E-ticaret Stopajı ve E-ticaret Stopaj
  İptali") hesaplananla karşılaştırılır; fark 0,05'i aşarsa `STOPAJ_EKSTRE_FARKI`.
- **Örnek:** 416,58 -> 4,17; 291,67 -> 2,92; toplam 7,09, ekstre 7,10, uyarı yok (G35).
- **Kaynak:** 9284 sayılı Cumhurbaşkanı Kararı (21.12.2024, yürürlük 01.01.2025, oran %1) ve 330 Seri No.lu Gelir
  Vergisi Genel Tebliği (RG 30.12.2024); ikincil kaynaklar: https://www.erdem-erdem.av.tr/bilgi-bankasi/elektronik-ticaret-uzerinden-yapilan-odemeler-icin-stopaj-uygulamasi ,
  https://www.parasut.com/blog/e-ticarette-stopaj-duzenlemesi ,
  https://www.muhasebenews.com/internet-pazar-yerlerinin-stopaj-kesintisi-ile-ilgili-ornek-hesaplamalar/ ;
  [CHG] 25.12.2024 ("1 Ocak 2025 itibarıyla yapılacak ödemelerden %1 stopaj") ve 27.12.2024 (`Stoppage` tipi).
- **Güven:** Yüksek (oran, gider olmadığı), Orta (matrahın TY indirimli siparişte hangi tutar olduğu; iadenin
  beyan sonrası düzeltmesi; işçilik bedeli ayrımı, K32). GİB ve RG metinleri bu oturumda ağ izni olmadığı için
  doğrudan açılamadı; müşavir teyidi §9 madde 8.

### K19 · Erken ödeme
- **Kural:** `CashAdvance` satırı vadesi gelmemiş hakedişin erken ödenmesidir: **nakit girişi, gider değil**
  (`erken_odeme_nakit_girisi`). Erken ödeme hizmet bedeli eşleme tablosunda `erken_odeme_bedeli` sınıfına
  düşerse dönem düzeyi finansman gideri olur; ürün kârına dağıtılmaz (finansman kararı ürüne ait değil).
- **Örnek:** 10.000,00 nakit girişi; 120,00 KDV dahil bedel -> 100,00 dönem gideri; dönem net kârı 119,09 - 100 =
  19,09 (G37).
- **Kaynak:** [CHE] ("CashAdvance: Vadesi henüz gelmemiş hakedişler için erken ödeme alındığında atılan kayıttır").
- **Güven:** Yüksek (CashAdvance anlamı), Doğrulanmadı (bedelin hangi satırda, hangi metinle geldiği, §9 madde 7).

### K20 · KDV etkisi (bilgi satırı)
- **Formül:** `kdv_etkisi = (satis_kdv - iade_kdv) - (komisyon_kdv + kargo_kdv + platform_hizmet_bedeli_kdv +
  ceza_kdv + urun_maliyeti_kdv + degisken_giderler_kdv + reklam_kdv)`. Pozitifse satırın ödenecek KDV'ye katkısı,
  negatifse devreden KDV'ye katkısı.
- **Not:** Alış KDV'si gerçekte alış döneminde indirilir; bu satır "birim başı teorik KDV yükü"dür, beyanname
  değildir. KDV mükellefi olmayan satıcı için (nadir) indirilecek KDV maliyete eklenmeli; v1 kapsam dışı.
- **Örnek:** G01: 83,32 - 59,50 = 23,82. G10 (%1 ürün): 1,78 - 14,95 = -13,17 (devreden KDV birikir).
- **Kaynak:** KDV mekanizması (3065 s. KDVK m.29 indirim); [HUK] §6. **Güven:** Yüksek (mekanizma).

### K21 · Nakit akışı satırı
- **Formül:** `trendyol_hakedis = rnd(satis_dahil) - rnd(iade_dahil) - komisyon_dahil` (ekstredeki
  `sellerRevenue` toplamına denk); `fatura_kesintileri_kdv_dahil` = gönderi + iade kargo + platform hizmet bedeli +
  ceza (KDV dahil; `whoPays=1` kargo hariç); `beklenen_net_tahsilat = hakedis - fatura_kesintileri - stopaj`.
  Reklam bakiye yüklemesi ve erken ödeme dönem nakit kalemleridir.
- **Örnek:** G01: 424,91 - 66,00 - 4,17 = 354,74.
- **Kaynak:** [CHE] (`sellerRevenue`, `paymentOrderId`), K18. **Güven:** Orta (fatura kesintilerinin aynı ödeme
  emrinden mahsup edildiği varsayımı).

### K22 · Durum makinesi
Ayrıntı §5.

### K23 · Fark tespiti ve beklenmeyen kesinti
Ayrıntı §6.

### K25 · Toplulaştırma, marj, ROAS
Ayrıntı §7.

### K26 · İptal
- **Kural:** `status` `Cancelled` ya da `UnSupplied` ise satır `cancelled`: gelir, gider, maliyet 0; ürün ve dönem
  toplamlarına girmez. Kısmi iptalde paket bölünür, yeni `shipmentPackageId` gelir; motor `lineId` ile çalışır.
- **Örnek:** G38. **Kaynak:** [PKG] (`createdBy`: "cancel", `originPackageIds`), [API] §2.4a.
- **Güven:** Yüksek (statü), Doğrulanmadı (gönderim sonrası iptalde kargo faturası gelip gelmediği).

### K27 · Eşleştirme anahtarları
- **Kural:** Ekstre satırı -> sipariş satırı: `orderNumber` eşit **ve** `barcode` eşit **ve**
  (`shipmentPackageId` eşit ya da ekstrede null). Aynı barkod aynı pakette birden çok satırda varsa tutar
  satırlara adet oranında dağıtılır. Bir Sale satırının bir satırın tüm adetlerini mi yoksa tek adedi mi temsil
  ettiği belgelenmemiş; motor eşleşen tüm satırları toplar (iki biçimde de doğru sonuç verir, G08).
- **Kaynak:** [CHE] (`shipmentPackageId` Mart 2025'te eklendi, [API]). **Güven:** Yüksek (alanlar), Doğrulanmadı
  (adet granülerliği, §9 madde 10).

### K28 · Ekstre iç tutarlılık kontrolü
- **Formül:** Satış ve iade tiplerinde `|sellerRevenue| = |(credit - debt) - işaret x |commissionAmount||`
  (0,01 tolerans). Tutmazsa `EKSTRE_IC_TUTARSIZLIK` (veri sorunu ya da işaret kuralı yanlış; destek kaydı açılır).
  Düzeltme tiplerinde uygulanmaz (`sellerRevenue` 0 gelir).
- **Örnek:** [CHE] örneği 449,99 - 67,4985 = 382,4915 tutar. **Güven:** Yüksek (örnekle).

### K29 · Teslimat ücreti (`DeliveryFee`)
- **Kural (v1):** Altın testte yok. Gelirse satış gibi işlenir (`credit - debt` gelir, komisyon işareti +1) ve
  `TESLIMAT_UCRETI` bilgi etiketi taşır. Kim öder, KDV oranı ne, belgelenmemiş.
- **Kaynak:** [CHE] ("DeliveryFee: Teslimat ücreti kayıtlarını verir"). **Güven:** Düşük (§9 madde 11).

### K30 · Kurumsal faturalı sipariş (`TyDiscount`, `TyCoupon`)
- **Kural (v1):** `commercial=true` siparişte Trendyol indirimi satıcıya ay sonu faturayla ödenir. Ekonomik gelir
  yine `brüt - satıcı indirimi`; `TyDiscount`/`TyCoupon` satırları gelir hesabına katılmaz, alacak takibi için
  ayrı listelenir. Altın testte yok.
- **Kaynak:** [CHE] ("Bu tutar, ay sonlarında satıcıdan talep edilen fatura ile satıcıya ödenir"; tabloda Borç (-)).
- **Güven:** Düşük (işaret tablosu ve fatura KDV'si belirsiz, §9 madde 3).

### K31 · Kargo tazmini (TEX)
- **Kural (v1):** `tex/compensation/.../tickets` onaylı statülerde (`CompensationApproved` vb.) `totalItemsAmount`
  sipariş satırlarına satış oranıyla **gelir** (eksi gider) olarak yazılır; satıcı Trendyol'a fatura keser
  ("Trendyol'a Kesmem Gereken Faturalar"), bu nedenle tutar KDV hariç kabul edilir ve KDV'si satış KDV'si gibi
  işlenir. Kayıp ürünün maliyeti gider kalır. Altın testte yok.
- **Kaynak:** [TAZ]. **Güven:** Düşük (tutar alanı örnekte boş string; dokümandaki `CompensationRejected`
  açıklaması onay metniyle aynı, doküman hatası olası).

### K32 · Gramaj provizyonu ve işçilik bedeli
- **Kural (v1):** `ProvisionPositive/Negative` satış tipi olarak işlenir (K04). `laborCostPerItem` (işçilik
  bedeli) yalnız stopaj matrahı ayrımı içindir; v1'de stopaj tüm KDV hariç satıştan hesaplanır, altın/takı
  kategorisi için uyarı gösterilir.
- **Kaynak:** [CHE] ("Gramaj farkından dolayı oluşan tutarlar"), [PKGR] `laborCostPerItem`, [CHG] 25.12.2024
  ("İşçilik bedelleri line bazlı bildirilmelidir"). **Güven:** Düşük (§9 madde 12).

---

## 5. Durum makinesi (K22)

```
               Sale/PayByLink satırı eşleşti                Return, ManualRefund(Cancel),
  estimated ─────────────────────────────────▶ settled ───▶ Commission*/SellerRevenue* düzeltmesi,
      │                                           │         iade kargo kalemi, siparişe bağlı ceza
      │  status Cancelled/UnSupplied              │                     │
      ▼                                           ▼                     ▼
  cancelled                                  (kalem kaynakları    adjusted (yeni kayıt geldikçe
                                              tek tek kesinleşir)  yeniden hesaplanır, terminal değil)
```

| Durum | Giriş koşulu | Gelir ve komisyon | Diğer kalemler |
|---|---|---|---|
| `estimated` | Sipariş var, eşleşen Sale yok | Sipariş satırından, `commission` oranıyla | Kargo tarifeden, hizmet bedeli ayardan, reklam Excel'den |
| `settled` | Eşleşen Sale/PayByLink var, düzeltme yok | Ekstreden (`credit - debt`, `commissionAmount`) | Her kalem kendi kaynağı gelince `kesin` olur; gelmeyen `tahmini` kalır (`kaynaklar` bloğu) |
| `adjusted` | settled + iade/düzeltme/iade kargo/sipariş cezası | Ekstreden, ters kayıtlar dahil | Aynı |
| `cancelled` | `Cancelled`, `UnSupplied` | 0 | 0 |

Notlar:
- İade ekstrede satıştan önce görünmez; Sale ve Return aynı gün gelirse doğrudan `adjusted` olur.
- "Finansal kayıtlar sipariş teslim edildikten sonra oluşmaktadır" ([CHE]); teslim edilmemiş sipariş hep
  `estimated`.
- Durum her senkronda baştan hesaplanır (idempotent); kayıtlar silinmez, eklenir.

---

## 6. Fark tespiti ve "beklenmeyen kesinti" (K23)

Ekstre gelmiş her satırda (settled, adjusted) motor aynı satırın **tahmini** değerlerini de hesaplar ve
`karsilastirma` bloğunda saklar.

- **Karşılaştırılan kalemler:** komisyon (iade ters kayıtları hariç, düzeltmeler dahil), gönderi kargo (yalnız
  fatura geldiyse), platform hizmet bedeli (yalnız fatura dağıtıldıysa). Hepsi KDV hariç. v0.2: tahmini
  tanımsız (tarife ya da hizmet bedeli ayarı yok) kalem karşılaştırmaya hiç girmez (K38).
- **Fark:** `fark = kesin_toplam - tahmini_toplam`.
- **Eşik:** `esik = max(5,00 TL; %5 x tahmini_toplam)`; `fark ≤ 0,05` yuvarlama sayılır.
- **Uyarılar:**
  - `BEKLENMEYEN_KESINTI`: `fark > 0,05` ve `fark > esik` (yalnız aleyhe fark; lehe fark bilgi).
  - `KOMISYON_ORANI_FARKLI`: Sale satırının `commissionRate`'i sipariş satırındaki `commission`'dan 0,01 puandan
    fazla farklıysa, tutardan bağımsız her zaman (kampanya komisyonu, kategori değişikliği sinyali).
  - `KARGO_DESI_FARKI`: faturadaki desi siparişteki `cargoDeci`'den farklıysa, tutardan bağımsız.
  - `SINIFLANDIRILMAMIS_KESINTI` (dönem): eşleme tablosunda karşılığı olmayan her `otherfinancials` gider satırı.
- **Örnekler:** G13 kargo 45 -> 60, fark 15,00 > 5,37: uyarı. G27 oran 15 -> 18, komisyon 62,49 -> 74,99, fark
  12,50: iki uyarı. G28 kargo 54,05, fark 0,04: uyarı yok. G40 düzeltme farkı 4,16 < 5,37: uyarı yok.
- **Eşik önerisinin gerekçesi:** 5 TL altı tek sipariş farkları kuruş yuvarlaması ve desi basamağı oynamalarıyla
  karışır; %5 oranı yüksek tutarlı siparişte tek başına 5 TL'nin anlamsızlaşmasını engeller. İlk 4 hafta pilot
  verisiyle uyarı oranı ölçülüp eşik ayarlardan güncellenmeli (hedef: siparişlerin en fazla %2'si uyarı).
- **Güven:** Orta (eşikler öneri), Yüksek (hesap).

---

## 7. Çıktı şeması, toplulaştırma, marj ve ROAS (K25)

Ayrıntılı JSON şeması: `services/api/tests/golden/README.md`.

### 7.1 Sipariş satırı kırılımı
`kalemler` (satış ve iade alanları KDV dahil ve hariç; giderler KDV hariç), `kdv`, `nakit_akisi`, `kaynaklar`
(her kalem: `kesin`, `kesin_dagitim`, `tahmini`, `kullanici`, `eslesen`, `dagitim_tahmini`, `eksik`, `yok`),
`degisken_gider_detayi`, `reklam_detayi`, `karsilastirma`, `uyarilar`, `durum`.
v0.2 ekleri (§12): `kesinlik` (K40), `eksik_kalemler` (K37), `kalemler.eksik_giderler_haric_kar` (K37),
`iade_kaydi_bekleyen_adet` ve `askidaki_urun_maliyeti` (K41). `eksik_kalemler` boş değilse `net_kar`,
`toplam_gider`, `net_kar_marji_yuzde` null'dır; `karsilastirma` içindeki tanımsız tahmin null'dır (K38).

### 7.2 Ürün (barkod) toplamı
Satırların yuvarlanmış değerlerinin toplamı (iptaller hariç). Ek alanlar: `reklam_satissiz`, `reklam_harcamasi`
(= satırlara dağıtılan + satışsız), `reklam_cirosu` (Excel), `roas`, `basabas_roas`, `maliyet_eksik`, `stopaj`.
Ürünün net kârı = satır net kârları - `reklam_satissiz`; satırlardan birinde eksik kalem varsa (maliyet, kargo,
hizmet bedeli; K37) `null`. v0.2 ekleri: `eksik_giderler_haric_kar`, `eksik_kalem_satir_sayilari`, `kesinlik`.

### 7.3 Dönem toplamı
`satir_net_kar_toplami` (maliyeti olan satırlar) eksi dönem düzeyi giderler (`reklam_satissiz_urunler`,
`reklam_dagitilamayan`, `dagitilmamis_ceza`, `erken_odeme_bedeli`, `siniflandirilmamis_kesinti`) = `donem_net_kar`.
Ayrıca `net_kar_kismi`, `kdv_etkisi`, `nakit_akisi` (`stopaj_hesaplanan`, `stopaj_ekstre`,
`erken_odeme_nakit_girisi`), dönem uyarıları. v0.2 (K39): `satir_net_kar_toplami` yalnız TAM satırları (eksik
kalemi olmayan) toplar; `donem_duzeyi_giderler_toplami`, `tam_satirlar` bloğu (tam satırların kalem kalem
kırılımı ve kendi marjı), `eksik_kalem_satir_sayilari`, `kesinlik`, `kesinlik_satir_sayilari`; kısmi dönemde
`net_kar_marji_yuzde` null. v0.3 (K39 Revizyon 1): kısmi dönemde `satir_net_kar_toplami` ve `donem_net_kar`
null; her dönemde `donem_eksik_giderler_haric_kar` (tüm aktif satırların bilinen giderlerle kârı eksi dönem
düzeyi giderler). API rapor yanıtları ayrıca `settings_revision` taşır (K44; motor alanı değildir).

### 7.4 Tanımlar
| Metrik | Formül | Not |
|---|---|---|
| Net kâr marjı % | `net_kar / net_satis_kdv_haric x 100` | Net satış 0 ise `null` (tam iade). Dönemde: kısmi dönemde `null` (K39) |
| Tam satır marjı % | `tam_satirlar.net_kar / tam_satirlar.net_satis_kdv_haric x 100` | Dönem düzeyi giderler hariç; pay ve payda aynı satır kümesi (K39). G46: 119,09 / 416,58 = 28,59 |
| Eksik giderler hariç kâr | `net_satis - bilinen giderler` | Eksik kalem 0 sayılmaz, hariç tutulur; etiketle gösterilir (K37) |
| Dönem eksik giderler hariç kâr | `Σ aktif satır eksik_giderler_haric_kar - donem_duzeyi_giderler_toplami` | Tam dönemde `donem_net_kar`'a eşit; kısmi dönemde dönemin tek kâr rakamı, eksik kalemleri sayan etiketle (K39 Revizyon 1). G46: 119,09 + 184,17 - 17,35 = 285,91 |
| Maliyet hariç katkı | `net_satis - (tüm giderler - ürün maliyeti)` | Maliyeti olmayan ürün için de gösterilir |
| ROAS | `reklam_cirosu / reklam_harcamasi` | Trendyol paneliyle aynı tanım; cironun KDV dahil olduğu varsayılır (Doğrulanmadı). Örnek 1.499,70 / 120,00 = 12,50 (G24) |
| Başabaş ROAS | `net_satis_kdv_haric / (net_kar + reklam_harcamasi)` | Reklamın tüm katkıyı yediği ROAS (KDV hariç ciro bazında). G24: 1.249,75 / 407,28 = 3,07. Platform ROAS'ı ile karşılaştırırken ciroyu KDV hariçleştirin (12,50 / 1,20 = 10,42 > 3,07: kârlı) |

---

## 8. Ayarlar ve varsayılanlar

Ayrıntı K33-K36 (§12) ve `docs/adr/0006-kar-ayarlari.md`. "Kullanıcı" ayarları pazaryeri hesabı düzeyindedir,
geçerlilik tarihlidir ve **varsayılanları tanımsızdır** (tanımsız 0 demek değildir). "Sistem" parametreleri
motor sabitidir, kullanıcıya açılmaz.

| Ayar (golden `ayarlar` anahtarı) | Tür | Varsayılan | Kural |
|---|---|---|---|
| `kargo_tarifesi` (Trendyol anlaşmalı), `satici_kargo_tarifesi` (whoPays=1) | Kullanıcı, sürümlü | boş (tarife yok) | K08, K34 |
| `varsayilan_desi` | Kullanıcı | `null` | K34 |
| `platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric` | Kullanıcı, sürümlü | `null` (tanımsız) | K13, K35 |
| `degisken_giderler` | Kullanıcı, geçerlilik aralıklı | boş | K17, K36 |
| `komisyon_tutari_kdv_dahil` | Sistem | `true` | K07 |
| `komisyon_kdv_orani`, `kargo_kdv_orani`, `hizmet_bedeli_kdv_orani`, `reklam_kdv_orani` | Sistem | `20` | K02 |
| `stopaj_orani` | Sistem | `1` | K18 |
| `kargo_faturasi_kdv_tespit_toleransi` | Sistem | `0.05` | K08 |
| `uyari_esikleri` | Sistem | 5,00 TL; %5; 0,05; 0,01 puan | K23 |

Testlerdeki tarife, hizmet bedeli ve kargo firma adları ("Ornek Kargo" dahil) kurgusaldır; üretimde
kullanılmaz. G01-G41 kurgusal tam ayar setiyle, G42, G48 ve G49 üretim varsayılanıyla (hiç kullanıcı ayarı yok),
G43 hizmet bedeli tanımsız, G44-G45 sürümlü ayarlarla çalışır.

---

## 9. Hasan / mali müşavir teyidi gereken noktalar (önem sırasıyla)

| # | Soru | Neden önemli | Nasıl doğrulanır | Etkilenen kural ve test |
|---|---|---|---|---|
| 1 | `commissionAmount` KDV dahil mi (komisyon faturası = commissionAmount), yoksa KDV hariç mi (fatura = commissionAmount x 1,20)? | Her siparişte komisyonun %16,7'si kadar kâr farkı (G02 ile G12 arası 12,50 TL) | Pilot satıcının bir haftalık komisyon faturası (`commissionInvoiceSerialNumber`) toplamı ile o haftanın Sale `commissionAmount` toplamını karşılaştırmak; mali müşavir komisyon faturasının KDV satırını okur | K07; G02, G12 ve tüm settled testler |
| 2 | Kargo faturası kalemlerindeki `amount` KDV dahil mi? Platform hizmet bedeli ve ceza `debt` tutarları KDV dahil mi? | Kargo her siparişte en büyük ikinci Trendyol kesintisi | K08 tespit kuralı veriyle cevaplar; pilotta tespit sonucu "bilinmiyor" çıkmamalı. Müşavir fatura PDF'ini kontrol eder | K08, K13, K14; G02, G13, G14, G23 |
| 3 | Bireysel siparişte Trendyol karşılamalı indirim satıcının faturasını ve Sale `credit`'ini nasıl etkiliyor? Satıcı müşteriye indirimli tutardan fatura kesip farkı Trendyol'dan mı alıyor? Kurumsal siparişte `TyDiscount` faturasının KDV'si? | Satış KDV'si ve stopaj matrahı değişir; TY kampanyalı satışta gelir yanlış olabilir | Pilot hesapta TY kuponlu bir siparişin e-faturası ile Sale satırı karşılaştırılır; Trendyol'a soru ([API] §4 madde 11) | K03, K04, K18, K30; G06, G07 |
| 4 | İşaret kuralları: Return/Discount/ManualRefund satırlarında `commissionAmount`, `debt`, `sellerRevenue` pozitif mi negatif mi döner? Tablolardaki çelişkiler (Coupon "Alacak (+)" ama sellerRevenue "-"; CommissionPositive sütunu) hangisi doğru? | Yanlış işaret iadede komisyonu iki kez sayar | Pilot hesapta bir iade ve bir indirimli siparişin ham ekstre satırları; K28 iç tutarlılık uyarısı izlenir | K05, K28; G05, G16, G18, G20, G40, G41 |
| 5 | Platform hizmet bedeli sipariş başına mı, satış tutarına bağlı mı? Satır `orderNumber` taşıyor mu? Hangi siparişleri kapsıyor (ödeme emri mi, fatura dönemi mi)? Güncel tutar? | Dağıtım anahtarı ürün kârını değiştirir | Pilot ekstre + Trendyol duyuruları; Hasan'ın satıcı panelinden fatura detayı | K13; G23 |
| 6 | İade edilen siparişte platform hizmet bedeli iade ediliyor mu? Gönderi kargo bedeli iadede geri alınıyor mu? | İade maliyetini doğrudan belirler | Pilot hesapta iade edilen bir siparişin sonraki ekstreleri | K10; G16, G17, G20 |
| 7 | Ceza, erken ödeme hizmet bedeli, reklam bakiyesi, influencer bedeli `otherfinancials` içinde hangi tip ve metinle geliyor, sipariş taşıyor mu, KDV'li mi? Ceza KDV'ye tabi mi (cezai şart KDV dışı olabilir)? | Eşleme tablosu olmadan bu kalemler "sınıflandırılmamış" kalır | Pilot hesabın 3 aylık `DeductionInvoices` ve `FinancialItem` dökümü; müşavir ceza faturalarının KDV durumunu yorumlar | K14, K19; G21, G22, G37 |
| 8 | Stopaj matrahı: TY indirimli siparişte hangi tutar? İadede stopaj iptali hangi dönemde? Kâr hesabında gider sayılmaması ve geçici vergide mahsubu doğru mu (şahıs ve şirket satıcı için)? | Nakit akışı ve kullanıcının vergi algısı | Müşavir; GİB 330 Seri No.lu Tebliğ metni (bu oturumda gib.gov.tr erişilemedi) | K18; G35 |
| 9 | Trendyol `commissionAmount` ve fatura toplamlarını hangi yöntemle yuvarlıyor (satır, fatura)? | Kuruş farkları ve beklenmeyen kesinti eşiği | Pilot komisyon faturası ile 4 ondalıklı ekstre toplamının farkı | K01, K23; G28 |
| 10 | Aynı barkoddan çok adetli satırda Sale satırı adet başına mı, satır toplamı mı? | Eşleştirme ve kısmi iade | Pilot veri ([API] §4 madde 7) | K27; G08, G19 |
| 11 | `DeliveryFee` kim tarafından, hangi siparişte, hangi KDV ile ödeniyor? | Ücretli teslimat seçeneklerinde gelir | Trendyol'a soru, pilot veri | K29 |
| 12 | Altın/takı gibi işçilik bedelli kategorilerde stopaj matrahı (`laborCostPerItem`) ve provizyon satırları | Yanlış stopaj tahmini | Müşavir; hedef kitlede bu kategori varsa | K32 |
| 13 | Reklam Excel'inde harcama KDV dahil mi, ciro KDV dahil mi, kolon adları sabit mi? | ROAS ve reklam payı | Hasan'ın panelden örnek Excel'i | K15; G24, G25, G26 |
| 14 | `parcelUniqueId` ile `cargoTrackingNumber` aynı mı (bölünmüş pakette kargo eşlemesi)? | Çok paketli siparişte kargo yanlış pakete gider | Pilot veri | K08, K09 |
| 15 | Ürün maliyetinde satıcıların çoğu KDV dahil mi düşünüyor? Giriş ekranı varsayılanı ne olmalı? | Kullanıcı hatası maliyeti %20 şişirir | Hasan ile 5 satıcı görüşmesi | K16 |
| 16 | Trendyol anlaşmalı kargo fiyatı nasıl belirleniyor: firma bazında desi kademeli mi, en yüksek kademe üstü (desi aşımı) nasıl fiyatlanıyor, ne sıklıkla değişiyor? Hasan'ın kendi anlaşması ve bir kargo faturası | K34 tarife modeli (firma x desi kademesi x sürüm) bunu varsayar; aşım ücreti modellenmedi (aşan desi "eksik" olur) | Hasan'ın satıcı panelindeki kargo fiyat ekranı ve bir aylık kargo faturası; research/01'de kaynak yok (Doğrulanmadı) | K34; G44, G45 |
| 17 | Siparişteki `cargoProviderName` metni sabit mi (aynı firma farklı yazımla, ör. "Marketplace" ekiyle gelir mi)? `cargoDeci` boş gelen sipariş ne sıklıkta? | Tarife eşlemesi metin birebir; yazım farkı kargoyu "eksik" bırakır. Varsayılan desinin gerekliliği | Pilot hesabın 3 aylık siparişlerinde firma adı ve `cargoDeci` dağılımı | K34; G45 |
| 18 | Platform hizmet bedeli sipariş başına sabit tek tutar mı, yoksa sepet tutarına ya da kategoriye göre kademeli mi? Güncel tutar ve son değişiklik tarihi? (madde 5 ile birlikte) | K35 yalnız sipariş başı tek tutarı (sürümlü) destekler; kademeli ise ayar şeması genişler | Hasan'ın panelindeki hizmet bedeli faturası ve Trendyol duyuruları | K13, K35; G43, G44 |
| 19 | İadede sıra: `Return` ekstre satırı iade talebi (claim) kabulünden önce gelebilir mi? Claim'i hiç olmayan `Return` var mı (ör. teslim edilemeyen paket)? Claim gecikmesi kaç gün? | K41 bu durumu geçici sayar; kalıcıysa maliyet kuralı değişmeli (teslim edilemeyen paket stoğa döner) | Pilot hesapta `Return` satırları ile `getClaims` kayıtlarının tarih karşılaştırması | K10, K41; G47 |
| 20 | Dönem düzeyi giderlerin (sınıflandırılmamış kesinti, bağsız ceza, erken ödeme bedeli, satışsız reklam) dönem kârından tam düşülmesi müşavir açısından uygun mu? | K39 Revizyon 1 bunları tam dönemde `donem_net_kar`'dan, kısmi dönemde `donem_eksik_giderler_haric_kar`'dan tam düşer (kısmi dönemde dönem net kârı artık null) | Müşavir görüşü | K39; G46, G49 |
| 21 | Eksik kalem varken panel "beklenen net tahsilat" ve "KDV etkisi"ni bilinen kalemlerle mi göstermeli, yoksa gizlemeli mi? | K37 bu blokları bilinen kalemlerle hesaplar ve `eksik_kalemler` ile etiketler; satıcı tahsilatı yanlış planlayabilir | Hasan (ürün kararı) | K37 |
| 22 | Değişken giderler (paketleme, e-fatura) KDV dahil girilebilmeli mi? Satıcıların çoğu paketleme fiyatını KDV dahil mi biliyor? | K17/K36 KDV hariç tutar + oran ister; tarife ve hizmet bedeli için dahil/hariç seçimi var | Hasan ile satıcı görüşmesi (madde 15 ile aynı turda) | K17, K33, K36 |
| 23 | Kısmi dönemde panelin ana rakamı "Dönem net kârı hesaplanamadı" + "Eksik giderler hariç dönem kârı (kargo ve hizmet bedeli hariç)" olarak satıcıya anlaşılır mı? Satıcı bu rakamı net kâr sanıyor mu? Etiket önerisi? | K39 Revizyon 1 dönem net kârını kısmi dönemde null yapar; yeni bağlanan her hesap ilk günlerde bu ekranı görür | Hasan ile 3-5 satıcıya panel taslağı gösterimi (ürün kararı) | K37, K39; G42, G49 |
| 24 | Mali müşavir, daha önce kendisine verilmiş bir NetKâr dönem raporunun ayar değişikliğiyle (geriye tarihli tarife, düzeltilen hizmet bedeli) yeniden hesaplanmasını nasıl karşılar: düzeltilmiş raporu mu ister, yoksa verildiği günkü raporun aynen yeniden üretilebilmesini mi? "Kapanmış ay" (KDV beyannamesi verilmiş, ekstresi ödenmiş) için NetKâr'da kilit beklenir mi? | K43 geçmişi etkileyen değişikliği onaylı ve izli yapar, kilitlemez; K44 raporu ayar sürümüyle damgalar. Müşavir kilit isterse "dönem kapatma" ayrı özellik olur (ADR-0007 §2.2 seçenek b) | Müşavir görüşü; Hasan'ın müşaviriyle bir görüşme | K42, K43, K44 |
| 25 | Muhasebede kayıtların silinmeyip düzeltme kaydıyla düzeltilmesi uygulamasının NetKâr ayar geçmişine benzetilmesi (geri çekilen ayar silinmez, "geri çekildi" işaretlenir) yerinde mi? Ayar geçmişinin saklama süresi hesabın diğer verileriyle aynı (abonelik süresi + 30 gün, research/03 §2.8 öneri tablosu) olmalı mı, yoksa dışa aktarılmış raporların daha uzun saklanması beklenir mi? | K42 saklama süresini hesabın diğer verilerine bağlar. NetKâr raporunun yasal defter ya da belge sayılmadığı bir varsayımdır (satıcının finans verisinde NetKâr veri işleyendir, research/03 §2.1); müşavirle teyit edilmeli | Müşavir görüşü (benzetme ve süre); KVKK yönü avukata (ADR-0007 §7) | K42 |
| 26 | Varsayılan desi tarihsizdir (K34): değiştirmek siparişinde desi olmayan TÜM geçmiş satırların kargo tahminini değiştirir. Satıcılar varsayılan desiyi sık değiştirir mi; geçerlilik tarihli olmalı mı? | K43 her varsayılan desi değişikliğini (ilk giriş hariç) geçmişi etkileyen değişiklik sayar ve onay ister | Hasan; pilot hesapta `cargoDeci` boş sipariş oranı (madde 17 ile aynı ölçüm) | K34, K43 |

---

## 10. Kural listesi (indeks)

| Kimlik | Kural | Güven |
|---|---|---|
| K01 | Sayı türü ve yuvarlama | Yüksek |
| K02 | KDV dahil / hariç dönüşümü | Yüksek |
| K03 | Brüt satış ve indirim ayrımı | Yüksek / Orta |
| K04 | Satış geliri (tahmini, kesin) | Yüksek / Orta |
| K05 | Ekstre işlem tipleri ve işaret kuralı | Orta |
| K06 | Komisyon matrahı ve tutarı | Yüksek |
| K07 | Komisyon tutarının KDV'si | Orta |
| K08 | Gönderi kargo bedeli ve fatura KDV tespiti | Yüksek / Doğrulanmadı |
| K09 | Kargonun satırlara dağıtımı | Orta |
| K10 | Tam iade | Yüksek / Orta |
| K11 | Kısmi iade | Yüksek / Orta |
| K12 | İade kargo bedeli | Yüksek |
| K13 | Platform hizmet bedeli | Doğrulanmadı |
| K14 | Ceza ve sınıflandırılmış kesintiler | Doğrulanmadı |
| K15 | Reklam | Orta / Doğrulanmadı |
| K16 | Ürün maliyeti | Yüksek |
| K17 | Değişken giderler | Yüksek |
| K18 | E-ticaret stopajı | Yüksek / Orta |
| K19 | Erken ödeme | Yüksek / Doğrulanmadı |
| K20 | KDV etkisi | Yüksek |
| K21 | Nakit akışı satırı | Orta |
| K22 | Durum makinesi | Yüksek |
| K23 | Fark tespiti ve beklenmeyen kesinti | Orta |
| K24 | Dağıtım algoritması | Yüksek |
| K25 | Toplulaştırma, marj, ROAS | Yüksek / Orta |
| K26 | İptal | Yüksek |
| K27 | Eşleştirme anahtarları | Yüksek / Doğrulanmadı |
| K28 | Ekstre iç tutarlılık | Yüksek |
| K29 | Teslimat ücreti | Düşük |
| K30 | Kurumsal faturalı sipariş | Düşük |
| K31 | Kargo tazmini (TEX) | Düşük |
| K32 | Gramaj provizyonu, işçilik bedeli | Düşük |
| K33 | Kâr ayarlarının kapsamı, düzeyi, varsayılanları, doğrulama sınırları | Yüksek (iç kural) |
| K34 | Kargo tarifesi çözümleme (firma, yedek, desi, sürüm) | Yüksek / Doğrulanmadı (tarife modeli) |
| K35 | Platform hizmet bedeli tahmini: tanımsız 0 değildir | Yüksek |
| K36 | Değişken gider geçerliliği | Yüksek |
| K37 | Eksik kalem, net kâr, eksik giderler hariç kâr, kesin zarar | Yüksek |
| K38 | Tanımsız tahmin fark karşılaştırmasına girmez | Yüksek |
| K39 | Dönem kısmi kâr, marj ve tam satırlar (Revizyon 1: kısmi dönemde dönem net kârı null, dönem eksik giderler hariç kâr) | Yüksek / Orta (dönem düzeyi gider) |
| K40 | Kesinlik etiketi | Yüksek |
| K41 | İade kaydı gelmemiş tam iade | Orta |
| K42 | Ayar kayıtlarının değişmezliği ve tarihçesi | Yüksek (iç kural) |
| K43 | Geçmişi etkileyen ayar değişikliği: etki tarihi ve onay | Yüksek (iç kural) / Doğrulanmadı (müşavir beklentisi, §9 madde 24) |
| K44 | Rapor ayar damgası ve yeniden üretilebilirlik | Yüksek (iç kural) |

K29 ile K32 v1 altın testlerinde yoktur; pilot verisi ve §9 cevapları geldikten sonra senaryo eklenecek.

---

## 11. Uygulama notları (kâr motoru kodu, `services/api/app/profit/`)

Bu bölüm kuralları değiştirmez; kuralların koddaki karşılığını ve genişletme noktalarını anlatır. Kural ile kod
çelişirse bu belgenin §1-§10 kısmı doğrudur (önce belge, sonra betik, sonra altın test, kod en son değişir).

### 11.1 İlkeler
- **Saf ve deterministik:** `calculate_profit(ProfitInput) -> ProfitResult`. Veritabanı, ağ, dosya, rastgelelik ve
  saat yok; tarihler girdi olarak gelir (sipariş günü İstanbul takvim günü, dönüşümü `schema_v1.istanbul_day`).
  `tests/test_profit_purity.py` yasak içe aktarmaları, saat çağrılarını, `float` ve em dash kullanımını denetler.
- **Yalnız Decimal ve Fraction:** Bölme gerektiren her işlem tam hassasiyetli `Fraction` ile yapılır, kuruşa tek
  yuvarlama fonksiyonu (`money.rnd`, ROUND_HALF_UP) ile inilir (K01). Ara adımlar yuvarlanmaz.
- **Girdi ve çıktı değişmezdir** (frozen dataclass); motorun iç birikim nesnesi (`work.LineWork`) dışarı sızmaz.
- **Tahmin uydurulmaz, eksik kalem sessizce 0 sayılmaz (v0.2, K33-K38):** kullanıcı ayarı yoksa (kargo tarifesi
  K34, hizmet bedeli tahmini K35) ya da maliyet yoksa (K16) kalem tutarı 0 yazılsa da kaynağı `eksik`tir, satır
  uyarısı verilir, kalem `eksik_kalemler` listesine girer ve satırın `net_kar`, `toplam_gider`,
  `net_kar_marji_yuzde` alanları null olur; bilinen giderlerle kâr ayrı alanda (`eksik_giderler_haric_kar`)
  verilir (K37). Tanımsız tahmin K23 karşılaştırmasına girmez (K38). Motorun ayar varsayılanı "tanımsız"dır
  (None), 0 değildir. K29-K32 için tahmini hesap yoktur, yalnız "teyit bekliyor" bayrağı vardır.

### 11.2 Modül yapısı ve kural eşlemesi

| Modül | İçerik | Kurallar |
|---|---|---|
| `money.py` | `rnd`, `split_inclusive/exclusive`, `allocate` (en büyük kalan), `percent_of`, `ratio`, `fmt`, `to_decimal` | K01, K02, K24 |
| `enums.py`, `constants.py` | Durum, kaynak, uyarı kodları; ekstre tipi kümeleri ve komisyon işaret tablosu | K05, K14, K22, K26 |
| `settings.py` | `ProfitSettings`, eşikler (`WarningThresholds`), tarife, değişken gider tanımı | §8, K07, K08, K17, K23 |
| `inputs.py` | Girdi alan modeli (`Order`, `OrderLine`, `SettlementRow`, `OtherFinancialRow`, `CargoInvoice`, `Claim`, `CostRecord`, `AdRecord`, `CompensationTicket`) ve `ProfitInputError` | K03, K27 |
| `settlement.py` | Ekstre eşleştirme, satış, iade, komisyon, hakediş düzeltmesi, iç tutarlılık | K04-K07, K11, K27, K28 |
| `costs.py` | İade kalemi sayımı, ürün maliyeti (geçerlilik tarihi), değişken giderler | K10, K16, K17 |
| `shipping.py` | Tarife tahmini, fatura KDV tespiti, kesin kargo, iade kargo, dağıtım | K08, K09, K12 |
| `fees.py` | Platform hizmet bedeli, ceza, erken ödeme, stopaj ekstresi, sınıflandırılamayan kesinti | K13, K14, K18 (ekstre), K19 |
| `advertising.py` | Reklam dağıtımı (eşlenen, eşlenmeyen, satışsız ürün) | K15 |
| `lines.py` | Durum makinesi, tahmini-kesin fark tespiti, KDV etkisi, nakit akışı, satır çıktısı | K18, K20-K23, K25 |
| `aggregate.py` | Ürün ve dönem toplulaştırma, marj, ROAS, başabaş ROAS | K25 |
| `pending.py` | K29-K32 yer tutucu: teyit bekleyen kural kaydı ve bayrak | K29-K32 |
| `engine.py` | Adımları sırayla çağıran giriş noktası | hepsi |
| `schema_v1.py` | Altın test şeması (Trendyol alan adları + `netkar_` alanları) <-> alan modeli | README şeması |
| `work.py`, `results.py` | İç birikim nesnesi; değişmez çıktı modeli (`wire` üst verisiyle şema anahtarları) | K25 |

v0.2 (K33-K41) eşlemesi: `settings.py` sürümlü ayarlar ve gün bazlı çözümleme (K33-K36); `shipping.py` tarife
seçimi, yedek firma, varsayılan desi (K34); `fees.py` tanımsız hizmet bedeli (K35); `costs.py` değişken gider
geçerliliği ve claim'siz iade (K36, K41); `lines.py` eksik kalem, kesin zarar, karşılaştırma, kesinlik (K37,
K38, K40); `aggregate.py` ürün ve dönem eksik sayıları, tam satırlar, kısmi marj, kesinlik (K37, K39, K40).
Uygulama sırası ve kabul ölçütleri: `docs/adr/0006-kar-ayarlari.md` §6.

Adım sırası (`engine.calculate_profit`): satır kurulumu -> ekstre eşleştirme ve satış/iade/komisyon -> iade
kalemleri ve maliyet -> kargo -> platform hizmet bedeli -> diğer finansallar -> değişken giderler -> reklam ->
satır kırılımı -> ürün ve dönem toplamı. Sıra anlamlıdır: dağıtımlar önceki adımların yuvarlanmış tutarlarını
ağırlık olarak kullanır (örn. reklam ve değişken gider net satışı, kargo ve hizmet bedeli KDV hariç satışı).

### 11.3 Belgenin açık bırakıp motorun karar verdiği noktalar
Bunlar altın testleri etkilemez; pilot verisi gelince §9 ile birlikte gözden geçirilmelidir.
1. **K27 adet oranı paylaşımı:** Aynı barkod aynı siparişte birden çok satırdaysa ekstre satırının tutarı
   satırlara adet oranında paylaştırılır (K27 metni). Referans betik bunu uygulamaz (her eşleşen satıra tam tutar
   verir); altın testlerde bu durumun ekstreli senaryosu yoktur (G33'te aynı barkod var ama ekstre yok).
2. **Kesin kargo sipariş düzeyinde:** Kargo faturası kalemleri `orderNumber` ile eşleştiği için (§9 madde 14)
   kesin tutar siparişin aktif, satıcı anlaşmasız tüm paketlerinin satırlarına **bir kez** dağıtılır; tahmini
   tutar paket düzeyinde kalır. Tek paketli siparişte sonuç referansla aynıdır. Referans, çok paketli siparişte
   fatura kalemini her pakete ayrı ayrı uygular (çift sayım riski). İade kargosu da sipariş düzeyindedir.
3. **Bağlanamayan platform hizmet bedeli satırı:** Siparişi bilinmeyen, tüm satırları iptal olan ya da
   `paymentOrderId`'si hiçbir satışlı siparişle eşleşmeyen (veya null olan) satır `siniflandirilmamis_kesinti`
   olur ve `SINIFLANDIRILMAMIS_KESINTI` uyarısı verir (K14 ihtiyat ilkesi). Referans bu durumda hata verir ya da
   tutarı sessizce düşürür.
4. **Nakit hareketi tipleri:** K14'e uygun olarak `PaymentOrder`, `WireTransfer`, `IncomingTransfer` gider
   sayılmaz (referans yalnız `PaymentOrder`'ı atlar). `CashAdvance` erken ödeme nakit girişidir (K19).
5. **Bilinmeyen ekstre tipi:** Komisyon işaret tablosunda olmayan `settlements` tipi hesaba katılmaz, satıra
   `teyit_bekliyor: ["K05"]` bayrağı konur (referans hata verir).
6. **Varsayılan ayarlar (v0.2'de değişti, K33):** tüm kullanıcı ayarları tanımsızdır: hizmet bedeli tahmini
   None (v0.1'de 0 idi ve "tahmini" etiketli uyarısız 0 üretiyordu, denetim S4 Y-02), kargo tarifeleri boş,
   varsayılan desi None, değişken gider yok. Referans betiğin kurgusal tarifesi motorun varsayılanı değildir;
   altın testler ayarları girdide taşır (G42, G48 üretim varsayılanını açıkça taşır).
7. **Stopaj ekstre farkı toleransı** ayrı sabit değil, `yuvarlama_toleransi` (0,05) ayarıdır.
8. **Uyarı sırası ve tekrarı:** Satır uyarıları ilk görülme sırasıyla tekrarsız listelenir; testler kümeyle
   karşılaştırır.

### 11.4 K29-K32 (düşük güvenli kurallar)
- `pending.LOW_CONFIDENCE_RULES`: teyit bekleyen kuralların künyesi (kimlik, başlık, §9 madde numarası). Arayüz
  "teyit bekliyor" rozetini bu kayıttan ve satır/dönem `teyit_bekliyor` alanından üretir.
- **K29** (`DeliveryFee`, `DeliveryFeeCancel`): belgedeki v1 kuralı uygulanır (satış gibi gelir, komisyon işareti
  +1/-1; tek başına satırı `settled` yapmaz) ve satır `K29` bayrağı taşır.
- **K30** (`TyDiscount`, `TyCoupon`): gelire ve komisyona katılmaz, satır `K30` bayrağı taşır; alacak takibi
  henüz yok.
- **K32** (`ProvisionPositive/Negative`): satış tipi olarak işlenir (K04), satır `K32` bayrağı taşır; işçilik
  bedeli stopaj ayrımı yoktur.
- **K31** (TEX tazmini): `ProfitInput.compensation_tickets` kabul edilir, tutar hesaba katılmaz, dönem
  `teyit_bekliyor` listesine `K31` eklenir.

### 11.5 Genişletme noktaları
- **Yeni ekstre tipi:** `constants.COMMISSION_SIGN` (işaret), gerekirse `REVENUE_TYPES`, `REFUND_TYPES`,
  `ADJUSTMENT_TYPES`; teyit bekliyorsa `pending.ROW_TYPE_RULES`. Önce bu belgedeki K05 tablosu güncellenir.
- **Yeni gider kalemi:** (1) kural bu belgeye, (2) `work.LineWork` alanları, (3) kural modülünde bir `apply_*`
  işlevi, (4) `engine.calculate_profit` içinde doğru sırada çağrı, (5) `lines.build_line_result` (toplam gider,
  KDV, nakit akışı), (6) `results.py` alanı ve `wire` adı, (7) `aggregate.py` toplamı, (8) altın test senaryosu.
- **Teyit gelen düşük güvenli kural:** `LOW_CONFIDENCE_RULES` kaydı ve `ROW_TYPE_RULES` girdisi kaldırılır, hesap
  ilgili modüle taşınır, belge güven düzeyi güncellenir, altın test eklenir.
- **Eşikler ve ayarlar:** `settings.WarningThresholds` ve `ProfitSettings`; yeni ayar eklenince
  `schema_v1._SETTING_FIELDS` tablosuna satır eklenir.
- **Girdi kaynağı:** DB ya da senkron katmanı `ProfitInput` kurar (ayrı iş); `schema_v1.parse_input` altın test
  JSON'unu aynı modele çevirir, `render_result` çıktıyı README şemasına çevirir.

### 11.6 Test ve kapsam
```
cd netkar && make test-profit    # tests/test_profit_*.py, app/profit satır VE dal kapsamı %100 (DB gerekmez)
cd netkar && make lint && make test
```
- `tests/test_profit_golden.py`: 49 senaryo (v0.1'de 41, v0.2'de 48) parametrik, kuruşu kuruşuna (kural: golden README "Motorun testte yapması
  gereken").
- `tests/test_profit_money.py`: yuvarlama sınırları (10,025; -0,005), KDV ayrımı, dağıtım (hypothesis: toplam
  korunur, negatif tutar ve ağırlık, sıfır ağırlık, boş liste, her parça tam payın 1 kuruş yakınında).
- `tests/test_profit_properties.py`: satır kırılımı tutarlılığı, dağıtılan giderlerin paket toplamını koruması,
  ürün ve dönem toplamının satır toplamı olması, stopajın kâra girmemesi, determinizm, tam iadede sıfır net satış.
- `tests/test_profit_engine.py`, `test_profit_shipping_fees.py`, `test_profit_ads_aggregate.py`,
  `test_profit_schema.py`, `test_profit_purity.py`: kural dalları, K29-K32 bayrakları, saflık güvenceleri.

---

## 12. Kâr ayarları ve eksik kalemler (K33-K41, v0.2)

Bağlam: denetim `docs/security/denetim_2026-11-09_S4_rapor.md` Y-02 (ayar yokken kargo ve hizmet bedeli 0,
yanlış `BEKLENMEYEN_KESINTI`), O-02 (kısmi dönem marjı), O-03 (`basis` etiketi), O-04 (claim'siz iade). Karar
kaydı, alternatifler, migrasyon ve API: `docs/adr/0006-kar-ayarlari.md` (K42-K44 ve K39 Revizyon 1:
`docs/adr/0007-ayar-tarihcesi-ve-donem-rakami.md`). Altın testler G42-G49; G01-G41'e
yeni alanlar eklendi; v0.2'deki tek değer değişikliği G29 dönem marjıdır (K39), v0.3'te G29 `satir_net_kar_toplami`
ve `donem_net_kar` de null oldu (K39 Revizyon 1).

Bu bölümün ilkesi: **bir gider kalemi yalnız üç yoldan değer alır: kesin kayıt (ekstre, fatura), kullanıcı
beyanı (maliyet, tarife, hizmet bedeli tahmini, değişken gider) ya da bu ikisinden kurala bağlı dağıtım.
Hiçbiri yoksa kalem "eksik"tir; eksik kalem 0 sayılarak net kâra karışmaz.**

### K33 · Kâr ayarlarının kapsamı, düzeyi, varsayılanları ve doğrulama sınırları
- **Düzey:** pazaryeri hesabı (`marketplace_accounts.id`) düzeyi; her kayıt `tenant_id` taşır, RLS ile korunur.
  Kiracı düzeyi ortak varsayılan v1'de yoktur.
- **Gerekçe:** kargo anlaşması ve platform hizmet bedeli Trendyol'da Satıcı ID'ye bağlıdır; bir kiracının iki
  mağazası farklı kargo anlaşmasıyla çalışabilir. İki düzeyli (kiracı + hesap) birleştirme "hangisi geçerli"
  belirsizliği üretir; ikinci mağaza için arayüzde "diğer hesaptan kopyala" yeterlidir.
- **Kullanıcı ayarları:** Trendyol anlaşmalı kargo tarifesi, satıcı anlaşmalı (`whoPays=1`) kargo tarifesi,
  varsayılan desi, platform hizmet bedeli tahmini, değişken giderler (§8 tablosu).
- **Sistem parametreleri (kullanıcıya açık değil):** komisyonun KDV varsayımı (K07), komisyon/kargo/hizmet
  bedeli/reklam KDV oranı (%20, K02), stopaj oranı (%1, K18), uyarı eşikleri (K23), kargo faturası KDV tespit
  toleransı (K08). Gerekçe: bunlar mevzuat ya da platform olgusudur, satıcı tercihi değildir; §9 teyidi
  geldiğinde tek yerde değişmeli; kullanıcının değiştirmesi en olası hata kaynağıdır.
- **Varsayılanlar:** tüm kullanıcı ayarları **tanımsız** başlar ("kullanıcı girer, varsayılan yok"). research/01
  Trendyol kargo tarifesi ya da hizmet bedeli tutarı için kaynak vermez; NetKâr hazır tarife tablosu sunmaz ve
  rakam uydurmaz. **Tanımsız, 0 değildir:** kullanıcı bir kalemi bilerek 0 girebilir (örn. hizmet bedeli
  kesilmiyorsa); bu durumda kalem "tahmini 0"dır ve eksik sayılmaz.
- **Geçerlilik tarihi:** kargo tarifesi sürümü, hizmet bedeli tahmini sürümü ve değişken gider tanımı
  `gecerlilik_baslangic` taşır (değişken giderde isteğe bağlı `gecerlilik_bitis`). Seçim K16 ile aynıdır: sipariş
  günü (`orderDate`, İstanbul takvim günü) ile `başlangıç <= gün` olan en son sürüm. Başlangıçsız sürüm (eski
  golden biçimi) en eski sayılır. Gerekçe: ayar değişikliği geçmiş dönem raporunu değiştirmemeli; özellikle
  değişken giderler hiçbir zaman kesin kayıtla değişmediği için tarihsiz olsaydı paketleme fiyatı güncellemesi
  geçmiş ayların kârını yeniden yazardı.
- **KDV dahil/hariç girişi:** motor tüm ayar tutarlarını **KDV hariç** alır. Kullanıcı kargo tarifesini ve hizmet
  bedelini KDV dahil ya da hariç girebilir; giriş biçimi kayıtta saklanır (`fiyat_kdv_dahil`), motora verilirken
  K02 ile hariçleştirilir: `haric = rnd(dahil / (1 + kargo_kdv_orani/100))`, kademe ya da tutar başına bir kez
  (K01). Örnek: 54,00 dahil -> 45,00; 50,00 dahil -> 41,67; 12,00 dahil hizmet bedeli -> 10,00. Arayüz iki
  değeri de gösterir. Değişken gider K17 gibi KDV hariç tutar + KDV oranıdır (§9 madde 22).
- **Doğrulama sınırları** (NetKâr akıl sağlığı sınırları, Trendyol değeri DEĞİLDİR; API 422 döner):

| Alan | Kural |
|---|---|
| Firma adı | 1-100 karakter, kırpılmış; `*` ayrılmış ad ("diğer firmalar"); kontrol karakteri yok |
| Kademe sayısı | sürüm başına 1-50 |
| Kademe üst desi | `0 < desi <= 1000`, en çok 2 ondalık, kesin artan sırada, tekrar yok |
| Kademe fiyatı | `0 <= fiyat <= 100.000,00`, en çok 2 ondalık (girildiği biçimde, dahil ya da hariç) |
| Varsayılan desi | `null` ya da `0 < desi <= 1000`, en çok 2 ondalık |
| Hizmet bedeli tahmini | `0 <= tutar <= 10.000,00`, en çok 2 ondalık; hesap başına en çok 200 sürüm (`too_many_service_fee_versions`, tarife sürümüyle aynı sınır; AO-01) |
| Büyük sayı | 28 haneyi aşan ya da `1e30` gibi değerler (tamsayı, ondalık, üstel) 500 değil 422 `*_out_of_range` döner (AD-01) |
| Değişken gider | ad 1-80 karakter; tip `siparis_basi`, `adet_basi`, `satis_yuzdesi`; tutar `0 <= x <= 100.000,00` (2 ondalık, KDV hariç; yüzde tipinde yok); oran `0 < x <= 100` (en çok 4 ondalık; yalnız yüzde tipinde); KDV oranı 0, 1, 10, 20; hesap başına en çok 50 tanım |
| Geçerlilik başlangıcı | `2000-01-01 <= tarih <= bugün + 366 gün` (maliyet içe aktarmayla aynı); bitiş başlangıçtan önce olamaz |
| Tekillik | (hesap, anlaşma, firma, başlangıç) tarifede; (hesap, başlangıç) hizmet bedelinde |

- **Sürüm seçimi maliyeti (AO-01):** sürümler motor ayarı kurulurken bir kez sıralanır ve seçim ikili aramayla
  (`bisect`) yapılır; seçim kuralı (`başlangıç <= gün` olan en son sürüm, başlangıçsız en eski) değişmemiştir.
  Hesap başına sürüm sınırı (tarife 200, hizmet bedeli 200, değişken gider 50) rapor ve `GET profit-settings`
  yanıtının büyümesini de sınırlar.
- **Güven:** Yüksek (iç kural). Ayar tutarları kullanıcı beyanıdır; doğruluğu kesin kayıt gelince K23 ile
  izlenir.

### K34 · Kargo tarifesi çözümleme (tahmini gönderi kargosu)
- **Model:** tarife = anlaşma (`trendyol` | `satici`) x firma x sürüm; sürüm = artan üst desi kademeleri (üst
  sınır dahil) ve kademe başına KDV hariç fiyat. Golden şeması: `{"Firma": [[desi, fiyat], ...]}` (başlangıçsız
  tek sürüm, eski biçim) ya da `{"Firma": [{"gecerlilik_baslangic": "2026-10-10", "kademeler": [[desi, fiyat],
  ...]}, ...]}`.
- **Firma eşlemesi:** siparişin `cargoProviderName` metniyle birebir. Arayüz firma adını elle yazdırmaz;
  hesabın siparişlerinde görülen adları önerir (ADR-0006 `carriers` ucu). `*` diğer tüm firmalar için yedektir.
- **Sürüm ve kademe seçimi (sırayla):**
  1. Firmanın sipariş gününde geçerli sürümü varsa **yalnız o** kullanılır. Desi en yüksek kademeyi aşıyorsa
     ya da desi bilinmiyorsa kargo **eksiktir**; `*` yedeğine düşülmez (firma tarifesi bilinirken yedek fiyat
     neredeyse kesin yanlıştır; aşım ücreti modeli §9 madde 16).
  2. Firmanın o gün geçerli sürümü yoksa `*` yedeğinin o gün geçerli sürümü.
  3. İkisi de yoksa kargo **eksik**.
- **Desi sırası:** `cargoDeci` -> `ceil(deci)` -> hesabın `varsayilan_desi`'si -> yok. Varsayılan desi
  kullanıldıysa satır uyarısı `KARGO_DESI_VARSAYILAN` (bilgi; kaynak yine `tahmini`). Varsayılan desi
  `KARGO_DESI_FARKI` karşılaştırmasına girmez (yalnız siparişten gelen desi faturadaki desiyle karşılaştırılır).
- **Eksik kargo:** tutar 0 yazılır ama kaynak `eksik`, uyarı `KARGO_TARIFESI_EKSIK`, kalem `eksik_kalemler`e
  girer (K37). Kargo faturası (K08) gelince kalem `kesin` olur ve eksiklik kalkar; kesin kargo için tarife
  gerekmez. Satıcı anlaşmalı siparişte aynı kural `satici` tarifesiyle uygulanır, kaynak `kullanici`.
- **Örnekler:** G44: Trendyol Express tarifesi 10 Ekim'de değişti; 5 Ekim siparişi desi 2 -> 42,00 (eski
  sürüm), 15 Ekim siparişi -> 45,00 (yeni sürüm). G45 satır 1: "Ornek Kargo" için tarife yok, siparişte desi yok;
  varsayılan desi 3, `*` kademesi `<= 3` -> 50,00 + `KARGO_DESI_VARSAYILAN`. G45 satır 2: Trendyol Express desi 7,
  en yüksek kademe 5 -> eksik (yedeğe düşmez). G42: tarife yok -> iki satırda da eksik.
- **Kaynak:** [PKG] (`cargoProviderName`, `cargoDeci`, `deci`, `whoPays`), [KRG]. **Güven:** Yüksek (iç kural),
  Doğrulanmadı (Trendyol kargo fiyatının firma x desi kademesi olarak ifade edilebildiği, §9 madde 16-17).

### K35 · Platform hizmet bedeli tahmini: tanımsız 0 değildir
- **Ayar:** `platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric`: `null` (tanımsız, varsayılan), tek tutar
  (başlangıçsız) ya da `[{"gecerlilik_baslangic", "tutar_kdv_haric"}, ...]` sürümleri. Sipariş başı tutar,
  sipariş içinde satış oranıyla dağıtılır (K13).
- **Kural:** kesin fatura (K13) dağıtılmamış aktif siparişte:
  - tahmin tanımlıysa (0 dahil): K13 tahmini, kaynak `tahmini`, uyarı yok;
  - tanımsızsa: tutar 0, kaynak `eksik`, satır uyarısı `HIZMET_BEDELI_TAHMINI_EKSIK`, kalem `eksik_kalemler`e
    girer (K37).
- Kesin fatura siparişe dağıtıldıysa (`kesin_dagitim`) ayar gerekmez.
- **Örnek:** G43 satır 1: kargo tahmini 45,00 tanımlı, hizmet bedeli tanımsız -> eksik giderler hariç kâr
  416,58 - 180,00 - 62,49 - 45,00 = 129,09, net kâr null. G48 satır 1: ayar yok ama siparişe bağlı 12,00 KDV
  dahil fatura -> 10,00 `kesin_dagitim`, eksik değil. G44: 5 Ekim 8,00, 15 Ekim 10,00 (sürüm).
- **Kaynak:** [CHE], [OTH] (K13 ile aynı). **Güven:** Yüksek (iç kural); tutarın yapısı Doğrulanmadı (§9 madde 5,
  18).

### K36 · Değişken gider geçerliliği
- **Kural:** her değişken gider tanımı (K17) yalnız sipariş günü `[gecerlilik_baslangic, gecerlilik_bitis]`
  aralığında (uçlar dahil, boş uç sınırsız) olan aktif satırlara uygulanır; `siparis_basi` tipinde sipariş günü
  esas alınır. Tutar değişikliği yeni tanım (yeni başlangıç) ve eskinin bitişi olarak girilir.
- **Tanımsız değişken gider eksik sayılmaz:** kaynak `yok`. Gerekçe: değişken giderler isteğe bağlıdır ve
  gerçekten 0 olabilir (paketlemeyi Trendyol yapıyor, e-fatura paket ücrete dahil); olmaması Trendyol tarafı
  bir kesintinin unutulması değildir. Arayüz kurulumda hatırlatır (ADR-0006 tamlık bloğu).
- **Örnek:** G44: "paketleme" 6,00 (1 Ocak - 9 Ekim) ve 7,50 (10 Ekim'den) -> 5 Ekim satırı 6,00, 15 Ekim
  satırı 7,50.
- **Güven:** Yüksek (iç kural).

### K37 · Eksik kalem, net kâr, eksik giderler hariç kâr ve kesin zarar
- **Eksik olabilen kalemler (kanonik sıra):** `urun_maliyeti` (K16), `kargo_gonderi` (K34), `platform_hizmet_bedeli`
  (K35). Diğer kalemler eksik olamaz: komisyon her zaman sipariş satırının oranından tahmin edilir; iade kargo,
  ceza ve reklam yalnız kayıt varsa vardır (kayıt yoksa 0 doğrudur, kaynak `yok`).
- **Satır:** `eksik_kalemler` kaynağı `eksik` olan kalemlerin kanonik sıradaki listesidir. Boş değilse
  `net_kar`, `toplam_gider`, `net_kar_marji_yuzde` **null**. Her aktif satırda ayrıca:
  `eksik_giderler_haric_kar = net_satis_kdv_haric - (bilinen tüm giderler)`; tam satırda `net_kar`'a, yalnız
  maliyeti eksik satırda `maliyet_haric_katki`'ya eşittir. İptal satırında 0,00 ve `eksik_kalemler` boştur.
- **Diğer bloklar:** `maliyet_haric_katki`, `kdv` ve `nakit_akisi` bilinen kalemlerle hesaplanır (v0.1'de maliyet
  eksikken de böyleydi); satırın `eksik_kalemler`i bu bloklar için de geçerlidir ve panel bunları "eksik kalemler
  hariç" etiketiyle gösterir (§9 madde 21).
- **ZARAR uyarısı:** `net_kar < 0` **ya da** (`net_kar` null **ve** `eksik_giderler_haric_kar < 0`). Gerekçe: eksik
  kalemler negatif olamaz (maliyet, tarife fiyatı, hizmet bedeli `>= 0` doğrulanır), bilinen giderlerle zarar
  eden satır kesin zarardadır (API `loss_reason` mantığıyla aynı, denetim D-02).
- **Ürün:** aktif satırlarından birinde eksik kalem varsa `net_kar` ve marj null; `eksik_giderler_haric_kar`
  = satırların toplamı - `reklam_satissiz`; `eksik_kalem_satir_sayilari` = kalem başına eksik satır sayısı.
  `maliyet_eksik` alanı değişmeden yalnız maliyeti anlatır.
- **Dönem:** `eksik_kalem_satir_sayilari`; özet uyarıları (satır uyarılarının sayımı, yeni kural değil):
  `MALIYET_EKSIK_SATIRLAR_VAR` (mevcut), `KARGO_EKSIK_SATIRLAR_VAR`, `HIZMET_BEDELI_EKSIK_SATIRLAR_VAR`.
- **Neden null, "kısmi bayraklı değer" değil:** eksik kalemi 0 sayıp `net_kar`'ı bir bayrakla döndürmek, bayrağı
  okumayan her tüketicide (sıralama, "en kârlı ürünler", zarar süzgeci, CSV, e-posta özeti, ileride uyarı
  motoru) sayıyı gerçek net kâr yapar; denetimde 4 altın senaryoda zarar bu yolla kâra dönmüştü. Null, hatayı
  görünür boşluğa çevirir; etiketli üst sınır ayrı ve adı ne olduğunu söyleyen alanda (`eksik_giderler_haric_kar`)
  durur. K16'nın maliyet için zaten uyguladığı kuralla tutarlıdır.
- **Örnek:** G42 satır 1 (ayar yok): 416,58 - 180,00 - 62,49 = 174,09 eksik giderler hariç kâr, net kâr null,
  `eksik_kalemler = [kargo_gonderi, platform_hizmet_bedeli]`, kesinlik `eksik`. v0.1'de aynı satır net kâr 174,09
  olarak görünüyordu (denetim: "G01 119,09 -> 174,09"). G43 satır 2: maliyetsiz, hizmet bedeli tanımsız ucuz ürün,
  41,67 - 6,25 - 40,00 = -4,58 -> net kâr null ama `ZARAR` (kesin zarar).
- **Güven:** Yüksek (iç kural).

### K38 · Tanımsız tahmin fark karşılaştırmasına girmez (K23 eki)
- **Kural:** `karsilastirma.kargo_gonderi_tahmini`, tarife satırı fiyatlayamadıysa (K34 eksik) **null**;
  `platform_hizmet_bedeli_tahmini`, tahmin tanımsızsa (K35) **null** (v0.1'de 0,00 idi). Bir kalem
  `karsilastirilan_tahmini_toplam` ve `karsilastirilan_kesin_toplam`'a **yalnız tahmini tanımlı VE kesin değeri
  gelmişse** girer; yoksa iki toplamdan da çıkar. Açıkça 0 girilmiş tahmin tanımlıdır ve girer (kullanıcının
  beyanıyla gerçek kesinti farkı anlamlıdır). Komisyon tahmini her zaman tanımlıdır.
- **Sonuç:** sıfır ya da tanımsız tahmin `BEKLENMEYEN_KESINTI` üretemez; uyarı yalnız kullanıcının (ya da
  siparişin) beklentisiyle gerçek kesinti arasındaki farkı ölçer.
- **Varsayılan desi izi (denetim AD-05):** tahmini kargo siparişte desi olmadığı için hesabın varsayılan desisiyle
  (K34) fiyatlandıysa `karsilastirma.kargo_tahmini_varsayilan_desi` **true** olur (aksi halde false; tarife
  fiyatlayamadıysa da false). Varsayılan desi bir beklenti değil yer tutucudur: fatura gelince `KARGO_DESI_VARSAYILAN`
  uyarısı K34 gereği kalkar (uyarı yalnız tahmin fiyatlanan faturasız durumda), ama fark varsayımdan doğuyor olabilir;
  panel bu alan true iken `BEKLENMEYEN_KESINTI` yanında "fark varsayılan desiden kaynaklanabilir" ipucu göstermelidir.
  Alan yalnız bilgidir: toplamlar, fark, eşik ve uyarı kümesi DEĞİŞMEZ (K38 kuralı ve altın beklentiler aynı).
  Kuralın kendisini değiştirmek (varsayılan desili tahmini karşılaştırmadan çıkarmak) alan kararıdır; açık madde.
- **Örnek:** G48 satır 1: ayar yok, kargo 45,00 ve hizmet bedeli 10,00 kesin geldi. v0.1: tahmini toplam 62,49,
  kesin 117,49, fark 55,00 > 5,00 -> yanlış `BEKLENMEYEN_KESINTI`. v0.2: iki kalem de karşılaştırma dışı, fark 0,00.
- **Ölçüm (betik):** G01-G41 üretim varsayılanıyla (ayar yok) hesaplandığında v0.1 kurallarıyla 28 satırda altın
  sonuçta olmayan `BEKLENMEYEN_KESINTI` çıkıyor, v0.2 kurallarıyla 0.
- **Güven:** Yüksek (iç kural).

### K39 · Dönem kısmi kâr, marj ve tam satırlar (denetim O-02)
- **Tam satır:** aktif (iptal değil) ve `eksik_kalemler` boş satır. `net_kar_kismi` = tam satır sayısı < aktif satır
  sayısı (v0.1'de yalnız maliyet eksikliğine bakıyordu; artık kargo ve hizmet bedeli eksikliği de kısmi yapar).
- **Pay** (**Revizyon 1 ile değişti**, aşağıda: kısmi dönemde bu iki alan null)**:** `satir_net_kar_toplami` =
  tam satırların net kârı; `donem_net_kar` = `satir_net_kar_toplami` - `donem_duzeyi_giderler_toplami`. Dönem düzeyi giderler (satışsız ürün reklamı, dağıtılamayan reklam, bağsız
  ceza, erken ödeme bedeli, sınıflandırılmamış kesinti) dönemin tamamına aittir ve ihtiyatla tam düşülür
  (§9 madde 20).
- **Marj:** dönem `net_kar_marji_yuzde` tam dönemde `donem_net_kar / net_satis_kdv_haric x 100`; **kısmi dönemde
  null** (pay tam satırlardan, payda tüm satırlardan gelirdi: v0.1 hatası). Kısmi dönemde gösterilebilecek tek
  marj `tam_satirlar.net_kar_marji_yuzde`'dir: `tam_satirlar.net_kar / tam_satirlar.net_satis_kdv_haric x 100`,
  pay ve payda aynı satır kümesinden, dönem düzeyi giderler hariç; panel etiketi "maliyeti ve giderleri tam
  satırların marjı (dönem giderleri hariç)".
- **`tam_satirlar` bloğu:** `satir_sayisi`, `net_satis_kdv_haric`, `urun_maliyeti`, `komisyon`, `kargo_gonderi`,
  `kargo_iade`, `platform_hizmet_bedeli`, `ceza`, `reklam`, `degisken_giderler`, `toplam_gider`, `net_kar`,
  `net_kar_marji_yuzde`; yalnız tam satırların yuvarlanmış değerlerinin toplamıdır.
- **Özdeşlikler (betik ve motor testleri her senaryoda denetler; Revizyon 1 I2, I3'ü değiştirir ve I5, I6'yı
  ekler):**
  - (I1) `tam_satirlar.toplam_gider` = `tam_satirlar` gider alanlarının toplamı;
  - (I2) `tam_satirlar.net_satis_kdv_haric - tam_satirlar.toplam_gider = tam_satirlar.net_kar = satir_net_kar_toplami`;
  - (I3) `donem_duzeyi_giderler_toplami` = `donem_duzeyi_giderler` alanlarının toplamı ve
    `satir_net_kar_toplami - donem_duzeyi_giderler_toplami = donem_net_kar`;
  - (I4) `net_kar_kismi = false` ise üst düzey alanlarla `net_satis_kdv_haric - (urun_maliyeti + komisyon +
    kargo_gonderi + kargo_iade + platform_hizmet_bedeli + ceza_satirlara_dagitilan + reklam_satirlara_dagitilan +
    degisken_giderler) - donem_duzeyi_giderler_toplami = donem_net_kar`.
- **Üst düzey kalem alanları** (`net_satis_kdv_haric`, `komisyon`, ...) tüm aktif satırların bilinen
  değerleridir (eksik kalem 0); kısmi dönemde (I4) tutmaz, panel bunlardan şelale/toplam gider çizmez,
  `tam_satirlar` bloğunu kullanır.
- **Örnek** (v0.2; `donem_net_kar` değeri Revizyon 1 ile null oldu)**:** G46: A tam (net 119,09), B maliyetsiz,
  17,35 sınıflandırılmamış kesinti. `donem_net_kar` 101,74; dönem marjı null (v0.1 kuralı 101,74 / 708,25 = 14,36 verirdi); `tam_satirlar`: net satış 416,58, toplam gider
  297,49, net kâr 119,09, marj 28,59. G29 (değişen tek eski değer): dönem marjı 19,60 -> null; tam satır marjı
  138,80 / 416,58 = 33,32.
- **Güven:** Yüksek (tanım), Orta (dönem düzeyi giderlerin kısmi dönemde tam düşülmesi, §9 madde 20).

#### K39 Revizyon 1 (10 Kasım 2026, denetim AO-03): kısmi dönemde dönem net kârı null

**Durum:** yürürlükte; yukarıdaki K39 metninin "Pay" maddesini, I2 ve I3 özdeşliklerini ve G46 örneğindeki
`donem_net_kar` değerini geçersiz kılar. Tam satır tanımı, `net_kar_kismi`, marj kuralı ve `tam_satirlar` bloğu
aynen sürer. Karar kaydı: `docs/adr/0007-ayar-tarihcesi-ve-donem-rakami.md` §1.

**Sorun (AO-03):** v0.2'de kısmi dönemde `donem_net_kar` = tam satırların net kârı eksi dönemin TÜM dönem düzeyi
giderleri idi ve yanında yalnız `net_kar_kismi=true` bayrağı vardı. Bu, ADR-0006 §2.1'in satır düzeyinde
reddettiği "bayraklı kısmi sayı" kalıbının dönem düzeyindeki karşılığıdır: bayrağı okumayan her tüketici (panel
başlık rakamı, CSV, e-posta özeti, ileride uyarı motoru) sayıyı gerçek dönem net kârı sanar. Ayarsız yeni hesapta
rakam 0,00 olur (G42), dönemde sınıflandırılmamış kesinti varsa uydurma bir zarar olur (G49: -17,35). Pay alt
kümeden, dönem giderleri tüm dönemden gelir: O-02'de marj için düzeltilen karışık taban hatasının tutar biçimidir.

**Kurallar:**
1. `satir_net_kar_toplami`: tam dönemde tüm aktif satırların net kârı; **kısmi dönemde null** (toplamın bir
   terimi bilinmiyorsa toplam bilinmez). Tam satırların toplamı her zaman `tam_satirlar.net_kar`'dadır.
2. `donem_net_kar`: tam dönemde `satir_net_kar_toplami - donem_duzeyi_giderler_toplami`; **kısmi dönemde null**.
   `net_kar_marji_yuzde` kısmi dönemde null kalır (değişmedi).
3. **Yeni alan `donem_eksik_giderler_haric_kar`** (her dönemde sayı): `Σ aktif satır eksik_giderler_haric_kar -
   donem_duzeyi_giderler_toplami`. Ürün düzeyindeki `eksik_giderler_haric_kar`'ın (K37) dönem karşılığıdır: tüm
   aktif satırlar, bilinen tüm giderler, tüm dönem düzeyi giderler; yalnız eksik kalemler hariç. Tam dönemde
   `donem_net_kar`'a eşittir. Kısmi dönemde eksik kalemler negatif olamadığı için (K37) gerçek dönem net kârının
   **üst sınırıdır**; değeri 0'dan küçükse dönem bilinen giderlerle bile zarardadır (kesin dönem zararı; panel bunu
   "bilinen giderlerle bile zarar" diye gösterir, yeni uyarı kodu yok). Bu alan için marj verilmez (üst sınırın
   oranı yanıltıcıdır; ürün düzeyinde de yoktur).
4. **Tam satır sayısı 0** (`tam_satirlar.satir_sayisi = 0`): `tam_satirlar` bloğu boş kümenin toplamıdır; para
   alanları 0,00, marj null (net satış 0). Blok null yapılmaz (şema sabit kalır); panel bu durumda bloğu
   göstermez. Dönemin gösterilebilecek tek kâr rakamı `donem_eksik_giderler_haric_kar`'dır, eksik kalem satır
   sayılarıyla (`eksik_kalem_satir_sayilari`) ve kurulum bağlantısıyla birlikte (G42, G43, G49).
5. Dönem kesinliği, uyarıları, `kdv_etkisi` ve `nakit_akisi` değişmedi (bilinen kalemlerle, K37 ve §9 madde 21).

**Neden bu biçim (ADR-0006 §2.1 ile tutarlılık):** satırda olduğu gibi dönemde de "net kâr" adını taşıyan alan
ya gerçek değeri taşır ya null'dır; bilinen kısım adı ne olduğunu söyleyen ayrı alandadır (`eksik_giderler_haric_kar`
satırda ve üründe, `donem_eksik_giderler_haric_kar` dönemde). Reddedilenler:

| Alternatif | Neden reddedildi |
|---|---|
| v0.2: `donem_net_kar` sayı + `net_kar_kismi` bayrağı | ADR-0006 §2.1'in satırda reddettiği kalıp; AO-03 |
| Denetim önerisi: tam satırların dönem giderleri dahil net kârı ayrı alanda (`tam_satirlar_donem_giderleri_dahil_net_kar`) | Pay tam satır alt kümesinden, dönem giderleri tüm dönemden: karışık taban (O-02); adı doğru olsa da anlamlı bir büyüklük değil |
| Yalnız `tam_satirlar.satir_sayisi = 0` iken null | 100 satırdan 1'i tam iken aynı yanıltıcı sayı sürer; kural keyfi bir eşiğe bağlanır |
| Dönem giderlerini tam satırlara orantılı dağıtıp "tam satırların dönem net kârı" vermek | Dağıtım anahtarı uydurmadır; dönem giderleri tam da satıra bağlanamadığı için dönem düzeyindedir (K14, K15, K19) |
| `donem_eksik_giderler_haric_kar` için marj | Üst sınırın oranı marj gibi okunur; kısmi dönemde gösterilebilecek marj yalnız `tam_satirlar.net_kar_marji_yuzde` |

**Özdeşlikler (yeni hâli; betik `degismezler` ve motor özellik testleri her senaryoda denetler):**
- (I1) değişmedi: `tam_satirlar.toplam_gider` = `tam_satirlar` gider alanlarının toplamı.
- (I2) `tam_satirlar.net_satis_kdv_haric - tam_satirlar.toplam_gider = tam_satirlar.net_kar`; `net_kar_kismi =
  false` ise ayrıca `= satir_net_kar_toplami`.
- (I3) `donem_duzeyi_giderler_toplami` = `donem_duzeyi_giderler` alanlarının toplamı. `net_kar_kismi = false` ise
  `satir_net_kar_toplami - donem_duzeyi_giderler_toplami = donem_net_kar`; `net_kar_kismi = true` ise
  `satir_net_kar_toplami`, `donem_net_kar` ve `net_kar_marji_yuzde` null.
- (I4) değişmedi: tam dönemde üst düzey kalem alanlarıyla `donem_net_kar`.
- (I5, yeni) `donem_eksik_giderler_haric_kar = Σ aktif satır eksik_giderler_haric_kar - donem_duzeyi_giderler_toplami`;
  `net_kar_kismi = false` ise `= donem_net_kar`.
- (I6, yeni) `Σ ürün eksik_giderler_haric_kar - (donem_duzeyi_giderler_toplami - reklam_satissiz_urunler) =
  donem_eksik_giderler_haric_kar` (ürün alanı satışsız reklamı zaten düşer).

**Örnekler (elle):**
- G46: `donem_net_kar` 101,74 -> null; `donem_eksik_giderler_haric_kar` = 119,09 + 184,17 - 17,35 = 285,91;
  `tam_satirlar` aynen (net kâr 119,09, marj 28,59).
- G49 (yeni): ayar yok, tek satır, 17,35 sınıflandırılmamış kesinti; tam satır 0. `donem_net_kar` null (v0.2:
  0,00 - 17,35 = -17,35); `donem_eksik_giderler_haric_kar` = 174,09 - 17,35 = 156,74; `tam_satirlar` 0,00, marj null.
- G42: 174,09 + 119,17 = 293,26 (v0.2 `donem_net_kar` 0,00). G43: 129,09 + (-4,58) = 124,51. G45: 51,67 + 89,17 =
  140,84. G48: 119,09 + 74,17 = 193,26. G29: 138,80 + 214,46 = 353,26 (214,46 = 291,67 - 52,50 - 20,59 - 4,12).
- Tam dönem: G44 229,68 = `donem_net_kar`; G47 -344,16 = `donem_net_kar`.

**Değişen eski değerler** (betik `IZINLI_FARKLAR` ve `ELLE`): G29 `satir_net_kar_toplami` ve `donem_net_kar`
138,80 -> null; G42 ve G43 ikisi 0,00 -> null; G45 51,67 -> null; G46 119,09 / 101,74 -> null; G48 119,09 ->
null. Diğer tüm eski alanlar aynıdır; `donem_eksik_giderler_haric_kar` 49 senaryonun hepsine eklendi.

**Ölçüm (betik, Y-02 tekrarı):** G01-G41 üretim varsayılanıyla (ayar yok) hesaplandığında 41 dönemin 39'u kısmidir;
v0.2'de 39'unun hepsinde `donem_net_kar` sayıydı, Revizyon 1 ile 0.

**API ve panel:** rapor `summary` yanıtında `donem_net_kar` ve `satir_net_kar_toplami` null olabilir (şema
`Amount | None`), `donem_eksik_giderler_haric_kar` aynı adla eklenir. Panel kuralı ADR-0007 §5.

**Güven:** Yüksek (tanım), Orta (dönem düzeyi giderlerin tam düşülmesi, §9 madde 20).

### K40 · Kesinlik etiketi (denetim O-03)
- **Satır `kesinlik`:**
  - `iptal`: satır iptal (K26);
  - `eksik`: `eksik_kalemler` boş değil;
  - `kesin`: tüm kalem kaynakları (`kaynaklar` bloğunun her alanı, satış ve komisyon dahil) `kesin`,
    `kesin_dagitim`, `kullanici`, `eslesen` ya da `yok` **ve** `teyit_bekliyor` boş;
  - `tahmini`: diğer her durum (en az bir kalem `tahmini` ya da `dagitim_tahmini`, ya da K29-K32 teyidi bekliyor).
- **Tanım:** "kesin" = hiçbir kalem NetKâr tahmini değil: değerler ekstre/fatura kaydından, kullanıcının kendi
  beyanından (maliyet, satıcı anlaşmalı kargo tarifesi, değişken gider) ya da bunların kurala bağlı dağıtımından
  gelir. Durum (`settled`) tek başına kesinlik değildir: ekstreli satırda kargo faturası ya da hizmet bedeli
  faturası gelmemiş olabilir.
- **Ürün ve dönem `kesinlik`:** aktif satır yoksa `yok`; herhangi biri `eksik` ise `eksik`; hepsi `kesin` ise
  `kesin`; aksi halde `tahmini`. Dönem ayrıca `kesinlik_satir_sayilari` (`kesin`, `tahmini`, `eksik`) verir.
- **API:** `basis` yalnız "ekstreli satır oranı" anlamında kalır (`statement_basis` adıyla); panelin "kesin"
  rozeti yalnız motor `kesinlik = kesin`'den türetilir (ADR-0006 §5).
- **Örnek:** G48 satır 1: ayar yok ama satış, komisyon, kargo (fatura), hizmet bedeli (siparişe bağlı fatura)
  kesin, maliyet kullanıcı -> `kesin`. G02: settled ama hizmet bedeli tahmini -> `tahmini`. G23: dört satır
  `kesin`. G47: settled/adjusted ama maliyet askıda (K41) -> `tahmini`. `teyit_bekliyor` kuralı altın testte yok
  (K29-K32 senaryosu yok); motor birim testiyle kilitlenir.
- **Güven:** Yüksek (iç kural).

### K41 · İade kaydı (claim) gelmemiş tam iade (denetim O-04)
- **Koşul:** satıra eşleşen `Return` satırlarında `Σ (debt - credit) > 0` **ve** satırın kabul edilmiş
  (`Accepted`) iade kalemi sayısı 0. `ManualRefund` (K11, ürün müşteride) kapsam dışıdır.
- **Davranış:**
  - Ürün maliyeti K10'daki gibi **tam gider kalır** (ihtiyat; stoğa dönüş kanıtı claim'dir). Değer değişmez.
  - `kaynaklar.urun_maliyeti = tahmini` (değer kesin değil; satır kesinliği en iyi `tahmini`, K40).
  - Satır uyarısı `IADE_KAYDI_BEKLENIYOR`; dönem özeti `IADE_KAYDI_BEKLENEN_SATIRLAR_VAR`.
  - Bilgi alanları: `iade_kaydi_bekleyen_adet = min(adet, max(1, rnd0(adet x iade_return_dahil /
    satis_dahil)))` (`rnd0`: tam sayıya ROUND_HALF_UP; satış 0 ise `adet`) ve `askidaki_urun_maliyeti =
    rnd(birim_maliyet_kdv_haric x iade_kaydi_bekleyen_adet)` (maliyet yoksa null). Panel: "iade kaydı bekleniyor;
    ürün stoğa dönerse tahmini net kâr: net_kar + askidaki_urun_maliyeti". Koşul yoksa 0 ve null.
  - Claim gelince standart K10 uygulanır; uyarı ve askıdaki tutar kendiliğinden kalkar (motor her senkronda
    baştan hesaplar).
- **Alternatifler:** (a) "stoğa döndü" varsayıp maliyeti düşürmek: reddedildi; kanıtsız maliyet düşürür, iade
  nedeni (kusurlu, hasarlı) bilinmeden kârı şişirir; yanlış yönde hata (zararı kâr göstermek) ürünün vaadine
  daha zararlıdır. (b) `net_kar` null: reddedildi; maliyet ve tutarlar bilinir, belirsiz olan yalnız iade
  adedinin stok durumudur; null, claim gecikmesi boyunca zarar sinyalini listeden siler. (c) Seçilen: ihtiyatlı
  değer + `tahmini` etiket + askıdaki tutarın açıkça gösterilmesi.
- **Sınırlar:** motor saat kullanmaz; "Return'den N gün sonra hâlâ claim yok" yükseltmesi API/uyarı katmanının
  işidir (§9 madde 19). Kısmen gelmiş claim (kabul edilen < beklenen) v1'de kapsam dışıdır (claim varsa claim
  esas alınır).
- **Örnek:** G47 satır 1: tam iade, claim yok; net satış 0, maliyet 180,00 gider, gönderi ve iade kargo 45 + 45,
  hizmet bedeli 10 -> net kâr -280,00, `ZARAR` + `IADE_KAYDI_BEKLENIYOR`, bekleyen adet 1, askıdaki maliyet 180,00
  (claim gelince G16 gibi -100,00). G47 satır 2: 2 adetten 100,00'lık iade; bekleyen adet rnd0(2 x 100 / 200) = 1;
  net satış 83,34, maliyet 80,00, komisyon 12,50, kargo 45, hizmet 10 -> -64,16; askıdaki 40,00.
- **Kaynak:** [CHE] (`Return`), [CLM]. **Güven:** Orta (Return ile claim arasındaki sıra ve gecikme
  Doğrulanmadı, §9 madde 19).

---

## 13. Ayar tarihçesi ve geçmiş dönem raporu (K42-K44, v0.3)

Bağlam: denetim `docs/security/denetim_2026-11-09_kar_ayarlari.md` AO-02. v0.2'de üç yol geçmiş dönem raporunu iz
bırakmadan yeniden yazıyordu: aynı anahtarlı PUT kaydı yerinde eziyordu, DELETE kaydı kalıcı siliyordu, geriye
tarihli yeni sürüm kapanmış dönemi değiştiriyordu; denetim izinde önceki değer ve silinen sürümün kimliği yoktu.
K33'ün sürümleme gerekçesi ("ayar değişikliği geçmiş dönem raporunu değiştirmemeli") yalnız farklı başlangıçlı
sürümler için sağlanıyordu. Karar kaydı, seçeneklerin değerlendirmesi, KVKK ve mali kayıt değerlendirmesi,
migrasyon 0008 taslağı ve API: `docs/adr/0007-ayar-tarihcesi-ve-donem-rakami.md`.

K42-K44 veritabanı, API ve ayar yükleyici kurallarıdır: motorun girdisi (`ProfitSettings`) ve hesap kuralları
değişmez, altın senaryo eklenmez; kabul testleri ADR-0007 §8'dedir.

### K42 · Ayar kayıtlarının değişmezliği ve tarihçesi
- **Kapsam:** kargo tarifesi sürümü, hizmet bedeli tahmini sürümü, değişken gider tanımı (bundan sonra "ayar
  satırı") ve hesabın varsayılan desisi. Ürün maliyeti kayıtları (`product_costs`, K16) kapsam dışıdır; aynı soru
  orada da vardır (ADR-0007 §7 açık madde).
- **Kural:** kaydedilmiş bir ayar satırının iş alanları (anlaşma, firma, başlangıç, bitiş, kademeler, tutar, oran,
  KDV bayrağı ve oranı, ad, tip) bir daha değişmez ve satır uygulama tarafından silinmez. Her yazım üç işlemden
  biridir; R yazımın ayar sürümüdür (`profit_settings.revision`, her yazımda +1, ADR-0006 §3.3):
  - **ekle:** yeni satır, `revision_from = R`;
  - **değiştir:** aynı anahtarlı etkin satır (tarife: anlaşma, firma, başlangıç; hizmet bedeli: başlangıç;
    değişken gider: kayıt kimliği) `revision_to = R`, `end_reason = degistirildi` ile kapanır; yeni satır
    `revision_from = R`, `replaces_id = <eski satır>`;
  - **geri çek:** etkin satır `revision_to = R`, `end_reason = geri_cekildi` ile kapanır; yeni satır yoktur
    (eski DELETE ucunun anlamı).
- **Etkinlik:** `revision_to` boşsa satır etkindir. Satır R sürümünde etkindir: `revision_from <= R` ve
  (`revision_to` boş ya da `R < revision_to`). Motor her zaman tek bir ayar sürümündeki etkin satırlarla çalışır
  (varsayılan: güncel sürüm). Değişken giderin bitiş tarihini değiştirmek (K36 "eskinin bitişi + yeni tanım")
  de bir "değiştir" işlemidir.
- **Varsayılan desi:** hesap satırında (`profit_settings.default_desi`) güncel değer olarak kalır; her değişikliği
  önceki ve yeni değeriyle ayar günlüğüne yazılır. R sürümündeki değer günlükten okunur.
- **Ayar günlüğü:** her ayar sürümü için tek kayıt: sürüm, kim, ne zaman, kalem, işlem, ilgili satır kimlikleri
  (yeni ve yerini aldığı), etki tarihi ve onay (K43). Tarife, hizmet bedeli ve gider tutarları günlükte yoktur
  (değer değişmez satırdadır); varsayılan desi istisnadır (önceki ve yeni değer). Günlük ve satırlar kiracıya
  görünürdür ("ayar geçmişi"), RLS altındadır.
- **Aynı içerik:** etkin satırla birebir aynı içerikli yazım yeni satır, yeni sürüm, günlük ve denetim kaydı
  üretmez (yanıt `changed: false`); tarihçe gürültüsü önlenir.
- **Sınırlar (AO-01 ile):** sürüm sayısı sınırları (tarife 200, hizmet bedeli 200, değişken gider 50) yalnız
  etkin satırları sayar; motor, `GET profit-settings` ve `carriers` yalnız etkin satırları okur. Kapanmış satır
  sayısını yazma hız sınırı (kiracı başına saatte 600, ADR-0006 §3.3) sınırlar; geçmiş ucu sayfalıdır.
- **Denetim izi:** `audit_log` meta'sı işlemin kimliklerini taşır (kalem, işlem, satır ve yerini aldığı satır
  kimliği, anlaşma, firma, başlangıç, gider adı ve tipi, etki tarihi, onay, sürüm); **tutar taşımaz** (ADR-0006
  kuralı sürer). Önceki değer denetim kaydından değil, değişmez satırdan okunur.
- **Saklama:** ayar satırları ve günlük, hesabın diğer verileriyle aynı süre saklanır ve hesapla birlikte silinir
  (research/03 §2.8 öneri tablosu: abonelik süresi + 30 gün). Değişmezlik uygulama rolü (`netkar_app`) içindir;
  hesap silme ve imha işi ayrı, yetkili roldür ve imha kaydı tutar (ADR-0007 §3).
- **Gerekçe:** sürümleme ancak eski değer okunabiliyorsa denetlenebilir. "Bu ay neden değişti" sorusunun cevabı
  (hangi kayıt, kim, ne zaman, önceki değer ne) sistemde durmalıdır. Muhasebedeki "kayıt silinmez, düzeltme
  ayrı kayıtla yapılır" uygulamasına benzer; NetKâr için yasal yükümlülük değil tasarım ilkesidir (§9 madde 25).
- **Revizyon 1 (10 Kasım 2026, bağımsız denetim `docs/security/denetim_2026-11-10_ayar_tarihcesi.md`
  YT-01..YT-10; eski içerik yukarıda aynen durur):**
  - **`created_at` devralma kuralı (YT-08, uygulayıcı sapması 4):** değişken gider "değiştir" işleminde yeni satır
    eskinin `created_at`'ini taşır. Amaç gider dökümünün tanım sırasını korumaktır: yükleyici giderleri
    `created_at, id` ile sıralar; bu kural olmasa değiştirilen gider listenin sonuna gider ve sürümle yükleme R'de
    ve R+1'de farklı sıra verirdi. Bedeli: `created_at` bu kalemde "satırın eklendiği an" değil "tanımın ilk
    oluşturulduğu an"dır. Satırın gerçekten eklendiği an için güvenilir kaynaklar ayar günlüğündeki `changed_at`
    ve eski satırın `ended_at`'idir (adli incelemede `created_at`'e dayanılmaz). Tarife ve hizmet bedeli satırları
    bu kuralı kullanmaz (varsayılan `now()`). Uzun vadede sıralama için ayrı bir `defined_at` ya da `lineage_id`
    sütunu önerilir; o zaman `created_at` gerçek ekleme anı olarak bırakılır.
  - **Değişmezlik tetikleyicisi, `ON DELETE SET NULL` ve veri doldurma (YT-05):** `profit_settings_version_guard`
    kapanmış satırdaki HER güncellemeyi ve etkin satırda kapanış sütunları dışındaki her değişikliği reddeder;
    `entered_by` ve `ended_by` istisna değildir. PostgreSQL referans eylemi (`ON DELETE SET NULL`) referans veren
    tabloda UPDATE yapar ve kullanıcı tetikleyicilerini tetikler: kullanıcı silmede `SET NULL` seçilirse silme
    "kapanmis kar ayari surumu degistirilemez" hatasıyla durur. Aynı çakışma, bir migrasyonun yeni bir sütunu
    mevcut satırlarda `UPDATE` ile doldurmasında doğar (her satır reddedilir). Nasıl aşılır: (1) kullanıcı hesabı
    kapatmada kullanıcı satırını silmek yerine kimliksizleştirmek (ad ve e-posta silinir, kimlik kalır) tercih
    edilir; `SET NULL` kesin seçilirse tetikleyici gövdesi `entered_by`/`ended_by` için yalnız `NOT NULL -> NULL`
    geçişine izin verecek biçimde ayrı bir migrasyonla değiştirilir. (2) Sürümlü tablolarda veri doldurma önce
    doldurup SONRA tetikleyiciyi kurar (0008'in `revision_from` doldurması böyle yapıldı) ya da aynı işlemde
    `ALTER TABLE <tablo> DISABLE TRIGGER trg_<tablo>_version_guard` ... `ENABLE TRIGGER` ile çalışır (tablo sahibi
    rol; işlem sonunda tetikleyicinin yeniden açıldığı testle doğrulanır). 0009'un sıra kuralı tetikleyicileri
    (ekleme, kapanış sürümü, günlük) yalnız `netkar_app` rolüne uygulanır; sahip rolün doldurması onlara takılmaz.
  - **Yükleyici tek sürüm okur (YT-01):** `load_bundle` satırları da başlıkta okunan sürümle süzer
    (`revision_from <= R` ve `revision_to` boş ya da `> R`); başlıktan sonra commit edilen yazım demete sızmaz.
    `summary` tamlığı (`completeness`) motorla aynı demetten hesaplanır; yanıtta damga, rakamlar ve tamlık tek
    sürümdür (önceki denetim AB-02 kapandı).
  - **Başlıksız hesap (YT-03):** 0008 taşıması satırı olup `profit_settings` başlığı olmayan hesap için başlığı
    `revision = 1` ile önce oluşturur; böylece etkin satırı olan hesapta damga 0 olmaz ve ilk değiştirme/geri çekme
    500 vermez.
  - **Şema sertleştirmesi, migrasyon 0009 (YT-02, YT-04, YT-09):** `replaces_id` kısmi indeksleri ve halef
    zincirinin tek özyinelemeli sorguyla (üst sınır 10.000) yürünmesi; `netkar_app` için ekleme (`revision_from`
    sayaca eşit, baştan kapalı satır yok), kapanış (`revision_to` sayaca eşit) ve günlük (`revision` sayaca eşit,
    `tasima` yalnız taşıma) kuralları; `changed_by` için `(changed_by, tenant_id) -> memberships (user_id,
    tenant_id)` bileşik yabancı anahtarı; `defaults` günlük kaydı için sıkı CHECK (ADR-0007 §4 Revizyon 1).
- **Güven:** Yüksek (iç kural).

### K43 · Geçmişi etkileyen ayar değişikliği: etki tarihi ve onay
- **Etki tarihi (`affects_from`):** yazımın sonucunu değiştirebileceği en erken sipariş günü:
  - tarife ve hizmet bedeli: ekle, değiştir ve geri çekte ilgili satırın başlangıcı (değiştirmede anahtar
    başlangıcı içerdiği için eski ve yeni aynıdır);
  - değişken gider: ekle ve geri çekte başlangıç; değiştirmede eski ve yeni başlangıcın küçüğü;
  - varsayılan desi: tarihsizdir (`null`, "tüm dönemler"), çünkü K34 onu tarihsiz kullanır (§9 madde 26).
  Etki tarihi ihtiyatlı bir alt sınırdır: daha sonra başlayan bir sürüm etkiyi erken kesse de tarih değişmez.
- **Geçmişi etkiler:** etki tarihi bugünden (İstanbul takvim günü) önceyse ya da tarihsizse.
- **Onay:** geçmişi etkileyen yazım açık onay olmadan uygulanmaz. API `confirm_past_change=true` görmeden 409
  `settings-past-change-unconfirmed` döner, etki tarihini bildirir ve hiçbir şey yazmaz (sürüm artmaz, günlük ve
  denetim kaydı yok). Onaylı yazımın günlük ve denetim kaydında `past_change_confirmed = true` durur.
  - **Revizyon (YT-08, 10 Kasım 2026):** hata türü adı bu belgede `past-change-confirmation-required` yazılmıştı;
    API sözleşmesinin sahibi ADR-0007 §5.1 ve §8'dir (ADR-0006 satır 281): `settings-past-change-unconfirmed`
    (diğer ayar hatalarıyla aynı önek). Belge düzeltildi.
  - **Revizyon (YT-07, 10 Kasım 2026): onay etki tarihine bağlıdır.** Çıplak `confirm_past_change=true` artık
    onay SAYILMAZ (alan geriye uyum için kabul edilir, karara etkisi yoktur). İstemci 409 gövdesindeki
    `affects_from` tarihini `confirm_affects_from` olarak geri gönderir (tarihsiz varsayılan desi için `all`;
    gövdede `affects_from` null olduğunda). Sunucunun hesapladığı etki tarihiyle eşleşmezse yeniden 409
    `settings-past-change-unconfirmed` (gövde sunucunun tarihini taşır) ve hiçbir şey yazılmaz. Böylece "1 Ekim
    için" alınan onay "1 Ocak"tan itibaren değişen bir gövdede kullanılamaz. Etki tarihi geçmiş değilse onay
    değerlendirilmez; ilk giriş istisnasında onay gerekmez ama gönderilmiş ve eşleşmeyen onay yine 409'dur.
- **İlk giriş istisnası:** yazım yalnız "eksik" olan bir kalemi dolduruyorsa onay gerekmez, çünkü geçmiş
  raporlarda hiçbir sayı başka bir sayıya dönmez (null sayıya döner, K37):
  - tarife **ekle** ve hesapta aynı anlaşmada (Trendyol ya da satıcı) hiç etkin tarife yok;
  - hizmet bedeli **ekle** ve hesapta hiç etkin hizmet bedeli tahmini yok;
  - varsayılan desi `null`'dan bir değere.
  Değişken giderde istisna yoktur: tanımsız değişken gider eksik değil 0'dır (K36), eklemek net kâr sayılarını
  değiştirir. İstisnada da kesin kargolu ya da kesin hizmet bedelli eski satırların K38 karşılaştırması
  değişebilir (yeni `BEKLENMEYEN_KESINTI`); bu bir sayı değişikliği değil uyarıdır ve kabul edilir.
- **Kilit yoktur:** NetKâr geriye tarihli değişikliği reddetmez. Gerekçe: (1) kurulumun olağan yolu geriye tarihli
  girişidir (başlangıç tarihi hesabın ilk siparişinden önce önerilir, denetim AB-01); (2) NetKâr'da yetkili bir
  "kapanmış dönem" yoktur: bir ayın ekstre, iade, kargo faturası ve düzeltme satırları haftalarca gelmeye devam
  eder, `settled` kapanmış demek değildir (K22); (3) kilit yanlış girilmiş değeri kapanmış aylarda korur ve
  düzeltmeyi engeller. Kullanıcının bilerek ayı dondurması ("dönem kapatma") ayrı bir özellik olarak §9 madde 24
  cevabına bağlıdır (ADR-0007 §2.2).
- **Güven:** Yüksek (iç kural); müşavirin kilit beklentisi Doğrulanmadı (§9 madde 24).

### K44 · Rapor ayar damgası ve yeniden üretilebilirlik
- **Damga:** her rapor yanıtı (`summary`, ürün listesi, ürün ve sipariş kırılımı, uyarılar) ve ileride her dışa
  aktarım (CSV, e-posta özeti) hesaplandığı ayar sürümünü taşır: `settings_revision` (hesapta hiç ayar yazılmamışsa
  0). Rapor önbelleği anahtarı bu sürümü içerir (ADR-0006 §3.4).
- **Sürümle yükleme:** ayar yükleyici (`profit_settings_for`) isteğe bağlı bir ayar sürümü alır ve o sürümde etkin
  satırlarla ve günlükteki varsayılan desiyle `ProfitSettings` kurar; güncel sürüm varsayılandır. Aynı sipariş ve
  ekstre verisiyle aynı sürüm aynı sonucu verir. Rapor API'sinde `settings_revision` sorgu parametresi (eski ayarla
  yeniden hesap) P1'dir; yükleyici parametresi ve testi P0'dadır (önbellek ve geçmiş ekranı için gerekir).
- **Sınır:** damga raporu yalnız ayar açısından yeniden üretilebilir kılar. Sipariş, ekstre, kargo faturası,
  iade ve ürün maliyeti verisi tasarım gereği değişmeye devam eder (tahmini -> kesin, K22); bir raporun aynen
  yeniden üretilmesi veri anlık görüntüsü de ister ve v1 kapsamında değildir. Panel "ayarlar şu sürümde, veri şu
  ana kadar senkron" bilgisini birlikte gösterir.
- **0008 öncesi kayıtlar:** taşıma her hesabın mevcut satırlarını o anki ayar sürümüyle (`revision_from = güncel
  sürüm`) ve günlükte bir `tasima` kaydıyla işaretler; bu sürümden eski bir sürümle yükleme istenirse yükleyici
  "sürüm yeniden kurulamaz" hatası verir (API'de P1: 409 `settings-revision-unavailable`).
- **Revizyon 1 (10 Kasım 2026, YT-01 ve YT-03):** (a) Damga ve rakamlar aynı sürümden okunur: yükleyici satırları
  başlıkta okunan sürümle süzer (K42 Revizyon 1), dolayısıyla eşzamanlı bir yazım "damga R, satırlar R+1" yanıtı
  üretemez ve rapor önbelleği anahtarı `settings_revision` içerdiğinde yanlış anahtarlı girdi yazılmaz. `summary`
  tamlığı aynı demetten hesaplanır. (b) Başlıksız hesapta damga 0 yalnız "hiç ayar satırı yok" demektir: taşıma
  satırı olan hesaba başlığı `revision = 1` ile oluşturur, etkin satırı olup damgası 0 olan hesap oluşamaz.
- **Güven:** Yüksek (iç kural).
