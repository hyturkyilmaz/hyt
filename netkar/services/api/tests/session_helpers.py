"""sessions değişmezlik tetikleyicisi için test yardımcıları (0023)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg


@contextmanager
def session_guard_disabled(conn: psycopg.Connection[Any]) -> Iterator[None]:
    """Tetikleyiciyi geçici kapatır (zaman kaydırma için), çıkışta ENABLE ALWAYS ile geri açar."""
    conn.execute("ALTER TABLE sessions DISABLE TRIGGER sessions_immutable_guard")
    try:
        yield
    finally:
        conn.execute("ALTER TABLE sessions ENABLE ALWAYS TRIGGER sessions_immutable_guard")
