"""Bildirim bastırma kararları (ADR-0009 §3). Saf: saat dışarıdan verilir, burada okunmaz."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

# ZARARINA_SATIS: toplam zarar son bildirilen değerin bu katına çıkarsa bir kez daha bildirilir.
LOSS_RENOTIFY_FACTOR = 2
# REKLAM_KARI_YIYOR ve IADE_ORANI_ARTISI: yeniden bildirim en erken bu kadar gün sonra.
REMINDER_DAYS = 14
# ZARARINA_SATIS: çözülmüş olay bu süre içinde yeniden açılırsa bildirim gitmez, yalnız panelde açılır.
REOPEN_SILENT_DAYS = 7


def loss_notification_due(
    total_loss: Decimal, notified_amount: Decimal | None, *, renotified: bool = False
) -> bool:
    """ZARARINA_SATIS bildirim kararı: ilk bildirim bir kez, yeniden bildirim yalnız TEK sefer.

    Hiç bildirilmediyse True. Daha önce yeniden bildirildiyse (`renotified`) False: 4 kat, 8 kat için ek
    bildirim yok (ADR: "bir kez daha"). Aksi halde zarar son bildirilenin 2 katına ulaştıysa (>=) True.
    """
    if notified_amount is None:
        return True
    if renotified:
        return False
    return total_loss >= notified_amount * LOSS_RENOTIFY_FACTOR


def reminder_due(
    last_notified_at: datetime | None, now: datetime, interval_days: int = REMINDER_DAYS
) -> bool:
    """Hiç bildirilmediyse ya da son bildirimden en az `interval_days` gün geçtiyse True."""
    if last_notified_at is None:
        return True
    return now - last_notified_at >= timedelta(days=interval_days)


def reopen_is_silent(resolved_at: datetime, now: datetime) -> bool:
    """Çözülmüş olayın 7 gün içinde yeniden açılması sessizdir (yalnız panel)."""
    return now - resolved_at < timedelta(days=REOPEN_SILENT_DAYS)
