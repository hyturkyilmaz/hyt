# -*- coding: utf-8 -*-
"""NetKâr kâr motoru altın test senaryolarını üreten referans hesap betiği.

Amaç: docs/12_kar_motoru.md içindeki kuralların (K01..K31) Decimal ile elle
hesaplanmış karşılığını üretmek ve services/api/tests/golden/*.json dosyalarına
yazmak. Bu dosya üretim motoru DEĞİLDİR; motorun çıktısını karşılaştırmak için
beklenen değerleri yeniden üretilebilir kılan bir hesap tablosudur.

Çalıştırma: bu betik artık TEK BAŞINA ÇALIŞTIRILMAZ (G42-G48'i silerdi); doğrudan çalıştırılırsa
altin_test_hesap_ayarlar.py'ye yönlendirilir. Dosyaları üretmek için:
    python3 netkar/calisma_dosyalari/altin_test_hesap_ayarlar.py --yaz

Kurallar:
- Tüm tutarlar Decimal; girdi string olarak okunur (float yok).
- Kuruşa yuvarlama ROUND_HALF_UP (negatiflerde sıfırdan uzağa), kalem sonunda bir kez (K01).
- Dağıtımlar en büyük kalan yöntemiyle kuruşu kuruşuna toplamı korur (K24).
- Alan adları Trendyol doküman kopyalarından alınmıştır; "netkar_" önekli alanlar
  NetKâr'ın kendi ingest/eşleme katmanının ürettiği alanlardır (Trendyol alanı değil).
- Tüm tutarlar kurgusaldır (gerçek satıcı verisi değildir).
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
CIKTI = KOK / "services" / "api" / "tests" / "golden"
TR = timezone(timedelta(hours=3))  # Europe/Istanbul, 2016'dan beri sabit UTC+3

KURUS = D("0.01")
YUZ = D("100")


# --------------------------------------------------------------------------- yardımcılar
def d(x) -> D:
    if x is None:
        return None
    if isinstance(x, D):
        return x
    if isinstance(x, float):
        raise TypeError("float kullanılmaz: " + repr(x))
    return D(str(x))


def rnd(x: D) -> D:
    """K01: kuruşa ROUND_HALF_UP (Decimal HALF_UP negatifte sıfırdan uzağa yuvarlar)."""
    return d(x).quantize(KURUS, rounding=ROUND_HALF_UP)


def s(x) -> str | None:
    """Çıktı biçimi: kuruş hassasiyetinde string."""
    if x is None:
        return None
    v = rnd(x)
    if v == 0:
        v = D("0.00")  # -0.00 yazma
    return format(v, "f")


def yuzde(pay: D, payda: D) -> str | None:
    if payda is None or pay is None or payda == 0:
        return None
    return s(pay / payda * YUZ)


def oran2(pay, payda) -> str | None:
    if payda is None or pay is None or payda == 0:
        return None
    return s(d(pay) / d(payda))


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def tarih(ms_: int) -> str:
    return datetime.fromtimestamp(ms_ / 1000, TR).date().isoformat()


def dahil_ayir(dahil_exact: D, oran_yuzde: D):
    """K02: KDV dahil tutardan (hariç, kdv). hariç = rnd(dahil/(1+r)), kdv = rnd(dahil) - hariç."""
    dahil_exact = d(dahil_exact)
    haric = rnd(dahil_exact / (1 + d(oran_yuzde) / YUZ))
    kdv = rnd(dahil_exact) - haric
    return haric, kdv


def haric_kdv(haric_exact: D, oran_yuzde: D):
    """K02: KDV hariç tutardan (hariç, kdv). kdv = rnd(hariç_exact * r)."""
    haric_exact = d(haric_exact)
    return rnd(haric_exact), rnd(haric_exact * d(oran_yuzde) / YUZ)


def dagit(toplam: D, agirliklar: list[D]) -> list[D]:
    """K24: kuruş cinsinden en büyük kalan dağıtımı. Toplam korunur.
    Ağırlıkların hepsi 0 ise eşit ağırlık. Eşit kalanlarda listedeki ilk öğe önce alır."""
    toplam = rnd(toplam)
    n = len(agirliklar)
    if n == 0:
        return []
    w = [max(d(a), D(0)) for a in agirliklar]
    if sum(w) == 0:
        w = [D(1)] * n
    isaret = -1 if toplam < 0 else 1
    kurus = int((abs(toplam) * 100).to_integral_value())
    W = sum(w)
    ham = [D(kurus) * x / W for x in w]
    taban = [int(math.floor(h)) for h in ham]
    kalan = kurus - sum(taban)
    sira = sorted(range(n), key=lambda i: (-(ham[i] - taban[i]), i))
    for i in sira[:kalan]:
        taban[i] += 1
    return [D(isaret * t) / 100 for t in taban]


# --------------------------------------------------------------------------- varsayılan ayarlar
VARSAYILAN_AYARLAR = {
    "komisyon_tutari_kdv_dahil": True,          # K07 (teyit gerekir)
    "komisyon_kdv_orani": "20",
    "kargo_kdv_orani": "20",
    "hizmet_bedeli_kdv_orani": "20",
    "reklam_kdv_orani": "20",
    "stopaj_orani": "1",                        # K18, 9284 s. CBK
    "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric": "10.00",  # K13, kullanıcı ayarı (kurgusal)
    "kargo_tarifesi": {                         # K08, tahmini kargo (kurgusal, KDV hariç)
        "Trendyol Express": [["1", "40.00"], ["2", "45.00"], ["3", "50.00"], ["5", "60.00"],
                             ["10", "85.00"], ["15", "110.00"]],
    },
    "satici_kargo_tarifesi": {                  # whoPays=1 (satıcı anlaşması), kullanıcı girer
        "Aras Kargo Marketplace": [["2", "38.00"], ["5", "52.00"], ["10", "75.00"]],
    },
    "kargo_faturasi_kdv_tespit_toleransi": "0.05",
    "uyari_esikleri": {
        "beklenmeyen_kesinti_tutar": "5.00",
        "beklenmeyen_kesinti_oran_yuzde": "5",
        "yuvarlama_toleransi": "0.05",
        "komisyon_orani_tolerans_puan": "0.01",
    },
    "degisken_giderler": [],
}

SATIS_TIPLERI = {"Sale", "PayByLink", "Discount", "DiscountCancel", "Coupon", "CouponCancel",
                 "ProvisionPositive", "ProvisionNegative"}
IADE_TIPLERI = {"Return", "ManualRefund", "ManualRefundCancel"}
DUZELTME_TIPLERI = {"SellerRevenuePositive", "SellerRevenueNegative", "CommissionPositive",
                    "CommissionNegative", "SellerRevenuePositiveCancel", "SellerRevenueNegativeCancel",
                    "CommissionPositiveCancel", "CommissionNegativeCancel"}
# K05: komisyon için NetKâr maliyet işareti (+1: satıcıya komisyon yazıldı, -1: geri verildi)
KOMISYON_ISARETI = {
    "Sale": 1, "PayByLink": 1, "DiscountCancel": 1, "CouponCancel": 1, "ProvisionPositive": 1,
    "ManualRefundCancel": 1, "CommissionPositive": 1, "CommissionNegativeCancel": 1, "DeliveryFee": 1,
    "Return": -1, "Discount": -1, "Coupon": -1, "ProvisionNegative": -1, "ManualRefund": -1,
    "CommissionNegative": -1, "CommissionPositiveCancel": -1, "DeliveryFeeCancel": -1,
    "SellerRevenuePositive": 0, "SellerRevenueNegative": 0, "SellerRevenuePositiveCancel": 0,
    "SellerRevenueNegativeCancel": 0,
}
TR_METIN = {
    "Sale": "Satış", "Return": "İade", "Discount": "İndirim", "DiscountCancel": "İndirim İptal",
    "Coupon": "Kupon", "CouponCancel": "Kupon İptal", "ManualRefund": "Kısmi İade",
    "ManualRefundCancel": "Kısmi İade İptal", "CommissionPositive": "Komisyon Pozitif Düzeltme",
    "CommissionNegative": "Komisyon Negatif Düzeltme",
}


def birlestir(ana: dict, ek: dict) -> dict:
    out = copy.deepcopy(ana)
    for k, v in (ek or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = birlestir(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def tarife_bul(tarife: dict, firma: str, desi) -> D | None:
    basamaklar = tarife.get(firma)
    if not basamaklar or desi is None:
        return None
    desi = d(desi)
    for ust, tutar in basamaklar:
        if desi <= d(ust):
            return d(tutar)
    return None


# --------------------------------------------------------------------------- hesap
def hesapla(g: dict) -> dict:
    ay = birlestir(VARSAYILAN_AYARLAR, g.get("ayarlar", {}))
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

    satirlar = []  # iç durum
    for o in g["siparisler"]:
        for ln in o["lines"]:
            satirlar.append({"o": o, "ln": ln})

    # ---- A. satış, iade, komisyon, maliyet (satır bazlı)
    for S in satirlar:
        o, ln = S["o"], S["ln"]
        r = d(ln["vatRate"])
        q = int(ln["quantity"])
        items = ln["discountDetails"]
        assert len(items) == q, "discountDetails adet sayısına eşit olmalı"
        brut = d(ln["lineGrossAmount"]) * q
        sind = sum((d(i["lineItemSellerDiscount"]) for i in items), D(0))
        tind = sum((d(i["lineItemTyDiscount"]) for i in items), D(0))
        S.update(r=r, q=q, brut=brut, sind=sind, tind=tind, uyarilar=[], bayraklar=[], kaynak={})
        S["iptal"] = o.get("status") in ("Cancelled", "UnSupplied")
        S["item_ids"] = {str(i["lineItemId"]) for i in items}
        # K27 eşleştirme
        rows = [x for x in settlements
                if x["orderNumber"] == o["orderNumber"] and x["barcode"] == ln["barcode"]
                and (x.get("shipmentPackageId") in (None, o["shipmentPackageId"]))]
        S["rows"] = rows
        tipler = {x["netkar_istek_tipi"] for x in rows}
        S["has_sale"] = bool(tipler & {"Sale", "PayByLink"})
        S["duzeltme_var"] = bool(tipler & (IADE_TIPLERI | DUZELTME_TIPLERI))

        # tahmini değerler (karşılaştırma için her zaman)
        satis_tahmini_dahil = brut - sind
        kom_tahmini_exact = satis_tahmini_dahil * d(ln["commission"]) / YUZ
        S["kom_tahmini_exact"] = kom_tahmini_exact

        if S["iptal"]:
            satis_dahil = iade_dahil = kom_exact = kom_satis_exact = D(0)
        elif S["has_sale"]:
            satis_dahil = sum((d(x["credit"]) - d(x["debt"]) for x in rows
                               if x["netkar_istek_tipi"] in SATIS_TIPLERI), D(0))
            iade_dahil = sum((d(x["debt"]) - d(x["credit"]) for x in rows
                              if x["netkar_istek_tipi"] in IADE_TIPLERI), D(0))
            kom_exact = sum((KOMISYON_ISARETI[x["netkar_istek_tipi"]] * abs(d(x["commissionAmount"] or 0))
                             for x in rows), D(0))
            # karşılaştırmaya giren kesin komisyon: iade ters kayıtları hariç, düzeltmeler dahil (K23)
            kom_satis_exact = sum((KOMISYON_ISARETI[x["netkar_istek_tipi"]] * abs(d(x["commissionAmount"] or 0))
                                   for x in rows if x["netkar_istek_tipi"] not in IADE_TIPLERI), D(0))
            # K05: hakediş düzeltmeleri komisyon düzeltmeleriyle eşleşir; eşleşmeyen kalan gelir düzeltmesidir
            kom_duz = sum((KOMISYON_ISARETI[x["netkar_istek_tipi"]] * abs(d(x["commissionAmount"] or 0))
                           for x in rows if x["netkar_istek_tipi"].startswith("Commission")), D(0))
            hak_duz = sum((d(x["credit"]) - d(x["debt"]) for x in rows
                           if x["netkar_istek_tipi"].startswith("SellerRevenue")), D(0))
            artik = hak_duz + kom_duz
            if artik != 0:
                satis_dahil += artik
                S["uyarilar"].append("ESLESMEMIS_HAKEDIS_DUZELTMESI")
            # K28 iç tutarlılık (yalnız satış ve iade tipleri; düzeltme tiplerinde sellerRevenue 0 olabilir)
            for x in rows:
                if x["netkar_istek_tipi"] not in (SATIS_TIPLERI | IADE_TIPLERI):
                    continue
                isr = KOMISYON_ISARETI[x["netkar_istek_tipi"]]
                beklenen_sr = (d(x["credit"]) - d(x["debt"])) - isr * abs(d(x["commissionAmount"] or 0))
                if x.get("sellerRevenue") is not None and abs(abs(d(x["sellerRevenue"])) - abs(beklenen_sr)) > D("0.01"):
                    S["uyarilar"].append("EKSTRE_IC_TUTARSIZLIK")
            # K23 komisyon oranı farkı
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
            if ay["komisyon_tutari_kdv_dahil"]:
                h, k = dahil_ayir(exact, kom_kdv_o)
            else:
                h, k = haric_kdv(exact, kom_kdv_o)
            return h, k
        S["kom_haric"], S["kom_kdv"] = kom_ayir(kom_exact)
        S["kom_tahmini_haric"], _ = kom_ayir(kom_tahmini_exact)
        S["kom_kesin_satis_haric"], _ = kom_ayir(kom_satis_exact)

        # iade adetleri (claims, K10)
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

        # K16 ürün maliyeti
        gun = tarih(o["orderDate"])
        adaylar = [m for m in maliyetler if m["barcode"] == ln["barcode"] and m["gecerlilik_baslangic"] <= gun]
        adaylar.sort(key=lambda m: m["gecerlilik_baslangic"])
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
            S["maliyet_haric"], S["maliyet_kdv"] = haric_kdv(d(m["birim_maliyet_kdv_haric"]) * adet, d(m["kdv_orani"]))
            S["kaynak"]["urun_maliyeti"] = "kullanici"
            S["maliyet_gecerlilik"] = m["gecerlilik_baslangic"]

        for k in ("kargo_g_h", "kargo_g_k", "kargo_i_h", "kargo_i_k", "hiz_h", "hiz_k", "ceza_h", "ceza_k",
                  "rek_h", "rek_k", "deg_h", "deg_k", "kargo_g_tahmini_h", "hiz_tahmini_h"):
            S[k] = D(0)
        S["kargo_g_kesin_var"] = False
        S["hiz_kesin_var"] = False
        S["degisken_detay"] = []
        S["reklam_detay"] = []

    # sipariş grupları (paket)
    paketler = {}
    for S in satirlar:
        paketler.setdefault(S["o"]["shipmentPackageId"], []).append(S)

    def agirlik_satis(grup):
        return [S["satis_haric"] for S in grup]

    # ---- B. kargo (K08, K09, K12)
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

    def kargo_kalemleri(order_no, tip):
        out = []
        for f in kargo_faturalari:
            durum = fatura_kdv_durumu(f)
            for i in f["items"]:
                if i["orderNumber"] == order_no and i["shipmentPackageType"] == tip:
                    out.append((i, durum))
        return out

    kargo_kdv_durumlari = {}
    for f in kargo_faturalari:
        kargo_kdv_durumlari[str(f["invoiceSerialNumber"])] = fatura_kdv_durumu(f)

    def kalem_toplam(kalemler):
        dahil_exact = D(0)
        haric_exact = D(0)
        belirsiz = False
        for i, durum in kalemler:
            if durum == "dahil":
                dahil_exact += d(i["amount"])
            else:
                if durum == "bilinmiyor":
                    belirsiz = True
                haric_exact += d(i["amount"])
        h1, k1 = dahil_ayir(dahil_exact, kargo_kdv_o)
        h2, k2 = haric_kdv(haric_exact, kargo_kdv_o)
        return h1 + h2, k1 + k2, belirsiz

    for pid, grup in paketler.items():
        o = grup[0]["o"]
        aktif = [S for S in grup if not S["iptal"]]
        if not aktif:
            continue
        # ağırlık: tüm satırlarda netkar_urun_desi varsa desi*adet, yoksa satış hariç
        if all(S["ln"].get("netkar_urun_desi") is not None for S in aktif):
            w = [d(S["ln"]["netkar_urun_desi"]) * S["q"] for S in aktif]
        else:
            w = agirlik_satis(aktif)
        desi_tahmin = o.get("cargoDeci")
        if desi_tahmin is None and o.get("deci") is not None:
            desi_tahmin = math.ceil(float(o["deci"]))  # yalnız desi yuvarlama, para değil
        if o.get("whoPays") == 1:
            tah = tarife_bul(ay["satici_kargo_tarifesi"], o["cargoProviderName"], desi_tahmin)
            tah_kaynak = "kullanici"
        else:
            tah = tarife_bul(ay["kargo_tarifesi"], o["cargoProviderName"], desi_tahmin)
            tah_kaynak = "tahmini"
        kalemler = kargo_kalemleri(o["orderNumber"], "Gönderi Kargo Bedeli") if o.get("whoPays") != 1 else []
        if kalemler:
            h, k, belirsiz = kalem_toplam(kalemler)
            kaynak = "kesin"
            desi_kesin = sum(int(i["desi"]) for i, _ in kalemler)
            if desi_tahmin is not None and d(desi_kesin) != d(desi_tahmin):
                for S in aktif:
                    S["uyarilar"].append("KARGO_DESI_FARKI")
            if belirsiz:
                for S in aktif:
                    S["uyarilar"].append("KARGO_FATURASI_KDV_BELIRSIZ")
        elif tah is not None:
            h, k = haric_kdv(tah, kargo_kdv_o)
            kaynak = tah_kaynak
        else:
            h, k, kaynak = D(0), D(0), "eksik"
            for S in aktif:
                S["uyarilar"].append("KARGO_TARIFESI_EKSIK")
        for S, ph, pk in zip(aktif, dagit(h, w), dagit(k, w)):
            S["kargo_g_h"], S["kargo_g_k"] = ph, pk
            S["kaynak"]["kargo_gonderi"] = kaynak
            S["kargo_g_kesin_var"] = kaynak == "kesin"
        if tah is not None:
            th, _ = haric_kdv(tah, kargo_kdv_o)
            for S, ph in zip(aktif, dagit(th, w)):
                S["kargo_g_tahmini_h"] = ph
        # iade kargo (K12)
        ikal = kargo_kalemleri(o["orderNumber"], "İade Kargo Bedeli")
        if ikal:
            h, k, belirsiz = kalem_toplam(ikal)
            hedef = [S for S in aktif if S["adet_iade"] > 0 or S["iade_haric"] > 0] or aktif
            wi = [S["iade_haric"] if S["iade_haric"] > 0 else S["satis_haric"] for S in hedef]
            for S, ph, pk in zip(hedef, dagit(h, wi), dagit(k, wi)):
                S["kargo_i_h"], S["kargo_i_k"] = ph, pk
                S["kaynak"]["kargo_iade"] = "kesin"

    # ---- C. platform hizmet bedeli (K13)
    psf = [x for x in others if x.get("netkar_istek_tipi") == "DeductionInvoices"
           and x.get("netkar_istek_alt_tipi") == "PlatformServiceFee"]
    siparis_satirlari = {}
    for S in satirlar:
        siparis_satirlari.setdefault(S["o"]["orderNumber"], []).append(S)
    tahmini_psf = d(ay["platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric"])
    kapsanan = set()
    for x in psf:
        if x.get("orderNumber"):
            hedef_sip = [x["orderNumber"]]
        else:
            hedef_sip = sorted({S["o"]["orderNumber"] for S in satirlar if S["has_sale"] and not S["iptal"]
                                and any(rw.get("paymentOrderId") == x.get("paymentOrderId")
                                        for rw in S["rows"] if rw["netkar_istek_tipi"] == "Sale")},
                               key=lambda n: [S["o"]["orderNumber"] for S in satirlar].index(n))
        h, k = dahil_ayir(d(x["debt"]) - d(x["credit"]), hiz_kdv_o)
        sh = dagit(h, [D(1)] * len(hedef_sip))
        sk = dagit(k, [D(1)] * len(hedef_sip))
        for no, oh, ok in zip(hedef_sip, sh, sk):
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
        th, tk = haric_kdv(tahmini_psf, hiz_kdv_o)
        w = agirlik_satis(grup)
        for S, ph, pk in zip(grup, dagit(th, w), dagit(tk, w)):
            S["hiz_tahmini_h"] = ph
            if no not in kapsanan:
                S["hiz_h"], S["hiz_k"] = ph, pk
                S["kaynak"]["platform_hizmet_bedeli"] = "tahmini"

    # ---- D. ceza ve diğer sınıflandırılmış kesintiler (K14, K19)
    donem = {"dagitilmamis_ceza_kdv_haric": D(0), "erken_odeme_bedeli_kdv_haric": D(0),
             "siniflandirilmamis_kesinti": D(0), "reklam_dagitilamayan_kdv_haric": D(0),
             "stopaj_ekstre": D(0), "erken_odeme_nakit_girisi": D(0), "uyarilar": []}
    for x in others:
        tip = x.get("netkar_istek_tipi")
        sinif = x.get("netkar_sinif")
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

    # ---- E. değişken giderler (K17)
    for gid in ay["degisken_giderler"]:
        ko = d(gid.get("kdv_orani", "20"))
        if gid["tip"] == "siparis_basi":
            for no, grup0 in siparis_satirlari.items():
                grup = [S for S in grup0 if not S["iptal"]]
                if not grup:
                    continue
                h, k = haric_kdv(d(gid["tutar_kdv_haric"]), ko)
                w = agirlik_satis(grup)
                for S, ph, pk in zip(grup, dagit(h, w), dagit(k, w)):
                    S["deg_h"] += ph
                    S["deg_k"] += pk
                    S["degisken_detay"].append({"ad": gid["ad"], "tutar_kdv_haric": s(ph)})
        else:
            for S in satirlar:
                if S["iptal"]:
                    continue
                if gid["tip"] == "adet_basi":
                    h, k = haric_kdv(d(gid["tutar_kdv_haric"]) * S["q"], ko)
                elif gid["tip"] == "satis_yuzdesi":
                    h, k = haric_kdv(S["net_satis"] * d(gid["oran_yuzde"]) / YUZ, ko)
                else:
                    raise ValueError(gid["tip"])
                S["deg_h"] += h
                S["deg_k"] += k
                S["degisken_detay"].append({"ad": gid["ad"], "tutar_kdv_haric": s(h)})
    for S in satirlar:
        S["kaynak"]["degisken_giderler"] = "kullanici" if S["degisken_detay"] else "yok"

    # ---- F. reklam (K15)
    katalog = {S["ln"]["barcode"] for S in satirlar} | {m["barcode"] for m in maliyetler} | \
        {u["barcode"] for u in g.get("urunler", [])}
    urun_reklam_satissiz = {}
    urun_reklam_cirosu = {}
    for rk in g.get("reklam_kayitlari", []):
        h_exact = d(rk["harcama"])
        if rk.get("harcama_kdv_dahil"):
            h, _ = dahil_ayir(h_exact, rek_kdv_o)
        else:
            h = rnd(h_exact)
        k = rnd(h * rek_kdv_o / YUZ)
        donemde = [S for S in satirlar if not S["iptal"]
                   and rk["baslangic"] <= tarih(S["o"]["orderDate"]) <= rk["bitis"]]
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

    # ---- G. satır sonuçları
    cikti_satirlar = []
    for S in satirlar:
        o, ln = S["o"], S["ln"]
        giderler_maliyetsiz = (S["kom_haric"] + S["kargo_g_h"] + S["kargo_i_h"] + S["hiz_h"] + S["ceza_h"]
                               + S["rek_h"] + S["deg_h"])
        katki = S["net_satis"] - giderler_maliyetsiz
        if S["maliyet_haric"] is None:
            net_kar = None
            toplam_gider = None
        else:
            toplam_gider = giderler_maliyetsiz + S["maliyet_haric"]
            net_kar = S["net_satis"] - toplam_gider
        if net_kar is not None and net_kar < 0 and not S["iptal"]:
            S["uyarilar"].append("ZARAR")

        # durum (K22)
        siparis_ceza = S["ceza_h"] != 0
        if S["iptal"]:
            durum = "cancelled"
        elif not S["has_sale"]:
            durum = "estimated"
        elif S["duzeltme_var"] or S["kargo_i_h"] != 0 or siparis_ceza:
            durum = "adjusted"
        else:
            durum = "settled"

        # karşılaştırma (K23)
        kars = None
        if S["has_sale"] and not S["iptal"]:
            kom_t, kom_k = S["kom_tahmini_haric"], S["kom_kesin_satis_haric"]
            kar_t = S["kargo_g_tahmini_h"]
            kar_k = S["kargo_g_h"] if S["kargo_g_kesin_var"] else None
            hiz_t = S["hiz_tahmini_h"]
            hiz_k = S["hiz_h"] if S["hiz_kesin_var"] else None
            tahmin_top = kom_t + (kar_t if kar_k is not None else 0) + (hiz_t if hiz_k is not None else 0)
            kesin_top = kom_k + (kar_k or 0) + (hiz_k or 0)
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
        if o.get("whoPays") == 1:  # satıcı anlaşmalı kargo Trendyol hakedişinden düşülmez
            fatura_kesintileri -= S["kargo_g_h"] + S["kargo_g_k"]
        stopaj = rnd(S["net_satis"] * stopaj_o / YUZ)
        S["stopaj"] = stopaj

        uy = []
        for u in S["uyarilar"]:
            if u not in uy:
                uy.append(u)
        S["uyarilar"] = uy
        S["net_kar"] = net_kar
        S["katki"] = katki
        S["toplam_gider"] = toplam_gider
        S["durum"] = durum

        cikti_satirlar.append({
            "orderNumber": o["orderNumber"],
            "shipmentPackageId": o["shipmentPackageId"],
            "lineId": ln["lineId"],
            "barcode": ln["barcode"],
            "durum": durum,
            "adet": S["q"],
            "adet_iade": S["adet_iade"],
            "kalemler": {
                "brut_satis_kdv_dahil": s(S["brut"]),
                "satici_indirimi_kdv_dahil": s(S["sind"]),
                "trendyol_indirimi_kdv_dahil": s(S["tind"]),
                "satis_kdv_dahil": s(S["satis_dahil_exact"]),
                "satis_kdv_haric": s(S["satis_haric"]),
                "iade_kdv_dahil": s(S["iade_dahil_exact"]),
                "iade_kdv_haric": s(S["iade_haric"]),
                "net_satis_kdv_haric": s(S["net_satis"]),
                "urun_maliyeti": s(S["maliyet_haric"]),
                "komisyon": s(S["kom_haric"]),
                "kargo_gonderi": s(S["kargo_g_h"]),
                "kargo_iade": s(S["kargo_i_h"]),
                "platform_hizmet_bedeli": s(S["hiz_h"]),
                "ceza": s(S["ceza_h"]),
                "reklam": s(S["rek_h"]),
                "degisken_giderler": s(S["deg_h"]),
                "toplam_gider": s(toplam_gider),
                "maliyet_haric_katki": s(katki),
                "net_kar": s(net_kar),
                "net_kar_marji_yuzde": yuzde(net_kar, S["net_satis"]),
            },
            "kdv": {
                "satis_kdv": s(S["satis_kdv"]),
                "iade_kdv": s(S["iade_kdv"]),
                "komisyon_kdv": s(S["kom_kdv"]),
                "kargo_kdv": s(S["kargo_g_k"] + S["kargo_i_k"]),
                "platform_hizmet_bedeli_kdv": s(S["hiz_k"]),
                "ceza_kdv": s(S["ceza_k"]),
                "urun_maliyeti_kdv": s(S["maliyet_kdv"]),
                "degisken_giderler_kdv": s(S["deg_k"]),
                "reklam_kdv": s(S["rek_k"]),
                "kdv_etkisi": s(kdv_etkisi),
            },
            "nakit_akisi": {
                "trendyol_hakedis": s(hakedis),
                "fatura_kesintileri_kdv_dahil": s(fatura_kesintileri),
                "stopaj": s(stopaj),
                "beklenen_net_tahsilat": s(hakedis - fatura_kesintileri - stopaj),
            },
            "kaynaklar": S["kaynak"],
            "degisken_gider_detayi": S["degisken_detay"],
            "reklam_detayi": S["reklam_detay"],
            "karsilastirma": kars,
            "uyarilar": S["uyarilar"],
        })

    # ---- H. ürün toplamları (K25)
    urunler = {}
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
        top = lambda k: sum((S[k] for S in grup), D(0))
        satissiz = urun_reklam_satissiz.get(bk, D(0))
        maliyet_eksik = any(S["maliyet_haric"] is None for S in grup)
        net = None if maliyet_eksik else sum((S["net_kar"] for S in grup), D(0)) - satissiz
        katki = top("katki") - satissiz
        reklam_top = top("rek_h") + satissiz
        net_satis = top("net_satis")
        ciro = urun_reklam_cirosu.get(bk)
        reklam_oncesi = None if net is None else net + reklam_top
        cikti_urunler.append({
            "barcode": bk,
            "satir_sayisi": len(grup),
            "adet": sum(S["q"] for S in grup),
            "adet_iade": sum(S["adet_iade"] for S in grup),
            "net_satis_kdv_haric": s(net_satis),
            "urun_maliyeti": None if maliyet_eksik else s(top("maliyet_haric")),
            "komisyon": s(top("kom_haric")),
            "kargo_gonderi": s(top("kargo_g_h")),
            "kargo_iade": s(top("kargo_i_h")),
            "platform_hizmet_bedeli": s(top("hiz_h")),
            "ceza": s(top("ceza_h")),
            "reklam_satirlara_dagitilan": s(top("rek_h")),
            "reklam_satissiz": s(satissiz),
            "degisken_giderler": s(top("deg_h")),
            "maliyet_haric_katki": s(katki),
            "net_kar": s(net),
            "net_kar_marji_yuzde": yuzde(net, net_satis),
            "maliyet_eksik": maliyet_eksik,
            "reklam_harcamasi": s(reklam_top),
            "reklam_cirosu": s(ciro),
            "roas": oran2(ciro, reklam_top) if ciro is not None else None,
            "basabas_roas": (oran2(net_satis, reklam_oncesi)
                             if reklam_oncesi is not None and reklam_oncesi > 0 and reklam_top > 0 else None),
            "stopaj": s(top("stopaj")),
        })

    # ---- I. dönem toplamı (K25)
    aktif = [S for S in satirlar if not S["iptal"]]
    top = lambda k: sum((S[k] for S in aktif), D(0))
    satissiz_top = sum(urun_reklam_satissiz.values(), D(0))
    eksik = sum(1 for S in aktif if S["maliyet_haric"] is None)
    satir_net = sum((S["net_kar"] for S in aktif if S["net_kar"] is not None), D(0))
    donem_gider = (satissiz_top + donem["reklam_dagitilamayan_kdv_haric"] + donem["dagitilmamis_ceza_kdv_haric"]
                   + donem["erken_odeme_bedeli_kdv_haric"] + donem["siniflandirilmamis_kesinti"])
    stopaj_hes = top("stopaj")
    uyarilar = list(donem["uyarilar"])
    if eksik:
        uyarilar.append("MALIYET_EKSIK_SATIRLAR_VAR")
    if donem["stopaj_ekstre"] != 0 and abs(donem["stopaj_ekstre"] - stopaj_hes) > d("0.05"):
        uyarilar.append("STOPAJ_EKSTRE_FARKI")
    cikti_donem = {
        "siparis_sayisi": len({S["o"]["orderNumber"] for S in aktif}),
        "satir_sayisi": len(aktif),
        "net_satis_kdv_haric": s(top("net_satis")),
        "urun_maliyeti": s(sum((S["maliyet_haric"] for S in aktif if S["maliyet_haric"] is not None), D(0))),
        "komisyon": s(top("kom_haric")),
        "kargo_gonderi": s(top("kargo_g_h")),
        "kargo_iade": s(top("kargo_i_h")),
        "platform_hizmet_bedeli": s(top("hiz_h")),
        "ceza_satirlara_dagitilan": s(top("ceza_h")),
        "reklam_satirlara_dagitilan": s(top("rek_h")),
        "degisken_giderler": s(top("deg_h")),
        "satir_net_kar_toplami": s(satir_net),
        "donem_duzeyi_giderler": {
            "reklam_satissiz_urunler": s(satissiz_top),
            "reklam_dagitilamayan": s(donem["reklam_dagitilamayan_kdv_haric"]),
            "dagitilmamis_ceza": s(donem["dagitilmamis_ceza_kdv_haric"]),
            "erken_odeme_bedeli": s(donem["erken_odeme_bedeli_kdv_haric"]),
            "siniflandirilmamis_kesinti": s(donem["siniflandirilmamis_kesinti"]),
        },
        "donem_net_kar": s(satir_net - donem_gider),
        "net_kar_kismi": eksik > 0,
        "maliyet_eksik_satir_sayisi": eksik,
        "net_kar_marji_yuzde": yuzde(satir_net - donem_gider, top("net_satis")),
        "kdv_etkisi": None,
        "nakit_akisi": {
            "stopaj_hesaplanan": s(stopaj_hes),
            "stopaj_ekstre": s(donem["stopaj_ekstre"]),
            "erken_odeme_nakit_girisi": s(donem["erken_odeme_nakit_girisi"]),
        },
        "uyarilar": uyarilar,
    }
    cikti_donem["kdv_etkisi"] = s(sum((d(c["kdv"]["kdv_etkisi"]) for c in cikti_satirlar
                                       if c["durum"] != "cancelled"), D(0)))
    return {
        "siparis_satirlari": cikti_satirlar,
        "urun_toplamlari": cikti_urunler,
        "donem_toplami": cikti_donem,
        "kargo_faturasi_kdv_durumu": kargo_kdv_durumlari,
    }


# --------------------------------------------------------------------------- girdi kurucular
_sayac = {"line": 470000000, "item": 900000000, "fin": 725000000, "pkg": 3300000000}


def _yeni(k):
    _sayac[k] += 1
    return _sayac[k]


def satir(barcode, fiyat, kdv="20", komisyon="15", adet=1, satici_ind=None, ty_ind=None, desi=None):
    """Sipariş satırı. satici_ind/ty_ind: kalem başına liste ya da tek değer (her kaleme)."""
    fiyat = d(fiyat)
    def liste(v):
        if v is None:
            return [D(0)] * adet
        if isinstance(v, (list, tuple)):
            assert len(v) == adet
            return [d(x) for x in v]
        return [d(v)] * adet
    si, ti = liste(satici_ind), liste(ty_ind)
    detay = []
    for a, b in zip(si, ti):
        detay.append({"lineItemId": str(_yeni("item")), "lineItemPrice": s(fiyat - a - b),
                      "lineItemSellerDiscount": s(a), "lineItemTyDiscount": s(b)})
    ort_s = sum(si, D(0)) / adet
    ort_t = sum(ti, D(0)) / adet
    ln = {
        "lineId": _yeni("line"), "barcode": barcode, "quantity": adet,
        "lineGrossAmount": s(fiyat), "lineSellerDiscount": s(ort_s), "lineTyDiscount": s(ort_t),
        "lineTotalDiscount": s(ort_s + ort_t), "lineUnitPrice": s(fiyat - ort_s - ort_t),
        "vatRate": kdv, "commission": komisyon, "discountDetails": detay,
    }
    if desi is not None:
        ln["netkar_urun_desi"] = str(desi)
    return ln


def siparis(no, lines, tarih_iso="2026-10-05T14:30:00+03:00", durum="Delivered", kargo="Trendyol Express",
            cargoDeci=2, whoPays=None, commercial=False):
    pkg = _yeni("pkg")
    o = {
        "orderNumber": no, "shipmentPackageId": pkg, "orderDate": ms(tarih_iso),
        "netkar_not_orderDate_iso": tarih_iso, "status": durum, "cargoProviderName": kargo,
        "cargoTrackingNumber": int("7280" + str(pkg)[-8:].rjust(12, "0")),
        "cargoDeci": cargoDeci, "commercial": commercial, "lines": lines,
    }
    if whoPays is not None:
        o["whoPays"] = whoPays
    o["packageGrossAmount"] = s(sum(d(l["lineGrossAmount"]) * l["quantity"] for l in lines))
    o["packageSellerDiscount"] = s(sum(d(i["lineItemSellerDiscount"]) for l in lines for i in l["discountDetails"]))
    o["packageTyDiscount"] = s(sum(d(i["lineItemTyDiscount"]) for l in lines for i in l["discountDetails"]))
    o["packageTotalDiscount"] = s(d(o["packageSellerDiscount"]) + d(o["packageTyDiscount"]))
    o["packageTotalPrice"] = s(d(o["packageGrossAmount"]) - d(o["packageTotalDiscount"]))
    return o


def fin(tip, o, ln, credit="0", debt="0", oran=None, tarih_iso="2026-10-14T10:00:00+03:00",
        paymentOrderId=112360, komisyon_tutari=None, sellerRevenue="auto"):
    """settlements satırı. commissionAmount verilmezse (credit+debt)*oran/100 tam hassasiyetle."""
    credit, debt = d(credit), d(debt)
    oran = d(oran if oran is not None else ln["commission"]) if tip not in DUZELTME_TIPLERI else None
    if komisyon_tutari is not None:
        kom = d(komisyon_tutari)
    elif oran is not None:
        kom = (credit + debt) * oran / YUZ
    else:
        kom = D(0)
    isr = KOMISYON_ISARETI[tip]
    sr = (credit - debt) - isr * kom if sellerRevenue == "auto" else d(sellerRevenue)
    return {
        "id": str(_yeni("fin")), "transactionDate": ms(tarih_iso), "barcode": ln["barcode"],
        "netkar_istek_tipi": tip, "transactionType": TR_METIN.get(tip, tip), "receiptId": 48376618,
        "description": TR_METIN.get(tip, tip), "debt": format(debt, "f"), "credit": format(credit, "f"),
        "paymentPeriod": 30, "commissionRate": None if oran is None else format(oran, "f"),
        "commissionAmount": format(kom.normalize(), "f") if kom != 0 else "0",
        "commissionInvoiceSerialNumber": None, "sellerRevenue": format(abs(sr).normalize(), "f"),
        "orderNumber": o["orderNumber"], "paymentOrderId": paymentOrderId, "paymentDate": None,
        "sellerId": 123456, "orderDate": o["orderDate"], "affiliate": "TRENDYOLTR",
        "shipmentPackageId": o["shipmentPackageId"],
    }


def satis_satiri(o, ln, **kw):
    """Sale satırı: credit = satır satış tutarı (brüt - satıcı indirimi), K04 varsayımı."""
    tutar = sum(d(i["lineItemPrice"]) + d(i["lineItemTyDiscount"]) for i in ln["discountDetails"])
    return fin("Sale", o, ln, credit=tutar, **kw)


def diger(tip, debt="0", credit="0", alt_tip=None, metin=None, orderNumber=None, sinif=None, kdv=None,
          paymentOrderId=112360, tarih_iso="2026-10-20T10:00:00+03:00", id_=None):
    x = {
        "id": str(id_ or _yeni("fin")), "transactionDate": ms(tarih_iso), "barcode": None,
        "netkar_istek_tipi": tip, "transactionType": metin or tip, "receiptId": None, "description": metin,
        "debt": str(debt), "credit": str(credit), "orderNumber": orderNumber, "paymentOrderId": paymentOrderId,
        "sellerId": 123456, "affiliate": "TRENDYOLTR", "shipmentPackageId": None,
    }
    if alt_tip:
        x["netkar_istek_alt_tipi"] = alt_tip
    if sinif:
        x["netkar_sinif"] = sinif
    if kdv is not None:
        x["netkar_kdv_orani"] = kdv
    return x


def kargo_faturasi(seri, kalemler, kdv_dahil=True):
    """kalemler: (tip, orderNumber, amount, desi). Ekstre satırı (DeductionInvoices, 'Kargo Faturası')
    borcu: kalemler KDV dahil ise toplam, hariç ise toplam*1.20 (K08 tespit kuralını sınamak için)."""
    items = [{"shipmentPackageType": t, "parcelUniqueId": 7260001151141000 + i, "orderNumber": no,
              "amount": str(a), "desi": int(ds)} for i, (t, no, a, ds) in enumerate(kalemler)]
    top = sum(d(a) for _, _, a, _ in kalemler)
    borc = top if kdv_dahil else rnd(top * D("1.20"))
    ust = diger("DeductionInvoices", debt=s(borc), metin="Kargo Faturası", id_=seri)
    return {"invoiceSerialNumber": str(seri), "items": items}, ust


def claim(o, ln, adet=1, durum="Accepted", neden="UNFIT", urun_durumu=None):
    cis = []
    for it in ln["discountDetails"][:adet]:
        ci = {"id": "claim-item-" + it["lineItemId"], "orderLineItemId": int(it["lineItemId"]),
              "customerClaimItemReason": {"id": "451", "name": "Diğer", "code": neden},
              "claimItemStatus": {"name": durum}, "autoAccepted": False, "acceptedBySeller": True}
        if urun_durumu:
            ci["netkar_urun_durumu"] = urun_durumu
        cis.append(ci)
    return {"claimId": "claim-" + str(o["shipmentPackageId"]), "orderNumber": o["orderNumber"],
            "orderShipmentPackageId": o["shipmentPackageId"],
            "items": [{"orderLine": {"barcode": ln["barcode"], "price": ln["lineGrossAmount"],
                                     "vatRate": ln["vatRate"]}, "claimItems": cis}]}


def maliyet(barcode, birim, kdv="20", bas="2026-01-01"):
    return {"barcode": barcode, "gecerlilik_baslangic": bas, "birim_maliyet_kdv_haric": birim, "kdv_orani": kdv}


# --------------------------------------------------------------------------- senaryolar
SENARYOLAR = []


def senaryo(sid, ad, aciklama, kurallar, etiketler):
    def sar(f):
        SENARYOLAR.append((sid, ad, aciklama, kurallar, etiketler, f))
        return f
    return sar


BK_A, BK_B, BK_C, BK_D = "8681000000011", "8681000000028", "8681000000035", "8681000000042"


@senaryo("G01", "basit_satis_tahmini", "Tek adet, %20 KDV, %15 komisyon, indirimsiz satış. Ekstre yok: durum "
         "estimated; komisyon sipariş satırındaki oranla, kargo tarifeyle (cargoDeci=2), platform hizmet bedeli "
         "kullanıcı ayarıyla tahmin edilir.", ["K02", "K04", "K06", "K07", "K08", "K13", "K16", "K22"],
         ["basit_satis", "estimated"])
def g01():
    o = siparis("10000001", [satir(BK_A, "499.90")])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")]}


@senaryo("G02", "basit_satis_kesin", "G01 ile aynı sipariş, teslim sonrası Sale satırı ve kargo faturası geldi. "
         "Kargo faturası kalemleri KDV dahil (kalem toplamı = ekstre borcu). Hizmet bedeli faturası henüz yok, "
         "tahmini kalır. Durum settled.", ["K04", "K05", "K06", "K07", "K08", "K22", "K23", "K27", "K28"],
         ["basit_satis", "settled", "komisyon_kdv"])
def g02():
    o = siparis("10000002", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000001", [("Gönderi Kargo Bedeli", "10000002", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G03", "satici_indirimi_tahmini", "Satıcı karşılamalı %15 indirim (350,00 brüt, 52,50 indirim; Trendyol "
         "indirim kılavuzu senaryo 2). Komisyon matrahı indirimli tutar 297,50.", ["K03", "K04", "K06"],
         ["satici_indirimi", "estimated"])
def g03():
    o = siparis("10000003", [satir(BK_B, "350.00", satici_ind="52.50", komisyon="18")])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_B, "120.00")]}


@senaryo("G04", "satici_indirimi_kesin_net_sale", "G03 siparişi kesinleşti. Sale satırı credit=297,50 (indirim "
         "düşülmüş), ayrı Discount satırı yok.", ["K03", "K04", "K05", "K06"], ["satici_indirimi", "settled"])
def g04():
    o = siparis("10000004", [satir(BK_B, "350.00", satici_ind="52.50", komisyon="18")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000004", [("Gönderi Kargo Bedeli", "10000004", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_B, "120.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G05", "satici_indirimi_kesin_brut_sale_discount", "G04 ile aynı ekonomi, ekstre farklı biçimde: Sale "
         "credit=350,00 (brüt) ve komisyon brüt üzerinden; Discount satırı debt=52,50 ve indirimin komisyonunu "
         "geri verir. Motor credit-debt toplamı ve işaret tablosuyla G04 ile kuruşu kuruşuna aynı sonucu bulmalı.",
         ["K04", "K05", "K06", "K28"], ["satici_indirimi", "settled", "isaret_kurali"])
def g05():
    o = siparis("10000005", [satir(BK_B, "350.00", satici_ind="52.50", komisyon="18")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000005", [("Gönderi Kargo Bedeli", "10000005", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_B, "120.00")],
            "settlements": [fin("Sale", o, ln, credit="350.00"), fin("Discount", o, ln, debt="52.50")],
            "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G06", "trendyol_karsilamali_indirim", "Trendyol kuponu 75,00 (kılavuz senaryo 3). Müşteri 425,00 öder, "
         "satıcı geliri ve komisyon matrahı 500,00 kalır (indirim satıcıya yansıtılmaz). Kesinleşmiş: Sale credit=500,00.",
         ["K03", "K04", "K06"], ["trendyol_indirimi", "settled"])
def g06():
    o = siparis("10000006", [satir(BK_C, "500.00", ty_ind="75.00", komisyon="12")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000006", [("Gönderi Kargo Bedeli", "10000006", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_C, "260.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G07", "birlesik_indirim_tahmini", "Satıcı %10 (60,00) ve Trendyol kuponu (50,00) aynı satırda "
         "(kılavuz senaryo 5). Gelir = 600 - 60 = 540,00 KDV dahil; TY indirimi yalnız bilgi.",
         ["K03", "K04", "K06"], ["satici_indirimi", "trendyol_indirimi", "estimated"])
def g07():
    o = siparis("10000007", [satir(BK_C, "600.00", satici_ind="60.00", ty_ind="50.00", komisyon="12")])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_C, "260.00")]}


@senaryo("G08", "cok_adetli_satir", "quantity=3, kalemlerde farklı satıcı indirimi (0; 25,00; 25,00 gibi sepet "
         "kampanyası). Gelir ve komisyon discountDetails toplamından; satır alanları (ortalama) kullanılmaz. Kesin "
         "Sale tek satırda 3 adet toplamı (adet granülerliği doğrulanmadı).", ["K03", "K04", "K16", "K27"],
         ["cok_adet", "settled"])
def g08():
    o = siparis("10000008", [satir(BK_A, "149.90", adet=3, satici_ind=["0", "25.00", "25.00"], komisyon="15")],
                cargoDeci=4)
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000008", [("Gönderi Kargo Bedeli", "10000008", "72.00", 4)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "55.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G09", "kdv_yuzde_10", "Ürün KDV oranı %10 (vatRate=10). Satış KDV'si %10, komisyon ve kargo KDV'si %20; "
         "maliyet alış KDV'si %10.", ["K02", "K07", "K20"], ["kdv_orani", "estimated"])
def g09():
    o = siparis("10000009", [satir(BK_D, "275.00", kdv="10", komisyon="16")])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_D, "130.00", kdv="10")]}


@senaryo("G10", "kdv_yuzde_1", "Ürün KDV oranı %1 (temel gıda grubu). Düşük satış KDV'sine karşı %20'lik komisyon "
         "ve kargo KDV'si nedeniyle KDV etkisi negatif (devreden KDV oluşur).", ["K02", "K20"],
         ["kdv_orani", "estimated"])
def g10():
    o = siparis("10000010", [satir("8681000000103", "180.00", kdv="1", komisyon="10")])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet("8681000000103", "95.00", kdv="1")]}


@senaryo("G11", "cok_satirli_karma_kdv_komisyon", "Bir pakette 3 satır: %20/%15, %10/%16, %1/%10. Her satırın "
         "komisyonu kendi oranıyla; kargo faturası paket düzeyinde, satırlara satış (KDV hariç) oranıyla en büyük "
         "kalan yöntemiyle dağıtılır.", ["K06", "K07", "K09", "K24"], ["komisyon_kdv", "kdv_orani", "settled"])
def g11():
    l1 = satir(BK_A, "499.90", komisyon="15")
    l2 = satir(BK_D, "275.00", kdv="10", komisyon="16")
    l3 = satir("8681000000103", "180.00", kdv="1", komisyon="10")
    o = siparis("10000011", [l1, l2, l3], cargoDeci=5)
    kf, ust = kargo_faturasi("KRG2026000011", [("Gönderi Kargo Bedeli", "10000011", "71.99", 5)])
    return {"siparisler": [o],
            "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_D, "130.00", kdv="10"),
                                 maliyet("8681000000103", "95.00", kdv="1")],
            "settlements": [satis_satiri(o, l1), satis_satiri(o, l2), satis_satiri(o, l3)],
            "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G12", "komisyon_kdv_haric_varsayimi", "G02 ile aynı veri, ayar komisyon_tutari_kdv_dahil=false: "
         "commissionAmount KDV hariç kabul edilir, KDV üstüne eklenir. Teyit sonucu bu yönde çıkarsa beklenen "
         "çıktı budur (duyarlılık senaryosu).", ["K07"], ["komisyon_kdv", "settled", "ayar"])
def g12():
    o = siparis("10000012", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000012", [("Gönderi Kargo Bedeli", "10000012", "54.00", 2)])
    return {"ayarlar": {"komisyon_tutari_kdv_dahil": False}, "siparisler": [o],
            "urun_maliyetleri": [maliyet(BK_A, "180.00")], "settlements": [satis_satiri(o, ln)],
            "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G13", "kargo_desi_farki", "Siparişte cargoDeci=2 (tahmin 45,00 + KDV), kargo faturasında desi=5 ve "
         "72,00 KDV dahil. Kargo kesin tutarla, KARGO_DESI_FARKI uyarısı; fark eşiği aştığı için "
         "BEKLENMEYEN_KESINTI.", ["K08", "K23"], ["kargo_desi", "beklenmeyen_kesinti", "settled"])
def g13():
    o = siparis("10000013", [satir(BK_A, "499.90")], cargoDeci=2)
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000013", [("Gönderi Kargo Bedeli", "10000013", "72.00", 5)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G14", "kargo_faturasi_kdv_haric_tespiti", "Kargo faturası kalemleri KDV hariç (kalem toplamı x 1,20 = "
         "ekstre borcu). Motor fatura bazında KDV durumunu tespit eder: 45,00 KDV hariç kabul edilir.",
         ["K08"], ["kargo_kdv", "settled"])
def g14():
    o = siparis("10000014", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000014", [("Gönderi Kargo Bedeli", "10000014", "45.00", 2),
                                               ("Gönderi Kargo Bedeli", "99999999", "40.00", 1)], kdv_dahil=False)
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G15", "kargo_desi_agirlikli_dagitim", "İki satırlı paket, ürün kartlarında netkar_urun_desi var (1 ve 3, "
         "adet 2 ve 1). Kargo 85,00 KDV hariç tahmin (desi 5 tarifesi değil, cargoDeci=7 -> 85,00) satırlara "
         "desi x adet (2:3) oranında dağıtılır.", ["K08", "K09", "K24"], ["kargo_dagitim", "estimated"])
def g15():
    l1 = satir(BK_A, "199.90", adet=2, desi=1)
    l2 = satir(BK_B, "350.00", komisyon="18", desi=3)
    o = siparis("10000015", [l1, l2], cargoDeci=7)
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "70.00"), maliyet(BK_B, "120.00")]}


@senaryo("G16", "tam_iade_stoga_donen", "Satış kesinleşti, müşteri iade etti (claim Accepted), ürün sağlam stoğa "
         "döndü. Return satırı geliri ve komisyonu ters çevirir; maliyet 0; gönderi ve iade kargo bedeli ile "
         "platform hizmet bedeli geri alınamaz. Durum adjusted, ZARAR uyarısı.",
         ["K10", "K12", "K05", "K22"], ["tam_iade", "iade_kargo", "adjusted", "negatif_kar"])
def g16():
    o = siparis("10000016", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000016", [("Gönderi Kargo Bedeli", "10000016", "54.00", 2),
                                               ("İade Kargo Bedeli", "10000016", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln), fin("Return", o, ln, debt="499.90",
                                                     tarih_iso="2026-10-22T10:00:00+03:00")],
            "otherfinancials": [ust], "kargo_faturalari": [kf], "iadeler": [claim(o, ln)]}


@senaryo("G17", "tam_iade_urun_satilamaz", "G16 ile aynı, ancak kullanıcı iade gelen ürünü 'satilamaz' işaretledi: "
         "ürün maliyeti gider olarak kalır.", ["K10", "K16"], ["tam_iade", "adjusted", "negatif_kar"])
def g17():
    o = siparis("10000017", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000017", [("Gönderi Kargo Bedeli", "10000017", "54.00", 2),
                                               ("İade Kargo Bedeli", "10000017", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln), fin("Return", o, ln, debt="499.90")],
            "otherfinancials": [ust], "kargo_faturalari": [kf],
            "iadeler": [claim(o, ln, urun_durumu="satilamaz")]}


@senaryo("G18", "kismi_iade_manualrefund", "Müşteriye 100,00 TL kısmi iade (ManualRefund): ürün müşteride kalır, "
         "maliyet düşmez; kısmi iade tutarının komisyonu geri gelir.", ["K11", "K05"], ["kismi_iade", "adjusted"])
def g18():
    o = siparis("10000018", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000018", [("Gönderi Kargo Bedeli", "10000018", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln), fin("ManualRefund", o, ln, debt="100.00")],
            "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G19", "cok_adetten_bir_iade", "3 adetlik satırdan 1 adet iade (Return debt = bir kalemin tutarı). "
         "Maliyet 2 adet; iade kargo bedeli iade edilen satıra.", ["K10", "K12", "K16"],
         ["kismi_iade", "cok_adet", "iade_kargo", "adjusted"])
def g19():
    o = siparis("10000019", [satir(BK_A, "149.90", adet=3)], cargoDeci=4)
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000019", [("Gönderi Kargo Bedeli", "10000019", "72.00", 4),
                                               ("İade Kargo Bedeli", "10000019", "48.00", 1)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "55.00")],
            "settlements": [satis_satiri(o, ln), fin("Return", o, ln, debt="149.90")],
            "otherfinancials": [ust], "kargo_faturalari": [kf], "iadeler": [claim(o, ln, adet=1)]}


@senaryo("G20", "kismi_iade_sonra_tam_iade", "Önce 100,00 ManualRefund, sonra ürün tamamen iade: ManualRefundCancel "
         "100,00 (kısmi iadenin iptali) ve Return 499,90. Net gelir 0, net komisyon 0.",
         ["K10", "K11", "K05"], ["kismi_iade", "tam_iade", "adjusted", "isaret_kurali"])
def g20():
    o = siparis("10000020", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000020", [("Gönderi Kargo Bedeli", "10000020", "54.00", 2),
                                               ("İade Kargo Bedeli", "10000020", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln), fin("ManualRefund", o, ln, debt="100.00"),
                            fin("ManualRefundCancel", o, ln, credit="100.00"), fin("Return", o, ln, debt="499.90")],
            "otherfinancials": [ust], "kargo_faturalari": [kf], "iadeler": [claim(o, ln)]}


@senaryo("G21", "ceza_siparise_bagli", "otherfinancials DeductionInvoices satırı sipariş numarası taşıyor ve "
         "NetKâr eşleme tablosu onu 'ceza' (KDV %20) sınıfladı: 60,00 KDV dahil, iki satırlı siparişe satış oranıyla.",
         ["K14", "K24", "K22"], ["ceza", "adjusted"])
def g21():
    l1 = satir(BK_A, "499.90")
    l2 = satir(BK_B, "350.00", komisyon="18")
    o = siparis("10000021", [l1, l2], cargoDeci=3)
    kf, ust = kargo_faturasi("KRG2026000021", [("Gönderi Kargo Bedeli", "10000021", "60.00", 3)])
    ceza = diger("DeductionInvoices", debt="60.00", metin="Geç Kargolama Cezası (kurgusal metin)",
                 orderNumber="10000021", sinif="ceza", kdv="20")
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_B, "120.00")],
            "settlements": [satis_satiri(o, l1), satis_satiri(o, l2)], "otherfinancials": [ust, ceza],
            "kargo_faturalari": [kf]}


@senaryo("G22", "ceza_bagsiz_ve_siniflandirilmamis", "Sipariş numarası taşımayan ceza (dönem düzeyi, ürüne "
         "dağıtılmaz) ve eşleme tablosunda karşılığı olmayan bir FinancialItem (SINIFLANDIRILMAMIS_KESINTI).",
         ["K14", "K25"], ["ceza", "donem", "siniflandirilmamis"])
def g22():
    o = siparis("10000022", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000022", [("Gönderi Kargo Bedeli", "10000022", "54.00", 2)])
    ceza = diger("DeductionInvoices", debt="240.00", metin="Operasyonel Ceza (kurgusal metin)", sinif="ceza",
                 kdv="20")
    bilinmeyen = diger("FinancialItem", debt="17.35", metin="Düzeltme (kurgusal metin)")
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust, ceza, bilinmeyen],
            "kargo_faturalari": [kf]}


@senaryo("G23", "platform_hizmet_bedeli_dagitimi", "PlatformServiceFee faturası 40,00 KDV dahil, sipariş numarası "
         "yok; aynı paymentOrderId'ye düşen 3 siparişe eşit, sipariş içinde satış oranıyla dağıtılır. 33,33 KDV "
         "hariç tutar 3'e bölününce 11,11 / 11,11 / 11,11; KDV 6,67 -> 2,23 / 2,22 / 2,22.",
         ["K13", "K24"], ["hizmet_bedeli", "dagitim", "settled"])
def g23():
    l1 = satir(BK_A, "499.90")
    o1 = siparis("10000231", [l1])
    l2a, l2b = satir(BK_B, "350.00", komisyon="18"), satir(BK_C, "500.00", komisyon="12")
    o2 = siparis("10000232", [l2a, l2b], cargoDeci=3)
    l3 = satir(BK_D, "275.00", kdv="10", komisyon="16")
    o3 = siparis("10000233", [l3])
    kf, ust = kargo_faturasi("KRG2026000023", [("Gönderi Kargo Bedeli", "10000231", "54.00", 2),
                                               ("Gönderi Kargo Bedeli", "10000232", "60.00", 3),
                                               ("Gönderi Kargo Bedeli", "10000233", "54.00", 2)])
    psf = diger("DeductionInvoices", debt="40.00", alt_tip="PlatformServiceFee", metin="Platform Hizmet Bedeli")
    return {"siparisler": [o1, o2, o3],
            "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_B, "120.00"), maliyet(BK_C, "260.00"),
                                 maliyet(BK_D, "130.00", kdv="10")],
            "settlements": [satis_satiri(o1, l1), satis_satiri(o2, l2a), satis_satiri(o2, l2b),
                            satis_satiri(o3, l3)],
            "otherfinancials": [ust, psf], "kargo_faturalari": [kf]}


@senaryo("G24", "reklam_eslenen", "Panel Excel'inden yüklenen ürün reklamı: barkod A, 120,00 KDV hariç harcama, "
         "reklam cirosu 1.499,70. Dönemde A'nın iki satırı var; harcama satış oranıyla satırlara. ROAS ve başabaş "
         "ROAS ürün toplamında.", ["K15", "K25"], ["reklam_eslenen", "estimated", "roas"])
def g24():
    o1 = siparis("10000241", [satir(BK_A, "499.90")], tarih_iso="2026-10-03T10:00:00+03:00")
    o2 = siparis("10000242", [satir(BK_A, "499.90", adet=2)], tarih_iso="2026-10-09T10:00:00+03:00", cargoDeci=3)
    rk = {"kayit_id": "RK-1", "kaynak": "trendyol_panel_excel", "barkod": BK_A, "baslangic": "2026-10-01",
          "bitis": "2026-10-31", "harcama": "120.00", "harcama_kdv_dahil": False, "reklam_cirosu": "1499.70"}
    return {"siparisler": [o1, o2], "urun_maliyetleri": [maliyet(BK_A, "180.00")], "reklam_kayitlari": [rk]}


@senaryo("G25", "reklam_eslenmeyen_dagitim", "Mağaza reklamı (barkod yok) 90,00 KDV dahil harcama: KDV hariç 75,00 "
         "dönemdeki tüm satırlara net satış oranıyla dağıtılır, 'dagitim_tahmini' etiketiyle.",
         ["K15", "K24"], ["reklam_eslenmeyen", "estimated"])
def g25():
    o1 = siparis("10000251", [satir(BK_A, "499.90")])
    o2 = siparis("10000252", [satir(BK_B, "350.00", komisyon="18")])
    o3 = siparis("10000253", [satir(BK_D, "275.00", kdv="10", komisyon="16")])
    rk = {"kayit_id": "RK-2", "kaynak": "trendyol_panel_excel", "barkod": None, "baslangic": "2026-10-01",
          "bitis": "2026-10-31", "harcama": "90.00", "harcama_kdv_dahil": True, "reklam_cirosu": None}
    return {"siparisler": [o1, o2, o3],
            "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_B, "120.00"), maliyet(BK_D, "130.00", kdv="10")],
            "reklam_kayitlari": [rk]}


@senaryo("G26", "reklam_satissiz_urun", "Barkod C için 80,00 reklam harcaması var ama dönemde C satışı yok: "
         "harcama başka ürüne dağıtılmaz, ürün toplamında reklam_satissiz ve dönem gideri olarak görünür; "
         "ayrıca katalogda olmayan barkodlu bir kayıt (eşlenemeyen) diğer satışlara dağıtılır.",
         ["K15", "K25"], ["reklam_eslenen", "reklam_eslenmeyen", "donem"])
def g26():
    o1 = siparis("10000261", [satir(BK_A, "499.90")])
    rk1 = {"kayit_id": "RK-3", "kaynak": "trendyol_panel_excel", "barkod": BK_C, "baslangic": "2026-10-01",
           "bitis": "2026-10-31", "harcama": "80.00", "harcama_kdv_dahil": False, "reklam_cirosu": "0"}
    rk2 = {"kayit_id": "RK-4", "kaynak": "trendyol_panel_excel", "barkod": "0000000000000",
           "baslangic": "2026-10-01", "bitis": "2026-10-31", "harcama": "12.50", "harcama_kdv_dahil": False,
           "reklam_cirosu": None}
    return {"siparisler": [o1], "urunler": [{"barcode": BK_C}],
            "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_C, "260.00")],
            "reklam_kayitlari": [rk1, rk2]}


@senaryo("G27", "beklenmeyen_kesinti_komisyon_orani", "Sipariş satırında commission=15, ekstrede commissionRate=18. "
         "Kesin komisyon tahminden 12,50 fazla: KOMISYON_ORANI_FARKLI ve BEKLENMEYEN_KESINTI.",
         ["K23", "K22"], ["estimated_settled_fark", "beklenmeyen_kesinti"])
def g27():
    o = siparis("10000027", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000027", [("Gönderi Kargo Bedeli", "10000027", "54.00", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln, oran="18")], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G28", "fark_esik_alti", "Kesin değerler tahminden çok az farklı (komisyon 4 hane hassasiyetle aynı; "
         "kargo faturası 54,05): fark yuvarlama toleransı/eşik altında, uyarı yok.",
         ["K23"], ["estimated_settled_fark", "settled"])
def g28():
    o = siparis("10000028", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000028", [("Gönderi Kargo Bedeli", "10000028", "54.05", 2)])
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G29", "maliyet_girilmemis", "İki satırlı sipariş, B ürününün maliyeti yok: satırın net_kar=null, "
         "maliyet_haric_katki hesaplanır; ürün toplamında maliyet_eksik=true; dönem net kârı kısmi.",
         ["K16", "K25"], ["maliyet_eksik", "estimated"])
def g29():
    o = siparis("10000029", [satir(BK_A, "499.90"), satir(BK_B, "350.00", komisyon="18")], cargoDeci=3)
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")]}


@senaryo("G30", "maliyet_gecerlilik_tarihi", "A için iki maliyet kaydı: 2026-01-01'den 170,00 ve 2026-10-10'dan "
         "190,00. 9 Ekim siparişi 170,00; 10 Ekim 00:30 (İstanbul) siparişi 190,00 kullanır.",
         ["K16"], ["maliyet_tarihli", "estimated"])
def g30():
    o1 = siparis("10000301", [satir(BK_A, "499.90")], tarih_iso="2026-10-09T23:50:00+03:00")
    o2 = siparis("10000302", [satir(BK_A, "499.90")], tarih_iso="2026-10-10T00:30:00+03:00")
    return {"siparisler": [o1, o2],
            "urun_maliyetleri": [maliyet(BK_A, "170.00"), maliyet(BK_A, "190.00", bas="2026-10-10")]}


@senaryo("G31", "sifir_kar", "Maliyet, net kâr tam 0,00 olacak biçimde seçildi (sınır: ZARAR uyarısı yok).",
         ["K25"], ["sifir_kar", "estimated"])
def g31():
    o = siparis("10000031", [satir(BK_A, "240.00")], cargoDeci=1)
    # net satış 200.00, komisyon 30.00, kargo 40.00, hizmet 10.00 -> maliyet 120.00 ile net kâr 0
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "120.00")]}


@senaryo("G32", "negatif_kar_ucuz_urun", "Düşük fiyatlı ürün: sabit kargo ve hizmet bedeli kârı siler, net kâr "
         "negatif, ZARAR uyarısı.", ["K25"], ["negatif_kar", "estimated"])
def g32():
    o = siparis("10000032", [satir("8681000000110", "59.90", komisyon="20")], cargoDeci=1)
    return {"siparisler": [o], "urun_maliyetleri": [maliyet("8681000000110", "25.00")]}


@senaryo("G33", "yuvarlama_sinir_yarim_kurus", "Satır 1 (1 adet, 12,03 KDV dahil): 12,03/1,20 = 10,025 -> HALF_UP "
         "10,03 (banker yuvarlaması 10,02 verirdi); maliyet 3,335 -> 3,34. Satır 2 (3 adet, 12,03): satır sonunda "
         "36,09/1,20 = 30,075 -> 30,08 (birim bazında yuvarlansaydı 3 x 10,03 = 30,09); komisyon %15 = 5,4135 KDV "
         "dahil -> hariç 4,51125 -> 4,51 (birim bazında 3 x 1,50 = 4,50); maliyet 3,335 x 3 = 10,005 -> 10,01 "
         "(banker 10,00). Kargo 40,00 iki satıra satış oranıyla.", ["K01", "K02", "K24"], ["yuvarlama", "estimated"])
def g33():
    o = siparis("10000033", [satir("8681000000127", "12.03"), satir("8681000000127", "12.03", adet=3)],
                cargoDeci=1)
    return {"ayarlar": {"platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric": "0.00"},
            "siparisler": [o], "urun_maliyetleri": [maliyet("8681000000127", "3.335")]}


@senaryo("G34", "yuvarlama_dagitim_en_buyuk_kalan", "Kargo 40,00 KDV hariç (KDV 8,00) eşit satışlı üç satıra: "
         "13,34 / 13,33 / 13,33 ve 2,67 / 2,67 / 2,66; toplam korunur. Hizmet bedeli 10,00 -> 3,34 / 3,33 / 3,33.",
         ["K01", "K24"], ["yuvarlama", "dagitim", "estimated"])
def g34():
    o = siparis("10000034", [satir(BK_A, "100.00"), satir(BK_B, "100.00"), satir(BK_C, "100.00")], cargoDeci=1)
    return {"siparisler": [o],
            "urun_maliyetleri": [maliyet(BK_A, "30.00"), maliyet(BK_B, "30.00"), maliyet(BK_C, "30.00")]}


@senaryo("G35", "stopaj_nakit_akisi", "%1 e-ticaret stopajı: KDV hariç net satış üzerinden hesaplanır, net kârı "
         "değiştirmez, yalnız nakit akışında ve dönemde görünür. Ekstredeki Stoppage satırı (dönem) hesaplananla "
         "karşılaştırılır; 1 kuruşluk fark tolerans içinde.", ["K18", "K21"], ["stopaj", "settled"])
def g35():
    l1, l2 = satir(BK_A, "499.90"), satir(BK_B, "350.00", komisyon="18")
    o1 = siparis("10000351", [l1])
    o2 = siparis("10000352", [l2])
    kf, ust = kargo_faturasi("KRG2026000035", [("Gönderi Kargo Bedeli", "10000351", "54.00", 2),
                                               ("Gönderi Kargo Bedeli", "10000352", "54.00", 2)])
    stop = diger("Stoppage", debt="7.10", metin="E-ticaret Stopajı")
    return {"siparisler": [o1, o2], "urun_maliyetleri": [maliyet(BK_A, "180.00"), maliyet(BK_B, "120.00")],
            "settlements": [satis_satiri(o1, l1), satis_satiri(o2, l2)],
            "otherfinancials": [ust, stop], "kargo_faturalari": [kf]}


@senaryo("G36", "degisken_giderler", "Kullanıcı tanımlı giderler: paketleme sipariş başı 6,00 (+%20 KDV), "
         "etiket adet başı 0,50 (+%20), muhasebe/e-fatura entegratörü net satışın %0,5'i (+%20). İki satır, biri "
         "2 adet.", ["K17", "K24"], ["degisken_gider", "estimated"])
def g36():
    o = siparis("10000036", [satir(BK_A, "199.90", adet=2), satir(BK_B, "350.00", komisyon="18")], cargoDeci=3)
    gid = [{"ad": "paketleme", "tip": "siparis_basi", "tutar_kdv_haric": "6.00", "kdv_orani": "20"},
           {"ad": "etiket", "tip": "adet_basi", "tutar_kdv_haric": "0.50", "kdv_orani": "20"},
           {"ad": "e_fatura_entegrator", "tip": "satis_yuzdesi", "oran_yuzde": "0.5", "kdv_orani": "20"}]
    return {"ayarlar": {"degisken_giderler": gid}, "siparisler": [o],
            "urun_maliyetleri": [maliyet(BK_A, "70.00"), maliyet(BK_B, "120.00")]}


@senaryo("G37", "erken_odeme", "CashAdvance (erken ödeme) 10.000,00 nakit girişi: gider değildir. Eşleme tablosunda "
         "'erken_odeme_bedeli' sınıflı 120,00 KDV dahil fatura dönem finansman gideri (100,00 KDV hariç); ürün "
         "kârına dağıtılmaz.", ["K19", "K25"], ["erken_odeme", "donem", "settled"])
def g37():
    o = siparis("10000037", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000037", [("Gönderi Kargo Bedeli", "10000037", "54.00", 2)])
    ca = diger("CashAdvance", credit="10000.00", metin="Erken Ödeme")
    bedel = diger("DeductionInvoices", debt="120.00", metin="Erken Ödeme Hizmet Bedeli (kurgusal metin)",
                  sinif="erken_odeme_bedeli", kdv="20")
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln)], "otherfinancials": [ust, ca, bedel], "kargo_faturalari": [kf]}


@senaryo("G38", "iptal_siparis", "Gönderim öncesi iptal (status=Cancelled): gelir ve gider yok, durum cancelled, "
         "ürün ve dönem toplamlarına girmez.", ["K26"], ["iptal"])
def g38():
    o = siparis("10000038", [satir(BK_A, "499.90")], durum="Cancelled")
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")]}


@senaryo("G39", "satici_anlasmali_kargo", "whoPays=1: satıcının kendi kargo anlaşması. Kargo bedeli kullanıcı "
         "tarifesinden (Aras, desi 2 -> 38,00), Trendyol kargo faturası beklenmez, hakedişten düşülmez.",
         ["K08", "K21"], ["kargo_satici_anlasmasi", "settled"])
def g39():
    o = siparis("10000039", [satir(BK_A, "499.90")], kargo="Aras Kargo Marketplace", whoPays=1)
    ln = o["lines"][0]
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln)]}


@senaryo("G40", "komisyon_duzeltme_kaydi", "Satıştan sonra Trendyol CommissionPositive düzeltmesi (5,00 ek komisyon) "
         "ve SellerRevenueNegative eşi (5,00). Eşleşen hakediş düzeltmesi geliri ayrıca düşürmez; komisyon gideri "
         "yaklaşık 4,16 KDV hariç artar (yuvarlanmış kalemler farkı), durum adjusted; fark karşılaştırmaya girer ama eşik altında kalır.",
         ["K05", "K22", "K23"], ["isaret_kurali", "adjusted"])
def g40():
    o = siparis("10000040", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000040", [("Gönderi Kargo Bedeli", "10000040", "54.00", 2)])
    kp = fin("CommissionPositive", o, ln, komisyon_tutari="5.00", sellerRevenue="0")
    srn = fin("SellerRevenueNegative", o, ln, debt="5.00", komisyon_tutari="0")
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln), kp, srn], "otherfinancials": [ust], "kargo_faturalari": [kf]}


@senaryo("G41", "eslesmemis_hakedis_duzeltmesi", "Komisyon düzeltmesi eşi olmayan SellerRevenuePositive (20,00 "
         "alacak): gelir düzeltmesi olarak satışa eklenir (ürün KDV oranıyla ayrıştırılır) ve "
         "ESLESMEMIS_HAKEDIS_DUZELTMESI uyarısı üretir; anlamı teyit edilene kadar kullanıcıya gösterilir.",
         ["K05", "K22"], ["isaret_kurali", "adjusted"])
def g41():
    o = siparis("10000041", [satir(BK_A, "499.90")])
    ln = o["lines"][0]
    kf, ust = kargo_faturasi("KRG2026000041", [("Gönderi Kargo Bedeli", "10000041", "54.00", 2)])
    srp = fin("SellerRevenuePositive", o, ln, credit="20.00", komisyon_tutari="0")
    return {"siparisler": [o], "urun_maliyetleri": [maliyet(BK_A, "180.00")],
            "settlements": [satis_satiri(o, ln), srp], "otherfinancials": [ust], "kargo_faturalari": [kf]}


# --------------------------------------------------------------------------- yazım
def main():
    CIKTI.mkdir(parents=True, exist_ok=True)
    for f in CIKTI.glob("G*.json"):
        f.unlink()
    ozet = []
    for sid, ad, aciklama, kurallar, etiketler, fn in SENARYOLAR:
        girdi = fn()
        girdi.setdefault("donem", {"baslangic": "2026-10-01", "bitis": "2026-10-31"})
        beklenen = hesapla(girdi)
        doc = {
            "senaryo_id": sid,
            "ad": ad,
            "aciklama": aciklama,
            "kurallar": kurallar,
            "etiketler": etiketler,
            "sema_surumu": "1",
            "not": "Tutarlar kurgusaldır. 'netkar_' önekli alanlar NetKâr ingest katmanınındır, Trendyol alanı değildir.",
            "girdi": {"ayarlar": birlestir(VARSAYILAN_AYARLAR, girdi.get("ayarlar", {})),
                      **{k: v for k, v in girdi.items() if k != "ayarlar"}},
            "beklenen": beklenen,
        }
        yol = CIKTI / f"{sid}_{ad}.json"
        yol.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ss = beklenen["siparis_satirlari"]
        ozet.append((sid, ad, [(x["durum"], x["kalemler"]["net_kar"], x["uyarilar"]) for x in ss]))
    for sid, ad, sat in ozet:
        print(sid, ad)
        for x in sat:
            print("   ", x)
    print(len(SENARYOLAR), "senaryo yazıldı ->", CIKTI)


if __name__ == "__main__":
    # v0.1 `main()` tüm G*.json dosyalarını silip yalnız G01-G41'i eski kurallarla yazar; bu G42-G48'i yok eder
    # ve G01-G41'in yeni alanlarını siler. Doğrudan çalıştırma bu yüzden yeni betiğe yönlendirilir (bu betik
    # yalnız içe aktarılan yardımcılar ve G01-G41 tanımları içindir). Argümanlar (`--yaz`) aynen aktarılır.
    import sys

    sys.stderr.write(
        "UYARI: altin_test_hesap.py tek başına çalıştırılmaz (G42-G48'i silerdi); "
        "altin_test_hesap_ayarlar.py'ye yönlendiriliyor.\n"
    )
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from altin_test_hesap_ayarlar import main as ayarlar_main

    sys.exit(ayarlar_main())
