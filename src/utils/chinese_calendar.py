"""Trading day detection using chinese-calendar."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import chinese_calendar

SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    """Return the current timezone-aware datetime for mainland China."""
    return datetime.now(SHANGHAI_TIMEZONE)


def shanghai_today() -> date:
    """Return the current mainland-China calendar date."""
    return shanghai_now().date()


def is_trading_day(d: date | None = None) -> bool:
    """Check if a given date is an A-share trading day.

    A trading day is a weekday that is not a Chinese public holiday.
    """
    if d is None:
        d = shanghai_today()
    # Weekend check
    if d.weekday() >= 5:
        return False
    # Chinese public holiday check
    try:
        return not chinese_calendar.is_holiday(d)
    except NotImplementedError:
        # chinese-calendar may not cover far-future dates
        return d.weekday() < 5
