# -*- coding: utf-8 -*-
"""NetKâr kâr motoru: kâr ayarları ve eksik kalem kuralları (K33-K41, K39 Revizyon 1) için referans hesap ve
doğrulama betiği.

docs/12_kar_motoru.md §12 (K33-K41; K39 Revizyon 1, denetim AO-03) ve docs/adr/0006-kar-ayarlari.md,
docs/adr/0007-ayar-tarihcesi-ve-donem-rakami.md kararlarının Decimal ile elle hesaplanmış karşılığıdır. K42-K44
(ayar tarihçesi, geçmişi etkileyen değişiklik, rapor ayar damgası) veritabanı ve API kuralıdır; motor girdisini
değiştirmez, bu betikte senaryosu yoktur. Üretim motoru DEĞİLDİR. `altin_test_hesap.py` (K01-K32) betiğinin yardımcılarını ve
G01-G41 senaryo tanımlarını içe aktarır, hesap işlevini yeni kurallarla yeniden yazar (`hesapla2`).

Çalıştırma (repo kökünden ya da netkar/services/api içinden, ikisi de aynı sonucu verir):
    python3 netkar/calisma_dosyalari/altin_test_hesap_ayarlar.py          # yalnız doğrula, dosya yazmaz
    python3 netkar/calisma_dosyalari/altin_test_hesap_ayarlar.py --yaz    # doğrula ve G01-G49'u yaz
    cd netkar/services/api && uv run python ../../calisma_dosyalari/altin_test_hesap_ayarlar.py --yaz

Doğrulama adımları:
  1. Eski betik ile diskteki G01-G41 aynı mı (girdi ve beklenen birebir).
  2. Gerileme: G01-G41 eski kurallarla (hesapla) ve yeni kurallarla (hesapla2) hesaplanır; eski çıktıdaki HER
     alan yeni çıktıda aynı olmalı. İzinli farklar açıkça listelenir (IZINLI_FARKLAR); başka fark hatadır.
  3. Yeni senaryolar (G42-G49): kilit tutarlar ELLE hesaplanmış sabitlerle (ELLE) karşılaştırılır.
  4. Değişmezler: her senaryoda satır, ürün ve dönem özdeşlikleri (K37, K39 Revizyon 1 I1-I6, K40).
  5. Denetim S4 Y-02 ölçümünün tekrarı: G01-G41 üretim varsayılanı ayarla (ayar yok) hesaplanır; hiçbir satırda
     eksik kalem varken net kâr hesaplanmamalı, altın sonuçta olmayan BEKLENMEYEN_KESINTI çıkmamalı ve kısmi
     dönemde dönem net kârı sayı olmamalı (denetim AO-03).

Kurallar: tüm tutarlar Decimal, float yok; kuruşa ROUND_HALF_UP, kalem (satır) sonunda bir kez (K01);
dağıtım en büyük kalan (K24). Tüm tutarlar ve kargo firma adları kurgusaldır.
"""
from __future__ import annotations

import copy
import json
import math
import sys
from decimal import ROUND_HALF_UP
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import altin_test_hesap as eski  # noqa: E402  (yardımcılar ve G01-G41 senaryo tanımları)

from altin_test_hesap import (  # noqa: E402
    BK_A, BK_B, BK_C, BK_D, CIKTI, DUZELTME_TIPLERI, IADE_TIPLERI, KOMISYON_ISARETI, SATIS_TIPLERI, YUZ,
    birlestir, claim, d, dagit, dahil_ayir, diger, fin, haric_kdv, kargo_faturasi, maliyet, rnd, s, satir,
    satis_satiri, siparis, tarih, yuzde,
)

# --------------------------------------------------------------------------- ayarlar
# Eski (G01-G41) kurgusal ayarlar + yeni anahtar. Yeni anahtarın varsayılanı "tanımsız".
VARSAYILAN_AYARLAR_2 = birlestir(eski.VARSAYILAN_AYARLAR, {"varsayilan_desi": None})

# Üretim varsayılanı (K33): hiçbir kullanıcı ayarı yok. Sistem parametreleri (KDV oranları, stopaj, eşikler,
# komisyon KDV varsayımı) motor sabitidir ve eski varsayılanlarla aynıdır.
URETIM_AYARLARI = {
    "komisyon_tutari_kdv_dahil": True,
    "komisyon_kdv_orani": "20",
    "kargo_kdv_orani": "20",
    "hizmet_bedeli_kdv_orani": "20",
    "reklam_kdv_orani": "20",
    "stopaj_orani": "1",
    "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric": None,
    "kargo_tarifesi": {},
    "satici_kargo_tarifesi": {},
    "varsayilan_desi": None,
    "kargo_faturasi_kdv_tespit_toleransi": "0.05",
    "uyari_esikleri": copy.deepcopy(eski.VARSAYILAN_AYARLAR["uyari_esikleri"]),
    "degisken_giderler": [],
}

EKSIK_SIRA = ("urun_maliyeti", "kargo_gonderi", "platform_hizmet_bedeli")  # K37 kanonik sıra
KESIN_KAYNAKLAR = {"kesin", "kesin_dagitim", "kullanici", "eslesen", "yok"}  # K40


def tam_ayarlar(girdi: dict) -> dict:
    """Senaryonun tam ayar seti: `ayarlar_tam` verilmişse birleştirme yapılmaz (boş tarife = tarife yok)."""
    if "ayarlar_tam" in girdi:
        return copy.deepcopy(girdi["ayarlar_tam"])
    return birlestir(VARSAYILAN_AYARLAR_2, girdi.get("ayarlar", {}))


# --------------------------------------------------------------------------- K34, K35, K36: ayar çözümleme
def _surumler(liste) -> list[tuple[str | None, list]]:
    """K34: tarife iki biçimde yazılabilir: [[desi, fiyat], ...] (başlangıçsız tek sürüm) ya da
    [{"gecerlilik_baslangic": "YYYY-MM-DD", "kademeler": [[desi, fiyat], ...]}, ...]."""
    if liste and isinstance(liste[0], dict):
        return [(x.get("gecerlilik_baslangic"), x["kademeler"]) for x in liste]
    return [(None, liste)]


def _gecerli(surumler, gun):
    """Sipariş gününde geçerli en son sürüm (başlangıç <= gün; başlangıçsız sürüm en eskidir). Yoksa None."""
    adaylar = [(b or "", v) for b, v in surumler if b is None or b <= gun]
    if not adaylar:
        return None
    adaylar.sort(key=lambda x: x[0])
    return adaylar[-1][1]


def tarife_fiyat(tarife: dict, firma: str, desi, gun: str) -> D | None:
    """K34: firmanın o gün geçerli sürümü varsa YALNIZ o kullanılır (desi kapsam dışıysa None, yedeğe düşmez);
    firmanın o gün geçerli sürümü yoksa '*' (diğer firmalar) yedeği; o da yoksa None."""
    for anahtar in (firma, "*"):
        if anahtar not in tarife:
            continue
        kademeler = _gecerli(_surumler(tarife[anahtar]), gun)
        if kademeler is None:
            continue
        if desi is None:
            return None
        for ust, tutar in kademeler:
            if d(desi) <= d(ust):
                return d(tutar)
        return None
    return None


def hizmet_tahmini(ay: dict, gun: str) -> D | None:
    """K35: null = tanımsız; "10.00" = başlangıçsız tek sürüm; liste = geçerlilik tarihli sürümler."""
    v = ay["platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric"]
    if v is None:
        return None
    if isinstance(v, list):
        secilen = _gecerli([(x.get("gecerlilik_baslangic"), x["tutar_kdv_haric"]) for x in v], gun)
        return None if secilen is None else d(secilen)
    return d(v)


def gider_gecerli(gid: dict, gun: str) -> bool:
    """K36: değişken gider tanımı sipariş gününde geçerli mi (uçlar dahil; boş uç sınırsız)."""
    bas, bit = gid.get("gecerlilik_baslangic"), gid.get("gecerlilik_bitis")
    return (bas is None or bas <= gun) and (bit is None or gun <= bit)


def tamsayi_yuvarla(x: D) -> int:
    return int(x.quantize(D("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- hesap (K01-K41)
def hesapla2(g: dict) -> dict:  # noqa: C901 (referans betik: tek akış, kural sırası docs/12 §11.2)
    ay = g["ayarlar"]
    ue = {k: d(v) for k, v in ay["uyari_esikleri"].items()}
    kom_kdv_o = d(ay["komisyon_kdv_orani"])
    kargo_kdv_o = d(ay["kargo_kdv_orani"])
    hiz_kdv_o = d(ay["hizmet_bedeli_kdv_orani"])
    rek_kdv_o = d(ay["reklam_kdv_orani"])
    stopaj_o = d(ay["stopaj_orani"])
    settlements = g.get("settlements", [])
    others = g.get("otherfinancials", [])
    kargo_faturalari = g.get("kargo_faturalari", [])
    claims = g.get("iadeler", [])
    maliyetler = g.get("urun_maliyetleri", [])

    satirlar = [{"o": o, "ln": ln} for o in g["siparisler"] for ln in o["lines"]]

    # ---- A. satış, iade, komisyon, maliyet (K03-K07, K10, K16, K27, K28) + K41 claim'siz iade
    for S in satirlar:
        o, ln = S["o"], S["ln"]
        r = d(ln["vatRate"])
        q = int(ln["quantity"])
        items = ln["discountDetails"]
        assert len(items) == q
        brut = d(ln["lineGrossAmount"]) * q
        sind = sum((d(i["lineItemSellerDiscount"]) for i in items), D(0))
        tind = sum((d(i["lineItemTyDiscount"]) for i in items), D(0))
        S.update(r=r, q=q, brut=brut, sind=sind, tind=tind, uyarilar=[], kaynak={})
        S["gun"] = tarih(o["orderDate"])
        S["iptal"] = o.get("status") in ("Cancelled", "UnSupplied")
        S["item_ids"] = {str(i["lineItemId"]) for i in items}
        rows = [x for x in settlements
                if x["orderNumber"] == o["orderNumber"] and x["barcode"] == ln["barcode"]
                and (x.get("shipmentPackageId") in (None, o["shipmentPackageId"]))]
        S["rows"] = rows
        tipler = {x["netkar_istek_tipi"] for x in rows}
        S["has_sale"] = bool(tipler & {"Sale", "PayByLink"})
        S["duzeltme_var"] = bool(tipler & (IADE_TIPLERI | DUZELTME_TIPLERI))

        satis_tahmini_dahil = brut - sind
        kom_tahmini_exact = satis_tahmini_dahil * d(ln["commission"]) / YUZ
        S["iade_return_dahil"] = D(0)

        if S["iptal"]:
            satis_dahil = iade_dahil = kom_exact = kom_satis_exact = D(0)
        elif S["has_sale"]:
            satis_dahil = sum((d(x["credit"]) - d(x["debt"]) for x in rows
                               if x["netkar_istek_tipi"] in SATIS_TIPLERI), D(0))
            iade_dahil = sum((d(x["debt"]) - d(x["credit"]) for x in rows
                              if x["netkar_istek_tipi"] in IADE_TIPLERI), D(0))
            S["iade_return_dahil"] = sum((d(x["debt"]) - d(x["credit"]) for x in rows
                                          if x["netkar_istek_tipi"] == "Return"), D(0))
            kom_exact = sum((KOMISYON_ISARETI[x["netkar_istek_tipi"]] * abs(d(x["commissionAmount"] or 0))
                             for x in rows), D(0))
            kom_satis_exact = sum((KOMISYON_ISARETI[x["netkar_istek_tipi"]] * abs(d(x["commissionAmount"] or 0))
                                   for x in rows if x["netkar_istek_tipi"] not in IADE_TIPLERI), D(0))
            kom_duz = sum((KOMISYON_ISARETI[x["netkar_istek_tipi"]] * abs(d(x["commissionAmount"] or 0))
                           for x in rows if x["netkar_istek_tipi"].startswith("Commission")), D(0))
            hak_duz = sum((d(x["credit"]) - d(x["debt"]) for x in rows
                           if x["netkar_istek_tipi"].startswith("SellerRevenue")), D(0))
            artik = hak_duz + kom_duz
            if artik != 0:
                satis_dahil += artik
                S["uyarilar"].append("ESLESMEMIS_HAKEDIS_DUZELTMESI")
            for x in rows:
                if x["netkar_istek_tipi"] not in (SATIS_TIPLERI | IADE_TIPLERI):
                    continue
                isr = KOMISYON_ISARETI[x["netkar_istek_tipi"]]
                beklenen_sr = (d(x["credit"]) - d(x["debt"])) - isr * abs(d(x["commissionAmount"] or 0))
                if x.get("sellerRevenue") is not None and \
                        abs(abs(d(x["sellerRevenue"])) - abs(beklenen_sr)) > D("0.01"):
                    S["uyarilar"].append("EKSTRE_IC_TUTARSIZLIK")
            for x in rows:
                if x["netkar_istek_tipi"] == "Sale" and x.get("commissionRate") is not None:
                    if abs(d(x["commissionRate"]) - d(ln["commission"])) > ue["komisyon_orani_tolerans_puan"]:
                        S["uyarilar"].append("KOMISYON_ORANI_FARKLI")
        else:
            satis_dahil = satis_tahmini_dahil
            iade_dahil = D(0)
            kom_exact = kom_tahmini_exact
            kom_satis_exact = kom_tahmini_exact
        S["kaynak"]["satis"] = "kesin" if S["has_sale"] else "tahmini"
        S["kaynak"]["komisyon"] = "kesin" if S["has_sale"] else "tahmini"

        S["satis_dahil_exact"], S["iade_dahil_exact"] = satis_dahil, iade_dahil
        S["satis_haric"], S["satis_kdv"] = dahil_ayir(satis_dahil, r)
        S["iade_haric"], S["iade_kdv"] = dahil_ayir(iade_dahil, r)
        S["net_satis"] = S["satis_haric"] - S["iade_haric"]

        def kom_ayir(exact):
            return dahil_ayir(exact, kom_kdv_o) if ay["komisyon_tutari_kdv_dahil"] else haric_kdv(exact, kom_kdv_o)
        S["kom_haric"], S["kom_kdv"] = kom_ayir(kom_exact)
        S["kom_tahmini_haric"], _ = kom_ayir(kom_tahmini_exact)
        S["kom_kesin_satis_haric"], _ = kom_ayir(kom_satis_exact)

        S["adet_iade_stok"] = S["adet_iade_hurda"] = 0
        for c in claims:
            if c["orderNumber"] != o["orderNumber"]:
                continue
            for it in c["items"]:
                for ci in it["claimItems"]:
                    if str(ci["orderLineItemId"]) in S["item_ids"] and ci["claimItemStatus"]["name"] == "Accepted":
                        if ci.get("netkar_urun_durumu", "stoga_dondu") == "satilamaz":
                            S["adet_iade_hurda"] += 1
                        else:
                            S["adet_iade_stok"] += 1
        S["adet_iade"] = S["adet_iade_stok"] + S["adet_iade_hurda"]

        # K41: ekstrede Return var, kabul edilmiş iade kalemi yok -> iade kaydı bekleniyor.
        S["iade_bekleyen_adet"] = 0
        if not S["iptal"] and S["iade_return_dahil"] > 0 and S["adet_iade"] == 0:
            if satis_dahil > 0:
                S["iade_bekleyen_adet"] = min(q, max(1, tamsayi_yuvarla(q * S["iade_return_dahil"] / satis_dahil)))
            else:
                S["iade_bekleyen_adet"] = q
            S["uyarilar"].append("IADE_KAYDI_BEKLENIYOR")

        adaylar = sorted((m for m in maliyetler if m["barcode"] == ln["barcode"]
                          and m["gecerlilik_baslangic"] <= S["gun"]), key=lambda m: m["gecerlilik_baslangic"])
        S["askidaki_maliyet"] = None
        if S["iptal"]:
            S["maliyet_haric"], S["maliyet_kdv"] = D(0), D(0)
            S["kaynak"]["urun_maliyeti"] = "yok"
        elif not adaylar:
            S["maliyet_haric"] = S["maliyet_kdv"] = None
            S["uyarilar"].append("MALIYET_EKSIK")
            S["kaynak"]["urun_maliyeti"] = "eksik"
        else:
            m = adaylar[-1]
            adet = q - S["adet_iade_stok"]
            S["maliyet_haric"], S["maliyet_kdv"] = haric_kdv(d(m["birim_maliyet_kdv_haric"]) * adet,
                                                             d(m["kdv_orani"]))
            S["kaynak"]["urun_maliyeti"] = "kullanici"
            if S["iade_bekleyen_adet"]:
                # K41: maliyet ihtiyatla tam gider kalır; değer kesin değil (tahmini), askıdaki tutar bilgi.
                S["kaynak"]["urun_maliyeti"] = "tahmini"
                S["askidaki_maliyet"] = rnd(d(m["birim_maliyet_kdv_haric"]) * S["iade_bekleyen_adet"])

        for k in ("kargo_g_h", "kargo_g_k", "kargo_i_h", "kargo_i_k", "hiz_h", "hiz_k", "ceza_h", "ceza_k",
                  "rek_h", "rek_k", "deg_h", "deg_k"):
            S[k] = D(0)
        S["kargo_g_tahmini_h"] = None  # K38: tanımsız tahmin None (0 değil)
        S["hiz_tahmini_h"] = None
        S["kargo_g_kesin_var"] = False
        S["hiz_kesin_var"] = False
        S["degisken_detay"] = []
        S["reklam_detay"] = []
        S["eksik"] = []
        if S["kaynak"]["urun_maliyeti"] == "eksik":
            S["eksik"].append("urun_maliyeti")

    paketler: dict = {}
    for S in satirlar:
        paketler.setdefault(S["o"]["shipmentPackageId"], []).append(S)

    def agirlik_satis(grup):
        return [S["satis_haric"] for S in grup]

    # ---- B. kargo (K08, K09, K12, K34)
    def fatura_kdv_durumu(fatura):
        ust = next((x for x in others if str(x["id"]) == str(fatura["invoiceSerialNumber"])), None)
        toplam = sum((d(i["amount"]) for i in fatura["items"]), D(0))
        tol = max(d(ay["kargo_faturasi_kdv_tespit_toleransi"]), D("0.01") * len(fatura["items"]))
        if ust is None:
            return "bilinmiyor"
        borc = d(ust["debt"])
        if abs(toplam - borc) <= tol:
            return "dahil"
        if abs(toplam * (1 + kargo_kdv_o / YUZ) - borc) <= tol:
            return "haric"
        return "bilinmiyor"

    durumlar = {str(f["invoiceSerialNumber"]): fatura_kdv_durumu(f) for f in kargo_faturalari}

    def kargo_kalemleri(order_no, tip):
        return [(i, durumlar[str(f["invoiceSerialNumber"])]) for f in kargo_faturalari for i in f["items"]
                if i["orderNumber"] == order_no and i["shipmentPackageType"] == tip]

    def kalem_toplam(kalemler):
        dahil_exact = sum((d(i["amount"]) for i, du in kalemler if du == "dahil"), D(0))
        haric_exact = sum((d(i["amount"]) for i, du in kalemler if du != "dahil"), D(0))
        belirsiz = any(du == "bilinmiyor" for _, du in kalemler)
        h1, k1 = dahil_ayir(dahil_exact, kargo_kdv_o)
        h2, k2 = haric_kdv(haric_exact, kargo_kdv_o)
        return h1 + h2, k1 + k2, belirsiz

    for _pid, grup in paketler.items():
        o = grup[0]["o"]
        aktif = [S for S in grup if not S["iptal"]]
        if not aktif:
            continue
        gun = aktif[0]["gun"]
        if all(S["ln"].get("netkar_urun_desi") is not None for S in aktif):
            w = [d(S["ln"]["netkar_urun_desi"]) * S["q"] for S in aktif]
        else:
            w = agirlik_satis(aktif)
        # K34 desi sırası: cargoDeci -> ceil(deci) -> hesabın varsayılan desisi (uyarılı) -> yok.
        siparis_desi = o.get("cargoDeci")
        if siparis_desi is None and o.get("deci") is not None:
            siparis_desi = math.ceil(d(o["deci"]))
        varsayilan_kullanildi = False
        desi_tahmin = siparis_desi
        if desi_tahmin is None and ay.get("varsayilan_desi") is not None:
            desi_tahmin = d(ay["varsayilan_desi"])
            varsayilan_kullanildi = True
        satici = o.get("whoPays") == 1
        tarife = ay["satici_kargo_tarifesi"] if satici else ay["kargo_tarifesi"]
        tah = tarife_fiyat(tarife, o["cargoProviderName"], desi_tahmin, gun)
        tah_kaynak = "kullanici" if satici else "tahmini"
        kalemler = kargo_kalemleri(o["orderNumber"], "Gönderi Kargo Bedeli") if not satici else []
        if kalemler:
            h, k, belirsiz = kalem_toplam(kalemler)
            kaynak = "kesin"
            desi_kesin = sum(int(i["desi"]) for i, _ in kalemler)
            # KARGO_DESI_FARKI yalnız siparişten gelen desiyle karşılaştırılır (varsayılan desiyle değil).
            if siparis_desi is not None and d(desi_kesin) != d(siparis_desi):
                for S in aktif:
                    S["uyarilar"].append("KARGO_DESI_FARKI")
            if belirsiz:
                for S in aktif:
                    S["uyarilar"].append("KARGO_FATURASI_KDV_BELIRSIZ")
        elif tah is not None:
            h, k = haric_kdv(tah, kargo_kdv_o)
            kaynak = tah_kaynak
            if varsayilan_kullanildi:
                for S in aktif:
                    S["uyarilar"].append("KARGO_DESI_VARSAYILAN")
        else:
            h, k, kaynak = D(0), D(0), "eksik"
            for S in aktif:
                S["uyarilar"].append("KARGO_TARIFESI_EKSIK")
                S["eksik"].append("kargo_gonderi")
        for S, ph, pk in zip(aktif, dagit(h, w), dagit(k, w)):
            S["kargo_g_h"], S["kargo_g_k"] = ph, pk
            S["kaynak"]["kargo_gonderi"] = kaynak
            S["kargo_g_kesin_var"] = kaynak == "kesin"
        if tah is not None:
            th, _ = haric_kdv(tah, kargo_kdv_o)
            for S, ph in zip(aktif, dagit(th, w)):
                S["kargo_g_tahmini_h"] = ph
        ikal = kargo_kalemleri(o["orderNumber"], "İade Kargo Bedeli")
        if ikal:
            h, k, _ = kalem_toplam(ikal)
            hedef = [S for S in aktif if S["adet_iade"] > 0 or S["iade_haric"] > 0] or aktif
            wi = [S["iade_haric"] if S["iade_haric"] > 0 else S["satis_haric"] for S in hedef]
            for S, ph, pk in zip(hedef, dagit(h, wi), dagit(k, wi)):
                S["kargo_i_h"], S["kargo_i_k"] = ph, pk
                S["kaynak"]["kargo_iade"] = "kesin"

    # ---- C. platform hizmet bedeli (K13, K35)
    psf = [x for x in others if x.get("netkar_istek_tipi") == "DeductionInvoices"
           and x.get("netkar_istek_alt_tipi") == "PlatformServiceFee"]
    siparis_satirlari: dict = {}
    for S in satirlar:
        siparis_satirlari.setdefault(S["o"]["orderNumber"], []).append(S)
    sira_no = [S["o"]["orderNumber"] for S in satirlar]
    kapsanan = set()
    for x in psf:
        if x.get("orderNumber"):
            hedef_sip = [x["orderNumber"]]
        else:
            hedef_sip = sorted({S["o"]["orderNumber"] for S in satirlar if S["has_sale"] and not S["iptal"]
                                and any(rw.get("paymentOrderId") == x.get("paymentOrderId")
                                        for rw in S["rows"] if rw["netkar_istek_tipi"] == "Sale")},
                               key=sira_no.index)
        h, k = dahil_ayir(d(x["debt"]) - d(x["credit"]), hiz_kdv_o)
        for no, oh, ok in zip(hedef_sip, dagit(h, [D(1)] * len(hedef_sip)), dagit(k, [D(1)] * len(hedef_sip))):
            grup = [S for S in siparis_satirlari[no] if not S["iptal"]]
            w = agirlik_satis(grup)
            for S, ph, pk in zip(grup, dagit(oh, w), dagit(ok, w)):
                S["hiz_h"] += ph
                S["hiz_k"] += pk
                S["kaynak"]["platform_hizmet_bedeli"] = "kesin_dagitim"
                S["hiz_kesin_var"] = True
            kapsanan.add(no)
    for no, grup0 in siparis_satirlari.items():
        grup = [S for S in grup0 if not S["iptal"]]
        if not grup:
            continue
        tahmin = hizmet_tahmini(ay, grup[0]["gun"])
        w = agirlik_satis(grup)
        if tahmin is None:
            if no not in kapsanan:
                for S in grup:
                    S["kaynak"]["platform_hizmet_bedeli"] = "eksik"
                    S["uyarilar"].append("HIZMET_BEDELI_TAHMINI_EKSIK")
                    S["eksik"].append("platform_hizmet_bedeli")
            continue
        th, tk = haric_kdv(tahmin, hiz_kdv_o)
        for S, ph, pk in zip(grup, dagit(th, w), dagit(tk, w)):
            S["hiz_tahmini_h"] = ph
            if no not in kapsanan:
                S["hiz_h"], S["hiz_k"] = ph, pk
                S["kaynak"]["platform_hizmet_bedeli"] = "tahmini"

    # ---- D. ceza, erken ödeme, stopaj, sınıflandırılamayan (K14, K18, K19)
    donem = {"dagitilmamis_ceza_kdv_haric": D(0), "erken_odeme_bedeli_kdv_haric": D(0),
             "siniflandirilmamis_kesinti": D(0), "reklam_dagitilamayan_kdv_haric": D(0),
             "stopaj_ekstre": D(0), "erken_odeme_nakit_girisi": D(0), "uyarilar": []}
    for x in others:
        tip, sinif = x.get("netkar_istek_tipi"), x.get("netkar_sinif")
        if tip == "Stoppage":
            donem["stopaj_ekstre"] += d(x["debt"]) - d(x["credit"])
            continue
        if tip == "CashAdvance":
            donem["erken_odeme_nakit_girisi"] += d(x["credit"]) - d(x["debt"])
            continue
        if tip == "DeductionInvoices" and x.get("netkar_istek_alt_tipi") == "PlatformServiceFee":
            continue
        if tip == "DeductionInvoices" and x.get("transactionType") in ("Kargo Faturası", "Kargo Fatura"):
            continue
        if tip in ("PaymentOrder",):
            continue
        tutar = d(x["debt"]) - d(x["credit"])
        if sinif in ("ceza", "erken_odeme_bedeli"):
            ko = d(x.get("netkar_kdv_orani", "0"))
            h, k = dahil_ayir(tutar, ko) if ko > 0 else (rnd(tutar), D(0))
            if sinif == "erken_odeme_bedeli":
                donem["erken_odeme_bedeli_kdv_haric"] += h
                continue
            if x.get("orderNumber") and x["orderNumber"] in siparis_satirlari:
                grup = [S for S in siparis_satirlari[x["orderNumber"]] if not S["iptal"]]
                w = agirlik_satis(grup)
                for S, ph, pk in zip(grup, dagit(h, w), dagit(k, w)):
                    S["ceza_h"] += ph
                    S["ceza_k"] += pk
                    S["kaynak"]["ceza"] = "kesin_dagitim"
            else:
                donem["dagitilmamis_ceza_kdv_haric"] += h
        else:
            donem["siniflandirilmamis_kesinti"] += rnd(tutar)
            if "SINIFLANDIRILMAMIS_KESINTI" not in donem["uyarilar"]:
                donem["uyarilar"].append("SINIFLANDIRILMAMIS_KESINTI")

    # ---- E. değişken giderler (K17, K36)
    for gid in ay["degisken_giderler"]:
        ko = d(gid.get("kdv_orani", "20"))
        if gid["tip"] == "siparis_basi":
            for _no, grup0 in siparis_satirlari.items():
                grup = [S for S in grup0 if not S["iptal"]]
                if not grup or not gider_gecerli(gid, grup[0]["gun"]):
                    continue
                h, k = haric_kdv(d(gid["tutar_kdv_haric"]), ko)
                w = agirlik_satis(grup)
                for S, ph, pk in zip(grup, dagit(h, w), dagit(k, w)):
                    S["deg_h"] += ph
                    S["deg_k"] += pk
                    S["degisken_detay"].append({"ad": gid["ad"], "tutar_kdv_haric": s(ph)})
        else:
            for S in satirlar:
                if S["iptal"] or not gider_gecerli(gid, S["gun"]):
                    continue
                if gid["tip"] == "adet_basi":
                    h, k = haric_kdv(d(gid["tutar_kdv_haric"]) * S["q"], ko)
                else:
                    h, k = haric_kdv(S["net_satis"] * d(gid["oran_yuzde"]) / YUZ, ko)
                S["deg_h"] += h
                S["deg_k"] += k
                S["degisken_detay"].append({"ad": gid["ad"], "tutar_kdv_haric": s(h)})
    for S in satirlar:
        S["kaynak"]["degisken_giderler"] = "kullanici" if S["degisken_detay"] else "yok"

    # ---- F. reklam (K15)
    katalog = {S["ln"]["barcode"] for S in satirlar} | {m["barcode"] for m in maliyetler} | \
        {u["barcode"] for u in g.get("urunler", [])}
    urun_reklam_satissiz: dict = {}
    urun_reklam_cirosu: dict = {}
    for rk in g.get("reklam_kayitlari", []):
        h_exact = d(rk["harcama"])
        h = dahil_ayir(h_exact, rek_kdv_o)[0] if rk.get("harcama_kdv_dahil") else rnd(h_exact)
        k = rnd(h * rek_kdv_o / YUZ)
        donemde = [S for S in satirlar if not S["iptal"] and rk["baslangic"] <= S["gun"] <= rk["bitis"]]
        bk = rk.get("barkod")
        if bk and bk in katalog:
            if rk.get("reklam_cirosu") is not None:
                urun_reklam_cirosu[bk] = urun_reklam_cirosu.get(bk, D(0)) + d(rk["reklam_cirosu"])
            hedef = [S for S in donemde if S["ln"]["barcode"] == bk and S["net_satis"] > 0]
            if not hedef:
                urun_reklam_satissiz[bk] = urun_reklam_satissiz.get(bk, D(0)) + h
                continue
            etiket = "eslesen"
        else:
            hedef = [S for S in donemde if S["net_satis"] > 0]
            if not hedef:
                donem["reklam_dagitilamayan_kdv_haric"] += h
                continue
            etiket = "dagitim_tahmini"
        w = [S["net_satis"] for S in hedef]
        for S, ph, pk in zip(hedef, dagit(h, w), dagit(k, w)):
            S["rek_h"] += ph
            S["rek_k"] += pk
            S["reklam_detay"].append({"kayit": rk["kayit_id"], "tur": etiket, "tutar_kdv_haric": s(ph)})
    for S in satirlar:
        turler = {x["tur"] for x in S["reklam_detay"]}
        S["kaynak"]["reklam"] = ("dagitim_tahmini" if "dagitim_tahmini" in turler else
                                 "eslesen" if turler else "yok")

    # ---- G. satır sonuçları (K20-K23, K37, K38, K40, K41)
    cikti_satirlar = []
    for S in satirlar:
        o, ln = S["o"], S["ln"]
        S["eksik"] = [k for k in EKSIK_SIRA if k in S["eksik"]]
        giderler_maliyetsiz = (S["kom_haric"] + S["kargo_g_h"] + S["kargo_i_h"] + S["hiz_h"] + S["ceza_h"]
                               + S["rek_h"] + S["deg_h"])
        katki = S["net_satis"] - giderler_maliyetsiz
        bilinen_maliyet = S["maliyet_haric"] if S["maliyet_haric"] is not None else D(0)
        haric_kar = katki - bilinen_maliyet  # K37: eksik kalemler hariç kâr (bilinen giderlerle)
        if S["eksik"]:
            net_kar = toplam_gider = None
        else:
            toplam_gider = giderler_maliyetsiz + S["maliyet_haric"]
            net_kar = S["net_satis"] - toplam_gider
        if not S["iptal"] and ((net_kar is not None and net_kar < 0) or (net_kar is None and haric_kar < 0)):
            S["uyarilar"].append("ZARAR")  # K37: eksik kalemler negatif olamaz; bilinenle zarar = kesin zarar

        if S["iptal"]:
            durum = "cancelled"
        elif not S["has_sale"]:
            durum = "estimated"
        elif S["duzeltme_var"] or S["kargo_i_h"] != 0 or S["ceza_h"] != 0:
            durum = "adjusted"
        else:
            durum = "settled"

        kars = None
        if S["has_sale"] and not S["iptal"]:
            kom_t, kom_k = S["kom_tahmini_haric"], S["kom_kesin_satis_haric"]
            kar_t, hiz_t = S["kargo_g_tahmini_h"], S["hiz_tahmini_h"]
            kar_k = S["kargo_g_h"] if S["kargo_g_kesin_var"] else None
            hiz_k = S["hiz_h"] if S["hiz_kesin_var"] else None
            # K38: kalem karşılaştırmaya YALNIZ tahmini tanımlı VE kesin geldiyse girer.
            kargo_gir = kar_k is not None and kar_t is not None
            hiz_gir = hiz_k is not None and hiz_t is not None
            tahmin_top = kom_t + (kar_t if kargo_gir else 0) + (hiz_t if hiz_gir else 0)
            kesin_top = kom_k + (kar_k if kargo_gir else 0) + (hiz_k if hiz_gir else 0)
            fark = kesin_top - tahmin_top
            esik = max(ue["beklenmeyen_kesinti_tutar"], tahmin_top * ue["beklenmeyen_kesinti_oran_yuzde"] / YUZ)
            if fark > ue["yuvarlama_toleransi"] and fark > esik:
                S["uyarilar"].append("BEKLENMEYEN_KESINTI")
            kars = {
                "komisyon_tahmini": s(kom_t), "komisyon_kesin": s(kom_k),
                "kargo_gonderi_tahmini": s(kar_t), "kargo_gonderi_kesin": s(kar_k),
                "platform_hizmet_bedeli_tahmini": s(hiz_t), "platform_hizmet_bedeli_kesin": s(hiz_k),
                "karsilastirilan_tahmini_toplam": s(tahmin_top), "karsilastirilan_kesin_toplam": s(kesin_top),
                "fark": s(fark), "esik": s(esik),
            }

        maliyet_kdv = S["maliyet_kdv"] or D(0)
        kdv_etkisi = (S["satis_kdv"] - S["iade_kdv"]) - (S["kom_kdv"] + S["kargo_g_k"] + S["kargo_i_k"] + S["hiz_k"]
                                                       + S["ceza_k"] + maliyet_kdv + S["deg_k"] + S["rek_k"])
        hakedis = rnd(S["satis_dahil_exact"]) - rnd(S["iade_dahil_exact"]) - (S["kom_haric"] + S["kom_kdv"])
        fatura_kesintileri = (S["kargo_g_h"] + S["kargo_g_k"] + S["kargo_i_h"] + S["kargo_i_k"]
                              + S["hiz_h"] + S["hiz_k"] + S["ceza_h"] + S["ceza_k"])
        if o.get("whoPays") == 1:
            fatura_kesintileri -= S["kargo_g_h"] + S["kargo_g_k"]
        stopaj = rnd(S["net_satis"] * stopaj_o / YUZ)

        # K40 kesinlik
        if S["iptal"]:
            kesinlik = "iptal"
        elif S["eksik"]:
            kesinlik = "eksik"
        elif all(v in KESIN_KAYNAKLAR for v in S["kaynak"].values()):
            kesinlik = "kesin"
        else:
            kesinlik = "tahmini"

        S.update(stopaj=stopaj, net_kar=net_kar, katki=katki, haric_kar=haric_kar, toplam_gider=toplam_gider,
                 durum=durum, kesinlik=kesinlik)
        S["uyarilar"] = list(dict.fromkeys(S["uyarilar"]))

        cikti_satirlar.append({
            "orderNumber": o["orderNumber"], "shipmentPackageId": o["shipmentPackageId"],
            "lineId": ln["lineId"], "barcode": ln["barcode"], "durum": durum,
            "adet": S["q"], "adet_iade": S["adet_iade"],
            "iade_kaydi_bekleyen_adet": S["iade_bekleyen_adet"],
            "askidaki_urun_maliyeti": s(S["askidaki_maliyet"]),
            "kesinlik": kesinlik,
            "eksik_kalemler": S["eksik"],
            "kalemler": {
                "brut_satis_kdv_dahil": s(S["brut"]), "satici_indirimi_kdv_dahil": s(S["sind"]),
                "trendyol_indirimi_kdv_dahil": s(S["tind"]), "satis_kdv_dahil": s(S["satis_dahil_exact"]),
                "satis_kdv_haric": s(S["satis_haric"]), "iade_kdv_dahil": s(S["iade_dahil_exact"]),
                "iade_kdv_haric": s(S["iade_haric"]), "net_satis_kdv_haric": s(S["net_satis"]),
                "urun_maliyeti": s(S["maliyet_haric"]), "komisyon": s(S["kom_haric"]),
                "kargo_gonderi": s(S["kargo_g_h"]), "kargo_iade": s(S["kargo_i_h"]),
                "platform_hizmet_bedeli": s(S["hiz_h"]), "ceza": s(S["ceza_h"]), "reklam": s(S["rek_h"]),
                "degisken_giderler": s(S["deg_h"]), "toplam_gider": s(toplam_gider),
                "maliyet_haric_katki": s(katki), "eksik_giderler_haric_kar": s(haric_kar),
                "net_kar": s(net_kar), "net_kar_marji_yuzde": yuzde(net_kar, S["net_satis"]),
            },
            "kdv": {
                "satis_kdv": s(S["satis_kdv"]), "iade_kdv": s(S["iade_kdv"]), "komisyon_kdv": s(S["kom_kdv"]),
                "kargo_kdv": s(S["kargo_g_k"] + S["kargo_i_k"]), "platform_hizmet_bedeli_kdv": s(S["hiz_k"]),
                "ceza_kdv": s(S["ceza_k"]), "urun_maliyeti_kdv": s(S["maliyet_kdv"]),
                "degisken_giderler_kdv": s(S["deg_k"]), "reklam_kdv": s(S["rek_k"]), "kdv_etkisi": s(kdv_etkisi),
            },
            "nakit_akisi": {
                "trendyol_hakedis": s(hakedis), "fatura_kesintileri_kdv_dahil": s(fatura_kesintileri),
                "stopaj": s(stopaj), "beklenen_net_tahsilat": s(hakedis - fatura_kesintileri - stopaj),
            },
            "kaynaklar": S["kaynak"],
            "degisken_gider_detayi": S["degisken_detay"],
            "reklam_detayi": S["reklam_detay"],
            "karsilastirma": kars,
            "uyarilar": S["uyarilar"],
        })

    def kesinlik_ozet(grup):
        if not grup:
            return "yok"
        if any(S["kesinlik"] == "eksik" for S in grup):
            return "eksik"
        if all(S["kesinlik"] == "kesin" for S in grup):
            return "kesin"
        return "tahmini"

    def eksik_sayilari(grup):
        return {k: sum(1 for S in grup if k in S["eksik"]) for k in EKSIK_SIRA}

    # ---- H. ürün toplamları (K25, K37, K40)
    urunler: dict = {}
    sira = []
    for S in satirlar:
        bk = S["ln"]["barcode"]
        if bk not in urunler:
            urunler[bk] = []
            sira.append(bk)
        urunler[bk].append(S)
    for bk in urun_reklam_satissiz:
        if bk not in urunler:
            urunler[bk] = []
            sira.append(bk)
    cikti_urunler = []
    for bk in sira:
        grup = [S for S in urunler[bk] if not S["iptal"]]
        top = lambda k, grup=grup: sum((S[k] for S in grup), D(0))  # noqa: E731
        satissiz = urun_reklam_satissiz.get(bk, D(0))
        maliyet_eksik = any(S["maliyet_haric"] is None for S in grup)
        tam = all(not S["eksik"] for S in grup)
        net = sum((S["net_kar"] for S in grup), D(0)) - satissiz if tam else None
        katki = top("katki") - satissiz
        reklam_top = top("rek_h") + satissiz
        net_satis = top("net_satis")
        ciro = urun_reklam_cirosu.get(bk)
        reklam_oncesi = None if net is None else net + reklam_top
        cikti_urunler.append({
            "barcode": bk, "satir_sayisi": len(grup), "adet": sum(S["q"] for S in grup),
            "adet_iade": sum(S["adet_iade"] for S in grup), "net_satis_kdv_haric": s(net_satis),
            "urun_maliyeti": None if maliyet_eksik else s(top("maliyet_haric")),
            "komisyon": s(top("kom_haric")), "kargo_gonderi": s(top("kargo_g_h")),
            "kargo_iade": s(top("kargo_i_h")), "platform_hizmet_bedeli": s(top("hiz_h")),
            "ceza": s(top("ceza_h")), "reklam_satirlara_dagitilan": s(top("rek_h")),
            "reklam_satissiz": s(satissiz), "degisken_giderler": s(top("deg_h")),
            "maliyet_haric_katki": s(katki),
            "eksik_giderler_haric_kar": s(top("haric_kar") - satissiz),
            "net_kar": s(net), "net_kar_marji_yuzde": yuzde(net, net_satis),
            "maliyet_eksik": maliyet_eksik,
            "eksik_kalem_satir_sayilari": eksik_sayilari(grup),
            "kesinlik": kesinlik_ozet(grup),
            "reklam_harcamasi": s(reklam_top), "reklam_cirosu": s(ciro),
            "roas": eski.oran2(ciro, reklam_top) if ciro is not None else None,
            "basabas_roas": (eski.oran2(net_satis, reklam_oncesi)
                             if reklam_oncesi is not None and reklam_oncesi > 0 and reklam_top > 0 else None),
            "stopaj": s(top("stopaj")),
        })

    # ---- I. dönem toplamı (K25, K39, K40)
    aktif = [S for S in satirlar if not S["iptal"]]
    tamlar = [S for S in aktif if not S["eksik"]]
    top = lambda k, grup=aktif: sum((S[k] for S in grup), D(0))  # noqa: E731
    satissiz_top = sum(urun_reklam_satissiz.values(), D(0))
    maliyet_eksik_n = sum(1 for S in aktif if S["maliyet_haric"] is None)
    satir_net = sum((S["net_kar"] for S in tamlar), D(0))  # tam satırların net kârı (tam_satirlar.net_kar)
    donem_gider = (satissiz_top + donem["reklam_dagitilamayan_kdv_haric"] + donem["dagitilmamis_ceza_kdv_haric"]
                   + donem["erken_odeme_bedeli_kdv_haric"] + donem["siniflandirilmamis_kesinti"])
    kismi = len(tamlar) != len(aktif)
    # K39 Revizyon 1 (denetim AO-03): kısmi dönemde satır net kâr toplamı ve dönem net kârı null; bilinen
    # giderlerle dönem kârı ayrı ve adı ne olduğunu söyleyen alanda (tüm aktif satırlar, tüm dönem giderleri).
    donem_net = None if kismi else satir_net - donem_gider
    donem_haric = sum((S["haric_kar"] for S in aktif), D(0)) - donem_gider
    stopaj_hes = top("stopaj")
    eksik_n = eksik_sayilari(aktif)
    uyarilar = list(donem["uyarilar"])
    if maliyet_eksik_n:
        uyarilar.append("MALIYET_EKSIK_SATIRLAR_VAR")
    if eksik_n["kargo_gonderi"]:
        uyarilar.append("KARGO_EKSIK_SATIRLAR_VAR")
    if eksik_n["platform_hizmet_bedeli"]:
        uyarilar.append("HIZMET_BEDELI_EKSIK_SATIRLAR_VAR")
    if any(S["iade_bekleyen_adet"] for S in aktif):
        uyarilar.append("IADE_KAYDI_BEKLENEN_SATIRLAR_VAR")
    if donem["stopaj_ekstre"] != 0 and abs(donem["stopaj_ekstre"] - stopaj_hes) > d("0.05"):
        uyarilar.append("STOPAJ_EKSTRE_FARKI")
    t = lambda k: top(k, tamlar)  # noqa: E731
    tam_gider = (t("maliyet_haric") + t("kom_haric") + t("kargo_g_h") + t("kargo_i_h") + t("hiz_h") + t("ceza_h")
                 + t("rek_h") + t("deg_h"))
    kesinlik_n = {k: sum(1 for S in aktif if S["kesinlik"] == k) for k in ("kesin", "tahmini", "eksik")}
    cikti_donem = {
        "siparis_sayisi": len({S["o"]["orderNumber"] for S in aktif}),
        "satir_sayisi": len(aktif),
        "net_satis_kdv_haric": s(top("net_satis")),
        "urun_maliyeti": s(sum((S["maliyet_haric"] for S in aktif if S["maliyet_haric"] is not None), D(0))),
        "komisyon": s(top("kom_haric")), "kargo_gonderi": s(top("kargo_g_h")), "kargo_iade": s(top("kargo_i_h")),
        "platform_hizmet_bedeli": s(top("hiz_h")), "ceza_satirlara_dagitilan": s(top("ceza_h")),
        "reklam_satirlara_dagitilan": s(top("rek_h")), "degisken_giderler": s(top("deg_h")),
        "satir_net_kar_toplami": None if kismi else s(satir_net),
        "donem_duzeyi_giderler": {
            "reklam_satissiz_urunler": s(satissiz_top),
            "reklam_dagitilamayan": s(donem["reklam_dagitilamayan_kdv_haric"]),
            "dagitilmamis_ceza": s(donem["dagitilmamis_ceza_kdv_haric"]),
            "erken_odeme_bedeli": s(donem["erken_odeme_bedeli_kdv_haric"]),
            "siniflandirilmamis_kesinti": s(donem["siniflandirilmamis_kesinti"]),
        },
        "donem_duzeyi_giderler_toplami": s(donem_gider),
        "donem_net_kar": s(donem_net),
        "donem_eksik_giderler_haric_kar": s(donem_haric),
        "net_kar_kismi": kismi,
        "maliyet_eksik_satir_sayisi": maliyet_eksik_n,
        "eksik_kalem_satir_sayilari": eksik_n,
        "net_kar_marji_yuzde": None if kismi else yuzde(donem_net, top("net_satis")),
        "tam_satirlar": {
            "satir_sayisi": len(tamlar),
            "net_satis_kdv_haric": s(t("net_satis")), "urun_maliyeti": s(t("maliyet_haric")),
            "komisyon": s(t("kom_haric")), "kargo_gonderi": s(t("kargo_g_h")), "kargo_iade": s(t("kargo_i_h")),
            "platform_hizmet_bedeli": s(t("hiz_h")), "ceza": s(t("ceza_h")), "reklam": s(t("rek_h")),
            "degisken_giderler": s(t("deg_h")), "toplam_gider": s(tam_gider), "net_kar": s(satir_net),
            "net_kar_marji_yuzde": yuzde(satir_net, t("net_satis")),
        },
        "kesinlik": kesinlik_ozet(aktif),
        "kesinlik_satir_sayilari": kesinlik_n,
        "kdv_etkisi": None,
        "nakit_akisi": {
            "stopaj_hesaplanan": s(stopaj_hes), "stopaj_ekstre": s(donem["stopaj_ekstre"]),
            "erken_odeme_nakit_girisi": s(donem["erken_odeme_nakit_girisi"]),
        },
        "uyarilar": uyarilar,
    }
    cikti_donem["kdv_etkisi"] = s(sum((d(c["kdv"]["kdv_etkisi"]) for c in cikti_satirlar
                                       if c["durum"] != "cancelled"), D(0)))
    return {"siparis_satirlari": cikti_satirlar, "urun_toplamlari": cikti_urunler, "donem_toplami": cikti_donem,
            "kargo_faturasi_kdv_durumu": durumlar}


# --------------------------------------------------------------------------- yeni senaryolar (G42-G49)
YENI = []


def senaryo(sid, ad, aciklama, kurallar, etiketler):
    def sar(f):
        YENI.append((sid, ad, aciklama, kurallar, etiketler, f))
        return f
    return sar


# Kurgusal, sürümlü kullanıcı ayarları (G44, G45). Firma "Ornek Kargo" kurgusaldır; "*" diğer firmalar yedeği.
AYARLI = birlestir(URETIM_AYARLARI, {
    "kargo_tarifesi": {
        "Trendyol Express": [
            {"gecerlilik_baslangic": "2026-01-01", "kademeler": [["1", "38.00"], ["2", "42.00"], ["5", "55.00"]]},
            {"gecerlilik_baslangic": "2026-10-10", "kademeler": [["1", "40.00"], ["2", "45.00"], ["5", "60.00"]]},
        ],
        "*": [{"gecerlilik_baslangic": "2026-01-01", "kademeler": [["3", "50.00"], ["10", "80.00"]]}],
    },
    "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric": [
        {"gecerlilik_baslangic": "2026-01-01", "tutar_kdv_haric": "8.00"},
        {"gecerlilik_baslangic": "2026-10-10", "tutar_kdv_haric": "10.00"},
    ],
    "varsayilan_desi": "3",
    "degisken_giderler": [
        {"ad": "paketleme", "tip": "siparis_basi", "tutar_kdv_haric": "6.00", "kdv_orani": "20",
         "gecerlilik_baslangic": "2026-01-01", "gecerlilik_bitis": "2026-10-09"},
        {"ad": "paketleme", "tip": "siparis_basi", "tutar_kdv_haric": "7.50", "kdv_orani": "20",
         "gecerlilik_baslangic": "2026-10-10", "gecerlilik_bitis": None},
    ],
})
AYARLI["kargo_tarifesi"] = copy.deepcopy(AYARLI["kargo_tarifesi"])  # birlestir dict'leri birleştirir; açıkça ata


@senaryo("G42", "ayarsiz_uretim_varsayilani", "Üretim varsayılanı: hesapta hiçbir kâr ayarı yok (kargo tarifesi "
         "boş, hizmet bedeli tahmini tanımsız). Trendyol anlaşmalı ve satıcı anlaşmalı (whoPays=1) iki tahmini "
         "sipariş. Kargo ve hizmet bedeli 0 sayılmaz: kaynak eksik, satır uyarısı, net kâr null; eksik giderler "
         "hariç kâr ayrıca verilir. Dönem kısmi, marj null.",
         ["K33", "K34", "K35", "K37", "K39", "K40"], ["ayar_yok", "eksik_kalem", "estimated"])
def g42():
    o1 = siparis("10000421", [satir(BK_A, "499.90")])
    o2 = siparis("10000422", [satir(BK_B, "350.00", komisyon="18")], kargo="Aras Kargo Marketplace", whoPays=1)
    return {"ayarlar_tam": URETIM_AYARLARI, "siparisler": [o1, o2],
            "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_B, "120.00")]}


@senaryo("G43", "ayarsiz_hizmet_bedeli_eksik", "Kargo tarifesi tanımlı, platform hizmet bedeli tahmini tanımsız. "
         "A: yalnız hizmet bedeli eksik. C: maliyeti de girilmemiş ucuz ürün; bilinen giderlerle bile zararda "
         "(eksik kalemler negatif olamaz), bu yüzden net kâr null iken ZARAR uyarısı verilir.",
         ["K35", "K37", "K39", "K40"], ["ayar_yok", "eksik_kalem", "maliyet_eksik", "negatif_kar", "estimated"])
def g43():
    ay = birlestir(VARSAYILAN_AYARLAR_2, {})
    ay["platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric"] = None
    o1 = siparis("10000431", [satir(BK_A, "499.90")])
    o2 = siparis("10000432", [satir(BK_C, "50.00")], cargoDeci=1)
    return {"ayarlar_tam": ay, "siparisler": [o1, o2], "urun_maliyetleri": [maliyet(BK_A, "180.00")]}


@senaryo("G44", "ayarli_surumlu_tam", "Ayar girilmiş hesap, geçerlilik tarihli sürümler: Trendyol Express tarifesi, "
         "hizmet bedeli tahmini ve paketleme gideri 10 Ekim'de değişti. 5 Ekim siparişi eski sürümle (42,00 / 8,00 "
         "/ 6,00), 15 Ekim siparişi yeni sürümle (45,00 / 10,00 / 7,50) hesaplanır. Eksik kalem yok, dönem tam.",
         ["K33", "K34", "K35", "K36", "K37", "K39", "K40"], ["ayarli", "surum", "estimated"])
def g44():
    o1 = siparis("10000441", [satir(BK_A, "499.90")], tarih_iso="2026-10-05T14:30:00+03:00")
    o2 = siparis("10000442", [satir(BK_A, "499.90")], tarih_iso="2026-10-15T09:00:00+03:00")
    return {"ayarlar_tam": AYARLI, "siparisler": [o1, o2], "urun_maliyetleri": [maliyet(BK_A, "180.00")]}


@senaryo("G45", "ayarli_tarife_yedek_varsayilan_desi", "G44 ayarları. B: tarifesi olmayan firma ('*' yedeğe "
         "düşer) ve siparişte desi yok (hesabın varsayılan desisi 3, KARGO_DESI_VARSAYILAN). C: firma tarifesi var "
         "ama desi 7 en yüksek kademeyi (5) aşıyor: yedeğe düşmez, kargo eksik.",
         ["K34", "K37", "K40"], ["ayarli", "kargo_tarife", "eksik_kalem", "estimated"])
def g45():
    o1 = siparis("10000451", [satir(BK_B, "350.00", komisyon="18")], tarih_iso="2026-10-15T09:00:00+03:00",
                 kargo="Ornek Kargo", cargoDeci=None)
    o2 = siparis("10000452", [satir(BK_C, "500.00", komisyon="12")], tarih_iso="2026-10-15T09:00:00+03:00",
                 cargoDeci=7)
    return {"ayarlar_tam": AYARLI, "siparisler": [o1, o2],
            "urun_maliyetleri": [maliyet(BK_B, "120.00"), maliyet(BK_C, "260.00")]}


@senaryo("G46", "kismi_donem_marji", "Bir maliyetli (A), bir maliyetsiz (B) satır ve 17,35 sınıflandırılmamış "
         "kesinti. Dönem net kârı = tam satırların net kârı - dönem düzeyi giderler; dönem marjı null (kısmi). "
         "Tam satırlar bloğu kendi içinde tutarlı: net satış - toplam gider = net kâr, marj aynı satır kümesinden.",
         ["K25", "K37", "K39"], ["kismi_donem", "maliyet_eksik", "donem", "estimated"])
def g46():
    o1 = siparis("10000461", [satir(BK_A, "499.90")])
    o2 = siparis("10000462", [satir(BK_B, "350.00", komisyon="18")])
    fi = diger("FinancialItem", debt="17.35", metin="Düzeltme")
    return {"siparisler": [o1, o2], "urun_maliyetleri": [maliyet(BK_A, "180.00")], "otherfinancials": [fi]}


@senaryo("G47", "claimsiz_iade", "Ekstrede Return var, iade kaydı (claim) henüz gelmedi. 1: tam iade, 1 adet; "
         "2: 2 adetten 1'inin iadesi (bekleyen adet iade tutarı oranıyla 1). Maliyet ihtiyatla tam gider kalır "
         "(K10), kaynak tahmini, IADE_KAYDI_BEKLENIYOR; stoğa dönerse geri gelecek maliyet askidaki_urun_maliyeti.",
         ["K10", "K40", "K41"], ["tam_iade", "kismi_iade", "claim_yok", "adjusted", "negatif_kar"])
def g47():
    o1 = siparis("10000471", [satir(BK_A, "499.90")])
    l1 = o1["lines"][0]
    o2 = siparis("10000472", [satir(BK_D, "100.00", adet=2)])
    l2 = o2["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000047", [("Gönderi Kargo Bedeli", "10000471", "54.00", 2),
                                               ("İade Kargo Bedeli", "10000471", "54.00", 2),
                                               ("Gönderi Kargo Bedeli", "10000472", "54.00", 2)])
    return {"siparisler": [o1, o2],
            "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_D, "40.00")],
            "settlements": [satis_satiri(o1, l1), fin("Return", o1, l1, debt="499.90",
                                                      tarih_iso="2026-10-22T10:00:00+03:00"),
                            satis_satiri(o2, l2), fin("Return", o2, l2, debt="100.00",
                                                      tarih_iso="2026-10-22T10:00:00+03:00")],
            "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G48", "sifir_tahmin_beklenmeyen_kesinti_yok", "Üretim varsayılanı (ayar yok), iki ekstreli sipariş. "
         "1: kargo faturası ve siparişe bağlı hizmet bedeli faturası geldi; tüm kalemler kesin, net kâr "
         "hesaplanır, kesinlik kesin. 2: kargo faturası geldi, hizmet bedeli faturası yok: hizmet bedeli eksik. "
         "Tahmini tanımsız kalem K23 karşılaştırmasına girmez: BEKLENMEYEN_KESINTI yok (eski davranışta 45,00 ve "
         "55,00 fark uyarı üretirdi).",
         ["K23", "K35", "K37", "K38", "K40"], ["ayar_yok", "settled", "beklenmeyen_kesinti_yok"])
def g48():
    o1 = siparis("10000481", [satir(BK_A, "499.90")])
    l1 = o1["lines"][0]
    o2 = siparis("10000482", [satir(BK_B, "350.00", komisyon="18")])
    l2 = o2["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000048", [("Gönderi Kargo Bedeli", "10000481", "54.00", 2),
                                               ("Gönderi Kargo Bedeli", "10000482", "54.00", 2)])
    psf = diger("DeductionInvoices", debt="12.00", alt_tip="PlatformServiceFee", metin="Platform Hizmet Bedeli",
                orderNumber="10000481")
    return {"ayarlar_tam": URETIM_AYARLARI, "siparisler": [o1, o2],
            "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_B, "120.00")],
            "settlements": [satis_satiri(o1, l1), satis_satiri(o2, l2)],
            "otherfinancials": [ust, psf], "kargo_faturalari": [kf]}


@senaryo("G49", "tam_satirsiz_donem_gideri", "Üretim varsayılanı (ayar yok), tek tahmini sipariş ve 17,35 "
         "sınıflandırılmamış kesinti. Dönemde tam satır yok: dönem net kârı null (v0.2 kuralı 0,00 - 17,35 = "
         "-17,35 gibi uydurma bir zarar gösterirdi); bilinen giderlerle dönem kârı ayrı alanda: 174,09 - 17,35 = "
         "156,74. Tam satırlar bloğu boş toplamdır (0,00, marj null).",
         ["K37", "K39"], ["ayar_yok", "eksik_kalem", "kismi_donem", "donem", "estimated"])
def g49():
    o1 = siparis("10000491", [satir(BK_A, "499.90")])
    fi = diger("FinancialItem", debt="17.35", metin="Düzeltme")
    return {"ayarlar_tam": URETIM_AYARLARI, "siparisler": [o1],
            "urun_maliyetleri": [maliyet(BK_A, "180.00")], "otherfinancials": [fi]}


# --------------------------------------------------------------------------- elle hesaplanan kilit değerler
# Her değer docs/12 §12 örneklerinde adım adım gösterilmiştir. Yol: (bölüm, indeks, alan.alt_alan).
ELLE = {
    "G42": [
        ("satir", 0, "kalemler.satis_kdv_haric", "416.58"), ("satir", 0, "kalemler.komisyon", "62.49"),
        ("satir", 0, "kalemler.kargo_gonderi", "0.00"), ("satir", 0, "kalemler.platform_hizmet_bedeli", "0.00"),
        ("satir", 0, "kalemler.eksik_giderler_haric_kar", "174.09"),  # 416,58 - 180,00 - 62,49
        ("satir", 0, "kalemler.maliyet_haric_katki", "354.09"), ("satir", 0, "kalemler.net_kar", None),
        ("satir", 0, "kalemler.toplam_gider", None), ("satir", 0, "kalemler.net_kar_marji_yuzde", None),
        ("satir", 0, "kaynaklar.kargo_gonderi", "eksik"), ("satir", 0, "kaynaklar.platform_hizmet_bedeli", "eksik"),
        ("satir", 0, "eksik_kalemler", ["kargo_gonderi", "platform_hizmet_bedeli"]),
        ("satir", 0, "kesinlik", "eksik"), ("satir", 0, "kdv.kdv_etkisi", "34.82"),  # 83,32 - 12,50 - 36,00
        ("satir", 0, "nakit_akisi.beklenen_net_tahsilat", "420.74"),  # 424,91 - 0 - 4,17
        ("satir", 0, "uyarilar", {"KARGO_TARIFESI_EKSIK", "HIZMET_BEDELI_TAHMINI_EKSIK"}),
        ("satir", 1, "kalemler.eksik_giderler_haric_kar", "119.17"),  # 291,67 - 120,00 - 52,50
        ("satir", 1, "kaynaklar.kargo_gonderi", "eksik"), ("satir", 1, "kdv.kdv_etkisi", "23.83"),
        ("satir", 1, "nakit_akisi.beklenen_net_tahsilat", "284.08"),  # 287,00 - 0 - 2,92
        ("urun", 0, "net_kar", None), ("urun", 0, "eksik_giderler_haric_kar", "174.09"),
        ("urun", 0, "kesinlik", "eksik"),
        ("donem", None, "satir_net_kar_toplami", None), ("donem", None, "donem_net_kar", None),
        ("donem", None, "donem_eksik_giderler_haric_kar", "293.26"),  # 174,09 + 119,17 - 0
        ("donem", None, "net_kar_kismi", True), ("donem", None, "net_kar_marji_yuzde", None),
        ("donem", None, "net_satis_kdv_haric", "708.25"), ("donem", None, "tam_satirlar.satir_sayisi", 0),
        ("donem", None, "tam_satirlar.net_kar", "0.00"), ("donem", None, "tam_satirlar.net_kar_marji_yuzde", None),
        ("donem", None, "eksik_kalem_satir_sayilari",
         {"urun_maliyeti": 0, "kargo_gonderi": 2, "platform_hizmet_bedeli": 2}),
        ("donem", None, "uyarilar", {"KARGO_EKSIK_SATIRLAR_VAR", "HIZMET_BEDELI_EKSIK_SATIRLAR_VAR"}),
        ("donem", None, "kdv_etkisi", "58.65"),
    ],
    "G43": [
        ("satir", 0, "kalemler.kargo_gonderi", "45.00"), ("satir", 0, "kaynaklar.kargo_gonderi", "tahmini"),
        ("satir", 0, "kalemler.eksik_giderler_haric_kar", "129.09"),  # 416,58 - 180 - 62,49 - 45
        ("satir", 0, "kalemler.net_kar", None), ("satir", 0, "eksik_kalemler", ["platform_hizmet_bedeli"]),
        ("satir", 0, "kdv.kdv_etkisi", "25.82"), ("satir", 0, "nakit_akisi.beklenen_net_tahsilat", "366.74"),
        ("satir", 0, "uyarilar", {"HIZMET_BEDELI_TAHMINI_EKSIK"}),
        ("satir", 1, "kalemler.satis_kdv_haric", "41.67"), ("satir", 1, "kalemler.komisyon", "6.25"),
        ("satir", 1, "kalemler.kargo_gonderi", "40.00"),
        ("satir", 1, "kalemler.eksik_giderler_haric_kar", "-4.58"),  # 41,67 - 6,25 - 40,00
        ("satir", 1, "kalemler.maliyet_haric_katki", "-4.58"),
        ("satir", 1, "eksik_kalemler", ["urun_maliyeti", "platform_hizmet_bedeli"]),
        ("satir", 1, "uyarilar", {"MALIYET_EKSIK", "HIZMET_BEDELI_TAHMINI_EKSIK", "ZARAR"}),
        ("satir", 1, "nakit_akisi.beklenen_net_tahsilat", "-5.92"),  # 42,50 - 48,00 - 0,42
        ("donem", None, "donem_net_kar", None), ("donem", None, "maliyet_eksik_satir_sayisi", 1),
        ("donem", None, "donem_eksik_giderler_haric_kar", "124.51"),  # 129,09 + (-4,58)
        ("donem", None, "eksik_kalem_satir_sayilari",
         {"urun_maliyeti": 1, "kargo_gonderi": 0, "platform_hizmet_bedeli": 2}),
        ("donem", None, "uyarilar", {"MALIYET_EKSIK_SATIRLAR_VAR", "HIZMET_BEDELI_EKSIK_SATIRLAR_VAR"}),
    ],
    "G44": [
        ("satir", 0, "kalemler.kargo_gonderi", "42.00"), ("satir", 0, "kalemler.platform_hizmet_bedeli", "8.00"),
        ("satir", 0, "kalemler.degisken_giderler", "6.00"),
        ("satir", 0, "kalemler.net_kar", "118.09"),  # 416,58 - 180 - 62,49 - 42 - 8 - 6
        ("satir", 0, "kalemler.net_kar_marji_yuzde", "28.35"), ("satir", 0, "kdv.kdv_etkisi", "23.62"),
        ("satir", 0, "nakit_akisi.beklenen_net_tahsilat", "360.74"),
        ("satir", 1, "kalemler.kargo_gonderi", "45.00"), ("satir", 1, "kalemler.platform_hizmet_bedeli", "10.00"),
        ("satir", 1, "kalemler.degisken_giderler", "7.50"),
        ("satir", 1, "kalemler.net_kar", "111.59"),  # 416,58 - 180 - 62,49 - 45 - 10 - 7,50
        ("satir", 1, "kdv.kdv_etkisi", "22.32"), ("satir", 1, "kesinlik", "tahmini"),
        ("satir", 1, "eksik_kalemler", []), ("satir", 1, "uyarilar", set()),
        ("urun", 0, "net_kar", "229.68"), ("urun", 0, "kesinlik", "tahmini"),
        ("donem", None, "donem_net_kar", "229.68"), ("donem", None, "net_kar_kismi", False),
        ("donem", None, "satir_net_kar_toplami", "229.68"),
        ("donem", None, "donem_eksik_giderler_haric_kar", "229.68"),  # tam dönemde dönem net kârına eşit
        ("donem", None, "net_kar_marji_yuzde", "27.57"),  # 229,68 / 833,16
        ("donem", None, "tam_satirlar.toplam_gider", "603.48"), ("donem", None, "tam_satirlar.net_kar", "229.68"),
    ],
    "G45": [
        ("satir", 0, "kalemler.kargo_gonderi", "50.00"), ("satir", 0, "kaynaklar.kargo_gonderi", "tahmini"),
        ("satir", 0, "kalemler.net_kar", "51.67"),  # 291,67 - 120 - 52,50 - 50 - 10 - 7,50
        ("satir", 0, "uyarilar", {"KARGO_DESI_VARSAYILAN"}), ("satir", 0, "kesinlik", "tahmini"),
        ("satir", 1, "kalemler.kargo_gonderi", "0.00"), ("satir", 1, "kaynaklar.kargo_gonderi", "eksik"),
        ("satir", 1, "kalemler.komisyon", "50.00"),
        ("satir", 1, "kalemler.eksik_giderler_haric_kar", "89.17"),  # 416,67 - 260 - 50 - 10 - 7,50
        ("satir", 1, "kalemler.net_kar", None), ("satir", 1, "uyarilar", {"KARGO_TARIFESI_EKSIK"}),
        ("donem", None, "donem_net_kar", None), ("donem", None, "net_kar_kismi", True),
        ("donem", None, "satir_net_kar_toplami", None), ("donem", None, "tam_satirlar.net_kar", "51.67"),
        ("donem", None, "donem_eksik_giderler_haric_kar", "140.84"),  # 51,67 + 89,17
        ("donem", None, "net_kar_marji_yuzde", None), ("donem", None, "tam_satirlar.net_kar_marji_yuzde", "17.72"),
    ],
    "G46": [
        ("satir", 0, "kalemler.net_kar", "119.09"), ("satir", 1, "kalemler.net_kar", None),
        ("satir", 1, "kalemler.maliyet_haric_katki", "184.17"),  # 291,67 - 52,50 - 45 - 10
        ("donem", None, "satir_net_kar_toplami", None), ("donem", None, "donem_duzeyi_giderler_toplami", "17.35"),
        ("donem", None, "donem_net_kar", None), ("donem", None, "net_kar_kismi", True),  # v0.2: 119,09 - 17,35
        ("donem", None, "donem_eksik_giderler_haric_kar", "285.91"),  # 119,09 + 184,17 - 17,35
        ("donem", None, "net_kar_marji_yuzde", None),  # eski davranış 101,74 / 708,25 = 14,36 (karışık taban)
        ("donem", None, "tam_satirlar.net_satis_kdv_haric", "416.58"),
        ("donem", None, "tam_satirlar.toplam_gider", "297.49"),  # 180 + 62,49 + 45 + 10
        ("donem", None, "tam_satirlar.net_kar", "119.09"),
        ("donem", None, "tam_satirlar.net_kar_marji_yuzde", "28.59"),  # 119,09 / 416,58
        ("donem", None, "uyarilar", {"SINIFLANDIRILMAMIS_KESINTI", "MALIYET_EKSIK_SATIRLAR_VAR"}),
    ],
    "G47": [
        ("satir", 0, "durum", "adjusted"), ("satir", 0, "adet_iade", 0), ("satir", 0, "iade_kaydi_bekleyen_adet", 1),
        ("satir", 0, "askidaki_urun_maliyeti", "180.00"), ("satir", 0, "kalemler.urun_maliyeti", "180.00"),
        ("satir", 0, "kalemler.net_kar", "-280.00"),  # 0 - 180 - 45 - 45 - 10
        ("satir", 0, "kaynaklar.urun_maliyeti", "tahmini"), ("satir", 0, "kesinlik", "tahmini"),
        ("satir", 0, "uyarilar", {"IADE_KAYDI_BEKLENIYOR", "ZARAR"}), ("satir", 0, "kdv.kdv_etkisi", "-56.00"),
        ("satir", 1, "kalemler.net_satis_kdv_haric", "83.34"), ("satir", 1, "kalemler.komisyon", "12.50"),
        ("satir", 1, "kalemler.urun_maliyeti", "80.00"),
        ("satir", 1, "kalemler.net_kar", "-64.16"),  # 83,34 - 80 - 12,50 - 45 - 10
        ("satir", 1, "iade_kaydi_bekleyen_adet", 1), ("satir", 1, "askidaki_urun_maliyeti", "40.00"),
        ("satir", 1, "kdv.kdv_etkisi", "-12.84"), ("satir", 1, "nakit_akisi.beklenen_net_tahsilat", "18.17"),
        ("donem", None, "uyarilar", {"IADE_KAYDI_BEKLENEN_SATIRLAR_VAR"}),
        ("donem", None, "kesinlik", "tahmini"), ("donem", None, "net_kar_kismi", False),
        ("donem", None, "donem_net_kar", "-344.16"),  # -280,00 + (-64,16)
        ("donem", None, "donem_eksik_giderler_haric_kar", "-344.16"),
    ],
    "G48": [
        ("satir", 0, "kalemler.kargo_gonderi", "45.00"), ("satir", 0, "kalemler.platform_hizmet_bedeli", "10.00"),
        ("satir", 0, "kaynaklar.platform_hizmet_bedeli", "kesin_dagitim"),
        ("satir", 0, "kalemler.net_kar", "119.09"), ("satir", 0, "kesinlik", "kesin"),
        ("satir", 0, "karsilastirma.kargo_gonderi_tahmini", None),
        ("satir", 0, "karsilastirma.platform_hizmet_bedeli_tahmini", None),
        ("satir", 0, "karsilastirma.fark", "0.00"), ("satir", 0, "uyarilar", set()),
        ("satir", 1, "kaynaklar.platform_hizmet_bedeli", "eksik"),
        ("satir", 1, "kalemler.eksik_giderler_haric_kar", "74.17"),  # 291,67 - 120 - 52,50 - 45
        ("satir", 1, "karsilastirma.fark", "0.00"),
        ("satir", 1, "uyarilar", {"HIZMET_BEDELI_TAHMINI_EKSIK"}),
        ("donem", None, "donem_net_kar", None), ("donem", None, "net_kar_marji_yuzde", None),
        ("donem", None, "tam_satirlar.net_kar", "119.09"),
        ("donem", None, "donem_eksik_giderler_haric_kar", "193.26"),  # 119,09 + 74,17
        ("donem", None, "kesinlik_satir_sayilari", {"kesin": 1, "tahmini": 0, "eksik": 1}),
    ],
    "G49": [
        ("satir", 0, "kalemler.eksik_giderler_haric_kar", "174.09"),  # 416,58 - 180,00 - 62,49
        ("satir", 0, "kalemler.net_kar", None),
        ("satir", 0, "eksik_kalemler", ["kargo_gonderi", "platform_hizmet_bedeli"]),
        ("donem", None, "donem_duzeyi_giderler.siniflandirilmamis_kesinti", "17.35"),
        ("donem", None, "donem_duzeyi_giderler_toplami", "17.35"),
        ("donem", None, "satir_net_kar_toplami", None),
        ("donem", None, "donem_net_kar", None),  # v0.2 kuralı: 0,00 - 17,35 = -17,35
        ("donem", None, "donem_eksik_giderler_haric_kar", "156.74"),  # 174,09 - 17,35
        ("donem", None, "net_kar_kismi", True), ("donem", None, "net_kar_marji_yuzde", None),
        ("donem", None, "tam_satirlar.satir_sayisi", 0), ("donem", None, "tam_satirlar.net_satis_kdv_haric", "0.00"),
        ("donem", None, "tam_satirlar.toplam_gider", "0.00"), ("donem", None, "tam_satirlar.net_kar", "0.00"),
        ("donem", None, "tam_satirlar.net_kar_marji_yuzde", None),
        ("donem", None, "kesinlik", "eksik"),
        ("donem", None, "uyarilar", {"SINIFLANDIRILMAMIS_KESINTI", "KARGO_EKSIK_SATIRLAR_VAR",
                                     "HIZMET_BEDELI_EKSIK_SATIRLAR_VAR"}),
    ],
}

# G01-G41: eski çıktıdan değişmesine izin verilen alanlar (gerekçe docs/12 §12 K39 ve K39 Revizyon 1).
IZINLI_FARKLAR = {
    ("G29", "donem_toplami.net_kar_marji_yuzde"),  # 19,60 (138,80 / 708,25 karışık taban) -> null (kısmi dönem)
    ("G29", "donem_toplami.satir_net_kar_toplami"),  # 138,80 (yalnız A satırı) -> null (K39 Revizyon 1)
    ("G29", "donem_toplami.donem_net_kar"),  # 138,80 (yalnız A satırı) -> null (K39 Revizyon 1, AO-03)
}


# --------------------------------------------------------------------------- doğrulama yardımcıları
def al(obj, yol: str):
    for parca in yol.split("."):
        obj = obj[parca]
    return obj


def farklar(eski_, yeni_, yol=""):
    """Eski çıktıdaki her alan yenide aynı mı (yeni ek alanlar serbest)."""
    out = []
    if isinstance(eski_, dict):
        for k, v in eski_.items():
            if not isinstance(yeni_, dict) or k not in yeni_:
                out.append((f"{yol}.{k}".lstrip("."), v, "<yok>"))
            else:
                out += farklar(v, yeni_[k], f"{yol}.{k}")
    elif isinstance(eski_, list) and yol.endswith("uyarilar"):
        if set(eski_) != set(yeni_):
            out.append((yol.lstrip("."), eski_, yeni_))
    elif isinstance(eski_, list):
        if not isinstance(yeni_, list) or len(eski_) != len(yeni_):
            out.append((yol.lstrip("."), eski_, yeni_))
        else:
            for i, (a, b) in enumerate(zip(eski_, yeni_)):
                out += farklar(a, b, f"{yol}[{i}]")
    elif eski_ != yeni_:
        out.append((yol.lstrip("."), eski_, yeni_))
    return out


def degismezler(sid: str, b: dict) -> list[str]:
    """K37, K39, K40 özdeşlikleri."""
    hata = []
    for i, x in enumerate(b["siparis_satirlari"]):
        k = x["kalemler"]
        if x["durum"] == "cancelled":
            continue
        if (k["net_kar"] is None) != bool(x["eksik_kalemler"]):
            hata.append(f"{sid} satir {i}: net_kar null <-> eksik_kalemler")
        if k["net_kar"] is not None:
            if d(k["net_satis_kdv_haric"]) - d(k["toplam_gider"]) != d(k["net_kar"]):
                hata.append(f"{sid} satir {i}: net_satis - toplam_gider != net_kar")
            if k["eksik_giderler_haric_kar"] != k["net_kar"]:
                hata.append(f"{sid} satir {i}: tam satırda eksik_giderler_haric_kar != net_kar")
        for kalem in x["eksik_kalemler"]:
            if x["kaynaklar"][kalem] != "eksik":
                hata.append(f"{sid} satir {i}: {kalem} eksik listede ama kaynak {x['kaynaklar'][kalem]}")
        if (x["kesinlik"] == "eksik") != bool(x["eksik_kalemler"]):
            hata.append(f"{sid} satir {i}: kesinlik eksik <-> eksik_kalemler")
        if x["kesinlik"] == "kesin" and (x["durum"] == "estimated" or
                                         set(x["kaynaklar"].values()) - KESIN_KAYNAKLAR):
            hata.append(f"{sid} satir {i}: kesin etiketli satırda tahmini kaynak")
        kars = x["karsilastirma"]
        if kars:  # K38: tanımsız tahminli kalem iki toplama da girmez
            tah, kes = d(kars["komisyon_tahmini"]), d(kars["komisyon_kesin"])
            for t_, k_ in (("kargo_gonderi_tahmini", "kargo_gonderi_kesin"),
                           ("platform_hizmet_bedeli_tahmini", "platform_hizmet_bedeli_kesin")):
                if kars[t_] is not None and kars[k_] is not None:
                    tah, kes = tah + d(kars[t_]), kes + d(kars[k_])
            if (tah, kes) != (d(kars["karsilastirilan_tahmini_toplam"]), d(kars["karsilastirilan_kesin_toplam"])):
                hata.append(f"{sid} satir {i}: karşılaştırma toplamı K38'e aykırı")
    t = b["donem_toplami"]
    tam = t["tam_satirlar"]
    gider = sum(d(tam[k]) for k in ("urun_maliyeti", "komisyon", "kargo_gonderi", "kargo_iade",
                                    "platform_hizmet_bedeli", "ceza", "reklam", "degisken_giderler"))
    if gider != d(tam["toplam_gider"]):
        hata.append(f"{sid}: tam_satirlar gider alanları toplamı != toplam_gider")
    if d(tam["net_satis_kdv_haric"]) - d(tam["toplam_gider"]) != d(tam["net_kar"]):  # I2
        hata.append(f"{sid}: tam_satirlar net_satis - toplam_gider != net_kar")
    ddg = sum(d(v) for v in t["donem_duzeyi_giderler"].values())
    if ddg != d(t["donem_duzeyi_giderler_toplami"]):  # I3
        hata.append(f"{sid}: dönem düzeyi gider toplamı")
    if t["net_kar_kismi"] != (tam["satir_sayisi"] != t["satir_sayisi"]):
        hata.append(f"{sid}: net_kar_kismi tanımı")
    if t["net_kar_kismi"]:  # K39 Revizyon 1: kısmi dönemde bayraklı sayı yok
        for alan in ("satir_net_kar_toplami", "donem_net_kar", "net_kar_marji_yuzde"):
            if t[alan] is not None:
                hata.append(f"{sid}: kısmi dönemde {alan} null olmalı")
    else:
        if tam["net_kar"] != t["satir_net_kar_toplami"]:  # I2 (tam dönem)
            hata.append(f"{sid}: tam_satirlar.net_kar != satir_net_kar_toplami")
        if d(t["satir_net_kar_toplami"]) - ddg != d(t["donem_net_kar"]):  # I3 (tam dönem)
            hata.append(f"{sid}: satır net kâr - dönem düzeyi gider != donem_net_kar")
        if t["donem_eksik_giderler_haric_kar"] != t["donem_net_kar"]:  # I5 (tam dönem)
            hata.append(f"{sid}: tam dönemde donem_eksik_giderler_haric_kar != donem_net_kar")
    aktif_satirlar = [x for x in b["siparis_satirlari"] if x["durum"] != "cancelled"]
    haric = sum((d(x["kalemler"]["eksik_giderler_haric_kar"]) for x in aktif_satirlar), D(0)) - ddg
    if haric != d(t["donem_eksik_giderler_haric_kar"]):  # I5
        hata.append(f"{sid}: Σ satır eksik_giderler_haric_kar - dönem gideri != donem_eksik_giderler_haric_kar")
    urun_haric = sum((d(p["eksik_giderler_haric_kar"]) for p in b["urun_toplamlari"]), D(0))
    satissiz = d(t["donem_duzeyi_giderler"]["reklam_satissiz_urunler"])
    if urun_haric - (ddg - satissiz) != d(t["donem_eksik_giderler_haric_kar"]):  # I6
        hata.append(f"{sid}: Σ ürün eksik_giderler_haric_kar - (dönem gideri - satışsız reklam) != dönem alanı")
    if not t["net_kar_kismi"]:
        tum = sum(d(t[k]) for k in ("urun_maliyeti", "komisyon", "kargo_gonderi", "kargo_iade",
                                    "platform_hizmet_bedeli", "ceza_satirlara_dagitilan",
                                    "reklam_satirlara_dagitilan", "degisken_giderler"))
        if d(t["net_satis_kdv_haric"]) - tum - ddg != d(t["donem_net_kar"]):
            hata.append(f"{sid}: tam dönemde gider alanları net kârı vermiyor")
    for p in b["urun_toplamlari"]:
        if p["net_kar"] is None and p["satir_sayisi"] and not any(p["eksik_kalem_satir_sayilari"].values()):
            hata.append(f"{sid} ürün {p['barcode']}: net_kar null ama eksik kalem yok")
    return hata


def elle_kontrol(sid: str, b: dict) -> list[str]:
    hata = []
    for bolum, idx, yol, beklenen in ELLE.get(sid, []):
        kok = {"satir": b["siparis_satirlari"], "urun": b["urun_toplamlari"]}.get(bolum)
        obj = b["donem_toplami"] if bolum == "donem" else kok[idx]
        gercek = al(obj, yol)
        if isinstance(beklenen, set):
            gercek = set(gercek)
        if gercek != beklenen:
            hata.append(f"{sid} {bolum}[{idx}].{yol}: elle {beklenen!r}, betik {gercek!r}")
    return hata


def ayarsiz(girdi_tam: dict) -> dict:
    """Denetim S4 Y-02: aynı girdi, üretim varsayılanı ayarla (kullanıcı ayarı yok)."""
    g = copy.deepcopy(girdi_tam)
    g["ayarlar"] = copy.deepcopy(URETIM_AYARLARI)
    return g


# --------------------------------------------------------------------------- ana akış
def main() -> int:
    yaz = "--yaz" in sys.argv[1:]
    hatalar: list[str] = []
    belgeler = []

    # 1-2. G01-G41: diskle eşlik ve gerileme
    izinli_gorulen = set()
    degisen_ozet = []
    y02 = {"satir": 0, "eksik_satir": 0, "null_net": 0, "yanlis_bk": 0, "eski_yanlis_bk": 0,
           "kismi_donem": 0, "kismi_donem_sayi_net": 0}
    for sid, ad, aciklama, kurallar, etiketler, fn in eski.SENARYOLAR:
        girdi = fn()
        girdi.setdefault("donem", {"baslangic": "2026-10-01", "bitis": "2026-10-31"})
        girdi_tam = {"ayarlar": tam_ayarlar(girdi), **{k: v for k, v in girdi.items() if k != "ayarlar"}}
        eski_beklenen = eski.hesapla(girdi)
        yol = CIKTI / f"{sid}_{ad}.json"
        disk = json.loads(yol.read_text(encoding="utf-8"))
        eski_girdi = {"ayarlar": birlestir(eski.VARSAYILAN_AYARLAR, girdi.get("ayarlar", {})),
                      **{k: v for k, v in girdi.items() if k != "ayarlar"}}
        # Disk G01-G41 ya eski üretimdir ya da bu betiğin --yaz çıktısıdır: girdi (yeni anahtar hariç) aynı,
        # beklenen eski çıktıyı kapsar (eski alanlar aynı, izinli farklar hariç).
        disk_girdi = copy.deepcopy(disk["girdi"])
        disk_girdi["ayarlar"].pop("varsayilan_desi", None)
        if disk_girdi != json.loads(json.dumps(eski_girdi)):
            hatalar.append(f"{sid}: diskteki girdi eski betikle üretilenden farklı")
        for alan, _a, _b in farklar(json.loads(json.dumps(eski_beklenen)), disk["beklenen"]):
            if (sid, alan) not in IZINLI_FARKLAR:
                hatalar.append(f"{sid}: diskteki beklenen eski betikten farklı: {alan}")
        yeni = json.loads(json.dumps(hesapla2(girdi_tam)))
        for alan, a, b in farklar(json.loads(json.dumps(eski_beklenen)), yeni):
            if (sid, alan) in IZINLI_FARKLAR:
                izinli_gorulen.add((sid, alan))
                degisen_ozet.append(f"{sid} {alan}: {a!r} -> {b!r} (izinli)")
            else:
                hatalar.append(f"{sid} gerileme {alan}: eski {a!r}, yeni {b!r}")
        hatalar += degismezler(sid, yeni)
        # 5. Y-02 tekrarı: ayarsız
        uretim = json.loads(json.dumps(hesapla2(ayarsiz(girdi_tam))))
        eski_uretim = json.loads(json.dumps(eski_ayarsiz_hesapla(girdi_tam)))
        hatalar += degismezler(sid + "/ayarsiz", uretim)
        if uretim["donem_toplami"]["net_kar_kismi"]:
            y02["kismi_donem"] += 1
            if uretim["donem_toplami"]["donem_net_kar"] is not None:
                y02["kismi_donem_sayi_net"] += 1
                hatalar.append(f"{sid}/ayarsiz: kısmi dönemde dönem net kârı sayı (AO-03)")
        for x, xa, xe in zip(uretim["siparis_satirlari"], yeni["siparis_satirlari"], eski_uretim["siparis_satirlari"]):
            if x["durum"] == "cancelled":
                continue
            y02["satir"] += 1
            if x["eksik_kalemler"]:
                y02["eksik_satir"] += 1
            if x["kalemler"]["net_kar"] is None:
                y02["null_net"] += 1
            if "BEKLENMEYEN_KESINTI" in x["uyarilar"] and "BEKLENMEYEN_KESINTI" not in xa["uyarilar"]:
                y02["yanlis_bk"] += 1
                hatalar.append(f"{sid}/ayarsiz: altın sonuçta olmayan BEKLENMEYEN_KESINTI")
            if "BEKLENMEYEN_KESINTI" in xe["uyarilar"] and "BEKLENMEYEN_KESINTI" not in xa["uyarilar"]:
                y02["eski_yanlis_bk"] += 1
        belgeler.append((sid, ad, aciklama, kurallar, etiketler, girdi_tam, yeni))
    for izinli in IZINLI_FARKLAR - izinli_gorulen:
        hatalar.append(f"izinli fark görülmedi (liste güncel değil): {izinli}")

    # 3-4. G42-G49
    for sid, ad, aciklama, kurallar, etiketler, fn in YENI:
        girdi = fn()
        girdi.setdefault("donem", {"baslangic": "2026-10-01", "bitis": "2026-10-31"})
        girdi_tam = {"ayarlar": tam_ayarlar(girdi),
                     **{k: v for k, v in girdi.items() if k not in ("ayarlar", "ayarlar_tam")}}
        yeni = json.loads(json.dumps(hesapla2(girdi_tam)))
        hatalar += elle_kontrol(sid, yeni)
        hatalar += degismezler(sid, yeni)
        belgeler.append((sid, ad, aciklama, kurallar, etiketler, girdi_tam, yeni))

    # rapor
    print("== G01-G41 gerileme: eski kural çıktısındaki her alan yenide aynı (izinli farklar hariç)")
    for satir_ in degisen_ozet:
        print("   ", satir_)
    print("== Y-02 tekrarı (G01-G41 ayarsız):", y02)
    print("== G42-G49 özet (durum, kesinlik, net_kar, eksik_giderler_haric_kar, uyarılar)")
    for sid, ad, *_r, b in belgeler[len(eski.SENARYOLAR):]:
        print(sid, ad, "| dönem net", b["donem_toplami"]["donem_net_kar"], "eksik giderler hariç",
              b["donem_toplami"]["donem_eksik_giderler_haric_kar"], "kısmi",
              b["donem_toplami"]["net_kar_kismi"], "marj", b["donem_toplami"]["net_kar_marji_yuzde"])
        for x in b["siparis_satirlari"]:
            print("    ", x["durum"], x["kesinlik"], x["kalemler"]["net_kar"],
                  x["kalemler"]["eksik_giderler_haric_kar"], sorted(x["uyarilar"]))
    n_elle = sum(len(v) for v in ELLE.values())
    print(f"== elle kontrol edilen değer: {n_elle}; senaryo: {len(belgeler)}")
    if hatalar:
        print("HATA:", len(hatalar))
        for h in hatalar:
            print("   ", h)
        return 1
    print("TAMAM: tüm kontroller geçti")

    if yaz:
        for sid, ad, aciklama, kurallar, etiketler, girdi_tam, beklenen in belgeler:
            doc = {"senaryo_id": sid, "ad": ad, "aciklama": aciklama, "kurallar": kurallar, "etiketler": etiketler,
                   "sema_surumu": "1",
                   "not": "Tutarlar kurgusaldır. 'netkar_' önekli alanlar NetKâr ingest katmanınındır, "
                          "Trendyol alanı değildir.",
                   "girdi": girdi_tam, "beklenen": beklenen}
            (CIKTI / f"{sid}_{ad}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
        print(len(belgeler), "senaryo yazıldı ->", CIKTI)
    return 0


def eski_ayarsiz_hesapla(girdi_tam: dict) -> dict:
    """Eski kuralların (K01-K32) ayarsız davranışı: tarife boş, hizmet bedeli 0 (denetimdeki ProfitSettings()).

    `eski.hesapla` ayarları modül düzeyi VARSAYILAN_AYARLAR ile birleştirir ve boş sözlük birleştirmede
    tarifeyi boşaltmaz; bu yüzden çağrı süresince varsayılan geçici olarak ayarsız sürümle değiştirilir.
    """
    g = copy.deepcopy(girdi_tam)
    g["ayarlar"] = {}
    orig = eski.VARSAYILAN_AYARLAR
    eski.VARSAYILAN_AYARLAR = {**copy.deepcopy(orig), "kargo_tarifesi": {}, "satici_kargo_tarifesi": {},
                               "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric": "0"}
    try:
        return eski.hesapla(g)
    finally:
        eski.VARSAYILAN_AYARLAR = orig


if __name__ == "__main__":
    sys.exit(main())
