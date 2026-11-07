"""Kâr motoru testleri için küçük girdi kurucuları (sentetik senaryolar; gerçek veri değildir)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from itertools import count
from typing import Any

from app.profit import ProfitInput, ProfitSettings
from app.profit.inputs import (
    Order,
    OrderItem,
    OrderLine,
    OtherFinancialRow,
    SettlementRow,
)
from app.profit.settings import CargoTariff

D = Decimal
_ids = count(1)

TARIFF = CargoTariff({"Trendyol Express": ((D("1"), D("40.00")), (D("2"), D("45.00")), (D("5"), D("60.00")))})
SELLER_TARIFF = CargoTariff({"Aras": ((D("2"), D("38.00")),)})


def make_settings(**overrides: Any) -> ProfitSettings:
    """Tarifesi ve hizmet bedeli tahmini dolu test ayarları."""
    base: dict[str, Any] = {
        "cargo_tariff": TARIFF,
        "seller_cargo_tariff": SELLER_TARIFF,
        "estimated_service_fee_per_order_excl_vat": D("10.00"),
    }
    base.update(overrides)
    return ProfitSettings(**base)


def line(
    barcode: str = "B1",
    price: str = "100.00",
    qty: int = 1,
    vat: str = "20",
    commission: str = "10",
    seller_discount: str = "0.00",
    ty_discount: str = "0.00",
    desi: str | None = None,
) -> OrderLine:
    line_id = next(_ids)
    return OrderLine(
        line_id=line_id,
        barcode=barcode,
        quantity=qty,
        unit_gross=D(price),
        vat_rate=D(vat),
        commission_rate=D(commission),
        items=tuple(OrderItem(f"item-{line_id}-{i}", D(seller_discount), D(ty_discount)) for i in range(qty)),
        unit_desi=None if desi is None else D(desi),
    )


def order(
    lines: list[OrderLine] | None = None,
    number: str = "O1",
    day: date = date(2026, 10, 5),
    status: str = "Delivered",
    carrier: str = "Trendyol Express",
    cargo_deci: str | None = "2",
    deci: str | None = None,
    who_pays: int | None = None,
    package_id: int | None = None,
) -> Order:
    return Order(
        order_number=number,
        package_id=package_id if package_id is not None else next(_ids),
        order_day=day,
        status=status,
        carrier=carrier,
        lines=tuple(lines if lines is not None else [line()]),
        cargo_deci=None if cargo_deci is None else D(cargo_deci),
        deci=None if deci is None else D(deci),
        who_pays=who_pays,
    )


def sale(o: Order, ln: OrderLine, credit: str | None = None, **kw: Any) -> SettlementRow:
    """Sale satırı; credit verilmezse satırın brüt - satıcı indirimi tutarı, komisyon tam hassasiyetle."""
    amount = (
        D(credit)
        if credit is not None
        else ln.unit_gross * ln.quantity - sum((i.seller_discount for i in ln.items), D(0))
    )
    kw.setdefault("commission_amount", amount * ln.commission_rate / 100)
    kw.setdefault("commission_rate", ln.commission_rate)
    kw.setdefault("seller_revenue", amount - kw["commission_amount"])
    return SettlementRow(
        row_id=f"fin-{next(_ids)}",
        request_type=kw.pop("request_type", "Sale"),
        order_number=o.order_number,
        barcode=ln.barcode,
        debt=kw.pop("debt", D("0")),
        credit=amount,
        package_id=kw.pop("package_id", o.package_id),
        payment_order_id=kw.pop("payment_order_id", 1),
        **kw,
    )


def ret(o: Order, ln: OrderLine, debt: str, request_type: str = "Return", **kw: Any) -> SettlementRow:
    """İade türü satır (debt = iade tutarı); komisyon iade tutarı üzerinden geri yazılır."""
    amount = D(debt)
    commission = amount * ln.commission_rate / 100
    return SettlementRow(
        row_id=f"fin-{next(_ids)}",
        request_type=request_type,
        order_number=o.order_number,
        barcode=ln.barcode,
        debt=amount,
        credit=D("0"),
        package_id=o.package_id,
        commission_amount=kw.pop("commission_amount", commission),
        commission_rate=ln.commission_rate,
        seller_revenue=kw.pop("seller_revenue", amount - commission),
        payment_order_id=1,
        **kw,
    )


def other(request_type: str, debt: str = "0", credit: str = "0", **kw: Any) -> OtherFinancialRow:
    return OtherFinancialRow(
        row_id=kw.pop("row_id", f"oth-{next(_ids)}"),
        request_type=request_type,
        debt=D(debt),
        credit=D(credit),
        **kw,
    )


def data(orders: list[Order], **kw: Any) -> ProfitInput:
    kw.setdefault("settings", make_settings())
    return ProfitInput(orders=tuple(orders), **kw)
