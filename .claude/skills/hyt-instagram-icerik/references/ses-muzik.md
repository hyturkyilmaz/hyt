# Ses ve müzik

## Klon ses (yalnız Hasan Yasin'in kendi sesi, kendi rızasıyla)
- Model: Chatterbox Multilingual (Resemble AI) — MIT lisans, Türkçe, sıfır atış klonlama. Ticari kullanıma uygun.
- XTTS-v2 (Coqui, CPML) ticari kullanım için uygun değil; Instagram lead/reklam işinde kullanılmaz.
- Referanslar: Drive `video-klon/ref/hasan_ref_kisa_1..6.wav`, `hasan_ref_3dk.wav`.
- Defter: Drive `video-klon/HYT_ses_klon_chatterbox.ipynb` (repo kopyası `icerik/ses/`). Colab T4 GPU.
- Girdi `video-klon/senaryo/<id>.json` → çıktı `video-klon/cikti/<id>/tam.wav` + `zamanlama.json`.
- Bulut oturumunda huggingface.co kapalı olabilir; klonlama Colab'da yapılır, çıktı sohbete yüklenir.

## Müzik
- `python3 icerik/araclar/muzik-uret.py <cikti.wav> <sn> <tohum>` — tamamen sentez, özgün, telifsiz.
  84 BPM lo-fi/podcast altlığı; farklı tohum = farklı akor dizisi.
- Hazır: `icerik/marka/muzik/hyt-altlik-01..03.wav` (60 sn).
- Trend ses gerekiyorsa: Instagram/TikTok uygulamasında lisanslı kütüphaneden, paylaşım anında eklenir.
  Telifli trend parça dosyaya gömülmez.

## Miks
- `python3 icerik/araclar/build-reels.py --medya ... --senaryo ... --muzik ... --ses tam.wav --zamanlama zamanlama.json --cikti ...`
- Konuşma -16 LUFS; müzik -16 LUFS'a eşitlenip ×0.09 (%9, ≈ -21 dB); final -14 LUFS, AAC 192k, 48 kHz.
- Ses yoksa: kelime sayısından süre tahmini, müzik tam seviye (altyazılı sessiz sürüm).
