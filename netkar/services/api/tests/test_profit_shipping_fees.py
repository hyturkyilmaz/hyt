"""Kargo, platform hizmet bedeli, ceza, erken ödeme, stopaj ve sınıflandırılamayan kesinti (K08-K14, K18, K19)."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.profit import calculate_profit
from app.profit.enums import InvoiceVatStatus, Source, Status, WarningCode
from app.profit.inputs import CargoInvoice, CargoInvoiceItem, OtherFinancialRow
from app.profit.settings import CargoTariff
from tests.profit_helpers import D, data, line, make_settings, order, other, ret, sale

OUT = "Gönderi Kargo Bedeli"
BACK = "İade Kargo Bedeli"


def invoice(serial: str, *items: tuple[str, str, str, int]) -> CargoInvoice:
    return CargoInvoice(serial, tuple(CargoInvoiceItem(t, n, D(a), d) for t, n, a, d in items))


def statement(serial: str, debt: str) -> OtherFinancialRow:
    return other("DeductionInvoices", debt=debt, row_id=serial, type_text="Kargo Faturası")


# --------------------------------------------------------------------------- tahmini kargo (K08)
def test_cargo_tariff_lookup_edges() -> None:
    tariff = CargoTariff.unversioned({"X": ((D("1"), D("10")), (D("3"), D("20")))})
    day = date(2026, 10, 5)
    assert tariff.lookup("X", D("1"), day) == D("10")
    assert tariff.lookup("X", D("1.5"), day) == D("20")
    assert tariff.lookup("X", D("3.01"), day) is None  # basamak aşıldı
    assert tariff.lookup("X", None, day) is None
    assert tariff.lookup("Y", D("1"), day) is None
    assert CargoTariff().lookup("X", D("1"), day) is None


def test_estimated_desi_prefers_cargo_deci_then_ceil_of_deci() -> None:
    by_deci = calculate_profit(data([order(cargo_deci=None, deci="1.2")])).lines[0]
    assert by_deci.items.shipping_outbound == D("45.00")  # ceil(1,2) = 2
    both = calculate_profit(data([order(cargo_deci="1", deci="4.0")])).lines[0]
    assert both.items.shipping_outbound == D("40.00")


def test_missing_tariff_marks_source_and_warns() -> None:
    no_desi = calculate_profit(data([order(cargo_deci=None)])).lines[0]
    assert no_desi.sources.shipping_outbound is Source.MISSING
    assert WarningCode.CARGO_TARIFF_MISSING in no_desi.warnings
    assert no_desi.items.shipping_outbound == D("0.00")
    too_big = calculate_profit(data([order(cargo_deci="99")])).lines[0]
    assert too_big.sources.shipping_outbound is Source.MISSING
    no_tariff = calculate_profit(data([order()], settings=make_settings(cargo_tariff=CargoTariff()))).lines[0]
    assert WarningCode.CARGO_TARIFF_MISSING in no_tariff.warnings


def test_seller_agreement_uses_seller_tariff_and_stays_off_trendyol_payout() -> None:
    o = order(carrier="Aras", who_pays=1)
    inv = invoice("S1", (OUT, "O1", "54.00", 2))
    r = calculate_profit(
        data([o], cargo_invoices=(inv,), other_financials=(statement("S1", "54.00"),))
    ).lines[0]
    assert r.sources.shipping_outbound is Source.USER
    assert r.items.shipping_outbound == D("38.00")  # fatura kalemi yok sayılır
    assert r.cash_flow.invoice_deductions_incl_vat == D("12.00")  # yalnız hizmet bedeli (10 + 2)


def test_seller_agreement_without_tariff_is_missing() -> None:
    o = order(carrier="Unknown", who_pays=1)
    r = calculate_profit(data([o])).lines[0]
    assert r.sources.shipping_outbound is Source.MISSING


# --------------------------------------------------------------------------- fatura KDV tespiti
def test_invoice_vat_detection() -> None:
    o = order()
    cases = {
        "dahil": ("54.00", "54.00", InvoiceVatStatus.INCLUDED),
        "haric": ("45.00", "54.00", InvoiceVatStatus.EXCLUDED),
        "bilinmiyor": ("45.00", "100.00", InvoiceVatStatus.UNKNOWN),
    }
    for amount, debt, expected in cases.values():
        result = calculate_profit(
            data(
                [o],
                cargo_invoices=(invoice("S1", (OUT, "O1", amount, 2)),),
                other_financials=(statement("S1", debt),),
            )
        )
        assert result.cargo_invoice_vat_status == {"S1": expected}
    no_statement = calculate_profit(data([o], cargo_invoices=(invoice("S2", (OUT, "O1", "54.00", 2)),)))
    assert no_statement.cargo_invoice_vat_status == {"S2": InvoiceVatStatus.UNKNOWN}


def test_uncertain_invoice_is_treated_as_excluded_and_warns() -> None:
    o = order()
    result = calculate_profit(
        data(
            [o],
            cargo_invoices=(invoice("S1", (OUT, "O1", "50.00", 2)),),
            other_financials=(statement("S1", "999.00"),),
        )
    )
    r = result.lines[0]
    assert r.items.shipping_outbound == D("50.00")
    assert r.vat.shipping_vat == D("10.00")
    assert WarningCode.CARGO_INVOICE_VAT_UNCERTAIN in r.warnings
    assert r.sources.shipping_outbound is Source.ACTUAL


# --------------------------------------------------------------------------- desi farkı ve çok paketli sipariş
def test_desi_mismatch_warning_rules() -> None:
    def run(cargo_deci: str | None, invoice_desi: int) -> tuple[WarningCode, ...]:
        o = order(cargo_deci=cargo_deci)
        return (
            calculate_profit(
                data(
                    [o],
                    cargo_invoices=(invoice("S1", (OUT, "O1", "54.00", invoice_desi)),),
                    other_financials=(statement("S1", "54.00"),),
                )
            )
            .lines[0]
            .warnings
        )

    assert WarningCode.CARGO_DESI_MISMATCH in run("2", 5)
    assert WarningCode.CARGO_DESI_MISMATCH not in run("2", 2)
    assert WarningCode.CARGO_DESI_MISMATCH not in run(None, 5)  # tahmini desi yok: karşılaştırma yok


def test_multi_package_order_invoice_is_distributed_once() -> None:
    a, b = line(price="100.00"), line(barcode="B2", price="300.00")
    o1 = order([a], number="O1")
    o2 = order([b], number="O1")
    inv = invoice("S1", (OUT, "O1", "120.00", 4))
    result = calculate_profit(
        data([o1, o2], cargo_invoices=(inv,), other_financials=(statement("S1", "120.00"),))
    )
    total = sum((r.items.shipping_outbound for r in result.lines), D(0))
    vat = sum((r.vat.shipping_vat for r in result.lines), D(0))
    assert total == D("100.00")  # 120 KDV dahil: bir kez
    assert vat == D("20.00")
    # satış oranıyla (1:3) dağıtılır
    assert [r.items.shipping_outbound for r in result.lines] == [D("25.00"), D("75.00")]
    # iki paketin tahmini desisi 2 + 2 = 4: fark yok
    assert all(WarningCode.CARGO_DESI_MISMATCH not in r.warnings for r in result.lines)


def test_invoice_for_cancelled_or_seller_paid_orders_is_ignored() -> None:
    cancelled = order([line()], number="O1", status="Cancelled")
    inv = invoice("S1", (OUT, "O1", "54.00", 2))
    result = calculate_profit(data([cancelled], cargo_invoices=(inv,)))
    assert result.lines[0].items.shipping_outbound == D("0.00")


def test_weights_use_unit_desi_when_all_lines_have_it() -> None:
    a, b = line(price="100.00", desi="2"), line(barcode="B2", price="100.00", qty=1, desi="3")
    o = order([a, b], cargo_deci="5")
    r1, r2 = calculate_profit(data([o])).lines
    assert (r1.items.shipping_outbound, r2.items.shipping_outbound) == (D("24.00"), D("36.00"))  # 60: 2:3


# --------------------------------------------------------------------------- iade kargosu (K12)
def test_return_shipping_goes_to_refunded_lines_else_all_active() -> None:
    a, b = line(price="100.00"), line(barcode="B2", price="100.00")
    o = order([a, b])
    inv = invoice("S1", (BACK, "O1", "54.00", 2))
    rows = (sale(o, a), sale(o, b), ret(o, b, "100.00"))
    only_b = calculate_profit(
        data([o], settlements=rows, cargo_invoices=(inv,), other_financials=(statement("S1", "54.00"),))
    )
    ra, rb = only_b.lines
    assert (ra.items.shipping_return, rb.items.shipping_return) == (D("0.00"), D("45.00"))
    assert rb.sources.shipping_return is Source.ACTUAL
    assert rb.status is Status.ADJUSTED
    no_refund = calculate_profit(
        data([o], cargo_invoices=(inv,), other_financials=(statement("S1", "54.00"),))
    )
    assert [r.items.shipping_return for r in no_refund.lines] == [D("22.50"), D("22.50")]


def test_return_invoice_for_cancelled_order_is_ignored() -> None:
    o = order([line()], status="Cancelled")
    inv = invoice("S1", (BACK, "O1", "54.00", 2))
    assert calculate_profit(data([o], cargo_invoices=(inv,))).lines[0].items.shipping_return == D("0.00")


# --------------------------------------------------------------------------- platform hizmet bedeli (K13)
def psf(debt: str, **kw: Any) -> OtherFinancialRow:
    return other("DeductionInvoices", debt=debt, request_sub_type="PlatformServiceFee", **kw)


def test_service_fee_by_order_number() -> None:
    o = order([line()])
    r = calculate_profit(data([o], other_financials=(psf("24.00", order_number="O1"),))).lines[0]
    assert r.items.platform_service_fee == D("20.00")
    assert r.vat.platform_service_fee_vat == D("4.00")
    assert r.sources.platform_service_fee is Source.ACTUAL_ALLOCATED


def test_service_fee_by_payment_order_is_split_equally_across_paid_orders() -> None:
    ln1, ln2, ln3 = line(), line(barcode="B2"), line(barcode="B3")
    o1, o2, o3 = order([ln1], number="O1"), order([ln2], number="O2"), order([ln3], number="O3")
    rows = (
        sale(o1, ln1, payment_order_id=7),
        sale(o2, ln2, payment_order_id=7),
        sale(o3, ln3, payment_order_id=8),
    )
    fee = psf("40.00", payment_order_id=7)
    result = calculate_profit(data([o1, o2, o3], settlements=rows, other_financials=(fee,)))
    first, second, third = result.lines
    assert first.items.platform_service_fee == D("16.67")
    assert second.items.platform_service_fee == D("16.66")  # 33,33 iki siparişe: 16,67 / 16,66
    assert first.vat.platform_service_fee_vat + second.vat.platform_service_fee_vat == D("6.67")
    assert third.items.platform_service_fee == D("10.00")  # ödeme emri 8: tahmini kalır
    assert third.sources.platform_service_fee is Source.ESTIMATED
    assert first.comparison is not None
    assert first.comparison.platform_service_fee_actual == D("16.67")


def test_unassignable_service_fee_becomes_unclassified_period_expense() -> None:
    o = order([line()])
    cancelled = order([line(barcode="B9")], number="O9", status="Cancelled")
    fees = (
        psf("12.00", order_number="UNKNOWN"),
        psf("12.00", order_number="O9"),  # tüm satırları iptal
        psf("6.00", payment_order_id=None),
        psf("6.00", payment_order_id=555),  # eşleşen satış yok
    )
    result = calculate_profit(data([o, cancelled], other_financials=fees))
    assert result.period.period_level_expenses.unclassified_deduction == D("36.00")
    assert result.period.warnings.count(WarningCode.UNCLASSIFIED_DEDUCTION) == 1
    assert result.lines[0].items.platform_service_fee == D("10.00")


def test_service_fee_refund_is_negative_expense() -> None:
    o = order([line()])
    fee = psf("0", credit="12.00", order_number="O1")
    r = calculate_profit(data([o], other_financials=(fee,))).lines[0]
    assert r.items.platform_service_fee == D("-10.00")


def test_cancelled_order_gets_no_estimated_service_fee() -> None:
    o = order([line()], status="Cancelled")
    assert calculate_profit(data([o])).lines[0].items.platform_service_fee == D("0.00")


# --------------------------------------------------------------------------- diğer finansallar (K14, K18, K19)
def test_other_financials_classification() -> None:
    o = order([line(price="100.00")], number="O1")
    rows = (
        other("Stoppage", debt="1.00", credit="0.20"),
        other("CashAdvance", credit="1000.00", debt="0"),
        other("PaymentOrder", credit="500.00"),
        other("WireTransfer", debt="300.00"),
        other("IncomingTransfer", credit="300.00"),
        other("DeductionInvoices", debt="54.00", type_text="Kargo Fatura"),
        other("DeductionInvoices", debt="120.00", category="erken_odeme_bedeli", vat_rate=D("20")),
        other("DeductionInvoices", debt="5.00", category="erken_odeme_bedeli"),
        other("DeductionInvoices", debt="60.00", category="ceza", vat_rate=D("20")),  # bağsız
        other("DeductionInvoices", debt="7.00", category="ceza", order_number="NOPE"),
        other("FinancialItem", debt="17.35"),
        other("FinancialItem", debt="0.65", credit="0"),
    )
    result = calculate_profit(data([o], other_financials=rows))
    period = result.period
    assert period.cash_flow.withholding_statement == D("0.80")
    assert period.cash_flow.early_payment_cash_in == D("1000.00")
    expenses = period.period_level_expenses
    assert expenses.early_payment_fee == D("105.00")  # 100,00 + 5,00 (KDV'siz)
    assert expenses.undistributed_penalty == D("57.00")  # 50,00 + 7,00
    assert expenses.unclassified_deduction == D("18.00")
    assert period.warnings.count(WarningCode.UNCLASSIFIED_DEDUCTION) == 1
    # stopaj, erken ödeme nakit girişi ve nakit hareketleri satır kârına girmez
    assert result.lines[0].items.penalty == D("0.00")
    # K39 Revizyon 1: bu senaryoda satırın eksik kalemi varsa dönem net kârı null, bilinen kısım ayrı alandadır.
    line_known = result.lines[0].items.known_expenses_profit
    assert period.period_known_expenses_profit == line_known - D("105.00") - D("57.00") - D("18.00")
    if period.net_profit_partial:
        assert period.period_net_profit is None
    else:
        assert period.period_net_profit == period.period_known_expenses_profit
    # 0,80 ekstre, 0,83 hesaplanan: fark 0,03 yuvarlama toleransı içinde
    assert WarningCode.WITHHOLDING_STATEMENT_DIFF not in period.warnings


def test_withholding_statement_difference_warning() -> None:
    o = order([line(price="100.00")])
    far = calculate_profit(data([o], other_financials=(other("Stoppage", debt="5.00"),)))
    assert WarningCode.WITHHOLDING_STATEMENT_DIFF in far.period.warnings
    none = calculate_profit(data([o]))
    assert WarningCode.WITHHOLDING_STATEMENT_DIFF not in none.period.warnings
