"""Değişmezlik tetikleyicileri için test yardımcıları (sessions 0023; tenants 0024)."""

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


@contextmanager
def tenant_guard_disabled(conn: psycopg.Connection[Any]) -> Iterator[None]:
    """tenants kimlik tetikleyicisini geçici kapatır (created_at kaydırma için), çıkışta ENABLE ALWAYS ile açar."""
    conn.execute("ALTER TABLE tenants DISABLE TRIGGER tenants_immutable_guard")
    try:
        yield
    finally:
        conn.execute("ALTER TABLE tenants ENABLE ALWAYS TRIGGER tenants_immutable_guard")
