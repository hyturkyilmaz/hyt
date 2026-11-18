"""DT-22 ve P1 kalan küçük maddeler: işçi sorgu zaman aşımı, PWNED uyarısı, açılış denetimi günlüğü, belge önbelleği."""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import TracebackType
from typing import Any

import psycopg
import pytest

from app.core.config import HARDENED_ENVIRONMENTS, Settings
from app.db import deployment_guard
from app.main import _warn_if_pwned_check_disabled, _warn_if_real_terms_without_gate
from app.services import legal as legal_service
from tests.conftest import Api
from tests.test_legal_acceptance import _publish


# --- DT-22a: işçi denetimi sorgu zaman aşımı ---------------------------------------------------------------
class _FakeConn:
    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str) -> _FakeConn:
        return self

    def fetchone(self) -> None:
        return None  # işaret yok: prod için açılır


def test_worker_check_passes_statement_timeout_derived_from_the_single_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_connect(conninfo: str, **kwargs: Any) -> _FakeConn:
        seen.update(kwargs)
        return _FakeConn()

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    deployment_guard.assert_not_marked_non_production_sync("postgresql://x/y", "prod")
    assert seen["connect_timeout"] == deployment_guard.CHECK_TIMEOUT_SECONDS == 10
    assert seen["options"] == f"-c statement_timeout={deployment_guard.CHECK_TIMEOUT_SECONDS}s"

    # Tek sabitten türer: sabit değişince hem bağlantı hem sorgu süresi birlikte değişir.
    monkeypatch.setattr(deployment_guard, "CHECK_TIMEOUT_SECONDS", 3)
    deployment_guard.assert_not_marked_non_production_sync("postgresql://x/y", "prod")
    assert seen["connect_timeout"] == 3
    assert seen["options"] == "-c statement_timeout=3s"


def test_worker_check_real_path_applies_statement_timeout_in_postgres(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gerçek `assert_not_marked_non_production_sync` yolu: sunucu `statement_timeout` değerini görür.

    Sorgu `SHOW statement_timeout` ile değiştirilir; hüküm işlevi okunan değeri yakalar (gerçek bağlantı).
    """
    seen: list[Any] = []
    connects: list[dict[str, Any]] = []
    real_connect = psycopg.connect

    def spy_connect(conninfo: str, **kwargs: Any) -> Any:
        connects.append(kwargs)
        return real_connect(conninfo, **kwargs)

    monkeypatch.setattr(psycopg, "connect", spy_connect)
    monkeypatch.setattr(deployment_guard, "_SQL", "SHOW statement_timeout")
    monkeypatch.setattr(deployment_guard, "_verdict", lambda environment, value: seen.append(value))
    deployment_guard.assert_not_marked_non_production_sync(settings.worker_libpq_url, "prod")
    assert connects and connects[0]["options"] == "-c statement_timeout=10s"
    assert seen == ["10s"]


# --- DT-22b: sertleşmiş ortamda PWNED_CHECK_ENABLED kapalıysa uyarı -------------------------------------
@pytest.mark.parametrize("environment", ["dev", "test", "staging", "prod"])
@pytest.mark.parametrize("enabled", [False, True])
def test_pwned_warning_only_in_hardened_environments_with_flag_off(
    settings: Settings, caplog: pytest.LogCaptureFixture, environment: str, enabled: bool
) -> None:
    candidate = settings.model_copy(update={"environment": environment, "pwned_check_enabled": enabled})
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _warn_if_pwned_check_disabled(candidate)
    warned = [r for r in caplog.records if "PWNED_CHECK_ENABLED" in r.getMessage()]
    assert bool(warned) == (environment in HARDENED_ENVIRONMENTS and not enabled)
    for record in warned:
        assert record.levelno == logging.WARNING
        # Sır yok: ileti yalnız ortam adı ve sabit metin taşır.
        assert candidate.database_url not in record.getMessage()


# --- açılış belge denetimi hata günlüğü ------------------------------------------------------------------
class _BrokenSession:
    async def __aenter__(self) -> Any:
        raise RuntimeError("postgresql://kullanici:gizli@host/db baglanti hatasi")

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None


async def test_startup_legal_check_failure_logs_a_warning_without_details(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    broken: Any = lambda: _BrokenSession()  # noqa: E731
    with caplog.at_level(logging.DEBUG, logger="app.main"):
        await _warn_if_real_terms_without_gate(broken, settings)  # açılış engellenmez, istisna sızmaz
    records = [r for r in caplog.records if "açılış denetimi yapılamadı" in r.getMessage()]
    assert [r.levelno for r in records] == [logging.WARNING]
    assert "gizli" not in caplog.text  # istisna ayrıntısı (bağlantı dizesi) yazılmaz
    assert "RuntimeError" in records[0].getMessage()


async def test_startup_legal_check_is_skipped_silently_when_gate_is_on(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    broken: Any = lambda: _BrokenSession()  # noqa: E731
    enforced = settings.model_copy(update={"legal_reacceptance_enforced": True})
    with caplog.at_level(logging.DEBUG, logger="app.main"):
        await _warn_if_real_terms_without_gate(broken, enforced)
    assert not caplog.records


# --- /v1/legal/current önbelleği ---------------------------------------------------------------------------
def test_legal_current_has_public_cache_header_matching_the_ttl(api: Api) -> None:
    response = api.get("/v1/legal/current")
    assert response.status_code == 200
    assert response.headers["cache-control"] == f"public, max-age={legal_service.CURRENT_CACHE_TTL_SECONDS}"
    assert legal_service.CURRENT_CACHE_TTL_SECONDS == 60


def test_legal_current_is_cached_until_ttl_then_shows_newly_visible_version(
    api: Api, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(legal_service, "_clock", lambda: clock["now"])

    def terms_version() -> str:
        body = api.get("/v1/legal/current").json()
        return str(next(d["version"] for d in body if d["doc_type"] == "terms"))

    assert terms_version() == "taslak-2026-11"
    # Veritabanında güncel olan yeni sürüm (yayın zamanı geldi); önbellek TTL boyunca eskiyi döner.
    _publish(admin_conn, "terms", "2026-12-a")
    clock["now"] += legal_service.CURRENT_CACHE_TTL_SECONDS - 1
    assert terms_version() == "taslak-2026-11"
    clock["now"] += 1  # TTL doldu
    assert terms_version() == "2026-12-a"


def test_future_dated_version_ends_the_cache_at_its_publish_time(
    api: Api, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Önbellek bitişi min(TTL, sonraki yayın): yayın anı geçince bayat liste (409 döngüsü) kalmaz."""
    clock = {"now": 5.0}
    monkeypatch.setattr(legal_service, "_clock", lambda: clock["now"])

    def terms_version() -> tuple[str, int]:
        response = api.get("/v1/legal/current")
        version = next(d["version"] for d in response.json() if d["doc_type"] == "terms")
        max_age = int(response.headers["cache-control"].rsplit("max-age=", 1)[1])
        return str(version), max_age

    admin_conn.execute(
        "INSERT INTO legal_documents (doc_type, version, published_at, content_sha256) "
        "VALUES ('terms', '2026-12-f', now() + interval '3 seconds', repeat('a', 64))"
    )
    version, max_age = terms_version()
    assert version == "taslak-2026-11"  # ileri tarihli: henüz görünmez
    assert 0 <= max_age <= 3  # tarayıcıya da yalnız kalan süre söylenir (TTL=60 değil)
    admin_conn.execute("SELECT pg_sleep(3.5)")
    clock["now"] += 4  # TTL (60 sn) dolmadan, yayın anı geçti
    assert terms_version()[0] == "2026-12-f"


def test_max_age_is_remaining_whole_seconds_and_never_negative(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(legal_service, "_clock", lambda: clock["now"])
    assert api.get("/v1/legal/current").headers["cache-control"] == "public, max-age=60"
    clock["now"] += 20.5
    assert api.get("/v1/legal/current").headers["cache-control"] == "public, max-age=39"
    clock["now"] += 38.9  # bitişe 0.6 sn kaldı
    assert api.get("/v1/legal/current").headers["cache-control"] == "public, max-age=0"


async def test_slow_older_fill_cannot_overwrite_a_newer_cache_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 10.0}
    monkeypatch.setattr(legal_service, "_clock", lambda: clock["now"])
    newer: tuple[float, float, tuple[Any, ...]] = (20.0, 80.0, ("yeni",))

    async def slow_current(db: Any) -> list[Any]:
        # Bu sorgu sürerken daha yeni başlayan bir doldurma önbelleği yazdı.
        legal_service._current_cache = newer
        return ["eski"]

    class _Result:
        def scalar_one_or_none(self) -> None:
            return None

    class _Db:
        async def execute(self, statement: Any) -> _Result:
            return _Result()

    monkeypatch.setattr(legal_service, "current_documents", slow_current)
    docs, _ = await legal_service.current_documents_cached(_Db())  # type: ignore[arg-type]
    assert [str(d) for d in docs] == ["eski"]  # bu isteğin kendi sonucu döner
    assert legal_service._current_cache == newer  # ama yeni kayıt ezilmez


def test_reset_helper_isolates_tests_and_register_does_not_use_the_cache(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    """Önbellek bayatken bile kayıt doğrulaması gerçek güncel sürümle yapılır (bayat sürüm 409)."""
    api = make_api()
    stale = api.get("/v1/legal/current").json()  # önbelleği doldurur
    _publish(admin_conn, "terms", "2026-12-b")
    assert api.get("/v1/legal/current").json() == stale  # hâlâ önbellekten
    stale_terms = next(d["version"] for d in stale if d["doc_type"] == "terms")
    response = api.register(
        "bayat@example.com", terms_version=stale_terms, privacy_notice_version="taslak-2026-11"
    )
    assert response.status_code == 409  # bayat liste yanlış kabul üretmez
    legal_service.reset_current_cache()
    assert any(d["version"] == "2026-12-b" for d in api.get("/v1/legal/current").json())
