"""Unit tests for target-event resolution (pure — the ambiguity gate for updates/deletes)."""
from datetime import UTC, datetime, time, timedelta

from app.calendar_actions.resolve import resolve_target
from app.calendar_actions.schema import ActionType, ParsedRequest, Resolution
from app.integrations.google.calendar import CalendarEvent


def _event(summary: str, hour: int, event_id: str) -> CalendarEvent:
    start = datetime(2026, 7, 9, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(minutes=30),
        all_day=False, location=None, event_id=event_id,
    )


def test_single_match_by_hint():
    events = [_event("ARISE sync", 15, "a"), _event("Dentist", 9, "b")]
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="dentist")
    result = resolve_target(req, events)
    assert result.resolution is Resolution.SINGLE
    assert result.event.event_id == "b"


def test_single_match_by_time():
    events = [_event("ARISE sync", 15, "a"), _event("Dentist", 9, "b")]
    req = ParsedRequest(action_type=ActionType.UPDATE, target_time=time(15, 0), new_time=time(16, 0))
    result = resolve_target(req, events)
    assert result.resolution is Resolution.SINGLE
    assert result.event.event_id == "a"


def test_ambiguous_when_multiple_match():
    events = [_event("Team meeting", 10, "a"), _event("Team meeting", 14, "b")]
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="team meeting")
    result = resolve_target(req, events)
    assert result.resolution is Resolution.AMBIGUOUS
    assert len(result.candidates) == 2


def test_none_when_no_match():
    events = [_event("ARISE sync", 15, "a")]
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="dentist")
    assert resolve_target(req, events).resolution is Resolution.NONE


def test_all_day_events_are_not_targets():
    all_day = CalendarEvent(
        summary="Conference", start=datetime(2026, 7, 9, tzinfo=UTC),
        end=datetime(2026, 7, 10, tzinfo=UTC), all_day=True, location=None, event_id="c",
    )
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="conference")
    assert resolve_target(req, [all_day]).resolution is Resolution.NONE
