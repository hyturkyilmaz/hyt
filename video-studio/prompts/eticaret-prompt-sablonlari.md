# Wan2.1 için e-ticaret prompt şablonları

Wan, İngilizce promptlarda daha tutarlı sonuç veriyor. Seslendirme ve altyazıyı OpenMontage Türkçe yapabiliyor. Prompt'u şu sırayla kur:

**Özne + ortam + hareket + kamera + ışık + stil**

Negatif prompt'u elle yazmana gerek yok. OpenMontage, Wan ekibinin önerdiği negatif prompt'u otomatik ekliyor.

## Şablonlar

| Kullanım | Prompt |
|---|---|
| Ürün vitrini | `A [product] on a [surface], slow 360-degree orbit shot, soft studio lighting, shallow depth of field, clean white background, commercial product photography style` |
| Doğal ortam | `A [product] placed on a rustic wooden table in a sunlit kitchen, steam rising, slow dolly in, warm morning light, cinematic, 4k commercial` |
| Kategori açılışı (hook) | `Fast macro shot of [material/texture], dramatic side light, particles floating, slow motion, dark background, premium brand aesthetic` |
| Yaşam tarzı | `Hands gently unboxing a [product] on a linen bedsheet, top-down shot, natural window light, calm and cozy mood` |
| Mevsimsel kampanya | `[product] surrounded by [autumn leaves / snow / spring flowers], gentle wind, slow pan left, golden hour light, festive commercial` |

## Örnek (Reels, 3 sahne, 15 sn)

```bash
.../python wan_openmontage.py --seconds 15 --width 480 --height 832 \
  --prompt "handmade olive oil soap commercial" \
  --shot "Macro shot of green olive oil soap bar, water droplets, dramatic side light" \
  --shot "Soap bar slowly rotating on wet slate stone, olive branches around, soft light" \
  --shot "Hands lathering soap under running water, gentle foam, bright bathroom, slow motion"
```

## Dikkat

- 1.3B model yazıyı ve logoyu düzgün çizemiyor. Marka adı, fiyat ve slogan gibi metinleri OpenMontage'a Remotion katmanı olarak ekletmek daha iyi sonuç veriyor.
- Gerçek ürün görüntüsünün birebir aynısı çıkmaz. Ürünün kendisini göstermen gereken sahnelerde gerçek fotoğraf ya da çekim kullan, Wan'ı atmosfer ve geçiş sahnelerinde kullan.
- Tanınan bir kişiye benzeyen yüz, başka markanın logosu ya da telifli karakter isteme.
