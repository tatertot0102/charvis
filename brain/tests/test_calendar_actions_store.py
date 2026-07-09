"""Integration tests for the pending-action store (requires the test DB, migrated)."""
import uuid

from app.calendar_actions import store
from app.calendar_actions.schema import ActionStatus, ActionType
from tests.calendar_action_helpers import insert_pending


def _acct() -> str:
    return f"store-{uuid.uuid4()}"


async def test_draft_supersedes_prior_pending():
    acct = _acct()
    first = await store.draft(
        action_type=ActionType.CREATE, summary="first", payload={}, account=acct
    )
    second = await store.draft(
        action_type=ActionType.CREATE, summary="second", payload={}, account=acct
    )
    pending = await store.list_pending(acct)
    assert [p.id for p in pending] == [second.id]  # only the latest remains live
    assert (await store.get(first.id)).status == ActionStatus.SUPERSEDED.value


async def test_latest_pending_returns_newest():
    acct = _acct()
    await insert_pending(account=acct, target_event_id="old", proposed_offset_seconds=0)
    newer = await insert_pending(account=acct, target_event_id="new", proposed_offset_seconds=5)
    latest = await store.latest_pending(acct)
    assert latest.id == newer.id


async def test_is_expired():
    acct = _acct()
    fresh = await insert_pending(account=acct, minutes_to_expiry=30)
    assert store.is_expired(fresh) is False
    stale = await insert_pending(account=acct, minutes_to_expiry=-1)
    assert store.is_expired(stale) is True


async def test_set_status_stamps_resolved_at():
    acct = _acct()
    row = await insert_pending(account=acct)
    updated = await store.set_status(row.id, ActionStatus.CANCELLED, result="nope")
    assert updated.status == ActionStatus.CANCELLED.value
    assert updated.resolved_at is not None
    assert updated.result == "nope"
