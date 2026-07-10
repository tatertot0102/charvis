"""Unit tests for confidence-ranked target resolution (pure — Phase 2D.1)."""
from datetime import UTC, datetime, time, timedelta

from app.calendar_actions import resolve
from app.calendar_actions.schema import ActionType, ParsedRequest, Resolution
from app.integrations.google.calendar import CalendarEvent

_MIN = 0.5


def _event(summary: str, hour: int, event_id: str, **kw) -> CalendarEvent:
    start = datetime(2026, 7, 9, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(minutes=30),
        all_day=False, location=None, event_id=event_id, **kw,
    )


def test_single_match_by_hint():
    events = [_event("ARISE sync", 15, "a"), _event("Dentist", 9, "b")]
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="dentist")
    result = resolve.resolve(req, events, min_confidence=_MIN)
    assert result.resolution is Resolution.SINGLE
    assert result.top.event.event_id == "b"


def test_single_match_by_time_only():
    events = [_event("ARISE sync", 15, "a"), _event("Dentist", 9, "b")]
    req = ParsedRequest(action_type=ActionType.UPDATE, target_time=time(15, 0), new_time=time(16, 0))
    result = resolve.resolve(req, events, min_confidence=_MIN)
    assert result.resolution is Resolution.SINGLE
    assert result.top.event.event_id == "a"


def test_ambiguous_when_multiple_match_single_request():
    events = [_event("Team meeting", 10, "a"), _event("Team meeting", 14, "b")]
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="team")
    result = resolve.resolve(req, events, min_confidence=_MIN)
    assert result.resolution is Resolution.AMBIGUOUS
    assert len(result.matches) == 2


def test_bulk_request_returns_whole_set():
    events = [_event("DSI Orientation", 10, "a"), _event("DSI Lab", 14, "b"), _event("Gym", 7, "c")]
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="dsi", bulk=True)
    result = resolve.resolve(req, events, min_confidence=_MIN)
    assert result.resolution is Resolution.BULK
    assert {s.event.event_id for s in result.matches} == {"a", "b"}  # Gym excluded


def test_none_when_no_match():
    events = [_event("ARISE sync", 15, "a")]
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="dentist")
    assert resolve.resolve(req, events, min_confidence=_MIN).resolution is Resolution.NONE


def test_all_day_events_are_not_targets():
    all_day = CalendarEvent(
        summary="Conference", start=datetime(2026, 7, 9, tzinfo=UTC),
        end=datetime(2026, 7, 10, tzinfo=UTC), all_day=True, location=None, event_id="c",
    )
    req = ParsedRequest(action_type=ActionType.DELETE, target_hint="conference")
    assert resolve.resolve(req, [all_day], min_confidence=_MIN).resolution is Resolution.NONE


def test_matches_ranked_by_confidence():
    events = [_event("random", 15, "time_only"), _event("DSI Orientation", 9, "titled")]
    # target_time matches the first; keyword matches the second (stronger).
    req = ParsedRequest(
        action_type=ActionType.DELETE, target_hint="dsi", target_time=time(15, 0), bulk=True
    )
    result = resolve.resolve(req, events, min_confidence=_MIN)
    assert result.matches[0].confidence >= result.matches[-1].confidence
