"""Conflict detection and free-time lookup (Phase 2D).

Pure helpers (overlap math, gap-finding) sit under thin async wrappers that read the calendar via the
read connector. All read-only — these inform a proposal ("heads up, this overlaps X"); they never
write. Used both to warn on a create/move and to answer "when am I free?".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.integrations.google import calendar


@dataclass(frozen=True)
class FreeSlot:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """True when [a_start, a_end) and [b_start, b_end) intersect."""
    return a_start < b_end and b_start < a_end


def find_conflicts(
    start: datetime, end: datetime, events: list, exclude_event_id: str | None = None
) -> list:
    """Timed events that overlap [start, end], excluding the event being moved. Pure/testable."""
    out = []
    for event in events:
        if getattr(event, "all_day", False):
            continue
        if exclude_event_id and getattr(event, "event_id", "") == exclude_event_id:
            continue
        if _overlaps(start, end, event.start, event.end):
            out.append(event)
    return out


def free_slots(
    events: list, window_start: datetime, window_end: datetime, min_minutes: int
) -> list[FreeSlot]:
    """Gaps of at least `min_minutes` between timed events within [window_start, window_end]. Pure."""
    busy = sorted(
        (
            (e.start, e.end)
            for e in events
            if not getattr(e, "all_day", False) and e.end > window_start and e.start < window_end
        ),
        key=lambda pair: pair[0],
    )
    slots: list[FreeSlot] = []
    cursor = window_start
    for start, end in busy:
        if start > cursor:
            gap = FreeSlot(cursor, min(start, window_end))
            if gap.minutes >= min_minutes:
                slots.append(gap)
        cursor = max(cursor, end)
        if cursor >= window_end:
            break
    if cursor < window_end:
        tail = FreeSlot(cursor, window_end)
        if tail.minutes >= min_minutes:
            slots.append(tail)
    return slots


def _resolve_tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001 — bad TZ config must not break a lookup.
        return ZoneInfo("UTC")


async def conflicts_for(
    start: datetime, end: datetime, exclude_event_id: str | None = None, account: str = "default"
) -> list:
    """Fetch the day around [start, end] and return overlapping events. Read-only."""
    pad = timedelta(hours=1)
    events = await calendar.list_events_range(start - pad, end + pad, account=account)
    return find_conflicts(start, end, events, exclude_event_id=exclude_event_id)


def _workday_bounds(day: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    settings = get_settings()
    day_start = datetime.combine(day.date(), time(settings.workday_start_hour, 0), tzinfo=tz)
    day_end = datetime.combine(day.date(), time(settings.workday_end_hour, 0), tzinfo=tz)
    return day_start, day_end


async def free_time(day_offset: int = 0, account: str = "default") -> list[FreeSlot]:
    """Open slots during the workday `day_offset` days from now. Read-only."""
    tz = _resolve_tz()
    settings = get_settings()
    day = datetime.now(tz) + timedelta(days=max(0, day_offset))
    window_start, window_end = _workday_bounds(day, tz)
    # Don't offer slots in the past on today.
    now = datetime.now(tz)
    if window_start < now < window_end:
        window_start = now
    events = await calendar.list_events_range(window_start, window_end, account=account)
    return free_slots(events, window_start, window_end, settings.free_time_min_slot_minutes)


def now_utc() -> datetime:
    return datetime.now(UTC)
