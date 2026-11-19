"""sessions: sütun düzeyi UPDATE yetkisi ve iptal/kimlik/zaman değişmezliği tetikleyicisi (migrasyon 0023)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.conftest import Api, DatabaseInfo

SESSION_COLUMNS = (
    "id",
    "token_hash",
    "user_id",
    "tenant_id",
    "created_at",
    "last_seen_at",
    "expires_at",
    "revoked_at",
    "ip_hash",
    "user_agent",
)


@contextmanager
def _app_tx(database: DatabaseInfo, tenant_id: str) -> Iterator[psycopg.Connection[Any]]:
    """Uygulama rolüyle işlem açar; kiracı bağlamı işlem yerel ayarlanır, çıkışta geri alınır."""
    with psycopg.connect(database.app_dsn()) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
        yield conn
        conn.rollback()


@contextmanager
def _as_role(conn: psycopg.Connection[Any], role: str) -> Iterator[None]:
    """Otomatik onaylı yönetici bağlantısında geçici rol değiştirir."""
    if role == "netkar_auth":
        conn.execute("SET ROLE netkar_auth")
    try:
        yield
    finally:
        conn.execute("RESET ROLE")


def _login(api: Api, admin_conn: psycopg.Connection, email: str) -> tuple[str, str, str]:
    """Oturum açar; (oturum kimliği, kullanıcı kimliği, kiracı kimliği) döner."""
    api.signup_and_login(email)
    me = api.get("/v1/me").json()
    row = admin_conn.execute(
        "SELECT s.id::text FROM sessions s WHERE s.user_id = %s::uuid ORDER BY s.created_at DESC LIMIT 1",
        (me["user_id"],),
    ).fetchone()
    assert row is not None
    return row[0], me["user_id"], me["tenant"]["id"]


def test_app_can_update_only_the_two_runtime_columns(
    api: Api, admin_conn: psycopg.Connection, database: DatabaseInfo
) -> None:
    sid, _, tid = _login(api, admin_conn, "yetki1@example.com")
    with _app_tx(database, tid) as conn:
        assert conn.execute("UPDATE sessions SET last_seen_at = now() WHERE id = %s", (sid,)).rowcount == 1
        assert conn.execute("UPDATE sessions SET revoked_at = now() WHERE id = %s", (sid,)).rowcount == 1
    allowed = {"last_seen_at", "revoked_at"}
    for column in SESSION_COLUMNS:
        assert admin_conn.execute(
            "SELECT has_column_privilege('netkar_app', 'sessions', %s, 'UPDATE')", (column,)
        ).fetchone() == (column in allowed,), column
    assert admin_conn.execute(
        "SELECT has_table_privilege('netkar_app', 'sessions', 'UPDATE'),"
        " has_table_privilege('netkar_app', 'sessions', 'DELETE'),"
        " has_table_privilege('netkar_app', 'sessions', 'INSERT'),"
        " has_table_privilege('netkar_app', 'sessions', 'SELECT')"
    ).fetchone() == (False, False, True, True)


def test_auth_role_can_update_only_revoked_at(admin_conn: psycopg.Connection) -> None:
    for column in SESSION_COLUMNS:
        assert admin_conn.execute(
            "SELECT has_column_privilege('netkar_auth', 'sessions', %s, 'UPDATE')", (column,)
        ).fetchone() == (column == "revoked_at",), column
    assert admin_conn.execute(
        "SELECT has_table_privilege('netkar_auth', 'sessions', 'UPDATE')"
    ).fetchone() == (False,)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE sessions SET user_id = gen_random_uuid() WHERE id = %s",
        "UPDATE sessions SET tenant_id = gen_random_uuid() WHERE id = %s",
        "UPDATE sessions SET id = gen_random_uuid() WHERE id = %s",
        "UPDATE sessions SET token_hash = 'x' WHERE id = %s",
        "UPDATE sessions SET created_at = now() WHERE id = %s",
        "UPDATE sessions SET expires_at = now() + interval '30 days' WHERE id = %s",
        "UPDATE sessions SET ip_hash = 'x' WHERE id = %s",
        "UPDATE sessions SET user_agent = 'x' WHERE id = %s",
    ],
)
def test_app_cannot_update_identity_or_expiry_columns(
    api: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, statement: str
) -> None:
    sid, _, tid = _login(api, admin_conn, "yetki2@example.com")
    with _app_tx(database, tid) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement, (sid,))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE sessions SET revoked_at = NULL WHERE id = %s",
        "UPDATE sessions SET revoked_at = now() + interval '1 day' WHERE id = %s",
    ],
)
def test_app_cannot_reopen_or_move_a_revoked_session(
    api: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, statement: str
) -> None:
    sid, _, tid = _login(api, admin_conn, "yetki3@example.com")
    api.post("/v1/auth/logout")
    before = admin_conn.execute("SELECT revoked_at FROM sessions WHERE id = %s", (sid,)).fetchone()
    assert before is not None and before[0] is not None
    with _app_tx(database, tid) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(statement, (sid,))
    assert admin_conn.execute("SELECT revoked_at FROM sessions WHERE id = %s", (sid,)).fetchone() == before
    assert api.get("/v1/me").status_code == 401


@pytest.mark.parametrize("role", ["superuser", "netkar_auth"])
def test_revoked_at_is_immutable_for_every_role(api: Api, admin_conn: psycopg.Connection, role: str) -> None:
    sid, _, _ = _login(api, admin_conn, "yetki4@example.com")
    admin_conn.execute("UPDATE sessions SET revoked_at = now() WHERE id = %s", (sid,))  # ilk doldurma serbest
    with _as_role(admin_conn, role):
        for statement in (
            "UPDATE sessions SET revoked_at = NULL WHERE id = %s",
            "UPDATE sessions SET revoked_at = now() + interval '1 hour' WHERE id = %s",
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                admin_conn.execute(statement, (sid,))
        # Değişiklik yoksa (aynı değerle yeniden yazma) tetikleyici engel olmaz.
        assert (
            admin_conn.execute("UPDATE sessions SET revoked_at = revoked_at WHERE id = %s", (sid,)).rowcount
            == 1
        )


@pytest.mark.parametrize("role", ["superuser", "netkar_auth"])
def test_identity_columns_are_immutable_for_every_role(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection, role: str
) -> None:
    first = make_api()
    sid, _, _ = _login(first, admin_conn, "yetki5a@example.com")
    second = make_api()
    _, other_user, other_tenant = _login(second, admin_conn, "yetki5b@example.com")
    # Gerçek ikinci kullanıcı/kiracı: dış anahtar değil, tetikleyici (23514) durdurmalı.
    # netkar_auth'ta kimlik sütunlarına yetki yoktur: orada 42501 beklenir.
    expected = psycopg.errors.CheckViolation if role == "superuser" else psycopg.errors.InsufficientPrivilege
    statements = [
        ("UPDATE sessions SET user_id = %s::uuid WHERE id = %s", (other_user, sid)),
        ("UPDATE sessions SET tenant_id = %s::uuid WHERE id = %s", (other_tenant, sid)),
        ("UPDATE sessions SET id = gen_random_uuid() WHERE id = %s", (sid,)),
        ("UPDATE sessions SET token_hash = 'x' WHERE id = %s", (sid,)),
        ("UPDATE sessions SET created_at = created_at - interval '1 day' WHERE id = %s", (sid,)),
    ]
    with _as_role(admin_conn, role):
        for statement, params in statements:
            with pytest.raises(expected):
                admin_conn.execute(statement, params)
    if role == "superuser":
        # Aynı değerle yeniden yazma serbest.
        assert (
            admin_conn.execute(
                "UPDATE sessions SET user_id = user_id, tenant_id = tenant_id WHERE id = %s", (sid,)
            ).rowcount
            == 1
        )


def test_last_seen_only_moves_forward_and_not_into_the_future(
    api: Api, admin_conn: psycopg.Connection
) -> None:
    sid, _, _ = _login(api, admin_conn, "yetki6@example.com")
    for statement in (
        "UPDATE sessions SET last_seen_at = last_seen_at - interval '1 second' WHERE id = %s",
        "UPDATE sessions SET last_seen_at = now() + interval '1 hour' WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(statement, (sid,))
    assert (
        admin_conn.execute(
            "UPDATE sessions SET last_seen_at = now() + interval '1 minute' WHERE id = %s", (sid,)
        ).rowcount
        == 1
    )
    assert (
        admin_conn.execute("UPDATE sessions SET last_seen_at = last_seen_at WHERE id = %s", (sid,)).rowcount
        == 1
    )


def test_first_revocation_time_must_be_close_to_now(api: Api, admin_conn: psycopg.Connection) -> None:
    sid, _, _ = _login(api, admin_conn, "yetki7@example.com")
    for statement in (
        "UPDATE sessions SET revoked_at = now() - interval '1 hour' WHERE id = %s",
        "UPDATE sessions SET revoked_at = now() + interval '1 hour' WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(statement, (sid,))
    assert admin_conn.execute("UPDATE sessions SET revoked_at = now() WHERE id = %s", (sid,)).rowcount == 1


def test_expiry_can_only_be_shortened(api: Api, admin_conn: psycopg.Connection) -> None:
    sid, _, _ = _login(api, admin_conn, "yetki8@example.com")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE sessions SET expires_at = expires_at + interval '1 second' WHERE id = %s", (sid,)
        )
    assert (
        admin_conn.execute(
            "UPDATE sessions SET expires_at = expires_at - interval '1 hour' WHERE id = %s", (sid,)
        ).rowcount
        == 1
    )
    with _as_role(admin_conn, "netkar_auth"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            admin_conn.execute(
                "UPDATE sessions SET expires_at = expires_at - interval '1 hour' WHERE id = %s", (sid,)
            )


def test_guard_also_fires_in_replica_mode(api: Api, admin_conn: psycopg.Connection) -> None:
    sid, _, _ = _login(api, admin_conn, "yetki9@example.com")
    admin_conn.execute("UPDATE sessions SET revoked_at = now() WHERE id = %s", (sid,))
    assert admin_conn.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgname = 'sessions_immutable_guard'"
    ).fetchone() == ("A",)
    admin_conn.execute("SET session_replication_role = replica")
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute("UPDATE sessions SET revoked_at = NULL WHERE id = %s", (sid,))
    finally:
        admin_conn.execute("RESET session_replication_role")


def test_auth_gate_flows_still_revoke_and_logout_works(api: Api, admin_conn: psycopg.Connection) -> None:
    """Giriş, `last_seen_at` tazeleme ve çıkış (uygulama rolü) dar sütun yetkisiyle çalışır."""
    _login(api, admin_conn, "yetki10@example.com")
    assert api.get("/v1/me").status_code == 200
    assert api.post("/v1/auth/logout").status_code == 204
    assert admin_conn.execute("SELECT revoked_at IS NOT NULL FROM sessions").fetchall() == [(True,)]


def test_clock_skew_does_not_break_touch_and_logout(
    api: Api, admin_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uygulama saati 10 dk ileri olsa da tazeleme ve çıkış 500 vermez; zamanlar veritabanı saatindendir."""
    import datetime as dt

    from app.api import deps
    from app.services import auth as auth_service

    class SkewedDatetime(dt.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> SkewedDatetime:  # type: ignore[override]
            return super().now(tz) + dt.timedelta(minutes=10)  # type: ignore[return-value]

    _login(api, admin_conn, "yetki11@example.com")
    monkeypatch.setattr(deps, "datetime", SkewedDatetime)
    monkeypatch.setattr(auth_service, "datetime", SkewedDatetime)
    assert api.get("/v1/me").status_code == 200  # app saati 10 dk ileri: tazeleme tetiklenir
    row = admin_conn.execute("SELECT extract(epoch FROM now() - last_seen_at) FROM sessions").fetchone()
    assert row is not None and abs(row[0]) < 60  # veritabanı saati yazıldı, app saati değil
    assert api.post("/v1/auth/logout").status_code == 204
    row = admin_conn.execute("SELECT extract(epoch FROM now() - revoked_at) FROM sessions").fetchone()
    assert row is not None and abs(row[0]) < 60


def test_migration_0023_roundtrip(alembic_cfg: Config, admin_conn: psycopg.Connection) -> None:
    def trigger() -> tuple[str, ...] | None:
        return admin_conn.execute(  # type: ignore[return-value]
            "SELECT tgenabled FROM pg_trigger WHERE tgname = 'sessions_immutable_guard'"
        ).fetchone()

    def privileges() -> tuple[bool, ...]:
        return admin_conn.execute(  # type: ignore[return-value]
            "SELECT has_table_privilege('netkar_app', 'sessions', 'UPDATE'),"
            " has_column_privilege('netkar_app', 'sessions', 'revoked_at', 'UPDATE'),"
            " has_column_privilege('netkar_app', 'sessions', 'user_id', 'UPDATE'),"
            " has_table_privilege('netkar_auth', 'sessions', 'UPDATE'),"
            " has_column_privilege('netkar_auth', 'sessions', 'revoked_at', 'UPDATE'),"
            " has_column_privilege('netkar_auth', 'sessions', 'expires_at', 'UPDATE')"
        ).fetchone()

    def column_acls() -> int:
        row = admin_conn.execute(
            "SELECT count(*) FROM pg_attribute WHERE attrelid = 'public.sessions'::regclass "
            "AND attnum > 0 AND NOT attisdropped AND attacl IS NOT NULL"
        ).fetchone()
        assert row is not None
        return int(row[0])

    new_state = (False, True, False, False, True, False)
    assert trigger() == ("A",) and privileges() == new_state and column_acls() > 0
    for _ in range(2):
        command.downgrade(alembic_cfg, "0022")
        assert trigger() is None
        assert admin_conn.execute(
            "SELECT to_regprocedure('public.sessions_immutable_guard()')"
        ).fetchone() == (None,)
        assert privileges() == (True, True, True, True, True, True)  # eski tablo düzeyi yetkiler
        assert column_acls() == 0  # sütun düzeyi kalıntı yok
        command.upgrade(alembic_cfg, "head")
        assert trigger() == ("A",) and privileges() == new_state and column_acls() > 0
