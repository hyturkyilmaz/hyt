"""Bir gönderinin tüm çıktılarını tek komutla üretir.

Kullanım: python3 icerik/araclar/gonderi-uret.py icerik/gonderiler/<id>/gonderi.json [--atla-medya]

Üretir (gönderi klasörüne):
  slaytlar.html            carousel kaynağı
  medya/slayt-XX.png|mp4   carousel medyası (1080×1350)
  medya/reels-altyazili.mp4  Reels (1080×1920, müzik + altyazı; ses gelince build-reels --ses ile yenilenir)
  medya/story.mp4          Story (1080×1920, kapak + çağrı)
  aciklama.md              açıklama metni + üretim notu
  senaryo.json             seslendirme senaryosu (Colab defterinin girdisi)
  dm.md                    herkese açık yanıtlar + DM metni
  lead/<id>.html|pdf       lead magnet
Mevcut dosyaların üzerine yazmadan önce .bak kopyası alır (aciklama.md, dm.md).
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys

ARAC = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(os.path.dirname(ARAC))
WHATSAPP = "https://chat.whatsapp.com/GKWDdd2jVy3GNCngWVHPhh"
RENK = {"seo": "#1a73e8", "ads": "#34a853", "ecom": "#f29900", "ai": "#7b1fa2"}


def run(*a):
    subprocess.run(a, check=True)


def yedekle(yol):
    if os.path.exists(yol):
        shutil.copy2(yol, yol + ".bak")


def muzik(tohum):
    yol = os.path.join(KOK, "icerik/marka/muzik", f"hyt-altlik-t{tohum:02d}.wav")
    if not os.path.exists(yol):
        run("python3", os.path.join(ARAC, "muzik-uret.py"), yol, "60", str(tohum))
    return yol


def zemin(png):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", png, "-vf", "crop=4:4:2:2,scale=1:1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return f"0x{out[0]:02x}{out[1]:02x}{out[2]:02x}"


def story(medya, cikti):
    """Kapak videosu + son (çağrı) videosu, 1080×1920 dikey."""
    vids = sorted(f for f in os.listdir(medya) if re.match(r"slayt-\d+\.mp4$", f))
    parcalar = [vids[0], vids[-1]]
    tmp = []
    for k, v in enumerate(parcalar):
        png = os.path.join(medya, v.replace(".mp4", ".png"))
        o = os.path.join(medya, f"_story{k}.mp4")
        run("ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(medya, v), "-vf",
            f"pad=1080:1920:0:285:color={zemin(png)},fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "20", "-an", o)
        tmp.append(o)
    liste = os.path.join(medya, "_story.txt")
    open(liste, "w").write("".join(f"file '{os.path.basename(t)}'\n" for t in tmp))
    run("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", liste, "-c", "copy", cikti)
    for t in tmp + [liste]:
        os.remove(t)


def aciklama_md(g, yol):
    yh = g["yazim_hatasi"]
    ilk = g["slaytlar"][0]
    md = f"""# {g['tarih']} {g['gun']} — {re.sub(r'[_*]', '', ilk['baslik'])}

| Alan | Değer |
|---|---|
| Sütun | {g['sutun']} |
| Carousel | {g['tarih']} 09:10 TRT |
| Story | {g['tarih']} 13:10 TRT |
| Reels | {g['tarih']} 20:50 TRT |
| Anahtar kelime | {g['anahtar']} |
| Lead magnet | `lead/{g['id']}.pdf` |

## Açıklama metni

```
{g['aciklama']}
```

## Üretim notu
- Yazım hatası: "{yh['kelime']}" (doğrusu: {yh['dogrusu']}), {yh['paragraf']}. paragraf. Görsellerde, seslendirmede ve altyazıda hata yok.
- Doğrulama: {'; '.join(g['dogrulama'])}.
- Reels müziği: `muzik-uret.py` tohum {g['muzik_tohum']} (özgün, telifsiz). Ses: Colab'da klon ses, `senaryo.json`.
"""
    yedekle(yol)
    open(yol, "w", encoding="utf-8").write(md)


def dm_md(g, yol):
    k = g["anahtar"]
    lead_ad = re.sub(r"[_*]", "", g["lead"]["baslik"])
    md = f"""# {k} → DM akışı ({g['id']})

Anahtar kelime varyantları: `{k}`, `{k.lower()}`, `{k.capitalize()}`""" + (
        f", `{k.replace('Ş','S').replace('İ','I').replace('Ç','C').replace('Ğ','G').replace('Ö','O').replace('Ü','U')}`"
        if re.search('[ŞİÇĞÖÜ]', k) else "") + f"""

## Herkese açık yanıtlar (sırayla)
1. Gönderdim, DM'e bak 📩
2. Listeyi DM'den ilettim, kolay gelsin.
3. DM kutuna düştü. WhatsApp grubunda da görüşelim.
4. Tamamdır, mesajlara bak 👍
5. Gönderdim. Sorun olursa DM'den yaz.

## DM metni

> Selam, ben Hasan Yasin 👋
>
> İstediğin "{lead_ad}" burada:
> 👉 [lead bağlantısı]?utm_source=instagram&utm_medium=dm&utm_campaign={k.lower()}_{g['tarih']}
>
> Bir de WhatsApp Topluluğumuz var. E-ticaret, AI, reklam ve SEO için ayrı gruplar açtık; ilgilendiğin gruba girip soru sorabilirsin:
> 👉 {WHATSAPP}
>
> Takıldığın yer olursa buradan yaz, bakarım.

Kurulum: `icerik/dm-akisi/ajan-dm-akisi.md` (Meta Business Suite veya ManyChat). DM'de kişisel veri istenmez.
"""
    yedekle(yol)
    open(yol, "w", encoding="utf-8").write(md)


def lead_html(g, yol):
    sablon = open(os.path.join(KOK, "icerik/dm-akisi/ajana-hazir-magaza.html"), encoding="utf-8").read()
    stil = re.search(r"<style>(.*?)</style>", sablon, re.S).group(1)
    L = g["lead"]

    def z(s):
        s = html.escape(s, quote=False)
        return re.sub(r"_(.+?)_", r"<span>\1</span>", s)
    govde, no = "", 0
    for b in L["bolumler"]:
        govde += f'<section><h2><i style="background:var(--{b["renk"]})"></i>{html.escape(b["ad"])}</h2>'
        for bas, acik in b["maddeler"]:
            no += 1
            govde += (f'<div class="item" style="--c:var(--{b["renk"]})"><span class="num">{no:02d}</span>'
                      f'<span class="box"></span><div><b>{html.escape(bas)}</b><p>{html.escape(acik)}</p></div></div>')
        govde += "</section>"
    sayfa = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>{html.escape(re.sub('[_*]', '', L['baslik']))}</title>
<style>{stil}</style></head><body><div class="page">
<header><img src="../../../marka/logo-isaret.svg" alt=""><div><div class="n">Hasan Yasin Türkyılmaz</div>
<div class="s">Dijital ve performans pazarlama danışmanı · hyturkyilmaz.com</div></div></header>
<div class="kicker">{html.escape(L['kicker'])}</div><h1>{z(L['baslik'])}</h1><p class="lead">{html.escape(L['giris'])}</p>
{govde}
<div class="cta"><div><b>Takıldığın yer olursa toplulukta soralım.</b><p>E-ticaret, AI, reklam ve SEO için ayrı gruplar var. İlgilendiğin gruba katıl.</p></div>
<a href="{WHATSAPP}">WhatsApp Topluluğu →</a></div>
<footer><span>© 2026 Hasan Yasin Türkyılmaz · hyturkyilmaz.com</span><span>Kişisel veriler: hyturkyilmaz.com/kvkk-aydinlatma-metni/</span></footer>
</div></body></html>"""
    open(yol, "w", encoding="utf-8").write(sayfa)


def main():
    yol = sys.argv[1]
    d = os.path.dirname(os.path.abspath(yol))
    g = json.load(open(yol, encoding="utf-8"))
    medya = os.path.join(d, "medya")
    html_yol = os.path.join(d, "slaytlar.html")

    run("python3", os.path.join(ARAC, "slayt-uret.py"), yol, html_yol)
    if "--atla-medya" not in sys.argv:
        run("node", os.path.join(ARAC, "render-media.mjs"), html_yol, medya, "30")

    aciklama_md(g, os.path.join(d, "aciklama.md"))
    dm_md(g, os.path.join(d, "dm.md"))

    senaryo = {"id": g["id"], "dil": "tr", "bolumler": [
        {"id": f"{i:02d}", "slayt": f"slayt-{i:02d}", **b} for i, b in enumerate(g["senaryo"], start=1)]}
    sen_yol = os.path.join(d, "senaryo.json")
    json.dump(senaryo, open(sen_yol, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    run("python3", os.path.join(ARAC, "build-reels.py"), "--medya", medya, "--senaryo", sen_yol,
        "--muzik", muzik(g["muzik_tohum"]), "--cikti", os.path.join(medya, "reels-altyazili.mp4"),
        "--vurgu", RENK[g["sutun"]])
    story(medya, os.path.join(medya, "story.mp4"))

    os.makedirs(os.path.join(d, "lead"), exist_ok=True)
    lh = os.path.join(d, "lead", g["id"] + ".html")
    lead_html(g, lh)
    run("node", os.path.join(ARAC, "render-pdf.mjs"), lh, lh.replace(".html", ".pdf"), lh.replace(".html", ".png"))
    print("tamam", g["id"])


if __name__ == "__main__":
    main()
