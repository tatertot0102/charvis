"""Phase 2D / 2D.1 safety proofs (requires the test DB, migrated).

THE HARD RULE under test: no calendar write executes without an explicit, correct confirmation, and
no fabricated event is ever written or proposed. Every test that could write installs a WriteSpy and
asserts exactly what fired (usually nothing).
"""
import uuid

from app.calendar_actions import service as ca_service
from app.calendar_actions import store
from app.calendar_actions.schema import ActionStatus, ActionType
from app.conversation import intents
from app.conversation import service as conv_service
from app.integrations.google import calendar, calendar_write
from tests.calendar_action_helpers import (
    WriteSpy,
    insert_bulk_pending,
    insert_pending,
    make_event,
    patch_validation,
)


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

    assert "CONFIRM" in reply
    assert spy.total == 0
    pending = await store.list_pending(acct)
    assert len(pending) == 1 and pending[0].status == ActionStatus.PENDING.value


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

    assert spy.deleted == ["new"]
    assert (await store.get(newer.id)).status == ActionStatus.EXECUTED.value
    assert (await store.get(older.id)).status == ActionStatus.SUPERSEDED.value


async def test_confirm_executes_a_move(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("ARISE sync", 15, "evt-3pm")])
    acct = _acct()

    await ca_service.request("move my 3pm to 4", account=acct)
    message = await ca_service.confirm_latest(acct)

    assert len(spy.updated) == 1 and spy.updated[0][0] == "evt-3pm"
    assert "✓" in message
    assert await store.list_pending(acct) == []


# --- 3) Wrong confirmation does not execute ----------------------------------


def test_is_confirm_is_strict():
    assert intents.is_confirm("CONFIRM")
    assert intents.is_confirm("confirm")
    assert not intents.is_confirm("confirm please")
    assert not intents.is_confirm("yes")
    assert not intents.is_confirm("confirm delete")  # bulk phrase is not a plain confirm


async def test_wrong_confirmation_via_conversation_does_not_execute(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("ARISE sync", 15, "evt-3pm")])

    async def fake_llm(prompt):
        return "Noted."

    monkeypatch.setattr(conv_service.llm, "generate", fake_llm)

    reply1, _ = await conv_service.handle_incoming("telegram", f"u-{uuid.uuid4()}", "move my 3pm to 4")
    assert "CONFIRM" in reply1

    reply2, _ = await conv_service.handle_incoming("telegram", f"u-{uuid.uuid4()}", "yes please")
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


# --- 5) Ambiguity handling ---------------------------------------------------


async def test_ambiguous_request_asks_and_drafts_nothing(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("Team meeting", 10, "a"), make_event("Team meeting", 14, "b")])
    acct = _acct()

    reply = await ca_service.request("cancel my team meeting", account=acct)

    assert "which" in reply.lower()
    assert await store.list_pending(acct) == []
    assert spy.total == 0


async def test_no_matching_event_says_so_without_fabricating(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, [make_event("ARISE sync", 15, "a")])
    acct = _acct()

    reply = await ca_service.request("delete all future DSI events", account=acct)

    assert "couldn't find" in reply.lower()
    assert "dsi" in reply.lower()  # echoes what the user asked, invents nothing
    assert await store.list_pending(acct) == []
    assert spy.total == 0


# --- Bulk actions (Phase 2D.1) ----------------------------------------------


def _dsi_events():
    return [
        make_event("DSI Orientation", 10, "dsi-1", recurring_event_id="dsi-series", day=18),
        make_event("DSI Writing Workshop", 14, "dsi-2", day=20),
        make_event("Data Science Institute Lab", 9, "dsi-3", day=22),  # acronym match
        make_event("Gym", 7, "gym-1", day=19),  # must NOT match
    ]


async def test_delete_all_future_dsi_events_proposes_bulk(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    _patch_calendar(monkeypatch, _dsi_events())
    acct = _acct()

    reply = await ca_service.request("delete all future DSI events", account=acct)

    assert "found 3" in reply.lower()  # the three DSI events, not the gym
    assert "CONFIRM DELETE" in reply
    assert "gym" not in reply.lower()
    assert spy.total == 0
    row = (await store.list_pending(acct))[0]
    assert row.item_count == 3
    assert row.required_phrase == "CONFIRM DELETE"
    assert row.action_type == ActionType.DELETE.value


async def test_bulk_delete_requires_confirm_delete_not_plain_confirm(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write, valid_ids={"dsi-1", "dsi-2", "dsi-3"})
    _patch_calendar(monkeypatch, _dsi_events())
    acct = _acct()
    await ca_service.request("delete all future DSI events", account=acct)

    # A plain CONFIRM must NOT fire a bulk delete.
    plain = await ca_service.confirm_latest(acct, phrase="CONFIRM")
    assert spy.total == 0
    assert "CONFIRM DELETE" in plain
    assert (await store.list_pending(acct))[0].status == ActionStatus.PENDING.value

    # The correct phrase executes all three.
    done = await ca_service.confirm_latest(acct, phrase="CONFIRM DELETE")
    assert set(spy.deleted) == {"dsi-1", "dsi-2", "dsi-3"}
    assert "3" in done


async def test_expired_bulk_proposal_does_not_execute(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = _acct()
    row = await insert_bulk_pending(account=acct, event_ids=["a", "b"], minutes_to_expiry=-1)

    message = await ca_service.confirm_latest(acct, phrase="CONFIRM DELETE")

    assert spy.total == 0
    assert (await store.get(row.id)).status == ActionStatus.EXPIRED.value
    assert "expired" in message.lower()


async def test_no_hallucinated_events_in_bulk_proposal(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    provided = _dsi_events()
    _patch_calendar(monkeypatch, provided)
    acct = _acct()

    await ca_service.request("cancel all upcoming DSI meetings", account=acct)

    row = (await store.list_pending(acct))[0]
    proposed_ids = {t["target_event_id"] for t in row.payload["targets"]}
    provider_ids = {e.event_id for e in provided}
    assert proposed_ids <= provider_ids  # every proposed id is a real provider event
    proposed_titles = {t["summary"] for t in row.payload["targets"]}
    assert proposed_titles <= {e.summary for e in provided}  # no invented titles


# --- Anti-hallucination: id validation on execute ----------------------------


async def test_fabricated_id_rejected(monkeypatch):
    spy = WriteSpy()
    # valid_ids empty → provider validation resolves every id to None (fabricated/unknown).
    spy.install(monkeypatch, calendar_write, valid_ids=set())
    acct = _acct()
    row = await insert_pending(
        account=acct, action_type=ActionType.DELETE, target_event_id="totally-made-up-id"
    )

    message = await ca_service.confirm_latest(acct)

    assert spy.deleted == []
    assert (await store.get(row.id)).status == ActionStatus.FAILED.value
    assert "no longer exists" in message.lower()


async def test_unknown_id_rejected_via_connector(monkeypatch):
    # Even if validation somehow passes, the connector's 404→RejectedEventError is a second guard.
    patch_validation(monkeypatch, valid_ids=None)  # validation says "real"

    async def _reject(event_id, account="default"):
        raise calendar_write.RejectedEventError(event_id)

    monkeypatch.setattr(calendar_write, "delete_event", _reject)
    acct = _acct()
    row = await insert_pending(
        account=acct, action_type=ActionType.DELETE, target_event_id="stale-id"
    )

    message = await ca_service.confirm_latest(acct)

    assert (await store.get(row.id)).status == ActionStatus.FAILED.value
    assert "rejected" in message.lower() or "already deleted" in message.lower()


async def test_bulk_skips_stale_ids_without_failing_batch(monkeypatch):
    spy = WriteSpy()
    # Only two of three ids are real; the third was deleted out from under the proposal.
    spy.install(monkeypatch, calendar_write, valid_ids={"a", "b"})
    acct = _acct()
    await insert_bulk_pending(account=acct, event_ids=["a", "b", "ghost"])

    message = await ca_service.confirm_latest(acct, phrase="CONFIRM DELETE")

    assert set(spy.deleted) == {"a", "b"}  # ghost never written
    assert "2" in message and "skipped" in message.lower()


# --- cancel path -------------------------------------------------------------


async def test_cancel_latest_drops_without_writing(monkeypatch):
    spy = WriteSpy()
    spy.install(monkeypatch, calendar_write)
    acct = _acct()
    row = await insert_pending(account=acct, action_type=ActionType.DELETE, target_event_id="e")

    await ca_service.cancel_latest(acct)

    assert spy.total == 0
    assert (await store.get(row.id)).status == ActionStatus.CANCELLED.value
