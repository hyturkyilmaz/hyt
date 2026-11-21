"""Bildirim dağıtıcısı (ADR-0009 D5, §7.1 ve §7.3): `dispatch` (outbox) ve `build_digests` (günlük özet).

Gerçek gönderim KAPALIDIR (`ALERT_NOTIFICATIONS_ENABLED=false`, varsayılan): kapalıyken gerçek arka uç
ASLA çağrılmaz, satır `suppressed` olur; ileti yalnız yerel geliştirme arka ucuna (`dev_sender`: `file`
ya da `memory`, ağa çıkmaz) yazılır. Gerçek e-posta sağlayıcısı entegrasyonu bu modülde YOKTUR (karar
H5/K12 Hasan'da): yalnız `EmailSender` arayüzü kullanılır.

`dispatch` akışı (idempotent; hesap değil outbox satırı başına, kiracı işlemiyle):
1. Bırakma: `notify_gate.releasable_outbox` ile süresi gelmiş `held` (sessiz saat) ve `failed` (geçici
   hata, bekleme bitti) satırlar `pending`'e döner. Sıklık sınırı nedeniyle bekleyen satırlar
   (`rate_limited`) bırakılmaz.
2. Liste: `notify_gate.due_outbox` (yalnız `id`, `tenant_id`). Her satır kendi kiracı işleminde `FOR
   UPDATE SKIP LOCKED` ile kilitlenir (aşama 1, aşağıdaki 5 ve 6): iki dağıtıcı aynı satırı iki kez almaz.
3. Kapılar (yalnız bayrak AÇIKKEN, `instant` e-posta): kullanıcının sessiz saati içindeyse satır `held`
   olur ve `not_before` = sessiz saat bitişi (08:00 İstanbul); kullanıcı ve kanal başına günlük 4 ileti
   ya da iki anlık arası 30 dakika aşılırsa satır `held` + `rate_limited` olur ve sonraki günlük özete
   katlanır (silinmez).
4. Aynı kullanıcıya bekleyen diğer anlık satırlar tek iletide birleşir (sessiz saat birikimi); birleşen
   satırlar `skipped` (`merged`) olur. Grup kimliğe göre sıralıdır: idempotency anahtarı sıralı kimliklerin
   özetidir ve ileti içeriği (token zamanı grubun en eski `created_at`ı) yeniden denemede aynıdır. Anahtar
   GRUP DEĞİŞMEDİKÇE kararlıdır (yeni satır gelirse ya da bir satır başka çalıştırmaya geçerse grup,
   anahtar ve içerik değişir; sağlayıcıya yeni ileti olarak gider).
5. Alıcı adresi YALNIZ burada, `notify_gate.email_for(outbox_id)` ile okunur (yalnız `pending`, `email`,
   zamanı gelmiş ve kiracısı bağlamla eşleşen satır): üyelikten çıkmış ya da e-postası doğrulanmamış
   kullanıcıda NULL döner ve satır `skipped` (`recipient_unavailable`) olur. Adres outbox'a, loga, hata
   metnine ve durum alanlarına YAZILMAZ.
6. Gönderim İŞLEM DIŞINDADIR, üç aşamalı: (1) işlem: kapılar, alıcı çözümü, ileti kurma ve grubun satırlarını
   KİRALAMA (`not_before = now() + 10 dk`, veritabanı saati) ve commit; (2) kilitsiz gönderim (`sender.send`,
   zaman aşımlı, `idempotency_key`; bayrak kapalıysa yerel arka uca yazılır ve satır `suppressed`); (3) sonuç
   yazımı, YALNIZ kirayı hâlâ tutuyorsak (`not_before = kira`): kira başkasına geçtiyse yazım etkisiz kalır
   (`lease_lost`). Başarı `sent`; geçici hata `failed` (deneme + 1, üstel bekleme 4, 16, 64, 256, 1024 sn,
   grubun tüm satırlarında aynı `not_before`); kalıcı hata (`EmailPermanentError`) ya da 6. hata
   `failed_permanent`.
   Çökerse satır kiralı `pending` kalır, kira dolunca aynı anahtarla yeniden denenir; beklenmeyen hata grubun
   TÜM satırlarına ayrı işlemde `attempts + 1` ve `failed` yazar. `last_error_class` yalnız hata SINIFI adı.
7. Push kanalı D8'in işidir (gönderici yok): push satırları `suppressed` olur (`push_not_available`).

`build_digests`: her saat başı (cron `13 * * * *` UTC) çalışır. Kullanıcının özet saati (varsayılan 08)
İstanbul saatine eşitse, `digest` modundaki kurallar için son 24 saatte AÇILAN olaylardan ve sıklık
sınırıyla katlanan bekleyen satırların olaylarından TEK özet satırı (`kind = 'digest'`) yazar; yeni olay
yoksa ileti yoktur (pencere YARI AÇIK `(tik - 24 sa, tik]`, tik zamanı parametredir; ardışık günlerde
aynı olay iki özete girmez). Bastırma (O-a) özette de geçerlidir: kaynağı bozuk kuralın olayları
özete girmez. Aynı gün ve saat için ikinci çalıştırma `dedupe_key` ile hiçbir şey yazmaz.

Log: yalnız sayaçlar ve hata sınıfı. E-posta adresi, barkod, tutar, sipariş numarası YOK (G09). SQL:
yalnız düz sabit dizge ve bağlı parametre (f-string ve birleştirme yok; test ve semgrep kuralı korur).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time as monotonic
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.alerts import AlertRule
from app.core.config import Settings
from app.core.email import (
    EmailMessage,
    EmailPermanentError,
    EmailSender,
    build_local_email_sender,
    is_local_sender,
)
from app.db.rls import tenant_transaction
from app.profit.schema_v1 import ISTANBUL
from app.services.alert_api import default_matrix
from app.services.alert_evaluation import (
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    WINDOW_DAYS,
    blocked_rules,
    quiet_until,
)
from app.services.notify_templates import (
    PANEL_PATH,
    SETTINGS_PATH,
    UNSUBSCRIBE_API_PATH,
    UNSUBSCRIBE_PAGE_PATH,
    RenderContext,
    clean_title,
    lines_from_payload,
    merge_payloads,
    render_email,
)
from app.services.notify_unsubscribe import ALL_RULES, UnsubscribeSigner

logger = logging.getLogger("netkar.notify")

try:
    LOCAL_TZ: ZoneInfo | Any = ZoneInfo("Europe/Istanbul")
except ZoneInfoNotFoundError:  # pragma: no cover - tzdata'sız ortam: Türkiye'de yaz saati yok (UTC+3)
    LOCAL_TZ = ISTANBUL

# --------------------------------------------------------------------------- sabitler (ADR-0009 §7.1, §7.3)
EMAIL_INSTANT_DAILY_LIMIT = 4
MIN_INSTANT_GAP = timedelta(minutes=30)
MAX_ATTEMPTS = 6
# Başarısız denemeden sonra bekleme (sn): `SYNC_RETRY` ile aynı üstel aralıklar (4^n).
BACKOFF_SECONDS = (4, 16, 64, 256, 1024)
SEND_TIMEOUT_SECONDS = 30.0
DISPATCH_BATCH = 100
# Bir `dispatch` çalıştırmasının toplam süre üst sınırı (sn): aşılınca kalan satırlar sonraki tike kalır.
DISPATCH_BUDGET_SECONDS = 50.0
# Gönderim işlem DIŞINDA yapılır: satır önce bu süreyle kiralanır (`not_before`, veritabanı saati);
# çökerse süre
# dolunca yeniden denenir (sağlayıcıya `idempotency_key` verilir).
SEND_LEASE_SECONDS = 600
MAX_DISPATCH_ROUNDS = 5
MAX_MERGED_ROWS = 50
MAX_EVENT_IDS = 500
DIGEST_WINDOW_HOURS = 24
DEFAULT_DIGEST_HOUR = 8
# Sıklık sınırı nedeniyle bekleyen satır işareti; `notify_gate.releasable_outbox` bunları bırakmaz.
RATE_LIMITED = "rate_limited"
# Özetin hiç gelmediği (kapalı) kullanıcıda katlanamayan bekleyen satırlar bu süreden sonra kapatılır.
HELD_EXPIRY = timedelta(days=2)

_RULE_VALUES = tuple(rule.value for rule in AlertRule)
# Kural -> olay kanıtındaki tutar anahtarı (`alert_evaluation.candidate_amount` ile aynı eşleme; iade: yok).
_AMOUNT_KEYS = {
    AlertRule.LOSS_MAKING_SALE.value: "total_loss",
    AlertRule.UNEXPECTED_DEDUCTION.value: "difference",
    AlertRule.AD_EATS_PROFIT.value: "ad_spend",
}

# --------------------------------------------------------------------------- SQL (düz sabit dizgeler)
_SQL_RELEASABLE = text("SELECT id, tenant_id FROM notify_gate.releasable_outbox(:limit)")
_SQL_DUE = text("SELECT id, tenant_id FROM notify_gate.due_outbox(:limit)")
_SQL_RELEASE = text(
    "UPDATE notification_outbox SET status = 'pending' WHERE id = :id AND tenant_id = :tenant_id "
    "AND status IN ('held', 'failed') AND not_before <= now() "
    "AND last_error_class IS DISTINCT FROM 'rate_limited' RETURNING id"
)
_SQL_LOCK_ROW = text(
    "SELECT id, user_id, channel, kind, attempts, alert_event_ids, payload, created_at "
    "FROM notification_outbox "
    "WHERE id = :id AND tenant_id = :tenant_id AND status = 'pending' AND not_before <= now() "
    "FOR UPDATE SKIP LOCKED"
)
_SQL_SIBLINGS = text(
    "SELECT id, user_id, channel, kind, attempts, alert_event_ids, payload, created_at "
    "FROM notification_outbox "
    "WHERE tenant_id = :tenant_id AND user_id = :user_id AND channel = 'email' AND kind = 'instant' "
    "AND status = 'pending' AND not_before <= now() AND id <> :id ORDER BY not_before, id LIMIT :limit "
    "FOR UPDATE SKIP LOCKED"
)
_SQL_USER_SETTINGS = text(
    "SELECT quiet_start, quiet_end, show_amounts_email FROM notification_settings "
    "WHERE tenant_id = :tenant_id AND user_id = :user_id"
)
_SQL_SENT_RECENTLY = text(
    "SELECT count(*) AS sent, max(sent_at) AS last_sent FROM notification_outbox "
    "WHERE tenant_id = :tenant_id AND user_id = :user_id AND channel = 'email' AND kind = 'instant' "
    "AND status = 'sent' AND sent_at > :since"
)
_SQL_HOLD = text(
    "UPDATE notification_outbox SET status = 'held', not_before = COALESCE(CAST(:not_before AS timestamptz), "
    "not_before), last_error_class = :error_class WHERE id = :id AND tenant_id = :tenant_id"
)
_SQL_CLOSE = text(
    "UPDATE notification_outbox SET status = :status, last_error_class = :error_class "
    "WHERE id = ANY(:ids) AND tenant_id = :tenant_id AND status = 'pending' "
    "AND (CAST(:lease AS timestamptz) IS NULL OR not_before = CAST(:lease AS timestamptz)) RETURNING id"
)
# Sonuç yazımı kira sahipliğini denetler (`:lease`): kira başkasına geçtiyse etkisiz kalır.
_SQL_FAIL = text(
    "UPDATE notification_outbox SET status = :status, attempts = attempts + 1, not_before = :not_before, "
    "last_error_class = :error_class WHERE id = :id AND tenant_id = :tenant_id AND status = 'pending' "
    "AND (CAST(:lease AS timestamptz) IS NULL OR not_before = CAST(:lease AS timestamptz)) RETURNING id"
)
_SQL_CLAIM = text(
    "UPDATE notification_outbox SET not_before = now() + make_interval(secs => :lease) "
    "WHERE id = ANY(:ids) AND tenant_id = :tenant_id AND status = 'pending' RETURNING not_before"
)
_SQL_FAIL_UNEXPECTED = text(
    "UPDATE notification_outbox SET attempts = attempts + 1, "
    "status = CASE WHEN attempts + 1 >= :max_attempts THEN 'failed_permanent' ELSE 'failed' END, "
    "not_before = now() + make_interval(secs => :wait), last_error_class = :error_class "
    "WHERE id = ANY(:ids) AND tenant_id = :tenant_id AND status = 'pending' "
    "AND (CAST(:lease AS timestamptz) IS NULL OR not_before = CAST(:lease AS timestamptz))"
)
_SQL_EMAIL_FOR = text("SELECT notify_gate.email_for(:id)")
_SQL_TITLES = text(
    "SELECT p.title FROM alert_events e JOIN products p ON p.tenant_id = e.tenant_id "
    "AND p.marketplace_account_id = e.marketplace_account_id AND p.barcode = substring(e.subject FROM 6) "
    "WHERE e.tenant_id = :tenant_id AND e.id = ANY(:ids) AND e.scope = 'product' AND p.title IS NOT NULL "
    "ORDER BY (e.severity = 'high') DESC, e.last_seen_at DESC, e.id LIMIT 20"
)
_SQL_ACTIVE_ACCOUNTS = text(
    "SELECT tenant_id, account_id, backfilled_sources FROM sync_gate.syncable_accounts()"
)
_SQL_RECIPIENTS = text("SELECT user_id, member_role FROM notify_gate.tenant_recipients(:tenant_id)")
_SQL_DIGEST_HOURS = text(
    "SELECT user_id, digest_hour FROM notification_settings WHERE tenant_id = :tenant_id"
)
_SQL_EMAIL_PREFERENCES = text(
    "SELECT user_id, rule, mode FROM notification_preferences "
    "WHERE tenant_id = :tenant_id AND channel = 'email'"
)
_SQL_FAILED_SOURCES = text(
    "SELECT marketplace_account_id, source FROM (SELECT DISTINCT ON (marketplace_account_id, source) "
    "marketplace_account_id, source, status FROM sync_runs WHERE tenant_id = :tenant_id "
    "ORDER BY marketplace_account_id, source, started_at DESC) latest WHERE status = 'failed'"
)
_SQL_NEW_EVENTS = text(
    "SELECT id, marketplace_account_id, rule, severity, payload, data_revision, settings_revision "
    "FROM alert_events WHERE tenant_id = :tenant_id AND status = 'open' "
    "AND notify_mode IN ('normal', 'digest_only') "
    "AND first_seen_at > CAST(:at AS timestamptz) - make_interval(hours => :hours) "
    "AND first_seen_at <= CAST(:at AS timestamptz) "
    "AND rule = ANY(CAST(:rules AS text[])) ORDER BY id"
)
_SQL_EVENTS_BY_ID = text(
    "SELECT id, marketplace_account_id, rule, severity, payload, data_revision, settings_revision "
    "FROM alert_events WHERE tenant_id = :tenant_id AND status = 'open' AND id = ANY(:ids) ORDER BY id"
)
_SQL_FOLDABLE = text(
    "SELECT id, alert_event_ids FROM notification_outbox WHERE tenant_id = :tenant_id AND user_id = :user_id "
    "AND channel = 'email' AND kind = 'instant' AND status = 'held' AND last_error_class = 'rate_limited' "
    "ORDER BY created_at, id FOR UPDATE SKIP LOCKED"
)
_SQL_FOLD = text(
    "UPDATE notification_outbox SET status = 'skipped', last_error_class = 'folded_into_digest' "
    "WHERE id = ANY(:ids) AND tenant_id = :tenant_id AND status = 'held'"
)
_SQL_EXPIRE_HELD = text(
    "UPDATE notification_outbox SET status = 'skipped', last_error_class = 'held_expired' "
    "WHERE tenant_id = :tenant_id AND status = 'held' AND last_error_class = 'rate_limited' "
    "AND created_at < now() - make_interval(days => :days) RETURNING id"
)
_SQL_DIGEST_INSERT = text(
    "INSERT INTO notification_outbox (tenant_id, user_id, channel, kind, dedupe_key, alert_event_ids, "
    "payload, status, not_before) "
    "VALUES (:tenant_id, :user_id, 'email', 'digest', :dedupe_key, :alert_event_ids, "
    "CAST(:payload AS jsonb), 'pending', :not_before) "
    "ON CONFLICT ON CONSTRAINT uq_notification_outbox_dedupe DO NOTHING RETURNING id"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def error_class_name(exc: BaseException) -> str:
    """Hata SINIFININ adı (`last_error_class` CHECK: küçük harf ve alt çizgi, en çok 40). Metin taşınmaz."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z_]+", "_", snake)).strip("_")[:40] or "error"


def group_idempotency_key(ids: Sequence[UUID]) -> str:
    """Birleşik grubun idempotency anahtarı: SIRALI satır kimliklerinin özeti.

    Yeniden denemede grup aynıysa anahtar ve ileti içeriği aynıdır (sağlayıcı tekilleştirebilir); sıralamadan
    ve birincil satır seçiminden bağımsızdır."""
    return hashlib.sha256("|".join(sorted(str(i) for i in ids)).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Counters:
    """Çalıştırma sayaçları (yalnız sayı; log ve iş kaydı için)."""

    counts: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount

    def get(self, key: str) -> int:
        return self.counts.get(key, 0)

    def summary(self) -> dict[str, object]:
        return dict(sorted(self.counts.items()))


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """İşlenen outbox satırı (adres YOK)."""

    id: UUID
    user_id: UUID
    channel: str
    kind: str
    attempts: int
    alert_event_ids: tuple[UUID, ...]
    payload: dict[str, Any]
    created_at: datetime


def _row(raw: Any) -> OutboxRow:
    return OutboxRow(
        raw.id,
        raw.user_id,
        raw.channel,
        raw.kind,
        int(raw.attempts),
        tuple(raw.alert_event_ids),
        dict(raw.payload),
        raw.created_at,
    )


@dataclass(frozen=True, slots=True)
class _UserSettings:
    quiet_start: Any
    quiet_end: Any
    show_amounts_email: bool


@dataclass(frozen=True, slots=True)
class _Event:
    id: UUID
    account_id: UUID
    rule: str
    severity: str
    payload: dict[str, Any]
    data_revision: int
    settings_revision: int


def digest_payload(events: Sequence[_Event]) -> dict[str, Any]:
    """Özet satırının yükü: `_outbox_payload` (D4) ile aynı izin listeli biçim; tutarlar metindir."""
    counts: dict[str, int] = {}
    amounts: dict[str, Decimal] = {}
    certain = True
    for event in events:
        counts[event.rule] = counts.get(event.rule, 0) + 1
        if event.payload.get("certainty") != "kesin":
            certain = False
        key = _AMOUNT_KEYS.get(event.rule)
        evidence = event.payload.get("evidence")
        if key is None or not isinstance(evidence, Mapping):
            continue
        try:
            amounts[event.rule] = amounts.get(event.rule, Decimal(0)) + Decimal(str(evidence[key]))
        except (KeyError, InvalidOperation):
            continue
    payload: dict[str, Any] = {
        "rule_counts": counts,
        "event_count": len(events),
        "data_revision": max(event.data_revision for event in events),
        "settings_revision": max(event.settings_revision for event in events),
        "certainty": "kesin" if certain else "tahmini",
    }
    for rule, count in counts.items():
        entry: dict[str, Any] = {"event_count": count, "window_days": WINDOW_DAYS[AlertRule(rule)]}
        if rule in amounts:
            entry["total_amount"] = format(amounts[rule], "f")
        payload[rule] = entry
    return payload


def digest_dedupe_key(user_id: UUID, local_day: date, hour: int) -> str:
    """Özet tekilleştirme anahtarı: kullanıcı, İstanbul günü ve saat (aynı saatte ikinci kez yazılmaz)."""
    seed = f"{user_id}|email|digest|{local_day.isoformat()}|{hour}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class _LeaseLostError(Exception):
    """Sonuç yazımı tümü-ya-hiç kuralını sağlamadı (kira kısmen ya da tamamen başkasına geçti)."""


class NotificationConfigError(ValueError):
    """Bildirim yapılandırması güvensiz (yerel olmayan geliştirme kopyası, canlı arka uçsuz açık bayrak)."""


class NotificationDispatcher:
    """Outbox dağıtıcısı ve özet kurucusu (`netkar_worker` motoru; saat ve göndericiler dışarıdan verilir)."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        sender: EmailSender | None,
        enabled: bool,
        product_name: str,
        web_base_url: str,
        signer: UnsubscribeSigner,
        dev_sender: EmailSender | None = None,
        now: Callable[[], datetime] = _utcnow,
        send_timeout: float = SEND_TIMEOUT_SECONDS,
        daily_limit: int = EMAIL_INSTANT_DAILY_LIMIT,
        min_gap: timedelta = MIN_INSTANT_GAP,
        max_runtime: float = DISPATCH_BUDGET_SECONDS,
    ) -> None:
        # Bayrak kapalıyken gönderim yapısal olarak imkânsız (ADR-0009 §7.1): geliştirme kopyası yalnız
        # yerel arka uca (ağa çıkmayan) yazılabilir; bayrak açıkken yerel gönderici "gerçek" yerine geçemez
        # (staging'de sahte `sent` olmasın).
        if dev_sender is not None and not is_local_sender(dev_sender):
            raise NotificationConfigError("dev_sender yerel (file/memory) olmalı")
        if enabled and (sender is None or is_local_sender(sender)):
            raise NotificationConfigError(
                "ALERT_NOTIFICATIONS_ENABLED açıkken gerçek (yerel olmayan) bir e-posta arka ucu gerekir"
            )
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
        self._sender = sender
        self._dev_sender = dev_sender
        self._enabled = enabled
        self._product_name = product_name
        self._base = web_base_url.rstrip("/")
        self._signer = signer
        self._now = now
        self._send_timeout = send_timeout
        self._daily_limit = daily_limit
        self._min_gap = min_gap
        self._max_runtime = max_runtime

    @classmethod
    def from_settings(
        cls,
        engine: AsyncEngine,
        settings: Settings,
        *,
        live_sender: EmailSender | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> NotificationDispatcher:
        """Üretim yolu: bayrak, ürün adı, bağlantı kökü ve imza anahtarı ayarlardan gelir.

        Geliştirme kopyası HER ZAMAN `build_local_email_sender` ile (file/memory) kurulur. Gerçek sağlayıcı
        (H5/K12) henüz yoktur: `live_sender` verilmezse bayrak açık yapılandırma kurucuda reddedilir.
        """
        return cls(
            engine,
            sender=live_sender,
            dev_sender=build_local_email_sender(settings),
            enabled=settings.alert_notifications_enabled,
            product_name=settings.product_name,
            web_base_url=settings.web_base_url,
            signer=UnsubscribeSigner.from_settings(settings),
            now=now,
        )

    # ------------------------------------------------------------------------------- dispatch
    async def dispatch(self, *, batch: int = DISPATCH_BATCH) -> Counters:
        """Zamanı gelen outbox satırlarını işler (bırakma, kapılar, birleştirme, gönderim)."""
        result = Counters()
        deadline = monotonic.monotonic() + self._max_runtime
        await self._release_ready(result, batch)
        for _ in range(MAX_DISPATCH_ROUNDS):
            due = await self._listing(_SQL_DUE, batch)
            if not due:
                break
            progressed = False
            for outbox_id, tenant_id in due:
                if monotonic.monotonic() > deadline:  # toplam süre sınırı: kalanlar sonraki tike
                    result.bump("budget_exhausted")
                    logger.warning("notify_dispatch_budget_exhausted", extra=dict(result.counts))
                    return result
                claim: dict[str, Any] = {}
                try:
                    progressed |= await self._process(tenant_id, outbox_id, result, claim)
                except Exception as exc:
                    result.bump("errors")
                    logger.error("notify_dispatch_row_failed", extra={"error_class": type(exc).__name__})
                    # Kiralanmış grubun TÜM satırları (yoksa yalnız bu satır) ve kira sahipliğiyle kaydedilir.
                    await self._record_unexpected(
                        tenant_id, claim.get("ids", [outbox_id]), claim.get("lease"), exc
                    )
            if not progressed or len(due) < batch:
                break
        logger.info("notify_dispatch_done", extra=dict(result.counts))
        return result

    async def _listing(self, statement: Any, batch: int) -> list[tuple[UUID, UUID]]:
        async with self._sessions() as session:
            rows = (await session.execute(statement, {"limit": batch})).all()
            await session.rollback()
        return [(UUID(str(r[0])), UUID(str(r[1]))) for r in rows]

    async def _release_ready(self, result: Counters, batch: int) -> None:
        """Zamanı gelmiş `held` ve `failed` satırları `pending`'e çevirir (satır başına hata yalıtımlı)."""
        for outbox_id, tenant_id in await self._listing(_SQL_RELEASABLE, batch):
            try:
                async with tenant_transaction(self._sessions, tenant_id) as session:
                    released = (
                        await session.execute(_SQL_RELEASE, {"id": outbox_id, "tenant_id": tenant_id})
                    ).all()
            except Exception as exc:
                result.bump("errors")
                logger.error("notify_release_row_failed", extra={"error_class": type(exc).__name__})
                continue
            result.bump("released", len(released))

    async def _record_unexpected(
        self, tenant_id: UUID, ids: Sequence[UUID], lease: datetime | None, exc: BaseException
    ) -> None:
        """Beklenmeyen hata: satır AYRI işlemde `attempts + 1` ve `failed` olur (6. denemede kalıcı);
        böylece sürekli hata veren satır sınırsız `pending` kalıp her dakika denenmez."""
        try:
            async with tenant_transaction(self._sessions, tenant_id) as session:
                await session.execute(
                    _SQL_FAIL_UNEXPECTED,
                    {
                        "ids": list(ids),
                        "lease": lease,
                        "tenant_id": tenant_id,
                        "max_attempts": MAX_ATTEMPTS,
                        "wait": BACKOFF_SECONDS[2],
                        "error_class": error_class_name(exc),
                    },
                )
        except Exception as inner:
            logger.error("notify_failure_not_recorded", extra={"error_class": type(inner).__name__})

    async def _process(
        self, tenant_id: UUID, outbox_id: UUID, result: Counters, claim: dict[str, Any] | None = None
    ) -> bool:
        """Üç aşama: (1) işlem: kilitle, kapılar, alıcıyı çöz, iletiyi kur, satırları KİRALA ve commit et;
        (2) işlem DIŞINDA gönder (`idempotency_key` = grup kimliklerinin sıralı özeti, toplam süre sınırlı);
        (3) işlem: sonucu YALNIZ kirayı hâlâ tutuyorsak yaz (grubun tüm satırlarına).
        Satır ele alındıysa True.

        `claim`: aşama 1 sonrası kiralanan satır kimlikleri ve kira zamanı (beklenmeyen hatada kaydı için)."""
        handled, outgoing = await self._prepare(tenant_id, outbox_id, result)
        if outgoing is None:
            return handled
        rows, message, lease = outgoing
        if claim is not None:
            claim.update(ids=[r.id for r in rows], lease=lease)
        sender = self._sender
        assert sender is not None  # bayrak açıkken kurucu gerçek göndericiyi şart koşar
        error: Exception | None = None
        try:
            await asyncio.wait_for(
                sender.send(message, idempotency_key=group_idempotency_key([r.id for r in rows])),
                self._send_timeout,
            )
        except Exception as exc:
            error = exc
        # Sonuç yazımı TÜMÜ YA DA HİÇ: grubun her satırı kirayla yazılamadıysa (kira kısmen başkasına
        # geçti) işlem
        # geri alınır ve grup olduğu gibi kalır (kiralı `pending`; kira dolunca bütün olarak yeniden denenir).
        outcome = Counters()
        try:
            async with tenant_transaction(self._sessions, tenant_id) as session:
                if error is not None:
                    written = await self._fail(session, tenant_id, rows, error, outcome, lease)
                else:
                    written = await self._close(session, tenant_id, rows[:1], "sent", None, outcome, lease)
                    if len(rows) > 1:
                        written += await self._close(
                            session, tenant_id, rows[1:], "skipped", "merged", outcome, lease
                        )
                if written != len(rows):
                    raise _LeaseLostError
        except _LeaseLostError:
            result.bump("lease_lost", len(rows))
            logger.warning("notify_lease_lost", extra={"rows": len(rows)})
            return True
        for key, count in outcome.counts.items():
            result.bump(key, count)
        return True

    async def _prepare(
        self, tenant_id: UUID, outbox_id: UUID, result: Counters
    ) -> tuple[bool, tuple[list[OutboxRow], EmailMessage, datetime] | None]:
        """Gönderim öncesi aşama (tek işlem). (ele alındı, gönderilecek (satırlar, ileti) ya da None)."""
        async with tenant_transaction(self._sessions, tenant_id) as session:
            locked = (await session.execute(_SQL_LOCK_ROW, {"id": outbox_id, "tenant_id": tenant_id})).first()
            if locked is None:  # başka dağıtıcı aldı ya da durumu değişti
                return False, None
            row = _row(locked)
            if row.channel != "email":
                await self._close(session, tenant_id, [row], "suppressed", "push_not_available", result)
                return True, None
            prefs = await self._user_settings(session, tenant_id, row.user_id)
            group = [row]
            if self._enabled and row.kind == "instant":
                now = self._now()
                until = quiet_until(now, prefs.quiet_start, prefs.quiet_end)
                if until is not None:
                    await self._hold(session, tenant_id, row, until, None, result)
                    return True, None
                if await self._rate_limited(session, tenant_id, row.user_id, now):
                    await self._hold(session, tenant_id, row, None, RATE_LIMITED, result)
                    return True, None
            if row.kind == "instant":
                group += await self._siblings(session, tenant_id, row)
            # Belirlenimci grup: kimliğe göre sıralı (anahtar ve içerik yeniden denemede aynı).
            group.sort(key=lambda r: str(r.id))
            address = (await session.execute(_SQL_EMAIL_FOR, {"id": row.id})).scalar_one_or_none()
            if address is None:
                await self._close(session, tenant_id, group, "skipped", "recipient_unavailable", result)
                return True, None
            message = await self._compose(session, tenant_id, str(address), group, prefs)
            if not self._enabled:
                if self._dev_sender is not None:
                    try:
                        await self._dev_sender.send(message, idempotency_key=str(row.id))
                    except Exception as exc:  # yerel kopya en iyi çaba: satır yine bastırılır
                        logger.warning("notify_dev_copy_failed", extra={"error_class": type(exc).__name__})
                await self._close(session, tenant_id, group, "suppressed", None, result)
                return True, None
            claimed = (
                await session.execute(
                    _SQL_CLAIM,
                    {"ids": [r.id for r in group], "tenant_id": tenant_id, "lease": SEND_LEASE_SECONDS},
                )
            ).all()
            if not claimed:  # kilitliyken kiralanamaması beklenmez; güvenli taraf: gönderme
                return True, None
            return True, (group, message, claimed[0][0])

    # ------------------------------------------------------------------------------- yardımcılar
    async def _user_settings(self, session: AsyncSession, tenant_id: UUID, user_id: UUID) -> _UserSettings:
        found = (
            await session.execute(_SQL_USER_SETTINGS, {"tenant_id": tenant_id, "user_id": user_id})
        ).first()
        if found is None:
            return _UserSettings(DEFAULT_QUIET_START, DEFAULT_QUIET_END, True)
        return _UserSettings(found.quiet_start, found.quiet_end, bool(found.show_amounts_email))

    async def _rate_limited(
        self, session: AsyncSession, tenant_id: UUID, user_id: UUID, now: datetime
    ) -> bool:
        """Kullanıcı başına günlük anlık e-posta sınırı ya da iki anlık arası asgari süre aşıldı mı."""
        found = (
            await session.execute(
                _SQL_SENT_RECENTLY,
                {"tenant_id": tenant_id, "user_id": user_id, "since": now - timedelta(hours=24)},
            )
        ).one()
        if int(found.sent) >= self._daily_limit:
            return True
        return found.last_sent is not None and found.last_sent > now - self._min_gap

    async def _siblings(self, session: AsyncSession, tenant_id: UUID, row: OutboxRow) -> list[OutboxRow]:
        """Aynı kullanıcıya zamanı gelmiş diğer anlık e-postalar (tek iletide birleşir)."""
        rows = (
            await session.execute(
                _SQL_SIBLINGS,
                {"tenant_id": tenant_id, "user_id": row.user_id, "id": row.id, "limit": MAX_MERGED_ROWS},
            )
        ).all()
        return [_row(r) for r in rows]

    async def _hold(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        row: OutboxRow,
        not_before: datetime | None,
        error_class: str | None,
        result: Counters,
    ) -> None:
        await session.execute(
            _SQL_HOLD,
            {"id": row.id, "tenant_id": tenant_id, "not_before": not_before, "error_class": error_class},
        )
        result.bump("held" if error_class is None else "held_rate_limited")

    async def _close(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        rows: Sequence[OutboxRow],
        status: str,
        error_class: str | None,
        result: Counters,
        lease: datetime | None = None,
    ) -> int:
        """Satırları kapatır; YAZILAN satır sayısını verir (kira sahipliği tutmayan satır yazılmaz)."""
        written = (
            await session.execute(
                _SQL_CLOSE,
                {
                    "ids": [r.id for r in rows],
                    "tenant_id": tenant_id,
                    "status": status,
                    "error_class": error_class,
                    "lease": lease,
                },
            )
        ).all()
        result.bump(status, len(written))
        if status == "skipped" and error_class == "merged":
            result.bump("merged", len(written))
        return len(written)

    async def _fail(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        rows: Sequence[OutboxRow],
        exc: BaseException,
        result: Counters,
        lease: datetime | None = None,
    ) -> int:
        """Gönderim hatası: kalıcı ya da 6. hata `failed_permanent`, aksi halde `failed` + üstel bekleme.

        Grubun TÜM satırları aynı `not_before` ile yazılır (en yüksek deneme sayısına göre bekleme): yeniden
        denemede birlikte bırakılır ve aynı grubu oluşturur."""
        permanent = isinstance(exc, EmailPermanentError)
        error_class = error_class_name(exc)
        now = self._now()
        top = max(row.attempts for row in rows) + 1
        not_before = now + timedelta(seconds=BACKOFF_SECONDS[min(top, len(BACKOFF_SECONDS)) - 1])
        total = 0
        for row in rows:
            final = permanent or row.attempts + 1 >= MAX_ATTEMPTS
            written = (
                await session.execute(
                    _SQL_FAIL,
                    {
                        "id": row.id,
                        "tenant_id": tenant_id,
                        "status": "failed_permanent" if final else "failed",
                        "not_before": not_before,
                        "error_class": error_class,
                        "lease": lease,
                    },
                )
            ).all()
            if written:
                total += 1
                result.bump("failed_permanent" if final else "failed")
        logger.warning("notify_send_failed", extra={"error_class": error_class, "permanent": permanent})
        return total

    async def _compose(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        address: str,
        group: Sequence[OutboxRow],
        prefs: _UserSettings,
    ) -> EmailMessage:
        """Satır(lar)dan iletiyi kurar. Adres yalnız `EmailMessage.to`'ya girer (başka hiçbir yere)."""
        primary = group[0]
        payload = group[0].payload if len(group) == 1 else merge_payloads([r.payload for r in group])
        lines, estimated, revision = lines_from_payload(payload)
        event_ids = sorted({i for r in group for i in r.alert_event_ids}, key=str)[:MAX_EVENT_IDS]
        titles: list[str] = []
        if event_ids:
            for (raw_title,) in (
                await session.execute(_SQL_TITLES, {"tenant_id": tenant_id, "ids": event_ids})
            ).all():
                title = clean_title(str(raw_title))
                if title and title not in titles:
                    titles.append(title)
        # Token zamanı belirlenimcidir (grubun en eski oluşturulma zamanı): içerik yeniden denemede aynı.
        now = min(r.created_at for r in group)
        links = {
            line.rule: f"{self._base}{UNSUBSCRIBE_PAGE_PATH}?token="
            f"{self._signer.sign(primary.user_id, tenant_id, line.rule, 'email', now)}"
            for line in lines
        }
        # Tek tık başlığı: özet tüm kuralları (`*`), tek kurallı anlık ileti yalnız o kuralı kapatır; çok
        # kurallı anlık iletide başlık YOKTUR (gövdedeki kural başına bağlantılar kalır).
        one_click_rule = (
            ALL_RULES if primary.kind == "digest" else (lines[0].rule if len(lines) == 1 else None)
        )
        one_click = (
            None
            if one_click_rule is None
            else f"{self._base}{UNSUBSCRIBE_API_PATH}?token="
            f"{self._signer.sign(primary.user_id, tenant_id, one_click_rule, 'email', now)}"
        )
        rendered = render_email(
            RenderContext(
                product_name=self._product_name,
                kind=primary.kind,
                lines=lines,
                titles=tuple(titles),
                show_amounts=prefs.show_amounts_email,
                estimated=estimated,
                settings_revision=revision,
                panel_url=f"{self._base}{PANEL_PATH}",
                settings_url=f"{self._base}{SETTINGS_PATH}",
                unsubscribe_links=links,
                one_click_url=one_click,
            )
        )
        return EmailMessage(
            to=address,
            subject=rendered.subject,
            body=rendered.text,
            html=rendered.html,
            headers=dict(rendered.headers),
        )

    # ------------------------------------------------------------------------------- özet
    async def build_digests(self, *, at: datetime | None = None) -> Counters:
        """Özet saati (İstanbul) gelen kullanıcılar için özet satırı yazar; yeni olay yoksa yazmaz.

        `at`: periyodik görevin ZAMANLANMIŞ tik zamanı (`timestamp` argümanı). Worker geç çalışsa da o saatin
        kullanıcıları atlanmaz; verilmezse şimdiki zaman kullanılır.
        """
        result = Counters()
        now = at if at is not None else self._now()
        local = now.astimezone(LOCAL_TZ)
        by_tenant: dict[UUID, dict[UUID, frozenset[str]]] = {}
        async with self._sessions() as session:
            accounts = (await session.execute(_SQL_ACTIVE_ACCOUNTS)).all()
            await session.rollback()
        for tenant_id, account_id, backfilled in accounts:
            by_tenant.setdefault(UUID(str(tenant_id)), {})[UUID(str(account_id))] = frozenset(backfilled)
        for tenant_id, active in by_tenant.items():
            try:
                await self._digests_for_tenant(tenant_id, active, local, now, result)
            except Exception as exc:
                result.bump("errors")
                logger.error("notify_digest_tenant_failed", extra={"error_class": type(exc).__name__})
        logger.info("notify_digests_done", extra=dict(result.counts))
        return result

    async def _digests_for_tenant(
        self,
        tenant_id: UUID,
        active: Mapping[UUID, frozenset[str]],
        local: datetime,
        at: datetime,
        result: Counters,
    ) -> None:
        params: dict[str, Any] = {"tenant_id": tenant_id}
        async with tenant_transaction(self._sessions, tenant_id) as session:
            expired = (await session.execute(_SQL_EXPIRE_HELD, {**params, "days": HELD_EXPIRY.days})).all()
            result.bump("expired", len(expired))
            # Alıcılar ÜYELERDEN kurulur (rol `memberships`'ten, `notify_gate` ile).
            # Özet saati ayar satırından;
            # satır yoksa varsayılan 08.
            members = (await session.execute(_SQL_RECIPIENTS, params)).all()
            hours = {
                r.user_id: int(r.digest_hour)
                for r in (await session.execute(_SQL_DIGEST_HOURS, params)).all()
            }
            due_users = [
                (r.user_id, str(r.member_role))
                for r in members
                if hours.get(r.user_id, DEFAULT_DIGEST_HOUR) == local.hour
            ]
            if not due_users:
                return
            failed: dict[UUID, set[str]] = {}
            for account_id, source in (await session.execute(_SQL_FAILED_SOURCES, params)).all():
                failed.setdefault(account_id, set()).add(source)
            blocked = {
                account_id: blocked_rules(backfilled, failed.get(account_id, ()))
                for account_id, backfilled in active.items()
            }
            modes = {
                (r.user_id, r.rule): r.mode
                for r in (await session.execute(_SQL_EMAIL_PREFERENCES, params)).all()
            }
            for user_id, role in due_users:
                result.bump("users_due")
                defaults = default_matrix(role)  # D6 ile TEK işlev: viewer e-posta off, owner/admin özet
                rules = [
                    rule
                    for rule in _RULE_VALUES
                    if modes.get((user_id, rule), defaults[rule]["email"]) == "digest"
                ]
                await self._digest_for_user(session, tenant_id, user_id, rules, blocked, local, at, result)

    async def _digest_for_user(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID,
        rules: Sequence[str],
        blocked: Mapping[UUID, frozenset[AlertRule]],
        local: datetime,
        at: datetime,
        result: Counters,
    ) -> None:
        events: dict[UUID, _Event] = {}
        if rules:
            fresh = (
                await session.execute(
                    _SQL_NEW_EVENTS,
                    {"tenant_id": tenant_id, "hours": DIGEST_WINDOW_HOURS, "rules": list(rules), "at": at},
                )
            ).all()
            for r in fresh:
                # O-a: hesap etkin olmalı ve kuralın kendi kaynağı bozuk olmamalı.
                if (
                    r.marketplace_account_id in blocked
                    and AlertRule(r.rule) not in blocked[r.marketplace_account_id]
                ):
                    events[r.id] = _event(r)
        foldable = (await session.execute(_SQL_FOLDABLE, {"tenant_id": tenant_id, "user_id": user_id})).all()
        fold_event_ids = list(dict.fromkeys(i for r in foldable for i in r.alert_event_ids))
        if fold_event_ids:
            for r in (
                await session.execute(_SQL_EVENTS_BY_ID, {"tenant_id": tenant_id, "ids": fold_event_ids})
            ).all():
                events.setdefault(r.id, _event(r))
        if not events:  # yeni olay yok: ileti yok
            return
        ordered = sorted(events.values(), key=lambda e: (e.severity != "high", str(e.id)))
        inserted = (
            await session.execute(
                _SQL_DIGEST_INSERT,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "dedupe_key": digest_dedupe_key(user_id, local.date(), local.hour),
                    "alert_event_ids": [e.id for e in ordered[:MAX_EVENT_IDS]],
                    "payload": json.dumps(digest_payload(ordered)),
                    "not_before": self._now(),
                },
            )
        ).scalar_one_or_none()
        if inserted is None:  # bu saat için özet zaten yazılmış
            return
        result.bump("digests")
        if foldable:
            await session.execute(_SQL_FOLD, {"tenant_id": tenant_id, "ids": [r.id for r in foldable]})
            result.bump("folded", len(foldable))


def _event(raw: Any) -> _Event:
    return _Event(
        raw.id,
        raw.marketplace_account_id,
        raw.rule,
        raw.severity,
        dict(raw.payload),
        int(raw.data_revision),
        int(raw.settings_revision),
    )
