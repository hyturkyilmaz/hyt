# NetKâr · Kâr Motoru Kuralları (v0.1, 6 Kasım 2026)

Sahibi: kâr motoru alan modelcisi (docs/40_ajan_promptlari.md §3.2).
Özet: docs/10_mimari.md §4. Altın testler: `services/api/tests/golden/` (41 senaryo), üreten betik:
`calisma_dosyalari/altin_test_hesap.py`.

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
  fatura geldiyse), platform hizmet bedeli (yalnız fatura dağıtıldıysa). Hepsi KDV hariç.
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

### 7.2 Ürün (barkod) toplamı
Satırların yuvarlanmış değerlerinin toplamı (iptaller hariç). Ek alanlar: `reklam_satissiz`, `reklam_harcamasi`
(= satırlara dağıtılan + satışsız), `reklam_cirosu` (Excel), `roas`, `basabas_roas`, `maliyet_eksik`, `stopaj`.
Ürünün net kârı = satır net kârları - `reklam_satissiz`; satırlardan biri maliyetsizse `null`.

### 7.3 Dönem toplamı
`satir_net_kar_toplami` (maliyeti olan satırlar) eksi dönem düzeyi giderler (`reklam_satissiz_urunler`,
`reklam_dagitilamayan`, `dagitilmamis_ceza`, `erken_odeme_bedeli`, `siniflandirilmamis_kesinti`) = `donem_net_kar`.
Ayrıca `net_kar_kismi`, `kdv_etkisi`, `nakit_akisi` (`stopaj_hesaplanan`, `stopaj_ekstre`,
`erken_odeme_nakit_girisi`), dönem uyarıları.

### 7.4 Tanımlar
| Metrik | Formül | Not |
|---|---|---|
| Net kâr marjı % | `net_kar / net_satis_kdv_haric x 100` | Net satış 0 ise `null` (tam iade) |
| Maliyet hariç katkı | `net_satis - (tüm giderler - ürün maliyeti)` | Maliyeti olmayan ürün için de gösterilir |
| ROAS | `reklam_cirosu / reklam_harcamasi` | Trendyol paneliyle aynı tanım; cironun KDV dahil olduğu varsayılır (Doğrulanmadı). Örnek 1.499,70 / 120,00 = 12,50 (G24) |
| Başabaş ROAS | `net_satis_kdv_haric / (net_kar + reklam_harcamasi)` | Reklamın tüm katkıyı yediği ROAS (KDV hariç ciro bazında). G24: 1.249,75 / 407,28 = 3,07. Platform ROAS'ı ile karşılaştırırken ciroyu KDV hariçleştirin (12,50 / 1,20 = 10,42 > 3,07: kârlı) |

---

## 8. Ayarlar ve varsayılanlar

| Ayar | Varsayılan | Kural |
|---|---|---|
| `komisyon_tutari_kdv_dahil` | `true` | K07 |
| `komisyon_kdv_orani`, `kargo_kdv_orani`, `hizmet_bedeli_kdv_orani`, `reklam_kdv_orani` | `20` | K02 |
| `stopaj_orani` | `1` | K18 |
| `platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric` | kullanıcı / NetKâr tablosu | K13 |
| `kargo_tarifesi`, `satici_kargo_tarifesi` | kullanıcı / NetKâr tablosu | K08 |
| `kargo_faturasi_kdv_tespit_toleransi` | `0.05` | K08 |
| `uyari_esikleri` | 5,00 TL; %5; 0,05; 0,01 puan | K23 |
| `degisken_giderler` | boş | K17 |

Testlerdeki tarife ve hizmet bedeli değerleri kurgusaldır; üretimde kullanılmaz.

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

K29 ile K32 v1 altın testlerinde yoktur; pilot verisi ve §9 cevapları geldikten sonra senaryo eklenecek.
