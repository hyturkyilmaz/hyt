"""Sağlık uç noktaları."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.v1.schemas import StatusResponse
from app.core.errors import ProblemError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=StatusResponse)
async def health() -> StatusResponse:
    """Canlılık: veritabanına dokunmaz."""
    return StatusResponse(status="ok")


@router.get("/ready", response_model=StatusResponse)
async def ready(request: Request) -> StatusResponse:
    """Hazırlık: veritabanına basit sorgu atar. Hata ayrıntısı istemciye verilmez."""
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("hazırlık denetimi başarısız")
        raise ProblemError(503, "Hizmet kullanılamıyor", "not-ready") from None
    return StatusResponse(status="ready")
