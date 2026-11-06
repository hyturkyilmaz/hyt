"""Rate limit: uç nokta davranışı ve pencere mantığı."""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.ratelimit import RateLimiter
from tests.conftest import GOOD_PASSWORD, Api, DatabaseInfo


def test_login_rate_limited_per_email(make_api: Callable[..., Api]) -> None:
    api = make_api(rate_limit_login_email=3)
    api.register("rl@example.com")
    statuses = [api.login("rl@example.com", "yanlis-parola-1234").status_code for _ in range(3)]
    assert statuses == [401, 401, 401]
    blocked = api.login("rl@example.com", GOOD_PASSWORD)  # doğru parola da engellenir
    assert blocked.status_code == 429
    assert blocked.headers["content-type"].startswith("application/problem+json")
    assert int(blocked.headers["retry-after"]) > 0
    # Başka e-posta etkilenmez
    api.register("other@example.com")
    assert api.login("other@example.com").status_code == 200


def test_login_rate_limited_per_ip(make_api: Callable[..., Api]) -> None:
    api = make_api(rate_limit_login_ip=2)
    assert api.login("a@example.com").status_code == 401
    assert api.login("b@example.com").status_code == 401
    assert api.login("c@example.com").status_code == 429


def test_register_rate_limited(make_api: Callable[..., Api]) -> None:
    api = make_api(rate_limit_register_ip=2)
    assert api.register("a1@example.com").status_code == 202
    assert api.register("a2@example.com").status_code == 202
    assert api.register("a3@example.com").status_code == 429


def test_reset_request_rate_limited_per_email(make_api: Callable[..., Api]) -> None:
    api = make_api(rate_limit_reset_email=2)
    codes = [
        api.post("/v1/auth/password-reset/request", {"email": "z@example.com"}).status_code for _ in range(3)
    ]
    assert codes == [202, 202, 429]


def test_reset_confirm_rate_limited(make_api: Callable[..., Api]) -> None:
    api = make_api(rate_limit_reset_ip=1)  # confirm için 2 istek
    body = {"token": "t" * 40, "new_password": GOOD_PASSWORD}
    codes = [api.post("/v1/auth/password-reset/confirm", body).status_code for _ in range(3)]
    assert codes == [400, 400, 429]


def test_rate_limit_keys_hold_no_pii(make_api: Callable[..., Api], admin_conn: psycopg.Connection) -> None:
    api = make_api()
    api.login("gizli.kisi@example.com")
    keys = " ".join(r[0] for r in admin_conn.execute("SELECT key FROM rate_limits"))
    assert "gizli" not in keys and "example.com" not in keys and "testclient" not in keys


async def test_fixed_window_resets_in_next_window(settings: Settings) -> None:
    engine = create_async_engine(settings.database_url)
    try:
        limiter = RateLimiter(engine)
        await limiter.hit("unit:k", 2, 60, now=1_000_020)
        await limiter.hit("unit:k", 2, 60, now=1_000_030)
        with pytest.raises(ProblemError) as exc:
            await limiter.hit("unit:k", 2, 60, now=1_000_031)
        assert exc.value.status == 429
        assert exc.value.headers["Retry-After"] == "49"  # pencere 1_000_020 ile 1_000_080 arası
        await limiter.hit("unit:k", 2, 60, now=1_000_080)  # yeni pencere
    finally:
        await engine.dispose()


def test_prune_task_removes_old_windows(database: DatabaseInfo, admin_conn: psycopg.Connection) -> None:
    import asyncio

    from app.worker.tasks import prune_rate_limits

    admin_conn.execute(
        "INSERT INTO rate_limits VALUES ('old', now() - interval '3 days', 5), ('new', now(), 1)"
    )

    async def run() -> int:
        engine = create_async_engine(database.app_url.render_as_string(hide_password=False))
        try:
            return await prune_rate_limits(engine)
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == 1
    assert [r[0] for r in admin_conn.execute("SELECT key FROM rate_limits")] == ["new"]
