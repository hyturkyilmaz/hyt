# Google Ads — 2026 Q4

Doğrulama: 24.10.2026 (WebSearch, ikincil kaynaklar)

## Kanal önceliği + bütçe dağılımı (duyuru 14.10.2026, kademeli) — güven: yüksek
- Kapsam: Search, Shopping, Performance Max, Demand Gen.
- **Öncelik:** kanal veya kanal grubu Yüksek/Düşük; varsayılan Yüksek. Google tCPA/tROAS içinde önce Yüksek'i fonlar, kalanı Düşük'e verir.
- **Bütçe dağılımı:** Düşük kanallara günlük ortalama bütçenin %'si kadar tavan. %0 = kapalı. Belirtilen bütçe üzerinden hesaplanır. "En iyi çaba", kesin limit değil.
- Demand Gen: öncelik var, bütçe dağılımı yok.
- PMax / Demand Gen: Search, YouTube, Maps, Gmail, Discover = tek blok "Google kanalları". Arama ağı iş ortakları ve Display ayrı kademelenir.
- Seviyeler: hesap varsayılanı < kampanya < paylaşılan bütçe (override).
- Kampanya toplam bütçesi kullanan Search/Shopping/PMax'te uygulanmadığı iddiası: teyit edilmedi.
- Şubat 2027: Display Expansion kullanan Search kampanyaları geçiş. Mevcut davranış = Display Düşük + %50.

### Senaryolar
| Senaryo | Ayar |
|---|---|
| Küçük bütçe | Display %0, iş ortakları Düşük %5 |
| BF / zirve | Google kanalları Yüksek; Display + iş ortakları Düşük %10–15 |
| Yeni kanal testi | Düşük %5–10, 2–4 hafta |
| Paylaşılan bütçe portföyü | Kural paylaşılan bütçe düzeyinde |

## API v26 → ayda iki sürüm (duyuru 12.10.2026) — güven: yüksek
- Yılda 4 büyük sürüm sürüyor; ara sürümler geriye uyumlu. Sunset değişmedi.
- 2027 taslak: v27 Ocak, v28 Nisan, v29 Temmuz, v30 Ekim. Duyurular üç ayda iki.
- Kendi entegrasyonlarında sürüm izleme ritmini iki haftaya çek.

## Universal Cart (ABD, 15.10.2026) — güven: yüksek
- Search (AI Mode dahil) + Gemini; çok mağazalı tek sepet; Google Pay ile ödeme veya mağaza sepetine aktarma (CreateCart, tek yön).
- Mağaza kayıtlı satıcı; sipariş ve destek mağazada. Ortaklar: Nike, Sephora, Target, Ulta, Walmart, Wayfair, Shopify mağazaları.
- YouTube/Gmail sonra; Avustralya ve Kanada gelecek yıl (Merchant Center UCP hub). TR için doğrudan etkisi yok; ABD'ye ihracat yapanlar feed + UCP hazırlığı.

## Sıfırdan kurulum (özet; detay DOCX Bölüm 6.5)
- **Faz 0 altyapı:** MCC, 2FA, en az yetki · KVKK: CMP + açık rıza + aydınlatma, Consent Mode v2 (4 sinyal), yurt dışı aktarım dayanağı · GA4 + GTM, satın alma birincil dönüşüm, gelişmiş dönüşümler · Lead markası: CRM çevrimdışı dönüşüm · Merchant Center feed.
- **Faz 1 mimari (bütçe payı hipotez):** Brand Search %10–15 · Non-brand Search %30–40 · PMax %35–45 (marka hariç tutma açık) · Demand Gen %10–15. Kanal önceliği her kampanyada bilinçli ayarlanır.
- **Faz 2 öğrenme:** 2 hafta dokunma, bütçe değişimi ≤ %20; 30+ dönüşüm/30 gün → tCPA/tROAS, hedef gerçekleşenin %10–20 gevşeği.
- **Faz 3 ölçek:** aylık kanal önceliği gözden geçirme, büyük dönemlerde mevsimsellik ayarı.

## Kaynaklar
Search Engine Roundtable (2026); TechWyse (2026); Relevant Audience (2026); Limelight Marketing (2026); Common Thread Co. (2026); PPC Land (2026); Digital Commerce 360 (2026).
