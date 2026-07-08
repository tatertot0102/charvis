"""Integration tests: sync persists messages, people, and waiting items (mocked Gmail, real DB)."""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import EmailMessage, Person, WaitingItem
from app.db.session import get_session
from app.integrations.google import gmail, sync
from app.lifemodel import people
from tests.gmail_helpers import msg


async def test_sync_persists_messages_people_and_waiting(monkeypatch):
    account = f"acct-{uuid.uuid4()}"
    my = f"me-{uuid.uuid4()}@example.com"
    bob = f"bob-{uuid.uuid4()}@example.com"
    thread_id = f"thread-{uuid.uuid4()}"
    thread = [
        msg(
            gmail_id=f"g-{uuid.uuid4()}", thread_id=thread_id, from_email=bob, to=(my,),
            subject="Question", snippet="can you review this?",
            received_at=datetime.now(UTC) - timedelta(days=2),
        )
    ]

    async def _profile(account: str = "default"):
        return my

    async def _threads(account: str = "default", max_threads: int = 25, window_days: int = 14):
        return [thread]

    monkeypatch.setattr(gmail, "get_profile_email", _profile)
    monkeypatch.setattr(gmail, "list_recent_threads", _threads)

    result = await sync.sync_recent(account=account)
    assert result.messages == 1
    assert result.waiting_items == 1

    async with get_session() as session:
        emails = (
            await session.execute(
                select(EmailMessage).where(EmailMessage.account == account)
            )
        ).scalars().all()
        ppl = (
            await session.execute(select(Person).where(Person.account == account))
        ).scalars().all()
        waits = (
            await session.execute(select(WaitingItem).where(WaitingItem.account == account))
        ).scalars().all()

    assert len(emails) == 1
    assert emails[0].requires_response is True
    assert any(p.email == bob for p in ppl)
    assert len(waits) == 1
    assert waits[0].kind == "waiting_on_me"


async def test_record_interaction_and_find_person():
    account = f"acct-{uuid.uuid4()}"
    email = f"bob-{uuid.uuid4()}@example.com"
    async with get_session() as session:
        await people.record_interaction(
            session, account=account, email=email, name="Bob Jones",
            direction="inbound", at=datetime.now(UTC),
        )
        await session.commit()

    found = await people.find_person("bob jones", account=account)
    assert found is not None
    assert found.email == email
    assert found.message_count == 1
