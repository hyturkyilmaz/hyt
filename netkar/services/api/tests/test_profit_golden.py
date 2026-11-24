"""Kâr motoru altın testleri: tests/golden/G*.json senaryoları kuruşu kuruşuna eşleşmeli.

Karşılaştırma kuralları (tests/golden/README.md):
- Para alanları string, iki ondalık, birebir eşit; `null` alanlar `null`.
- `uyarilar` listeleri sıra önemsiz küme olarak karşılaştırılır.
- Motorun ürettiği ek alanlar karşılaştırmayı bozmaz; eksik alan hatadır.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.profit import calculate_profit
from app.profit.schema_v1 import parse_input, render_result

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("G*.json"))


def assert_matches(expected: Any, actual: Any, path: str = "") -> None:
    """`expected` içindeki her alan `actual` içinde birebir bulunmalı (ek alanlar serbest)."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: sözlük bekleniyordu, {actual!r} geldi"
        for key, value in expected.items():
            assert key in actual, f"{path}.{key}: alan eksik"
            assert_matches(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list) and path.endswith(".uyarilar"):
        assert set(expected) == set(actual), f"{path}: {sorted(expected)} != {sorted(actual)}"
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: liste bekleniyordu"
        assert len(expected) == len(actual), f"{path}: uzunluk {len(expected)} != {len(actual)}"
        for index, (exp, act) in enumerate(zip(expected, actual, strict=True)):
            assert_matches(exp, act, f"{path}[{index}]")
    else:
        assert expected == actual, f"{path}: beklenen {expected!r}, gelen {actual!r}"


def test_all_49_scenarios_present() -> None:
    # G01-G41 (v0.1 + v0.2 yeni alanlar), G42-G48 (kâr ayarları, K33-K41) ve G49 (K39 Revizyon 1).
    assert len(GOLDEN_FILES) == 49
    assert [p.name[:4] for p in GOLDEN_FILES] == [f"G{i:02d}_" for i in range(1, 50)]


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_golden_scenario(path: Path) -> None:
    scenario = json.loads(path.read_text(encoding="utf-8"))
    result = render_result(calculate_profit(parse_input(scenario["girdi"])))
    assert_matches(scenario["beklenen"], result, scenario["senaryo_id"])
