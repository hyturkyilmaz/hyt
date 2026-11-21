"""Eşik ayar nesnesi (H9 önerisi, kiracı ezmesi) ve bastırma kararları (ADR-0009 §3, §12 madde 2)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.alerts import AlertThresholds, loss_notification_due, reminder_due, reopen_is_silent
from app.profit.settings import WarningThresholds

D = Decimal
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def test_defaults_are_the_h9_proposal() -> None:
    t = AlertThresholds()
    assert t.loss_min_amount == D("5.00")
    assert t.ad_share_percent == D("100")
    assert t.ad_min_spend == D("50.00")
    assert t.deduction_notify_min == D("10.00")
    assert t.return_min_diff_points == D("5")
    assert t.notify_default_desi_deductions is False


def test_settings_are_frozen_and_do_not_touch_engine_thresholds() -> None:
    t = AlertThresholds()
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.loss_min_amount = D("1")  # type: ignore[misc]
    engine = WarningThresholds()
    assert (engine.unexpected_deduction_amount, engine.unexpected_deduction_percent) == (D("5.00"), D("5"))


def test_overrides_replace_only_given_values() -> None:
    base = AlertThresholds()
    assert base.with_overrides(None) is base
    assert base.with_overrides({}) is base
    changed = base.with_overrides(
        {"loss_min_amount": D("0.00"), "ad_min_spend": None, "ad_share_percent": D("50")}
    )
    assert changed.loss_min_amount == D("0.00")
    assert changed.ad_share_percent == D("50")
    assert changed.ad_min_spend == D("50.00")  # None varsayılanı korur
    assert base.loss_min_amount == D("5.00")  # asıl nesne değişmez


def test_unknown_override_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="bilinmeyen eşik"):
        AlertThresholds().with_overrides({"alpha": D("0.05")})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"loss_min_amount": D("-0.01")},
        {"ad_min_spend": D("-1")},
        {"deduction_notify_min": D("-1")},
        {"ad_share_percent": D("49.99")},
        {"ad_share_percent": D("100.01")},
        {"return_min_diff_points": D("-1")},
        {"return_min_diff_points": D("100.01")},
    ],
)
def test_out_of_range_values_are_rejected(kwargs: dict[str, Decimal]) -> None:
    with pytest.raises(ValueError, match=r"olmalı|olamaz"):
        AlertThresholds(**kwargs)  # type: ignore[arg-type]


def test_override_types_and_scale_are_checked() -> None:
    base = AlertThresholds()
    for field in ("loss_min_amount", "ad_share_percent", "ad_min_spend", "deduction_notify_min"):
        for bad in (True, 7, 7.5, "7"):
            with pytest.raises(TypeError, match="Decimal olmalı"):
                base.with_overrides({field: bad})  # type: ignore[dict-item]
    with pytest.raises(TypeError, match="Decimal olmalı"):
        AlertThresholds(return_min_diff_points=5)  # type: ignore[arg-type]
    for bad_bool in (D("1"), 1, "yes"):
        with pytest.raises(TypeError, match="bool olmalı"):
            base.with_overrides({"notify_default_desi_deductions": bad_bool})  # type: ignore[dict-item]
    assert (
        base.with_overrides({"notify_default_desi_deductions": True}).notify_default_desi_deductions is True
    )
    # ölçek: en çok 2 ondalık (numeric(14,2)); sonlu; üst sınır
    with pytest.raises(ValueError, match="en çok 2 ondalıklı"):
        base.with_overrides({"loss_min_amount": D("1.001")})
    with pytest.raises(ValueError, match="sonlu"):
        base.with_overrides({"ad_min_spend": D("NaN")})
    with pytest.raises(ValueError, match="sonlu"):
        base.with_overrides({"ad_min_spend": D("Infinity")})
    with pytest.raises(ValueError, match="sınırını"):
        base.with_overrides({"deduction_notify_min": D("1e12")})
    assert base.with_overrides({"loss_min_amount": D("1.10")}).loss_min_amount == D("1.10")


def test_range_edges_are_allowed() -> None:
    AlertThresholds(ad_share_percent=D("50"), return_min_diff_points=D("0"), loss_min_amount=D("0"))
    AlertThresholds(ad_share_percent=D("100"), return_min_diff_points=D("100"))


# --------------------------------------------------------------------------- bastırma
def test_loss_renotifies_only_at_double_the_last_notified_amount_and_only_once() -> None:
    assert loss_notification_due(D("10.00"), None) is True  # hiç bildirilmedi
    assert loss_notification_due(D("19.00"), D("10.00")) is False  # 1,9 kat
    assert loss_notification_due(D("19.99"), D("10.00")) is False
    assert loss_notification_due(D("20.00"), D("10.00")) is True  # tam 2 kat
    assert loss_notification_due(D("35.00"), D("10.00")) is True
    # "Bir kez daha": yeniden bildirimden sonra 2x, 4x, 8x için ek bildirim yok.
    assert loss_notification_due(D("40.00"), D("20.00"), renotified=True) is False
    assert loss_notification_due(D("400.00"), D("20.00"), renotified=True) is False
    # Hiç bildirilmemişse bayrak anlamsızdır (ilk bildirim).
    assert loss_notification_due(D("5.00"), None, renotified=True) is True


def test_reminder_after_fourteen_days() -> None:
    assert reminder_due(None, NOW) is True
    assert reminder_due(NOW - timedelta(days=13, hours=23), NOW) is False
    assert reminder_due(NOW - timedelta(days=14), NOW) is True
    assert reminder_due(NOW - timedelta(days=3), NOW, interval_days=2) is True


def test_reopen_within_seven_days_is_silent() -> None:
    assert reopen_is_silent(NOW - timedelta(days=6, hours=23), NOW) is True
    assert reopen_is_silent(NOW - timedelta(days=7), NOW) is False
