"""Read-only Google Calendar connector (Phase 2A).

Read side only — there is no create/move/delete here (writes are a Phase 4 concern behind the
autonomy gate). The Google API client is synchronous, so every call is offloaded with
asyncio.to_thread to keep the FastAPI event loop unblocked.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import get_settings
from app.integrations.google import tokens
from app.telemetry import get_logger

log = get_logger(__name__)

MAX_EVENTS = 50
_PRIMARY_CALENDAR = "primary"


class NotConnectedError(RuntimeError):
    """Raised when a calendar read is attempted before Google is connected."""


@dataclass(frozen=True)
class CalendarEvent:
    summary: str
    start: datetime  # timezone-aware
    end: datetime  # timezone-aware
    all_day: bool
    location: str | None


def _resolve_tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001 — bad TZ config should not break a read; fall back to UTC.
        log.warning("calendar_tz_fallback_utc", configured_tz=get_settings().tz)
        return ZoneInfo("UTC")


def _day_bounds(tz: ZoneInfo, now: datetime | None = None) -> tuple[datetime, datetime]:
    """[midnight, next-midnight) in the configured timezone."""
    current = now or datetime.now(tz)
    start = datetime.combine(current.date(), time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _parse_dt(node: dict, tz: ZoneInfo, all_day: bool) -> datetime:
    if all_day:
        # All-day events carry a plain date; anchor it to the local day start.
        return datetime.fromisoformat(node["date"]).replace(tzinfo=tz)
    # Timed events carry an RFC 3339 dateTime with an offset (3.12 fromisoformat handles it).
    return datetime.fromisoformat(node["dateTime"])


def _parse_event(raw: dict, tz: ZoneInfo) -> CalendarEvent:
    start_node = raw.get("start", {})
    end_node = raw.get("end", {})
    all_day = "date" in start_node
    return CalendarEvent(
        summary=raw.get("summary") or "(no title)",
        start=_parse_dt(start_node, tz, all_day),
        end=_parse_dt(end_node, tz, all_day),
        all_day=all_day,
        location=raw.get("location"),
    )


def _fetch_todays_events(creds: Credentials, tz: ZoneInfo) -> list[dict]:
    """Synchronous Google Calendar call — always run via asyncio.to_thread."""
    start, end = _day_bounds(tz)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    response = (
        service.events()
        .list(
            calendarId=_PRIMARY_CALENDAR,
            timeMin=start.astimezone(UTC).isoformat(),
            timeMax=end.astimezone(UTC).isoformat(),
            singleEvents=True,  # expand recurring events into instances
            orderBy="startTime",
            maxResults=MAX_EVENTS,
        )
        .execute()
    )
    return response.get("items", [])


async def list_todays_events(account: str = "default") -> list[CalendarEvent]:
    """Return today's events on the primary calendar. Raises NotConnectedError if unauthed."""
    creds = await tokens.load_credentials(account)
    if creds is None:
        raise NotConnectedError("Google Calendar is not connected.")
    tz = _resolve_tz()
    raw = await asyncio.to_thread(_fetch_todays_events, creds, tz)
    events = [_parse_event(e, tz) for e in raw]
    log.info("calendar_today_fetched", account=account, count=len(events))
    return events


def format_todays_events(events: list[CalendarEvent]) -> str:
    """Human-friendly summary for chat replies (Telegram / on-demand)."""
    if not events:
        return "You have no events on your calendar today. 🎉"
    lines = ["Here's your day:"]
    for event in events:
        if event.all_day:
            lines.append(f"• {event.summary} (all day)")
        else:
            when = event.start.strftime("%-I:%M %p").lstrip("0")
            location = f" @ {event.location}" if event.location else ""
            lines.append(f"• {when} — {event.summary}{location}")
    return "\n".join(lines)
