"""Üretimde "üretim dışı" işaretli veritabanıyla API ve işçi açılışı reddedilir (demo tohumu denetimi DT-14)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.deployment_guard import (
    NonProductionMarkError,
    assert_not_marked_non_production,
    assert_not_marked_non_production_sync,
)
from app.db.session import create_engine


@pytest.fixture
def marked(admin_conn: psycopg.Connection[Any]) -> Iterator[None]:
    admin_conn.execute(
        "INSERT INTO deployment_marks (key, value) VALUES ('non_production', 'true') ON CONFLICT DO NOTHING"
    )
    yield
    admin_conn.execute("DELETE FROM deployment_marks WHERE key = 'non_production'")


@pytest.fixture
def unmarked(admin_conn: psycopg.Connection[Any]) -> Iterator[None]:
    admin_conn.execute("DELETE FROM deployment_marks WHERE key = 'non_production'")
    yield


def _unreachable(url: str) -> str:
    """Bağlantı kurulamayan (olmayan veritabanı) aynı sunucu adresi; test kümesi trust kimlik doğrulaması kullanır."""
    name = make_url(url).database
    assert name is not None
    return url.replace(name, "olmayan_veritabani", 1)


def prod(settings: Settings) -> Settings:
    # model_copy doğrulamayı atlar: prod'a özgü zorunlu alanlar bu testin konusu değil.
    return settings.model_copy(update={"environment": "prod"})


def start(app: FastAPI) -> None:
    with TestClient(app, base_url="https://testserver"):
        pass


def test_api_refuses_to_start_in_prod_when_database_is_marked_non_production(
    make_app: Callable[..., FastAPI], settings: Settings, marked: None
) -> None:
    with pytest.raises(NonProductionMarkError, match="üretim dışı olarak işaretli"):
        start(make_app(environment="prod"))


def test_api_starts_in_prod_when_database_is_not_marked(
    make_app: Callable[..., FastAPI], unmarked: None
) -> None:
    start(make_app(environment="prod"))


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_api_ignores_the_mark_outside_prod(
    make_app: Callable[..., FastAPI], environment: str, marked: None
) -> None:
    start(make_app(environment=environment))


def test_api_does_not_even_query_outside_prod(
    make_app: Callable[..., FastAPI], admin_conn: psycopg.Connection[Any]
) -> None:
    """prod dışında tablo okunmaz: işaret tablosu olmayan eski şemada da açılış bozulmaz."""
    admin_conn.execute("ALTER TABLE deployment_marks RENAME TO deployment_marks_gizli")
    try:
        start(make_app(environment="test"))
    finally:
        admin_conn.execute("ALTER TABLE deployment_marks_gizli RENAME TO deployment_marks")


async def test_prod_start_check_tolerates_missing_table_but_not_other_errors(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    engine = create_engine(settings.database_url)
    bad = create_engine(_unreachable(settings.database_url))
    try:
        admin_conn.execute("ALTER TABLE deployment_marks RENAME TO deployment_marks_gizli")
        try:
            await assert_not_marked_non_production(engine, "prod")  # tablo yok: işaret de olamaz
        finally:
            admin_conn.execute("ALTER TABLE deployment_marks_gizli RENAME TO deployment_marks")
        # Doğrulanamayan üretim açılmaz (bağlantı/yetki hatası fail-closed).
        with pytest.raises(NonProductionMarkError, match="okunamadı"):
            await assert_not_marked_non_production(bad, "prod")
        await assert_not_marked_non_production(bad, "dev")  # prod değilse hiç bağlanmaz
    finally:
        await engine.dispose()
        await bad.dispose()


def test_worker_refuses_to_start_in_prod_when_database_is_marked_non_production(
    settings: Settings, worker_env: None, marked: None
) -> None:
    from app.worker.app import build_app

    with pytest.raises(NonProductionMarkError, match="üretim dışı olarak işaretli"):
        build_app(prod(settings))
    build_app(settings)  # test ortamı: işaret yok sayılır
    with pytest.raises(NonProductionMarkError):
        assert_not_marked_non_production_sync(settings.worker_libpq_url, "prod")


def test_worker_starts_in_prod_when_database_is_not_marked(
    settings: Settings, worker_env: None, unmarked: None
) -> None:
    from app.worker.app import build_app

    build_app(prod(settings))


def test_worker_prod_check_fails_closed_when_database_cannot_be_read(settings: Settings) -> None:
    bad = _unreachable(settings.worker_libpq_url)
    with pytest.raises(NonProductionMarkError, match="okunamadı"):
        assert_not_marked_non_production_sync(bad, "prod")
    assert_not_marked_non_production_sync(bad, "dev")  # prod değilse hiç bağlanmaz
