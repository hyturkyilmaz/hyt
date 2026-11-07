# -*- coding: utf-8 -*-
"""NetKâr işletim maliyeti ve başabaş modeli.

Girdi: fiyatlar_2026-11-05.csv içindeki birim fiyatlar (ajan araştırması, 5 Kasım 2026).
Çıktı: NetKar_Maliyet_Modeli.xlsx ve konsola özet.
Tüm tutarlar KDV hariçtir. Yurt dışı hizmetlerde sorumlu sıfatıyla KDV (2 No.lu beyanname)
nakit olarak ödenir ve indirilir; maliyete eklenmedi.
"""
from decimal import Decimal as D, ROUND_HALF_UP
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# --- Kurlar (TCMB gösterge, döviz satış, 5 Kasım 2026) ---
USD = D("50.0260")
EUR = D("56.2588")


def tl(x):
    """Kuruşa yuvarla."""
    return D(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)


# --- Senaryolar: aylık sabit altyapı kalemleri (para birimi, tutar) ---
# Kademe: mvp (0-100 satıcı), buyume (100-500), olcek (500-2000)
SENARYOLAR = {
    "A · Hetzner AB, tek sunucu (önerilen MVP)": {
        "mvp": [("Hetzner CX33 4vCPU/8GB (web+api+worker+db)", "EUR", "8.49"),
                ("Hetzner IPv4", "EUR", "0.50"),
                ("Cloudflare R2 yedek (~20 GB)", "USD", "0.30"),
                ("Resend Free (3.000 e-posta)", "USD", "0"),
                ("Sentry Developer (ücretsiz)", "USD", "0"),
                ("Cloudflare Free (DNS/WAF/TLS)", "USD", "0")],
        "buyume": [("Hetzner CX33 web+api+worker", "EUR", "8.49"),
                   ("Hetzner CPX32 ayrı DB sunucusu", "EUR", "35.49"),
                   ("Hetzner IPv4 x2", "EUR", "1.00"),
                   ("Cloudflare R2 yedek (~150 GB)", "USD", "2.25"),
                   ("Resend Pro", "USD", "20"),
                   ("Sentry Team (yıllık)", "USD", "26")],
        "olcek": [("Hetzner CPX32 x2 (web/api + worker)", "EUR", "70.98"),
                  ("Hetzner CCX13 DB (adanmış vCPU) x2 (birincil + replika)", "EUR", "85.98"),
                  ("Hetzner IPv4 x4", "EUR", "2.00"),
                  ("Cloudflare R2 yedek (~1 TB)", "USD", "15"),
                  ("Resend Pro", "USD", "20"),
                  ("Sentry Team (yıllık)", "USD", "26")],
    },
    "B · Türkiye VPS (KVKK yurt içi)": {
        "mvp": [("Natro XCloud Pro 4vCPU/8GB (güven düşük)", "USD", "41.11"),
                ("Cloudflare R2 yedek (~20 GB)", "USD", "0.30"),
                ("Resend Free", "USD", "0"), ("Sentry Developer", "USD", "0")],
        "buyume": [("Natro XCloud Pro x2 (uygulama + DB)", "USD", "82.22"),
                   ("Cloudflare R2 yedek (~150 GB)", "USD", "2.25"),
                   ("Resend Pro", "USD", "20"), ("Sentry Team", "USD", "26")],
        "olcek": [("Natro XCloud Pro x4", "USD", "164.44"),
                  ("Cloudflare R2 yedek (~1 TB)", "USD", "15"),
                  ("Resend Pro", "USD", "20"), ("Sentry Team", "USD", "26")],
    },
    "C · Yönetilen bulut (Vercel + Supabase + Hetzner worker)": {
        "mvp": [("Vercel Pro (1 koltuk)", "USD", "20"), ("Supabase Pro", "USD", "25"),
                ("Hetzner CX23 worker", "EUR", "5.49"), ("Resend Free", "USD", "0"),
                ("Sentry Developer", "USD", "0")],
        "buyume": [("Vercel Pro", "USD", "20"), ("Supabase Pro + compute ek (varsayım 50 USD)", "USD", "75"),
                   ("Hetzner CX33 worker", "EUR", "8.49"), ("Resend Pro", "USD", "20"),
                   ("Sentry Team", "USD", "26")],
        "olcek": [("Vercel Pro + kullanım (varsayım)", "USD", "60"),
                  ("Supabase Pro + büyük compute (varsayım)", "USD", "250"),
                  ("Hetzner CPX32 worker x2", "EUR", "70.98"), ("Resend Pro", "USD", "20"),
                  ("Sentry Team", "USD", "26")],
    },
}

# --- İşletme sabit giderleri (aylık, TL, KDV hariç) ---
ISLETME = {
    "sahis": [("Mali müşavir (şahıs)", D("3593")), ("Paraşüt ön muhasebe + e-Arşiv (9.024/yıl)", D("752")),
              ("Alan adları (.com 15 USD + .com.tr ~550 TL)/12", tl((D("15") * USD + D("550")) / 12))],
    "limited": [("Mali müşavir (limited, alt sınır)", D("7985")), ("Paraşüt ön muhasebe + e-Arşiv", D("752")),
                ("Alan adları /12", tl((D("15") * USD + D("550")) / 12))],
}
# Mobil mağaza (faz 2): Apple 99 USD/yıl, Google 25 USD tek sefer
MAGAZA_AYLIK = tl(D("99") * USD / 12)

# --- Değişken maliyetler (satıcı başına aylık) ---
E_ARSIV_KONTOR = D("4.00")           # 100 kontör 400 TL
IYZICO_ORAN = D("0.0279")
IYZICO_SABIT = D("0.25")
# AI soru taslağı (faz 2): 300 soru/ay, soru başına 1.500 girdi + 300 çıktı token, Haiku 5.5
AI_USD = D("300") * (D("1500") * D("0.10") + D("300") * D("0.50")) / D("1000000")
AI_TL = tl(AI_USD * USD)
# Sunucu kaynak payı kademe içinde sabitte; ek değişken yok sayıldı.

FIYATLAR = [D("499"), D("799"), D("1199")]  # KDV hariç aylık


def kalem_tl(birim, tutar):
    t = D(tutar)
    return tl(t * (EUR if birim == "EUR" else USD if birim == "USD" else 1))


def senaryo_toplam(kalemler):
    return sum((kalem_tl(b, t) for _, b, t in kalemler), D("0"))


def satici_basi_net(fiyat):
    """Abonelik fiyatından ödeme komisyonu, e-Arşiv kontörü ve AI maliyeti düşülmüş katkı."""
    komisyon = tl(fiyat * IYZICO_ORAN + IYZICO_SABIT)
    return tl(fiyat - komisyon - E_ARSIV_KONTOR - AI_TL)


def main():
    wb = Workbook()
    bas = Font(bold=True, color="FFFFFF")
    dolgu = PatternFill("solid", fgColor="1F4E79")

    def baslik(ws, satir):
        ws.append(satir)
        for c in ws[ws.max_row]:
            c.font, c.fill = bas, dolgu

    # Sayfa 1: Özet
    ws = wb.active
    ws.title = "1 Ozet"
    ws.append(["NetKâr İşletim Maliyeti Modeli", "5 Kasım 2026", "Tutarlar KDV hariç, TL"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Kur: 1 USD = {USD} TL, 1 EUR = {EUR} TL (TCMB gösterge, döviz satış)"])
    ws.append([])
    baslik(ws, ["Senaryo", "Kademe", "Altyapı aylık", "İşletme aylık (şahıs)", "Toplam aylık",
                "Toplam yıllık", "Başabaş 499", "Başabaş 799", "Başabaş 1199"])
    ozet = []
    for ad, kademeler in SENARYOLAR.items():
        for kademe, kalemler in kademeler.items():
            alt = senaryo_toplam(kalemler)
            isl = sum((t for _, t in ISLETME["sahis"]), D("0"))
            top = alt + isl
            bb = [int((top / satici_basi_net(f)).to_integral_value(rounding="ROUND_CEILING")) for f in FIYATLAR]
            satir = [ad, kademe, float(alt), float(isl), float(top), float(top * 12)] + bb
            ws.append(satir)
            ozet.append(satir)

    # Sayfa 2: Kalemler
    ws2 = wb.create_sheet("2 Altyapi Kalemleri")
    baslik(ws2, ["Senaryo", "Kademe", "Kalem", "Para birimi", "Birim tutar", "Aylık TL", "Yıllık TL"])
    for ad, kademeler in SENARYOLAR.items():
        for kademe, kalemler in kademeler.items():
            for k, b, t in kalemler:
                a = kalem_tl(b, t)
                ws2.append([ad, kademe, k, b, float(D(t)), float(a), float(a * 12)])

    # Sayfa 3: İşletme ve değişken
    ws3 = wb.create_sheet("3 Isletme ve Degisken")
    baslik(ws3, ["Tür", "Kalem", "Aylık TL", "Yıllık TL", "Not"])
    for tur, kalemler in ISLETME.items():
        for k, t in kalemler:
            ws3.append([f"İşletme ({tur})", k, float(t), float(t * 12), ""])
    ws3.append(["Faz 2", "Apple Developer 99 USD/yıl", float(MAGAZA_AYLIK), float(MAGAZA_AYLIK * 12), "Expo mobil uygulama ile"])
    ws3.append(["Faz 2", "Google Play 25 USD tek sefer", "", float(tl(D('25') * USD)), "tek seferlik"])
    ws3.append(["Değişken/satıcı", "iyzico %2,79 + 0,25 TL", "", "", "oran işletmeye özel, pazarlık edilir"])
    ws3.append(["Değişken/satıcı", "e-Arşiv kontör", float(E_ARSIV_KONTOR), "", "fatura başına"])
    ws3.append(["Değişken/satıcı", "AI soru taslağı (Haiku 5.5, 300 soru/ay)", float(AI_TL), "", f"{AI_USD} USD"])
    ws3.append([])
    baslik(ws3, ["Fiyat (KDV hariç)", "Satıcı başı net katkı", "", "", ""])
    for f in FIYATLAR:
        ws3.append([float(f), float(satici_basi_net(f)), "", "", "komisyon + kontör + AI düşülmüş"])
    ws3.append([])
    ws3.append(["Tek seferlik", "Limited şirket kuruluşu (sermaye hariç)", "", "30.000-42.500", "asgari sermaye 50.000 TL ayrı"])

    # Sayfa 4: Gelir senaryoları (önerilen senaryo A)
    ws4 = wb.create_sheet("4 Gelir Senaryolari")
    baslik(ws4, ["Ödeyen satıcı", "Kademe", "Ort. fiyat", "Aylık gelir", "Aylık toplam gider",
                 "Aylık katkı (kâr)", "Yıllık kâr", "Marj %"])
    A = SENARYOLAR["A · Hetzner AB, tek sunucu (önerilen MVP)"]
    isl = sum((t for _, t in ISLETME["sahis"]), D("0"))
    for n in [25, 50, 100, 200, 300, 500, 1000, 2000]:
        kademe = "mvp" if n <= 100 else "buyume" if n <= 500 else "olcek"
        ort = D("799")
        gelir = ort * n
        degisken = (ort - satici_basi_net(ort)) * n
        gider = senaryo_toplam(A[kademe]) + isl + degisken
        kar = gelir - gider
        ws4.append([n, kademe, float(ort), float(gelir), float(tl(gider)), float(tl(kar)),
                    float(tl(kar * 12)), float(tl(kar / gelir * 100))])

    # Sayfa 5: Varsayımlar ve kaynak
    ws5 = wb.create_sheet("5 Varsayimlar")
    for satir in [
        "Fiyatlar: calisma_dosyalari/fiyatlar_2026-11-05.csv (WebSearch özetleri; resmi sayfa teyidi bekliyor, güven çoğunlukla orta).",
        "LLM fiyatı resmi Anthropic sayfasından (yüksek güven).",
        "Kurucu emeği, Claude abonelik/oturum maliyeti ve pazarlama zamanı dahil değil.",
        "Supabase/Vercel ölçek kalemlerinde kullanım fazlası varsayımdır.",
        "Türkiye VPS fiyatı agregatör kaynaklı (düşük güven); teklif alınmalı.",
        "Gelir senaryosu ortalama 799 TL KDV hariç fiyat ve churn sıfır varsayar (iyimser); churn etkisi pazarlama modelinde.",
        "Yurt dışı hizmetlerde sorumlu sıfatıyla KDV ödenir ve indirilir; maliyete eklenmedi.",
    ]:
        ws5.append([satir])

    for w in wb.worksheets:
        for i in range(1, w.max_column + 1):
            w.column_dimensions[get_column_letter(i)].width = 22 if i > 1 else 48
        for row in w.iter_rows():
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save("NetKar_Maliyet_Modeli.xlsx")

    for s in ozet:
        print(f"{s[0][:24]:24} {s[1]:7} altyapı {s[2]:>9,.0f} işletme {s[3]:>7,.0f} toplam/ay {s[4]:>9,.0f} yıl {s[5]:>10,.0f} başabaş {s[6:]}")
    for f in FIYATLAR:
        print("net katkı", f, satici_basi_net(f))
    print("AI satıcı/ay TL", AI_TL)


if __name__ == "__main__":
    main()
