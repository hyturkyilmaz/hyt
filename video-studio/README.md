# HYT Video Stüdyosu: Wan2.1 + OpenMontage

## Özet

- **Wan2.1**, Alibaba'nın açık kaynak video üretim modeli (Apache-2.0). Yazıdan video üretiyor ve kendi GPU'nda ücretsiz çalışıyor.
- **OpenMontage**, işin prodüksiyon tarafını üstleniyor: senaryo, sahne planı, seslendirme, müzik, altyazı, kurgu ve render. Claude Code ile konuşarak kullanılıyor.
- İkisi zaten birbirine bağlı. OpenMontage'ın içinde `wan_video` adlı bir araç var ve Wan2.1'i diffusers üzerinden çağırıyor. Bu klasördeki scriptler kurulumu, model seçimini ve `.env` ayarlarını tek seferde yapıyor.
- **GPU şart.** NVIDIA kart gerekiyor, en az 8 GB VRAM (Wan2.1 1.3B için). Linux ya da Windows'ta WSL2 olur. Mac ve CPU'da pratik değil.
- **Maliyet:** Kendi kartında sadece elektrik parası ödersin. Bulut GPU kiralarsan saatlik ücret çıkar (aşağıda anlatılıyor).

## Hedefler

1. Tek komutla kurulum: `setup.sh`
2. VRAM'e göre doğru Wan2.1 modelini otomatik seçmek
3. Kısa sahne klibi üretimi: `wan_openmontage.py`
4. Tam reklam veya tanıtım videosu: OpenMontage ajanı ve Wan klipleri birlikte
5. İsteğe bağlı olarak resmi Wan2.1 `generate.py` yolu: `wan_native.sh`

---

## 1. Donanım ve model seçimi

| GPU VRAM | Model | Ne yapar | İndirme |
|---|---|---|---|
| 8–40 GB (RTX 3060 12GB, 4070, 4090 vb.) | `wan2.1-1.3b` | Yazıdan video, 480p, 16 fps | ~29 GB |
| 40 GB+ (A100, H100) | `wan2.1-14b` | Yazıdan video, 720p, daha yüksek kalite | çok daha büyük |

- Resmi rakam şöyle: 1.3B model 8.19 GB VRAM ile çalışıyor. RTX 4090'da 5 saniyelik 480p video yaklaşık 4 dakika sürüyor (Wan Team, 2025).
- 1.3B modelinde **görselden video (image-to-video) yok**. Ürün fotoğrafını hareketlendirmek istersen 14B I2V modeli ya da `wan2.2-ti2v-5b` gerekiyor (12 GB+). İstersen `WAN_MODEL=wan2.2-ti2v-5b bash setup.sh` ile kurabilirsin.
- Disk için en az 60 GB boş yer ayır: model, önbellek ve render dosyaları.

## 2. Kurulum

```bash
# hyt deposundan
cd video-studio
bash setup.sh                                 # ~/hyt-video-studio altına kurar
bash download_models.sh wan2.1-1.3b           # ~29 GB, kesilirse tekrar çalıştır
```

Önce şunlar kurulu olmalı: `git`, `python3` (3.10+), `ffmpeg`, `node`/`npm` (18+) ve NVIDIA sürücüsü.

`setup.sh` şunları yapıyor:
- OpenMontage ve Wan2.1 depolarını test edilmiş commit'e sabitleyerek indiriyor
- `make setup` ve `make install-gpu` komutlarını çalıştırıyor (torch, diffusers, Remotion, Piper TTS)
- OpenMontage `.env` dosyasına sadece şu üç satırı yazıyor: `VIDEO_GEN_LOCAL_ENABLED=true`, `VIDEO_GEN_LOCAL_MODEL=...` ve `HF_HOME=...`. Diğer ayarlara ve API anahtarlarına dokunmuyor.
- Hiçbir dosyayı silmiyor. Tekrar çalıştırırsan sadece güncelliyor.

Resmi Wan2.1 komut satırını da istersen:

```bash
bash setup.sh --native
bash download_models.sh wan2.1-1.3b --native  # +17.5 GB
```

> Resmi yol `flash-attn` paketine mecbur. Bu paketin derlenmesi 10–40 dakika sürüyor ve sadece Linux'ta sorunsuz çalışıyor. OpenMontage yolunun buna ihtiyacı yok, o yüzden önerdiğim yol OpenMontage.

## 3. Kullanım

### a) Kurulumu doğrula (GPU'ya dokunmaz)

```bash
~/hyt-video-studio/OpenMontage/.venv/bin/python wan_openmontage.py \
  --prompt "A ceramic coffee mug on a wooden table, morning light" --dry-run
```

Çıktıda `"durum": "available"` görmelisin. Model, boyut, kare sayısı ve tahmini süre de listelenir.

### b) Tek sahne klibi

```bash
# hızlı taslak (20 adım)
.../python wan_openmontage.py --prompt "..." --seconds 5 --steps 20
# 15 saniyelik, 3 çekimlik klip
.../python wan_openmontage.py --prompt "product commercial" --seconds 15 \
  --shot "close-up of the bottle, water droplets" \
  --shot "bottle slowly rotates on a marble surface" \
  --shot "soft light sweep, bottle in center"
```

Wan tek seferde yaklaşık 5 saniye üretebiliyor. Daha uzun kliplerde OpenMontage parçaları birbirine ekliyor: her parça bir öncekinin son karesinden başlıyor ve renkler dengeleniyor. Süre de parça sayısıyla doğru orantılı artıyor.

### c) Tam video (asıl kullanım)

```bash
cd ~/hyt-video-studio/OpenMontage
claude
```

Ajana doğal dille yaz, örneğin:

```text
wan_video (wan2.1-1.3b) kullanarak 30 saniyelik dikey (9:16) bir Instagram Reels
reklamı yap: el yapımı zeytinyağlı sabun. Türkçe seslendirme Piper ile,
telifsiz müzik, kelime kelime altyazı. Önce konsept ve maliyet tahmini göster.
```

OpenMontage senaryoyu, sahne planını, seslendirmeyi, müziği, altyazıyı ve kurguyu kendisi yapıyor. Wan'ı sadece sahne kliplerini üretmek için kullanıyor. Her aşamada onay istiyor. Masrafı sıfırda tutmak istersen `config.yaml` içinde `budget.mode: cap` ve `total_usd: 0` yap. Bu ayarla ücretli araç çağrıları bütçe aşımı hatasıyla durur. Yine de API anahtarlarını `.env` dosyasına hiç girmemek en garanti yol.

### d) Resmi generate.py ile klip

```bash
bash wan_native.sh "A red sneaker floating and slowly rotating, studio light"
```

Klip `OpenMontage/library/wan/` klasörüne kaydediliyor. Ajana "bu klibi kullan" demen yeterli.

Prompt örnekleri için [`prompts/eticaret-prompt-sablonlari.md`](prompts/eticaret-prompt-sablonlari.md) dosyasına bak.

## 4. GPU yoksa

| Seçenek | Maliyet | Not |
|---|---|---|
| Kendi PC'ne ikinci el RTX 3060 12GB | tek seferlik donanım | Uzun vadede en ucuzu. Elektrik dışında gider yok. |
| Bulut GPU kiralamak (RunPod, Vast.ai, Lambda) | saatlik, RTX 4090 sınıfı genelde saati 1 $'ın altında | Sadece render zamanı aç, iş bitince kapat. Güncel fiyatı sağlayıcıdan kontrol et. |
| OpenMontage'ın ücretli API'leri (Kling, Veo, fal.ai) | video başına ücret | GPU gerektirmez ama her üretim para tutar. |

Bulutta çalışırken bir şeye dikkat et. Diskte model ve çıktılar varken makine durdurulursa depolama ücreti işlemeye devam edebiliyor. İşin bitince çıktıları indir, sonra makineyi tamamen sil.

## 5. Hukuki notlar

- **Lisanslar:** Wan2.1 Apache-2.0, ticari kullanım serbest. OpenMontage AGPLv3. Kendi bilgisayarında kullanmakta sorun yok ama OpenMontage'ı değiştirip bir web hizmeti olarak başkalarına açarsan kaynak kodu da paylaşman gerekiyor. Ürettiğin videolar bu yükümlülüğün kapsamında değil.
- **KVKK / GDPR:** Yerel üretimde prompt ve görseller makineden dışarı çıkmıyor. Gerçek bir kişinin yüzünü, sesini ya da müşteri verisini kullanacaksan açık rıza al. Ücretli bulut API'lerine gönderilen veriler yurt dışına aktarılmış sayılır.
- **Reklam etiği:** Yapay zekayla üretilmiş görüntüyü "gerçek ürün çekimi" gibi sunmak, Ticaret Bakanlığı'nın haksız ticari uygulama kurallarıyla sorun yaratabilir. Ürünün gerçek özelliklerini abartan sahneler kullanma.

## 6. Sorun giderme

| Belirti | Çözüm |
|---|---|
| `durum: unavailable` | `.env` içinde `VIDEO_GEN_LOCAL_ENABLED=true` var mı kontrol et. `make install-gpu` çalıştı mı? |
| CUDA out of memory | `--width 640 --height 368` ile çözünürlüğü düşür. Olmazsa `precision` değerini `int8` yap (bitsandbytes gerekir). |
| Çok yavaş | `--steps 20` ile taslak çıkar, beğendiğini 50 adımla yeniden üret. |
| Görüntü donuk veya statik | Promptu İngilizce yaz ve kamera hareketini belirt ("slow dolly in", "orbit"). |
| `flash_attn` hatası | Sadece resmi yolda çıkar. OpenMontage yolunu kullan. |

---

## Kaynakça

calesthio. (2026). *OpenMontage: The first open-source, agentic video production system* [Computer software]. GitHub. https://github.com/calesthio/OpenMontage

Hugging Face. (2025). *Wan-AI/Wan2.1-T2V-1.3B-Diffusers* [Model card]. https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B-Diffusers

Wan Team. (2025). *Wan: Open and advanced large-scale video generative models* (arXiv:2503.20314). arXiv. https://arxiv.org/abs/2503.20314

Wan Team. (2025). *Wan2.1* [Computer software]. GitHub. https://github.com/Wan-Video/Wan2.1
