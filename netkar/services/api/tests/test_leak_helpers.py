"""leak_helpers.visible_text için birim testleri."""

from __future__ import annotations

import httpx
import pytest

from tests.leak_helpers import visible_text

RID = "0123456789abcdef1003456789abcdef"  # içinde "1003" geçen geçerli bir uuid4 hex


def _resp(payload: object) -> httpx.Response:
    return httpx.Response(500, json=payload)


def test_request_id_is_excluded_from_leak_text() -> None:
    r = _resp({"type": "urn:x", "request_id": RID})
    assert "1003" in r.text  # ham metinde tesadüfi eşleşme var
    assert "1003" not in visible_text(r)


def test_real_reflection_outside_request_id_is_still_caught() -> None:
    r = _resp({"type": "urn:x", "detail": "sipariş 1003", "request_id": RID})
    assert "1003" in visible_text(r)


def test_reflection_inside_request_id_field_fails() -> None:
    r = _resp({"type": "urn:x", "request_id": "sipariş 1003"})
    with pytest.raises(AssertionError):
        visible_text(r)


def test_non_object_bodies_are_returned_as_is() -> None:
    assert visible_text(httpx.Response(200, json=[1, 2])) == "[1,2]"
    assert visible_text(httpx.Response(200, text="düz 1003")) == "düz 1003"
