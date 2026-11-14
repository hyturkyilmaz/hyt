# Runbook: takılan rapor motoru (kalıcı 503 report-busy / 429)

Kapsam: kâr raporu uçları (`/profit/*`). Denetim bulgusu DK-10.

## Belirti

- Raporlar sürekli `503` ve `type: ...report-busy` (süreç doluluğu) ya da `429` ve `...report-in-progress`
  (kiracı doluluğu) döner; `Retry-After` sonrası yeniden deneme de aynı yanıtı verir.
- Yük düşük olduğu halde sürer; önbellek isabeti olan (aynı dönem) istekler çalışmaya devam eder.

## Neden

Hesap üst süresi (`PROFIT_REPORT_COMPUTE_TIMEOUT_SECONDS`) dolunca istek `503 report-compute-timeout` alır,
ancak motor Python iş parçacığında çalıştığı için öldürülemez. Kapı yuvası, iş parçacığı GERÇEKTEN bitene dek
tutulur (süreçte en çok N motor sınırı bozulmasın diye). Takılı (hiç bitmeyen) bir motor yuvasını süreç yeniden
başlayana dek tutar: `PROFIT_REPORT_TENANT_CONCURRENCY` kadar takılı motor o kiracıyı kalıcı 429'a,
`PROFIT_REPORT_PROCESS_CONCURRENCY` kadar takılı motor bütün raporları kalıcı 503'e sokar.

## Nasıl tespit edilir

Uygulama günlüğünde (WARNING) yapılandırılmış anahtarlar:

- `profit_engine_abandoned pid=<süreç> account=<hesap> abandoned=<N> process_slots=<M>`: bir motor terk edildi; `N` o
  andaki terk edilmiş ama hâlâ çalışan motor sayısıdır.
- `profit_engine_abandoned_finished pid=<süreç> account=<hesap> abandoned=<N>`: terk edilen motor sonunda bitti, yuva
  bırakıldı (`N` kalan sayı).
- Karar kuralı: `abandoned` değeri `process_slots`'a eşitse bütün raporlar bloktur; aynı `pid` için son `abandoned` kaydı
  için karşılığında `..._finished` kaydı gelmiyorsa motor takılıdır. Yavaş ama biten motorlar `..._finished`
  ile kapanır, müdahale gerekmez.
- Ayrıca `profit_statement_timeout` / `db_statement_timeout` kayıtları veritabanı tarafı aşımını gösterir.

Not: Bu ortamda metrik altyapısı (prometheus vb.) yoktur ve sağlık ucuna sayaç eklenmemiştir; izleme log
anahtarları üzerindendir (log tabanlı uyarı kuralı: `profit_engine_abandoned` içeren satırda `abandoned >=
process_slots`).

## Çözüm

1. API sürecini yeniden başlatın (takılı iş parçacığı yalnız süreçle birlikte kalkar; zarif kapanış takılı
   motoru bekleyebilir, gerekirse süreci zorla sonlandırın). Çok süreçli dağıtımda sayaç süreç başınadır:
   log satırındaki `pid` alanı hangi sürecin takıldığını verir, yalnız o süreci yeniden başlatın.
2. Takılmaya yol açan girdiyi araştırın: log'daki `account=<hesap>` için o hesabın dönem verisi (satır
   sayısı, tutarsız kayıtlar), motor girdisi ve son senkron/maliyet içe aktarma işlemleri. Aynı hesap ve dönemle
   yeniden denenince tekrar ediyorsa hata raporu açın; tekrarda aynı hesabın raporu kalıcı olarak yuva tüketir.
3. Geçici önlem: `PROFIT_REPORT_PROCESS_CONCURRENCY` değerini artırmak yuva tükenmesini geciktirir ama kök
   nedeni gidermez.
