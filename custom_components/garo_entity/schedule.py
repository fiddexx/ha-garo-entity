"""Pure helpers for the optional local current-limit schedule."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .const import (
    CONF_SCHEDULE_DEFAULT_LIMIT,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_MONTHS,
    CONF_SCHEDULE_PEAK_LIMIT,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_WEEKDAYS,
    DEFAULT_SCHEDULE_DEFAULT_LIMIT,
    DEFAULT_SCHEDULE_END,
    DEFAULT_SCHEDULE_MONTHS,
    DEFAULT_SCHEDULE_PEAK_LIMIT,
    DEFAULT_SCHEDULE_START,
    DEFAULT_SCHEDULE_WEEKDAYS,
)


def scheduled_limit(options: dict[str, Any], now: datetime) -> tuple[int, bool]:
    """Return the desired current limit and whether the peak rule is active."""
    default_limit = int(
        options.get(CONF_SCHEDULE_DEFAULT_LIMIT, DEFAULT_SCHEDULE_DEFAULT_LIMIT)
    )
    if not options.get(CONF_SCHEDULE_ENABLED, False):
        return default_limit, False

    start = _minutes(
        str(options.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START))
    )
    end = _minutes(str(options.get(CONF_SCHEDULE_END, DEFAULT_SCHEDULE_END)))
    current = now.hour * 60 + now.minute

    schedule_date = now.date()
    if start <= end:
        time_matches = start <= current < end
    else:
        time_matches = current >= start or current < end
        if current < end:
            schedule_date -= timedelta(days=1)

    weekdays = {
        int(value)
        for value in options.get(
            CONF_SCHEDULE_WEEKDAYS, DEFAULT_SCHEDULE_WEEKDAYS
        )
    }
    months = {
        int(value)
        for value in options.get(CONF_SCHEDULE_MONTHS, DEFAULT_SCHEDULE_MONTHS)
    }
    active = (
        time_matches
        and schedule_date.weekday() in weekdays
        and schedule_date.month in months
    )
    return (
        int(options.get(CONF_SCHEDULE_PEAK_LIMIT, DEFAULT_SCHEDULE_PEAK_LIMIT))
        if active
        else default_limit,
        active,
    )


def _minutes(value: str) -> int:
    parts = value.split(":")
    return int(parts[0]) * 60 + int(parts[1])
