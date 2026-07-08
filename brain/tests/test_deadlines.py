"""Unit tests for deadline aggregation across calendar + email (mocked sources)."""
from datetime import UTC, datetime, timedelta

from app.context import deadlines
from app.integrations.google import calendar, gmail
from app.integrations.google.calendar import CalendarEvent
from tests.gmail_helpers import msg


def _event(summary, hours_ahead, all_day=False) -> CalendarEvent:
    start = datetime.now(UTC) + timedelta(hours=hours_ahead)
    return CalendarEvent(summary=summary, start=start, end=start + timedelta(hours=1),
                         all_day=all_day, location="")


async def test_aggregate_merges_and_sorts_by_urgency(monkeypatch):
    async def fake_upcoming(account="default", window_days=14):
        return [_event("Far event", 200), _event("Soon event", 3)]

    async def fake_profile(account="default"):
        return "me@example.com"

    async def fake_search(query, account="default", max_results=20):
        return [msg(subject="Invoice due tomorrow", snippet="payment due by friday asap",
                    from_email="billing@x.com", from_name="Billing")]

    monkeypatch.setattr(calendar, "list_upcoming_events", fake_upcoming)
    monkeypatch.setattr(gmail, "get_profile_email", fake_profile)
    monkeypatch.setattr(gmail, "search", fake_search)

    result = await deadlines.aggregate_deadlines()
    titles = [d.title for d in result]
    assert "Soon event" in titles
    assert "Invoice due tomorrow" in titles
    # Highest urgency first — the soon event and the deadline email rank above the far event.
    assert result[-1].title == "Far event"


async def test_aggregate_degrades_when_gmail_unconnected(monkeypatch):
    async def fake_upcoming(account="default", window_days=14):
        return [_event("Board meeting", 10)]

    async def no_gmail(account="default"):
        raise gmail.NotConnectedError("nope")

    monkeypatch.setattr(calendar, "list_upcoming_events", fake_upcoming)
    monkeypatch.setattr(gmail, "get_profile_email", no_gmail)

    result = await deadlines.aggregate_deadlines()
    assert [d.title for d in result] == ["Board meeting"]


async def test_aggregate_skips_all_day_events(monkeypatch):
    async def fake_upcoming(account="default", window_days=14):
        return [_event("Holiday", 24, all_day=True)]

    async def no_gmail(account="default"):
        raise gmail.NotConnectedError("nope")

    monkeypatch.setattr(calendar, "list_upcoming_events", fake_upcoming)
    monkeypatch.setattr(gmail, "get_profile_email", no_gmail)

    result = await deadlines.aggregate_deadlines()
    assert result == []
