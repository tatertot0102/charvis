"""Unit tests for conflict detection and free-slot math (pure)."""
from datetime import UTC, datetime, timedelta

from app.calendar_actions.conflicts import find_conflicts, free_slots
from app.integrations.google.calendar import CalendarEvent


def _event(hour: int, minutes: int = 60, event_id: str = "x", summary: str = "Busy") -> CalendarEvent:
    start = datetime(2026, 7, 9, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(minutes=minutes),
        all_day=False, location=None, event_id=event_id,
    )


def test_detects_overlap():
    events = [_event(15, event_id="a")]
    proposed_start = datetime(2026, 7, 9, 15, 30, tzinfo=UTC)
    proposed_end = proposed_start + timedelta(minutes=30)
    assert find_conflicts(proposed_start, proposed_end, events)[0].event_id == "a"


def test_excludes_the_event_being_moved():
    events = [_event(15, event_id="a")]
    # Moving event "a" onto its own slot must not report a self-conflict.
    start = datetime(2026, 7, 9, 15, 0, tzinfo=UTC)
    end = start + timedelta(minutes=60)
    assert find_conflicts(start, end, events, exclude_event_id="a") == []


def test_no_conflict_when_adjacent():
    events = [_event(15, minutes=60, event_id="a")]  # 15:00–16:00
    start = datetime(2026, 7, 9, 16, 0, tzinfo=UTC)  # starts exactly when the other ends
    end = start + timedelta(minutes=30)
    assert find_conflicts(start, end, events) == []


def test_free_slots_between_events():
    window_start = datetime(2026, 7, 9, 9, 0, tzinfo=UTC)
    window_end = datetime(2026, 7, 9, 17, 0, tzinfo=UTC)
    events = [_event(10, 60, "a"), _event(14, 60, "b")]  # busy 10–11 and 14–15
    slots = free_slots(events, window_start, window_end, min_minutes=30)
    # Expect: 9–10, 11–14, 15–17.
    spans = [(s.start.hour, s.end.hour) for s in slots]
    assert (9, 10) in spans
    assert (11, 14) in spans
    assert (15, 17) in spans


def test_free_slots_respects_minimum():
    window_start = datetime(2026, 7, 9, 9, 0, tzinfo=UTC)
    window_end = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    events = [_event(9, 45, "a")]  # busy 9:00–9:45, leaving only a 15-min gap
    assert free_slots(events, window_start, window_end, min_minutes=30) == []
