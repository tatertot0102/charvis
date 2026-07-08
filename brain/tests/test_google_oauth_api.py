"""Tests for the Google OAuth endpoints (connect auth/config, callback CSRF state). Requires DB."""
from httpx import ASGITransport, AsyncClient

from app.api import google_oauth
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


async def test_callback_returns_readable_error_on_unexpected_token_exchange_failure(monkeypatch):
    """Regression test: a token-exchange failure (e.g. oauthlib's InvalidGrantError from the
    PKCE bug) must surface as a readable HTTP error, not an unhandled 500 traceback."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "csec")

    async def fake_exchange_code(code: str, state: str, account: str = "default") -> None:
        raise RuntimeError("(invalid_grant) Missing code verifier.")

    monkeypatch.setattr(google_oauth.oauth, "exchange_code", fake_exchange_code)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/integrations/google/callback", params={"code": "x", "state": "y"}
        )
    assert response.status_code == 502
    assert "Traceback" not in response.text
    assert "/integrations/google/connect" in response.text
