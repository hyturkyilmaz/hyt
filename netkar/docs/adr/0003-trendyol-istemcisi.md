# ADR-0003: Trendyol istemcisi, bağlantı doğrulama ve anahtar saklama

- Durum: Kabul edildi (S2, ilk tur: istemci + bağlantı; depolama ve senkron sonraki tur)
- Tarih: 6 Kasım 2026
- İlgili: `docs/10_mimari.md` §3 (veri akışı, istemci kuralları, PII), `docs/50_guvenlik.md` G05 ve G16, `docs/research/01_trendyol_api.md`, ADR-0001 (RLS), ADR-0004 (zarf şifreleme), `services/api/app/integrations/trendyol/`
- Güncelleme (7 Kasım 2026, S2 denetim düzeltme turu): §2 (TLS/ortam), §4 (bekleme bütçesi), §5 (hata yolunda ham yanıt), §6 (sayfalama sonlandırma), §7 (saklama: zarf şifreleme) ve §10 düzeltildi; ayrıntı ADR-0004 ve `docs/security/denetim_2026-11-07_S2.md` "Kapanış durumu".

## 1. Bağlam

NetKâr, satıcının kendi API anahtarıyla Trendyol'a salt okuma bağlanır. Üç risk aynı kodda toplanır: (1) çok satıcılı bir SaaS'ın rate limit ve 429 yönetimi, (2) son müşteri kişisel verisinin (KVKK, sözleşme EK-6) sisteme hiç girmemesi, (3) satıcı anahtarlarının güvenli saklanması. Bu ADR bu üç konuda ve istemcinin yapısında verilen kararları, reddedilen seçenekleri ve Trendyol'dan teyit beklenen noktaları (K-N07) kaydeder.

## 2. Karar: yapı, ortam ve kimlik

- **Tek istemci.** Trendyol'a tüm HTTP çağrıları `TrendyolClient` (httpx.AsyncClient) üzerinden yapılır. `tests/test_trendyol_client.py` uygulama kodunda başka bir dosyanın httpx'i Trendyol için kullanmadığını denetler (HIBP istemcisi Trendyol dışıdır ve ayrı tutulur). İstemci süreç başına değil kullanım başına kurulur (`async with`); hız sınırı kovaları ise uygulama genelinde paylaşılan `RateLimiterRegistry` içindedir.
- **Ortam.** Canlı `https://apigw.trendyol.com`, stage `https://stageapigw.trendyol.com`. `TRENDYOL_ENVIRONMENT` ile seçilir, **varsayılan stage**: yanlış yapılandırılmış bir ortam canlı satıcı verisine kazara dokunmaz. Eski `api.trendyol.com/sapigw` adresleri 2025'te kapandığı için hiçbir yerde yoktur. Stage ortamı IP yetkilendirmesi ister; yetki yokken 503 döner ve bu, 5xx olarak yeniden denenip `TrendyolServerError` ile biter (kullanıcıya "ulaşılamadı" olarak yansır). Stage erişimi için IP bildirimi Hasan kararıdır (K-N07 madde 15).
- **Kimlik.** Basic Auth (API Key : API Secret). Zorunlu `User-Agent: "{sellerId} - {integrator}"`. `integrator` `TRENDYOL_INTEGRATOR_NAME` ayarından gelir, varsayılan ürün kod adı `NetKar` (ürün adı `NetKâr` Türkçe karakter içerdiği için kullanılamaz). Doğrulama en katı yorumdur: yalnız ASCII harf/rakam, 1 ile 30 karakter, boşluk ve noktalama yok (research/01 §2.1: "alfanümerik, en fazla 30"). Geçersiz ad `Settings` doğrulamasında uygulamayı başlatmaz; `TrendyolConfig` ve `TrendyolClient` de ayrıca doğrular, yani User-Agent geçerli değilse istemci kurulmaz (403'ü Trendyol'a bırakmayız). Satıcı kimliği yalnız rakam (baştaki sıfır yok, en fazla 18 hane). API anahtarı ve sırrı boşluksuz ASCII olmak zorundadır (başlık enjeksiyonu engeli); anahtarda `:` olamaz (RFC 7617).
- **Zaman aşımları.** Bağlantı 5 sn, okuma 20 sn, yazma 10 sn, havuz 5 sn (ayarlanabilir). Yönlendirme izlenmez (kimlik bilgisi başka bir adrese gitmesin). httpx `trust_env=False`: `HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE` gibi ortam değişkenleri vekil veya güven deposunu değiştiremez; TLS bağlamı certifi ile açıkça kurulur (en az TLS 1.2). Yanıt gövdesi akışla okunur ve çözülmüş 20 MiB'ı aşarsa `TrendyolProtocolError` olur; bozuk `Content-Encoding` (`httpx.DecodingError`), aşırı iç içe JSON (`RecursionError`) ve geçersiz JSON da `TrendyolProtocolError`'a eşlenir (S2 D-03, B-04).

## 3. Karar: rate limit ve yeniden deneme

**Strateji.** İstek atılmadan önce iki jeton kovasından birer jeton alınır; ikisi de yoksa asenkron beklenir:

1. **(satıcı, uç nokta grubu)** kovası: grubun dakikalık limiti ve küçük bir burst.
2. **(satıcı, uç nokta)** genel kuralı: "aynı uç noktaya 10 sn'de 50 istek" (5 istek/sn, burst 50).

| Grup | Uç noktalar | Dakikalık limit (en tutucu) | Burst | Kaynak |
|---|---|---|---|---|
| `orders` | `v2/orders` | 30 | 5 | Sipariş tablosu: seviyeye göre 30/40/50/100; en düşüğü |
| `orders_stream` | `orders/stream` | 12 (5 sn aralık) | 1 | Ayrı limit yok; "en az 5 sn aralık" önerisi |
| `claims` | `claims` | 1000 | 50 | İade tablosu |
| `finance` | `settlements`, `otherfinancials`, `payment-order`, `cargo-invoice` | 100 | 10 | Finans tablosu |
| `product_read` | `products/approved`, `.../inventory-and-price` | 1000 (en düşük seviye) | 50 | Ürün Read grubu 1000-2000/dk |
| `qna` | `questions/filter`, `questions/{id}` | 1000 | 50 | Soru-cevap tablosu |

Burst küçük tutulur çünkü kova kapasitesi + dolum hızı kısa pencerede dakikalık limiti aşabilir; limitin sabit mi kayan pencere mi olduğu bilinmiyor. Kalan fark 429 geri çekilmesiyle karşılanır.

**429 ve 5xx.** 429, 500, 502, 503, 504 ve ağ hataları yeniden denenir: "eşit jitter" üstel geri çekilme `gecikme = tavan/2 + rastgele * tavan/2`, `tavan = min(30 sn, 1 sn * 2^deneme)`; en fazla `TRENDYOL_MAX_RETRIES` (4) yeniden deneme. `Retry-After` varsa (saniye) ve daha uzunsa o kullanılır, 60 sn ile kırpılır. 429 alınınca aynı satıcı ve grubun kovası o süre boyunca bloke edilir; paralel çağrılar da bekler. Eşit jitter seçildi çünkü tam jitter bazen sıfıra yakın bekletir ve 429'dan hemen sonra tekrar vurur.

**401 ve 403.** Yeniden denenmez. 401: `TrendyolAuthError` (anahtar geçersiz veya iptal), 403: `TrendyolForbiddenError` (User-Agent, IP veya rol). Diğer 4xx/3xx: `TrendyolRequestError`. Hata nesneleri yanıt gövdesi taşımaz.

**Sınırlar.** Kovalar süreç içidir. Aynı satıcıya birden çok worker süreci istek atarsa toplam hız süreç sayısıyla çarpılır; 429 geri çekilmesi bunu tolere eder. Ölçek tetikleyicisi: worker sayısı 1'i aşarken finans veya sipariş 429 oranı belirgin artarsa kova durumu PostgreSQL'e (ADR-0001 §4'teki gibi atomik sayaç) taşınır. Limitlerin satıcı, anahtar veya IP bazlı sayıldığı doğrulanmadı (K-N07 madde 1); tek çıkış IP'siyle çok satıcı çekmek IP bazlıysa kovalar satıcı bazlı olduğu için yetmez.

## 4. Karar: bağlantı doğrulama çağrısı

Seçim: `GET /integration/product/sellers/{sellerId}/products/approved/inventory-and-price?page=0&size=1` (stok ve fiyat odaklı onaylı ürün v2).

Gerekçe:

- **Salt okuma ve PII yok.** Sipariş, iade ve soru uç noktaları müşteri adı/adresi içerir; bu çağrı yalnız barkod, fiyat ve stok döndürür. Doğrulama için kişisel veri taşıyan bir uç noktayı çağırmayız.
- **En küçük yük.** `size=1` ve zaten "yalnız stok ve fiyat" varyantı: açıklama, görsel ve öznitelik yok.
- **En geniş limit.** Product Integration Read grubu (1000-2000/dk); finans (100/dk) ve sipariş (30/dk) gruplarını tüketmez.
- **Net ayrım.** Geçersiz anahtar 401, yanlış User-Agent/IP/rol 403 döner; geçerli ama ürünsüz satıcı 200 ve boş liste.
- Yan fayda: `totalElements` toplam ürün sayısıdır (onboarding'de gösterilebilir).

Reddedilenler: `payment-order` (finans limiti dar, yeni satıcıda boş olabilir), `claims`/`orders` (PII), `questions/filter` (PII), tam `products/approved` (ağır yanıt).

Risk: salt okuma rolüyle üretilen anahtarın ürün okuma yetkisi olmayabilir (K-N07 madde 3). O durumda 403 döner ve kullanıcıya rol kontrolü önerilir (`marketplace-access-denied`). Doğrulama isteği içinde en fazla 1 yeniden deneme yapılır ve toplam bekleme (kova beklemesi + geri çekilme + `Retry-After`) en fazla 5 sn, toplam süre 15 sn'dir (`TRENDYOL_VALIDATION_MAX_WAIT_SECONDS`, `_DEADLINE_SECONDS`). Bekleme bütçesi aşılacaksa uyunmadan 503 `marketplace-busy` döner; toplam süre aşılırsa 502 `marketplace-unavailable`. Senkron işleri bu sınırlara tabi değildir (istemci `max_total_wait=None` ile kurulur, uzun bekleme serbesttir). Veritabanı işlemi dış çağrı sırasında tutulmaz. Doğrulama çağrıları ayrıca platform geneli dakikalık tavana (`RATE_LIMIT_MARKETPLACE_GLOBAL_PER_MINUTE`, varsayılan 60) tabidir (S2 D-02, D-06).

## 5. Karar: PII atma noktası

Atma noktası `TrendyolClient._validate` (ve `_page`): ham yanıt `json.loads` (parasal alanlar `Decimal`) ile bir dict'e çevrilir ve **aynı çağrıda** pydantic modellerine doğrulanır. Modeller `extra="ignore"` olduğundan şemada olmayan her alan ayrıştırma sırasında sessizce düşer. Dışarı yalnız model nesneleri çıkar.

- Modellenmeyen alanlar: `customerFirstName`, `customerLastName`, `customerEmail`, `customerId`, `identityNumber`/`customerTckn`, `invoiceAddress` (tamamı), `shipmentAddress` içindeki ad, adres, telefon, ilçe, mahalle, posta kodu, `fullName`, `fullAddress`, `latitude`/`longitude`, `taxNumber`/`taxOffice`/`company`, `invoiceLink` (dokümandaki örnekte kimlik numarası taşıyor), claims'te müşteri adı, `note`/`customerNote`, red paketi adresi, sorularda `userName`/`customerId`. Teslimat adresinden yalnız `city` ve `cityCode` alınır (`ProvinceOnly`).
- `tests/test_trendyol_models_pii.py`: (a) hiçbir modelde yasaklı alan takma adı yoktur, (b) PII dolu fixture'lar tüm uç noktalardan geçirilir ve sentinel kişisel veri değerleri hiçbir model nesnesinin `repr`, `json` çıktısında ve hiçbir log kaydında bulunmaz, (c) hata nesneleri (şema uyuşmazlığı, 4xx/5xx) gövde değeri taşımaz ve `__context__` boştur. Hata nesneleri `except` bloğunun dışında fırlatılır; `ValidationError` ve `JSONDecodeError` ham değeri taşıdığından bağlam bırakılmaz. Şema hatasında ham sözlük yerinde boşaltılır (`dict.clear()`), böylece çağıran çerçevelerin yerellerinde (traceback, Sentry `include_local_variables`) ham yanıt kalmaz; Sentry eklenirken `app/core/privacy.py` içindeki `sentry_init_options()` ve `scrub_event` zorunludur (S2 D-01).
- **Log.** Yalnız çağrı meta logu: `http_method`, `endpoint_group`, `endpoint` (işlem adı, URL değil), `status`, `duration_ms`, `attempt`. Sorgu dizesi, başlık, gövde ve kimlik bilgisi yazılmaz. httpx/httpcore'un kendi INFO kayıtları tam URL yazdığı için uyarı seviyesine çekilmiştir.
- **Serbest metin istisnası.** Müşteri sorusunun `text` alanı serbest metindir ve müşteri kişisel veri yazmış olabilir. Bu turda yalnız çekilir ve modelde tutulur, loglanmaz; saklama kararı sonraki tura aittir (öneri: saklamadan, yalnız satıcının ekranında göstermek).
- **customerId.** `docs/10_mimari.md` §3.5 takma adlı müşteri anahtarını (tuzlu HMAC) öngörür; research/01 §2.6 ise hukukçu onayı olmadan önermez. Karar verilene kadar `customerId` modellenmez. Tekrar eden müşteri analizi istenirse HMAC'in istemci içinde hesaplanması gerekir (ham değer model katmanına girmeden), bu sonraki turun açık sorusudur.

## 6. Karar: pencere ve sayfalama kuralları

- **v2/orders:** `size` en fazla 200; tarih verilirse aralık en fazla 14 gün; `page x size` en fazla 10.000 (page 0 ile 49). `iter_shipment_packages` aralığı 14 günlük pencerelere böler; bir pencerede `totalElements > 10000` ise sessizce kırpmaz, `TrendyolWindowTooLargeError` fırlatır (stream kullanılmalı veya aralık daraltılmalı). **Sayfalı yineleyicilerde sonlandırma:** `totalPages` varsa ona uyulur. Yoksa (page tabanlı uç noktalarda belgelenmiş bir sonlandırma koşulu yok; yalnız stream'de yoktur ve orada `hasMore` kullanılır) güvenli tarafta kalınır: `totalElements` karşılanana veya boş sayfa gelene kadar devam edilir; boş sayfa geldiği halde `totalElements` kadar kayıt toplanmadıysa "eksik sayfa" `TrendyolProtocolError` olur, sayfa üst sınırı (100.000) aşılırsa yine `TrendyolProtocolError` olur. Sessiz kesme yoktur (kâr hesabı eksik veriyle yapılmasın). Eski `/orders` yolu 15 Ekim 2026'dan beri kapalı olduğu için kullanılmaz.
- **orders/stream:** cursor (`nextCursor`/`hasMore`), `size` en fazla 200 (varsayılan 50), `lastModified` aralığı en fazla 14 gün, son 3 ay; imleç opaktır, filtre değişince yeni akış başlar (her pencere yeni akış). `hasMore` doğru ama imleç yoksa veya tekrarlanıyorsa `TrendyolProtocolError` (sonsuz döngü koruması). Son 3 ay sınırı istemcide denetlenmez (sınır gününün yorumu belirsiz); sunucu 400 verirse `TrendyolRequestError` olur.
- **Finans:** `startDate`-`endDate` en fazla 15 gün; `size` 500 veya 1000; kip tam olarak biri: tarih aralığı, `paymentDate` veya `paymentOrderId`. `iter_settlements`/`iter_other_financials` aralığı otomatik böler. **Pencere sınır kuralı:** her pencere en fazla 15 gün eksi 1 ms'dir ("15 günden uzun olamaz" sınırının tam değerinde 400 riski alınmaz) ve komşu pencereler sınır anını paylaşır. Uç değerlerin dahil/hariç olması doğrulanmadığı için boşluk yerine sınırda yinelenen kayıt tercih edildi; tüketici kayıtları `id` ile tekilleştirmelidir (aynı kural stream ve soru pencereleri için de geçerli, paket ve soru kimliğiyle).
- **Ürünler:** `size` en fazla 100; ilk 10.000 content sayfa ile, sonrası `nextPageToken` ile (token ile `page` gönderilmez). Token geçişinin ayrıntıları doğrulanmadı.
- **Sorular:** `size` en fazla 50, aralık en fazla 14 gün. **İadeler:** `size` en fazla 200; tarih aralığı üst sınırı dokümante değil.
- **Çoklu değer gösterimi** (`transactionTypes`, `packageItemStatuses`, `shipmentPackageIds`, `barcodes`): virgülle ayrılmış tek parametre. Dokümandaki örnek ("Type1, Type2") bu yöndedir; boşluksuz virgül ve tekrarlı parametre farkı doğrulanmadı.

## 7. Karar: anahtar saklama ve `marketplace_accounts`

- **Şifreleme (ADR-0004).** `api_key_encrypted`, `api_secret_encrypted`: **zarf şifreleme** vardır. Her değer için rastgele 256 bit DEK ile AES-256-GCM; DEK, KEK ile sarılır. Biçim `v2:<kid>:<sarılı_dek>:<veri>`; KEK'ler `DATA_KEKS` / `DATA_KEK_ACTIVE` ortam değişkenlerindedir (`docs/10` §3.1 ve G05 ile uyumlu), birden çok kid desteklenir, `python -m app.tools.rewrap_keys` ile döndürülür. AAD `marketplace_accounts:v2:{tenant_id}:{platform}:{seller_id}:{satır id}:{alan}`: değer başka kiracıya, satıcıya, satıra veya alana taşınırsa çözülemez. Satır kimliği uygulamada üretilir (şifrelemeden önce bilinsin diye). Eski `v1:` (FieldCipher, `DATA_ENCRYPTION_KEY`) değerler okunabilir ve `python -m app.tools.migrate_envelope` ile (geri alınabilir) dönüştürülür. **Faz 2 olan yalnız KMS'tir** (KEK'lerin bir KMS'te tutulması); zarf şifreleme bu turda yapıldı. İlk turdaki "zarf şifreleme faz 2" ifadesi `docs/10`'u yanlış aktarıyordu (S2 O-01).
- **Gösterim.** Yalnız API anahtarının son 4 hanesi (`api_key_last4`, düz metin; sır sayılmaz). Sırrın hiçbir parçası saklanmaz veya gösterilmez. İptal sonrası son 4 hane kalır (hangi anahtarın iptal edildiği anlaşılsın).
- **Durumlar.** `active`, `invalid`, `revoked`. CHECK kısıtı tutarlılığı veritabanında garanti eder: `revoked` ise iki şifreli alan NULL ve `revoked_at` dolu, değilse iki alan dolu. `invalid` durumuna geçişi senkron işi yapar (401/403 alınca, ADR-0005 §5); yeniden bağlanma yolu aynı satıcıyla POST'tur (satırı yerinde günceller ve yeni backfill kuyruğa girer).
- **Tekillik.** İstek "kiracı başına aynı platform + satıcı tekil" der. Uygulama: kısmi tekil indeks `(tenant_id, platform, seller_id) WHERE status <> 'revoked'`. İptal edilmiş satırlar geçmiş olarak kalır (veri silme yok) ve aynı satıcı yeniden eklenebilir; etkin veya `invalid` iken ikinci satır açılamaz.
- **Silme.** İptal satırı silmez; şifreli alanlar NULL yapılır. `netkar_app` için `DELETE` yetkisi yoktur ve UPDATE yalnız gerekli sütunlarla sınırlıdır (migrasyon 0005: şifreli sütunlar, `api_key_last4`, `status`, `last_validated_at`, `updated_at`, `revoked_at`). PostgreSQL'de eski satır sürümleri `VACUUM`'a kadar diskte kalabilir; bu yüzden gerçek güvence anahtarın Trendyol panelinden de silinmesidir (API yanıtının ve README'nin uyarısı). RLS: `ENABLE` + `FORCE`, politika `tenant_isolation`; `test_every_tenant_table_has_forced_rls` yeni tabloyu da kapsar.
- **API.** `POST /v1/marketplace-accounts` (owner/admin) Trendyol'a doğrulama çağrısı yapar, başarısızsa hiçbir şey kaydetmez; yanıtta sır yoktur. Sınırlar: IP başına 20 ve kiracı başına 10 deneme/saat, tüm kiracılar için dakikada 60 (platform tavanı; aşımda Trendyol'a gidilmez, 503) (her deneme dışarı çağrı yapar), gövde 8 KiB. Audit: `marketplace_account.connected`, `.reconnected`, `.revoked`, `.validation_failed` (sırsız, yalnız neden kodu). Hata eşlemesi: 401 → 422 `marketplace-credentials-rejected`; 403 → 422 `marketplace-access-denied`; 429 → 503 `marketplace-busy` (`Retry-After: 30`); diğerleri → 502 `marketplace-unavailable`. Ham Trendyol ayrıntısı kullanıcıya aktarılmaz.

## 8. Reddedilen alternatifler

- **Sipariş yanıtını ham JSON olarak saklayıp sonra ayıklamak:** PII diske girer (EK-6 ihlali). Atma noktası saklamadan önce olmak zorunda.
- **Kara liste (PII alanlarını silmek):** Trendyol yeni PII alanı eklerse sızar. Beyaz liste (yalnız modellenen alanlar) güvenli yön.
- **Kovaları baştan PostgreSQL'de tutmak:** her Trendyol çağrısı bir yazma olur; MVP'de gereksiz. Tetik tanımlandı (§3).
- **Tam jitter, sabit gecikme veya Retry-After'ı yok saymak:** sırasıyla bazen sıfıra yakın bekleme, eşzamanlı yeniden deneme çarpışması ve Trendyol'un açık isteğini görmezden gelme.
- **Bağlantı doğrulamada sipariş veya iade çağrısı:** PII taşır ve dar limitli gruptur.
- **`seller_id` için tamsayı sütunu:** int64 sınırı ve JSON sayı belirsizliği; metin + CHECK (rakam deseni) yeterli.

## 9. Açık sorular ve Trendyol'dan teyit beklenenler (K-N07)

Hasan'ın Trendyol'a (Taleplerim/entegrasyon destek) veya canlı pilot hesapla teyit etmesi gereken noktalar. Kodda ilgili yerlerde "doğrulanmadı" yorumu vardır.

1. Rate limitler satıcı, API anahtarı veya IP bazında mı sayılır? (kova anahtarı ve çok satıcılı tek çıkış IP riski; research/01 §4 madde 4)
2. `orders/stream` ve `v2/orders` için güncel limit nedir? (sayfada 1000/dk, tabloda 30-100/dk; stream için ayrı limit yok)
3. Salt okuma rolüyle anahtar üretilebiliyor mu ve doğrulama çağrımız (`inventory-and-price`) hangi rolü gerektirir?
4. User-Agent kuralı: 30 karakter sınırı yalnız entegratör adı için mi yoksa tüm değer için mi? Boşluk ve tire serbest mi? Kendi yazılımımız için `SelfIntegration` mı, kayıtlı entegratör adı mı kullanılmalı?
5. Finans: aralık tam 15 gün kabul ediliyor mu; `startDate`/`endDate` uçları dahil mi; geriye dönük en fazla kaç ay?
6. Çoklu değer parametreleri (`transactionTypes`, `packageItemStatuses`, `shipmentPackageIds`, `barcodes`) virgülle ayrılmış tek parametre olarak mı gönderilmeli, boşluklu mu?
7. Sipariş şeması: OpenAPI referans sayfaları (`id`, `grossAmount`, `lines[].price`...) ile örnek yanıtlar (`shipmentPackageId`, `packageGrossAmount`, `lines[].lineGrossAmount`...) çelişiyor. Hangisi canlıda geçerli? (Örnek yanıt esas alındı; paket kimliği için iki ad da kabul ediliyor.)
8. `orderDate` "GMT+3 ms" etiketi: epoch'a +3 saat mi eklenmiş, normal epoch mı? (Modeller ham ms tutuyor.)
9. `nextPageToken` ilk 10.000 content'ten sonra nasıl çalışıyor (ilk yanıtlarda token var mı, page ile birlikte kullanılabilir mi)?
10. `packageTyDiscount` ve `lineItemTyDiscount` bireysel siparişlerde dolu gelir mi? Ürün `commission` oranı KDV dahil mi? (kâr motoru için; research/01 §4 madde 11)
11. Soru uç noktası: `size` üst sınırı 50 mi 200 mü (doküman 50, OpenAPI 200); `UNANSWERED` durumu OpenAPI listesinde yok.
12. `claims` için tarih aralığı üst sınırı var mı?
13. 429 yanıtlarında `Retry-After` başlığı gönderiliyor mu?
14. Stage ortamı için bulut (dinamik/NAT) IP ile erişim nasıl yetkilendirilir? ("Statik IP'ler için yetkilendirme sağlanamamaktadır" cümlesi belirsiz; research/01 §4 madde 15)
15. `cargoTrackingNumber` ile kargo faturasındaki `parcelUniqueId` eşleşiyor mu?
16. Hukuk: `customerId`'nin takma adlı (tuzlu HMAC) saklanması, EK-6 md. 4.2 ("kayıt yaratma yasağı") karşısında kabul edilebilir mi? Müşteri sorusu serbest metni saklanabilir mi?

## 10. Sonuçlar ve riskler

- Sipariş, iade, ekstre ve ürün verisi artık ADR-0005 ile veritabanına yazılır (soru verisi yazılmaz, serbest metin kararı bekliyor). Bu ADR'nin ilk turunda veri yalnız bellekte okunuyordu.
- Trendyol API'si sık değişiyor (2025-2026 base URL, limit ve zorunlu v2 geçişleri): sözleşme testleri fixture'a dayanır; canlı pilot hesapla fixture'ların doğrulanması gerekir.
- Süreç içi kovalar çoklu worker'da gevşer (§3). Anahtar döndürme vardır (ADR-0004); KMS faz 2.
- Bağlantı doğrulama çağrısı ürün okuma yetkisi ister; rol dar anahtarlarda yanlış reddedebilir (madde 3).
- `invalid` durumuna otomatik geçiş artık senkron işinde yapılır (ADR-0005 §5: 401/403, denetim kaydı, senkron durur). Kullanıcıya "yeniden bağlan" uyarısını gösteren arayüz sonraki turun işidir.
