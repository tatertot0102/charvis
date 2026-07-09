"""Tests for the Phase 2D approval-queue endpoints (auth, list, confirm, cancel)."""
import uuid

from httpx import ASGITransport, AsyncClient

from app.calendar_actions.schema import ActionStatus, ActionType
from app.config import get_settings
from app.integrations.google import calendar_write
from app.main import app
from tests.calendar_action_helpers import WriteSpy, insert_pending


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().auth_shared_token}"}


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_approvals_requires_auth():
    async with await _client() as client:
        resp = await client.get("/approvals")
    assert resp.status_code == 401


async def test_list_shows_pending():
    acct = f"api-{uuid.uuid4()}"
    row = await insert_pending(account=acct, summary="Move standup to 4pm")
    async with await _client() as client:
        resp = await client.get("/approvals", headers=_auth())
    assert resp.status_code == 200
    ids = [a["id"] for a in resp.json()["actions"]]
    assert row.id in ids


async def test_confirm_executes_and_marks_executed(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = f"api-{uuid.uuid4()}"
    row = await insert_pending(
        account=acct, action_type=ActionType.DELETE, target_event_id="evt-x"
    )
    async with await _client() as client:
        resp = await client.post(f"/approvals/{row.id}/confirm", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["status"] == ActionStatus.EXECUTED.value
    assert spy.deleted == ["evt-x"]


async def test_confirm_expired_does_not_execute(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = f"api-{uuid.uuid4()}"
    row = await insert_pending(account=acct, target_event_id="evt-y", minutes_to_expiry=-1)
    async with await _client() as client:
        resp = await client.post(f"/approvals/{row.id}/confirm", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["status"] == ActionStatus.EXPIRED.value
    assert spy.total == 0


async def test_cancel_marks_cancelled(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = f"api-{uuid.uuid4()}"
    row = await insert_pending(account=acct, target_event_id="evt-z")
    async with await _client() as client:
        resp = await client.post(f"/approvals/{row.id}/cancel", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["status"] == ActionStatus.CANCELLED.value
    assert spy.total == 0


async def test_confirm_unknown_id_404():
    async with await _client() as client:
        resp = await client.post("/approvals/99999999/confirm", headers=_auth())
    assert resp.status_code == 404
