"""Unit tests for the Google OAuth flow helpers (no network — nothing hits Google)."""
import pytest

from app.config import get_settings
from app.integrations.google import oauth


def _configure(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(
        settings, "google_oauth_redirect_uri",
        "http://localhost:8000/integrations/google/callback",
    )


def test_build_auth_url_contains_scope_and_offline_access(monkeypatch):
    _configure(monkeypatch)
    url = oauth.build_auth_url()
    assert "accounts.google.com" in url
    assert "test-client-id" in url
    assert "calendar.readonly" in url
    assert "access_type=offline" in url


def test_build_auth_url_requires_configuration(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    with pytest.raises(oauth.GoogleOAuthNotConfiguredError):
        oauth.build_auth_url()


async def test_exchange_code_rejects_unknown_state(monkeypatch):
    _configure(monkeypatch)
    with pytest.raises(oauth.InvalidOAuthStateError):
        await oauth.exchange_code("any-code", "state-never-issued")
