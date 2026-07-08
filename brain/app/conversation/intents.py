"""Lightweight, deterministic intent detection used before falling back to the LLM.

Phase 2A: "what's my day?" → calendar. Phase 2B: a small family of email intents → Gmail. Kept as
plain string/regex matching (no LLM) so routing is fast, free, reliable, and unit-testable. The user
never needs Gmail-specific commands — natural phrasing maps to the right read function.
"""
import re
from enum import Enum

_STRIP_PUNCT = re.compile(r"[^a-z0-9\s]")

# Apostrophe-free phrases (normalization strips punctuation, so "what's" → "whats").
_SCHEDULE_PHRASES: tuple[str, ...] = (
    "whats my day",
    "what is my day",
    "hows my day",
    "how does my day look",
    "what does my day look like",
    "whats on my calendar",
    "whats on the calendar",
    "whats on my schedule",
    "whats my schedule",
    "my schedule today",
    "todays schedule",
    "schedule for today",
    "what do i have today",
    "what am i doing today",
    "whats on today",
    "whats happening today",
    "whats my agenda",
    "todays agenda",
    "agenda today",
)


def _normalize(text: str) -> str:
    return " ".join(_STRIP_PUNCT.sub("", text.lower()).split())


def is_todays_schedule_query(text: str) -> bool:
    """True when the message is asking about today's calendar/schedule."""
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in _SCHEDULE_PHRASES)


# --- Phase 2B: email intents -------------------------------------------------


class EmailIntent(str, Enum):
    UNREAD = "unread"  # show unread / check email
    IMPORTANT = "important"  # anything important / needs attention
    WAITING = "waiting"  # what am I waiting on
    DID_REPLY = "did_reply"  # did <person> reply (carries a name)
    SUMMARIZE = "summarize"  # summarize today's email


_WAITING_PHRASES = (
    "waiting on", "waiting for", "am i waiting", "what am i waiting", "who owes me",
    "who hasnt replied", "who has not replied", "who havent i heard", "any follow up",
    "any followups", "follow ups", "followups", "need to follow up",
)
_SUMMARIZE_PHRASES = (
    "summarize", "summarise", "summary of my email", "summary of my inbox", "email summary",
    "recap my email", "recap my inbox", "brief me on my email", "rundown of my email",
)
_IMPORTANT_PHRASES = (
    "anything important", "anything urgent", "important email", "important emails",
    "whats important", "what needs my attention", "emails need my attention",
    "need my attention", "needs my attention", "what should i look at", "anything i need to",
    "what emails need", "what needs attention",
)
_UNREAD_PHRASES = (
    "show unread", "unread email", "unread emails", "show me unread", "check my email",
    "check email", "check my inbox", "check inbox", "any new email", "any new emails",
    "new emails", "read my email", "show me my email", "whats in my inbox", "do i have email",
    "any email", "look at my email", "go through my email",
)

_PRONOUNS = frozenset({"i", "you", "we", "they", "it", "me", "us", "anyone", "anybody", "someone"})
_TITLES = frozenset({"mr", "mrs", "ms", "mister", "miss", "dr", "prof", "professor", "sir", "madam"})

_REPLY_VERB = (
    r"(?:reply|replied|respond|responded|get back|got back|gotten back|"
    r"answer|answered|email|emailed|write back|wrote back|written back)"
)
_DID_REPLY_RE = re.compile(rf"\b(?:did|has|have)\s+(.+?)\s+{_REPLY_VERB}\b")
_FROM_REPLY_RE = re.compile(
    r"\b(?:heard back from|hear back from|word from|reply from|response from|"
    r"replied from|update from|anything from|message from)\s+(.+?)"
    r"(?:\s+(?:yet|today|already|lately|recently))?$"
)


def _clean_name(raw: str) -> str | None:
    words = [w for w in raw.split() if w not in _TITLES and w not in _PRONOUNS]
    return " ".join(words) if words else None


def _extract_reply_subject(normalized: str) -> str | None:
    for pattern in (_DID_REPLY_RE, _FROM_REPLY_RE):
        match = pattern.search(normalized)
        if match:
            name = _clean_name(match.group(1).strip())
            if name:
                return name
    return None


def detect_email_intent(text: str) -> tuple[EmailIntent, str | None] | None:
    """Map a message to an email intent (+ optional person name), or None to fall back to the LLM."""
    normalized = _normalize(text)

    name = _extract_reply_subject(normalized)
    if name:
        return (EmailIntent.DID_REPLY, name)
    if any(phrase in normalized for phrase in _WAITING_PHRASES):
        return (EmailIntent.WAITING, None)
    if any(phrase in normalized for phrase in _SUMMARIZE_PHRASES):
        return (EmailIntent.SUMMARIZE, None)
    if any(phrase in normalized for phrase in _IMPORTANT_PHRASES):
        return (EmailIntent.IMPORTANT, None)
    if any(phrase in normalized for phrase in _UNREAD_PHRASES):
        return (EmailIntent.UNREAD, None)
    return None


# --- Phase 2C: unified-intelligence / meeting-prep intents -------------------


class ContextIntent(str, Enum):
    PREP_MEETING = "prep_meeting"  # prep me for my next meeting → full briefing
    MEETING_ABOUT = "meeting_about"  # what is my next meeting about → one-liner
    EVENT_EMAILS = "event_emails"  # what emails relate to my next event → list
    DEADLINES = "deadlines"  # what deadlines are coming up
    NEXT_ACTION = "next_action"  # what should I do next / top priority


_DEADLINE_PHRASES = (
    "deadline", "deadlines", "whats due", "what is due", "due soon", "coming up",
    "whats coming up", "upcoming due", "what do i owe", "time sensitive",
)
_PREP_PHRASES = (
    "prep me", "prepare me", "prep for", "brief me on my", "brief me for", "meeting prep",
    "get me ready for", "ready for my meeting", "ready for my next", "prep my next",
)
_MEETING_ABOUT_PHRASES = (
    "what is my next meeting about", "whats my next meeting about", "what is this meeting about",
    "whats this meeting about", "what is my meeting about", "whats my meeting about",
    "what is the meeting about", "whats the meeting about",
)
_EVENT_EMAIL_PHRASES = (
    "related to my next", "related to my meeting", "related to my event", "about my meeting",
    "emails for my meeting", "related emails for my", "emails relate to my next",
    "emails for my next", "emails about my next", "emails about the meeting",
)
_NEXT_ACTION_PHRASES = (
    "what should i do next", "whats my next action", "what is my next action", "next action",
    "what should i focus on", "top priority", "what matters most", "whats most important right now",
    "what should i work on",
)


def detect_context_intent(text: str) -> ContextIntent | None:
    """Map a message to a cross-source context intent, or None to try other routes/the LLM.

    Order matters: the more specific meeting phrasings are checked before the generic ones so
    "what is my next meeting about" doesn't get swallowed by the prep matcher.
    """
    normalized = _normalize(text)
    if any(phrase in normalized for phrase in _MEETING_ABOUT_PHRASES):
        return ContextIntent.MEETING_ABOUT
    if any(phrase in normalized for phrase in _EVENT_EMAIL_PHRASES):
        return ContextIntent.EVENT_EMAILS
    if any(phrase in normalized for phrase in _PREP_PHRASES):
        return ContextIntent.PREP_MEETING
    if any(phrase in normalized for phrase in _DEADLINE_PHRASES):
        return ContextIntent.DEADLINES
    if any(phrase in normalized for phrase in _NEXT_ACTION_PHRASES):
        return ContextIntent.NEXT_ACTION
    return None
