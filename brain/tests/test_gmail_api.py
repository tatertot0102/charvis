"""Tests for the read-only Gmail endpoints (auth, not-connected, mocked data). Requires DB."""
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.coordination import waiting as waiting_mod
from app.db.models import WaitingItem
from app.integrations.google import gmail, sync
from app.main import app
from tests.gmail_helpers import MY_EMAIL, msg


def _token() -> str:
    return get_settings().auth_shared_token


async def _get(path: str, *, auth: bool = True, params: dict | None = None):
    headers = {"Authorization": f"Bearer {_token()}"} if auth else {}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers, params=params)


async def test_unread_requires_auth():
    response = await _get("/gmail/unread", auth=False)
    assert response.status_code == 401


async def test_unread_not_connected(monkeypatch):
    async def _raise(account: str = "default"):
        raise gmail.NotConnectedError()

    monkeypatch.setattr(gmail, "get_profile_email", _raise)
    response = await _get("/gmail/unread")
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["detail"]


async def test_unread_returns_classified_messages(monkeypatch):
    async def _profile(account: str = "default"):
        return MY_EMAIL

    async def _unread(max_results: int = 20):
        return [msg(from_name="Bob", subject="Please review", snippet="can you review?",
                    labels=("INBOX", "UNREAD"))]

    monkeypatch.setattr(gmail, "get_profile_email", _profile)
    monkeypatch.setattr(gmail, "list_unread", _unread)
    response = await _get("/gmail/unread")
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["count"] == 1
    assert body["messages"][0]["from_name"] == "Bob"
    assert body["messages"][0]["requires_response"] is True


async def test_search_requires_query():
    response = await _get("/gmail/search")  # missing ?q=
    assert response.status_code == 422


async def test_waiting_returns_split_lists(monkeypatch):
    async def _sync(account: str = "default"):
        return None

    async def _list(account: str = "default"):
        return [
            WaitingItem(
                kind="waiting_on_them", thread_id="t1", person_email="b@x.com", subject="Hi",
                last_message_at=datetime.now(UTC), last_message_direction="outbound",
                follow_up_recommended=True,
            )
        ]

    monkeypatch.setattr(sync, "sync_recent", _sync)
    monkeypatch.setattr(waiting_mod, "list_waiting", _list)
    response = await _get("/gmail/waiting")
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert len(body["waiting_on_them"]) == 1
    assert body["waiting_on_them"][0]["person_email"] == "b@x.com"
