"""Kâr ayarları uç noktalarının istek ve yanıt şemaları (ADR-0006 §3.3).

Para ve oranlar JSON'da DECIMAL DİZGESİ (örn. "45.00") olarak döner. Girdide JSON sayısı (45.5) ya da dizge
("45.50") kabul edilir; float aritmetiği yapılmaz (en kısa gösterim Decimal'e çevrilir). Doğrulama hataları
RFC 9457 `errors: [{field, code}]` biçimindedir ve girdi değerini ASLA yansıtmaz.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.core.clock import today_istanbul
from app.services import profit_settings as ps
from app.services.product_costs import RuleError, check_valid_from

# İşaretli, yalnız ASCII rakam (aralık dışı değer `*_out_of_range` koduyla reddedilir; denetim S3 B-01).
_PLAIN_DECIMAL = re.compile(r"-?[0-9]{1,15}(?:\.[0-9]{1,10})?")
# Onay tarihi: sorgu parametresindeki katı desenle aynı (YYYY-AA-GG; saat dilimli tarih-saat ve sayısal zaman
# damgası pydantic esnek kipinde kabul edilirdi, YK-04).
_STRICT_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

Agreement = Literal["trendyol", "seller"]
ExpenseKindName = Literal["siparis_basi", "adet_basi", "satis_yuzdesi"]


def _coerce_decimal(value: Any) -> Any:
    """float ve bool para değeri olamaz; JSON sayısı en kısa gösterimiyle, dizge sade biçimle Decimal olur."""
    if isinstance(value, bool):
        raise PydanticCustomError("decimal_invalid", "Sayı olmalıdır.")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PydanticCustomError("decimal_invalid", "Sayı olmalıdır.")
        return Decimal(repr(value))
    if isinstance(value, str):
        if not _PLAIN_DECIMAL.fullmatch(value):
            raise PydanticCustomError("decimal_invalid", "Sayı olmalıdır (örn. 12.50).")
        return Decimal(value)
    return value


def _require_text(value: Any) -> Any:
    if not isinstance(value, str):
        raise PydanticCustomError("date_type", "Tarih YYYY-AA-GG dizgesi olmalıdır.")
    return value


def _require_strict_date(value: Any) -> Any:
    """`confirm_affects_from` gövde alanı: yalnız `all` ya da tam `YYYY-AA-GG` dizgesi (sorguyla aynı sözleşme)."""
    if value is None or value == "all":
        return value
    text = _require_text(value)
    if not _STRICT_DATE.fullmatch(text):
        raise PydanticCustomError("date_invalid", "Tarih YYYY-AA-GG olmalıdır (ya da all).")
    return text


def _run[T](check: Any, value: T) -> T:
    try:
        result: T = check(value)
    except RuleError as exc:
        raise PydanticCustomError(exc.code, exc.message) from None
    except ArithmeticError:
        # Genel güvence (AD-01): kuraldan kaçan `decimal.InvalidOperation` 500 değil doğrulama hatasıdır.
        raise PydanticCustomError("decimal_invalid", "Sayı geçersiz ya da çok büyük.") from None
    return result


def _valid_from_rule(value: date) -> date:
    return _run(lambda v: check_valid_from(v, today_istanbul()), value)


Money = Annotated[Decimal, BeforeValidator(_coerce_decimal)]
ValidFrom = Annotated[date, BeforeValidator(_require_text), AfterValidator(_valid_from_rule)]
OptionalDate = Annotated[date | None, BeforeValidator(lambda v: v if v is None else _require_text(v))]
Carrier = Annotated[str, AfterValidator(lambda v: _run(ps.check_carrier, v))]
ExpectedRevision = Annotated[int | None, Field(ge=0, le=2**62)]
# K43: geçmişi etkileyen yazım için açık onay (ilk giriş istisnası dışında onaysız 409).
# YT-07: onay etki tarihine bağlıdır; çıplak `confirm_past_change` artık yetmez (geriye uyum için kabul edilir,
# karara etkisi yoktur).
ConfirmPastChange = Annotated[
    bool,
    Field(
        description=(
            "KULLANIMDAN KALKTI: tek başına onay SAYILMAZ. Onay `confirm_affects_from` ile verilir "
            "(ADR-0007 §5.1)."
        )
    ),
]
ConfirmAffectsFrom = Annotated[
    date | Literal["all"] | None,
    BeforeValidator(_require_strict_date),
    Field(
        description=(
            "Geçmiş raporların değişeceğinin onayı (K43): 409 `settings-past-change-unconfirmed` gövdesindeki "
            "`affects_from` tarihi (YYYY-AA-GG) geri gönderilir, tarihsiz değişiklikte (`affects_from` null) "
            "`all`. Sunucunun hesapladığı etki tarihiyle eşleşmezse yeniden 409."
        )
    ),
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BracketIn(_Strict):
    max_desi: Annotated[
        Decimal, BeforeValidator(_coerce_decimal), AfterValidator(lambda v: _run(ps.check_desi, v))
    ]
    price: Annotated[
        Decimal, BeforeValidator(_coerce_decimal), AfterValidator(lambda v: _run(ps.check_price, v))
    ]


class CargoTariffIn(_Strict):
    agreement: Agreement
    carrier: Carrier
    valid_from: ValidFrom
    price_includes_vat: bool
    brackets: list[BracketIn]
    expected_revision: ExpectedRevision = None
    confirm_past_change: ConfirmPastChange = False
    confirm_affects_from: ConfirmAffectsFrom = None

    @field_validator("brackets")
    @classmethod
    def _brackets_rule(cls, value: list[BracketIn]) -> list[BracketIn]:
        _run(ps.check_brackets, [(b.max_desi, b.price) for b in value])
        return value


class ServiceFeeIn(_Strict):
    valid_from: ValidFrom
    amount: Annotated[
        Decimal,
        BeforeValidator(_coerce_decimal),
        AfterValidator(lambda v: _run(ps.check_service_fee_amount, v)),
    ]
    amount_includes_vat: bool
    expected_revision: ExpectedRevision = None
    confirm_past_change: ConfirmPastChange = False
    confirm_affects_from: ConfirmAffectsFrom = None


class VariableExpenseIn(_Strict):
    name: Annotated[str, AfterValidator(lambda v: _run(ps.check_expense_name, v))]
    kind: ExpenseKindName
    amount_excl_vat: Annotated[
        Decimal | None,
        BeforeValidator(lambda v: v if v is None else _coerce_decimal(v)),
        AfterValidator(lambda v: v if v is None else _run(ps.check_expense_amount, v)),
    ] = None
    percent: Annotated[
        Decimal | None,
        BeforeValidator(lambda v: v if v is None else _coerce_decimal(v)),
        AfterValidator(lambda v: v if v is None else _run(ps.check_percent, v)),
    ] = None
    vat_rate: Annotated[
        Decimal,
        BeforeValidator(_coerce_decimal),
        AfterValidator(lambda v: _run(ps.check_expense_vat_rate, v)),
    ]
    valid_from: ValidFrom
    valid_to: OptionalDate = None
    expected_revision: ExpectedRevision = None
    confirm_past_change: ConfirmPastChange = False
    confirm_affects_from: ConfirmAffectsFrom = None

    @field_validator("valid_to")
    @classmethod
    def _valid_to_rule(cls, value: date | None, info: Any) -> date | None:
        start = info.data.get("valid_from")
        if start is not None:  # başlangıç geçersizse o alan zaten hata verdi
            _run(lambda v: ps.check_valid_to(start, v), value)
        return value

    @model_validator(mode="after")
    def _kind_rule(self) -> VariableExpenseIn:
        # Gövde düzeyi kural (alan boş): tip ile tutar/oran uyumu.
        _run(lambda _: ps.check_kind_amount(self.kind, self.amount_excl_vat, self.percent), None)
        return self


class DefaultsIn(_Strict):
    default_desi: Annotated[
        Decimal | None,
        BeforeValidator(lambda v: v if v is None else _coerce_decimal(v)),
        AfterValidator(lambda v: v if v is None else _run(ps.check_desi, v)),
    ]
    expected_revision: ExpectedRevision = None
    confirm_past_change: ConfirmPastChange = False
    confirm_affects_from: ConfirmAffectsFrom = None


# --------------------------------------------------------------------------- yanıtlar
class BracketOut(BaseModel):
    max_desi: Decimal
    price: Decimal
    price_excl_vat: Decimal


class CargoTariffOut(BaseModel):
    id: str
    agreement: Agreement
    carrier: str
    valid_from: date
    price_includes_vat: bool
    brackets: list[BracketOut]


class ServiceFeeOut(BaseModel):
    id: str
    valid_from: date
    amount: Decimal
    amount_includes_vat: bool
    amount_excl_vat: Decimal


class VariableExpenseOut(BaseModel):
    id: str
    name: str
    kind: ExpenseKindName
    amount_excl_vat: Decimal | None
    percent: str | None
    vat_rate: int
    valid_from: date
    valid_to: date | None


class CompletenessOut(BaseModel):
    """ "Bugün geçerli bir sürüm var mı" bayrakları (ADR-0006 §3.3)."""

    cargo_tariff_defined: bool
    seller_cargo_tariff_defined: bool
    service_fee_estimate_defined: bool
    variable_expenses_defined: bool
    default_desi_defined: bool


class VatRatesOut(BaseModel):
    """Motorun kargo ve platform hizmet bedeli için kullandığı KDV oranları (yüzde, Decimal dizgesi)."""

    shipping: Decimal
    service_fee: Decimal


class SettingsOut(BaseModel):
    revision: int
    default_desi: Decimal | None
    cargo_tariffs: list[CargoTariffOut]
    service_fee_estimates: list[ServiceFeeOut]
    variable_expenses: list[VariableExpenseOut]
    completeness: CompletenessOut
    # Panelin başlangıç tarihi önerisi, "bugün" ve KDV hariç karşılık hesabı için sunucu değerleri.
    earliest_order_day: date | None
    today_istanbul: date
    vat_rates: VatRatesOut


class CarrierOut(BaseModel):
    carrier: str
    agreement: Agreement
    line_count: int
    covered: bool


class CarriersOut(BaseModel):
    lookback_days: int
    items: list[CarrierOut]


WriteAction = Literal["created", "replaced", "retracted", "unchanged"]


class WriteInfo(BaseModel):
    """Her yazım yanıtının ortak alanları (K42, K43). `changed = false`: içerik aynıydı, hiçbir şey yazılmadı."""

    revision: int
    changed: bool
    action: WriteAction
    replaced_id: str | None
    affects_from: date | None
    affects_past: bool


class TariffWriteOut(WriteInfo):
    created: bool  # `action == "created"` ile aynı (bir sürüm boyunca korunur)
    tariff: CargoTariffOut


class ServiceFeeWriteOut(WriteInfo):
    created: bool
    estimate: ServiceFeeOut


class ExpenseWriteOut(WriteInfo):
    expense: VariableExpenseOut


class DefaultsOut(WriteInfo):
    default_desi: Decimal | None


class DeleteOut(WriteInfo):
    """Geri çekme (eski DELETE): satır silinmez, `end_reason = geri_cekildi` ile kapanır."""


class ChangedByOut(BaseModel):
    """Değiştiren kullanıcı: kimlik ve kiracıdaki rol (üyeler listesindeki gibi; ad ve e-posta tutulmaz)."""

    user_id: str
    role: str | None


class HistoryItemOut(BaseModel):
    """Ayar günlüğü kaydı (ADR-0007 §5.1). `record` ve `replaced_record` satırın tam içeriğidir."""

    revision: int
    changed_at: datetime
    changed_by: ChangedByOut | None
    item: Literal["cargo_tariff", "service_fee_estimate", "variable_expense", "defaults", "tasima"]
    action: Literal["ekle", "degistir", "geri_cek", "tasima"]
    affects_from: date | None
    affects_past: bool
    past_change_confirmed: bool
    record: CargoTariffOut | ServiceFeeOut | VariableExpenseOut | None
    replaced_record: CargoTariffOut | ServiceFeeOut | VariableExpenseOut | None
    default_desi_before: Decimal | None
    default_desi_after: Decimal | None


class HistoryOut(BaseModel):
    items: list[HistoryItemOut]
    next_cursor: str | None
