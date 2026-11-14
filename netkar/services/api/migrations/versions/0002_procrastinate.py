"""procrastinate iş kuyruğu şeması (PostgreSQL tabanlı kuyruk) ve uygulama rolü yetkileri.

Şema, kurulu procrastinate sürümünün kendi schema.sql dosyasıdır. Sürüm yükseltmelerinde
procrastinate'in sağladığı artımlı SQL migrasyonları yeni bir Alembic revizyonuyla uygulanır.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
from procrastinate.schema import SchemaManager

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_GRANTS = """
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT c.relname, c.relkind FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relname LIKE 'procrastinate\\_%' AND c.relkind IN ('r', 'S')
    LOOP
        IF r.relkind = 'r' THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO netkar_app', r.relname);
        ELSE
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE public.%I TO netkar_app', r.relname);
        END IF;
    END LOOP;
END
$$
"""


def upgrade() -> None:
    connection = op.get_bind().connection  # ham DBAPI bağlantısı: % ve : karakterleri yorumlanmaz
    cursor = connection.cursor()
    cursor.execute(SchemaManager.get_schema())
    cursor.execute(_GRANTS)


def downgrade() -> None:
    for name in (
        "procrastinate_periodic_defers",
        "procrastinate_events",
        "procrastinate_workers",
        "procrastinate_jobs",
    ):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p
                     JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate\\_%'
            LOOP
                EXECUTE 'DROP FUNCTION IF EXISTS ' || r.sig || ' CASCADE';
            END LOOP;
        END $$
        """
    )
    for typ in ("procrastinate_job_to_defer_v1", "procrastinate_job_event_type", "procrastinate_job_status"):
        op.execute(f"DROP TYPE IF EXISTS {typ} CASCADE")
