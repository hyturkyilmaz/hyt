"""Altın test betiklerinin güvenliği: eski betik tek başına çalıştırılınca G42-G48'i silmez.

`calisma_dosyalari/altin_test_hesap.py` (v0.1) eskiden `tests/golden` altındaki tüm `G*.json` dosyalarını silip
yalnız G01-G41'i yazardı. Artık doğrudan çalıştırılınca yeni betiğe (`altin_test_hesap_ayarlar.py`)
yönlendirilir. Test, betiği ARGÜMANSIZ çalıştırır (yalnız doğrulama, dosya yazmaz) ve dosyaların hiçbirinin
değişmediğini denetler. Betikler deponun `calisma_dosyalari/` klasöründedir (uygulama paketinin dışı).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = API_ROOT.parent.parent / "calisma_dosyalari"
GOLDEN = API_ROOT / "tests" / "golden"


def _digest() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(GOLDEN.glob("G*.json"))}


@pytest.mark.skipif(not SCRIPTS.is_dir(), reason="calisma_dosyalari/ bu ortamda yok (yalnız api paketi)")
def test_old_script_run_alone_redirects_and_keeps_every_golden_file() -> None:
    before = _digest()
    assert len(before) == 48
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "altin_test_hesap.py")],
        capture_output=True,
        text=True,
        cwd=API_ROOT,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "yönlendiriliyor" in result.stderr
    assert "TAMAM" in result.stdout  # yeni betiğin doğrulaması çalıştı
    assert _digest() == before  # hiçbir dosya silinmedi ya da değişmedi


@pytest.mark.skipif(not SCRIPTS.is_dir(), reason="calisma_dosyalari/ bu ortamda yok (yalnız api paketi)")
def test_new_script_verifies_the_golden_files_without_writing() -> None:
    before = _digest()
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "altin_test_hesap_ayarlar.py")],
        capture_output=True,
        text=True,
        cwd=API_ROOT,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TAMAM: tüm kontroller geçti" in result.stdout
    assert _digest() == before
