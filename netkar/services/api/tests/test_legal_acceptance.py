"""Kullanım koşulları ve aydınlatma metni sürüm kaydı, kayıt onayı, yeniden kabul (0021; TBK m.20-21 ispat notu).

Kapsam: kayıtta zorunlu onay (422), kabul kaydının yalnız gerekli alanları, değişmezlik (tetikleyici + yetki),
RLS (FORCE, kullanıcı yalıtımı), /me bekleyen bilgisi, POST /v1/legal/accept, yeniden kabul kapısı (varsayılan
kapalı; açıkken yalnız tenant yazma uçları 403), yayın aracı ve 0021 geri alınabilirliği.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.tools import legal_documents as tool
from app.tools.common import ToolConfigError
from tests.conftest import GOOD_PASSWORD, Api, DatabaseInfo
from tests.test_email_verification import _BLOCKED_ENDPOINTS, _TOTP_PATHS, _is_problem

PLACEHOLDER = "taslak-2026-11"


def _publish(conn: psycopg.Connection[Any], doc_type: str, version: str) -> None:
    conn.execute(
        "INSERT INTO legal_documents (doc_type, version, content_sha256) VALUES (%s, %s, %s)",
        (doc_type, version, hashlib.sha256(f"{doc_type}:{version}".encode()).hexdigest()),
    )


def _acceptances(conn: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    return conn.execute(
        "SELECT d.doc_type, d.version FROM user_legal_acceptances a "
        "JOIN legal_documents d ON d.id = a.document_id ORDER BY d.doc_type, d.version"
    ).fetchall()


def _pending(api: Api) -> list[dict[str, Any]]:
    return list(api.get("/v1/me").json()["legal"]["pending"])


# --- şema: sürüm kaydı, yer tutucu, alanlar -----------------------------------------------------------
def test_placeholder_versions_are_seeded_with_sha256_digests(admin_conn: psycopg.Connection[Any]) -> None:
    rows = admin_conn.execute(
        "SELECT doc_type, version, content_sha256 FROM legal_documents ORDER BY doc_type"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [("privacy_notice", PLACEHOLDER), ("terms", PLACEHOLDER)]
    for doc_type, version, digest in rows:
        expected = hashlib.sha256(f"netkar-legal-placeholder:{doc_type}:{version}".encode()).hexdigest()
        assert digest == expected  # yer tutucunun özeti (belge metni değil)


def test_acceptance_table_holds_only_necessary_fields(admin_conn: psycopg.Connection[Any]) -> None:
    """Veri en aza indirme: IP, IP özeti ya da aracı bilgisi sütunu yok."""
    columns = {
        r[0]
        for r in admin_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'user_legal_acceptances'"
        )
    }
    assert columns == {"id", "user_id", "document_id", "accepted_at"}


# --- kayıt: zorunlu onay ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("terms", "notice"),
    [
        (None, True),
        (True, None),
        (None, None),
        (False, True),
        (True, False),
        (1, True),
        ("true", True),
        (True, "evet"),
    ],
)
def test_register_without_both_explicit_confirmations_is_422_and_creates_nothing(
    api: Api, admin_conn: psycopg.Connection[Any], terms: Any, notice: Any
) -> None:
    response = api.register("onaysiz@example.com", accept_terms=terms, acknowledge_privacy_notice=notice)
    assert response.status_code == 422
    assert admin_conn.execute("SELECT count(*) FROM users").fetchone() == (0,)
    assert _acceptances(admin_conn) == []


def test_register_records_current_versions_in_the_same_transaction(
    api: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    assert api.register("kabul@example.com").status_code == 202
    assert _acceptances(admin_conn) == [("privacy_notice", PLACEHOLDER), ("terms", PLACEHOLDER)]
    user_id = admin_conn.execute("SELECT id FROM users").fetchone()
    assert admin_conn.execute("SELECT DISTINCT user_id FROM user_legal_acceptances").fetchall() == [user_id]
    api.login("kabul@example.com")
    assert _pending(api) == []


def test_register_records_the_latest_published_version(api: Api, admin_conn: psycopg.Connection[Any]) -> None:
    _publish(admin_conn, "terms", "2026-12-a")
    assert api.register("yeni-surum@example.com").status_code == 202
    assert _acceptances(admin_conn) == [("privacy_notice", PLACEHOLDER), ("terms", "2026-12-a")]


def test_future_dated_version_is_not_current_yet(api: Api, admin_conn: psycopg.Connection[Any]) -> None:
    admin_conn.execute(
        "INSERT INTO legal_documents (doc_type, version, published_at, content_sha256) "
        "VALUES ('terms', 'ileri', now() + interval '1 day', %s)",
        ("a" * 64,),
    )
    assert api.register("ileri@example.com").status_code == 202
    assert ("terms", "ileri") not in _acceptances(admin_conn)


def test_register_for_existing_email_is_still_202_and_records_nothing_extra(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    """Numaralandırma koruması: aynı 202; var olan hesap için kabul kaydı eklenmez, onay yine zorunludur."""
    first = make_api()
    assert first.register("var@example.com").status_code == 202
    before = _acceptances(admin_conn)
    second = make_api()
    again = second.register("var@example.com", tenant="Başka")
    assert again.status_code == 202 and again.json() == {"status": "accepted"}
    assert _acceptances(admin_conn) == before
    # onay eksikse mevcut adres için de aynı 422 (yanıt farkından hesap varlığı anlaşılmaz)
    assert second.register("var@example.com", accept_terms=None).status_code == 422
    assert second.register("hic-yok@example.com", accept_terms=None).status_code == 422


# --- değişmezlik, yetki ve RLS ---------------------------------------------------------------------------
def test_records_are_immutable_for_every_role(
    api: Api, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    assert api.register("degismez@example.com").status_code == 202
    for sql in (
        "UPDATE user_legal_acceptances SET accepted_at = now() - interval '1 year'",
        "DELETE FROM user_legal_acceptances",
        "UPDATE legal_documents SET content_sha256 = repeat('b', 64)",
        "DELETE FROM legal_documents",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):  # superuser için bile tetikleyici
            admin_conn.execute(sql)  # type: ignore[arg-type]
    user_id = admin_conn.execute("SELECT id FROM users").fetchone()
    assert user_id is not None
    with psycopg.connect(database.app_dsn(), autocommit=True) as app:
        for sql in (
            "UPDATE user_legal_acceptances SET accepted_at = now()",
            "DELETE FROM user_legal_acceptances",
            "UPDATE legal_documents SET version = 'x'",
            "DELETE FROM legal_documents",
            "INSERT INTO legal_documents (doc_type, version, content_sha256) VALUES ('terms', 'x', repeat('a', 64))",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute(sql)  # type: ignore[arg-type]


def test_privileges_and_force_rls(admin_conn: psycopg.Connection[Any]) -> None:
    for table in ("legal_documents", "user_legal_acceptances"):
        assert admin_conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", (table,)
        ).fetchone() == (True, True)
        assert admin_conn.execute(
            "SELECT has_table_privilege('netkar_app', %s, 'UPDATE'), has_table_privilege('netkar_app', %s, 'DELETE'),"
            " has_table_privilege('netkar_worker', %s, 'SELECT'), has_table_privilege('netkar_app', %s, 'SELECT')",
            (table, table, table, table),
        ).fetchone() == (False, False, False, True)
    assert admin_conn.execute(
        "SELECT has_table_privilege('netkar_app', 'user_legal_acceptances', 'INSERT')"
    ).fetchone() == (True,)


def test_acceptances_are_isolated_per_user_and_cannot_be_written_for_others(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    for email in ("a@example.com", "b@example.com"):
        assert make_api().register(email).status_code == 202
    ids = {r[0]: r[1] for r in admin_conn.execute("SELECT email, id::text FROM users").fetchall()}
    doc = admin_conn.execute("SELECT id::text FROM legal_documents WHERE doc_type = 'terms'").fetchone()
    assert doc is not None
    _publish(admin_conn, "terms", "2026-12-b")
    new_doc = admin_conn.execute(
        "SELECT id::text FROM legal_documents WHERE version = '2026-12-b'"
    ).fetchone()
    assert new_doc is not None
    with psycopg.connect(database.app_dsn()) as app:
        app.execute("SELECT set_config('app.user_id', %s, true)", (ids["a@example.com"],))
        seen = app.execute("SELECT DISTINCT user_id::text FROM user_legal_acceptances").fetchall()
        assert seen == [(ids["a@example.com"],)]  # B'nin kaydı görünmez
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(
                "INSERT INTO user_legal_acceptances (user_id, document_id) VALUES (%s, %s)",
                (ids["b@example.com"], new_doc[0]),
            )
        app.rollback()
        app.execute("SELECT set_config('app.user_id', '', true)")
        assert app.execute("SELECT count(*) FROM user_legal_acceptances").fetchone() == (
            0,
        )  # bağlamsız satır yok


# --- /me ve POST /v1/legal/accept ------------------------------------------------------------------------
def test_me_reports_pending_documents_after_a_new_version(
    api: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    api.signup_and_login("bekleyen@example.com")
    me = api.get("/v1/me").json()
    assert me["legal"] == {"pending": [], "enforced": False}
    _publish(admin_conn, "terms", "2026-12-a")
    pending = _pending(api)
    assert [(p["doc_type"], p["version"]) for p in pending] == [("terms", "2026-12-a")]
    assert pending[0]["published_at"]


def test_accept_records_current_version_is_idempotent_and_audited(
    api: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    api.signup_and_login("kabul2@example.com")
    _publish(admin_conn, "terms", "2026-12-a")
    _publish(admin_conn, "privacy_notice", "2026-12-a")
    body = {
        "documents": [
            {"doc_type": "terms", "version": "2026-12-a"},
            {"doc_type": "privacy_notice", "version": "2026-12-a"},
        ]
    }
    response = api.post("/v1/legal/accept", body)
    assert response.status_code == 200 and response.json() == {"pending": [], "enforced": False}
    assert ("terms", "2026-12-a") in _acceptances(admin_conn)
    before = len(_acceptances(admin_conn))
    assert api.post("/v1/legal/accept", body).status_code == 200  # ikinci kez zararsız
    assert len(_acceptances(admin_conn)) == before
    audits = admin_conn.execute(
        "SELECT action, ip_hash, target FROM audit_log WHERE action = 'legal.accepted'"
    ).fetchall()
    assert len(audits) == 1 and audits[0][1] is None  # IP özeti de yazılmaz
    assert "terms:2026-12-a" in audits[0][2]


def test_accept_rejects_stale_or_unknown_versions_and_bad_input(
    api: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    api.signup_and_login("eski@example.com")
    _publish(admin_conn, "terms", "2026-12-a")
    stale = api.post("/v1/legal/accept", {"documents": [{"doc_type": "terms", "version": PLACEHOLDER}]})
    assert _is_problem(stale, 409, "legal-version-stale")
    unknown = api.post("/v1/legal/accept", {"documents": [{"doc_type": "terms", "version": "uydurma"}]})
    assert _is_problem(unknown, 409, "legal-version-stale")
    bad_bodies: list[dict[str, Any]] = [
        {"documents": []},
        {"documents": [{"doc_type": "marketing", "version": "x"}]},
        {"documents": [{"doc_type": "terms", "version": "x", "extra": 1}]},
        {},
    ]
    for bad in bad_bodies:
        assert api.post("/v1/legal/accept", bad).status_code == 422
    # reddedilen istek kısmen kayıt yazmaz (tek geçersiz kalem tüm isteği düşürür)
    mixed = {
        "documents": [
            {"doc_type": "terms", "version": "2026-12-a"},
            {"doc_type": "privacy_notice", "version": "eski-surum"},
        ]
    }
    assert api.post("/v1/legal/accept", mixed).status_code == 409
    assert ("terms", "2026-12-a") not in _acceptances(admin_conn)


def test_accept_requires_session_and_csrf(api: Api, make_api: Callable[..., Api]) -> None:
    body = {"documents": [{"doc_type": "terms", "version": PLACEHOLDER}]}
    assert api.post("/v1/legal/accept", body).status_code == 401
    api.signup_and_login("csrf@example.com")
    assert api.post("/v1/legal/accept", body, csrf=False).status_code == 403


def test_unverified_account_can_accept(api: Api, admin_conn: psycopg.Connection[Any]) -> None:
    api.signup_and_login("dogrulanmamis@example.com", verified=False)
    _publish(admin_conn, "terms", "2026-12-a")
    ok = api.post("/v1/legal/accept", {"documents": [{"doc_type": "terms", "version": "2026-12-a"}]})
    assert ok.status_code == 200


# --- yeniden kabul kapısı ----------------------------------------------------------------------------------
_TENANT_WRITES = [e for e in _BLOCKED_ENDPOINTS if e[1] not in _TOTP_PATHS]


def test_gate_is_off_by_default_even_with_pending_documents(
    api: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    api.signup_and_login("kapali@example.com")
    _publish(admin_conn, "terms", "2026-12-a")
    base = f"/v1/marketplace-accounts/{uuid.uuid4()}/products/ABC123/costs"
    body = {"valid_from": "2026-01-01", "unit_cost_excl_vat": "10.00", "vat_rate": "20"}
    assert api.put(base, body).status_code == 404  # kapı yok: hesap bulunamadı (404)


@pytest.mark.parametrize(("method", "path", "body"), _TENANT_WRITES, ids=lambda v: str(v)[:40])
def test_enforced_gate_blocks_every_tenant_write_endpoint_until_accepted(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], method: str, path: str, body: Any
) -> None:
    api = make_api(legal_reacceptance_enforced=True)
    api.signup_and_login("kapi@example.com")
    _publish(admin_conn, "terms", "2026-12-a")
    if body == "FILE":
        response = api.post(path, files={"file": ("m.csv", b"a;b\n1;2\n", "text/csv")})
    elif method == "post":
        response = api.post(path, body)
    elif method == "put":
        response = api.put(path, body)
    else:
        response = api.delete(path)
    assert _is_problem(response, 403, "terms-acceptance-required"), response.text
    assert response.json()["status"] == 403 and response.json()["title"]


def test_enforced_gate_keeps_reads_security_and_accept_open_then_lifts_on_accept(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    api = make_api(legal_reacceptance_enforced=True)
    api.signup_and_login("acik@example.com")
    base = f"/v1/marketplace-accounts/{uuid.uuid4()}/products/ABC123/costs"
    body = {"valid_from": "2026-01-01", "unit_cost_excl_vat": "10.00", "vat_rate": "20"}
    assert api.put(base, body).status_code == 404  # güncel sürüm kabul edilmiş: kapı geçilir
    _publish(admin_conn, "terms", "2026-12-a")
    assert _is_problem(api.put(base, body), 403, "terms-acceptance-required")
    me = api.get("/v1/me")
    assert me.status_code == 200 and me.json()["legal"]["enforced"] is True
    assert api.get("/v1/marketplace-accounts").status_code == 200  # okuma açık
    assert api.post("/v1/auth/totp/setup", {"password": GOOD_PASSWORD}).status_code == 200  # güvenlik açık
    accepted = api.post("/v1/legal/accept", {"documents": [{"doc_type": "terms", "version": "2026-12-a"}]})
    assert accepted.status_code == 200 and accepted.json()["pending"] == []
    assert api.put(base, body).status_code == 404  # kabulden sonra kapı açıldı
    assert api.post("/v1/auth/logout").status_code == 204


def test_enforced_gate_blocks_legacy_user_with_no_acceptance(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    """0021 öncesi kullanıcı (hiç kabul kaydı yok): kapı açılınca iki belge de bekler."""
    api = make_api(legal_reacceptance_enforced=True)
    api.signup_and_login("eski-kullanici@example.com")
    admin_conn.execute("TRUNCATE user_legal_acceptances")
    assert {p["doc_type"] for p in _pending(api)} == {"terms", "privacy_notice"}
    base = f"/v1/marketplace-accounts/{uuid.uuid4()}/products/ABC123/costs"
    body = {"valid_from": "2026-01-01", "unit_cost_excl_vat": "10.00", "vat_rate": "20"}
    assert _is_problem(api.put(base, body), 403, "terms-acceptance-required")


def test_unverified_error_takes_precedence_over_acceptance_gate(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    api = make_api(legal_reacceptance_enforced=True)
    api.signup_and_login("oncelik@example.com", verified=False)
    _publish(admin_conn, "terms", "2026-12-a")
    path = f"/v1/marketplace-accounts/{uuid.uuid4()}/revoke"
    assert _is_problem(api.post(path), 403, "email-not-verified")


# --- yayın aracı -------------------------------------------------------------------------------------------
def test_publish_tool_inserts_a_digest_only_row_and_refuses_duplicates(
    admin_conn: psycopg.Connection[Any],
    database: DatabaseInfo,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = tmp_path / "terms.md"
    doc.write_bytes("Örnek belge içeriği (test).\n".encode())
    env = {"DATABASE_ADMIN_URL": database.admin_dsn()}
    args = ["publish", "--type", "terms", "--version", "2026-12-t", "--file", str(doc)]
    assert tool.main(args, env) == 0
    expected = hashlib.sha256(doc.read_bytes()).hexdigest()
    assert expected in capsys.readouterr().out
    row = admin_conn.execute(
        "SELECT content_sha256 FROM legal_documents WHERE version = '2026-12-t'"
    ).fetchone()
    assert row == (expected,)
    assert tool.main(args, env) == 3  # aynı sürüm ikinci kez yayınlanamaz
    assert "zaten yayınlanmış" in capsys.readouterr().err
    assert tool.main(["publish", "--type", "terms", "--version", "BÜYÜK", "--file", str(doc)], env) == 3
    empty = tmp_path / "bos.md"
    empty.write_bytes(b"  \n")
    assert tool.main(["publish", "--type", "terms", "--version", "bos", "--file", str(empty)], env) == 3
    assert tool.main(args, {}) == 3  # DATABASE_ADMIN_URL yok
    with pytest.raises(ToolConfigError):
        tool.publish_document(admin_conn, "marketing", "v1", b"x")  # type: ignore[arg-type]


# --- migrasyon ---------------------------------------------------------------------------------------------
def test_migration_0021_downgrade_protects_evidence_and_is_reversible(
    api: Api,
    alembic_cfg: Config,
    admin_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tables() -> set[str]:
        return {
            r[0] for r in admin_conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }

    assert api.register("kanit@example.com").status_code == 202
    monkeypatch.delenv("NETKAR_ALLOW_LEGAL_DATA_LOSS", raising=False)
    try:
        with pytest.raises(RuntimeError, match="DURDURULDU"):
            command.downgrade(alembic_cfg, "0020")
        # koruma işlemi geri aldı: tablolar, kayıtlar ve FORCE RLS yerinde
        assert {"legal_documents", "user_legal_acceptances"} <= tables()
        assert len(_acceptances(admin_conn)) == 2
        assert admin_conn.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'user_legal_acceptances'"
        ).fetchone() == (True,)
        monkeypatch.setenv("NETKAR_ALLOW_LEGAL_DATA_LOSS", "1")
        command.downgrade(alembic_cfg, "0020")
        assert not ({"legal_documents", "user_legal_acceptances"} & tables())
        assert {"mfa_recovery_codes", "users"} <= tables()  # 0020 ve öncesi etkilenmedi
        command.upgrade(alembic_cfg, "head")
        assert admin_conn.execute("SELECT count(*) FROM legal_documents").fetchone() == (
            2,
        )  # yer tutucular geri
        assert admin_conn.execute("SELECT count(*) FROM user_legal_acceptances").fetchone() == (0,)
        assert admin_conn.execute(
            "SELECT has_table_privilege('netkar_app', 'legal_documents', 'SELECT'),"
            " has_table_privilege('netkar_app', 'legal_documents', 'UPDATE')"
        ).fetchone() == (True, False)
    finally:
        command.upgrade(alembic_cfg, "head")


def test_migration_0021_downgrade_without_evidence_needs_no_flag(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NETKAR_ALLOW_LEGAL_DATA_LOSS", raising=False)
    try:
        command.downgrade(alembic_cfg, "0020")  # yalnız yer tutucu sürümler var, kabul kaydı yok
        command.upgrade(alembic_cfg, "head")
        assert admin_conn.execute("SELECT count(*) FROM legal_documents").fetchone() == (2,)
    finally:
        command.upgrade(alembic_cfg, "head")
