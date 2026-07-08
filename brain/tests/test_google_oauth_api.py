"""Tests for the Google OAuth endpoints (connect auth/config, callback CSRF state). Requires DB."""
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


async def test_connect_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/integrations/google/connect")
    assert response.status_code == 401


async def test_connect_returns_auth_url_when_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "csec")
    token = settings.auth_shared_token
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/integrations/google/connect", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    assert "accounts.google.com" in response.json()["auth_url"]


async def test_callback_rejects_unknown_state(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "csec")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/integrations/google/callback", params={"code": "x", "state": "never-issued"}
        )
    assert response.status_code == 400
