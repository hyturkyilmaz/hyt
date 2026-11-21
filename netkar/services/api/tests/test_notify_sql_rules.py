"""SQL yazım kuralı (ADR-0009 D5): `text()` içinde f-string, birleştirme, `%` ve `.format` YOK; düz sabit + bağlı parametre.

İki katman: (1) AST taraması (her zaman koşar; yeni D5 dosyaları ve değerlendirme/worker dosyaları), (2) yerel Semgrep
kuralı `semgrep/sql-text-literal.yml` (semgrep kuruluysa gerçek dosyalarda koşar; kural kendi pozitif örneğini yakalar).
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RULE = ROOT / "semgrep"  # dizin: CI de aynı dizini `--config` olarak alır
SCANNED = (
    "app/services/notify.py",
    "app/services/notify_templates.py",
    "app/services/notify_unsubscribe.py",
    "app/services/alert_evaluation.py",
    "app/api/v1/notify_unsubscribe.py",
    "app/worker/tasks.py",
    "app/worker/queue.py",
    "app/worker/runtime.py",
    "app/core/email.py",
)


def violations(source: str) -> list[str]:
    """`text(...)` / `sqlalchemy.text(...)` çağrılarından ilk argümanı düz dizge sabiti OLMAYANLAR.

    İzinli: dizge sabiti ve modül düzeyinde dizge sabitine atanmış ad (`_SQL = "..."`; `text(_SQL)`).
    """
    tree = ast.parse(source)
    constants = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_text = (isinstance(func, ast.Name) and func.id == "text") or (
            isinstance(func, ast.Attribute)
            and func.attr == "text"
            and isinstance(func.value, ast.Name)
            and func.value.id in {"sa", "sqlalchemy"}
        )
        if not is_text:
            continue
        first = node.args[0] if node.args else None
        literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
        named_constant = isinstance(first, ast.Name) and first.id in constants
        if not (literal or named_constant):
            found.append(f"satır {node.lineno}: text() düz dizge sabiti almıyor")
    return found


@pytest.mark.parametrize("relative", SCANNED)
def test_text_calls_take_plain_literals_only(relative: str) -> None:
    assert violations((ROOT / relative).read_text(encoding="utf-8")) == []


def test_every_python_file_under_app_takes_plain_literals_only() -> None:
    files = sorted((ROOT / "app").rglob("*.py"))
    assert len(files) > 50  # tarama boş değil
    offenders = {
        str(f.relative_to(ROOT)): found for f in files if (found := violations(f.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_the_scan_is_not_vacuous_and_the_checker_catches_every_unsafe_form() -> None:
    notify = (ROOT / "app/services/notify.py").read_text(encoding="utf-8")
    assert notify.count("text(") >= 15  # dağıtıcı SQL'i gerçekten text() sabitleriyle yazılmış
    bad = {
        "f-string": 'text(f"SELECT * FROM t WHERE a = {x}")',
        "birleştirme": 'text("SELECT * FROM t WHERE a = " + x)',
        "yüzde": 'text("SELECT %s" % x)',
        "format": 'text("SELECT {}".format(x))',
        "değişken": "text(query)",
        "nitelikli": 'sqlalchemy.text(f"SELECT {x}")',
        "bağsız": "text()",
    }
    for name, snippet in bad.items():
        assert violations(f"import sqlalchemy\nfrom sqlalchemy import text\nx = 1\nr = {snippet}\n"), name
    good = 'text("SELECT a FROM t WHERE b = :b " "AND c = :c")'  # örtük birleştirme tek sabittir
    assert violations(f"from sqlalchemy import text\nr = {good}\n") == []


def test_bound_parameters_are_used_for_every_value_in_the_dispatcher_sql() -> None:
    """Sabit SQL'de kullanıcı/kiracı değerleri yalnız `:ad` yer tutucusuyla gelir (sabit dizgelerde `%s` ya da `{}` yok)."""
    tree = ast.parse((ROOT / "app/services/notify.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "text":
            literal = node.args[0]
            assert isinstance(literal, ast.Constant) and isinstance(literal.value, str)
            assert "%s" not in literal.value and "{" not in literal.value, literal.value[:60]


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep kurulu değil (CI'da uvx ile koşar)")
def test_local_semgrep_rule_passes_on_real_files_and_flags_a_bad_sample(tmp_path: Path) -> None:
    command = [
        "semgrep",
        "scan",
        "--config",
        str(RULE),
        "--error",
        "--metrics=off",
        "--quiet",
        "--disable-version-check",
    ]
    ok = subprocess.run(
        [*command, str(ROOT / "app")],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    sample = tmp_path / "bad.py"
    sample.write_text('from sqlalchemy import text\nx = 1\nr = text(f"SELECT {x}")\n', encoding="utf-8")
    variable = tmp_path / "variable.py"  # `text(degisken)` (kaynağı bilinmeyen) biçimi de yakalanır
    variable.write_text(
        "from sqlalchemy import text\n\n\ndef run(query):\n    return text(query)\n", encoding="utf-8"
    )
    assert (
        subprocess.run(
            [*command, str(variable)], capture_output=True, text=True, timeout=300, check=False
        ).returncode
        != 0
    )
    bad = subprocess.run([*command, str(sample)], capture_output=True, text=True, timeout=300, check=False)
    assert bad.returncode != 0
