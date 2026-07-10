"""Persistence for the calendar-write approval queue (Phase 2D).

The only module that reads/writes pending_calendar_actions. Drafting a proposal supersedes any prior
pending action for the account (there is at most one live proposal), so "confirm the latest" is
unambiguous. Nothing here touches Google — it only records intent awaiting confirmation.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.calendar_actions.schema import ActionStatus, ActionType
from app.config import get_settings
from app.db.models import PendingCalendarAction
from app.db.session import get_session
from app.telemetry import get_logger

log = get_logger(__name__)


async def supersede_pending(
    account: str, *, except_id: int | None = None, session=None
) -> None:
    """Mark every still-pending action for the account as superseded (optionally sparing one)."""
    stmt = (
        update(PendingCalendarAction)
        .where(
            PendingCalendarAction.account == account,
            PendingCalendarAction.status == ActionStatus.PENDING.value,
        )
        .values(status=ActionStatus.SUPERSEDED.value, resolved_at=datetime.now(UTC))
    )
    if except_id is not None:
        stmt = stmt.where(PendingCalendarAction.id != except_id)
    if session is not None:
        await session.execute(stmt)
        return
    async with get_session() as own:
        await own.execute(stmt)
        await own.commit()


async def draft(
    *,
    action_type: ActionType,
    summary: str,
    payload: dict,
    target_event_id: str | None = None,
    channel: str = "telegram",
    external_id: str | None = None,
    account: str = "default",
    confidence: float = 1.0,
    required_phrase: str = "CONFIRM",
    item_count: int = 1,
) -> PendingCalendarAction:
    """Record a new pending action, superseding any earlier live proposal for the account.

    `required_phrase` is the exact text the user must send to confirm — a bulk delete uses the
    stronger "CONFIRM DELETE" so a plain "CONFIRM" can never fire it (Phase 2D.1).
    """
    ttl = timedelta(minutes=get_settings().calendar_action_ttl_minutes)
    expires_at = datetime.now(UTC) + ttl
    async with get_session() as session:
        await supersede_pending(account, session=session)
        row = PendingCalendarAction(
            account=account,
            channel=channel,
            external_id=external_id,
            action_type=action_type.value,
            status=ActionStatus.PENDING.value,
            summary=summary,
            target_event_id=target_event_id,
            payload=payload,
            expires_at=expires_at,
            confidence=confidence,
            required_phrase=required_phrase,
            item_count=item_count,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    log.info(
        "calendar_action_drafted",
        account=account,
        action_id=row.id,
        kind=action_type.value,
        item_count=item_count,
        confidence=confidence,
    )
    return row


async def get(action_id: int) -> PendingCalendarAction | None:
    async with get_session() as session:
        return await session.get(PendingCalendarAction, action_id)


async def list_pending(account: str | None = None) -> list[PendingCalendarAction]:
    """Live proposals, newest first."""
    async with get_session() as session:
        stmt = select(PendingCalendarAction).where(
            PendingCalendarAction.status == ActionStatus.PENDING.value
        )
        if account is not None:
            stmt = stmt.where(PendingCalendarAction.account == account)
        stmt = stmt.order_by(
            PendingCalendarAction.proposed_at.desc(), PendingCalendarAction.id.desc()
        )
        return list((await session.execute(stmt)).scalars().all())


async def latest_pending(account: str) -> PendingCalendarAction | None:
    rows = await list_pending(account)
    return rows[0] if rows else None


async def set_status(
    action_id: int, status: ActionStatus, *, result: str | None = None
) -> PendingCalendarAction | None:
    """Transition an action's status and stamp resolved_at. Returns the updated row."""
    async with get_session() as session:
        row = await session.get(PendingCalendarAction, action_id)
        if row is None:
            return None
        row.status = status.value
        if result is not None:
            row.result = result
        if status is not ActionStatus.PENDING:
            row.resolved_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
    return row


def is_expired(row: PendingCalendarAction, now: datetime | None = None) -> bool:
    reference = now or datetime.now(UTC)
    expires = row.expires_at
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return reference >= expires
