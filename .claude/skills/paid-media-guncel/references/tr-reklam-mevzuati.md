# Türkiye Reklam Mevzuatı — 2026

Doğrulama: 24.10.2026. Hukuki görüş değildir; uygulama öncesi resmi metin (RG 33297) ve hukuk ekibi kontrolü gerekir.

## Ticari Reklam ve Haksız Ticari Uygulamalar Yönetmeliği değişikliği — güven: yüksek
- Resmî Gazete 33297, 01.07.2026; yürürlük 01.08.2026.
- **İndirim öncesi fiyat:** indirimin başladığı tarihten önceki **10 gün** içindeki en düşük fiyat (önceden 30 gün).
- Sadece indirimin yapıldığı **satış kanalındaki** fiyat dikkate alınır.
- Çabuk bozulan ürün (meyve-sebze) ve hizmetlerde: indirimden hemen önceki fiyat.
- Kolay erişilebilir sadakat programı indirimleri de kapsamda.
- "Hedefli reklam" kavramı ilk kez tanımlandı; AI ile üretilen reklamlar ve influencer tanıtımları kapsamda. AI açıklama yükümlülüğünün tetikleyicileri resmi metinden kontrol edilmeli (teyit edilmedi).
- Aldatıcı indirim reklamında ceza üst sınırı 39,9 milyon TL olarak aktarılıyor (tek kaynak).

## Denetim verisi — güven: yüksek
- Reklam Kurulu 08.10.2026: 161 dosya, 136 durdurma, 17.176.744 TL ceza; 32 sosyal medya hesabı için resen inceleme.
- 2026 ilk 9 ay: 33.000+ başvuru, 249 milyon TL+ ceza.
- Ekim odakları: 10 gün kuralına uymama, sadakat kartı kampanyaları.

## Referans penceresi hesabı (Python)
```python
import datetime as dt
def referans_penceresi(baslangic: dt.date):
    return baslangic - dt.timedelta(days=10), baslangic - dt.timedelta(days=1)
```
2026: BF 27.11 (Cuma) → pencere 17–26.11 · Cyber Monday 30.11 (Pazartesi) · 1 Kasım başlangıç → pencere 22–31.10.

## Uyum kontrol listesi
- Fiyat geçmişi kanal bazında günlük loglanır (DB + ekran görüntüsü).
- "…'e varan" ifadesinde en yüksek oranlı ürünler belgelenir ve kampanya süresince stokta tutulur.
- Kart, üyelik, sepette indirim koşulları reklamın kendisinde açık.
- Gerçek stok/süre bilgisi; sahte geri sayım yok.
- Influencer işbirliğinde reklam etiketi baştan.
- AI ile üretilen/değiştirilen görsel ürünü olduğundan farklı göstermez; iç onay.

## KVKK hatırlatmaları
- Pixel, CAPI, gelişmiş dönüşümler, müşteri listesi yükleme → açık rıza + aydınlatma + yurt dışına aktarım dayanağı.
- Consent Mode v2 sinyalleri CMP ile senkron.
