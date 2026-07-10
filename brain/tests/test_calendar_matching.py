"""Unit tests for the confidence-scoring engine (pure — Phase 2D.1).

These prove the *evidence* behind every match: acronym, fuzzy, attendee, location, description, and
time-only signals — and that an event with no signal scores 0.0 (never a fabricated match).
"""
from datetime import UTC, datetime, timedelta

from app.calendar_actions import matching
from app.calendar_actions.schema import ActionType, ParsedRequest
from app.integrations.google.calendar import CalendarEvent


def _event(summary: str, hour: int = 10, **kw) -> CalendarEvent:
    start = datetime(2026, 7, 9, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(minutes=30),
        all_day=False, location=kw.pop("location", None), event_id="e",
        attendees=kw.pop("attendees", ()), description=kw.pop("description", ""),
        recurring_event_id=kw.pop("recurring_event_id", ""),
    )


def _q(**kw):
    return matching.build_query(ParsedRequest(action_type=ActionType.DELETE, **kw))


def test_literal_title_token():
    conf, reasons = matching.score_event(_q(target_hint="dsi"), _event("DSI Orientation"))
    assert conf >= 0.85
    assert any("contains" in r for r in reasons)


def test_acronym_initials_match():
    conf, reasons = matching.score_event(_q(target_hint="dsi"), _event("Data Science Institute"))
    assert conf >= 0.85
    assert any("initials" in r.lower() for r in reasons)


def test_fuzzy_title_match():
    conf, reasons = matching.score_event(_q(target_hint="physics"), _event("Physic Lecture"))
    assert conf >= 0.5
    assert any("~" in r for r in reasons)


def test_attendee_match():
    ev = _event("Weekly sync", attendees=("dana@lab.org",))
    conf, reasons = matching.score_event(_q(attendee_hint="dana"), ev)
    assert conf >= 0.85
    assert any("attendee" in r for r in reasons)


def test_location_match():
    ev = _event("Study block", location="ARISE Lab Room 200")
    conf, _ = matching.score_event(_q(target_hint="arise"), ev)
    assert conf >= 0.6


def test_description_match():
    ev = _event("Study block", description="prep for the ARISE grant")
    conf, _ = matching.score_event(_q(target_hint="arise"), ev)
    assert conf >= 0.5


def test_recurring_reason_surfaces():
    ev = _event("DSI Orientation", recurring_event_id="series-1")
    _, reasons = matching.score_event(_q(target_hint="dsi"), ev)
    assert "recurring series" in reasons


def test_no_signal_scores_zero():
    # An event that matches nothing must not be conjured into a match.
    conf, reasons = matching.score_event(_q(target_hint="quantum"), _event("Lunch with mom"))
    assert conf == 0.0
    assert reasons == ()


def test_time_only_identifies_event():
    from datetime import time
    q = _q(target_time=time(15, 0))
    conf, reasons = matching.score_event(q, _event("Untitled", hour=15))
    assert conf >= 0.5
    assert reasons  # cites the start time
