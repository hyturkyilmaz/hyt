"""Log maskeleme filtresi ve JSON biçimi."""

from __future__ import annotations

import io
import json
import logging

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.logging import MASK, JsonFormatter, MaskingFilter, configure_logging, mask_text, mask_value


@pytest.fixture
def stream_logger() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(MaskingFilter())
    logger = logging.getLogger("netkar.test.masking")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, stream


def test_message_values_are_masked(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = stream_logger
    logger.info("giriş denendi kullanici=ali.veli@example.com password=Cok-Gizli-123 token=abcDEF123456")
    logger.info("başlık Authorization: Bearer eyJhbGciOi.payload.sig ve %s", "Basic dXNlcjpwYXNz")
    logger.info("cookie __Host-nk_session=SECRETVALUE123; yol=/v1")
    logger.info("Cookie: a=ILKCEREZ; b=IKINCICEREZ")
    out = stream.getvalue()
    for leaked in (
        "ali.veli",
        "Cok-Gizli-123",
        "abcDEF123456",
        "eyJhbGciOi",
        "dXNlcjpwYXNz",
        "SECRETVALUE123",
        "ILKCEREZ",
        "IKINCICEREZ",
    ):
        assert leaked not in out
    assert MASK in out


def test_extra_fields_are_masked_by_key(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = stream_logger
    logger.info(
        "istek",
        extra={
            "email": "kisi@example.com",
            "api_key": "TY-KEY-123",
            "trendyol_api_secret": "TY-SECRET-456",
            "authorization": "Bearer abc",
            "cookie": "__Host-nk_session=zzz",
            "headers": {"X-CSRF-Token": "csrfdeger", "Accept": "application/json"},
            "status": 200,
        },
    )
    record = json.loads(stream.getvalue())
    assert record["email"] == record["api_key"] == record["trendyol_api_secret"] == MASK
    assert record["authorization"] == record["cookie"] == MASK
    assert record["headers"] == {"X-CSRF-Token": MASK, "Accept": "application/json"}
    assert record["status"] == 200


def test_exception_text_is_masked(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = stream_logger
    try:
        raise ValueError("kullanıcı kisi@example.com parola=Gizli-Parola-99 reddedildi")
    except ValueError:
        logger.exception("hata")
    out = stream.getvalue()
    assert "kisi@example.com" not in out and "Gizli-Parola-99" not in out
    assert json.loads(out)["level"] == "ERROR"


def test_output_is_single_line_json(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = stream_logger
    logger.warning("merhaba %s", "dünya")
    line = stream.getvalue().strip()
    assert "\n" not in line
    data = json.loads(line)
    assert data["msg"] == "merhaba dünya" and data["level"] == "WARNING" and "ts" in data


def test_mask_value_handles_nested_structures() -> None:
    value = {"a": [{"password": "x"}, "mail: u@example.com"], "n": 5, "t": ("token=abc",)}
    masked = mask_value(value)
    assert masked["a"][0]["password"] == MASK
    assert "u@example.com" not in masked["a"][1]
    assert masked["n"] == 5 and "abc" not in masked["t"][0]


@given(st.text(alphabet=st.characters(whitelist_categories=("Ll", "Nd")), min_size=6, max_size=24))
def test_any_password_value_in_text_is_masked(secret: str) -> None:
    assert mask_text(f"password={secret}") == f"password={MASK}"


def test_configure_logging_installs_json_handler_and_is_idempotent() -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert any(isinstance(f, MaskingFilter) for f in root.handlers[0].filters)


def test_app_request_logs_do_not_contain_query_secrets(api, caplog: pytest.LogCaptureFixture) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="netkar.request"):
        api.get("/v1/health?token=SUPERGIZLI")
    records = [r for r in caplog.records if r.name == "netkar.request"]
    assert records and all("SUPERGIZLI" not in str(r.__dict__) for r in records)
