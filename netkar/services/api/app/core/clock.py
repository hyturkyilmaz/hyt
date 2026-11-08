"""Zaman kaynağı. Testlerde TOTP zaman adımını sabitlemek için tek noktadan değiştirilebilir."""

from __future__ import annotations

import time
from datetime import date, datetime

from app.profit.schema_v1 import ISTANBUL  # motorla aynı sabit UTC+3 (Türkiye'de yaz saati yok)


def unix_time() -> float:
    """Şimdiki Unix zamanı (saniye)."""
    return time.time()


def today_istanbul() -> date:
    """İstanbul takvim günü (sipariş günü ve maliyet geçerlilik tarihi İstanbul gününe göredir)."""
    return datetime.fromtimestamp(unix_time(), ISTANBUL).date()
