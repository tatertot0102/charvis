"""Deterministic natural-language time-range parsing (Phase 2D.3).

"what about this month?" must resolve to a real [start, end) window and be answered from provider
data — never fabricated by the LLM. This module is the pure, unit-testable core: it maps a phrase to
a concrete window in the configured timezone. It knows nothing about calendars; the schedule handler
feeds these bounds to a paginated provider read.
"""
from __future__ import annotations

import calendar as _calmod
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings

_STRIP_PUNCT = re.compile(r"[^a-z0-9\s]")


def _normalize(text: str) -> str:
    return " ".join(_STRIP_PUNCT.sub("", text.lower()).split())


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001 — bad TZ config must not break parsing; fall back to UTC.
        return ZoneInfo("UTC")


@dataclass(frozen=True)
class TimeRange:
    """A concrete [start, end) window with a stable key and a human label. tz-aware, half-open."""

    key: str  # today | tomorrow | this_week | next_week | weekend | this_month | next_month
    label: str  # human phrasing for prose ("this month", "next week")
    start: datetime
    end: datetime

    def as_dict(self) -> dict:
        """Serializable form persisted into conversation_task_state.active_time_range."""
        return {
            "key": self.key,
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


def _start_of_day(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), time.min, tzinfo=dt.tzinfo)


def _first_of_month(dt: datetime) -> datetime:
    return datetime.combine(dt.date().replace(day=1), time.min, tzinfo=dt.tzinfo)


def _add_month(first_of_month: datetime) -> datetime:
    """First day of the month after `first_of_month` (which must already be a month start)."""
    year, month = first_of_month.year, first_of_month.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    last_day = _calmod.monthrange(year, month)[1]  # touch to validate; unused directly
    _ = last_day
    return first_of_month.replace(year=year, month=month, day=1)


# Phrase → range key. Ordered longest/most-specific first so "next week" wins over "week".
_RANGE_PHRASES: tuple[tuple[str, str], ...] = (
    ("next month", "next_month"),
    ("this month", "this_month"),
    ("rest of this month", "this_month"),
    ("rest of the month", "this_month"),
    ("the month", "this_month"),
    ("my month", "this_month"),
    ("next week", "next_week"),
    ("this weekend", "weekend"),
    ("the weekend", "weekend"),
    ("this week", "this_week"),
    ("tomorrow", "tomorrow"),
    ("today", "today"),
)

_LABELS = {
    "today": "today",
    "tomorrow": "tomorrow",
    "this_week": "this week",
    "next_week": "next week",
    "weekend": "this weekend",
    "this_month": "this month",
    "next_month": "next month",
}


def _bounds(key: str, now: datetime) -> tuple[datetime, datetime]:
    start_today = _start_of_day(now)
    span = get_settings().week_span_days
    if key == "today":
        return start_today, start_today + timedelta(days=1)
    if key == "tomorrow":
        start = start_today + timedelta(days=1)
        return start, start + timedelta(days=1)
    if key == "this_week":
        return start_today, start_today + timedelta(days=span)
    if key == "next_week":
        start = start_today + timedelta(days=span)
        return start, start + timedelta(days=span)
    if key == "weekend":
        # The upcoming Saturday 00:00 → Monday 00:00 (or the current weekend if today is Sat/Sun).
        weekday = start_today.weekday()  # Mon=0 … Sun=6
        days_to_sat = (5 - weekday) % 7
        if weekday in (5, 6):
            days_to_sat = 5 - weekday  # Sat→0, Sun→-1 (already in the weekend)
        sat = start_today + timedelta(days=days_to_sat)
        return sat, sat + timedelta(days=2)
    if key == "this_month":
        # From today through the end of the current month (the "rest of the month").
        return start_today, _add_month(_first_of_month(now))
    if key == "next_month":
        first_next = _add_month(_first_of_month(now))
        return first_next, _add_month(first_next)
    raise ValueError(f"unknown range key: {key}")


def parse_range(text: str, *, now: datetime | None = None) -> TimeRange | None:
    """Return the TimeRange named in `text`, or None if no range phrase is present.

    Pure and deterministic. `now` defaults to the current time in the configured timezone (injectable
    for tests). Longest phrases match first so "next month"/"next week" are never mis-parsed.
    """
    tz = _tz()
    now = now.astimezone(tz) if now is not None else datetime.now(tz)
    normalized = _normalize(text)
    for phrase, key in _RANGE_PHRASES:
        if phrase in normalized:
            start, end = _bounds(key, now)
            return TimeRange(key=key, label=_LABELS[key], start=start, end=end)
    return None


def range_from_key(key: str, *, now: datetime | None = None) -> TimeRange | None:
    """Rebuild a TimeRange from a stored key (task-state follow-ups recompute against today)."""
    if key not in _LABELS:
        return None
    tz = _tz()
    now = now.astimezone(tz) if now is not None else datetime.now(tz)
    start, end = _bounds(key, now)
    return TimeRange(key=key, label=_LABELS[key], start=start, end=end)
