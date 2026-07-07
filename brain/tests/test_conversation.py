"""Conversation service persists history and reuses the same conversation per user.

Requires the database (run via `make test`). Uses the echo provider — no network.
"""
import uuid

from app.config import get_settings
from app.conversation import service
from app.llm.factory import get_provider


def _use_echo(monkeypatch):
    monkeypatch.setattr(get_settings(), "local_llm_provider", "echo")
    get_provider.cache_clear()


async def test_reply_and_history(monkeypatch):
    _use_echo(monkeypatch)
    external_id = f"test-{uuid.uuid4()}"

    reply1, cid1 = await service.handle_incoming("http", external_id, "first message")
    assert reply1 == "echo: first message"

    reply2, cid2 = await service.handle_incoming("http", external_id, "second message")
    assert reply2 == "echo: second message"

    # Same user → same conversation across turns.
    assert cid1 == cid2
