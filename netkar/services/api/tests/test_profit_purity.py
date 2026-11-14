"""Kâr motoru saflık güvenceleri: I/O, saat, rastgelelik ve float yok; em dash yok; girdi değişmez."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from app.profit import calculate_profit
from tests.profit_helpers import data, line, order, sale

PROFIT_DIR = Path(__file__).resolve().parent.parent / "app" / "profit"
SOURCES = sorted(PROFIT_DIR.glob("*.py"))
FORBIDDEN_IMPORTS = {
    "sqlalchemy", "psycopg", "httpx", "requests", "socket", "urllib", "http", "asyncio", "os", "sys",
    "subprocess", "random", "secrets", "time", "pathlib", "fastapi", "app.db", "app.core", "app.integrations",
}  # fmt: skip


def imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_io_clock_or_randomness_imports(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module in imported_modules(tree):
        assert module.split(".")[0] not in FORBIDDEN_IMPORTS, f"{path.name}: yasak içe aktarma {module}"
        assert module not in FORBIDDEN_IMPORTS, f"{path.name}: yasak içe aktarma {module}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_wall_clock_calls(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"now", "today", "utcnow", "time"}:
            raise AssertionError(f"{path.name}:{node.lineno}: saat okuması yasak ({node.attr})")


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_float_and_no_em_dash(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert chr(0x2014) not in text, f"{path.name}: em dash yasak"
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            raise AssertionError(f"{path.name}:{node.lineno}: float sabiti yasak")
        if isinstance(node, ast.Name) and node.id == "float":
            # money.to_decimal float'ı yalnız reddetmek için anar
            assert path.name == "money.py", f"{path.name}:{node.lineno}: float kullanımı yasak"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
            raise AssertionError(f"{path.name}:{node.lineno}: float() yasak")


def test_input_is_not_mutated_and_result_is_frozen() -> None:
    ln = line()
    o = order([ln])
    inputs = data([o], settlements=(sale(o, ln),))
    snapshot = repr(inputs)
    result = calculate_profit(inputs)
    assert repr(inputs) == snapshot
    assert calculate_profit(inputs) == result
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.period.line_count = 5  # type: ignore[misc]
