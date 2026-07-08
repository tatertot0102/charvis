"""Unit tests for briefing synthesis (deterministic fallback + LLM path) and data formatters."""
from datetime import UTC, datetime, timedelta

from app.context import briefing
from app.context.deadlines import Deadline
from app.context.resolver import EventContext, RelatedEmail
from app.integrations.google.calendar import CalendarEvent
from tests.gmail_helpers import msg


def _event(summary="ARISE lab onboarding") -> CalendarEvent:
    start = datetime(2026, 7, 9, 15, 0, tzinfo=UTC)
    return CalendarEvent(summary=summary, start=start, end=start + timedelta(hours=1),
                         all_day=False, location="Room 200", attendees=("priya@arise.org",))


def _context_with_email() -> EventContext:
    m = msg(from_email="priya@arise.org", from_name="Priya", subject="ARISE onboarding",
            snippet="can you confirm the time?", labels=("INBOX", "UNREAD"),
            received_at=datetime(2026, 7, 8, tzinfo=UTC))
    return EventContext(event=_event(), my_email="me@example.com",
                        related_emails=[RelatedEmail(m, reason="with priya@arise.org")])


def test_deterministic_briefing_combines_sources():
    text = briefing.deterministic_briefing(_context_with_email())
    assert "ARISE lab onboarding" in text
    assert "Priya" in text  # names the related email's sender
    assert "haven't replied" in text.lower() or "waiting" in text.lower()


def test_deterministic_briefing_handles_no_context():
    text = briefing.deterministic_briefing(EventContext(event=_event(), my_email="me@example.com"))
    assert "ARISE lab onboarding" in text
    assert "couldn't find" in text.lower()


async def test_generate_briefing_uses_llm_when_available(monkeypatch):
    async def fake_generate(messages, *, temperature=None, max_tokens=None):
        return "Synthesized brief about onboarding."

    monkeypatch.setattr(briefing.llm, "generate", fake_generate)
    text = await briefing.generate_briefing(_context_with_email())
    assert text == "Synthesized brief about onboarding."


async def test_generate_briefing_falls_back_when_llm_fails(monkeypatch):
    async def boom(messages, *, temperature=None, max_tokens=None):
        raise RuntimeError("model down")

    monkeypatch.setattr(briefing.llm, "generate", boom)
    text = await briefing.generate_briefing(_context_with_email())
    # Fallback is the deterministic template — still a real briefing.
    assert "ARISE lab onboarding" in text


async def test_generate_briefing_falls_back_on_empty_llm(monkeypatch):
    async def empty(messages, *, temperature=None, max_tokens=None):
        return "   "

    monkeypatch.setattr(briefing.llm, "generate", empty)
    text = await briefing.generate_briefing(_context_with_email())
    assert "ARISE lab onboarding" in text


def test_format_deadlines_empty():
    assert "nothing" in briefing.format_deadlines([]).lower()


def test_format_deadlines_sorted_and_marked():
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    dls = [
        Deadline(source="calendar", title="Submit grant", when=now + timedelta(hours=5),
                 detail="", urgency="high"),
        Deadline(source="email", title="Reply to landlord", when=None, detail="from Bob",
                 urgency="high"),
    ]
    text = briefing.format_deadlines(dls, now)
    assert "Submit grant" in text
    assert "🔴" in text  # high-urgency marker


def test_format_next_action_prioritizes_unanswered_meeting_question():
    rec = briefing.format_next_action(_context_with_email(), [], [])
    assert "Priya" in rec
    assert "reply" in rec.lower()


def test_format_next_action_idle():
    ctx = EventContext(event=_event(), my_email="me@example.com")
    rec = briefing.format_next_action(ctx, [], [])
    assert "nothing urgent" in rec.lower()
