# K-N02 / K-N05 hesap doğrulaması (maliyet_modeli.py sabitleriyle)
import sys; sys.path.insert(0, ".")
from decimal import Decimal as D, ROUND_CEILING
import maliyet_modeli as m
isl = sum((t for _, t in m.ISLETME["sahis"]), D("0"))
a_altyapi = m.senaryo_toplam(m.SENARYOLAR["A · Hetzner AB, tek sunucu (önerilen MVP)"]["mvp"])
guzel = m.tl(D("16198.90") / 12) + m.kalem_tl("USD", "0.30")  # Private Cloud 3 yıllık/12 + R2 yedek
print("işletme sabit", isl)
for ad, alt in [("A Hetzner", a_altyapi), ("B' Güzel PC3", guzel)]:
    top = alt + isl
    print(f"{ad}: altyapı {alt} toplam/ay {top} yıl {top*12}")
    for f in [D("249"), D("349"), D("399"), D("449"), D("499"), D("799")]:
        net = m.satici_basi_net(f)
        bb = (top / net).to_integral_value(rounding=ROUND_CEILING)
        print(f"   fiyat {f}: satıcı başı net {net}, başabaş {bb} satıcı")
print("fark/ay", guzel - a_altyapi, "fark/yıl", (guzel - a_altyapi) * 12)
print("Sellerboard 19 USD =", m.kalem_tl("USD", "19"), " yarısı", m.kalem_tl("USD", "9.5"))
print("Sentos Basic 9500/12 =", m.tl(D("9500")/12), " yarısı", m.tl(D("9500")/24))
