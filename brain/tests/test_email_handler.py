"""Unit tests for the email intent handler (mocked Gmail/people, real DB for find_person)."""
import uuid
from datetime import UTC, datetime

from app.conversation import email_handler
from app.conversation.intents import EmailIntent
from app.db.session import get_session
from app.integrations.google import gmail
from app.lifemodel import people
from tests.gmail_helpers import msg


async def test_did_reply_resolves_known_person_to_their_email(monkeypatch):
    account = "default"
    real_email = f"john-{uuid.uuid4()}@example.com"
    async with get_session() as session:
        await people.record_interaction(
            session, account=account, email=real_email, name="John Smith",
            direction="inbound", at=datetime.now(UTC),
        )
        await session.commit()

    captured: dict[str, str] = {}

    async def fake_profile(account: str = "default") -> str:
        return "me@example.com"

    async def fake_search(query: str, account: str = "default", max_results: int = 20):
        captured["query"] = query
        return [msg(from_email=real_email, from_name="John Smith")]

    monkeypatch.setattr(gmail, "get_profile_email", fake_profile)
    monkeypatch.setattr(gmail, "search", fake_search)

    reply = await email_handler.handle(EmailIntent.DID_REPLY, "john smith")

    assert real_email in captured["query"]
    assert "john smith" in reply.lower()


async def test_did_reply_falls_back_to_raw_name_when_person_unknown(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_profile(account: str = "default") -> str:
        return "me@example.com"

    async def fake_search(query: str, account: str = "default", max_results: int = 20):
        captured["query"] = query
        return []

    monkeypatch.setattr(gmail, "get_profile_email", fake_profile)
    monkeypatch.setattr(gmail, "search", fake_search)

    reply = await email_handler.handle(EmailIntent.DID_REPLY, "someone-never-seen")

    assert "someone-never-seen" in captured["query"]
    assert "someone-never-seen" in reply


async def test_unread_intent_formats_gmail_results(monkeypatch):
    async def fake_profile(account: str = "default") -> str:
        return "me@example.com"

    async def fake_unread(account: str = "default", max_results: int = 20):
        return [msg(subject="Ping", labels=("INBOX", "UNREAD"))]

    monkeypatch.setattr(gmail, "get_profile_email", fake_profile)
    monkeypatch.setattr(gmail, "list_unread", fake_unread)

    reply = await email_handler.handle(EmailIntent.UNREAD, None)

    assert "unread" in reply.lower()


async def test_not_connected_degrades_to_friendly_message(monkeypatch):
    async def fake_profile(account: str = "default") -> str:
        raise gmail.NotConnectedError("nope")

    monkeypatch.setattr(gmail, "get_profile_email", fake_profile)

    reply = await email_handler.handle(EmailIntent.UNREAD, None)

    assert "connect" in reply.lower() or "gmail" in reply.lower()
