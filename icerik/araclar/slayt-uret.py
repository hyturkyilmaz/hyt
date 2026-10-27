"""Gönderi JSON'undan carousel slayt HTML'i üretir (HYT görsel stili).

Kullanım: python3 icerik/araclar/slayt-uret.py <gonderi.json> <cikti/slaytlar.html>

Stil tek kaynaktan gelir: .claude/skills/hyt-instagram-icerik/sablonlar/carousel-7.html içindeki <style>.
Slayt tipleri: kapak, ekran, akis, grafik, oncesonra, kural, matris, cta.
Metinde _kelime_ el çizimi alt çizgiyle vurgulanır; **kelime** kalın yazılır.
Hareketli tipler (kapak, ekran, akis, grafik, cta) MP4 olarak üretilir (data-duration).
"""
import html
import json
import os
import re
import sys

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SABLON = os.path.join(KOK, ".claude/skills/hyt-instagram-icerik/sablonlar/carousel-7.html")
SURE = {"kapak": 6, "ekran": 8, "akis": 6, "grafik": 6, "cta": 5}

EK_CSS = """
  .rows tr:nth-child(4) { animation-delay: 4.4s }
  .btn { white-space: nowrap; }
  /* grafik */
  .bars { display: flex; flex-direction: column; gap: 26px; margin-top: 10px; }
  .bar .lbl { display: flex; justify-content: space-between; font-size: 28px; font-weight: 700; margin-bottom: 10px; }
  .bar .lbl span:last-child { font-family: "Inter Display", sans-serif; font-weight: 800; }
  .bar .track { height: 46px; background: rgba(17,24,39,.06); border-radius: 10px; overflow: hidden; }
  .bar .fill { height: 100%; border-radius: 10px; transform-origin: left; animation: grow 1.2s ease-out both; }
  .bar .alt { font-size: 21px; color: var(--muted); margin-top: 8px; }
  .chart-note { font-size: 22px; color: var(--muted); margin-top: 26px; }
"""

IKON = {
    "kisi": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    "sohbet": '<path d="M4 5h16v11H9l-5 4z"/>',
    "veri": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    "kutu": '<path d="M3 8l9-5 9 5v8l-9 5-9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    "etiket": '<path d="M3 12l9-9h9v9l-9 9z"/><circle cx="16" cy="8" r="1.5"/>',
    "belge": '<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h7"/>',
    "onay": '<path d="M5 12l5 5 9-10"/>',
    "magaza": '<path d="M3 9l2-5h14l2 5M3 9v11h18V9M3 9h18"/><path d="M9 20v-6h6v6"/>',
    "grafik": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "arama": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    "hoparlor": '<path d="M3 10v4h4l6 4V6L7 10z"/><path d="M16 9a4 4 0 0 1 0 6"/>',
    "saat": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "sepet": '<path d="M3 4h2l2.5 11h11L21 8H6.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
    "kalkan": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "kod": '<path d="M8 8l-5 4 5 4M16 8l5 4-5 4"/>',
}


def esc(s):
    return html.escape(s, quote=False)


def zengin(s, cizim=True):
    """_kelime_ → el çizimi alt çizgi, **x** → kalın."""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    yol = '<svg viewBox="0 0 400 30" preserveAspectRatio="none"><path class="draw" d="M4 18 C 120 10, 260 8, 396 16"/></svg>'
    return re.sub(r"_(.+?)_", lambda m: f'<span class="u">{m.group(1)}{yol}</span>', s)


def ust(i, n):
    return (f'<div class="top"><div class="author"><img class="mark" src="../../marka/logo-isaret.svg" alt="">'
            f'Hasan Yasin Türkyılmaz</div><div class="counter">{i}/{n}</div></div>')


def alt(sol, sag="→"):
    return f'<div class="foot"><span>{esc(sol)}</span><span class="next">{sag}</span></div>'


def kicker(s, renk=None, num=None):
    if num:
        return f'<div class="kicker"><span class="num">{num}</span>{esc(s)}</div>'
    stil = f' style="background:var(--{renk})"' if renk else ""
    return f'<div class="kicker"><span class="dot"{stil}></span>{esc(s)}</div>'


def kapak(s, i, n):
    pts = s.get("zaman", [])
    k = len(pts)
    noktalar = ""
    for j, p in enumerate(pts):
        merkez = 110 + (680 * j / (k - 1) if k > 1 else 340)
        noktalar += (f'<div class="tl-pt" style="left:{merkez - 110:.0f}px; color:var(--{p.get("renk", "ai")}); '
                     f'animation-delay:{1.1 + 0.4 * j:.1f}s"><b></b><div class="t">{esc(p["t"])}</div>'
                     f'<div class="s">{esc(p["s"])}</div></div>')
    zaman = (f'<div class="timeline"><div class="tl-line"></div>{noktalar}</div>' if pts else "")
    return (f'{ust(i, n)}{kicker(s["kicker"])}<h1>{zengin(s["baslik"])}</h1>'
            f'<p class="lead">{zengin(s["alt"])}</p>{zaman}{alt(s["kaynak"], "Kaydır →")}')


NOTR = {"Yok", "Uygun", "Normal", "-"}  # vurgu sütununda kırmızı gösterilmeyen olumlu değerler


def tablo(t, cls="t", animasyon=False):
    bas = "".join(f"<th>{esc(h)}</th>" for h in t["basliklar"])
    vurgu = t.get("vurgu_sutun", -1)
    satir = ""
    for r in t["satirlar"]:
        satir += "<tr>" + "".join(
            f'<td{" class=low" if c == vurgu and str(v) not in NOTR else ""}>{esc(str(v))}</td>'
            for c, v in enumerate(r)) + "</tr>"
    govde = f'<tbody class="rows">{satir}</tbody>' if animasyon else satir
    return f'<table class="{cls}"><thead><tr>{bas}</tr></thead>{govde}</table>'


def ekran(s, i, n):
    return (f'{ust(i, n)}{kicker(s["kicker"])}<h2>{zengin(s["baslik"])}</h2>'
            f'<div class="window"><div class="chrome"><i></i><i></i><i></i><span>{esc(s["pencere"])}</span></div>'
            f'<div class="chat"><div class="bubble-user"><span class="typing" style="animation-timing-function:steps({len(s["istek"])})">'
            f'{esc(s["istek"])}</span></div><div class="bot">{zengin(s["yanit"])}</div>'
            f'{tablo(s["tablo"], animasyon=True)}'
            f'<div class="actions"><span class="btn ok">{esc(s.get("evet", "Onayla"))}</span>'
            f'<span class="btn no">{esc(s.get("hayir", "Reddet"))}</span><small>{esc(s["aksiyon"])}</small></div></div></div>'
            f'<p class="disclaim">Temsili ekran. Gerçek arayüz farklı olabilir.</p>{alt(s["kaynak"])}')


def akis(s, i, n):
    satirlar = s["satirlar"]  # [[düğüm,...], ...]
    ys = [90, 380, 640][: len(satirlar)]
    poz, dugumler = [], ""
    for r, sat in enumerate(satirlar):
        for c, d in enumerate(sat):
            x = 900 * (c + 1) / (len(sat) + 1) if len(sat) < 3 else [150, 450, 750][c]
            if len(sat) == 2:
                x = [300, 600][c]
            poz.append((x, ys[r]))
            insan = " human" if d.get("insan") else ""
            dugumler += (f'<div class="node{insan}" style="left:{x:.0f}px; top:{ys[r]}px">'
                         f'<div class="ic" style="background:var(--{d.get("renk", "ink")})"><svg viewBox="0 0 24 24">'
                         f'{IKON[d.get("ikon", "kutu")]}</svg></div><div class="n">{esc(d["ad"])}</div>'
                         f'<div class="d">{esc(d.get("alt", ""))}</div></div>')
    yollar = ""
    for a, b in s["baglar"]:
        (x1, y1), (x2, y2) = poz[a], poz[b]
        if y1 == y2:
            yollar += f'<path d="M{x1:.0f} {y1} L {x2:.0f} {y2}"/>'
        else:
            yollar += f'<path d="M{x1:.0f} {y1 + 125} C {x1:.0f} {y1 + 185}, {x2:.0f} {y2 - 110}, {x2:.0f} {y2 - 48}"/>'
    return (f'{ust(i, n)}{kicker(s["kicker"], s.get("renk", "ai"))}<h2>{zengin(s["baslik"])}</h2>'
            f'<div class="flow"><svg class="wires" viewBox="0 0 900 780">{yollar}</svg>{dugumler}</div>'
            f'{alt(s["kaynak"])}')


def grafik(s, i, n):
    enbuyuk = max(b["deger"] for b in s["barlar"])
    barlar = ""
    for j, b in enumerate(s["barlar"]):
        oran = max(2, 100 * b["deger"] / enbuyuk)
        barlar += (f'<div class="bar"><div class="lbl"><span>{esc(b["ad"])}</span><span>{esc(b["etiket"])}</span></div>'
                   f'<div class="track"><div class="fill" style="width:{oran:.1f}%; background:var(--{b.get("renk", "ai")}); '
                   f'animation-delay:{0.6 + 0.35 * j:.2f}s"></div></div>'
                   + (f'<div class="alt">{esc(b["alt"])}</div>' if b.get("alt") else "") + "</div>")
    notu = f'<p class="chart-note">{esc(s["not"])}</p>' if s.get("not") else ""
    return (f'{ust(i, n)}{kicker(s["kicker"], s.get("renk"))}<h2>{zengin(s["baslik"])}</h2>'
            f'<div class="bars">{barlar}</div>{notu}{alt(s["kaynak"])}')


def oncesonra(s, i, n):
    def pencere(p, iyi):
        cls = "window sheet good" if iyi else "window sheet"
        etiket = "tag-good" if iyi else "tag-bad"
        satir = ""
        for r in p["satirlar"]:
            satir += f'<tr{"" if iyi else " class=bad"}>' + "".join(f"<td>{esc(str(v))}</td>" for v in r) + "</tr>"
        bas = "".join(f"<th>{esc(h)}</th>" for h in p["basliklar"])
        return (f'<div class="{cls}"><div class="chrome"><i></i><i></i><i></i><span>{esc(p["dosya"])}</span>'
                f'<span class="pill {etiket}" style="margin-left:auto">{esc(p["etiket"])}</span></div>'
                f'<table><tr>{bas}</tr>{satir}</table></div>')
    return (f'{ust(i, n)}{kicker(s["kicker"], num=s.get("num"))}<h2>{zengin(s["baslik"])}</h2>'
            f'<div class="sheets">{pencere(s["once"], False)}{pencere(s["sonra"], True)}</div>{alt(s["kaynak"])}')


def kural(s, i, n):
    kod = "<br>".join(s["kod"])  # satırlar hazır HTML: <span class=k>, <span class=g>, <span class=c>
    lead = f'<p class="lead" style="margin-bottom:34px">{zengin(s["alt"])}</p>' if s.get("alt") else ""
    etiket = esc(s.get("prompt_etiket", "Claude'a yapıştır"))
    return (f'{ust(i, n)}{kicker(s["kicker"], num=s.get("num"))}<h2>{zengin(s["baslik"])}</h2>{lead}'
            f'<div class="rule">{kod}</div>'
            f'<div class="prompt"><div style="font-size:22px; font-weight:800; letter-spacing:2.5px; text-transform:uppercase; '
            f'color:var(--ai); margin-bottom:10px">{etiket}</div>'
            f'<p>"{esc(s["prompt"])}"</p></div>{alt(s["kaynak"])}')


def matris(s, i, n):
    satir = ""
    for r in s["satirlar"]:
        renk, ilk = r[0]
        satir += (f'<tr><td><span class="sw" style="background:var(--{renk})"></span>{esc(ilk)}</td>'
                  + "".join(f"<td>{esc(str(v))}</td>" for v in r[1:]) + "</tr>")
    bas = "".join(f"<th>{esc(h)}</th>" for h in s["basliklar"])
    lead = f'<p class="lead" style="margin-bottom:40px">{zengin(s["alt"])}</p>' if s.get("alt") else ""
    return (f'{ust(i, n)}{kicker(s["kicker"], num=s.get("num"))}<h2>{zengin(s["baslik"])}</h2>{lead}'
            f'<table class="m"><tr>{bas}</tr>{satir}</table>{alt(s["kaynak"])}')


def cta(s, i, n):
    return (f'{ust(i, n)}<div class="say">Yorumlara yaz:</div><div><span class="kw">{esc(s["anahtar"])}</span></div>'
            f'<p class="give">{zengin(s["vaat"])}</p><div class="chips"><span class="chip">Kaydet</span>'
            f'<span class="chip">Ekibinle paylaş</span><span class="chip on">Takip et</span></div>'
            f'<div class="foot" style="color:#94a3b8"><span>@hyturkyilmaz · hyturkyilmaz.com</span></div>')


TIPLER = {"kapak": kapak, "ekran": ekran, "akis": akis, "grafik": grafik,
          "oncesonra": oncesonra, "kural": kural, "matris": matris, "cta": cta}


def main():
    g = json.load(open(sys.argv[1], encoding="utf-8"))
    sablon = open(SABLON, encoding="utf-8").read()
    stil = re.search(r"<style>(.*?)</style>", sablon, re.S).group(1)
    stil = stil.replace("--accent: var(--ecom);", f"--accent: var(--{g['sutun']});")
    n = len(g["slaytlar"])
    govde = ""
    for i, s in enumerate(g["slaytlar"], start=1):
        tip = s["tip"]
        sure = f' data-duration="{SURE[tip]}"' if tip in SURE else ""
        cls = "slide dark" if tip == "cta" else "slide"
        ic = f' id="s{i}"' if tip != "cta" else ' id="s7"'
        govde += f'<section class="{cls}"{ic}{sure}>{TIPLER[tip](s, i, n)}</section>\n'
    out = sys.argv[2]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(
        f'<!doctype html>\n<html lang="tr">\n<head>\n<meta charset="utf-8">\n<title>{esc(g["id"])}</title>\n'
        f"<style>{stil}{EK_CSS}</style>\n</head>\n<body>\n{govde}</body>\n</html>\n")
    print(out, n, "slayt")


if __name__ == "__main__":
    main()
