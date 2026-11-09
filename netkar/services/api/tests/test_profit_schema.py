"""Altın test şeması dönüştürücüsü (schema_v1): ayar ayrıştırma, İstanbul günü, çıktı serileştirme."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.profit import ProfitInputError, ProfitSettings, calculate_profit
from app.profit.enums import ExpenseKind
from app.profit.schema_v1 import istanbul_day, parse_input, parse_settings, render_result, to_wire

D = Decimal


def minimal_order(**over: Any) -> dict[str, Any]:
    order: dict[str, Any] = {
        "orderNumber": "1",
        "shipmentPackageId": 10,
        "orderDate": 1791199800000,
        "status": "Delivered",
        "cargoProviderName": "Trendyol Express",
        "lines": [
            {
                "lineId": 1,
                "barcode": "B",
                "quantity": 1,
                "lineGrossAmount": "100.00",
                "vatRate": "20",
                "commission": "10",
                "discountDetails": [
                    {"lineItemId": "i1", "lineItemSellerDiscount": "0.00", "lineItemTyDiscount": "0.00"}
                ],
            }
        ],
    }
    order.update(over)
    return order


def test_istanbul_day_uses_fixed_utc_plus_3() -> None:
    # 2026-10-05T21:30:00Z = İstanbul 06 Ekim 00:30
    assert istanbul_day(1791235800000) == date(2026, 10, 6)
    assert istanbul_day(1791235800000 - 1_800_000 - 1) == date(2026, 10, 5)
    assert istanbul_day(0) == date(1970, 1, 1)


def test_parse_settings_defaults_and_overrides() -> None:
    defaults = parse_settings({})
    assert defaults == ProfitSettings()
    assert defaults.service_fee_estimates == ()  # tahmin uydurulmaz: tanımsız, 0 değil (K33, K35)
    assert defaults.default_desi is None
    assert defaults.cargo_tariff.steps == {}
    parsed = parse_settings(
        {
            "komisyon_tutari_kdv_dahil": False,
            "stopaj_orani": "2",
            "kargo_tarifesi": {"X": [["1", "10.00"], ["2", "20.00"]]},
            "satici_kargo_tarifesi": {"Y": [["3", "30.00"]]},
            "uyari_esikleri": {"beklenmeyen_kesinti_tutar": "9.00"},
            "degisken_giderler": [
                {"ad": "paket", "tip": "siparis_basi", "tutar_kdv_haric": "6.00"},
                {"ad": "yuzde", "tip": "satis_yuzdesi", "oran_yuzde": "0.5", "kdv_orani": "10"},
            ],
        }
    )
    assert parsed.commission_includes_vat is False
    assert parsed.withholding_rate == D("2")
    assert parsed.cargo_tariff.lookup("X", D("2"), date(2026, 10, 5)) == D("20.00")
    assert parsed.seller_cargo_tariff.lookup("Y", D("1"), date(2026, 10, 5)) == D("30.00")
    assert parsed.thresholds.unexpected_deduction_amount == D("9.00")
    assert parsed.thresholds.unexpected_deduction_percent == D("5")  # varsayılan korunur
    assert parsed.variable_expenses[0].kind is ExpenseKind.PER_ORDER
    assert parsed.variable_expenses[0].vat_rate == D("20")
    assert parsed.variable_expenses[1].vat_rate == D("10")
    assert parsed.variable_expenses[1].percent == D("0.5")


def test_parse_settings_reads_both_tariff_forms_and_versioned_blocks() -> None:
    """Golden README "Ayarlar bloğu": eski liste biçimi (başlangıçsız tek sürüm) ve sürümlü biçim, `*` yedeği."""
    parsed = parse_settings(
        {
            "kargo_tarifesi": {
                "Legacy": [["1", "10.00"], ["2", "20.00"]],
                "TE": [
                    {"gecerlilik_baslangic": "2026-01-01", "kademeler": [["2", "42.00"]]},
                    {"gecerlilik_baslangic": "2026-10-10", "kademeler": [["2", "45.00"]]},
                ],
                "*": [{"kademeler": [["3", "50.00"]]}],  # başlangıçsız sürümlü kayıt
            },
            "varsayilan_desi": "3",
            "degisken_giderler": [
                {
                    "ad": "paket",
                    "tip": "siparis_basi",
                    "tutar_kdv_haric": "6.00",
                    "gecerlilik_baslangic": "2026-01-01",
                    "gecerlilik_bitis": "2026-10-09",
                },
                {"ad": "paket", "tip": "siparis_basi", "tutar_kdv_haric": "7.50", "gecerlilik_bitis": None},
            ],
        }
    )
    tariff = parsed.cargo_tariff
    assert tariff.lookup("Legacy", D("2"), date(1999, 1, 1)) == D("20.00")  # başlangıçsız: her günde geçerli
    assert tariff.lookup("TE", D("2"), date(2026, 10, 9)) == D("42.00")
    assert tariff.lookup("TE", D("2"), date(2026, 10, 10)) == D("45.00")
    assert tariff.lookup("Baska", D("3"), date(2026, 10, 10)) == D("50.00")
    assert parsed.default_desi == D("3")
    first, second = parsed.variable_expenses
    assert (first.valid_from, first.valid_to) == (date(2026, 1, 1), date(2026, 10, 9))
    assert (second.valid_from, second.valid_to) == (None, None)


def test_parse_settings_service_fee_forms() -> None:
    key = "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric"
    day = date(2026, 10, 5)
    assert parse_settings({key: None}).service_fee_estimates == ()  # null = tanımsız
    assert parse_settings({key: None}).service_fee_estimate_on(day) is None
    assert parse_settings({}).service_fee_estimate_on(day) is None
    assert parse_settings({key: "10.00"}).service_fee_estimate_on(date(1999, 1, 1)) == D("10.00")
    assert parse_settings({key: "0"}).service_fee_estimate_on(day) == D("0")  # bilerek 0: tanımlı
    versioned = parse_settings(
        {
            key: [
                {"gecerlilik_baslangic": "2026-01-01", "tutar_kdv_haric": "8.00"},
                {"gecerlilik_baslangic": "2026-10-10", "tutar_kdv_haric": "10.00"},
            ]
        }
    )
    assert versioned.service_fee_estimate_on(day) == D("8.00")
    assert versioned.service_fee_estimate_on(date(2026, 10, 10)) == D("10.00")
    assert versioned.service_fee_estimate_on(date(2025, 12, 31)) is None
    assert parse_settings({key: [{"tutar_kdv_haric": "5.00"}]}).service_fee_estimate_on(day) == D("5.00")


def test_parse_settings_rejects_unknown_expense_kind() -> None:
    with pytest.raises(ValueError, match="gecersiz"):
        parse_settings({"degisken_giderler": [{"ad": "x", "tip": "gecersiz"}]})


def test_parse_input_minimal_and_optional_blocks() -> None:
    data = parse_input({"siparisler": [minimal_order()]})
    order = data.orders[0]
    assert order.order_day == date(2026, 10, 5)
    assert order.cargo_deci is None
    assert order.deci is None
    assert order.who_pays is None
    assert order.lines[0].unit_desi is None
    assert data.costs == ()
    assert data.claims == ()
    assert data.compensation_tickets == ()


def test_parse_input_reads_all_blocks() -> None:
    raw = {
        "siparisler": [
            minimal_order(cargoDeci=2, deci="1.5", whoPays=1),
        ],
        "urun_maliyetleri": [
            {
                "barcode": "B",
                "gecerlilik_baslangic": "2026-01-01",
                "birim_maliyet_kdv_haric": "5",
                "kdv_orani": "20",
            }
        ],
        "urunler": [{"barcode": "Z"}],
        "settlements": [
            {
                "id": 1,
                "netkar_istek_tipi": "Sale",
                "orderNumber": "1",
                "barcode": "B",
                "debt": "0",
                "credit": "100.00",
                "commissionAmount": None,
            }
        ],
        "otherfinancials": [
            {"id": 2, "netkar_istek_tipi": "Stoppage", "debt": "1", "credit": "0", "netkar_kdv_orani": "20"}
        ],
        "kargo_faturalari": [
            {
                "invoiceSerialNumber": 7,
                "items": [
                    {
                        "shipmentPackageType": "Gönderi Kargo Bedeli",
                        "orderNumber": "1",
                        "amount": "5",
                        "desi": 2,
                    }
                ],
            }
        ],
        "iadeler": [
            {
                "orderNumber": "1",
                "items": [
                    {
                        "claimItems": [
                            {"orderLineItemId": 99, "claimItemStatus": {"name": "Accepted"}},
                            {
                                "orderLineItemId": 98,
                                "claimItemStatus": {"name": "Accepted"},
                                "netkar_urun_durumu": "satilamaz",
                            },
                        ]
                    }
                ],
            }
        ],
        "reklam_kayitlari": [
            {"kayit_id": "a", "baslangic": "2026-10-01", "bitis": "2026-10-02", "harcama": "3.00"}
        ],
        "tazminler": [{"orderNumber": "1", "status": "CompensationApproved", "amount": "9.99"}],
    }
    data = parse_input(raw)
    assert data.orders[0].who_pays == 1
    assert data.orders[0].deci == D("1.5")
    assert data.catalog_barcodes == ("Z",)
    assert data.settlements[0].commission_amount is None
    assert data.settlements[0].row_id == "1"
    assert data.other_financials[0].vat_rate == D("20")
    assert data.cargo_invoices[0].serial_number == "7"
    assert [i.returned_to_stock for i in data.claims[0].items] == [True, False]
    assert data.claims[0].items[0].order_line_item_id == "99"
    assert data.ad_records[0].spend_includes_vat is False
    assert data.compensation_tickets[0].amount == D("9.99")
    calculate_profit(data)  # uçtan uca çalışır


def test_parse_input_rejects_float_money() -> None:
    order = minimal_order()
    order["lines"][0]["lineGrossAmount"] = 100.0
    with pytest.raises(TypeError):
        parse_input({"siparisler": [order]})


def test_parse_input_rejects_inconsistent_item_count() -> None:
    order = minimal_order()
    order["lines"][0]["quantity"] = 2
    with pytest.raises(ProfitInputError):
        parse_input({"siparisler": [order]})


def test_to_wire_conversions() -> None:
    assert to_wire(D("1.5")) == "1.50"
    assert to_wire(None) is None
    assert to_wire((D("1"), D("2.005"))) == ["1.00", "2.01"]
    assert to_wire([1, "x", True]) == [1, "x", True]
    assert to_wire({1: D("3")}) == {"1": "3.00"}


def test_render_result_uses_wire_names() -> None:
    result = render_result(calculate_profit(parse_input({"siparisler": [minimal_order(cargoDeci=2)]})))
    assert set(result) == {
        "siparis_satirlari",
        "urun_toplamlari",
        "donem_toplami",
        "kargo_faturasi_kdv_durumu",
    }
    line = result["siparis_satirlari"][0]
    assert line["durum"] == "estimated"
    assert line["kalemler"]["net_satis_kdv_haric"] == "83.33"
    assert line["kalemler"]["net_kar"] is None  # maliyet yok
    assert line["teyit_bekliyor"] == []
    # Ayarsız hesapta hizmet bedeli tahmini de tanımsızdır (K35): eksik, 0 değil.
    assert set(line["uyarilar"]) == {"MALIYET_EKSIK", "KARGO_TARIFESI_EKSIK", "HIZMET_BEDELI_TAHMINI_EKSIK"}
