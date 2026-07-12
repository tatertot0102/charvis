"""Routine detection (Phase 2D.4) — weekday/weekly/monthly cadence from recurring calendar titles.

Pure function over synthetic EventSignals; no DB. Times are chosen at midday UTC so the local-tz
conversion never shifts the weekday, keeping cadence assertions deterministic across configured tz.
"""
from datetime import UTC, datetime, timedelta

from app.memory import patterns
from app.memory.signals import EventSignal, Signals


def _event(title: str, when: datetime, dur_hours: int = 4) -> EventSignal:
    return EventSignal(
        event_id=f"{title}-{when.isoformat()}",
        summary=title,
        start=when,
        end=when + timedelta(hours=dur_hours),
        location=None,
        attendees=(),
        description="",
    )


def _signals(events: list[EventSignal]) -> Signals:
    return Signals(account="default", now=datetime(2026, 7, 12, tzinfo=UTC), events=events)


def _weekday_series(title: str, weeks: int = 2) -> list[EventSignal]:
    # 2026-06-01 is a Monday; emit Mon–Fri at 15:00 UTC (midday everywhere) for N weeks.
    monday = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)
    out = []
    for w in range(weeks):
        for d in range(5):  # Mon..Fri
            out.append(_event(title, monday + timedelta(days=7 * w + d)))
    return out


def test_weekday_routine_detected():
    result = patterns.routine_patterns(_signals(_weekday_series("ECE Machine Learning Lab")))
    routines = [p for p in result if p.pattern_type == "routine"]
    assert len(routines) == 1
    r = routines[0]
    assert r.subject == "ECE Machine Learning Lab"
    assert "most weekdays" in r.description
    assert r.confidence > 0.3


def test_weekly_routine_detected():
    tuesday = datetime(2026, 6, 2, 15, 0, tzinfo=UTC)  # a Tuesday
    events = [_event("ARISE Seminar", tuesday + timedelta(days=7 * w)) for w in range(4)]
    routines = patterns.routine_patterns(_signals(events))
    assert len(routines) == 1
    assert "every Tuesday" in routines[0].description


def test_monthly_routine_detected():
    base = datetime(2026, 4, 15, 15, 0, tzinfo=UTC)
    events = [
        _event("Board Meeting", base),
        _event("Board Meeting", base + timedelta(days=30)),
        _event("Board Meeting", base + timedelta(days=61)),
    ]
    routines = patterns.routine_patterns(_signals(events))
    assert len(routines) == 1
    assert "about once a month" in routines[0].description


def test_too_few_occurrences_is_not_a_routine():
    twice = _weekday_series("Rare Thing")[:2]
    assert patterns.routine_patterns(_signals(twice)) == []


def test_routines_flow_into_all_patterns():
    result = patterns.all_patterns(_signals(_weekday_series("Daily Standup")))
    assert any(p.pattern_type == "routine" for p in result)
