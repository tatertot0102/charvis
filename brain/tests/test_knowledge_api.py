"""Tests for the Phase 2D.3 /knowledge + /query endpoints (auth + WorldModel shape)."""
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.knowledge import engine
from app.knowledge.model import Fact, Reality
from app.main import app
from app.sources import registry
from app.sources.registry import CALENDAR, GMAIL, SourceReport, SourceStatus


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().auth_shared_token}"}


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _Fake:
    def __init__(self, name, facts):
        self.name = name
        self._facts = facts

    async def fetch(self, q):
        return list(self._facts)


def _connected(monkeypatch):
    async def allr(account="default"):
        def r(n):
            return SourceReport(name=n, status=SourceStatus.CONNECTED, detail="ok")
        return {CALENDAR: r(CALENDAR), GMAIL: r(GMAIL)}

    monkeypatch.setattr(registry, "all_reports", allr)


async def test_query_requires_auth():
    async with await _client() as client:
        resp = await client.post("/query", json={"intent": "entity", "subjects": ["x"]})
    assert resp.status_code == 401


async def test_query_returns_world_model(monkeypatch):
    _connected(monkeypatch)
    event = Fact(kind="event", reality=Reality.VERIFIED, text="Robotics — Jul 15",
                 source="calendar", provider_object_id="e1", confidence=0.95,
                 data={"summary": "Robotics"})
    monkeypatch.setattr(engine, "ALL_PROVIDERS", [_Fake("calendar", [event])])

    async with await _client() as client:
        resp = await client.post(
            "/query", json={"intent": "entity", "subjects": ["Robotics"]}, headers=_auth()
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "entity"
    assert len(body["events"]) == 1
    assert body["events"][0]["reality"] == "verified"
    assert body["sources"]["calendar"]["connected"] is True


async def test_sources_endpoint(monkeypatch):
    _connected(monkeypatch)
    async with await _client() as client:
        resp = await client.get("/knowledge/sources", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["gmail"]["connected"] is True
