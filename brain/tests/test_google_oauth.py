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


def test_build_auth_url_does_not_request_pkce(monkeypatch):
    """Regression test for InvalidGrantError: "Missing code verifier".

    build_auth_url() and exchange_code() each build a *separate* Flow instance, so a
    code_verifier generated on one never reaches the other. If PKCE is left enabled, Google
    issues a code_challenge here that the token exchange can never satisfy. This is a
    confidential web app (has a client secret), so PKCE is unnecessary — the auth URL must not
    carry a code_challenge at all.
    """
    _configure(monkeypatch)
    url = oauth.build_auth_url()
    assert "code_challenge" not in url


def test_exchange_flow_does_not_require_a_code_verifier(monkeypatch):
    """The Flow built for token exchange must not depend on a code_verifier being restored."""
    _configure(monkeypatch)
    settings = get_settings()
    flow = oauth._flow(settings, state="some-state")
    assert flow.autogenerate_code_verifier is False
    assert flow.code_verifier is None


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
