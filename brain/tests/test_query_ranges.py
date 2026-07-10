"""Unit tests for the deterministic time-range parser (Phase 2D.3 — pure, no DB)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.query import ranges

_UTC = ZoneInfo("UTC")
# 2026-07-10 is a Friday.
_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=_UTC)


def test_today_bounds():
    tr = ranges.parse_range("what do I have today", now=_NOW)
    assert tr.key == "today"
    assert tr.start == datetime(2026, 7, 10, 0, 0, tzinfo=_UTC)
    assert tr.end == datetime(2026, 7, 11, 0, 0, tzinfo=_UTC)


def test_tomorrow_bounds():
    tr = ranges.parse_range("anything tomorrow", now=_NOW)
    assert tr.key == "tomorrow"
    assert tr.start == datetime(2026, 7, 11, 0, 0, tzinfo=_UTC)
    assert tr.end == datetime(2026, 7, 12, 0, 0, tzinfo=_UTC)


def test_this_week_is_seven_days_from_today():
    tr = ranges.parse_range("this week", now=_NOW)
    assert tr.key == "this_week"
    assert tr.start == datetime(2026, 7, 10, 0, 0, tzinfo=_UTC)
    assert (tr.end - tr.start) == timedelta(days=7)


def test_next_week_beats_week():
    tr = ranges.parse_range("what do I have next week", now=_NOW)
    assert tr.key == "next_week"
    assert tr.start == datetime(2026, 7, 17, 0, 0, tzinfo=_UTC)
    assert (tr.end - tr.start) == timedelta(days=7)


def test_this_month_runs_to_first_of_next_month():
    tr = ranges.parse_range("what does my month look like", now=_NOW)
    assert tr.key == "this_month"
    assert tr.start == datetime(2026, 7, 10, 0, 0, tzinfo=_UTC)
    assert tr.end == datetime(2026, 8, 1, 0, 0, tzinfo=_UTC)


def test_next_month_beats_month():
    tr = ranges.parse_range("what about next month", now=_NOW)
    assert tr.key == "next_month"
    assert tr.start == datetime(2026, 8, 1, 0, 0, tzinfo=_UTC)
    assert tr.end == datetime(2026, 9, 1, 0, 0, tzinfo=_UTC)


def test_next_month_wraps_year():
    dec = datetime(2026, 12, 5, 9, 0, tzinfo=_UTC)
    tr = ranges.parse_range("next month", now=dec)
    assert tr.start == datetime(2027, 1, 1, 0, 0, tzinfo=_UTC)
    assert tr.end == datetime(2027, 2, 1, 0, 0, tzinfo=_UTC)


def test_weekend_is_saturday_to_monday():
    tr = ranges.parse_range("what about this weekend", now=_NOW)
    assert tr.key == "weekend"
    assert tr.start.weekday() == 5  # Saturday
    assert (tr.end - tr.start) == timedelta(days=2)
    assert tr.start >= datetime(2026, 7, 10, 0, 0, tzinfo=_UTC)


def test_no_range_phrase_returns_none():
    assert ranges.parse_range("how are you doing", now=_NOW) is None
    assert ranges.parse_range("email LuAnn about the report", now=_NOW) is None


def test_range_from_key_roundtrip():
    tr = ranges.range_from_key("this_month", now=_NOW)
    assert tr is not None
    assert tr.as_dict()["key"] == "this_month"
    assert ranges.range_from_key("bogus") is None
