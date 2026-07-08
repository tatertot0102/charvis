"""Unit tests for Calendar parsing/formatting (no network, no DB)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.integrations.google import calendar

TZ = ZoneInfo("America/New_York")


def test_parse_timed_event():
    raw = {
        "summary": "Standup",
        "start": {"dateTime": "2026-07-07T09:30:00-04:00"},
        "end": {"dateTime": "2026-07-07T10:00:00-04:00"},
        "location": "Zoom",
    }
    event = calendar._parse_event(raw, TZ)
    assert event.summary == "Standup"
    assert event.all_day is False
    assert event.location == "Zoom"


def test_parse_all_day_event():
    raw = {"summary": "Holiday", "start": {"date": "2026-07-07"}, "end": {"date": "2026-07-08"}}
    event = calendar._parse_event(raw, TZ)
    assert event.all_day is True
    assert event.summary == "Holiday"


def test_parse_event_without_summary_gets_placeholder():
    raw = {"start": {"dateTime": "2026-07-07T09:30:00-04:00"},
           "end": {"dateTime": "2026-07-07T10:00:00-04:00"}}
    assert calendar._parse_event(raw, TZ).summary == "(no title)"


def test_format_empty_day():
    assert "no events" in calendar.format_todays_events([]).lower()


def test_format_lists_events():
    events = [
        calendar.CalendarEvent(
            "Standup", datetime(2026, 7, 7, 9, 30, tzinfo=TZ),
            datetime(2026, 7, 7, 10, 0, tzinfo=TZ), False, "Zoom",
        ),
        calendar.CalendarEvent(
            "Holiday", datetime(2026, 7, 7, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 8, 0, 0, tzinfo=TZ), True, None,
        ),
    ]
    text = calendar.format_todays_events(events)
    assert "Standup" in text
    assert "9:30" in text
    assert "Zoom" in text
    assert "all day" in text
