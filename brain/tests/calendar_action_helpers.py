"""Shared helpers for Phase 2D calendar-action tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.calendar_actions.schema import ActionStatus, ActionType
from app.db.models import PendingCalendarAction
from app.db.session import get_session
from app.integrations.google.calendar import CalendarEvent


def make_event(summary: str, hour: int, event_id: str, minutes: int = 30) -> CalendarEvent:
    """A timed CalendarEvent on a fixed date (UTC) — resolve/conflict logic reads .hour directly."""
    start = datetime(2026, 7, 9, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        summary=summary, start=start, end=start + timedelta(minutes=minutes),
        all_day=False, location=None, event_id=event_id,
    )


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
    )
    async with get_session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


class WriteSpy:
    """Records calls to the calendar write connector so tests can assert what (if anything) fired."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    def install(self, monkeypatch, calendar_write) -> None:
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

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated) + len(self.deleted)
