"""Uyarı değerlendirme işi (ADR-0009 D4, §6.2): hesap başına, idempotent, tek işlemde yazan akış.

Akış (`AlertEvaluator.evaluate`):

1. Hesabın kiracısı `sync_gate` ile çözülür (etkin değilse iş yok).
2. OKUMA AŞAMASI (yazma yok): veri sürümü (`report_data_revisions`) ve ayar sürümü (K44) motor girdisi
   okunmadan ÖNCE okunur; kiracı eşik ezmesi (`alert_rule_settings`) okunur; değerlendirme anahtarı kurulur
   ve `alert_evaluations`'ta varsa iş biter (ucuz yol: motor çalışmaz). Yoksa motor, mevcut besleyici ve rapor
   yolundan (`period_profit`; yeni hesap yazılmaz) 7 ve 92 günlük dönemle çalışır, iade kohortu
   (`load_return_cohorts`) yüklenir ve saf kurallar (`app.alerts`) aday listesini üretir.
3. YAZMA AŞAMASI (TEK işlem, `netkar_worker` rolü): değerlendirme satırı `ON CONFLICT DO NOTHING` ile eklenir
   (eklenmediyse iş biter); adaylar `dedupe_key` ile olaya yazılır (yeni açılış, güncelleme, yeniden açılma);
   durum değişikliği YALNIZ `alert_event_transitions` INSERT ile yapılır (sistem aktörü); bastırma kararları
   `app.alerts.suppression` ile verilir; koşulu kalkan olaylar `resolved` olur; bildirim gerekenler için
   `notification_outbox` satırı yazılır (adres YOK; gönderim D5'in işidir); değerlendirme `succeeded` ile
   kapanır.
4. Hata olursa yazma işlemi tümüyle geri alınır (kısmi olay ya da outbox satırı kalmaz) ve AYRI bir işlemde
   değerlendirme `failed` olarak kaydedilir; ardından hata yeniden fırlatılır.

Değerlendirme anahtarı: (hesap, İstanbul günü, veri sürümü, ayar sürümü, kural sürümü). Ayar sürümü, motor
ayarının K44 sürümü ile kiracı eşik ezmesinin (`alert_rule_settings`, sürüm sayacı olmayan bir tablo) içerik
özetinin birleşimidir (`composite_settings_revision`): eşik değişince aynı gün ve aynı veriyle yeniden
değerlendirilir, içerik aynıysa değerlendirilmez. Olayların `settings_revision` damgası YALNIZ K44
sürümüdür (e-posta özeti ve panel için).

Kapanış kuralı (bilinen sınır): `failed` ile kapanmış bir anahtar aynı anahtarla yeniden denenemez (tablo
kapanmış satırı değiştirmez ve `UNIQUE` anahtar yeniden eklemeyi engeller). Yeniden değerlendirme sonraki
veri sürümünde, ayar değişiminde ya da ertesi gün olur.

Reklam kuralı: reklam verisi tablosu yoktur (D9); besleyici `ad_records` vermez. Kural "veri yok" sayılır,
uyarı üretilmez ve 30 günlük motor çalışması yapılmaz.

Bildirim bastırma (O-a, D5'te daraltıldı): kuralın KENDİ veri kaynağı başarısız ya da yedeklemesi eksikse
o kuralın bildirimi bastırılır (`RULE_SOURCES`, `blocked_rules`); olay yine açılır. Başka kaynağın hatası
etkilemez.

Bildirim notu: olay bildirime uygunsa (`notified` sayacı) `last_notified_at` yazılır; alıcı seçen kullanıcı
yoksa outbox satırı yazılmaz. Günlük özet satırlarını D5 olaylardan kurar, burada yazılmaz.

Log: yalnız hesap kimliği, sayaçlar ve süre. Barkod, sipariş numarası, tutar, e-posta YOK (G09).
SQL: yalnız düz sabit dizge ve bağlı parametre (f-string ve birleştirme yok).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time as monotonic
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from sqlalchemy import exc as sa_exc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.alerts import (
    AlertCandidate,
    AlertRule,
    AlertThresholds,
    NotifyMode,
    RuleOutcome,
    RuleStatus,
    Severity,
    evaluate_loss_making_sales,
    evaluate_return_rate,
    evaluate_unexpected_deduction,
    loss_notification_due,
    reminder_due,
    reopen_is_silent,
)
from app.alerts.stats import CURRENT_WINDOW_DAYS
from app.db.rls import set_rls_context, tenant_transaction
from app.profit.enums import Certainty
from app.profit.schema_v1 import ISTANBUL
from app.services.alert_inputs import AccountReturnCounts, ReturnCohortSet, load_return_cohorts
from app.services.profit_report import PeriodReport, period_profit
from app.services.profit_settings import load_profit_settings
from app.services.report_cache import report_data_version
from app.services.sync.sources import SOURCE_ORDER

logger = logging.getLogger("netkar.alerts")

# Kural sürümü: `alert_evaluations.rules_version` ve `alert_events.payload_version` (bilinmeyen sürümü
# veritabanı reddeder; kural kanıt alanları değişirse yeni sürüm = yeni migrasyon).
RULES_VERSION = 1

# Dönem uzunlukları (İstanbul günü, bugün dahil; ADR-0009 §3). Reklam dönemi (30 gün) D9'da kullanılır.
LOSS_PERIOD_DAYS = 7
DEDUCTION_PERIOD_DAYS = 92
AD_PERIOD_DAYS = 30

# Değerlendirme kapsamı: `all` tüm kurallar; `fast` yalnız 7 günlük zarar ve (SQL tabanlı) iade kuralı.
# 92 günlük kesinti kuralı (pahalı motor çalışması) yalnız finans senkronu sonrası, günlük işte ve
# ayar/maliyet yazımında çalışır.
SCOPE_ALL = "all"
SCOPE_FAST = "fast"
SCOPE_RULES: dict[str, frozenset[str]] = {
    SCOPE_ALL: frozenset(rule.value for rule in AlertRule),
    SCOPE_FAST: frozenset({AlertRule.LOSS_MAKING_SALE.value, AlertRule.RETURN_RATE_INCREASE.value}),
}

# Bir outbox satırının taşıyabileceği olay sayısı (`alert_event_ids` CHECK <= 500); fazlası parçalara bölünür.
MAX_EVENT_IDS_PER_OUTBOX_ROW = 500
# Aynı anahtar için en çok bu kadar deneme (`alert_evaluations.attempt`, migrasyon 0026).
MAX_ATTEMPTS = 3

# ADR-0009 §10.1 (bildirim taşkını): hesap başına günlük en çok bu kadar YENİ olay açılır.
MAX_NEW_EVENTS_PER_DAY = 500

# O-a (ADR-0009 D4 açık maddesi, D5 ile daraltıldı): bildirim, YALNIZ ilgili kuralın veri kaynağı
# başarısızsa ya da yedeklemesi (backfill) eksikse bastırılır; başka kaynağın hatası bu kuralın bildirimini
# engellemez. Olay her durumda açılır, yalnız outbox (anlık bildirim) ve günlük özet bastırılır. Kaynak adları
# `SOURCE_ORDER` ile (sync_runs.source CHECK'i) aynıdır; her kuralın girdisi besleyici kodundan çıkarılmıştır:
# - ZARARINA_SATIS: satır kârı (siparişler, ekstre, diğer finansal kayıtlar, kargo faturaları) ve satırın iade
#   adedi (`claims`: iadeli satır kural dışıdır, iade kaydı eksikse zarar yanlış görünür).
# - BEKLENMEYEN_KESINTI: tahmin ile gerçekleşen kesinti karşılaştırması: siparişler ve tüm finans kaynakları.
#   İade kaydı kullanılmaz.
# - IADE_ORANI_ARTISI: yalnız sipariş satırı kohortu ve iade kayıtları (`alert_inputs`); finans yok.
# - REKLAM_KARI_YIYOR: reklam verisi senkron kaynağı değildir (D9, Excel/elle giriş): sinyal zaten üretilmez.
# `products` hiçbir kuralın bastırma girdisi DEĞİLDİR: katalog yalnız varsayılan oran/desi ve başlık verir;
# eksikliği tahmini etiketler, yanlış olay üretmez.
RULE_SOURCES: dict[AlertRule, frozenset[str]] = {
    AlertRule.LOSS_MAKING_SALE: frozenset(
        {"orders", "claims", "settlements", "other_financials", "cargo_invoices"}
    ),
    AlertRule.UNEXPECTED_DEDUCTION: frozenset(
        {"orders", "settlements", "other_financials", "cargo_invoices"}
    ),
    AlertRule.RETURN_RATE_INCREASE: frozenset({"orders", "claims"}),
    AlertRule.AD_EATS_PROFIT: frozenset(),
}

# Kural başına bildirim penceresi (outbox yükü, panel metni için).
WINDOW_DAYS = {
    AlertRule.LOSS_MAKING_SALE: LOSS_PERIOD_DAYS,
    AlertRule.AD_EATS_PROFIT: AD_PERIOD_DAYS,
    AlertRule.UNEXPECTED_DEDUCTION: DEDUCTION_PERIOD_DAYS,
    AlertRule.RETURN_RATE_INCREASE: CURRENT_WINDOW_DAYS,
}

# ADR-0009 §8.1 varsayılan matris: yalnız ANLIK bildirimler outbox'a yazılır; e-posta varsayılanı günlük
# özettir (özeti D5 `notify.build_digests` olaylardan kurar). Push varsayılanı yalnız bu iki kuralda anlıktır.
DEFAULT_PUSH_INSTANT = frozenset({AlertRule.LOSS_MAKING_SALE, AlertRule.UNEXPECTED_DEDUCTION})
DEFAULT_QUIET_START = time(22, 0)
DEFAULT_QUIET_END = time(8, 0)

try:
    _LOCAL_TZ: ZoneInfo | Any = ZoneInfo("Europe/Istanbul")
except (
    ZoneInfoNotFoundError
):  # pragma: no cover - tzdata'sız çalışma ortamı: Türkiye'de yaz saati yok (UTC+3)
    _LOCAL_TZ = ISTANBUL

EvaluationStatus = Literal["succeeded", "skipped", "inactive"]

# --------------------------------------------------------------------------- SQL (düz sabit dizgeler)
_SQL_THRESHOLDS = text(
    "SELECT loss_min_amount, ad_share_percent, ad_min_spend, deduction_notify_min, return_min_diff_points, "
    "rules_enabled, updated_at FROM alert_rule_settings "
    "WHERE tenant_id = :tenant_id AND marketplace_account_id = :account_id"
)
_SQL_EVALUATION_ATTEMPTS = text(
    "SELECT status, attempt FROM alert_evaluations "
    "WHERE marketplace_account_id = :account_id AND as_of_date = :as_of "
    "AND data_revision = :data_revision AND settings_revision = :settings_revision "
    "AND rules_version = :rules_version"
)
_SQL_EVALUATION_INSERT = text(
    "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, "
    "settings_revision, rules_version, attempt) "
    "VALUES (:tenant_id, :account_id, :as_of, :data_revision, :settings_revision, :rules_version, :attempt) "
    "ON CONFLICT ON CONSTRAINT uq_alert_evaluations_key DO NOTHING RETURNING id"
)
_SQL_EVALUATION_CLOSE = text(
    "UPDATE alert_evaluations SET status = :status, counts = CAST(:counts AS jsonb) "
    "WHERE id = :id AND tenant_id = :tenant_id"
)
_SQL_DB_NOW = text("SELECT now()")
_SQL_EVENTS = text(
    "SELECT id, dedupe_key, rule, status, muted_until, resolved_at, last_notified_at, notified_amount, "
    "renotified FROM alert_events WHERE tenant_id = :tenant_id AND marketplace_account_id = :account_id "
    "ORDER BY id FOR UPDATE"
)
_SQL_NEW_TODAY = text(
    "SELECT count(*) FROM alert_events WHERE tenant_id = :tenant_id AND marketplace_account_id = :account_id "
    "AND first_seen_at >= :since"
)
_SQL_EVENT_INSERT = text(
    "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, "
    "last_seen_at, occurrence_count, severity, payload, payload_version, data_revision, settings_revision, "
    "last_notified_at, notified_amount, renotified, notify_mode) "
    "VALUES (:tenant_id, :account_id, :rule, :scope, :subject, :dedupe_key, now(), 1, :severity, "
    "CAST(:payload AS jsonb), :payload_version, :data_revision, :settings_revision, :last_notified_at, "
    ":notified_amount, :renotified, :notify_mode) RETURNING id"
)
_SQL_EVENT_UPDATE = text(
    "UPDATE alert_events SET last_seen_at = now(), occurrence_count = occurrence_count + 1, "
    "severity = :severity, payload = CAST(:payload AS jsonb), payload_version = :payload_version, "
    "data_revision = :data_revision, settings_revision = :settings_revision, "
    "last_notified_at = :last_notified_at, notified_amount = :notified_amount, renotified = :renotified, "
    "notify_mode = :notify_mode WHERE id = :id AND tenant_id = :tenant_id"
)
_SQL_TRANSITION = text(
    "INSERT INTO alert_event_transitions (tenant_id, alert_event_id, to_status, muted_until) "
    "VALUES (:tenant_id, :event_id, :to_status, NULL)"
)
_SQL_PUSH_USERS = text(
    "SELECT DISTINCT user_id FROM push_subscriptions WHERE tenant_id = :tenant_id AND revoked_at IS NULL"
)
_SQL_PREFERENCES = text(
    "SELECT user_id, rule, channel, mode FROM notification_preferences WHERE tenant_id = :tenant_id"
)
_SQL_QUIET_HOURS = text(
    "SELECT user_id, quiet_start, quiet_end FROM notification_settings WHERE tenant_id = :tenant_id"
)
_SQL_OUTBOX_INSERT = text(
    "INSERT INTO notification_outbox (tenant_id, user_id, channel, kind, dedupe_key, alert_event_ids, "
    "payload, status, not_before) "
    "VALUES (:tenant_id, :user_id, :channel, 'instant', :dedupe_key, :alert_event_ids, "
    "CAST(:payload AS jsonb), :status, :not_before) "
    "ON CONFLICT ON CONSTRAINT uq_notification_outbox_dedupe DO NOTHING RETURNING id"
)
_SQL_RESOLVE_TENANT = text(
    "SELECT tenant_id, backfilled_sources FROM sync_gate.syncable_accounts(:account_id)"
)
_SQL_FAILED_SOURCES = text(
    "SELECT source FROM (SELECT DISTINCT ON (source) source, status FROM sync_runs "
    "WHERE marketplace_account_id = :account_id ORDER BY source, started_at DESC) latest "
    "WHERE status = 'failed'"
)
_SQL_ADVISORY_LOCK = text("SELECT pg_advisory_xact_lock(hashtext('alerts:' || CAST(:account_id AS text)))")


# --------------------------------------------------------------------------- anahtar ve yük yardımcıları
@dataclass(frozen=True, slots=True)
class EvaluationKey:
    """Değerlendirme anahtarı (hesap dışında): gün, veri sürümü, ayar sürümü, kural sürümü."""

    as_of: date
    data_revision: int
    settings_revision: int
    thresholds_digest: int
    rules_version: int = RULES_VERSION

    @property
    def stored_settings_revision(self) -> int:
        """`alert_evaluations.settings_revision` sütununa yazılan birleşik değer."""
        return composite_settings_revision(self.settings_revision, self.thresholds_digest)

    def outbox_seed(self, account_id: UUID) -> str:
        """Outbox tekilleştirme anahtarının değerlendirmeye bağlı kısmı."""
        return (
            f"{account_id}|{self.as_of.isoformat()}|{self.data_revision}|{self.stored_settings_revision}"
            f"|{self.rules_version}"
        )


def composite_settings_revision(profit_revision: int, thresholds_digest: int) -> int:
    """K44 ayar sürümü (üst bitler) ve eşik özeti (alt 31 bit): bigint sütuna sığar, çakışma yok."""
    if not 0 <= profit_revision < 2**32 or not 0 <= thresholds_digest < 2**31:
        raise ValueError("sürüm ya da özet aralık dışı")
    return (profit_revision << 31) | thresholds_digest


def thresholds_digest(
    overrides: dict[str, Decimal] | None, enabled: Sequence[str] | None, stamp: datetime | None = None
) -> int:
    """Eşik ezmesi, etkin kural kümesi ve satırın `updated_at` damgasının özeti (hiçbiri yoksa 0).

    Damga içeriğe KATILIR (ABA): eşik A -> B -> A olursa içerik aynı kalsa da damga değişir, anahtar yeniden
    kullanılmaz ve son ayar değerlendirilir.
    """
    if overrides is None and enabled is None and stamp is None:
        return 0
    parts = [f"{k}={format(v, 'f')}" for k, v in sorted((overrides or {}).items())]
    parts.append("enabled=" + ",".join(sorted(enabled or ())))
    parts.append("stamp=" + ("" if stamp is None else stamp.astimezone(UTC).isoformat()))
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _json_value(value: Any) -> Any:
    """Kanıt değerini JSON'a çevirir: Decimal metin (kuruş kaybı yok), bool/int/str olduğu gibi."""
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def event_payload(candidate: AlertCandidate) -> dict[str, Any]:
    """Olay yükü (izin listeli CHECK ile uyumlu): kesinlik ve iç içe `evidence`; kişisel veri yok."""
    return {
        "certainty": candidate.certainty.value,
        "evidence": {k: _json_value(v) for k, v in candidate.evidence.items()},
    }


def candidate_amount(candidate: AlertCandidate) -> Decimal | None:
    """Bildirim tutarı (KDV hariç TL): zarar toplamı, kesinti farkı, reklam harcaması; iade: yok."""
    key = {
        AlertRule.LOSS_MAKING_SALE: "total_loss",
        AlertRule.UNEXPECTED_DEDUCTION: "difference",
        AlertRule.AD_EATS_PROFIT: "ad_spend",
    }.get(candidate.rule)
    if key is None:
        return None
    value = candidate.evidence[key]
    assert isinstance(value, Decimal)
    return value


def quiet_until(moment: datetime, start: time, end: time) -> datetime | None:
    """`moment` sessiz saat aralığındaysa (Europe/Istanbul) aralığın bitişi (UTC), değilse None.

    Gece yarısını aşan aralık (22:00-08:00) ve aynı gün aralığı desteklenir; `start == end` boş aralıktır.
    """
    if start == end:
        return None
    local = moment.astimezone(_LOCAL_TZ)
    clock = local.time()
    inside = start <= clock < end if start < end else (clock >= start or clock < end)
    if not inside:
        return None
    end_at = datetime.combine(local.date(), end, tzinfo=_LOCAL_TZ)
    if end_at <= local:
        end_at += timedelta(days=1)
    return end_at.astimezone(UTC)


def blocked_rules(backfilled: Collection[str], failed: Collection[str]) -> frozenset[AlertRule]:
    """Bildirimi bastırılacak kurallar (O-a): kaynağı başarısız ya da yedeklemesi eksik olanlar.

    `backfilled`: yedeklemesi tamamlanmış kaynaklar; `failed`: son senkronu başarısız kaynaklar. Bir kural
    yalnız KENDİ kaynaklarından (`RULE_SOURCES`) biri bozuksa bastırılır; kaynağı olmayan kural (reklam)
    hiç bastırılmaz.
    """
    broken = (set(SOURCE_ORDER) - set(backfilled)) | set(failed)
    return frozenset(rule for rule, sources in RULE_SOURCES.items() if sources & broken)


# --------------------------------------------------------------------------- bastırma kararı
@dataclass(frozen=True, slots=True)
class ExistingEvent:
    """Kalıcı olayın bastırma ve geçiş kararı için gereken alanları."""

    id: UUID
    dedupe_key: str
    rule: str
    status: str
    muted_until: datetime | None
    resolved_at: datetime | None
    last_notified_at: datetime | None
    notified_amount: Decimal | None
    renotified: bool


@dataclass(frozen=True, slots=True)
class NotifyDecision:
    """Bildirim kararı ve olaya yazılacak bildirim alanları (bildirim yoksa mevcut değerler korunur)."""

    notify: bool
    last_notified_at: datetime | None
    notified_amount: Decimal | None
    renotified: bool


def decide_notification(
    candidate: AlertCandidate,
    existing: ExistingEvent | None,
    now: datetime,
    reopened_from: Literal["resolved", "muted"] | None,
) -> NotifyDecision:
    """ADR-0009 §3 bastırma kuralları (olay her durumda açılır; yalnız ANLIK bildirim kararı verilir).

    - `NotifyMode` NORMAL değilse bildirim yok (özet ya da yalnız panel).
    - Susturulmuş olay (süresi dolmadı) ve susturma süresi dolup yeniden açılan olay bildirim üretmez.
    - ZARARINA_SATIS: ilk bildirim bir kez; zarar son bildirilenin 2 katına çıkarsa YALNIZ BİR KEZ daha;
      çözülmüş olay 7 gün içinde yeniden açılırsa sessiz, sonra yeniden açılırsa yeni olay gibi.
    - REKLAM_KARI_YIYOR ve IADE_ORANI_ARTISI: en çok 14 günde bir.
    - BEKLENMEYEN_KESINTI: aynı satır bir kez.
    """
    kept = NotifyDecision(
        False,
        None if existing is None else existing.last_notified_at,
        None if existing is None else existing.notified_amount,
        False if existing is None else existing.renotified,
    )
    if candidate.notify is not NotifyMode.NORMAL:
        return kept
    if reopened_from == "muted" or (
        existing is not None and existing.status == "muted" and not reopened_from
    ):
        return kept
    if candidate.rule is AlertRule.LOSS_MAKING_SALE:
        total = candidate.evidence["total_loss"]
        assert isinstance(total, Decimal)
        fresh = existing is None or existing.notified_amount is None
        if existing is not None and reopened_from == "resolved":
            assert existing.resolved_at is not None
            if reopen_is_silent(existing.resolved_at, now):
                return kept
            fresh = True
        prior_amount = None if existing is None or fresh else existing.notified_amount
        prior_renotified = False if existing is None or fresh else existing.renotified
        if not loss_notification_due(total, prior_amount, renotified=prior_renotified):
            return kept
        return NotifyDecision(True, now, total, renotified=not fresh)
    if candidate.rule in (AlertRule.AD_EATS_PROFIT, AlertRule.RETURN_RATE_INCREASE):
        due = reminder_due(None if existing is None else existing.last_notified_at, now)
    else:
        due = existing is None or existing.last_notified_at is None
    if not due:
        return kept
    return NotifyDecision(True, now, kept.notified_amount, kept.renotified)


# --------------------------------------------------------------------------- sonuç tipleri
@dataclass(frozen=True, slots=True)
class Notifiable:
    """Anlık bildirim gerektiren olay (kural, olay kimliği, tutar, kesinlik)."""

    rule: AlertRule
    event_id: UUID
    amount: Decimal | None
    certainty: Certainty


@dataclass(slots=True)
class EvaluationOutcome:
    """Bir değerlendirmenin sonucu (özet: yalnız sayılar ve durum)."""

    account_id: UUID
    status: EvaluationStatus
    counts: dict[str, Any] = field(default_factory=dict)
    # Atlama nedeni: `completed` (anahtar başarıyla kapandı), `exhausted` (3 deneme tükendi), `raced`.
    reason: str | None = None

    def summary(self) -> dict[str, object]:
        extra = {} if self.reason is None else {"reason": self.reason}
        return {"account_id": str(self.account_id), "status": self.status, **extra, **self.counts}


@dataclass(frozen=True, slots=True)
class _Inputs:
    """Okuma aşamasının ürünü: anahtar, eşikler ve kural sonuçları."""

    key: EvaluationKey
    attempt: int
    outcomes: tuple[RuleOutcome, ...]
    unmatched_returns: int
    orphan_returns: int
    ambiguous_returns: int
    # O-a: kaynağı başarısız ya da yedeklemesi eksik kurallarda olay açılır ama bildirim (outbox) yazılmaz.
    blocked_rules: frozenset[AlertRule]


@dataclass(slots=True)
class _Counters:
    opened: int = 0
    updated: int = 0
    resolved: int = 0
    reopened: int = 0
    dropped: int = 0
    notifiables: list[Notifiable] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AlertEvaluationFailed(RuntimeError):
    """Arındırılmış değerlendirme hatası: yalnız özgün hatanın SINIF adını taşır.

    Veritabanı hata metni (psycopg DETAIL: barkod, sipariş no, tutar içerebilir) yeniden fırlatılırken
    bağlama ve iletiye taşınmaz (`raise ... from None`); log ve procrastinate iş kaydı yalnız sınıfı görür.
    """

    def __init__(self, error_class: str) -> None:
        super().__init__(f"alert evaluation failed: {error_class}")
        self.error_class = error_class


class AlertEvaluationTransient(AlertEvaluationFailed):
    """Geçici hata (bağlantı, serileştirme 40001, kilitlenme 40P01): procrastinate yeniden dener."""


TRANSIENT_SQLSTATES = frozenset({"40001", "40P01"})


def is_transient(exc: BaseException) -> bool:
    """Geçici veritabanı hatası mı (OperationalError, havuz TimeoutError, 40001, 40P01)."""
    if isinstance(exc, sa_exc.OperationalError | sa_exc.TimeoutError | psycopg.OperationalError):
        return True
    original = getattr(exc, "orig", exc)
    return getattr(original, "sqlstate", None) in TRANSIENT_SQLSTATES


class AlertEvaluator:
    """Hesap başına uyarı değerlendirmesi (`netkar_worker` motoru; saat dışarıdan verilebilir)."""

    def __init__(self, engine: AsyncEngine, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._engine = engine
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
        self._now = now

    # --- giriş ---------------------------------------------------------------------------------
    async def evaluate(self, account_id: UUID, scope: str = SCOPE_ALL) -> EvaluationOutcome:
        """Hesabı değerlendirir; kapanmış (ya da 3 deneme tükenmiş) anahtar hiçbir şey yazmaz (`skipped`).

        `scope`: `all` tüm etkin kurallar, `fast` yalnız 7 günlük zarar ve iade kuralı (artımlı sipariş
        senkronu). Hata `AlertEvaluationFailed` (geçiciyse `AlertEvaluationTransient`) olarak, özgün hata
        metni olmadan fırlar.
        """
        if scope not in SCOPE_RULES:
            raise ValueError("bilinmeyen değerlendirme kapsamı")
        started = monotonic.monotonic()
        resolved = await self._resolve_tenant(account_id)
        if resolved is None:
            return EvaluationOutcome(account_id, "inactive")
        tenant_id, backfilled = resolved
        now = self._now()
        as_of = now.astimezone(ISTANBUL).date()
        key: EvaluationKey | None = None
        attempt = 1
        try:
            inputs = await self._read_inputs(tenant_id, account_id, as_of, scope, backfilled)
            if isinstance(inputs, str):
                return self._skipped(account_id, inputs)
            key, attempt = inputs.key, inputs.attempt
            counts = await self._write(tenant_id, account_id, inputs, now, started)
        except Exception as exc:
            transient = is_transient(exc)
            logger.error(
                "alert_evaluation_failed",
                extra={
                    "account_id": str(account_id),
                    "error_class": type(exc).__name__,
                    "transient": transient,
                    "attempt": attempt,
                },
            )
            if key is not None:
                await self._record_failure(tenant_id, account_id, key, attempt, started)
            error = AlertEvaluationTransient if transient else AlertEvaluationFailed
            raise error(type(exc).__name__) from None
        if counts is None:
            return self._skipped(account_id, "raced")
        logger.info(
            "alert_evaluation_done",
            extra={
                "account_id": str(account_id),
                "scope": scope,
                "attempt": attempt,
                **{k: v for k, v in counts.items() if isinstance(v, int)},
                # Eşlenemeyen iade sayaçları yalnız sayıdır (kişisel veri yok).
                "unmatched_returns": inputs.unmatched_returns,
                "orphan_returns": inputs.orphan_returns,
                "ambiguous_returns": inputs.ambiguous_returns,
                "notify_blocked_rules": sorted(rule.value for rule in inputs.blocked_rules),
            },
        )
        return EvaluationOutcome(account_id, "succeeded", counts)

    @staticmethod
    def _skipped(account_id: UUID, reason: str) -> EvaluationOutcome:
        logger.info("alert_evaluation_skipped", extra={"account_id": str(account_id), "reason": reason})
        return EvaluationOutcome(account_id, "skipped", reason=reason)

    # --- hesap çözümü --------------------------------------------------------------------------
    async def _resolve_tenant(self, account_id: UUID) -> tuple[UUID, frozenset[str]] | None:
        """Hesabın kiracısı ve yedeklemesi tamamlanmış kaynaklar (yalnız etkin hesaplar; dar işlev)."""
        async with self._sessions() as session:
            row = (await session.execute(_SQL_RESOLVE_TENANT, {"account_id": account_id})).first()
            await session.rollback()
        if row is None:
            return None
        return UUID(str(row[0])), frozenset(row[1])

    # --- okuma aşaması ---------------------------------------------------------------------------
    async def _read_inputs(
        self, tenant_id: UUID, account_id: UUID, as_of: date, scope: str, backfilled: frozenset[str]
    ) -> _Inputs | str:
        """Sürümleri ve eşikleri okur; anahtar kapanmışsa atlama nedeni, değilse kuralları çalıştırır."""
        async with self._sessions() as session:
            await set_rls_context(session, tenant_id)
            # Sürümler motor girdisi okunmadan ÖNCE alınır (okuma sırasında veri değişirse sonraki
            # değerlendirme yeni sürümü görür; güvenli yön).
            data_revision = await report_data_version(session, tenant_id, account_id)
            loaded = await load_profit_settings(session, tenant_id, account_id)
            thresholds, enabled, digest = await self._load_thresholds(session, tenant_id, account_id, scope)
            key = EvaluationKey(as_of, data_revision, loaded.revision, digest)
            previous = (
                await session.execute(
                    _SQL_EVALUATION_ATTEMPTS,
                    {
                        "account_id": account_id,
                        "as_of": as_of,
                        "data_revision": data_revision,
                        "settings_revision": key.stored_settings_revision,
                        "rules_version": key.rules_version,
                    },
                )
            ).all()
            if any(r.status == "succeeded" for r in previous):
                await session.rollback()
                return "completed"
            attempt = max((int(r.attempt) for r in previous), default=0) + 1
            if attempt > MAX_ATTEMPTS:
                await session.rollback()
                return "exhausted"
            failed_sources = (
                (await session.execute(_SQL_FAILED_SOURCES, {"account_id": account_id})).scalars().all()
            )
            blocked = blocked_rules(backfilled, failed_sources)
            outcomes: list[RuleOutcome] = []
            if AlertRule.LOSS_MAKING_SALE.value in enabled:
                losses = await self._period(
                    session, tenant_id, account_id, as_of, LOSS_PERIOD_DAYS, loaded.settings
                )
                outcomes.append(evaluate_loss_making_sales(account_id, losses.result, thresholds))
            if AlertRule.AD_EATS_PROFIT.value in enabled:
                # Reklam verisi yok (D9): kural çalışmaz, motor 30 günlük dönemle çalıştırılmaz.
                outcomes.append(RuleOutcome(AlertRule.AD_EATS_PROFIT, RuleStatus.NO_DATA))
            if AlertRule.UNEXPECTED_DEDUCTION.value in enabled:
                deductions = await self._period(
                    session, tenant_id, account_id, as_of, DEDUCTION_PERIOD_DAYS, loaded.settings
                )
                outcomes.append(evaluate_unexpected_deduction(account_id, deductions.result, thresholds))
            cohorts = ReturnCohortSet(
                products=(),
                account=AccountReturnCounts(
                    current_lines=0, current_returned=0, base_lines=0, base_returned=0
                ),
            )
            if AlertRule.RETURN_RATE_INCREASE.value in enabled:
                cohorts = await load_return_cohorts(session, tenant_id, account_id, as_of)
                outcomes.append(evaluate_return_rate(account_id, as_of, cohorts.products, thresholds))
            await session.rollback()
        return _Inputs(
            key,
            attempt,
            tuple(outcomes),
            cohorts.unmatched_returns,
            cohorts.orphan_returns,
            cohorts.ambiguous_returns,
            blocked,
        )

    async def _period(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        account_id: UUID,
        as_of: date,
        days: int,
        profit_settings: Any,
    ) -> PeriodReport:
        """Mevcut besleyici ve rapor yolundan motor çıktısı (işlem kapanır; bağlam sonra yeniden kurulur)."""
        await set_rls_context(session, tenant_id)
        return await period_profit(
            session,
            tenant_id,
            account_id,
            as_of - timedelta(days=days - 1),
            as_of,
            profit_settings,
            release_connection=True,
        )

    async def _load_thresholds(
        self, session: AsyncSession, tenant_id: UUID, account_id: UUID, scope: str
    ) -> tuple[AlertThresholds, frozenset[str], int]:
        """Eşikler, ETKİN kurallar (satırdaki `rules_enabled` ve kapsam kesişimi) ve anahtar özeti.

        Kiracı ezmesi (`alert_rule_settings`) varsa onunla, yoksa varsayılanlarla. Kapsam `fast` iken özet
        kural
        kümesini içerir: aynı gün ve veri sürümünde `fast` çalıştırma `all` anahtarını kapatmaz.
        """
        row = (
            await session.execute(_SQL_THRESHOLDS, {"tenant_id": tenant_id, "account_id": account_id})
        ).first()
        in_scope = SCOPE_RULES[scope]
        if row is None:
            digest = 0 if scope == SCOPE_ALL else thresholds_digest(None, sorted(in_scope))
            return AlertThresholds(), in_scope, digest
        overrides: dict[str, Decimal] = {
            "loss_min_amount": row.loss_min_amount,
            "ad_share_percent": row.ad_share_percent,
            "ad_min_spend": row.ad_min_spend,
            "deduction_notify_min": row.deduction_notify_min,
            "return_min_diff_points": row.return_min_diff_points,
        }
        enabled = frozenset(row.rules_enabled) & in_scope
        return (
            AlertThresholds().with_overrides(overrides),
            enabled,
            thresholds_digest(overrides, sorted(enabled), row.updated_at),
        )

    # --- yazma aşaması ---------------------------------------------------------------------------
    async def _write(
        self, tenant_id: UUID, account_id: UUID, inputs: _Inputs, now: datetime, started: float
    ) -> dict[str, Any] | None:
        """Tek işlemde tüm yazımlar; anahtar başka bir çalıştırmada kapanmışsa None (hiçbir şey yazılmaz).

        İşlem hesap başına danışma kilidiyle başlar: aynı hesabın iki değerlendirmesi (ör. takılmış işin
        yeniden
        kuyruğa alınması) aynı anda yazamaz.
        """
        key = inputs.key
        async with tenant_transaction(self._sessions, tenant_id) as session:
            await session.execute(_SQL_ADVISORY_LOCK, {"account_id": account_id})
            evaluation_id = await self._open_evaluation(session, tenant_id, account_id, key, inputs.attempt)
            if evaluation_id is None:
                return None
            counters = await _apply_outcomes(session, tenant_id, account_id, inputs, now)
            outbox_rows = await _write_outbox(session, tenant_id, account_id, key, counters.notifiables, now)
            counts = _build_counts(inputs, counters, outbox_rows, started)
            await session.execute(
                _SQL_EVALUATION_CLOSE,
                {
                    "status": "succeeded",
                    "counts": json.dumps(counts),
                    "id": evaluation_id,
                    "tenant_id": tenant_id,
                },
            )
        if counters.dropped:
            logger.warning(
                "alert_event_cap_reached",
                extra={"account_id": str(account_id), "dropped": counters.dropped},
            )
        return counts

    @staticmethod
    async def _open_evaluation(
        session: AsyncSession, tenant_id: UUID, account_id: UUID, key: EvaluationKey, attempt: int
    ) -> UUID | None:
        row = (
            await session.execute(
                _SQL_EVALUATION_INSERT,
                {
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "as_of": key.as_of,
                    "data_revision": key.data_revision,
                    "settings_revision": key.stored_settings_revision,
                    "rules_version": key.rules_version,
                    "attempt": attempt,
                },
            )
        ).scalar_one_or_none()
        return None if row is None else UUID(str(row))

    async def _record_failure(
        self, tenant_id: UUID, account_id: UUID, key: EvaluationKey, attempt: int, started: float
    ) -> None:
        """Geri alınmış değerlendirme için AYRI işlemde `failed` satırı (kayıt hatası yalnız loglanır)."""
        counts = {"duration_ms": int((monotonic.monotonic() - started) * 1000)}
        try:
            async with tenant_transaction(self._sessions, tenant_id) as session:
                evaluation_id = await self._open_evaluation(session, tenant_id, account_id, key, attempt)
                if evaluation_id is not None:
                    await session.execute(
                        _SQL_EVALUATION_CLOSE,
                        {
                            "status": "failed",
                            "counts": json.dumps(counts),
                            "id": evaluation_id,
                            "tenant_id": tenant_id,
                        },
                    )
        except Exception as exc:
            logger.error(
                "alert_evaluation_failure_not_recorded",
                extra={"account_id": str(account_id), "error_class": type(exc).__name__},
            )


def _build_counts(inputs: _Inputs, counters: _Counters, outbox_rows: int, started: float) -> dict[str, Any]:
    """`alert_evaluations.counts` (izin listeli anahtarlar; yalnız sayılar)."""
    evaluated = [o for o in inputs.outcomes if o.status is RuleStatus.EVALUATED]
    return {
        "opened": counters.opened,
        "updated": counters.updated,
        "resolved": counters.resolved,
        "reopened": counters.reopened,
        "notified": len(counters.notifiables),
        "outbox_rows": outbox_rows,
        "candidates": sum(len(o.candidates) for o in evaluated),
        "rules_evaluated": len(evaluated),
        "rules_no_data": len(inputs.outcomes) - len(evaluated),
        "dropped": counters.dropped,
        "duration_ms": int((monotonic.monotonic() - started) * 1000),
        "rule_counts": {o.rule.value: len(o.candidates) for o in evaluated},
    }


# --------------------------------------------------------------------------- olay yazımı
async def _apply_outcomes(
    session: AsyncSession, tenant_id: UUID, account_id: UUID, inputs: _Inputs, now: datetime
) -> _Counters:
    """Adayları olaya yazar, koşulu kalkanları çözer ve bildirim gerekenleri toplar."""
    key = inputs.key
    db_now = (await session.execute(_SQL_DB_NOW)).scalar_one()
    rows = (await session.execute(_SQL_EVENTS, {"tenant_id": tenant_id, "account_id": account_id})).all()
    existing = {
        r.dedupe_key: ExistingEvent(
            r.id,
            r.dedupe_key,
            r.rule,
            r.status,
            r.muted_until,
            r.resolved_at,
            r.last_notified_at,
            r.notified_amount,
            r.renotified,
        )
        for r in rows
    }
    day_start = datetime.combine(key.as_of, time.min, tzinfo=ISTANBUL)
    new_today = (
        await session.execute(
            _SQL_NEW_TODAY, {"tenant_id": tenant_id, "account_id": account_id, "since": day_start}
        )
    ).scalar_one()
    budget = max(0, MAX_NEW_EVENTS_PER_DAY - int(new_today))
    counters = _Counters()
    for outcome in inputs.outcomes:
        if outcome.status is not RuleStatus.EVALUATED:
            continue  # veri yok: ne olay açılır ne de mevcut olay çözülür
        seen: set[str] = set()
        ordered = sorted(outcome.candidates, key=lambda c: (c.severity is not Severity.HIGH, c.subject))
        for candidate in ordered:
            seen.add(candidate.dedupe_key)
            current = existing.get(candidate.dedupe_key)
            if current is None:
                if budget <= 0:
                    counters.dropped += 1
                    continue
                budget -= 1
                decision = _gate(
                    decide_notification(candidate, None, now, None),
                    None,
                    candidate.rule not in inputs.blocked_rules,
                )
                event_id = await _insert_event(session, tenant_id, account_id, key, candidate, decision)
                counters.opened += 1
            else:
                reopened_from = _reopened_from(current, db_now)
                decision = _gate(
                    decide_notification(candidate, current, now, reopened_from),
                    current,
                    candidate.rule not in inputs.blocked_rules,
                )
                event_id = current.id
                await _update_event(session, tenant_id, key, candidate, current.id, decision)
                if reopened_from is None:
                    counters.updated += 1
                else:
                    if await _transition(session, tenant_id, current, "open"):
                        counters.reopened += 1
            if decision.notify:
                counters.notifiables.append(
                    Notifiable(candidate.rule, event_id, candidate_amount(candidate), candidate.certainty)
                )
        for event in existing.values():
            if event.rule != outcome.rule.value or event.dedupe_key in seen or event.status == "resolved":
                continue
            if await _transition(session, tenant_id, event, "resolved"):
                counters.resolved += 1
    return counters


def _reopened_from(event: ExistingEvent, db_now: datetime) -> Literal["resolved", "muted"] | None:
    """Yeniden açılma gerekir mi: çözülmüş ya da susturma süresi dolmuş (veritabanı saatiyle)."""
    if event.status == "resolved":
        return "resolved"
    if event.status == "muted" and event.muted_until is not None and event.muted_until <= db_now:
        return "muted"
    return None


async def _insert_event(
    session: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    key: EvaluationKey,
    candidate: AlertCandidate,
    decision: NotifyDecision,
) -> UUID:
    event_id = (
        await session.execute(
            _SQL_EVENT_INSERT,
            {
                "tenant_id": tenant_id,
                "account_id": account_id,
                "rule": candidate.rule.value,
                "scope": candidate.scope.value,
                "subject": candidate.subject,
                "dedupe_key": candidate.dedupe_key,
                "severity": candidate.severity.value,
                "payload": json.dumps(event_payload(candidate)),
                "payload_version": RULES_VERSION,
                "data_revision": key.data_revision,
                "settings_revision": key.settings_revision,
                "last_notified_at": decision.last_notified_at,
                "notified_amount": decision.notified_amount,
                "renotified": decision.renotified,
                "notify_mode": candidate.notify.value,
            },
        )
    ).scalar_one()
    assert isinstance(event_id, UUID)
    return event_id


async def _update_event(
    session: AsyncSession,
    tenant_id: UUID,
    key: EvaluationKey,
    candidate: AlertCandidate,
    event_id: UUID,
    decision: NotifyDecision,
) -> None:
    await session.execute(
        _SQL_EVENT_UPDATE,
        {
            "id": event_id,
            "tenant_id": tenant_id,
            "severity": candidate.severity.value,
            "payload": json.dumps(event_payload(candidate)),
            "payload_version": RULES_VERSION,
            "data_revision": key.data_revision,
            "settings_revision": key.settings_revision,
            "last_notified_at": decision.last_notified_at,
            "notified_amount": decision.notified_amount,
            "renotified": decision.renotified,
            "notify_mode": candidate.notify.value,
        },
    )


async def _transition(session: AsyncSession, tenant_id: UUID, event: ExistingEvent, to_status: str) -> bool:
    """Durum değişikliğinin TEK yolu: geçiş defterine ekleme (sistem aktörü veritabanında türetilir).

    Olay satırı okunurken kilitlendiği (`FOR UPDATE`) için `event.status` güncel durumdur; hedef durum zaten
    geçerliyse hiçbir şey yazılmaz (`from_status <> to_status` CHECK'i). Geçiş yazıldıysa True.
    """
    if event.status == to_status:
        return False
    await session.execute(
        _SQL_TRANSITION, {"tenant_id": tenant_id, "event_id": event.id, "to_status": to_status}
    )
    return True


def _gate(decision: NotifyDecision, existing: ExistingEvent | None, notify_allowed: bool) -> NotifyDecision:
    """Kuralın kaynağı bozuksa (O-a: başarısız son senkron, eksik yedekleme) olay açılır ama bildirim yok.

    Bildirim alanları (`last_notified_at`, tutar, bayrak) DEĞİŞMEZ: koşul sürerse veri tamamlanınca
    bildirilir.
    """
    if notify_allowed or not decision.notify:
        return decision
    return NotifyDecision(
        False,
        None if existing is None else existing.last_notified_at,
        None if existing is None else existing.notified_amount,
        False if existing is None else existing.renotified,
    )


# --------------------------------------------------------------------------- outbox yazımı
async def _write_outbox(
    session: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    key: EvaluationKey,
    notifiables: Sequence[Notifiable],
    now: datetime,
) -> int:
    """Anlık bildirimleri kullanıcı ve kanal başına TEK outbox satırı olarak yazar; satır sayısını verir.

    Alıcı adresi YAZILMAZ (gönderimde `notify_gate.email_for`). Alıcılar: açık tercih satırı olan kullanıcılar
    ve etkin push aboneliği olanlar; etkin mod tercih satırından, yoksa ADR-0009 §8.1 varsayılanından gelir
    (e-posta varsayılanı özet olduğundan anlık satır üretmez). Sessiz saatteki satır `held` ve `not_before` =
    sessiz saat bitişi olur.
    """
    if not notifiables:
        return 0
    params = {"tenant_id": tenant_id}
    preferences = {
        (r.user_id, r.rule, r.channel): r.mode
        for r in (await session.execute(_SQL_PREFERENCES, params)).all()
    }
    push_users = {r.user_id for r in (await session.execute(_SQL_PUSH_USERS, params)).all()}
    quiet = {
        r.user_id: (r.quiet_start, r.quiet_end)
        for r in (await session.execute(_SQL_QUIET_HOURS, params)).all()
    }
    users = {user for user, _rule, _channel in preferences} | push_users
    written = 0
    for user_id in sorted(users, key=str):
        for channel in ("email", "push"):
            if channel == "push" and user_id not in push_users:
                continue
            chosen = [
                n
                for n in notifiables
                if _instant_mode(preferences.get((user_id, n.rule.value, channel)), n.rule, channel)
            ]
            if not chosen:
                continue
            start, end = quiet.get(user_id, (DEFAULT_QUIET_START, DEFAULT_QUIET_END))
            until = quiet_until(now, start, end)
            # 500'den fazla olay (CHECK sınırı) parçalara bölünür: hiçbir bildirim kesilip atılmaz ve sınır
            # aşımı değerlendirmenin tamamını düşürmez. Her parça kendi tekilleştirme anahtarını taşır.
            for part, begin in enumerate(range(0, len(chosen), MAX_EVENT_IDS_PER_OUTBOX_ROW)):
                chunk = chosen[begin : begin + MAX_EVENT_IDS_PER_OUTBOX_ROW]
                seed = f"{user_id}|{channel}|instant|{key.outbox_seed(account_id)}|{part}"
                inserted = (
                    await session.execute(
                        _SQL_OUTBOX_INSERT,
                        {
                            "tenant_id": tenant_id,
                            "user_id": user_id,
                            "channel": channel,
                            "dedupe_key": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
                            "alert_event_ids": [n.event_id for n in chunk],
                            "payload": json.dumps(_outbox_payload(key, chunk)),
                            "status": "pending" if until is None else "held",
                            "not_before": now if until is None else until,
                        },
                    )
                ).scalar_one_or_none()
                if inserted is not None:
                    written += 1
    return written


def _instant_mode(preference: str | None, rule: AlertRule, channel: str) -> bool:
    """Etkin mod `instant` mı: tercih satırı varsa o, yoksa varsayılan matris."""
    if preference is not None:
        return preference == "instant"
    return channel == "push" and rule in DEFAULT_PUSH_INSTANT


def _outbox_payload(key: EvaluationKey, chosen: Sequence[Notifiable]) -> dict[str, Any]:
    """Outbox yükü (izin listeli CHECK ile uyumlu): kural başına sayı, tutar, pencere."""
    per_rule: dict[str, dict[str, Any]] = {}
    for item in chosen:
        entry = per_rule.setdefault(
            item.rule.value, {"event_count": 0, "window_days": WINDOW_DAYS[item.rule]}
        )
        entry["event_count"] += 1
        if item.amount is not None:
            entry["total_amount"] = format(Decimal(entry.get("total_amount", "0")) + item.amount, "f")
    payload: dict[str, Any] = {
        "rule_counts": {rule: entry["event_count"] for rule, entry in per_rule.items()},
        "event_count": len(chosen),
        "data_revision": key.data_revision,
        "settings_revision": key.settings_revision,
        "certainty": (
            Certainty.CERTAIN.value
            if all(item.certainty is Certainty.CERTAIN for item in chosen)
            else Certainty.ESTIMATED.value
        ),
    }
    payload.update(per_rule)
    return payload
