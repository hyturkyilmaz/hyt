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


def _resp_for(path: str, payload: object) -> httpx.Response:
    return httpx.Response(422, json=payload, request=httpx.Request("PUT", f"http://test{path}"))


def test_instance_path_is_excluded_but_must_equal_the_request_path() -> None:
    path = "/v1/accounts/a396d971-2d9e-4edf-909f-ab9183f1e306/profit-settings/defaults"
    r = _resp_for(path, {"type": "urn:x", "instance": path, "request_id": RID})
    assert "1e30" in r.text  # yolda tesadüfi eşleşme var
    assert "1e30" not in visible_text(r)


def test_reflection_inside_instance_field_fails() -> None:
    r = _resp_for("/v1/x", {"type": "urn:x", "instance": "/v1/x?desi=1e30"})
    with pytest.raises(AssertionError):
        visible_text(r)
