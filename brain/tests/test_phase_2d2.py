"""Phase 2D.2 end-to-end proofs (requires the test DB, migrated).

Reproduces the exact bug that motivated this phase — after deleting DSI events, "what is my week?"
made Jarvis hallucinate a schedule and falsely claim it had updated the calendar — and proves every
part of the fix: week answers come from provider-backed snapshots, corrections update commitments
without touching the calendar, a recurrence statement drafts a CONFIRM-gated create, time references
resolve against real events, and deleting an event never erases a commitment.
"""
import uuid
from datetime import UTC, datetime, timedelta

from app.calendar_actions import service as ca_service
from app.calendar_actions import store
from app.calendar_actions.schema import ActionType
from app.commitments import store as commitments
from app.conversation import service as conv_service
from app.conversation import truth_guard
from app.integrations.google import calendar, calendar_write
from app.integrations.google.calendar import CalendarEvent
from tests.calendar_action_helpers import WriteSpy, insert_pending, make_event


def _user() -> str:
    return f"u-{uuid.uuid4()}"


def _acct() -> str:
    return f"2d2-{uuid.uuid4()}"


def _ev(summary: str, days: int, hour: int, event_id: str) -> CalendarEvent:
    day = (datetime.now(UTC) + timedelta(days=days)).date()
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(hours=1),
        all_day=False, location=None, event_id=event_id,
    )


def _patch_calendar(monkeypatch, events):
    async def fake_range(start, end, account="default"):
        return events

    monkeypatch.setattr(calendar, "list_events_range", fake_range)


class _LLMSpy:
    def __init__(self, reply="[insert existing events] — 9am standup, 11am sync"):
        self.calls = 0
        self.reply = reply

    async def generate(self, prompt):
        self.calls += 1
        return self.reply


# --- THE BUG: "what is my week?" must read snapshots, never the model --------


async def test_week_query_reads_snapshots_not_the_model(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)
    _patch_calendar(monkeypatch, [_ev("DSI Orientation", 1, 10, "dsi-1"), _ev("ARISE sync", 2, 14, "a1")])

    reply, _ = await conv_service.handle_incoming("telegram", _user(), "what is my week?")

    assert llm.calls == 0  # the deterministic path handled it — the model was never consulted
    assert "DSI Orientation" in reply and "ARISE sync" in reply
    assert "[insert" not in reply.lower()


async def test_deleting_dsi_removes_it_from_the_week_answer(monkeypatch):
    llm = _LLMSpy()
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)

    _patch_calendar(monkeypatch, [_ev("DSI Orientation", 1, 10, "dsi-1"), _ev("Gym", 2, 7, "gym-1")])
    first, _ = await conv_service.handle_incoming("telegram", _user(), "what is my week?")
    assert "DSI Orientation" in first

    # DSI deleted upstream; Google now returns only the gym. The next week answer must reflect that.
    _patch_calendar(monkeypatch, [_ev("Gym", 2, 7, "gym-1")])
    second, _ = await conv_service.handle_incoming("telegram", _user(), "whats my week look like")

    assert "DSI Orientation" not in second  # no lingering, no hallucination
    assert "Gym" in second
    assert llm.calls == 0


# --- Naming correction updates a commitment, never claims a calendar change ---


async def test_naming_correction_updates_commitment_without_write(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    user = _user()

    reply, _ = await conv_service.handle_incoming("telegram", user, "it is ECE Machine Learning Lab")

    assert spy.total == 0  # memory update is never a calendar write
    lowered = reply.lower()
    assert "haven't changed" in lowered or "have not changed" in lowered
    assert "updated your" not in lowered and "added" not in lowered
    row = await commitments.get_by_key("default", "ece machine learning lab")
    assert row is not None and row.title == "ECE Machine Learning Lab"


# --- Recurrence statement → CONFIRM-gated recurring create -------------------


async def test_recurrence_drafts_confirm_required_create(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [])  # for the post-write snapshot refresh
    user = _user()

    await conv_service.handle_incoming("telegram", user, "it is ECE Machine Learning Lab")
    reply, _ = await conv_service.handle_incoming("telegram", user, "it's every weekday 10-2")

    assert "CONFIRM" in reply
    assert spy.total == 0  # nothing written yet — only a proposal
    pending = await store.list_pending("default")
    assert pending and pending[0].action_type == ActionType.CREATE.value
    assert pending[0].payload["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"]
    assert pending[0].required_phrase == "CONFIRM"

    # And confirming actually creates the recurring event (RRULE plumbed end to end).
    done, _ = await conv_service.handle_incoming("telegram", user, "CONFIRM")
    assert "✓" in done
    assert len(spy.created) == 1
    assert spy.created[0]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"]


# --- Time reference resolves against real events (never fabricated) ----------


async def test_get_rid_of_the_9am_one_resolves_and_asks_to_confirm(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("Standup", 9, "nine"), make_event("Lunch", 12, "noon")])
    acct = _acct()

    reply = await ca_service.request("get rid of the 9am one", account=acct)

    assert "CONFIRM" in reply
    assert spy.total == 0
    pending = await store.list_pending(acct)
    assert len(pending) == 1
    assert pending[0].action_type == ActionType.DELETE.value
    assert pending[0].target_event_id == "nine"  # the real 9am event, not an invented one


# --- Deleting a calendar event never erases a commitment --------------------


async def test_calendar_delete_keeps_commitment(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write, valid_ids={"evt-x"})
    _patch_calendar(monkeypatch, [])  # post-write refresh
    acct = _acct()

    await commitments.upsert(
        account=acct, title="ARISE", linked_event_ids=["evt-x"], evidence_source="conversation"
    )
    await insert_pending(account=acct, action_type=ActionType.DELETE, target_event_id="evt-x")

    await ca_service.confirm_latest(acct)

    assert spy.deleted == ["evt-x"]
    still_there = await commitments.get_by_key(acct, "arise")
    assert still_there is not None  # the event is gone; the commitment survives
    assert "evt-x" in still_there.linked_event_ids


# --- The generic LLM path is post-filtered (placeholder + false write) -------


async def test_generic_reply_is_sanitized(monkeypatch):
    llm = _LLMSpy(reply="I've updated your schedule: [insert existing events]")
    monkeypatch.setattr(conv_service.llm, "generate", llm.generate)

    reply, _ = await conv_service.handle_incoming("telegram", _user(), "help me brainstorm some ideas")

    assert llm.calls == 1  # it did hit the model…
    assert reply == truth_guard.SAFE_REPLY  # …but the fabrication was replaced
    assert "[insert" not in reply.lower()
