"""Tests for GET /calendar/today (auth, not-connected, and mocked-events paths). Requires DB."""
from datetime import datetime
from zoneinfo import ZoneInfo

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.integrations.google import calendar
from app.main import app


async def test_calendar_today_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/calendar/today")
    assert response.status_code == 401


async def test_calendar_today_not_connected(monkeypatch):
    async def _raise(account: str = "default"):
        raise calendar.NotConnectedError()

    monkeypatch.setattr(calendar, "list_todays_events", _raise)
    token = get_settings().auth_shared_token
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/calendar/today", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["events"] == []
    assert body["detail"]


async def test_calendar_today_returns_events(monkeypatch):
    tz = ZoneInfo("UTC")
    events = [
        calendar.CalendarEvent(
            "Standup", datetime(2026, 7, 7, 9, 30, tzinfo=tz),
            datetime(2026, 7, 7, 10, 0, tzinfo=tz), False, None,
        )
    ]

    async def _events(account: str = "default"):
        return events

    monkeypatch.setattr(calendar, "list_todays_events", _events)
    token = get_settings().auth_shared_token
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/calendar/today", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert len(body["events"]) == 1
    assert body["events"][0]["summary"] == "Standup"
    assert body["events"][0]["all_day"] is False
