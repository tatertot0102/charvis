"""Unit tests for Gmail parsing + the async list wrapper (no live Google)."""
import pytest
from googleapiclient.errors import HttpError

from app.integrations.google import gmail, tokens
from tests.gmail_helpers import raw


def test_to_message_parses_headers_and_labels():
    message = gmail._to_message(
        raw(
            from_="Alice Smith <alice@example.com>",
            to="me@example.com, cc@x.com",
            subject="Hello",
            labels=("INBOX", "UNREAD"),
        )
    )
    assert message.from_email == "alice@example.com"
    assert message.from_name == "Alice Smith"
    assert "me@example.com" in message.to_emails
    assert "cc@x.com" in message.to_emails
    assert message.is_unread is True
    assert message.received_at is not None
    assert message.received_at.year == 2026


def test_parse_date_invalid_returns_none():
    assert gmail._parse_date("not a date") is None
    assert gmail._parse_date("") is None


async def test_list_unread_parses_via_connector(monkeypatch):
    async def _fake_load(account: str = "default"):
        return object()  # truthy stand-in for Credentials

    monkeypatch.setattr(tokens, "load_credentials", _fake_load)
    monkeypatch.setattr(gmail, "_fetch_messages", lambda creds, query, n: [raw(id="m1")])

    messages = await gmail.list_unread()
    assert len(messages) == 1
    assert messages[0].gmail_id == "m1"


async def test_insufficient_scope_maps_to_not_connected(monkeypatch):
    async def _fake_load(account: str = "default"):
        return object()

    def _raise_403(creds, query, n):
        resp = type("Resp", (), {"status": 403, "reason": "Forbidden"})()
        raise HttpError(resp=resp, content=b'{"error": {"message": "insufficient scope"}}')

    monkeypatch.setattr(tokens, "load_credentials", _fake_load)
    monkeypatch.setattr(gmail, "_fetch_messages", _raise_403)
    with pytest.raises(gmail.NotConnectedError):
        await gmail.list_unread()
