"""Bildirim dağıtıcısı (ADR-0009 D5): bekleyen (held) ve yeniden denenecek (failed) outbox satırlarının keşfi.

`notify_gate.due_outbox` (0025) YALNIZ `pending` satırları listeler ve bilerek değiştirilmez. Ancak `held`
(sessiz saatte bekleyen) ve `failed` (geçici hata, üstel bekleme) satırları `pending`'e dönmedikçe hiç gönderilmez
ve outbox satırları kiracı RLS'i altında olduğundan worker bunları kiracılar arası listeleyemez. Bu migrasyon:

- `notify_gate.releasable_outbox(limit)`: kiracılar arası `(id, tenant_id)` listesi (`due_outbox` deseni: sahibi
  `netkar_notify_gate`, SECURITY DEFINER, sabit `search_path`, PUBLIC EXECUTE yok, yalnız `netkar_worker`). Yalnız
  `not_before` zamanı gelmiş `held` ve `failed` satırlar; sıklık sınırı nedeniyle bekleyen satırlar
  (`last_error_class = 'rate_limited'`) HARİÇTİR: onlar sonraki günlük özete katlanır, anlık gönderilmez.
  Dağıtıcı bu satırları kiracı bağlamında `pending`'e çevirir (durum makinesi bunu zaten izin verir), ardından
  `due_outbox` onları listeler.
- `notify_gate.tenant_recipients(tenant)`: günlük özet alıcıları (D5/O5). Kiracının e-postası DOĞRULANMIŞ üyeleri ve
  rolleri `(user_id, member_role)`; çağıran kiracı bağlamı (`app.tenant_id`) `p_tenant` ile eşleşmelidir (42501).
  Worker `memberships` tablosunu doğrudan OKUYAMAZ; yalnız bu dar işlev üzerinden. Adres döndürmez.
- `netkar_notify_gate`'e `notification_outbox.last_error_class` ve `memberships.role` SELECT yetkisi (yalnız bu sütunlar).
- `ix_notification_outbox_failed_due`: `failed` satırlar için kısmi indeks (0025 indeksi `pending`/`held` içindir).

Veri değişmez; hiçbir satır yazılmaz ya da silinmez. Geri alma: işlev, indeks ve sütun yetkisi kaldırılır (yalnız
bu migrasyonun eklediği nesneler). Downgrade koruması (0025/0026 deseni): ENVIRONMENT=prod iken `held` ya da
`failed` satır varsa REDDEDİLİR (işlev kalkınca bu satırlar sonsuza dek bekler); diğer ortamlarda veri kaybı
olmadığından bayrak istemez.

Revision ID: 0027
Revises: 0026
"""

import os

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

NOTIFY_GATE_ROLE = "netkar_notify_gate"

_RELEASABLE = """
CREATE FUNCTION notify_gate.releasable_outbox(p_limit integer DEFAULT 100)
RETURNS TABLE (id uuid, tenant_id uuid)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    RETURN QUERY
        SELECT o.id, o.tenant_id FROM public.notification_outbox o
        WHERE o.status IN ('held', 'failed') AND o.not_before <= now()
          AND o.last_error_class IS DISTINCT FROM 'rate_limited'
        ORDER BY o.not_before, o.id
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 100), 500));
END
$$
"""

_RECIPIENTS = """
CREATE FUNCTION notify_gate.tenant_recipients(p_tenant uuid)
RETURNS TABLE (user_id uuid, member_role text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    v_ctx uuid;
BEGIN
    v_ctx := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    IF v_ctx IS NULL OR v_ctx IS DISTINCT FROM p_tenant THEN
        RAISE EXCEPTION 'rls baglami ile uyusmuyor' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
        SELECT m.user_id, m.role::text FROM public.memberships m
        JOIN public.users u ON u.id = m.user_id
        WHERE m.tenant_id = p_tenant AND u.email_verified_at IS NOT NULL
        ORDER BY m.user_id;
END
$$
"""


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{NOTIFY_GATE_ROLE}') THEN
                RAISE EXCEPTION '{NOTIFY_GATE_ROLE} rolu gerekli (0025 ile kurulur)';
            END IF;
            IF NOT pg_catalog.pg_has_role(current_user, '{NOTIFY_GATE_ROLE}', 'SET') THEN
                RAISE EXCEPTION 'migrasyonu calistiran rol {NOTIFY_GATE_ROLE} rolune SET yetkisine sahip degil';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT SELECT (last_error_class) ON notification_outbox TO {NOTIFY_GATE_ROLE}")
    op.execute(f"GRANT SELECT (role) ON memberships TO {NOTIFY_GATE_ROLE}")
    op.execute(
        "CREATE INDEX ix_notification_outbox_failed_due ON notification_outbox (not_before) "
        "WHERE status = 'failed'"
    )
    op.execute(f"SET LOCAL ROLE {NOTIFY_GATE_ROLE}")
    op.execute(_RELEASABLE)
    op.execute("REVOKE ALL ON FUNCTION notify_gate.releasable_outbox(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION notify_gate.releasable_outbox(integer) TO netkar_worker")
    op.execute(_RECIPIENTS)
    op.execute("REVOKE ALL ON FUNCTION notify_gate.tenant_recipients(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION notify_gate.tenant_recipients(uuid) TO netkar_worker")
    op.execute("RESET ROLE")


def _guard() -> None:
    """Prod'da `held`/`failed` satır varken reddeder (satırlar işlevsiz kalırdı); diğer ortamlarda geçer."""
    if os.environ.get("ENVIRONMENT", "").strip().lower() != "prod":
        return
    bind = op.get_bind()
    op.execute("LOCK TABLE notification_outbox IN ACCESS EXCLUSIVE MODE")
    op.execute("ALTER TABLE notification_outbox NO FORCE ROW LEVEL SECURITY")
    stranded = int(
        bind.exec_driver_sql(
            "SELECT count(*) FROM notification_outbox WHERE status IN ('held', 'failed')"
        ).scalar_one()
    )
    op.execute("ALTER TABLE notification_outbox FORCE ROW LEVEL SECURITY")
    if stranded:
        raise RuntimeError(
            f"0027 downgrade REDDEDİLDİ: ENVIRONMENT=prod iken notification_outbox içinde {stranded} held/failed "
            "satır var; keşif işlevi kalkarsa bu satırlar sonsuza dek bekler. Önce dağıtıcıyı durdurup satırları "
            "boşaltın ya da onaylı bir bakım sürecinde ilerleyin."
        )


def downgrade() -> None:
    _guard()
    op.execute(f"SET LOCAL ROLE {NOTIFY_GATE_ROLE}")
    op.execute("DROP FUNCTION notify_gate.tenant_recipients(uuid)")
    op.execute("DROP FUNCTION notify_gate.releasable_outbox(integer)")
    op.execute("RESET ROLE")
    op.execute("DROP INDEX ix_notification_outbox_failed_due")
    op.execute(f"REVOKE SELECT (last_error_class) ON notification_outbox FROM {NOTIFY_GATE_ROLE}")
    op.execute(f"REVOKE SELECT (role) ON memberships FROM {NOTIFY_GATE_ROLE}")
