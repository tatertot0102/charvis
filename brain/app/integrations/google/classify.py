"""Deterministic email classification (Phase 2B).

No LLM: classification is derived from Gmail's own labels plus cheap keyword/structure heuristics.
This keeps it reliable, fast, free, and unit-testable with fixtures — the local model is reserved
for open-ended conversation, not per-message tagging whose output we'd have to trust blindly.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.integrations.google.gmail import GmailMessage

_PROMO_LABELS = frozenset(
    {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS", "CATEGORY_UPDATES", "SPAM"}
)
_IMPORTANT_LABEL = "IMPORTANT"

_CALENDAR_KEYWORDS = (
    "meeting", "invite", "invitation", "calendar", "appointment", "rsvp", "are you free",
    "reschedule", "zoom", "google meet", "webinar", "let's meet", "schedule a", "book a time",
)
_DEADLINE_KEYWORDS = (
    "deadline", "due ", "due date", "by end of", "by eod", " eod", "asap", "overdue", "reminder",
    "expires", "expiration", "last chance", "final notice", "submit by", "respond by", "due by",
)
_NO_REPLY_HINTS = (
    "no-reply", "noreply", "no_reply", "donotreply", "do-not-reply", "mailer-daemon",
    "notifications@", "notification@", "updates@", "newsletter@",
)
_REQUEST_HINTS = (
    "?", "please", "could you", "can you", "would you", "let me know", "any update", "follow up",
    "following up", "waiting on", "need your", "need you", "confirm", "review", "sign", "approve",
)


@dataclass(frozen=True)
class Classification:
    direction: str  # inbound | outbound
    importance: str  # high | normal | low
    urgency: str  # high | normal | low
    requires_response: bool
    is_promotional: bool
    is_calendar_related: bool
    is_deadline_related: bool
    is_fyi: bool


def is_noreply(sender: str) -> bool:
    lowered = sender.lower()
    return any(hint in lowered for hint in _NO_REPLY_HINTS)


def _searchable_text(msg: GmailMessage) -> str:
    return f"{msg.subject}\n{msg.snippet}".lower()


def classify(msg: GmailMessage, my_email: str) -> Classification:
    my = (my_email or "").lower()
    direction = "outbound" if my and msg.from_email == my else "inbound"
    text = _searchable_text(msg)

    is_promotional = any(label in _PROMO_LABELS for label in msg.labels)
    is_calendar_related = any(kw in text for kw in _CALENDAR_KEYWORDS)
    is_deadline_related = any(kw in text for kw in _DEADLINE_KEYWORDS)

    addressed_to_me = (my in msg.to_emails) if my else True
    from_person = not is_noreply(msg.from_email)
    requires_response = (
        direction == "inbound"
        and not is_promotional
        and from_person
        and addressed_to_me
        and any(hint in text for hint in _REQUEST_HINTS)
    )

    if is_promotional:
        importance = "low"
    elif _IMPORTANT_LABEL in msg.labels or requires_response or is_deadline_related:
        importance = "high"
    else:
        importance = "normal"

    if not is_promotional and (is_deadline_related or "asap" in text or "urgent" in text):
        urgency = "high"
    elif is_promotional:
        urgency = "low"
    else:
        urgency = "normal"

    is_fyi = direction == "inbound" and not is_promotional and not requires_response

    return Classification(
        direction=direction,
        importance=importance,
        urgency=urgency,
        requires_response=requires_response,
        is_promotional=is_promotional,
        is_calendar_related=is_calendar_related,
        is_deadline_related=is_deadline_related,
        is_fyi=is_fyi,
    )
