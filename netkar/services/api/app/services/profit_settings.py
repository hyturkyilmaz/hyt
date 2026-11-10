"""Kâr ayarları (ADR-0006, docs/12 K33-K36): doğrulama kuralları, okuma, yazma ve motor ayarına çeviri.

Kurallar tek yerdedir: PUT gövdeleri (`app.api.v1.profit_settings_schemas`) bu işlevleri çağırır. Para ve
oranlar
`Decimal`'dir, float yoktur; saklanan tutar projedeki tek yuvarlama işlevi `app.profit.money.rnd` ile kuruşa
normalleştirilir. Kullanıcı tutarı KDV dahil ya da hariç girebilir; giriş biçimi kayıtta saklanır ve motora
verilirken K02 ile KDV hariçe çevrilir (tutar başına bir yuvarlama): 54,00 dahil -> 45,00; 50,00 -> 41,67;
hizmet bedeli 12,00 dahil -> 10,00.

Yazımlar `profit_settings.revision` ile serileştirilir: her yazım önce hesabın ayar satırını (yoksa oluşturup)
kilitler ve beklenen sürümü doğrular; yazım gerçekten bir değişiklik yapıyorsa sürüm +1 olur. Böylece iki
yönetici aynı anda düzenlerse biri 409 alır (sessiz ezme yok) ve hesap başına yazımlar sıraya girer.

ADR-0007 (K42-K44): ayar satırları DEĞİŞMEZDİR. Yazım üç işlemden biridir: ekle, değiştir (eski satır
`revision_to` ile kapanır, yeni satır eklenir) ve geri çek (yalnız kapanır); hiçbir şey silinmez. Her
yazım aynı işlemde ayar günlüğüne (`profit_settings_changes`) tek kayıt düşer. Geçmişi etkileyen yazım
açık onay ister (`PastChangeUnconfirmed`), yalnız "eksik"i dolduran ilk giriş hariç. Okuma yalnız
etkin satırları görür; yükleyici istenirse belirli bir ayar sürümüyle çalışır. Commit çağırana aittir.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import unix_time
from app.models import (
    CargoTariffRecord,
    Membership,
    Order,
    OrderLine,
    ProfitSettingsChange,
    ProfitSettingsRecord,
    ServiceFeeEstimateRecord,
    VariableExpenseRecord,
)
from app.profit.constants import CANCELLED_STATUSES, SELLER_PAYS_CARGO
from app.profit.enums import ExpenseKind
from app.profit.money import rnd, split_inclusive
from app.profit.settings import (
    FALLBACK_CARRIER,
    CargoTariff,
    DatedAmount,
    ProfitSettings,
    TariffVersion,
    VariableExpense,
)
from app.services.product_costs import ALLOWED_VAT_RATES, RuleError
from app.services.profit_feed import period_bounds

AGREEMENTS = ("trendyol", "seller")
CARRIER_WILDCARD = FALLBACK_CARRIER
MAX_CARRIER_LENGTH = 100
MAX_BRACKETS = 50
MAX_DESI = Decimal("1000")
MAX_PRICE = Decimal("100000")
MAX_SERVICE_FEE = Decimal("10000")
MAX_EXPENSE_AMOUNT = Decimal("100000")
MAX_EXPENSE_NAME = 80
MAX_EXPENSES = 50
MAX_TARIFF_VERSIONS = 200
# Hizmet bedeli tahmini sürümü: tarifeyle aynı sınır (denetim AO-01); sınırsızken rapor maliyeti sürüm
# sayısıyla çarpılıyordu. Değişken gider için MAX_EXPENSES (50) zaten vardır.
MAX_SERVICE_FEE_VERSIONS = 200
CARRIER_LOOKBACK_DAYS = 92
_CENT = Decimal("0.01")
_BASIS_POINT = Decimal("0.0001")
_BASE = ProfitSettings()  # sistem parametreleri (KDV oranları) motor sabitidir; tabloda yoktur


# --------------------------------------------------------------------------- doğrulama kuralları
class LimitError(ValueError):
    """Hesap başına sayı sınırı aşıldı (durum kontrolü: gövde tek başına geçersiz değil)."""

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message


class RevisionConflict(Exception):
    """Beklenen ayar sürümü güncel sürümle uyuşmuyor (iki yönetici aynı anda düzenledi)."""

    def __init__(self, current: int) -> None:
        super().__init__("revision conflict")
        self.current = current


def _has_control(text: str) -> bool:
    return any(unicodedata.category(ch).startswith("C") for ch in text)


def check_carrier(value: str) -> str:
    """Firma adı: 1-100 karakter, kırpılmış, kontrol karakteri yok; `*` yalnız tek başına (diğer firmalar)."""
    if (
        not 1 <= len(value) <= MAX_CARRIER_LENGTH
        or value != value.strip()
        or _has_control(value)
        or ("*" in value and value != CARRIER_WILDCARD)
    ):
        raise RuleError(
            "carrier_invalid",
            "Firma adı 1-100 karakter olmalı, baştaki/sondaki boşluk ve kontrol karakteri içermemeli; "
            "'*' yalnız tek başına 'diğer firmalar' anlamındadır.",
        )
    return value


def _fits(value: Decimal, exponent: Decimal) -> bool:
    """Sonlu ve en çok `exponent` ondalıklı mı. `quantize` sonuç 28 haneyi aşınca `InvalidOperation` atar
    (denetim AD-01: 1e30, 31 haneli tamsayı); bu "aralık dışı"dır, 500 değil."""
    if not value.is_finite():
        return False
    try:
        return value == value.quantize(exponent)
    except InvalidOperation:
        return False


def _two_decimals(value: Decimal) -> bool:
    return _fits(value, _CENT)


def check_desi(value: Decimal) -> Decimal:
    """0 < desi <= 1000, en çok 2 ondalık."""
    if not _two_decimals(value) or not Decimal(0) < value <= MAX_DESI:
        raise RuleError("desi_out_of_range", "Desi 0'dan büyük, en çok 1000 ve en çok 2 ondalıklı olmalıdır.")
    return value.quantize(_CENT)


def check_price(value: Decimal) -> Decimal:
    """0 <= fiyat <= 100.000, en çok 2 ondalık."""
    if not _two_decimals(value) or not Decimal(0) <= value <= MAX_PRICE:
        raise RuleError("price_out_of_range", "Fiyat 0 ile 100.000 arasında ve en çok 2 ondalıklı olmalıdır.")
    return rnd(value)


def check_brackets(pairs: Sequence[tuple[Decimal, Decimal]]) -> list[tuple[Decimal, Decimal]]:
    """Kademeler: 1-50 adet, üst desi kesin artan (tekrar yok), her biri alan kuralına uyar."""
    if not pairs:
        raise RuleError("brackets_empty", "En az bir kademe gerekir.")
    if len(pairs) > MAX_BRACKETS:
        raise RuleError("too_many_brackets", f"En çok {MAX_BRACKETS} kademe girilebilir.")
    checked = [(check_desi(desi), check_price(price)) for desi, price in pairs]
    if any(later <= earlier for (earlier, _), (later, _) in pairwise(checked)):
        raise RuleError("brackets_not_increasing", "Kademelerin üst desisi kesin artan sırada olmalıdır.")
    return checked


def check_service_fee_amount(value: Decimal) -> Decimal:
    """0 <= tutar <= 10.000, en çok 2 ondalık. Sıfır geçerlidir (bilerek 0: tanımlı, K35)."""
    if not _two_decimals(value) or not Decimal(0) <= value <= MAX_SERVICE_FEE:
        raise RuleError("amount_out_of_range", "Tutar 0 ile 10.000 arasında ve en çok 2 ondalıklı olmalıdır.")
    return rnd(value)


def check_expense_amount(value: Decimal) -> Decimal:
    """Değişken gider tutarı (KDV hariç): 0 <= tutar <= 100.000, en çok 2 ondalık."""
    if not _two_decimals(value) or not Decimal(0) <= value <= MAX_EXPENSE_AMOUNT:
        raise RuleError(
            "amount_out_of_range", "Tutar 0 ile 100.000 arasında ve en çok 2 ondalıklı olmalıdır."
        )
    return rnd(value)


def check_percent(value: Decimal) -> Decimal:
    """0 < oran <= 100, en çok 4 ondalık."""
    if not _fits(value, _BASIS_POINT) or not Decimal(0) < value <= Decimal(100):
        raise RuleError(
            "percent_out_of_range", "Oran 0'dan büyük, en çok 100 ve en çok 4 ondalıklı olmalıdır."
        )
    return value.quantize(_BASIS_POINT)


def check_expense_vat_rate(value: Decimal) -> Decimal:
    if not value.is_finite() or value not in ALLOWED_VAT_RATES:
        raise RuleError("vat_rate_invalid", "KDV oranı yüzde olarak 0, 1, 10 veya 20 olmalıdır.")
    return value


def check_expense_name(value: str) -> str:
    if not 1 <= len(value) <= MAX_EXPENSE_NAME or value != value.strip() or _has_control(value):
        raise RuleError(
            "name_invalid", "Ad 1-80 karakter olmalı, baştaki/sondaki boşluk ve kontrol karakteri içermemeli."
        )
    return value


def check_kind_amount(kind: str, amount: Decimal | None, percent: Decimal | None) -> None:
    """Tip ile tutar/oran uyumu: yüzde tipinde yalnız oran, diğer tiplerde yalnız tutar."""
    if kind == ExpenseKind.PERCENT_OF_SALES:
        consistent = percent is not None and amount is None
    else:
        consistent = amount is not None and percent is None
    if not consistent:
        raise RuleError(
            "kind_amount_mismatch",
            "satis_yuzdesi tipinde yalnız oran, siparis_basi ve adet_basi tiplerinde yalnız tutar girilir.",
        )


def check_valid_to(valid_from: date, valid_to: date | None) -> date | None:
    if valid_to is not None and valid_to < valid_from:
        raise RuleError("valid_to_before_valid_from", "Geçerlilik bitişi başlangıçtan önce olamaz.")
    return valid_to


# --------------------------------------------------------------------------- KDV dönüşümü (K02)
def to_excl_vat(amount: Decimal, includes_vat: bool, vat_rate: Decimal) -> Decimal:
    """Girilen tutarı KDV hariçe çevirir: dahilse `rnd(dahil / (1 + oran/100))` (K02), değilse kuruşa."""
    if includes_vat:
        return split_inclusive(amount, vat_rate)[0]
    return rnd(amount)


def bracket_pairs(record: CargoTariffRecord) -> list[tuple[Decimal, Decimal]]:
    """Kayıtlı kademeler (metin tutarlar) -> (üst desi, girilen fiyat)."""
    return [(Decimal(b["max_desi"]), Decimal(b["price"])) for b in record.brackets]


# --------------------------------------------------------------------------- okuma
@dataclass(frozen=True, slots=True)
class SettingsBundle:
    """Bir hesabın bir ayar sürümündeki ayar kayıtları (hacim küçüktür, dönem öncesi son sürüm de gerekir).

    Varsayılan: güncel sürümün ETKİN satırları (K42). `at_revision` verilirse o sürümde etkin satırlar ve
    günlükten okunan varsayılan desi (K44).
    """

    default_desi: Decimal | None
    revision: int
    tariffs: tuple[CargoTariffRecord, ...]
    fees: tuple[ServiceFeeEstimateRecord, ...]
    expenses: tuple[VariableExpenseRecord, ...]


class RevisionUnavailable(Exception):
    """İstenen ayar sürümü yeniden kurulamaz: henüz yok ya da 0008 taşımasından önce (K44)."""

    def __init__(self, requested: int, current: int) -> None:
        super().__init__("settings revision unavailable")
        self.requested = requested
        self.current = current


def _in_force(model: Any, at_revision: int | None) -> list[Any]:
    """Etkinlik: güncel sürümde `revision_to IS NULL`; R sürümünde `revision_from <= R < revision_to`."""
    if at_revision is None:
        return [model.revision_to.is_(None)]
    return [
        model.revision_from <= at_revision,
        or_(model.revision_to.is_(None), model.revision_to > at_revision),
    ]


async def _desi_at(db: AsyncSession, tenant_id: UUID, account_id: UUID, revision: int) -> Decimal | None:
    """R sürümündeki varsayılan desi: günlükte R'ye kadarki son `defaults`/`tasima` kaydının sonrası."""
    return (
        await db.execute(
            select(ProfitSettingsChange.default_desi_after)
            .where(
                ProfitSettingsChange.tenant_id == tenant_id,
                ProfitSettingsChange.marketplace_account_id == account_id,
                ProfitSettingsChange.revision <= revision,
                ProfitSettingsChange.item.in_(("defaults", "tasima")),
            )
            .order_by(ProfitSettingsChange.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def load_bundle(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, at_revision: int | None = None
) -> SettingsBundle:
    """Ayar kayıtlarını okur (RLS bağlamı çağıranda kurulu; sorgular ayrıca kiracı ve hesap süzgeci taşır).

    `at_revision` None ya da güncel sürüm ise etkin satırlar ve hesap satırındaki desi; daha eskiyse o
    sürümde etkin satırlar ve günlükten desi. Güncelden büyük sürüm ya da `tasima` kaydından önceki sürüm
    `RevisionUnavailable` (K44).
    """

    def scoped(model: Any) -> tuple[Any, Any]:
        return model.tenant_id == tenant_id, model.marketplace_account_id == account_id

    head = (
        await db.execute(select(ProfitSettingsRecord).where(*scoped(ProfitSettingsRecord)))
    ).scalar_one_or_none()
    current = 0 if head is None else int(head.revision)
    if at_revision is not None and (at_revision < 0 or at_revision > current):
        raise RevisionUnavailable(at_revision, current)
    as_of = None if at_revision is None or at_revision == current else at_revision
    if as_of is not None:
        moved = (
            await db.execute(
                select(func.min(ProfitSettingsChange.revision)).where(
                    *scoped(ProfitSettingsChange), ProfitSettingsChange.item == "tasima"
                )
            )
        ).scalar_one()
        if moved is not None and as_of < moved:
            raise RevisionUnavailable(as_of, current)
    tariffs = (
        (
            await db.execute(
                select(CargoTariffRecord)
                .where(*scoped(CargoTariffRecord), *_in_force(CargoTariffRecord, as_of))
                .order_by(
                    CargoTariffRecord.agreement, CargoTariffRecord.carrier, CargoTariffRecord.valid_from
                )
            )
        )
        .scalars()
        .all()
    )
    fees = (
        (
            await db.execute(
                select(ServiceFeeEstimateRecord)
                .where(*scoped(ServiceFeeEstimateRecord), *_in_force(ServiceFeeEstimateRecord, as_of))
                .order_by(ServiceFeeEstimateRecord.valid_from)
            )
        )
        .scalars()
        .all()
    )
    expenses = (
        (
            await db.execute(
                select(VariableExpenseRecord)
                .where(*scoped(VariableExpenseRecord), *_in_force(VariableExpenseRecord, as_of))
                # Tanım sırası: değiştirme `created_at`'i devralır; motor gider dökümü sırası bozulmaz.
                .order_by(VariableExpenseRecord.created_at, VariableExpenseRecord.id)
            )
        )
        .scalars()
        .all()
    )
    if as_of is not None:
        desi = await _desi_at(db, tenant_id, account_id, as_of)
    else:
        desi = None if head is None else head.default_desi
    return SettingsBundle(
        default_desi=desi,
        revision=current if as_of is None else as_of,
        tariffs=tuple(tariffs),
        fees=tuple(fees),
        expenses=tuple(expenses),
    )


def to_profit_settings(bundle: SettingsBundle) -> ProfitSettings:
    """Kayıtlardan motor ayarı: KDV dahil girişler K02 ile hariçe çevrilir; kayıt yoksa `ProfitSettings()`.

    Sürüm seçimi (sipariş gününe göre) motor tarafındadır (`app.profit.settings.pick_version`); burada tüm
    sürümler motora verilir.
    """
    steps: dict[str, dict[str, list[TariffVersion]]] = {a: defaultdict(list) for a in AGREEMENTS}
    for record in bundle.tariffs:
        brackets = tuple(
            (desi, to_excl_vat(price, record.price_includes_vat, _BASE.shipping_vat_rate))
            for desi, price in bracket_pairs(record)
        )
        steps[record.agreement][record.carrier].append(TariffVersion(brackets, record.valid_from))
    return ProfitSettings(
        cargo_tariff=CargoTariff({c: tuple(v) for c, v in steps["trendyol"].items()}),
        seller_cargo_tariff=CargoTariff({c: tuple(v) for c, v in steps["seller"].items()}),
        service_fee_estimates=tuple(
            DatedAmount(
                to_excl_vat(fee.amount, fee.amount_includes_vat, _BASE.service_fee_vat_rate), fee.valid_from
            )
            for fee in bundle.fees
        ),
        default_desi=bundle.default_desi,
        variable_expenses=tuple(
            VariableExpense(
                name=e.name,
                kind=ExpenseKind(e.kind),
                amount_excl_vat=rnd(e.amount_excl_vat) if e.amount_excl_vat is not None else Decimal(0),
                percent=e.percent if e.percent is not None else Decimal(0),
                vat_rate=e.vat_rate,
                valid_from=e.valid_from,
                valid_to=e.valid_to,
            )
            for e in bundle.expenses
        ),
    )


async def profit_settings_for(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, at_revision: int | None = None
) -> ProfitSettings:
    """Hesabın kâr ayarları (ADR-0005 §7 tek değişiklik noktası). Hiç kayıt yoksa `ProfitSettings()`.

    `at_revision` verilirse o ayar sürümünde etkin satırlarla kurar (K44, iç API); varsayılan güncel sürümdür.
    """
    return to_profit_settings(await load_bundle(db, tenant_id, account_id, at_revision))


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    """Motor ayarı ve ona karşılık gelen ayar sürümü (rapor damgası `settings_revision`, K44)."""

    settings: ProfitSettings
    revision: int


async def load_profit_settings(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, at_revision: int | None = None
) -> LoadedSettings:
    """`profit_settings_for` ile aynı, ama okunan sürümü de verir (ayar ve damga tek okumada tutarlı)."""
    bundle = await load_bundle(db, tenant_id, account_id, at_revision)
    return LoadedSettings(to_profit_settings(bundle), bundle.revision)


@dataclass(frozen=True, slots=True)
class Completeness:
    """ "Bugün geçerli bir sürüm var mı" bayrakları (ADR-0006 §3.3)."""

    cargo_tariff_defined: bool
    seller_cargo_tariff_defined: bool
    service_fee_estimate_defined: bool
    variable_expenses_defined: bool
    default_desi_defined: bool

    @property
    def configured(self) -> bool:
        """Eski `settings_configured` anlamı: kargo tarifesi VE hizmet bedeli tahmini tanımlı."""
        return self.cargo_tariff_defined and self.service_fee_estimate_defined


def completeness_of(bundle: SettingsBundle, today: date) -> Completeness:
    return Completeness(
        cargo_tariff_defined=any(t.agreement == "trendyol" and t.valid_from <= today for t in bundle.tariffs),
        seller_cargo_tariff_defined=any(
            t.agreement == "seller" and t.valid_from <= today for t in bundle.tariffs
        ),
        service_fee_estimate_defined=any(f.valid_from <= today for f in bundle.fees),
        variable_expenses_defined=any(
            e.valid_from <= today and (e.valid_to is None or today <= e.valid_to) for e in bundle.expenses
        ),
        default_desi_defined=bundle.default_desi is not None,
    )


async def profit_settings_completeness(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, today: date
) -> Completeness:
    return completeness_of(await load_bundle(db, tenant_id, account_id), today)


async def profit_settings_configured(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, today: date
) -> bool:
    """Kâr ayarı tanımlı mı (gerçek durum): bugün geçerli kargo tarifesi VE hizmet bedeli tahmini var."""
    return (await profit_settings_completeness(db, tenant_id, account_id, today)).configured


@dataclass(frozen=True, slots=True)
class CarrierUsage:
    """Son 92 günün siparişlerinde görülen (firma, anlaşma) çifti ve bugünkü tarifeyle kapsanma durumu."""

    carrier: str
    agreement: str
    line_count: int
    covered: bool


def _covers(bundle: SettingsBundle, agreement: str, carrier: str, today: date) -> bool:
    """K34 özeti: firmanın bugün geçerli sürümü var ya da `*` yedeğinin bugün geçerli sürümü var."""
    return any(
        t.agreement == agreement and t.carrier in (carrier, CARRIER_WILDCARD) and t.valid_from <= today
        for t in bundle.tariffs
    )


async def carrier_usage(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, today: date, bundle: SettingsBundle
) -> list[CarrierUsage]:
    """Hesabın son 92 gündeki (iptal olmayan) siparişlerinde görülen `cargoProviderName` x anlaşma çiftleri.

    Arayüz firma adını elle yazdırmaz, buradan önerir (K34: tarife eşlemesi metin birebirdir).
    """
    lower, _ = period_bounds(today - timedelta(days=CARRIER_LOOKBACK_DAYS - 1), today)
    rows = (
        await db.execute(
            select(Order.carrier, Order.who_pays, func.count(OrderLine.id))
            .join(OrderLine, OrderLine.order_id == Order.id)
            .where(
                Order.tenant_id == tenant_id,
                Order.marketplace_account_id == account_id,
                Order.ordered_at >= lower,
                Order.status.notin_(sorted(CANCELLED_STATUSES)),
                OrderLine.removed_at.is_(None),
            )
            .group_by(Order.carrier, Order.who_pays)
        )
    ).all()
    # Anlaşma yalnız `whoPays` ile belirlenir (1 = satıcı anlaşması); null ve diğerleri Trendyol anlaşmalı.
    lines: dict[tuple[str, str], int] = defaultdict(int)
    for carrier, who_pays, count in rows:
        agreement = "seller" if who_pays == SELLER_PAYS_CARGO else "trendyol"
        lines[(carrier or "", agreement)] += int(count)
    return [
        CarrierUsage(carrier, agreement, count, _covers(bundle, agreement, carrier, today))
        for (carrier, agreement), count in sorted(lines.items())
    ]


# --------------------------------------------------------------------------- yazma (K42, K43)
@dataclass(slots=True)
class WriteTicket:
    """`begin_write` sonucu: kilitli hesap satırı ve yazımın alacağı sürüm (henüz uygulanmadı)."""

    row: ProfitSettingsRecord
    previous: int  # güncel sürüm (hesapta hiç ayar yoksa 0)
    created: bool  # hesap satırı bu işlemde oluşturuldu (revision zaten 1)

    @property
    def next(self) -> int:
        return 1 if self.created else self.previous + 1


async def begin_write(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, user_id: UUID, expected: int | None
) -> WriteTicket:
    """Hesabın ayar satırını (yoksa oluşturup) kilitler ve beklenen sürümü doğrular; sürümü ARTIRMAZ.

    Beklenen sürüm verilmişse ve güncel sürümle uyuşmuyorsa `RevisionConflict` (satır yoksa güncel sürüm 0).
    Sürüm yalnız yazım gerçekten bir değişiklik yapıyorsa `finish_write` ile artar: aynı içerikli yazım ve
    onaysız geçmiş değişiklik sürümü artırmaz. Çağıran bu durumlarda işlemi commit ETMEMELİDİR (hesap satırı
    oluşturma da geri alınır).
    """
    created = (
        await db.execute(
            pg_insert(ProfitSettingsRecord)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                marketplace_account_id=account_id,
                default_desi=None,
                revision=1,
                updated_by=user_id,
            )
            .on_conflict_do_nothing(index_elements=["marketplace_account_id"])
            .returning(ProfitSettingsRecord.id)
        )
    ).first() is not None
    row = (
        await db.execute(
            select(ProfitSettingsRecord)
            .where(
                ProfitSettingsRecord.tenant_id == tenant_id,
                ProfitSettingsRecord.marketplace_account_id == account_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    previous = 0 if created else int(row.revision)
    if expected is not None and expected != previous:
        raise RevisionConflict(previous)
    return WriteTicket(row, previous, created)


def finish_write(ticket: WriteTicket, user_id: UUID) -> int:
    """Yazım değişiklik yapıyor: sürümü +1 yapar (aynı işlemde) ve yeni sürümü döndürür."""
    revision = ticket.next
    if not ticket.created:
        ticket.row.revision = revision
        ticket.row.updated_by = user_id
        ticket.row.updated_at = func.now()
    return revision


class PastChangeUnconfirmed(Exception):
    """Geçmişi etkileyen yazım açık onay (`confirm_past_change`) olmadan geldi (K43)."""

    def __init__(self, affects_from: date | None, current_revision: int) -> None:
        super().__init__("past change unconfirmed")
        self.affects_from = affects_from
        self.current_revision = current_revision


class RecordEnded(Exception):
    """Yazım kapanmış (değiştirilmiş/geri çekilmiş) satıra geldi; `current_id` yerini alan etkin satır."""

    def __init__(self, current_id: UUID | None) -> None:
        super().__init__("settings record ended")
        self.current_id = current_id


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """Bir ayar yazımının sonucu (yanıt ve denetim izi bundan kurulur)."""

    action: Literal["created", "replaced", "retracted", "unchanged"]
    revision: int  # yazımdan sonraki güncel ayar sürümü (değişmediyse değişmeyen sürüm)
    affects_from: date | None
    affects_past: bool
    record: Any  # eklenen/yeni satır; geri çekmede kapanan satır; değişmediyse etkin satır; desi için None
    replaced_id: UUID | None = None
    past_change_confirmed: bool = False

    @property
    def changed(self) -> bool:
        return self.action != "unchanged"


def is_past(affects_from: date | None, today: date) -> bool:
    """K43: etki tarihi bugünden (İstanbul günü) önceyse ya da tarihsizse (`None`) geçmişi etkiler."""
    return affects_from is None or affects_from < today


def _confirm(
    ticket: WriteTicket, affects_from: date | None, today: date, confirmed: bool, first_entry: bool
) -> bool:
    """Onay kuralı: geçmişi etkileyen, istisnasız yazım onaysızsa `PastChangeUnconfirmed`.

    Dönüş: günlüğe yazılacak `past_change_confirmed` (geçmişi etkiledi VE kullanıcı onayladı).
    """
    past = is_past(affects_from, today)
    if past and not first_entry and not confirmed:
        raise PastChangeUnconfirmed(affects_from, ticket.previous)
    return past and confirmed


def _journal(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    revision: int,
    item: str,
    action: str,
    outcome: WriteOutcome,
    desi: tuple[Decimal | None, Decimal | None] | None = None,
) -> None:
    """Ayar günlüğüne sürüm başına tek kayıt (tutar yok; varsayılan desi istisna). Aynı işlemde."""
    db.add(
        ProfitSettingsChange(
            id=uuid4(),
            tenant_id=tenant_id,
            marketplace_account_id=account_id,
            revision=revision,
            changed_by=user_id,
            item=item,
            action=action,
            record_id=None if outcome.record is None else outcome.record.id,
            replaced_record_id=outcome.replaced_id,
            affects_from=outcome.affects_from,
            affects_past=outcome.affects_past,
            past_change_confirmed=outcome.past_change_confirmed,
            default_desi_before=None if desi is None else desi[0],
            default_desi_after=None if desi is None else desi[1],
        )
    )


def _now() -> datetime:
    return datetime.fromtimestamp(unix_time(), UTC)


async def _close(
    db: AsyncSession,
    record: Any,
    revision: int,
    user_id: UUID,
    reason: Literal["degistirildi", "geri_cekildi"],
) -> None:
    """Etkin satırı kapatır (yalnız kapanış sütunları; iş alanları değişmez)."""
    record.revision_to = revision
    record.ended_at = _now()
    record.ended_by = user_id
    record.end_reason = reason
    await db.flush()


def _scope(model: Any, tenant_id: UUID, account_id: UUID) -> tuple[Any, Any]:
    return model.tenant_id == tenant_id, model.marketplace_account_id == account_id


async def _active_count(db: AsyncSession, model: Any, tenant_id: UUID, account_id: UUID, *where: Any) -> int:
    """ETKİN satır sayısı (K42: sürüm sınırı kapanmış satırları saymaz; onları hız sınırı sınırlar)."""
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(model)
                .where(*_scope(model, tenant_id, account_id), model.revision_to.is_(None), *where)
            )
        ).scalar_one()
    )


async def get_record(
    db: AsyncSession, model: Any, tenant_id: UUID, account_id: UUID, record_id: UUID
) -> Any | None:
    """Kimlikle satır (etkin ya da kapanmış); başka kiracı ya da hesabın kimliği None."""
    return (
        await db.execute(select(model).where(model.id == record_id, *_scope(model, tenant_id, account_id)))
    ).scalar_one_or_none()


async def _current_id(
    db: AsyncSession, model: Any, tenant_id: UUID, account_id: UUID, record: Any
) -> UUID | None:
    """Kapanmış satırın yerini alan etkin satırın kimliği (zincir izlenir); geri çekilmişse None."""
    current = record
    while current.end_reason != "geri_cekildi":
        successor = (
            await db.execute(
                select(model).where(model.replaces_id == current.id, *_scope(model, tenant_id, account_id))
            )
        ).scalar_one_or_none()
        if successor is None:  # savunma: değiştirilmiş ama halefi olmayan satır olmaz
            return None
        if successor.revision_to is None:
            return UUID(str(successor.id))
        current = successor
    return None


@dataclass(frozen=True, slots=True)
class TariffInput:
    agreement: str
    carrier: str
    valid_from: date
    price_includes_vat: bool
    brackets: tuple[tuple[Decimal, Decimal], ...]


async def write_cargo_tariff(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    ticket: WriteTicket,
    data: TariffInput,
    today: date,
    confirmed: bool,
) -> WriteOutcome:
    """(anlaşma, firma, başlangıç) anahtarıyla ekle / değiştir / değişmedi (K42, K43). Hiçbir şey silinmez."""
    stored = [{"max_desi": format(d, "f"), "price": format(p, "f")} for d, p in data.brackets]
    active = (
        await db.execute(
            select(CargoTariffRecord).where(
                *_scope(CargoTariffRecord, tenant_id, account_id),
                CargoTariffRecord.revision_to.is_(None),
                CargoTariffRecord.agreement == data.agreement,
                CargoTariffRecord.carrier == data.carrier,
                CargoTariffRecord.valid_from == data.valid_from,
            )
        )
    ).scalar_one_or_none()
    affects_from = data.valid_from
    past = is_past(affects_from, today)
    if active is not None:
        if active.price_includes_vat == data.price_includes_vat and bracket_pairs(active) == list(
            data.brackets
        ):
            return WriteOutcome("unchanged", ticket.previous, affects_from, past, active)
        first_entry = False
    else:
        if await _active_count(db, CargoTariffRecord, tenant_id, account_id) >= MAX_TARIFF_VERSIONS:
            raise LimitError(
                "valid_from",
                "too_many_tariff_versions",
                f"Hesap başına en çok {MAX_TARIFF_VERSIONS} tarife sürümü.",
            )
        # İlk giriş istisnası: aynı anlaşmada hiç etkin tarife yok (K43).
        first_entry = not await _active_count(
            db, CargoTariffRecord, tenant_id, account_id, CargoTariffRecord.agreement == data.agreement
        )
    flag = _confirm(ticket, affects_from, today, confirmed, first_entry)
    revision = finish_write(ticket, user_id)
    if active is not None:
        await _close(db, active, revision, user_id, "degistirildi")
    record = CargoTariffRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        marketplace_account_id=account_id,
        agreement=data.agreement,
        carrier=data.carrier,
        valid_from=data.valid_from,
        price_includes_vat=data.price_includes_vat,
        brackets=stored,
        entered_by=user_id,
        revision_from=revision,
        replaces_id=None if active is None else active.id,
    )
    db.add(record)
    await db.flush()
    outcome = WriteOutcome(
        "created" if active is None else "replaced",
        revision,
        affects_from,
        past,
        record,
        None if active is None else active.id,
        flag,
    )
    _journal(
        db,
        tenant_id,
        account_id,
        user_id,
        revision,
        "cargo_tariff",
        "ekle" if active is None else "degistir",
        outcome,
    )
    return outcome


async def write_service_fee(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    ticket: WriteTicket,
    valid_from: date,
    amount: Decimal,
    includes_vat: bool,
    today: date,
    confirmed: bool,
) -> WriteOutcome:
    """Başlangıç tarihiyle ekle / değiştir / değişmedi (K42, K43)."""
    active = (
        await db.execute(
            select(ServiceFeeEstimateRecord).where(
                *_scope(ServiceFeeEstimateRecord, tenant_id, account_id),
                ServiceFeeEstimateRecord.revision_to.is_(None),
                ServiceFeeEstimateRecord.valid_from == valid_from,
            )
        )
    ).scalar_one_or_none()
    past = is_past(valid_from, today)
    if active is not None:
        if active.amount == amount and active.amount_includes_vat == includes_vat:
            return WriteOutcome("unchanged", ticket.previous, valid_from, past, active)
        first_entry = False
    else:
        if (
            await _active_count(db, ServiceFeeEstimateRecord, tenant_id, account_id)
            >= MAX_SERVICE_FEE_VERSIONS
        ):
            raise LimitError(
                "valid_from",
                "too_many_service_fee_versions",
                f"Hesap başına en çok {MAX_SERVICE_FEE_VERSIONS} hizmet bedeli sürümü.",
            )
        # İlk giriş istisnası: hesapta hiç etkin hizmet bedeli tahmini yok (K43).
        first_entry = not await _active_count(db, ServiceFeeEstimateRecord, tenant_id, account_id)
    flag = _confirm(ticket, valid_from, today, confirmed, first_entry)
    revision = finish_write(ticket, user_id)
    if active is not None:
        await _close(db, active, revision, user_id, "degistirildi")
    record = ServiceFeeEstimateRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        marketplace_account_id=account_id,
        valid_from=valid_from,
        amount=amount,
        amount_includes_vat=includes_vat,
        entered_by=user_id,
        revision_from=revision,
        replaces_id=None if active is None else active.id,
    )
    db.add(record)
    await db.flush()
    outcome = WriteOutcome(
        "created" if active is None else "replaced",
        revision,
        valid_from,
        past,
        record,
        None if active is None else active.id,
        flag,
    )
    _journal(
        db,
        tenant_id,
        account_id,
        user_id,
        revision,
        "service_fee_estimate",
        "ekle" if active is None else "degistir",
        outcome,
    )
    return outcome


@dataclass(frozen=True, slots=True)
class ExpenseInput:
    name: str
    kind: str
    amount_excl_vat: Decimal | None
    percent: Decimal | None
    vat_rate: Decimal
    valid_from: date
    valid_to: date | None


def _expense_same(record: VariableExpenseRecord, data: ExpenseInput) -> bool:
    return (
        record.name == data.name
        and record.kind == data.kind
        and record.amount_excl_vat == data.amount_excl_vat
        and record.percent == data.percent
        and record.vat_rate == data.vat_rate
        and record.valid_from == data.valid_from
        and record.valid_to == data.valid_to
    )


def _new_expense(
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    revision: int,
    data: ExpenseInput,
    replaces: VariableExpenseRecord | None,
) -> VariableExpenseRecord:
    return VariableExpenseRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        marketplace_account_id=account_id,
        name=data.name,
        kind=data.kind,
        amount_excl_vat=data.amount_excl_vat,
        percent=data.percent,
        vat_rate=data.vat_rate,
        valid_from=data.valid_from,
        valid_to=data.valid_to,
        entered_by=user_id,
        revision_from=revision,
        replaces_id=None if replaces is None else replaces.id,
        # Tanım sırası korunur: değiştirilen gider listede yerini kaybetmez (motor gider dökümü sırası).
        **({} if replaces is None else {"created_at": replaces.created_at}),
    )


async def create_expense(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    ticket: WriteTicket,
    data: ExpenseInput,
    today: date,
    confirmed: bool,
) -> WriteOutcome:
    """Değişken gider ekler (etkin en çok 50). İlk giriş istisnası yoktur: tanımsız gider 0'dır (K36, K43)."""
    if await _active_count(db, VariableExpenseRecord, tenant_id, account_id) >= MAX_EXPENSES:
        raise LimitError("name", "too_many_expenses", f"Hesap başına en çok {MAX_EXPENSES} değişken gider.")
    flag = _confirm(ticket, data.valid_from, today, confirmed, False)
    revision = finish_write(ticket, user_id)
    record = _new_expense(tenant_id, account_id, user_id, revision, data, None)
    db.add(record)
    await db.flush()
    outcome = WriteOutcome(
        "created", revision, data.valid_from, is_past(data.valid_from, today), record, None, flag
    )
    _journal(db, tenant_id, account_id, user_id, revision, "variable_expense", "ekle", outcome)
    return outcome


async def replace_expense(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    ticket: WriteTicket,
    expense_id: UUID,
    data: ExpenseInput,
    today: date,
    confirmed: bool,
) -> WriteOutcome | None:
    """Gider tanımını değiştirir (eski kapanır, yeni kimlikle yeni satır) ya da değişmedi. Yoksa None (404).

    Kapanmış satıra gelirse `RecordEnded` (yerini alan etkin satır kimliğiyle). Etki tarihi eski ve yeni
    başlangıcın küçüğüdür (K43).
    """
    old = await get_record(db, VariableExpenseRecord, tenant_id, account_id, expense_id)
    if old is None:
        return None
    if old.revision_to is not None:
        raise RecordEnded(await _current_id(db, VariableExpenseRecord, tenant_id, account_id, old))
    affects_from = min(old.valid_from, data.valid_from)
    past = is_past(affects_from, today)
    if _expense_same(old, data):
        return WriteOutcome("unchanged", ticket.previous, affects_from, past, old)
    flag = _confirm(ticket, affects_from, today, confirmed, False)
    revision = finish_write(ticket, user_id)
    await _close(db, old, revision, user_id, "degistirildi")
    record = _new_expense(tenant_id, account_id, user_id, revision, data, old)
    db.add(record)
    await db.flush()
    outcome = WriteOutcome("replaced", revision, affects_from, past, record, old.id, flag)
    _journal(db, tenant_id, account_id, user_id, revision, "variable_expense", "degistir", outcome)
    return outcome


async def retract_record(
    db: AsyncSession,
    model: Any,
    item: str,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    ticket: WriteTicket,
    record_id: UUID,
    today: date,
    confirmed: bool,
) -> WriteOutcome | None:
    """Etkin satırı geri çeker (kapatır, yeni satır yok; eski DELETE'in anlamı). Yoksa None (404).

    Satır tabloda kalır (`end_reason = geri_cekildi`) ve motor onu kullanmaz. Kapanmış satıra `RecordEnded`.
    Etki tarihi satırın başlangıcıdır (K43).
    """
    record = await get_record(db, model, tenant_id, account_id, record_id)
    if record is None:
        return None
    if record.revision_to is not None:
        raise RecordEnded(await _current_id(db, model, tenant_id, account_id, record))
    affects_from = record.valid_from
    flag = _confirm(ticket, affects_from, today, confirmed, False)
    revision = finish_write(ticket, user_id)
    await _close(db, record, revision, user_id, "geri_cekildi")
    outcome = WriteOutcome(
        "retracted", revision, affects_from, is_past(affects_from, today), record, None, flag
    )
    _journal(db, tenant_id, account_id, user_id, revision, item, "geri_cek", outcome)
    return outcome


async def write_default_desi(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    ticket: WriteTicket,
    value: Decimal | None,
    confirmed: bool,
) -> WriteOutcome:
    """Varsayılan desi (tarihsiz: "tüm dönemler", K43). Yerinde güncellenir; önceki ve yeni değer günlüğe.

    Değişmedi: aynı değer. Önceki değer `None` ve yenisi sayı ise ilk giriş istisnasıdır (onay gerekmez).
    """
    before = ticket.row.default_desi
    if before == value:
        return WriteOutcome("unchanged", ticket.previous, None, True, None)
    flag = _confirm(ticket, None, date.min, confirmed, before is None)  # tarihsiz: her zaman geçmişi etkiler
    revision = finish_write(ticket, user_id)
    ticket.row.default_desi = value
    await db.flush()
    action: Literal["created", "replaced", "retracted"]
    if before is None:
        action, journal_action = "created", "ekle"
    elif value is None:
        action, journal_action = "retracted", "geri_cek"
    else:
        action, journal_action = "replaced", "degistir"
    outcome = WriteOutcome(action, revision, None, True, None, None, flag)
    _journal(
        db, tenant_id, account_id, user_id, revision, "defaults", journal_action, outcome, (before, value)
    )
    return outcome


# --------------------------------------------------------------------------- ayar geçmişi (GET /history)
@dataclass(frozen=True, slots=True)
class HistoryEntry:
    change: ProfitSettingsChange
    role: str | None  # değiştiren kullanıcının kiracıdaki rolü (üyelik silindiyse None)
    record: Any | None
    replaced_record: Any | None


@dataclass(frozen=True, slots=True)
class HistoryPage:
    entries: tuple[HistoryEntry, ...]
    next_cursor: int | None


_ITEM_MODELS: dict[str, Any] = {
    "cargo_tariff": CargoTariffRecord,
    "service_fee_estimate": ServiceFeeEstimateRecord,
    "variable_expense": VariableExpenseRecord,
}


async def read_history(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, cursor: int | None, limit: int
) -> HistoryPage:
    """Ayar günlüğü, yeniden eskiye; imleç son görülen sürümdür (sonraki sayfa `revision < cursor`)."""
    query = (
        select(ProfitSettingsChange)
        .where(*_scope(ProfitSettingsChange, tenant_id, account_id))
        .order_by(ProfitSettingsChange.revision.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        query = query.where(ProfitSettingsChange.revision < cursor)
    changes = list((await db.execute(query)).scalars().all())
    more = len(changes) > limit
    changes = changes[:limit]
    wanted: dict[str, set[UUID]] = {item: set() for item in _ITEM_MODELS}
    for c in changes:
        if c.item in wanted:
            wanted[c.item].update(i for i in (c.record_id, c.replaced_record_id) if i is not None)
    records: dict[UUID, Any] = {}
    for item, ids in wanted.items():
        if ids:
            model = _ITEM_MODELS[item]
            rows = (
                await db.execute(
                    select(model).where(model.id.in_(ids), *_scope(model, tenant_id, account_id))
                )
            ).scalars()
            records.update({r.id: r for r in rows})
    users = {c.changed_by for c in changes if c.changed_by is not None}
    roles: dict[UUID, str] = {}
    if users:
        rows2 = (
            await db.execute(
                select(Membership.user_id, Membership.role).where(
                    Membership.tenant_id == tenant_id, Membership.user_id.in_(users)
                )
            )
        ).all()
        roles = {uid: role.value for uid, role in rows2}
    entries = tuple(
        HistoryEntry(
            c,
            None if c.changed_by is None else roles.get(c.changed_by),
            None if c.record_id is None else records.get(c.record_id),
            None if c.replaced_record_id is None else records.get(c.replaced_record_id),
        )
        for c in changes
    )
    return HistoryPage(entries, changes[-1].revision if more and changes else None)
