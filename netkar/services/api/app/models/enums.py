"""Ortak enum tanımları."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Kiracı içi rol."""

    OWNER = "owner"
    ADMIN = "admin"
    VIEWER = "viewer"
