# NetKâr (çalışma adı)

Trendyol satıcıları için ürün bazında **gerçek net kâr**: komisyon, komisyon KDV'si, kargo, iade, reklam ve hakediş ekstresi düşüldükten sonra kalan para. Sipariş anında tahmini, ekstre gelince kesinleşmiş kâr.

## Durum
- Faz: S0 Kapı (araştırma ve karar). Bkz. `docs/30_yol_haritasi.md`.
- Proje takibi: Trello "HYT Proje Yönetimi" panosu, `NetKâr ·` ile başlayan sütunlar.
- Koordinasyon: "NetKâr Ürün Koordinatörü" zamanlanmış görevi.

## Dokümanlar
| Dosya | İçerik |
|---|---|
| `docs/00_yonetici_ozeti.md` | Karar özeti, GO/NO-GO, maliyet, sonraki adımlar |
| `docs/10_mimari.md` | Sistem mimarisi, veri modeli, ölçek planı |
| `docs/20_maliyet.md` + `calisma_dosyalari/NetKar_Maliyet_Modeli.xlsx` | Aylık/yıllık işletim maliyeti ve başabaş |
| `docs/30_yol_haritasi.md` | Faz ve sprint planı |
| `docs/40_ajan_promptlari.md` | Ajan rolleri, model rotası, prompt kütüphanesi |
| `docs/50_guvenlik.md` | Güvenlik ve uyum gereksinimleri |
| `docs/research/01-06` | Trendyol API, rakipler, hukuk, altyapı fiyatları, pazarlama, web planı |

## Planlanan kod yapısı
```
netkar/
  apps/web/          Next.js 15 (LP + panel, PWA)
  services/api/      Python FastAPI + kâr motoru + Trendyol istemcisi + worker
  infra/             Docker Compose, Coolify/Dokploy, yedek betikleri
  docs/              Dokümanlar
  calisma_dosyalari/ Analiz scriptleri, ara veriler, fiyat CSV'leri, log
```

## Çalışma kuralları
Veri silme yok, önce yedek, her değişiklik `calisma_dosyalari/degisiklik_kaydi.tsv` dosyasına. Yayın, ödeme, e-posta gönderimi, prod deploy ve geri alınamaz işler Hasan onayıyla.
