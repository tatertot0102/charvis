"""/chat enforces auth and returns a reply (echo provider — no network). Requires DB."""
import uuid

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.llm.factory import get_provider
from app.main import app


def _use_echo(monkeypatch):
    monkeypatch.setattr(get_settings(), "local_llm_provider", "echo")
    get_provider.cache_clear()


async def test_chat_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat", json={"message": "hi"})
    assert response.status_code == 401


async def test_chat_returns_reply(monkeypatch):
    _use_echo(monkeypatch)
    token = get_settings().auth_shared_token
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/chat",
            json={"message": "hello jarvis", "session_id": f"s-{uuid.uuid4()}"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "echo: hello jarvis"
    assert isinstance(body["conversation_id"], int)


async def test_chat_rejects_empty_message(monkeypatch):
    _use_echo(monkeypatch)
    token = get_settings().auth_shared_token
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/chat", json={"message": ""}, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 422
