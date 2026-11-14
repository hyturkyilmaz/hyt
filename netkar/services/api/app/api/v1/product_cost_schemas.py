"""Ürün maliyeti uç noktalarının istek ve yanıt şemaları.

Para ve oranlar JSON'da DECIMAL DİZGESİ (örn. "12.50") olarak döner; `vat_rate` tamsayı yüzdedir.
Girdide JSON sayısı (12.5) veya dizge ("12.50") kabul edilir; float aritmetiği yapılmaz (en kısa gösterim
Decimal'e çevrilir) ve 2'den fazla ondalık reddedilir.
"""

from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, field_validator
from pydantic_core import PydanticCustomError

from app.core.clock import today_istanbul
from app.services.product_costs import (
    RuleError,
    check_unit_cost,
    check_valid_from,
    check_vat_rate,
)

# Yalnız ASCII rakam (\d Unicode rakamları da eşler; denetim S3 B-01).
_PLAIN_DECIMAL = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,10})?")


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


def _rule(check: Any, value: Decimal) -> Decimal:
    try:
        result: Decimal = check(value)
    except RuleError as exc:
        raise PydanticCustomError(exc.code, exc.message) from None
    return result


def _cost_rule(value: Decimal) -> Decimal:
    return _rule(check_unit_cost, value)


def _vat_rule(value: Decimal) -> Decimal:
    return _rule(check_vat_rate, value)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CostUpsertIn(_Strict):
    # Tarih: JSON'da yalnız "YYYY-AA-GG" dizgesi (sayısal zaman damgası kabul edilmez).
    valid_from: Annotated[date, BeforeValidator(_require_text)]
    unit_cost_excl_vat: Annotated[Decimal, BeforeValidator(_coerce_decimal), AfterValidator(_cost_rule)]
    vat_rate: Annotated[Decimal, BeforeValidator(_coerce_decimal), AfterValidator(_vat_rule)]

    @field_validator("valid_from")
    @classmethod
    def _valid_from_range(cls, value: date) -> date:
        try:
            return check_valid_from(value, today_istanbul())
        except RuleError as exc:
            raise PydanticCustomError(exc.code, exc.message) from None


class CostOut(BaseModel):
    valid_from: date
    unit_cost_excl_vat: Decimal
    vat_rate: int


class ProductItemOut(BaseModel):
    barcode: str
    title: str | None
    stock_code: str | None
    current_cost: CostOut | None
    cost_missing: bool


class ProductListOut(BaseModel):
    items: list[ProductItemOut]
    next_cursor: str | None


class CostHistoryOut(BaseModel):
    barcode: str
    product_known: bool
    items: list[CostOut]


class CostUpsertOut(BaseModel):
    barcode: str
    product_known: bool
    created: bool
    cost: CostOut


class ImportIssueOut(BaseModel):
    row: int
    column: str
    message: str
    value: str | None


class ImportReportOut(BaseModel):
    dry_run: bool
    committed: bool
    format: str
    total: int
    valid: int
    invalid: int
    skipped: int
    unknown_barcodes: int
    created: int | None
    updated: int | None
    errors: list[ImportIssueOut]
    errors_truncated: bool
    ignored_columns: list[str]
