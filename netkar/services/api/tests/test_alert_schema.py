"""Migrasyon 0025 (ADR-0009 D2): uyarı olayları, geçiş defteri, bildirim tabloları, gate işlevleri.

Kapsam: yetki matrisi (app, worker, auth, PUBLIC, notify_gate), RLS kiracı yalıtımı (IDOR), değişmezlik (superuser ve
replica rolü dahil 23514), dedupe çakışması, durum geçişinin yalnız ekleme ile yapılması (matris, rol, süre), outbox'ta
adres sütunu olmaması, `notify_gate` ve `alert_gate` işlevleri, veri sürüm tetikleyicisinin etkilenmemesi ve
upgrade/downgrade/upgrade döngüsü ile downgrade koruması.

Dosya adı bilerek `test_alert_schema.py`: `make test-alerts` yalnız `tests/test_alerts_*.py` (DB'siz, saf kural testleri)
koşar; bu dosya gerçek PostgreSQL ister.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb
from sqlalchemy import inspect as sa_inspect

from app.models import (
    AlertEvaluation,
    AlertEvent,
    AlertEventTransition,
    AlertRuleSettings,
    NotificationOutbox,
    NotificationPreference,
    NotificationSettings,
    PushSubscription,
)
from tests.conftest import DatabaseInfo
from tests.sync_helpers import Seller, make_seller

NEW_TABLES = (
    "alert_events",
    "alert_event_transitions",
    "alert_rule_settings",
    "notification_preferences",
    "notification_settings",
    "push_subscriptions",
    "notification_outbox",
    "alert_evaluations",
)
MODELS: tuple[type[Any], ...] = (
    AlertEvent,
    AlertEventTransition,
    AlertRuleSettings,
    NotificationPreference,
    NotificationSettings,
    PushSubscription,
    NotificationOutbox,
    AlertEvaluation,
)
RULES = ("ZARARINA_SATIS", "REKLAM_KARI_YIYOR", "BEKLENMEYEN_KESINTI", "IADE_ORANI_ARTISI")
DIGEST = "ab" * 32


# ---- yardımcılar ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    """İki kiracı: A'da owner, admin, viewer; B'de owner. `stranger` hiçbir kiracının üyesi değil."""

    a: Seller
    b: Seller
    admin_id: UUID
    viewer_id: UUID
    stranger_id: UUID


def _add_user(
    conn: psycopg.Connection[Any], tenant_id: UUID | None, role: str | None, verified: bool = True
) -> UUID:
    user_id = uuid4()
    conn.execute(
        "INSERT INTO users (id, email, password_hash, email_verified_at) VALUES (%s, %s, 'x', %s)",
        (user_id, f"{user_id.hex[:10]}@example.com", datetime.now(UTC) if verified else None),
    )
    if tenant_id is not None and role is not None:
        conn.execute(
            "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, %s::membership_role)",
            (user_id, tenant_id, role),
        )
    return user_id


def make_world(conn: psycopg.Connection[Any]) -> World:
    a = make_seller(conn)
    b = make_seller(conn, seller_id="9999")
    for seller in (a, b):
        conn.execute(
            "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'owner')",
            (seller.user_id, seller.tenant_id),
        )
        conn.execute("UPDATE users SET email_verified_at = now() WHERE id = %s", (seller.user_id,))
    return World(
        a=a,
        b=b,
        admin_id=_add_user(conn, a.tenant_id, "admin"),
        viewer_id=_add_user(conn, a.tenant_id, "viewer"),
        stranger_id=_add_user(conn, None, None),
    )


@contextmanager
def role_tx(
    dsn: str, tenant: UUID | None = None, user: UUID | None = None, *, commit: bool = False
) -> Iterator[psycopg.Connection[Any]]:
    """Verilen rolle işlem açar; RLS bağlamı işlem yerel kurulur; çıkışta geri alınır (commit=True: onaylanır)."""
    with psycopg.connect(dsn) as conn:
        if tenant is not None:
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
        if user is not None:
            conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user),))
        yield conn
        if commit:
            conn.commit()
        else:
            conn.rollback()


def dedupe(rule: str, account_id: UUID, subject: str) -> str:
    return hashlib.sha256(f"{rule}|{account_id}|{subject}".encode()).hexdigest()


EVENT_INSERT = (
    "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, severity, "
    "payload, payload_version, data_revision, settings_revision) "
    "VALUES (%s, %s, %s, %s, %s, %s, 'high', %s, 1, 3, 2) RETURNING id"
)


def add_event(
    conn: psycopg.Connection[Any],
    seller: Seller,
    *,
    rule: str = "ZARARINA_SATIS",
    scope: str = "product",
    subject: str = "urun:BC-1",
    payload: dict[str, Any] | None = None,
) -> UUID:
    row = conn.execute(
        EVENT_INSERT,
        (
            seller.tenant_id,
            seller.account_id,
            rule,
            scope,
            subject,
            dedupe(rule, seller.account_id, subject),
            Jsonb(payload if payload is not None else {"loss_line_count": 2}),
        ),
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


TRANSITION = "INSERT INTO alert_event_transitions (tenant_id, alert_event_id, to_status, muted_until) VALUES (%s, %s, %s, %s)"


def transition(
    conn: psycopg.Connection[Any], seller: Seller, event_id: UUID, to: str, until: datetime | None = None
) -> None:
    conn.execute(TRANSITION, (seller.tenant_id, event_id, to, until))


def event_state(conn: psycopg.Connection[Any], event_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, muted_until, resolved_at FROM alert_events WHERE id = %s", (event_id,)
    ).fetchone()
    assert row is not None
    return row  # type: ignore[no-any-return]


def days(n: float) -> datetime:
    return datetime.now(UTC) + timedelta(days=n)


@contextmanager
def immutable_guard_disabled(conn: psycopg.Connection[Any]) -> Iterator[None]:
    """Kimlik/durum tetikleyicisini yalnız zaman kaydırmak için kapatır (DDL yetkisi gerekir), ALWAYS ile açar."""
    conn.execute("ALTER TABLE alert_events DISABLE TRIGGER alert_events_immutable_guard")
    try:
        yield
    finally:
        conn.execute("ALTER TABLE alert_events ENABLE ALWAYS TRIGGER alert_events_immutable_guard")


def all_columns(conn: psycopg.Connection[Any], table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
        )
    }


def col_privs(conn: psycopg.Connection[Any], role: str, table: str, priv: str) -> set[str]:
    rows = conn.execute(
        "SELECT a.attname FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attnum > 0 "
        "AND NOT a.attisdropped AND has_column_privilege(%s, a.attrelid, a.attnum, %s)",
        (f"public.{table}", role, priv),
    ).fetchall()
    return {r[0] for r in rows}


def table_priv(conn: psycopg.Connection[Any], role: str, table: str, priv: str) -> bool:
    row = conn.execute("SELECT has_table_privilege(%s, %s, %s)", (role, f"public.{table}", priv)).fetchone()
    assert row is not None
    return bool(row[0])


@pytest.fixture
def world(admin_conn: psycopg.Connection[Any]) -> World:
    return make_world(admin_conn)


# ===================================================================================== şema, RLS, ORM


def test_tables_have_forced_rls_a_policy_and_no_data_version_trigger_names(
    admin_conn: psycopg.Connection[Any],
) -> None:
    for table in NEW_TABLES:
        row = admin_conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity, "
            "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname AND p.schemaname = 'public') "
            "FROM pg_class c WHERE c.oid = %s::regclass",
            (f"public.{table}",),
        ).fetchone()
        assert row is not None and row[0] and row[1] and row[2] >= 1, table
    # test_profit_settings_history_schema.py 'trg\_%guard' sorgusuna takılmamak için trg_ öneki kullanılmaz.
    names = [
        r[0]
        for r in admin_conn.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = ANY(%s::regclass[])",
            ([f"public.{t}" for t in NEW_TABLES],),
        )
    ]
    assert names and not [n for n in names if n.startswith("trg_")]


def test_orm_models_match_database_columns(admin_conn: psycopg.Connection[Any]) -> None:
    for model in MODELS:
        mapper: Any = sa_inspect(model)
        assert {c.key for c in mapper.columns} == all_columns(admin_conn, model.__tablename__), (
            model.__tablename__
        )


def test_identity_and_guard_triggers_are_enable_always_and_truncate_guards_are_not(
    admin_conn: psycopg.Connection[Any],
) -> None:
    rows = admin_conn.execute(
        "SELECT c.relname, t.tgname, t.tgenabled, (t.tgtype & 32) = 32 AS is_truncate FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal AND c.relname = ANY(%s)",
        (list(NEW_TABLES),),
    ).fetchall()
    assert rows
    for _, name, enabled, is_truncate in rows:
        assert enabled == ("O" if is_truncate else "A"), (
            name
        )  # TRUNCATE tetikleyicileri 0022 gibi replica ile atlanır
    expected = {
        "alert_events_insert_guard",
        "alert_events_immutable_guard",
        "alert_events_delete_guard",
        "alert_events_truncate_guard",
        "alert_event_transitions_insert_guard",
        "alert_event_transitions_apply",
        "alert_event_transitions_immutable",
        "alert_event_transitions_truncate_guard",
        "alert_rule_settings_guard",
        "notification_preferences_touch_guard",
        "notification_settings_touch_guard",
        "push_subscriptions_guard",
        "notification_outbox_guard",
        "alert_evaluations_guard",
    }
    assert {r[1] for r in rows} == expected


def test_trigger_functions_pin_search_path_and_the_state_writer_is_a_locked_down_security_definer(
    admin_conn: psycopg.Connection[Any],
) -> None:
    rows = admin_conn.execute(
        "SELECT p.proname, p.prosecdef, r.rolname, p.proconfig, has_function_privilege('public', p.oid, 'EXECUTE') "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE n.nspname = 'public' AND (p.proname LIKE 'alert\\_%' OR p.proname LIKE 'push\\_subscriptions\\_%' "
        "OR p.proname LIKE 'notification\\_outbox\\_%')"
    ).fetchall()
    by_name = {r[0]: r for r in rows}
    assert "alert_event_transitions_apply" in by_name and "alert_jsonb_is_safe" in by_name
    for name, secdef, owner, config, _ in rows:
        assert config == ["search_path=pg_catalog, public, pg_temp"], name
        assert owner == "netkar_owner" or not secdef, name
        assert secdef is (name == "alert_event_transitions_apply"), name
    assert by_name["alert_event_transitions_apply"][4] is False  # PUBLIC EXECUTE yok


# ===================================================================================== yetki matrisi


def test_privilege_matrix_for_app_worker_auth_public_and_notify_gate(
    admin_conn: psycopg.Connection[Any],
) -> None:
    cols = {t: all_columns(admin_conn, t) for t in NEW_TABLES}
    none: set[str] = set()
    push_secret = {"endpoint_enc", "p256dh_enc", "auth_enc"}
    app: dict[str, dict[str, set[str]]] = {
        "alert_events": {"select": cols["alert_events"], "insert": none, "update": none},
        "alert_event_transitions": {
            "select": cols["alert_event_transitions"],
            "insert": {"tenant_id", "alert_event_id", "to_status", "muted_until"},
            "update": none,
        },
        "alert_rule_settings": {
            "select": cols["alert_rule_settings"],
            "insert": {
                "tenant_id",
                "marketplace_account_id",
                "loss_min_amount",
                "ad_share_percent",
                "ad_min_spend",
                "deduction_notify_min",
                "return_min_diff_points",
                "rules_enabled",
            },
            "update": {
                "loss_min_amount",
                "ad_share_percent",
                "ad_min_spend",
                "deduction_notify_min",
                "return_min_diff_points",
                "rules_enabled",
            },
        },
        "notification_preferences": {
            "select": cols["notification_preferences"],
            "insert": {"tenant_id", "user_id", "rule", "channel", "mode"},
            "update": {"mode"},  # updated_at sunucuda (tetikleyici)
        },
        "notification_settings": {
            "select": cols["notification_settings"],
            "insert": {
                "tenant_id",
                "user_id",
                "quiet_start",
                "quiet_end",
                "digest_hour",
                "show_amounts_email",
                "show_amounts_push",
            },
            "update": {
                "quiet_start",
                "quiet_end",
                "digest_hour",
                "show_amounts_email",
                "show_amounts_push",
            },
        },
        "push_subscriptions": {
            "select": cols["push_subscriptions"] - push_secret,
            "insert": {
                "tenant_id",
                "user_id",
                "endpoint_host",
                "endpoint_digest",
                "endpoint_enc",
                "p256dh_enc",
                "auth_enc",
                "vapid_key_id",
                "created_session_id",
            },
            "update": {"revoked_at"},
        },
        "notification_outbox": {"select": none, "insert": none, "update": none},  # outbox'a erişemez
        "alert_evaluations": {"select": cols["alert_evaluations"], "insert": none, "update": none},
    }
    worker: dict[str, dict[str, set[str]]] = {
        "alert_events": {
            "select": cols["alert_events"],
            "insert": {
                "tenant_id",
                "marketplace_account_id",
                "rule",
                "scope",
                "subject",
                "dedupe_key",
                "last_seen_at",
                "occurrence_count",
                "severity",
                "payload",
                "payload_version",
                "data_revision",
                "settings_revision",
                "last_notified_at",
                "notified_amount",
                "renotified",
                "notify_mode",
            },
            # Kimlik ve durum sütunları yok: durum yalnız geçiş tablosuyla değişir.
            "update": {
                "last_seen_at",
                "occurrence_count",
                "severity",
                "payload",
                "payload_version",
                "data_revision",
                "settings_revision",
                "last_notified_at",
                "notified_amount",
                "renotified",
                "notify_mode",
            },
        },
        "alert_event_transitions": {
            "select": cols["alert_event_transitions"],
            "insert": {"tenant_id", "alert_event_id", "to_status", "muted_until"},
            "update": none,
        },
        "alert_rule_settings": {"select": cols["alert_rule_settings"], "insert": none, "update": none},
        "notification_preferences": {
            "select": cols["notification_preferences"],
            "insert": none,
            "update": none,
        },
        "notification_settings": {"select": cols["notification_settings"], "insert": none, "update": none},
        "push_subscriptions": {
            "select": cols["push_subscriptions"],
            "insert": none,
            "update": {"last_success_at", "failure_count", "revoked_at"},
        },
        "notification_outbox": {
            "select": cols["notification_outbox"],
            "insert": {
                "tenant_id",
                "user_id",
                "channel",
                "kind",
                "dedupe_key",
                "alert_event_ids",
                "payload",
                "status",
                "not_before",
            },
            "update": {"status", "not_before", "attempts", "last_error_class"},
        },
        "alert_evaluations": {
            "select": cols["alert_evaluations"],
            "insert": {
                "tenant_id",
                "marketplace_account_id",
                "as_of_date",
                "data_revision",
                "settings_revision",
                "rules_version",
                "attempt",  # migrasyon 0026
            },
            "update": {"status", "counts"},
        },
    }
    for role, expected in (("netkar_app", app), ("netkar_worker", worker)):
        for table in NEW_TABLES:
            for priv in ("select", "insert", "update"):
                actual = col_privs(admin_conn, role, table, priv.upper())
                assert actual == expected[table][priv], (role, table, priv, actual ^ expected[table][priv])
    # DELETE ve TRUNCATE (ve REFERENCES, TRIGGER) hiçbir uygulama rolünde yok; PUBLIC, auth ve gate hiçbir şey almaz.
    for role in (
        "netkar_app",
        "netkar_worker",
        "netkar_auth",
        "public",
        "netkar_sync_gate",
        "netkar_notify_gate",
    ):
        for table in NEW_TABLES:
            for priv in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert not table_priv(admin_conn, role, table, priv), (role, table, priv)
    for role in ("netkar_auth", "public", "netkar_sync_gate"):
        for table in NEW_TABLES:
            for priv in ("SELECT", "INSERT", "UPDATE"):
                assert not col_privs(admin_conn, role, table, priv), (role, table, priv)
    # netkar_notify_gate: yalnız outbox'ta altı sütun SELECT (+ `last_error_class`, migrasyon 0027); başka yetki yok.
    for table in NEW_TABLES:
        for priv in ("INSERT", "UPDATE"):
            assert not col_privs(admin_conn, "netkar_notify_gate", table, priv)
        expected_select = (
            {"id", "tenant_id", "user_id", "status", "channel", "not_before", "last_error_class"}
            if table == "notification_outbox"
            else set()
        )
        assert col_privs(admin_conn, "netkar_notify_gate", table, "SELECT") == expected_select, table
    assert col_privs(admin_conn, "netkar_notify_gate", "users", "SELECT") == {
        "id",
        "email",
        "email_verified_at",
    }
    assert col_privs(admin_conn, "netkar_notify_gate", "memberships", "SELECT") == {
        "user_id",
        "tenant_id",
        "role",  # migrasyon 0027: özet alıcı rolü (`notify_gate.tenant_recipients`)
    }
    for table in ("users", "memberships"):
        for priv in ("INSERT", "UPDATE"):
            assert not col_privs(admin_conn, "netkar_notify_gate", table, priv)
    login_flags = admin_conn.execute(
        "SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'netkar_notify_gate'"
    ).fetchone()
    assert login_flags == (False, False, False)


def test_app_role_cannot_write_events_or_touch_the_outbox_and_cannot_read_push_secrets(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    event_id = add_event(admin_conn, a)
    admin_conn.execute(
        "INSERT INTO notification_outbox (tenant_id, user_id, channel, kind, dedupe_key, alert_event_ids) "
        "VALUES (%s, %s, 'email', 'instant', %s, %s)",
        (a.tenant_id, a.user_id, DIGEST, [event_id]),
    )
    statements = (
        ("UPDATE alert_events SET severity = 'medium'", ()),
        ("UPDATE alert_events SET status = 'resolved'", ()),
        ("DELETE FROM alert_events", ()),
        ("TRUNCATE alert_events", ()),
        ("TRUNCATE alert_event_transitions", ()),
        ("DELETE FROM alert_event_transitions", ()),
        ("UPDATE alert_event_transitions SET to_status = 'open'", ()),
        ("SELECT count(*) FROM notification_outbox", ()),
        (
            "INSERT INTO notification_outbox (tenant_id, user_id, channel, kind, dedupe_key) VALUES (%s, %s, 'email', 'test', %s)",
            (a.tenant_id, a.user_id, "cd" * 32),
        ),
        ("SELECT * FROM notification_outbox", ()),
        ("SELECT endpoint_enc FROM push_subscriptions", ()),
        ("SELECT * FROM push_subscriptions", ()),
    )
    for sql, params in statements:
        with (
            role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(sql, params)  # type: ignore[call-overload]


# ===================================================================================== RLS kiracı yalıtımı (IDOR)


def test_tenant_isolation_for_events_transitions_evaluations_and_settings(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    event_a, event_b = add_event(admin_conn, a), add_event(admin_conn, b)
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        transition(conn, a, event_a, "resolved")
    with role_tx(database.worker_dsn(), b.tenant_id, commit=True) as conn:
        transition(conn, b, event_b, "resolved")
    admin_conn.execute(
        "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, "
        "settings_revision, rules_version) VALUES (%s, %s, '2026-11-20', 1, 1, 1), (%s, %s, '2026-11-20', 1, 1, 1)",
        (a.tenant_id, a.account_id, b.tenant_id, b.account_id),
    )
    admin_conn.execute(
        "INSERT INTO alert_rule_settings (tenant_id, marketplace_account_id, updated_by) VALUES (%s, %s, %s), (%s, %s, %s)",
        (a.tenant_id, a.account_id, a.user_id, b.tenant_id, b.account_id, b.user_id),
    )
    for dsn in (database.app_dsn(), database.worker_dsn()):
        with role_tx(dsn, a.tenant_id, a.user_id) as conn:
            assert conn.execute("SELECT id FROM alert_events").fetchall() == [(event_a,)]
            assert conn.execute("SELECT alert_event_id FROM alert_event_transitions").fetchall() == [
                (event_a,)
            ]
            assert conn.execute("SELECT tenant_id FROM alert_evaluations").fetchall() == [(a.tenant_id,)]
            assert conn.execute("SELECT tenant_id FROM alert_rule_settings").fetchall() == [(a.tenant_id,)]
            # Başka kiracının olayı kimlikle istenirse de görünmez (IDOR).
            assert conn.execute("SELECT count(*) FROM alert_events WHERE id = %s", (event_b,)).fetchone() == (
                0,
            )
        with role_tx(dsn) as conn:  # bağlamsız oturum hiçbir satır görmez
            for table in (
                "alert_events",
                "alert_event_transitions",
                "alert_evaluations",
                "alert_rule_settings",
            ):
                assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def test_cannot_add_a_transition_to_another_tenants_event_or_forge_the_tenant(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    event_b = add_event(admin_conn, b)
    # A bağlamında B'nin olayına: kendi kiracı kimliğiyle olay görünmez (23503); B'nin kiracı kimliğiyle RLS reddeder.
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        transition(conn, a, event_b, "read")
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ForeignKeyViolation)),
    ):
        transition(conn, b, event_b, "read")
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        transition(conn, a, event_b, "resolved")
    # Olay yazma: worker başka kiracı kimliğiyle olay ekleyemez (RLS WITH CHECK).
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            EVENT_INSERT,
            (
                b.tenant_id,
                b.account_id,
                "ZARARINA_SATIS",
                "product",
                "urun:X",
                dedupe("ZARARINA_SATIS", b.account_id, "urun:X"),
                Jsonb({}),
            ),
        )
    assert admin_conn.execute("SELECT count(*) FROM alert_event_transitions").fetchone() == (0,)


def test_per_user_tables_are_visible_only_to_their_owner_and_readable_by_the_tenant_worker(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    for user, tenant in ((a.user_id, a.tenant_id), (world.admin_id, a.tenant_id), (b.user_id, b.tenant_id)):
        admin_conn.execute(
            "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, 'email', 'digest')",
            (tenant, user, RULES[0]),
        )
        admin_conn.execute(
            "INSERT INTO notification_settings (tenant_id, user_id) VALUES (%s, %s)", (tenant, user)
        )
        admin_conn.execute(
            "INSERT INTO push_subscriptions (tenant_id, user_id, endpoint_host, endpoint_digest, endpoint_enc, p256dh_enc, "
            "auth_enc, vapid_key_id) VALUES (%s, %s, 'fcm.googleapis.com', %s, 'v1:e', 'v1:p', 'v1:a', 'k1')",
            (tenant, user, uuid4().hex + uuid4().hex),
        )
    for table in ("notification_preferences", "notification_settings", "push_subscriptions"):
        with role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn:
            assert conn.execute(f"SELECT user_id FROM {table}").fetchall() == [(a.user_id,)]
        with role_tx(database.app_dsn(), a.tenant_id) as conn:  # kullanıcı bağlamı yok
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        with role_tx(
            database.worker_dsn(), a.tenant_id
        ) as conn:  # worker kiracı içinde iki kullanıcıyı da okur
            assert {r[0] for r in conn.execute(f"SELECT user_id FROM {table}").fetchall()} == {
                a.user_id,
                world.admin_id,
            }
    # Kullanıcı başkasının (aynı kiracıda) ya da başka kiracının satırını yazamaz.
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, 'push', 'off')",
            (a.tenant_id, world.admin_id, RULES[1]),
        )
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "INSERT INTO notification_settings (tenant_id, user_id) VALUES (%s, %s)", (b.tenant_id, a.user_id)
        )
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn:
        # Kendi satırı güncellenir; başkasının satırı 0 satır etkiler.
        assert conn.execute("UPDATE notification_preferences SET mode = 'off'").rowcount == 1
    # Worker tercih tablolarına yazamaz.
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE notification_preferences SET mode = 'off'")


# ===================================================================================== değişmezlik


IDENTITY_UPDATES = (
    ("id", "gen_random_uuid()"),
    ("tenant_id", "(SELECT id FROM tenants WHERE id <> alert_events.tenant_id LIMIT 1)"),
    ("marketplace_account_id", "gen_random_uuid()"),
    ("rule", "'IADE_ORANI_ARTISI'"),
    ("scope", "'account'"),
    ("subject", "'hesap:*'"),
    ("dedupe_key", "repeat('0', 64)"),
    ("first_seen_at", "now() - interval '1 day'"),
    ("created_at", "now() - interval '1 day'"),
)


def test_identity_columns_are_immutable_even_for_superuser_and_replica_role(
    admin_conn: psycopg.Connection[Any], world: World
) -> None:
    add_event(admin_conn, world.a)
    for replica in (False, True):
        for column, value in IDENTITY_UPDATES:
            with admin_conn.transaction(force_rollback=True):
                if replica:
                    admin_conn.execute(
                        "SET LOCAL session_replication_role = replica"
                    )  # ENABLE ALWAYS atlanamaz
                with pytest.raises(psycopg.errors.CheckViolation, match="kimlik"):
                    admin_conn.execute(f"UPDATE alert_events SET {column} = {value}")  # type: ignore[call-overload]


def test_status_columns_change_only_through_the_transition_ledger(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    event_id = add_event(admin_conn, world.a)
    updates = (
        "UPDATE alert_events SET status = 'resolved', resolved_at = now()",
        "UPDATE alert_events SET status = 'read'",
        "UPDATE alert_events SET muted_until = now() + interval '1 day', status = 'muted'",
        "UPDATE alert_events SET resolved_at = now()",
    )
    for sql in updates:  # superuser dahil, replica rolü dahil
        for replica in (False, True):
            with admin_conn.transaction(force_rollback=True):
                if replica:
                    admin_conn.execute("SET LOCAL session_replication_role = replica")
                with pytest.raises(psycopg.errors.CheckViolation, match="alert_event_transitions"):
                    admin_conn.execute(sql)  # type: ignore[call-overload]
    # Sistem sütunlarının güncellenmesi serbesttir (worker); durum etkilenmez.
    with role_tx(database.worker_dsn(), world.a.tenant_id) as conn:
        assert conn.execute("UPDATE alert_events SET occurrence_count = 5, renotified = true").rowcount == 1
    assert event_state(admin_conn, event_id)[0] == "open"


def test_new_events_are_born_open_with_server_set_fields(
    admin_conn: psycopg.Connection[Any], world: World
) -> None:
    row = admin_conn.execute(
        "INSERT INTO alert_events (id, tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, severity, "
        "payload_version, data_revision, settings_revision, status, muted_until, first_seen_at, created_at) "
        "VALUES (%s, %s, %s, 'ZARARINA_SATIS', 'product', 'urun:Z', %s, 'high', 1, 0, 0, 'resolved', NULL, "
        "now() - interval '9 days', now() - interval '9 days') "
        "RETURNING id <> %s, status, resolved_at, now() - first_seen_at < interval '1 minute', "
        "now() - created_at < interval '1 minute'",
        (
            uuid4(),
            world.a.tenant_id,
            world.a.account_id,
            dedupe("ZARARINA_SATIS", world.a.account_id, "urun:Z"),
            UUID(int=0),
        ),
    ).fetchone()
    assert row is not None
    assert row[1:] == ("open", None, True, True)


# ===================================================================================== dedupe ve kısıtlar


def test_dedupe_key_is_unique_per_tenant_and_account_and_worker_can_upsert(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    add_event(admin_conn, a)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_event(admin_conn, a)
    # Aynı konu başka kiracıda ve başka kuralda ayrı olaydır.
    add_event(admin_conn, b)
    add_event(admin_conn, a, rule="REKLAM_KARI_YIYOR")
    upsert = (
        "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, severity, "
        "payload, payload_version, data_revision, settings_revision) VALUES (%s, %s, 'ZARARINA_SATIS', 'product', "
        "'urun:BC-1', %s, 'high', %s, 1, 9, 9) ON CONFLICT (tenant_id, marketplace_account_id, dedupe_key) DO UPDATE "
        "SET occurrence_count = alert_events.occurrence_count + 1, last_seen_at = now(), data_revision = EXCLUDED.data_revision "
        "RETURNING occurrence_count, data_revision"
    )
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        key = dedupe("ZARARINA_SATIS", a.account_id, "urun:BC-1")
        assert conn.execute(upsert, (a.tenant_id, a.account_id, key, Jsonb({}))).fetchone() == (2, 9)
        assert conn.execute(upsert, (a.tenant_id, a.account_id, key, Jsonb({}))).fetchone() == (3, 9)
    assert admin_conn.execute(
        "SELECT count(*) FROM alert_events WHERE tenant_id = %s", (a.tenant_id,)
    ).fetchone() == (2,)


def test_event_check_constraints(admin_conn: psycopg.Connection[Any], world: World) -> None:
    a = world.a
    bad = (
        {"rule": "BASKA_KURAL"},
        {"scope": "tenant"},
        {"scope": "account", "subject": "urun:X"},
        {"scope": "product", "subject": "hesap:*"},
        {"scope": "product", "subject": "urun:"},
        {"scope": "order_line", "subject": "urun:X"},
    )
    for i, override in enumerate(bad):
        kwargs: dict[str, Any] = {"subject": f"urun:CK{i}", **override}
        with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            add_event(admin_conn, a, **kwargs)
    with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, severity, "
            "payload_version, data_revision, settings_revision) VALUES (%s, %s, 'ZARARINA_SATIS', 'product', 'urun:D', 'xyz', "
            "'high', 1, 0, 0)",
            (a.tenant_id, a.account_id),
        )
    # İyi biçimli olay: hesap ve kiracı çifti tutarlı olmalı (bileşik FK).
    with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_event(admin_conn, Seller(world.b.tenant_id, a.user_id, a.account_id, "x"), subject="urun:FK")


FORBIDDEN_PAYLOADS = (
    {"email": "a@b.c"},
    {"Email": "a@b.c"},
    {"customer_name": "x"},
    {"name": "x"},
    {"nested": {"deep": [{"address": "x"}]}},
    {"phone": "5"},
    {"tckn": "1"},
    {"x": "y" * 5000},
)


def test_event_payload_is_allow_listed_at_every_depth_with_value_checks(
    admin_conn: psycopg.Connection[Any], world: World
) -> None:
    deep: dict[str, Any] = {"loss_line_count": 1}
    for _ in range(400):  # 4096 bayt sınırı: izinli anahtarlarla bile iç içe şişirilemez
        deep = {"evidence": deep}
    bad_payloads: list[Any] = [
        {"musteri_adi": "x"},
        {"customerName": "x"},
        {"eposta": "a@b.c"},
        {"email": "a@b.c"},
        {"adres": "x"},
        {"telefon": "5"},
        {"recipient": "x"},
        {"name": "x"},
        {"Loss_line_count": 1},  # büyük/küçük harf farkı da listede yok
        {"buyer": {"fullName": "x"}},
        {"evidence": {"buyer": {"fullName": "x"}}},
        {"evidence": {"loss_line_count": 1, "address": "x"}},
        {"reason_codes": "ali@example.com"},  # e-posta biçimli değer
        {"reason_codes": "x" * 201},  # metin uzunluk sınırı
        {"loss_line_count": [1, 2]},  # dizi yok
        {"evidence": [{"loss_line_count": 1}]},
        deep,
        [1, 2],
        "metin",
        5,
    ]
    for payload in bad_payloads:
        with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            add_event(admin_conn, world.a, payload=payload)
    # Bilinmeyen kural sürümü reddedilir.
    with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, severity, "
            "payload_version, data_revision, settings_revision) VALUES (%s, %s, 'ZARARINA_SATIS', 'product', 'urun:V2', %s, "
            "'high', 2, 0, 0)",
            (world.a.tenant_id, world.a.account_id, "ab" * 32),
        )
    # Geçerli kanıt yükleri: kural kanıt alanları, certainty ve iç içe evidence; 200 karakterlik metin kabul edilir.
    add_event(
        admin_conn,
        world.a,
        subject="urun:P1",
        payload={
            "loss_line_count": 3,
            "total_loss": "412.30",
            "worst_line_loss": "180.00",
            "has_missing_items": True,
            "certainty": "tahmini",
        },
    )
    add_event(
        admin_conn,
        world.a,
        subject="urun:P2",
        payload={
            "certainty": "kesin",
            "evidence": {"current_lines": 40, "current_start": "2026-10-01", "reason_codes": "a,b,c"},
        },
    )
    add_event(admin_conn, world.a, subject="urun:P3", payload={"reason_codes": "x" * 200})
    add_event(admin_conn, world.a, subject="urun:P4", payload={})


# ===================================================================================== geçiş defteri


def test_user_transition_matrix_by_role(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    event_id = add_event(admin_conn, a)
    # Görüntüleyici okundu/açık yapabilir.
    with role_tx(database.app_dsn(), a.tenant_id, world.viewer_id, commit=True) as conn:
        transition(conn, a, event_id, "read")
    assert event_state(admin_conn, event_id)[0] == "read"
    with role_tx(database.app_dsn(), a.tenant_id, world.viewer_id, commit=True) as conn:
        transition(conn, a, event_id, "open")
    # Görüntüleyici susturamaz; üye olmayan hiçbir şey yapamaz.
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.viewer_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        transition(conn, a, event_id, "muted", days(3))
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.stranger_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        transition(conn, a, event_id, "read")
    with (
        role_tx(database.app_dsn(), a.tenant_id, None) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        transition(conn, a, event_id, "read")  # kullanıcı bağlamı yok
    # Hiçbir kullanıcı çözemez ya da aynı duruma geçiremez.
    for to in ("resolved", "open"):
        with (
            role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            transition(conn, a, event_id, to)
    # Owner ve admin susturur; muted_until zorunlu ve en çok 90 gün.
    for bad in (None, days(-1), days(91)):
        with (
            role_tx(database.app_dsn(), a.tenant_id, world.admin_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            transition(conn, a, event_id, "muted", bad)
    until = days(89)
    with role_tx(database.app_dsn(), a.tenant_id, world.admin_id, commit=True) as conn:
        transition(conn, a, event_id, "muted", until)
    status, muted_until, resolved_at = event_state(admin_conn, event_id)
    assert status == "muted" and resolved_at is None and abs((muted_until - until).total_seconds()) < 1
    # Susturulmuş olay: kullanıcı yalnız owner/admin açar, muted -> read yok; muted_until açık olmayan geçişte yazılamaz.
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.viewer_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        transition(conn, a, event_id, "open")
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        transition(conn, a, event_id, "read")
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        transition(conn, a, event_id, "open", days(3))  # muted_until yalnız muted için; trigger sıfırlar
    assert event_state(admin_conn, event_id) == ("open", None, None)
    rows = admin_conn.execute(
        "SELECT from_status, to_status, actor, actor_user_id FROM alert_event_transitions ORDER BY created_at, to_status"
    ).fetchall()
    assert len(rows) == 4
    assert {r[2] for r in rows} == {"user"} and all(r[3] is not None for r in rows)
    assert {(r[0], r[1]) for r in rows} == {
        ("open", "read"),
        ("read", "open"),
        ("open", "muted"),
        ("muted", "open"),
    }


def test_client_cannot_supply_server_derived_ledger_columns(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    event_id = add_event(admin_conn, a)
    for column, value in (
        ("actor", "'system'"),
        ("actor_user_id", f"'{world.admin_id}'"),
        ("from_status", "'resolved'"),
        ("id", f"'{uuid4()}'"),
        ("created_at", "now() - interval '9 days'"),
    ):
        for dsn in (database.app_dsn(), database.worker_dsn()):
            with (
                role_tx(dsn, a.tenant_id, a.user_id) as conn,
                pytest.raises(psycopg.errors.InsufficientPrivilege),
            ):
                conn.execute(  # type: ignore[call-overload]
                    f"INSERT INTO alert_event_transitions (tenant_id, alert_event_id, to_status, {column}) "
                    f"VALUES (%s, %s, 'read', {value})",
                    (a.tenant_id, event_id),
                )
    # Kimlik her zaman bağlamdan: worker asla 'user', uygulama asla 'system' yazamaz.
    with role_tx(database.worker_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        transition(conn, a, event_id, "resolved")
    row = admin_conn.execute(
        "SELECT actor, actor_user_id, from_status FROM alert_event_transitions"
    ).fetchone()
    assert row == ("system", None, "open")


def test_system_transition_matrix_and_resolved_marks(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    event_id = add_event(admin_conn, a)
    worker = database.worker_dsn()
    # Sistem: open -> resolved (resolved_at atanır); resolved -> read ya da muted yok.
    with role_tx(worker, a.tenant_id, commit=True) as conn:
        transition(conn, a, event_id, "resolved")
    status, muted_until, resolved_at = event_state(admin_conn, event_id)
    assert status == "resolved" and muted_until is None and resolved_at is not None
    for to in ("read", "muted", "resolved"):
        with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
            transition(conn, a, event_id, to, days(2) if to == "muted" else None)
    with role_tx(worker, a.tenant_id, commit=True) as conn:
        transition(conn, a, event_id, "open")  # yeniden görülme
    assert event_state(admin_conn, event_id) == ("open", None, None)
    # open -> muted sistemin işi değil; kullanıcı susturur, süre dolmadan sistem açamaz, dolunca açar.
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        transition(conn, a, event_id, "muted", days(2))
    with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="sure"):
        transition(conn, a, event_id, "open")
    with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        transition(conn, a, event_id, "muted", days(2))
    with immutable_guard_disabled(admin_conn):
        admin_conn.execute("UPDATE alert_events SET muted_until = now() - interval '1 hour'")
    with role_tx(worker, a.tenant_id, commit=True) as conn:
        transition(conn, a, event_id, "open")
    assert event_state(admin_conn, event_id) == ("open", None, None)
    # muted -> resolved (sistem) süre dolmasa da serbest.
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        transition(conn, a, event_id, "muted", days(30))
    with role_tx(worker, a.tenant_id, commit=True) as conn:
        transition(conn, a, event_id, "resolved")
    assert event_state(admin_conn, event_id)[0] == "resolved"


def test_ledger_is_append_only_even_for_superuser(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    event_id = add_event(admin_conn, a)
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        transition(conn, a, event_id, "resolved")
    for sql in (
        "UPDATE alert_event_transitions SET to_status = 'open'",
        "UPDATE alert_event_transitions SET actor = 'user'",
        "DELETE FROM alert_event_transitions",
        "TRUNCATE alert_event_transitions",
        "TRUNCATE alert_events CASCADE",
    ):
        with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(sql)  # type: ignore[call-overload]
    for sql in (
        "UPDATE alert_event_transitions SET to_status = 'open'",
        "DELETE FROM alert_event_transitions",
    ):
        with admin_conn.transaction(force_rollback=True):
            admin_conn.execute("SET LOCAL session_replication_role = replica")  # ENABLE ALWAYS: yine reddeder
            with pytest.raises(psycopg.errors.CheckViolation):
                admin_conn.execute(sql)  # type: ignore[call-overload]
    assert admin_conn.execute("SELECT count(*) FROM alert_event_transitions").fetchone() == (1,)
    # Açık olay hiçbir rolle silinemez.
    open_id = add_event(admin_conn, a, subject="urun:OPEN")
    with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("DELETE FROM alert_events WHERE id = %s", (open_id,))


def test_concurrent_transitions_on_the_same_event_fail_with_serialization_error(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    """İki oturum aynı olayı `open` görüp geçiş eklerse ikincisi 40001 alır (olay satırı kilitlenir, durum yeniden okunur)."""
    a = world.a
    event_id = add_event(admin_conn, a)
    first = psycopg.connect(database.app_dsn())
    second = psycopg.connect(database.app_dsn())
    outcome: list[BaseException | None] = []

    def second_session() -> None:
        try:
            second.execute("SET lock_timeout = '20s'")
            second.execute("SELECT set_config('app.tenant_id', %s, true)", (str(a.tenant_id),))
            second.execute("SELECT set_config('app.user_id', %s, true)", (str(world.admin_id),))
            transition(second, a, event_id, "muted", days(2))
            second.commit()
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)
        finally:
            second.close()

    try:
        first.execute("SELECT set_config('app.tenant_id', %s, true)", (str(a.tenant_id),))
        first.execute("SELECT set_config('app.user_id', %s, true)", (str(a.user_id),))
        transition(first, a, event_id, "read")  # olay satırı bu işlemde kilitli (UPDATE), henüz onaylanmadı
        thread = threading.Thread(target=second_session)
        thread.start()
        deadline = time.monotonic() + 15
        waiting = False
        while time.monotonic() < deadline and not waiting:
            row = admin_conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock' "
                "AND usename = 'netkar_app'"
            ).fetchone()
            waiting = bool(row and row[0] >= 1)
            time.sleep(0.05)
        assert waiting, "ikinci oturum satır kilidini beklemiyor"
        first.commit()
        thread.join(timeout=20)
    finally:
        first.close()
    assert len(outcome) == 1 and isinstance(outcome[0], psycopg.errors.SerializationFailure)
    assert event_state(admin_conn, event_id)[0] == "read"
    assert admin_conn.execute("SELECT count(*) FROM alert_event_transitions").fetchone() == (1,)


# ===================================================================================== eşikler, tercihler, abonelik


def test_rule_settings_are_writable_only_by_owner_and_admin_and_stamped_server_side(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    insert = (
        "INSERT INTO alert_rule_settings (tenant_id, marketplace_account_id, loss_min_amount, ad_share_percent) "
        "VALUES (%s, %s, 7.50, 80)"
    )
    for user in (world.viewer_id, world.stranger_id):
        with (
            role_tx(database.app_dsn(), a.tenant_id, user) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(insert, (a.tenant_id, a.account_id))
    with role_tx(database.app_dsn(), a.tenant_id, world.admin_id, commit=True) as conn:
        conn.execute(insert, (a.tenant_id, a.account_id))
    row = admin_conn.execute(
        "SELECT updated_by, loss_min_amount, ad_share_percent, ad_min_spend, deduction_notify_min, return_min_diff_points, "
        "rules_enabled FROM alert_rule_settings"
    ).fetchone()
    assert row is not None and row[0] == world.admin_id
    assert [str(x) for x in row[1:6]] == ["7.50", "80.00", "50.00", "10.00", "5.00"] and row[6] == list(RULES)
    # Güncelleme: görüntüleyici reddedilir (0 satır değil, 42501), owner güncelleyince updated_by değişir.
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.viewer_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE alert_rule_settings SET loss_min_amount = 1")
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        conn.execute(
            "UPDATE alert_rule_settings SET loss_min_amount = 1, rules_enabled = ARRAY['ZARARINA_SATIS']"
        )
    assert admin_conn.execute("SELECT updated_by, rules_enabled FROM alert_rule_settings").fetchone() == (
        a.user_id,
        ["ZARARINA_SATIS"],
    )
    # Kimlik ve sunucu sütunları uygulama tarafından yazılamaz; sınır dışı değerler reddedilir.
    for column, value in (
        ("updated_by", f"'{a.user_id}'"),
        ("updated_at", "now()"),
        ("tenant_id", f"'{uuid4()}'"),
    ):
        with (
            role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(f"UPDATE alert_rule_settings SET {column} = {value}")  # type: ignore[call-overload]
    for bad in (
        "ad_share_percent = 49",
        "ad_share_percent = 101",
        "loss_min_amount = -1",
        "return_min_diff_points = 101",
        "rules_enabled = ARRAY['BASKA']",
    ):
        with (
            role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            conn.execute(f"UPDATE alert_rule_settings SET {bad}")  # type: ignore[call-overload]
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        assert conn.execute("SELECT count(*) FROM alert_rule_settings").fetchone() == (1,)
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE alert_rule_settings SET loss_min_amount = 0")


def test_preferences_and_settings_constraints(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    ok = "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, %s, %s)"
    with role_tx(database.app_dsn(), a.tenant_id, world.viewer_id, commit=True) as conn:
        conn.execute(ok, (a.tenant_id, world.viewer_id, RULES[0], "email", "off"))
        conn.execute(
            "INSERT INTO notification_settings (tenant_id, user_id) VALUES (%s, %s)",
            (a.tenant_id, world.viewer_id),
        )
    row = admin_conn.execute(
        "SELECT quiet_start, quiet_end, digest_hour, show_amounts_email, show_amounts_push FROM notification_settings"
    ).fetchone()
    assert row is not None and (str(row[0]), str(row[1]), row[2], row[3], row[4]) == (
        "22:00:00",
        "08:00:00",
        8,
        True,
        False,
    )
    for params in (
        (a.tenant_id, world.viewer_id, "BASKA", "email", "off"),
        (a.tenant_id, world.viewer_id, RULES[1], "sms", "off"),
        (a.tenant_id, world.viewer_id, RULES[1], "email", "hepsi"),
        (a.tenant_id, world.viewer_id, RULES[0], "email", "digest"),  # PK çakışması
    ):
        with (
            role_tx(database.app_dsn(), a.tenant_id, world.viewer_id) as conn,
            pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.UniqueViolation)),
        ):
            conn.execute(ok, params)
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.viewer_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute("UPDATE notification_settings SET digest_hour = 24")
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.viewer_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM notification_preferences")


PUSH_INSERT = (
    "INSERT INTO push_subscriptions (tenant_id, user_id, endpoint_host, endpoint_digest, endpoint_enc, p256dh_enc, auth_enc, "
    "vapid_key_id, created_session_id) VALUES (%s, %s, %s, %s, 'v1:e', 'v1:p', 'v1:a', 'k1', NULL) RETURNING id"
)


def test_push_subscription_lifecycle_secrets_and_revocation(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        row = conn.execute(PUSH_INSERT, (a.tenant_id, a.user_id, "fcm.googleapis.com", DIGEST)).fetchone()
        assert row is not None
        sub_id = row[0]
    # Aynı uç nokta aynı kiracıda ikinci kez eklenemez, başka kiracıda eklenebilir; ana bilgisayar küçük harf olmalı.
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.admin_id) as conn,
        pytest.raises(psycopg.errors.UniqueViolation),
    ):
        conn.execute(PUSH_INSERT, (a.tenant_id, world.admin_id, "fcm.googleapis.com", DIGEST))
    with role_tx(database.app_dsn(), b.tenant_id, b.user_id, commit=True) as conn:
        conn.execute(PUSH_INSERT, (b.tenant_id, b.user_id, "fcm.googleapis.com", DIGEST))
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute(PUSH_INSERT, (a.tenant_id, a.user_id, "FCM.googleapis.com", "cd" * 32))
    # Uygulama kendi aboneliğini (sırsız sütunlarla) okur; kimlik sütunlarını güncelleyemez.
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn:
        assert conn.execute(
            "SELECT endpoint_host, failure_count, revoked_at FROM push_subscriptions"
        ).fetchall() == [("fcm.googleapis.com", 0, None)]
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE push_subscriptions SET endpoint_host = 'evil.example'")
    # Worker şifreli alanları okur ve sayaçları günceller.
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        assert conn.execute(
            "SELECT endpoint_enc, p256dh_enc, auth_enc FROM push_subscriptions WHERE id = %s", (sub_id,)
        ).fetchone() == ("v1:e", "v1:p", "v1:a")
        conn.execute(
            "UPDATE push_subscriptions SET failure_count = 3, last_success_at = now() WHERE id = %s",
            (sub_id,),
        )
    # İptal: şifreli alanlar tetikleyiciyle silinir; geri alınamaz; zaman damgası ±5 dk içinde olmalı.
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute("UPDATE push_subscriptions SET revoked_at = now() - interval '2 days'")
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        assert conn.execute("UPDATE push_subscriptions SET revoked_at = now()").rowcount == 1
    row = admin_conn.execute(
        "SELECT revoked_at IS NOT NULL, endpoint_enc, p256dh_enc, auth_enc, failure_count FROM push_subscriptions WHERE id = %s",
        (sub_id,),
    ).fetchone()
    assert row == (True, None, None, None, 3)
    for dsn in (database.app_dsn(), database.worker_dsn()):
        with role_tx(dsn, a.tenant_id, a.user_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE push_subscriptions SET revoked_at = NULL")
    with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE push_subscriptions SET revoked_at = NULL")  # superuser dahil
    # İptal edilmemiş abonelikte şifreli alan boş olamaz.
    with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE push_subscriptions SET auth_enc = NULL WHERE revoked_at IS NULL")


# ===================================================================================== outbox


OUTBOX_INSERT = (
    "INSERT INTO notification_outbox (tenant_id, user_id, channel, kind, dedupe_key, alert_event_ids, payload, status, not_before) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
)


def add_outbox(
    conn: psycopg.Connection[Any],
    seller: Seller,
    *,
    event_ids: list[UUID] | None = None,
    key: str = DIGEST,
    status: str = "pending",
    kind: str = "instant",
    channel: str = "email",
    payload: dict[str, Any] | None = None,
    not_before: datetime | None = None,
    user_id: UUID | None = None,
) -> UUID:
    row = conn.execute(
        OUTBOX_INSERT,
        (
            seller.tenant_id,
            user_id or seller.user_id,
            channel,
            kind,
            key,
            event_ids if event_ids is not None else [],
            Jsonb(payload if payload is not None else {"rule_counts": {"ZARARINA_SATIS": 2}}),
            status,
            not_before or datetime.now(UTC),
        ),
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def test_outbox_has_no_address_column_and_only_the_worker_writes(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    columns = all_columns(admin_conn, "notification_outbox")
    assert columns == {
        "id",
        "tenant_id",
        "user_id",
        "channel",
        "kind",
        "dedupe_key",
        "alert_event_ids",
        "payload",
        "status",
        "not_before",
        "attempts",
        "last_error_class",
        "created_at",
        "sent_at",
    }
    assert not [
        c for c in columns if any(p in c for p in ("email", "address", "recipient", "to_", "phone", "mail"))
    ]
    a = world.a
    event_id = add_event(admin_conn, a)
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        add_outbox(conn, a, event_ids=[event_id])
        add_outbox(conn, a, key="12" * 32, kind="test")  # test iletisi olay gerektirmez
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        assert conn.execute(
            "SELECT count(*), min(attempts), bool_and(sent_at IS NULL) FROM notification_outbox"
        ).fetchone() == (2, 0, True)
    # Pazarlama türü yok; olaysız anlık/özet ileti yok; 500'den fazla olay yok; kanal ve durum sınırlı.
    cases: list[dict[str, Any]] = [
        {"kind": "marketing", "event_ids": [event_id]},
        {"kind": "instant", "event_ids": []},
        {"kind": "digest", "event_ids": []},
        {"kind": "instant", "event_ids": [uuid4() for _ in range(501)], "key": "ef" * 32},
        {"channel": "sms", "event_ids": [event_id], "key": "34" * 32},
        {"status": "sent", "event_ids": [event_id], "key": "56" * 32},
        {"status": "failed", "event_ids": [event_id], "key": "78" * 32},
        {"key": "xyz", "event_ids": [event_id]},
    ]
    for case in cases:
        with (
            role_tx(database.worker_dsn(), a.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            add_outbox(conn, a, **{"key": "9a" * 32, **case})
    # Aynı kiracıda aynı dedupe_key ikinci kez eklenmez (ON CONFLICT DO NOTHING çalışır); başka kiracıda eklenir.
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            add_outbox(conn, a, event_ids=[event_id])
    with role_tx(database.worker_dsn(), a.tenant_id, commit=False) as conn:
        assert (
            conn.execute(
                "INSERT INTO notification_outbox (tenant_id, user_id, channel, kind, dedupe_key, alert_event_ids) "
                "VALUES (%s, %s, 'email', 'instant', %s, %s) ON CONFLICT DO NOTHING",
                (a.tenant_id, a.user_id, DIGEST, [event_id]),
            ).rowcount
            == 0
        )
    with role_tx(database.worker_dsn(), world.b.tenant_id) as conn:
        add_outbox(conn, world.b, event_ids=[uuid4()])
    # Tenant yalıtımı: worker başka kiracının satırını yazamaz.
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        add_outbox(conn, world.b, event_ids=[event_id], key="bc" * 32)


def test_outbox_payload_is_allow_listed(database: DatabaseInfo, world: World) -> None:
    a = world.a
    bad: list[Any] = [
        {"email": "x@y.z"},
        {"eposta": "x"},
        {"to": 1, "Address": "x"},
        {"adres": "x"},
        {"telefon": "5"},
        {"recipient": "x@y.z"},
        {"rule_counts": {"ZARARINA_SATIS": 2, "musteri_adi": 1}},
        {"rule_counts": {"buyer": {"fullName": "x"}}},
        {"certainty": "ali@example.com"},
        {"certainty": "x" * 201},
        {"x": "y" * 5000},
        {"event_count": [1]},
    ]
    for payload in bad:
        with (
            role_tx(database.worker_dsn(), a.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            add_outbox(conn, a, kind="test", payload=payload)
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        add_outbox(
            conn,
            a,
            kind="test",
            payload={"event_count": 1, "total_amount": "412.30", "rule_counts": {"ZARARINA_SATIS": 2}},
        )


def test_outbox_state_machine(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    worker = database.worker_dsn()

    def new(key: str, status: str = "pending") -> UUID:
        with role_tx(worker, a.tenant_id, commit=True) as conn:
            return add_outbox(conn, a, kind="test", key=key, status=status)

    def update(row_id: UUID, set_sql: str) -> None:
        with role_tx(worker, a.tenant_id, commit=True) as conn:
            conn.execute(f"UPDATE notification_outbox SET {set_sql} WHERE id = %s", (row_id,))  # type: ignore[call-overload]

    def state(row_id: UUID) -> tuple[Any, ...]:
        row = admin_conn.execute(
            "SELECT status, attempts, sent_at IS NOT NULL FROM notification_outbox WHERE id = %s", (row_id,)
        ).fetchone()
        assert row is not None
        return row  # type: ignore[no-any-return]

    # pending -> sent: sent_at sunucuda atanır, kapanmış satır değişmez.
    sent = new("a1" * 32)
    update(sent, "status = 'sent'")
    assert state(sent) == ("sent", 0, True)
    for sql in (
        "status = 'pending'",
        "status = 'failed'",
        "attempts = 3",
        "not_before = now()",
        "last_error_class = 'x'",
    ):
        with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(f"UPDATE notification_outbox SET {sql} WHERE id = %s", (sent,))  # type: ignore[call-overload]
    # suppressed ve skipped kapanıştır; held <-> pending serbest, held -> sent serbest.
    for target in ("suppressed", "skipped"):
        row_id = new(("e1" if target == "suppressed" else "e2") * 32, "held")
        update(row_id, f"status = '{target}'")
        with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE notification_outbox SET status = 'pending' WHERE id = %s", (row_id,))
    held = new("c1" * 32, "held")
    update(held, "status = 'pending'")
    update(held, "status = 'held', not_before = now() + interval '1 hour'")
    update(held, "status = 'sent'")
    assert state(held)[0] == "sent"
    # failed -> pending yalnız attempts < 6; failed -> sent/held yok.
    failed = new("d1" * 32)
    update(failed, "status = 'failed', attempts = 1, last_error_class = 'timeout'")
    for to in ("sent", "held", "suppressed", "skipped"):
        with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(f"UPDATE notification_outbox SET status = '{to}' WHERE id = %s", (failed,))  # type: ignore[call-overload]
    update(failed, "status = 'pending'")
    assert state(failed) == ("pending", 1, False)
    with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE notification_outbox SET attempts = 0 WHERE id = %s", (failed,))  # geri alınamaz
    # Deneme hakkı 6'ya ulaşınca ya da kalıcı hatada `failed_permanent` zorunludur (failed + attempts 6 geçersiz).
    with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE notification_outbox SET status = 'failed', attempts = 6 WHERE id = %s", (failed,)
        )
    update(failed, "status = 'failed_permanent', attempts = 6, last_error_class = 'bad_address'")
    assert state(failed) == ("failed_permanent", 6, False)
    for to in ("pending", "held", "failed", "sent"):  # kapanmış
        with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(f"UPDATE notification_outbox SET status = '{to}' WHERE id = %s", (failed,))  # type: ignore[call-overload]
    for bad_class in ("Timeout", "bad class", "x" * 41, "a1", ""):
        fresh = new(bad_class.encode().hex().ljust(64, "0")[:64] or "f0" * 32)
        with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE notification_outbox SET last_error_class = %s WHERE id = %s", (bad_class, fresh)
            )
    direct = new("f1" * 32)
    update(
        direct, "status = 'failed_permanent', last_error_class = 'invalid_address'"
    )  # pending -> kalıcı hata
    assert state(direct)[0] == "failed_permanent"
    with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE notification_outbox SET attempts = 7 WHERE id = %s", (fresh,))
    # Kimlik ve içerik sütunları: worker'ın yetkisi yok; superuser için de tetikleyici reddeder.
    with role_tx(worker, a.tenant_id) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE notification_outbox SET user_id = %s", (world.admin_id,))
    for column, value in (
        ("user_id", f"'{world.admin_id}'"),
        ("payload", "'{}'::jsonb"),
        ("dedupe_key", f"'{'0' * 64}'"),
        ("channel", "'push'"),
        ("kind", "'digest'"),
    ):
        with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(f"UPDATE notification_outbox SET {column} = {value} WHERE id = %s", (failed,))  # type: ignore[call-overload]


# ===================================================================================== değerlendirme günlüğü


def test_evaluation_log_closes_once_and_rejects_duplicates(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    insert = (
        "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, settings_revision, "
        "rules_version) VALUES (%s, %s, '2026-11-20', 4, 2, 1) RETURNING id"
    )
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        row = conn.execute(insert, (a.tenant_id, a.account_id)).fetchone()
        assert row is not None
        eval_id = row[0]
        # Aynı anahtar ikinci kez çalışmaz (idempotent iş: ON CONFLICT DO NOTHING).
        assert (
            conn.execute(
                insert.replace("RETURNING id", "ON CONFLICT DO NOTHING"), (a.tenant_id, a.account_id)
            ).rowcount
            == 0
        )
    assert admin_conn.execute("SELECT status, finished_at FROM alert_evaluations").fetchone() == (
        "running",
        None,
    )
    for sql in (
        "UPDATE alert_evaluations SET status = 'running'",
        "UPDATE alert_evaluations SET status = 'baska'",
    ):
        with (
            role_tx(database.worker_dsn(), a.tenant_id) as conn,
            pytest.raises((psycopg.errors.CheckViolation,)),
        ):
            conn.execute(sql)
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        conn.execute(
            "UPDATE alert_evaluations SET status = 'succeeded', counts = %s WHERE id = %s",
            (Jsonb({"opened": 2}), eval_id),
        )
    status, finished = admin_conn.execute("SELECT status, finished_at FROM alert_evaluations").fetchone() or (
        None,
        None,
    )
    assert status == "succeeded" and finished is not None
    for sql in (
        "UPDATE alert_evaluations SET status = 'failed'",
        "UPDATE alert_evaluations SET counts = '{}'",
    ):
        with (
            role_tx(database.worker_dsn(), a.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            conn.execute(sql)
    for column, value in (("data_revision", "9"), ("as_of_date", "'2026-01-01'"), ("started_at", "now()")):
        with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(f"UPDATE alert_evaluations SET {column} = {value}")  # type: ignore[call-overload]
    # Worker dışı yazamaz; uygulama okur ("son değerlendirme").
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn:
        assert conn.execute("SELECT status FROM alert_evaluations").fetchall() == [("succeeded",)]
    with (
        role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(insert, (a.tenant_id, a.account_id))
    # Hesap/kiracı çifti tutarlı olmalı (bileşik FK).
    with (
        role_tx(database.worker_dsn(), world.b.tenant_id) as conn,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        conn.execute(insert.replace("4, 2, 1", "99, 2, 1"), (world.b.tenant_id, a.account_id))


# ===================================================================================== gate işlevleri


def _function_row(conn: psycopg.Connection[Any], schema: str, name: str) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT p.prosecdef, r.rolname, p.proconfig, has_function_privilege('netkar_worker', p.oid, 'EXECUTE'), "
        "has_function_privilege('netkar_app', p.oid, 'EXECUTE'), has_function_privilege('public', p.oid, 'EXECUTE'), "
        "has_function_privilege('netkar_auth', p.oid, 'EXECUTE'), has_schema_privilege('netkar_worker', n.oid, 'USAGE'), "
        "has_schema_privilege('netkar_app', n.oid, 'USAGE'), has_schema_privilege('public', n.oid, 'USAGE') "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE n.nspname = %s AND p.proname = %s",
        (schema, name),
    ).fetchone()
    assert row is not None
    return row  # type: ignore[no-any-return]


def test_gate_functions_are_locked_down_security_definers_executable_only_by_the_worker(
    admin_conn: psycopg.Connection[Any],
) -> None:
    cases = (
        ("notify_gate", "email_for", "netkar_notify_gate"),
        ("alert_gate", "purge_push_subscriptions", "netkar_owner"),
        ("notify_gate", "due_outbox", "netkar_notify_gate"),
        ("alert_gate", "purge_resolved", "netkar_owner"),
        ("alert_gate", "purge_outbox", "netkar_owner"),
    )
    for schema, name, owner in cases:
        (
            secdef,
            actual_owner,
            config,
            worker_exec,
            app_exec,
            public_exec,
            auth_exec,
            w_usage,
            a_usage,
            p_usage,
        ) = _function_row(admin_conn, schema, name)
        assert secdef is True and actual_owner == owner, (schema, name)
        assert config == ["search_path=pg_catalog, public, pg_temp"], (schema, name)
        assert (worker_exec, app_exec, public_exec, auth_exec) == (True, False, False, False), (schema, name)
        assert (w_usage, a_usage, p_usage) == (True, False, False), schema
    schema_owners = dict(
        admin_conn.execute(
            "SELECT n.nspname, r.rolname FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
            "WHERE n.nspname IN ('notify_gate', 'alert_gate')"
        ).fetchall()
    )
    assert schema_owners == {"notify_gate": "netkar_notify_gate", "alert_gate": "netkar_owner"}


def test_notify_gate_email_for_resolves_only_a_due_pending_email_row_of_a_verified_member(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    unverified = _add_user(admin_conn, a.tenant_id, "admin", verified=False)
    event_id = add_event(admin_conn, a)
    now = datetime.now(UTC)
    rows: dict[str, UUID] = {}
    for name, user, kwargs in (
        ("owner", a.user_id, {}),
        ("admin", world.admin_id, {}),
        ("unverified", unverified, {}),
        ("stranger", world.stranger_id, {}),
        ("push", a.user_id, {"channel": "push"}),
        ("held", a.user_id, {"status": "held"}),
        ("future", a.user_id, {"not_before": now + timedelta(hours=1)}),
        ("failed", a.user_id, {}),
        ("sent", a.user_id, {}),
    ):
        rows[name] = add_outbox(
            admin_conn, a, event_ids=[event_id], key=uuid4().hex + uuid4().hex, user_id=user, **kwargs
        )
    admin_conn.execute("UPDATE notification_outbox SET status = 'failed' WHERE id = %s", (rows["failed"],))
    admin_conn.execute("UPDATE notification_outbox SET status = 'sent' WHERE id = %s", (rows["sent"],))
    sql = "SELECT notify_gate.email_for(%s)"

    def email_of(user_id: UUID) -> str:
        row = admin_conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()
        assert row is not None
        return str(row[0])

    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        assert conn.execute(sql, (rows["owner"],)).fetchone() == (email_of(a.user_id),)
        assert conn.execute(sql, (rows["admin"],)).fetchone() == (email_of(world.admin_id),)
        assert conn.execute(sql, (rows["unverified"],)).fetchone() == (None,)  # doğrulanmamış
        assert conn.execute(sql, (rows["stranger"],)).fetchone() == (None,)  # üye değil
        # push kanalı, held, henüz erken, failed ve kapanmış satırla adres ÇÖZÜLEMEZ.
        for name in ("push", "held", "future", "failed", "sent"):
            assert conn.execute(sql, (rows[name],)).fetchone() == (None,), name
        assert conn.execute(sql, (uuid4(),)).fetchone() == (None,)
    # Üyelikten çıkarılmış kullanıcı: NULL (satır `skipped` olur).
    admin_conn.execute("ALTER TABLE memberships DISABLE TRIGGER USER")
    try:
        admin_conn.execute("DELETE FROM memberships WHERE user_id = %s", (a.user_id,))
        with role_tx(database.worker_dsn(), a.tenant_id) as conn:
            assert conn.execute(sql, (rows["owner"],)).fetchone() == (None,)
    finally:
        admin_conn.execute(
            "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'owner')",
            (a.user_id, a.tenant_id),
        )
        admin_conn.execute("ALTER TABLE memberships ENABLE ALWAYS TRIGGER memberships_immutable_guard")


def test_notify_gate_rejects_other_tenant_rows_missing_context_and_other_roles(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    event_id = add_event(admin_conn, b)
    row_b = add_outbox(admin_conn, b, event_ids=[event_id])
    sql = "SELECT notify_gate.email_for(%s)"
    # Başka kiracının satırı ya da bağlamsız çağrı: 42501 (hata ve yanlış kullanıma karşı savunma).
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(sql, (row_b,))
    with role_tx(database.worker_dsn()) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(sql, (row_b,))
    with role_tx(database.worker_dsn(), b.tenant_id) as conn:
        assert conn.execute(sql, (row_b,)).fetchone() is not None
    # Uygulama rolü şemaya ve işlevlere erişemez (ADR testi 11).
    for stmt in (
        f"SELECT notify_gate.email_for('{row_b}')",
        "SELECT * FROM notify_gate.due_outbox()",
        "SELECT alert_gate.purge_resolved(now() - interval '2 years')",
        "SELECT alert_gate.purge_push_subscriptions(now() - interval '2 years')",
    ):
        with (
            role_tx(database.app_dsn(), b.tenant_id, b.user_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(stmt)  # type: ignore[call-overload]
    # users.email'i uygulama yalnız kendi satırında görür.
    with role_tx(database.app_dsn(), b.tenant_id, b.user_id) as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM users").fetchall()] == [b.user_id]
    with (
        role_tx(database.app_dsn(), b.tenant_id, b.user_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT password_hash FROM users")


def test_notify_gate_due_outbox_lists_cross_tenant_pending_rows_without_addresses(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    now = datetime.now(UTC)
    due_a = add_outbox(admin_conn, a, kind="test", key="01" * 32, not_before=now - timedelta(minutes=5))
    due_b = add_outbox(admin_conn, b, kind="test", key="02" * 32, not_before=now - timedelta(minutes=1))
    add_outbox(admin_conn, a, kind="test", key="03" * 32, not_before=now + timedelta(hours=1))  # henüz erken
    add_outbox(admin_conn, a, kind="test", key="04" * 32, status="held", not_before=now - timedelta(hours=1))
    sent = add_outbox(admin_conn, a, kind="test", key="05" * 32)
    admin_conn.execute("UPDATE notification_outbox SET status = 'sent' WHERE id = %s", (sent,))
    with role_tx(database.worker_dsn()) as conn:  # kiracı bağlamı gerekmez
        rows = conn.execute("SELECT id, tenant_id FROM notify_gate.due_outbox(100)").fetchall()
        assert rows == [(due_a, a.tenant_id), (due_b, b.tenant_id)]  # not_before sırası
        assert len(conn.execute("SELECT * FROM notify_gate.due_outbox(1)").fetchall()) == 1
        assert len(conn.execute("SELECT * FROM notify_gate.due_outbox(0)").fetchall()) == 1  # alt sınır 1
        assert len(conn.execute("SELECT * FROM notify_gate.due_outbox()").fetchall()) == 2
        assert [
            d.name for d in conn.execute("SELECT * FROM notify_gate.due_outbox(5)").description or []
        ] == ["id", "tenant_id"]
        # Worker tabloyu bağlamsız doğrudan listeleyemez (RLS); yalnız kapı işlevi kiracılar arası görür.
        assert conn.execute("SELECT count(*) FROM notification_outbox").fetchone() == (0,)


def _resolved_event(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], seller: Seller, subject: str, age_days: int
) -> UUID:
    event_id = add_event(admin_conn, seller, subject=subject)
    with role_tx(database.worker_dsn(), seller.tenant_id, commit=True) as conn:
        transition(conn, seller, event_id, "resolved")
    with immutable_guard_disabled(admin_conn):
        admin_conn.execute(
            "UPDATE alert_events SET resolved_at = now() - make_interval(days => %s) WHERE id = %s",
            (age_days, event_id),
        )
    return event_id


def test_alert_gate_purge_resolved_deletes_only_old_resolved_events_with_their_ledger(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    old = _resolved_event(database, admin_conn, a, "urun:OLD", 500)
    recent = _resolved_event(database, admin_conn, a, "urun:RECENT", 100)
    open_event = add_event(admin_conn, a, subject="urun:OPEN")
    cutoff_ok = "now() - interval '13 months'"
    # Saklama tabanı: 13 aydan yeni kesim reddedilir (ele geçirilmiş worker toplu silemez).
    for cutoff in ("now()", "now() - interval '12 months'", "NULL"):
        with (
            role_tx(database.worker_dsn(), a.tenant_id) as conn,
            pytest.raises(psycopg.errors.InvalidParameterValue),
        ):
            conn.execute(f"SELECT alert_gate.purge_resolved(({cutoff})::timestamptz)")  # type: ignore[call-overload]
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        assert conn.execute(f"SELECT alert_gate.purge_resolved({cutoff_ok})").fetchone() == (1,)  # type: ignore[call-overload]
    remaining = {r[0] for r in admin_conn.execute("SELECT id FROM alert_events").fetchall()}
    assert remaining == {recent, open_event} and old not in remaining
    assert admin_conn.execute(
        "SELECT count(*) FROM alert_event_transitions WHERE alert_event_id = %s", (old,)
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM alert_event_transitions WHERE alert_event_id = %s", (recent,)
    ).fetchone() == (1,)
    # Çok eski ama açık olay silinmez.
    with immutable_guard_disabled(admin_conn):
        admin_conn.execute(
            "UPDATE alert_events SET last_seen_at = now() - interval '5 years' WHERE id = %s", (open_event,)
        )
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        assert conn.execute("SELECT alert_gate.purge_resolved(now() - interval '4 years')").fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM alert_events WHERE id = %s", (open_event,)
    ).fetchone() == (1,)


def test_alert_gate_purge_outbox_keeps_live_and_recent_rows(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    ids: dict[str, UUID] = {}
    for i, status in enumerate(("pending", "held", "sent", "failed", "suppressed", "skipped")):
        ids[status] = add_outbox(admin_conn, a, kind="test", key=f"{i:02d}" * 32, status="pending")
        if status != "pending":
            admin_conn.execute(
                "UPDATE notification_outbox SET status = %s WHERE id = %s", (status, ids[status])
            )
    retry = add_outbox(admin_conn, a, kind="test", key="aa" * 32)
    admin_conn.execute(
        "UPDATE notification_outbox SET status = 'failed_permanent', attempts = 6 WHERE id = %s", (retry,)
    )
    admin_conn.execute("ALTER TABLE notification_outbox DISABLE TRIGGER notification_outbox_guard")
    try:
        admin_conn.execute("UPDATE notification_outbox SET created_at = now() - interval '60 days'")
    finally:
        admin_conn.execute("ALTER TABLE notification_outbox ENABLE ALWAYS TRIGGER notification_outbox_guard")
    new_sent = add_outbox(admin_conn, a, kind="test", key="bb" * 32)
    admin_conn.execute("UPDATE notification_outbox SET status = 'sent' WHERE id = %s", (new_sent,))
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InvalidParameterValue),
    ):
        conn.execute("SELECT alert_gate.purge_outbox(now() - interval '10 days')")
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        # sent, suppressed, skipped ve failed_permanent silinir; pending, held, yeniden denenebilir failed ve yeni kalır.
        assert conn.execute("SELECT alert_gate.purge_outbox(now() - interval '30 days')").fetchone() == (4,)
    left = {r[0] for r in admin_conn.execute("SELECT id FROM notification_outbox").fetchall()}
    assert left == {ids["pending"], ids["held"], ids["failed"], new_sent}
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM notification_outbox")


# ===================================================================================== veri sürümü ve worker okuması


def test_alert_tables_do_not_touch_the_report_data_revision_counter(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    # Sürüm tetikleyicisinin kapsadığı tablo kümesi 0012'deki sekiz tabloyla aynı kalır (yeni tablo yok).
    versioned = {
        r[0]
        for r in admin_conn.execute(
            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p ON p.oid = t.tgfoid "
            "WHERE p.proname = 'bump_report_data_revision' AND NOT t.tgisinternal"
        )
    }
    assert versioned == {
        "orders",
        "order_lines",
        "returns",
        "financial_transactions",
        "cargo_invoice_items",
        "products",
        "product_costs",
        "sync_cursors",
    }
    assert not versioned & set(NEW_TABLES)
    # Davranış: değerlendirmenin bütün yazımları (olay, geçiş, eşik, outbox, değerlendirme, tercih) sayaç satırı yaratmaz.
    event_id = add_event(admin_conn, a)
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        conn.execute("UPDATE alert_events SET occurrence_count = 2")
        transition(conn, a, event_id, "resolved")
        add_outbox(conn, a, event_ids=[event_id])
        conn.execute(
            "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, settings_revision, "
            "rules_version) VALUES (%s, %s, '2026-11-20', 0, 0, 1)",
            (a.tenant_id, a.account_id),
        )
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        conn.execute(
            "INSERT INTO alert_rule_settings (tenant_id, marketplace_account_id) VALUES (%s, %s)",
            (a.tenant_id, a.account_id),
        )
        conn.execute(
            "INSERT INTO notification_settings (tenant_id, user_id) VALUES (%s, %s)", (a.tenant_id, a.user_id)
        )
    assert admin_conn.execute("SELECT count(*) FROM report_data_revisions").fetchone() == (0,)


def test_worker_reads_the_data_revision_of_its_own_tenant_only(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a, b = world.a, world.b
    admin_conn.execute(
        "INSERT INTO report_data_revisions (marketplace_account_id, tenant_id, revision) VALUES (%s, %s, 5), (%s, %s, 7)",
        (a.account_id, a.tenant_id, b.account_id, b.tenant_id),
    )
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        assert conn.execute("SELECT revision FROM report_data_revisions").fetchall() == [(5,)]
    with role_tx(database.worker_dsn()) as conn:
        assert conn.execute("SELECT count(*) FROM report_data_revisions").fetchone() == (0,)
    for sql in (
        "UPDATE report_data_revisions SET revision = 0",
        "INSERT INTO report_data_revisions VALUES (gen_random_uuid(), gen_random_uuid(), 1)",
        "DELETE FROM report_data_revisions",
    ):
        with (
            role_tx(database.worker_dsn(), a.tenant_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(sql)  # type: ignore[call-overload]
    with role_tx(database.app_dsn(), a.tenant_id) as conn:  # uygulamanın okuması değişmedi
        assert conn.execute("SELECT revision FROM report_data_revisions").fetchall() == [(5,)]


# ===================================================================================== migrasyon döngüsü ve downgrade koruması


def _snapshot(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Şemanın yetki, politika, tetikleyici ve işlev dökümü (0025 dışı nesneler dahil, karşılaştırma için)."""
    tables = conn.execute(
        "SELECT c.relname, c.relacl::text, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 1"
    ).fetchall()
    attrs = conn.execute(
        "SELECT c.relname, a.attname, a.attacl::text FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r' "
        "AND a.attacl IS NOT NULL ORDER BY 1, 2"
    ).fetchall()
    policies = conn.execute(
        "SELECT tablename, policyname, roles::text, cmd, qual, with_check FROM pg_policies WHERE schemaname = 'public' ORDER BY 1, 2"
    ).fetchall()
    triggers = conn.execute(
        "SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal ORDER BY 1, 2"
    ).fetchall()
    functions = conn.execute(
        "SELECT n.nspname, p.proname, pg_get_functiondef(p.oid), p.proacl::text FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname IN ('public', 'notify_gate', 'alert_gate') ORDER BY 1, 2"
    ).fetchall()
    return {
        "tables": tables,
        "attrs": attrs,
        "policies": policies,
        "triggers": triggers,
        "functions": functions,
    }


def _alert_objects(conn: psycopg.Connection[Any]) -> dict[str, set[str]]:
    return {
        "tables": {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        & set(NEW_TABLES),
        "schemas": {
            r[0]
            for r in conn.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname IN ('notify_gate', 'alert_gate')"
            )
        },
        "functions": {
            r[0]
            for r in conn.execute(
                "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' "
                "AND (p.proname LIKE 'alert\\_%' OR p.proname LIKE 'push\\_subscriptions\\_%' OR p.proname LIKE 'notification\\_outbox\\_%')"
            )
        },
    }


def test_migration_0025_upgrade_downgrade_upgrade_cycle(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any]
) -> None:
    before = _snapshot(admin_conn)
    full = _alert_objects(admin_conn)
    assert (
        full["tables"] == set(NEW_TABLES)
        and full["schemas"] == {"notify_gate", "alert_gate"}
        and full["functions"]
    )
    assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() is not None
    try:
        command.downgrade(alembic_cfg, "0024")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0024",)
        assert _alert_objects(admin_conn) == {"tables": set(), "schemas": set(), "functions": set()}
        # 0025'in eklediği yetki ve politikalar geri alındı; 0012-0024 durumu bozulmadı.
        assert admin_conn.execute(
            "SELECT has_table_privilege('netkar_worker', 'report_data_revisions', 'SELECT')"
        ).fetchone() == (False,)
        assert admin_conn.execute(
            "SELECT has_table_privilege('netkar_app', 'report_data_revisions', 'SELECT')"
        ).fetchone() == (True,)
        assert not admin_conn.execute(
            "SELECT 1 FROM pg_policies WHERE policyname IN ('notify_gate_path', 'tenant_isolation_worker')"
        ).fetchall()
        assert admin_conn.execute(
            "SELECT has_column_privilege('netkar_notify_gate', 'users', 'email', 'SELECT')"
        ).fetchone() == (False,)
        # Rol silinmez (provision sahibi).
        assert (
            admin_conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'netkar_notify_gate'").fetchone()
            is not None
        )
    finally:
        command.upgrade(alembic_cfg, "head")
    assert _alert_objects(admin_conn) == full
    assert _snapshot(admin_conn) == before  # tam eşit: yetkiler, politikalar, tetikleyiciler, işlev gövdeleri
    # Çift tur.
    try:
        command.downgrade(alembic_cfg, "0024")
    finally:
        command.upgrade(alembic_cfg, "head")
    assert _snapshot(admin_conn) == before


def test_migration_0025_downgrade_guard_requires_exact_total_and_prod_always_refuses(
    alembic_cfg: Config,
    admin_conn: psycopg.Connection[Any],
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    monkeypatch.delenv("NETKAR_ALLOW_ALERT_DATA_LOSS", raising=False)
    try:
        # Kayıt yokken prod HER durumda reddeder.
        monkeypatch.setenv("ENVIRONMENT", "prod")
        with pytest.raises(RuntimeError, match="ENVIRONMENT=prod"):
            command.downgrade(alembic_cfg, "0024")
        monkeypatch.setenv("ENVIRONMENT", "test")
        # Yalnız bir tercih satırı bile (olay ya da outbox olmadan) korumayı devreye sokar: toplam 1.
        admin_conn.execute(
            "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, 'email', 'off')",
            (a.tenant_id, a.user_id, RULES[0]),
        )
        event_id = add_event(admin_conn, a)
        add_outbox(admin_conn, a, event_ids=[event_id])
        admin_conn.execute("UPDATE users SET email_verified_at = now() WHERE id = %s", (a.user_id,))
        total = 3  # tercih + olay + outbox
        for wrong in ("1", "", "total=3", "03", str(total + 1)):
            monkeypatch.setenv("NETKAR_ALLOW_ALERT_DATA_LOSS", wrong)
            with pytest.raises(RuntimeError, match=f"NETKAR_ALLOW_ALERT_DATA_LOSS={total}"):
                command.downgrade(alembic_cfg, "0024")
            assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0025",)
            assert admin_conn.execute("SELECT count(*) FROM alert_events").fetchone() == (
                1,
            )  # veri silinmedi
        monkeypatch.delenv("NETKAR_ALLOW_ALERT_DATA_LOSS")
        with pytest.raises(RuntimeError, match="DURDURULDU"):
            command.downgrade(alembic_cfg, "0024")
        # Reddedilen denemeler FORCE RLS'yi yerinde bırakır (işlem geri alındı).
        forced = admin_conn.execute(
            "SELECT bool_and(relforcerowsecurity) FROM pg_class WHERE relname = ANY(%s)", (list(NEW_TABLES),)
        ).fetchone()
        assert forced == (True,)
        # Doğru bayrak bile prod'da yetmez.
        monkeypatch.setenv("NETKAR_ALLOW_ALERT_DATA_LOSS", str(total))
        monkeypatch.setenv("ENVIRONMENT", "prod")
        with pytest.raises(RuntimeError, match="ENVIRONMENT=prod"):
            command.downgrade(alembic_cfg, "0024")
        assert admin_conn.execute("SELECT count(*) FROM alert_events").fetchone() == (1,)
        monkeypatch.setenv("ENVIRONMENT", "test")
        command.downgrade(alembic_cfg, "0024")  # tam sayı: geri alınır (kayıt kaybı bilerek kabul edildi)
        assert _alert_objects(admin_conn)["tables"] == set()
    finally:
        monkeypatch.delenv("NETKAR_ALLOW_ALERT_DATA_LOSS", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "test")
        command.upgrade(alembic_cfg, "head")
    assert _alert_objects(admin_conn)["tables"] == set(NEW_TABLES)
    assert admin_conn.execute("SELECT count(*) FROM alert_events").fetchone() == (
        0,
    )  # yeniden kurulum boş başlar


# ===================================================================================== ek sertleştirme testleri


def test_push_resubscribe_after_revocation_and_purge_of_old_revoked_rows(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        conn.execute(PUSH_INSERT, (a.tenant_id, a.user_id, "fcm.googleapis.com", DIGEST))
    # Etkin abonelik varken aynı uç nokta eklenemez; iptal sonrası YENİDEN abonelik mümkündür (kısmi benzersizlik).
    with (
        role_tx(database.app_dsn(), a.tenant_id, world.admin_id) as conn,
        pytest.raises(psycopg.errors.UniqueViolation),
    ):
        conn.execute(PUSH_INSERT, (a.tenant_id, world.admin_id, "fcm.googleapis.com", DIGEST))
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        conn.execute("UPDATE push_subscriptions SET revoked_at = now()")
    with role_tx(database.app_dsn(), a.tenant_id, world.admin_id, commit=True) as conn:
        conn.execute(PUSH_INSERT, (a.tenant_id, world.admin_id, "fcm.googleapis.com", DIGEST))
    assert admin_conn.execute(
        "SELECT count(*) FILTER (WHERE revoked_at IS NULL), count(*) FROM push_subscriptions"
    ).fetchone() == (1, 2)
    # Saklama: 30 günden yeni kesim reddedilir; yalnız eski İPTAL edilmiş satır silinir, etkin olan kalır.
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InvalidParameterValue),
    ):
        conn.execute("SELECT alert_gate.purge_push_subscriptions(now() - interval '10 days')")
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        assert conn.execute(
            "SELECT alert_gate.purge_push_subscriptions(now() - interval '30 days')"
        ).fetchone() == (0,)  # iptal yeni
    admin_conn.execute("ALTER TABLE push_subscriptions DISABLE TRIGGER push_subscriptions_guard")
    try:
        admin_conn.execute(
            "UPDATE push_subscriptions SET revoked_at = now() - interval '45 days' WHERE revoked_at IS NOT NULL"
        )
    finally:
        admin_conn.execute("ALTER TABLE push_subscriptions ENABLE ALWAYS TRIGGER push_subscriptions_guard")
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        assert conn.execute(
            "SELECT alert_gate.purge_push_subscriptions(now() - interval '30 days')"
        ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE revoked_at IS NULL) FROM push_subscriptions"
    ).fetchone() == (1, 1)


def test_preference_and_settings_updated_at_is_set_by_the_server(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    a = world.a
    admin_conn.execute(
        "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode, updated_at) "
        "VALUES (%s, %s, %s, 'email', 'digest', now() - interval '9 days')",
        (a.tenant_id, a.user_id, RULES[0]),
    )
    admin_conn.execute(
        "INSERT INTO notification_settings (tenant_id, user_id, updated_at) VALUES (%s, %s, now() - interval '9 days')",
        (a.tenant_id, a.user_id),
    )
    for column_sql, table in (
        (
            "UPDATE notification_preferences SET updated_at = now() - interval '5 days'",
            "notification_preferences",
        ),
        ("UPDATE notification_settings SET updated_at = now() - interval '5 days'", "notification_settings"),
    ):  # istemci updated_at yazamaz (sütun yetkisi yok)
        with (
            role_tx(database.app_dsn(), a.tenant_id, a.user_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(column_sql)  # type: ignore[call-overload]
        assert table
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        conn.execute("UPDATE notification_preferences SET mode = 'off'")
        conn.execute("UPDATE notification_settings SET digest_hour = 9")
    for table in ("notification_preferences", "notification_settings"):
        row = admin_conn.execute("SELECT now() - updated_at < interval '1 minute' FROM " + table).fetchone()
        assert row == (True,), table


def test_orm_inserts_get_database_generated_ids(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], world: World
) -> None:
    """ORM `default=uuid.uuid4` yok: kimliği veritabanı üretir ve ORM RETURNING ile gerçek kimliği alır."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    a = world.a
    engine = create_engine(database.worker_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a.tenant_id)})
            event = AlertEvent(
                tenant_id=a.tenant_id,
                marketplace_account_id=a.account_id,
                rule="ZARARINA_SATIS",
                scope="product",
                subject="urun:ORM",
                dedupe_key=dedupe("ZARARINA_SATIS", a.account_id, "urun:ORM"),
                severity="high",
                payload={"loss_line_count": 1},
                payload_version=1,
                data_revision=1,
                settings_revision=1,
            )
            session.add(event)
            session.flush()
            assert isinstance(event.id, UUID)
            ledger = AlertEventTransition(
                tenant_id=a.tenant_id, alert_event_id=event.id, to_status="resolved"
            )
            session.add(ledger)
            session.flush()
            assert isinstance(ledger.id, UUID)
            outbox = NotificationOutbox(
                tenant_id=a.tenant_id,
                user_id=a.user_id,
                channel="email",
                kind="instant",
                dedupe_key=DIGEST,
                alert_event_ids=[event.id],
                payload={"event_count": 1},
            )
            evaluation = AlertEvaluation(
                tenant_id=a.tenant_id,
                marketplace_account_id=a.account_id,
                as_of_date=datetime(2026, 11, 20, tzinfo=UTC).date(),
                data_revision=1,
                settings_revision=1,
                rules_version=1,
            )
            session.add_all([outbox, evaluation])
            session.flush()
            session.commit()
            ids = (event.id, ledger.id, outbox.id, evaluation.id)
    finally:
        engine.dispose()
    # ORM'nin tuttuğu kimlikler satırların gerçek kimlikleridir.
    assert admin_conn.execute("SELECT id FROM alert_events").fetchone() == (ids[0],)
    assert admin_conn.execute("SELECT id, alert_event_id FROM alert_event_transitions").fetchone() == (
        ids[1],
        ids[0],
    )
    assert admin_conn.execute("SELECT id FROM notification_outbox").fetchone() == (ids[2],)
    assert admin_conn.execute("SELECT id FROM alert_evaluations").fetchone() == (ids[3],)
    assert event_state(admin_conn, ids[0])[0] == "resolved"
