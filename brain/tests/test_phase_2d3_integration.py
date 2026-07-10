"""Phase 2D.3 integration behaviors through the chat entry point (requires the migrated test DB).

Proves the required scenarios: a ranged schedule MERGES calendar + commitments + email invitations;
"what is X" merges every provider; a correction becomes a permanent alias; a remembered recurring
commitment the calendar can't confirm is surfaced as a conflict, never hidden or invented.
"""
import uuid
from datetime import UTC, datetime, timedelta

from app.commitments import store as commitments_store
from app.conversation import commitment_handler
from app.conversation import service as conv_service
from app.integrations.google import calendar as calendar_mod
from app.integrations.google import gmail as gmail_mod
from app.integrations.google.calendar import CalendarEvent
from app.knowledge import entities
from app.knowledge import providers as providers_mod
from app.sources import registry
from app.sources.registry import CALENDAR, GMAIL, SourceReport, SourceStatus
from tests.gmail_helpers import msg as gmsg


def _user():
    return f"2d3i-{uuid.uuid4()}"


def _acct():
    return f"2d3i-{uuid.uuid4()}"


class _LLMSpy:
    def __init__(self):
        self.calls = 0

    async def generate(self, prompt):
        self.calls += 1
        return "(model)"


def _patch_connected(monkeypatch):
    def rep(name):
        return SourceReport(name=name, status=SourceStatus.CONNECTED, detail="ok")

    async def allr(account="default"):
        return {CALENDAR: rep(CALENDAR), GMAIL: rep(GMAIL)}

    monkeypatch.setattr(registry, "all_reports", allr)


def _patch_calendar(monkeypatch, events):
    async def fake(start, end, account="default"):
        return list(events)

    monkeypatch.setattr(calendar_mod, "list_events_range", fake)


def _patch_gmail(monkeypatch, messages):
    async def fake(query, account="default", max_results=25):
        return list(messages)

    monkeypatch.setattr(gmail_mod, "search", fake)


def _patch_commitments(monkeypatch, rows):
    async def fake(account="default"):
        return list(rows)

    monkeypatch.setattr(providers_mod.commitments_store, "list_all", fake)


def _ev(summary, days, hour, eid):
    day = (datetime.now(UTC) + timedelta(days=days)).date()
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)
    return CalendarEvent(summary=summary, start=start, end=start + timedelta(hours=1),
                         all_day=False, location=None, event_id=eid)


def _commitment(title, *, recurrence=None, schedule=None):
    return commitments_store.Commitment(
        account="default", key=title.lower(), title=title, type=None,
        schedule_summary=schedule, recurrence=recurrence, contexts=[], confidence=0.7,
        linked_event_ids=[], linked_email_ids=[], status="active",
    )


# --- behavior 1: ranged schedule MERGES calendar + commitments + email -------


async def test_month_schedule_merges_providers(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    _patch_calendar(monkeypatch, [_ev("ARISE Review", 3, 10, "e1")])
    _patch_gmail(monkeypatch, [gmsg(gmail_id="g1", subject="ARISE Kickoff invite")])
    _patch_commitments(monkeypatch, [_commitment("Weekly ARISE sync", schedule="Fridays 3pm")])

    reply, _ = await conv_service.handle_incoming("telegram", _user(), "what does my month look like")
    assert llm.calls == 0
    assert "ARISE Review" in reply                    # VERIFIED calendar event
    assert "Weekly ARISE sync" in reply               # REMEMBERED commitment
    assert "ARISE Kickoff invite" in reply            # LIKELY email invitation
    assert "[insert" not in reply.lower()


# --- behavior 5: "what is X" merges every provider ---------------------------


async def test_entity_query_merges_all_providers(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    _patch_calendar(monkeypatch, [_ev("Robotics Team Sync", 2, 14, "r1")])
    _patch_gmail(monkeypatch, [gmsg(gmail_id="rg1", subject="Robotics grant update")])
    _patch_commitments(monkeypatch, [_commitment("Robotics Club", schedule="mentoring")])

    reply, _ = await conv_service.handle_incoming("telegram", _user(), "what is Robotics related to?")
    assert llm.calls == 0
    assert reply.startswith("Here's what I know about")
    assert "Robotics Team Sync" in reply    # verified
    assert "Robotics grant update" in reply  # likely
    assert "Verified" in reply and "Likely" in reply  # realities kept separate


async def test_unknown_entity_is_honest_not_invented(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    _patch_calendar(monkeypatch, [])
    _patch_gmail(monkeypatch, [])
    _patch_commitments(monkeypatch, [])

    reply, _ = await conv_service.handle_incoming(
        "telegram", _user(), "what do you know about my Antarctic expedition"
    )
    assert llm.calls == 0
    assert "don't have anything on" in reply.lower()


# --- behavior 8: conflict between remembered commitment and calendar ---------


async def test_conflict_surfaced_when_calendar_cannot_confirm(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_connected(monkeypatch)
    _patch_calendar(monkeypatch, [])  # nothing on the calendar
    _patch_gmail(monkeypatch, [])
    _patch_commitments(
        monkeypatch,
        [_commitment("ECE Machine Learning Lab", recurrence="RRULE:FREQ=WEEKLY",
                     schedule="weekdays 10-2")],
    )

    reply, _ = await conv_service.handle_incoming("telegram", _user(), "what does my month look like")
    assert llm.calls == 0
    assert "can't verify matching events" in reply
    assert "ECE Machine Learning Lab" in reply


# --- behavior 7: a correction becomes a permanent alias ----------------------


async def test_naming_correction_records_permanent_alias():
    account = _acct()
    await commitments_store.upsert(account=account, title="ARISE thing", confidence=0.6)
    # The user corrects the name; the handler must alias the old referent to the new canonical name.
    reply = await commitment_handler._handle_naming("ECE Machine Learning Lab", account)
    assert "haven't changed anything on your calendar" in reply
    resolved = await entities.resolve_name("ARISE thing", account)
    assert resolved is not None
    assert resolved.canonical_name == "ECE Machine Learning Lab"
