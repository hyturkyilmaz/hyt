"""Uyarı olayları, geçiş defteri, bildirim tabloları ve gate işlevleri (ADR-0009 D2, §4 ve §5).

Kapsam: yalnız şema, değişmezlik/geçiş tetikleyicileri, RLS, yetkiler ve gate işlevleri. Kural değerlendirmesi,
dağıtıcı, API ve gerçek gönderim sonraki dilimlerdedir.

Tablolar (hepsi ENABLE + FORCE RLS):

- `alert_events`: kalıcı uyarı olayı. Kimlik sütunları (`id`, `tenant_id`, `marketplace_account_id`, `rule`, `scope`,
  `subject`, `dedupe_key`, `first_seen_at`, `created_at`) değişmez (BEFORE UPDATE, ENABLE ALWAYS: superuser ve
  `session_replication_role = replica` dahil 23514). `status`, `muted_until`, `resolved_at` YALNIZ geçiş
  tetikleyicisinin içinden değişir: koruma tetikleyicisi `pg_trigger_depth() >= 2` ister (geçiş tablosunun AFTER INSERT
  tetikleyicisi içindeki UPDATE). ADR §4.3 bunu `set_config` işlem yerel bayrağıyla tarif ediyordu; noktalı GUC her
  rol için USERSET olduğundan (0013 dersi) istemci sahteleyebilirdi, tetikleyici derinliği sahtelenemez. Ek sütunlar
  (ADR §3.1 ve §2): `renotified` (zarar için tek seferlik yeniden bildirim bayrağı) ve `notify_mode`
  (`normal`/`digest_only`/`none`).
  `UNIQUE (tenant_id, marketplace_account_id, dedupe_key)`; `UNIQUE (id, tenant_id)` geçiş tablosunun bileşik FK'sı için.
  `netkar_app` yalnız SELECT; `netkar_worker` SELECT, INSERT ve yalnız sistem sütunlarında UPDATE (sütun düzeyi).
  DELETE hiçbir uygulama rolünde yoktur; yalnız `alert_gate.purge_resolved` (sahibi `netkar_owner`) çözülmüş ve
  saklama süresi dolmuş olayları siler (BEFORE DELETE tetikleyicisi `resolved` dışındakini reddeder).
- `alert_event_transitions`: yalnız ekleme defteri (UPDATE, DELETE, TRUNCATE 23514; DELETE yalnız olay silinirken
  basamaklı silmede, yani tetikleyici derinliği >= 2 iken geçer). Durum değişikliğinin tek yolu bu tabloya INSERT'tür.
  İstemci yalnız `(tenant_id, alert_event_id, to_status, muted_until)` yazar (sütun düzeyi INSERT); `id`,
  `created_at`, `from_status`, `actor`, `actor_user_id` BEFORE INSERT tetikleyicisinde sunucuda türetilir
  (`netkar_app` = kullanıcı, kimlik `app.user_id`; `netkar_worker` = sistem). Aynı tetikleyici ADR §4.2 geçiş
  matrisini uygular (kullanıcı `resolved` yapamaz, `muted` ve `muted -> open` yalnız owner/admin, `muted_until` en
  çok 90 gün; sistem matrisi ve süresi dolmamış `muted -> open` reddi). AFTER INSERT tetikleyicisi (SECURITY DEFINER,
  sahibi `netkar_owner`) olay satırını kilitler, eşzamanlı değişimde 40001 verir ve `alert_events` durum alanlarını
  günceller (`muted_until` yalnız `muted` iken, `resolved_at` yalnız `resolved` iken dolu).
- `alert_rule_settings`: hesap başına eşikler. Yazma `netkar_app` (BEFORE tetikleyicisi `memberships` üzerinden
  owner/admin ister, `updated_by`/`updated_at` sunucuda atanır); worker yalnız okur.
- `notification_preferences`, `notification_settings`: kullanıcı başına; `netkar_app` yalnız kendi satırı
  (politika kiracı VE kullanıcı), worker kiracı içinde okur.
- `push_subscriptions`: uç nokta, `p256dh`, `auth` zarf şifreli sütunlardır ve yalnız worker okur (`netkar_app` bu
  üç sütunda SELECT alamaz, 0005 deseni). İptalde (`revoked_at`) şifreli alanlar tetikleyiciyle NULL'lanır; iptal geri
  alınamaz. `endpoint_digest` benzersizliği kiracı kapsamlı ve KISMİdir (`WHERE revoked_at IS NULL`): iptal sonrası
  aynı uç noktayla yeniden abonelik mümkündür; iptal edilmiş satırlar `alert_gate.purge_push_subscriptions` ile
  30 gün sonra silinir.
- `notification_outbox`: e-posta adresi SAKLAMAZ (gönderimde `notify_gate.email_for`). Yalnız worker yazar; `netkar_app`
  hiçbir yetki almaz. Durum makinesi tetikleyicisi: `pending|held -> sent|failed|suppressed|skipped`,
  `failed -> pending` yalnız `attempts < 6`; kapanmış (`sent`, `suppressed`, `skipped`, `failed_permanent`) satır
  değişmez. ADR'de olmayan ekler: `pending <-> held` (sessiz saat ve sıklık sınırı) ve `failed_permanent` durumu
  (kalıcı hata ya da 6 deneme tükenmesi; `failed` yalnız `attempts < 6` iken geçerlidir, CHECK). `sent_at` sunucuda
  atanır; `last_error_class` yalnız `^[a-z_]{1,40}$`. `UNIQUE (tenant_id, dedupe_key)` (ADR yalnız `dedupe_key` demişti).
- `alert_evaluations`: değerlendirme günlüğü; yalnız ekleme, `status`/`counts` yalnız bir kez (`running` ->
  `succeeded|failed`) değişir, `finished_at` sunucuda atanır. Worker yazar; `netkar_app` yalnız okur ("son değerlendirme").

`payload` ve `counts` jsonb alanları İZİN LİSTELİ CHECK'lerle sınırlıdır (`alert_event_payload_is_safe(payload,
payload_version)`, `alert_outbox_payload_is_safe`, `alert_counts_is_safe`; hepsi `alert_jsonb_is_safe` üzerine): nesne,
en çok 4096 bayt, HER derinlikte yalnız listedeki anahtarlar (olay yükü: `app/alerts/rules.py` kanıt alanları +
`certainty` + iç içe `evidence`), dizi yok, metin değerler en çok 200 karakter ve `x@y` biçimli (e-posta benzeri) değer
yok. Bilinmeyen `payload_version` reddedilir (yeni sürüm = yeni migrasyon).

Gate işlevleri (hepsi SECURITY DEFINER, `search_path = pg_catalog, public, pg_temp`, PUBLIC EXECUTE yok, yalnız
`netkar_worker` çalıştırır, şema USAGE'ı da yalnız worker'da):

- `notify_gate.email_for(outbox_id)` (sahibi yeni NOLOGIN `netkar_notify_gate`): satır `status = 'pending'`,
  `channel = 'email'`, `not_before <= now()` ise ve kiracısı `app.tenant_id` ile eşleşiyorsa (eşleşmezse 42501) satırın
  kullanıcısının adresi (üye ve e-posta doğrulanmışsa), aksi halde NULL. Beyan: bu, hata ve programlama yanlışına karşı
  derinlemesine savunmadır; GUC'yi taklit eden kötü niyetli bir worker'a karşı TAM sınır DEĞİLDİR (worker kendi
  oturumunda `app.tenant_id`'yi ve outbox satırlarını yazabilir).
- `notify_gate.due_outbox(limit)`: kiracılar arası `(id, tenant_id)` iş listesi (`sync_gate` deseni), en çok 500.
- `alert_gate.purge_resolved(cutoff)` (sahibi `netkar_owner`): `cutoff`, 13 aydan yeni olamaz (22023).
- `alert_gate.purge_outbox(cutoff)`: ADR §9 outbox saklaması (30 gün); `cutoff` 30 günden yeni olamaz; yalnız kapanmış
  satırlar (`sent`, `suppressed`, `skipped`, `failed_permanent`) silinir.
- `alert_gate.purge_push_subscriptions(cutoff)`: yalnız iptal edilmiş abonelikler; 30 günden yeni `cutoff` reddedilir.

Ayrıca worker'a `report_data_revisions` SELECT ve `tenant_isolation_worker` politikası verilir (ADR §5 madde 6; 0012
"işçi hiçbir yetki almaz" kararını değiştirir, ADR-0005 §6 kapsamını genişletir, güvenlik incelemesi gerekir).

Yeni tablolar `report_data_revisions` tetikleyici listesine EKLENMEZ: değerlendirmenin kendi yazımı veri sürümünü
artırır ve sonsuz döngü doğurur (ADR §5 madde 7; test korur).

Ön koşul: roller migrasyondan önce kurulur (`app.db.provision.provision_roles` ya da `infra/postgres/init/01-roles.sh`):
`netkar_notify_gate` NOLOGIN ve `GRANT netkar_notify_gate TO netkar_owner WITH INHERIT FALSE, SET TRUE`.

Geri alma: gate işlevleri ve şemalar, tetikleyiciler, politikalar, tablolar sırayla düşer; worker'ın
`report_data_revisions` yetkisi alınır; `netkar_notify_gate` rolü silinmez (provision sahibi). Downgrade koruması
(0021/0022 deseni): ENVIRONMENT=prod iken HER durumda reddedilir; sekiz tabloda toplam kayıt varsa
`NETKAR_ALLOW_ALERT_DATA_LOSS=<toplam kayıt sayısı>` tam eşleşmelidir ("1" yetmez, sayı değiştiyse yeniden hesaplanır);
önce yedek alın. Kayıt yoksa veri kaybı olmadan geri alınır.

Revision ID: 0025
Revises: 0024
"""

import os

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

ALLOW_DATA_LOSS_ENV = "NETKAR_ALLOW_ALERT_DATA_LOSS"
OWNER_ROLE = "netkar_owner"
NOTIFY_GATE_ROLE = "netkar_notify_gate"

TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"

RULES_SQL = "('ZARARINA_SATIS', 'REKLAM_KARI_YIYOR', 'BEKLENMEYEN_KESINTI', 'IADE_ORANI_ARTISI')"
STATUS_SQL = "('open', 'read', 'muted', 'resolved')"

# Silinecek/kaybolacak kayıt sayısı bu sekiz tablodan toplanır (sıra: bağımlılıkların tersi, DROP sırası).
TABLES = (
    "alert_event_transitions",
    "alert_events",
    "alert_evaluations",
    "notification_outbox",
    "push_subscriptions",
    "notification_settings",
    "notification_preferences",
    "alert_rule_settings",
)

_ROLE_GUARD = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'netkar_worker')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'netkar_app')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{OWNER_ROLE}')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{NOTIFY_GATE_ROLE}') THEN
        RAISE EXCEPTION 'netkar_worker, netkar_app, {OWNER_ROLE} ve {NOTIFY_GATE_ROLE} rolleri gerekli: migrasyondan once '
            'app.db.provision.provision_roles veya infra/postgres/init/01-roles.sh calistirin (ADR-0009 5)';
    END IF;
    IF NOT pg_catalog.pg_has_role(current_user, '{NOTIFY_GATE_ROLE}', 'SET') THEN
        RAISE EXCEPTION 'migrasyonu calistiran rol {NOTIFY_GATE_ROLE} rolune SET yetkisine sahip degil: '
            'GRANT {NOTIFY_GATE_ROLE} TO {OWNER_ROLE} WITH INHERIT FALSE, SET TRUE';
    END IF;
END
$$
"""

_EVIDENCE_KEYS = (
    "loss_line_count, total_loss, worst_line_loss, has_missing_items, ad_spend, matched_ad_spend, estimated_ad_spend, "
    "net_profit, profit_before_ads, ad_share_percent, difference, threshold, default_desi_used, commission_rate_differs, "
    "current_lines, current_returned, base_lines, base_returned, current_rate_percent, base_rate_percent, z_squared, "
    "critical_z_squared, tested_count, horizon_days, current_window_days, base_window_days, current_start, current_end, "
    "base_start, base_end, reason_codes, certainty, evidence"
)
_RULE_KEYS = "ZARARINA_SATIS, REKLAM_KARI_YIYOR, BEKLENMEYEN_KESINTI, IADE_ORANI_ARTISI"
_OUTBOX_KEYS = (
    "rule_counts, event_count, total_amount, settings_revision, data_revision, certainty, window_days, " + _RULE_KEYS
)
_COUNTS_KEYS = (
    "opened, updated, resolved, reopened, notified, outbox_rows, candidates, rules_evaluated, rules_no_data, "
    "duration_ms, rule_counts, " + _RULE_KEYS
)


def _array(keys: str) -> str:
    return "ARRAY[" + ", ".join(f"'{k.strip()}'" for k in keys.split(",")) + "]::text[]"


def _wrapper(name: str, args: str, body: str) -> str:
    return (
        f"CREATE FUNCTION public.{name}({args}) RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE "
        f"SET search_path = pg_catalog, public, pg_temp AS $$ SELECT {body} $$"
    )


# ---- Yardımcı işlevler: jsonb yük güvenliği (izin listeli CHECK) ------------------------------------------------------
_PAYLOAD_FUNCTIONS = [
    r"""
CREATE FUNCTION public.alert_jsonb_is_safe(p jsonb, p_allowed text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT p IS NOT NULL
       AND jsonb_typeof(p) = 'object'
       AND octet_length(p::text) <= 4096
       AND NOT EXISTS (
           WITH RECURSIVE n(k, v) AS (
               SELECT NULL::text, p
               UNION ALL
               SELECT e.key, e.value
               FROM n, LATERAL jsonb_each(CASE WHEN jsonb_typeof(n.v) = 'object' THEN n.v ELSE '{}'::jsonb END) e
           )
           SELECT 1 FROM n
           WHERE jsonb_typeof(v) = 'array'
              OR (k IS NOT NULL AND k <> ALL (p_allowed))
              OR (jsonb_typeof(v) = 'string'
                  AND (char_length(v #>> '{}') > 200 OR (v #>> '{}') ~ '[^\s@]+@[^\s@]+'))
       )
$$
""",
    _wrapper(
        "alert_event_payload_is_safe",
        "p jsonb, p_version smallint",
        f"p_version = 1 AND public.alert_jsonb_is_safe(p, {_array(_EVIDENCE_KEYS)})",
    ),
    _wrapper("alert_outbox_payload_is_safe", "p jsonb", f"public.alert_jsonb_is_safe(p, {_array(_OUTBOX_KEYS)})"),
    _wrapper("alert_counts_is_safe", "p jsonb", f"public.alert_jsonb_is_safe(p, {_array(_COUNTS_KEYS)})"),
]
_PAYLOAD_FUNCTION_SIGNATURES = (
    "public.alert_event_payload_is_safe(jsonb, smallint)",
    "public.alert_outbox_payload_is_safe(jsonb)",
    "public.alert_counts_is_safe(jsonb)",
    "public.alert_jsonb_is_safe(jsonb, text[])",
)

_TABLE_SQL = [
    f"""
    CREATE TABLE alert_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        marketplace_account_id uuid NOT NULL,
        rule text NOT NULL CHECK (rule IN {RULES_SQL}),
        scope text NOT NULL CHECK (scope IN ('product', 'order_line', 'account')),
        subject text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 400),
        dedupe_key text NOT NULL CHECK (dedupe_key ~ '^[0-9a-f]{{64}}$'),
        first_seen_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        occurrence_count integer NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
        severity text NOT NULL CHECK (severity IN ('high', 'medium')),
        status text NOT NULL DEFAULT 'open' CHECK (status IN {STATUS_SQL}),
        muted_until timestamptz,
        resolved_at timestamptz,
        payload jsonb NOT NULL DEFAULT '{{}}'::jsonb
            CHECK (public.alert_event_payload_is_safe(payload, payload_version)),
        payload_version smallint NOT NULL CHECK (payload_version >= 1),
        data_revision bigint NOT NULL CHECK (data_revision >= 0),
        settings_revision bigint NOT NULL CHECK (settings_revision >= 0),
        last_notified_at timestamptz,
        notified_amount numeric(14,2),
        renotified boolean NOT NULL DEFAULT false,
        notify_mode text NOT NULL DEFAULT 'normal' CHECK (notify_mode IN ('normal', 'digest_only', 'none')),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT fk_alert_events_account FOREIGN KEY (marketplace_account_id, tenant_id)
            REFERENCES marketplace_accounts (id, tenant_id),
        CONSTRAINT uq_alert_events_dedupe UNIQUE (tenant_id, marketplace_account_id, dedupe_key),
        CONSTRAINT uq_alert_events_id_tenant UNIQUE (id, tenant_id),
        CONSTRAINT ck_alert_events_scope_subject CHECK (
            (scope = 'product' AND subject LIKE 'urun:_%')
            OR (scope = 'order_line' AND subject LIKE 'satir:_%')
            OR (scope = 'account' AND subject = 'hesap:*')),
        CONSTRAINT ck_alert_events_muted CHECK ((status = 'muted') = (muted_until IS NOT NULL)),
        CONSTRAINT ck_alert_events_resolved CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))
    )
    """,
    "CREATE INDEX ix_alert_events_tenant ON alert_events (tenant_id)",
    "CREATE INDEX ix_alert_events_tenant_status_seen ON alert_events (tenant_id, status, last_seen_at DESC)",
    f"""
    CREATE TABLE alert_event_transitions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        alert_event_id uuid NOT NULL,
        from_status text NOT NULL CHECK (from_status IN {STATUS_SQL}),
        to_status text NOT NULL CHECK (to_status IN {STATUS_SQL}),
        actor text NOT NULL CHECK (actor IN ('user', 'system')),
        actor_user_id uuid REFERENCES users (id),
        muted_until timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT fk_alert_event_transitions_event FOREIGN KEY (alert_event_id, tenant_id)
            REFERENCES alert_events (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT ck_alert_event_transitions_change CHECK (from_status <> to_status),
        CONSTRAINT ck_alert_event_transitions_actor CHECK ((actor = 'user') = (actor_user_id IS NOT NULL)),
        CONSTRAINT ck_alert_event_transitions_muted CHECK ((to_status = 'muted') = (muted_until IS NOT NULL))
    )
    """,
    "CREATE INDEX ix_alert_event_transitions_event ON alert_event_transitions (tenant_id, alert_event_id, created_at)",
    f"""
    CREATE TABLE alert_rule_settings (
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        marketplace_account_id uuid NOT NULL,
        loss_min_amount numeric(14,2) NOT NULL DEFAULT 5.00 CHECK (loss_min_amount BETWEEN 0 AND 1000000),
        ad_share_percent numeric(5,2) NOT NULL DEFAULT 100 CHECK (ad_share_percent BETWEEN 50 AND 100),
        ad_min_spend numeric(14,2) NOT NULL DEFAULT 50.00 CHECK (ad_min_spend BETWEEN 0 AND 1000000),
        deduction_notify_min numeric(14,2) NOT NULL DEFAULT 10.00 CHECK (deduction_notify_min BETWEEN 0 AND 1000000),
        return_min_diff_points numeric(5,2) NOT NULL DEFAULT 5 CHECK (return_min_diff_points BETWEEN 0 AND 100),
        rules_enabled text[] NOT NULL DEFAULT ARRAY['ZARARINA_SATIS', 'REKLAM_KARI_YIYOR',
            'BEKLENMEYEN_KESINTI', 'IADE_ORANI_ARTISI']::text[]
            CHECK (rules_enabled <@ ARRAY['ZARARINA_SATIS', 'REKLAM_KARI_YIYOR',
            'BEKLENMEYEN_KESINTI', 'IADE_ORANI_ARTISI']::text[]),
        updated_by uuid NOT NULL REFERENCES users (id),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_alert_rule_settings PRIMARY KEY (tenant_id, marketplace_account_id),
        CONSTRAINT fk_alert_rule_settings_account FOREIGN KEY (marketplace_account_id, tenant_id)
            REFERENCES marketplace_accounts (id, tenant_id)
    )
    """,
    f"""
    CREATE TABLE notification_preferences (
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        user_id uuid NOT NULL REFERENCES users (id),
        rule text NOT NULL CHECK (rule IN {RULES_SQL}),
        channel text NOT NULL CHECK (channel IN ('email', 'push')),
        mode text NOT NULL CHECK (mode IN ('off', 'instant', 'digest')),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_notification_preferences PRIMARY KEY (tenant_id, user_id, rule, channel)
    )
    """,
    """
    CREATE TABLE notification_settings (
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        user_id uuid NOT NULL REFERENCES users (id),
        quiet_start time NOT NULL DEFAULT '22:00',
        quiet_end time NOT NULL DEFAULT '08:00',
        digest_hour smallint NOT NULL DEFAULT 8 CHECK (digest_hour BETWEEN 0 AND 23),
        show_amounts_email boolean NOT NULL DEFAULT true,
        show_amounts_push boolean NOT NULL DEFAULT false,
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_notification_settings PRIMARY KEY (tenant_id, user_id)
    )
    """,
    """
    CREATE TABLE push_subscriptions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        user_id uuid NOT NULL REFERENCES users (id),
        endpoint_host text NOT NULL CHECK (char_length(endpoint_host) BETWEEN 1 AND 253
            AND endpoint_host = lower(endpoint_host)),
        endpoint_digest text NOT NULL CHECK (endpoint_digest ~ '^[0-9a-f]{64}$'),
        endpoint_enc text,
        p256dh_enc text,
        auth_enc text,
        vapid_key_id text NOT NULL CHECK (char_length(vapid_key_id) BETWEEN 1 AND 64),
        created_session_id uuid REFERENCES sessions (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        last_success_at timestamptz,
        failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
        revoked_at timestamptz,
        CONSTRAINT ck_push_subscriptions_secrets CHECK (
            revoked_at IS NOT NULL
            OR (endpoint_enc IS NOT NULL AND p256dh_enc IS NOT NULL AND auth_enc IS NOT NULL))
    )
    """,
    "CREATE INDEX ix_push_subscriptions_tenant_user ON push_subscriptions (tenant_id, user_id)",
    "CREATE UNIQUE INDEX uq_push_subscriptions_endpoint ON push_subscriptions (tenant_id, endpoint_digest) "
    "WHERE revoked_at IS NULL",
    """
    CREATE TABLE notification_outbox (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        user_id uuid NOT NULL REFERENCES users (id),
        channel text NOT NULL CHECK (channel IN ('email', 'push')),
        kind text NOT NULL CHECK (kind IN ('instant', 'digest', 'test')),
        dedupe_key text NOT NULL CHECK (dedupe_key ~ '^[0-9a-f]{64}$'),
        alert_event_ids uuid[] NOT NULL DEFAULT '{}'::uuid[] CHECK (
            cardinality(alert_event_ids) <= 500 AND (kind = 'test' OR cardinality(alert_event_ids) >= 1)),
        payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (public.alert_outbox_payload_is_safe(payload)),
        status text NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'held', 'sent', 'failed', 'failed_permanent', 'suppressed', 'skipped')),
        not_before timestamptz NOT NULL DEFAULT now(),
        attempts smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 6),
        last_error_class text CHECK (last_error_class IS NULL OR last_error_class ~ '^[a-z_]{1,40}$'),
        created_at timestamptz NOT NULL DEFAULT now(),
        sent_at timestamptz,
        CONSTRAINT uq_notification_outbox_dedupe UNIQUE (tenant_id, dedupe_key),
        CONSTRAINT ck_notification_outbox_sent CHECK ((status = 'sent') = (sent_at IS NOT NULL)),
        CONSTRAINT ck_notification_outbox_failed CHECK (status <> 'failed' OR attempts < 6)
    )
    """,
    "CREATE INDEX ix_notification_outbox_tenant ON notification_outbox (tenant_id)",
    "CREATE INDEX ix_notification_outbox_due ON notification_outbox (status, not_before) "
    "WHERE status IN ('pending', 'held')",
    "CREATE INDEX ix_notification_outbox_user_channel "
    "ON notification_outbox (tenant_id, user_id, channel, created_at DESC)",
    """
    CREATE TABLE alert_evaluations (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        marketplace_account_id uuid NOT NULL,
        as_of_date date NOT NULL,
        data_revision bigint NOT NULL CHECK (data_revision >= 0),
        settings_revision bigint NOT NULL CHECK (settings_revision >= 0),
        rules_version integer NOT NULL CHECK (rules_version >= 1),
        started_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz,
        status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
        counts jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (public.alert_counts_is_safe(counts)),
        CONSTRAINT fk_alert_evaluations_account FOREIGN KEY (marketplace_account_id, tenant_id)
            REFERENCES marketplace_accounts (id, tenant_id),
        CONSTRAINT uq_alert_evaluations_key UNIQUE
            (marketplace_account_id, as_of_date, data_revision, settings_revision, rules_version),
        CONSTRAINT ck_alert_evaluations_finished CHECK ((status = 'running') = (finished_at IS NULL))
    )
    """,
    "CREATE INDEX ix_alert_evaluations_tenant_account ON alert_evaluations (tenant_id, marketplace_account_id, started_at DESC)",
]

# Tabloların ve yardımcı işlevin sahibi migrasyonu çalıştıran rolden bağımsız olarak netkar_owner'dır (0013 deseni):
# SECURITY DEFINER işlevler ve `owner_path` politikaları bu role bağlıdır.
_OWNERSHIP = [f"ALTER TABLE {t} OWNER TO {OWNER_ROLE}" for t in reversed(TABLES)] + [
    *[f"ALTER FUNCTION {sig} OWNER TO {OWNER_ROLE}" for sig in _PAYLOAD_FUNCTION_SIGNATURES],
]

_RLS = [
    stmt
    for t in TABLES
    for stmt in (f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY", f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
] + [
    # Kiracı yalıtımı: olay, geçiş, eşik, outbox ve değerlendirme (app ve worker aynı kiracı bağlamıyla çalışır).
    *[
        f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
        f"WITH CHECK (tenant_id = {TENANT_EXPR})"
        for t in (
            "alert_events",
            "alert_event_transitions",
            "alert_rule_settings",
            "notification_outbox",
            "alert_evaluations",
        )
    ],
    # Kullanıcı başına tablolar: uygulama yalnız KENDİ satırını (kiracı VE kullanıcı), worker kiracı içinde okur.
    *[
        f"CREATE POLICY user_self ON {t} FOR ALL TO netkar_app "
        f"USING (tenant_id = {TENANT_EXPR} AND user_id = {USER_EXPR}) "
        f"WITH CHECK (tenant_id = {TENANT_EXPR} AND user_id = {USER_EXPR})"
        for t in ("notification_preferences", "notification_settings", "push_subscriptions")
    ],
    *[
        f"CREATE POLICY tenant_read_worker ON {t} FOR SELECT TO netkar_worker USING (tenant_id = {TENANT_EXPR})"
        for t in ("notification_preferences", "notification_settings")
    ],
    f"CREATE POLICY tenant_worker ON push_subscriptions FOR ALL TO netkar_worker "
    f"USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})",
    # FORCE RLS altında sahip rol: geçiş tetikleyicisi (alert_events güncelleme) ve saklama işlevleri için.
    f"CREATE POLICY owner_path ON alert_events FOR ALL TO {OWNER_ROLE} USING (true) WITH CHECK (true)",
    f"CREATE POLICY owner_path ON notification_outbox FOR ALL TO {OWNER_ROLE} USING (true) WITH CHECK (true)",
    f"CREATE POLICY owner_path ON push_subscriptions FOR ALL TO {OWNER_ROLE} USING (true) WITH CHECK (true)",
    # Olay durum korumasının (aynı işlemde defter satırı arar) okuması.
    f"CREATE POLICY owner_read ON alert_event_transitions FOR SELECT TO {OWNER_ROLE} USING (true)",
    # ADR §5 madde 6: değerlendirme veri sürümünü (0012 sayacı) kiracı bağlamında okur.
    f"CREATE POLICY tenant_isolation_worker ON report_data_revisions FOR SELECT TO netkar_worker "
    f"USING (tenant_id = {TENANT_EXPR})",
]

# ---- Tetikleyici işlevleri ------------------------------------------------------------------------------------------
_FUNCTIONS = [
    # alert_events: doğumda sunucu alanları.
    """
    CREATE FUNCTION public.alert_events_insert_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        NEW.id := gen_random_uuid();
        NEW.created_at := now();
        NEW.first_seen_at := now();
        NEW.status := 'open';
        NEW.muted_until := NULL;
        NEW.resolved_at := NULL;
        RETURN NEW;
    END
    $$
    """,
    # alert_events: kimlik sütunları ve durum alanları.
    """
    CREATE FUNCTION public.alert_events_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.marketplace_account_id IS DISTINCT FROM OLD.marketplace_account_id
           OR NEW.rule IS DISTINCT FROM OLD.rule
           OR NEW.scope IS DISTINCT FROM OLD.scope
           OR NEW.subject IS DISTINCT FROM OLD.subject
           OR NEW.dedupe_key IS DISTINCT FROM OLD.dedupe_key
           OR NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'uyari olayi kimlik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        -- Durum alanları yalnız geçiş tablosunun AFTER INSERT tetikleyicisinin içinden (derinlik >= 2) değişir.
        IF (NEW.status IS DISTINCT FROM OLD.status
            OR NEW.muted_until IS DISTINCT FROM OLD.muted_until
            OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at)
           AND pg_catalog.pg_trigger_depth() < 2 THEN
            RAISE EXCEPTION 'uyari olayi durumu yalnizca alert_event_transitions tablosuna ekleme ile degisir'
                USING ERRCODE = '23514';
        END IF;
        -- Derinlik tek başına yetmez: aynı işlemde yeni duruma geçiren bir defter satırı da bulunmalıdır.
        IF NEW.status IS DISTINCT FROM OLD.status AND NOT EXISTS (
               SELECT 1 FROM public.alert_event_transitions t
               WHERE t.alert_event_id = NEW.id AND t.to_status = NEW.status AND t.created_at = now()) THEN
            RAISE EXCEPTION 'uyari olayi durumu icin ayni islemde gecis kaydi yok' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # alert_events: yalnız çözülmüş olay silinebilir (saklama işlevi); açık olay hiçbir rolle silinemez.
    """
    CREATE FUNCTION public.alert_events_delete_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        IF OLD.status <> 'resolved' THEN
            RAISE EXCEPTION 'yalniz cozulmus uyari olayi silinebilir' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END
    $$
    """,
    # Geçiş defteri: sunucu alanları, aktör türetme ve ADR §4.2 matrisi (çağıranın hakkıyla, RLS altında).
    """
    CREATE FUNCTION public.alert_event_transitions_insert_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_status text;
        v_muted_until timestamptz;
        v_user uuid;
        v_role text;
    BEGIN
        NEW.id := gen_random_uuid();
        NEW.created_at := now();
        SELECT e.status, e.muted_until INTO v_status, v_muted_until
            FROM public.alert_events e WHERE e.id = NEW.alert_event_id AND e.tenant_id = NEW.tenant_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'uyari olayi bulunamadi' USING ERRCODE = '23503';
        END IF;
        NEW.from_status := v_status;
        IF current_user = 'netkar_app' THEN
            v_user := NULLIF(current_setting('app.user_id', true), '')::uuid;
            IF v_user IS NULL THEN
                RAISE EXCEPTION 'kullanici baglami yok' USING ERRCODE = '42501';
            END IF;
            NEW.actor := 'user';
            NEW.actor_user_id := v_user;
        ELSIF current_user = 'netkar_worker' THEN
            NEW.actor := 'system';
            NEW.actor_user_id := NULL;
        END IF;
        IF NEW.actor = 'user' THEN
            SELECT m.role::text INTO v_role FROM public.memberships m
                WHERE m.user_id = NEW.actor_user_id AND m.tenant_id = NEW.tenant_id;
            IF v_role IS NULL THEN
                RAISE EXCEPTION 'kullanici bu kiracinin uyesi degil' USING ERRCODE = '42501';
            END IF;
            IF (v_status = 'open' AND NEW.to_status = 'read') OR (v_status = 'read' AND NEW.to_status = 'open') THEN
                NULL;  -- okundu/açık: her üye
            ELSIF (v_status IN ('open', 'read') AND NEW.to_status = 'muted')
                  OR (v_status = 'muted' AND NEW.to_status = 'open') THEN
                IF v_role NOT IN ('owner', 'admin') THEN
                    RAISE EXCEPTION 'bu gecis icin yonetici yetkisi gerekir' USING ERRCODE = '42501';
                END IF;
            ELSE
                RAISE EXCEPTION 'kullanici icin gecersiz durum gecisi' USING ERRCODE = '23514';
            END IF;
        ELSE
            IF NOT ((v_status IN ('open', 'read') AND NEW.to_status = 'resolved')
                    OR (v_status = 'resolved' AND NEW.to_status = 'open')
                    OR (v_status = 'muted' AND NEW.to_status IN ('open', 'resolved'))) THEN
                RAISE EXCEPTION 'sistem icin gecersiz durum gecisi' USING ERRCODE = '23514';
            END IF;
            IF v_status = 'muted' AND NEW.to_status = 'open' AND v_muted_until > now() THEN
                RAISE EXCEPTION 'susturma suresi dolmadan sistem yeniden acamaz' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF NEW.to_status = 'muted' THEN
            IF NEW.muted_until IS NULL OR NEW.muted_until <= now() OR NEW.muted_until > now() + interval '90 days' THEN
                RAISE EXCEPTION 'susturma bitisi simdi ile 90 gun arasinda olmali' USING ERRCODE = '23514';
            END IF;
        ELSE
            NEW.muted_until := NULL;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # Geçiş defteri: olay satırının durumunu uygular (SECURITY DEFINER; tek durum yazarı).
    """
    CREATE FUNCTION public.alert_event_transitions_apply() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_status text;
        v_muted_until timestamptz;
    BEGIN
        SELECT e.status, e.muted_until INTO v_status, v_muted_until
            FROM public.alert_events e WHERE e.id = NEW.alert_event_id AND e.tenant_id = NEW.tenant_id
            FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'uyari olayi bulunamadi' USING ERRCODE = '23503';
        END IF;
        IF v_status IS DISTINCT FROM NEW.from_status THEN
            RAISE EXCEPTION 'uyari olayi durumu bu arada degisti, yeniden deneyin' USING ERRCODE = '40001';
        END IF;
        IF NEW.actor = 'system' AND v_status = 'muted' AND NEW.to_status = 'open' AND v_muted_until > now() THEN
            RAISE EXCEPTION 'susturma suresi dolmadan sistem yeniden acamaz' USING ERRCODE = '23514';
        END IF;
        UPDATE public.alert_events
            SET status = NEW.to_status,
                muted_until = CASE WHEN NEW.to_status = 'muted' THEN NEW.muted_until END,
                resolved_at = CASE WHEN NEW.to_status = 'resolved' THEN now() END
            WHERE id = NEW.alert_event_id AND tenant_id = NEW.tenant_id;
        RETURN NULL;
    END
    $$
    """,
    # Geçiş defteri: yalnız ekleme. DELETE yalnız olay silinirken basamaklı silmede (derinlik >= 2) geçer.
    """
    CREATE FUNCTION public.alert_event_transitions_immutable() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        IF TG_OP = 'DELETE' AND pg_catalog.pg_trigger_depth() >= 2 THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'durum gecis kayitlari degistirilemez ve silinemez' USING ERRCODE = '23514';
    END
    $$
    """,
    # Olay ve geçiş tablosu: TRUNCATE ile kayıt silinemez (0022 deseni; yalnız replica rolü atlar).
    """
    CREATE FUNCTION public.alert_records_truncate_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        RAISE EXCEPTION 'uyari kayitlari TRUNCATE ile silinemez' USING ERRCODE = '23514';
    END
    $$
    """,
    # Tercih ve ayar tabloları: updated_at sunucuda (istemci yazamaz).
    """
    CREATE FUNCTION public.alert_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        NEW.updated_at := now();
        RETURN NEW;
    END
    $$
    """,
    # alert_rule_settings: yazma yalnız owner/admin; sunucu alanları.
    """
    CREATE FUNCTION public.alert_rule_settings_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_user uuid;
        v_role text;
    BEGIN
        IF TG_OP = 'UPDATE' AND (NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                                 OR NEW.marketplace_account_id IS DISTINCT FROM OLD.marketplace_account_id) THEN
            RAISE EXCEPTION 'esik kaydinin kimlik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        IF current_user = 'netkar_app' THEN
            v_user := NULLIF(current_setting('app.user_id', true), '')::uuid;
            SELECT m.role::text INTO v_role FROM public.memberships m
                WHERE m.user_id = v_user AND m.tenant_id = NEW.tenant_id;
            IF v_role IS NULL OR v_role NOT IN ('owner', 'admin') THEN
                RAISE EXCEPTION 'esikleri yalniz sahip veya yonetici degistirebilir' USING ERRCODE = '42501';
            END IF;
            NEW.updated_by := v_user;
            NEW.updated_at := now();
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # push_subscriptions: kimlik değişmez, iptal geri alınamaz ve şifreli alanları siler.
    """
    CREATE FUNCTION public.push_subscriptions_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            NEW.created_at := now();
            NEW.revoked_at := NULL;
            NEW.last_success_at := NULL;
            NEW.failure_count := 0;
            RETURN NEW;
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.user_id IS DISTINCT FROM OLD.user_id
           OR NEW.endpoint_host IS DISTINCT FROM OLD.endpoint_host
           OR NEW.endpoint_digest IS DISTINCT FROM OLD.endpoint_digest
           OR NEW.vapid_key_id IS DISTINCT FROM OLD.vapid_key_id
           OR NEW.created_session_id IS DISTINCT FROM OLD.created_session_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'abonelik kimlik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        IF OLD.revoked_at IS NOT NULL THEN
            IF NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
                RAISE EXCEPTION 'iptal edilmis abonelik yeniden acilamaz' USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.revoked_at IS NOT NULL THEN
            IF NEW.revoked_at NOT BETWEEN now() - interval '5 minutes' AND now() + interval '5 minutes' THEN
                RAISE EXCEPTION 'iptal zamani gecersiz' USING ERRCODE = '23514';
            END IF;
        END IF;
        -- İptal edilen aboneliğin şifreli alanları (cihaz tanımlayıcısı) her durumda silinir.
        IF NEW.revoked_at IS NOT NULL THEN
            NEW.endpoint_enc := NULL;
            NEW.p256dh_enc := NULL;
            NEW.auth_enc := NULL;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # notification_outbox: doğum değerleri ve durum makinesi.
    """
    CREATE FUNCTION public.notification_outbox_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.status NOT IN ('pending', 'held') THEN
                RAISE EXCEPTION 'outbox satiri pending veya held olarak dogar' USING ERRCODE = '23514';
            END IF;
            NEW.created_at := now();
            NEW.attempts := 0;
            NEW.last_error_class := NULL;
            NEW.sent_at := NULL;
            RETURN NEW;
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.user_id IS DISTINCT FROM OLD.user_id
           OR NEW.channel IS DISTINCT FROM OLD.channel
           OR NEW.kind IS DISTINCT FROM OLD.kind
           OR NEW.dedupe_key IS DISTINCT FROM OLD.dedupe_key
           OR NEW.alert_event_ids IS DISTINCT FROM OLD.alert_event_ids
           OR NEW.payload IS DISTINCT FROM OLD.payload
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'outbox kimlik ve icerik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        IF OLD.status IN ('sent', 'suppressed', 'skipped', 'failed_permanent') THEN
            RAISE EXCEPTION 'kapanmis outbox satiri degistirilemez' USING ERRCODE = '23514';
        END IF;
        IF NEW.attempts < OLD.attempts THEN
            RAISE EXCEPTION 'deneme sayisi geriye alinamaz' USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'failed' AND NEW.status <> 'failed' THEN
            IF NEW.status NOT IN ('pending', 'failed_permanent') OR OLD.attempts >= 6 THEN
                RAISE EXCEPTION 'failed satiri yalniz pending (6 denemeden az) ya da failed_permanent olabilir'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF NEW.status = 'sent' THEN
            NEW.sent_at := now();
        ELSE
            NEW.sent_at := NULL;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # alert_evaluations: doğum değerleri; kapanış bir kez.
    """
    CREATE FUNCTION public.alert_evaluations_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            NEW.started_at := now();
            NEW.finished_at := NULL;
            NEW.status := 'running';
            RETURN NEW;
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.marketplace_account_id IS DISTINCT FROM OLD.marketplace_account_id
           OR NEW.as_of_date IS DISTINCT FROM OLD.as_of_date
           OR NEW.data_revision IS DISTINCT FROM OLD.data_revision
           OR NEW.settings_revision IS DISTINCT FROM OLD.settings_revision
           OR NEW.rules_version IS DISTINCT FROM OLD.rules_version
           OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
            RAISE EXCEPTION 'degerlendirme kimlik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        IF OLD.status <> 'running' THEN
            RAISE EXCEPTION 'kapanmis degerlendirme degistirilemez' USING ERRCODE = '23514';
        END IF;
        IF NEW.status NOT IN ('succeeded', 'failed') THEN
            RAISE EXCEPTION 'degerlendirme yalniz succeeded veya failed ile kapanir' USING ERRCODE = '23514';
        END IF;
        NEW.finished_at := now();
        RETURN NEW;
    END
    $$
    """,
    f"ALTER FUNCTION public.alert_event_transitions_apply() OWNER TO {OWNER_ROLE}",
]

_TRIGGERS = [
    "CREATE TRIGGER alert_events_insert_guard BEFORE INSERT ON alert_events "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_events_insert_guard()",
    "CREATE TRIGGER alert_events_immutable_guard BEFORE UPDATE ON alert_events "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_events_immutable_guard()",
    "CREATE TRIGGER alert_events_delete_guard BEFORE DELETE ON alert_events "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_events_delete_guard()",
    "CREATE TRIGGER alert_events_truncate_guard BEFORE TRUNCATE ON alert_events "
    "FOR EACH STATEMENT EXECUTE FUNCTION public.alert_records_truncate_guard()",
    "CREATE TRIGGER alert_event_transitions_insert_guard BEFORE INSERT ON alert_event_transitions "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_event_transitions_insert_guard()",
    "CREATE TRIGGER alert_event_transitions_apply AFTER INSERT ON alert_event_transitions "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_event_transitions_apply()",
    "CREATE TRIGGER alert_event_transitions_immutable BEFORE UPDATE OR DELETE ON alert_event_transitions "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_event_transitions_immutable()",
    "CREATE TRIGGER alert_event_transitions_truncate_guard BEFORE TRUNCATE ON alert_event_transitions "
    "FOR EACH STATEMENT EXECUTE FUNCTION public.alert_records_truncate_guard()",
    "CREATE TRIGGER notification_preferences_touch_guard BEFORE UPDATE ON notification_preferences "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_touch_updated_at()",
    "CREATE TRIGGER notification_settings_touch_guard BEFORE UPDATE ON notification_settings "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_touch_updated_at()",
    "CREATE TRIGGER alert_rule_settings_guard BEFORE INSERT OR UPDATE ON alert_rule_settings "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_rule_settings_guard()",
    "CREATE TRIGGER push_subscriptions_guard BEFORE INSERT OR UPDATE ON push_subscriptions "
    "FOR EACH ROW EXECUTE FUNCTION public.push_subscriptions_guard()",
    "CREATE TRIGGER notification_outbox_guard BEFORE INSERT OR UPDATE ON notification_outbox "
    "FOR EACH ROW EXECUTE FUNCTION public.notification_outbox_guard()",
    "CREATE TRIGGER alert_evaluations_guard BEFORE INSERT OR UPDATE ON alert_evaluations "
    "FOR EACH ROW EXECUTE FUNCTION public.alert_evaluations_guard()",
    # Değişmezlik ve durum makinesi tetikleyicileri çoğaltma modunda da çalışır (0023/0024 deseni). TRUNCATE
    # tetikleyicileri bilerek hariç: test temizliği ve bakım için yalnız superuser'ın replica rolüyle atlanır (0022).
    *[
        f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}"
        for table, trigger in (
            ("alert_events", "alert_events_insert_guard"),
            ("alert_events", "alert_events_immutable_guard"),
            ("alert_events", "alert_events_delete_guard"),
            ("alert_event_transitions", "alert_event_transitions_insert_guard"),
            ("alert_event_transitions", "alert_event_transitions_apply"),
            ("alert_event_transitions", "alert_event_transitions_immutable"),
            ("notification_preferences", "notification_preferences_touch_guard"),
            ("notification_settings", "notification_settings_touch_guard"),
            ("alert_rule_settings", "alert_rule_settings_guard"),
            ("push_subscriptions", "push_subscriptions_guard"),
            ("notification_outbox", "notification_outbox_guard"),
            ("alert_evaluations", "alert_evaluations_guard"),
        )
    ],
    # Tetikleyici işlevinin doğrudan çağrılmasını da kapatmak için PUBLIC EXECUTE alınır (tetikleyici EXECUTE gerektirmez).
    "REVOKE ALL ON FUNCTION public.alert_event_transitions_apply() FROM PUBLIC",
]

_GRANTS = [
    # ---- netkar_app --------------------------------------------------------------------------------------------
    "GRANT SELECT ON alert_events TO netkar_app",
    "GRANT SELECT ON alert_event_transitions TO netkar_app",
    "GRANT INSERT (tenant_id, alert_event_id, to_status, muted_until) ON alert_event_transitions TO netkar_app",
    "GRANT SELECT ON alert_evaluations TO netkar_app",
    "GRANT SELECT ON alert_rule_settings TO netkar_app",
    "GRANT INSERT (tenant_id, marketplace_account_id, loss_min_amount, ad_share_percent, ad_min_spend, "
    "deduction_notify_min, return_min_diff_points, rules_enabled) ON alert_rule_settings TO netkar_app",
    "GRANT UPDATE (loss_min_amount, ad_share_percent, ad_min_spend, deduction_notify_min, "
    "return_min_diff_points, rules_enabled) ON alert_rule_settings TO netkar_app",
    "GRANT SELECT ON notification_preferences TO netkar_app",
    "GRANT INSERT (tenant_id, user_id, rule, channel, mode) ON notification_preferences TO netkar_app",
    "GRANT UPDATE (mode) ON notification_preferences TO netkar_app",
    "GRANT SELECT ON notification_settings TO netkar_app",
    "GRANT INSERT (tenant_id, user_id, quiet_start, quiet_end, digest_hour, show_amounts_email, "
    "show_amounts_push) ON notification_settings TO netkar_app",
    "GRANT UPDATE (quiet_start, quiet_end, digest_hour, show_amounts_email, show_amounts_push) "
    "ON notification_settings TO netkar_app",
    # Şifreli üç sütun uygulamaya okunmaz (0005 deseni): yalnız yazılır; okuyan tek rol worker'dır.
    "GRANT SELECT (id, tenant_id, user_id, endpoint_host, endpoint_digest, vapid_key_id, created_session_id, "
    "created_at, last_success_at, failure_count, revoked_at) ON push_subscriptions TO netkar_app",
    "GRANT INSERT (tenant_id, user_id, endpoint_host, endpoint_digest, endpoint_enc, p256dh_enc, auth_enc, "
    "vapid_key_id, created_session_id) ON push_subscriptions TO netkar_app",
    "GRANT UPDATE (revoked_at) ON push_subscriptions TO netkar_app",
    # ---- netkar_worker -----------------------------------------------------------------------------------------
    "GRANT SELECT ON alert_events, alert_event_transitions, alert_evaluations, alert_rule_settings, "
    "notification_preferences, notification_settings, push_subscriptions, notification_outbox TO netkar_worker",
    "GRANT INSERT (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, last_seen_at, "
    "occurrence_count, severity, payload, payload_version, data_revision, settings_revision, last_notified_at, "
    "notified_amount, renotified, notify_mode) ON alert_events TO netkar_worker",
    "GRANT UPDATE (last_seen_at, occurrence_count, severity, payload, payload_version, data_revision, "
    "settings_revision, last_notified_at, notified_amount, renotified, notify_mode) ON alert_events TO netkar_worker",
    "GRANT INSERT (tenant_id, alert_event_id, to_status, muted_until) ON alert_event_transitions TO netkar_worker",
    "GRANT INSERT (tenant_id, marketplace_account_id, as_of_date, data_revision, settings_revision, "
    "rules_version) ON alert_evaluations TO netkar_worker",
    "GRANT UPDATE (status, counts) ON alert_evaluations TO netkar_worker",
    "GRANT INSERT (tenant_id, user_id, channel, kind, dedupe_key, alert_event_ids, payload, status, not_before) "
    "ON notification_outbox TO netkar_worker",
    "GRANT UPDATE (status, not_before, attempts, last_error_class) ON notification_outbox TO netkar_worker",
    "GRANT UPDATE (last_success_at, failure_count, revoked_at) ON push_subscriptions TO netkar_worker",
    # ADR §5 madde 6: değerlendirme veri sürümünü okur.
    "GRANT SELECT ON report_data_revisions TO netkar_worker",
]

# ---- notify_gate (sahibi netkar_notify_gate) ve alert_gate (sahibi netkar_owner) ------------------------------------
_NOTIFY_GATE_GRANTS = [
    # Yalnız bu rol için açık, adlandırılmış okuma politikaları (sync_gate deseni) ve dar sütun yetkileri.
    "GRANT SELECT (id, email, email_verified_at) ON users TO netkar_notify_gate",
    "GRANT SELECT (user_id, tenant_id) ON memberships TO netkar_notify_gate",
    "GRANT SELECT (id, tenant_id, user_id, status, channel, not_before) ON notification_outbox TO netkar_notify_gate",
    "CREATE POLICY notify_gate_path ON users FOR SELECT TO netkar_notify_gate USING (true)",
    "CREATE POLICY notify_gate_path ON memberships FOR SELECT TO netkar_notify_gate USING (true)",
    "CREATE POLICY notify_gate_path ON notification_outbox FOR SELECT TO netkar_notify_gate USING (true)",
    "CREATE SCHEMA notify_gate AUTHORIZATION netkar_notify_gate",
]

_NOTIFY_GATE_FUNCTIONS = [
    "REVOKE ALL ON SCHEMA notify_gate FROM PUBLIC",
    "GRANT USAGE ON SCHEMA notify_gate TO netkar_worker",
    """
    CREATE FUNCTION notify_gate.email_for(p_outbox_id uuid)
    RETURNS text
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_ctx uuid;
        v_tenant uuid;
        v_user uuid;
    BEGIN
        -- Derinlemesine savunma (hata ve programlama yanlışına karşı; GUC'yi taklit eden worker'a karşı tam sınır değil).
        v_ctx := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
        IF v_ctx IS NULL THEN
            RAISE EXCEPTION 'rls baglami yok' USING ERRCODE = '42501';
        END IF;
        SELECT o.tenant_id, o.user_id INTO v_tenant, v_user
            FROM public.notification_outbox o
            WHERE o.id = p_outbox_id AND o.status = 'pending' AND o.channel = 'email' AND o.not_before <= now();
        IF NOT FOUND THEN
            RETURN NULL;
        END IF;
        IF v_tenant IS DISTINCT FROM v_ctx THEN
            RAISE EXCEPTION 'rls baglami ile uyusmuyor' USING ERRCODE = '42501';
        END IF;
        RETURN (
            SELECT u.email
            FROM public.users u
            JOIN public.memberships m ON m.user_id = u.id AND m.tenant_id = v_tenant
            WHERE u.id = v_user AND u.email_verified_at IS NOT NULL
        );
    END
    $$
    """,
    """
    CREATE FUNCTION notify_gate.due_outbox(p_limit integer DEFAULT 100)
    RETURNS TABLE (id uuid, tenant_id uuid)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    BEGIN
        RETURN QUERY
            SELECT o.id, o.tenant_id FROM public.notification_outbox o
            WHERE o.status = 'pending' AND o.not_before <= now()
            ORDER BY o.not_before, o.id
            LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 100), 500));
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION notify_gate.email_for(uuid) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION notify_gate.due_outbox(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION notify_gate.email_for(uuid) TO netkar_worker",
    "GRANT EXECUTE ON FUNCTION notify_gate.due_outbox(integer) TO netkar_worker",
]

_ALERT_GATE = [
    f"CREATE SCHEMA alert_gate AUTHORIZATION {OWNER_ROLE}",
    "REVOKE ALL ON SCHEMA alert_gate FROM PUBLIC",
    "GRANT USAGE ON SCHEMA alert_gate TO netkar_worker",
    """
    CREATE FUNCTION alert_gate.purge_resolved(p_cutoff timestamptz)
    RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_count integer;
    BEGIN
        -- Saklama süresi (13 ay, ADR-0009 H13) dolmamış kayıt silinemez: ele geçirilmiş worker toplu silemez.
        IF p_cutoff IS NULL OR p_cutoff > now() - interval '13 months' THEN
            RAISE EXCEPTION 'saklama suresi dolmamis olaylar silinemez' USING ERRCODE = '22023';
        END IF;
        DELETE FROM public.alert_events WHERE status = 'resolved' AND resolved_at < p_cutoff;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END
    $$
    """,
    """
    CREATE FUNCTION alert_gate.purge_outbox(p_cutoff timestamptz)
    RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_count integer;
    BEGIN
        -- Saklama süresi (30 gün, ADR-0009 §9) dolmamış kayıt silinemez; bekleyen ve yeniden denenebilir satırlar kalır.
        IF p_cutoff IS NULL OR p_cutoff > now() - interval '30 days' THEN
            RAISE EXCEPTION 'saklama suresi dolmamis outbox satirlari silinemez' USING ERRCODE = '22023';
        END IF;
        DELETE FROM public.notification_outbox
            WHERE created_at < p_cutoff
              AND status IN ('sent', 'suppressed', 'skipped', 'failed_permanent');
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END
    $$
    """,
    """
    CREATE FUNCTION alert_gate.purge_push_subscriptions(p_cutoff timestamptz)
    RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_count integer;
    BEGIN
        -- Yalnız iptal edilmiş abonelikler ve 30 günlük saklama tabanı (ADR-0009 §9).
        IF p_cutoff IS NULL OR p_cutoff > now() - interval '30 days' THEN
            RAISE EXCEPTION 'saklama suresi dolmamis abonelikler silinemez' USING ERRCODE = '22023';
        END IF;
        DELETE FROM public.push_subscriptions WHERE revoked_at IS NOT NULL AND revoked_at < p_cutoff;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END
    $$
    """,
    f"ALTER FUNCTION alert_gate.purge_push_subscriptions(timestamptz) OWNER TO {OWNER_ROLE}",
    "REVOKE ALL ON FUNCTION alert_gate.purge_push_subscriptions(timestamptz) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION alert_gate.purge_push_subscriptions(timestamptz) TO netkar_worker",
    f"ALTER FUNCTION alert_gate.purge_resolved(timestamptz) OWNER TO {OWNER_ROLE}",
    f"ALTER FUNCTION alert_gate.purge_outbox(timestamptz) OWNER TO {OWNER_ROLE}",
    "REVOKE ALL ON FUNCTION alert_gate.purge_resolved(timestamptz) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION alert_gate.purge_outbox(timestamptz) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION alert_gate.purge_resolved(timestamptz) TO netkar_worker",
    "GRANT EXECUTE ON FUNCTION alert_gate.purge_outbox(timestamptz) TO netkar_worker",
]

_DOWNGRADE_GATES = [
    f"SET LOCAL ROLE {NOTIFY_GATE_ROLE}",
    "DROP SCHEMA IF EXISTS notify_gate CASCADE",
    "RESET ROLE",
    "DROP SCHEMA IF EXISTS alert_gate CASCADE",
    "DROP POLICY IF EXISTS notify_gate_path ON notification_outbox",
    "DROP POLICY IF EXISTS notify_gate_path ON memberships",
    "DROP POLICY IF EXISTS notify_gate_path ON users",
    f"REVOKE ALL ON users, memberships, notification_outbox FROM {NOTIFY_GATE_ROLE}",
    "DROP POLICY IF EXISTS tenant_isolation_worker ON report_data_revisions",
    "REVOKE ALL ON report_data_revisions FROM netkar_worker",
]

_DOWNGRADE_OBJECTS = [
    *[f"DROP TABLE IF EXISTS {t}" for t in TABLES],
    "DROP FUNCTION IF EXISTS public.alert_evaluations_guard()",
    "DROP FUNCTION IF EXISTS public.notification_outbox_guard()",
    "DROP FUNCTION IF EXISTS public.push_subscriptions_guard()",
    "DROP FUNCTION IF EXISTS public.alert_rule_settings_guard()",
    "DROP FUNCTION IF EXISTS public.alert_records_truncate_guard()",
    "DROP FUNCTION IF EXISTS public.alert_event_transitions_immutable()",
    "DROP FUNCTION IF EXISTS public.alert_event_transitions_apply()",
    "DROP FUNCTION IF EXISTS public.alert_event_transitions_insert_guard()",
    "DROP FUNCTION IF EXISTS public.alert_events_delete_guard()",
    "DROP FUNCTION IF EXISTS public.alert_events_immutable_guard()",
    "DROP FUNCTION IF EXISTS public.alert_events_insert_guard()",
    "DROP FUNCTION IF EXISTS public.alert_touch_updated_at()",
    *[f"DROP FUNCTION IF EXISTS {sig}" for sig in _PAYLOAD_FUNCTION_SIGNATURES],
]


def upgrade() -> None:
    op.execute(_ROLE_GUARD)
    for statement in _PAYLOAD_FUNCTIONS:
        op.execute(statement)
    for statement in _TABLE_SQL:
        op.execute(statement)
    for statement in _OWNERSHIP:
        op.execute(statement)
    for statement in (*_RLS, *_FUNCTIONS, *_TRIGGERS, *_GRANTS, *_NOTIFY_GATE_GRANTS):
        op.execute(statement)
    op.execute(f"SET LOCAL ROLE {NOTIFY_GATE_ROLE}")
    for statement in _NOTIFY_GATE_FUNCTIONS:
        op.execute(statement)
    op.execute("RESET ROLE")
    for statement in _ALERT_GATE:
        op.execute(statement)


def _guard() -> None:
    """Prod'da her durumda reddeder; kayıt varsa bayrak toplam kayıt sayısıyla tam eşleşmeli (0022 deseni)."""
    if os.environ.get("ENVIRONMENT", "").strip().lower() == "prod":
        raise RuntimeError(
            "0025 downgrade REDDEDİLDİ: ENVIRONMENT=prod iken uyarı olayları ve bildirim kayıtları geri alınamaz. "
            "Gerekirse önce yedek alıp ayrı, onaylı bir bakım sürecinde ilerleyin."
        )
    bind = op.get_bind()
    # Sayım ile DROP arasında eşzamanlı yazım olmasın (D8): tüm tablolar kilitlenir.
    op.execute("LOCK TABLE " + ", ".join(TABLES) + " IN ACCESS EXCLUSIVE MODE")
    # FORCE RLS altında sayım için geçici kapatılır; hata ya da sonraki DROP işlemle birlikte geri alınır/düşer.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    total = int(
        bind.exec_driver_sql(
            "SELECT (SELECT count(*) FROM alert_event_transitions) + (SELECT count(*) FROM alert_events)"
            " + (SELECT count(*) FROM alert_evaluations) + (SELECT count(*) FROM notification_outbox)"
            " + (SELECT count(*) FROM push_subscriptions) + (SELECT count(*) FROM notification_settings)"
            " + (SELECT count(*) FROM notification_preferences) + (SELECT count(*) FROM alert_rule_settings)"
        ).scalar_one()
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    if total == 0:
        return
    if os.environ.get(ALLOW_DATA_LOSS_ENV) != str(total):
        raise RuntimeError(
            f"0025 downgrade DURDURULDU: uyarı ve bildirim tablolarında toplam {total} kayıt var (olay, geçiş, "
            "değerlendirme, outbox, push aboneliği, bildirim tercihi ve ayarı, eşik). Önce yedek alın "
            "(pg_dump -t alert_events -t alert_event_transitions -t alert_evaluations -t notification_outbox "
            "-t push_subscriptions -t notification_settings -t notification_preferences -t alert_rule_settings). "
            f"Kaybı bilerek kabul ediyorsanız {ALLOW_DATA_LOSS_ENV}={total} ile yeniden çalıştırın "
            "(sayı değiştiyse yeniden hesaplanır). Downgrade uygulama (API ve worker) DURDURULMUŞKEN çalıştırılmalı."
        )


def downgrade() -> None:
    _guard()
    for statement in _DOWNGRADE_GATES:
        op.execute(statement)
    for statement in _DOWNGRADE_OBJECTS:
        op.execute(statement)
