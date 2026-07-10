"""Calendar verification ("is X on my Google Calendar?") — Phase 2D.3, defect R4.

The user asks whether something is really on their calendar; Jarvis must READ the provider and answer
from what's actually there — a truthful yes with the real event, or a truthful no that never invents
one. It also never denies the capability: if the calendar is connected, it checks; if it isn't, it
says so plainly. A missing match is reported as "not found in the window I checked", not as proof the
thing doesn't exist.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.integrations.google import calendar
from app.security.crypto import EncryptionUnavailableError
from app.sources import registry
from app.telemetry import get_logger

log = get_logger(__name__)

_NOT_CONNECTED = (
    "I'm not connected to your Google Calendar yet, so I can't check. Ask me to connect first."
)
_NO_KEY = "I can't read your calendar yet — the encryption key isn't configured on the server."
_ERROR = "Sorry — I couldn't check your calendar just now. Try again in a moment."
_NO_SUBJECT = "What would you like me to check is on your calendar?"

_STRIP_PUNCT = re.compile(r"[^a-z0-9\s]")
_STOPWORDS = frozenset(
    {"the", "a", "an", "my", "our", "of", "for", "to", "on", "in", "at", "and", "with", "event",
     "meeting", "appointment", "class", "lab", "session"}
)


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _normalize(text: str) -> str:
    return " ".join(_STRIP_PUNCT.sub("", text.lower()).split())


def _significant_tokens(subject: str) -> list[str]:
    return [t for t in _normalize(subject).split() if t not in _STOPWORDS]


def matches(subject: str, summary: str) -> bool:
    """True when every significant word of `subject` appears in the event `summary`.

    Deliberately strict-ish: an acronym or full name must be present. Stopwords like "lab"/"meeting"
    are ignored so "ECE ML lab" still matches "ECE Machine Learning Lab" via ECE/ML — but if the
    subject has no significant tokens we fall back to a plain substring test.
    """
    tokens = _significant_tokens(subject)
    summary_norm = _normalize(summary)
    if not tokens:
        return _normalize(subject) in summary_norm
    return all(tok in summary_norm for tok in tokens)


def _fmt_when(event: calendar.CalendarEvent, tz: ZoneInfo) -> str:
    local = event.start.astimezone(tz)
    if event.all_day:
        return local.strftime("%A %b %-d")
    return local.strftime("%A %b %-d at %-I:%M %p").replace(" 0", " ")


async def handle(subject: str | None, account: str = "default") -> str:
    """Answer "is <subject> on my calendar?" truthfully from a provider read. Never raises."""
    if not subject or not subject.strip():
        return _NO_SUBJECT

    report = await registry.calendar_report(account)
    if not report.connected:
        return _NOT_CONNECTED

    settings = get_settings()
    now = datetime.now(UTC)
    start = now - timedelta(days=settings.calendar_action_lookback_days)
    end = now + timedelta(days=settings.calendar_action_lookahead_days)
    try:
        events = await calendar.list_events_range(start, end, account=account)
    except calendar.NotConnectedError:
        return _NOT_CONNECTED
    except EncryptionUnavailableError:
        return _NO_KEY
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("verify_failed", error=str(exc), error_type=type(exc).__name__)
        return _ERROR

    tz = _tz()
    found = [e for e in events if e.event_id and matches(subject, e.summary)]
    window = f"{settings.calendar_action_lookback_days} days back and " \
             f"{settings.calendar_action_lookahead_days} days ahead"
    if not found:
        return (
            f"No — I don't see anything matching “{subject}” on your Google Calendar "
            f"(I checked {window}). I'm not going to guess one exists."
        )
    found.sort(key=lambda e: e.start)
    if len(found) == 1:
        ev = found[0]
        return f"Yes — “{ev.summary}” is on your Google Calendar: {_fmt_when(ev, tz)}."
    lines = [f"Yes — I see {len(found)} matching events on your Google Calendar:"]
    for ev in found[:5]:
        lines.append(f"• {ev.summary} — {_fmt_when(ev, tz)}")
    return "\n".join(lines)
