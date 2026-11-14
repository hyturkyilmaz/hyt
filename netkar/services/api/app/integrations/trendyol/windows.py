"""Tarih penceresi yardımcıları (saf işlevler)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.integrations.trendyol.errors import TrendyolValidationError

_ONE_MS = timedelta(milliseconds=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def to_epoch_ms(moment: datetime) -> int:
    """Saat dilimli datetime'ı Unix milisaniyesine çevirir; naive değer reddedilir."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise TrendyolValidationError("tarih saat dilimi içermeli")
    return (moment.astimezone(UTC) - _EPOCH) // _ONE_MS


def check_order(start: datetime, end: datetime, label: str) -> None:
    """Aralığın saat dilimli ve sıralı olduğunu doğrular (üst sınır aranmaz)."""
    to_epoch_ms(start)
    to_epoch_ms(end)
    if end < start:
        raise TrendyolValidationError(f"{label}: bitiş başlangıçtan önce olamaz")


def check_span(start: datetime, end: datetime, max_span: timedelta, label: str) -> None:
    """Tek istekte kullanılacak aralığın sırasını ve uzunluğunu doğrular."""
    check_order(start, end, label)
    if end - start > max_span:
        raise TrendyolValidationError(f"{label}: aralık en fazla {max_span.days} gün olabilir")


def split_window(start: datetime, end: datetime, max_span: timedelta) -> list[tuple[datetime, datetime]]:
    """[start, end] aralığını her biri `max_span`'den KISA ardışık pencerelere böler.

    Her pencerenin uzunluğu en fazla `max_span - 1 ms`'dir ("15 günden uzun olamaz" kuralının tam
    sınırında 400 riskine girilmez). Komşu pencereler sınır anını paylaşır (bir pencerenin bitişi
    sonrakinin başlangıcıdır): uç değerlerin dahil/hariç olması doğrulanmadığı için boşluk bırakmak
    yerine sınırda yinelenen kayıt tercih edilir; tüketici kayıtları kimliğiyle tekilleştirmelidir.
    """
    to_epoch_ms(start)
    to_epoch_ms(end)
    if end < start:
        raise TrendyolValidationError("bitiş başlangıçtan önce olamaz")
    step = max_span - _ONE_MS
    if step <= timedelta(0):
        raise TrendyolValidationError("pencere uzunluğu çok kısa")
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while True:
        window_end = min(cursor + step, end)
        windows.append((cursor, window_end))
        if window_end >= end:
            return windows
        cursor = window_end
