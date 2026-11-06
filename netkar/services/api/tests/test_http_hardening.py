"""Güvenlik başlıkları, RFC 9457 hata biçimi ve sağlık uç noktaları."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import Api

REQUIRED = {
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cache-control": "no-store",
}


def _assert_headers(headers) -> None:  # type: ignore[no-untyped-def]
    for name, value in REQUIRED.items():
        assert headers[name] == value, name
    csp = headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "default-src 'none'" in csp
    assert "camera=()" in headers["permissions-policy"]
    assert headers["x-request-id"]


def test_security_headers_on_success_and_errors(api: Api) -> None:
    _assert_headers(api.get("/v1/health").headers)  # 200
    _assert_headers(api.get("/v1/yok").headers)  # 404
    _assert_headers(api.get("/v1/me").headers)  # 401
    _assert_headers(api.post("/v1/auth/login", {}, csrf=False).headers)  # 403 CSRF
    _assert_headers(api.post("/v1/auth/login", {"email": "x"}).headers)  # 422


def test_not_found_validation_and_method_errors_are_problem_json(api: Api) -> None:
    not_found = api.get("/v1/yok")
    assert not_found.status_code == 404
    assert not_found.headers["content-type"].startswith("application/problem+json")
    body = not_found.json()
    assert body["status"] == 404 and body["type"].startswith("urn:netkar:problem:")
    assert body["instance"] == "/v1/yok" and body["request_id"]

    invalid = api.post("/v1/auth/login", {"email": "gecersiz", "password": "gizli-parola-1234"})
    assert invalid.status_code == 422
    assert invalid.headers["content-type"].startswith("application/problem+json")
    assert invalid.json()["errors"] == [{"field": "email", "code": "value_error"}]
    assert "gizli-parola-1234" not in invalid.text

    wrong_method = api.client.put("/v1/health", headers={"X-CSRF-Token": api.csrf()})
    assert wrong_method.status_code == 405
    assert wrong_method.headers["content-type"].startswith("application/problem+json")


def test_unhandled_exception_returns_generic_500_without_internals(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()

    async def boom() -> None:
        raise RuntimeError("ic-ayrinti postgres://kullanici:parola@host/db")

    app.add_api_route("/v1/boom", boom)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        r = client.get("/v1/boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "ic-ayrinti" not in r.text and "Traceback" not in r.text and "postgres://" not in r.text
    assert r.json()["type"].endswith("internal-error")
    _assert_headers(r.headers)


def test_health_and_ready(api: Api) -> None:
    assert api.get("/v1/health").json() == {"status": "ok"}
    assert api.get("/v1/health/ready").json() == {"status": "ready"}


def test_ready_reports_503_when_database_is_down(make_api: Callable[..., Api]) -> None:
    bad = make_api(database_url="postgresql+psycopg://x:y@127.0.0.1:1/none")
    assert bad.get("/v1/health").status_code == 200  # DB'ye dokunmaz
    r = bad.get("/v1/health/ready")
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "127.0.0.1" not in r.text


def test_docs_ui_disabled_and_openapi_hidden_in_prod(make_api: Callable[..., Api]) -> None:
    dev = make_api()
    assert dev.get("/docs").status_code == 404
    assert dev.get("/v1/openapi.json").status_code == 200
    prod = make_api(environment="prod")
    assert prod.get("/v1/openapi.json").status_code == 404


def test_proxy_headers_trusted_only_when_enabled(make_api: Callable[..., Api]) -> None:
    body = {"email": "a@example.com", "password": "x"}

    def attempt(api: Api, forwarded: str) -> int:
        return int(api.post("/v1/auth/login", body, headers={"X-Forwarded-For": forwarded}).status_code)

    trusted = make_api(trust_proxy_headers=True, rate_limit_login_ip=1)
    assert attempt(trusted, "9.9.9.9, 1.1.1.1") == 401
    assert attempt(trusted, "9.9.9.9, 2.2.2.2") == 401  # en sağdaki (proxy'nin eklediği) değer esas
    assert attempt(trusted, "8.8.8.8, 1.1.1.1") == 429

    untrusted = make_api(rate_limit_login_ip=1)
    assert attempt(untrusted, "9.9.9.9, 1.1.1.1") == 401
    assert attempt(untrusted, "9.9.9.9, 2.2.2.2") == 429  # başlık yok sayılır, gerçek bağlantı IP'si
