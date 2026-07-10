"""Hardened output validation for the LLM fallback path (Phase 2D.3).

truth_guard (2D.2) blocks two lies: placeholder scaffolding and false calendar-write claims. This
extends the backstop with the 2D.3 failure mode (root-cause R4): the model denying a capability it
actually has ("I can't access your email") while the source registry reports that source connected.
It runs ONLY on the raw-LLM fallback — the one branch where Jarvis produced prose without assembling
a StructuredAnswer — and replaces a false capability-denial with an honest, source-truthful message.
"""
from __future__ import annotations

import re

from app.conversation import truth_guard
from app.sources.registry import GMAIL, SourceReport

# A denial of *capability* — access/read/reach a source — not a report of an empty result. "find" and
# "check" are intentionally excluded so "I couldn't find any events in your email" is never flagged.
_ACCESS_VERB = (
    r"(?:access|read|see|view|reach|connect(?:\s+to)?|get\s+(?:in)?to|log\s+in(?:to)?|open|"
    r"pull\s+up|retrieve)"
)
_CAP_DENIAL_RE = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|(?:'?m|am|are)\s+(?:not\s+able|unable)\s+to)\s+"
    rf"{_ACCESS_VERB}"
    r"|(?:do(?:n'?t| not)\s+have|have\s+no)\s+(?:access|the\s+ability)",
    re.IGNORECASE,
)

_EMAIL_WORDS = ("email", "emails", "inbox", "gmail", "mailbox")
_CALENDAR_WORDS = ("calendar", "schedule", "events", "event")

SAFE_EMAIL_REPLY = (
    "I do have access to your email — let me actually search it. "
    "Tell me what you're looking for (e.g. upcoming events, a person, a subject) and I'll pull it up."
)
SAFE_CALENDAR_REPLY = (
    "I do have access to your calendar — let me actually pull it up rather than guess. "
    "Ask me what's on your day, week, or month and I'll read it from Google."
)


def _mentions(reply_lower: str, words: tuple[str, ...]) -> bool:
    return any(w in reply_lower for w in words)


def falsely_denies(reply: str, reports: dict[str, SourceReport]) -> str | None:
    """Return the source name the reply falsely claims to lack access to, or None.

    "False" means: the reply denies capability for a source the registry reports connected. A denial
    for a genuinely disconnected source is truthful and passes through untouched.
    """
    if not _CAP_DENIAL_RE.search(reply):
        return None
    lowered = reply.lower()
    gmail = reports.get(GMAIL)
    if gmail is not None and gmail.connected and _mentions(lowered, _EMAIL_WORDS):
        return GMAIL
    calendar = reports.get("calendar")
    if calendar is not None and calendar.connected and _mentions(lowered, _CALENDAR_WORDS):
        return "calendar"
    return None


def sanitize_fallback(reply: str, *, reports: dict[str, SourceReport]) -> str:
    """Validate a raw-LLM reply against source truth + truth_guard; return a safe reply if it lies."""
    denied = falsely_denies(reply, reports)
    if denied == GMAIL:
        return SAFE_EMAIL_REPLY
    if denied == "calendar":
        return SAFE_CALENDAR_REPLY
    # Fall through to the 2D.2 backstop (placeholders + false write claims).
    return truth_guard.sanitize(reply)
