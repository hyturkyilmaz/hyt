"""JSON log biçimi ve hassas veri maskeleme filtresi."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

MASK = "***"

# Anahtar adında bu parçalardan biri geçiyorsa değer maskelenir.
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "parola",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "api-key",
    "email",
    "e_mail",
    "totp",
    "csrf",
    "trendyol",
    "credential",
    "private_key",
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_AUTH_SCHEME_RE = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]+", re.IGNORECASE)
_HOST_COOKIE_RE = re.compile(r"(__Host-|__Secure-)[\w\-]+=[^;\s,]+")
_COOKIE_HEADER_RE = re.compile(r"(?i)\b(set-cookie|cookie)(\s*[=:]\s*)[^\r\n]+")
_KV_RE = re.compile(
    r"(?i)\b(password|passwd|parola|secret|token|api[_-]?key|api[_-]?secret|authorization|cookie|set-cookie|"
    r"totp[_-]?secret|csrf[_-]?token|x-csrf-token)\b(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)

_STANDARD_ATTRS = frozenset(logging.LogRecord("x", 0, "x", 0, "x", (), None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def mask_text(text: str) -> str:
    """Serbest metindeki e-posta, token, parola ve çerez değerlerini maskeler."""
    text = _COOKIE_HEADER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    text = _AUTH_SCHEME_RE.sub(lambda m: f"{m.group(1)} {MASK}", text)
    text = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    text = _HOST_COOKIE_RE.sub(lambda m: f"{m.group(1)}{MASK}", text)
    return _EMAIL_RE.sub(MASK, text)


def mask_value(value: Any, key: str | None = None) -> Any:
    """İç içe yapılarda anahtar adına ve değer desenine göre maskeleme yapar."""
    if key is not None and _is_sensitive_key(key):
        return MASK
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {str(k): mask_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [mask_value(v) for v in value]
    return value


class MaskingFilter(logging.Filter):
    """Mesajı ve ek alanları maskeler; istisna metnini de temizler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_text(record.getMessage())
        record.args = ()
        for key in list(record.__dict__.keys()):
            if key not in _STANDARD_ATTRS:
                record.__dict__[key] = mask_value(record.__dict__[key], key)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = mask_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = mask_text(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    """Her kaydı tek satır JSON olarak yazar."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                data[key] = value
        if record.exc_text:
            data["exc"] = record.exc_text
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Kök logger'ı JSON + maskeleme ile yeniden kurar (idempotent)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(MaskingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn erişim logu sorgu dizesi taşıyabilir; kendi ara katmanımız yazar.
    logging.getLogger("uvicorn.access").disabled = True
