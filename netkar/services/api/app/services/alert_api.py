"""Uyarı API'sinin veritabanı işlemleri (ADR-0009 D6): olay okuma, geçiş ekleme, eşikler ve tercihler.

Güvenlik ilkeleri:

- Her sorguda açık `tenant_id` (ve olaylarda `marketplace_account_id`) süzgeci VAR; RLS ayrıca çalışır
  (çift kilit). Başka kiracının ya da hesabın olayı "yok" ile aynı sonuçtur (çağıran 404 verir, varlık
  sızdırılmaz).
- Olay durumu YALNIZ `alert_event_transitions` defterine ekleme ile değişir (insert-only; `netkar_app` olay
  tablosuna yazamaz). `from_status`, `actor`, `actor_user_id`, `id`, `created_at` veritabanı tetikleyicisinde
  türetilir; bu modül yalnız `(tenant_id, alert_event_id, to_status, muted_until)` yazar. Geçiş matrisi, rol
  denetimi ve `muted_until` <= 90 gün tetikleyicide de uygulanır (çift kilit); burada ön denetim yalnız temiz
  hata içindir.
- Süre hesabı (`muted_until`) veritabanı saatiyle yapılır (`now() + N gün`): istemci saatine güvenilmez.
- Tutarlar `Decimal`; log'a ve denetim kaydına yazılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, insert, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.settings import AlertThresholds
from app.models import (
    AlertEvaluation,
    AlertEvent,
    AlertEventTransition,
    AlertRuleSettings,
    NotificationPreference,
    NotificationSettings,
)

# Toplu okundu üst sınırı (ADR §8.2).
READ_ALL_LIMIT = 500
# Geçiş geçmişi sayfası (olay başına pratikte onlarca kayıt; üst sınır savunmadır).
TRANSITIONS_LIMIT = 200
RULE_NAMES = ("ZARARINA_SATIS", "REKLAM_KARI_YIYOR", "BEKLENMEYEN_KESINTI", "IADE_ORANI_ARTISI")
CHANNELS = ("email", "push")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
TWO_PLACES = Decimal("0.01")

# Kullanıcı geçiş matrisi (ADR §4.2); `resolved` ve sistem geçişleri kullanıcıya kapalıdır.
USER_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"read", "muted"}),
    "read": frozenset({"open", "muted"}),
    "muted": frozenset({"open"}),
    "resolved": frozenset(),
}
# Yalnız owner/admin yapabilir: susturma ve susturmayı kaldırma.
ADMIN_ONLY_TARGETS = frozenset({"muted"})


def transition_needs_admin(from_status: str, to_status: str) -> bool:
    """`muted` hedefi ve `muted -> open` yalnız owner/admin içindir (ADR §4.2)."""
    return to_status in ADMIN_ONLY_TARGETS or from_status == "muted"


def sqlstate(exc: DBAPIError) -> str | None:
    """Sürücü hatasının SQLSTATE'i (iç ayrıntı istemciye gitmez; yalnız sınıflandırma için okunur)."""
    return getattr(exc.orig, "sqlstate", None)


# --------------------------------------------------------------------------- olaylar
@dataclass(frozen=True, slots=True)
class EventFilter:
    status: str | None
    rule: str | None
    since: datetime | None  # dahil
    until: datetime | None  # hariç


def _scope(tenant_id: UUID, account_id: UUID) -> list[ColumnElement[bool]]:
    return [AlertEvent.tenant_id == tenant_id, AlertEvent.marketplace_account_id == account_id]


async def list_events(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    flt: EventFilter,
    limit: int,
    after: tuple[datetime, UUID] | None,
) -> tuple[list[AlertEvent], bool]:
    """Son görülmeye göre yeniden eskiye (anahtar kümesi: `last_seen_at`, `id`). `limit + 1` satır okunur."""
    stmt = select(AlertEvent).where(*_scope(tenant_id, account_id))
    if flt.status is not None:
        stmt = stmt.where(AlertEvent.status == flt.status)
    if flt.rule is not None:
        stmt = stmt.where(AlertEvent.rule == flt.rule)
    if flt.since is not None:
        stmt = stmt.where(AlertEvent.last_seen_at >= flt.since)
    if flt.until is not None:
        stmt = stmt.where(AlertEvent.last_seen_at < flt.until)
    if after is not None:
        stmt = stmt.where(tuple_(AlertEvent.last_seen_at, AlertEvent.id) < tuple_(after[0], after[1]))
    stmt = stmt.order_by(AlertEvent.last_seen_at.desc(), AlertEvent.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt.execution_options(populate_existing=True))).scalars())
    return rows[:limit], len(rows) > limit


async def open_count(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> int:
    stmt = select(func.count()).select_from(AlertEvent).where(*_scope(tenant_id, account_id))
    return int((await db.execute(stmt.where(AlertEvent.status == "open"))).scalar_one())


async def last_evaluation(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> AlertEvaluation | None:
    stmt = (
        select(AlertEvaluation)
        .where(
            AlertEvaluation.tenant_id == tenant_id,
            AlertEvaluation.marketplace_account_id == account_id,
            AlertEvaluation.status == "succeeded",
        )
        .order_by(AlertEvaluation.finished_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_event(db: AsyncSession, tenant_id: UUID, account_id: UUID, event_id: UUID) -> AlertEvent | None:
    """Kiracı VE hesapla kapsamlı tek olay; başka kiracı/hesap ya da olmayan kimlik `None`."""
    stmt = select(AlertEvent).where(*_scope(tenant_id, account_id), AlertEvent.id == event_id)
    return (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()


async def list_transitions(
    db: AsyncSession, tenant_id: UUID, event_id: UUID
) -> tuple[list[AlertEventTransition], bool]:
    """Olayın SON `TRANSITIONS_LIMIT` geçişi (eskiden yeniye) ve daha eskilerin kesilip kesilmediği.

    Olayın hesaba aitliği çağıranda `get_event` ile doğrulanır.
    """
    stmt = (
        select(AlertEventTransition)
        .where(AlertEventTransition.tenant_id == tenant_id, AlertEventTransition.alert_event_id == event_id)
        .order_by(AlertEventTransition.created_at.desc(), AlertEventTransition.id.desc())
        .limit(TRANSITIONS_LIMIT + 1)
    )
    rows = list((await db.execute(stmt)).scalars())
    return rows[:TRANSITIONS_LIMIT][::-1], len(rows) > TRANSITIONS_LIMIT


async def add_transition(
    db: AsyncSession, tenant_id: UUID, event_id: UUID, to_status: str, muted_days: int | None
) -> UUID:
    """Deftere TEK satır ekler; durumu tetikleyici uygular. Veritabanı reddederse `DBAPIError` yayılır."""
    muted_until = func.now() + timedelta(days=muted_days) if muted_days is not None else None
    row = await db.execute(
        insert(AlertEventTransition)
        .values(tenant_id=tenant_id, alert_event_id=event_id, to_status=to_status, muted_until=muted_until)
        .returning(AlertEventTransition.id)
    )
    return row.scalar_one()


async def mark_open_events_read(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> int:
    """Hesabın açık olaylarından en çok `READ_ALL_LIMIT` tanesine `read` geçişi ekler; eklenen sayıyı döner.

    Tek çok satırlı ekleme (ledger'a yalnız ekleme). Eşzamanlı bir durum değişimi tetikleyicide 40001 verirse
    savepoint geri alınır ve liste yeniden okunarak bir kez daha denenir; ikinci kez de olursa hata yayılır.
    """
    for attempt in (1, 2):
        ids = list(
            (
                await db.execute(
                    select(AlertEvent.id)
                    .where(*_scope(tenant_id, account_id), AlertEvent.status == "open")
                    .order_by(AlertEvent.last_seen_at.desc(), AlertEvent.id.desc())
                    .limit(READ_ALL_LIMIT)
                )
            ).scalars()
        )
        if not ids:
            return 0
        try:
            async with db.begin_nested():
                await db.execute(
                    insert(AlertEventTransition).values(
                        [
                            {
                                "tenant_id": tenant_id,
                                "alert_event_id": i,
                                "to_status": "read",
                                "muted_until": None,
                            }
                            for i in ids
                        ]
                    )
                )
        except DBAPIError as exc:
            # Eşzamanlı değişim (40001), kilit kilitlenmesi (40P01) ve araya giren durum değişimi (23514):
            # liste yeniden okunarak bir kez daha denenir.
            if sqlstate(exc) in ("40001", "40P01", "23514") and attempt == 1:
                continue
            raise
        return len(ids)
    return 0  # pragma: no cover (döngü ya döner ya da yayar)


# --------------------------------------------------------------------------- hesap eşikleri
@dataclass(frozen=True, slots=True)
class SettingsValues:
    """Eşik değerleri (hepsi 2 ondalıklı Decimal) ve etkin kurallar (kanonik sıra)."""

    loss_min_amount: Decimal
    ad_share_percent: Decimal
    ad_min_spend: Decimal
    deduction_notify_min: Decimal
    return_min_diff_points: Decimal
    rules_enabled: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SettingsState:
    values: SettingsValues
    updated_at: datetime | None  # None: kayıt yok (varsayılanlar)

    @property
    def is_default(self) -> bool:
        return self.updated_at is None

    @property
    def etag(self) -> str:
        return etag_for(self.updated_at)


def _q2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES)


def _canonical_rules(rules: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(r for r in RULE_NAMES if r in rules)


def default_values() -> SettingsValues:
    base = AlertThresholds()
    return SettingsValues(
        loss_min_amount=_q2(base.loss_min_amount),
        ad_share_percent=_q2(base.ad_share_percent),
        ad_min_spend=_q2(base.ad_min_spend),
        deduction_notify_min=_q2(base.deduction_notify_min),
        return_min_diff_points=_q2(base.return_min_diff_points),
        rules_enabled=RULE_NAMES,
    )


def etag_for(updated_at: datetime | None) -> str:
    """Eşik kaydının ETag'i: sunucu `updated_at` damgasının mikrosaniyesi (kayıt yoksa 0). Sürüm sayacı yok;
    her yazım tetikleyicide `updated_at := now()` yaptığı için damga sürüm işlevi görür."""
    micros = 0 if updated_at is None else (updated_at - _EPOCH) // timedelta(microseconds=1)
    return f'"as-{micros}"'


async def load_settings(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> SettingsState:
    stmt = select(AlertRuleSettings).where(
        AlertRuleSettings.tenant_id == tenant_id, AlertRuleSettings.marketplace_account_id == account_id
    )
    row = (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        return SettingsState(default_values(), None)
    return SettingsState(
        SettingsValues(
            loss_min_amount=_q2(row.loss_min_amount),
            ad_share_percent=_q2(row.ad_share_percent),
            ad_min_spend=_q2(row.ad_min_spend),
            deduction_notify_min=_q2(row.deduction_notify_min),
            return_min_diff_points=_q2(row.return_min_diff_points),
            rules_enabled=_canonical_rules(row.rules_enabled),
        ),
        row.updated_at,
    )


async def write_settings(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    values: SettingsValues,
    expected_updated_at: datetime | None,
) -> datetime | None:
    """Eşikleri yazar; ETag eşleşmezse (eşzamanlı yazım) `None` döner ve hiçbir şey yazılmaz.

    `expected_updated_at` None: kayıt henüz yok (ilk giriş) `INSERT ... ON CONFLICT DO NOTHING`; var olan
    kayıt `updated_at = beklenen` koşuluyla güncellenir (READ COMMITTED altında eşzamanlı yazım satır kilidini
    bekler, koşulu yeniden değerlendirir ve 0 satır döner). `updated_by` ve `updated_at` BEFORE
    tetikleyicisinde atanır; owner/admin denetimi de orada çift kilittir.
    """
    data: dict[str, Any] = {
        "loss_min_amount": values.loss_min_amount,
        "ad_share_percent": values.ad_share_percent,
        "ad_min_spend": values.ad_min_spend,
        "deduction_notify_min": values.deduction_notify_min,
        "return_min_diff_points": values.return_min_diff_points,
        "rules_enabled": list(values.rules_enabled),
    }
    table = AlertRuleSettings
    if expected_updated_at is None:
        insert_stmt = (
            pg_insert(table)
            .values(tenant_id=tenant_id, marketplace_account_id=account_id, **data)
            .on_conflict_do_nothing(index_elements=["tenant_id", "marketplace_account_id"])
            .returning(table.updated_at)
        )
        inserted: datetime | None = (await db.execute(insert_stmt)).scalar_one_or_none()
        return inserted
    update_stmt = (
        update(table)
        .where(
            table.tenant_id == tenant_id,
            table.marketplace_account_id == account_id,
            table.updated_at == expected_updated_at,
        )
        .values(**data)
        .returning(table.updated_at)
    )
    updated: datetime | None = (await db.execute(update_stmt)).scalar_one_or_none()
    return updated


# --------------------------------------------------------------------------- kullanıcı tercihleri
# ADR §8.1 varsayılan matrisi: e-posta özet, push yalnız zarar ve kesintide anında; viewer e-postası kapalı.
_DEFAULT_PUSH = {
    "ZARARINA_SATIS": "instant",
    "BEKLENMEYEN_KESINTI": "instant",
    "REKLAM_KARI_YIYOR": "off",
    "IADE_ORANI_ARTISI": "off",
}


@dataclass(frozen=True, slots=True)
class PreferencesValues:
    matrix: dict[str, dict[str, str]]
    quiet_start: str
    quiet_end: str
    digest_hour: int
    show_amounts_email: bool
    show_amounts_push: bool


def default_matrix(role: str) -> dict[str, dict[str, str]]:
    email = "off" if role == "viewer" else "digest"
    return {rule: {"email": email, "push": _DEFAULT_PUSH[rule]} for rule in RULE_NAMES}


def _hhmm(value: Any) -> str:
    return str(value.strftime("%H:%M"))


async def load_preferences(db: AsyncSession, tenant_id: UUID, user_id: UUID, role: str) -> PreferencesValues:
    """Kullanıcının kendi tercihleri (kiracı + kullanıcı süzgeci, RLS `user_self`); eksik hücre varsayılan."""
    matrix = default_matrix(role)
    pref_stmt = select(NotificationPreference).where(
        NotificationPreference.tenant_id == tenant_id, NotificationPreference.user_id == user_id
    )
    for pref in (await db.execute(pref_stmt.execution_options(populate_existing=True))).scalars():
        if pref.rule in matrix and pref.channel in CHANNELS:
            matrix[pref.rule][pref.channel] = pref.mode
    set_stmt = select(NotificationSettings).where(
        NotificationSettings.tenant_id == tenant_id, NotificationSettings.user_id == user_id
    )
    row = (await db.execute(set_stmt.execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        return PreferencesValues(matrix, "22:00", "08:00", 8, True, False)
    return PreferencesValues(
        matrix,
        _hhmm(row.quiet_start),
        _hhmm(row.quiet_end),
        int(row.digest_hour),
        bool(row.show_amounts_email),
        bool(row.show_amounts_push),
    )


async def save_preferences(
    db: AsyncSession, tenant_id: UUID, user_id: UUID, values: PreferencesValues
) -> None:
    """Sekiz matris hücresini ve kullanıcı ayarını UPSERT eder (yalnız kendi satırı; RLS ve sütun yetkisi)."""
    cells = [
        {"tenant_id": tenant_id, "user_id": user_id, "rule": rule, "channel": channel, "mode": mode}
        for rule, by_channel in values.matrix.items()
        for channel, mode in by_channel.items()
    ]
    pref_insert = pg_insert(NotificationPreference).values(cells)
    await db.execute(
        pref_insert.on_conflict_do_update(
            index_elements=["tenant_id", "user_id", "rule", "channel"],
            set_={"mode": pref_insert.excluded.mode},
        )
    )
    new_values = {
        "quiet_start": time.fromisoformat(values.quiet_start),
        "quiet_end": time.fromisoformat(values.quiet_end),
        "digest_hour": values.digest_hour,
        "show_amounts_email": values.show_amounts_email,
        "show_amounts_push": values.show_amounts_push,
    }
    settings_insert = pg_insert(NotificationSettings).values(
        tenant_id=tenant_id, user_id=user_id, **new_values
    )
    await db.execute(
        settings_insert.on_conflict_do_update(index_elements=["tenant_id", "user_id"], set_=new_values)
    )
