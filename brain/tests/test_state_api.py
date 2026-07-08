"""Tests for the Phase 2C /state/* endpoints (auth, not-connected, and connected paths)."""
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.context import deadlines, resolver
from app.integrations.google import calendar
from app.integrations.google.calendar import CalendarEvent
from app.main import app


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().auth_shared_token}"}


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_state_today_requires_auth():
    async with await _client() as client:
        resp = await client.get("/state/today")
    assert resp.status_code == 401


async def test_state_today_not_connected(monkeypatch):
    async def no_cal(account="default"):
        raise calendar.NotConnectedError("nope")

    monkeypatch.setattr(calendar, "list_todays_events", no_cal)
    async with await _client() as client:
        resp = await client.get("/state/today", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False


async def test_state_today_connected(monkeypatch):
    start = datetime.now(UTC) + timedelta(hours=2)
    event = CalendarEvent(summary="Standup", start=start, end=start + timedelta(minutes=30),
                          all_day=False, location="Zoom")

    async def events(account="default"):
        return [event]

    monkeypatch.setattr(calendar, "list_todays_events", events)
    async with await _client() as client:
        resp = await client.get("/state/today", headers=_auth())
    body = resp.json()
    assert body["connected"] is True
    assert len(body["events"]) == 1
    assert "event" in body["summary"].lower()


async def test_state_deadlines_connected(monkeypatch):
    async def agg(account="default"):
        return [deadlines.Deadline(source="calendar", title="Grant due", when=None,
                                   detail="", urgency="high")]

    monkeypatch.setattr(deadlines, "aggregate_deadlines", agg)
    async with await _client() as client:
        resp = await client.get("/state/deadlines", headers=_auth())
    body = resp.json()
    assert body["connected"] is True
    assert body["deadlines"][0]["title"] == "Grant due"


async def test_state_next_meeting_no_meeting(monkeypatch):
    async def none_meeting(account="default"):
        return None

    monkeypatch.setattr(resolver, "resolve_next_meeting", none_meeting)
    async with await _client() as client:
        resp = await client.get("/state/next-meeting", headers=_auth())
    body = resp.json()
    assert body["connected"] is True
    assert body["has_event"] is False


async def test_state_next_meeting_briefing(monkeypatch):
    start = datetime.now(UTC) + timedelta(hours=3)
    event = CalendarEvent(summary="ARISE onboarding", start=start, end=start + timedelta(hours=1),
                          all_day=False, location="Room 200", attendees=("priya@arise.org",))

    async def ctx(account="default"):
        return resolver.EventContext(event=event, my_email="me@example.com")

    async def fake_brief(context):
        return "Your ARISE onboarding is at 3pm."

    monkeypatch.setattr(resolver, "resolve_next_meeting", ctx)
    monkeypatch.setattr("app.api.state.briefing.generate_briefing", fake_brief)
    async with await _client() as client:
        resp = await client.get("/state/next-meeting", headers=_auth())
    body = resp.json()
    assert body["connected"] is True
    assert body["has_event"] is True
    assert body["briefing"] == "Your ARISE onboarding is at 3pm."
    assert body["event"]["summary"] == "ARISE onboarding"
