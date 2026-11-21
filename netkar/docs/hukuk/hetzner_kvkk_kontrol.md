# Hetzner ve KVKK: yurt dışı aktarım kontrol listesi

Tarih: 2026-11-10. Durum: K-N02 koşullu. Hukuki görüş değildir; canlıya almadan önce KVKK konusunda çalışan bir avukatın teyidi gerekir.

## Özet

- NetTablo Hetzner'de (Almanya/Finlandiya) çalışırsa satıcı hesaplarına ait kişisel veri (ad, e-posta, şahıs şirketi satıcının kimliği) yurt dışına aktarılmış olur. Son müşteri kişisel verisi zaten saklanmaz (docs/10_mimari.md §5), bu yüzden aktarım satıcı verisiyle sınırlı kalır.
- KVKK m.9 (2024 değişikliği): yeterlilik kararı yoksa düzenli aktarım için uygun güvencelerden biri gerekir. Bizim için gerçekçi olan **Kurul'un standart sözleşmesi** (veri sorumlusundan veri işleyene modülü).
- Standart sözleşme Kurul metniyle, iki tarafın da imzasıyla yapılır; imzadan sonra **5 iş günü içinde** Kurum'a bildirilir (KEP, fiziki ya da Standart Sözleşme Bildirim Modülü). Bildirim yapılmazsa idari para cezası var (kaynaklara göre 2026 için 90.308 TL ile 1.806.377 TL arası; tutarı resmi kaynaktan teyit et).
- Açık rıza artık düzenli aktarım dayanağı değil; yalnız arızi (tek seferlik) istisnalarda kullanılabilir. Bu yüzden SaaS için çözüm olmaz.

## Engel

Hetzner, kişilerin ya da şirketlerin kendi hazırladığı veri işleme sözleşmelerini imzalamadığını, DPA'nın yalnız müşteri panelinden oluşturulduğunu açıklıyor. Türk standart sözleşmesini imzalayıp imzalamayacağı bilinmiyor (güven: orta). İmzalamazsa Hetzner ile KVKK'ya uygun düzenli aktarım yolu kalmaz.

## Hasan'ın yapacakları (sırayla)

1. Hetzner destek ekibine aşağıdaki soruyu gönder (hesap açmadan, iletişim formundan).
2. Yanıt "imzalarız" ise: Kurul'un standart sözleşme metnini (veri sorumlusu -> veri işleyen modülü) iki taraf imzalar; imza tarihinden itibaren 5 iş günü içinde Kurum'a bildirim. Avukat teyidi.
3. Yanıt "imzalamayız" ise: K-N02 Güzel Hosting'e (yurt içi) döner. Fark 844 TL/ay (10.130 TL/yıl).
4. Her iki durumda: aydınlatma metnine yurt dışı aktarım bilgisi, VERBİS yükümlülüğü kontrolü (şahıs şirketi eşikleri), Trendyol sözleşmesi EK-6 ile çelişki olmadığının teyidi (son müşteri verisi saklanmadığı için risk düşük, emin değilim).

## Hetzner'e gönderilecek soru (İngilizce taslak, gönderilmedi)

> Subject: Signing the Turkish KVKK standard contract for international data transfer
>
> Hello,
>
> We are a Turkish company planning to host a SaaS application on Hetzner Cloud (Germany or Finland). Under Article 9 of the Turkish Personal Data Protection Law (KVKK, Law No. 6698, as amended in 2024), transfers of personal data abroad require a standard contract published by the Turkish Personal Data Protection Board, signed by both parties, and notified to the Authority within 5 business days.
>
> Before we open an account, we need to know:
> 1. Would Hetzner Online GmbH sign the Board's standard contract (controller to processor module) in addition to your DPA?
> 2. If not, is there any other mechanism you offer for Turkish customers?
>
> Thank you.

## Kaynaklar

- Kişisel Verileri Koruma Kurumu. (2024). *Standart sözleşmeler*. https://www.kvkk.gov.tr/Icerik/7929/Standart-Sozlesmeler
- Kişisel Verileri Koruma Kurumu. (2025, 5 Şubat). *Yurt dışına kişisel veri aktarımında kullanılacak standart sözleşmelerde dikkat edilmesi gereken hususlara ilişkin kamuoyu duyurusu*. https://www.kvkk.gov.tr/Icerik/8170/Yurt-Disina-Kisisel-Veri-Aktariminda-Kullanilacak-Standart-Sozlesmelerde-Dikkat-Edilmesi-Gereken-Hususlara-Iliskin-Kamuoyu-Duyurusu
- Hetzner Online GmbH. (t.y.). *Data protection at Hetzner*. https://docs.hetzner.com/general/company-and-policy/data-protection-at-hetzner
- Cott Group. (t.y.). *Standart sözleşme bildirim yükümlülüğü ve yaptırımları*. https://cottgroup.com/tr/blog/kvkk-gdpr/item/standart-sozlesme-bildirim-yukumlulugu-ve-yaptirimlari (akademik kaynak değil; avukatlık/danışmanlık notu)
