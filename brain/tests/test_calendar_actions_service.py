"""The Phase 2D safety proofs (requires the test DB, migrated).

THE HARD RULE under test: no calendar write executes without an explicit CONFIRM. Every test that
could write installs a WriteSpy and asserts on exactly what fired (usually nothing).
"""
import uuid

from app.calendar_actions import service as ca_service
from app.calendar_actions import store
from app.calendar_actions.schema import ActionStatus, ActionType
from app.conversation import intents
from app.conversation import service as conv_service
from app.integrations.google import calendar, calendar_write
from tests.calendar_action_helpers import WriteSpy, insert_pending, make_event


def _acct() -> str:
    return f"svc-{uuid.uuid4()}"


def _patch_calendar(monkeypatch, events):
    async def fake_range(start, end, account="default"):
        return events

    monkeypatch.setattr(calendar, "list_events_range", fake_range)


# --- 1) No write occurs without confirmation ---------------------------------


async def test_proposal_drafts_but_never_writes(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("ARISE sync", 15, "evt-3pm")])
    acct = _acct()

    reply = await ca_service.request("move my 3pm meeting to 4", account=acct)

    assert "CONFIRM" in reply  # the exact proposed change + confirm instruction
    assert spy.total == 0  # nothing was written
    pending = await store.list_pending(acct)
    assert len(pending) == 1
    assert pending[0].status == ActionStatus.PENDING.value


# --- 2) CONFIRM executes only the latest pending action ----------------------


async def test_confirm_executes_only_the_latest(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = _acct()
    older = await insert_pending(
        account=acct, action_type=ActionType.DELETE, target_event_id="old",
        proposed_offset_seconds=0,
    )
    newer = await insert_pending(
        account=acct, action_type=ActionType.DELETE, target_event_id="new",
        proposed_offset_seconds=5,
    )

    await ca_service.confirm_latest(acct)

    assert spy.deleted == ["new"]  # only the newest fired
    assert (await store.get(newer.id)).status == ActionStatus.EXECUTED.value
    assert (await store.get(older.id)).status == ActionStatus.SUPERSEDED.value


async def test_confirm_executes_a_move(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("ARISE sync", 15, "evt-3pm")])
    acct = _acct()

    await ca_service.request("move my 3pm to 4", account=acct)
    message = await ca_service.confirm_latest(acct)

    assert len(spy.updated) == 1
    assert spy.updated[0][0] == "evt-3pm"
    assert "✓" in message
    assert await store.list_pending(acct) == []  # nothing left pending after execution


# --- 3) Wrong confirmation does not execute ----------------------------------


def test_is_confirm_is_strict():
    assert intents.is_confirm("CONFIRM")
    assert intents.is_confirm("confirm")
    assert not intents.is_confirm("confirm please")
    assert not intents.is_confirm("yes")
    assert not intents.is_confirm("ok do it")
    assert not intents.is_confirm("y")


async def test_wrong_confirmation_via_conversation_does_not_execute(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("ARISE sync", 15, "evt-3pm")])

    async def fake_llm(prompt):
        return "Noted."

    monkeypatch.setattr(conv_service.llm, "generate", fake_llm)

    # Draft a proposal on the default account (the conversation path Telegram uses).
    reply1, _ = await conv_service.handle_incoming(
        "telegram", f"u-{uuid.uuid4()}", "move my 3pm to 4"
    )
    assert "CONFIRM" in reply1

    # A reply that is NOT exactly "CONFIRM" must not execute the pending write.
    reply2, _ = await conv_service.handle_incoming(
        "telegram", f"u-{uuid.uuid4()}", "yes please"
    )
    assert spy.total == 0
    assert any(p.status == ActionStatus.PENDING.value for p in await store.list_pending("default"))


# --- 4) Expired pending actions do not execute -------------------------------


async def test_expired_action_does_not_execute(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = _acct()
    row = await insert_pending(
        account=acct, action_type=ActionType.DELETE, target_event_id="e", minutes_to_expiry=-1
    )

    message = await ca_service.confirm_latest(acct)

    assert spy.total == 0
    assert (await store.get(row.id)).status == ActionStatus.EXPIRED.value
    assert "expired" in message.lower()


# --- 5) Ambiguous event requests ask a clarifying question -------------------


async def test_ambiguous_request_asks_and_drafts_nothing(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(
        monkeypatch,
        [make_event("Team meeting", 10, "a"), make_event("Team meeting", 14, "b")],
    )
    acct = _acct()

    reply = await ca_service.request("cancel my team meeting", account=acct)

    assert "which" in reply.lower()  # a clarifying question, not an action
    assert await store.list_pending(acct) == []  # nothing drafted
    assert spy.total == 0


async def test_no_matching_event_asks_and_drafts_nothing(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("ARISE sync", 15, "a")])
    acct = _acct()

    reply = await ca_service.request("cancel my dentist appointment", account=acct)

    assert "couldn't find" in reply.lower()
    assert await store.list_pending(acct) == []
    assert spy.total == 0


# --- cancel path -------------------------------------------------------------


async def test_cancel_latest_drops_without_writing(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = _acct()
    row = await insert_pending(account=acct, action_type=ActionType.DELETE, target_event_id="e")

    await ca_service.cancel_latest(acct)

    assert spy.total == 0
    assert (await store.get(row.id)).status == ActionStatus.CANCELLED.value
