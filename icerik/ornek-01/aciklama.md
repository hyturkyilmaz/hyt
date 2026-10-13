# Örnek 01 — Amazon satıcı panelini Claude'a açtı

## Yayın künyesi

| Alan | Değer |
|---|---|
| Format | Carousel, 7 slayt, 1080×1350 |
| Sütun | AI haberi → pratik etki |
| Önerilen yayın | Çarşamba 14 Ekim 2026, 20:50 TRT |
| Yedek pencere | Perşembe 15 Ekim 2026, 09:10 TRT |
| Anahtar kelime | AJAN |
| Lead magnet | "Ajana Hazır Mağaza" kontrol listesi (`lead-magnet-kontrol-listesi.md`) |
| Medya (v2) | `v2/medya/` — yükleme sırası aşağıda |

## Yükleme sırası (v2, karışık carousel)

| # | Dosya | Tür |
|---|---|---|
| 1 | `slayt-01.mp4` | Video 6 sn — kapak, alt çizgi ve zaman çizgisi animasyonu |
| 2 | `slayt-02.mp4` | Video 8 sn — sohbet ekranı, istek yazılıyor, tablo geliyor |
| 3 | `slayt-03.mp4` | Video 6 sn — ajan iş akışı, akan bağlantılar |
| 4 | `slayt-04.png` | Görsel — önce/sonra katalog tablosu |
| 5 | `slayt-05.png` | Görsel — kural bloğu + Claude prompt'u |
| 6 | `slayt-06.png` | Görsel — onay matrisi |
| 7 | `slayt-07.mp4` | Video 5 sn — AJAN çağrısı |

- Reels: `reels-1080x1920.mp4` (35 sn, sessiz). Perşembe yayınlanır, ses uygulama içinden eklenir.
- GIF: `onizleme-sohbet.gif` — LinkedIn, site ve WhatsApp paylaşımı için.
- Her PNG'nin bir de statik hali var (`slayt-0X.png`); video yüklenemezse onlar kullanılır.

Reels ve GIF üretimi:

```
ffmpeg -i slayt-0X.mp4 -vf "pad=1080:1920:0:285:color=0xf5f7fa" ... (bkz. gorsel-stil-rehberi.md)
ffmpeg -i slayt-02.mp4 -vf "fps=15,scale=540:-1,split[a][b];[a]palettegen[p];[b][p]paletteuse" onizleme-sohbet.gif
```

## Açıklama metni (kopyala-yapıştır)

```
Amazon satıcı panelini Claude'a açtı. Bunu sadece bir Amazon haberi sanma.

23 Eylül'de Amazon Accelerate'te duyurdular: Seller Assistant artık Claude'un içinden çalışıyor. Stok bakıyor, fiyat değiştiriyor, ürün sayfası düzenliyor. Her adım satıcının onayıyla. Şimdilik ABD'de, beta ve ücretsiz.

Haberi okuyunca aklıma ilk müşterilerimzin Excel dosyaları geldi. Aynı ürünün üç farklı adla kayıtlı olduğu, stok kuralının tek bir çalışanın kafasında durduğu dosyalar. Ajan o dosyayı okuyamaz. Okusa da yanlış okur.

Bu düzende paneli iyi bilen değil, verisi düzenli olan kazanacak. Pazaryerleri de bu yöne gidiyor. Bence Türkiye'ye gelmesi uzun sürmez.

Kaydırınca 3 hazırlığı göreceksin. Hepsi bu hafta başlanabilecek işler.

Yorumlara AJAN yaz, 10 maddelik "Ajana Hazır Mağaza" kontrol listesini DM'den göndereyim.

#eticaret #yapayzeka #claude #amazon #dijitalpazarlama
```

## Üretim notu (yayınlanmaz)

- Yazım hatası: 3. paragraf, "müşterilerimzin" (doğrusu: müşterilerimizin). Görsellerde hata yok.
- Doğrulama: Seller Assistant'ın Claude entegrasyonu, 23 Eylül 2026 Amazon Accelerate duyurusu, onay şartı, ABD betası ve ücretsiz olması en az iki bağımsız kaynakta geçiyor.
- Kullanılmayan iddia: "Claude reklam ayarı da yapabiliyor" bilgisi tek ve zayıf kaynakta geçtiği için metne alınmadı.
- İlk 60 dakika: tüm AJAN yorumlarına kısa yanıt ("Gönderdim, DM'e bak").
- Reels türevi (Perşembe): slayt 1 + 4 + 5 + 6, sesli anlatım 25-30 sn.

## Kaynakça

Seller Labs. (2026). *Amazon put its AI in Claude for free. Did it just kill Seller Labs?* https://www.sellerlabs.com/blog/amazon-seller-assistant-claude/

AI Weekly. (2026, Eylül). *Amazon opens seller tools to outside AI agents, starts with Claude on Bedrock at Accelerate*. https://aiweekly.co/alerts/amazon-opens-seller-tools-to-outside-ai-agents-starts-with-claude-on-bedrock-at

My Amazon Guy. (2026). *Amazon AI Seller Assistant Claude integration is here*. https://myamazonguy.com/?p=175600
