"""Integration tests for the encrypted OAuth token store (requires DB — run via `make test`)."""
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials

from app.config import get_settings
from app.integrations.google import tokens


def _make_creds(token: str = "access-1", refresh: str | None = "refresh-1") -> Credentials:
    creds = Credentials(
        token=token,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        client_secret="csec",
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    # Future expiry so load_credentials does not attempt a (network) refresh.
    # google-auth compares expiry against a naive UTC now(), so keep it naive.
    creds.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
    return creds


def _configure(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "secret_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "csec")


async def test_save_and_load_roundtrip(monkeypatch):
    _configure(monkeypatch)
    account = f"test-{uuid.uuid4()}"

    await tokens.save_credentials(_make_creds("acc", "ref"), account=account)

    assert await tokens.is_connected(account) is True
    loaded = await tokens.load_credentials(account)
    assert loaded is not None
    assert loaded.token == "acc"
    assert loaded.refresh_token == "ref"
    assert "calendar.readonly" in " ".join(loaded.scopes or [])


async def test_second_save_without_refresh_preserves_stored_refresh(monkeypatch):
    _configure(monkeypatch)
    account = f"test-{uuid.uuid4()}"

    await tokens.save_credentials(_make_creds("acc1", "ref1"), account=account)
    # A later token response commonly omits the refresh token — must not clobber the stored one.
    await tokens.save_credentials(_make_creds("acc2", None), account=account)

    loaded = await tokens.load_credentials(account)
    assert loaded is not None
    assert loaded.token == "acc2"
    assert loaded.refresh_token == "ref1"


async def test_load_missing_account_returns_none(monkeypatch):
    _configure(monkeypatch)
    assert await tokens.load_credentials(f"absent-{uuid.uuid4()}") is None
    assert await tokens.is_connected(f"absent-{uuid.uuid4()}") is False
