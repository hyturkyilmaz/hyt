"""Kâr ayarları (ADR-0006, docs/12 K33-K36): doğrulama kuralları, okuma, yazma ve motor ayarına çeviri.

Kurallar tek yerdedir: PUT gövdeleri (`app.api.v1.profit_settings_schemas`) bu işlevleri çağırır. Para ve
oranlar
`Decimal`'dir, float yoktur; saklanan tutar projedeki tek yuvarlama işlevi `app.profit.money.rnd` ile kuruşa
normalleştirilir. Kullanıcı tutarı KDV dahil ya da hariç girebilir; giriş biçimi kayıtta saklanır ve motora
verilirken K02 ile KDV hariçe çevrilir (tutar başına bir yuvarlama): 54,00 dahil -> 45,00; 50,00 -> 41,67;
hizmet bedeli 12,00 dahil -> 10,00.

Yazımlar `profit_settings.revision` ile serileştirilir: her yazım önce hesabın ayar satırını (yoksa oluşturup)
kilitler, beklenen sürümü doğrular ve sürümü +1 yapar; böylece iki yönetici aynı anda düzenlerse biri 409 alır
(sessiz ezme yok) ve hesap başına yazımlar sıraya girer (benzersizlik yarışı olmaz). Commit çağırana aittir.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CargoTariffRecord,
    Order,
    OrderLine,
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


def _two_decimals(value: Decimal) -> bool:
    return value.is_finite() and value == value.quantize(_CENT)


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
    if (
        not value.is_finite()
        or value != value.quantize(_BASIS_POINT)
        or not Decimal(0) < value <= Decimal(100)
    ):
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
    """Bir hesabın tüm ayar kayıtları (hepsi okunur: dönem öncesi son sürüm de gerekir, hacim küçüktür)."""

    default_desi: Decimal | None
    revision: int
    tariffs: tuple[CargoTariffRecord, ...]
    fees: tuple[ServiceFeeEstimateRecord, ...]
    expenses: tuple[VariableExpenseRecord, ...]


async def load_bundle(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> SettingsBundle:
    """Dört tabloyu okur (RLS bağlamı çağıranda kurulu; sorgular ayrıca kiracı ve hesap süzgeci taşır)."""

    def scoped(model: Any) -> tuple[Any, Any]:
        return model.tenant_id == tenant_id, model.marketplace_account_id == account_id

    head = (
        await db.execute(select(ProfitSettingsRecord).where(*scoped(ProfitSettingsRecord)))
    ).scalar_one_or_none()
    tariffs = (
        (
            await db.execute(
                select(CargoTariffRecord)
                .where(*scoped(CargoTariffRecord))
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
                .where(*scoped(ServiceFeeEstimateRecord))
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
                .where(*scoped(VariableExpenseRecord))
                # Tanım sırası (oluşturma sırası): motor çıktısındaki gider dökümü bu sırayı izler.
                .order_by(VariableExpenseRecord.created_at, VariableExpenseRecord.id)
            )
        )
        .scalars()
        .all()
    )
    return SettingsBundle(
        default_desi=None if head is None else head.default_desi,
        revision=0 if head is None else int(head.revision),
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


async def profit_settings_for(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> ProfitSettings:
    """Hesabın kâr ayarları (ADR-0005 §7 tek değişiklik noktası). Hiç kayıt yoksa `ProfitSettings()`."""
    return to_profit_settings(await load_bundle(db, tenant_id, account_id))


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


# --------------------------------------------------------------------------- yazma
async def begin_write(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, user_id: UUID, expected: int | None
) -> tuple[ProfitSettingsRecord, int]:
    """Hesabın ayar satırını (yoksa oluşturup) kilitler, beklenen sürümü doğrular ve sürümü +1 yapar.

    Dönüş: (satır, yeni sürüm). Beklenen sürüm verilmişse ve güncel sürümle uyuşmuyorsa `RevisionConflict`
    (satır yoksa güncel sürüm 0'dır). Çağıran hatada işlemi commit ETMEMELİDİR (oluşturma geri alınır).
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
    if not created:
        row.revision = previous + 1
        row.updated_by = user_id
        row.updated_at = func.now()
    return row, previous + 1


@dataclass(frozen=True, slots=True)
class TariffInput:
    agreement: str
    carrier: str
    valid_from: date
    price_includes_vat: bool
    brackets: tuple[tuple[Decimal, Decimal], ...]


async def upsert_cargo_tariff(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, user_id: UUID, data: TariffInput
) -> tuple[CargoTariffRecord, bool]:
    """(anlaşma, firma, başlangıç) tekilliğiyle upsert; (kayıt, yeni mi). Önceki sürümler silinmez."""
    stored = [{"max_desi": format(d, "f"), "price": format(p, "f")} for d, p in data.brackets]
    record = (
        await db.execute(
            select(CargoTariffRecord).where(
                CargoTariffRecord.tenant_id == tenant_id,
                CargoTariffRecord.marketplace_account_id == account_id,
                CargoTariffRecord.agreement == data.agreement,
                CargoTariffRecord.carrier == data.carrier,
                CargoTariffRecord.valid_from == data.valid_from,
            )
        )
    ).scalar_one_or_none()
    if record is not None:
        record.price_includes_vat = data.price_includes_vat
        record.brackets = stored
        record.entered_by = user_id
        record.updated_at = func.now()
        await db.flush()
        return record, False
    versions = (
        await db.execute(
            select(func.count())
            .select_from(CargoTariffRecord)
            .where(
                CargoTariffRecord.tenant_id == tenant_id,
                CargoTariffRecord.marketplace_account_id == account_id,
            )
        )
    ).scalar_one()
    if versions >= MAX_TARIFF_VERSIONS:
        raise LimitError(
            "valid_from",
            "too_many_tariff_versions",
            f"Hesap başına en çok {MAX_TARIFF_VERSIONS} tarife sürümü.",
        )
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
    )
    db.add(record)
    await db.flush()
    return record, True


async def upsert_service_fee(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    valid_from: date,
    amount: Decimal,
    includes_vat: bool,
) -> tuple[ServiceFeeEstimateRecord, bool]:
    """Başlangıç tarihiyle upsert; (kayıt, yeni mi)."""
    record = (
        await db.execute(
            select(ServiceFeeEstimateRecord).where(
                ServiceFeeEstimateRecord.tenant_id == tenant_id,
                ServiceFeeEstimateRecord.marketplace_account_id == account_id,
                ServiceFeeEstimateRecord.valid_from == valid_from,
            )
        )
    ).scalar_one_or_none()
    if record is not None:
        record.amount = amount
        record.amount_includes_vat = includes_vat
        record.entered_by = user_id
        record.updated_at = func.now()
        await db.flush()
        return record, False
    record = ServiceFeeEstimateRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        marketplace_account_id=account_id,
        valid_from=valid_from,
        amount=amount,
        amount_includes_vat=includes_vat,
        entered_by=user_id,
    )
    db.add(record)
    await db.flush()
    return record, True


@dataclass(frozen=True, slots=True)
class ExpenseInput:
    name: str
    kind: str
    amount_excl_vat: Decimal | None
    percent: Decimal | None
    vat_rate: Decimal
    valid_from: date
    valid_to: date | None


async def create_expense(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, user_id: UUID, data: ExpenseInput
) -> VariableExpenseRecord:
    count = (
        await db.execute(
            select(func.count())
            .select_from(VariableExpenseRecord)
            .where(
                VariableExpenseRecord.tenant_id == tenant_id,
                VariableExpenseRecord.marketplace_account_id == account_id,
            )
        )
    ).scalar_one()
    if count >= MAX_EXPENSES:
        raise LimitError("name", "too_many_expenses", f"Hesap başına en çok {MAX_EXPENSES} değişken gider.")
    record = VariableExpenseRecord(
        id=uuid4(), tenant_id=tenant_id, marketplace_account_id=account_id, entered_by=user_id
    )
    _fill_expense(record, data)
    db.add(record)
    await db.flush()
    return record


def _fill_expense(record: VariableExpenseRecord, data: ExpenseInput) -> None:
    record.name = data.name
    record.kind = data.kind
    record.amount_excl_vat = data.amount_excl_vat
    record.percent = data.percent
    record.vat_rate = data.vat_rate
    record.valid_from = data.valid_from
    record.valid_to = data.valid_to


async def update_expense(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    expense_id: UUID,
    data: ExpenseInput,
) -> VariableExpenseRecord | None:
    """Kaydı yerinde günceller (tutar değişikliği için eskinin bitişi + yeni kayıt da önerilir, K36)."""
    record = await get_expense(db, tenant_id, account_id, expense_id)
    if record is None:
        return None
    _fill_expense(record, data)
    record.entered_by = user_id
    record.updated_at = func.now()
    await db.flush()
    return record


async def get_expense(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, expense_id: UUID
) -> VariableExpenseRecord | None:
    return (
        await db.execute(
            select(VariableExpenseRecord).where(
                VariableExpenseRecord.id == expense_id,
                VariableExpenseRecord.tenant_id == tenant_id,
                VariableExpenseRecord.marketplace_account_id == account_id,
            )
        )
    ).scalar_one_or_none()


async def delete_version(
    db: AsyncSession, model: Any, tenant_id: UUID, account_id: UUID, record_id: UUID
) -> bool:
    """Tek bir sürümü/kaydı siler (yalnız istenen kayıt; geçmişin geri kalanı korunur). Bulunamazsa False."""
    deleted = await db.execute(
        delete(model)
        .where(
            model.id == record_id,
            model.tenant_id == tenant_id,
            model.marketplace_account_id == account_id,
        )
        .returning(model.id)
    )
    return deleted.first() is not None
