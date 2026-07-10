"""Phase 2D.3a end-to-end proofs — the truth-routing core (requires the migrated test DB).

Reproduces the conversation that exposed the bug: a "this month" follow-up, an email-for-events
search that then gets refined by a bare name ("LuAnn" → "LuAnn Williams"), and a "is this on my
calendar?" verification. Each must be answered from real provider data or an honest not-found — never
the raw LLM, and never a denial of a capability Jarvis actually has.
"""
import uuid
from datetime import UTC, datetime, timedelta

from app.conversation import service as conv_service
from app.integrations.google import calendar as calendar_mod
from app.integrations.google import gmail as gmail_mod
from app.integrations.google.calendar import CalendarEvent
from app.query import validate
from app.sources import registry
from app.sources.registry import CALENDAR, GMAIL, SourceReport, SourceStatus
from tests.gmail_helpers import msg as gmsg


def _user() -> str:
    return f"2d3a-{uuid.uuid4()}"


class _LLMSpy:
    def __init__(self, reply="(model reply)"):
        self.calls = 0
        self.reply = reply

    async def generate(self, prompt):
        self.calls += 1
        return self.reply


def _ev(summary: str, month: int, day: int, hour: int, event_id: str) -> CalendarEvent:
    start = datetime(2026, month, day, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(hours=1),
        all_day=False, location=None, event_id=event_id,
    )


def _patch_connected(monkeypatch):
    def rep(name):
        return SourceReport(name=name, status=SourceStatus.CONNECTED, detail="ok")

    async def cal(account="default"):
        return rep(CALENDAR)

    async def gm(account="default"):
        return rep(GMAIL)

    async def allr(account="default"):
        return {CALENDAR: rep(CALENDAR), GMAIL: rep(GMAIL)}

    monkeypatch.setattr(registry, "calendar_report", cal)
    monkeypatch.setattr(registry, "gmail_report", gm)
    monkeypatch.setattr(registry, "all_reports", allr)


def _patch_range(monkeypatch, events):
    async def fake(start, end, account="default"):
        return list(events)

    monkeypatch.setattr(calendar_mod, "list_events_range", fake)


class _GmailSpy:
    def __init__(self, messages):
        self.messages = messages
        self.queries: list[str] = []

    async def search(self, query, account="default", max_results=20):
        self.queries.append(query)
        return list(self.messages)


# --- R1: ranged schedule reads (fresh + follow-up) come from the calendar ----


async def test_month_query_and_followup_read_calendar_not_model(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    _patch_range(monkeypatch, [_ev("ARISE Review", 7, 15, 10, "e1"), _ev("Union Essay", 7, 20, 9, "e2")])
    user = _user()

    r1, _ = await conv_service.handle_incoming("telegram", user, "what does my month look like")
    assert llm.calls == 0
    assert "ARISE Review" in r1 and "Union Essay" in r1
    assert "[insert" not in r1.lower()

    # A bare ranged follow-up refines the same schedule task — not a fresh LLM chat.
    r2, _ = await conv_service.handle_incoming("telegram", user, "what about next week?")
    assert llm.calls == 0
    assert "ARISE Review" in r2  # answered from the (patched) calendar, deterministically


async def test_disconnected_calendar_is_reported_honestly(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)

    async def disconnected(account="default"):
        return SourceReport(name=CALENDAR, status=SourceStatus.DISCONNECTED, detail="")

    monkeypatch.setattr(registry, "calendar_report", disconnected)

    reply, _ = await conv_service.handle_incoming("telegram", _user(), "what does my month look like")
    assert llm.calls == 0
    assert "not connected" in reply.lower()


# --- R3 + R2: email event search, then refined by a bare name ---------------


async def test_email_event_search_then_name_followups(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    spy = _GmailSpy([gmsg(gmail_id="g1", subject="ARISE Kickoff invite", from_name="LuAnn Williams")])
    monkeypatch.setattr(gmail_mod, "search", spy.search)
    user = _user()

    r1, _ = await conv_service.handle_incoming("telegram", user, "check my email for upcoming events")
    assert llm.calls == 0
    assert "can't access" not in r1.lower() and "cannot access" not in r1.lower()
    assert "ARISE Kickoff invite" in r1

    r2, _ = await conv_service.handle_incoming("telegram", user, "LuAnn")
    assert "LuAnn" in spy.queries[-1]  # the search was re-scoped to the name
    assert "can't access" not in r2.lower()

    r3, _ = await conv_service.handle_incoming("telegram", user, "LuAnn Williams")
    assert "LuAnn Williams" in spy.queries[-1]
    assert llm.calls == 0  # the whole chain stayed on the deterministic path


# --- R4: calendar verification hits the provider, never guesses --------------


async def test_verify_found(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    _patch_range(monkeypatch, [_ev("ECE Machine Learning Lab", 7, 15, 10, "v1")])

    reply, _ = await conv_service.handle_incoming(
        "telegram", _user(), "is the ECE Machine Learning Lab on my calendar?"
    )
    assert llm.calls == 0
    assert reply.lower().startswith("yes")
    assert "ECE Machine Learning Lab" in reply


async def test_verify_not_found_does_not_fabricate(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    _patch_range(monkeypatch, [])

    reply, _ = await conv_service.handle_incoming(
        "telegram", _user(), "is the ECE Machine Learning Lab on my calendar?"
    )
    assert llm.calls == 0
    assert reply.lower().startswith("no")
    assert "guess" in reply.lower()


# --- the LLM fallback can never deny a connected capability ------------------


async def test_llm_fallback_capability_denial_is_replaced(monkeypatch):
    async def deny(prompt):
        return "I'm sorry, I can't access your email right now."

    monkeypatch.setattr(conv_service.llm, "generate", deny)
    _patch_connected(monkeypatch)

    reply, _ = await conv_service.handle_incoming(
        "telegram", _user(), "ramble on about my email situation"
    )
    assert reply == validate.SAFE_EMAIL_REPLY
