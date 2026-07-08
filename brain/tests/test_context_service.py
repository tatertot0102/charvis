"""Integration: the conversation service routes 2C context intents through context_handler.

Exercises the same code path Telegram uses (service.handle_incoming), so a green test here means
a "prep me for my next meeting" text on Telegram gets the synthesized briefing, not the raw LLM.
"""
import uuid
from datetime import UTC, datetime, timedelta

from app.conversation import context_handler, service
from app.context import resolver
from app.integrations.google.calendar import CalendarEvent


def _event() -> CalendarEvent:
    start = datetime.now(UTC) + timedelta(hours=2)
    return CalendarEvent(summary="ARISE onboarding", start=start, end=start + timedelta(hours=1),
                         all_day=False, location="Room 200", attendees=("priya@arise.org",))


async def test_prep_meeting_routes_to_briefing(monkeypatch):
    async def fake_ctx(account="default"):
        return resolver.EventContext(event=_event(), my_email="me@example.com")

    async def fake_brief(context):
        return "Your ARISE onboarding is at 2pm; Priya emailed about the agenda."

    monkeypatch.setattr(resolver, "resolve_next_meeting", fake_ctx)
    monkeypatch.setattr(context_handler.briefing, "generate_briefing", fake_brief)

    reply, cid = await service.handle_incoming(
        "telegram", f"u-{uuid.uuid4()}", "prep me for my next meeting"
    )
    assert "ARISE onboarding" in reply
    assert isinstance(cid, int)


async def test_deadlines_intent_routes_to_deadline_formatter(monkeypatch):
    async def fake_agg(account="default"):
        return []

    monkeypatch.setattr(context_handler.deadlines, "aggregate_deadlines", fake_agg)
    reply, _cid = await service.handle_incoming(
        "telegram", f"u-{uuid.uuid4()}", "what deadlines are coming up?"
    )
    assert "deadline" in reply.lower() or "✅" in reply
