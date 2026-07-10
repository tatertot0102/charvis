"""Phase 2D.2 — the snapshot cache mirrors reality and prunes what Google no longer returns.

Requires the test DB, migrated. These prove week/schedule answers are built from provider-backed
snapshots (never invented) and stay fresh: delete an event upstream and it disappears from the cache.
"""
import uuid
from datetime import UTC, datetime, timedelta

from app.calendar_state import schedule, snapshots
from app.integrations.google import calendar
from app.integrations.google.calendar import CalendarEvent


def _acct() -> str:
    return f"snap-{uuid.uuid4()}"


def _ev(summary: str, days_from_today: int, hour: int, event_id: str) -> CalendarEvent:
    """A timed event on a now-relative day at noon-ish (UTC), so windows are deterministic."""
    day = (datetime.now(UTC) + timedelta(days=days_from_today)).date()
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(hours=1),
        all_day=False, location=None, event_id=event_id,
    )


def _patch(monkeypatch, events):
    async def fake_range(start, end, account="default"):
        return events

    monkeypatch.setattr(calendar, "list_events_range", fake_range)


async def test_rebuild_mirrors_provider_events(monkeypatch):
    acct = _acct()
    _patch(monkeypatch, [_ev("ARISE sync", 1, 10, "a1"), _ev("Physics", 2, 12, "p1")])

    count = await snapshots.rebuild(acct)

    assert count == 2
    start = datetime.now(UTC) - timedelta(days=1)
    rows = await snapshots.read_range(acct, start, start + timedelta(days=10))
    assert {r.title for r in rows} == {"ARISE sync", "Physics"}
    assert {r.provider_event_id for r in rows} == {"a1", "p1"}


async def test_rebuild_prunes_events_google_no_longer_returns(monkeypatch):
    acct = _acct()
    _patch(monkeypatch, [_ev("DSI Orientation", 1, 10, "dsi-1"), _ev("Gym", 2, 7, "gym-1")])
    await snapshots.rebuild(acct)

    # DSI deleted upstream — Google now returns only the gym.
    _patch(monkeypatch, [_ev("Gym", 2, 7, "gym-1")])
    await snapshots.rebuild(acct)

    start = datetime.now(UTC) - timedelta(days=1)
    rows = await snapshots.read_range(acct, start, start + timedelta(days=10))
    titles = {r.title for r in rows}
    assert "Gym" in titles
    assert "DSI Orientation" not in titles  # pruned, not lingering


async def test_week_summary_reads_snapshots_only(monkeypatch):
    acct = _acct()
    _patch(monkeypatch, [_ev("ECE Lab", 1, 10, "e1"), _ev("ARISE", 3, 14, "a1")])

    text = await schedule.week_summary(acct)

    assert "ECE Lab" in text
    assert "ARISE" in text
    assert "[insert" not in text.lower()  # never scaffolding


async def test_empty_week_is_stated_not_invented(monkeypatch):
    acct = _acct()
    _patch(monkeypatch, [])
    text = await schedule.week_summary(acct)
    assert "clear" in text.lower()
