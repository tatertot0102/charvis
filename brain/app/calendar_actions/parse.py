"""Deterministic natural-language parsing for calendar-action requests (Phase 2D).

Plain regex/keyword matching — no LLM — so routing is fast, free, and unit-testable. The goal is not
to parse everything; it is to reliably recognise the common cases ("move my 3pm to 4", "cancel
standup", "schedule Dentist tomorrow at 2") and to return None (→ the caller asks a clarifying
question) whenever the request is ambiguous or unparseable. Better to ask than to guess a write.
"""
from __future__ import annotations

import re
from datetime import time

from app.calendar_actions.schema import ActionType, ParsedRequest

_STRIP = re.compile(r"[^a-z0-9:\s]")

# Verb families → action type. detect() checks delete/update before create so "cancel my meeting"
# isn't read as "create".
_DELETE_VERBS = ("cancel", "delete", "remove", "clear", "drop", "call off", "get rid of")
_UPDATE_VERBS = ("move", "reschedule", "shift", "push", "change", "bump", "make it")
_CREATE_VERBS = (
    "schedule", "create", "add", "book", "set up", "put", "new event", "block off", "block out",
    "plan", "arrange",
)

_TOMORROW = ("tomorrow", "tmrw", "tmr")
_TODAY = ("today", "this afternoon", "this morning", "tonight", "this evening")

# Bulk quantifiers → operate on the whole matched set ("delete all future DSI events",
# "cancel upcoming ARISE meetings"). Plurals alone don't trigger bulk — the marker must be explicit.
_BULK_MARKERS = ("all", "every", "each", "upcoming", "future")
# "… with Dana" → match by attendee rather than title. Capture the name up to a time/day/stopword.
_ATTENDEE_RE = re.compile(
    r"\bwith\s+([a-z0-9.@]+(?:\s+[a-z0-9.@]+)?)"
    r"(?=\s+(?:on|at|about|tomorrow|today|tonight|this|next|to|for|by)\b|$)"
)

# One left-to-right, non-overlapping scanner so times are captured *in order* — the first time in a
# move is the target ("my 3pm"), the last is the destination ("to 4").
_TIME_SCANNER = re.compile(
    r"(?P<hm>\b\d{1,2}:\d{2}\s*(?:am|pm)?\b)"
    r"|(?P<hmer>\b\d{1,2}\s*(?:am|pm)\b)"
    r"|(?P<word>\bnoon\b|\bmidnight\b)"
    r"|(?P<bare>\b(?:to|at|for|by)\s+\d{1,2}\b)"
)
_DIGITS = re.compile(r"\d{1,2}")

_DURATION = re.compile(r"\b(?:for\s+)?(\d{1,3})\s*(min|mins|minute|minutes|hour|hours|hr|hrs|h)\b")


def _normalize(text: str) -> str:
    return " ".join(_STRIP.sub(" ", text.lower()).split())


def _meridiem_hour(hour: int, meridiem: str | None) -> int | None:
    if hour > 23:
        return None
    if meridiem == "pm":
        return hour if hour == 12 else hour + 12
    if meridiem == "am":
        return 0 if hour == 12 else hour
    # Bare hour: assume business-day sensible. 1–7 → afternoon (PM); 8–11 → morning; 12 → noon.
    if hour == 12:
        return 12
    if 1 <= hour <= 7:
        return hour + 12
    return hour


def _match_to_time(match: re.Match) -> time | None:
    kind = match.lastgroup
    token = match.group()
    if kind == "word":
        return time(0, 0) if "midnight" in token else time(12, 0)
    meridiem = "pm" if "pm" in token else "am" if "am" in token else None
    if kind == "hm":
        hh, mm = token.split(":")
        hour = _meridiem_hour(int(hh.strip()), meridiem)
        minute = int(_DIGITS.search(mm).group())
        return time(hour, minute) if hour is not None and 0 <= minute <= 59 else None
    # hmer or bare — a single hour number (bare uses business-hour heuristic).
    hour = _meridiem_hour(int(_DIGITS.search(token).group()), meridiem)
    return time(hour, 0) if hour is not None else None


def _all_times(normalized: str) -> list[time]:
    """Clock times in order of appearance (duplicates preserved)."""
    out: list[time] = []
    for match in _TIME_SCANNER.finditer(normalized):
        parsed = _match_to_time(match)
        if parsed is not None:
            out.append(parsed)
    return out


def parse_time(text: str) -> time | None:
    """First clock time in a phrase, or None. Kept for simple callers/tests."""
    times = _all_times(_normalize(text))
    return times[0] if times else None


def _day_offset(normalized: str) -> int | None:
    if any(w in normalized for w in _TOMORROW):
        return 1
    if any(w in normalized for w in _TODAY):
        return 0
    return None


def _duration_minutes(normalized: str) -> int | None:
    m = _DURATION.search(normalized)
    if not m:
        return None
    value = int(m.group(1))
    return value * 60 if m.group(2).startswith(("hour", "hr", "h")) else value


def _first_verb(normalized: str, verbs: tuple[str, ...]) -> str | None:
    for verb in verbs:
        if re.search(rf"\b{re.escape(verb)}\b", normalized):
            return verb
    return None


# Words that never belong in an event's name/target hint.
_NOISE = frozenset(
    {
        "my", "the", "a", "an", "to", "at", "for", "by", "on", "meeting", "meetings", "event",
        "events", "appointment", "appointments", "session", "sessions", "class", "classes",
        "please", "can", "you", "me", "i", "with", "and", "from", "of", "it", "that", "this",
        "am", "pm", "oclock", "call", "calls", "tomorrow", "today", "tonight", "morning",
        "afternoon", "evening", "next", "up", "off", "out", "new", "noon", "midnight",
        "min", "mins", "minute", "minutes", "hour", "hours", "hr", "hrs",
        # Bulk quantifiers / scope words — not part of an event name.
        "all", "every", "each", "future", "upcoming", "remaining", "any",
    }
)


def _is_bulk(normalized: str) -> bool:
    return any(re.search(rf"\b{re.escape(m)}\b", normalized) for m in _BULK_MARKERS)


def _attendee_hint(normalized: str) -> str | None:
    match = _ATTENDEE_RE.search(normalized)
    if not match:
        return None
    name = " ".join(w for w in match.group(1).split() if w not in _NOISE)
    return name or None


def _strip_verbs_and_times(normalized: str) -> str:
    cleaned = normalized
    for verb in (*_DELETE_VERBS, *_UPDATE_VERBS, *_CREATE_VERBS):
        cleaned = re.sub(rf"\b{re.escape(verb)}\b", " ", cleaned)
    cleaned = _TIME_SCANNER.sub(" ", cleaned)
    return " ".join(cleaned.split())


def _hint(normalized: str, drop: set[str] = frozenset()) -> str | None:
    """Distinctive words that name the target event / new event, noise (and `drop`) removed."""
    cleaned = _strip_verbs_and_times(normalized)
    words = [
        w for w in cleaned.split() if w not in _NOISE and w not in drop and not w.isdigit()
    ]
    return " ".join(words) if words else None


def detect(text: str) -> ParsedRequest | None:
    """Parse a message into a calendar-action request, or None if it isn't one."""
    normalized = _normalize(text)
    if not normalized:
        return None

    delete_verb = _first_verb(normalized, _DELETE_VERBS)
    update_verb = _first_verb(normalized, _UPDATE_VERBS)
    create_verb = _first_verb(normalized, _CREATE_VERBS)

    times = _all_times(normalized)
    day_offset = _day_offset(normalized)
    bulk = _is_bulk(normalized)
    attendee_hint = _attendee_hint(normalized)
    # Keep attendee tokens out of the title hint so "meetings with Dana" matches by attendee only.
    drop = set(attendee_hint.split()) if attendee_hint else set()
    hint = _hint(normalized, drop=drop)

    if delete_verb:
        # Any time in a delete names the target ("cancel my 3pm").
        return ParsedRequest(
            action_type=ActionType.DELETE,
            target_hint=hint,
            target_time=times[0] if times else None,
            bulk=bulk,
            attendee_hint=attendee_hint,
        )
    if update_verb:
        # Two times → first identifies the target, last is the destination. One time → destination.
        target_time = times[0] if len(times) >= 2 else None
        new_time = times[-1] if times else None
        return ParsedRequest(
            action_type=ActionType.UPDATE,
            target_hint=hint,
            target_time=target_time,
            new_time=new_time,
            day_offset=day_offset,
            bulk=bulk,
            attendee_hint=attendee_hint,
        )
    if create_verb:
        return ParsedRequest(
            action_type=ActionType.CREATE,
            title=hint,
            new_time=times[0] if times else None,
            day_offset=day_offset,
            duration_minutes=_duration_minutes(normalized),
        )
    return None
