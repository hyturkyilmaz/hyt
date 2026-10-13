"""Slayt medyası + ses + müzik + altyazıdan 1080x1920 Reels üretir.

Kullanım:
  python3 icerik/araclar/build-reels.py \
      --medya icerik/ornek-01/v2/medya \
      --senaryo icerik/ses/senaryo/ornek01_reels.json \
      --muzik icerik/marka/muzik/hyt-altlik-01.wav \
      --cikti icerik/ornek-01/v2/medya/reels-sesli.mp4 \
      [--ses tam.wav --zamanlama zamanlama.json] [--muzik-seviye 0.09]

Ses verilirse: slayt süreleri seslendirme bölümlerine göre ayarlanır, müzik
konuşmanın altında --muzik-seviye oranında (varsayılan %9) kalır.
Ses yoksa: süreler kelime sayısından tahmin edilir, müzik tam seviyede çalar
(sessiz önizleme / altyazılı sürüm).
Gerekli: ffmpeg, node + playwright (altyazı PNG'leri için).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile

W, H = 1080, 1920
SLAYT_Y = 160          # slaytın üst kenarı (Instagram üst arayüzü altında kalan başlık şeridi)
ALTYAZI_ALT = 1490     # altyazı kutusunun alt kenarı (Reels güvenli alanı içinde)
FPS = 30
BURADA = os.path.dirname(os.path.abspath(__file__))


def run(*args):
    subprocess.run(args, check=True)


def probe_sure(yol):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", yol], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def zemin_rengi(png):
    """Slaytın sol üst köşe rengini okuyup Reels boşluklarını aynı renkle doldurur."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", png, "-vf", "crop=4:4:2:2,scale=1:1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    r, g, b = out.stdout[:3]
    return f"0x{r:02x}{g:02x}{b:02x}"


def parcala(metin, en_fazla=9):
    """Altyazıyı cümle ve virgül sınırlarından, ekranda en fazla ~9 kelime kalacak şekilde böler."""
    cumleler = [c.strip() for c in re.split(r"(?<=[.!?])\s+", metin) if c.strip()]
    parcalar = []
    for c in cumleler:
        kelimeler = c.split()
        while len(kelimeler) > en_fazla:
            # virgülde kesmeyi tercih et
            kes = next((i + 1 for i in range(en_fazla - 1, 2, -1) if kelimeler[i].endswith(",")), en_fazla)
            parcalar.append(" ".join(kelimeler[:kes]))
            kelimeler = kelimeler[kes:]
        parcalar.append(" ".join(kelimeler))
    return parcalar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--medya", required=True)
    ap.add_argument("--senaryo", required=True)
    ap.add_argument("--muzik", required=True)
    ap.add_argument("--cikti", required=True)
    ap.add_argument("--ses")
    ap.add_argument("--zamanlama")
    ap.add_argument("--muzik-seviye", type=float, default=0.09)
    ap.add_argument("--vurgu", default="#f29900")
    a = ap.parse_args()

    senaryo = json.load(open(a.senaryo, encoding="utf-8"))
    bolumler = senaryo["bolumler"]
    if a.zamanlama:
        z = {b["id"]: b for b in json.load(open(a.zamanlama, encoding="utf-8"))["bolumler"]}
        for i, b in enumerate(bolumler):
            nxt = bolumler[i + 1]["id"] if i + 1 < len(bolumler) else None
            b["sure"] = (z[nxt]["bas"] - z[b["id"]]["bas"]) if nxt else z[b["id"]]["sure"] + 1.2
            b["konusma"] = z[b["id"]]["sure"]
    else:
        for b in bolumler:
            b["konusma"] = len(b["altyazi"].split()) / 2.3
            b["sure"] = b["konusma"] + 0.6

    tmp = tempfile.mkdtemp(prefix="reels_")
    try:
        # 1) altyazı PNG'leri
        isler, zaman = [], []
        for bi, b in enumerate(bolumler):
            parcalar = parcala(b["altyazi"])
            toplam = sum(len(p.split()) for p in parcalar)
            t = 0.0
            for pi, p in enumerate(parcalar):
                d = b["konusma"] * len(p.split()) / toplam
                out = os.path.join(tmp, f"cap_{bi:02d}_{pi:02d}.png")
                isler.append({"text": p, "out": out, "accent": a.vurgu})
                zaman.append((bi, out, t, t + d if pi < len(parcalar) - 1 else b["sure"]))
                t += d
        is_json = os.path.join(tmp, "isler.json")
        json.dump(isler, open(is_json, "w", encoding="utf-8"), ensure_ascii=False)
        run("node", os.path.join(BURADA, "render-altyazi.mjs"), is_json)

        # 2) slayt klipleri
        klipler = []
        for bi, b in enumerate(bolumler):
            mp4 = os.path.join(a.medya, b["slayt"] + ".mp4")
            png = os.path.join(a.medya, b["slayt"] + ".png")
            renk = zemin_rengi(png)
            caps = [z for z in zaman if z[0] == bi]
            girdiler = []
            if os.path.exists(mp4):
                girdiler += ["-i", mp4]
                kaynak = f"[0:v]tpad=stop_mode=clone:stop_duration={b['sure'] + 1},trim=0:{b['sure']:.3f},setpts=PTS-STARTPTS"
            else:
                girdiler += ["-loop", "1", "-framerate", str(FPS), "-t", f"{b['sure']:.3f}", "-i", png]
                kaynak = "[0:v]null"
            for c in caps:
                girdiler += ["-i", c[1]]
            fc = f"{kaynak},fps={FPS},pad={W}:{H}:0:{SLAYT_Y}:color={renk}[v0]"
            son = "v0"
            for k, c in enumerate(caps, start=1):
                fc += f";[{son}][{k}:v]overlay=0:{ALTYAZI_ALT - 400}:enable='between(t,{c[2]:.3f},{c[3]:.3f})'[v{k}]"
                son = f"v{k}"
            out = os.path.join(tmp, f"klip_{bi:02d}.mp4")
            run("ffmpeg", "-y", "-loglevel", "error", *girdiler, "-filter_complex", fc, "-map", f"[{son}]",
                "-t", f"{b['sure']:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19", "-an", out)
            klipler.append(out)

        liste = os.path.join(tmp, "liste.txt")
        open(liste, "w").write("".join(f"file '{k}'\n" for k in klipler))
        video = os.path.join(tmp, "video.mp4")
        run("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", liste, "-c", "copy", video)
        sure = probe_sure(video)

        # 3) ses: konuşma -16 LUFS, müzik aynı ölçüye getirilip oranla kısılır
        muzik = (f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{sure:.3f},loudnorm=I=-16:TP=-2,"
                 f"afade=t=in:d=1,afade=t=out:st={max(0, sure - 2):.3f}:d=2")
        if a.ses:
            fc = (f"[2:a]loudnorm=I=-16:TP=-1.5,apad,atrim=0:{sure:.3f}[vo];"
                  f"{muzik},volume={a.muzik_seviye}[mz];"
                  f"[vo][mz]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1[a]")
            girdi = ["-i", video, "-i", a.muzik, "-i", a.ses]
        else:
            fc = f"{muzik},loudnorm=I=-14:TP=-1[a]"
            girdi = ["-i", video, "-i", a.muzik]
        run("ffmpeg", "-y", "-loglevel", "error", *girdi, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
            "-shortest", a.cikti)
        print(a.cikti, f"{sure:.1f} sn", "sesli" if a.ses else "sessiz önizleme (müzik + altyazı)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
