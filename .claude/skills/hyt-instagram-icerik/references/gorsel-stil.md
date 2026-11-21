# Görsel stil

Ana kaynak: `icerik/rehber/gorsel-stil-rehberi.md`. Özet:

- Referans: @lawrenceaiseo (kâğıt zemin, el çizimi alt çizgi, renkli zaman çizgisi, kaynak satırı)
  + @badarmunir_official (iş akışı ekranları, koyu ızgaralı "yorum yaz" slaydı).
- 7 slayt kalıbı: Kapak (video) · Ekran (video) · Akış (video) · Önce/Sonra · Kural+Prompt · Matris · CTA (video).
- Şablon: `sablonlar/carousel-7.html`. `data-duration="N"` olan slayt MP4 olur.
- Animasyonlar yalnız CSS (keyframes); `render-media.mjs` kare kare çeker, sonuç deterministik.
- Sol üst: logo işareti + isim; sağ üst: sayaç; alt: kaynak / uygulama satırı.

## Reels yerleşimi (1080×1920)
- Slayt y=160'tan başlar (1080×1350). Boşluk rengi slaytın zemininden otomatik alınır.
- Altyazı kutusu alt kenarı y=1490; en fazla ~9 kelime, koyu kutu, beyaz yazı, BÜYÜK harfli anahtar kelime vurgu renginde.
- Instagram arayüzü üst ~160 px ve alt ~430 px'i kapatır; kritik bilgi oraya konmaz.

## Ekran görüntüsü
- Gerçek ekran varsa tercih edilir (kullanıcıdan iste). Müşteri adı, sipariş no, e-posta, telefon bulanıklaştırılır.
- Yoksa HTML ile temsili ekran + "Temsili ekran" notu. Başka markanın logosu kullanılmaz.
- Stok görsel siteleri bu ortamda kapalı olabilir; grafik ve şema HTML/SVG ile üretilir.
