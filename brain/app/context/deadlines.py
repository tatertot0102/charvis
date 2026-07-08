"""Deadline aggregation (Phase 2C) — pull time-pressure signals from every read source.

Two deterministic sources: (1) upcoming calendar events (a scheduled thing IS a deadline), and
(2) Gmail messages the classifier flagged `is_deadline_related`. Merged, de-duplicated, and sorted
by urgency (soonest first). No LLM, no writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import get_settings
from app.integrations.google import calendar, gmail
from app.integrations.google.calendar import CalendarEvent
from app.integrations.google.classify import classify
from app.integrations.google.gmail import GmailMessage
from app.telemetry import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Deadline:
    source: str  # "calendar" | "email"
    title: str
    when: datetime | None  # timezone-aware; None if an email deadline with no explicit date
    detail: str  # location for events; sender for emails
    urgency: str  # high | normal | low


def _urgency_for(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "normal"
    hours = (when - now).total_seconds() / 3600
    if hours <= 24:
        return "high"
    if hours <= 72:
        return "normal"
    return "low"


def _event_to_deadline(event: CalendarEvent, now: datetime) -> Deadline:
    return Deadline(
        source="calendar",
        title=event.summary,
        when=event.start,
        detail=event.location or "",
        urgency="high" if event.all_day is False and _hours_until(event.start, now) <= 24 else
        _urgency_for(event.start, now),
    )


def _hours_until(when: datetime, now: datetime) -> float:
    return (when - now).total_seconds() / 3600


def _email_to_deadline(msg: GmailMessage) -> Deadline:
    sender = msg.from_name or msg.from_email or "(unknown)"
    return Deadline(
        source="email",
        title=(msg.subject or "(no subject)").strip(),
        when=None,  # deterministic date extraction from body is out of scope; flag it, don't guess
        detail=f"from {sender}",
        urgency="high",  # deadline-flagged mail is surfaced as high so it isn't missed
    )


async def aggregate_deadlines(account: str = "default") -> list[Deadline]:
    """Merge upcoming calendar events + deadline-flagged email into one urgency-sorted list.

    Degrades gracefully: if one source isn't connected, returns what the other provides.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    deadlines: list[Deadline] = []

    try:
        events = await calendar.list_upcoming_events(
            account, window_days=settings.deadline_window_days
        )
        deadlines += [_event_to_deadline(e, now) for e in events if not e.all_day]
    except calendar.NotConnectedError:
        log.info("deadlines_calendar_unavailable")

    try:
        my_email = await gmail.get_profile_email(account)
        # Search deadline-ish mail in the inbox, then confirm with the classifier.
        candidates = await gmail.search(
            f"newer_than:{settings.deadline_window_days}d in:inbox"
        )
        for msg in candidates:
            if classify(msg, my_email).is_deadline_related:
                deadlines.append(_email_to_deadline(msg))
    except gmail.NotConnectedError:
        log.info("deadlines_gmail_unavailable")

    # Soonest-first; email deadlines (no date) sort after dated ones but before far-off events.
    def _sort_key(d: Deadline) -> tuple[int, float]:
        rank = {"high": 0, "normal": 1, "low": 2}[d.urgency]
        when = d.when.timestamp() if d.when else float("inf")
        return (rank, when)

    deadlines.sort(key=_sort_key)
    log.info("deadlines_aggregated", count=len(deadlines))
    return deadlines
