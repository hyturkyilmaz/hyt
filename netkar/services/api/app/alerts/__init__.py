"""Uyarı kuralları (ADR-0009 D1): saf, veritabanı ve I/O yok.

Kurallar motor sonucunu (`app.profit`) ve sayımları okur, aday olay değerleri üretir. Kalıcılık, değerlendirme
işi ve bildirim teslimatı sonraki dilimlerdir.
"""

from app.alerts.rules import (
    ReturnCohort,
    evaluate_ad_eats_profit,
    evaluate_loss_making_sales,
    evaluate_return_rate,
    evaluate_unexpected_deduction,
)
from app.alerts.settings import AlertThresholds
from app.alerts.suppression import loss_notification_due, reminder_due, reopen_is_silent
from app.alerts.types import (
    ACCOUNT_SUBJECT,
    AlertCandidate,
    AlertRule,
    AlertScope,
    NotifyMode,
    RuleOutcome,
    RuleStatus,
    Severity,
    dedupe_key,
    normalize_account_id,
    order_line_subject,
    product_subject,
)

__all__ = [
    "ACCOUNT_SUBJECT",
    "AlertCandidate",
    "AlertRule",
    "AlertScope",
    "AlertThresholds",
    "NotifyMode",
    "ReturnCohort",
    "RuleOutcome",
    "RuleStatus",
    "Severity",
    "dedupe_key",
    "evaluate_ad_eats_profit",
    "evaluate_loss_making_sales",
    "evaluate_return_rate",
    "evaluate_unexpected_deduction",
    "loss_notification_due",
    "normalize_account_id",
    "order_line_subject",
    "product_subject",
    "reminder_due",
    "reopen_is_silent",
]
