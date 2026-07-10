"""Tests for per-conversation active-task state (Phase 2D.3 — requires the test DB)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.conversation import task_state
from app.db.models import Conversation
from app.db.session import get_session


async def _new_conversation() -> int:
    async with get_session() as session:
        convo = Conversation(channel="test", external_id=f"ts-{uuid.uuid4()}")
        session.add(convo)
        await session.flush()
        cid = convo.id
        await session.commit()
    return cid


@pytest.mark.parametrize(
    "text, expected",
    [
        ("LuAnn", True),
        ("LuAnn Williams", True),
        ("the second one", True),
        ("what is my week", False),   # opens with a question word
        ("check my email again", False),
        ("yes please", False),        # only fillers
        ("", False),
        ("this is a much longer sentence than a name", False),
    ],
)
def test_looks_like_bare_reference(text, expected):
    assert task_state.looks_like_bare_reference(text) is expected


async def test_remember_then_get_active_roundtrip():
    cid = await _new_conversation()
    async with get_session() as session:
        await task_state.remember(
            session, cid, intent="email_event_search", source_types=["gmail"],
            query="check my email for events", person_name="LuAnn",
        )
        await session.commit()
    async with get_session() as session:
        active = await task_state.get_active(session, cid)
        assert active is not None
        assert active.active_intent == "email_event_search"
        assert active.active_source_types == ["gmail"]
        assert active.active_person_name == "LuAnn"


async def test_remember_upserts_single_row():
    cid = await _new_conversation()
    async with get_session() as session:
        await task_state.remember(session, cid, intent="schedule_range", source_types=["calendar"])
        await task_state.remember(
            session, cid, intent="email_event_search", source_types=["gmail"], person_name="Dana"
        )
        await session.commit()
    async with get_session() as session:
        active = await task_state.get_active(session, cid)
        assert active.active_intent == "email_event_search"
        assert active.active_person_name == "Dana"


async def test_expired_state_is_not_returned():
    cid = await _new_conversation()
    past = datetime.now(UTC) - timedelta(hours=2)
    async with get_session() as session:
        await task_state.remember(
            session, cid, intent="schedule_range", ttl_minutes=30, now=past,
        )
        await session.commit()
    async with get_session() as session:
        assert await task_state.get_active(session, cid) is None


async def test_clear_removes_state():
    cid = await _new_conversation()
    async with get_session() as session:
        await task_state.remember(session, cid, intent="schedule_range")
        await session.commit()
    async with get_session() as session:
        await task_state.clear(session, cid)
        await session.commit()
    async with get_session() as session:
        assert await task_state.get_active(session, cid) is None
