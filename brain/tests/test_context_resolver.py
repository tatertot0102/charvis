"""Unit tests for the ContextResolver (deterministic assembly; mocked Gmail, real DB)."""
from datetime import UTC, datetime, timedelta

from app.context import resolver
from app.context.resolver import RelatedEmail
from app.integrations.google import gmail
from app.integrations.google.calendar import CalendarEvent
from tests.gmail_helpers import msg


def _event(summary="ARISE lab onboarding", attendees=("priya@arise.org",)) -> CalendarEvent:
    start = datetime(2026, 7, 9, 15, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(hours=1), all_day=False,
        location="Room 200", event_id="evt1", description="", attendees=tuple(attendees),
    )


def test_event_keywords_drops_stopwords():
    kws = resolver.event_keywords(_event("Weekly ARISE onboarding sync"))
    assert "arise" in kws
    assert "onboarding" in kws
    assert "weekly" not in kws  # stopword
    assert "sync" not in kws  # stopword


def test_dedupe_by_thread_keeps_newest():
    older = RelatedEmail(msg(gmail_id="a", thread_id="t1",
                             received_at=datetime(2026, 7, 1, tzinfo=UTC)), reason="x")
    newer = RelatedEmail(msg(gmail_id="b", thread_id="t1",
                             received_at=datetime(2026, 7, 5, tzinfo=UTC)), reason="y")
    out = resolver._dedupe_by_thread([older, newer])
    assert len(out) == 1
    assert out[0].message.gmail_id == "b"


async def test_resolve_event_context_links_related_email(monkeypatch):
    async def fake_profile(account="default"):
        return "me@example.com"

    async def fake_search(query, account="default", max_results=20):
        # Return a hit only for the attendee search; keyword search returns nothing.
        if "priya@arise.org" in query:
            return [msg(gmail_id="m1", thread_id="t1", from_email="priya@arise.org",
                        from_name="Priya", subject="ARISE onboarding",
                        received_at=datetime(2026, 7, 8, tzinfo=UTC))]
        return []

    monkeypatch.setattr(gmail, "get_profile_email", fake_profile)
    monkeypatch.setattr(gmail, "search", fake_search)

    ctx = await resolver.resolve_event_context(_event())
    assert ctx.has_context
    assert len(ctx.related_emails) == 1
    assert ctx.related_emails[0].message.from_email == "priya@arise.org"
    assert resolver.latest_related_message(ctx).gmail_id == "m1"


async def test_resolve_event_context_gmail_unconnected_returns_event_only(monkeypatch):
    async def fake_profile(account="default"):
        raise gmail.NotConnectedError("nope")

    monkeypatch.setattr(gmail, "get_profile_email", fake_profile)
    ctx = await resolver.resolve_event_context(_event())
    assert ctx.related_emails == []
    assert ctx.has_context is False


def test_unanswered_question_flags_unread_inbound_needing_reply():
    m = msg(from_email="priya@arise.org", subject="quick question",
            snippet="can you confirm the time?", labels=("INBOX", "UNREAD"))
    ctx = resolver.EventContext(event=_event(), my_email="me@example.com",
                                related_emails=[RelatedEmail(m, reason="with priya@arise.org")])
    owed = resolver.unanswered_question(ctx)
    assert owed is not None
    assert owed.message.from_email == "priya@arise.org"
