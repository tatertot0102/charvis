"""Anti-hallucination guards (Phase 2D.1): assembled context only references provider objects.

The permanent rule — Jarvis may reason, but may never invent facts — is enforced structurally: the
context resolver returns exactly the Gmail messages the provider handed back (never a fabricated
subject/sender), and returns nothing when the provider returns nothing.
"""
from datetime import UTC, datetime, timedelta

from app.context import resolver
from app.integrations.google.calendar import CalendarEvent
from tests.gmail_helpers import msg


def _event() -> CalendarEvent:
    start = datetime.now(UTC) + timedelta(hours=2)
    return CalendarEvent(
        summary="ARISE sync", start=start, end=start + timedelta(hours=1),
        all_day=False, location=None, event_id="evt", attendees=("priya@arise.org",),
    )


async def test_related_emails_are_exactly_the_provider_set(monkeypatch):
    provided = [msg(gmail_id="m1", thread_id="t1", subject="Agenda", from_email="priya@arise.org")]

    async def fake_profile(account="default"):
        return "me@example.com"

    async def fake_search(query, account="default"):
        return provided

    monkeypatch.setattr(resolver.gmail, "get_profile_email", fake_profile)
    monkeypatch.setattr(resolver.gmail, "search", fake_search)

    context = await resolver.resolve_event_context(_event())

    provider_ids = {m.gmail_id for m in provided}
    assert all(r.message.gmail_id in provider_ids for r in context.related_emails)
    assert all(r.message.subject == "Agenda" for r in context.related_emails)


async def test_no_related_emails_when_provider_returns_none(monkeypatch):
    async def fake_profile(account="default"):
        return "me@example.com"

    async def fake_search(query, account="default"):
        return []  # provider found nothing → we must invent nothing

    monkeypatch.setattr(resolver.gmail, "get_profile_email", fake_profile)
    monkeypatch.setattr(resolver.gmail, "search", fake_search)

    context = await resolver.resolve_event_context(_event())
    assert context.related_emails == []
