"""Senkron hata sınıflandırması (ADR-0005 §5).

Hata sınıfı kısa bir metin belirteçtir; `sync_runs.error_class` sütununa ve loga YALNIZ bu yazılır.
Hata iletisi, yanıt gövdesi veya veritabanı ayrıntısı yazılmaz: Trendyol hataları gövde taşımaz ama
veritabanı hata iletileri satır değeri içerebilir.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.trendyol import (
    TrendyolAuthError,
    TrendyolError,
    TrendyolForbiddenError,
    TrendyolNetworkError,
    TrendyolProtocolError,
    TrendyolRateLimitedError,
    TrendyolRequestError,
    TrendyolServerError,
    TrendyolValidationError,
    TrendyolWindowTooLargeError,
)


class SyncTransientError(Exception):
    """Geçici hata: iş procrastinate tarafından geri çekilmeyle yeniden denenir.

    İlerleme imleçlerde saklıdır; yeniden deneme kaldığı yerden devam eder.
    """


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """Hatanın sınıfı ve nasıl ele alınacağı."""

    error_class: str
    # Yeniden denenmeye değer geçici hata (429, 5xx, ağ).
    transient: bool = False
    # 401/403: anahtar geçersiz veya yetkisiz; hesap `invalid` yapılır ve senkron durur.
    auth: bool = False


def classify_error(exc: BaseException) -> ErrorInfo:
    """İstisnayı hata sınıfına çevirir. Sıra önemlidir (alt sınıflar önce)."""
    if isinstance(exc, TrendyolAuthError):
        return ErrorInfo("unauthorized", auth=True)
    if isinstance(exc, TrendyolForbiddenError):
        return ErrorInfo("forbidden", auth=True)
    if isinstance(exc, TrendyolRateLimitedError):  # TrendyolWaitBudgetError dahil
        return ErrorInfo("rate_limited", transient=True)
    if isinstance(exc, TrendyolServerError):
        return ErrorInfo("server_error", transient=True)
    if isinstance(exc, TrendyolNetworkError):
        return ErrorInfo("network", transient=True)
    if isinstance(exc, TrendyolWindowTooLargeError):
        return ErrorInfo("window_too_large")
    if isinstance(exc, TrendyolProtocolError):
        return ErrorInfo("protocol")
    if isinstance(exc, TrendyolRequestError):
        return ErrorInfo("request_rejected")
    if isinstance(exc, TrendyolValidationError):
        return ErrorInfo("validation")
    if isinstance(exc, TrendyolError):
        return ErrorInfo("trendyol")
    return ErrorInfo("internal")
