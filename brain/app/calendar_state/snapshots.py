"""Provider-backed calendar snapshot cache (Phase 2D.2).

`rebuild()` pulls the real events in a window from Google, upserts them, and prunes any snapshot in
that window Google no longer returns — so the cache is always a faithful mirror of reality, never a
stale or invented one. `read_range()` returns detached snapshot rows for a sub-window. Everything a
week/schedule answer shows comes from here, so Jarvis can never fabricate a schedule.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import CalendarSnapshot
from app.db.session import get_session
from app.integrations.google import calendar
from app.telemetry import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SnapshotEvent:
    """A read-only view of one cached event — detached from the DB session. Pure/testable."""

    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str | None = None
    provider_event_id: str = ""
    recurring_event_id: str = ""


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001 — bad TZ must not break a read; fall back to UTC.
        return ZoneInfo("UTC")


def _window(tz: ZoneInfo, back_days: int, forward_days: int) -> tuple[datetime, datetime]:
    start_of_today = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
    return start_of_today - timedelta(days=back_days), start_of_today + timedelta(days=forward_days)


async def rebuild(
    account: str = "default", *, back_days: int | None = None, forward_days: int | None = None
) -> int:
    """Refresh the snapshot cache for `account` from Google. Returns the number of live events.

    Raises calendar.NotConnectedError (and EncryptionUnavailableError) exactly like a calendar read —
    the caller decides how to explain it. Upserts every event Google returns and deletes any snapshot
    within the window Google no longer returns (an event that was cancelled/deleted upstream).
    """
    settings = get_settings()
    tz = _tz()
    back = settings.calendar_snapshot_back_days if back_days is None else back_days
    forward = settings.calendar_snapshot_forward_days if forward_days is None else forward_days
    window_start, window_end = _window(tz, back, forward)

    events = await calendar.list_events_range(window_start, window_end, account=account)
    now = datetime.now(UTC)
    seen_ids = [e.event_id for e in events if e.event_id]

    async with get_session() as session:
        existing = {
            row.provider_event_id: row
            for row in (
                await session.execute(
                    select(CalendarSnapshot).where(CalendarSnapshot.account == account)
                )
            ).scalars()
        }
        for event in events:
            if not event.event_id:
                continue  # never cache an event without a real provider id
            row = existing.get(event.event_id)
            if row is None:
                session.add(_to_row(account, event, now))
            else:
                _apply(row, event, now)
        # Prune anything inside the refreshed window that Google no longer returns.
        await session.execute(
            delete(CalendarSnapshot).where(
                CalendarSnapshot.account == account,
                CalendarSnapshot.start >= window_start,
                CalendarSnapshot.start < window_end,
                CalendarSnapshot.provider_event_id.not_in(seen_ids) if seen_ids else True,
            )
        )
        await session.commit()

    log.info("calendar_snapshot_rebuilt", account=account, count=len(seen_ids))
    return len(seen_ids)


def _to_row(account: str, event: calendar.CalendarEvent, now: datetime) -> CalendarSnapshot:
    return CalendarSnapshot(
        account=account,
        provider_event_id=event.event_id,
        recurring_event_id=event.recurring_event_id or None,
        title=event.summary,
        attendees=list(event.attendees),
        description=event.description,
        location=event.location,
        start=event.start,
        end=event.end,
        status="confirmed",
        all_day=event.all_day,
        synced_at=now,
    )


def _apply(row: CalendarSnapshot, event: calendar.CalendarEvent, now: datetime) -> None:
    row.recurring_event_id = event.recurring_event_id or None
    row.title = event.summary
    row.attendees = list(event.attendees)
    row.description = event.description
    row.location = event.location
    row.start = event.start
    row.end = event.end
    row.all_day = event.all_day
    row.synced_at = now


async def read_range(account: str, start: datetime, end: datetime) -> list[SnapshotEvent]:
    """Cached events overlapping [start, end), start-sorted. Pure read — never calls Google."""
    async with get_session() as session:
        rows = (
            await session.execute(
                select(CalendarSnapshot)
                .where(
                    CalendarSnapshot.account == account,
                    CalendarSnapshot.start < end,
                    CalendarSnapshot.end > start,
                )
                .order_by(CalendarSnapshot.start.asc())
            )
        ).scalars().all()
    return [
        SnapshotEvent(
            title=r.title,
            start=r.start,
            end=r.end,
            all_day=r.all_day,
            location=r.location,
            provider_event_id=r.provider_event_id,
            recurring_event_id=r.recurring_event_id or "",
        )
        for r in rows
    ]
