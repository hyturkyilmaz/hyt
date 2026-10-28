"""Gönderi klasörünü kalite kapısından geçirir.

Kullanım: python3 .claude/skills/hyt-instagram-icerik/scripts/kontrol.py <gonderi-klasoru> [--medya alt/klasor]

Kontrol eder: slayt ölçüleri, video süre/codec, hareketli slayt sayısı, Reels ölçüsü ve ses
seviyesi, açıklama uzunluğu, hashtag sayısı, üretim notunda yazım hatası kaydı, senaryo alanları.
Çıkış kodu: 0 = hepsi geçti, 1 = en az bir hata.
"""
import glob
import json
import os
import re
import subprocess
import sys


def probe(yol):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height:format=duration",
                          "-of", "json", yol], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def lufs(yol):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", yol, "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", out.stderr)
    return float(m[-1]) if m else None


sonuc = []


def kayit(ok, ad, detay=""):
    sonuc.append((ok, ad, detay))


def main():
    kok = sys.argv[1]
    medya = os.path.join(kok, sys.argv[sys.argv.index("--medya") + 1]) if "--medya" in sys.argv else os.path.join(kok, "medya")

    # Slaytlar
    pngs = sorted(glob.glob(os.path.join(medya, "slayt-*.png")))
    kayit(len(pngs) >= 5, "Slayt sayısı ≥ 5", f"{len(pngs)}")
    for p in pngs:
        v = [s for s in probe(p)["streams"] if s["codec_type"] == "video"][0]
        kayit((v["width"], v["height"]) == (1080, 1350), f"{os.path.basename(p)} 1080×1350", f"{v['width']}×{v['height']}")

    mp4s = sorted(glob.glob(os.path.join(medya, "slayt-*.mp4")))
    kayit(len(mp4s) >= 2, "Hareketli slayt ≥ 2", f"{len(mp4s)}")
    for p in mp4s:
        d = probe(p)
        v = [s for s in d["streams"] if s["codec_type"] == "video"][0]
        sure = float(d["format"]["duration"])
        kayit(v["codec_name"] == "h264" and (v["width"], v["height"]) == (1080, 1350) and 3 <= sure <= 60,
              f"{os.path.basename(p)} H.264 1080×1350 3-60 sn", f"{v['codec_name']} {v['width']}×{v['height']} {sure:.1f} sn")

    # Reels
    for p in sorted(glob.glob(os.path.join(medya, "reels*.mp4"))):
        d = probe(p)
        v = [s for s in d["streams"] if s["codec_type"] == "video"][0]
        a = [s for s in d["streams"] if s["codec_type"] == "audio"]
        kayit((v["width"], v["height"]) == (1080, 1920), f"{os.path.basename(p)} 1080×1920", f"{v['width']}×{v['height']}")
        if a:
            l = lufs(p)
            kayit(l is not None and -15.5 <= l <= -12.5, f"{os.path.basename(p)} ses -14 LUFS ±1.5", f"{l}")

    # Açıklama
    acik = os.path.join(kok, "aciklama.md")
    if os.path.exists(acik):
        md = open(acik, encoding="utf-8").read()
        m = re.search(r"## Açıklama metni.*?```\n(.*?)```", md, re.S)
        metin = m.group(1).strip() if m else ""
        kayit(600 <= len(metin) <= 1200, "Açıklama 600-1.200 karakter", f"{len(metin)}")
        tags = re.findall(r"#\w+", metin)
        kayit(3 <= len(tags) <= 5, "Hashtag 3-5", f"{len(tags)}")
        kayit(bool(re.search(r"[Yy]azım hatası:\s*\S+.*\(doğrusu|[Yy]azım hatası:.*doğrusu", md)),
              "Üretim notunda yazım hatası kaydı", "kelime + doğrusu")
        kayit(bool(re.search(r"Yorumlara [A-ZÇĞİÖŞÜ]{3,} yaz", metin)), "CTA anahtar kelime büyük harf")
    else:
        kayit(False, "aciklama.md var")

    # Senaryo
    sen = [f for f in glob.glob(os.path.join(kok, "*.json")) + glob.glob(os.path.join(kok, "senaryo", "*.json"))]
    for s in sen:
        try:
            j = json.load(open(s, encoding="utf-8"))
        except json.JSONDecodeError as e:
            kayit(False, f"{os.path.basename(s)} geçerli JSON", str(e))
            continue
        bos = [b["id"] for b in j.get("bolumler", []) if not b.get("tts") or not b.get("altyazi")]
        kayit(not bos, f"{os.path.basename(s)} tts + altyazi dolu", ",".join(bos))

    hata = 0
    for ok, ad, detay in sonuc:
        print(("✔" if ok else "✘"), ad, f"({detay})" if detay else "")
        hata += not ok
    print(f"\n{len(sonuc) - hata}/{len(sonuc)} geçti")
    sys.exit(1 if hata else 0)


if __name__ == "__main__":
    main()
