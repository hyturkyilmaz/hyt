# Demo doğru cevap kartı (moderatör)

> Bu dosya `make seed-demo` ile ÜRETİLİR; rakamlar gerçek kâr motorundan ve rapor servislerinden gelir, elle yazılmaz. Elle düzenlemeyin, tohumu yeniden çalıştırın.

- Tohum sürümü: **1**
- Veri tarihi (`as_of`): **2026-11-14**, oturum no: **1**
- Dönem (panelde "30 gün", uçlar dahil): **2026-10-16 - 2026-11-14**
- Tutarlar KDV hariçtir (panelin kalem dökümü gibi). Veri `as_of` gününden en çok 27 gün geriye uzanır: tohumdan sonraki 2 gün içinde "30 gün" aynı rakamları verir; sonra betiği yeniden çalıştırın.
- Parolalar bu dosyada YOKTUR; betik bunları yalnız çalıştığı anda ekrana yazar.

## Hesaplar

| Hesap | E-posta (uydurma) | Satıcı no (uydurma) |
|---|---|---|
| Hesap A (ayarsız) | demo-a-1@example.com | 9001001 |
| Hesap B (ayarlı, veri seti X) | demo-bx-1@example.com | 9001002 |
| Hesap B (ayarlı, veri seti Y) | demo-by-1@example.com | 9001003 |

## Hesap A (ayarsız): G1, G2, G3

Dönem 2026-10-16 - 2026-11-14; 38 sipariş, 38 aktif satır. Ürün maliyetleri dolu; kargo tarifesi, hizmet bedeli ve varsayılan desi YOK.

### G1 Özet ekranına ilk bakış

| Ekranda | Doğru değer |
|---|---|
| Dönem net kârı | hesaplanamadı (net kâr kısmi) |
| Eksik giderler hariç dönem kârı (kargo ve hizmet bedeli hariç) | **4.246,03 ₺** |
| Kargosu eksik satır sayısı | 38 |
| Hizmet bedeli eksik satır sayısı | 38 |
| Eksiksiz satırların net kârı | yok (hiçbir satır eksiksiz değil) |
| Zarar ettiren ürün sayısı | 0 |

Doğru okuma: bilinen rakam NET KÂR DEĞİLDİR; kargo ve hizmet bedeli düşülünce azalır. Katılımcı kargo tarifesini ve hizmet bedelini girmesi gerektiğini söyler.

### G2 İlk kurulum (bilgi kartı girildikten sonra)

Bilgi kartı: Trendyol anlaşmalı, Trendyol Express; 0-2 desi 50 TL, 3-5 desi 60 TL, 6-10 desi 80 TL (KDV dahil); hizmet bedeli sipariş başına 10 TL (KDV dahil). Başlangıç tarihi dönemin ilk gününden önce olmalı.

- Doğru giriş sonrası dönem net kârı: **2.179,38 ₺** (kısmi mi: hayır).

### G3 Geçmişi etkileyen değişiklik (3-5 desi 60 TL -> 65 TL)

- Değişiklik sonrası dönem net kârı: **2.158,53 ₺** (kısmi mi: hayır); fark: -20,85 ₺.
- Pencerenin doğru anlatımı: geçmiş siparişlerin kâr rakamları değişir, eski rakamlı raporlar farklı olabilir, önceki değer ayar geçmişinde saklanır.

## Hesap B (ayarlı, veri seti X): G4 - G8

Dönem 2026-10-16 - 2026-11-14; 95 sipariş, 96 aktif satır.

Not: Bu hesapta maliyeti girilmemiş iki ürün ve kendi kargo anlaşmasıyla giden (tarifesi tanımsız) bir ürün bulunduğundan DÖNEM net kârı kısmidir; panelde "Eksik giderler hariç dönem kârı" görünür (plan §7.1 şartnamesi).

| Dönem özeti | Doğru değer |
|---|---|
| Dönem net kârı | hesaplanamadı (kısmi) |
| Eksik giderler hariç dönem kârı | **2.084,70 ₺** |
| Eksiksiz satırların net kârı | 1.194,67 ₺ (72 satır) |
| Maliyeti eksik satır / kargosu eksik satır | 14 / 10 |

### G4 / G8a: en çok zarar ettiren ürün

**Doğru ürün: Demo Ürün: Büyük Boy Saklama Sandığı (`990200000101`)**; zarar: **-1.154,92 ₺** (rozet: "Zarar"), 20 adet.
Neden: ürün maliyeti dışındaki en büyük gider kalemi **Kargo (gönderi)**; kalem dökümüne aşağıdaki tablodan bakılır.

| Gider kalemi (KDV hariç, toplam) | Tutar | Net satışa oranı |
|---|---|---|
| Ürün maliyeti | 1.560,00 ₺ | %66,91 |
| Komisyon | 349,80 ₺ | %15,00 |
| Kargo (gönderi) | 1.333,40 ₺ | %57,19 |
| Kargo (iade) | 0,00 ₺ | %0,00 |
| Platform hizmet bedeli | 193,32 ₺ | %8,29 |
| Ceza | 0,00 ₺ | %0,00 |
| Değişken giderler | 50,00 ₺ | %2,14 |
| Reklam | 0,00 ₺ | %0,00 |
| Net satış | 2.331,60 ₺ | %100,00 |

Zarar rozetleri (üçü birbirinden farklıdır):

| Ürün | Rozet | Zarar (net kâr ya da bilinen giderlerle kâr) | Net kâr |
|---|---|---|---|
| Demo Ürün: Büyük Boy Saklama Sandığı (`990200000101`) | Zarar | -1.154,92 ₺ | -1.154,92 ₺ |
| Demo Ürün: Ucuz Mutfak Askısı (`990200000103`) | Maliyet girilmese de zarar | -124,73 ₺ | hesaplanamadı |
| Demo Ürün: Kendi Kargomla Giden Poşet Seti (`990200000102`) | Bilinen giderlerle bile zarar | -107,36 ₺ | hesaplanamadı |

Maliyeti girilmemiş ürünler: `990200000103`, `990200000104`

### G5: çok ürünlü sipariş, kalem dökümü

İade: ekstrede iade satırı (Return) vardır ama iade kaydı (claim) henüz gelmemiştir; panelde "İade kaydı bekleniyor." notu görünür. Motor ürün maliyetini ihtiyatla gider bırakır (docs/12 K10).

Sipariş no (tam yazılmalı): **`7201094`**. Sipariş toplamı net kâr: -11,97 ₺; eksik giderler hariç kâr: -11,97 ₺.

**Demo Ürün: Seramik Kupa Seti (`990200000002`)**: 2 adet, 0 adedi iade, iade kaydı bekleyen adet: 1; durum: adjusted; net kâr: -85,58 ₺; uyarılar: IADE_KAYDI_BEKLENIYOR, ZARAR

| Kalem | Tutar (KDV hariç) | Kaynak |
|---|---|---|
| Net satış | 274,91 ₺ | Kesin |
| Ürün maliyeti | 219,94 ₺ | Tahmini |
| Komisyon | 43,99 ₺ | Kesin |
| Kargo (gönderi) | 37,50 ₺ | Kesin |
| Kargo (iade) | 50,00 ₺ | Kesin |
| Platform hizmet bedeli | 7,25 ₺ | Kesin |
| Ceza | 0,00 ₺ | Yok |
| Değişken giderler | 1,81 ₺ | Girdiğiniz |
| Reklam | 0,00 ₺ | Yok |

**Demo Ürün: Bambu Kesme Tahtası (`990200000001`)**: 1 adet, 0 adedi iade; durum: settled; net kâr: 73,61 ₺

| Kalem | Tutar (KDV hariç) | Kaynak |
|---|---|---|
| Net satış | 208,25 ₺ | Kesin |
| Ürün maliyeti | 87,46 ₺ | Girdiğiniz |
| Komisyon | 31,24 ₺ | Kesin |
| Kargo (gönderi) | 12,50 ₺ | Kesin |
| Kargo (iade) | 0,00 ₺ | Yok |
| Platform hizmet bedeli | 2,75 ₺ | Kesin |
| Ceza | 0,00 ₺ | Yok |
| Değişken giderler | 0,69 ₺ | Girdiğiniz |
| Reklam | 0,00 ₺ | Yok |

### G6 / G8b: ekstresi gelmeyen ve beklenmeyen kesintili siparişler

- "Ekstresi gelmedi" sipariş sayısı: **20**
  Sipariş no: `7201001`, `7201006`, `7201011`, `7201016`, `7201021`, `7201028`, `7201033`, `7201038`, `7201043`, `7201050`, `7201055`, `7201060`, `7201065`, `7201070`, `7201077`, `7201080`, `7201081`, `7201089`, `7201097`, `7201098`
  Bunlardan kasıtlı olarak eski (19 gün ve daha eski) olanlar: `7201097`, `7201098`
- "Beklenmeyen kesinti" sipariş sayısı: **2**

**`7201095`**: toplam fark 15,00 ₺ (eşik 5,00 ₺)

| Kalem | Tahmini | Kesin | Farka girdi mi | Fark |
|---|---|---|---|---|
| Komisyon | 46,66 ₺ | 59,99 ₺ | evet | 13,33 ₺ |
| Kargo (gönderi) | 50,00 ₺ | - | hayır | - |
| Platform hizmet bedeli | 8,33 ₺ | 10,00 ₺ | evet | 1,67 ₺ |

**`7201096`**: toplam fark 39,17 ₺ (eşik 5,00 ₺); kargo tahmini varsayılan desiyle yapıldı

| Kalem | Tahmini | Kesin | Farka girdi mi | Fark |
|---|---|---|---|---|
| Komisyon | 37,49 ₺ | 37,49 ₺ | evet | 0,00 ₺ |
| Kargo (gönderi) | 41,67 ₺ | 79,17 ₺ | evet | 37,50 ₺ |
| Platform hizmet bedeli | 8,33 ₺ | 10,00 ₺ | evet | 1,67 ₺ |

### G7: uyarılar sayfası

Dört kart ve satır sayıları (motorun ürettiği uyarılar, iptal satırlar hariç):

| Kart | Kod | Sayı |
|---|---|---|
| Zarar eden satışlar | `ZARAR` | 40 |
| Beklenmeyen kesintiler | `BEKLENMEYEN_KESINTI` | 2 |
| Ürün maliyeti eksik | `MALIYET_EKSIK` | 14 |
| Kargo tarifesi eksik | `KARGO_TARIFESI_EKSIK` | 10 |

Tüm kodlar: `BEKLENMEYEN_KESINTI`: 2, `IADE_KAYDI_BEKLENEN_SATIRLAR_VAR`: 1, `IADE_KAYDI_BEKLENIYOR`: 1, `KARGO_EKSIK_SATIRLAR_VAR`: 1, `KARGO_TARIFESI_EKSIK`: 10, `KOMISYON_ORANI_FARKLI`: 1, `MALIYET_EKSIK`: 14, `MALIYET_EKSIK_SATIRLAR_VAR`: 1, `ZARAR`: 40

## Hesap B (ayarlı, veri seti Y): G4 - G8

Dönem 2026-10-16 - 2026-11-14; 86 sipariş, 87 aktif satır.

Not: Bu hesapta maliyeti girilmemiş iki ürün ve kendi kargo anlaşmasıyla giden (tarifesi tanımsız) bir ürün bulunduğundan DÖNEM net kârı kısmidir; panelde "Eksik giderler hariç dönem kârı" görünür (plan §7.1 şartnamesi).

| Dönem özeti | Doğru değer |
|---|---|
| Dönem net kârı | hesaplanamadı (kısmi) |
| Eksik giderler hariç dönem kârı | **1.961,20 ₺** |
| Eksiksiz satırların net kârı | 1.418,50 ₺ (66 satır) |
| Maliyeti eksik satır / kargosu eksik satır | 12 / 9 |

### G4 / G8a: en çok zarar ettiren ürün

**Doğru ürün: Demo Ürün: Dolgulu Yatak Minderi (`990300000101`)**; zarar: **-959,73 ₺** (rozet: "Zarar"), 14 adet.
Neden: ürün maliyeti dışındaki en büyük gider kalemi **Kargo (gönderi)**; kalem dökümüne aşağıdaki tablodan bakılır.

| Gider kalemi (KDV hariç, toplam) | Tutar | Net satışa oranı |
|---|---|---|
| Ürün maliyeti | 1.960,00 ₺ | %76,40 |
| Komisyon | 461,86 ₺ | %18,00 |
| Kargo (gönderi) | 933,38 ₺ | %36,38 |
| Kargo (iade) | 0,00 ₺ | %0,00 |
| Platform hizmet bedeli | 134,99 ₺ | %5,26 |
| Ceza | 0,00 ₺ | %0,00 |
| Değişken giderler | 35,00 ₺ | %1,36 |
| Reklam | 0,00 ₺ | %0,00 |
| Net satış | 2.565,50 ₺ | %100,00 |

Zarar rozetleri (üçü birbirinden farklıdır):

| Ürün | Rozet | Zarar (net kâr ya da bilinen giderlerle kâr) | Net kâr |
|---|---|---|---|
| Demo Ürün: Dolgulu Yatak Minderi (`990300000101`) | Zarar | -959,73 ₺ | -959,73 ₺ |
| Demo Ürün: Mini Plastik Tarak Seti (`990300000103`) | Maliyet girilmese de zarar | -160,58 ₺ | hesaplanamadı |
| Demo Ürün: Kendi Kargomla Giden Baskılı Kutu (`990300000102`) | Bilinen giderlerle bile zarar | -73,07 ₺ | hesaplanamadı |

Maliyeti girilmemiş ürünler: `990300000103`, `990300000104`

### G5: çok ürünlü sipariş, kalem dökümü

İade: ekstrede iade satırı (Return) vardır ama iade kaydı (claim) henüz gelmemiştir; panelde "İade kaydı bekleniyor." notu görünür. Motor ürün maliyetini ihtiyatla gider bırakır (docs/12 K10).

Sipariş no (tam yazılmalı): **`7301085`**. Sipariş toplamı net kâr: 16,01 ₺; eksik giderler hariç kâr: 16,01 ₺.

**Demo Ürün: Cam Baharatlık Takımı (`990300000004`)**: 3 adet, 0 adedi iade, iade kaydı bekleyen adet: 1; durum: adjusted; net kâr: -47,96 ₺; uyarılar: IADE_KAYDI_BEKLENIYOR, ZARAR

| Kalem | Tutar (KDV hariç) | Kaynak |
|---|---|---|
| Net satış | 316,50 ₺ | Kesin |
| Ürün maliyeti | 208,89 ₺ | Tahmini |
| Komisyon | 53,81 ₺ | Kesin |
| Kargo (gönderi) | 42,86 ₺ | Kesin |
| Kargo (iade) | 50,00 ₺ | Kesin |
| Platform hizmet bedeli | 7,12 ₺ | Kesin |
| Ceza | 0,00 ₺ | Yok |
| Değişken giderler | 1,78 ₺ | Girdiğiniz |
| Reklam | 0,00 ₺ | Yok |

**Demo Ürün: Metal Telefon Standı (`990300000006`)**: 1 adet, 0 adedi iade; durum: settled; net kâr: 63,97 ₺

| Kalem | Tutar (KDV hariç) | Kaynak |
|---|---|---|
| Net satış | 191,58 ₺ | Kesin |
| Ürün maliyeti | 82,38 ₺ | Girdiğiniz |
| Komisyon | 34,49 ₺ | Kesin |
| Kargo (gönderi) | 7,14 ₺ | Kesin |
| Kargo (iade) | 0,00 ₺ | Yok |
| Platform hizmet bedeli | 2,88 ₺ | Kesin |
| Ceza | 0,00 ₺ | Yok |
| Değişken giderler | 0,72 ₺ | Girdiğiniz |
| Reklam | 0,00 ₺ | Yok |

### G6 / G8b: ekstresi gelmeyen ve beklenmeyen kesintili siparişler

- "Ekstresi gelmedi" sipariş sayısı: **20**
  Sipariş no: `7301001`, `7301006`, `7301011`, `7301016`, `7301021`, `7301028`, `7301033`, `7301038`, `7301043`, `7301050`, `7301055`, `7301060`, `7301064`, `7301071`, `7301073`, `7301074`, `7301081`, `7301087`, `7301088`, `7301089`
  Bunlardan kasıtlı olarak eski (19 gün ve daha eski) olanlar: `7301087`, `7301088`, `7301089`
- "Beklenmeyen kesinti" sipariş sayısı: **1**

**`7301086`**: toplam fark 15,00 ₺ (eşik 5,00 ₺)

| Kalem | Tahmini | Kesin | Farka girdi mi | Fark |
|---|---|---|---|---|
| Komisyon | 46,66 ₺ | 59,99 ₺ | evet | 13,33 ₺ |
| Kargo (gönderi) | 50,00 ₺ | - | hayır | - |
| Platform hizmet bedeli | 8,33 ₺ | 10,00 ₺ | evet | 1,67 ₺ |

### G7: uyarılar sayfası

Dört kart ve satır sayıları (motorun ürettiği uyarılar, iptal satırlar hariç):

| Kart | Kod | Sayı |
|---|---|---|
| Zarar eden satışlar | `ZARAR` | 32 |
| Beklenmeyen kesintiler | `BEKLENMEYEN_KESINTI` | 1 |
| Ürün maliyeti eksik | `MALIYET_EKSIK` | 12 |
| Kargo tarifesi eksik | `KARGO_TARIFESI_EKSIK` | 9 |

Tüm kodlar: `BEKLENMEYEN_KESINTI`: 1, `IADE_KAYDI_BEKLENEN_SATIRLAR_VAR`: 1, `IADE_KAYDI_BEKLENIYOR`: 1, `KARGO_EKSIK_SATIRLAR_VAR`: 1, `KARGO_TARIFESI_EKSIK`: 9, `KOMISYON_ORANI_FARKLI`: 1, `MALIYET_EKSIK`: 12, `MALIYET_EKSIK_SATIRLAR_VAR`: 1, `ZARAR`: 32

## Notlar

- Bu karttaki iki teknik varsayım (G2: ilk girişte onay penceresi çıkmaz; G3: mevcut tarifeyi düzenlemek geçmişi etkileyen onayı tetikler) motorun değil ayar servisinin davranışıdır; sınama testlerde vardır, yine de staging'de bir kez deneyin.
- Her katılımcı için temiz Hesap A gerekir (G2 ve G3 ayarı değiştirir ve silinemez): `--instance N` ile yeni bir oturum üretin.
- Bu veri uydurmadır; hiçbir gerçek kişi, mağaza ya da müşteri bilgisi yoktur.
