"""Deterministic week/schedule answers from the snapshot cache (Phase 2D.2).

The whole point: a "what's my week?" reply is BUILT from provider-backed snapshots, never generated
by the LLM. rebuild-then-read guarantees freshness — if an event was deleted upstream, it's gone from
the snapshot and therefore gone from the answer. No placeholder, no invention, ever.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.calendar_state import snapshots
from app.config import get_settings


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _fmt_time(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%-I:%M %p").lstrip("0")


def format_week(events: list[snapshots.SnapshotEvent], start: datetime, span_days: int) -> str:
    """Group cached events by day across [start, start+span_days). Pure/testable."""
    tz = start.tzinfo
    if not events:
        return "Your calendar is clear for the next 7 days. 🎉"

    by_day: dict[int, list[snapshots.SnapshotEvent]] = {}
    for event in events:
        offset = (event.start.astimezone(tz).date() - start.date()).days
        if 0 <= offset < span_days:
            by_day.setdefault(offset, []).append(event)

    lines = ["Here's your week:"]
    for offset in range(span_days):
        day_events = by_day.get(offset)
        if not day_events:
            continue
        day = start + timedelta(days=offset)
        lines.append(f"\n{day.strftime('%A %b %-d')}:")
        for event in sorted(day_events, key=lambda e: e.start):
            if event.all_day:
                lines.append(f"  • {event.title} (all day)")
            else:
                where = f" @ {event.location}" if event.location else ""
                lines.append(f"  • {_fmt_time(event.start, tz)} — {event.title}{where}")
    if len(lines) == 1:
        return "Your calendar is clear for the next 7 days. 🎉"
    return "\n".join(lines)


async def week_summary(account: str = "default") -> str:
    """Refresh the snapshot cache, then answer the week from it (never from the model)."""
    await snapshots.rebuild(account)
    tz = _tz()
    span = get_settings().week_span_days
    start = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
    end = start + timedelta(days=span)
    events = await snapshots.read_range(account, start, end)
    return format_week(events, start, span)
