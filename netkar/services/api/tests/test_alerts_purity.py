"""app/alerts saflık güvenceleri (ADR-0009 §3, test listesi madde 6): I/O, saat, float ve math yok; girdi değişmez."""

from __future__ import annotations

import ast
import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.alerts import (
    AlertThresholds,
    ReturnCohort,
    evaluate_ad_eats_profit,
    evaluate_loss_making_sales,
    evaluate_return_rate,
    evaluate_unexpected_deduction,
)
from app.profit.enums import WarningCode
from app.profit.inputs import AdRecord
from tests.alerts_helpers import make_comparison, make_line, make_product, make_result
from tests.test_profit_purity import FORBIDDEN_IMPORTS, imported_modules

ALERTS_DIR = Path(__file__).resolve().parent.parent / "app" / "alerts"
SOURCES = sorted(ALERTS_DIR.glob("*.py"))
EXTRA_FORBIDDEN = {"math", "datetime.now"}
ACC = "6f1c2b9e-3d4a-4c5b-8e7f-0a1b2c3d4e5f"
FORBIDDEN_KEYS = {"email", "name", "address", "phone", "customer", "customer_id"}


def test_sources_exist() -> None:
    assert {p.name for p in SOURCES} >= {"rules.py", "stats.py", "types.py", "settings.py", "suppression.py"}


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_io_math_clock_or_float(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert chr(0x2014) not in text, f"{path.name}: em dash yasak"
    assert chr(0x2015) not in text, f"{path.name}: U+2015 yasak"
    tree = ast.parse(text)
    for module in imported_modules(tree):
        root = module.split(".")[0]
        assert root not in FORBIDDEN_IMPORTS | EXTRA_FORBIDDEN, f"{path.name}: yasak içe aktarma {module}"
        assert not module.startswith("app.db"), f"{path.name}: veritabanı içe aktarması {module}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"now", "today", "utcnow", "time"}:
            raise AssertionError(f"{path.name}:{node.lineno}: saat okuması yasak ({node.attr})")
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            raise AssertionError(f"{path.name}:{node.lineno}: float sabiti yasak")
        if isinstance(node, ast.Name) and node.id in {"float", "sqrt"}:
            raise AssertionError(f"{path.name}:{node.lineno}: float/karekök yasak")
        if isinstance(node, ast.Attribute) and node.attr == "sqrt":
            raise AssertionError(f"{path.name}:{node.lineno}: karekök yasak")


def test_rules_do_not_mutate_inputs_and_are_deterministic() -> None:
    result = make_result(
        (
            make_line("A", "-9.00", line_id=1),
            make_line(
                "B",
                "5.00",
                warnings=(WarningCode.UNEXPECTED_DEDUCTION,),
                comparison=make_comparison("12.00"),
                line_id=2,
            ),  # type: ignore[arg-type]
        ),
        (make_product("A", "0.00", "80.00"),),
    )
    cohorts = [
        ReturnCohort(barcode="A", current_lines=100, current_returned=20, base_lines=200, base_returned=10)
    ]
    records = (AdRecord("AD1", date(2026, 10, 1), date(2026, 10, 31), Decimal("1.00"), False),)
    t = AlertThresholds()
    snapshot = (dataclasses.astuple(result.lines[0].items), tuple(cohorts))

    def run_all() -> list[object]:
        return [
            evaluate_loss_making_sales(ACC, result, t),
            evaluate_ad_eats_profit(ACC, result, records, t),
            evaluate_unexpected_deduction(ACC, result, t),
            evaluate_return_rate(ACC, date(2026, 11, 20), cohorts, t),
        ]

    first, second = run_all(), run_all()
    assert first == second
    assert snapshot == (dataclasses.astuple(result.lines[0].items), tuple(cohorts))
    # Her aday: kanıt anahtarlarında kişisel veri yok; kanıt salt okunur.
    for outcome in first:
        for cand in outcome.candidates:  # type: ignore[attr-defined]
            assert not (set(cand.evidence) & FORBIDDEN_KEYS)
            with pytest.raises(TypeError):
                cand.evidence["x"] = 1  # type: ignore[index]
            with pytest.raises(dataclasses.FrozenInstanceError):
                cand.subject = "x"
