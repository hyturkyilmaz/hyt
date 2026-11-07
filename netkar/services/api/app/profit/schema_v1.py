"""Altın test şeması (sema_surumu 1) <-> alan modeli dönüştürücüsü.

`tests/golden/README.md` içindeki girdi biçimi (Trendyol alan adları + `netkar_` önekli alanlar) alan
modeline, motor çıktısı da aynı şemadaki JSON uyumlu sözlüğe çevrilir. Saf fonksiyonlardır; I/O yoktur.
JSON number alanları `Decimal(str(x))` ile okunur, float kabul edilmez (K01).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from app.profit.enums import ExpenseKind
from app.profit.inputs import (
    AdRecord,
    CargoInvoice,
    CargoInvoiceItem,
    Claim,
    ClaimItem,
    CompensationTicket,
    CostRecord,
    Order,
    OrderItem,
    OrderLine,
    OtherFinancialRow,
    ProfitInput,
    SettlementRow,
)
from app.profit.money import fmt, to_decimal
from app.profit.results import ProfitResult
from app.profit.settings import CargoTariff, ProfitSettings, VariableExpense, WarningThresholds

# Europe/Istanbul 2016'dan beri sabit UTC+3 (K16). Saat bağımlılığı değil, sabit dönüşümdür.
ISTANBUL = timezone(timedelta(hours=3))


def istanbul_day(epoch_ms: int) -> date:
    """Epoch milisaniyeyi İstanbul takvim gününe çevirir (K16, K15). Tamsayı aritmetiği, float yok."""
    moment = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=epoch_ms)
    return moment.astimezone(ISTANBUL).date()


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else to_decimal(value)


# --------------------------------------------------------------------------- ayarlar
_SETTING_FIELDS: tuple[tuple[str, str, Callable[[Any], Any]], ...] = (
    ("komisyon_tutari_kdv_dahil", "commission_includes_vat", bool),
    ("komisyon_kdv_orani", "commission_vat_rate", to_decimal),
    ("kargo_kdv_orani", "shipping_vat_rate", to_decimal),
    ("hizmet_bedeli_kdv_orani", "service_fee_vat_rate", to_decimal),
    ("reklam_kdv_orani", "ad_vat_rate", to_decimal),
    ("stopaj_orani", "withholding_rate", to_decimal),
    (
        "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric",
        "estimated_service_fee_per_order_excl_vat",
        to_decimal,
    ),
    ("kargo_faturasi_kdv_tespit_toleransi", "cargo_invoice_vat_tolerance", to_decimal),
)
_THRESHOLD_FIELDS: tuple[tuple[str, str], ...] = (
    ("beklenmeyen_kesinti_tutar", "unexpected_deduction_amount"),
    ("beklenmeyen_kesinti_oran_yuzde", "unexpected_deduction_percent"),
    ("yuvarlama_toleransi", "rounding_tolerance"),
    ("komisyon_orani_tolerans_puan", "commission_rate_tolerance_points"),
)


def _parse_tariff(raw: Mapping[str, Sequence[Sequence[Any]]]) -> CargoTariff:
    return CargoTariff(
        {
            carrier: tuple((to_decimal(upper), to_decimal(price)) for upper, price in brackets)
            for carrier, brackets in raw.items()
        }
    )


def parse_settings(raw: Mapping[str, Any]) -> ProfitSettings:
    """`ayarlar` bloğu -> ProfitSettings. Eksik anahtarlar motor varsayılanlarında kalır."""
    kwargs: dict[str, Any] = {attr: convert(raw[key]) for key, attr, convert in _SETTING_FIELDS if key in raw}
    if "kargo_tarifesi" in raw:
        kwargs["cargo_tariff"] = _parse_tariff(raw["kargo_tarifesi"])
    if "satici_kargo_tarifesi" in raw:
        kwargs["seller_cargo_tariff"] = _parse_tariff(raw["satici_kargo_tarifesi"])
    thresholds = raw.get("uyari_esikleri", {})
    kwargs["thresholds"] = WarningThresholds(
        **{attr: to_decimal(thresholds[key]) for key, attr in _THRESHOLD_FIELDS if key in thresholds}
    )
    kwargs["variable_expenses"] = tuple(
        VariableExpense(
            name=item["ad"],
            kind=ExpenseKind(item["tip"]),
            amount_excl_vat=to_decimal(item.get("tutar_kdv_haric", "0")),
            percent=to_decimal(item.get("oran_yuzde", "0")),
            vat_rate=to_decimal(item.get("kdv_orani", "20")),
        )
        for item in raw.get("degisken_giderler", [])
    )
    return ProfitSettings(**kwargs)


# --------------------------------------------------------------------------- girdi
def _parse_line(raw: Mapping[str, Any]) -> OrderLine:
    return OrderLine(
        line_id=int(raw["lineId"]),
        barcode=raw["barcode"],
        quantity=int(raw["quantity"]),
        unit_gross=to_decimal(raw["lineGrossAmount"]),
        vat_rate=to_decimal(raw["vatRate"]),
        commission_rate=to_decimal(raw["commission"]),
        items=tuple(
            OrderItem(
                item_id=str(item["lineItemId"]),
                seller_discount=to_decimal(item["lineItemSellerDiscount"]),
                ty_discount=to_decimal(item["lineItemTyDiscount"]),
            )
            for item in raw["discountDetails"]
        ),
        unit_desi=_optional_decimal(raw.get("netkar_urun_desi")),
    )


def _parse_order(raw: Mapping[str, Any]) -> Order:
    return Order(
        order_number=raw["orderNumber"],
        package_id=int(raw["shipmentPackageId"]),
        order_day=istanbul_day(int(raw["orderDate"])),
        status=raw["status"],
        carrier=raw["cargoProviderName"],
        lines=tuple(_parse_line(line) for line in raw["lines"]),
        cargo_deci=_optional_decimal(raw.get("cargoDeci")),
        deci=_optional_decimal(raw.get("deci")),
        who_pays=raw.get("whoPays"),
    )


def _parse_settlement(raw: Mapping[str, Any]) -> SettlementRow:
    return SettlementRow(
        row_id=str(raw["id"]),
        request_type=raw["netkar_istek_tipi"],
        order_number=raw["orderNumber"],
        barcode=raw["barcode"],
        debt=to_decimal(raw["debt"]),
        credit=to_decimal(raw["credit"]),
        package_id=raw.get("shipmentPackageId"),
        commission_amount=_optional_decimal(raw.get("commissionAmount")),
        commission_rate=_optional_decimal(raw.get("commissionRate")),
        seller_revenue=_optional_decimal(raw.get("sellerRevenue")),
        payment_order_id=raw.get("paymentOrderId"),
    )


def _parse_other(raw: Mapping[str, Any]) -> OtherFinancialRow:
    return OtherFinancialRow(
        row_id=str(raw["id"]),
        request_type=raw["netkar_istek_tipi"],
        debt=to_decimal(raw["debt"]),
        credit=to_decimal(raw["credit"]),
        request_sub_type=raw.get("netkar_istek_alt_tipi"),
        type_text=raw.get("transactionType"),
        order_number=raw.get("orderNumber"),
        payment_order_id=raw.get("paymentOrderId"),
        category=raw.get("netkar_sinif"),
        vat_rate=_optional_decimal(raw.get("netkar_kdv_orani")),
    )


def _parse_claim(raw: Mapping[str, Any]) -> Claim:
    return Claim(
        order_number=raw["orderNumber"],
        items=tuple(
            ClaimItem(
                order_line_item_id=str(claim_item["orderLineItemId"]),
                status=claim_item["claimItemStatus"]["name"],
                returned_to_stock=claim_item.get("netkar_urun_durumu", "stoga_dondu") != "satilamaz",
            )
            for item in raw["items"]
            for claim_item in item["claimItems"]
        ),
    )


def parse_input(raw: Mapping[str, Any]) -> ProfitInput:
    """Altın test `girdi` bloğu -> ProfitInput. `donem` bloğu motoru etkilemez (dönem seçimi çağıranındır)."""
    return ProfitInput(
        settings=parse_settings(raw.get("ayarlar", {})),
        orders=tuple(_parse_order(o) for o in raw["siparisler"]),
        costs=tuple(
            CostRecord(
                barcode=c["barcode"],
                valid_from=date.fromisoformat(c["gecerlilik_baslangic"]),
                unit_cost_excl_vat=to_decimal(c["birim_maliyet_kdv_haric"]),
                vat_rate=to_decimal(c["kdv_orani"]),
            )
            for c in raw.get("urun_maliyetleri", [])
        ),
        catalog_barcodes=tuple(p["barcode"] for p in raw.get("urunler", [])),
        settlements=tuple(_parse_settlement(s) for s in raw.get("settlements", [])),
        other_financials=tuple(_parse_other(o) for o in raw.get("otherfinancials", [])),
        cargo_invoices=tuple(
            CargoInvoice(
                serial_number=str(inv["invoiceSerialNumber"]),
                items=tuple(
                    CargoInvoiceItem(
                        package_type=i["shipmentPackageType"],
                        order_number=i["orderNumber"],
                        amount=to_decimal(i["amount"]),
                        desi=int(i["desi"]),
                    )
                    for i in inv["items"]
                ),
            )
            for inv in raw.get("kargo_faturalari", [])
        ),
        claims=tuple(_parse_claim(c) for c in raw.get("iadeler", [])),
        ad_records=tuple(
            AdRecord(
                record_id=r["kayit_id"],
                start=date.fromisoformat(r["baslangic"]),
                end=date.fromisoformat(r["bitis"]),
                spend=to_decimal(r["harcama"]),
                spend_includes_vat=bool(r.get("harcama_kdv_dahil", False)),
                barcode=r.get("barkod"),
                ad_revenue=_optional_decimal(r.get("reklam_cirosu")),
            )
            for r in raw.get("reklam_kayitlari", [])
        ),
        compensation_tickets=tuple(
            CompensationTicket(
                order_number=t["orderNumber"],
                status=t["status"],
                amount=_optional_decimal(t.get("amount")),
            )
            for t in raw.get("tazminler", [])
        ),
    )


# --------------------------------------------------------------------------- çıktı
def to_wire(value: object) -> Any:
    """Çıktı modelini şema anahtarlarıyla JSON uyumlu yapıya çevirir (Decimal -> iki ondalıklı string)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return fmt(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.metadata.get("wire", f.name): to_wire(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(k): to_wire(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [to_wire(v) for v in value]
    return value


def render_result(result: ProfitResult) -> dict[str, Any]:
    """ProfitResult -> altın test `beklenen` şeması."""
    rendered: dict[str, Any] = to_wire(result)
    return rendered
