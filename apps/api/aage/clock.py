"""Jam aplikasi. Bisa digeser lewat context var agar seed demo bisa membuat riwayat 14 hari
tanpa pernah mengubah baris Ledger yang sudah ada (Ledger tetap append-only).

Saat digeser, jam tetap berjalan sesuai waktu nyata sejak titik geser, sehingga latensi
yang tercatat adalah waktu proses sebenarnya."""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))

_override: ContextVar[tuple[datetime, float] | None] = ContextVar("aage_clock_override", default=None)


def now() -> datetime:
    value = _override.get()
    if value is None:
        return datetime.now(timezone.utc)
    moment, started = value
    return moment + timedelta(seconds=time.perf_counter() - started)


@contextmanager
def frozen_at(moment: datetime):
    token = _override.set((moment, time.perf_counter()))
    try:
        yield
    finally:
        _override.reset(token)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite mengembalikan datetime tanpa zona; semua waktu disimpan dalam UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
