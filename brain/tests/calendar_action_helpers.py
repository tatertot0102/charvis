"""Shared helpers for Phase 2D / 2D.1 calendar-action tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.calendar_actions.schema import ActionStatus, ActionType
from app.db.models import PendingCalendarAction
from app.db.session import get_session
from app.integrations.google import calendar as calendar_mod
from app.integrations.google.calendar import CalendarEvent


def make_event(
    summary: str,
    hour: int,
    event_id: str,
    minutes: int = 30,
    *,
    attendees: tuple[str, ...] = (),
    location: str | None = None,
    description: str = "",
    recurring_event_id: str = "",
    day: int = 9,
) -> CalendarEvent:
    """A timed CalendarEvent on a fixed date (UTC) — resolve/conflict logic reads .hour directly."""
    start = datetime(2026, 7, day, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(minutes=minutes),
        all_day=False, location=location, event_id=event_id,
        attendees=attendees, description=description, recurring_event_id=recurring_event_id,
    )


def patch_validation(monkeypatch, *, valid_ids=None) -> None:
    """Patch calendar.get_event so execution's id-validation treats `valid_ids` as real.

    valid_ids=None → every non-empty id validates (the common "these are real events" case).
    Otherwise only ids in the set validate; anything else resolves to None (fabricated/unknown/stale).
    """
    async def _get_event(event_id, account="default"):
        if not event_id:
            return None
        if valid_ids is not None and event_id not in valid_ids:
            return None
        return make_event("Validated", 15, event_id)

    monkeypatch.setattr(calendar_mod, "get_event", _get_event)


async def insert_pending(
    *,
    account: str,
    action_type: ActionType = ActionType.DELETE,
    target_event_id: str = "evt",
    summary: str = "proposed change",
    payload: dict | None = None,
    minutes_to_expiry: int = 30,
    proposed_offset_seconds: int = 0,
    status: ActionStatus = ActionStatus.PENDING,
    required_phrase: str = "CONFIRM",
    item_count: int = 1,
    confidence: float = 1.0,
) -> PendingCalendarAction:
    """Insert a pending row directly, bypassing draft()'s supersede — for multi-pending scenarios."""
    now = datetime.now(UTC)
    row = PendingCalendarAction(
        account=account,
        channel="test",
        action_type=action_type.value,
        status=status.value,
        summary=summary,
        target_event_id=target_event_id,
        payload=payload or {"target_event_id": target_event_id, "summary": summary},
        proposed_at=now + timedelta(seconds=proposed_offset_seconds),
        expires_at=now + timedelta(minutes=minutes_to_expiry),
        required_phrase=required_phrase,
        item_count=item_count,
        confidence=confidence,
    )
    async with get_session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def insert_bulk_pending(
    *,
    account: str,
    action_type: ActionType = ActionType.DELETE,
    event_ids: list[str],
    required_phrase: str = "CONFIRM DELETE",
    minutes_to_expiry: int = 30,
    status: ActionStatus = ActionStatus.PENDING,
) -> PendingCalendarAction:
    """Insert a bulk pending row whose payload carries a list of provider-backed targets."""
    targets = [
        {"target_event_id": eid, "summary": f"Event {eid}", "start": "2026-07-18T10:00:00+00:00"}
        for eid in event_ids
    ]
    return await insert_pending(
        account=account,
        action_type=action_type,
        target_event_id=None,
        summary=f"bulk over {len(event_ids)}",
        payload={"targets": targets, "bulk": True, "new_time": None},
        required_phrase=required_phrase,
        item_count=len(event_ids),
        minutes_to_expiry=minutes_to_expiry,
        status=status,
    )


class WriteSpy:
    """Records calls to the calendar write connector so tests can assert what (if anything) fired."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    def install(self, monkeypatch, calendar_write, *, monkeypatch_validation=True, valid_ids=None) -> None:
        async def _create(*, summary, start, end, location=None, account="default"):
            self.created.append({"summary": summary, "start": start, "end": end})
            return {"id": "new-event-id", "htmlLink": "https://cal/new"}

        async def _update(event_id, *, start=None, end=None, summary=None, location=None, account="default"):
            self.updated.append((event_id, {"start": start, "end": end}))
            return {"id": event_id}

        async def _delete(event_id, account="default"):
            self.deleted.append(event_id)

        monkeypatch.setattr(calendar_write, "create_event", _create)
        monkeypatch.setattr(calendar_write, "update_event", _update)
        monkeypatch.setattr(calendar_write, "delete_event", _delete)
        # By default, make id-validation pass so execution tests exercise the write path. Tests that
        # probe the anti-hallucination guard pass valid_ids (or monkeypatch_validation=False).
        if monkeypatch_validation:
            patch_validation(monkeypatch, valid_ids=valid_ids)

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated) + len(self.deleted)
