"""Lightweight, deterministic intent detection used before falling back to the LLM.

Phase 2A: "what's my day?" → calendar. Phase 2B: a small family of email intents → Gmail. Kept as
plain string/regex matching (no LLM) so routing is fast, free, reliable, and unit-testable. The user
never needs Gmail-specific commands — natural phrasing maps to the right read function.
"""
import re
from enum import Enum

from app.query import ranges

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


# A week/range schedule query. Answered deterministically from the snapshot cache (Phase 2D.2) — the
# fix for the "invent a week" bug: these must NEVER fall through to the free-form LLM path.
_WEEK_PHRASES: tuple[str, ...] = (
    "whats my week",
    "what is my week",
    "hows my week",
    "how does my week look",
    "what does my week look like",
    "whats my week look like",
    "my week look",
    "whats on this week",
    "whats on my week",
    "what do i have this week",
    "what i have this week",
    "have this week",
    "what am i doing this week",
    "doing this week",
    "my schedule this week",
    "schedule this week",
    "schedule for this week",
    "schedule for the week",
    "whats my schedule this week",
    "my agenda this week",
    "agenda this week",
    "rest of my week",
    "rest of the week",
    "week ahead",
    "the week ahead",
    "whats happening this week",
    "whats going on this week",
    "plans this week",
    "whats coming up this week",
)


def is_week_schedule_query(text: str) -> bool:
    """True when the message asks about the week / a multi-day range (not just today)."""
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in _WEEK_PHRASES)


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


# --- Phase 2C.5: memory-introspection intents --------------------------------


class MemoryIntent(str, Enum):
    KNOW_ABOUT_ME = "know_about_me"  # what do you know about me
    PATTERNS = "patterns"  # what patterns have you noticed
    PROJECTS = "projects"  # what projects do you think I'm working on
    WHY = "why"  # why do you think X is important (carries a subject)
    LOW_CONFIDENCE = "low_confidence"  # show low-confidence conclusions


_LOW_CONFIDENCE_PHRASES = (
    "low confidence", "low confidence conclusions", "least confident", "not sure about",
    "what are you unsure", "what are you least sure", "uncertain conclusions", "shaky conclusions",
    "what are you unsure about", "least sure",
)
_PATTERN_PHRASES = (
    "what patterns", "patterns have you noticed", "noticed any patterns", "any patterns",
    "what have you noticed", "what patterns have you", "notice any patterns", "behavior patterns",
)
_PROJECT_PHRASES = (
    "what projects", "what projects am i working", "what projects do you think", "my projects",
    "what am i working on", "which projects", "projects am i working on", "projects do you think",
)
_KNOW_PHRASES = (
    "what do you know about me", "what do you know", "what have you learned about me",
    "what do you remember about me", "tell me what you know", "what have you figured out",
    "what do you understand about me", "what do you know about my life", "what have you learned",
)

# "why do you think ARISE is important" / "why does Dana matter" → capture the subject.
_WHY_THINK_RE = re.compile(
    r"why (?:do|does) (?:you|i) (?:think|believe|feel|say) (?:that )?(.+?)"
    r"(?:\s+(?:is|are|really|so|matters?))?\s+(?:important|matters?|a priority|relevant)"
)
_WHY_IS_RE = re.compile(r"why (?:is|are|does|do) (.+?) (?:important|matters?|a priority|relevant)")
_WHY_MATTER_RE = re.compile(r"why (?:do|does) (.+?) matter")
_WHY_FALLBACK_RE = re.compile(r"why (?:do|does) (?:you|i) (?:think|believe|say) (?:that )?(.+)")

_FILLER = frozenset({"so", "really", "very", "the", "a", "an", "to", "me", "is", "are", "that"})


def _clean_subject(raw: str) -> str | None:
    words = [w for w in raw.split() if w not in _FILLER and w not in _PRONOUNS]
    return " ".join(words) if words else None


def _extract_why_subject(normalized: str) -> str | None:
    for pattern in (_WHY_THINK_RE, _WHY_IS_RE, _WHY_MATTER_RE, _WHY_FALLBACK_RE):
        match = pattern.search(normalized)
        if match:
            subject = _clean_subject(match.group(1).strip())
            if subject:
                return subject
    return None


# --- Phase 2D: calendar-action confirmation + free-time -----------------------

# Exact whole-message confirm/cancel. Deliberately strict: "yes", "confirm please", "ok do it" must
# NOT confirm a calendar write. The user must reply exactly "CONFIRM" (case-insensitive).
_CONFIRM_WORDS = frozenset({"confirm", "confirmed"})
_CANCEL_WORDS = frozenset({"cancel", "nvm", "nevermind", "never mind", "abort", "stop"})

_FREE_TIME_PHRASES = (
    "when am i free", "when am i available", "whats my free time", "free time",
    "am i free", "do i have time", "find me time", "when do i have time", "any free time",
    "open slots", "free slots", "gaps in my", "wheres my free",
)


# Bulk/destructive actions require a stronger, explicit phrase so a plain "confirm" can't fire them.
_BULK_CONFIRM_PHRASES = {
    "confirm delete": "CONFIRM DELETE",
    "confirm move": "CONFIRM MOVE",
}


def is_confirm(text: str) -> bool:
    """True only when the whole message is exactly a confirmation word (the single-action gate)."""
    return _normalize(text) in _CONFIRM_WORDS


def bulk_confirm_phrase(text: str) -> str | None:
    """Canonical bulk-confirm phrase if the whole message is exactly one (e.g. 'CONFIRM DELETE')."""
    return _BULK_CONFIRM_PHRASES.get(_normalize(text))


def is_cancel(text: str) -> bool:
    """True only when the whole message is exactly a cancel word (drops a pending proposal)."""
    return _normalize(text) in _CANCEL_WORDS


def is_free_time_query(text: str) -> bool:
    """True when the message asks about free/open time (a read, not a write)."""
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in _FREE_TIME_PHRASES)


def detect_memory_intent(text: str) -> tuple[MemoryIntent, str | None] | None:
    """Map a message to a memory-introspection intent (+ optional subject), or None to fall back.

    'Why …' is checked first since it is the most specific; the generic 'what do you know' is last.
    """
    normalized = _normalize(text)
    if normalized.startswith("why"):
        subject = _extract_why_subject(normalized)
        if subject:
            return (MemoryIntent.WHY, subject)
    if any(phrase in normalized for phrase in _LOW_CONFIDENCE_PHRASES):
        return (MemoryIntent.LOW_CONFIDENCE, None)
    if any(phrase in normalized for phrase in _PATTERN_PHRASES):
        return (MemoryIntent.PATTERNS, None)
    if any(phrase in normalized for phrase in _PROJECT_PHRASES):
        return (MemoryIntent.PROJECTS, None)
    if any(phrase in normalized for phrase in _KNOW_PHRASES):
        return (MemoryIntent.KNOW_ABOUT_ME, None)
    return None


# --- Phase 2D.3: schedule-range, calendar-verification, email-event-search ----
#
# These fix three of the routing defects that funnelled real questions into the raw LLM:
#   R1  "what does my month look like"        → a ranged schedule read (not the LLM)
#   R4  "is this in my Google Calendar?"      → a provider verification (not a guess)
#   R3  "check my email for upcoming events"  → a Gmail event search (not list_unread)

# Generic "asking about my schedule/agenda" phrasing, range-agnostic. Paired with a parsed range so a
# fresh "what do I have next week" routes deterministically. Today/this-week keep their own matchers.
_SCHEDULE_INTENT_PHRASES = (
    "schedule", "agenda", "on my calendar", "on the calendar", "my calendar",
    "what do i have", "what have i got", "what am i doing", "what i have", "whats on",
    "whats happening", "whats going on", "coming up", "look like", "any events", "any plans",
    "anything on", "anything going on", "anything happening", "what are my plans", "my plans",
    "do i have anything", "have anything", "what does my",
)


def _has_schedule_intent(normalized: str) -> bool:
    return any(phrase in normalized for phrase in _SCHEDULE_INTENT_PHRASES)


def detect_schedule_range(text: str) -> ranges.TimeRange | None:
    """A ranged schedule query ("what do I have next week/this month/tomorrow"), else None.

    Requires BOTH a schedule-intent phrase and a parseable range so plain statements that merely
    mention a month ("remind me next month") don't get treated as schedule reads. Today/this-week are
    left to their dedicated matchers; only other ranges are returned here.
    """
    normalized = _normalize(text)
    if not _has_schedule_intent(normalized):
        return None
    time_range = ranges.parse_range(text)
    if time_range is None or time_range.key in ("today", "this_week"):
        return None
    return time_range


# A read-only verification question about the calendar ("is X on my calendar?"). Distinct from a
# calendar ACTION (add/move/delete) — those carry an action verb and route to the action handler.
_VERIFY_SUBJECT_RES = (
    re.compile(r"\b(?:is|are|was|were)\s+(.+?)\s+(?:on|in|already on|actually on)\s+my\s+"
               r"(?:google\s+)?calendar\b"),
    re.compile(r"\bdo(?:es)?\s+(?:i|my calendar)\s+have\s+(.+?)\s+(?:on|in|scheduled)\b"),
    re.compile(r"\b(?:did|have)\s+you\s+(?:actually\s+)?(?:add|schedule|create|put)\s+(.+?)\s+"
               r"(?:on|to|in)\s+my\s+(?:google\s+)?calendar\b"),
    re.compile(r"\bis\s+(.+?)\s+(?:actually\s+)?scheduled\b"),
)
# Bare "is this/that/it on my calendar?" — the subject comes from conversation context, not the text.
_VERIFY_BARE_RE = re.compile(
    r"\b(?:is|are)\s+(?:this|that|it)\s+(?:actually\s+)?(?:on|in)\s+my\s+(?:google\s+)?calendar\b"
)
_VERIFY_MARKERS = ("on my calendar", "in my calendar", "on my google calendar", "in my google calendar")
# A verification is a yes/no QUESTION — it must open with one of these. Guards against declarative
# statements ("my lab is on my calendar every weekday") being misread as a check.
_VERIFY_LEAD_WORDS = frozenset(
    {"is", "are", "was", "were", "do", "does", "did", "have", "has", "can", "could", "should"}
)


def detect_calendar_verification(text: str) -> tuple[bool, str | None] | None:
    """Detect "is X on my calendar?" → (True, subject|None); None if it isn't a verification question."""
    normalized = _normalize(text)
    if not any(marker in normalized for marker in _VERIFY_MARKERS) and "scheduled" not in normalized:
        return None
    tokens = normalized.split()
    if not tokens or tokens[0] not in _VERIFY_LEAD_WORDS:
        return None  # not phrased as a question — leave it to statement handlers / the LLM
    if _VERIFY_BARE_RE.search(normalized):
        return (True, None)
    for pattern in _VERIFY_SUBJECT_RES:
        match = pattern.search(normalized)
        if match:
            subject = _clean_subject(match.group(1).strip())
            return (True, subject)
    # A question with a marker but no clean subject → verify, resolving the subject from context.
    if any(marker in normalized for marker in _VERIFY_MARKERS):
        return (True, None)
    return None


# Searching EMAIL specifically for events/invitations — must beat the generic "check my email"→unread.
_EVENT_TOKENS = (
    "event", "events", "invite", "invites", "invitation", "invitations", "rsvp",
)
_EMAIL_TOKENS = ("email", "emails", "inbox", "gmail", "mailbox")
_EMAIL_SEARCH_MARKERS = (
    "check", "search", "look", "scan", "find", "go through", "any", "for", "upcoming", "in my",
    "through my",
)
_PERSON_SCOPE_RE = re.compile(r"\bfrom\s+(.+?)(?:\s+(?:in|about|regarding|for|on)\b|$)")


def _extract_person_scope(normalized: str) -> str | None:
    match = _PERSON_SCOPE_RE.search(normalized)
    if not match:
        return None
    return _clean_name(match.group(1).strip())


def detect_email_event_search(text: str) -> tuple[bool, str | None] | None:
    """Detect "check my email for events/invitations" → (True, person|None); None otherwise.

    Requires an email token AND an event/invite token AND a search cue, so plain "check my email"
    still routes to unread and only an explicit event hunt lands here (root-cause R3).
    """
    normalized = _normalize(text)
    has_email = any(t in normalized for t in _EMAIL_TOKENS)
    has_event = any(t in normalized for t in _EVENT_TOKENS)
    searchy = any(m in normalized for m in _EMAIL_SEARCH_MARKERS)
    if has_email and has_event and searchy:
        return (True, _extract_person_scope(normalized))
    return None
