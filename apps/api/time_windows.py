"""Time-window helpers shared by the public stats endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))


def bj_today_start_utc(now: datetime) -> datetime:
    """UTC instant of the current Beijing-time midnight.

    All public "today" statistics use the Beijing-day window to match the
    collector's operating window, regardless of the server's own timezone.
    """
    bj_now = now.astimezone(BJT)
    return bj_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        UTC
    )


def ensure_aware(value: datetime) -> datetime:
    """Coerce a possibly-naive DB timestamp to aware UTC.

    SQLite drops the timezone offset on DateTime(timezone=True) columns, so
    values read back naive; treat them as UTC (the application writes UTC).
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
