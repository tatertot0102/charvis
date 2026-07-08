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


# --- Phase 2C: attendee parsing + next-meeting selection ---------------------


def test_parse_event_extracts_attendees_excluding_self():
    raw = {
        "summary": "ARISE onboarding",
        "id": "evt1",
        "description": "lab intro",
        "start": {"dateTime": "2026-07-09T15:00:00-04:00"},
        "end": {"dateTime": "2026-07-09T16:00:00-04:00"},
        "attendees": [
            {"email": "me@example.com", "self": True},
            {"email": "PRIYA@arise.org"},
            {"email": "room-200@resource.calendar.google.com", "resource": True},
        ],
    }
    event = calendar._parse_event(raw, TZ)
    assert event.event_id == "evt1"
    assert event.description == "lab intro"
    assert event.attendees == ("priya@arise.org",)  # lowercased, self + resource excluded


def test_next_timed_event_skips_all_day_and_past():
    now = datetime(2026, 7, 9, 12, 0, tzinfo=TZ)
    past = calendar.CalendarEvent("Done", datetime(2026, 7, 9, 9, 0, tzinfo=TZ),
                                  datetime(2026, 7, 9, 10, 0, tzinfo=TZ), False, None)
    allday = calendar.CalendarEvent("Holiday", datetime(2026, 7, 9, 0, 0, tzinfo=TZ),
                                    datetime(2026, 7, 10, 0, 0, tzinfo=TZ), True, None)
    upcoming = calendar.CalendarEvent("Meeting", datetime(2026, 7, 9, 15, 0, tzinfo=TZ),
                                      datetime(2026, 7, 9, 16, 0, tzinfo=TZ), False, None)
    assert calendar.next_timed_event([past, allday, upcoming], now=now).summary == "Meeting"


def test_next_timed_event_returns_none_when_all_past():
    now = datetime(2026, 7, 9, 18, 0, tzinfo=TZ)
    past = calendar.CalendarEvent("Done", datetime(2026, 7, 9, 9, 0, tzinfo=TZ),
                                  datetime(2026, 7, 9, 10, 0, tzinfo=TZ), False, None)
    assert calendar.next_timed_event([past], now=now) is None
