"""Migrasyon 0027 (ADR-0009 D5): `notify_gate.releasable_outbox` ve outbox keşif yetkisi.

Kapsam: işlevin yetki ve sertleştirme özellikleri (0025 kapı işlevleriyle aynı), kiracılar arası listeleme anlamı
(yalnız zamanı gelmiş `held` ve `failed`; sıklık sınırı bekleyenleri, `pending`, gelecek ve kapanmış satırlar hariç),
`due_outbox`'ın değişmemesi, upgrade -> downgrade -> upgrade tam eşitliği (yetki, politika, işlev, indeks), verinin
silinmemesi, prod downgrade koruması ve `trg_` önekli tetikleyici yokluğu.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.conftest import DatabaseInfo
from tests.test_alert_evaluation import mark_synced
from tests.test_alert_schema import (
    World,
    _function_row,
    _snapshot,
    add_outbox,
    col_privs,
    make_world,
    role_tx,
)

SEL = "SELECT id, tenant_id FROM notify_gate.releasable_outbox(%s)"


@pytest.fixture
def world(admin_conn: psycopg.Connection[Any]) -> World:
    """İki kiracı (A: owner, admin, viewer; B: owner); tüm kaynakların yedeklemesi tamam."""
    made = make_world(admin_conn)
    mark_synced(admin_conn, made.a)
    mark_synced(admin_conn, made.b)
    return made


def make_state(
    conn: psycopg.Connection[Any], outbox_id: Any, status: str, *, attempts: int = 0, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE notification_outbox SET status = %s, attempts = %s, last_error_class = %s WHERE id = %s",
        (status, attempts, error, outbox_id),
    )


def test_releasable_outbox_is_a_locked_down_security_definer_for_the_worker_only(
    admin_conn: psycopg.Connection[Any],
) -> None:
    secdef, owner, config, worker_exec, app_exec, public_exec, auth_exec, w_usage, a_usage, p_usage = (
        _function_row(admin_conn, "notify_gate", "releasable_outbox")
    )
    assert secdef is True and owner == "netkar_notify_gate"
    assert config == ["search_path=pg_catalog, public, pg_temp"]
    assert (worker_exec, app_exec, public_exec, auth_exec) == (True, False, False, False)
    assert (w_usage, a_usage, p_usage) == (True, False, False)


def test_notify_gate_gets_only_the_one_extra_column_and_the_app_role_nothing(
    admin_conn: psycopg.Connection[Any],
) -> None:
    assert col_privs(admin_conn, "netkar_notify_gate", "notification_outbox", "SELECT") == {
        "id",
        "tenant_id",
        "user_id",
        "status",
        "channel",
        "not_before",
        "last_error_class",
    }
    for role in ("netkar_app", "netkar_auth", "public"):
        assert "last_error_class" not in col_privs(admin_conn, role, "notification_outbox", "SELECT"), role


def test_it_lists_only_due_held_and_failed_rows_across_tenants_without_rate_limited_ones(
    database: DatabaseInfo,
    admin_conn: psycopg.Connection[Any],
    world: World,
) -> None:
    a, b = world.a, world.b
    now = datetime.now(UTC)
    past, future = now - timedelta(minutes=5), now + timedelta(hours=1)
    keys = iter(f"{n:02x}" * 32 for n in range(1, 40))

    def row(seller: Any, status: str, not_before: datetime, **kw: Any) -> Any:
        outbox_id = add_outbox(admin_conn, seller, kind="test", key=next(keys), not_before=not_before)
        if status != "pending":
            make_state(admin_conn, outbox_id, status, **kw)
        return outbox_id

    held_a = row(a, "held", past - timedelta(minutes=3))
    held_b = row(b, "held", past - timedelta(minutes=2))
    failed_a = row(a, "failed", past - timedelta(minutes=1), attempts=2, error="timeout_error")
    row(a, "held", future)  # zamanı gelmedi
    row(a, "failed", future, attempts=1, error="timeout_error")
    row(a, "held", past, error="rate_limited")  # özete katlanır: bırakılmaz
    row(a, "pending", past)  # pending `due_outbox`'ın işi
    row(a, "sent", past)
    row(a, "suppressed", past)
    row(a, "skipped", past)
    row(a, "failed_permanent", past, attempts=6)
    with role_tx(database.worker_dsn()) as conn:  # kiracı bağlamı gerekmez
        rows = conn.execute(SEL, (100,)).fetchall()
        assert rows == [
            (held_a, a.tenant_id),
            (held_b, b.tenant_id),
            (failed_a, a.tenant_id),
        ]  # not_before sırası
        assert len(conn.execute(SEL, (1,)).fetchall()) == 1
        assert len(conn.execute(SEL, (0,)).fetchall()) == 1  # alt sınır 1
        assert len(conn.execute("SELECT * FROM notify_gate.releasable_outbox()").fetchall()) == 3
        assert [d.name for d in conn.execute(SEL, (5,)).description or []] == ["id", "tenant_id"]
        assert conn.execute("SELECT count(*) FROM notification_outbox").fetchone() == (
            0,
        )  # RLS: doğrudan görünmez
    with role_tx(database.worker_dsn()) as conn:  # `due_outbox` değişmedi: yalnız pending
        assert {r[0] for r in conn.execute("SELECT id FROM notify_gate.due_outbox(100)")} == {
            r[0]
            for r in admin_conn.execute(
                "SELECT id FROM notification_outbox WHERE status = 'pending' AND not_before <= now()"
            )
        }
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(SEL, (10,))


def test_the_worker_can_release_a_listed_row_to_pending_but_not_a_closed_one(
    database: DatabaseInfo,
    admin_conn: psycopg.Connection[Any],
    world: World,
) -> None:
    a = world.a
    held = add_outbox(
        admin_conn,
        a,
        kind="test",
        key="aa" * 32,
        status="held",
        not_before=datetime.now(UTC) - timedelta(minutes=1),
    )
    failed = add_outbox(admin_conn, a, kind="test", key="bb" * 32)
    make_state(admin_conn, failed, "failed", attempts=5, error="timeout_error")
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        for outbox_id in (held, failed):
            conn.execute("UPDATE notification_outbox SET status = 'pending' WHERE id = %s", (outbox_id,))
    assert admin_conn.execute(
        "SELECT status FROM notification_outbox WHERE id = ANY(%s) ORDER BY status", ([held, failed],)
    ).fetchall() == [("pending",), ("pending",)]
    closed = add_outbox(admin_conn, a, kind="test", key="cc" * 32)
    admin_conn.execute("UPDATE notification_outbox SET status = 'sent' WHERE id = %s", (closed,))
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute("UPDATE notification_outbox SET status = 'pending' WHERE id = %s", (closed,))


def test_migration_0027_upgrade_downgrade_upgrade_restores_everything_and_keeps_data(
    alembic_cfg: Config,
    admin_conn: psycopg.Connection[Any],
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    monkeypatch.setenv("ENVIRONMENT", "test")
    held = add_outbox(
        admin_conn,
        a,
        kind="test",
        key="dd" * 32,
        status="held",
        not_before=datetime.now(UTC) - timedelta(minutes=1),
    )
    failed = add_outbox(admin_conn, a, kind="test", key="ee" * 32)
    make_state(admin_conn, failed, "failed", attempts=1, error="timeout_error")
    before = _snapshot(admin_conn)
    indexes = lambda: {  # noqa: E731
        r[0]
        for r in admin_conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'notification_outbox'"
        )
    }
    assert "ix_notification_outbox_failed_due" in indexes()
    try:
        command.downgrade(alembic_cfg, "0026")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0026",)
        assert "ix_notification_outbox_failed_due" not in indexes()
        assert not admin_conn.execute(
            "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'notify_gate' AND p.proname = 'releasable_outbox'"
        ).fetchall()
        assert "last_error_class" not in col_privs(
            admin_conn, "netkar_notify_gate", "notification_outbox", "SELECT"
        )
        # Veri silinmedi: iki satır da yerinde.
        assert admin_conn.execute(
            "SELECT count(*) FROM notification_outbox WHERE id = ANY(%s)", ([held, failed],)
        ).fetchone() == (2,)
        # 0025 işlevleri ve due_outbox bozulmadı.
        assert admin_conn.execute(
            "SELECT count(*) FROM pg_proc WHERE proname IN ('due_outbox', 'email_for')"
        ).fetchone() == (2,)
    finally:
        command.upgrade(alembic_cfg, "head")
    assert _snapshot(admin_conn) == before  # yetki, politika, tetikleyici, işlev gövdesi tam eşit
    assert admin_conn.execute(
        "SELECT count(*) FROM notification_outbox WHERE id = ANY(%s)", ([held, failed],)
    ).fetchone() == (2,)
    assert "ix_notification_outbox_failed_due" in indexes()


def test_migration_0027_creates_no_trigger_at_all(admin_conn: psycopg.Connection[Any]) -> None:
    """`trg_` öneki başka migrasyonlara ayrılmıştır: 0027 hiç tetikleyici eklemez (kaynak ve outbox tetikleyicileri)."""
    source = (
        Path(__file__).resolve().parent.parent / "migrations/versions/0027_notify_outbox_release.py"
    ).read_text()
    assert "CREATE TRIGGER" not in source.upper() and "trg_" not in source
    names = {
        r[0]
        for r in admin_conn.execute(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname = 'notification_outbox'"
        )
    }
    assert names == {"notification_outbox_guard"}  # 0025'in tek tetikleyicisi; 0027 eklemedi


def test_migration_0027_downgrade_in_prod_stops_while_held_or_failed_rows_exist(
    alembic_cfg: Config,
    admin_conn: psycopg.Connection[Any],
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    head = ScriptDirectory.from_config(alembic_cfg).get_current_head()
    held = add_outbox(
        admin_conn,
        a,
        kind="test",
        key="f1" * 32,
        status="held",
        not_before=datetime.now(UTC) - timedelta(minutes=1),
    )
    try:
        monkeypatch.setenv("ENVIRONMENT", "prod")
        with pytest.raises(
            RuntimeError, match="ENVIRONMENT=prod iken notification_outbox içinde 1 held/failed"
        ):
            command.downgrade(alembic_cfg, "0026")
        # Reddedilen 0027 geri alması sürümü 0027'de bırakır (sonraki migrasyonlar varsa onlar önce geri alınmış
        # olur; Alembic her adımı ayrı işler).
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0027",)
        assert admin_conn.execute(
            "SELECT count(*) FROM pg_proc WHERE proname = 'releasable_outbox'"
        ).fetchone() == (1,)
        assert admin_conn.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'notification_outbox'"
        ).fetchone() == (True,)  # reddedilen deneme FORCE RLS'yi yerinde bıraktı
        # held satır boşalınca (kapanınca) prod'da da geri alınabilir; yalnız `pending/sent` kalır.
        admin_conn.execute(
            "UPDATE notification_outbox SET status = 'skipped', last_error_class = 'x_y' WHERE id = %s",
            (held,),
        )
        command.downgrade(alembic_cfg, "0026")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0026",)
        assert admin_conn.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'notification_outbox'"
        ).fetchone() == (True,)
    finally:
        monkeypatch.setenv("ENVIRONMENT", "test")
        command.upgrade(alembic_cfg, "head")
    assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == (head,)


def test_tenant_recipients_lists_verified_members_with_roles_and_checks_the_context(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    unverified = admin_conn.execute(
        "INSERT INTO users (email, password_hash) VALUES ('uye-dogrulanmamis@example.com', 'x') RETURNING id"
    ).fetchone()
    assert unverified is not None
    admin_conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'admin')",
        (unverified[0], a.tenant_id),
    )
    sql = "SELECT user_id, member_role FROM notify_gate.tenant_recipients(%s)"
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        got = dict(conn.execute(sql, (a.tenant_id,)).fetchall())
        assert got == {
            a.user_id: "owner",
            world.admin_id: "admin",
            world.viewer_id: "viewer",
        }  # doğrulanmamış yok
        assert [d.name for d in conn.execute(sql, (a.tenant_id,)).description or []] == [
            "user_id",
            "member_role",
        ]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # başka kiracının listesi
            conn.execute(sql, (b.tenant_id,))
    with role_tx(database.worker_dsn()) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(sql, (a.tenant_id,))  # bağlamsız
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(sql, (a.tenant_id,))
    secdef, owner, config, worker_exec, app_exec, public_exec, *_ = _function_row(
        admin_conn, "notify_gate", "tenant_recipients"
    )
    assert (secdef, owner, worker_exec, app_exec, public_exec) == (
        True,
        "netkar_notify_gate",
        True,
        False,
        False,
    )
    assert config == ["search_path=pg_catalog, public, pg_temp"]
    assert col_privs(admin_conn, "netkar_notify_gate", "memberships", "SELECT") == {
        "user_id",
        "tenant_id",
        "role",
    }
