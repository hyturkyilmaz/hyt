"""Zaman kaynağı. Testlerde TOTP zaman adımını sabitlemek için tek noktadan değiştirilebilir."""

from __future__ import annotations

import time


def unix_time() -> float:
    """Şimdiki Unix zamanı (saniye)."""
    return time.time()
