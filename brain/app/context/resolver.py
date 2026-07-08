"""ContextResolver (Phase 2C) — reason across the sources Jarvis already has.

Given an anchor (a calendar event, "next meeting", a person, or free text) this assembles the
*related* signals from every connected read source: calendar events, Gmail threads, waiting-on
items, captures, and recent conversation snippets. The assembly is **deterministic** (keyword +
address + thread-id matching), so it is fast, free, and unit-testable with mocked sources. Turning
the assembled `EventContext` into natural-language prose is a separate step (app.context.briefing),
which is the only place an LLM is involved.

Read-only: nothing here mutates Calendar, Gmail, or any external system.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.coordination import waiting
from app.db.models import Capture, WaitingItem
from app.db.session import get_session
from app.integrations.google import calendar, gmail
from app.integrations.google.calendar import CalendarEvent
from app.integrations.google.classify import classify
from app.integrations.google.gmail import GmailMessage
from app.telemetry import get_logger

log = get_logger(__name__)

_WORD = re.compile(r"[a-z0-9]{3,}")
# Generic calendar words that make useless search terms — drop them from event keywords.
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "meeting", "call", "sync", "chat", "catch", "up",
        "weekly", "biweekly", "monthly", "daily", "standup", "1on1", "one", "zoom", "google",
        "meet", "invite", "invitation", "appointment", "reminder", "re", "fwd", "about",
    }
)


@dataclass(frozen=True)
class RelatedEmail:
    message: GmailMessage
    reason: str  # why we linked it (e.g. "from attendee priya@…", "subject match: ARISE")


@dataclass
class EventContext:
    """Everything Jarvis knows that bears on one calendar event."""

    event: CalendarEvent
    related_emails: list[RelatedEmail] = field(default_factory=list)
    waiting_items: list[WaitingItem] = field(default_factory=list)
    captures: list[Capture] = field(default_factory=list)
    my_email: str = ""

    @property
    def has_context(self) -> bool:
        return bool(self.related_emails or self.waiting_items or self.captures)


def event_keywords(event: CalendarEvent) -> list[str]:
    """Distinctive lowercase tokens from an event's title (for Gmail subject matching). Pure."""
    tokens = _WORD.findall(event.summary.lower())
    seen: list[str] = []
    for token in tokens:
        if token not in _STOPWORDS and token not in seen:
            seen.append(token)
    return seen


def _dedupe_by_thread(emails: list[RelatedEmail]) -> list[RelatedEmail]:
    """Keep the newest message per thread so a briefing talks about threads, not every reply."""
    best: dict[str, RelatedEmail] = {}
    for item in emails:
        tid = item.message.thread_id or item.message.gmail_id
        current = best.get(tid)
        if current is None or _received(item.message) > _received(current.message):
            best[tid] = item
    return sorted(best.values(), key=lambda r: _received(r.message), reverse=True)


def _received(msg: GmailMessage) -> datetime:
    return msg.received_at or datetime.min.replace(tzinfo=UTC)


async def _search_related_emails(event: CalendarEvent, lookback_days: int) -> list[RelatedEmail]:
    """Find emails related to an event: from/to attendees, or subject/keyword overlap."""
    found: list[RelatedEmail] = []

    # 1) Anyone on the invite — their recent correspondence is the strongest signal.
    for attendee in event.attendees:
        hits = await gmail.search(f"from:{attendee} OR to:{attendee} newer_than:{lookback_days}d")
        for msg in hits:
            found.append(RelatedEmail(message=msg, reason=f"with {attendee}"))

    # 2) Distinctive words from the event title.
    keywords = event_keywords(event)
    if keywords:
        # Quote terms so multi-word titles still match on any single distinctive token.
        query = " OR ".join(f'subject:{kw}' for kw in keywords[:5])
        hits = await gmail.search(f"({query}) newer_than:{lookback_days}d")
        matched = ", ".join(keywords[:3])
        for msg in hits:
            found.append(RelatedEmail(message=msg, reason=f"subject match: {matched}"))

    return _dedupe_by_thread(found)


async def _load_waiting_for_threads(thread_ids: set[str], account: str) -> list[WaitingItem]:
    if not thread_ids:
        return []
    items = await waiting.list_waiting(account=account)
    return [item for item in items if item.thread_id in thread_ids]


async def _load_related_captures(keywords: list[str], limit: int = 3) -> list[Capture]:
    """Captures whose text mentions any event keyword (cheap substring match)."""
    if not keywords:
        return []
    async with get_session() as session:
        rows = (
            await session.execute(select(Capture).order_by(Capture.created_at.desc()).limit(200))
        ).scalars().all()
    out: list[Capture] = []
    for row in rows:
        text = (row.text or "").lower()
        if any(kw in text for kw in keywords):
            out.append(row)
        if len(out) >= limit:
            break
    return out


async def resolve_event_context(
    event: CalendarEvent, account: str = "default"
) -> EventContext:
    """Assemble all related signals for one calendar event. Deterministic; read-only."""
    settings = get_settings()
    my_email = ""
    try:
        my_email = await gmail.get_profile_email(account)
    except gmail.NotConnectedError:
        # Gmail not authorized — still return event-only context (calendar may be connected).
        log.info("context_gmail_unavailable")
        return EventContext(event=event, my_email="")

    related = await _search_related_emails(event, settings.event_email_lookback_days)
    related = related[: settings.context_max_related_emails]

    thread_ids = {r.message.thread_id for r in related if r.message.thread_id}
    waiting_items = await _load_waiting_for_threads(thread_ids, account)
    captures = await _load_related_captures(event_keywords(event))

    return EventContext(
        event=event,
        related_emails=related,
        waiting_items=waiting_items,
        captures=captures,
        my_email=my_email,
    )


async def resolve_next_meeting(account: str = "default") -> EventContext | None:
    """Context for the next upcoming timed meeting, or None if there isn't one."""
    settings = get_settings()
    event = await calendar.next_meeting(account, window_days=settings.upcoming_window_days)
    if event is None:
        return None
    return await resolve_event_context(event, account=account)


def latest_related_message(context: EventContext) -> GmailMessage | None:
    """The single most recent related email across all threads (for a headline in the briefing)."""
    if not context.related_emails:
        return None
    return max(context.related_emails, key=lambda r: _received(r.message)).message


def unanswered_question(context: EventContext) -> RelatedEmail | None:
    """A related inbound email that looks like it still needs the user's reply."""
    for item in context.related_emails:
        cls = classify(item.message, context.my_email)
        if cls.direction == "inbound" and cls.requires_response and item.message.is_unread:
            return item
    return None
