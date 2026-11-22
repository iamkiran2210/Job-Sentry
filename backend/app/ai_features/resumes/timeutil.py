from __future__ import annotations

from datetime import datetime, timezone

from app.models.base import utc_now as utcnow  # noqa: F401  (re-export: one clock for the module)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; PostgreSQL returns aware ones."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
