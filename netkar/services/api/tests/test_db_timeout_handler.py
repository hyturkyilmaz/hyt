"""57014 (statement_timeout) işleyicisi: yola göre slug, ayrıntı sızmaz, diğer DB hataları 500 (DK-11, DK-13)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.errors import install_error_handlers


class _Orig(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("SECRET sürücü iletisi pg_sleep")
        self.sqlstate = sqlstate


def _client(sqlstate: str | None) -> TestClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace(profit_report_retry_after_seconds=3)
    install_error_handlers(app)

    def boom() -> None:
        raise DBAPIError("SELECT secret_sql", {"p": "secret"}, _Orig(sqlstate))

    for path in ("/v1/marketplace-accounts/x/profit/products", "/v1/auth/login", "/v1/profiteroles"):
        app.add_api_route(path, boom)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("path", "slug", "title"),
    [
        ("/v1/marketplace-accounts/x/profit/products", "report-compute-timeout", "Rapor hesaplanamadı"),
        ("/v1/auth/login", "db-timeout", "Veritabanı zaman aşımı"),
        ("/v1/profiteroles", "db-timeout", "Veritabanı zaman aşımı"),  # yol parçası eşleşir, önek değil
    ],
)
def test_57014_slug_depends_on_the_path_and_never_leaks_detail(path: str, slug: str, title: str) -> None:
    resp = _client("57014").get(path)
    assert resp.status_code == 503 and resp.json()["type"].endswith(slug) and resp.json()["title"] == title
    assert resp.headers["Retry-After"] == "3"
    assert "SECRET" not in resp.text and "secret" not in resp.text and "pg_sleep" not in resp.text


def test_other_database_errors_stay_a_plain_500() -> None:
    assert _client("23505").get("/v1/auth/login").status_code == 500
    assert _client(None).get("/v1/marketplace-accounts/x/profit/products").status_code == 500
